import os, glob, cv2, numpy as np, importlib.util
SRC = os.path.expanduser("~/data/muzzle_eval")
spec = importlib.util.spec_from_file_location("mb", os.path.expanduser("~/muzzle_api/video/muzzle_boxes.py"))
mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)

rows = []
for split in ["enroll","query","unknown"]:
    for vid in sorted(glob.glob(os.path.join(SRC, split, "*.mp4"))):
        name = os.path.splitext(os.path.basename(vid))[0]
        cx, cy, bw = mb.BOXES.get(name, mb.DEFAULT)
        cap = cv2.VideoCapture(vid); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 30
        tri = []
        for pos in (0.25, 0.50, 0.75):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n*pos)); ok, fr = cap.read()
            if not ok: continue
            fr = np.ascontiguousarray(fr); H, W = fr.shape[:2]
            w = int(W*bw); h = int(w*0.72)
            x1 = max(0,int(cx*W-w/2)); y1 = max(0,int(cy*H-h/2))
            d = fr.copy()
            for g in range(1,10):
                cv2.line(d,(int(W*g/10),0),(int(W*g/10),H),(80,80,80),1)
                cv2.line(d,(0,int(H*g/10)),(W,int(H*g/10)),(80,80,80),1)
            cv2.rectangle(d,(x1,y1),(min(W,x1+w),min(H,y1+h)),(0,255,0),4)
            tri.append(cv2.resize(d,(230,230)))
        cap.release()
        if tri: rows.append((f"{name}   {cx:.2f}, {cy:.2f}, {bw:.2f}", tri))

if rows:
    RH = 230+22
    z = np.full((len(rows)*RH, 230*3, 3), 25, np.uint8)
    for r,(lab,tri) in enumerate(rows):
        for c,im in enumerate(tri): z[r*RH:r*RH+230, c*230:(c+1)*230] = im
        cv2.putText(z, lab, (5, r*RH+230+16), cv2.FONT_HERSHEY_SIMPLEX, 0.55,(255,255,255),1)
    p = os.path.join(SRC,"_preview_boxes.jpg"); cv2.imwrite(p, z)
    print("미리보기 →", p, f"({len(rows)}개 영상)")
