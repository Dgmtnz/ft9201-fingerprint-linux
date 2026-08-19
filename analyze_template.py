#!/usr/bin/env python3
"""Extrae las imagenes del enroll de test-storage.variant y las analiza.

El driver focaltech_moh guarda la plantilla como GVariant "(ya(ay))":
version (byte) + array de imagenes de 64x80 = 5120 bytes ya preprocesadas.
"""
import sys, itertools
import numpy as np
from PIL import Image

W, H, SZ = 64, 80, 5120
path = sys.argv[1] if len(sys.argv) > 1 else "test-storage.variant"
blob = open(path, "rb").read()
print(f"fichero: {path}  ({len(blob)} bytes)")

# Las imagenes son bloques contiguos de 5120B. Localizamos el offset probando
# cual da la maxima autocorrelacion horizontal (una imagen real tiene filas
# correlacionadas con sus vecinas; el ruido no).
def row_corr(img):
    a = img[:-1].astype(float).ravel()
    b = img[1:].astype(float).ravel()
    a -= a.mean(); b -= b.mean()
    d = np.sqrt((a*a).sum() * (b*b).sum())
    return float((a*b).sum()/d) if d else 0.0

n_img = (len(blob)) // SZ
best = (None, -2)
for off in range(0, len(blob) - SZ*n_img + 1):
    img = np.frombuffer(blob[off:off+SZ], dtype=np.uint8).reshape(H, W)
    c = row_corr(img)
    if c > best[1]:
        best = (off, c)
off = best[0]
print(f"offset detectado: {off}  (correlacion inter-fila {best[1]:.4f})")

imgs = []
p = off
while p + SZ <= len(blob):
    imgs.append(np.frombuffer(blob[p:p+SZ], dtype=np.uint8).reshape(H, W))
    p += SZ
print(f"imagenes extraidas: {len(imgs)}\n")

def ncc(a, b):
    a = a.astype(float) - a.mean()
    b = b.astype(float) - b.mean()
    d = np.sqrt((a*a).sum() * (b*b).sum())
    return float((a*b).sum()/d) if d else 0.0

print("=== ESTADISTICAS POR IMAGEN ===")
print(f"{'#':>2} {'min':>4} {'max':>4} {'media':>7} {'std':>7} {'unicos':>7} {'corr-fila':>10}")
for i, im in enumerate(imgs):
    print(f"{i:>2} {im.min():>4} {im.max():>4} {im.mean():>7.1f} {im.std():>7.1f} "
          f"{len(np.unique(im)):>7} {row_corr(im):>10.4f}")

print("\n=== NCC ENTRE IMAGENES DEL MISMO DEDO (deberia ser ALTA) ===")
scores = []
for i, j in itertools.combinations(range(len(imgs)), 2):
    s = ncc(imgs[i], imgs[j])
    scores.append(s)
    print(f"  img{i} vs img{j}: {s:+.4f}")
if scores:
    print(f"\n  media {np.mean(scores):+.4f}   max {max(scores):+.4f}   min {min(scores):+.4f}")
    print(f"  umbral del driver: 0.30")

print("\n=== REFERENCIA: NCC de ruido aleatorio puro ===")
rng = np.random.default_rng(0)
noise = [rng.integers(0, 256, (H, W), dtype=np.uint8) for _ in range(5)]
ns = [ncc(a, b) for a, b in itertools.combinations(noise, 2)]
print(f"  media {np.mean(ns):+.4f}   max {max(ns):+.4f}")

for i, im in enumerate(imgs):
    Image.fromarray(im, "L").resize((W*4, H*4), Image.NEAREST).save(f"enroll_img{i}.png")
print(f"\nPNGs guardados: enroll_img0.png .. enroll_img{len(imgs)-1}.png (escalados x4)")
