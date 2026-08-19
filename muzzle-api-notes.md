
---

## 16. 트랙·시계열 인계 규칙 (2026-08-12 추가)

### 16.1 개체별 시계열은 API 로 받을 것

엔드포인트: `GET /muzzle/cattle/{national_id}/timeline`
질의 파라미터: `start`, `end` (ISO8601), `limit` (기본 2000), `include_test` (기본 false)

응답은 두 층이다. 필요한 해상도만 쓰면 된다.

| 필드 | 내용 |
|---|---|
| `segments` | 트랙 단위 요약 — 시작·종료 시각, 관측 수, 유사도 |
| `observations` | 프레임 단위 원시 데이터 — `ts`, `bbox`, `conf`, `behavior` |

**`v_identified_track_observation` 뷰를 직접 조회하지 말 것.** 이유는 둘이다.

1. **테스트 데이터가 섞인다.** 검증용 데이터는 삭제하지 않고 `session_id` 를
   `test_` 로 시작시켜 격리한다. 필터는 뷰가 아니라 이 엔드포인트에 있다
   (뷰는 팀 공용이므로 내 사정으로 필터를 걸지 않았다).
2. **바인딩의 소급 적용을 놓칠 수 있다.** 개체번호는 관측 행에 기록되지 않고
   `track_identity_binding` 1행이 JOIN 으로 소급 적용한다. 직접 짠 쿼리가 이
   JOIN 을 빠뜨리면 식별 이전 구간이 통째로 비어 보인다.

### 16.2 트랙 테이블 소유권

| 테이블 | 소유 | 비고 |
|---|---|---|
| `track_segment` | 개체 식별 파트 | 카메라·세션·트랙 단위 구간 |
| `track_observation` | 개체 식별 파트 | 프레임 단위. `behavior` 는 이상행동 파이프라인이 채운다 |
| `track_identity_binding` | 개체 식별 파트 | **역전파의 핵심.** 트랙당 활성 바인딩 1행 |
| `v_identified_track_observation` | 개체 식별 파트 | 위 3개를 JOIN 한 조회용 뷰 |

`track_` 접두어는 전부 개체 식별 파트 소유다. INSERT/UPDATE 가 필요하면 API 로
요청할 것. 특히 `track_identity_binding` 에 직접 INSERT 하면 임계값 검사·중복
방지·이력 보존이 모두 우회된다.

### 16.3 세션 ID 접두어 규약

- `test_20260812023011-e3eca6` — 검증용. timeline 기본 응답에서 제외
- `demo_...` — 발표용. 노출
- `20260812023011-e3eca6` — 실데이터. 노출

검증 데이터는 **삭제하지 않고 남긴다.** 지우면 재현에 매번 추론을 다시 돌려야
하고, 발표 시 "그때 그 결과"를 보여줄 수 없다. `is_test` 컬럼을 새로 만들지
않은 것은 팀 공용 DB 에서 `ALTER TABLE` 을 피하기 위해서다 — `session_id` 는
이미 "추적 1회 실행 단위"라는 의미를 갖고 있어 규약과 어긋나지 않는다.


---

## 17. E2E 오케스트레이터와 핸드오프 (2026-08-14)

### 17.1 한 명령 관통

    muzzle/tracking/run_e2e.py
      --wide <전경 영상, GPU VM 경로>
      --choke <초크포인트 영상, DB VM 경로. ROI 등록된 것만>
      --start-time <전경 기준 시각>  --choke-start-time <초크 기준 시각>
      --window 2.0  --zone top  --anchor topright  --stride 1

전경과 초크포인트의 기준 시각을 **따로 받는다.** 카메라마다 녹화 시작이 다른
것이 현실이고, 이것을 맞추는 것이 핸드오프의 전제다.

`--jsonl` 로 이미 받아둔 JSONL 을 재사용할 수 있으나 **적재가 다시 일어난다**
(§17.3). 정합 로직 시험용이며 실행 결과로 쓰지 말 것.

### 17.2 트랙 테이블에 쓰는 경로는 셋뿐이다

| 경로 | 용도 |
|---|---|
| `track_load.py <jsonl>` | 적재 |
| `POST /muzzle/tracks/{id}/bind` | 바인딩 |
| `run_e2e.py` | 위 둘을 순서대로 부른다 |

`track_identity_binding` 에 직접 INSERT 하면 임계값 검사·중복 방지·이력 보존이
모두 우회된다(§7.7).

