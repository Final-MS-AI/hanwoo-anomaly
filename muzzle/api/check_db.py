import os
from dotenv import load_dotenv
load_dotenv("/home/azureuser/muzzle_api/.env")
import psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("""
        SELECT c.id, c.national_id, c.status, count(e.id)
        FROM public.cattle c
        LEFT JOIN public.enrollment e ON e.cattle_id = c.id
        GROUP BY c.id ORDER BY c.id DESC LIMIT 10""")
    print(f"{'id':>5} {'가축이력번호':>14} {'상태':>8} {'벡터':>5}")
    for r in cur.fetchall():
        print(f"{r[0]:>5} {r[1]:>14} {str(r[2]):>8} {r[3]:>5}")
