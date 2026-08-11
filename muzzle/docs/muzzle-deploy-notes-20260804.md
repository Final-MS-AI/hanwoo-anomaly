# 비문 개체식별 API — 배포 및 프론트엔드 연동 기록

**작업일** 2026-08-04
**담당** 개체 식별 파트
**상태** 프로덕션 연동 완료 · 실사용 검증 통과

> 이 문서는 `muzzle-api-notes.md`(API 구현)와 `muzzle-db-setup-notes.md`(DB 스키마)의
> 후속이다. 앞의 두 문서가 "만들었다"라면, 이 문서는 **"실제로 서비스에 붙였다"**의 기록이다.

---

## 0. 다섯 줄 요약

1. 팀 스키마 통일 작업으로 비문 테이블이 `muzzle` → `public`으로 이동되면서 **API가 중단**됐고, 참조를 수정해 복구했다.
2. 비문 API에 **HTTPS 공개 주소**를 부여했다. 팀 공용 도메인에 `/muzzle/*` 라우팅 한 블록만 추가했고, 기존 백엔드·프론트는 건드리지 않았다.
3. `systemd` 서비스로 전환해 **VM 재부팅 시 자동 기동**하도록 했다.
4. 프론트엔드 소 등록 화면에 비문 등록 호출을 연동했다. 팀원 백엔드 장애와 **무관하게 동작**하도록 순서를 설계했다.
5. 프로덕션 사이트에서 실제 등록에 성공했다 — `cattle_id 68`, 등록 벡터 2건, 중복 행 없음.

---

## 1. 사건: 스키마 이동으로 API가 중단됨

### 무슨 일이 있었나

다른 파트에서 "DB 경로를 통일하자"는 요청이 있었고, 이에 따라 비문 전용 테이블 2개가 이동됐다.

```sql
ALTER TABLE muzzle.enrollment          SET SCHEMA public;
ALTER TABLE muzzle.identification_log  SET SCHEMA public;
```

### 왜 문제가 됐나

`muzzle_api/main.py`의 SQL이 테이블명을 문자열로 직접 참조하고 있었다.

```python
SELECT ... FROM muzzle.enrollment ...     # 이 테이블은 더 이상 존재하지 않음
INSERT INTO muzzle.identification_log ... # 동일
```

테이블이 옮겨진 순간 **등록·식별 두 엔드포인트가 모두 죽었다.** `/muzzle/health`는 DB 연결만 확인하므로 여전히 `ok`를 반환했고, 그래서 겉으로는 정상으로 보였다. 이것이 발견을 늦출 수 있는 지점이었다.

### 왜 되돌리지 않았나

원래 설계 의도는 이랬다.

| 테이블 | 스키마 | 이유 |
|---|---|---|
| `cattle` | `public` | 여러 파트가 FK로 참조하는 **공용 개체 명부** |
| `enrollment`, `identification_log` | `muzzle` | 비문 전용. 다른 파트가 직접 쿼리하지 못하게 **격리** |

스키마 분리는 "직접 SELECT 금지" 원칙을 **시각적으로 강제**하는 장치였다. 다른 파트가 쿼리를 쓸 때 `muzzle.` 접두사를 붙여야 하므로 "이건 내 담당이 아니다"라고 한 번 인지하게 된다.

그러나 되돌리지 않기로 판단했다. 근거는 셋이다.

1. **다른 팀원이 경로 통일을 이미 요청했었다.** 되돌리면 팀 합의를 거부하는 형태가 된다.
2. **스키마 분리는 애초에 강한 안전장치가 아니다.** 권한(GRANT)으로 막은 것이 아니라 심리적 턱에 불과하므로, 잃는 것이 크지 않다.
3. **되돌리기도 동일하게 파괴적 변경이다.** 이미 `public.enrollment`를 참조하기 시작한 코드가 있다면 이번엔 그쪽이 깨진다. 변경 횟수만 두 배가 된다.

