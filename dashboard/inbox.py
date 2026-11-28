"""Discord에서 찾은 목표·작업 후보함.

흐름: Discord 대화 → Gemini 정리(integrations.discord.summarize) → 후보(proposed) 저장
→ 앱 화면에 알림 → 사람이 추가/거절. AI는 대시보드에 직접 쓰지 않는다.

비밀 값(DISCORD_BOT_TOKEN, GEMINI_API_KEY, PM_INGEST_SECRET)은 환경 변수(코랩 보안 비밀 등)에서만 읽고,
파일·로그·응답에 넣지 않는다. 후보 파일은 Git에 포함하지 않는 data/private/inbox/<프로젝트 id>.json.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CHANNEL_ID = re.compile(r'^\d{5,25}$')
MAX_KEEP = 300
SYNC_MINUTES = 10  # 연결된 채널에 새 메시지가 있을 때만 Gemini를 부른다.


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def discord_ready():
    return bool(os.environ.get('DISCORD_BOT_TOKEN') and os.environ.get('GEMINI_API_KEY'))


def empty_inbox():
    return {'channel_id': '', 'cursor': '', 'candidates': [], 'conflicts': [],
            'last_sync': '', 'last_error': ''}


def existing_items(state):
    return ([{'id': g['id'], 'kind': 'goal', 'title': g['title'], 'due': g.get('due', ''),
              'status': '완료' if g.get('done') else '진행'} for g in state['goals']]
            + [{'id': t['id'], 'kind': 'task', 'title': t['title'], 'due': t.get('end', ''),
                'status': t.get('status', '')} for t in state['tasks']])


def _valid_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def to_item(candidate, state, today=None):
    """후보 하나를 대시보드 목표·작업으로 바꾼다. 근거 메시지 링크는 메모에 남긴다."""
    today = today or date.today()
    f = candidate.get('fields', {})
    links = '\n'.join(e['url'] for e in candidate.get('evidence', [])[:3] if e.get('url'))
    note = '\n'.join(x for x in (f.get('description', ''), 'Discord 대화에서 추가 · 근거:' if links else '', links) if x)
    due = _valid_day(f.get('due'))
    item_id = 'dc_' + candidate['id'].removeprefix('cand_')
    if candidate['kind'] == 'goal':
        return 'goals', {'id': item_id, 'title': candidate['title'][:200], 'note': note[:3000], 'done': False,
                         'due': (due or _valid_day(state['project']['end']) or today).isoformat()}
    end = due or today + timedelta(days=7)
    start = min(today, end)
    goal = f.get('parent_goal_id', '')
    return 'tasks', {'id': item_id, 'title': candidate['title'][:200], 'note': note[:3000],
                     'start': start.isoformat(), 'end': end.isoformat(),
                     'owner': (f.get('owner_hint') or '')[:100], 'status': '예정', 'predecessor': '',
                     'goal': goal if goal in {g['id'] for g in state['goals']} else ''}


class Inbox:
    def __init__(self, directory, projects, summarize=None, client_factory=None):
        self.dir = Path(directory)
        self.projects = projects
        self.lock = threading.RLock()
        self._summarize = summarize
        self._client_factory = client_factory
        self.running = set()  # 가져오는 중인 프로젝트. 서버를 다시 켜면 비워진다.

    # 파일
    def _path(self, pid):
        self.projects.get(pid)  # 없는 프로젝트면 LookupError
        return self.dir / f'{pid}.json'

    def read(self, pid):
        with self.lock:
            path = self._path(pid)
            data = empty_inbox()
            if path.exists():
                data.update(json.loads(path.read_text(encoding='utf-8')))
            return data

    def _write(self, pid, data):
        path = self._path(pid)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)

    def view(self, pid):
        """화면에 보낼 내용. 비밀 값은 없다."""
        data = self.read(pid)
        data.pop('cursor', None)
        data['discord_ready'] = discord_ready()
        data['syncing'] = pid in self.running
        return data

    # 설정
    def link(self, pid, channel_id):
        channel_id = (channel_id or '').strip()
        if channel_id and not CHANNEL_ID.match(channel_id):
            raise ValueError('Discord 채널 ID는 숫자만 입력하세요.')
        with self.lock:
            data = self.read(pid)
            if data['channel_id'] != channel_id:
                data.update(channel_id=channel_id, cursor='', last_error='')
            self._write(pid, data)
        return self.view(pid)

    # 후보 받기
    def add_summary(self, pid, summary, cursor=''):
        """정리 결과(summarize 반환값)의 목표·작업을 후보함에 넣는다. 새로 넣은 개수를 돌려준다."""
        with self.lock:
            data = self.read(pid)
            seen = {c['title'] for c in data['candidates']}
            added = 0
            for c in summary.get('goals', []) + summary.get('tasks', []):
                if c['title'] in seen:
                    continue
                c = dict(c, project_id=pid)
                data['candidates'].append(c)
                seen.add(c['title'])
                added += 1
            for c in summary.get('conflicts', []):
                if c['summary'] not in {x['summary'] for x in data['conflicts']}:
                    data['conflicts'].append(dict(c, created_at=now_iso()))
            # 오래된 처리 완료 후보부터 정리해 파일 크기를 묶어 둔다.
            done = [c for c in data['candidates'] if c['status'] != 'proposed']
            if len(data['candidates']) > MAX_KEEP and done:
                drop = {id(c) for c in done[:len(data['candidates']) - MAX_KEEP]}
                data['candidates'] = [c for c in data['candidates'] if id(c) not in drop]
            data['conflicts'] = data['conflicts'][-100:]
            if cursor:
                data['cursor'] = cursor
            data.update(last_sync=now_iso(), last_error='')
            self._write(pid, data)
            return added

    def _dedupe_against(self, pid):
        store = self.projects.get(pid)
        state = store.read()
        data = self.read(pid)
        # 거절한 후보도 다시 올라오지 않게 열린 후보처럼 넘긴다.
        known = [dict(c, status='proposed') for c in data['candidates']]
        return existing_items(state), known

    def ingest_batch(self, pid, batch):
        """Bot이 보낸 메시지 묶음(docs/interface-discord-app.md 1절)을 Gemini로 정리해 후보로 넣는다."""
        if not isinstance(batch, dict) or not isinstance(batch.get('messages'), list):
            raise ValueError('메시지 묶음 형식이 올바르지 않습니다.')
        msgs = [m for m in batch['messages'] if isinstance(m, dict) and isinstance(m.get('id'), str)
                and (m.get('content') or '').strip() and not m.get('deleted')]
        if not msgs:
            return 0
        items, known = self._dedupe_against(pid)
        summary = self._summarizer()(dict(batch, project_id=pid, messages=msgs), items, known)
        return self.add_summary(pid, summary, max((m['id'] for m in msgs), key=int, default=''))

    def _summarizer(self):
        if self._summarize:
            return self._summarize
        from integrations.discord.summarize import summarize
        return lambda batch, items, known: summarize(batch, items, known)

    # Discord에서 직접 가져오기 (앱 서버에 두 비밀 값이 있을 때)
    def _begin(self, pid):
        """가져오기를 시작할 수 있는지 확인하고 '가져오는 중'으로 표시한다. 이미 진행 중이면 None."""
        with self.lock:
            data = self.read(pid)
            if not data['channel_id']:
                raise ValueError('먼저 이 프로젝트와 연결할 Discord 채널 ID를 입력하세요.')
            if not self._client_factory and not discord_ready():
                raise ValueError('앱 서버에 DISCORD_BOT_TOKEN과 GEMINI_API_KEY 보안 비밀이 없습니다.')
            if pid in self.running:
                return None
            self.running.add(pid)
            return data

    def sync(self, pid):
        data = self._begin(pid)
        return self._run_sync(pid, data) if data else 'running'

    def _run_sync(self, pid, data):
        try:
            client = self._client()
            channel = client.request('GET', f'/channels/{data["channel_id"]}')
            guild = channel.get('guild_id', '')
            latest = client.latest_message_id(data['channel_id'])
            if not latest or latest == data['cursor']:
                self._finish(pid, '')
                return 'no_new'
            raw = (client.messages_after(data['channel_id'], data['cursor'])
                   if data['cursor'] else client.all_messages(data['channel_id']))
            from integrations.discord.bot import to_ingest_message
            msgs = [to_ingest_message(guild, data['channel_id'], m) for m in raw
                    if not (m.get('author') or {}).get('bot') and (m.get('content') or '').strip()]
            if msgs:
                self.ingest_batch(pid, {'source': 'discord', 'guild_id': guild,
                                        'channel_id': data['channel_id'],
                                        'batch_id': f'app-sync:{latest}', 'messages': msgs})
            self._finish(pid, '', latest)
            return 'done'
        except Exception as exc:  # 오류 내용에 비밀 값은 들어가지 않는다(클라이언트가 토큰을 숨긴다).
            self._finish(pid, str(exc)[:300])
            raise

    def _client(self):
        if self._client_factory:
            return self._client_factory()
        from integrations.discord.client import DiscordClient
        return DiscordClient()

    def _finish(self, pid, error, cursor=''):
        with self.lock:
            self.running.discard(pid)
            data = self.read(pid)
            data['last_error'] = error
            if cursor:
                data['cursor'] = cursor
            if not error:
                data['last_sync'] = now_iso()
            self._write(pid, data)

    def sync_in_background(self, pid):
        data = self._begin(pid)  # 설정이 빠졌으면 여기서 바로 오류를 돌려준다.
        if data:
            threading.Thread(target=lambda: self._quiet(self._run_sync, pid, data), daemon=True).start()

    @staticmethod
    def _quiet(fn, *args):
        try:
            fn(*args)
        except Exception:
            pass  # 오류는 last_error에 남아 화면에 보인다.

    def _safe_sync(self, pid):
        self._quiet(self.sync, pid)

    def start_auto_sync(self, minutes=SYNC_MINUTES):
        """채널이 연결된 프로젝트를 주기적으로 확인한다. 새 메시지가 없으면 Gemini를 부르지 않는다."""
        def loop():
            while True:
                time.sleep(minutes * 60)
                if not discord_ready():
                    continue
                for p in self.projects.list():
                    try:
                        if self.read(p['id'])['channel_id']:
                            self._safe_sync(p['id'])
                    except Exception:
                        pass
        threading.Thread(target=loop, daemon=True).start()

    # 사람의 결정
    def decide(self, pid, cid, action):
        if action not in ('accept', 'reject'):
            raise ValueError('추가 또는 거절만 할 수 있습니다.')
        with self.lock:
            data = self.read(pid)
            cand = next((c for c in data['candidates'] if c['id'] == cid), None)
            if not cand:
                raise LookupError('후보를 찾을 수 없습니다. 새로고침하세요.')
            if cand['status'] != 'proposed':
                raise RuntimeError('이미 처리한 후보입니다.')
            store = self.projects.get(pid)
            with store.lock:
                state = store.read()
                if action == 'accept':
                    group, item = to_item(cand, state)
                    state[group].append(item)
                    state = store.save(state, state['revision'])
                    cand['item_id'] = item['id']
            cand['status'] = 'accepted' if action == 'accept' else 'rejected'
            cand['decided_at'] = now_iso()
            self._write(pid, data)
            return {'state': state, 'inbox': self.view(pid)}

    def resolve_conflict(self, pid, index):
        with self.lock:
            data = self.read(pid)
            if not isinstance(index, int) or not 0 <= index < len(data['conflicts']):
                raise LookupError('확인 필요 항목을 찾을 수 없습니다.')
            data['conflicts'][index]['status'] = 'resolved'
            self._write(pid, data)
            return self.view(pid)
