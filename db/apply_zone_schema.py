"""schema_zone.sql 을 적용하고 결과를 검증한다. 멱등이므로 여러 번 실행해도 안전하다."""
import os
import psycopg
from dotenv import load_dotenv

ENV = "/home/azureuser/muzzle_api/.env"
SQL = "/home/azureuser/hanwoo-yeri/db/schema_zone.sql"

# stdin 실행 시 find_dotenv() 가 죽으므로 경로를 명시한다.
load_dotenv(ENV)
url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit(f"DATABASE_URL 없음. {ENV} 확인할 것")

sql = open(SQL, encoding="utf-8").read()
stmts = [s.strip() for s in sql.split(";") if s.strip()]
print("문장 수:", len(stmts))

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        for i, s in enumerate(stmts, 1):
            cur.execute(s)
            print(f"  [{i}] ok  {s.splitlines()[0][:60]}")
        conn.commit()
        cur.execute(
            "SELECT id, name, device_id, camera_id, frame_w, frame_h, anchor,"
            " jsonb_array_length(poly), is_active"
            " FROM public.track_zone ORDER BY id"
        )
        print("--- track_zone ---")
        for r in cur.fetchall():
            print(r)