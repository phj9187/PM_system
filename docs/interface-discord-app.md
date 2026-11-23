# Discord ↔ 앱 연결 형식

상태: 초안 (2026-11-23). "앱 틀과 화면 개발"과 "Discord 채팅 연동 개발" 두 작업이 함께 지키는 형식이다.
기준 설계는 `docs/system-design.md`(PR #3)의 확정된 결정이다.

## 역할

- **Discord Bot**: 등록된 채널의 메시지를 모아 앱 서버로 넘기고, 앱이 보낸 알림을 Discord 채널에 올린다. 판단하거나 저장하지 않는다.
- **앱 서버(Gemini 정제 관문)**: 받은 메시지를 Gemini로 정제·인식하고, 결과만 원본 저장소에 쓴다. 원본 저장소 쓰기 경로는 이 관문 하나다.
- **Discord 인식 모듈** `integrations/discord/recognize.py`: 관문이 호출하는 Discord 전용 단계. 새 목표·작업 후보와 기존 항목의 논의 요약을 만든다.
- **사람**: 앱에서 후보를 추가하거나 거절한다. AI가 스스로 목표·작업을 추가하지 않는다.

## 1. Bot → 앱: 메시지 묶음

`POST /api/ingest/discord`
헤더 `Authorization: Bearer <PM_INGEST_SECRET>`. Bot과 앱이 한 프로세스에서 돌 때는 같은 본문을 함수 호출로 넘긴다.

```json
{
  "source": "discord",
  "guild_id": "123",
  "channel_id": "456",
  "thread_id": null,
  "target_id": null,
  "project_id": "p1",
  "batch_id": "456:1311000000000000000",
  "messages": [
    {"id": "1311000000000000000", "author_id": "789", "author_name": "표시 이름",
     "content": "본문", "created_at": "2026-11-23T09:00:00Z", "edited_at": null,
     "deleted": false, "url": "https://discord.com/channels/123/456/1311000000000000000"}
  ]
}
```

- `project_id`는 채널↔프로젝트 연결에서, `thread_id`·`target_id`는 스레드↔목표·작업 연결에서 Bot이 채운다. 연결이 없는 채널은 보내지 않는다.
- 앱은 `batch_id`와 메시지 `id`로 중복 수신을 무시한다.
- 응답 `202 {"accepted": n, "queued": n}`. Bot은 2xx를 받은 뒤에만 채널 커서를 옮긴다.
- Bot 메시지와 빈 메시지는 Bot이 미리 뺀다.

## 2. 앱 내부: 목표·작업 후보

```json
{
  "id": "cand_1a2b3c4d5e6f",
  "kind": "goal | task",
  "status": "proposed | accepted | rejected",
  "project_id": "p1",
  "title": "발표 자료 초안 작성",
  "fields": {"due": "2026-11-27", "owner_hint": "표시 이름", "parent_goal_id": "g1",
             "duplicate_of": "", "confidence": 0.9},
  "evidence": [{"message_id": "1311000000000000000", "url": "https://discord.com/channels/..."}],
  "source": {"kind": "discord", "channel_id": "456", "batch_id": "..."},
  "created_by": "gemini",
  "created_at": "2026-11-23T09:05:00+00:00"
}
```

- 후보는 대시보드 목표·작업을 바꾸지 않는다. 사람이 추가하면 목표·작업으로 들어가고 확정 결정 기록이 남는다.
- 근거 메시지가 없거나, 기존 항목·열린 후보와 제목이 같은 후보는 인식 모듈이 버린다.
- `kind: "update"`(기존 항목의 기한 변경·완료 보고)는 첫 버전에서 만들지 않는다. 사용자 결정 후 추가한다.

## 3. 앱 내부: 기록(논의 요약)

```json
{"id": "rec_...", "target_id": "g1", "kind": "discussion_summary",
 "summary": "발표 자료 초안 일정 논의", "evidence": [{"message_id": "...", "url": "..."}],
 "source": "discord", "created_by": "gemini", "created_at": "..."}
```

모든 기록은 `target_id`로 소속 목표·작업을 가진다. 그 항목의 상세 창에 시간순으로 쌓인다. 추가만 하고 덮어쓰지 않는다.

## 4. 앱 → Discord: 알림

```json
{"event": "candidate.created | candidate.accepted | candidate.rejected",
 "candidate_id": "cand_...", "title": "발표 자료 초안 작성", "app_url": "https://..."}
```

Bot은 앱 설정에 정한 알림 채널에 짧은 글과 앱 링크만 올린다.

## 5. 앱 → Bot: 채널·스레드 생성 요청

사용자 결정(2026-11-23): Bot이 프로젝트마다 채널을, 목표·작업마다 그 채널 안의 스레드를 만든다.

```json
{"action": "channel.create | channel.rename | channel.delete | thread.create | thread.rename | thread.archive",
 "request_id": "req_...", "project_id": "p1", "target_id": "g1", "name": "1차 발표 준비",
 "parent_channel_id": "456", "category_name": "PM_system"}
```

- `channel.create`는 프로젝트 생성 때, `thread.create`는 목표·작업 추가(후보 추가 포함) 때 보낸다. 목표·작업은 서버당 채널 500개 제한 때문에 채널이 아니라 스레드로 만든다.
- Bot 응답: `{"request_id": "...", "ok": true, "channel_id": "...", "thread_id": "..."}`. 앱은 받은 id를 프로젝트·목표·작업에 저장하고, 그 채널·스레드를 수집 대상과 기록 연결에 자동 등록한다. 스레드 메시지의 묶음에는 `thread_id`와 `target_id`가 붙어 해당 항목 상세 창 기록으로 간다.
- `channel.delete`는 앱에서 사람이 한 번 더 확인한 요청만 보낸다. 완료된 항목은 지우지 않고 `thread.archive`로 보관한다.
- 같은 `request_id`는 한 번만 실행한다. 권한이 없으면 `ok: false`와 이유를 돌려주고 앱은 설정창에 표시한다.
- 필요한 Bot 권한: 채널 관리, 공개 스레드 만들기, 스레드에서 메시지 보내기. 채널별 공개 범위를 정하려면 역할 관리.

## 6. 실패 처리

인식 모듈은 키가 없거나 Gemini 호출·응답 검증이 실패하면 `RecognitionError`를 낸다. 관문은 그 묶음을 원본 저장소에 넣지 않고 대기열에 남긴 뒤 다시 시도한다(추천안, 사용자 확정 전).

## 7. 비밀 값

`DISCORD_BOT_TOKEN`, `GEMINI_API_KEY`, `PM_INGEST_SECRET`는 실행 환경의 비밀 저장소에서만 읽는다. 저장소·로그·백업·설정창 화면에 값을 넣지 않는다. 이름 목록은 `.env.example`에 있다.

## 미정 (사용자 확인 필요)

수집 방식(주기 수집 추천), 자동 생성 채널의 카테고리와 공개 범위(추천: "PM_system" 카테고리, 팀 전체 공개), 인식 주기, 과거 대화 범위, Gemini 실패 처리, 정제 전 원문 보관, 알림 대상, 추가 전 편집 허용, 기존 항목 변화 인식, 수정·삭제 메시지 반영.
