# KBO 매직넘버 백엔드 파이프라인 (Phase 1~2)

네이버 스포츠 비공식 API로 KBO 경기 상태/순위를 크롤링하고, 매직넘버를 계산해
`magic_number.json`을 GitHub Pages 저장소에 커밋하며, 경기 시작/응원팀 경기 종료/
전체 경기 종료 시 FCM 푸시를 보내는 GCP Cloud Functions(2nd gen) 파이프라인.

## 푸시 알림 (FCM 토픽 3개)

| 시점 | 토픽 | 내용 |
|---|---|---|
| 오늘 경기 중 하나라도 시작 | `kbo-magic-number-start` | "게임이 시작되었어요! 과연 매직넘버는 어떻게 갱신될까요?" |
| 응원팀(target team) 경기 종료 | `kbo-magic-number-team-result` | "내 팀이 승리/패배했어요! 다른 팀들의 경기가 다 끝나면 매직넘버를 알려드릴게요." (`data`에 `team_name`/`won`) |
| 오늘 모든 경기 종료 | `kbo-magic-number-end` | "모든 경기가 다 끝났어요! 갱신된 매직넘버를 확인해주세요." (`data`에 `reload_widget`/`magic_number`) |

각 토픽은 하루 1회만 발송되도록 `state.json`으로 중복을 막는다. 취소된 응원팀
경기는 승패가 없어 2번째 푸시를 보내지 않는다 (전체 종료 푸시에는 포함됨).

## 앱 버전 게이트 (Firebase Remote Config)

강제 업데이트는 이 파이프라인이 아니라 **Firebase Remote Config**로 처리한다
(저장소 루트의 `firebase.json`/`.firebaserc`/`remoteconfig.template.json`).
파라미터 3개: `minimum_supported_version`, `latest_version`, `force_update_message`.
클라이언트 앱이 시작 시 Remote Config를 fetch해서 자기 버전과
`minimum_supported_version`을 비교해 차단하는 로직은 앱 구현 범위 (이 저장소는
값만 서빙).

```bash
firebase deploy --only remoteconfig --project kbomagicnumb-28129
firebase remoteconfig:get --project kbomagicnumb-28129   # 반영 확인
```

## 디렉토리 구조

| 파일 | 역할 |
|---|---|
| `main.py` | Cloud Functions HTTP 엔트리포인트(`magic_number_pipeline`). 상태 머신 조율. |
| `crawler.py` | 네이버 스포츠 API 클라이언트 (경기 일정/상태, 순위표). |
| `calculator.py` | 매직넘버 연산 엔진 + 결과 JSON 페이로드 조립. |
| `github_deployer.py` | GitHub Contents API 래퍼 (JSON get/put, sha 덮어쓰기). |
| `state_store.py` | GitHub에 커밋된 `state.json`을 통한 상태머신 저장/조회. |
| `notifier.py` | firebase-admin으로 FCM 토픽 발송. |
| `tests/test_calculator.py` | 매직넘버 로직 단위 테스트 (`python -m pytest tests/`). |

## `magic_number.json` 확장 필드 (전체 경기 종료 시에만 채워짐)

`targetTeam`/`runnerUpTeam`/`todayGamesStatus`는 항상 갱신되고, 아래 3개는
오늘 모든 경기가 끝난 순간(하루 1회)에만 값이 채워진다 — 로컬에서 매직넘버
경우의 수를 재계산할 수 있도록 원본에 가까운 데이터를 실어보낸다:

- `standings`: 전체 10개 팀 순위표 (`team`, `rank`, `wins`, `losses`, `draws`, `gamesBehind`, `remainingGames`).
- `magicNumberTable`: 순위 인접쌍(1-2위, 2-3위, ...)마다 계산한 매직넘버 배열. 마지막 팀은 `magicNumber`/`chasingTeam`이 `null`. `HEAD_TO_HEAD_ADVANTAGE`는 target/chaser 쌍에만 반영되고 나머지 쌍은 근사치.
- `remainingSchedule`: 오늘 이후 ~ `KBO_SEASON_END_DATE`까지 전체 팀의 남은 경기 목록 (`gameDate`, `homeTeamCode`, `awayTeamCode` 등). 특정 팀으로 좁히지 않음 — `TARGET_TEAM_CODE`를 나중에 바꿔도 그대로 재사용 가능.

## 알려진 제약사항

- **네이버 비공식 API**: 공식 문서가 없으므로 언제든 스키마가 바뀔 수 있음. 이 코드는
  2025-08 시점 실제 응답을 기준으로 작성됨 (쿼리 파라미터는 `categoryId=kbo`,
  `upperCategoryId=kbo`가 아님 — 흔히 도는 문서와 다름).
- **잔여 경기 수**: 순위표 API에 잔여 경기 필드가 없어 `KBO_TOTAL_GAMES`(기본 144)에서
  누적 경기 수를 빼서 계산. 시즌 도중 우천 취소로 총 경기 수가 변하는 등의 예외는
  반영되지 않음.
- **상대전적 타이브레이커**: 네이버 API가 팀 간 상대전적을 제공하지 않아 자동 판별
  불가. `HEAD_TO_HEAD_ADVANTAGE` 환경변수로 수동 지정.
