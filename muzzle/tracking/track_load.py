"""JSONL → Postgres 적재."""
import json, os, sys
from collections import defaultdict

import psycopg as pg
from dotenv import load_dotenv

load_dotenv("/home/azureuser/muzzle_api/.env")

path = sys.argv[1]
rows = [json.loads(l) for l in open(path) if l.strip()]
if not rows:
    sys.exit("빈 파일")

groups = defaultdict(list)
for r in rows:
    groups[(r["camera_id"], r["session_id"], r["track_id"])].append(r)

with pg.connect(os.getenv("DATABASE_URL")) as c:
    for (cam, sess, tid), obs in sorted(groups.items()):
        obs.sort(key=lambda r: r["frame_idx"])
        seg_id = c.execute("""
            INSERT INTO public.track_segment
              (camera_id, session_id, track_id, started_at, ended_at, frame_count, source_video)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (camera_id, session_id, track_id) DO UPDATE
              SET ended_at = EXCLUDED.ended_at, frame_count = EXCLUDED.frame_count
            RETURNING id
        """, (cam, sess, tid, obs[0]["ts"], obs[-1]["ts"], len(obs),
              obs[0].get("source_video"))).fetchone()[0]

        c.cursor().executemany("""
            INSERT INTO public.track_observation
              (segment_id, ts, frame_idx, bbox_x, bbox_y, bbox_w, bbox_h, conf)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, [(seg_id, o["ts"], o["frame_idx"], o["bbox_x"], o["bbox_y"],
               o["bbox_w"], o["bbox_h"], o["conf"]) for o in obs])

        print(f"segment {seg_id}  camera={cam}  track={tid}  관측={len(obs)}")
    c.commit()

print(f"적재 완료 — 트랙 {len(groups)}개")