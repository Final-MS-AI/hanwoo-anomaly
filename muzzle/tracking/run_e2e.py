#!/usr/bin/env python3
"""전경 영상 + 초크포인트 영상 -> 검출/추적/행동 -> 적재 -> 비문 식별
-> 시간+행동 정합 핸드오프 -> timeline. 한 명령으로 관통한다.

사람이 세그먼트 번호를 고르지 않는다. 그것이 마지막 수동 단계였다.

설계 요점 5가지
1. 세션 ID 를 실행마다 새로 만든다. track_observation 의 INSERT 는 멱등이
   아니므로(track_segment 만 ON CONFLICT) 같은 세션으로 두 번 적재하면
   관측 행이 2배가 되고 행동 통계가 조용히 부풀어 규칙 판정이 틀린다.
2. ★ 후보를 시간만으로 좁히지 않는다. 초크포인트는 급이대이므로 그 순간
   전경에서 feeding 인 트랙만 후보가 된다. 실측: 시간만 10건 -> +행동 3건.
   화면 좌표(구역)를 쓰지 않으므로 영상이 바뀌어도 재설정할 것이 없다.
   행동 라벨은 이상행동 파트의 산출물을 그대로 쓴다.
3. 두 영상은 기준 시각을 따로 받는다. 카메라마다 녹화 시작이 다른 것이
   현실이고, 이것을 맞추는 것이 핸드오프의 전제다.
4. 후보가 정확히 1건일 때만 바인딩한다. 2건 이상이면 보류다.
   오배정이 미탐보다 나쁘다(THRESHOLD_POLICY.md).
5. auto_bind.py 를 복사하지 않고 import 한다. 임계값이나 투표 로직이
   바뀔 때 한쪽만 낡는 일을 막는다.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import cv2
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auto_bind as AB   # noqa: E402  identify() / call_bind() 재사용

API = os.getenv("MUZZLE_API_BASE", "http://127.0.0.1:8001/muzzle")
GPU = os.getenv("GPU_VM", "azureuser@10.0.0.5")
GPU_PY = os.getenv("GPU_PY", "/home/azureuser/realtime-inference/.venv/bin/python")
GPU_DIR = os.getenv("GPU_DIR", "/home/azureuser/muzzle-bridge")
LOADER = os.path.join(HERE, "track_load.py")

SEG_RE = re.compile(r"segment\s+(\d+)\s+camera=(\S+)\s+track=(\d+)\s+\S+=(\d+)")


def head(n, title):
    print("\n" + "=" * 74)
    print(f"[{n}] {title}")
    print("=" * 74)


def run(cmd, label):
    print(f"$ {cmd if isinstance(cmd, str) else ' '.join(cmd)}\n")
    p = subprocess.run(cmd, shell=isinstance(cmd, str), text=True,
                       capture_output=True)
    sys.stdout.write(p.stdout)
    if p.stderr.strip():
        sys.stderr.write(p.stderr[-2000:])
    if p.returncode != 0:
        sys.exit(f"\n[중단] {label} 실패 (exit {p.returncode})")
    return p.stdout


def extract_remote(wide, out_remote, camera, session, t0, stride, max_frames):
    inner = (f"cd {GPU_DIR} && {GPU_PY} behavior_extract.py"
             f" --video {shlex.quote(wide)}"
             f" --out {shlex.quote(out_remote)}"
             f" --camera {shlex.quote(camera)}"
             f" --session {shlex.quote(session)}"
             f" --start-time {shlex.quote(t0)}"
             f" --stride {stride}")
    if max_frames:
        inner += f" --max-frames {max_frames}"
    run(["ssh", "-o", "BatchMode=yes", GPU, inner], "GPU VM 행동 추출")


def load_jsonl(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if not rows:
        sys.exit("[중단] JSONL 이 비었다. 검출이 0건이면 stride/conf 를 확인할 것")
    for r in rows:
        r["_ts"] = datetime.fromisoformat(r["ts"])
    spans = {}
    for r in rows:
        key = (r["camera_id"], r["track_id"])
        lo, hi, n = spans.get(key, (r["_ts"], r["_ts"], 0))
        spans[key] = (min(lo, r["_ts"]), max(hi, r["_ts"]), n + 1)
    return rows, spans


def parse_segments(stdout):
    out = {}
    for m in SEG_RE.finditer(stdout):
        out[(m.group(2), int(m.group(3)))] = int(m.group(1))
    if not out:
        sys.exit("[중단] track_load.py 출력에서 segment id 를 못 찾았다")
    return out


def id_time(choke_video, frames, nid, t0):
    """승자의 최고 유사도 프레임이 찍힌 시각. 이것이 B 카메라 확정 시각이다."""
    cands = [f for f in frames
             if f.get("confirmed") and f.get("national_id") == nid]
    best = max(cands, key=lambda f: f["similarity"])
    cap = cv2.VideoCapture(choke_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return t0 + timedelta(seconds=best["frame"] / fps), best, fps


def pick_candidates(rows, spans, seg_map, camera, t_id, window, behavior):
    """시간 정합 + 행동 정합. 둘 다 만족하는 트랙만 후보다."""
    w = timedelta(seconds=window)
    hits = {}
    for r in rows:
        if r["camera_id"] != camera:
            continue
        if not (t_id - w <= r["_ts"] <= t_id + w):
            continue
        if behavior and r.get("behavior") != behavior:
            continue
        hits[r["track_id"]] = hits.get(r["track_id"], 0) + 1

    cands = []
    for (cam, tid), (lo, hi, n) in sorted(spans.items()):
        if cam != camera:
            continue
        alive = (lo - w) <= t_id <= (hi + w)
        h = hits.get(tid, 0)
        seg = seg_map.get((cam, tid))
        ok = alive and h > 0
        if ok and seg:
            cands.append(seg)
        mark = ">>" if ok else ("~ " if alive else "  ")
        print(f"  {mark} seg {seg}  track {tid:>3}  "
              f"{lo.strftime('%H:%M:%S')}~{hi.strftime('%H:%M:%S')}  "
              f"관측 {n:>4}  창내 {behavior or 'any'} {h:>3}프레임")
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True,
                    help="전경 영상 (GPU VM 상의 절대경로)")
    ap.add_argument("--choke", required=True,
                    help="초크포인트 영상 (이 VM. ROI 등록된 것만 가능)")
    ap.add_argument("--start-time", default="2026-08-14T09:00:00+00:00",
                    help="전경 영상의 기준 시각")
    ap.add_argument("--choke-start-time", default=None,
                    help="초크포인트 영상의 기준 시각. 미지정 시 --start-time 과 같다")
    ap.add_argument("--camera-wide", default="A")
    ap.add_argument("--window", type=float, default=2.0,
                    help="시간 정합 허용 오차(초)")
    ap.add_argument("--require-behavior", default="feeding",
                    help="후보 조건이 되는 행동. 빈 문자열이면 시간만으로 판단")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--topn", type=int, default=8)
    ap.add_argument("--prefix", default="demo_")
    ap.add_argument("--jsonl", default=None,
                    help="이미 받아둔 JSONL 로 재실행 (GPU 단계 생략)")
    a = ap.parse_args()

    t0 = datetime.fromisoformat(a.start_time)
    tc = datetime.fromisoformat(a.choke_start_time or a.start_time)
    session = a.prefix + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    local = a.jsonl or f"/tmp/e2e_{session}.jsonl"

    head(0, "실행 계획")
    print(f"  세션 ID          : {session}")
    print(f"  전경 기준 시각   : {t0.isoformat()}")
    print(f"  초크 기준 시각   : {tc.isoformat()}")
    print(f"  전경 (GPU VM)    : {a.wide}")
    print(f"  초크포인트       : {a.choke}")
    print(f"  시간 정합 창     : +-{a.window}초")
    print(f"  행동 정합 조건   : {a.require_behavior or '(없음 — 시간만)'}")

    if a.jsonl:
        head(1, "GPU VM 행동 추출 — 생략 (--jsonl 지정)")
    else:
        head(1, "GPU VM 에서 한우 검출 + ByteTrack + 행동 분류")
        remote = f"/tmp/e2e_{session}.jsonl"
        extract_remote(a.wide, remote, a.camera_wide, session,
                       a.start_time, a.stride, a.max_frames)
        head(2, "JSONL 회수 (DB 자격증명은 GPU VM 에 두지 않는다)")
        run(["scp", "-o", "BatchMode=yes", f"{GPU}:{remote}", local], "JSONL 회수")

    rows, spans = load_jsonl(local)
    print(f"관측 {len(rows)}건 / 트랙 {len(spans)}개")

    head(3, "DB 적재")
    seg_map = parse_segments(run([sys.executable, LOADER, local], "DB 적재"))

    head(4, "초크포인트 영상 비문 식별")
    nid, sim, frames, votes = AB.identify(a.choke, a.topn)
    for f in frames:
        if "error" in f:
            print(f"  frame {f['frame']:4d}  HTTP {f['error']}")
        else:
            mark = "확정" if f["confirmed"] else "보류"
            print(f"  frame {f['frame']:4d} match {f['match']:.2f} | "
                  f"{f['national_id']} sim {f['similarity']:.4f} | {mark}")
    if nid is None:
        print("\n최종 판정: 미확정. 바인딩을 호출하지 않는다.")
        print("행동 데이터는 적재됐으나 개체번호가 없다 — 설계된 동작이다.")
        return 0
    print(f"\n  판정 {nid} | 가중표 " +
          ", ".join(f"{k}:{v:.2f}" for k, v in votes.items()))
    print(f"  bind 에 보낼 similarity {sim:.4f}  (가중표 합이 아니다)")

    head(5, "★ 시간 + 행동 정합 핸드오프 — 대상 세그먼트 자동 선택")
    t_id, best, fps = id_time(a.choke, frames, nid, tc)
    print(f"  B 확정 프레임 {best['frame']} @ {fps:.1f}fps → 확정 시각 {t_id.isoformat()}")
    print(f"  탐색 구간 {(t_id - timedelta(seconds=a.window)).strftime('%H:%M:%S.%f')[:-3]}"
          f" ~ {(t_id + timedelta(seconds=a.window)).strftime('%H:%M:%S.%f')[:-3]}")
    print(f"  범례  >> 후보   ~ 시간만 일치({a.require_behavior} 없음)   (공백) 시간 불일치\n")
    cands = pick_candidates(rows, spans, seg_map, a.camera_wide,
                            t_id, a.window, a.require_behavior)
    print(f"\n  후보 {len(cands)}건: {cands}")

    head(6, "판정")
    if len(cands) == 1:
        print(f"  후보 1건 → 바인딩한다 (segment {cands[0]})")
        code, body = AB.call_bind(cands[0], nid, sim, False)
        print(f"  POST /tracks/{cands[0]}/bind → HTTP {code}")
        print("  " + json.dumps(body, ensure_ascii=False, default=str))
    elif not cands:
        print(f"  후보 0건 → 보류. 그 시각에 {a.require_behavior} 인 트랙이 없다.")
        print("  기준 시각을 확인하거나 --window 를 늘릴 것.")
    else:
        print(f"  후보 {len(cands)}건 → 보류. 자동 바인딩하지 않는다.")
        print("  둘 이상이 동시에 급이 중이면 시간·행동 정합으로 구분되지 않는다.")
        print("  오배정이 미탐보다 나쁘므로 붙이지 않는 것이 옳다.")

    head(7, f"timeline 확인 — GET /cattle/{nid}/timeline")
    r = requests.get(f"{API}/cattle/{nid}/timeline", timeout=30)
    d = r.json()
    print(f"  세그먼트 {d['segment_count']} / 관측 {d['observation_count']}")
    for s in d.get("segments", []):
        print(f"    seg {s['segment_id']:>3} track {s['track_id']:>3} "
              f"obs {s['observations']:>4} {s['session_id']}")
    beh = [o for o in d.get("observations", []) if o.get("behavior")]
    print(f"  행동 보유 관측 {len(beh)}건")
    for o in beh[:5]:
        print(f"    seg {o['segment_id']} frame {o['frame_idx']:>3} "
              f"{o['behavior']:<9} conf {o['behavior_conf']:.3f}")
    print(f"\n세션 {session} 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
