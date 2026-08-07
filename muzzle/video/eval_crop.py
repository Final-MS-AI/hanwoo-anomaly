import os, glob, json, cv2, numpy as np, importlib.util
SRC=os.path.expanduser("~/data/muzzle_eval"); OUT=os.path.join(SRC,"crops")
KEEP={"enroll":8,"query":6,"unknown":6}
SAMPLE_EVERY, MIN_GAP, PAD = 2, 4, 0.10
MATCH_MIN, SCALES = 0.32, [0.82, 0.92, 1.0, 1.10, 1.22]
spec=importlib.util.spec_from_file_location("mb",os.path.expanduser("~/muzzle_api/video/muzzle_boxes.py"))
mb=importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
A=np.ascontiguousarray
def G(x): return cv2.cvtColor(A(x),cv2.COLOR_BGR2GRAY)
def sharp(im):
    g=G(cv2.resize(A(im),(180,180))).astype(np.float32)
    l=-4*g+np.roll(g,1,0)+np.roll(g,-1,0)+np.roll(g,1,1)+np.roll(g,-1,1)
    return float(l[1:-1,1:-1].var())

os.makedirs(OUT,exist_ok=True); stats={}; skipped=[]
for split,keep_n in KEEP.items():
    sheet=[]
    for vid in sorted(glob.glob(os.path.join(SRC,split,"*.mp4"))):
        name=os.path.splitext(os.path.basename(vid))[0]; cow=name.split("_")[0]
        b=getattr(mb,"BOXES",{}).get(name)
        if not b or len(b)!=5: skipped.append(name); print(f"{name:18s} — 좌표 없음"); continue
        fidx,rx1,ry1,rx2,ry2=b
        cap=cv2.VideoCapture(vid); cap.set(cv2.CAP_PROP_POS_FRAMES,int(fidx))
        ok,ref=cap.read()
        if not ok: cap.set(cv2.CAP_PROP_POS_FRAMES,0); ok,ref=cap.read()
        if not ok: skipped.append(name); cap.release(); continue
        ref=A(ref); H,W=ref.shape[:2]
        tx1,ty1=max(0,int(rx1*W)),max(0,int(ry1*H))
        tx2,ty2=min(W,int(rx2*W)),min(H,int(ry2*H))
        tpl=A(G(ref[ty1:ty2,tx1:tx2]))
        if tpl.size==0 or min(tpl.shape)<12: skipped.append(name); cap.release(); continue
        tw,th=tpl.shape[1],tpl.shape[0]
        cap.set(cv2.CAP_PROP_POS_FRAMES,0)
        dst=os.path.join(OUT,split,cow); os.makedirs(dst,exist_ok=True)
        i,cands,nlow=0,[],0
        while True:
            ok,fr=cap.read()
            if not ok: break
            if i%SAMPLE_EVERY: i+=1; continue
            i+=1; fr=A(fr); g=A(G(fr)); best=None
            for s in SCALES:
                w2,h2=int(tw*s),int(th*s)
                if w2<10 or h2<10 or w2>=g.shape[1] or h2>=g.shape[0]: continue
                t2=A(cv2.resize(tpl,(w2,h2)))
                res=cv2.matchTemplate(g,t2,cv2.TM_CCOEFF_NORMED)
                _,mx,_,loc=cv2.minMaxLoc(res)
                if best is None or mx>best[0]: best=(mx,loc,w2,h2)
            if best is None: continue
            sc,(x,y),w2,h2=best
            if sc<MATCH_MIN: nlow+=1; continue
            px,py=int(w2*PAD),int(h2*PAD)
            crop=A(fr[max(0,y-py):min(fr.shape[0],y+h2+py),
                      max(0,x-px):min(fr.shape[1],x+w2+px)])
            if crop.size==0 or min(crop.shape[:2])<32: continue
            cands.append({"f":i,"img":crop,"m":sc,"sh":sharp(crop)})
        cap.release()
        if not cands: skipped.append(name); print(f"{name:18s} ❌ 매칭 0 (임계 {MATCH_MIN})"); continue
        shs=np.array([c["sh"] for c in cands]); lo,hi=np.percentile(shs,10),np.percentile(shs,95)
        ms=np.array([c["m"] for c in cands]); mlo,mhi=ms.min(),ms.max()
        for c in cands:
            c["score"]=0.50*float(np.clip((c["m"]-mlo)/max(mhi-mlo,1e-6),0,1))+\
                       0.50*float(np.clip((c["sh"]-lo)/max(hi-lo,1e-6),0,1))
        picked=[]
        for c in sorted(cands,key=lambda z:-z["score"]):
            if all(abs(c["f"]-p["f"])>=MIN_GAP for p in picked): picked.append(c)
            if len(picked)>=keep_n: break
        for c in picked:
            cv2.imwrite(os.path.join(dst,f"{name}_f{c['f']:05d}_c{c['score']:.3f}.jpg"),
                        c["img"],[cv2.IMWRITE_JPEG_QUALITY,95])
            sheet.append((name,c["img"]))
        stats[name]={"split":split,"cow":cow,"kept":len(picked),
                     "matched":len(cands),"dropped_lowmatch":nlow,
                     "mean_match":round(float(ms.mean()),3)}
        print(f"{name:18s} {split:8s} 채택 {len(picked):2d}/{len(cands):3d}  "
              f"매칭평균 {ms.mean():.2f}  화면밖제외 {nlow}")
    if sheet:
        T,C=170,8; R=(len(sheet)+C-1)//C
        z=np.full((R*(T+18),C*T,3),30,np.uint8)
        for k,(lab,im) in enumerate(sheet):
            r_,c_=divmod(k,C)
            z[r_*(T+18):r_*(T+18)+T,c_*T:c_*T+T]=cv2.resize(A(im),(T,T))
            cv2.putText(z,lab[:20],(c_*T+3,r_*(T+18)+T+13),cv2.FONT_HERSHEY_SIMPLEX,0.38,(255,255,255),1)
        cv2.imwrite(os.path.join(OUT,f"_contact_{split}.jpg"),z)
json.dump(stats,open(os.path.join(OUT,"crop_stats.json"),"w"),indent=2,ensure_ascii=False)
en={v["cow"] for v in stats.values() if v["split"]=="enroll"}
qu={v["cow"] for v in stats.values() if v["split"]=="query"}
un={v["cow"] for v in stats.values() if v["split"]=="unknown"}
print(f"\n총 {len(glob.glob(os.path.join(OUT,'*','*','*.jpg')))}장")
if skipped: print("제외:",", ".join(skipped))
print(f"등록개체: {sorted(en&qu)} → {len(en&qu)}두")
print(f"미등록개체: {sorted(un)} → {len(un)}두")
