"""공고 자유 추출용 섹션 DB 생성

각 공고의 detail.md + 첨부 MD를 섹션 맵으로 파싱하여
챗봇이 '평가 기준?', '우대 대상?' 같은 자유 질문에 원문 근거로 답할 수 있게 한다.

출력: outputs/chatbot-sections.json
  { noticeId: { sections: {"섹션명": "텍스트", ...}, fullText: "정제·캡" } }
"""

import json
import re
from pathlib import Path

RUN_ID = '20260601-224706'
FULLTEXT_CAP = 2000
SECTION_CAP = 600

# 노이즈 라인 제거용
TAG_RE = re.compile(r'<[^<>]*>')
BULLET_RE = re.compile(r'^[\s\-·○◦◎▶☞▪□▢■※*]+')
MULTISPACE_RE = re.compile(r'[ \t]{2,}')

# 섹션 헤딩 후보: 마크다운 헤딩 또는 "■ 평가기준", "○ 지원규모", "1. 신청자격", 굵은 라벨
HEADING_RE = re.compile(
    r'^(?:#{1,4}\s*)?'
    r'(?:[■◆▶○◎※]\s*|\d+[.)]\s*|[가-힣]\s*[.)]\s*)?'
    r'(사업\s*개요|사업\s*목적|지원\s*개요|지원\s*내용|지원\s*규모|지원\s*대상|지원\s*조건|지원\s*기준|'
    r'신청\s*자격|신청\s*대상|신청\s*기간|신청\s*방법|신청\s*절차|접수\s*방법|접수\s*기간|'
    r'제출\s*서류|구비\s*서류|필요\s*서류|선정\s*방법|선정\s*기준|평가\s*기준|평가\s*방법|심사\s*기준|'
    r'우대\s*사항|가점|우대|지원\s*제외|제외\s*대상|참여\s*제한|제한\s*사항|'
    r'유의\s*사항|기타\s*사항|문의\s*처|문의|사후\s*관리|정산|협약|추진\s*일정|기대\s*효과)'
    r'\s*[:：]?\s*(.*)$'
)


def clean_line(raw):
    line = TAG_RE.sub(' ', raw)
    line = BULLET_RE.sub('', line)
    line = MULTISPACE_RE.sub(' ', line).strip(' <>\t')
    return line


def normalize_section_name(name):
    n = re.sub(r'\s+', '', name)
    aliases = {
        '사업개요': '사업 개요', '사업목적': '사업 개요', '지원개요': '사업 개요',
        '지원내용': '지원 내용', '지원규모': '지원 규모', '지원조건': '지원 조건',
        '지원기준': '지원 조건', '지원대상': '신청 자격', '신청자격': '신청 자격',
        '신청대상': '신청 자격', '신청기간': '신청 기간', '접수기간': '신청 기간',
        '신청방법': '신청 방법', '신청절차': '신청 방법', '접수방법': '신청 방법',
        '제출서류': '제출 서류', '구비서류': '제출 서류', '필요서류': '제출 서류',
        '선정방법': '평가·선정', '선정기준': '평가·선정', '평가기준': '평가·선정',
        '평가방법': '평가·선정', '심사기준': '평가·선정',
        '우대사항': '우대·가점', '가점': '우대·가점', '우대': '우대·가점',
        '지원제외': '지원 제외', '제외대상': '지원 제외', '참여제한': '지원 제외', '제한사항': '지원 제외',
        '유의사항': '유의 사항', '기타사항': '유의 사항',
        '문의처': '문의처', '문의': '문의처',
        '사후관리': '사후관리·정산', '정산': '사후관리·정산', '협약': '사후관리·정산',
        '추진일정': '추진 일정', '기대효과': '기대 효과',
    }
    return aliases.get(n, name.strip())


def parse_sections(text):
    """텍스트를 섹션명→내용 맵으로 파싱"""
    lines = text.split('\n')
    sections = {}
    cur_name = None
    cur_buf = []

    def flush():
        if cur_name and cur_buf:
            body = ' '.join(l for l in (clean_line(x) for x in cur_buf) if len(l) >= 2)
            body = MULTISPACE_RE.sub(' ', body).strip()
            if len(body) >= 5:
                # 같은 섹션 여러 번 → 더 긴 것 유지
                if cur_name not in sections or len(body) > len(sections[cur_name]):
                    sections[cur_name] = body[:SECTION_CAP]

    for raw in lines:
        m = HEADING_RE.match(raw.strip())
        if m:
            flush()
            cur_name = normalize_section_name(m.group(1))
            cur_buf = []
            tail = m.group(2).strip()
            if tail:
                cur_buf.append(tail)
        elif cur_name:
            cur_buf.append(raw)
    flush()
    return sections


def build_fulltext(text):
    cleaned = []
    for raw in text.split('\n'):
        line = clean_line(raw)
        if len(line) >= 2:
            cleaned.append(line)
    full = ' '.join(cleaned)
    full = MULTISPACE_RE.sub(' ', full).strip()
    return full[:FULLTEXT_CAP]


def main():
    root = Path.cwd()
    md_dir = root / 'raw' / 'markdown' / RUN_ID
    # 대상 ID: chatbot-db.json 기준
    db = json.loads((root / 'outputs' / 'chatbot-db.json').read_text(encoding='utf-8'))
    ids = [n['id'] for n in db]

    out = {}
    n_sections = 0
    for nid in ids:
        nd = md_dir / nid
        if not nd.exists():
            continue
        parts = []
        detail = nd / 'detail.md'
        if detail.exists():
            parts.append(detail.read_text(encoding='utf-8', errors='replace'))
        for f in sorted(nd.iterdir()):
            if f.is_file() and f.name != 'detail.md' and f.suffix == '.md':
                parts.append(f.read_text(encoding='utf-8', errors='replace'))
        text = '\n'.join(parts)
        if not text.strip():
            continue
        sections = parse_sections(text)
        n_sections += len(sections)
        out[nid] = {
            'sections': sections,
            'fullText': build_fulltext(text),
        }

    out_path = root / 'outputs' / 'chatbot-sections.json'
    payload = json.dumps(out, ensure_ascii=False)
    out_path.write_text(payload, encoding='utf-8')
    print(json.dumps({
        'notices': len(out),
        'sizeKB': len(payload) // 1024,
        'avgSections': round(n_sections / max(1, len(out)), 1),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
