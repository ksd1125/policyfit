"""챗봇용 경량 지식DB 생성

knowledge-db.json(1.4MB) → outputs/chatbot-db.json(~700KB)
목적 태그(support.purposes)를 포함하여 챗봇이 4축 다축 필터를 할 수 있게 한다.
"""

import csv
import json
from pathlib import Path


def trunc(text, n):
    if not text:
        return text
    return text if len(text) <= n else text[:n] + '…'


def load_family_map(root):
    """ml-preallocation.csv → {record_id: (familyId, familySize)}"""
    path = root / 'outputs' / 'ml-preallocation.csv'
    fam = {}
    if not path.exists():
        return fam
    with path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            fam[row['record_id']] = (row.get('program_family_id', ''), int(row.get('program_family_size', '1') or 1))
    return fam


def main():
    root = Path.cwd()
    kdb = json.loads((root / 'outputs' / 'knowledge-db.json').read_text(encoding='utf-8'))
    fam_map = load_family_map(root)

    lite = []
    for r in kdb:
        support = r.get('support', {})
        eligibility = r.get('eligibility', {})
        application = r.get('application', {})
        contact = r.get('contact', {})
        quality = r.get('quality', {})

        amount = support.get('amount')
        amount_max = amount.get('max') if isinstance(amount, dict) else None

        rid = r.get('id', '')
        fam_id, fam_size = fam_map.get(rid, ('', 1))

        lite.append({
            'id': rid,
            'familyId': fam_id,
            'familySize': fam_size,
            'title': r.get('title', ''),
            'region': r.get('region', '공통'),
            'category': r.get('category', ''),
            'subcategory': r.get('subcategory', ''),
            'institution': r.get('institution', ''),
            'executor': r.get('executor', ''),
            'url': r.get('url', ''),
            'purposes': support.get('purposes', []),
            'summary': trunc(support.get('summary', ''), 160),
            'amount': amount_max,
            'rate': support.get('rate'),
            'type': support.get('type', ''),   # 융자/보증/보조금 구분
            'target': eligibility.get('target', ''),
            'exclusions': eligibility.get('exclusions', [])[:3],
            'period': trunc(application.get('period', ''), 40),
            'method': trunc(application.get('method', ''), 120),
            'documents': application.get('documents', [])[:5],
            'online': bool(application.get('onlineAvailable')),
            'contact': {
                'name': contact.get('name'),
                'phone': contact.get('phone'),
                'email': contact.get('email'),
            },
            'grade': quality.get('grade', 'moderate'),
        })

    out_path = root / 'outputs' / 'chatbot-db.json'
    text = json.dumps(lite, ensure_ascii=False)
    out_path.write_text(text, encoding='utf-8')

    # 요약
    from collections import Counter
    pc = Counter()
    for r in lite:
        for p in r['purposes']:
            pc[p] += 1
    print(json.dumps({
        'records': len(lite),
        'sizeKB': len(text) // 1024,
        'purposeTags': len(pc),
        'topPurposes': dict(pc.most_common(5)),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
