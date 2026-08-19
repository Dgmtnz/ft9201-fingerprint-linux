#!/usr/bin/env python3
"""Hipotesis: algunas capturas llegan desplazadas ciclicamente por un fallo de
sincronizacion del protocolo, no por movimiento del dedo.

Si al desplazar CICLICAMENTE una imagen (np.roll) la correlacion con otra sube
a valores muy altos, el problema es de sincronizacion de la lectura bulk y se
arregla en el driver, no en el matcher.
"""
import sys, itertools
import numpy as np
W, H, SZ = 64, 80, 5120

def load(p):
    b=open(p,"rb").read()
    def rc(im):
        a=im[:-1].astype(float).ravel(); c=im[1:].astype(float).ravel()
        a-=a.mean(); c-=c.mean(); d=np.sqrt((a*a).sum()*(c*c).sum())
        return float((a*c).sum()/d) if d else 0.
    n=len(b)//SZ
    off=max(range(0,len(b)-SZ*n+1), key=lambda o: rc(np.frombuffer(b[o:o+SZ],np.uint8).reshape(H,W)))
    o=[];q=off
    while q+SZ<=len(b): o.append(np.frombuffer(b[q:q+SZ],np.uint8).reshape(H,W).astype(float)); q+=SZ
    return o

def ncc(a,b):
    a=a-a.mean(); b=b-b.mean()
    d=np.sqrt((a*a).sum()*(b*b).sum())
    return 0. if d<1e-9 else float((a*b).sum()/d)

imgs=load(sys.argv[1])
pairs=list(itertools.combinations(range(len(imgs)),2))

print("=== A) NCC directa, sin desplazar ===")
base=[ncc(imgs[i],imgs[j]) for i,j in pairs]
print(f"  media {np.mean(base):+.4f}  max {max(base):+.4f}\n")

print("=== B) Mejor NCC con desplazamiento CICLICO de pixeles del buffer ===")
print("   (equivale a leer el buffer empezando en otro offset)")
res=[]
for (i,j) in pairs:
    flat_j=imgs[j].ravel()
    best=(-2,0)
    for s in range(SZ):
        v=ncc(imgs[i].ravel(), np.roll(flat_j,s))
        if v>best[0]: best=(v,s)
    res.append(best)
    px=best[1]; print(f"  img{i}-img{j}: NCC={best[0]:+.4f} con roll={px:5d} px  (= {px//W:3d} filas + {px%W:2d} col)")
sc=[r[0] for r in res]
print(f"\n  media {np.mean(sc):+.4f}  min {min(sc):+.4f}  max {max(sc):+.4f}")
print(f"  pares que superan 0.30: {sum(s>=0.30 for s in sc)}/{len(sc)}")
print(f"  pares que superan 0.70: {sum(s>=0.70 for s in sc)}/{len(sc)}")

print("\n=== C) VEREDICTO ===")
mejora=np.mean(sc)-np.mean(base)
if np.mean(sc) > 0.70:
    print(f"  Las capturas SI son casi identicas tras corregir el offset (media {np.mean(sc):+.3f}).")
    print(f"  => El fallo es de SINCRONIZACION del protocolo, arreglable en el driver.")
elif mejora > 0.25:
    print(f"  Mejora sustancial (+{mejora:.3f}) pero no total: hay algo de desincronizacion")
    print(f"  ademas del movimiento real del dedo.")
else:
    print(f"  Sin mejora relevante (+{mejora:.3f}). Las capturas difieren de verdad;")
    print(f"  el problema NO es de sincronizacion sino del dedo/matcher.")

# ---- CONTROL: mismo procedimiento sobre pares NO relacionados ----
if len(sys.argv) > 2:
    imp = load(sys.argv[2])
    print("\n=== D) CONTROL: mismo barrido de 5120 rolls con dedos DISTINTOS ===")
    print("   (si sale parecido a B, la 'mejora' de B es sobreajuste, no sincronizacion)")
    ctrl = []
    for i in range(len(imgs)):
        for j in range(len(imp)):
            fj = imp[j].ravel(); b = -2.
            for s in range(SZ):
                v = ncc(imgs[i].ravel(), np.roll(fj, s))
                if v > b: b = v
            ctrl.append(b)
    print(f"  media {np.mean(ctrl):+.4f}  min {min(ctrl):+.4f}  max {max(ctrl):+.4f}")
    print(f"  pares que superan 0.30: {sum(s>=0.30 for s in ctrl)}/{len(ctrl)}")
    print("\n=== E) VEREDICTO FINAL ===")
    diff = np.mean(sc) - np.mean(ctrl)
    print(f"  genuinos con roll : {np.mean(sc):+.4f}")
    print(f"  impostores con roll: {np.mean(ctrl):+.4f}")
    print(f"  diferencia real    : {diff:+.4f}")
    if diff < 0.10:
        print("  => La mejora de B era SOBREAJUSTE. No hay evidencia de desincronizacion.")
    else:
        print("  => Queda senal genuina por encima del control; la hipotesis se sostiene.")
