import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'build-knowledge-db.py'
SPEC = importlib.util.spec_from_file_location('build_knowledge_db', SCRIPT)
KB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KB)


class BuildKnowledgeDbTest(unittest.TestCase):
    def test_online_application_is_not_online_sales_purpose(self):
        self.assertNotIn('온라인판로', KB.extract_purposes('온라인 접수 및 이메일 제출'))
        self.assertIn('온라인판로', KB.extract_purposes('온라인 판로 입점 지원'))

    def test_rate_requires_financing_context(self):
        self.assertIsNone(KB.extract_rate('산재보험료 20% 감면 혜택'))
        self.assertIsNone(KB.extract_rate('부채비율 1,000% 이상 제외'))
        self.assertEqual('연 2.5% 이내', KB.extract_rate('대출금리 연 2.5% 이내'))

    def test_amount_selects_largest_explicit_limit(self):
        amount = KB.extract_amount('업체당 최대 200만원, 최대 500만원, 최대 300만원')
        self.assertEqual('최대 500만원', amount['max'])
        self.assertTrue(amount['raw'].startswith('최대 500만원'))

    def test_section_cleanup_stops_at_next_heading(self):
        lines = ['온라인 접수', '## 문의처', '담당자 02-1234-5678']
        self.assertEqual(['온라인 접수'], KB.clean_extracted_lines(lines, 8, 150))
        lines = ['온라인 접수', '## 사업신청 사이트', '온라인신청 바로가기']
        self.assertEqual(['온라인 접수'], KB.clean_extracted_lines(lines, 8, 150))

    def test_section_cleanup_discards_parenthesized_heading(self):
        lines = ['▢ (지원규모 및 내용)', '◦지원내용 : 세부 사업별 프로그램 지원']
        self.assertEqual([], KB.clean_extracted_lines(lines, 8, 200))

    def test_inline_exclusions_are_extracted(self):
        text = '▶ 지원제외 : 휴폐업, 국세 체납처분, 채무불이행자, 일반 안내'
        self.assertEqual(
            ['휴폐업', '국세 체납처분', '채무불이행자'],
            KB.extract_exclusions(text),
        )

    def test_exclusions_drop_neighboring_section_noise(self):
        text = '지원 제외\\n지원예산이 소진되면 마감\\n전문기술은 현장방문 후 결정\\n지원절차 : 접수→선정'
        self.assertEqual([], KB.extract_exclusions(text))

    def test_website_discards_navigation_tail(self):
        contact = KB.extract_contact('홈페이지 www.btp.or.kr→공고·공지→사업공고', '')
        self.assertEqual('www.btp.or.kr', contact['website'])


if __name__ == '__main__':
    unittest.main()
