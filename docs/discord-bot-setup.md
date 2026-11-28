# Discord Bot 만들기와 연결 확인

Bot 코드는 `integrations/discord/`에 있고 Python 3.10 이상의 표준 라이브러리만 씁니다. 설치할 패키지는 없습니다.

## 1. 개발자 포털에서 Bot 만들기 (사용자)

1. https://discord.com/developers/applications 에서 **New Application**을 누르고 이름(예: PM System)을 정합니다.
2. **General Information**의 **Application ID**를 복사해 둡니다. 비밀 값이 아닙니다.
3. 왼쪽 **Bot** 메뉴에서
   - **Privileged Gateway Intents**의 **Message Content Intent**를 켜고 저장합니다.
   - **Public Bot**은 끕니다(우리 팀 서버에만 들어가게).
   - **Reset Token**으로 토큰을 만들고 바로 아래 3번의 비밀 저장 위치에 넣습니다. 토큰은 채팅·저장소·스크린샷에 남기지 않습니다.

## 2. 서버에 초대

```sh
python -m integrations.discord.bot invite <Application ID>
```

출력된 주소를 열어 팀 서버(처음에는 시험용 서버 추천)를 고르고 승인합니다. 주소에 담긴 권한은 채널 보기·메시지 기록 읽기·메시지 보내기·채널 관리·스레드 관리·공개 스레드 만들기·스레드에서 메시지 보내기입니다.

## 3. 토큰을 비밀 저장소에 넣기

- 내 컴퓨터: 터미널 환경 변수 `DISCORD_BOT_TOKEN` (macOS/Linux `export DISCORD_BOT_TOKEN=...`, Windows PowerShell `$env:DISCORD_BOT_TOKEN="..."`). 명령 기록에 남지 않게 하려면 입력 직전에 공백을 붙이거나 창을 닫은 뒤 다시 엽니다.
- Colab: 왼쪽 열쇠 아이콘(보안 비밀)에 `DISCORD_BOT_TOKEN`을 추가하고, 셀에서 `os.environ['DISCORD_BOT_TOKEN'] = userdata.get('DISCORD_BOT_TOKEN')`로 읽습니다. 셀 출력에 값을 찍지 않습니다.

## 4. 연결 확인

```sh
python -m integrations.discord.bot check
python -m integrations.discord.bot setup --guild <서버 ID>
python -m integrations.discord.bot create-project test "시험 프로젝트"
python -m integrations.discord.bot poll --once
```

- `check`: Bot 이름과 볼 수 있는 서버·채널·카테고리를 출력합니다. 토큰은 출력하지 않습니다.
- `create-project`: `PM_system` 카테고리(없으면 만듦) 아래 채널을 만들고 수집 대상에 등록합니다.
- `poll --once`: 새 메시지 건수만 출력합니다. 앱 수신 창구(`--ingest-url`)가 생기기 전에는 내용을 보관하지 않고 커서도 옮기지 않습니다.

연결 정보와 커서는 Git에서 제외되는 `data/private/discord.json`에 저장됩니다. 토큰은 이 파일에도 들어가지 않습니다.
