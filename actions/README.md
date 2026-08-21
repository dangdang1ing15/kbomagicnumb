# KBO 매직넘버 백엔드 파이프라인 (Phase 1~2)

네이버 스포츠 비공식 API로 KBO 경기 상태/순위를 크롤링하고, 매직넘버를 계산해
`magic_number.json`을 GitHub Pages 저장소에 커밋하며, 경기 시작/종료 시 FCM
푸시를 보내는 GCP Cloud Functions(2nd gen) 파이프라인.

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
| `HEAD_TO_HEAD_ADVANTAGE` | X | `false` | `true`시 동률 승률도 우승 확정으로 처리 |

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
