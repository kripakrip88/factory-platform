# -*- coding: utf-8 -*-
"""spec_verify — НЕЗАВИСИМАЯ проверка (свой код, без импорта кодеков других тем) ключевых утверждений
о Geometry2D/data.bin, Shapes2D/data.bin и их связи с XML на всех образцах.

usage: python3 -I spec_verify.py samples/*.lxds
Только стандартная библиотека. Образцы читаются как zip в памяти (данные, не код).
"""
import sys, struct, zipfile, hashlib, collections, math
import xml.etree.ElementTree as ET

D1, D0, C1, C0 = b"\xd1" * 4, b"\xd0" * 4, b"\xc1" * 4, b"\xc0" * 4
PT = 0x00020010


def al8(n):
    return (n + 7) & ~7


# ---------------------------------------------------------------- независимый разбор
def tstr(b, p):
    """tagged string at p -> (text, field_size_relative, field_size_absolute)"""
    tag, n = struct.unpack_from("<HH", b, p)
    assert tag == 0x53, hex(p)
    rel = al8(4 + n)
    ab = al8(p + 4 + n) - p
    return b[p + 4:p + 4 + n].decode("ascii"), rel, ab


def split_objects(b):
    assert b[:4] == b"BCMP"
    size, ver = struct.unpack_from("<II", b, 4)
    out, p = [], 0x1000
    while p < len(b):
        assert b[p:p + 4] == D1
        z0, L, z1 = struct.unpack_from("<III", b, p + 4)
        assert b[p + L - 4:p + L] == D0
        out.append((p, b[p:p + L], z0, z1, b[p + L:al8(p + L)]))
        p = al8(p + L)
    return dict(size=size, ver=ver, rest=b[12:0x1000], tail=b[p:]), out


def parse_obj(ob, base, strstat):
    """object bytes -> (cls, items) with items = ('sub', name, ver, len, z, payload, addr) | ('raw', bytes)"""
    cls, rel, ab = tstr(ob, 16)
    strstat[(base + 16) % 8, rel == ab] += 1
    q, items = 16 + rel, []
    end = len(ob) - 4
    while q < end:
        if ob[q:q + 4] == C1:
            ver, L, z = struct.unpack_from("<III", ob, q + 4)
            nm, rel, ab = tstr(ob, q + 16)
            strstat[(base + q + 16) % 8, rel == ab] += 1
            if rel != ab:  # единственная позиция, где правила (от поля / абсолютно) расходятся
                extra = ab - rel
                strstat["bytes_between_rel_and_abs_pad_all_zero", ob[q + 16 + rel:q + 16 + ab] == bytes(extra)] += 1
                strstat["unaligned_name", nm] += 1
            assert ob[q + L - 4:q + L] == C0
            items.append(("sub", nm, ver, L, z, ob[q + 16 + rel:q + L - 4], base + q))
            q += L
        else:
            items.append(("raw", ob[q:q + 4]))
            q += 4
    return cls, items


# ---------------------------------------------------------------- независимый кодировщик с нуля
def wstr(s):
    s = s.encode("ascii")
    return struct.pack("<HH", 0x53, len(s)) + s + bytes(al8(4 + len(s)) - 4 - len(s))


def wsub(name, ver, payload):
    nm = wstr(name)
    return C1 + struct.pack("<III", ver, 16 + len(nm) + len(payload) + 4, 0) + nm + payload + C0


def wobj(cls, body):
    c = wstr("TGks" + cls)
    return D1 + struct.pack("<III", 0, 16 + len(c) + len(body) + 4, 0) + c + body + D0


def geo_line(p1, p2):
    return wobj("Line", wsub("Line", 1, struct.pack("<I2dI2d", PT, p1[0], p1[1], PT, p2[0], p2[1])))


def geo_circle(cx, cy, r, a0):
    return wobj("Circle", wsub("Circle", 1, struct.pack("<I3dId", PT, cx, cy, r, 0, a0) + bytes(8)))


def geo_lw(verts, flag, sp):
    pl = struct.pack("<dII", sp, flag, len(verts))
    for k, (x, y, bu) in enumerate(verts):
        pl += struct.pack("<I3dI", k + 1, x, y, bu, 0)
    return wobj("LwPolyline", wsub("LwPolyline", 1, pl + struct.pack("<I", 0)))


def attr_rec(handle, cls, layer, coedge, flag64, outer, lead_payload=None):
    w = [0] * 13
    w[0], w[5], w[8] = layer, coedge, flag64
    body = wsub("Object", 1, struct.pack("<I", handle)) + wsub("Shape", 6, struct.pack("<13I", *w))
    if lead_payload is None:
        body += struct.pack("<II", 0, 0)
    else:
        body += struct.pack("<I", 1) + wsub("LeadParam", 1, lead_payload) + struct.pack("<I", 0)
    body += wsub("Curve", 2, struct.pack("<9I", outer, 0, 1, 0, 0, 0, 0, 0, 6))
    return wobj(cls, body)


