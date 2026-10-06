#!/usr/bin/python3
"""Open a V4L2 capture device N times; each time wait up to WAIT seconds for the
first changing frame, then read for SECS seconds and count changing frames.
Usage: devcheck.py /dev/videoN cycles secs min_fps [wait] [gap]
gap: pause between cycles (longer than a relay's stop grace forces a real restart)"""
import sys
import time

import cv2
import numpy as np

dev, cycles, secs, min_fps = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
wait = float(sys.argv[5]) if len(sys.argv) > 5 else secs
gap = float(sys.argv[6]) if len(sys.argv) > 6 else 0.5
ok = 0
ttff = []
for i in range(cycles):
    t_open = time.time()
    for _ in range(10):    # a relay that just started may not offer capture yet
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if cap.isOpened():
            break
        time.sleep(0.5)
    if not cap.isOpened():
        print(f'cycle {i+1}: open failed')
        time.sleep(1)
        continue
    prev = first = last = None
    changing = n = 0
    mean = 0.0
    while True:
        now = time.time()
        if first is None and now - t_open > wait:
            break
        if first is not None and now - first > secs:
            break
        r, f = cap.read()
        if not r:
            continue
        n += 1
        g = (f if f.ndim == 2 else cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)).astype(np.int16)
        mean = float(g.mean())
        # Idle relays feed constant black; real sensor frames differ by noise at least.
        if prev is not None and g.shape == prev.shape and np.abs(g - prev).mean() > 0.3 and mean > 2:
            now = time.time()
            if first is None:
                first = now
            changing += 1
            last = now
        prev = g
    cap.release()
    fps = (changing - 1) / (last - first) if changing > 1 and last > first else 0
    good = changing >= 10 and fps >= min_fps
    ok += good
    if first is not None:
        ttff.append(first - t_open)
    tf = f'{first - t_open:.1f}s' if first is not None else 'none'
    print(f'cycle {i+1}: first_frame={tf} frames={n} changing={changing} fps={fps:.1f} mean={mean:.0f} {"ok" if good else "BAD"}', flush=True)
    time.sleep(gap)
if ttff:
    print(f'first-frame times: min {min(ttff):.1f}s median {sorted(ttff)[len(ttff)//2]:.1f}s max {max(ttff):.1f}s')
print(f'RESULT {ok}/{cycles}')
sys.exit(0 if ok == cycles else 1)