### 17.3 ★ 같은 JSONL 을 두 번 적재해도 안전하다 (2026-08-18 갱신)

`track_load.py` 의 두 INSERT 는 성격이 다르다.

    track_segment      ... ON CONFLICT DO UPDATE    멱등이다
    track_observation  ... ON CONFLICT DO NOTHING   멱등이다 (2026-08-18 부터)

**2026-08-18 이전에는 관측 INSERT 에 제약이 없었다.** 같은 `session_id` 로 두 번
적재하면 세그먼트는 합쳐지는데 관측만 쌓여, `frame_count` 와 실제 관측 수가
어긋나고 행동 통계가 조용히 2배가 됐다 (실측 379 -> 758 로 재현). 지금은 유일
인덱스가 DB 층에서 막고 `ON CONFLICT DO NOTHING` 이 예외 없이 흘린다 (17.7).

**그래도 세션은 실행마다 새로 줄 것.** `run_e2e.py` 는 그렇게 한다. 인덱스는
사고를 막는 장치이지 세션 설계를 대신하지 않으며, `frame_idx` 가 NULL 인 행은
인덱스로 막히지 않는다.

### 17.4 핸드오프 판정 — 시간 + 구역

    B 카메라가 T 시각에 개체 확정
      -> A 카메라에서 T±window 에 살아 있고
         그 사이 구역 안에 들어온 적이 있는 트랙을 찾는다
      -> 정확히 1건이면 바인딩, 0건 또는 2건 이상이면 보류

**시간 정합만으로는 후보가 좁혀지지 않는다.** 실측에서 23트랙 중 10건이 남았고
창을 3초에서 1초로 줄여도 1건만 줄었다.

행동 라벨(`feeding`)로 좁히는 것도 가능하지만 (`--require-behavior feeding`)
**기본값은 쓰지 않는다.** 그 라벨은 급이대 부근에서 고개를 숙이면 붙는 것으로
확인됐고, 이상행동 파트의 모델이 갱신되면 조용히 바뀐다. 전량 2832건 대조에서
구역 판정과의 일치율은 90.4%, 라벨 재현은 47.2% 였다 — 라벨만 참인 201건은
과검출이며 구역 쪽이 더 보수적이다.

### 17.5 구역 정의 — `muzzle/tracking/zones.py`

정규화(0~1) 다각형 + ray casting. 외부 의존이 없다. **좌표는 정규화, bbox 는
픽셀**이므로 `frame` 크기를 함께 저장해 변환한다.

    ZONES = {"top": {"frame": (1920, 1080), "poly": [(x, y), ...]}}

구역은 `muzzle/tools/zone_pick.html` 로 CCTV 첫 프레임 위에 클릭해 찍는다.
급이대가 화면에서 사선이면 사각형으로는 무관한 바닥이 함께 들어오므로 다각형을
쓴다. 장기적으로는 농가가 서비스 최초 이용 시 지정하는 화면으로 옮긴다.

### 17.6 ★ 판정 기준점 (`--anchor`)

bbox 는 **좌상단 기준 `(x, y, w, h)` 이고 픽셀**이다. 실측으로 확인했다 —
중심 가정이면 `x - w/2` 가 음수가 되어 프레임 밖으로 나간다.

기본값은 `topright` 다. **소는 몸을 급이대에 넣지 않고 고개만 넣으므로**
`bottom`(발)·`center`(몸통)은 구역 안에 들어오지 않는다. 실측에서 두 기준 모두
후보 0건이었다. 급이대가 좌하->우상 사선이고 소가 그 아래에서 위를 향하므로
머리가 bbox 우상단에 온다.

카메라 배치나 급이대 방향이 다르면 달라진다. 선택지는
`topright / top / topleft / bottom / center / touch` 이며, 새 영상에서는
**추측하지 말고 6가지를 전부 계산해 후보 수를 비교할 것.**

### 17.7 ★ 재적재 멱등성 — 이제 DB 가 강제한다 (2026-08-18)

**17.3 은 규칙이었고 강제 수단이 없었다.** 그 규칙을 쓰면서 재현해 둔 데이터
(`demo_20260814070456-136a18`, 379 -> 758)가 정리되지 않은 채 남았고, 8/18
정합성 검사에서 중복 (세그먼트, 프레임) 쌍 2,832건으로 다시 잡혔다.
**현상을 알고 재현까지 해두고도 정리와 강제가 없어 4일간 오염으로 남았다.**

