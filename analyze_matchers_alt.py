#!/usr/bin/env python3
"""Compara algoritmos de matching alternativos sobre las mismas capturas.

Pregunta: existe algun matcher que separe genuinos de impostores con estas
imagenes de 64x80? Se evalua el margen = min(genuinos) - max(impostores).
Margen > 0 significa que existe un umbral seguro.
"""
import sys, itertools
import numpy as np

W, H, SZ = 64, 80, 5120

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
    while p+SZ <= len(blob):
        out.append(np.frombuffer(blob[p:p+SZ], np.uint8).reshape(H, W).astype(np.float64)); p += SZ
    return out

def sobel(img):
    kx = np.array([[-1,0,1],[-2,0,2],[-1,0,1]], float)
    ky = kx.T
    def conv(a, k):
        p = np.pad(a, 1, mode='edge'); o = np.zeros_like(a)
        for i in range(3):
            for j in range(3):
                o += k[i,j]*p[i:i+a.shape[0], j:j+a.shape[1]]
        return o
    return conv(img, kx), conv(img, ky)

def orientation_field(img, blk=8):
    """Campo de orientacion por bloques (metodo de gradientes al cuadrado).
    Devuelve (cos2t, sin2t, coherencia) por bloque."""
    gx, gy = sobel(img)
    gxx, gyy, gxy = gx*gx, gy*gy, gx*gy
    bh, bw = H//blk, W//blk
    c2 = np.zeros((bh,bw)); s2 = np.zeros((bh,bw)); coh = np.zeros((bh,bw))
    for i in range(bh):
        for j in range(bw):
            sl = (slice(i*blk,(i+1)*blk), slice(j*blk,(j+1)*blk))
            a = gxx[sl].sum(); b = gyy[sl].sum(); c = gxy[sl].sum()
            num = 2*c; den = a-b
            m = np.hypot(num, den)
            if m > 1e-9:
                c2[i,j] = den/m; s2[i,j] = num/m
            coh[i,j] = m/(a+b+1e-9)
    return c2, s2, coh

def orient_sim(A, B, max_shift_blk=2):
    """Similitud de campos de orientacion con busqueda de desplazamiento
    en bloques. Compara vectores de orientacion doblada, pesados por coherencia."""
    c2a, s2a, coha = A; c2b, s2b, cohb = B
    bh, bw = c2a.shape
    best = -2.0
    for dy in range(-max_shift_blk, max_shift_blk+1):
        for dx in range(-max_shift_blk, max_shift_blk+1):
            ys0, ys1 = max(0,-dy), min(bh, bh-dy)
            xs0, xs1 = max(0,-dx), min(bw, bw-dx)
            if (ys1-ys0)*(xs1-xs0) < bh*bw//2: continue
            pa = (c2a[ys0:ys1, xs0:xs1], s2a[ys0:ys1, xs0:xs1], coha[ys0:ys1, xs0:xs1])
            pb = (c2b[ys0+dy:ys1+dy, xs0+dx:xs1+dx], s2b[ys0+dy:ys1+dy, xs0+dx:xs1+dx],
                  cohb[ys0+dy:ys1+dy, xs0+dx:xs1+dx])
            wgt = pa[2]*pb[2]
            dot = pa[0]*pb[0] + pa[1]*pb[1]      # cos(2*(ta-tb))
            v = float((wgt*dot).sum()/(wgt.sum()+1e-9))
            if v > best: best = v
    return best

def binarize_skel_ncc(a, b, radius=12):
    """NCC sobre imagen binarizada localmente (realza crestas, quita presion)."""
    def binz(img, blk=8):
        o = np.zeros_like(img)
        for i in range(0, H, blk):
            for j in range(0, W, blk):
                sl = (slice(i,min(i+blk,H)), slice(j,min(j+blk,W)))
                o[sl] = (img[sl] > img[sl].mean()).astype(float)
        return o*2-1
    A, B = binz(a), binz(b)
    best = -2.0
    for dy in range(-radius, radius+1):
        for dx in range(-radius, radius+1):
            y0,y1 = max(0,-dy), min(H,H-dy); x0,x1 = max(0,-dx), min(W,W-dx)
            n = (y1-y0)*(x1-x0)
            if n < W*H//2: continue
            pa = A[y0:y1,x0:x1]; pb = B[y0+dy:y1+dy, x0+dx:x1+dx]
            v = float((pa*pb).sum()/n)
            if v > best: best = v
    return best

gen = load(sys.argv[1]); imp = load(sys.argv[2])
gp = list(itertools.combinations(range(len(gen)), 2))
ip = [(i,j) for i in range(len(gen)) for j in range(len(imp))]

print(f"genuinos: {len(gp)} pares | impostores: {len(ip)} pares\n")
print(f"{'matcher':>28} {'gen min':>9} {'gen med':>9} {'imp MAX':>9} {'imp med':>9} {'MARGEN':>9}  veredicto")
print("-"*95)

def evaluate(name, fn_gen, fn_imp):
    g = [fn_gen(i,j) for i,j in gp]
    m = [fn_imp(i,j) for i,j in ip]
    margin = min(g)-max(m)
    verdict = "SEPARA (usable)" if margin > 0 else "se solapan"
    print(f"{name:>28} {min(g):>+9.4f} {np.mean(g):>+9.4f} {max(m):>+9.4f} {np.mean(m):>+9.4f} {margin:>+9.4f}  {verdict}")

# 1) campo de orientacion
ofg = [orientation_field(x) for x in gen]
ofi = [orientation_field(x) for x in imp]
evaluate("campo orientacion (blk 8)",
         lambda i,j: orient_sim(ofg[i], ofg[j]),
         lambda i,j: orient_sim(ofg[i], ofi[j]))

ofg4 = [orientation_field(x, 4) for x in gen]
ofi4 = [orientation_field(x, 4) for x in imp]
evaluate("campo orientacion (blk 4)",
         lambda i,j: orient_sim(ofg4[i], ofg4[j], 4),
         lambda i,j: orient_sim(ofg4[i], ofi4[j], 4))

# 2) binarizado local + correlacion
evaluate("binarizado local r=12",
         lambda i,j: binarize_skel_ncc(gen[i], gen[j]),
         lambda i,j: binarize_skel_ncc(gen[i], imp[j]))
