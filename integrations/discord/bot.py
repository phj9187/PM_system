"""PM_system Discord Bot: 메시지 수집, 채널·스레드 생성, 알림.

판단과 저장은 하지 않는다. 모은 메시지는 앱 서버의 수신 창구로 넘기고,
앱이 보낸 채널·스레드 요청만 실행한다(docs/interface-discord-app.md).

사용 예 (저장소 루트, DISCORD_BOT_TOKEN 설정 후):
    python -m integrations.discord.bot invite <APPLICATION_ID>
    python -m integrations.discord.bot check
    python -m integrations.discord.bot setup --guild <서버 ID>
    python -m integrations.discord.bot create-project p1 "새 프로젝트"
    python -m integrations.discord.bot poll --once
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .client import CATEGORY, TEXT, DiscordClient, DiscordError, invite_url

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / 'data/private/discord.json'
DEFAULT_CATEGORY = 'PM_system'


def empty_state():
    return {'guild_id': '', 'category_name': DEFAULT_CATEGORY, 'category_id': '',
            'notify_channel_id': '', 'channels': {}, 'threads': {}, 'cursors': {},
            'done_requests': {}}


class BotState:
    """Bot의 연결 정보와 커서. 비공개 경로(data/private)에만 저장한다. 토큰은 넣지 않는다."""

    def __init__(self, path: Path = STATE_PATH):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = empty_state()
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding='utf-8')))

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, self.path)


def channel_name(name: str) -> str:
    """Discord 텍스트 채널 이름 규칙(소문자, 공백→하이픈)에 맞춘다."""
    name = re.sub(r'\s+', '-', name.strip().lower())
    name = re.sub(r'[^\w\-]', '', name)
    return (name or 'project')[:100]


def to_ingest_message(guild_id: str, channel_id: str, m: dict) -> dict:
    author = m.get('author') or {}
    return {'id': m['id'], 'author_id': author.get('id', ''),
            'author_name': author.get('global_name') or author.get('username', ''),
            'content': m.get('content', ''), 'created_at': m.get('timestamp', ''),
            'edited_at': m.get('edited_timestamp'), 'deleted': False,
            'url': f'https://discord.com/channels/{guild_id}/{channel_id}/{m["id"]}'}


class Collector:
    """등록된 채널·스레드의 새 메시지를 묶어 deliver로 넘긴다.

    처음 보는 채널은 현재 위치만 기록하고 과거 대화는 처리하지 않는다(연결 이후만).
    deliver가 True를 돌려줄 때만 커서를 옮겨, 실패하면 다음 주기에 다시 보낸다.
    """

    def __init__(self, client: DiscordClient, state: BotState):
        self.client, self.state = client, state

    def sources(self):
        d = self.state.data
        for cid, info in d['channels'].items():
            yield cid, {'project_id': info.get('project_id', ''), 'thread_id': None, 'target_id': None}
        for tid, info in d['threads'].items():
            if not info.get('archived'):
                yield tid, {'project_id': info.get('project_id', ''), 'thread_id': tid,
                            'target_id': info.get('target_id')}

    def poll_once(self, deliver: Callable[[dict], bool]) -> dict:
        d, stats = self.state.data, {'batches': 0, 'messages': 0, 'failed': 0}
        for source_id, meta in list(self.sources()):
            cursor = d['cursors'].get(source_id)
            if cursor is None:
                d['cursors'][source_id] = self.client.latest_message_id(source_id) or '0'
                self.state.save()
                continue
            fetched = []
            while True:
                page = self.client.messages_after(source_id, cursor if not fetched else fetched[-1]['id'])
                fetched += page
                if len(page) < 100:
                    break
            if not fetched:
                continue
            messages = [to_ingest_message(d['guild_id'], source_id, m) for m in fetched
                        if not (m.get('author') or {}).get('bot') and (m.get('content') or '').strip()]
            last = fetched[-1]['id']
            if messages:
                batch = {'source': 'discord', 'guild_id': d['guild_id'], 'channel_id': source_id,
                         'batch_id': f'{source_id}:{last}', **meta, 'messages': messages}
                if not deliver(batch):
                    stats['failed'] += 1
                    continue
                stats['batches'] += 1
                stats['messages'] += len(messages)
            d['cursors'][source_id] = last
            self.state.save()
        return stats


class Actions:
    """앱의 채널·스레드 요청 실행(interface 5절). 같은 request_id는 한 번만 실행한다."""

    def __init__(self, client: DiscordClient, state: BotState):
        self.client, self.state = client, state

    def _category_id(self) -> str:
        d = self.state.data
        if d.get('category_id'):
            return d['category_id']
        for ch in self.client.channels(d['guild_id']) or []:
            if ch.get('type') == CATEGORY and ch.get('name') == d['category_name']:
                d['category_id'] = ch['id']
                break
        else:
            d['category_id'] = self.client.create_channel(d['guild_id'], d['category_name'], CATEGORY)['id']
        self.state.save()
        return d['category_id']

    def handle(self, req: dict) -> dict:
        d = self.state.data
        rid, action = req.get('request_id', ''), req.get('action', '')
        if rid and rid in d['done_requests']:
            return d['done_requests'][rid]
        try:
            result = self._run(action, req)
        except DiscordError as exc:
            reason = '권한이 없습니다. Bot 권한을 확인하세요.' if exc.status == 403 else str(exc)
            return {'request_id': rid, 'ok': False, 'error': reason}
        result = {'request_id': rid, 'ok': True, **result}
        if rid:
            d['done_requests'][rid] = result
        self.state.save()
        return result

    def _run(self, action: str, req: dict) -> dict:
        d, c = self.state.data, self.client
        if not d['guild_id']:
            raise DiscordError(0, '서버가 설정되지 않았습니다. setup --guild 를 먼저 실행하세요.')
        if action == 'channel.create':
            ch = c.create_channel(d['guild_id'], channel_name(req['name']), TEXT, self._category_id())
            d['channels'][ch['id']] = {'project_id': req.get('project_id', '')}
            d['cursors'][ch['id']] = '0'  # 새 채널은 처음부터 수집
            return {'channel_id': ch['id']}
        if action == 'thread.create':
            parent = req['parent_channel_id']
            th = c.create_thread(parent, req['name'])
            d['threads'][th['id']] = {'project_id': req.get('project_id', ''),
                                      'target_id': req.get('target_id'), 'parent_channel_id': parent}
            d['cursors'][th['id']] = '0'
            return {'thread_id': th['id']}
        if action == 'channel.rename':
            c.edit_channel(req['channel_id'], name=channel_name(req['name']))
            return {}
        if action == 'thread.rename':
            c.edit_channel(req['thread_id'], name=req['name'][:100])
            return {}
        if action == 'thread.archive':
            c.edit_channel(req['thread_id'], archived=True)
            d['threads'].get(req['thread_id'], {})['archived'] = True
            return {}
        if action == 'channel.delete':
            if req.get('confirmed_by_human') is not True:
                raise DiscordError(0, '채널 삭제는 앱에서 사람이 확인한 요청만 실행합니다.')
            c.delete_channel(req['channel_id'])
            d['channels'].pop(req['channel_id'], None)
            d['cursors'].pop(req['channel_id'], None)
            return {}
        raise DiscordError(0, f'알 수 없는 요청: {action}')

    def notify(self, event: dict) -> bool:
        """앱 알림(interface 4절)을 알림 채널에 짧게 올린다."""
        channel = self.state.data.get('notify_channel_id')
        if not channel:
            return False
        label = {'candidate.created': '새 후보', 'candidate.accepted': '추가됨',
                 'candidate.rejected': '거절됨'}.get(event.get('event'), '알림')
        text = f'[{label}] {event.get("title", "")}'
        if event.get('app_url'):
            text += f'\n앱에서 확인: {event["app_url"]}'
        self.client.send_message(channel, text)
        return True


def http_deliver(url: str, secret: str) -> Callable[[dict], bool]:
    def deliver(batch: dict) -> bool:
        req = urllib.request.Request(url, data=json.dumps(batch, ensure_ascii=False).encode('utf-8'),
                                     method='POST', headers={'Content-Type': 'application/json',
                                                             'Authorization': f'Bearer {secret}'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError):
            return False
    return deliver


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m integrations.discord.bot')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('invite', help='서버 초대 주소 출력')
    s.add_argument('application_id')
    s = sub.add_parser('check', help='Bot 연결과 볼 수 있는 서버·채널 확인')
    s.add_argument('--summary', action='store_true', help='이름 없이 개수만 출력(공개 실행 기록용)')
    s = sub.add_parser('setup', help='사용할 서버와 카테고리 저장')
    s.add_argument('--guild', required=True)
    s.add_argument('--category', default=DEFAULT_CATEGORY)
    s.add_argument('--notify-channel', default='')
    s = sub.add_parser('link', help='이미 있는 채널을 프로젝트에 연결')
    s.add_argument('channel_id'); s.add_argument('project_id')
    s = sub.add_parser('create-project', help='프로젝트 채널 만들기(시험용)')
    s.add_argument('project_id'); s.add_argument('name')
    s = sub.add_parser('recognize-test', help='최근 메시지로 Gemini 인식 시험, 후보를 같은 채널에 알림')
    s.add_argument('--limit', type=int, default=50)
    s = sub.add_parser('summarize-channel', help='채널 전체 대화를 정리해 워드 파일과 추천 목표를 채널에 올림')
    s.add_argument('--channel', default='', help='채널 ID. 비우면 Bot이 읽을 수 있는 텍스트 채널 전부')
    s = sub.add_parser('poll', help='새 메시지 수집')
    s.add_argument('--once', action='store_true')
    s.add_argument('--interval', type=int, default=300)
    s.add_argument('--ingest-url', default='')
    a = p.parse_args(argv)

    if a.cmd == 'invite':
        print(invite_url(a.application_id))
        return 0
    try:
        client, state = DiscordClient(), BotState()
        if a.cmd == 'check':
            me = client.me()
            print(f'Bot 연결 성공: {me.get("username")}')
            if a.summary:
                print(f'서버 {len(client.guilds() or [])}개에 들어가 있음')
            for g in client.guilds() or []:
                channels = [ch for ch in client.channels(g['id']) or [] if ch.get('type') in (TEXT, CATEGORY)]
                if a.summary:
                    texts = [ch for ch in channels if ch.get('type') == TEXT]
                    readable = with_messages = 0
                    for ch in texts:  # 메시지 읽기 권한 시험. 내용은 출력하지 않는다.
                        try:
                            last = client.latest_message_id(ch['id'])
                        except DiscordError:
                            continue
                        readable += 1
                        with_messages += bool(last)
                    print(f'- 서버 1개: 채널·카테고리 {len(channels)}개, 텍스트 채널 {len(texts)}개 중 '
                          f'메시지 읽기 가능 {readable}개, 메시지가 있는 채널 {with_messages}개')
                    continue
                print(f'- 서버 {g["name"]} (ID {g["id"]})')
                for ch in channels:
                    kind = '카테고리' if ch['type'] == CATEGORY else '채널'
                    print(f'    {kind} {ch["name"]} (ID {ch["id"]})')
        elif a.cmd == 'setup':
            state.data.update(guild_id=a.guild, category_name=a.category, category_id='',
                              notify_channel_id=a.notify_channel)
            state.save()
            print('저장했습니다: data/private/discord.json')
        elif a.cmd == 'link':
            state.data['channels'][a.channel_id] = {'project_id': a.project_id}
            state.save()
            print('연결했습니다. 다음 수집부터 새 메시지를 가져옵니다.')
        elif a.cmd == 'create-project':
            print(Actions(client, state).handle({'action': 'channel.create', 'request_id': '',
                                                  'project_id': a.project_id, 'name': a.name}))
        elif a.cmd == 'recognize-test':
            from .recognize import RecognitionError, recognize
            total = 0
            for g in client.guilds() or []:
                for ch in client.channels(g['id']) or []:
                    if ch.get('type') != TEXT:
                        continue
                    try:
                        raw = client.request('GET', f'/channels/{ch["id"]}/messages',
                                             query={'limit': str(min(a.limit, 100))}) or []
                    except DiscordError:
                        continue
                    raw = sorted(raw, key=lambda m: int(m['id']))
                    msgs = [to_ingest_message(g['id'], ch['id'], m) for m in raw
                            if not (m.get('author') or {}).get('bot') and (m.get('content') or '').strip()]
                    if not msgs:
                        continue
                    batch = {'source': 'discord', 'guild_id': g['id'], 'channel_id': ch['id'],
                             'project_id': 'test', 'batch_id': 'test', 'messages': msgs}
                    try:
                        result = recognize(batch, [])
                    except RecognitionError as exc:
                        print(f'인식 실패: {exc}', file=sys.stderr)
                        return 1
                    total += len(result['candidates'])
                    print(f'채널 1개 (모델 {result.get("model", "")}): 메시지 {len(msgs)}개, 후보 {len(result["candidates"])}개, '
                          f'버린 후보 {len(result["skipped"])}개')
                    lines = ['[인식 시험] 이 채널의 최근 대화에서 찾은 목표·작업 후보입니다. 아직 추가되지 않았습니다.']
                    for c in result['candidates']:
                        kind = '목표' if c['kind'] == 'goal' else '작업'
                        extra = ', '.join(x for x in (c['fields']['due'] and f'기한 {c["fields"]["due"]}',
                                                      c['fields']['owner_hint'] and f'담당 {c["fields"]["owner_hint"]}') if x)
                        lines.append(f'- [{kind}] {c["title"]}' + (f' ({extra})' if extra else '')
                                     + ' ' + ' '.join(f'<{e["url"]}>' for e in c['evidence'][:2]))
                    if not result['candidates']:
                        lines.append('- 찾은 후보가 없습니다.')
                    client.send_message(ch['id'], '\n'.join(lines))
            print(f'전체 후보 {total}개. 메시지가 있는 채널에는 결과를 올렸습니다.')
        elif a.cmd == 'summarize-channel':
            from .recognize import RecognitionError
            from .summarize import build_docx, discord_messages, summarize, KST
            from datetime import datetime
            done = 0
            for g in client.guilds() or []:
                for ch in client.channels(g['id']) or []:
                    if ch.get('type') != TEXT or (a.channel and ch['id'] != a.channel):
                        continue
                    try:
                        raw = client.all_messages(ch['id'])
                    except DiscordError:
                        continue
                    msgs = [to_ingest_message(g['id'], ch['id'], m) for m in raw
                            if not (m.get('author') or {}).get('bot') and (m.get('content') or '').strip()]
                    if not msgs:
                        continue
                    batch = {'source': 'discord', 'guild_id': g['id'], 'channel_id': ch['id'],
                             'project_id': '', 'batch_id': f'summary:{ch["id"]}', 'messages': msgs}
                    try:
                        summary = summarize(batch)
                    except RecognitionError as exc:
                        print(f'정리 실패: {exc}', file=sys.stderr)
                        return 1
                    docx = build_docx(summary, f'#{ch.get("name", "")}')
                    texts = discord_messages(summary)
                    for text in texts[:-1]:
                        client.send_message(ch['id'], text)
                    stamp = datetime.now(KST).strftime('%Y%m%d-%H%M')
                    client.send_file(ch['id'], texts[-1], f'대화정리-{stamp}.docx', docx,
                                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                    done += 1
                    print(f'채널 1개 정리 (모델 {summary["model"]}): 메시지 {summary["message_count"]}개, '
                          f'주제 {len(summary["topics"])}개, 합의 {len(summary["decisions"])}개, '
                          f'추천 목표 {len(summary["goals"])}개, 할 일 {len(summary["tasks"])}개, '
                          f'워드 파일 {len(docx) // 1024}KB')
            print(f'정리한 채널 {done}개. 결과는 각 Discord 채널에 올렸습니다.')
        elif a.cmd == 'poll':
            collector = Collector(client, state)
            if a.ingest_url:
                deliver = http_deliver(a.ingest_url, os.environ.get('PM_INGEST_SECRET', ''))
            else:  # 앱 수신 창구가 없을 때: 건수만 출력하고 커서는 옮기지 않는다.
                deliver = lambda b: print(f'묶음 {b["channel_id"]}: 메시지 {len(b["messages"])}개 (앱 미연결, 보관 안 함)') and False
            while True:
                print(collector.poll_once(deliver), flush=True)
                if a.once:
                    break
                time.sleep(max(a.interval, 30))
    except DiscordError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
