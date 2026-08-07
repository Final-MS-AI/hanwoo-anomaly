import os, glob, csv
import numpy as np, cv2, onnxruntime as ort

ONNX  = os.path.expanduser("~/models/muzzle/weights/muzzle_encoder.onnx")
CROPS = os.path.expanduser("~/data/muzzle_eval/crops")
OUT   = os.path.expanduser("~/data/muzzle_eval/results"); os.makedirs(OUT, exist_ok=True)
ENROLL_PER_COW = 5
THRS   = [0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.70]
SCALES = [1.0, 0.5, 0.25, 0.125]

sess = ort.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
INP  = sess.get_inputs()[0].name
CL   = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
MEAN = np.array([0.485,0.456,0.406], np.float32)
STD  = np.array([0.229,0.224,0.225], np.float32)

def preprocess(bgr):
    rgb  = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    g    = CL.apply(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    x    = np.stack([g,g,g], -1)
    h, w = x.shape[:2]; s = 255.0/min(h,w)
    x    = cv2.resize(x, (max(224,int(round(w*s))), max(224,int(round(h*s)))))
    h, w = x.shape[:2]
    x    = x[(h-224)//2:(h-224)//2+224, (w-224)//2:(w-224)//2+224]
    x    = (x.astype(np.float32)/255.0 - MEAN)/STD
    return np.transpose(x,(2,0,1))[None].astype(np.float32)

def embed(bgr):
    v = sess.run(None, {INP: preprocess(bgr)})[0][0]
    return v/(np.linalg.norm(v)+1e-12)

def degrade(img, s):
    if s >= 1.0: return img
    h, w = img.shape[:2]
    sm = cv2.resize(img, (max(8,int(w*s)), max(8,int(h*s))), interpolation=cv2.INTER_AREA)
    return cv2.resize(sm, (w,h), interpolation=cv2.INTER_LINEAR)

def conf_of(p):
    try: return float(os.path.basename(p).rsplit("_c",1)[1][:-4])
    except: return 0.0

# ── 갤러리 (등록) : API와 동일하게 임베딩 평균 후 재정규화
gallery = {}
for cow in sorted(os.listdir(os.path.join(CROPS,"enroll"))):
    fs = sorted(glob.glob(os.path.join(CROPS,"enroll",cow,"*.jpg")), key=conf_of, reverse=True)[:ENROLL_PER_COW]
    if not fs: continue
    v = np.mean([embed(cv2.imread(f)) for f in fs], axis=0)
    gallery[cow] = v/(np.linalg.norm(v)+1e-12)
    print(f"[등록] {cow}: {len(fs)}장")
cows = sorted(gallery)
print(f"갤러리 {len(cows)}두 → 무작위 추측 = {1/len(cows):.3f}\n")

pos_files = [(c,f) for c in sorted(os.listdir(os.path.join(CROPS,"query")))
             for f in glob.glob(os.path.join(CROPS,"query",c,"*.jpg"))]
neg_files = [f for c in sorted(os.listdir(os.path.join(CROPS,"unknown")))
             for f in glob.glob(os.path.join(CROPS,"unknown",c,"*.jpg"))]
print(f"조회: 등록개체 {len(pos_files)}건 / 미등록개체 {len(neg_files)}건\n")

def run(scale):
    pos, neg = [], []
    for cow, f in pos_files:
        e = embed(degrade(cv2.imread(f), scale))
        s = {c: float(e @ gallery[c]) for c in cows}
        b = max(s, key=s.get); pos.append((cow, b, s[b]))
    for f in neg_files:
        e = embed(degrade(cv2.imread(f), scale))
        s = {c: float(e @ gallery[c]) for c in cows}
        neg.append(max(s.values()))
    return pos, neg

def metrics(pos, neg, t):
    n, m = len(pos), len(neg)
    conf_ok  = sum(1 for a,b,s in pos if s>=t and a==b)
    misassign= sum(1 for a,b,s in pos if s>=t and a!=b)
    hold     = sum(1 for a,b,s in pos if s< t)
    fa       = sum(1 for s in neg if s>=t)
    return conf_ok/n, misassign/n, hold/n, fa/max(m,1)

# ── 표 1: 임계값별 open-set 성능 (원해상도)
pos, neg = run(1.0)
top1 = sum(1 for a,b,_ in pos if a==b)/len(pos)
print(f"■ Top-1 정확도(임계값 무관) = {top1:.4f}\n")
print(f"{'임계값':>7} {'확정률':>9} {'오배정률':>10} {'보류율':>9} {'미등록오확정':>13}")
rows=[]
for t in THRS:
    c,mi,h,fa = metrics(pos,neg,t)
    print(f"{t:7.2f} {c:9.4f} {mi:10.4f} {h:9.4f} {fa:13.4f}")
    rows.append({"threshold":t,"confirm_rate":round(c,4),"misassign_rate":round(mi,4),
                 "hold_rate":round(h,4),"unenrolled_false_accept":round(fa,4)})
csv.DictWriter(open(f"{OUT}/video_openset.csv","w",newline=""),
               fieldnames=list(rows[0])).writerows([dict(zip(rows[0],rows[0]))]+rows) if False else None
with open(f"{OUT}/video_openset.csv","w",newline="") as fp:
    w=csv.DictWriter(fp,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

# ── 표 2: 해상도 열화
print(f"\n■ 해상도 열화 (임계값 0.70 고정)")
print(f"{'배율':>7} {'Top-1':>9} {'확정률':>9} {'오배정률':>10} {'보류율':>9} {'미등록오확정':>13}")
drows=[]
for s in SCALES:
    p,n2 = (pos,neg) if s==1.0 else run(s)
    t1 = sum(1 for a,b,_ in p if a==b)/len(p)
    c,mi,h,fa = metrics(p,n2,0.70)
    print(f"{s:7.3f} {t1:9.4f} {c:9.4f} {mi:10.4f} {h:9.4f} {fa:13.4f}")
    drows.append({"scale":s,"top1":round(t1,4),"confirm_rate":round(c,4),
                  "misassign_rate":round(mi,4),"hold_rate":round(h,4),
                  "unenrolled_false_accept":round(fa,4)})
with open(f"{OUT}/video_degradation.csv","w",newline="") as fp:
    w=csv.DictWriter(fp,fieldnames=list(drows[0])); w.writeheader(); w.writerows(drows)
print(f"\n저장 완료 → {OUT}/video_openset.csv , {OUT}/video_degradation.csv")