**왜 눈으로 못 잡았나.** 제약이 부모 테이블에만 있었다.

| 테이블 | 제약 (사고 당시) | 재실행 시 |
|---|---|---|
| `track_segment` | `UNIQUE (camera_id, session_id, track_id)` | 중복 안 됨 |
| `track_observation` | **없음** | **두 배가 된다** |

세그먼트가 중복되지 않으므로 `frame_count` 는 정상값을 유지한다. 세그먼트
목록을 봐도 프레임 수를 봐도 정상으로 보인다. **관측 행수를 고유 프레임
수와 비교해야만 드러난다.** 그리고 중복은 `affected_observations` 를 키우는
방향으로 깨지므로, 모르고 보면 오히려 더 잘 된 것처럼 보인다.

**조치 — 두 층 모두.** 한 층만 고치면 안 된다.

| 층 | 조치 | 없으면 |
|---|---|---|
| DB | `CREATE UNIQUE INDEX uq_track_obs_segment_frame (segment_id, frame_idx)` | 중복이 다시 들어간다 |
| 코드 | `INSERT ... ON CONFLICT (segment_id, frame_idx) DO NOTHING` | 재실행이 예외로 죽는다 |

순서가 있다. 중복을 지우기 전에 인덱스를 만들면 생성 자체가 실패하고,
인덱스가 없으면 `ON CONFLICT` 가 참조할 대상이 없다.

**`DO UPDATE` 와 `DO NOTHING` 을 섞어 쓴 이유.** `track_segment` 는
`DO UPDATE` 여야 한다 — `DO NOTHING` 은 충돌 시 행을 반환하지 않으므로
`RETURNING id` 가 비고 `.fetchone()[0]` 에서 `TypeError` 로 죽는다.
멱등화를 의도했는데 오히려 예외를 만드는 흔한 함정이다.

    track_segment      ON CONFLICT ... DO UPDATE    기존 id 를 돌려준다
    track_observation  ON CONFLICT ... DO NOTHING   조용히 흘린다

**실측.** 5프레임 JSONL 을 같은 세션으로 두 번 적재했다.

    1회차  종료코드 0  ->  세그먼트 1 / 관측 5 / 고유프레임 5
    2회차  종료코드 0  ->  세그먼트 1 / 관측 5 / 고유프레임 5

2회차도 `segment 154` 를 동일하게 반환했다. `track_load.py` 는 자기가 5건을
넣었다고 출력하지만 DB 는 5행을 유지한다. 그것이 정상 동작이다.

**한계.** Postgres 는 NULL 을 서로 다른 값으로 취급하므로 `frame_idx` 가
NULL 인 행은 이 인덱스로 막히지 않는다. `track_load.py` 는 항상 값을
채우므로 현재 문제되지 않으나 알려진 범위로 기록한다.

**17.3 은 여전히 유효하다.** DB 가 막아주더라도 세션 ID 는 실행마다 새로
만드는 것이 맞다. 인덱스는 사고를 막는 장치이지 설계를 대신하지 않는다.

### 17.8 정합성 검사 — `muzzle/tools/verify_backprop.py` (2026-08-18)

역전파는 UPDATE 가 아니라 JOIN 으로 설계했다(16.2). 조회하면 값이 나오므로
**깨질 때도 정상처럼 보인다.** 불변식 6개를 코드로 고정해 검사한다.

    python muzzle/tools/verify_backprop.py                  # test_ 세션 제외
    python muzzle/tools/verify_backprop.py --include-test   # 포함

| # | 검사 | 깨지면 |
|---|---|---|
| 1 | 뷰 행 수 == 관측 행 수 | JOIN 이 행을 복제 중 (활성 바인딩 중복) |
| 2 | 세그먼트당 활성 바인딩 <= 1 | 한 트랙에 개체 2개 |
| 3 | 바인딩된 세그먼트에 NULL 개체번호 0건 | **역전파가 안 먹었다** |
| 4 | 최소 `frame_idx` 관측이 개체번호 보유 | 소급이 부분 적용 |
| 5 | 세그먼트 내 `frame_idx` 중복 0건 | **중복 적재** |
| 6 | 활성 바인딩 유사도 >= 0.70 | 임계값 방어가 뚫렸다 |