대신 **명시적 공지로 안전장치를 대체**했다. 표지판은 못 볼 수 있지만, 채널에 남긴 요청은 못 봤다고 하기 어렵다.

### 어떻게 고쳤나

```bash
cd ~/muzzle_api
cp main.py main.py.bak

# 테이블 참조만 치환. URL 경로(/muzzle/enroll)는 건드리지 않도록 테이블명을 명시
sed -i 's/muzzle\.enrollment/public.enrollment/g; \
        s/muzzle\.identification_log/public.identification_log/g' main.py

# 누락 확인 — 아무것도 안 나와야 정상
grep -rn "muzzle\.enrollment\|muzzle\.identification_log" *.py *.sh
```

`main.py`뿐 아니라 **`run_test.sh`에도 같은 참조가 박혀 있었다.** 첫 수정에서 이걸 빠뜨려 6번 테스트만 실패했고, 두 번째에 함께 처리했다.

### 부수적으로 발견한 버그

`run_test.sh`가 파이썬을 파일 없이 표준입력으로 실행하는데, `load_dotenv()`가 자기 위치를 추적하려다 실패했다.

```
AssertionError  (dotenv/main.py find_dotenv)
```

`.env` 경로를 명시해 해결했다.

```bash
sed -i 's|load_dotenv()|load_dotenv("/home/azureuser/muzzle_api/.env")|g' run_test.sh
```

### 재발 방지

`main.py`가 테이블명을 문자열로 직접 들고 있는 한 같은 사고가 반복된다. 다음 리팩터링 시 스키마를 상수로 분리할 것.

```python
SCHEMA = os.getenv("MUZZLE_SCHEMA", "public")
```

---

## 2. 테스트 데이터 처리 — 삭제 대신 표시

### 상황

`run_test.sh`가 만든 개체 2건(`999900000001`, `999900000002`)은 랜덤 노이즈 이미지로 등록된 **실존하지 않는 소**다. 실제 집계에 섞이면 발표 자료의 "등록 두수"가 틀어진다.

그러나 다른 파트에서 **"DB의 테스트 기록을 지우지 말아달라"**는 요청이 있었다.

### 판단

두 요구가 충돌하지 않는다는 것을 확인했다.

| | 실체 | `cattle` 삭제 시 |
|---|---|---|
| 식별 기록 | `identification_log` 행 | `matched_cattle_id`가 NULL 허용이라 **남는다** |
| 가짜 개체 | `cattle` 61·62번 | 사라진다 |

그러나 굳이 삭제할 필요도 없었다. `cattle.status` 컬럼을 처음부터 설계에 넣어뒀기 때문이다.

```sql
UPDATE public.cattle SET status = 'test' WHERE national_id LIKE '9999%';
```

- 기록은 전부 보존 → 팀원 요구 충족
- 집계 시 `WHERE status = 'active'` 한 줄로 제외 → 데이터 오염 방지

**다른 파트에 전달할 규칙:** 개체 수 집계·시계열 생성 시 `status = 'active'` 조건을 넣을 것.

### 실행 방법 두 가지

SQL은 **터미널(bash)에서 직접 실행되지 않는다.** SQL 클라이언트를 쓰거나 스크립트로 감싸야 한다.

**방법 A — VSCode SQLTools**
`Ctrl+Shift+P` → `SQLTools: New SQL File` → 쿼리 입력 → 전체 선택 후 `Ctrl+E` 두 번

**방법 B — 스크립트 (터미널에서 반복 사용)**
`~/muzzle_api/mark_test.py`로 저장해 재사용한다.

```python
import os
from dotenv import load_dotenv
load_dotenv("/home/azureuser/muzzle_api/.env")
import psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("UPDATE public.cattle SET status='test' WHERE national_id LIKE '9999%'")
    print(f"{cur.rowcount}건 표시 완료")
    c.commit()
```

```bash
./venv/bin/python mark_test.py
```

curl 테스트로 생성된 `999900000009`(67번)를 포함해 전 테스트 개체에 표시를 완료했다.

### 참고 — 테스트 반복 실행 시

