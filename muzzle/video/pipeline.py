# pipeline.py — 영상 -> 프레임 -> 코 크롭 -> 품질선별 -> 식별 API
#
# 사용법:
#   python pipeline.py identify <영상경로>
#   python pipeline.py enroll   <영상경로> <가축이력번호12자리>

import os, sys, json, argparse, inspect
import cv2, numpy as np, requests

# ---------------- 설정 (나중에 여기만 만지면 됨) ----------------
API_BASE   = "http://localhost:8001"
SAMPLE_FPS = 3       # 초당 몇 장 볼지
MIN_SIDE   = 224     # 크롭 짧은 변 하한 (모델 입력 크기)
MIN_SHARP  = 40.0    # 라플라시안 분산 하한. 낮으면 흐린 것
TOP_N      = 5       # 최종 사용할 프레임 수
DEBUG_DIR  = os.path.expanduser("~/data/stock_video/debug")
CROP_DIR   = os.path.expanduser("~/models/muzzle/crop")
# --------------------------------------------------------------

sys.path.insert(0, CROP_DIR)


def load_cropper():
    """muzzle_cropper 안의 크롭 함수를 자동으로 찾아 준다."""
    import muzzle_cropper as mc
    for name in ("crop_muzzle", "crop", "detect_and_crop",
                 "get_muzzle_crop", "run", "predict"):
        fn = getattr(mc, name, None)
        if callable(fn):
            print(f"[크롭] 함수 사용: muzzle_cropper.{name}")
            return fn
    for name in dir(mc):
        obj = getattr(mc, name)
        if inspect.isclass(obj) and "crop" in name.lower():
            inst = obj()
            for m in ("crop", "__call__", "run", "predict"):
                fn = getattr(inst, m, None)
                if callable(fn):
                    print(f"[크롭] 클래스 사용: {name}.{m}")
                    return fn
    raise RuntimeError(
        "크롭 함수를 못 찾았다. check_env.py 출력의 '공개 이름'을 보고 "
        "load_cropper() 후보 목록에 이름을 추가해라."
    )


def to_image(result):
    """크롭 함수 반환값이 뭐든 ndarray 이미지 하나로 정리."""
    if result is None:
        return None
    if isinstance(result, np.ndarray):
        return result if result.ndim == 3 else None
    if isinstance(result, (list, tuple)):
        imgs = [r for r in result if isinstance(r, np.ndarray) and r.ndim == 3]
        if not imgs:
            return None
        return max(imgs, key=lambda a: a.shape[0] * a.shape[1])   # 가장 큰 코
    if isinstance(result, dict):
        for k in ("crop", "image", "img"):
            if k in result:
                return to_image(result[k])
    return None


def sharpness(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def collect(video_path, crop_fn, save_debug=True):
    """영상에서 품질 통과한 크롭들을 모아 반환."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 못 연다: {video_path}")

    fps  = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    tag  = os.path.splitext(os.path.basename(video_path))[0]
    outd = os.path.join(DEBUG_DIR, tag)
    if save_debug:
        os.makedirs(outd, exist_ok=True)

    stats = {"sampled": 0, "detected": 0, "too_small": 0,
             "too_blurry": 0, "passed": 0}
    cands, i = [], 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            stats["sampled"] += 1
            try:
                crop = to_image(crop_fn(frame))
            except Exception as e:
                print(f"  [경고] 프레임 {i} 크롭 실패: {e}")
                crop = None
            if crop is not None and crop.size > 0:
                stats["detected"] += 1
                h, w = crop.shape[:2]
                s = sharpness(crop)
                if min(h, w) < MIN_SIDE:
                    stats["too_small"] += 1
                elif s < MIN_SHARP:
                    stats["too_blurry"] += 1
                else:
                    stats["passed"] += 1
                    cands.append({"frame": i, "sharp": s,
                                  "size": [w, h], "img": crop})
                    if save_debug:
                        cv2.imwrite(
                            os.path.join(outd, f"f{i:05d}_s{int(s)}.png"), crop)
        i += 1

    cap.release()
    cands.sort(key=lambda c: -c["sharp"])
    return cands, stats, outd


def post_identify(img):
    ok, buf = cv2.imencode(".png", img)
    r = requests.post(f"{API_BASE}/muzzle/identify",
                      files={"file": ("f.png", buf.tobytes(), "image/png")},
                      data={"source": "camera_b"}, timeout=30)
    r.raise_for_status()
    return r.json()


def post_enroll(imgs, national_id):
    files = []
    for n, im in enumerate(imgs):
        ok, buf = cv2.imencode(".png", im)
        files.append(("files", (f"{n}.png", buf.tobytes(), "image/png")))
    r = requests.post(f"{API_BASE}/muzzle/enroll",
                      files=files, data={"national_id": national_id}, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["identify", "enroll"])
    ap.add_argument("video")
    ap.add_argument("national_id", nargs="?", default=None)
    args = ap.parse_args()

    crop_fn = load_cropper()
    print(f"\n[영상] {args.video}")
    cands, stats, outd = collect(args.video, crop_fn)

    print("\n[집계]")
    for k, v in stats.items():
        print(f"  {k:12s} {v}")
    print(f"  디버그 크롭 -> {outd}")

    if not cands:
        print("\n[결과] 쓸 수 있는 프레임이 없다.")
        print("  -> MIN_SIDE 또는 MIN_SHARP 를 낮추거나, 코가 더 크게 나온 영상을 써라.")
        return

    picked = cands[:TOP_N]
    print(f"\n[선택] 상위 {len(picked)}장 "
          f"(선명도 {picked[0]['sharp']:.0f} ~ {picked[-1]['sharp']:.0f})")

    if args.mode == "enroll":
        if not args.national_id:
            print("\n[오류] enroll 모드는 가축이력번호 12자리가 필요하다.")
            return
        res = post_enroll([c["img"] for c in picked], args.national_id)
        print("\n[등록 결과]", json.dumps(res, ensure_ascii=False, indent=2))
        return

    results = []
    for c in picked:
        try:
            r = post_identify(c["img"])
        except Exception as e:
            print(f"  [경고] 프레임 {c['frame']} API 실패: {e}")
            continue
        r["frame"] = c["frame"]
        r["sharp"] = round(c["sharp"], 1)
        results.append(r)
        print(f"  프레임 {c['frame']:5d}  sim={r.get('similarity')}  "
              f"{r.get('decision')}  id={r.get('cattle_id')}")

    conf = [r for r in results if r.get("decision") == "confirmed"]
    if not conf:
        final = {"decision": "unconfirmed",
                 "note": "등록된 개체가 없거나 유사도가 임계값 미만"}
    else:
        from collections import Counter
        cid, votes = Counter(r["cattle_id"] for r in conf).most_common(1)[0]
        final = {"decision": "confirmed", "cattle_id": cid,
                 "votes": f"{votes}/{len(results)}",
                 "best_similarity": max(r["similarity"] for r in conf
                                        if r["cattle_id"] == cid)}

    print("\n[최종]", json.dumps(final, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()