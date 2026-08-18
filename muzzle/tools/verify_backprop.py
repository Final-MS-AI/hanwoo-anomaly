"""ID 역전파 정합성 검사. 불변식 6개를 확인하고 하나라도 깨지면 종료코드 1."""
import os, sys, psycopg as pg

def get_dsn():
    p = os.path.expanduser("~/muzzle_api/.env")
    env = {}
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    d = env.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not d:
        sys.exit("DATABASE_URL 을 찾지 못했다")
    return d

EXCLUDE_TEST = "--include-test" not in sys.argv
SEG_FILTER = ""
if EXCLUDE_TEST:
    SEG_FILTER = "AND s.session_id NOT LIKE 'test_%'"

fails = []

def check(n, title, sql, ok_pred, fmt):
    cur.execute(sql)
    rows = cur.fetchall()
    ok = ok_pred(rows)
    print("[%s] %d. %s" % ("PASS" if ok else "FAIL", n, title))
    print("       -> " + fmt(rows))
    if not ok:
        fails.append(n)
        for r in rows[:10]:
            print("       !! " + str(r))

conn = pg.connect(get_dsn())
cur = conn.cursor()

print("=" * 62)
print(" ID 역전파 정합성 검사   (test_ 세션 %s)"
      % ("제외" if EXCLUDE_TEST else "포함"))
print("=" * 62)

# --- 현황 요약 (검사 아님) -------------------------------------------
cur.execute("""SELECT count(*) FROM track_segment s WHERE 1=1 %s""" % SEG_FILTER)
n_seg = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM track_identity_binding b
               JOIN track_segment s ON s.id=b.segment_id
               WHERE b.is_active %s""" % SEG_FILTER)
n_bind = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM track_observation o
               JOIN track_segment s ON s.id=o.segment_id WHERE 1=1 %s""" % SEG_FILTER)
n_obs = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM v_identified_track_observation v
               JOIN track_segment s ON s.id=v.segment_id
               WHERE v.national_id IS NOT NULL %s""" % SEG_FILTER)
n_named = cur.fetchone()[0]
print("\n[현황] 세그먼트 %d / 활성바인딩 %d / 관측 %d / 개체번호 부여된 관측 %d"
      % (n_seg, n_bind, n_obs, n_named))
print("       역전파로 확보된 관측 비율: %.1f%%\n"
      % (100.0 * n_named / n_obs if n_obs else 0.0))

# --- 1. 뷰가 행을 복제하지 않는가 -----------------------------------
check(1, "뷰 행 수 == 관측 행 수 (JOIN 복제 없음)",
      """SELECT (SELECT count(*) FROM track_observation),
                (SELECT count(*) FROM v_identified_track_observation)""",
      lambda r: r[0][0] == r[0][1],
      lambda r: "관측 %d / 뷰 %d" % (r[0][0], r[0][1]))

# --- 2. 세그먼트당 활성 바인딩 1개 이하 -----------------------------
check(2, "세그먼트당 활성 바인딩 <= 1",
      """SELECT segment_id, count(*) FROM track_identity_binding
         WHERE is_active GROUP BY 1 HAVING count(*) > 1""",
      lambda r: len(r) == 0,
      lambda r: "위반 세그먼트 %d건" % len(r))

# --- 3. ★ 바인딩된 세그먼트에 NULL 개체번호가 없는가 ----------------
check(3, "★ 바인딩된 세그먼트의 모든 관측이 개체번호 보유 (역전파 본체)",
      """SELECT v.segment_id, count(*)
         FROM v_identified_track_observation v
         JOIN track_segment s ON s.id = v.segment_id
         WHERE v.national_id IS NULL
           AND v.segment_id IN (SELECT segment_id FROM track_identity_binding
                                WHERE is_active)
           %s
         GROUP BY 1""" % SEG_FILTER,
      lambda r: len(r) == 0,
      lambda r: "NULL 남은 세그먼트 %d건" % len(r))

# --- 4. ★ 첫 프레임이 개체번호를 갖는가 (소급 증거) -----------------
check(4, "★ 바인딩된 세그먼트의 최소 frame_idx 관측이 개체번호 보유",
      """SELECT v.segment_id, v.national_id, min(v.frame_idx), count(*)
         FROM v_identified_track_observation v
         JOIN track_segment s ON s.id = v.segment_id
         WHERE v.national_id IS NOT NULL %s
         GROUP BY 1,2 ORDER BY 1""" % SEG_FILTER,
      lambda r: len(r) > 0,
      lambda r: "; ".join("seg %s -> %s (frame %s부터 %s건)"
                          % (a, b, c, d) for a, b, c, d in r) or "바인딩 0건")

# --- 5. ★ 중복 적재 탐지 (세션 재사용 사고) -------------------------
check(5, "★ 세그먼트 내 frame_idx 중복 없음 (중복 적재 탐지)",
      """SELECT o.segment_id, o.frame_idx, count(*)
         FROM track_observation o
         JOIN track_segment s ON s.id = o.segment_id
         WHERE o.frame_idx IS NOT NULL %s
         GROUP BY 1,2 HAVING count(*) > 1
         ORDER BY 3 DESC""" % SEG_FILTER,
      lambda r: len(r) == 0,
      lambda r: "중복 (세그먼트, 프레임) 쌍 %d건" % len(r))

# --- 6. 바인딩 유사도가 임계값 이상인가 -----------------------------
check(6, "활성 바인딩 유사도 >= 0.70 (임계값 방어)",
      """SELECT b.segment_id, b.national_id, b.similarity
         FROM track_identity_binding b
         JOIN track_segment s ON s.id = b.segment_id
         WHERE b.is_active AND (b.similarity IS NULL OR b.similarity < 0.70) %s""" % SEG_FILTER,
      lambda r: len(r) == 0,
      lambda r: "임계값 미달 바인딩 %d건" % len(r))

print("\n" + "=" * 62)
if fails:
    print(" 결과: FAIL  — 깨진 불변식 %s" % fails)
else:
    print(" 결과: 전체 PASS  (불변식 6/6)")
print("=" * 62)

cur.close(); conn.close()
sys.exit(1 if fails else 0)
