#!/usr/bin/env python3
"""Evaluacion con la regla de decision real (max sobre N plantillas) y estudio
del efecto del numero de plantillas. Tambien comprueba la hipotesis de que los
pares genuinos se dividen en 'solapan' y 'no solapan'.
"""
import numpy as np, glob, itertools
W,H=64,80
def load(p):
    return [np.frombuffer(open(f,'rb').read(),np.uint8).reshape(H,W).astype(float)
            for f in sorted(glob.glob(p))]
def poc_peak(a,b,band=0.5):
    A=np.fft.fft2(a); B=np.fft.fft2(b)
    R=A*np.conj(B); m=np.abs(R)
    R=np.where(m>1e-9,R/m,0)
    Rs=np.fft.fftshift(R); kh,kw=int(H*band/2),int(W*band/2)
    mask=np.zeros_like(Rs); cy,cx=H//2,W//2
    mask[cy-kh:cy+kh+1,cx-kw:cx+kw+1]=1
    return float(np.fft.ifft2(np.fft.ifftshift(Rs*mask)).real.max())
def ncc_shift(a,b,r=16):
    best=-2.
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            y0,y1=max(0,-dy),min(H,H-dy); x0,x1=max(0,-dx),min(W,W-dx)
            n=(y1-y0)*(x1-x0)
            if n<H*W//2: continue
            pa=a[y0:y1,x0:x1]; pb=b[y0+dy:y1+dy,x0+dx:x1+dx]
            da=pa-pa.mean(); db=pb-pb.mean()
            d=np.sqrt((da*da).sum()*(db*db).sum())
            if d>1e-9:
                v=float((da*db).sum()/d)
                if v>best: best=v
    return best

gen=load("dataset/indiceD_*.raw"); imp=load("dataset/otros_*.raw")
print(f"genuinos {len(gen)}  impostores {len(imp)}\n")

for mname, mfn in [("BLPOC pico(0.5)", poc_peak), ("NCC radio16", ncc_shift)]:
    print(f"########## {mname} ##########")
    # matriz genuino-genuino
    G=np.full((len(gen),len(gen)),-2.)
    for i,j in itertools.combinations(range(len(gen)),2):
        v=mfn(gen[i],gen[j]); G[i,j]=G[j,i]=v
    # matriz impostor-genuino
    M=np.zeros((len(imp),len(gen)))
    for i in range(len(imp)):
        for j in range(len(gen)):
            M[i,j]=mfn(imp[i],gen[j])

    gvals=G[np.triu_indices(len(gen),1)]
    print(f"  pares genuinos: media {gvals.mean():+.3f}  p10 {np.percentile(gvals,10):+.3f}  "
          f"p90 {np.percentile(gvals,90):+.3f}  max {gvals.max():+.3f}")
    print(f"  pares impostor: media {M.mean():+.3f}  p90 {np.percentile(M,90):+.3f}  max {M.max():+.3f}")
    hi=(gvals>np.percentile(M,99)).mean()
    print(f"  -> {hi*100:.0f}% de los pares genuinos superan el percentil 99 de impostores")

    print(f"\n  {'N plantillas':>13} {'EER':>7} {'FRR@FAR=0':>11}")
    rng=np.random.default_rng(0)
    for N in (1,3,5,10,15,24):
        gs,ms=[],[]
        for _ in range(60):
            for q in range(len(gen)):
                pool=[k for k in range(len(gen)) if k!=q]
                sel=rng.choice(pool,size=min(N,len(pool)),replace=False)
                gs.append(max(G[q,k] for k in sel))
            for q in range(len(imp)):
                sel=rng.choice(len(gen),size=min(N,len(gen)),replace=False)
                ms.append(max(M[q,k] for k in sel))
        gs=np.array(gs); ms=np.array(ms)
        lo,hi2=min(gs.min(),ms.min()),max(gs.max(),ms.max())
        best=None
        for t in np.linspace(lo,hi2,500):
            frr=(gs<t).mean(); far=(ms>=t).mean()
            if best is None or abs(frr-far)<best[0]: best=(abs(frr-far),frr,far)
        eer=(best[1]+best[2])/2
        frr0=(gs<=ms.max()).mean()
        print(f"  {N:>13} {eer*100:>6.1f}% {frr0*100:>10.1f}%")
    print()
