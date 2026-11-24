"""표준 라이브러리만 쓰는 Discord REST 클라이언트.

Bot 토큰은 DISCORD_BOT_TOKEN 환경 변수(또는 Colab 보안 비밀)에서만 읽는다.
토큰은 Authorization 헤더로만 보내고 출력·로그·예외 메시지에 넣지 않는다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

API = 'https://discord.com/api/v10'
USER_AGENT = 'DiscordBot (pm-system, 0.1)'

# 채널 종류
TEXT, CATEGORY, PUBLIC_THREAD = 0, 4, 11

# Bot 초대 권한 (docs/interface-discord-app.md 5절)
PERMISSIONS = {
    'MANAGE_CHANNELS': 1 << 4,
    'VIEW_CHANNEL': 1 << 10,
    'SEND_MESSAGES': 1 << 11,
    'READ_MESSAGE_HISTORY': 1 << 16,
    'MANAGE_THREADS': 1 << 34,
    'CREATE_PUBLIC_THREADS': 1 << 35,
    'SEND_MESSAGES_IN_THREADS': 1 << 38,
}
BOT_PERMISSIONS = sum(PERMISSIONS.values())


class DiscordError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f'Discord API 오류 HTTP {status}: {message}' if status else message)
        self.status = status


def invite_url(application_id: str, permissions: int = BOT_PERMISSIONS) -> str:
    """서버에 Bot을 초대하는 주소. Application ID는 비밀 값이 아니다."""
    query = urllib.parse.urlencode({'client_id': application_id, 'scope': 'bot',
                                    'permissions': str(permissions)})
    return f'https://discord.com/oauth2/authorize?{query}'


def http_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float = 30):
    """(status, headers, parsed_json)를 돌려준다."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        return exc.code, dict(exc.headers or {}), data


class DiscordClient:
    def __init__(self, token: str | None = None, transport: Callable = http_transport,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 3):
        self._token = token or os.environ.get('DISCORD_BOT_TOKEN', '')
        if not self._token:
            raise DiscordError(0, 'DISCORD_BOT_TOKEN이 설정되지 않았습니다.')
        self._transport = transport
        self._sleep = sleep
        self._max_retries = max_retries

    def __repr__(self):  # 토큰이 출력되지 않게 한다.
        return 'DiscordClient(token=***)'

    def request(self, method: str, path: str, *, query: dict | None = None, json_body=None,
                raw_body: bytes | None = None, content_type: str | None = None):
        url = API + path + ('?' + urllib.parse.urlencode(query) if query else '')
        headers = {'Authorization': f'Bot {self._token}', 'User-Agent': USER_AGENT}
        body = None
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(json_body, ensure_ascii=False).encode('utf-8')
        elif raw_body is not None:
            headers['Content-Type'] = content_type or 'application/octet-stream'
            body = raw_body
        for attempt in range(self._max_retries + 1):
            status, resp_headers, data = self._transport(method, url, headers, body)
            if status == 429 and attempt < self._max_retries:
                wait = (data or {}).get('retry_after') or resp_headers.get('Retry-After') or 1
                self._sleep(min(float(wait), 60.0))
                continue
            if 200 <= status < 300:
                return data
            message = (data or {}).get('message', '') if isinstance(data, dict) else ''
            raise DiscordError(status, message or '요청 실패')
        raise DiscordError(429, '요청 한도 초과')

    # 조회
    def me(self):
        return self.request('GET', '/users/@me')

    def guilds(self):
        return self.request('GET', '/users/@me/guilds')

    def channels(self, guild_id: str):
        return self.request('GET', f'/guilds/{guild_id}/channels')

    def active_threads(self, guild_id: str):
        return (self.request('GET', f'/guilds/{guild_id}/threads/active') or {}).get('threads', [])

    def messages_after(self, channel_id: str, after: str | None, limit: int = 100):
        """after 이후 메시지를 오래된 순으로 돌려준다(최대 limit개)."""
        query = {'limit': str(limit)}
        if after:
            query['after'] = after
        data = self.request('GET', f'/channels/{channel_id}/messages', query=query) or []
        return sorted(data, key=lambda m: int(m['id']))

    def all_messages(self, channel_id: str, max_messages: int = 1000):
        """채널의 메시지를 오래된 순으로 최대 max_messages개 돌려준다."""
        out, before = [], None
        while len(out) < max_messages:
            query = {'limit': '100'}
            if before:
                query['before'] = before
            page = self.request('GET', f'/channels/{channel_id}/messages', query=query) or []
            out += page
            if len(page) < 100:
                break
            before = min(page, key=lambda m: int(m['id']))['id']
        return sorted(out[:max_messages], key=lambda m: int(m['id']))

    def latest_message_id(self, channel_id: str) -> str | None:
        data = self.request('GET', f'/channels/{channel_id}/messages', query={'limit': '1'}) or []
        return data[0]['id'] if data else None

    # 쓰기
    def create_channel(self, guild_id: str, name: str, kind: int = TEXT, parent_id: str | None = None):
        body = {'name': name[:100], 'type': kind}
        if parent_id:
            body['parent_id'] = parent_id
        return self.request('POST', f'/guilds/{guild_id}/channels', json_body=body)

    def create_thread(self, channel_id: str, name: str):
        return self.request('POST', f'/channels/{channel_id}/threads', json_body={
            'name': name[:100], 'type': PUBLIC_THREAD, 'auto_archive_duration': 10080})

    def edit_channel(self, channel_id: str, **fields):
        return self.request('PATCH', f'/channels/{channel_id}', json_body=fields)

    def delete_channel(self, channel_id: str):
        return self.request('DELETE', f'/channels/{channel_id}')

    def send_file(self, channel_id: str, content: str, filename: str, data: bytes,
                  mime: str = 'application/octet-stream'):
        """파일 하나를 첨부한 메시지를 보낸다(multipart/form-data)."""
        boundary = 'pm-' + os.urandom(12).hex()
        payload = json.dumps({'content': content[:2000], 'allowed_mentions': {'parse': []},
                              'attachments': [{'id': 0, 'filename': filename}]}, ensure_ascii=False)
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
            f'Content-Type: application/json\r\n\r\n{payload}\r\n'.encode('utf-8'),
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; '
            f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode('utf-8'),
            data, f'\r\n--{boundary}--\r\n'.encode('utf-8')]
        return self.request('POST', f'/channels/{channel_id}/messages', raw_body=b''.join(parts),
                            content_type=f'multipart/form-data; boundary={boundary}')

    def send_message(self, channel_id: str, content: str):
        return self.request('POST', f'/channels/{channel_id}/messages', json_body={
            'content': content[:2000], 'allowed_mentions': {'parse': []}})
