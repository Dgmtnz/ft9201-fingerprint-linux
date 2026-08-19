#!/usr/bin/env python3
"""Evaluacion con la regla de decision REAL del driver: score = max sobre las
5 plantillas. Genuinos por leave-one-out (una imagen de consulta contra las
otras 4 como plantillas). Es la unica evaluacion comparable a lo que ocurre
en un verify de verdad.
"""
import sys, itertools
import numpy as np
W, H, SZ = 64, 80, 5120

def load(p):
    b = open(p,"rb").read()
    def rc(im):
        a=im[:-1].astype(float).ravel(); c=im[1:].astype(float).ravel()
        a-=a.mean(); c-=c.mean(); d=np.sqrt((a*a).sum()*(c*c).sum())
        return float((a*c).sum()/d) if d else 0.
    n=len(b)//SZ
    off=max(range(0,len(b)-SZ*n+1), key=lambda o: rc(np.frombuffer(b[o:o+SZ],np.uint8).reshape(H,W)))
    o=[];q=off
    while q+SZ<=len(b): o.append(np.frombuffer(b[q:q+SZ],np.uint8).reshape(H,W).astype(float)); q+=SZ
    return o

def sobel(img):
    kx=np.array([[-1,0,1],[-2,0,2],[-1,0,1]],float); ky=kx.T
    def conv(a,k):
        p=np.pad(a,1,mode='edge'); o=np.zeros_like(a)
        for i in range(3):
            for j in range(3): o+=k[i,j]*p[i:i+a.shape[0], j:j+a.shape[1]]
        return o
    return conv(img,kx), conv(img,ky)

def ofield(img, blk=8):
    gx,gy=sobel(img); gxx,gyy,gxy=gx*gx,gy*gy,gx*gy
    bh,bw=H//blk,W//blk
    c2=np.zeros((bh,bw)); s2=np.zeros((bh,bw)); coh=np.zeros((bh,bw))
    for i in range(bh):
        for j in range(bw):
            sl=(slice(i*blk,(i+1)*blk), slice(j*blk,(j+1)*blk))
            a=gxx[sl].sum(); b=gyy[sl].sum(); c=gxy[sl].sum()
            num=2*c; den=a-b; m=np.hypot(num,den)
            if m>1e-9: c2[i,j]=den/m; s2[i,j]=num/m
            coh[i,j]=m/(a+b+1e-9)
    return c2,s2,coh

def osim(A,B,ms=2):
    c2a,s2a,ca=A; c2b,s2b,cb=B; bh,bw=c2a.shape; best=-2.
    for dy in range(-ms,ms+1):
        for dx in range(-ms,ms+1):
            y0,y1=max(0,-dy),min(bh,bh-dy); x0,x1=max(0,-dx),min(bw,bw-dx)
            if (y1-y0)*(x1-x0) < bh*bw//2: continue
            w=ca[y0:y1,x0:x1]*cb[y0+dy:y1+dy,x0+dx:x1+dx]
            d=c2a[y0:y1,x0:x1]*c2b[y0+dy:y1+dy,x0+dx:x1+dx] + \
              s2a[y0:y1,x0:x1]*s2b[y0+dy:y1+dy,x0+dx:x1+dx]
            v=float((w*d).sum()/(w.sum()+1e-9))
            if v>best: best=v
    return best

def ncc_drv(a,b,dx,dy):
    x0,x1=max(0,-dx),min(W,W-dx); y0,y1=max(0,-dy),min(H,H-dy)
    n=(x1-x0)*(y1-y0)
    if n < W*H//2: return -1.
    pa=a[y0:y1,x0:x1]; pb=b[y0+dy:y1+dy,x0+dx:x1+dx]
    da=pa-pa.mean(); db=pb-pb.mean()
    d=np.sqrt((da*da).sum()*(db*db).sum())
    return 0. if d<1e-6 else float((da*db).sum()/d)

def ncc_best(a,b,r):
    return max(ncc_drv(a,b,dx,dy) for dy in range(-r,r+1) for dx in range(-r,r+1))

gen=load(sys.argv[1]); imp=load(sys.argv[2])
ofg=[ofield(x) for x in gen]; ofi=[ofield(x) for x in imp]

def run(name, simfn, gsim, isim):
    # genuinos: leave-one-out (consulta i vs las otras 4)
    gs=[max(gsim(i,j) for j in range(len(gen)) if j!=i) for i in range(len(gen))]
    # impostores: cada imagen impostora vs las 5 plantillas genuinas
    is_=[max(isim(k,j) for j in range(len(gen))) for k in range(len(imp))]
    margin=min(gs)-max(is_)
    print(f"\n--- {name} ---")
    print(f"  genuinos  (max sobre plantillas): {[f'{v:+.3f}' for v in gs]}")
    print(f"  impostores(max sobre plantillas): {[f'{v:+.3f}' for v in is_]}")
    print(f"  peor genuino {min(gs):+.4f} | mejor impostor {max(is_):+.4f} | MARGEN {margin:+.4f}")
    if margin>0:
        print(f"  ==> SEPARA. Umbral seguro sugerido: {(min(gs)+max(is_))/2:.3f}")
    else:
        print(f"  ==> se solapan, no hay umbral seguro")
    return margin

print("EVALUACION CON LA REGLA DE DECISION REAL (max sobre 5 plantillas)")
print("="*70)
run("NCC del driver, radio 3 (ACTUAL)", None,
    lambda i,j: ncc_best(gen[i],gen[j],3), lambda k,j: ncc_best(imp[k],gen[j],3))
run("NCC del driver, radio 12", None,
    lambda i,j: ncc_best(gen[i],gen[j],12), lambda k,j: ncc_best(imp[k],gen[j],12))
run("NCC del driver, radio 20", None,
    lambda i,j: ncc_best(gen[i],gen[j],20), lambda k,j: ncc_best(imp[k],gen[j],20))
run("Campo de orientacion (blk 8)", None,
    lambda i,j: osim(ofg[i],ofg[j]), lambda k,j: osim(ofi[k],ofg[j]))
