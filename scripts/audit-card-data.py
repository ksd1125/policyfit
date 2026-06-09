#!/usr/bin/env python3
"""카드 UI 노출 데이터 전수 감사.

카드에 보이는 4가지 핵심 필드를 모두 검사:
  - amountLabel: 지원 금액 (상식 범위 / "당" 명시 여부)
  - period/endDate: 신청 기간 / D-day
  - purpose: 목적문
  - match: 매칭도

발견된 이슈를 카테고리별로 분류해 HTML 보고서 생성.
"""
import json, sys, re
from pathlib import Path
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "outputs" / "policyfit-db.json"
OUT = ROOT / "outputs" / "audit-card-data.html"


def label_value(label):
    if not label: return 0
    rn = re.sub(r"\s+", "", label)
    m = re.search(r"(\d[\d,.]*)(억원|천만원|백만원|만원|조원)", rn)
    if not m: return 0
    units = {"조원": 1_000_000_000_000, "억원": 100_000_000,
             "천만원": 10_000_000, "백만원": 1_000_000, "만원": 10_000}
    try:
        return int(float(m.group(1).replace(",", "")) * units[m.group(2)])
    except Exception:
        return 0


def has_per_keyword(label):
    return bool(re.search(r"(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가)\s*당", label or ""))


def audit_amount(records):
    """금액 필드 이슈."""
    issues = {
        "거대_당없음": [],   # 100억+ 인데 "당" 표현 없음 — 총액 의심
        "확인필요": [],      # "지원 규모 확인 필요" 표기
        "이상값": [],        # 1억 미만의 일부 의심값
    }
    for r in records:
        lbl = r.get("amountLabel") or ""
        v = label_value(lbl)
        if not lbl or lbl == "지원 규모 확인 필요":
            issues["확인필요"].append(r)
        elif v >= 10_000_000_000 and not has_per_keyword(lbl):
            issues["거대_당없음"].append(r)
    return issues


def audit_period(records):
    """신청기간 이슈."""
    issues = {
        "기간_없음": [],
        "기간_과거": [],   # 이미 마감
        "기간_파싱불가": [],
    }
    today = date.today()
    for r in records:
        per = r.get("period") or ""
        end = r.get("endDate")
        if not per or per == "기간 확인 필요":
            issues["기간_없음"].append(r)
            continue
        if end:
            try:
                y, m, d = map(int, end.split("-"))
                if date(y, m, d) < today:
                    issues["기간_과거"].append(r)
            except Exception:
                issues["기간_파싱불가"].append(r)
    return issues


def audit_purpose(records):
    """목적문 잔존 이슈."""
    issues = {
        "너무_짧음": [],
        "너무_김": [],
        "법령_잔존": [],
        "관공서_잔존": [],
    }
    for r in records:
        p = r.get("purpose") or ""
        if len(p) < 30:
            issues["너무_짧음"].append((r, p))
        if len(p) > 150:
            issues["너무_김"].append((r, p))
        if "「" in p and ("법률" in p or "법 제" in p or "조례" in p):
            issues["법령_잔존"].append((r, p))
        if re.search(r"(?:합니다|입니다)\s*\.?\s*$", p) or "도모" in p or "제고" in p:
            issues["관공서_잔존"].append((r, p))
    return issues


def audit_match(records):
    """매칭도 분포."""
    bins = {"90~100": 0, "80~89": 0, "70~79": 0, "60~69": 0, "0~59": 0}
    for r in records:
        m = r.get("match") or 0
        if m >= 90: bins["90~100"] += 1
        elif m >= 80: bins["80~89"] += 1
        elif m >= 70: bins["70~79"] += 1
        elif m >= 60: bins["60~69"] += 1
        else: bins["0~59"] += 1
    return bins


