"""정책공고 지식DB 구축 스크립트

입력:
  - outputs/normalized-notices-20260601-224706.json (정규화 데이터)
  - raw/markdown/20260601-224706/{noticeId}/detail.md (상세 HTML)
  - raw/markdown/20260601-224706/{noticeId}/*.md (첨부 MD)

출력:
  - outputs/knowledge-db.json (구조화된 지식DB)
  - outputs/knowledge-db-report.html (추출 요약 리포트)

스펙: outputs/knowledge-db-spec.html 참조
"""

import json
import os
import re
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime
from html import escape


# ── 용도 태그 사전 ──
PURPOSE_TAGS = {
    '운전자금': ['운전자금', '운영자금', '경영안정자금', '유동자금', '경영자금'],
    '시설개보수': ['시설', '인테리어', '설비', '개보수', '리모델링', '점포환경개선', '시설개선', '시설자금', '시설투자'],
    '인건비': ['인건비', '인력', '급여', '임금', '4대보험', '고용'],
    '재료비': ['재료비', '원자재', '원부자재'],
    '마케팅비': ['마케팅', '홍보', '광고', '판촉', '전시', '박람회'],
    '사업화': ['사업화', '시제품', '프로토타입', 'R&D', '연구개발', '기술개발'],
    '교육훈련': ['교육', '훈련', '연수', '역량강화', '아카데미'],
    '컨설팅': ['컨설팅', '진단', '멘토링', '자문', '코칭'],
    '디자인·브랜딩': ['디자인', '브랜드', '패키징', '포장', 'BI', 'CI'],
    '인증취득': ['인증', 'ISO', 'HACCP', '규격', '특허', '지식재산'],
    '수출': ['수출', '해외진출', '바이어', '해외전시'],
    '온라인판로': ['온라인 판로', '온라인 판매', '온라인몰', '쇼핑몰', '입점', '라이브커머스', '전자상거래'],
    '이자보전': ['이자', '이차보전', '금리', '대출이자', '이자지원'],
    '보증지원': ['보증', '신용보증', '기술보증', '보증서'],
}

# ── "불가" 문맥 감지: 이 키워드가 부정 문맥에 있으면 제외 ──
NEGATIVE_CONTEXT = re.compile(r'(불가|불포함|제외|사용할\s*수\s*없|지원\s*불가|해당\s*없)', re.IGNORECASE)
SECTION_BOUNDARY = re.compile(
    r'^(?:#{1,6}\s*)?(?:\d+[.)]?\s*)?'
    r'(?:사업\s*개요|지원\s*내용|지원\s*대상|지원\s*규모(?:\s*및\s*내용)?|신청\s*기간|'
    r'신청\s*방법|신청\s*절차|접수\s*절차|제출\s*서류|구비\s*서류|'
    r'필요\s*서류|문의처|유의\s*사항|기타\s*사항|선정\s*방법|모집\s*대상|'
    r'신청\s*요건|지원\s*기준|접수처|사업\s*신청\s*사이트|사업\s*신청\s*방법)\s*(?::.*)?$',
    re.IGNORECASE,
)
RATE_CONTEXT = re.compile(
    r'(?:대출\s*)?(?:금리|이율|이자율|이차보전(?:율|률)?|금리\s*지원(?:율|률)?)',
    re.IGNORECASE,
)
EXCLUSION_SIGNAL = re.compile(
    r'(?:불가|제외|제한|체납|휴[·ㆍ․\s-]*폐업|부도|채무불이행|파산|'
    r'자본잠식|환수|허위|중복|연체|보증사고|행정처분|영업정지|'
    r'의무\s*사항.*불이행|사치|향락|도박|유흥|업종)',
    re.IGNORECASE,
)


