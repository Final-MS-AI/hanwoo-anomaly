import os, glob, base64, json, cv2
SRC=os.path.expanduser("~/data/muzzle_eval"); DST=os.path.expanduser("~/muzzle_api/video/annot")
os.makedirs(DST,exist_ok=True); N=9
vids=[]
for split in ["enroll","query","unknown"]:
    for v in sorted(glob.glob(os.path.join(SRC,split,"*.mp4"))):
        name=os.path.splitext(os.path.basename(v))[0]
        cap=cv2.VideoCapture(v); total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 30
        frames=[]
        for k in range(N):
            idx=int(total*(k+0.5)/N)
            cap.set(cv2.CAP_PROP_POS_FRAMES,idx); ok,fr=cap.read()
            if not ok: continue
            h,w=fr.shape[:2]; s=460/max(w,h)
            sm=cv2.resize(fr,(int(w*s),int(h*s)))
            b=base64.b64encode(cv2.imencode(".jpg",sm,[cv2.IMWRITE_JPEG_QUALITY,85])[1]).decode()
            frames.append({"idx":idx,"img":"data:image/jpeg;base64,"+b})
        cap.release()
        if frames: vids.append({"name":name,"split":split,"frames":frames})
print(f"{len(vids)}개 영상 × 최대 {N}프레임")
html="""<!doctype html><meta charset=utf-8><title>코 지정</title>
<style>body{font-family:sans-serif;background:#111;color:#eee;margin:14px}
.card{margin-bottom:22px;border:1px solid #333;padding:8px;border-radius:8px}
.row{display:flex;flex-wrap:wrap;gap:6px}canvas{cursor:crosshair;border:2px solid #222;max-width:290px}
h3{margin:4px 0;font-size:15px}.done{color:#4ade80}.todo{color:#f87171}
#out{width:100%;height:230px;background:#000;color:#4ade80;font-family:monospace;font-size:13px}
button{background:#2563eb;color:#fff;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;margin:6px}</style>
<h2>코가 <b>잘 보이는 프레임 아무거나 하나</b>를 골라 좌상단→우하단 2번 클릭</h2>
<p>영상당 한 장만 하면 됩니다. 나머지 프레임은 자동 추적됩니다. 다시 찍으면 덮어씁니다.</p>
<div id=L></div><button onclick=gen()>결과 만들기</button><textarea id=out></textarea>
<script>
const V=__DATA__, R={};
V.forEach((v,i)=>{
 const d=document.createElement('div');d.className='card';
 d.innerHTML=`<h3 id=t${i} class=todo>${v.name} (${v.split}) — 미지정</h3><div class=row id=r${i}></div>`;
 document.getElementById('L').appendChild(d);
 v.frames.forEach((f,j)=>{
  const c=document.createElement('canvas');document.getElementById('r'+i).appendChild(c);
  const im=new Image();im.onload=()=>{c.width=im.width;c.height=im.height;
   const x=c.getContext('2d');x.drawImage(im,0,0);
   c.onclick=e=>{const b=c.getBoundingClientRect();
    const px=(e.clientX-b.left)/b.width*c.width, py=(e.clientY-b.top)/b.height*c.height;
    if(v._c!==j){v._c=j;v._p=[];}
    v._p=(v._p&&v._p.length===1)?[v._p[0],[px,py]]:[[px,py]];
    v.frames.forEach((g,k)=>{if(g._c&&k!==j){g._c.getContext('2d').drawImage(g._im,0,0);g._c.style.borderColor='#222';}});
    x.clearRect(0,0,c.width,c.height);x.drawImage(im,0,0);
    if(v._p.length===1){x.fillStyle='#f00';x.fillRect(v._p[0][0]-4,v._p[0][1]-4,8,8);}
    else{const[a,q]=v._p,X=Math.min(a[0],q[0]),Y=Math.min(a[1],q[1]),
     W=Math.abs(a[0]-q[0]),H=Math.abs(a[1]-q[1]);
     x.strokeStyle='#0f0';x.lineWidth=3;x.strokeRect(X,Y,W,H);c.style.borderColor='#0f0';
     R[v.name]=[f.idx,+(X/c.width).toFixed(4),+(Y/c.height).toFixed(4),
                +((X+W)/c.width).toFixed(4),+((Y+H)/c.height).toFixed(4)];
     const t=document.getElementById('t'+i);t.className='done';
     t.textContent=v.name+' ('+v.split+') — 완료 ✔';}};
   f._c=c;f._im=im;};im.src=f.img;});});
function gen(){const m=V.filter(v=>!R[v.name]).map(v=>v.name);
 let s='BOXES = {\\n';for(const k in R)s+=`    "${k}": (${R[k].join(', ')}),\\n`;s+='}\\n';
 document.getElementById('out').value=(m.length?'# 미지정: '+m.join(', ')+'\\n':'')+s;}
</script>"""
open(os.path.join(DST,"index.html"),"w").write(html.replace("__DATA__",json.dumps(vids)))
print("생성 →",os.path.join(DST,"index.html"))
