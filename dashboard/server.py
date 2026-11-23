"""표준 라이브러리만으로 실행하는 대시보드 서버.

python -m dashboard.server
운영 자료는 Git에 포함하지 않는 data/private/dashboard.json에 저장한다.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
STATUSES = ('예정', '진행 중', '완료', '차단')
# 앱 설치(PWA)에 필요한 화면 파일. 운영 데이터는 포함하지 않는다.
PUBLIC_FILES = {'manifest.webmanifest': 'application/manifest+json; charset=utf-8',
                'sw.js': 'text/javascript; charset=utf-8',
                'icon.svg': 'image/svg+xml'}


def initial_state():
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    return {'version': 1, 'revision': 0,
            'project': {'title': '새 프로젝트', 'purpose': '팀이 달성하려는 목적을 작성하세요.',
                        'success': '완료 여부를 확인할 기준을 작성하세요.',
                        'start': d(-7), 'end': d(21)},
            'goals': [], 'tasks': [], 'decisions': []}


def validate(state):
    """가져오기와 저장 모두 같은 규칙을 적용한다."""
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError('지원하는 대시보드 백업 파일(version 1)이 아닙니다.')
    def text(obj, key, required=False, limit=3000):
        value = obj.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{key}: 문자열 길이가 올바르지 않습니다.')
        if required and not value.strip():
            raise ValueError('제목은 비워둘 수 없습니다.')
    def dates(obj, start='start', end='end'):
        a, b = date.fromisoformat(obj[start]), date.fromisoformat(obj[end])
        if a > b or (b-a).days > 3650:
            raise ValueError('종료일은 시작일 이후이며 기간은 10년 이내여야 합니다.')
    p = state['project']
    for k in ('title', 'purpose', 'success'):
        text(p, k, k == 'title')
    dates(p)
    ids = set()
    for group in ('goals', 'tasks', 'decisions'):
        if not isinstance(state.get(group), list) or len(state[group]) > 500:
            raise ValueError('항목은 종류별 500개까지 저장할 수 있습니다.')
        for item in state[group]:
            if not isinstance(item, dict):
                raise ValueError('항목 형식이 올바르지 않습니다.')
            text(item, 'id', True, 100)
            if item['id'] in ids:
                raise ValueError('중복된 항목 ID입니다.')
            ids.add(item['id'])
            text(item, 'title', True, 200)
            text(item, 'note')
            if group == 'tasks':
                dates(item)
                text(item, 'owner', limit=100)
                if item.get('status') not in STATUSES:
                    raise ValueError('작업 상태가 올바르지 않습니다.')
            else:
                date.fromisoformat(item['due'])
                if not isinstance(item.get('done'), bool):
                    raise ValueError('완료 상태가 올바르지 않습니다.')
    tasks = {t['id']: t for t in state['tasks']}
    horizon = [date.fromisoformat(p['start']), date.fromisoformat(p['end'])]
    horizon.extend(date.fromisoformat(t[k]) for t in tasks.values() for k in ('start','end'))
    if (max(horizon)-min(horizon)).days > 3650:
        raise ValueError('프로젝트와 작업의 전체 시간 범위는 10년 이내여야 합니다.')
    for t in tasks.values():
        seen = {t['id']}
        pred = t.get('predecessor', '')
        while pred:
            if pred not in tasks or pred in seen:
                raise ValueError('선행 작업이 없거나 순환 관계입니다.')
            seen.add(pred)
            pred = tasks[pred].get('predecessor', '')
        pred = t.get('predecessor', '')
        if pred and t['start'] < tasks[pred]['end']:
            raise ValueError('후속 작업 시작일은 선행 작업 종료일 이후여야 합니다.')
        goal = t.get('goal', '')
        if goal and goal not in {g['id'] for g in state['goals']}:
            raise ValueError('연결된 목표가 없습니다.')
    # 반환할 필드만 유지해서 가져온 파일의 불필요한 데이터는 저장하지 않는다.
    result = {'version': 1, 'project': {k: p[k] for k in ('title','purpose','success','start','end')}}
    fields = {'goals': ('id','title','due','note','done'),
              'decisions': ('id','title','due','note','done'),
              'tasks': ('id','title','start','end','owner','status','note','predecessor','goal')}
    for group, keys in fields.items():
        result[group] = [{k: item.get(k, '') for k in keys} for item in state[group]]
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.state = initial_state()
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            self.state = validate(raw)
            self.state['revision'] = int(raw.get('revision', 0))

    def read(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def save(self, state, revision):
        with self.lock:
            if revision != self.state['revision']:
                raise RuntimeError('다른 창에서 내용이 바뀌었습니다. 새로고침 후 다시 수정하세요.')
            clean = validate(state)
            clean['revision'] = self.state['revision'] + 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, self.path)
            self.state = clean
            return self.read()


def start_server(port=8765, data_path=None, token=None):
    store = Store(data_path or ROOT.parent/'data/private/dashboard.json')
    token = token or secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # 접속 키와 실제 운영 정보를 로그에 남기지 않는다.

        def reply(self, code, body, content_type='application/json; charset=utf-8', headers=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get('Cookie', ''))
                candidate = cookies['pm_access'].value if 'pm_access' in cookies else ''
            except Exception:
                candidate = ''
            return secrets.compare_digest(candidate, token)

        def do_GET(self):
            url = urlsplit(self.path)
            key = parse_qs(url.query).get('key', [''])[0]
            if key and secrets.compare_digest(key, token):
                self.reply(303, b'', headers={'Location': './', 'Set-Cookie':
                    f'pm_access={token}; Path=/; HttpOnly; SameSite=Lax'})
                return
            name = url.path.rsplit('/', 1)[-1]
            if name in PUBLIC_FILES:
                # 설치형 앱 파일은 데이터가 없어 접속 키 없이 제공한다.
                self.reply(200, (ROOT/name).read_bytes(), PUBLIC_FILES[name])
                return
            if not self.authorized():
                self.reply(401, {'error': '코랩 출력에 표시된 전용 접속 링크로 다시 열어주세요.'})
                return
            if url.path in ('/', '/dashboard', '/dashboard/'):
                self.reply(200, (ROOT/'index.html').read_bytes(), 'text/html; charset=utf-8')
            elif url.path in ('/app.js', '/dashboard/app.js'):
                self.reply(200, (ROOT/'app.js').read_bytes(), 'text/javascript; charset=utf-8')
            elif url.path.endswith('/api/state'):
                self.reply(200, store.read())
            elif url.path.endswith('/api/export'):
                self.reply(200, store.read(), headers={'Content-Disposition': 'attachment; filename="dashboard-backup.json"'})
            else:
                self.reply(404, {'error': '찾을 수 없습니다.'})

        def do_POST(self):
            if not self.authorized():
                self.reply(401, {'error': '접속 인증이 만료되었습니다.'}); return
            if not urlsplit(self.path).path.endswith('/api/state'):
                self.reply(404, {'error': '찾을 수 없습니다.'}); return
            if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                self.reply(415, {'error': 'JSON 형식만 지원합니다.'}); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 2_000_000:
                    raise ValueError('저장할 데이터는 2MB 이하여야 합니다.')
                body = json.loads(self.rfile.read(length))
                self.reply(200, store.save(body['state'], body['revision']))
            except RuntimeError as exc:
                self.reply(409, {'error': str(exc)})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except OSError:
                self.reply(500, {'error': '저장 공간에 기록하지 못했습니다. 백업을 내려받고 다시 시도하세요.'})
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.access_token = token
    server.store = store
    return server


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = start_server(args.port)
    print(f'대시보드: http://127.0.0.1:{server.server_port}/?key={server.access_token}', flush=True)
    print('종료: Ctrl+C. 데이터: data/private/dashboard.json', flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
