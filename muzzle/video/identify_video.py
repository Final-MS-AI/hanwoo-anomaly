import sys, os, cv2, numpy as np, requests, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muzzle_boxes as MB

API = "https://hanwoo.koreacentral.cloudapp.azure.com/muzzle/identify"
DIAG = 0.30      # 1위 후보를 보기 위한 진단용
OPER = 0.70      # 실제 운영 임계값
SCALES = [0.82, 0.9, 1.0, 1.1, 1.22]
MATCH_MIN = 0.32

def norm(e):
    e = list(e)
    return tuple(e) if len(e) == 5 else (0, *e)

def pick(path, ent, topn):
    f0, x1, y1, x2, y2 = ent
    cap = cv2.VideoCapture(path)
    W, H = int(cap.get(3)), int(cap.get(4))
    if max(x1, y1, x2, y2) <= 1.0:
        X1, Y1, X2, Y2 = int(x1*W), int(y1*H), int(x2*W), int(y2*H)
    else:
        X1, Y1, X2, Y2 = map(int, (x1, y1, x2, y2))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(f0)); ok, fr = cap.read()
    if not ok: sys.exit(f"프레임 {f0} 읽기 실패")
    tg = cv2.cvtColor(fr[Y1:Y2, X1:X2], cv2.COLOR_BGR2GRAY)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    out, i = [], 0
    while True:
        ok, fr = cap.read()
        if not ok: break
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY); best = None
        for s in SCALES:
            t = cv2.resize(tg, None, fx=s, fy=s)
            if t.shape[0] >= g.shape[0] or t.shape[1] >= g.shape[1]: continue
            _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED))
            if best is None or mx > best[0]: best = (mx, loc, t.shape)
        if best and best[0] >= MATCH_MIN:
            mx, (lx, ly), (th, tw) = best
            c = fr[ly:ly+th, lx:lx+tw]
            if c.size:
                sh = cv2.Laplacian(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
                out.append((float(mx)*float(np.log1p(sh)), i, float(mx), c))
        i += 1
    cap.release(); out.sort(key=lambda z: -z[0])
    return out[:topn]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--topn", type=int, default=8)
    a = ap.parse_args()
    stem = os.path.basename(a.video).split(".")[0]
    if stem not in MB.BOXES:
        print("ROI 없음. 사용 가능한 키:"); [print("  ", k) for k in MB.BOXES]; sys.exit(1)
    picked = pick(a.video, norm(MB.BOXES[stem]), a.topn)
    print(f"\n영상 {stem} | 채택 {len(picked)}장 | 운영 임계값 {OPER}")
    print("-"*66)
    votes = {}
    for _, idx, mx, img in picked:
        _, buf = cv2.imencode(".jpg", img)
        r = requests.post(API, files={"file": ("f.jpg", buf.tobytes(), "image/jpeg")},
                          data={"source": "video", "threshold": DIAG}, timeout=30)
        if r.status_code != 200:
            print(f"frame {idx:4d}  HTTP {r.status_code}"); continue
        j = r.json(); nid = j.get("national_id"); sim = j.get("similarity", 0.0)
        ok = sim >= OPER
        print(f"frame {idx:4d} match {mx:.2f} | 1위 {nid} sim {sim:.4f} | "
              + ("✅ 확정" if ok else "⏸ 보류"))
        if ok: votes[nid] = votes.get(nid, 0.0) + sim
    print("-"*66)
    if votes:
        w = max(votes, key=votes.get)
        print(f"최종 판정: {w}   (가중표 {', '.join(f'{k}:{v:.2f}' for k,v in votes.items())})")
    else:
        print("최종 판정: 미확정 — 확정 프레임 0장. ID를 부여하지 않는다.")
