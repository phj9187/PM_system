"""소스에서 독립 실행 가능한 Colab 노트북을 재생성한다. 외부 의존성 없음."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def cell(kind, source):
    out = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        out.update(execution_count=None, outputs=[])
    return out

files = {f'dashboard/{name}': (ROOT/'dashboard'/name).read_text(encoding='utf-8')
         for name in ('__init__.py','server.py','inbox.py','colab.py','index.html','app.js',
                         'manifest.webmanifest','sw.js','icon.svg')}
# Discord 제안함이 쓰는 정리 모듈(표준 라이브러리만 사용).
files.update({f'integrations/{name}': (ROOT/'integrations'/name).read_text(encoding='utf-8')
              for name in ('__init__.py','discord/__init__.py','discord/client.py','discord/recognize.py',
                           'discord/summarize.py','discord/bot.py')})
setup = '''from pathlib import Path
import json, sys

APP_DIR = Path('/content/PM_system_dashboard')
# 이 노트북에 소스를 포함하므로 저장소 연결이나 API 키 없이 실행됩니다.
FILES = json.loads(SOURCE_JSON)
for name, content in FILES.items():
    dest = APP_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding='utf-8')
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
print('대시보드 준비 완료. 추가 패키지 설치 없음.')
'''.replace('SOURCE_JSON', repr(json.dumps(files, ensure_ascii=False)))
run = '''# 같은 런타임에서 재실행하면 기존 서버를 종료하고 저장 파일을 다시 읽습니다.
if 'dashboard_server' in globals():
    dashboard_server.shutdown()
    dashboard_server.server_close()
# 새 소스를 받은 뒤 다시 실행해도 이전에 불러온 코드가 남지 않게 한다.
for _name in [m for m in sys.modules if m.split('.')[0] in ('dashboard', 'integrations')]:
    del sys.modules[_name]
# Discord 제안함(선택): 코랩 왼쪽 열쇠 아이콘(보안 비밀)에 DISCORD_BOT_TOKEN과 GEMINI_API_KEY를 넣고
# 이 노트북에 접근을 허용하면 켜집니다. 값은 화면·파일·백업에 남기지 않습니다.
import os
try:
    from google.colab import userdata
    for _key in ('DISCORD_BOT_TOKEN', 'GEMINI_API_KEY'):
        try:
            os.environ[_key] = userdata.get(_key)
        except Exception:
            pass
except ImportError:
    pass
print('Discord 제안함:', '켜짐' if os.environ.get('DISCORD_BOT_TOKEN') and os.environ.get('GEMINI_API_KEY')
      else '꺼짐 (보안 비밀 없음)')
from dashboard.server import start_server
from dashboard.colab import private_link, show_link

dashboard_server = start_server(port=0, data_path=APP_DIR/'data/private/dashboard.json')
show_link(private_link(dashboard_server), '별도 탭에서 대시보드 열기')
print('코랩 전용 링크입니다. Google 계정으로 로그인한 현재 사용자를 위한 접속 방식입니다.')
print('런타임이 종료되면 서버도 종료됩니다. 대시보드 상단에서 백업 저장을 눌러주세요.')
'''
public = '''# 공개 링크가 필요할 때만 아래 값을 True로 바꾸고 이 셀을 실행하세요.
# 설치는 내 PC가 아니라 Colab의 임시 실행 환경에서만 이루어집니다.
PUBLIC_LINK = False
if PUBLIC_LINK:
    # 공개 링크를 켜면 링크 소지자 누구나 접속하므로 Discord·Gemini 비밀 값은 서버에서 내린다.
    import os
    for _key in ('DISCORD_BOT_TOKEN', 'GEMINI_API_KEY'):
        os.environ.pop(_key, None)
    print('공개 링크 사용 중에는 Discord 제안함 가져오기를 끕니다.')
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                    'gradio==5.49.1', 'huggingface-hub<1.0'], check=True)
    if 'public_demo' in globals():
        public_demo.close()
    from dashboard.colab import public_link
    public_demo, url = public_link(dashboard_server)
    show_link(url, '공유 링크에서 대시보드 열기')
    print('이 전용 링크를 가진 사람은 같은 데이터를 열람·수정할 수 있습니다.')
    print('링크는 임시이며 코랩 런타임 종료 또는 터널 만료 시 사용할 수 없습니다.')
else:
    print('공개 링크를 만들지 않았습니다. 위의 코랩 전용 링크를 사용하세요.')
'''
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'colab':{'name':'PM_system.ipynb','provenance':[]},
    'kernelspec':{'display_name':'Python 3','name':'python3'},'language_info':{'name':'python'}},
    'cells':[cell('markdown', '''# PM System · 의사결정 보조 대시보드

**런타임 → 모두 실행** 후 `별도 탭에서 대시보드 열기`를 누르세요. CPU만 있으면 됩니다.

- 프로젝트 제목·목적·성공 조건·기간 편집
- 목표·작업·결정 요청 추가 / 수정 / 삭제
- 실제 날짜에 비례한 가지형 타임라인, 드래그 이동, 확대·축소
- 자동 파일 저장, JSON 백업 저장·불러오기
- Discord 제안함(선택): 연결한 채널의 대화에서 Gemini가 찾은 목표·할 일을 띄우고, 사람이 추가/거절

기본 실행에는 패키지를 설치하지 않습니다. 선택 셀에서 공개 링크를 켜는 경우에만 Colab에 Gradio를 설치합니다.
**코랩은 상시 서버가 아닙니다. 런타임 초기화 시 저장 파일도 사라질 수 있으므로 백업을 내려받으세요.**
실제 운영 데이터가 포함된 실행 출력·백업은 공개 GitHub에 올리지 마세요.
'''),cell('markdown','## 1. 프로그램 준비\n소스가 포함되어 있어 이 노트북 파일만으로 실행할 수 있습니다.\n'),cell('code',setup),
cell('markdown','## 2. 대시보드 실행\n출력되는 버튼을 누르면 코드 없이 대시보드만 별도 탭에 열립니다.\n'),cell('code',run),
cell('markdown','## 3. 다른 사람에게 공유하는 임시 링크 (선택)\n기본값은 꺼짐입니다. 공유가 필요하면 PUBLIC_LINK를 True로 바꾸세요. 링크 소지자 모두 같은 편집 권한을 갖는 초기 버전입니다.\n'),cell('code',public)]}
for i,c in enumerate(nb['cells']): c['id']=f'dashboard-{i+1:02}'
path=ROOT/'notebooks/PM_system.ipynb'
path.write_text(json.dumps(nb,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(path)
