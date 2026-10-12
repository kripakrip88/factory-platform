# Чтение DXF без потерь: секция ENTITIES, LINE / CIRCLE / ARC / LWPOLYLINE(с bulge). Только чтение.
import math
def _pairs(path):
    raw=open(path,"rb").read()
    try: txt=raw.decode("utf-8")
    except UnicodeDecodeError: txt=raw.decode("cp1251")
    L=txt.splitlines()
    return [(L[i].strip(),L[i+1].rstrip("\r")) for i in range(0,len(L)-1,2)]
def entities(path):
    pr=_pairs(path); out=[]; insec=False; cur=None; i=0
    while i<len(pr):
        c,v=pr[i]
        if c=="0" and v=="SECTION" and i+1<len(pr) and pr[i+1]==("2","ENTITIES"): insec=True; i+=2; continue
        if insec and c=="0" and v=="ENDSEC":
            if cur: out.append(cur)
            break
        if insec:
            if c=="0":
                if cur: out.append(cur)
                cur={"type":v,"g":[]}
            elif cur is not None: cur["g"].append((c,v.strip()))
        i+=1
    return out
def bulge_arc(p0,p1,b):
    # дуга LWPOLYLINE: b=tan(theta/4), b>0 — против часовой от p0 к p1
    theta=4*math.atan(b); ch=math.hypot(p1[0]-p0[0],p1[1]-p0[1])
    r=ch/(2*math.sin(abs(theta)/2))
    mx,my=(p0[0]+p1[0])/2,(p0[1]+p1[1])/2
    h=r*math.cos(theta/2)   # расстояние от хорды до центра (со знаком через theta)
    ux,uy=(p1[0]-p0[0])/ch,(p1[1]-p0[1])/ch
    nx,ny=-uy,ux             # левая нормаль
    s = 1 if b>0 else -1
    cx,cy=mx+nx*h*s*(1 if abs(theta)<math.pi else 1), my+ny*h*s
    # центр: для b>0 (CCW) центр слева от хорды при |theta|<pi
    cx,cy = mx + nx*(r*math.cos(theta/2))*(1 if b>0 else -1)*(1), my + ny*(r*math.cos(theta/2))*(1 if b>0 else -1)
    # средняя точка дуги: от середины хорды в сторону, противоположную центру, на сагитту
    sag=r-r*math.cos(theta/2)
    pmx,pmy = mx - nx*sag*(1 if b>0 else -1), my - ny*sag*(1 if b>0 else -1)
    return (cx,cy), r, (pmx,pmy)
def load(path):
    """-> holes [(x,y,d)], segs [{'t':'L'|'A', p0,p1, [c,r,pm]}], stats"""
    holes=[]; segs=[]; st={}
    for e in entities(path):
        t=e["type"]; st[t]=st.get(t,0)+1
        g=e["g"]
        def f(code,default=0.0):
            for c,v in g:
                if c==code: return float(v)
            return default
        if any(c=="230" and float(v)<0 for c,v in g): st["OCS_neg"]=st.get("OCS_neg",0)+1
        if t=="LINE":
            segs.append({"t":"L","p0":[f("10"),f("20")],"p1":[f("11"),f("21")]})
        elif t=="CIRCLE":
            holes.append((f("10"),f("20"),round(2*f("40"),3)))
        elif t=="ARC":
            cx,cy,r=f("10"),f("20"),f("40"); a0=math.radians(f("50")); a1=math.radians(f("51"))
            while a1<=a0: a1+=2*math.pi
            am=(a0+a1)/2
            segs.append({"t":"A","c":[cx,cy],"r":r,"p0":[cx+r*math.cos(a0),cy+r*math.sin(a0)],
                         "p1":[cx+r*math.cos(a1),cy+r*math.sin(a1)],"pm":[cx+r*math.cos(am),cy+r*math.sin(am)]})
        elif t=="LWPOLYLINE":
            closed=int(f("70",0))&1
            verts=[]; 
            for c,v in g:
                if c=="10": verts.append([float(v),None,0.0])
                elif c=="20": verts[-1][1]=float(v)
                elif c=="42": verts[-1][2]=float(v)
            n=len(verts); m=n if closed else n-1
            for i in range(m):
                a=verts[i]; b=verts[(i+1)%n]
                p0=[a[0],a[1]]; p1=[b[0],b[1]]
                if abs(a[2])<1e-9:
                    segs.append({"t":"L","p0":p0,"p1":p1})
                else:
                    c,r,pm=bulge_arc(p0,p1,a[2])
                    segs.append({"t":"A","c":list(c),"r":r,"p0":p0,"p1":p1,"pm":list(pm),"bulge":a[2]})
    return holes,segs,st