`run_test.sh`는 실행할 때마다 같은 개체에 등록 벡터를 추가한다(설계상 한 개체 다중 등록 허용). 누적이 부담되면 행을 지우지 말고 비활성화한다.

```sql
UPDATE public.enrollment SET is_active = false
WHERE cattle_id IN (SELECT id FROM public.cattle WHERE status = 'test');
```

---

## 3. HTTPS 공개 — 왜 필요했고 어떻게 했나

### 문제

프론트엔드는 `https://`로 서빙되는데 비문 API는 `http://20.194.30.236:8001`이었다.

브라우저는 **HTTPS 페이지에서 HTTP 리소스 호출을 차단한다(mixed content).** 코드가 완벽해도 요청 자체가 나가지 않는다. 즉 프론트 연동의 **선행 조건**이었다.

### 선택: Caddy 리버스 프록시

```
브라우저 → https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/*
                          ↓
                      [Caddy]  ← TLS 종단, 인증서 자동 발급·갱신
                          ↓
                   127.0.0.1:8001  (비문 API, 코드 변경 없음)
```

Caddy를 택한 이유: **Let's Encrypt 인증서를 자동으로 발급하고 90일마다 자동 갱신**한다. 수동 관리 항목이 하나도 늘지 않는다.

### ★ 중요 — 이미 팀이 쓰고 있었다

`/etc/caddy/Caddyfile`을 열어보니 **팀 전체의 관문**이 이미 구성돼 있었다.

```
hanwoo.koreacentral.cloudapp.azure.com {
    handle /auth/*      { reverse_proxy 127.0.0.1:8000 }
    handle /cattle*     { reverse_proxy 127.0.0.1:8000 }
    handle /ocr/*       { reverse_proxy 127.0.0.1:8000 }
    handle /rag/*       { reverse_proxy 127.0.0.1:8000 }
    ...
    handle { root * /var/www/hanwoo; file_server }   ← 프론트엔드
}
```

**이 파일을 덮어썼다면 사이트 전체가 중단됐다.** 새로 작성하려던 계획을 중단하고, 블록 하나만 추가하는 방식으로 전환했다.

### 실제 작업

```bash
# 1. 백업
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.0804

# 2. /rag/* 블록 뒤에 삽입
#    handle /muzzle/* { reverse_proxy 127.0.0.1:8001 }
#    ※ 맨 아래 handle{}(fallback)보다 위에 와야 한다.
#      Caddy는 위에서부터 검사하고 첫 매치에서 멈춘다.

# 3. 문법 검사 후 무중단 반영
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy    # restart 아님 — 팀원 작업 중 끊기지 않게
```

### 검증 — 남의 것이 안 깨졌는지 반드시 확인

내 것만 확인하면 부족하다. **세 개를 모두 확인했다.**

```bash
curl -s https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/health   # 내 API
curl -s https://hanwoo.koreacentral.cloudapp.azure.com/health          # 팀원 백엔드
curl -s -o /dev/null -w "%{http_code}\n" https://hanwoo.koreacentral.cloudapp.azure.com/  # 프론트
```

결과: `{"status":"ok",...}` / `{"status":"healthy"}` / `200` — 전부 정상.

### 부수 수정 — FastAPI 문서 경로

Caddy가 `/muzzle/`로 시작하는 요청만 8001로 보내므로, 기본 문서 경로 `/docs`는 프론트엔드로 흘러가 404가 났다. 경로를 옮겼다.

```python
app = FastAPI(
    title="Muzzle Identification API",
    docs_url="/muzzle/docs",
    openapi_url="/muzzle/openapi.json",
)
```

→ `https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/docs`

### Azure 사전 설정

| 항목 | 값 |
|---|---|
| 공인 IP | `20.194.30.236` (Static — 재부팅해도 불변) |
| DNS 이름 | `hanwoo.koreacentral.cloudapp.azure.com` |
| NSG 인바운드 | 80, 443 허용 |

