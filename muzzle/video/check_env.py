# check_env.py — 실행 전 환경 점검
import sys, os, importlib, inspect

print("=" * 60)
print("1. 파이썬 :", sys.executable)

print("\n2. 패키지")
for pkg in ["cv2", "numpy", "requests", "ultralytics"]:
    try:
        m = importlib.import_module(pkg)
        print(f"   [OK] {pkg:12s} {getattr(m, '__version__', '')}")
    except ImportError:
        print(f"   [없음] {pkg}")

print("\n3. 크롭 모듈")
CROP_DIR = os.path.expanduser("~/models/muzzle/crop")
print("   경로:", CROP_DIR, "->", "있음" if os.path.isdir(CROP_DIR) else "없음")
if os.path.isdir(CROP_DIR):
    print("   파일:", os.listdir(CROP_DIR))
    sys.path.insert(0, CROP_DIR)
    try:
        import muzzle_cropper as mc
        names = [n for n in dir(mc) if not n.startswith("_")]
        print("   [OK] import 성공")
        print("   공개 이름:", names)
        for n in names:
            o = getattr(mc, n)
            if callable(o):
                try:
                    print(f"      - {n}{inspect.signature(o)}")
                except Exception:
                    print(f"      - {n} (시그니처 확인 불가)")
    except Exception as e:
        print("   [실패]", type(e).__name__, e)

print("\n4. API 상태")
try:
    import requests
    r = requests.get("http://localhost:8001/muzzle/health", timeout=5)
    print("   [OK]", r.json())
except Exception as e:
    print("   [실패]", type(e).__name__, e)
    print("   -> API가 꺼져 있다. 아래로 켜라:")
    print('      cd ~/muzzle_api && nohup ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 > api.log 2>&1 &')

print("=" * 60)