def load_all_text(md_dir, notice_id):
    """공고의 detail.md + 모든 첨부 md를 합친 텍스트 반환"""
    nd = md_dir / notice_id
    if not nd.exists():
        return '', ''
    detail = ''
    detail_path = nd / 'detail.md'
    if detail_path.exists():
        detail = detail_path.read_text(encoding='utf-8', errors='replace')
    attach_parts = []
    for f in sorted(nd.iterdir()):
        if f.is_file() and f.name != 'detail.md' and f.suffix == '.md':
            attach_parts.append(f.read_text(encoding='utf-8', errors='replace'))
    return detail, '\n\n'.join(attach_parts)


def extract_purposes(full_text):
    """용도 태그 추출 (부정 문맥 제외)"""
    purposes = []
    lower = full_text.lower()
    for tag, keywords in PURPOSE_TAGS.items():
        for kw in keywords:
            idx = lower.find(kw.lower())
            if idx < 0:
                continue
            # 전후 50자에서 부정 문맥 체크
            context = full_text[max(0, idx-50):idx+len(kw)+50]
            if NEGATIVE_CONTEXT.search(context):
                continue
            purposes.append(tag)
            break
    return list(dict.fromkeys(purposes))  # dedup, 순서 유지


def extract_amount(full_text):
    """지원 금액 추출. 보수적 패턴 — 업체당/최대 우선, 사업 총예산 제외.

    원칙: 신청자 1인(1사) 기준 한도를 우선. "총사업비/지원예산/국비" 컨텍스트
    부근 숫자는 사업 전체 규모이므로 fallback에서도 제외.
    """
    # 단위 사이 공백 허용 (PDF 추출 텍스트 대응)
    UNIT = r'(억\s*원|천\s*만\s*원|백\s*만\s*원|만\s*원)'
    # 1인/1사 기준 키워드 — "건/회/차" 같은 일반어는 제외 (부속 비용 오인 위험)
    PER = r'(?:업체|기업|사업자|점포|업소|개사|개인|학생|농가|어가|투자\s*건|사업)'
    # 우선순위: 패턴 1("당" 명시 = 1인/1사 기준)이 가장 신뢰 — 있으면 단독 사용
    # 패턴 2/3("한도/최대/이내")은 1인 한도일 수도 총액일 수도 있어 차순위
    # 패턴 4는 최후 fallback (총예산 컨텍스트 제외)
    per_pattern = r'(?:' + PER + r')\s*당\s*(?:총|최대|한도|상한|약)?\s*(\d[\d,.]*)\s*' + UNIT
    secondary_patterns = [
        r'(?:최대|한도|상한)\s*(\d[\d,.]*)\s*' + UNIT,
        r'(\d[\d,.]*)\s*' + UNIT + r'\s*(?:이내|한도|이하)',
    ]
    fallback_pattern = r'(\d[\d,.]*)\s*' + UNIT
    # 총예산 신호 — fallback에서 이 컨텍스트의 숫자는 거름
    TOTAL_BUDGET_CTX = re.compile(
        r'(?:지원예산|총\s*예산|총\s*사업비|사업\s*예산|총\s*규모|총\s*지원\s*규모|'
        r'국비\s*총|총\s*국비|전체\s*예산|연간\s*예산|올해\s*예산|예산\s*총액)'
    )

    amounts = []
    # 1순위: "당" 패턴(1인/1사 기준) — 있으면 단독 사용 (다른 패턴 무시)
    for m in re.finditer(per_pattern, full_text):
        raw = m.group(0).strip()
        raw_norm = re.sub(r'\s+', '', raw)
        if raw_norm not in [re.sub(r'\s+', '', a) for a in amounts]:
            amounts.append(raw)
    # 2순위: "한도/최대/이내" 패턴 — "당" 패턴 매칭이 없을 때만
    if not amounts:
        for pat in secondary_patterns:
            for m in re.finditer(pat, full_text):
                # 총예산 컨텍스트 가까이는 거름
                before = full_text[max(0, m.start() - 60):m.start()]
                if TOTAL_BUDGET_CTX.search(before):
                    continue
                raw = m.group(0).strip()
                raw_norm = re.sub(r'\s+', '', raw)
                if raw_norm not in [re.sub(r'\s+', '', a) for a in amounts]:
                    amounts.append(raw)
    # 3순위: fallback (단순 숫자+단위) — 위 모든 패턴 매칭 없을 때만
    if not amounts:
        for m in re.finditer(fallback_pattern, full_text):
            before = full_text[max(0, m.start() - 60):m.start()]
            if TOTAL_BUDGET_CTX.search(before):
                continue
            raw = m.group(0).strip()
            raw_norm = re.sub(r'\s+', '', raw)
            if raw_norm not in [re.sub(r'\s+', '', a) for a in amounts]:
                amounts.append(raw)
    if not amounts:
        return None
    unique = list(dict.fromkeys(amounts))
    unit_values = {'억원': 100_000_000, '천만원': 10_000_000, '백만원': 1_000_000, '만원': 10_000}

    def amount_value(raw):
        rn = re.sub(r'\s+', '', raw)
        m = re.search(r'(\d[\d,.]*)(억원|천만원|백만원|만원)', rn)
        if not m:
            return 0
        try:
            num = float(m.group(1).replace(',', ''))
            return int(num * unit_values[m.group(2)])
        except (ValueError, KeyError):
            return 0

    ranked = sorted(unique, key=amount_value, reverse=True)
    return {'max': ranked[0], 'raw': '; '.join(ranked[:3])}


