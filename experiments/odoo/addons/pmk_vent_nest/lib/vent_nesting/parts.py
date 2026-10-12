import json, math
from collections import defaultdict
TOL=0.05
def key(p): return (round(p[0]/TOL), round(p[1]/TOL))
def load(path):
    objs=json.load(open(path))
    holes=[]; segs=[]
    for o in objs:
        for e in o["edges"]:
            if e["t"]=="C": holes.append((e["c"][0],e["c"][1],round(e["r"]*2,2)))
            else: segs.append(e)
    return holes, segs
def components(segs):
    parent={}
    def f(a):
        while parent.setdefault(a,a)!=a:
            parent[a]=parent[parent[a]]; a=parent[a]
        return a
    def u(a,b): parent[f(a)]=f(b)
    for e in segs: u(key(e["p0"]),key(e["p1"]))
    comp=defaultdict(list)
    for e in segs: comp[f(key(e["p0"]))].append(e)
    out=[]
    for es in comp.values():
        pts=[]
        for e in es:
            pts+= [e["p0"],e["p1"]]+([e["pm"]] if "pm" in e else [])
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        # замкнутость: каждая вершина степени 2
        deg=defaultdict(int)
        for e in es: deg[key(e["p0"])]+=1; deg[key(e["p1"])]+=1
        closed=all(v==2 for v in deg.values())
        out.append({"edges":es,"bbox":[min(xs),max(xs),min(ys),max(ys)],"closed":closed,
                    "n_arc":sum(1 for e in es if e["t"]=="A")})
    return out
def ordered_poly(es, n_arc_samples=6):
    # обход замкнутого контура в порядке, дуги дискретизуем через p0-pm-p1
    adj=defaultdict(list)
    for i,e in enumerate(es):
        adj[key(e["p0"])].append(i); adj[key(e["p1"])].append(i)
    used=set(); poly=[]
    cur=es[0]; start=key(cur["p0"]); node=start; i=0
    order=[]
    while True:
        cand=[j for j in adj[node] if j not in used]
        if not cand: break
        j=cand[0]; used.add(j); e=es[j]
        fwd = key(e["p0"])==node
        a,b = (e["p0"],e["p1"]) if fwd else (e["p1"],e["p0"])
        if e["t"]=="A":
            poly += arc_points(e, fwd, n_arc_samples)[:-1]
        else:
            poly.append(a)
        node=key(b)
        if node==start: break
    return poly
def arc_points(e, fwd, n):
    cx,cy=e["c"]; r=e["r"]
    a0=math.atan2(e["p0"][1]-cy,e["p0"][0]-cx); a1=math.atan2(e["p1"][1]-cy,e["p1"][0]-cx)
    am=math.atan2(e["pm"][1]-cy,e["pm"][0]-cx)
    # направление p0->p1 через pm
    def norm(a): 
        while a<0: a+=2*math.pi
        while a>=2*math.pi: a-=2*math.pi
        return a
    ccw_span=norm(a1-a0); ccw_mid=norm(am-a0)
    if ccw_mid<=ccw_span: span=ccw_span
    else: span=-(2*math.pi-ccw_span)
    pts=[(cx+r*math.cos(a0+span*t/n), cy+r*math.sin(a0+span*t/n)) for t in range(n+1)]
    return pts if fwd else pts[::-1]
def inside(pt, poly):
    x,y=pt; c=False; n=len(poly)
    for i in range(n):
        x1,y1=poly[i]; x2,y2=poly[(i+1)%n]
        if (y1>y)!=(y2>y) and x < x1+(y-y1)*(x2-x1)/(y2-y1): c=not c
    return c
def close_gaps(segs, gap=35.0):
    # висячие концы крупных контуров соединяем виртуальными отрезками (только для разбора)
    comps=components(segs)
    big=[c for c in comps if max(c["bbox"][1]-c["bbox"][0],c["bbox"][3]-c["bbox"][2])>60]
    dang=[]
    for c in big:
        deg=defaultdict(int); pts={}
        for e in c["edges"]:
            for q in (e["p0"],e["p1"]): k=key(q); deg[k]+=1; pts[k]=q
        dang+=[pts[k] for k,v in deg.items() if v==1]
    used=set(); virt=[]
    pairs=[]
    for i in range(len(dang)):
        for j in range(i+1,len(dang)):
            d=math.hypot(dang[i][0]-dang[j][0],dang[i][1]-dang[j][1])
            if d<gap: pairs.append((d,i,j))
    for d,i,j in sorted(pairs):
        if i in used or j in used: continue
        used.add(i); used.add(j)
        virt.append({"t":"L","p0":dang[i],"p1":dang[j],"virtual":True,"gap":d})
    return segs+virt, virt
def analyze(path, report=None):
    if path.lower().endswith(".dxf"):
        from . import dxfread; holes,segs,_=dxfread.load(path)
    else:
        holes,segs=load(path)
    # дубли отрезков/отверстий — убрать (отчитаться)
    seen=set(); ded=[]
    for e in segs:
        k=(e["t"],)+tuple(sorted([tuple(round(v,2) for v in e["p0"]),tuple(round(v,2) for v in e["p1"])]))
        if k in seen:
            if report is not None: report.append({"dup_seg":e})
            continue
        seen.add(k); ded.append(e)
    segs=ded
    hs=set(); hd=[]
    for h in holes:
        k=(round(h[0],2),round(h[1],2),h[2])
        if k in hs:
            if report is not None: report.append({"dup_hole":h})
            continue
        hs.add(k); hd.append(h)
    holes=hd
    segs,virt=close_gaps(segs)
    if report is not None: report.extend(virt)
    comps=components(segs)
    parts=[c for c in comps if max(c["bbox"][1]-c["bbox"][0],c["bbox"][3]-c["bbox"][2])>60]
    small=[c for c in comps if c not in parts]
    for p in parts:
        p["poly"]=ordered_poly(p["edges"]) if p["closed"] else None
        p["holes"]=[]; p["slots"]=[]; p["smalls"]=[]
    for h in holes:
        for p in parts:
            if p["poly"] and inside((h[0],h[1]),p["poly"]): p["holes"].append(h); break
        else:
            if report is not None: report.append({"warn": "отверстие вне деталей (%.1f, %.1f) Ø%g" % (h[0], h[1], h[2])})
    for s in small:
        cx=(s["bbox"][0]+s["bbox"][1])/2; cy=(s["bbox"][2]+s["bbox"][3])/2
        for p in parts:
            if p["poly"] and inside((cx,cy),p["poly"]):
                (p["slots"] if s["n_arc"]>0 else p["smalls"]).append(s); break
        else:
            if report is not None: report.append({"warn": "мелкий контур вне деталей %s" % [round(v,1) for v in s["bbox"]]})
    return parts, small
