#!/usr/bin/env python3
"""Evaluacion limpia del matcher. BLPOC verificado con pruebas de sanidad.
Metricas: altura del pico y PSR (pico / desviacion de los lobulos laterales).
"""
import numpy as np, glob, itertools, sys
W,H=64,80

def load(p):
    return [np.frombuffer(open(f,'rb').read(),np.uint8).reshape(H,W).astype(float)
            for f in sorted(glob.glob(p))]

def norm_global(img):
    s=img.std(); return (img-img.mean())/s if s>1e-6 else img*0

def bandpass(img, lo=0.05, hi=0.45):
    """Filtro paso banda suave: quita continua/iluminacion y ruido fino."""
    F=np.fft.fftshift(np.fft.fft2(img))
    cy,cx=H//2,W//2
    yy,xx=np.mgrid[0:H,0:W]
    r=np.sqrt(((yy-cy)/(H/2))**2+((xx-cx)/(W/2))**2)
    m=np.exp(-(r/hi)**8)*(1-np.exp(-(r/lo)**4))
    return np.fft.ifft2(np.fft.ifftshift(F*m)).real

def poc_surface(a,b,band=1.0):
    A=np.fft.fft2(a); B=np.fft.fft2(b)
    R=A*np.conj(B); m=np.abs(R)
    R=np.where(m>1e-9,R/m,0)
    if band<1.0:
        Rs=np.fft.fftshift(R)
        kh,kw=int(H*band/2),int(W*band/2)
        mask=np.zeros_like(Rs); cy,cx=H//2,W//2
        mask[cy-kh:cy+kh+1,cx-kw:cx+kw+1]=1
        R=np.fft.ifftshift(Rs*mask)
    return np.fft.ifft2(R).real

def peak(a,b,band):
    return float(poc_surface(a,b,band).max())

def psr(a,b,band,excl=3):
    c=poc_surface(a,b,band)
    pos=np.unravel_index(c.argmax(),c.shape); pk=c[pos]
    mask=np.ones_like(c,bool)
    y0,y1=max(0,pos[0]-excl),min(H,pos[0]+excl+1)
    x0,x1=max(0,pos[1]-excl),min(W,pos[1]+excl+1)
    mask[y0:y1,x0:x1]=False
    side=c[mask]
    return float((pk-side.mean())/(side.std()+1e-9))

def evaluate(name, fn, gen, imp):
    gp=list(itertools.combinations(range(len(gen)),2))
    g=np.array([fn(gen[i],gen[j]) for i,j in gp])
    m=np.array([fn(gen[i],imp[j]) for i in range(len(gen)) for j in range(len(imp))])
    lo,hi=min(g.min(),m.min()),max(g.max(),m.max())
    best=None
    for t in np.linspace(lo,hi,800):
        frr=(g<t).mean(); far=(m>=t).mean()
        if best is None or abs(frr-far)<best[0]: best=(abs(frr-far),t,frr,far)
    _,t,frr,far=best; eer=(frr+far)/2
    frr0=(g<=m.max()).mean()
    sep=(g.mean()-m.mean())/np.sqrt((g.var()+m.var())/2)   # d-prime
    print(f"{name:38} EER {eer*100:5.1f}%  d'={sep:5.2f}  FRR@FAR0 {frr0*100:5.1f}%   gen {g.mean():+.3f}/imp {m.mean():+.3f}")
    return eer

gen=load("dataset/indiceD_*.raw"); imp=load("dataset/otros_*.raw")
print(f"genuinos {len(gen)}  impostores {len(imp)}\n")
print(f"{'configuracion':38} {'resultado'}")
print("-"*110)

variants = {
  "cruda":                 (gen, imp),
  "norm global":           ([norm_global(x) for x in gen],  [norm_global(x) for x in imp]),
  "bandpass 0.05-0.45":    ([bandpass(x) for x in gen],     [bandpass(x) for x in imp]),
  "bandpass 0.08-0.35":    ([bandpass(x,0.08,0.35) for x in gen], [bandpass(x,0.08,0.35) for x in imp]),
}
for vn,(G,I) in variants.items():
    for band in (1.0, 0.5, 0.3):
        evaluate(f"[{vn}] pico banda={band}", lambda a,b,band=band: peak(a,b,band), G, I)
    evaluate(f"[{vn}] PSR banda=0.5", lambda a,b: psr(a,b,0.5), G, I)
    print()
