import os
from dotenv import load_dotenv
load_dotenv("/home/azureuser/muzzle_api/.env")
import psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("UPDATE public.cattle SET status='test' WHERE national_id LIKE '9999%'")
    print(f"{cur.rowcount}건 표시 완료")
    c.commit()
