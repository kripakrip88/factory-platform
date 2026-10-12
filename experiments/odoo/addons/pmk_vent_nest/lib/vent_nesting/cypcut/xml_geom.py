"""Minimal geometry reader for Geometry2D/data.bin (own re-implementation of the logic described in
lxds_report README s.5). Used by xml_validate.py for Utilization / OutlineID / thumbnail bounds."""
import struct, math

class Unsupported(Exception):
    pass

def geo(buf, off, kind):
    size = struct.unpack_from("<I", buf, off + 8)[0]
    rec = buf[off:off + size]
    name = kind.encode()
    i = rec.find(name, rec.find(b"\xc1\xc1\xc1\xc1"))
    if i < 0:
        raise Unsupported(kind)
    if kind == "Line":
        pts, j = [], i
        while len(pts) < 2:
            j = rec.find(b"\x10\x00\x02\x00", j)
            if j < 0: raise Unsupported(kind)
            pts.append(struct.unpack_from("<2d", rec, j + 4)); j += 20
        return {"kind": kind, "pts": pts, "bulge": [0.0, 0.0], "closed": False}
    if kind == "Circle":
        j = rec.find(b"\x10\x00\x02\x00", i)
        cx, cy, r = struct.unpack_from("<3d", rec, j + 4)
        a0 = struct.unpack_from("<d", rec, j + 32)[0]
        return {"kind": kind, "pts": [(cx + r * math.cos(a0), cy + r * math.sin(a0))], "bulge": [0.0], "closed": True, "circle": (cx, cy, r, a0)}
    if kind == "LwPolyline":
        for k in range(i + len(name), len(rec) - 12):
            n = struct.unpack_from("<I", rec, k + 4)[0]
            if 1 <= n <= 200000 and struct.unpack_from("<I", rec, k + 8)[0] == 1 and \
                    all(struct.unpack_from("<I", rec, k + 8 + 32 * q)[0] == q + 1 for q in range(min(n, 4))):
                flag = struct.unpack_from("<I", rec, k)[0]
                pts, bul = [], []
                for q in range(n):
                    x, y, b = struct.unpack_from("<3d", rec, k + 12 + 32 * q)
                    pts.append((x, y)); bul.append(b)
                return {"kind": kind, "pts": pts, "bulge": bul, "closed": bool(flag & 1)}
    raise Unsupported(kind)

def layer_of(buf, off):
    size = struct.unpack_from("<I", buf, off + 8)[0]
    rec = buf[off:off + size]
    i = rec.find(b"S\x00\x05\x00Shape")
    return struct.unpack_from("<I", rec, i + 16)[0] if i >= 0 else None

def points(sh, n_arc=16):
    P, B = sh["pts"], sh["bulge"]
    if sh.get("circle"):
        cx, cy, r, a0 = sh["circle"]
        n = max(24, min(180, int(2 * math.pi * r / 4)))
        return [(cx + r * math.cos(a0 + 2 * math.pi * k / n), cy + r * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n + 1)]
    if sh["kind"] == "Line":
        return [P[0], P[1]]
    out = []
    m = len(P) if sh["closed"] else len(P) - 1
    for i in range(m):
        a, c = P[i], P[(i + 1) % len(P)]
        bu = B[i] if i < len(B) else 0.0
        out.append(a)
        if abs(bu) > 1e-9:
            th = 4 * math.atan(bu); ch = math.hypot(c[0] - a[0], c[1] - a[1])
            if ch < 1e-9: continue
            r = ch / (2 * math.sin(abs(th) / 2))
            mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
            ux, uy = (c[0] - a[0]) / ch, (c[1] - a[1]) / ch
            d = r * math.cos(th / 2) * (1 if bu > 0 else -1)
            cx, cy = mx - uy * d, my + ux * d
            a0 = math.atan2(a[1] - cy, a[0] - cx)
            for t in range(1, n_arc):
                ang = a0 + th * t / n_arc
                out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    out.append(P[0] if sh["closed"] else P[-1])
    return out

def area(sh):
    """exact area for closed LwPolyline with bulges (polygon + circular segments), circle = pi r^2"""
    if sh.get("circle"):
        return math.pi * sh["circle"][2] ** 2
    P, B = sh["pts"], sh["bulge"]
    n = len(P)
    if not sh["closed"] or n < 2:
        return 0.0
    s = 0.0
    for i in range(n):
        a, c = P[i], P[(i + 1) % n]
        s += a[0] * c[1] - c[0] * a[1]
    s /= 2
    seg = 0.0
    for i in range(n):
        b = B[i]
        if abs(b) > 1e-12:
            a, c = P[i], P[(i + 1) % n]
            ch = math.hypot(c[0] - a[0], c[1] - a[1])
            th = 4 * math.atan(b)
            r = ch / (2 * math.sin(abs(th) / 2))
            segA = r * r / 2 * (abs(th) - math.sin(abs(th)))
            seg += segA if b > 0 else -segA
    return abs(s + seg)

def bbox(sh):
    pts = points(sh, 32)
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)
