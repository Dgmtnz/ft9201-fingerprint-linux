#!/usr/bin/env python3
"""Evalua el matcher del driver focaltech_moh replicando su NCC exacta.

Reproduce ft9201_ncc() de focaltech_moh.c: correlacion sobre la region de
solapamiento completa, con la guarda n < w*h/2 -> -1.0.

Uso: analyze_matcher.py GENUINO.variant [IMPOSTOR.variant]
Mide tasa de aceptacion de genuinos (FRR) y de impostores (FAR) para
distintos radios de busqueda, y busca el punto de operacion optimo.
"""
import sys, itertools
import numpy as np

W, H, SZ = 64, 80, 5120
GUARD = W * H // 2          # 2560: minimo de pixeles solapados

def load(path):
    blob = open(path, "rb").read()
    def rc(im):
        a = im[:-1].astype(float).ravel(); b = im[1:].astype(float).ravel()
        a -= a.mean(); b -= b.mean()
        d = np.sqrt((a*a).sum()*(b*b).sum())
        return float((a*b).sum()/d) if d else 0.0
    n = len(blob)//SZ
    off = max(range(0, len(blob)-SZ*n+1),
              key=lambda o: rc(np.frombuffer(blob[o:o+SZ], np.uint8).reshape(H, W)))
    out, p = [], off
    while p + SZ <= len(blob):
        out.append(np.frombuffer(blob[p:p+SZ], np.uint8).reshape(H, W).astype(np.float64))
        p += SZ
    return out

def rotate(img, deg):
    if deg == 0: return img
    t = np.deg2rad(deg); cy, cx = (H-1)/2.0, (W-1)/2.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    dy, dx = yy-cy, xx-cx
    sy = np.clip(cy + dy*np.cos(t) - dx*np.sin(t), 0, H-1)
    sx = np.clip(cx + dy*np.sin(t) + dx*np.cos(t), 0, W-1)
    y0 = np.floor(sy).astype(int); x0 = np.floor(sx).astype(int)
    y1 = np.minimum(y0+1, H-1);    x1 = np.minimum(x0+1, W-1)
    fy = sy-y0; fx = sx-x0
    return (img[y0,x0]*(1-fy)*(1-fx) + img[y1,x0]*fy*(1-fx) +
            img[y0,x1]*(1-fy)*fx     + img[y1,x1]*fy*fx)

def ncc_driver(a, b, dx, dy):
    """Replica exacta de ft9201_ncc()."""
    x0, x1 = max(0, -dx), min(W, W-dx)
    y0, y1 = max(0, -dy), min(H, H-dy)
    n = (x1-x0)*(y1-y0)
    if n < GUARD: return -1.0
    pa = a[y0:y1, x0:x1]
    pb = b[y0+dy:y1+dy, x0+dx:x1+dx]
    da = pa - pa.mean(); db = pb - pb.mean()
    den = np.sqrt((da*da).sum()*(db*db).sum())
    return 0.0 if den < 1e-6 else float((da*db).sum()/den)

def best(a, b, radius, angles=(0,)):
    s = -2.0
    for ang in angles:
        br = rotate(b, ang) if ang else b
        for dy in range(-radius, radius+1):
            for dx in range(-radius, radius+1):
                v = ncc_driver(a, br, dx, dy)
                if v > s: s = v
    return s

gen_path = sys.argv[1]
imp_path = sys.argv[2] if len(sys.argv) > 2 else None
gen = load(gen_path)
print(f"genuino : {gen_path}  ({len(gen)} imgs)")
imp = None
if imp_path:
    imp = load(imp_path)
    print(f"impostor: {imp_path}  ({len(imp)} imgs)")
print()

gen_pairs = list(itertools.combinations(range(len(gen)), 2))
ANG = tuple(range(-15, 16, 3))

def report(radius, angles, label):
    g = [best(gen[i], gen[j], radius, angles) for i, j in gen_pairs]
    row = {"g_mean": np.mean(g), "g_min": min(g), "g": g}
    if imp:
        im = [best(gen[i], imp[j], radius, angles)
              for i in range(len(gen)) for j in range(len(imp))]
        row["i_mean"] = np.mean(im); row["i_max"] = max(im); row["i"] = im
    return row

print("=== BARRIDO DE RADIO (sin rotacion) ===")
print(f"{'radio':>6} {'gen media':>10} {'gen min':>9} {'imp media':>10} {'imp MAX':>9} {'margen':>8}")
rows = {}
for R in (3, 6, 9, 12, 16, 20, 24):
    r = report(R, (0,), f"r{R}")
    rows[('norot', R)] = r
    if imp:
        margin = r["g_min"] - r["i_max"]
        print(f"{R:>6} {r['g_mean']:>+10.4f} {r['g_min']:>+9.4f} {r['i_mean']:>+10.4f} {r['i_max']:>+9.4f} {margin:>+8.4f}")
    else:
        print(f"{R:>6} {r['g_mean']:>+10.4f} {r['g_min']:>+9.4f} {'--':>10} {'--':>9} {'--':>8}")

print("\n=== BARRIDO DE RADIO (con rotacion +-15 paso 3) ===")
print(f"{'radio':>6} {'gen media':>10} {'gen min':>9} {'imp media':>10} {'imp MAX':>9} {'margen':>8}")
for R in (6, 9, 12, 16, 20, 24):
    r = report(R, ANG, f"r{R}rot")
    rows[('rot', R)] = r
    if imp:
        margin = r["g_min"] - r["i_max"]
        print(f"{R:>6} {r['g_mean']:>+10.4f} {r['g_min']:>+9.4f} {r['i_mean']:>+10.4f} {r['i_max']:>+9.4f} {margin:>+8.4f}")
    else:
        print(f"{R:>6} {r['g_mean']:>+10.4f} {r['g_min']:>+9.4f} {'--':>10} {'--':>9} {'--':>8}")

if imp:
    print("\n=== PUNTO DE OPERACION: umbral que separa genuinos de impostores ===")
    print(f"{'config':>14} {'margen':>9} {'umbral sugerido':>17}  veredicto")
    for (kind, R), r in sorted(rows.items(), key=lambda kv: -(kv[1]['g_min']-kv[1]['i_max'])):
        m = r["g_min"] - r["i_max"]
        thr = (r["g_min"] + r["i_max"]) / 2
        verdict = "SEPARABLE" if m > 0 else "SE SOLAPAN - inseguro"
        print(f"{kind+' r='+str(R):>14} {m:>+9.4f} {thr:>17.3f}  {verdict}")