def extract_rate(full_text):
    """금리/이율 추출"""
    pattern = re.compile(r'(?<![\d,.])(?:연\s*)?(\d{1,3}(?:\.\d+)?)\s*%\s*(?:이내|고정|변동)?')
    for m in pattern.finditer(full_text):
        value = float(m.group(1))
        if not 0 < value <= 30:
            continue
        context = full_text[max(0, m.start() - 60):m.end() + 60]
        if RATE_CONTEXT.search(context):
            return m.group(0).strip()
    return None


def clean_extracted_lines(lines, limit, max_length):
    """목록 섹션에서 제목, 표 잔해, 중복을 제거"""
    cleaned = []
    for raw in lines:
        line = re.sub(r'<[^<>]*>', ' ', raw)
        line = re.sub(r'^[\s\-·○◦◎▶☞▪□▢■※*]+', '', line)
        line = re.sub(r'^\d+[.)]\s*', '', line)
        line = re.sub(r'\s+', ' ', line).strip(' <>')
        if not line:
            continue
        if raw.lstrip().startswith('#'):
            if cleaned:
                break
            continue
        line = re.sub(r'^\(([^)]+)\)$', r'\1', line)
        if SECTION_BOUNDARY.match(line):
            if cleaned:
                break
            continue
        if len(line) < 2 or len(line) >= max_length:
            continue
        if line not in cleaned:
            cleaned.append(line)
        if len(cleaned) >= limit:
            break
    return cleaned


def extract_exclusions(full_text):
    """제외 대상 추출"""
    exclusions = []
    # 변환된 표에서는 "지원제외 : 항목, 항목"이 한 줄에 남기도 한다.
    inline_pattern = re.compile(
        r'(?:지원\s*제외|제외\s*대상|참여\s*제한|지원\s*불가)\s*[:：]\s*([^\n]{5,500})',
        re.IGNORECASE,
    )
    for m in inline_pattern.finditer(full_text):
        parts = re.split(r'[,;]', m.group(1))
        exclusions.extend(clean_extracted_lines(parts, limit=8, max_length=200))

    # 제외 섹션 찾기
    patterns = [
        r'(?:지원\s*제외|제외\s*대상|참여\s*제한|지원\s*불가)[^\n]*\n((?:[\s\-·○◎▶☞]*[^\n]+\n?){1,10})',
        r'(?:다음.*해당.*(?:제외|불가|제한))[^\n]*\n((?:[\s\-·○◎▶☞]*[^\n]+\n?){1,10})',
    ]
    for pat in patterns:
        for m in re.finditer(pat, full_text, re.MULTILINE):
            exclusions.extend(clean_extracted_lines(m.group(1).splitlines(), limit=8, max_length=200))
    return [line for line in dict.fromkeys(exclusions) if EXCLUSION_SIGNAL.search(line)][:8]


