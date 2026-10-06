#!/usr/bin/python3
"""Image metrics for a captured frame: per-channel mean, sharpness, clipping."""
import sys

import cv2

f = cv2.imread(sys.argv[1])
if f is None:
    print('unreadable')
    sys.exit(1)
g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
b, gr, r = (float(f[..., i].mean()) for i in range(3))
lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
# Centre third only: what the camera is pointed at, not the edges.
h, w = g.shape
c = g[h // 3:2 * h // 3, w // 3:2 * w // 3]
lapc = float(cv2.Laplacian(c, cv2.CV_64F).var())
hi = float((g >= 250).mean() * 100)
lo = float((g <= 5).mean() * 100)
print(f'{w}x{h} mean R={r:.0f} G={gr:.0f} B={b:.0f} sharp={lap:.0f} sharp_centre={lapc:.0f} clip_hi={hi:.1f}% clip_lo={lo:.1f}%')