def write_html(amt, per_iss, pur, match_bins, total):
    rows_amt = "\n".join(
        f"<tr><td>{r['id']}</td><td>{r['title'][:60]}</td>"
        f"<td><strong>{r.get('amountLabel','')}</strong></td>"
        f"<td>{r.get('amountSub','') or '-'}</td></tr>"
        for r in amt["거대_당없음"][:50]
    )
    rows_period_past = "\n".join(
        f"<tr><td>{r['id']}</td><td>{r['title'][:60]}</td>"
        f"<td>{r.get('endDate','')}</td><td>{r.get('period','')[:50]}</td></tr>"
        for r in per_iss["기간_과거"][:30]
    )
    rows_purpose_short = "\n".join(
        f"<tr><td>{r['id']}</td><td>{r['title'][:50]}</td>"
        f"<td>{p}</td></tr>"
        for r, p in pur["너무_짧음"][:20]
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>카드 데이터 감사 보고서</title>
<style>
  body {{ font-family: -apple-system, "Pretendard", sans-serif; max-width: 1100px;
          margin: 30px auto; padding: 20px; color: #191F28; line-height: 1.6; }}
  h1 {{ color: #3182F6; border-bottom: 2px solid #3182F6; padding-bottom: 10px; }}
  h2 {{ color: #191F28; margin-top: 40px; }}
  .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }}
  .card {{ background: #F2F4F6; border-radius: 12px; padding: 20px; text-align: center; }}
  .card .num {{ font-size: 28px; font-weight: 700; color: #3182F6; }}
  .card .lbl {{ font-size: 13px; color: #6B7684; margin-top: 6px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }}
  th, td {{ border: 1px solid #E5E8EB; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #F2F4F6; font-weight: 600; }}
  .warn {{ color: #FF6B6B; font-weight: 600; }}
  .ok {{ color: #00C896; font-weight: 600; }}
  .meta {{ color: #6B7684; font-size: 13px; margin-bottom: 20px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 6px;
            background: #FFF4E5; color: #FF9900; font-size: 12px; margin-left: 8px; }}
</style>
</head>
<body>
<h1>카드 UI 데이터 감사 보고서</h1>
<p class="meta">대상: 전체 {total}건 · 작성일: {date.today()}</p>

<div class="summary">
  <div class="card"><div class="num">{len(amt['거대_당없음'])}</div><div class="lbl">⚠ 금액 의심 (100억+, "당" 표현 없음)</div></div>
  <div class="card"><div class="num">{len(amt['확인필요'])}</div><div class="lbl">금액 미상 ("확인 필요")</div></div>
  <div class="card"><div class="num">{len(per_iss['기간_과거'])}</div><div class="lbl">⚠ 신청기간 만료</div></div>
  <div class="card"><div class="num">{len(pur['너무_짧음']) + len(pur['관공서_잔존'])}</div><div class="lbl">목적문 잔존 이슈</div></div>
</div>

<h2>1. 금액 의심 사례 (총액→1인 한도 혼동 가능)</h2>
<p>100억원 이상 표시되지만 원문에 "업체당/기업당" 등 1인 기준 표현이 없는 케이스.
대부분 융자/이차보전 사업의 총 융자한도가 잘못 표시된 것으로 추정. 카드에서 사용자는
이 금액을 본인이 받을 수 있는 한도로 오해할 수 있음.</p>
<table>
<tr><th>ID</th><th>제목</th><th>표시 금액</th><th>sub</th></tr>
{rows_amt}
</table>
<p class="meta">표시 50건 / 총 {len(amt['거대_당없음'])}건</p>

<h2>2. 신청기간 만료 사례</h2>
<p>endDate가 오늘({date.today()}) 이전 — 카드에 D-음수가 표시되거나 잘못 보일 가능성.</p>
<table>
<tr><th>ID</th><th>제목</th><th>endDate</th><th>원문 period</th></tr>
{rows_period_past}
</table>
<p class="meta">표시 30건 / 총 {len(per_iss['기간_과거'])}건</p>

<h2>3. 목적문 잔존 이슈 (너무 짧음)</h2>
<table>
<tr><th>ID</th><th>제목</th><th>목적문</th></tr>
{rows_purpose_short}
</table>
<p class="meta">표시 20건 / 총 {len(pur['너무_짧음'])}건</p>

<h2>4. 매칭도 분포</h2>
<table>
<tr><th>구간</th><th>건수</th><th>비율</th></tr>
"""
    for k, v in match_bins.items():
        html += f"<tr><td>{k}</td><td>{v}</td><td>{v*100//total}%</td></tr>\n"
    html += f"""
</table>

<h2>5. 권장 후속 조치</h2>
<ul>
<li><strong>금액 의심 {len(amt['거대_당없음'])}건</strong>: LLM에 원문 + 현재 라벨 보여주고 "1개 기업이 실제 받는 한도" 재추출 → 또는 라벨에 "총사업비" 명시 또는 "공고 확인" 표기로 후퇴</li>
<li><strong>신청기간 만료 {len(per_iss['기간_과거'])}건</strong>: status를 "closed"로 표시하고 카드 정렬에서 후순위</li>
<li><strong>목적문 짧음 {len(pur['너무_짧음'])}건</strong>: LLM 재생성</li>
</ul>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"→ HTML 보고서: {OUT}")


def main():
    data = json.loads(DB.read_text(encoding="utf-8"))
    print(f"전체 {len(data)}건 감사 중...\n")

    amt = audit_amount(data)
    per_iss = audit_period(data)
    pur = audit_purpose(data)
    match_bins = audit_match(data)

    print(f"[금액] 거대(100억+) & '당' 없음: {len(amt['거대_당없음'])}건")
    print(f"[금액] 확인 필요: {len(amt['확인필요'])}건")
    print(f"[기간] 없음: {len(per_iss['기간_없음'])}건, 과거(만료): {len(per_iss['기간_과거'])}건")
    print(f"[목적] 짧음(<30자): {len(pur['너무_짧음'])}건, 김(>150자): {len(pur['너무_김'])}건")
    print(f"[목적] 법령 잔존: {len(pur['법령_잔존'])}건, 관공서 잔존: {len(pur['관공서_잔존'])}건")
    print(f"[매칭] {match_bins}")
    print()

    write_html(amt, per_iss, pur, match_bins, len(data))


if __name__ == "__main__":
    main()