def extract_documents(full_text):
    """필요 서류 추출"""
    docs = []
    patterns = [
        r'(?:제출\s*서류|구비\s*서류|필요\s*서류)[^\n]*\n((?:[\s\-·○◎▶☞\d.]+[^\n]+\n?){1,15})',
    ]
    for pat in patterns:
        for m in re.finditer(pat, full_text, re.MULTILINE):
            docs.extend(clean_extracted_lines(m.group(1).splitlines(), limit=10, max_length=150))
    return list(dict.fromkeys(docs))[:10]


def extract_steps(full_text):
    """신청 절차 추출"""
    steps = []
    patterns = [
        r'(?:신청\s*절차|접수\s*절차|신청\s*방법)[^\n]*\n((?:[\s\-·○◎▶☞\d.→]+[^\n]+\n?){1,10})',
    ]
    for pat in patterns:
        for m in re.finditer(pat, full_text, re.MULTILINE):
            steps.extend(clean_extracted_lines(m.group(1).splitlines(), limit=8, max_length=150))
    return list(dict.fromkeys(steps))[:8]


def extract_contact(full_text, existing):
    """연락처 구조화"""
    contact = {'name': None, 'phone': None, 'email': None, 'website': None}
    if existing:
        contact['name'] = existing
    # 전화번호
    phones = re.findall(r'(\d{2,4}[-)\s]?\d{3,4}[-\s]?\d{4})', full_text)
    if phones:
        contact['phone'] = phones[0]
    # 이메일
    emails = re.findall(r'[\w.\-]+@[\w.\-]+\.\w+', full_text)
    if emails:
        contact['email'] = emails[0]
    # 웹사이트
    urls = re.findall(r'(?:www\.\S+|https?://\S+)', full_text)
    if urls:
        contact['website'] = re.split(r'[<>()\[\]{}"\'→※,\s]', urls[0])[0].rstrip('.')
    return contact


def extract_summary(full_text, existing_content):
    """1~2줄 요약 생성"""
    text = existing_content or full_text
    # HTML 태그 제거
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&\w+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # 법률 제거
    text = re.sub(r'[「『][^」』]*[」』]', '', text)
    text = re.sub(r'제\d+조[^\s,)]*', '', text)
    text = re.sub(r'다음과\s*같이\s*(공고|안내|시행)\S*', '', text)
    # ☞ 이후 핵심
    parts = text.split('☞')
    if len(parts) > 1:
        core = [p.strip() for p in parts[1:3] if len(p.strip()) > 10]
        if core:
            return ' / '.join(core)[:200]
    # 첫 문장
    sentences = text.split('.')
    first = sentences[0].strip() if sentences else text[:200]
    return first[:200] if len(first) > 5 else text[:200]


def determine_quality(record):
    """정보 품질 등급"""
    score = 0
    if len(record['support']['purposes']) >= 2:
        score += 2
    elif len(record['support']['purposes']) >= 1:
        score += 1
    if record['support']['amount']:
        score += 1
    if len(record['eligibility']['exclusions']) >= 1:
        score += 1
    if len(record['application']['documents']) >= 1:
        score += 1
    if record['contact']['phone'] or record['contact']['email']:
        score += 1

    if score >= 4:
        return 'detailed'
    elif score >= 2:
        return 'moderate'
    return 'vague'


