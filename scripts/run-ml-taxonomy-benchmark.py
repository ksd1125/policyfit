"""Run the full policy taxonomy benchmark after the exploratory pilot.

The benchmark keeps administrative category labels out of clustering inputs.
They are used only after fitting as external reference variables.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_score,
    v_measure_score,
)
from sklearn.model_selection import GroupKFold
from sentence_transformers import SentenceTransformer


def load_pilot_module(path: Path):
    spec = importlib.util.spec_from_file_location("taxonomy_pilot", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import pilot module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def logsumexp(values: np.ndarray, axis: int = 1) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    return np.squeeze(maximum, axis=axis) + np.log(
        np.sum(np.exp(values - maximum), axis=axis)
    )


def discretize_numeric(values: np.ndarray, name: str) -> list[str]:
    valid = values[~np.isnan(values)]
    if not len(valid) or np.all(valid == valid[0]):
        return [f"{name}:missing" if math.isnan(value) else f"{name}:single" for value in values]
    quantiles = np.unique(np.quantile(valid, [0.25, 0.5, 0.75]))
    result = []
    for value in values:
        if math.isnan(value):
            result.append(f"{name}:missing")
        else:
            result.append(f"{name}:q{int(np.searchsorted(quantiles, value, side='right')) + 1}")
    return result


def build_lca_features(dataset) -> tuple[np.ndarray, list[str]]:
    columns = [
        dataset.categorical[:, idx].astype(str).tolist()
        for idx in range(dataset.categorical.shape[1])
    ]
    names = list(dataset.categorical_names)
    for idx, name in enumerate(dataset.numeric_names):
        columns.append(discretize_numeric(dataset.numeric[:, idx], name))
        names.append(name)
    for idx, name in enumerate(dataset.binary_names):
        columns.append([f"{name}:{int(value)}" for value in dataset.binary[:, idx]])
        names.append(name)
    return np.array(columns, dtype=object).T, names


@dataclass
class MixedLCA:
    k: int
    seed: int
    n_init: int = 6
    max_iter: int = 180
    tolerance: float = 1e-6
    alpha: float = 0.5

    def fit(self, features: np.ndarray, sample_weight: np.ndarray | None = None):
        weight = np.ones(len(features), dtype=float) if sample_weight is None else sample_weight
        self.levels_ = [sorted(set(features[:, col])) for col in range(features.shape[1])]
        self.level_maps_ = [{value: idx for idx, value in enumerate(levels)} for levels in self.levels_]
        encoded = self._encode(features)
        rng = np.random.default_rng(self.seed)
        best = None
        for _ in range(self.n_init):
            responsibilities = rng.dirichlet(np.ones(self.k), size=len(features))
            previous = -math.inf
            for _iteration in range(self.max_iter):
                priors, probabilities = self._m_step(encoded, responsibilities, weight)
                log_joint = self._log_joint(encoded, priors, probabilities)
                likelihood = float(np.sum(weight * logsumexp(log_joint)))
                normalized = log_joint - logsumexp(log_joint)[:, None]
                responsibilities = np.exp(normalized)
                if abs(likelihood - previous) < self.tolerance:
                    break
                previous = likelihood
            if best is None or likelihood > best[0]:
                best = (likelihood, priors, probabilities, responsibilities)
        assert best is not None
        self.log_likelihood_, self.priors_, self.probabilities_, self.responsibilities_ = best
        self.labels_ = np.argmax(self.responsibilities_, axis=1)
        self.n_parameters_ = (self.k - 1) + sum(
            self.k * (len(levels) - 1) for levels in self.levels_
        )
        self.bic_ = -2 * self.log_likelihood_ + self.n_parameters_ * math.log(weight.sum())
        self.aic_ = -2 * self.log_likelihood_ + 2 * self.n_parameters_
        entropy = -np.sum(self.responsibilities_ * np.log(self.responsibilities_ + 1e-12), axis=1)
        self.entropy_ = float(1 - np.mean(entropy) / math.log(self.k)) if self.k > 1 else 1.0
        return self

    def _encode(self, features: np.ndarray) -> np.ndarray:
        encoded = np.full(features.shape, -1, dtype=int)
        for col, mapping in enumerate(self.level_maps_):
            for row, value in enumerate(features[:, col]):
                encoded[row, col] = mapping.get(value, -1)
        return encoded

    def _m_step(
        self, encoded: np.ndarray, responsibilities: np.ndarray, weight: np.ndarray
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        weighted = responsibilities * weight[:, None]
        class_weight = weighted.sum(axis=0)
        priors = (class_weight + self.alpha) / (weight.sum() + self.alpha * self.k)
        probabilities = []
        for col, levels in enumerate(self.levels_):
            table = np.full((self.k, len(levels)), self.alpha, dtype=float)
            for level in range(len(levels)):
                mask = encoded[:, col] == level
                if mask.any():
                    table[:, level] += weighted[mask].sum(axis=0)
            table /= table.sum(axis=1, keepdims=True)
            probabilities.append(table)
        return priors, probabilities

    def _log_joint(
        self, encoded: np.ndarray, priors: np.ndarray, probabilities: list[np.ndarray]
    ) -> np.ndarray:
        result = np.tile(np.log(priors + 1e-12), (len(encoded), 1))
        for col, table in enumerate(probabilities):
            for row, level in enumerate(encoded[:, col]):
                if level >= 0:
                    result[row] += np.log(table[:, level] + 1e-12)
        return result

    def predict(self, features: np.ndarray) -> np.ndarray:
        encoded = self._encode(features)
        return np.argmax(self._log_joint(encoded, self.priors_, self.probabilities_), axis=1)

    def sample(self, size: int, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        classes = rng.choice(self.k, size=size, p=self.priors_)
        sampled = np.empty((size, len(self.levels_)), dtype=object)
        for row, cluster in enumerate(classes):
            for col, levels in enumerate(self.levels_):
                sampled[row, col] = rng.choice(levels, p=self.probabilities_[col][cluster])
        return sampled


def viability(labels: np.ndarray) -> dict:
    counts = Counter(labels)
    minimum_required = max(5, math.ceil(len(labels) * 0.01))
    minimum = min(counts.values())
    maximum_share = max(counts.values()) / len(labels)
    return {
        "min_cluster_size": minimum,
        "max_cluster_share": round(maximum_share, 6),
        "singleton_clusters": sum(size == 1 for size in counts.values()),
        "structurally_viable": int(minimum >= minimum_required and maximum_share <= 0.75),
    }


def evaluate_labels(dataset, algorithm: str, labels: np.ndarray, embeddings: np.ndarray) -> dict:
    if algorithm.startswith("gower_") or algorithm == "lca":
        space, metric = dataset.gower_distance, "precomputed"
        coordinates = dataset.gower_coordinates
    elif algorithm == "structured_kmeans":
        space, metric = dataset.structured_matrix, "euclidean"
        coordinates = space
    elif algorithm == "text_tfidf_svd_kmeans":
        space, metric = dataset.text_matrix, "cosine"
        coordinates = space
    elif algorithm == "sentence_embedding_kmeans":
        space, metric = embeddings, "cosine"
        coordinates = space
    else:
        raise ValueError(algorithm)
    return {
        "silhouette": round(float(silhouette_score(space, labels, metric=metric)), 6),
        "davies_bouldin": round(float(davies_bouldin_score(coordinates, labels)), 6),
        "calinski_harabasz": round(float(calinski_harabasz_score(coordinates, labels)), 6),
        **viability(labels),
        "ari_category": round(float(adjusted_rand_score(dataset.categories, labels)), 6),
        "nmi_category": round(float(normalized_mutual_info_score(dataset.categories, labels)), 6),
        "v_measure_category": round(float(v_measure_score(dataset.categories, labels)), 6),
        "ari_subcategory": round(float(adjusted_rand_score(dataset.subcategories, labels)), 6),
        "nmi_subcategory": round(
            float(normalized_mutual_info_score(dataset.subcategories, labels)), 6
        ),
        "v_measure_subcategory": round(float(v_measure_score(dataset.subcategories, labels)), 6),
    }


def fit_algorithm(
    pilot,
    algorithm: str,
    dataset,
    indices: np.ndarray,
    k: int,
    seed: int,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
    weights: np.ndarray | None = None,
) -> tuple[np.ndarray, object | None]:
    if algorithm == "sentence_embedding_kmeans":
        model = KMeans(n_clusters=k, n_init=20, random_state=seed)
        model.fit(embeddings[indices], sample_weight=weights)
        return model.labels_, model
    if algorithm == "lca":
        model = MixedLCA(k=k, seed=seed).fit(lca_features[indices], sample_weight=weights)
        return model.labels_, model
    return pilot.fit_labels(algorithm, dataset, indices, k, seed, weights=weights), None


def fit_full_grid(
    pilot,
    dataset,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
    k_min: int,
    k_max: int,
    seed: int,
) -> tuple[list[dict], dict]:
    algorithms = [
        "gower_pam",
        "gower_hierarchical",
        "structured_kmeans",
        "text_tfidf_svd_kmeans",
        "sentence_embedding_kmeans",
        "lca",
    ]
    indices = np.arange(len(dataset.ids))
    rows = []
    labels_by_key = {}
    lca_models = {}
    for algorithm in algorithms:
        for k in range(k_min, k_max + 1):
            labels, model = fit_algorithm(
                pilot, algorithm, dataset, indices, k, seed, embeddings, lca_features
            )
            labels_by_key[(algorithm, k)] = labels
            row = {
                "algorithm": algorithm,
                "representation": (
                    "gower_mixed"
                    if algorithm.startswith("gower_")
                    else "structured_onehot"
                    if algorithm == "structured_kmeans"
                    else "tfidf_svd"
                    if algorithm == "text_tfidf_svd_kmeans"
                    else "sentence_embedding"
                    if algorithm == "sentence_embedding_kmeans"
                    else "latent_class"
                ),
                "k": k,
                **evaluate_labels(dataset, algorithm, labels, embeddings),
            }
            if algorithm == "lca":
                lca_models[k] = model
                row.update(
                    {
                        "log_likelihood": round(model.log_likelihood_, 6),
                        "bic": round(model.bic_, 6),
                        "aic": round(model.aic_, 6),
                        "entropy": round(model.entropy_, 6),
                    }
                )
            else:
                row.update({"log_likelihood": "", "bic": "", "aic": "", "entropy": ""})
            rows.append(row)
    return rows, {"labels": labels_by_key, "lca_models": lca_models}


def select_best(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["algorithm"]].append(row)
    selected = {}
    for algorithm, candidates in grouped.items():
        viable = [row for row in candidates if row["structurally_viable"]]
        pool = viable or candidates
        if algorithm == "lca":
            selected[algorithm] = min(pool, key=lambda row: float(row["bic"]))
        else:
            selected[algorithm] = max(pool, key=lambda row: row["silhouette"])
    return selected


def mean_cluster_jaccard(reference: np.ndarray, candidate: np.ndarray) -> float:
    values = []
    for label in sorted(set(reference)):
        left = set(np.where(reference == label)[0])
        values.append(
            max(
                len(left & set(np.where(candidate == other)[0]))
                / len(left | set(np.where(candidate == other)[0]))
                for other in sorted(set(candidate))
            )
        )
    return float(np.mean(values))


def resampling_stability(
    pilot,
    algorithm: str,
    dataset,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
    k: int,
    labels: np.ndarray,
    repeats: int,
    seed: int,
) -> dict:
    rng = np.random.default_rng(seed)
    families = sorted(set(dataset.families))
    ari_values, jaccard_values = [], []
    for iteration in range(repeats):
        selected = set(rng.choice(families, size=int(len(families) * 0.8), replace=False))
        indices = np.array(
            [idx for idx, family in enumerate(dataset.families) if family in selected], dtype=int
        )
        candidate, _ = fit_algorithm(
            pilot,
            algorithm,
            dataset,
            indices,
            k,
            seed + iteration + 1,
            embeddings,
            lca_features,
        )
        reference = labels[indices]
        ari_values.append(float(adjusted_rand_score(reference, candidate)))
        jaccard_values.append(mean_cluster_jaccard(reference, candidate))
    return {
        "algorithm": algorithm,
        "k": k,
        "bootstrap_repeats": repeats,
        "stability_ari_mean": round(float(np.mean(ari_values)), 6),
        "stability_ari_min": round(float(np.min(ari_values)), 6),
        "stability_jaccard_mean": round(float(np.mean(jaccard_values)), 6),
        "stability_jaccard_min": round(float(np.min(jaccard_values)), 6),
    }


def infer_test_labels(
    pilot,
    algorithm: str,
    dataset,
    train: np.ndarray,
    test: np.ndarray,
    train_labels: np.ndarray,
    model: object | None,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
) -> np.ndarray:
    if algorithm in {"structured_kmeans", "text_tfidf_svd_kmeans", "sentence_embedding_kmeans"}:
        if algorithm == "structured_kmeans":
            matrix = dataset.structured_matrix
        elif algorithm == "text_tfidf_svd_kmeans":
            matrix = dataset.text_matrix
        else:
            matrix = embeddings
        if model is None:
            trained = KMeans(n_clusters=len(set(train_labels)), n_init=20, random_state=20260602)
            trained.fit(matrix[train])
            return trained.predict(matrix[test])
        return model.predict(matrix[test])
    if algorithm == "lca":
        return model.predict(lca_features[test])
    if algorithm == "gower_pam":
        medoids = []
        for label in sorted(set(train_labels)):
            members = train[np.where(train_labels == label)[0]]
            local = dataset.gower_distance[np.ix_(members, members)]
            medoids.append(int(members[np.argmin(local.sum(axis=1))]))
        return np.argmin(dataset.gower_distance[np.ix_(test, medoids)], axis=1)
    if algorithm == "gower_hierarchical":
        distances = []
        for label in sorted(set(train_labels)):
            members = train[np.where(train_labels == label)[0]]
            distances.append(dataset.gower_distance[np.ix_(test, members)].mean(axis=1))
        return np.argmin(np.column_stack(distances), axis=1)
    raise ValueError(algorithm)


def prediction_strength(
    pilot,
    algorithm: str,
    dataset,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
    k: int,
    seed: int,
    folds: int,
) -> dict:
    splitter = GroupKFold(n_splits=folds)
    fold_values = []
    indices = np.arange(len(dataset.ids))
    for fold, (train, test) in enumerate(splitter.split(indices, groups=dataset.families)):
        train_labels, model = fit_algorithm(
            pilot, algorithm, dataset, train, k, seed + fold, embeddings, lca_features
        )
        predicted = infer_test_labels(
            pilot,
            algorithm,
            dataset,
            train,
            test,
            train_labels,
            model,
            embeddings,
            lca_features,
        )
        independent, _ = fit_algorithm(
            pilot, algorithm, dataset, test, k, seed + 100 + fold, embeddings, lca_features
        )
        strengths = []
        for label in sorted(set(predicted)):
            members = np.where(predicted == label)[0]
            if len(members) < 2:
                continue
            together = independent[members][:, None] == independent[members][None, :]
            strengths.append(float((together.sum() - len(members)) / (len(members) * (len(members) - 1))))
        if strengths:
            fold_values.append(min(strengths))
    return {
        "algorithm": algorithm,
        "k": k,
        "group_folds": folds,
        "prediction_strength_mean": round(float(np.mean(fold_values)), 6),
        "prediction_strength_min": round(float(np.min(fold_values)), 6),
    }


def weight_sensitivity(
    pilot,
    algorithm: str,
    dataset,
    embeddings: np.ndarray,
    lca_features: np.ndarray,
    k: int,
    reference: np.ndarray,
    seed: int,
) -> list[dict]:
    indices = np.arange(len(dataset.ids))
    rows = []
    for scheme, exponent in pilot.WEIGHT_SCHEMES.items():
        weights = 1 / np.power(dataset.family_sizes, exponent)
        if algorithm == "gower_hierarchical":
            labels = reference
            fit_mode = "evaluation_only"
        else:
            labels, _ = fit_algorithm(
                pilot, algorithm, dataset, indices, k, seed, embeddings, lca_features, weights
            )
            fit_mode = "weighted_refit"
        rows.append(
            {
                "algorithm": algorithm,
                "k": k,
                "weight_scheme": scheme,
                "fit_mode": fit_mode,
                "ari_vs_unweighted": round(float(adjusted_rand_score(reference, labels)), 6),
            }
        )
    return rows


def approximate_blrt(
    null_model: MixedLCA,
    alternative_model: MixedLCA,
    size: int,
    repeats: int,
    seed: int,
) -> dict:
    observed = 2 * (alternative_model.log_likelihood_ - null_model.log_likelihood_)
    bootstrap = []
    for iteration in range(repeats):
        sample = null_model.sample(size, seed + iteration)
        null = MixedLCA(null_model.k, seed + 1000 + iteration, n_init=3).fit(sample)
        alternative = MixedLCA(alternative_model.k, seed + 2000 + iteration, n_init=3).fit(sample)
        bootstrap.append(2 * (alternative.log_likelihood_ - null.log_likelihood_))
    return {
        "null_k": null_model.k,
        "alternative_k": alternative_model.k,
        "observed_lr": round(float(observed), 6),
        "bootstrap_repeats": repeats,
        "bootstrap_p_value": round(float((1 + sum(value >= observed for value in bootstrap)) / (repeats + 1)), 6),
        "note": "Pilot-scale parametric BLRT; increase repetitions for publication use.",
    }


def profiles(pilot, dataset, algorithm: str, k: int, labels: np.ndarray) -> list[dict]:
    return pilot.cluster_profiles(dataset, algorithm, k, labels)


def assignments(dataset, selected: dict[str, dict], labels_by_key: dict) -> list[dict]:
    rows = []
    for index, record_id in enumerate(dataset.ids):
        row = {
            "record_id": record_id,
            "title": dataset.titles[index],
            "program_family_id": dataset.families[index],
            "category_reference": dataset.categories[index],
            "subcategory_reference": dataset.subcategories[index],
        }
        for algorithm, model in selected.items():
            row[f"{algorithm}_k{model['k']}"] = int(labels_by_key[(algorithm, int(model["k"]))][index])
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
    dataset,
    args,
    selected: dict[str, dict],
    stability_rows: list[dict],
    prediction_rows: list[dict],
    blrt: dict,
    sensitivity_rows: list[dict],
    profile_rows: list[dict],
    content_candidates: list[dict],
    preferred: dict,
) -> str:
    stability = {row["algorithm"]: row for row in stability_rows}
    prediction = {row["algorithm"]: row for row in prediction_rows}
    summary_rows = []
    for algorithm in sorted(selected):
        summary_rows.append(
            {
                **selected[algorithm],
                "stability_jaccard_mean": stability[algorithm]["stability_jaccard_mean"],
                "stability_ari_mean": stability[algorithm]["stability_ari_mean"],
                "prediction_strength_mean": prediction[algorithm]["prediction_strength_mean"],
                "prediction_strength_min": prediction[algorithm]["prediction_strength_min"],
            }
        )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>정책상품 taxonomy ML 본 benchmark 결과</title>
<style>
body{{font-family:Arial,"Malgun Gothic",sans-serif;line-height:1.62;background:#f5f1e8;color:#24332f;margin:0}}main{{max-width:1250px;margin:auto;padding:34px 22px 70px}}
h1{{font-size:29px}}h2{{border-left:5px solid #2e806d;padding-left:12px;margin-top:32px}}.hero,.note{{background:#fffdfa;border-radius:12px;padding:16px 18px;margin:12px 0;box-shadow:0 2px 10px #0000000d}}.warn{{border-left:5px solid #c9871a}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:9px}}.metric{{background:#e8f3ed;border-radius:9px;padding:11px}}.metric b{{display:block;font-size:22px;color:#276b5d}}
table{{border-collapse:collapse;width:100%;font-size:12px;background:#fffdfa;margin:10px 0}}th,td{{border:1px solid #ddd4c5;padding:6px;vertical-align:top}}th{{background:#e8f3ed}}code{{background:#e7ece8;padding:2px 5px;border-radius:4px}}
</style></head><body><main>
<h1>정책상품 taxonomy ML 본 benchmark 결과</h1><p>2026-06-02 | 비지도 정책상품 taxonomy의 구조적 일관성·재현성 benchmark</p>
<section class="hero"><b>우선 검토 후보</b><p>구조 조건을 통과한 후보 중 사업군 재표집 안정성, GroupKFold Prediction Strength, 군집 프로파일을 함께 검토하여 <code>{escape(preferred['algorithm'])}</code>의 <code>k={preferred['k']}</code>를 우선 해석 후보로 둔다. 이는 행정적 정답 확정이 아니라 데이터 기반 taxonomy 후보 선정이다.</p></section>
<div class="grid"><div class="metric"><b>{len(dataset.ids)}</b>분석 공고</div><div class="metric"><b>{len(set(dataset.families))}</b>사업군</div><div class="metric"><b>6</b>알고리즘</div><div class="metric"><b>{args.bootstrap}</b>재표집 반복</div><div class="metric"><b>{args.group_folds}</b>GroupKFold</div><div class="metric"><b>{len(content_candidates)}</b>내용 반복 후보 쌍</div></div>
<h2>1. 알고리즘별 선택 후보</h2>
<div class="note warn">표현 공간이 다른 알고리즘의 Silhouette 절대값만으로 우열을 확정하지 않는다. 구조 조건, 재표집 안정성, Prediction Strength, 프로파일 해석을 결합한다.</div>
{html_table(summary_rows,['algorithm','representation','k','silhouette','min_cluster_size','max_cluster_share','structurally_viable','stability_jaccard_mean','stability_ari_mean','prediction_strength_mean','prediction_strength_min','v_measure_category','v_measure_subcategory','bic','entropy'])}
<h2>2. LCA 간이 BLRT</h2><p>출판용 본 분석에서는 반복 수를 더 늘려야 한다.</p>{html_table([blrt],list(blrt))}
<h2>3. 반복사업 가중 민감도</h2>{html_table(sensitivity_rows,['algorithm','k','weight_scheme','fit_mode','ari_vs_unweighted'])}
<h2>4. 우선 후보 군집 프로파일</h2>{html_table(profile_rows,['cluster','size','top_category','top_category_share','top_subcategory','top_subcategory_share','top_purposes','sample_titles'])}
<h2>5. 확장 내용 반복 후보</h2><p>목적 태그 Jaccard 0.8 이상, 제목·요약 TF-IDF cosine 0.9 이상인 쌍이다. 자동 삭제하지 않는다.</p>{html_table(content_candidates[:30],['purpose_jaccard','summary_title_cosine','same_family','left_title','right_title'])}
<h2>6. 해석 경계</h2><ul><li>기존 행정 category·subcategory는 입력에서 제외하고 사후 V-measure 비교에만 사용했다.</li><li>동일 사업군은 GroupKFold에서 함께 이동하여 누수를 방지했다.</li><li>통계적으로 확인한 것은 구조적 일관성과 재현성이다.</li><li>법적·행정적 적합성은 전문가 또는 별도 정답 데이터 없이 확정하지 않는다.</li></ul>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-db", required=True, type=Path)
    parser.add_argument("--preallocation", required=True, type=Path)
    parser.add_argument("--pilot-script", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--embedding-model", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    parser.add_argument("--k-min", type=int, default=4)
    parser.add_argument("--k-max", type=int, default=16)
    parser.add_argument("--bootstrap", type=int, default=48)
    parser.add_argument("--group-folds", type=int, default=5)
    parser.add_argument("--blrt-bootstrap", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260602)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pilot_path = args.pilot_script or Path(__file__).with_name("run-ml-taxonomy-pilot.py")
    pilot = load_pilot_module(pilot_path)
    records = json.loads(args.knowledge_db.read_text(encoding="utf-8"))
    with args.preallocation.open(encoding="utf-8-sig", newline="") as file:
        allocation = list(csv.DictReader(file))
    dataset = pilot.build_dataset(records, allocation, args.seed)
    lca_features, _lca_names = build_lca_features(dataset)

    encoder = SentenceTransformer(args.embedding_model, local_files_only=True)
    embeddings = encoder.encode(
        dataset.text_corpus,
        batch_size=32,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    comparison, fitted = fit_full_grid(
        pilot, dataset, embeddings, lca_features, args.k_min, args.k_max, args.seed
    )
    selected = select_best(comparison)
    stability_rows = []
    prediction_rows = []
    sensitivity_rows = []
    for algorithm, model in selected.items():
        k = int(model["k"])
        labels = fitted["labels"][(algorithm, k)]
        stability_rows.append(
            resampling_stability(
                pilot,
                algorithm,
                dataset,
                embeddings,
                lca_features,
                k,
                labels,
                args.bootstrap,
                args.seed,
            )
        )
        prediction_rows.append(
            prediction_strength(
                pilot,
                algorithm,
                dataset,
                embeddings,
                lca_features,
                k,
                args.seed,
                args.group_folds,
            )
        )
        sensitivity_rows.extend(
            weight_sensitivity(
                pilot,
                algorithm,
                dataset,
                embeddings,
                lca_features,
                k,
                labels,
                args.seed,
            )
        )

    lca_k = int(selected["lca"]["k"])
    if lca_k > args.k_min:
        null_k, alternative_k = lca_k - 1, lca_k
    else:
        null_k, alternative_k = lca_k, lca_k + 1
    blrt = approximate_blrt(
        fitted["lca_models"][null_k],
        fitted["lca_models"][alternative_k],
        len(dataset.ids),
        args.blrt_bootstrap,
        args.seed,
    )
    stability_map = {row["algorithm"]: row for row in stability_rows}
    prediction_map = {row["algorithm"]: row for row in prediction_rows}
    viable = [row for row in selected.values() if row["structurally_viable"]]
    preferred = max(
        viable,
        key=lambda row: (
            prediction_map[row["algorithm"]]["prediction_strength_mean"],
            stability_map[row["algorithm"]]["stability_jaccard_mean"],
            row["silhouette"],
        ),
    )
    preferred_labels = fitted["labels"][(preferred["algorithm"], int(preferred["k"]))]
    profile_rows = profiles(pilot, dataset, preferred["algorithm"], int(preferred["k"]), preferred_labels)
    content_candidates = pilot.content_repeat_candidates(dataset)
    assignment_rows = assignments(dataset, selected, fitted["labels"])

    write_csv(args.output_dir / "benchmark-model-comparison.csv", comparison)
    write_csv(args.output_dir / "benchmark-cluster-stability.csv", stability_rows)
    write_csv(args.output_dir / "benchmark-prediction-strength.csv", prediction_rows)
    write_csv(args.output_dir / "benchmark-weight-sensitivity.csv", sensitivity_rows)
    write_csv(args.output_dir / "benchmark-cluster-profiles.csv", profile_rows)
    write_csv(args.output_dir / "benchmark-content-repeat-candidates.csv", content_candidates)
    write_csv(args.output_dir / "benchmark-cluster-assignments.csv", assignment_rows)
    (args.output_dir / "benchmark-lca-blrt.json").write_text(
        json.dumps(blrt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "status": "BENCHMARK_COMPLETE",
        "records": len(dataset.ids),
        "families": len(set(dataset.families)),
        "algorithms": sorted(selected),
        "kRange": [args.k_min, args.k_max],
        "bootstrapRepeats": args.bootstrap,
        "groupFolds": args.group_folds,
        "blrtBootstrapRepeats": args.blrt_bootstrap,
        "embeddingModel": args.embedding_model,
        "selectedByAlgorithm": selected,
        "stability": stability_rows,
        "predictionStrength": prediction_rows,
        "lcaBlrt": blrt,
        "preferredCandidate": preferred,
        "expandedContentRepeatCandidatePairs": len(content_candidates),
        "claimBoundary": "Structural consistency and reproducibility only; no legal or administrative correctness claim.",
    }
    (args.output_dir / "benchmark-run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "ml-taxonomy-benchmark-report-20260602.html").write_text(
        render_report(
            dataset,
            args,
            selected,
            stability_rows,
            prediction_rows,
            blrt,
            sensitivity_rows,
            profile_rows,
            content_candidates,
            preferred,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
