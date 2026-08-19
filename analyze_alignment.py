#!/usr/bin/env python3
"""Mide cuanto desplazamiento y rotacion hay entre capturas del mismo dedo.

Objetivo: averiguar que radio de busqueda necesita el matcher del driver
focaltech_moh para que dos tomas del mismo dedo superen el umbral 0.30.
El driver actual usa FT9201_SEARCH_RADIUS = 3 px y no compensa rotacion.
"""
import sys, itertools
import numpy as np

W, H, SZ = 64, 80, 5120

def load_images(path):
    blob = open(path, "rb").read()
    def row_corr(img):
        a = img[:-1].astype(float).ravel(); b = img[1:].astype(float).ravel()
        a -= a.mean(); b -= b.mean()
        d = np.sqrt((a*a).sum()*(b*b).sum())
        return float((a*b).sum()/d) if d else 0.0
    n = len(blob)//SZ
    best = max(range(0, len(blob)-SZ*n+1),
               key=lambda o: row_corr(np.frombuffer(blob[o:o+SZ], np.uint8).reshape(H, W)))
    imgs, p = [], best
    while p + SZ <= len(blob):
        imgs.append(np.frombuffer(blob[p:p+SZ], np.uint8).reshape(H, W).astype(np.float64))
        p += SZ
    return imgs

def ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a*a).sum()*(b*b).sum())
    return float((a*b).sum()/d) if d else 0.0

def rotate(img, deg):
    """Rotacion bilineal alrededor del centro (sin scipy)."""
    if deg == 0:
        return img
    t = np.deg2rad(deg)
    cy, cx = (H-1)/2.0, (W-1)/2.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    dy, dx = yy-cy, xx-cx
    sy = cy + dy*np.cos(t) - dx*np.sin(t)
    sx = cx + dy*np.sin(t) + dx*np.cos(t)
    sy = np.clip(sy, 0, H-1); sx = np.clip(sx, 0, W-1)
    y0 = np.floor(sy).astype(int); x0 = np.floor(sx).astype(int)
    y1 = np.minimum(y0+1, H-1);    x1 = np.minimum(x0+1, W-1)
    fy = sy-y0; fx = sx-x0
    return (img[y0,x0]*(1-fy)*(1-fx) + img[y1,x0]*fy*(1-fx) +
            img[y0,x1]*(1-fy)*fx     + img[y1,x1]*fy*fx)

def best_align(a, b, max_shift, angles, margin=None):
    """NCC maxima de un parche central de 'a' deslizado sobre 'b'."""
    m = margin if margin is not None else max_shift
    m = max(m, max_shift)
    if H-2*m < 16 or W-2*m < 16:
        return None
    patch = a[m:H-m, m:W-m]
    ph, pw = patch.shape
    best = (-2.0, 0, 0, 0.0)
    for ang in angles:
        br = rotate(b, ang) if ang else b
        for dy in range(-max_shift, max_shift+1):
            for dx in range(-max_shift, max_shift+1):
                y, x = m+dy, m+dx
                if y < 0 or x < 0 or y+ph > H or x+pw > W:
                    continue
                s = ncc(patch, br[y:y+ph, x:x+pw])
                if s > best[0]:
                    best = (s, dx, dy, ang)
    return best

path = sys.argv[1] if len(sys.argv) > 1 else "test-storage.variant"
imgs = load_images(path)
pairs = list(itertools.combinations(range(len(imgs)), 2))
print(f"{len(imgs)} imagenes de {path}\n")

print("=== A) LO QUE HACE EL DRIVER HOY (radio 3 px, sin rotacion) ===")
cur = []
for i, j in pairs:
    r = best_align(imgs[i], imgs[j], 3, [0])
    cur.append(r[0]); print(f"  img{i}-img{j}: NCC={r[0]:+.4f}  (dx={r[1]:+d} dy={r[2]:+d})")
print(f"  --> media {np.mean(cur):+.4f}   max {max(cur):+.4f}   pasan 0.30: {sum(s>=0.30 for s in cur)}/{len(cur)}\n")

print("=== B) SOLO AMPLIANDO EL RADIO DE BUSQUEDA (sin rotacion) ===")
print(f"  {'radio':>6} {'media':>9} {'max':>9} {'pasan>=0.30':>12}")
for R in (3, 6, 9, 12, 16, 20):
    sc = [best_align(imgs[i], imgs[j], R, [0])[0] for i, j in pairs]
    print(f"  {R:>6} {np.mean(sc):>+9.4f} {max(sc):>+9.4f} {sum(s>=0.30 for s in sc):>8}/{len(sc)}")

print("\n=== C) RADIO + ROTACION ===")
angles = list(range(-15, 16, 3))
print(f"  angulos probados: {angles[0]}..{angles[-1]} paso 3 grados")
print(f"  {'radio':>6} {'media':>9} {'max':>9} {'pasan>=0.30':>12}")
best_cfg = None
for R in (8, 12, 16, 20):
    res = [best_align(imgs[i], imgs[j], R, angles) for i, j in pairs]
    sc = [r[0] for r in res]
    n_ok = sum(s >= 0.30 for s in sc)
    print(f"  {R:>6} {np.mean(sc):>+9.4f} {max(sc):>+9.4f} {n_ok:>8}/{len(sc)}")
    if best_cfg is None or n_ok > best_cfg[1]:
        best_cfg = (R, n_ok, res)

R, n_ok, res = best_cfg
print(f"\n=== D) DETALLE con el mejor ajuste (radio {R}, rotacion +-15) ===")
for (i, j), r in zip(pairs, res):
    flag = "OK " if r[0] >= 0.30 else "NO "
    print(f"  {flag} img{i}-img{j}: NCC={r[0]:+.4f}  dx={r[1]:+3d} dy={r[2]:+3d} ang={r[3]:+.0f}")
dxs = [abs(r[1]) for r in res]; dys = [abs(r[2]) for r in res]; ags = [abs(r[3]) for r in res]
print(f"\n  desplazamiento real medido: |dx| max={max(dxs)} med={np.mean(dxs):.1f} | "
      f"|dy| max={max(dys)} med={np.mean(dys):.1f} | |ang| max={max(ags):.0f} med={np.mean(ags):.1f}")
