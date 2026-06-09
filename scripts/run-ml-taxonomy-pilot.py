"""Run a reproducible pilot benchmark for policy notice taxonomy discovery.

This is deliberately a pilot, not a final taxonomy estimator. Existing
administrative category labels are excluded from clustering inputs and used
only as external reference variables after fitting.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_samples,
    silhouette_score,
    v_measure_score,
)
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import Normalizer, OneHotEncoder, StandardScaler


SEED = 20260602
PURPOSES = [
    "운전자금",
    "시설개보수",
    "인건비",
    "재료비",
    "마케팅비",
    "사업화",
    "교육훈련",
    "컨설팅",
    "디자인·브랜딩",
    "인증취득",
    "수출",
    "온라인판로",
    "이자보전",
    "보증지원",
]
WEIGHT_SCHEMES = {
    "unweighted": 0.0,
    "inverse_sqrt_family": 0.5,
    "inverse_family": 1.0,
}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_amount(value: object) -> float:
    if isinstance(value, dict):
        value = value.get("max")
    text = compact(value).replace("\n", " ")
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(억원|천만원|백만원|만원)", text)
    if not match:
        return math.nan
    number = float(match.group(1).replace(",", ""))
    multiplier = {
        "억원": 100_000_000,
        "천만원": 10_000_000,
        "백만원": 1_000_000,
        "만원": 10_000,
    }[match.group(2)]
    return number * multiplier


def parse_rate(value: object) -> float:
    match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", compact(value))
    return float(match.group(1)) if match else math.nan


def label_encode(values: list[str]) -> tuple[np.ndarray, list[str]]:
    labels = sorted(set(values))
    mapping = {value: idx for idx, value in enumerate(labels)}
    return np.array([mapping[value] for value in values], dtype=int), labels


@dataclass
class Dataset:
    records: list[dict]
    allocation: list[dict]
    ids: list[str]
    titles: list[str]
    families: np.ndarray
    family_sizes: np.ndarray
    categories: np.ndarray
    subcategories: np.ndarray
    categorical: np.ndarray
    categorical_names: list[str]
    numeric: np.ndarray
    numeric_names: list[str]
    binary: np.ndarray
    binary_names: list[str]
    structured_matrix: np.ndarray
    text_matrix: np.ndarray
    text_corpus: list[str]
    gower_distance: np.ndarray
    gower_coordinates: np.ndarray


def build_dataset(records: list[dict], allocation: list[dict], seed: int) -> Dataset:
    by_id = {row["id"]: row for row in records}
    selected = [row for row in allocation if str(row["analysis_include"]).lower() == "true"]
    selected_records = [by_id[row["record_id"]] for row in selected]

    ids = [row["id"] for row in selected_records]
    titles = [row["title"] for row in selected_records]
    families = np.array([row["program_family_id"] for row in selected])
    family_sizes = np.array([int(row["program_family_size"]) for row in selected], dtype=float)
    categories = np.array([compact(row.get("category")) or "(missing)" for row in selected_records])
    subcategories = np.array([compact(row.get("subcategory")) or "(missing)" for row in selected_records])

    categorical_names = ["target", "period_type"]
    categorical_values = []
    numeric_names = [
        "log_amount",
        "rate",
        "log_exclusions",
        "log_documents",
        "log_steps",
    ]
    numeric_values = []
    binary_names = PURPOSES + ["online", "has_amount", "has_rate"]
    binary_values = []
    text_corpus = []

    for row in selected_records:
        support = row.get("support", {})
        eligibility = row.get("eligibility", {})
        application = row.get("application", {})
        amount = parse_amount(support.get("amount"))
        rate = parse_rate(support.get("rate"))
        purposes = set(support.get("purposes", []))
        categorical_values.append(
            [
                compact(eligibility.get("target")) or "(missing)",
                compact(application.get("periodType")) or "(missing)",
            ]
        )
        numeric_values.append(
            [
                math.log1p(amount) if not math.isnan(amount) else math.nan,
                rate,
                math.log1p(len(eligibility.get("exclusions", []))),
                math.log1p(len(application.get("documents", []))),
                math.log1p(len(application.get("steps", []))),
            ]
        )
        binary_values.append(
            [int(name in purposes) for name in PURPOSES]
            + [
                int(bool(application.get("onlineAvailable"))),
                int(not math.isnan(amount)),
                int(not math.isnan(rate)),
            ]
        )
        text_corpus.append(
            " ".join(
                [
                    compact(row.get("title")),
                    compact(support.get("summary")),
                    " ".join(sorted(purposes)),
                ]
            )
        )

    categorical = np.array(categorical_values, dtype=object)
    numeric = np.array(numeric_values, dtype=float)
    binary = np.array(binary_values, dtype=float)

    filled_numeric = numeric.copy()
    for col in range(filled_numeric.shape[1]):
        valid = ~np.isnan(filled_numeric[:, col])
        median = float(np.median(filled_numeric[valid, col])) if valid.any() else 0.0
        filled_numeric[~valid, col] = median
    scaled_numeric = StandardScaler().fit_transform(filled_numeric)
    onehot = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit_transform(categorical)
    structured_matrix = np.hstack([scaled_numeric, binary, onehot])

    vectorizer = TfidfVectorizer(
        min_df=2,
        max_df=0.98,
        ngram_range=(1, 2),
        max_features=3000,
        sublinear_tf=True,
    )
    text_tfidf = vectorizer.fit_transform(text_corpus)
    components = min(60, text_tfidf.shape[0] - 1, text_tfidf.shape[1] - 1)
    text_matrix = TruncatedSVD(n_components=max(2, components), random_state=seed).fit_transform(text_tfidf)
    text_matrix = Normalizer(copy=False).fit_transform(text_matrix)

    gower_distance = build_gower_distance(categorical, numeric, binary)
    gower_coordinates = classical_mds(gower_distance, components=20)
    return Dataset(
        records=selected_records,
        allocation=selected,
        ids=ids,
        titles=titles,
        families=families,
        family_sizes=family_sizes,
        categories=categories,
        subcategories=subcategories,
        categorical=categorical,
        categorical_names=categorical_names,
        numeric=numeric,
        numeric_names=numeric_names,
        binary=binary,
        binary_names=binary_names,
        structured_matrix=structured_matrix,
        text_matrix=text_matrix,
        text_corpus=text_corpus,
        gower_distance=gower_distance,
        gower_coordinates=gower_coordinates,
    )


def build_gower_distance(categorical: np.ndarray, numeric: np.ndarray, binary: np.ndarray) -> np.ndarray:
    size = len(categorical)
    total = np.zeros((size, size), dtype=float)
    denominator = np.zeros((size, size), dtype=float)

    for col in range(categorical.shape[1]):
        values = categorical[:, col]
        total += (values[:, None] != values[None, :]).astype(float)
        denominator += 1

    for col in range(numeric.shape[1]):
        values = numeric[:, col]
        valid = ~np.isnan(values)
        valid_pairs = valid[:, None] & valid[None, :]
        if valid.any():
            width = float(np.nanmax(values) - np.nanmin(values))
            width = width if width > 0 else 1.0
            distance = np.abs(values[:, None] - values[None, :]) / width
            total += np.where(valid_pairs, distance, 0.0)
            denominator += valid_pairs.astype(float)

    for col in range(binary.shape[1]):
        values = binary[:, col]
        total += np.abs(values[:, None] - values[None, :])
        denominator += 1

    result = np.divide(total, denominator, out=np.zeros_like(total), where=denominator > 0)
    np.fill_diagonal(result, 0.0)
    return result


def classical_mds(distance: np.ndarray, components: int) -> np.ndarray:
    size = len(distance)
    centering = np.eye(size) - np.ones((size, size)) / size
    gram = -0.5 * centering @ (distance**2) @ centering
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    order = np.argsort(eigenvalues)[::-1]
    positive = [idx for idx in order if eigenvalues[idx] > 1e-12][:components]
    if not positive:
        return np.zeros((size, 1))
    return eigenvectors[:, positive] * np.sqrt(eigenvalues[positive])


def family_weights(family_sizes: np.ndarray, scheme: str) -> np.ndarray:
    exponent = WEIGHT_SCHEMES[scheme]
    return 1 / np.power(family_sizes, exponent)


def pam(distance: np.ndarray, k: int, weights: np.ndarray | None = None, max_iter: int = 50) -> np.ndarray:
    size = len(distance)
    weights = np.ones(size) if weights is None else weights
    medoids = [int(np.argmin((distance * weights[None, :]).sum(axis=1)))]
    while len(medoids) < k:
        nearest = np.min(distance[:, medoids], axis=1)
        nearest[medoids] = -1
        medoids.append(int(np.argmax(nearest)))

    labels = np.zeros(size, dtype=int)
    for _ in range(max_iter):
        labels = np.argmin(distance[:, medoids], axis=1)
        updated = []
        for cluster in range(k):
            members = np.where(labels == cluster)[0]
            if len(members) == 0:
                candidates = np.argsort(np.min(distance[:, medoids], axis=1))[::-1]
                updated.append(int(next(item for item in candidates if item not in updated)))
                continue
            local = distance[np.ix_(members, members)]
            costs = (local * weights[members][None, :]).sum(axis=1)
            updated.append(int(members[np.argmin(costs)]))
        if updated == medoids:
            break
        medoids = updated
    return np.argmin(distance[:, medoids], axis=1)


def fit_labels(
    algorithm: str,
    dataset: Dataset,
    indices: np.ndarray,
    k: int,
    seed: int,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    if algorithm == "gower_pam":
        distance = dataset.gower_distance[np.ix_(indices, indices)]
        return pam(distance, k, weights=weights)
    if algorithm == "gower_hierarchical":
        distance = dataset.gower_distance[np.ix_(indices, indices)]
        condensed = squareform(distance, checks=False)
        return fcluster(linkage(condensed, method="average"), k, criterion="maxclust") - 1
    if algorithm == "structured_kmeans":
        model = KMeans(n_clusters=k, n_init=20, random_state=seed)
        model.fit(dataset.structured_matrix[indices], sample_weight=weights)
        return model.labels_
    if algorithm == "text_tfidf_svd_kmeans":
        model = KMeans(n_clusters=k, n_init=20, random_state=seed)
        model.fit(dataset.text_matrix[indices], sample_weight=weights)
        return model.labels_
    raise ValueError(f"Unknown algorithm: {algorithm}")


def metric_space(algorithm: str, dataset: Dataset, indices: np.ndarray) -> tuple[np.ndarray, str]:
    if algorithm.startswith("gower_"):
        return dataset.gower_distance[np.ix_(indices, indices)], "precomputed"
    if algorithm == "structured_kmeans":
        return dataset.structured_matrix[indices], "euclidean"
    return dataset.text_matrix[indices], "cosine"


def score_labels(algorithm: str, dataset: Dataset, indices: np.ndarray, labels: np.ndarray) -> dict:
    unique = len(set(labels))
    counts = Counter(labels)
    minimum_cluster_size = min(counts.values())
    maximum_cluster_share = max(counts.values()) / len(labels)
    singleton_clusters = sum(size == 1 for size in counts.values())
    minimum_required = max(5, math.ceil(len(labels) * 0.01))
    structurally_viable = minimum_cluster_size >= minimum_required and maximum_cluster_share <= 0.75
    if unique < 2 or unique >= len(labels):
        return {
            "silhouette": math.nan,
            "davies_bouldin": math.nan,
            "calinski_harabasz": math.nan,
            "min_cluster_size": minimum_cluster_size,
            "max_cluster_share": maximum_cluster_share,
            "singleton_clusters": singleton_clusters,
            "structurally_viable": structurally_viable,
        }
    space, metric = metric_space(algorithm, dataset, indices)
    silhouette = float(silhouette_score(space, labels, metric=metric))
    coordinates = dataset.gower_coordinates[indices] if metric == "precomputed" else space
    return {
        "silhouette": silhouette,
        "davies_bouldin": float(davies_bouldin_score(coordinates, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(coordinates, labels)),
        "min_cluster_size": minimum_cluster_size,
        "max_cluster_share": maximum_cluster_share,
        "singleton_clusters": singleton_clusters,
        "structurally_viable": structurally_viable,
    }


def weighted_silhouette(
    algorithm: str,
    dataset: Dataset,
    labels: np.ndarray,
    weights: np.ndarray,
) -> float:
    indices = np.arange(len(labels))
    space, metric = metric_space(algorithm, dataset, indices)
    values = silhouette_samples(space, labels, metric=metric)
    return float(np.average(values, weights=weights))


def mean_cluster_jaccard(reference: np.ndarray, candidate: np.ndarray) -> float:
    scores = []
    for label in sorted(set(reference)):
        left = set(np.where(reference == label)[0])
        scores.append(
            max(
                len(left & set(np.where(candidate == other)[0]))
                / len(left | set(np.where(candidate == other)[0]))
                for other in sorted(set(candidate))
            )
        )
    return float(np.mean(scores))


def stability(
    algorithm: str,
    dataset: Dataset,
    k: int,
    labels: np.ndarray,
    repeats: int,
    seed: int,
) -> dict:
    rng = np.random.default_rng(seed)
    families = sorted(set(dataset.families))
    ari_scores = []
    jaccard_scores = []
    for iteration in range(repeats):
        selected_families = set(
            rng.choice(families, size=max(k + 2, int(len(families) * 0.8)), replace=False)
        )
        indices = np.array(
            [idx for idx, family in enumerate(dataset.families) if family in selected_families],
            dtype=int,
        )
        if len(indices) <= k:
            continue
        candidate = fit_labels(algorithm, dataset, indices, k, seed + iteration + 1)
        reference = labels[indices]
        ari_scores.append(float(adjusted_rand_score(reference, candidate)))
        jaccard_scores.append(mean_cluster_jaccard(reference, candidate))
    return {
        "bootstrap_repeats": len(ari_scores),
        "stability_ari_mean": float(np.mean(ari_scores)),
        "stability_ari_min": float(np.min(ari_scores)),
        "stability_jaccard_mean": float(np.mean(jaccard_scores)),
        "stability_jaccard_min": float(np.min(jaccard_scores)),
    }


def compare_models(dataset: Dataset, k_min: int, k_max: int, seed: int) -> tuple[list[dict], dict]:
    algorithms = [
        "gower_pam",
        "gower_hierarchical",
        "structured_kmeans",
        "text_tfidf_svd_kmeans",
    ]
    indices = np.arange(len(dataset.ids))
    rows = []
    labels_by_key = {}
    for algorithm in algorithms:
        for k in range(k_min, k_max + 1):
            labels = fit_labels(algorithm, dataset, indices, k, seed)
            labels_by_key[(algorithm, k)] = labels
            metrics = score_labels(algorithm, dataset, indices, labels)
            rows.append(
                {
                    "algorithm": algorithm,
                    "representation": (
                        "gower_mixed"
                        if algorithm.startswith("gower_")
                        else "structured_onehot"
                        if algorithm == "structured_kmeans"
                        else "tfidf_svd"
                    ),
                    "k": k,
                    **{name: round(value, 6) for name, value in metrics.items()},
                    "ari_category": round(float(adjusted_rand_score(dataset.categories, labels)), 6),
                    "nmi_category": round(
                        float(normalized_mutual_info_score(dataset.categories, labels)), 6
                    ),
                    "v_measure_category": round(float(v_measure_score(dataset.categories, labels)), 6),
                    "ari_subcategory": round(
                        float(adjusted_rand_score(dataset.subcategories, labels)), 6
                    ),
                    "nmi_subcategory": round(
                        float(normalized_mutual_info_score(dataset.subcategories, labels)), 6
                    ),
                    "v_measure_subcategory": round(
                        float(v_measure_score(dataset.subcategories, labels)), 6
                    ),
                }
            )
    return rows, labels_by_key


def choose_best_by_algorithm(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["algorithm"]].append(row)
    result = {}
    for algorithm, candidates in grouped.items():
        viable = [row for row in candidates if row["structurally_viable"]]
        pool = viable or candidates
        result[algorithm] = max(pool, key=lambda row: row["silhouette"])
    return result


def stability_rows(
    dataset: Dataset,
    best: dict[str, dict],
    labels_by_key: dict,
    repeats: int,
    seed: int,
) -> list[dict]:
    rows = []
    for algorithm, model in best.items():
        k = int(model["k"])
        values = stability(algorithm, dataset, k, labels_by_key[(algorithm, k)], repeats, seed)
        rows.append({"algorithm": algorithm, "k": k, **{k: round(v, 6) for k, v in values.items()}})
    return rows


def sensitivity_rows(dataset: Dataset, best: dict[str, dict], labels_by_key: dict, seed: int) -> list[dict]:
    indices = np.arange(len(dataset.ids))
    rows = []
    for algorithm, model in best.items():
        k = int(model["k"])
        reference = labels_by_key[(algorithm, k)]
        for scheme in WEIGHT_SCHEMES:
            weights = family_weights(dataset.family_sizes, scheme)
            if algorithm == "gower_hierarchical":
                labels = reference
                fit_mode = "evaluation_only"
            else:
                labels = fit_labels(algorithm, dataset, indices, k, seed, weights=weights)
                fit_mode = "weighted_refit"
            rows.append(
                {
                    "algorithm": algorithm,
                    "k": k,
                    "weight_scheme": scheme,
                    "fit_mode": fit_mode,
                    "ari_vs_unweighted": round(float(adjusted_rand_score(reference, labels)), 6),
                    "weighted_silhouette": round(
                        weighted_silhouette(algorithm, dataset, labels, weights), 6
                    ),
                }
            )
    return rows


def cluster_profiles(dataset: Dataset, algorithm: str, k: int, labels: np.ndarray) -> list[dict]:
    rows = []
    for cluster in sorted(set(labels)):
        indices = np.where(labels == cluster)[0]
        category = Counter(dataset.categories[indices]).most_common(1)[0]
        subcategory = Counter(dataset.subcategories[indices]).most_common(1)[0]
        purpose_counts = {
            name: int(dataset.binary[indices, col].sum()) for col, name in enumerate(PURPOSES)
        }
        top_purposes = sorted(purpose_counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        rows.append(
            {
                "algorithm": algorithm,
                "k": k,
                "cluster": int(cluster),
                "size": len(indices),
                "top_category": category[0],
                "top_category_share": round(category[1] / len(indices), 4),
                "top_subcategory": subcategory[0],
                "top_subcategory_share": round(subcategory[1] / len(indices), 4),
                "top_purposes": "; ".join(
                    f"{name}:{count / len(indices):.1%}" for name, count in top_purposes if count
                ),
                "sample_titles": " | ".join(dataset.titles[idx] for idx in indices[:3]),
            }
        )
    return rows


def content_repeat_candidates(dataset: Dataset) -> list[dict]:
    purpose_count = len(PURPOSES)
    purpose = dataset.binary[:, :purpose_count]
    vectorizer = TfidfVectorizer(min_df=1, ngram_range=(1, 2), max_features=4000)
    matrix = vectorizer.fit_transform(dataset.text_corpus)
    cosine = cosine_similarity(matrix)
    rows = []
    for left in range(len(dataset.ids)):
        for right in range(left + 1, len(dataset.ids)):
            union = np.maximum(purpose[left], purpose[right]).sum()
            if union == 0:
                continue
            jaccard = np.minimum(purpose[left], purpose[right]).sum() / union
            if jaccard >= 0.8 and cosine[left, right] >= 0.9:
                rows.append(
                    {
                        "left_id": dataset.ids[left],
                        "right_id": dataset.ids[right],
                        "purpose_jaccard": round(float(jaccard), 6),
                        "summary_title_cosine": round(float(cosine[left, right]), 6),
                        "same_family": dataset.families[left] == dataset.families[right],
                        "left_title": dataset.titles[left],
                        "right_title": dataset.titles[right],
                    }
                )
    return sorted(
        rows,
        key=lambda row: (-row["summary_title_cosine"], -row["purpose_jaccard"], row["left_id"]),
    )


def assignments(dataset: Dataset, labels_by_key: dict, best: dict[str, dict]) -> list[dict]:
    rows = []
    for idx, record_id in enumerate(dataset.ids):
        row = {
            "record_id": record_id,
            "title": dataset.titles[idx],
            "program_family_id": dataset.families[idx],
            "category_reference": dataset.categories[idx],
            "subcategory_reference": dataset.subcategories[idx],
        }
        for algorithm, model in best.items():
            row[f"{algorithm}_k{model['k']}"] = int(labels_by_key[(algorithm, int(model["k"]))][idx])
        rows.append(row)
    return rows


def html_table(rows: list[dict], columns: list[str]) -> str:
    return (
        "<table><tr>"
        + "".join(f"<th>{escape(column)}</th>" for column in columns)
        + "</tr>"
        + "".join(
            "<tr>"
            + "".join(f"<td>{escape(str(row.get(column, '')))}</td>" for column in columns)
            + "</tr>"
            for row in rows
        )
        + "</table>"
    )


def render_report(
    dataset: Dataset,
    comparison: list[dict],
    best: dict[str, dict],
    stability_result: list[dict],
    sensitivity: list[dict],
    profiles: list[dict],
    repeat_candidates: list[dict],
    args: argparse.Namespace,
) -> str:
    best_rows = [best[name] for name in sorted(best)]
    stability_by_algorithm = {row["algorithm"]: row for row in stability_result}
    merged_best = [
        {
            **row,
            "stability_jaccard_mean": stability_by_algorithm[row["algorithm"]][
                "stability_jaccard_mean"
            ],
            "stability_ari_mean": stability_by_algorithm[row["algorithm"]]["stability_ari_mean"],
        }
        for row in best_rows
    ]
    preferred = max(
        [row for row in merged_best if row["structurally_viable"]],
        key=lambda row: (row["stability_jaccard_mean"], row["silhouette"]),
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>정책상품 taxonomy ML 파일럿 결과</title>
<style>
body{{font-family:Arial,"Malgun Gothic",sans-serif;line-height:1.6;background:#f5f1e8;color:#24332f;margin:0}}
main{{max-width:1180px;margin:auto;padding:34px 22px 70px}}h1{{font-size:29px}}h2{{border-left:5px solid #2e806d;padding-left:12px;margin-top:32px}}
.hero,.note{{background:#fffdfa;border-radius:12px;padding:16px 18px;margin:12px 0;box-shadow:0 2px 10px #0000000d}}.warn{{border-left:5px solid #c9871a}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:9px}}.metric{{background:#e8f3ed;border-radius:9px;padding:11px}}.metric b{{display:block;font-size:22px;color:#276b5d}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fffdfa;margin:10px 0}}th,td{{border:1px solid #ddd4c5;padding:7px;vertical-align:top}}th{{background:#e8f3ed}}code{{background:#e7ece8;padding:2px 5px;border-radius:4px}}
</style></head><body><main>
<h1>정책상품 taxonomy ML 파일럿 결과</h1>
<p>2026-06-02 | 전문가 라벨 없이 구조적 일관성과 재현성을 탐색하는 사전 실험</p>
<section class="hero"><b>파일럿 결론</b><p>현재 데이터에서 복수 비지도 방법을 실제 실행했다. 기존 행정 분류는 입력에서 제외하고 사후 비교에만 사용했다. 최소 군집 크기와 최대 군집 비중 조건을 통과한 후보 중 재표집 안정성이 가장 높은 <code>{escape(str(preferred['algorithm']))}</code>의 <code>k={preferred['k']}</code> 결과를 후속 검토 우선순위로 둔다. 이 결과는 taxonomy 확정이 아니라 본 실험 설계를 점검하기 위한 후보이다.</p></section>
<div class="grid">
<div class="metric"><b>{len(dataset.ids)}</b>분석 공고</div><div class="metric"><b>{len(set(dataset.families))}</b>사업군</div>
<div class="metric"><b>{len(comparison)}</b>모형 조합</div><div class="metric"><b>{args.bootstrap}</b>사업군 재표집 반복</div>
<div class="metric"><b>{len(repeat_candidates)}</b>확장 내용 반복 후보 쌍</div>
</div>
<h2>1. 실행 범위</h2>
<div class="note warn"><b>중요:</b> 이 파일럿에는 LCA와 최종 Prediction Strength가 아직 포함되지 않았다. 외부 패키지 설치 없이 실행 가능한 네 후보를 먼저 비교했다. Silhouette 값은 표현 공간이 다른 텍스트 모형과 구조 모형 사이에서 절대값만으로 단순 우열을 확정하면 안 된다.</div>
<ul><li><code>gower_pam</code>: 혼합형 정책 속성의 Gower 거리와 k-medoids</li>
<li><code>gower_hierarchical</code>: 동일 Gower 거리와 평균 연결 계층형 군집화</li>
<li><code>structured_kmeans</code>: 구조화 속성 one-hot 및 표준화 후 KMeans</li>
<li><code>text_tfidf_svd_kmeans</code>: 제목·요약 텍스트 TF-IDF, SVD 후 KMeans</li></ul>
<h2>2. 알고리즘별 최상 후보</h2>
{html_table(merged_best, ['algorithm','representation','k','silhouette','min_cluster_size','max_cluster_share','singleton_clusters','structurally_viable','stability_jaccard_mean','stability_ari_mean','v_measure_category','v_measure_subcategory'])}
<h2>3. 가중 방식 민감도</h2>
<p>사업군 반복 크기에 따라 비가중, <code>1/sqrt(n)</code>, <code>1/n</code>을 비교했다. 계층형 군집화는 가중 재학습이 없어 평가 가중치만 변경했다.</p>
{html_table(sensitivity, ['algorithm','k','weight_scheme','fit_mode','ari_vs_unweighted','weighted_silhouette'])}
<h2>4. 우선 검토 후보의 군집 프로파일</h2>
{html_table(profiles, ['cluster','size','top_category','top_category_share','top_subcategory','top_subcategory_share','top_purposes','sample_titles'])}
<h2>5. 내용 반복 후보 확장</h2>
<p>문헌 검토 의견에 따라 목적 태그 Jaccard 0.8 이상, 제목·요약 TF-IDF cosine 0.9 이상인 쌍을 별도 후보로 산출했다. 자동 삭제하지 않는다.</p>
{html_table(repeat_candidates[:30], ['purpose_jaccard','summary_title_cosine','same_family','left_title','right_title'])}
<h2>6. 다음 본 실험 보완</h2>
<ol><li>LCA를 추가하고 BIC, entropy, BLRT를 보고한다.</li><li>GroupKFold 기반 Prediction Strength를 구현한다.</li>
<li>문장 임베딩 모형을 TF-IDF 파일럿과 비교한다.</li><li>확장 내용 반복 후보를 검토해 사업군 규칙을 정교화한다.</li>
<li>동일 표현 공간 안에서 지표를 비교하고, 표현 공간 간 비교는 ARI·프로파일 해석을 함께 사용한다.</li></ol>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-db", required=True, type=Path)
    parser.add_argument("--preallocation", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--k-min", type=int, default=4)
    parser.add_argument("--k-max", type=int, default=12)
    parser.add_argument("--bootstrap", type=int, default=16)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records = json.loads(args.knowledge_db.read_text(encoding="utf-8"))
    with args.preallocation.open(encoding="utf-8-sig", newline="") as file:
        allocation = list(csv.DictReader(file))
    dataset = build_dataset(records, allocation, args.seed)

    comparison, labels_by_key = compare_models(dataset, args.k_min, args.k_max, args.seed)
    best = choose_best_by_algorithm(comparison)
    stability_result = stability_rows(dataset, best, labels_by_key, args.bootstrap, args.seed)
    sensitivity = sensitivity_rows(dataset, best, labels_by_key, args.seed)
    stability_by_algorithm = {row["algorithm"]: row for row in stability_result}
    preferred = max(
        [row for row in best.values() if row["structurally_viable"]],
        key=lambda row: (
            stability_by_algorithm[row["algorithm"]]["stability_jaccard_mean"],
            row["silhouette"],
        ),
    )
    strongest_algorithm = preferred["algorithm"]
    strongest_k = int(preferred["k"])
    profiles = cluster_profiles(
        dataset,
        strongest_algorithm,
        strongest_k,
        labels_by_key[(strongest_algorithm, strongest_k)],
    )
    repeat_candidates = content_repeat_candidates(dataset)
    assignment_rows = assignments(dataset, labels_by_key, best)

    write_csv(args.output_dir / "pilot-model-comparison.csv", comparison)
    write_csv(args.output_dir / "pilot-cluster-stability.csv", stability_result)
    write_csv(args.output_dir / "pilot-weight-sensitivity.csv", sensitivity)
    write_csv(args.output_dir / "pilot-cluster-profiles.csv", profiles)
    write_csv(args.output_dir / "pilot-content-repeat-candidates.csv", repeat_candidates)
    write_csv(args.output_dir / "pilot-cluster-assignments.csv", assignment_rows)

    summary = {
        "status": "PILOT_COMPLETE",
        "records": len(dataset.ids),
        "families": len(set(dataset.families)),
        "kRange": [args.k_min, args.k_max],
        "bootstrapRepeats": args.bootstrap,
        "modelsCompared": len(comparison),
        "bestByAlgorithm": best,
        "stability": stability_result,
        "expandedContentRepeatCandidatePairs": len(repeat_candidates),
        "preferredRobustnessPilotCandidate": {
            "algorithm": strongest_algorithm,
            "k": strongest_k,
            "reason": "Highest family-aware resampling Jaccard among structurally viable pilot candidates",
        },
        "limitations": [
            "LCA is deferred to the full benchmark.",
            "Prediction Strength is deferred to the full benchmark.",
            "TF-IDF+SVD is a text pilot; sentence embeddings remain to be compared.",
            "Cross-representation silhouette values must not be treated as directly comparable.",
            "No administrative or legal correctness claim is made.",
        ],
    }
    (args.output_dir / "pilot-run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "ml-taxonomy-pilot-report-20260602.html").write_text(
        render_report(
            dataset,
            comparison,
            best,
            stability_result,
            sensitivity,
            profiles,
            repeat_candidates,
            args,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
