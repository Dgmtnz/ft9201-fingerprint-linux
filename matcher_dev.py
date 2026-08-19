#!/usr/bin/env python3
"""Desarrollo del matcher para el FT9201 sobre imagenes CRUDAS de 64x80.

Candidato principal: BLPOC (Band-Limited Phase-Only Correlation), el enfoque
habitual para sensores de huella de area pequena. Localiza el desplazamiento
por FFT (sin busqueda exhaustiva) y usa la altura del pico como puntuacion.

Uso: matcher_dev.py <glob_genuinos> <glob_impostores>
"""
import sys, glob, itertools
import numpy as np

W, H = 64, 80

def load(pattern):
    fs = sorted(glob.glob(pattern))
    return [np.frombuffer(open(f,'rb').read(), np.uint8).reshape(H, W).astype(float) for f in fs], fs

# ---------- preprocesado ----------
def segment(img, blk=8, thr=0.35):
    """Marca bloques con crestas reales (alta varianza local)."""
    m = np.zeros((H, W), bool)
    vs = []
    for i in range(0, H, blk):
        for j in range(0, W, blk):
            vs.append(img[i:i+blk, j:j+blk].std())
    vmax = max(vs) if vs else 1.0
    for i in range(0, H, blk):
        for j in range(0, W, blk):
            if img[i:i+blk, j:j+blk].std() >= thr*vmax:
                m[i:i+blk, j:j+blk] = True
    return m

def normalize(img, blk=8):
    """Normalizacion local de contraste: media 0, varianza 1 por bloque."""
    o = np.zeros_like(img)
    for i in range(0, H, blk):
        for j in range(0, W, blk):
            p = img[i:i+blk, j:j+blk]
            s = p.std()
            o[i:i+blk, j:j+blk] = (p - p.mean())/s if s > 1e-6 else 0.0
    return o

def hann2d(h, w):
    return np.outer(np.hanning(h), np.hanning(w))

WIN = hann2d(H, W)

def prep(img, use_seg=True):
    x = normalize(img)
    if use_seg:
        x = x * segment(img)
    return x * WIN

# ---------- BLPOC ----------
def blpoc(a, b, band=0.35):
    """Correlacion de fase de banda limitada. Devuelve la altura del pico."""
    A = np.fft.fft2(a); B = np.fft.fft2(b)
    R = A * np.conj(B)
    m = np.abs(R)
    R = np.where(m > 1e-9, R/m, 0)
    # limitar banda: conservar solo las frecuencias bajas centrales
    Rs = np.fft.fftshift(R)
    kh, kw = int(H*band/2), int(W*band/2)
    mask = np.zeros_like(Rs)
    cy, cx = H//2, W//2
    mask[cy-kh:cy+kh+1, cx-kw:cx+kw+1] = 1
    Rs = Rs*mask
    c = np.fft.ifft2(np.fft.ifftshift(Rs)).real
    # normalizar por el numero de coeficientes conservados
    n = (2*kh+1)*(2*kw+1)
    return float(c.max() * (H*W) / n)

def evaluate(name, score_fn, gen, imp):
    gp = list(itertools.combinations(range(len(gen)), 2))
    g = np.array([score_fn(gen[i], gen[j]) for i,j in gp])
    m = np.array([score_fn(gen[i], imp[j]) for i in range(len(gen)) for j in range(len(imp))])
    # EER aproximado
    thrs = np.linspace(min(g.min(), m.min()), max(g.max(), m.max()), 600)
    best = None
    for t in thrs:
        frr = (g < t).mean()      # genuinos rechazados
        far = (m >= t).mean()     # impostores aceptados
        d = abs(frr-far)
        if best is None or d < best[0]:
            best = (d, t, frr, far)
    _, t, frr, far = best
    eer = (frr+far)/2
    # umbral con FAR=0 estricto
    t0 = m.max()
    frr_at_far0 = (g <= t0).mean()
    print(f"\n--- {name} ---")
    print(f"  genuinos : media {g.mean():+.4f}  min {g.min():+.4f}  max {g.max():+.4f}  (n={len(g)})")
    print(f"  impostores: media {m.mean():+.4f}  min {m.min():+.4f}  max {m.max():+.4f}  (n={len(m)})")
    print(f"  EER ~ {eer*100:5.1f}%  (umbral {t:.4f}, FRR {frr*100:.1f}%, FAR {far*100:.1f}%)")
    print(f"  con FAR=0 (umbral {t0:.4f}): rechaza al legitimo el {frr_at_far0*100:.1f}% de las veces")
    return eer

gen, gf = load(sys.argv[1])
imp, if_ = load(sys.argv[2]) if len(sys.argv) > 2 else ([], [])
print(f"genuinos: {len(gen)}   impostores: {len(imp)}")
if not imp:
    print("sin impostores todavia; solo estadistica de genuinos")
    gp = list(itertools.combinations(range(len(gen)), 2))
    pg = [prep(x) for x in gen]
    s = [blpoc(pg[i], pg[j]) for i,j in gp]
    print(f"BLPOC genuinos: media {np.mean(s):+.4f} min {min(s):+.4f} max {max(s):+.4f}")
    sys.exit(0)

pg = [prep(x) for x in gen]; pi = [prep(x) for x in imp]
pg_ns = [prep(x, False) for x in gen]; pi_ns = [prep(x, False) for x in imp]

for band in (0.20, 0.35, 0.50):
    evaluate(f"BLPOC banda={band} (con segmentacion)",
             lambda a,b,band=band: blpoc(a,b,band),
             pg, pi)
evaluate("BLPOC banda=0.35 (sin segmentacion)",
         lambda a,b: blpoc(a,b,0.35), pg_ns, pi_ns)
