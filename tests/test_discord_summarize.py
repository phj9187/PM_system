import io
import json
import unittest
import zipfile

from integrations.discord.summarize import build_docx, discord_messages, summarize
from tests.test_discord_recognize import BATCH, ITEMS, fake

RESULT = {
    'title': '발표 준비 회의', 'overview': '발표 자료 준비 일정을 논의했다.',
    'topics': [{'topic': '일정', 'summary': '금요일까지 초안', 'evidence_message_ids': ['m1']}],
    'decisions': [{'decision': '금요일까지 초안 작성', 'evidence_message_ids': ['m1']}],
    'goals': [{'title': '발표 자료 초안 완성', 'description': '다음 주 발표용', 'due': '2026-11-27',
               'confidence': 0.9, 'evidence_message_ids': ['m1']},
              {'title': '근거 없는 목표', 'confidence': 0.9, 'evidence_message_ids': ['zz']},
              {'title': '1차 발표 준비', 'confidence': 0.9, 'evidence_message_ids': ['m1']}],
    'tasks': [{'title': '자료 수집', 'owner_hint': '가상팀원B', 'confidence': 0.8, 'evidence_message_ids': ['m2']}],
    'open_questions': ['발표 장소'],
    'conflicts': [{'kind': 'timeline', 'summary': '대화는 금요일 초안, 앱 목표 기한은 12월 5일',
                   'item_ids': ['g1', 'nope'], 'evidence_message_ids': ['m1']},
                  {'kind': 'weird', 'summary': '근거 없는 충돌', 'evidence_message_ids': ['zz']}],
}


class SummarizeTests(unittest.TestCase):
    def test_summary_goals_are_validated_proposals(self):
        out = summarize(BATCH, ITEMS, api_key='k', transport=fake(RESULT))
        self.assertEqual([g['title'] for g in out['goals']], ['발표 자료 초안 완성'])
        g = out['goals'][0]
        self.assertEqual(g['status'], 'proposed')
        self.assertEqual(g['fields']['description'], '다음 주 발표용')
        self.assertEqual(len(out['tasks']), 1)
        self.assertEqual(out['decisions'][0]['evidence'][0]['message_id'], 'm1')

    def test_docx_is_valid_word_package(self):
        out = summarize(BATCH, ITEMS, api_key='k', transport=fake(RESULT))
        data = build_docx(out, '#일반')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('word/document.xml', z.namelist())
            doc = z.read('word/document.xml').decode('utf-8')
        self.assertIn('발표 자료 초안 완성', doc)
        self.assertIn('추천 목표', doc)

    def test_discord_messages_fit_limit(self):
        out = summarize(BATCH, ITEMS, api_key='k', transport=fake(RESULT))
        out['overview'] = '가' * 5000
        msgs = discord_messages(out)
        self.assertTrue(all(len(m) <= 1900 for m in msgs))
        self.assertIn('추천 목표', ''.join(msgs))

    def test_conflicts_need_evidence_and_show_as_needs_review(self):
        out = summarize(BATCH, ITEMS, api_key='k', transport=fake(RESULT))
        self.assertEqual(len(out['conflicts']), 1)
        c = out['conflicts'][0]
        self.assertEqual((c['kind'], c['status'], c['item_ids']), ('timeline', 'needs_review', ['g1']))
        self.assertIn('확인 필요', ''.join(discord_messages(out)))
        with zipfile.ZipFile(io.BytesIO(build_docx(out))) as z:
            self.assertIn('확인 필요', z.read('word/document.xml').decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