- **무승부 가정**: 매직넘버 계산은 "앞으로 남은 경기에 무승부가 없다"고 가정 (MLB/KBO
  매직넘버 관례와 동일한 단순화).

## 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `GITHUB_TOKEN` | O | - | `contents:write` 권한의 GitHub PAT (fine-grained 권장) |
| `GITHUB_REPO` | O | - | `owner/repo` 형식 |
| `GITHUB_JSON_PATH` | X | `magic_number.json` | 결과 JSON 커밋 경로 |
| `GITHUB_STATE_PATH` | X | `data/state.json` | 상태머신 파일 경로 |
| `GITHUB_BRANCH` | X | `main` | 커밋 대상 브랜치 |
| `FIREBASE_CREDENTIALS` | X | - | 서비스계정 JSON 문자열. 미설정시 Cloud Functions 런타임 서비스계정(ADC) 사용 |
| `TARGET_TEAM_CODE` | X | (1위 팀) | 특정 팀 기준으로 매직넘버 계산 (예: `LG`) |
| `KBO_SEASON` | X | 현재 연도 | 순위표 조회 시즌 |
| `KBO_TOTAL_GAMES` | X | `144` | 팀당 정규시즌 총 경기 수 |
| `KBO_SEASON_END_DATE` | X | `{KBO_SEASON}-10-05` | 잔여 경기 일정 조회 상한일 (정규시즌 종료 근사치) |
| `HEAD_TO_HEAD_ADVANTAGE` | X | `false` | `true`시 동률 승률도 우승 확정으로 처리 (target/chaser 쌍에만 적용, `magicNumberTable`의 다른 쌍에는 미적용) |

Secret Manager로 민감값(`GITHUB_TOKEN`, `FIREBASE_CREDENTIALS`) 관리:

```bash
echo -n "ghp_xxx" | gcloud secrets create kbo-github-token --data-file=-
echo -n "$(cat service-account.json)" | gcloud secrets create kbo-firebase-credentials --data-file=-
```

## 배포

```bash
gcloud functions deploy kbo-magic-number-pipeline \
  --gen2 \
  --runtime=python311 \
  --region=asia-northeast3 \
  --source=. \
  --entry-point=magic_number_pipeline \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=256Mi \
  --timeout=60s \
  --max-instances=1 \
  --set-env-vars=GITHUB_REPO=your-org/your-repo,GITHUB_JSON_PATH=magic_number.json,KBO_SEASON=2026 \
  --set-secrets=GITHUB_TOKEN=kbo-github-token:latest,FIREBASE_CREDENTIALS=kbo-firebase-credentials:latest
```

`--max-instances=1`은 GitHub `state.json`에 대한 동시 쓰기(sha 충돌)를 피하기 위한
안전장치 — free tier에서 트래픽이 매우 낮으므로 지연 영향은 무시할 수준.

## Cloud Scheduler

HTTP 트리거 함수이므로 Scheduler가 OIDC 토큰으로 인증 호출해야 함. 먼저 호출용
서비스계정을 만들고 함수 invoker 권한을 부여:

```bash
gcloud iam service-accounts create kbo-scheduler-invoker

gcloud functions add-invoker-policy-binding kbo-magic-number-pipeline \
  --region=asia-northeast3 \
  --member="serviceAccount:kbo-scheduler-invoker@$(gcloud config get-value project).iam.gserviceaccount.com"
```

경기 없는 시간대 호출을 줄이기 위해 3개 job으로 분리 (모두 같은 엔드포인트를 호출하며,
`main.py`는 상태 파일로 중복 알림/커밋을 막으므로 멱등적):

```bash
FN_URL=$(gcloud functions describe kbo-magic-number-pipeline --region=asia-northeast3 --gen2 --format='value(serviceConfig.uri)')
SA="kbo-scheduler-invoker@$(gcloud config get-value project).iam.gserviceaccount.com"

# 11:00 KST 1회 - 당일 경기 일정 확인용
gcloud scheduler jobs create http kbo-morning-check \
  --location=asia-northeast3 --schedule="0 11 * * *" --time-zone="Asia/Seoul" \
  --uri="$FN_URL" --http-method=POST --oidc-service-account-email="$SA"

# 평일 저녁 경기 시간대 2분 간격
gcloud scheduler jobs create http kbo-weekday-live \
  --location=asia-northeast3 --schedule="*/2 18-22 * * 1-5" --time-zone="Asia/Seoul" \
  --uri="$FN_URL" --http-method=POST --oidc-service-account-email="$SA"

# 주말 낮~저녁 경기 시간대 2분 간격
gcloud scheduler jobs create http kbo-weekend-live \
  --location=asia-northeast3 --schedule="*/2 13-18 * * 6,0" --time-zone="Asia/Seoul" \
  --uri="$FN_URL" --http-method=POST --oidc-service-account-email="$SA"
```

## 로컬 검증

```bash
python -m pytest tests/           # 매직넘버 연산 단위 테스트
python -m py_compile *.py         # 문법 검증
python -c "from crawler import fetch_games; import datetime; print(fetch_games(datetime.date.today()))"
```
