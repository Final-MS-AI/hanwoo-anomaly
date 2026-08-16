"""초크포인트 구역 — 사용자가 CCTV 화면에서 직접 지정한 다각형.

왜 필요한가. 핸드오프를 시간 정합만으로 하면 축사에 소가 상시 여러 마리
있을 때 후보가 좁혀지지 않는다(실측 23트랙 중 10건). 그 시각 급이대에
있던 트랙만 남겨야 한다.

행동 라벨(feeding)로 좁히는 방법도 되지만, 그 라벨은 급이대 부근에서
고개를 숙이면 붙는 것으로 알려져 있다. 즉 좌표 의존성이 사라진 것이
아니라 남의 모델 안에 들어가 통제권만 잃은 상태다. 구역을 직접 받으면
농장마다 다른 급이대 위치에 대응되고, 모델이 갱신돼도 흔들리지 않는다.

좌표는 정규화(0~1), bbox 는 픽셀이다. frame 을 함께 저장해 변환한다.
"""
import json
import os
import urllib.parse
import urllib.request
ZONES = {
    "top": {
        "frame": (1920, 1080),
        "poly": [(0.0009, 0.7023), (0.0009, 0.7487), (0.1226, 0.6034),
                 (0.3026, 0.452), (0.4939, 0.3067), (0.6243, 0.2124),
                 (0.6122, 0.2), (0.4565, 0.3051), (0.3009, 0.4241),
                 (0.16, 0.5354)],
    },
}


# --- DB 우선 조회 (2026-08-17) -------------------------------------------
# 구역은 사용자가 CCTV 화면에서 지정하고 track_zone 에 저장된다.
# DB 가 없거나 구역이 등록되지 않았으면 위 ZONES 딕셔너리로 폴백한다.
# 폴백이 있으므로 DB 장애가 시연을 멈추지 않는다.
ZONE_API = os.getenv("MUZZLE_ZONE_API",
                     "http://127.0.0.1:8001/muzzle/zones")
USE_DB_ZONE = os.getenv("MUZZLE_ZONE_SOURCE", "db") != "dict"


def zone_spec(name, camera_id="A", device_id=None):
    """구역 정의를 {"frame": (w,h), "poly": [(x,y),...], "anchor": str} 로 반환.

    DB -> 실패 시 ZONES 딕셔너리. 어느 쪽을 썼는지 source 로 알린다.
    """
    if USE_DB_ZONE:
        try:
            q = {"camera_id": camera_id}
            if device_id:
                q["device_id"] = device_id
            url = f"{ZONE_API}/{name}?" + urllib.parse.urlencode(q)
            with urllib.request.urlopen(url, timeout=3) as r:
                d = json.loads(r.read().decode("utf-8"))
            return {"frame": (d["frame_w"], d["frame_h"]),
                    "poly": [(float(x), float(y)) for x, y in d["poly"]],
                    "anchor": d.get("anchor", "topright"),
                    "source": f"db(id={d['id']})"}
        except Exception as e:
            print(f"[zones] DB 조회 실패 ({e}) -> 내장 정의로 폴백", flush=True)
    z = ZONES[name]
    return {"frame": z["frame"],
            "poly": [(float(x), float(y)) for x, y in z["poly"]],
            "anchor": z.get("anchor", "topright"),
            "source": "dict"}


def poly_px(name, camera_id="A", device_id=None):
    """정규화 좌표를 픽셀로 변환한 꼭짓점 목록."""
    z = zone_spec(name, camera_id, device_id)
    w, h = z["frame"]
    return [(x * w, y * h) for x, y in z["poly"]]


def point_in_poly(pt, poly):
    """ray casting. 외부 라이브러리 없이 판정한다."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1
            if x < xin:
                inside = not inside
    return inside


def poly_touches_bbox(poly, bx, by, bw, bh, step=4.0):
    """다각형 변을 촘촘히 샘플링해 bbox 안에 들어오는 점이 있는지 본다.

    띠가 얇아 정식 선분교차 대신 샘플링으로 충분하다. bbox 가 띠를 가로지르면
    반드시 어느 샘플이 안에 들어온다.
    """
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        d = max(abs(x2 - x1), abs(y2 - y1))
        k = max(2, int(d / step))
        for j in range(k + 1):
            t = j / k
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return True
    return False


# bbox 는 좌상단 기준 (x, y, w, h) 다. 실측으로 확인했다:
# 중심 가정이면 x - w/2 가 -150 이 되어 프레임 밖으로 나간다.
ANCHORS = {
    "bottom":   lambda x, y, w, h: (x + w / 2, y + h),        # 발
    "center":   lambda x, y, w, h: (x + w / 2, y + h / 2),    # 몸통
    "top":      lambda x, y, w, h: (x + w / 2, y),            # 위쪽 변
    "topleft":  lambda x, y, w, h: (x, y),
    "topright": lambda x, y, w, h: (x + w, y),
}


def hit(zone, bx, by, bw, bh, mode="touch"):
    """mode: touch(bbox 가 띠에 닿음) 또는 ANCHORS 의 키."""
    poly = poly_px(zone)
    if mode == "touch":
        return poly_touches_bbox(poly, bx, by, bw, bh)
    return point_in_poly(ANCHORS[mode](bx, by, bw, bh), poly)