8001은 외부에 열지 않았다. Caddy를 경유하므로 노출할 필요가 없고, 인증 없는 API를 인터넷에 직접 노출하지 않는 편이 안전하다.

---

## 4. systemd 전환 — 재부팅 내성

### 왜

기존에는 `nohup ... &`로 실행 중이었다. VM이 재부팅되면 프로세스가 사라지고, **아무도 모르는 채 서비스가 죽어 있게 된다.** 프론트가 붙은 이후로는 "죽으면 데모가 불가능한" 서비스가 되므로 자동 기동이 필수다.

### 설정

```ini
# /etc/systemd/system/muzzle-api.service
[Unit]
Description=Muzzle Identification API
After=network.target

[Service]
User=azureuser
WorkingDirectory=/home/azureuser/muzzle_api
ExecStart=/home/azureuser/muzzle_api/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now muzzle-api
```

`Restart=always` — 프로세스가 비정상 종료돼도 자동 재기동된다.

### 운영 명령

| 목적 | 명령 |
|---|---|
| 상태 | `sudo systemctl status muzzle-api` |
| 재시작 | `sudo systemctl restart muzzle-api` |
| 실시간 로그 | `journalctl -u muzzle-api -f` |

### ⚠️ 다른 파트에 요청한 사항

```bash
pkill -f uvicorn          # ❌ 8000·8001이 함께 죽는다
pkill -f "port 8000"      # ✅ 포트를 명시할 것
```

---

## 5. 프론트엔드 연동

### 대상

`front/src/App.jsx` — 소 등록 모달(`소 등록하기`)

### 연동 전 상태와 문제점

| 항목 | 상태 | 문제 |
|---|---|---|
| 귀표 사진 + OCR | 구현됨 | — |
| 비문 사진 | **1장만** 선택 가능 | 등록은 3장 이상 권장 |
| 제출 대상 | `POST /cattle` (8000) 단독 | 비문 API 호출 없음 |

### 설계 결정 ★ — 호출 순서를 앞으로 뺀 이유

당초 `/cattle` 성공 후 비문을 등록하도록 붙였으나, 실제 테스트에서 `POST /cattle`이 **404**를 반환했다(팀원 백엔드 미구현).

```js
if (!response.ok) throw new Error(...);   // ← 여기서 중단
// 비문 등록                                 ← 실행되지 않음
```

**남의 파트 미완성이 내 파트를 막는 구조**였다. 순서를 뒤집어 해결했다.

```
[등록하기] 클릭
   ① POST /muzzle/enroll  → 비문 임베딩 저장 (독립 try/catch)
   ② POST /cattle         → 팀원 백엔드 (기존 로직 무수정)
```

이제 `/cattle`이 404여도 비문 등록은 정상 완료된다. 사용자에게는 `"비문 등록은 완료됐으나 개체 정보 저장에 실패했습니다"`로 상태를 정확히 안내한다.

### 절대 주소를 쓴 이유

프론트가 두 도메인에서 서빙된다.

| 도메인 | 용도 |
|---|---|
| `polite-rock-....azurestaticapps.net` | 팀 공식 (GitHub push 자동 배포) |
| `hanwoo.koreacentral.cloudapp.azure.com` | VM 직접 배포 (테스트용) |

`API_BASE_URL`은 상대 경로 방식이라 도메인에 따라 동작이 달라진다. 비문 API는 **어느 도메인에서든 동일하게 동작해야 하므로 절대 주소로 고정**했다.

```js
const MUZZLE_API = "https://hanwoo.koreacentral.cloudapp.azure.com";
```

### 추가한 코드

