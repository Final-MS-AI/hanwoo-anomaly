#!/usr/bin/env python3
"""
비문 모델 검수 스크립트 — 어디든 올리기 전에 이걸 먼저 돌린다.

사용법 (Colab):
    !python test_muzzle_model.py --ckpt muzzle_encoder.pt --onnx muzzle_encoder.onnx --data cff_crops

사용법 (Azure VM):
    python3 test_muzzle_model.py --ckpt muzzle_encoder.pt --onnx muzzle_encoder.onnx --data cff_crops

--data 폴더 구조는 둘 다 지원:
    A) cff_crops/cattle-241__1.jpg   (파일명에 개체명, __ 로 구분)
    B) cff_crops/cattle-241/1.jpg    (폴더명이 개체명)

검사 항목 7개. 하나라도 FAIL이면 배포하지 마라.
"""
import argparse, os, sys, glob, time, collections
import numpy as np

THRESHOLD = 0.40
RESULT = []


def check(name, ok, detail=""):
    RESULT.append((name, ok, detail))
    mark = "\033[92m✓ PASS\033[0m" if ok else "\033[91m✗ FAIL\033[0m"
    print(f"  {mark}  {name}" + (f"   ({detail})" if detail else ""))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="muzzle_encoder.pt")
    ap.add_argument("--onnx", default="muzzle_encoder.onnx")
    ap.add_argument("--data", default="", help="검수용 이미지 폴더 (없으면 데이터 검사는 건너뜀)")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    a = ap.parse_args()

    # ── 1. 환경 ───────────────────────────────────────────────
    print("\n[1/7] 환경 확인")
    try:
        import torch, timm, cv2
        from PIL import Image
        import torch.nn as nn, torch.nn.functional as F
        from torchvision import transforms as T
        check("필수 패키지 (torch/timm/cv2/PIL)", True,
              f"torch {torch.__version__}, timm {timm.__version__}")
    except ImportError as e:
        check("필수 패키지", False, str(e))
        print("\n→ pip install torch timm opencv-python-headless pillow")
        return
    HAS_ORT = True
    try:
        import onnxruntime as ort
    except ImportError:
        HAS_ORT = False
        print("     (onnxruntime 없음 → ONNX 검사 건너뜀. pip install onnxruntime)")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"       실행 장치: {dev}")

    # ── 2. 체크포인트 로드 ─────────────────────────────────────
    print("\n[2/7] 모델 로드")
    if not os.path.exists(a.ckpt):
        check("체크포인트 파일 존재", False, a.ckpt)
        return
    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    cfg = ck["cfg"]

    class Enc(nn.Module):
        def __init__(s, c):
            super().__init__()
            s.backbone = timm.create_model(c["model"], pretrained=False, num_classes=0)
            d = s.backbone.num_features
            s.neck = nn.Sequential(nn.BatchNorm1d(d), nn.Dropout(0.2),
                                   nn.Linear(d, c["embed_dim"]), nn.BatchNorm1d(c["embed_dim"]))
        def forward(s, x): return s.neck(s.backbone(x))

    model = Enc(cfg)
    missing, unexpected = model.load_state_dict(ck["enc"], strict=False)
    model.eval().to(dev)
    check("가중치 로드 (누락/초과 텐서 0개)", not missing and not unexpected,
          f"missing {len(missing)}, unexpected {len(unexpected)}")
    print(f"       백본 {cfg['model']} | 입력 {cfg['img_size']}px | "
          f"GRAY={cfg['GRAY']} CLAHE={cfg['CLAHE']} | 임베딩 {cfg['embed_dim']}차원")

    # ── 전처리 (학습과 동일해야 함) ─────────────────────────────
    _cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
    tf = T.Compose([T.Resize(int(cfg["img_size"] * 1.14)), T.CenterCrop(cfg["img_size"]),
                    T.ToTensor(), T.Normalize(MEAN, STD)])

    def prep(img):
        if isinstance(img, str):
            b = cv2.imread(img)
            if b is None: return None
            img = cv2.cvtColor(b, cv2.COLOR_BGR2RGB)
        img = np.asarray(img)
        if cfg["GRAY"]:
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            if cfg["CLAHE"]: g = _cl.apply(g)
            img = np.stack([g, g, g], -1)
        return tf(Image.fromarray(img))

    @torch.no_grad()
    def embed(items, bs=32):
        out = []
        for i in range(0, len(items), bs):
            xs = [prep(x) for x in items[i:i + bs]]
            xs = [x for x in xs if x is not None]
            if not xs: continue
            v = model(torch.stack(xs).to(dev))
            out.append(F.normalize(v, dim=1).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, cfg["embed_dim"]), np.float32)

    # ── 3. ONNX 일치 ──────────────────────────────────────────
    print("\n[3/7] ONNX 일치 검사  (서빙과 학습이 같은 답을 내는가)")
    if HAS_ORT and os.path.exists(a.onnx):
        d = torch.randn(4, 3, cfg["img_size"], cfg["img_size"])
        with torch.no_grad():
            ref = model(d.to(dev)).cpu().numpy()
        sess = ort.InferenceSession(a.onnx, providers=["CPUExecutionProvider"])
        got = sess.run(None, {sess.get_inputs()[0].name: d.numpy()})[0]
        # 실제 운영에서 쓰는 건 정규화된 벡터의 코사인 유사도다.
        # 원시 절대오차는 임베딩 크기(norm 100~1000)에 비례해 커 보이므로 기준이 될 수 없다.
        nr = ref / (np.linalg.norm(ref, axis=1, keepdims=True) + 1e-12)
        ng = got / (np.linalg.norm(got, axis=1, keepdims=True) + 1e-12)
        cos = float((nr * ng).sum(1).min())
        check("PyTorch vs ONNX 코사인 일치 > 0.9999", cos > 0.9999, f"최소 {cos:.6f}")
    else:
        check("ONNX 검사", False, "onnxruntime 미설치 또는 .onnx 파일 없음 — 건너뜀")

    # ── 4. 속도 ───────────────────────────────────────────────
    print("\n[4/7] 추론 속도  (경량화 담당에게 넘길 숫자)")
    dummy = np.random.randint(0, 255, (300, 300, 3), dtype=np.uint8)
    embed([dummy])  # 워밍업
    t0 = time.time(); [embed([dummy]) for _ in range(20)]
    ms1 = (time.time() - t0) / 20 * 1000
    t0 = time.time(); embed([dummy] * 32)
    ms32 = (time.time() - t0) / 32 * 1000
    check("1장 추론 200ms 이내", ms1 < 200, f"1장 {ms1:.1f}ms / 배치32 장당 {ms32:.1f}ms ({dev})")

    # ── 5. 데이터 수집 ────────────────────────────────────────
    print("\n[5/7] 검수 데이터")
    if not a.data or not os.path.isdir(a.data):
        check("데이터 폴더", False, "--data 미지정 — 6·7번 검사 건너뜀")
        summary(); return

    exts = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.PNG", "*.bmp")
    paths = []
    for e in exts:
        paths += glob.glob(os.path.join(a.data, "**", e), recursive=True)
    by_cow = collections.defaultdict(list)
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        parent = os.path.basename(os.path.dirname(p))
        cow = stem.split("__")[0] if "__" in stem else parent
        by_cow[cow].append(p)
    by_cow = {k: sorted(v) for k, v in by_cow.items() if len(v) >= 4}
    ok = len(by_cow) >= 5
    check("개체 5두 이상 (각 4장 이상)", ok, f"{len(by_cow)}두 / 총 {sum(len(v) for v in by_cow.values())}장")
    if not ok:
        print("       → 폴더 구조를 확인해라. cff_crops.zip을 풀면 cattle-XXX__N.jpg 형태여야 한다")
        summary(); return

    # ── 6. 등록 → 조회 ────────────────────────────────────────
    print("\n[6/7] 등록 → 조회  (실제 운영 절차 그대로)")
    gal, probes, ptruth = {}, [], []
    for cow, ps in by_cow.items():
        gv = embed(ps[:3])
        if len(gv) == 0: continue
        c = gv.mean(0); gal[cow] = c / (np.linalg.norm(c) + 1e-12)
        probes += ps[3:]; ptruth += [cow] * len(ps[3:])
    ids = list(gal); G = np.stack([gal[k] for k in ids])
    P = embed(probes)
    sim = P @ G.T
    best = sim.max(1); pred = [ids[i] for i in sim.argmax(1)]
    corr = np.array([x == y for x, y in zip(pred, ptruth)])

    top1 = float(corr.mean())
    assigned = best >= a.threshold
    mis = float(((assigned) & (~corr)).sum() / len(ptruth))
    hold = float((~assigned).sum() / len(ptruth))
    print(f"       Top-1 {top1:.4f} | @{a.threshold}: 오배정 {mis:.4f} / 보류 {hold:.4f} "
          f"| 등록 {len(ids)}두 / 조회 {len(probes)}장")
    check("Top-1이 무작위보다 크게 높음", top1 > 5.0 / len(ids), f"무작위 {1/len(ids):.4f}")
    check("유사도가 임계값 부근에서 동작 (전부 통과/전부 보류가 아님)",
          0.0 < hold < 0.9 or mis < 0.05,
          f"보류율 {hold:.4f} — 0.0000이면 이 도메인에서 임계값 재보정 필요")

    # ── 7. 분리도 + 화질 강건성 ───────────────────────────────
    print("\n[7/7] 분리도 · 화질 강건성")
    same, diff = [], []
    for cow, ps in list(by_cow.items())[:20]:
        v = embed(ps[:4])
        if len(v) < 2: continue
        s = v @ v.T
        same += [s[i, j] for i in range(len(v)) for j in range(i + 1, len(v))]
    ks = list(gal)
    for i in range(len(ks)):
        for j in range(i + 1, min(i + 4, len(ks))):
            diff.append(float(gal[ks[i]] @ gal[ks[j]]))
    ms_, md_ = float(np.mean(same)), float(np.mean(diff))
    check("같은 개체 유사도 > 다른 개체 유사도", ms_ > md_ + 0.05,
          f"같은 {ms_:.3f} vs 다른 {md_:.3f} (차이 {ms_-md_:.3f})")

    # 저화질로 떨어뜨려도 같은 개체로 매칭되는가
    test_ps = [ps[3] for ps in list(by_cow.values())[:30] if len(ps) > 3]
    truth = [c for c, ps in list(by_cow.items())[:30] if len(ps) > 3]
    degraded = []
    for p in test_ps:
        im = cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
        h, w = im.shape[:2]
        sm = cv2.resize(im, (max(8, w // 3), max(8, h // 3)), interpolation=cv2.INTER_AREA)
        im = cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR)
        _, enc_ = cv2.imencode(".jpg", im[:, :, ::-1], [int(cv2.IMWRITE_JPEG_QUALITY), 40])
        degraded.append(cv2.imdecode(enc_, cv2.IMREAD_COLOR)[:, :, ::-1])
    Pd = embed(degraded)
    pd_pred = [ids[i] for i in (Pd @ G.T).argmax(1)]
    acc_d = float(np.mean([x == y for x, y in zip(pd_pred, truth)]))
    check("1/3 축소 + JPEG40 후에도 Top-1 유지", acc_d >= max(0.4, top1 - 0.3),
          f"열화 후 {acc_d:.4f} (원본 {top1:.4f})")

    summary()


def summary():
    n_fail = sum(1 for _, ok, _ in RESULT if not ok)
    print("\n" + "=" * 62)
    for name, ok, detail in RESULT:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 62)
    if n_fail == 0:
        print("  전부 통과. 배포해도 된다.")
    else:
        print(f"  {n_fail}건 실패. 위 detail을 확인하고 고친 뒤 다시 돌려라.")
    print()


if __name__ == "__main__":
    main()