def build_bin(objs):
    out = bytearray(b"BCMP" + bytes(0x1000 - 4))
    struct.pack_into("<I", out, 8, 1)
    addrs = []
    for ob in objs:
        addrs.append(len(out))
        out += ob + bytes(al8(len(ob)) - len(ob))
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out), addrs


def ndiff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))


# ---------------------------------------------------------------- проверка одного образца
def check(path, G):
    z = zipfile.ZipFile(path)
    name = path.rsplit("/", 1)[-1].replace(".lxds", "")
    R = collections.OrderedDict()
    gb, sb = z.read("Geometry2D/data.bin"), z.read("Shapes2D/data.bin")
    sx = ET.fromstring(z.read("Shapes2D/content.xml"))
    gx = z.read("Geometry2D/content.xml")
    els = [e for e in sx if e.tag != "MD5"]
    strstat = G["strstat"]

    # --- Geometry2D
    gh, gobjs = split_objects(gb)
    R["geo.hdr"] = (gh["size"] == len(gb), gh["ver"], gh["rest"] == bytes(len(gh["rest"])), gh["tail"] == b"")
    rebuilt, kinds = [], collections.Counter()
    geo_by_handle = {}
    for (addr, ob, z0, z1, pad), e in zip(gobjs, els):
        cls, items = parse_obj(ob, addr, strstat)
        assert (z0, z1) == (0, 0) and pad == bytes(len(pad))
        assert len(items) == 1 and items[0][0] == "sub" and items[0][1] == cls[4:] and items[0][2] == 1 and items[0][4] == 0
        assert cls == "TGks" + e.tag
        pl = items[0][5]
        k = e.tag
        kinds[k] += 1
        if k == "Line":
            t1, x1, y1, t2, x2, y2 = struct.unpack("<I2dI2d", pl)
            assert t1 == t2 == PT
            new = geo_line((x1, y1), (x2, y2))
            geo_by_handle[int(e.get("Handle"))] = ("Line", (x1, y1), (x2, y2))
        elif k == "Circle":
            t, cx, cy, r, u, a0 = struct.unpack_from("<I3dId", pl)
            assert t == PT and u == 0 and pl[40:48] == bytes(8) and len(pl) == 48
            new = geo_circle(cx, cy, r, a0)
            geo_by_handle[int(e.get("Handle"))] = ("Circle", cx, cy, r, a0)
        else:
            sp, fl, n = struct.unpack_from("<dII", pl)
            V = []
            for i in range(n):
                idx, x, y, bu, u = struct.unpack_from("<I3dI", pl, 16 + 32 * i)
                assert idx == i + 1 and u == 0
                V.append((x, y, bu))
            assert struct.unpack_from("<I", pl, 16 + 32 * n)[0] == 0 and len(pl) == 16 + 32 * n + 4
            new = geo_lw(V, fl, sp)
            geo_by_handle[int(e.get("Handle"))] = ("LwPolyline", V, fl, sp)
            G["lw_flag"][fl] += 1
        G["geo_obj_match"][new == ob] += 1
        rebuilt.append(new)
    data, addrs = build_bin(rebuilt)
    R["geo.scratch_diff_bytes"] = ndiff(data, gb)
    R["geo.GeoAddr==xml"] = addrs == [int(e.get("GeoAddr")) for e in els]
    md5g = hashlib.md5(gb).hexdigest().upper()
    R["geo.content.xml==template(md5)"] = gx == ('<?xml version="1.0" encoding="utf-8"?>\r\n<Geometry2D>\r\n\t<MD5>%s</MD5>\r\n</Geometry2D>\r\n' % md5g).encode()

    # --- Shapes2D
    sh, sobjs = split_objects(sb)
    R["shp.hdr"] = (sh["size"] == len(sb), sh["ver"], sh["rest"] == bytes(len(sh["rest"])), sh["tail"] == b"")
    rebuilt = []
    attrs = {}
    for (addr, ob, z0, z1, pad), e in zip(sobjs, els):
        cls, items = parse_obj(ob, addr, strstat)
        assert (z0, z1) == (0, 0) and pad == bytes(len(pad)) and cls == "TGks" + e.tag
        it = iter(items)
        o = next(it); assert o[1] == "Object" and o[2] == 1 and len(o[5]) == 4
        h = struct.unpack("<I", o[5])[0]
        assert h == int(e.get("Handle"))
        s = next(it); assert s[1] == "Shape" and s[2] == 6 and len(s[5]) == 52
        w = struct.unpack("<13I", s[5])
        G["shape_words_other_zero"][all(w[i] == 0 for i in range(13) if i not in (0, 5, 8))] += 1
        nl = struct.unpack("<I", next(it)[1])[0]
        lead = None
        if nl:
            lp = next(it); assert lp[1] == "LeadParam" and lp[2] == 1
            lead = lp[5]
            G["lead_payload"][lead.hex()] += 1
        tc = struct.unpack("<I", next(it)[1])[0]
        assert tc == 0
        c = next(it); assert c[1] == "Curve" and c[2] == 2
        cw = struct.unpack("<9I", c[5])
        G["curve_const"][cw[1:]] += 1
        assert next(it, None) is None
        new = attr_rec(h, e.tag, w[0], w[5], w[8], cw[0], lead)
        G["shp_obj_match"][new == ob] += 1
        rebuilt.append(new)
        attrs[h] = dict(layer=w[0], coedge=w[5], flag64=w[8], outer=cw[0], lead=lead is not None,
                        layername=e.get("LayerName"))
    data, addrs = build_bin(rebuilt)
    R["shp.scratch_diff_bytes"] = ndiff(data, sb)
    R["shp.DataAddr==xml"] = addrs == [int(e.get("DataAddr")) for e in els]
    R["shp.MD5==xml"] = sx.find("MD5").text == hashlib.md5(sb).hexdigest().upper()

    # --- порядок Shapes2D против Blocks / Plates / Results
    blocks = ET.fromstring(z.read("Blocks/content.xml"))
    bh = [int(b.get("Handle")) for b in blocks]
    R["blocks_sorted_by_handle"] = bh == sorted(bh)
    order = []
    owner = {}
    for b in blocks:
        for s in b.find("Shapes"):
            order.append(int(s.get("Handle")))
            owner[int(s.get("Handle"))] = ("block", b)
    plates = ET.fromstring(z.read("Nest2D/Plates/content.xml"))
    for p in plates:
        order.append(int(p.find("LwPolyline").get("Handle")))
        owner[order[-1]] = ("plate", p)
    res = ET.fromstring(z.read("Nest2D/Results/content.xml"))
    for r in res:
        rc = ET.fromstring(z.read("Nest2D/Results/%s/content.xml" % r.get("Index")))
        for s in rc.find("Shapes"):
            if s.get("Class") != "Insert":
                order.append(int(s.get("Handle")))
                owner[order[-1]] = ("rplate", rc)
    R["shapes2d_order==blocks+plates+resultplates"] = order == [int(e.get("Handle")) for e in els]

    # --- LayerName у кого есть / нет
    for h, a in attrs.items():
        kind = owner[h][0]
        if kind == "block":
            b = owner[h][1]
            role = "part" if b.get("Flags") == "512" or b.get("Name").startswith("CloneForNest") or not b.get("Name").startswith("{") else "blk{GUID}"
        else:
            role = kind
        G["layername_by_role"][(name, role, a["layername"])] += 1
        G["layer_by_role"][(role, a["layer"])] += 1

    # --- контуры, у которых start_param != 0, и где они
    for h, g in geo_by_handle.items():
        if g[0] == "LwPolyline" and g[3] != 0:
            b = owner[h][1]
            G["sp_nonzero_owner"][(name, "OutlineID" in b.attrib, b.get("Flags"), attrs[h]["lead"])] += 1
    G["files"][name] = R
    G["geo"][name] = geo_by_handle
    G["attrs"][name] = attrs
    return R


def main(paths):
    G = collections.defaultdict(collections.Counter)
    G["files"], G["geo"], G["attrs"] = {}, {}, {}
    for p in paths:
        R = check(p, G)
        print("==", p.rsplit("/", 1)[-1])
        for k, v in R.items():
            print("   %-45s %s" % (k, v))
    print("== итого по всем файлам")
    for k in ("geo_obj_match", "shp_obj_match", "shape_words_other_zero", "curve_const", "lw_flag"):
        print("   %-24s %s" % (k, dict(G[k])))
    print("   lead payloads:", {k[:24] + "..": v for k, v in G["lead_payload"].items()})
    print("   strings: (addr%8, rel==abs) ->", {str(k): v for k, v in G["strstat"].items()})
    print("   LayerName by role:")
    for k, v in sorted(G["layername_by_role"].items(), key=str):
        print("      ", k, v)
    print("   tech layer by role:", dict(G["layer_by_role"]))
    print("   start_param!=0 owners (file, block has OutlineID, Flags, has LeadParam):", dict(G["sp_nonzero_owner"]))


if __name__ == "__main__":
    main(sys.argv[1:])
