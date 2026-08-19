#!/usr/bin/env python3
"""Pruebas de sanidad del BLPOC antes de sacar conclusiones."""
import numpy as np, glob
W,H=64,80
fs=sorted(glob.glob("dataset/indiceD_*.raw"))
imgs=[np.frombuffer(open(f,'rb').read(),np.uint8).reshape(H,W).astype(float) for f in fs]

def blpoc(a,b,band=0.35):
    A=np.fft.fft2(a); B=np.fft.fft2(b)
    R=A*np.conj(B); m=np.abs(R)
    R=np.where(m>1e-9,R/m,0)
    Rs=np.fft.fftshift(R)
    kh,kw=int(H*band/2),int(W*band/2)
    mask=np.zeros_like(Rs); cy,cx=H//2,W//2
    mask[cy-kh:cy+kh+1,cx-kw:cx+kw+1]=1
    c=np.fft.ifft2(np.fft.ifftshift(Rs*mask)).real
    n=(2*kh+1)*(2*kw+1)
    peak=c.max()*(H*W)/n
    pos=np.unravel_index(c.argmax(),c.shape)
    dy = pos[0] if pos[0]<=H//2 else pos[0]-H
    dx = pos[1] if pos[1]<=W//2 else pos[1]-W
    return peak,dx,dy

def norm_blocks(img,blk=8):
    o=np.zeros_like(img)
    for i in range(0,H,blk):
        for j in range(0,W,blk):
            p=img[i:i+blk,j:j+blk]; s=p.std()
            o[i:i+blk,j:j+blk]=(p-p.mean())/s if s>1e-6 else 0.
    return o

def norm_global(img):
    s=img.std()
    return (img-img.mean())/s if s>1e-6 else img*0

WIN=np.outer(np.hanning(H),np.hanning(W))

print("=== SANIDAD 1: imagen contra si misma (debe dar pico ~1.0, dx=dy=0) ===")
for name,f in [("cruda",lambda x:x),("norm global",norm_global),("norm bloques 8x8",norm_blocks)]:
    p,dx,dy=blpoc(f(imgs[0]),f(imgs[0]))
    print(f"  {name:20} pico={p:.4f}  dx={dx:+d} dy={dy:+d}")

print("\n=== SANIDAD 2: imagen contra si misma DESPLAZADA 7px derecha, 5px abajo ===")
sh=np.roll(np.roll(imgs[0],5,axis=0),7,axis=1)
for name,f in [("cruda",lambda x:x),("norm global",norm_global),("norm bloques 8x8",norm_blocks)]:
    p,dx,dy=blpoc(f(imgs[0]),f(sh))
    print(f"  {name:20} pico={p:.4f}  dx={dx:+d} dy={dy:+d}   (esperado dx=-7 dy=-5)")

print("\n=== SANIDAD 3: efecto de la ventana de Hann ===")
p,dx,dy=blpoc(norm_global(imgs[0])*WIN, norm_global(sh)*WIN)
print(f"  norm global + Hann   pico={p:.4f}  dx={dx:+d} dy={dy:+d}")

print("\n=== DIAGNOSTICO: ¿la rejilla 8x8 domina el espectro? ===")
nb=norm_blocks(imgs[0]); ng=norm_global(imgs[0])
for name,x in [("norm bloques",nb),("norm global",ng)]:
    F=np.abs(np.fft.fftshift(np.fft.fft2(x)))
    # energia en los armonicos de la rejilla (multiplos de H/8, W/8)
    cy,cx=H//2,W//2
    grid=0.
    for ky in range(-3,4):
        for kx in range(-3,4):
            if ky==0 and kx==0: continue
            y=cy+ky*(H//8); x_=cx+kx*(W//8)
            if 0<=y<H and 0<=x_<W: grid+=F[y,x_]**2
    print(f"  {name:15} energia en armonicos de rejilla: {grid/(F**2).sum()*100:6.2f}% del total")
