import os, sys, cv2, requests
from fastapi import APIRouter, HTTPException
sys.path.insert(0, os.path.expanduser("~/muzzle_api/video"))
from identify_video import pick, norm
import muzzle_boxes as MB

VIDEO_DIR = os.path.expanduser("~/data/muzzle_eval/query")
SELF = "http://127.0.0.1:8001/muzzle/identify"   # Caddy 우회, 내부 직통
OPER = 0.70
router = APIRouter()

@router.get("/videos")
def list_videos():
    if not os.path.isdir(VIDEO_DIR): return {"videos": []}
    return {"videos": sorted(f for f in os.listdir(VIDEO_DIR)
                             if f.endswith(".mp4") and f.split(".")[0] in MB.BOXES)}

@router.post("/videos/{name}/identify")
def identify_video(name: str, topn: int = 8):
    stem = name.split(".")[0]
    if stem not in MB.BOXES:
        raise HTTPException(404, "roi_not_found")
    path = os.path.join(VIDEO_DIR, name if name.endswith(".mp4") else name + ".mp4")
    if not os.path.exists(path):
        raise HTTPException(404, "video_not_found")
    frames, votes = [], {}
    for _, idx, mx, img in pick(path, norm(MB.BOXES[stem]), topn):
        _, buf = cv2.imencode(".jpg", img)
        r = requests.post(SELF, files={"file": ("f.jpg", buf.tobytes(), "image/jpeg")},
                          data={"source": "video", "threshold": 0.30}, timeout=30)
        if r.status_code != 200: continue
        j = r.json(); nid, sim = j.get("national_id"), j.get("similarity", 0.0)
        ok = sim >= OPER
        frames.append({"frame": idx, "match": round(mx, 3), "top1": nid,
                       "similarity": sim, "confirmed": ok})
        if ok: votes[nid] = votes.get(nid, 0.0) + sim
    win = max(votes, key=votes.get) if votes else None
    return {"video": stem, "threshold": OPER, "frames": frames, "votes": votes,
            "decision": "confirmed" if win else "unconfirmed", "national_id": win}