def build_record(notice, detail_md, attach_md):
    """공고 1건의 지식 레코드 생성"""
    full_text = (detail_md + '\n\n' + attach_md).strip()
    existing = notice.get('fields', {})

    # 지역 추출
    region_match = re.match(r'^\[([^\]]+)\]', notice.get('title', ''))
    region = region_match.group(1) if region_match else '공통'

    # 지원 정보
    content_val = existing.get('지원내용', {}).get('value', '')
    # API 지원내용은 지원 목적을 압축한 큐레이션 텍스트다. 첨부 전체를
    # 훑으면 신청방법의 "온라인" 같은 단어가 용도 태그로 오염된다.
    purposes = extract_purposes(content_val or full_text)
    amount = extract_amount(full_text)
    rate = extract_rate(full_text)

    # 자격/제외
    target_val = existing.get('지원대상', {}).get('value', '')
    exclusions = extract_exclusions(full_text)
    if not exclusions and existing.get('제외조건', {}).get('value'):
        # 기존 제외조건 필드에서 추출
        exc_text = existing['제외조건']['value']
        exclusions = [
            line for line in clean_extracted_lines(exc_text.splitlines(), limit=8, max_length=200)
            if EXCLUSION_SIGNAL.search(line)
        ]

    # 신청
    period_val = existing.get('신청기간', {}).get('value', '')
    method_val = existing.get('신청방법', {}).get('value', '')
    steps = extract_steps(full_text)
    documents = extract_documents(full_text)
    if not documents and existing.get('제출서류', {}).get('value'):
        doc_text = existing['제출서류']['value']
        documents = clean_extracted_lines(doc_text.splitlines(), limit=10, max_length=150)

    online = bool(re.search(r'온라인|앱|홈페이지|이메일', method_val))

    # 기간 유형
    period_type = 'unknown'
    if re.search(r'예산\s*소진', period_val):
        period_type = 'budget_exhausted'
    elif re.search(r'상시', period_val):
        period_type = 'always_open'
    elif re.search(r'선착순', period_val):
        period_type = 'first_come'
    elif re.search(r'\d{4}', period_val):
        period_type = 'date_range'

    # 연락처
    contact_val = existing.get('문의처', {}).get('value', '')
    contact = extract_contact(full_text, contact_val)

    # 요약
    summary = extract_summary(full_text, content_val)

    record = {
        'id': notice.get('id', ''),
        'title': notice.get('title', ''),
        'region': region,
        'category': notice.get('category', ''),
        'subcategory': notice.get('subcategory', ''),
        'institution': notice.get('institution', ''),
        'executor': notice.get('executor', ''),
        'registeredAt': notice.get('registeredAt', ''),
        'url': notice.get('url', ''),
        'support': {
            'summary': summary,
            'type': notice.get('subcategory', ''),
            'purposes': purposes,
            'amount': amount,
            'rate': rate,
            'duration': None,
        },
        'eligibility': {
            'target': target_val,
            'conditions': [],
            'exclusions': exclusions,
            'industryRestrictions': [],
        },
        'application': {
            'period': period_val,
            'periodType': period_type,
            'method': method_val,
            'steps': steps,
            'documents': documents,
            'onlineAvailable': online,
        },
        'contact': contact,
        'quality': {
            'grade': 'vague',
            'sources': [],
            'attachmentCount': 0,
            'contentLength': len(full_text),
            'purposeConfidence': 'low',
        },
    }

    # 소스 태그
    sources = ['api']
    if detail_md:
        sources.append('html')
    if attach_md:
        sources.append('attachment')
    record['quality']['sources'] = sources
    record['quality']['attachmentCount'] = attach_md.count('\n\n---\n\n') + (1 if attach_md else 0)

    # 품질 등급
    record['quality']['grade'] = determine_quality(record)
    record['quality']['purposeConfidence'] = (
        'high' if len(purposes) >= 2 else 'medium' if len(purposes) >= 1 else 'low'
    )

    return record


