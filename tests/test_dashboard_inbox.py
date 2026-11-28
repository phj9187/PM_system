import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from dashboard.inbox import Inbox, to_item
from dashboard.server import Projects, start_server

DUE = (date.today() + timedelta(days=5)).isoformat()


def candidate(cid, kind, title, **fields):
    return {'id': cid, 'kind': kind, 'status': 'proposed', 'title': title,
            'fields': dict({'due': DUE, 'owner_hint': '', 'parent_goal_id': '', 'confidence': 0.9,
                            'description': ''}, **fields),
            'evidence': [{'message_id': 'm1', 'url': 'https://discord.com/channels/1/2/m1'}],
            'created_by': 'gemini'}


SUMMARY = {'goals': [candidate('cand_g1', 'goal', '홍보 영상 완성')],
           'tasks': [candidate('cand_t1', 'task', '콘티 작성', owner_hint='지은', description='촬영용 콘티')],
           'conflicts': [{'kind': 'timeline', 'status': 'needs_review', 'summary': '기한이 서로 다름',
                          'item_ids': [], 'evidence': [{'message_id': 'm1', 'url': 'https://discord.com/x'}]}]}


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **_):
        return {'guild_id': '1'}

    def latest_message_id(self, channel_id):
        return '30'

    def all_messages(self, channel_id):
        self.calls.append('all')
        return [{'id': '10', 'content': '콘티는 제가 쓸게요', 'timestamp': '2026-11-28T00:00:00+00:00',
                 'author': {'id': 'u', 'username': '지은'}},
                {'id': '30', 'content': '봇 글', 'author': {'id': 'b', 'bot': True}}]

    def messages_after(self, channel_id, after):
        self.calls.append(('after', after))
        return []


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.projects = Projects(root / 'projects')
        self.pid = self.projects.create('시험')['id']
        self.seen = []

        def fake_summarize(batch, items, known):
            self.seen.append((batch, items, known))
            return json.loads(json.dumps(SUMMARY))
        self.inbox = Inbox(root / 'inbox', self.projects, summarize=fake_summarize,
                           client_factory=FakeClient)

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidates_wait_for_a_person(self):
        self.assertEqual(self.inbox.add_summary(self.pid, SUMMARY), 2)
        self.assertEqual(self.inbox.add_summary(self.pid, SUMMARY), 0)  # 같은 제안은 한 번만
        state = self.projects.get(self.pid).read()
        self.assertEqual(state['tasks'], [])  # 사람이 추가하기 전에는 대시보드에 없다
        view = self.inbox.view(self.pid)
        self.assertEqual([c['status'] for c in view['candidates']], ['proposed', 'proposed'])
        self.assertEqual(len(view['conflicts']), 1)
        self.assertNotIn('cursor', view)

    def test_accept_adds_task_with_evidence_and_reject_hides(self):
        self.inbox.add_summary(self.pid, SUMMARY)
        out = self.inbox.decide(self.pid, 'cand_t1', 'accept')
        task = out['state']['tasks'][0]
        self.assertEqual((task['title'], task['owner'], task['end'], task['status']), ('콘티 작성', '지은', DUE, '예정'))
        self.assertIn('https://discord.com/channels/1/2/m1', task['note'])
        self.inbox.decide(self.pid, 'cand_g1', 'reject')
        self.assertEqual(self.projects.get(self.pid).read()['goals'], [])
        with self.assertRaises(RuntimeError):
            self.inbox.decide(self.pid, 'cand_t1', 'accept')

    def test_goal_without_due_uses_project_end(self):
        state = self.projects.get(self.pid).read()
        group, item = to_item(candidate('cand_x', 'goal', '목표', due=''), state)
        self.assertEqual((group, item['due']), ('goals', state['project']['end']))

    def test_sync_reads_channel_skips_bots_and_passes_known_items(self):
        self.inbox.link(self.pid, '123456')
        self.assertEqual(self.inbox.sync(self.pid), 'done')
        batch, items, known = self.seen[0]
        self.assertEqual([m['id'] for m in batch['messages']], ['10'])
        self.assertEqual(batch['messages'][0]['url'], 'https://discord.com/channels/1/123456/10')
        self.inbox.decide(self.pid, 'cand_t1', 'reject')
        # 새 메시지가 없으면 Gemini를 다시 부르지 않는다.
        self.assertEqual(self.inbox.sync(self.pid), 'no_new')
        self.assertEqual(len(self.seen), 1)

    def test_link_rejects_non_numeric_channel(self):
        with self.assertRaises(ValueError):
            self.inbox.link(self.pid, 'general')

    def test_sync_needs_channel(self):
        with self.assertRaises(ValueError):
            self.inbox.sync(self.pid)


class IngestEndpointTests(unittest.TestCase):
    def test_ingest_requires_secret_and_cookie_routes_stay_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = start_server(0, Path(tmp) / 'dashboard.json', token='t', auto_sync=False)
            try:
                pid = server.projects.create('시험')['id']
                server.inbox._summarize = lambda batch, items, known: json.loads(json.dumps(SUMMARY))
                base = f'http://127.0.0.1:{server.server_port}/api/projects/{pid}'
                body = json.dumps({'messages': [{'id': '1', 'content': '할 일', 'url': ''}]}).encode()

                def post(url, headers):
                    req = urllib.request.Request(url, body, dict(headers, **{'Content-Type': 'application/json'}))
                    try:
                        with urllib.request.urlopen(req) as r:
                            return r.status, json.loads(r.read())
                    except urllib.error.HTTPError as e:
                        return e.code, None

                with mock.patch.dict(os.environ, {'PM_INGEST_SECRET': 's3'}):
                    self.assertEqual(post(base + '/ingest/discord', {'Authorization': 'Bearer nope'})[0], 401)
                    self.assertEqual(post(base + '/ingest/discord', {'Authorization': 'Bearer s3'}),
                                     (200, {'added': 2}))
                    # 수신 비밀 값으로는 다른 화면 API를 쓸 수 없다.
                    self.assertEqual(post(base + '/inbox', {'Authorization': 'Bearer s3'})[0], 401)
                with mock.patch.dict(os.environ, {'PM_INGEST_SECRET': ''}):
                    self.assertEqual(post(base + '/ingest/discord', {'Authorization': 'Bearer '})[0], 401)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