```js
// ── 비문 임베딩 등록 (개체 식별 파트) ──
let muzzleOk = false;
const muzzleInput = event.target.elements.muzzle_files;
const muzzleFiles = muzzleInput ? Array.from(muzzleInput.files) : [];
const nationalId = normalizedEarTagNumber
  .replace(/\D/g, "")
  .slice(-12)
  .padStart(12, "0");

if (muzzleFiles.length > 0) {
  try {
    const muzzleForm = new FormData();
    muzzleForm.append("national_id", nationalId);
    muzzleForm.append("barn_id", "");
    muzzleFiles.forEach((f) => muzzleForm.append("files", f));

    const muzzleRes = await fetch(`${MUZZLE_API}/muzzle/enroll`, {
      method: "POST",
      body: muzzleForm,
    });

    if (muzzleRes.ok) {
      muzzleOk = true;
      console.log("[비문] 등록 완료:", await muzzleRes.json());
    } else {
      console.error("[비문] 등록 실패", muzzleRes.status, await muzzleRes.text());
    }
  } catch (err) {
    console.error("[비문] 등록 오류:", err);
  }
}
```

기타 변경:
- 비문 `<input>`에 `name="muzzle_files"`, `multiple` 추가
- 촬영 안내 문구 강화 (아래 §7 참조)

### FormData 주의사항 (다른 파트가 호출할 때도 동일)

| 금지 | 결과 |
|---|---|
| `headers: {"Content-Type": "multipart/form-data"}` 직접 지정 | **요청이 깨진다.** 브라우저가 boundary와 함께 자동 설정 |
| 필드명 변경 | `national_id` / `barn_id` / `files` 고정. 다르면 422 |
| `/cattle/...` 로 호출 | Caddy가 8000으로 보낸다. 반드시 `/muzzle/...` |

### CORS

`main.py`에 이미 설정돼 있었다.

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
```

`["*"]`는 모든 출처를 허용하므로 개발 단계에서는 문제없다. **발표 전 실제 도메인 목록으로 좁힐 것**(§8 후속 과제).

---

## 6. Git 충돌 — 원인과 해결

### 무엇이 일어났나

작업 브랜치를 **22개 커밋 뒤처진 `main`**에서 분기했다. 그 사이 다른 파트가 `App.jsx`를 대폭 수정해 PR에서 충돌이 발생했다.

### 왜 웹 에디터로 풀지 않았나

22개 커밋 분량의 충돌을 수동 병합하면 **다른 파트의 작업을 덮어쓸 위험**이 크다. 내가 추가한 것은 명확히 4군데뿐이므로, **최신 파일을 그대로 받아 그 위에 패치를 재적용**하는 편이 안전하다.

```bash
git fetch origin
git merge origin/main
git checkout origin/main -- front/src/App.jsx   # 최신본으로 완전히 교체
# → 패치 스크립트 재실행 → 빌드 검증 → 커밋
```

### 커밋에서 제외한 것

| 파일 | 이유 |
|---|---|
| `front/.env.production` | 다른 파트가 만든 Google 클라이언트 ID 설정 |
| `API_BASE_URL = ""` 변경 | 내가 만든 것이 아님. 프로덕션에서 팀원 백엔드 호출이 깨질 수 있어 원복 |
| `package-lock.json` | `npm install` 부작용 |
| `App.bak*.jsx` | 로컬 임시 백업 |

### 머지 후 정리

PR 머지 확인 후 로컬을 정리했다. 정리를 머지 **이후**에 한 이유는, 백업 파일이 문제 발생 시 유일한 복구 수단이기 때문이다.

```bash
cd ~/hanwoo-anomaly
rm -f front/src/App.bak*.jsx    # 로컬 임시 백업 제거
git checkout main
git pull origin main            # 로컬을 최신 main으로 동기화
```

마지막 `git pull`을 생략하면 다음 작업 브랜치도 뒤처진 상태에서 분기해 동일한 충돌이 반복된다.

### 다음부터의 순서

```bash
git checkout main && git pull origin main   # ← 분기 전 필수
git checkout -b feat/작업명
```

---

## 7. 검증 결과

### 배관 검증 (`run_test.sh`)

| 단계 | 결과 |
|---|---|
| 헬스체크 | ✅ |
| 개체 A/B 등록 | ✅ `cattle_id` 61 / 62 |
| A·B 조회 | ✅ 유사도 0.9894 / 0.9890, 모두 `confirmed` |
| 로그 기록 | ✅ |

### 외부 HTTPS 경유 등록

```bash
curl -X POST https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/enroll \
  -F "national_id=999900000009" -F "files=@test/cowA_0.jpg" ...
