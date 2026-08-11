import os, glob, json, requests
from collections import defaultdict

ROOT = os.path.expanduser("~/data/zenodo6324361/BeefCattle_Muzzle_Individualized")
API, THR = "http://localhost:8001", 0.40
N_ENROLL_IMG, N_QUERY_IMG = 3, 5

pool = json.load(open(os.path.expanduser("~/muzzle_api/eval_cows.json")))
cows = {}
for c in pool:
    imgs = sorted(glob.glob(os.path.join(ROOT, c, "*.jpg")))
    if len(imgs) >= N_ENROLL_IMG + 2:
        cows[c] = imgs
keys = sorted(cows)
split = 45
enrolled, unknowns = keys[:split], keys[split:]
print(f"등록 {len(enrolled)}두 / 미등록 {len(unknowns)}두")
nid = {c: f"9999{str(i).zfill(8)}" for i, c in enumerate(enrolled)}

for c in enrolled:
    fs = [("files", open(p, "rb")) for p in cows[c][:N_ENROLL_IMG]]
    requests.post(f"{API}/muzzle/enroll",
                  data={"national_id": nid[c], "barn_id": "TEST"}, files=fs).raise_for_status()
    [f[1].close() for f in fs]
print("등록 완료")

def q(paths, src):
    out = []
    for p in paths:
        with open(p, "rb") as f:
            out.append(requests.post(f"{API}/muzzle/identify", files={"file": f},
                                     data={"source": src, "threshold": THR}).json())
    return out

top1 = mis = unconf = tot = 0; sc = []
for c in enrolled:
    for r in q(cows[c][N_ENROLL_IMG:N_ENROLL_IMG + N_QUERY_IMG], "test_known"):
        tot += 1
        if r["decision"] == "unconfirmed": unconf += 1
        elif r["national_id"] == nid[c]: top1 += 1; sc.append(r["similarity"])
        else: mis += 1

ut = uw = 0; su = []
for c in unknowns:
    for r in q(cows[c][:3], "test_unknown"):
        ut += 1; su.append(r["similarity"])
        if r["decision"] == "confirmed": uw += 1

print(json.dumps({
  "등록개체_조회수": tot, "Top1정확도": round(top1/tot,4),
  "오배정률": round(mis/tot,4), "미확정보류율": round(unconf/tot,4),
  "정답시_최소유사도": round(min(sc),4) if sc else None,
  "미등록_조회수": ut, "미등록인데_확정": round(uw/ut,4) if ut else None,
  "미등록_최대유사도": round(max(su),4) if su else None,
  "분리간격": round(min(sc)-max(su),4) if sc and su else None,
}, ensure_ascii=False, indent=2))