**4번이 역전파의 직접 증거다** — 코가 보인 시점보다 앞선 프레임이 개체번호를
갖는가를 묻는다. 소급이 실제로 일어났다는 것을 이 검사만 확인할 수 있다.

**하나라도 깨지면 종료코드 1 을 낸다.** 사람이 출력을 읽어야만 알 수 있게
만들면 도구의 값이 절반으로 준다. 배포 스크립트나 CI 에 그대로 붙일 수 있다.

**DB 를 조작할 때는 `import psycopg as pg` 를 쓸 것.** venv 에 `psycopg2` 는
없다 (psycopg 3.3.4). 이 검사 도구도 같은 규약을 따른다.

### 17.9 ★ 정적 페이지 배포 — 별도 루트를 쓴다 (2026-08-18)

`zone-setup.html` 과 `muzzle-timeline.html` 은 **`/var/www/hanwoo-static/` 에 있다.**
`/var/www/hanwoo/` 가 아니다.

이유는 하나다. 프론트 배포가 `rsync -a --delete dist/ /var/www/hanwoo/` 이고,
이 명령은 **`dist` 에 없는 파일을 정의상 제거한다.** 8/17 에 `/var/www/hanwoo/` 에
직접 올린 두 장이 그날 밤 배포로 삭제됐다.

Caddyfile 에서 `handle /devices/*` 와 최종 `handle` 사이에 다음이 있다.

    @muzzleStatic path /zone-setup.html /muzzle-timeline.html
    handle @muzzleStatic {
            root * /var/www/hanwoo-static
            file_server
    }

**URL 은 바뀌지 않았다.** 갱신은 `sudo cp` 한 줄이고, React 재빌드가 필요 없다.

### 17.10 ★★ SPA 폴백에서 상태 코드는 존재 증명이 아니다

최종 `handle` 블록에 `try_files {path} /index.html` 이 있다. **파일이 없어도
200 이 나오고, 내용은 React 껍데기(495 bytes)다.**

    curl -o /dev/null -w "%{http_code}"  ->  200      <- 파일이 없어도 이렇게 나온다
    curl ... | wc -c                     ->  495      <- 이것이 진실

8/17 배포 확인이 이 방식으로 통과했고, 그날 밤 파일이 삭제된 뒤에도 계속 200 이
나왔다. **하루 동안 소실을 탐지하지 못했다.**