```
→ 200 정상.

### 프로덕션 사이트 실사용 검증

`https://polite-rock-0ee43f000.7.azurestaticapps.net/cattle/register`

```
[비문] 등록 완료: {cattle_id: 68, national_id: "000158780357",
                  enrollment_id: 69, images_used: 3}
```

DB 확인:

| id | national_id | status | 등록 벡터 수 |
|---|---|---|---|
| 68 | 000158780357 | active | **2** |
| 67 | 999900000009 | active | 1 |
| 62 | 999900000002 | test | 3 |
| 61 | 999900000001 | test | 3 |

**68번의 벡터 수 2가 중요한 확인점이다.** 테스트 사이트와 프로덕션에서 각 1회씩 등록했는데 `cattle` 행은 하나만 생기고 등록 벡터만 늘었다. **동일 `national_id`에 대해 기존 개체를 재사용하는 로직이 정상 동작**하며, 중복 행이 생기지 않았다.

### ★ 검증되지 않은 것 — 반드시 인지할 것

**등록 성공은 임베딩 품질을 보장하지 않는다.**

이 API는 **코 부위만 크롭된 이미지**를 전제로 한다. 전신·얼굴 사진을 보내도 **에러 없이 그럴듯한 512차원 벡터가 반환된다.** 조용히 틀린다.

즉 위 검증은 **"배관이 뚫렸다"까지이며 "정확도가 확보됐다"가 아니다.** 크롭 규격 협의(§8)가 완료되기 전까지 등록된 임베딩의 유효성은 미보증이다.

임시 대응으로 촬영 안내 문구를 강화했다.

> "코가 화면에 가득 차도록 30cm 거리에서 정면 촬영해 주세요. 얼굴이나 전신이 나오면 인식되지 않습니다. 각도를 바꿔 3장 이상 선택해 주세요."

30cm는 임의 값이 아니라 **한우 비문 선행연구의 촬영 조건**(iPhone Xs / Galaxy S20, 30cm 고정, 아랫입술 전체 포함)을 그대로 옮긴 것이다.

---

## 8. 미해결 및 후속 과제

### 즉시 확인 필요 (다른 파트)

| 항목 | 내용 |
|---|---|
| `POST /cattle` 404 | 8000번 백엔드 미구현으로 보임. 등록 후 화면에 "Not Found" 표시. 비문 저장에는 영향 없음 |
| **`national_id` 자릿수 불일치** | 귀표 OCR 출력이 **9자리**(`158780357`). 프론트에서 0 패딩해 12자리로 맞춤(`000158780357`). 양측이 다른 형식을 쓰면 **동일 개체가 `cattle`에 2행으로 생성됨.** 가축이력번호 실제 규칙 확인 후 통일 필요 |

### 내 파트 우선순위

1. **크롭 규격 협의 (검출/YOLO 파트)** — 최우선. 마진, 최소 해상도, 종횡비. 미합의 상태에서 등록된 임베딩은 통합 시점에 정확도 문제로 드러난다.
2. **모델 가중치 백업** — `muzzle_encoder.onnx`(18MB), `muzzle_encoder.pt`(19MB), `run_manifest.json`이 여전히 VM 디스크에만 존재. VM 소실 시 재학습 필요.
3. **`/muzzle/identify` 프론트 연동** — 등록 다음 단계.
4. **CORS 출처 제한** — `["*"]` → 실제 도메인 목록.
5. **`main.py` 스키마 상수화** — §1 재발 방지.
6. **`ivfflat` 벡터 인덱스** — 등록 데이터 누적 후. 현 규모에서는 순차 검색으로 충분.

### 유지되는 설계 원칙 (다른 파트 대상)

스키마 격리가 해제됐으므로 **명시적 규칙으로 대체**한다.

