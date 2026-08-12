#!/usr/bin/env python3
"""영상 → 비문 식별 → 트랙 자동 바인딩 (ID 역전파 연결).

identify_video.py 의 프레임 선택 로직을 재사용한다. 복사하지 않는다.
가중 투표 승자가 나왔을 때만 bind API 를 호출하고, 미확정이면 아무 것도
하지 않는다 — 오배정이 미탐보다 나쁘다는 원칙(THRESHOLD_POLICY.md).

bind 에 보내는 similarity 는 가중표 합이 아니라 승자의 최고 프레임 유사도다.
가중표 합은 1 을 넘을 수 있어 임계값 검사를 무력화한다.
"""
import argparse
import json
import os
import sys

import cv2
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.getenv("MUZZLE_VIDEO_DIR", os.path.join(HERE, "..", "video"))
sys.path.insert(0, os.path.abspath(VIDEO_DIR))

import identify_video as IV   # noqa: E402  프레임 선택 로직 재사용
import muzzle_boxes as MB     # noqa: E402  ROI 좌표

API_BASE = os.getenv("MUZZLE_API_BASE", "http://127.0.0.1:8001/muzzle")
DIAG = 0.30   # 1위 후보를 보기 위한 진단용 (판정에는 쓰지 않는다)
OPER = 0.70   # 실제 운영 임계값


def identify(video_path, topn):
    stem = os.path.basename(video_path).split(".")[0]
    if stem not in MB.BOXES:
        sys.exit(f"ROI 없음: {stem}\n사용 가능: {list(MB.BOXES)}")

    picked = IV.pick(video_path, IV.norm(MB.BOXES[stem]), topn)
    votes, best_sim, frames = {}, {}, []

    for _, idx, mx, img in picked:
        _, buf = cv2.imencode(".jpg", img)
        r = requests.post(
            f"{API_BASE}/identify",
            files={"file": ("f.jpg", buf.tobytes(), "image/jpeg")},
            data={"source": "video_autobind", "threshold": DIAG},
            timeout=30,
        )
        if r.status_code != 200:
            frames.append({"frame": idx, "error": r.status_code})
            continue
        j = r.json()
        nid = j.get("national_id")
        sim = float(j.get("similarity") or 0.0)
        ok = sim >= OPER
        frames.append({"frame": idx, "match": float(mx), "national_id": nid,
                       "similarity": sim, "confirmed": ok})
        if ok and nid:
            votes[nid] = votes.get(nid, 0.0) + sim
            best_sim[nid] = max(best_sim.get(nid, 0.0), sim)

    if not votes:
        return None, 0.0, frames, votes
    win = max(votes, key=votes.get)
    return win, best_sim[win], frames, votes


def call_bind(segment_id, national_id, similarity, force):
    params = {"national_id": national_id, "similarity": similarity, "source": "muzzle"}
    if force:
        params["force"] = "true"
    r = requests.post(f"{API_BASE}/tracks/{segment_id}/bind", params=params, timeout=30)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="영상 파일 경로")
    ap.add_argument("--segment-id", type=int, help="바인딩할 track_segment.id")
    ap.add_argument("--topn", type=int, default=8)
    ap.add_argument("--force", action="store_true", help="다른 개체로 바인딩된 트랙을 교체")
    ap.add_argument("--dry-run", action="store_true", help="식별만 하고 바인딩은 호출하지 않는다")
    a = ap.parse_args()

    if not a.dry_run and a.segment_id is None:
        sys.exit("--segment-id 가 필요하다 (또는 --dry-run 으로 식별만 확인)")

    nid, sim, frames, votes = identify(a.video, a.topn)

    print(f"\n영상 {os.path.basename(a.video)} | 채택 {len(frames)}장 | 운영 임계값 {OPER}")
    print("-" * 72)
    for f in frames:
        if "error" in f:
            print(f"frame {f['frame']:4d}  HTTP {f['error']}")
            continue
        mark = "✅ 확정" if f["confirmed"] else "⏸ 보류"
        print(f"frame {f['frame']:4d} match {f['match']:.2f} | "
              f"1위 {f['national_id']} sim {f['similarity']:.4f} | {mark}")
    print("-" * 72)

    if nid is None:
        print("최종 판정: 미확정 — 확정 프레임 0장. 바인딩을 호출하지 않는다.")
        return 0

    tally = ", ".join(f"{k}:{v:.2f}" for k, v in votes.items())
    print(f"최종 판정: {nid}   (가중표 {tally})")
    print(f"bind 에 보낼 similarity: {sim:.4f}   ← 승자의 최고 프레임 유사도")

    if a.dry_run:
        print("\n[dry-run] 바인딩을 호출하지 않았다.")
        return 0

    code, body = call_bind(a.segment_id, nid, sim, a.force)
    print(f"\nPOST /tracks/{a.segment_id}/bind → HTTP {code}")
    print(json.dumps(body, ensure_ascii=False, indent=2, default=str))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