검증은 반드시 **바이트 수 또는 내용**으로 한다.

    local=$(wc -c < ~/hanwoo-yeri/muzzle/tools/zone_setup.html)
    served=$(curl -s https://hanwoo.koreacentral.cloudapp.azure.com/zone-setup.html | wc -c)
    # local == served 여야 한다. 495 면 폴백이다.

같은 현상이 Azure Static Web Apps 에서도 재현된다. SWA 에는 이 정적 파일이 없으므로
링크를 눌러도 `navigationFallback` 이 대시보드를 띄운다. **버튼 동작 확인은 VM 에서만
유효하다.**

### 17.11 프론트 배포 판단 — 해시 판별식

VM(`/var/www/hanwoo`)은 자동 배포가 없다. 손으로 빌드·`rsync` 해야 하고, **지금
배포본에 커밋되지 않은 작업이 섞여 있으면 내가 배포하는 순간 그것이 사라진다.**

Vite 자산 파일명은 내용 해시다. 이것으로 측정한다.

    cd ~/hanwoo-yeri/front && npm run build
    ls dist/assets/*.js
    curl -s https://hanwoo.koreacentral.cloudapp.azure.com/ | grep -o 'index-[A-Za-z0-9_-]*\.js'

| 결과 | 의미 | 조치 |
|---|---|---|
| 일치 | 배포본 = 깨끗한 main | 배포해도 잃는 것이 없다 |
| 불일치 | 미커밋 작업이 프로덕션에 있다 | 배포하면 사라진다 |

**배포는 `--delete` 없이 한다.** Vite 자산은 해시 파일명이라 덮어써도 충돌하지 않고,
지우면 손으로 올린 파일이 함께 날아간다. 배포 전 `sudo cp -a` 로 백업한다.

**배포해도 팀원 소스는 무손상이다.** 배포는 빌드 산출물을 웹서버 폴더에 복사하는
것이고 git 작업 폴더를 건드리지 않는다. 화면에 보이는 번들만 바뀐다.

### 17.12 프론트 화면 확인은 API 가 붙은 환경에서만 된다

`npm run preview` 는 API 를 프록시하지 않는다. `getCurrentUser()` 가 실패해
`user` 가 `undefined` 로 남고 로딩 화면에서 멈춘다. 게이트를 임시로 꺼도 그 뒤
화면이 API 에 의존하면 같은 벽에 부딪힌다.

**우회로가 없다.** VM 배포 또는 팀원 배포를 기다린다.

### 17.13 ★ 구역 지정 화면은 iframe 으로 임베드돼 있다 (2026-08-19)

`/inference` 탭(하단 라벨 **구역 지정**)이 `zone-setup.html` 을 iframe 으로
품고 있다. 버튼으로 페이지를 넘기던 방식에서 바뀌었다.

**왜 포팅하지 않았나.** 캔버스를 React 컴포넌트로 옮기면 8/17 에 실측 검증한
다각형 좌표계·422 거부 검사·판정 기준점 로직을 **전부 재증명**해야 한다.
같은 오리진 iframe 은 그 코드를 한 글자도 건드리지 않고 앱 안으로 들여온다.
WebView 에서도 같은 오리진 문서라 그대로 뜬다.

**경로는 `/inference` 그대로다.** 하단 탭의 라벨과 아이콘만 바꿨다. 경로를
바꾸면 라우트 정의·북마크·앱 딥링크가 전부 영향을 받는다.

**임베드 때문에 정적 파일에서 제거한 것들**

- `<div class="top">` — 로고와 복귀 링크. 바깥 카드가 이미 제목을 갖고 있어
  액자 속 액자가 된다. 특히 복귀 링크는 누르면 **iframe 안에 대시보드가 또
  열린다.** 하단 탭이 이동을 담당하므로 역할이 없다.
- `<div class="steps">` — 1/2/3 단계 표시. 같은 이유.

**높이는 두 층에서 관리한다.**

바깥: `onLoad` 에서 `contentWindow.document.documentElement.scrollHeight` 를
읽어 iframe 높이를 맞추고, 이미지 업로드로 캔버스가 커질 때를 위해 주기 갱신한다.

안쪽: 그것만으로는 여백이 남는다. **계산 대상인 문서 자체가 `min-height` 와
하단 패딩을 갖고 있기 때문이다.** `<style id="embed-fit">` 로 이를 무력화한다.

    html, body { min-height: 0 !important; height: auto !important; padding: 0 !important; }
    .wrap { min-height: 0 !important; padding-bottom: 0 !important; overflow: hidden; }

### 17.14 ★★ 검증 명령을 `&&` 로 잇지 않는다

두 방향으로 거짓 결과가 나온다.

**파이프는 실패를 숨긴다.** `npm run build 2>&1 | head -14 && git commit ...` 은
파이프의 종료 코드가 `head` 것이라 **빌드가 실패해도 커밋·push 가 진행된다.**
실제로 JSX 오류가 있는 코드가 PR 까지 올라갔다.

**`grep -c` 는 0 일 때 실패 종료 코드를 낸다.** 체인 중간에 두면 뒤 명령이
실행되지 않는데, `$(...)` 는 먼저 평가되므로 **이전 실행이 남긴 로그 파일을 읽어
"빌드 성공"을 출력**한다.

올바른 형태 — 한 줄씩 독립 실행한다.

    cd ~/hanwoo-yeri/front
    npm run build > /tmp/b.log 2>&1
    grep -c "built in" /tmp/b.log     # 1 이어야 함
    head -16 /tmp/b.log               # 0 이면 여기에 원인이 있다

### 17.15 프론트 배포는 여러 사람이 손으로 한다 — 덮어쓰기가 일어난다

VM(`/var/www/hanwoo`)은 자동 배포가 없다. **내가 배포해도 몇 분 뒤 다른 사람의
빌드로 덮인다.** 화면이 옛 버전으로 보이면 "코드가 안 들어갔다"고 판단하기 전에
**누가 그사이 배포했는지**를 먼저 의심한다.

해시 판별식(§17.11)은 "지금 무엇이 올라가 있는가"를 재는 도구이지 덮어쓰기를
막지는 못한다. **배포 전 공유가 유일한 대책이다.**

`/var/www/hanwoo-static/` 의 정적 파일은 이 문제에서 자유롭다(§17.9).