1. `public.enrollment` / `public.identification_log`를 **직접 SELECT 하지 말 것.** 임계값 판정(0.45)과 미확정 보류 로직이 API 계층에만 존재한다. 직접 쿼리하면 확신도와 무관하게 항상 최근접 개체가 반환되어, 오배정으로 두 개체의 baseline이 동시에 오염된다.
2. `decision == "unconfirmed"`이면 **ID를 부여하지 말 것.** 소는 급이대·음수대를 하루에 반복 방문하므로 재확정 기회가 계속 온다.
3. 입력은 **코 크롭 이미지**여야 한다. 원본에서 코를 찾아 자르는 것은 검출 파트의 역할이다.
4. 개체 참조는 `public.cattle.id`를 FK로 사용할 것.
5. 개체 수 집계 시 `WHERE status = 'active'`로 테스트 데이터를 제외할 것.
6. `pkill -f uvicorn` 금지. 포트를 명시할 것.

---

## 9. 최종 구성

```
[브라우저]
  polite-rock-....azurestaticapps.net   (팀 공식, GitHub 자동 배포)
  hanwoo.koreacentral.cloudapp.azure.com (VM 직접 배포)
        │
        │  https
        ↓
  ┌─ Caddy (443) ─────────────────────────────┐
  │  /muzzle/*  → 127.0.0.1:8001  ★ 비문 API   │
  │  /auth/*, /cattle*, /ocr/*, /rag/* → 8000 │
  │  그 외 → /var/www/hanwoo (프론트)          │
  └───────────────────────────────────────────┘
        ↓
  muzzle-api.service (systemd, Restart=always)
    uvicorn main:app --port 8001
    ├── encoder_onnx.py  (전처리 + ONNX 추론 + L2 정규화)
    └── models/muzzle/weights/muzzle_encoder.onnx
        ↓
  cow-db (Azure PostgreSQL + pgvector)
    public.cattle / public.enrollment / public.identification_log
```

### 공개 엔드포인트

```
GET  https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/health
POST https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/enroll
POST https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/identify
     https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/docs
```

### 변경 파일

| 파일 | 변경 | 백업 |
|---|---|---|
| `~/muzzle_api/main.py` | 테이블 참조, docs_url | `main.py.bak*` |
| `~/muzzle_api/run_test.sh` | 테이블 참조, dotenv 경로 | — |
| `/etc/caddy/Caddyfile` | `/muzzle/*` 블록 추가 | `Caddyfile.bak.0804` |
| `/etc/systemd/system/muzzle-api.service` | 신규 | — |
| `front/src/App.jsx` | 비문 등록 연동 | `App.bak*.jsx` |

### 운영 점검 3종

Caddy 설정을 변경했을 때는 **내 API만이 아니라 세 개를 모두 확인**한다. 하나만 확인하면 남의 파트가 끊긴 것을 놓친다.

```bash
curl -s https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/health   # 비문 API
curl -s https://hanwoo.koreacentral.cloudapp.azure.com/health          # 공통 백엔드
curl -s -o /dev/null -w "%{http_code}\n" https://hanwoo.koreacentral.cloudapp.azure.com/
```

### 보조 스크립트

터미널에서 SQL을 직접 실행할 수 없으므로, 자주 쓰는 조회·갱신을 스크립트로 만들어 뒀다.

| 파일 | 용도 | 실행 |
|---|---|---|
| `~/muzzle_api/check_db.py` | 개체별 등록 벡터 수 조회 | `./venv/bin/python check_db.py` |
| `~/muzzle_api/mark_test.py` | 테스트 개체에 `status='test'` 표시 | `./venv/bin/python mark_test.py` |
| `~/muzzle_api/run_test.sh` | 등록→식별→로그 전 경로 검증 | `./run_test.sh` |

```bash
cd ~/muzzle_api && ./venv/bin/python check_db.py
```

```
   id   가축이력번호       상태   벡터
   68   000158780357   active      2
   67   999900000009     test      1
   62   999900000002     test      3
   61   999900000001     test      3
```
