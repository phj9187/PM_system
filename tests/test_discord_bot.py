import json
import tempfile
import unittest
from pathlib import Path

from integrations.discord.bot import Actions, BotState, Collector, channel_name
from integrations.discord.client import BOT_PERMISSIONS, DiscordClient, DiscordError, invite_url


class FakeDiscord:
    """경로별 응답을 흉내 내는 가짜 transport."""

    def __init__(self):
        self.calls, self.messages, self.next_id, self.fail = [], {}, 1000, {}

    def __call__(self, method, url, headers, body):
        path = url.split('/api/v10', 1)[1]
        data = json.loads(body) if body else None
        self.calls.append((method, path, headers, data))
        if path in self.fail:
            return self.fail.pop(path)
        if method == 'GET' and '/messages' in path:
            cid = path.split('/')[2]
            msgs = self.messages.get(cid, [])
            query = dict(q.split('=') for q in path.split('?')[1].split('&'))
            if 'after' in query:
                msgs = [m for m in msgs if int(m['id']) > int(query['after'])]
                return 200, {}, list(reversed(msgs[:int(query['limit'])]))
            return 200, {}, list(reversed(msgs))[:int(query['limit'])]
        if method == 'GET' and path.endswith('/channels'):
            return 200, {}, [{'id': 'cat9', 'type': 4, 'name': 'PM_system'}]
        if method == 'POST' and (path.endswith('/channels') or path.endswith('/threads')):
            self.next_id += 1
            return 201, {}, {'id': str(self.next_id), **data}
        return 200, {}, {}


def msg(i, text='내용', bot=False):
    return {'id': str(i), 'content': text, 'timestamp': '2026-11-23T14:00:00Z', 'edited_timestamp': None,
            'author': {'id': 'u1', 'username': 'tester', 'global_name': '가상팀원', 'bot': bot}}


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = BotState(Path(self.tmp.name) / 'discord.json')
        self.state.data['guild_id'] = 'g1'
        self.fake = FakeDiscord()
        self.client = DiscordClient(token='secret-token', transport=self.fake, sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_token_only_in_auth_header(self):
        self.client.me()
        _, _, headers, _ = self.fake.calls[0]
        self.assertEqual(headers['Authorization'], 'Bot secret-token')
        self.assertNotIn('secret-token', repr(self.client))
        with self.assertRaises(DiscordError):
            DiscordClient(token='', transport=self.fake)

    def test_rate_limit_retry(self):
        self.fake.fail['/users/@me'] = (429, {}, {'retry_after': 0.1})
        self.client.me()
        self.assertEqual(len(self.fake.calls), 2)

    def test_invite_url_has_needed_permissions(self):
        url = invite_url('123')
        self.assertIn('client_id=123', url)
        self.assertIn(f'permissions={BOT_PERMISSIONS}', url)

    def test_first_poll_skips_history_then_collects_new(self):
        self.state.data['channels']['c1'] = {'project_id': 'p1'}
        self.fake.messages['c1'] = [msg(1, '예전 대화')]
        col, got = Collector(self.client, self.state), []
        col.poll_once(lambda b: got.append(b) or True)
        self.assertEqual(got, [])
        self.assertEqual(self.state.data['cursors']['c1'], '1')
        self.fake.messages['c1'] += [msg(2, '새 작업 하자'), msg(3, 'bot', bot=True), msg(4, '  ')]
        stats = col.poll_once(lambda b: got.append(b) or True)
        self.assertEqual(stats['messages'], 1)
        [batch] = got
        self.assertEqual(batch['project_id'], 'p1')
        self.assertEqual(batch['messages'][0]['url'], 'https://discord.com/channels/g1/c1/2')
        self.assertEqual(batch['messages'][0]['author_name'], '가상팀원')
        self.assertEqual(self.state.data['cursors']['c1'], '4')
        saved = json.loads(self.state.path.read_text(encoding='utf-8'))
        self.assertNotIn('secret-token', json.dumps(saved))

    def test_failed_delivery_keeps_cursor(self):
        self.state.data['channels']['c1'] = {'project_id': 'p1'}
        self.state.data['cursors']['c1'] = '1'
        self.fake.messages['c1'] = [msg(1), msg(2)]
        col = Collector(self.client, self.state)
        self.assertEqual(col.poll_once(lambda b: False)['failed'], 1)
        self.assertEqual(self.state.data['cursors']['c1'], '1')

    def test_channel_thread_actions_and_idempotency(self):
        act = Actions(self.client, self.state)
        r = act.handle({'action': 'channel.create', 'request_id': 'r1', 'project_id': 'p1', 'name': '1차 발표 준비'})
        self.assertTrue(r['ok'])
        post = [c for c in self.fake.calls if c[0] == 'POST'][0]
        self.assertEqual(post[3]['parent_id'], 'cat9')
        self.assertEqual(post[3]['name'], '1차-발표-준비')
        self.assertEqual(act.handle({'action': 'channel.create', 'request_id': 'r1', 'name': 'x'}), r)
        cid = r['channel_id']
        t = act.handle({'action': 'thread.create', 'request_id': 'r2', 'project_id': 'p1',
                        'target_id': 'g1', 'parent_channel_id': cid, 'name': '자료 조사'})
        self.state.data['cursors'][t['thread_id']] = '0'
        self.fake.messages[t['thread_id']] = [msg(5, '자료 찾았어요')]
        got = []
        Collector(self.client, self.state).poll_once(lambda b: got.append(b) or True)
        thread_batch = [b for b in got if b['thread_id'] == t['thread_id']][0]
        self.assertEqual(thread_batch['target_id'], 'g1')
        act.handle({'action': 'thread.archive', 'request_id': 'r3', 'thread_id': t['thread_id']})
        self.assertTrue(self.state.data['threads'][t['thread_id']]['archived'])

    def test_delete_requires_human_confirmation(self):
        act = Actions(self.client, self.state)
        r = act.handle({'action': 'channel.delete', 'request_id': 'd1', 'channel_id': 'c1'})
        self.assertFalse(r['ok'])
        self.assertFalse(any(c[0] == 'DELETE' for c in self.fake.calls))
        r = act.handle({'action': 'channel.delete', 'request_id': 'd2', 'channel_id': 'c1',
                        'confirmed_by_human': True})
        self.assertTrue(r['ok'])

    def test_permission_error_reported(self):
        self.fake.fail['/guilds/g1/channels'] = (403, {}, {'message': 'Missing Permissions'})
        r = Actions(self.client, self.state).handle({'action': 'channel.create', 'request_id': 'x',
                                                     'name': 'a'})
        self.assertFalse(r['ok'])
        self.assertIn('권한', r['error'])

    def test_channel_name(self):
        self.assertEqual(channel_name('  Team Alpha 회의 '), 'team-alpha-회의')


if __name__ == '__main__':
    unittest.main()