def build_report_html(records, stats):
    """HTML 요약 리포트 생성"""
    grades = Counter(r['quality']['grade'] for r in records)
    purpose_coverage = sum(1 for r in records if r['support']['purposes'])
    amount_coverage = sum(1 for r in records if r['support']['amount'])
    exclusion_coverage = sum(1 for r in records if r['eligibility']['exclusions'])
    doc_coverage = sum(1 for r in records if r['application']['documents'])
    rate_coverage = sum(1 for r in records if r['support']['rate'])
    online_count = sum(1 for r in records if r['application']['onlineAvailable'])

    purpose_dist = Counter()
    for r in records:
        for p in r['support']['purposes']:
            purpose_dist[p] += 1

    # 샘플 레코드
    detailed_samples = [r for r in records if r['quality']['grade'] == 'detailed'][:3]
    multiple_amounts = sum(
        1 for r in records
        if r['support']['amount'] and ';' in r['support']['amount']['raw']
    )
    high_purpose_count = sum(1 for r in records if len(r['support']['purposes']) >= 6)
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M')

    total = len(records)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generated-at" content="{generated_at}">
<title>지식DB 구축 리포트</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Pretendard Variable',sans-serif;background:#F5F2EC;color:#1A1916;line-height:1.7}}
.w{{max-width:900px;margin:0 auto;padding:32px 24px}}
h1{{font-size:22px;color:#2D4540;margin-bottom:16px}}
h2{{font-size:17px;color:#2D4540;margin:28px 0 10px;border-bottom:2px solid #E8E3D7;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{border:1px solid #E8E3D7;padding:7px 10px;text-align:left}}
th{{background:#E8F0ED;font-weight:600}}
.bar{{height:18px;border-radius:4px;display:inline-block;vertical-align:middle}}
.b-h{{background:#16a34a}}.b-m{{background:#ca8a04}}.b-l{{background:#dc2626}}
pre{{background:#f4f0e6;padding:12px;border-radius:8px;font-size:11px;overflow-x:auto;margin:8px 0}}
.s{{display:inline-block;background:#fff;border:1px solid #E8E3D7;border-radius:8px;padding:10px 14px;margin:3px;text-align:center}}
.s .n{{font-size:22px;font-weight:700;color:#2D4540}}.s .l{{font-size:11px;color:#6F6B62}}
.note{{background:#fffdf8;border-left:4px solid #ca8a04;padding:12px 14px;margin:12px 0;border-radius:0 8px 8px 0;font-size:13px}}
.toc{{font-size:13px;margin:14px 0 18px;padding-left:18px}}.toc a{{color:#2D4540}}
@media print{{body{{background:#fff}}.w{{max-width:none;padding:0}}}}
</style></head><body><div class="w">
<h1>지식DB 구축 리포트</h1>
<p style="color:#6F6B62">총 {total}건 처리 · 생성 {generated_at}</p>
<ol class="toc">
<li><a href="#coverage">커버리지</a></li>
<li><a href="#quality">정확도 점검</a></li>
<li><a href="#purposes">용도 태그 분포</a></li>
<li><a href="#samples">상세 등급 샘플</a></li>
</ol>

<div style="display:flex;flex-wrap:wrap;gap:6px;margin:16px 0">
<div class="s"><div class="n">{grades.get('detailed',0)}</div><div class="l">상세</div></div>
<div class="s"><div class="n">{grades.get('moderate',0)}</div><div class="l">보통</div></div>
<div class="s"><div class="n">{grades.get('vague',0)}</div><div class="l">모호</div></div>
<div class="s"><div class="n">{purpose_coverage}</div><div class="l">용도 추출</div></div>
<div class="s"><div class="n">{amount_coverage}</div><div class="l">금액 추출</div></div>
<div class="s"><div class="n">{rate_coverage}</div><div class="l">금리 추출</div></div>
<div class="s"><div class="n">{exclusion_coverage}</div><div class="l">제외조건</div></div>
<div class="s"><div class="n">{doc_coverage}</div><div class="l">서류 추출</div></div>
<div class="s"><div class="n">{online_count}</div><div class="l">온라인 접수</div></div>
</div>

<h2 id="coverage">커버리지</h2>
<div class="note">커버리지는 값이 채워진 비율이며 정확도와 같지 않습니다. 금액 후보가 여러 개인 공고와 목적 태그가 많은 공고는 후속 표본 검토가 필요합니다.</div>
<table>
<tr><th>필드</th><th>추출 건수</th><th>비율</th></tr>
<tr><td>지원 용도(purposes)</td><td>{purpose_coverage}</td><td>{purpose_coverage/total*100:.1f}%</td></tr>
<tr><td>지원 금액(amount)</td><td>{amount_coverage}</td><td>{amount_coverage/total*100:.1f}%</td></tr>
<tr><td>금리(rate)</td><td>{rate_coverage}</td><td>{rate_coverage/total*100:.1f}%</td></tr>
<tr><td>제외 조건(exclusions)</td><td>{exclusion_coverage}</td><td>{exclusion_coverage/total*100:.1f}%</td></tr>
<tr><td>제출 서류(documents)</td><td>{doc_coverage}</td><td>{doc_coverage/total*100:.1f}%</td></tr>
<tr><td>온라인 접수 가능</td><td>{online_count}</td><td>{online_count/total*100:.1f}%</td></tr>
</table>

<h2 id="quality">정확도 점검</h2>
<table>
<tr><th>점검 항목</th><th>건수</th><th>해석</th></tr>
<tr><td>금액 후보 2개 이상</td><td>{multiple_amounts}</td><td>최대값 자동 선택. 총사업비와 기업별 한도 혼합 여부 표본 검토 필요</td></tr>
<tr><td>목적 태그 6개 이상</td><td>{high_purpose_count}</td><td>복합 지원사업 또는 과다 태깅 가능성 검토</td></tr>
</table>
<div class="note">1차 보정 적용: 목적 태그는 API 지원내용 중심으로 판정하고, 금리는 금리·이율·이차보전 문맥의 0~30% 값만 허용하며, 목록 추출은 다음 섹션 제목에서 중단합니다.</div>

<h2 id="purposes">용도 태그 분포</h2>
<table>
<tr><th>용도</th><th>건수</th></tr>
{''.join(f"<tr><td>{escape(p)}</td><td>{c}</td></tr>" for p, c in purpose_dist.most_common())}
</table>

<h2 id="samples">상세 등급 샘플</h2>
{''.join(f"<pre>{escape(json.dumps(s, ensure_ascii=False, indent=2)[:800])}</pre>" for s in detailed_samples)}

</div></body></html>"""


def main():
    project_root = Path.cwd()
    # 환경변수로 runId/출력 경로 override 가능 (격리 테스트·재사용)
    run_id = os.environ.get('E2E_RUN_ID', '20260601-224706')
    knowledge_out = os.environ.get('E2E_KNOWLEDGE_OUT', 'knowledge-db.json')
    normalized_path = project_root / 'outputs' / f'normalized-notices-{run_id}.json'
    md_dir = project_root / 'raw' / 'markdown' / run_id

    notices = json.loads(normalized_path.read_text(encoding='utf-8'))
    print(f'Loaded {len(notices)} notices (runId={run_id})')

    records = []
    for i, notice in enumerate(notices):
        detail_md, attach_md = load_all_text(md_dir, notice.get('id', ''))
        record = build_record(notice, detail_md, attach_md)
        records.append(record)
        if (i + 1) % 100 == 0:
            print(f'  Processed: {i + 1}/{len(notices)}')

    print(f'  Processed: {len(notices)}/{len(notices)}')

    # 저장
    outputs = project_root / 'outputs'
    db_path = outputs / knowledge_out
    db_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved: {db_path.name} ({db_path.stat().st_size // 1024}KB)')

    # 리포트
    report_path = outputs / 'knowledge-db-report.html'
    report_path.write_text(build_report_html(records, {}), encoding='utf-8')
    print(f'Saved: {report_path.name}')

    # 요약 출력
    grades = Counter(r['quality']['grade'] for r in records)
    print(json.dumps({
        'total': len(records),
        'detailed': grades.get('detailed', 0),
        'moderate': grades.get('moderate', 0),
        'vague': grades.get('vague', 0),
    }, indent=2))


if __name__ == '__main__':
    main()
