#!/usr/bin/env python3
"""Extrae las imagenes 64x80 de un .variant a ficheros .raw sueltos."""
import sys, os
import numpy as np
W,H,SZ=64,80,5120
def load(p):
    b=open(p,"rb").read()
    def rc(im):
        a=im[:-1].astype(float).ravel(); c=im[1:].astype(float).ravel()
        a-=a.mean(); c-=c.mean(); d=np.sqrt((a*a).sum()*(c*c).sum())
        return float((a*c).sum()/d) if d else 0.
    n=len(b)//SZ
    off=max(range(0,len(b)-SZ*n+1), key=lambda o: rc(np.frombuffer(b[o:o+SZ],np.uint8).reshape(H,W)))
    o=[];q=off
    while q+SZ<=len(b): o.append(b[q:q+SZ]); q+=SZ
    return o
src, prefix, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(outdir, exist_ok=True)
for i,d in enumerate(load(src)):
    fn=os.path.join(outdir, f"{prefix}{i}.raw")
    open(fn,"wb").write(d)
    print("escrito", fn)
