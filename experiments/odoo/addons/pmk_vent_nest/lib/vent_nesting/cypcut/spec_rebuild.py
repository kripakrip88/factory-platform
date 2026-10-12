# -*- coding: utf-8 -*-
"""spec_rebuild — сквозная проверка сводной спецификации (LXDS_FORMAT.md) на настоящих файлах.

decompile(raw) -> модель высокого уровня (детали, листы, раскладки, вставки) + таблица «идентичности»
                  (хэндлы, GUID, время, порядок записей zip, параметры экрана для EMF, мусор шрифта EMF)
compile(model)  -> байты .lxds, собранные ТОЛЬКО по правилам спецификации: все длины, адреса, MD5,
                  DataAddr/GeoAddr, OutlineID, Flags, счётчики, Amount/AmountUsed, PartCount, PlanCount,
                  SizeX/SizeY, ExtMax, ActiveModelID, HandleSeed, точки листа, копии листа, info.xml,
                  content.xml, Viewports, zip — ВЫЧИСЛЯЮТСЯ, а не копируются.

Уровни:
  L0  replay   : геометрия блоков вставок берётся как есть; ждём побайтного совпадения всего архива.
  L1  placed   : геометрия блоков вставок NestPart ВЫЧИСЛЯЕТСЯ из блока детали по (theta, dx, dy,
                 порядок контуров); a0 окружности = a0 + theta. Показывает, какие байты не воспроизвести.
  L2  fresh    : новые хэндлы по правилу распределения, новые GUID, новое время, канонический порядок zip,
                 Utilization вычисляется; результат проверяется валидатором xml_validate.py (тема xml).

usage: python3 -I spec_rebuild.py OUTDIR sample.lxds ...
Только стандартная библиотека. Образцы читаются как данные (zip в памяти).
"""
import sys, os, io, math, struct, zipfile, hashlib, datetime, collections, uuid, random
import xml.etree.ElementTree as ET
from . import spec_verify as SV          # независимые кодировщики объектов Geometry2D / Shapes2D (свои)
from . import xml_model as XM            # Node / serialize / fmt_num (тема xml; проверено 84/84)
from . import xml_zip as XZ              # write_new (тема xml; проверено 5/5)
from . import xml_emf as XE              # generate (тема xml; проверено 15/15)
from . import spec_emf_tie2 as XT        # поправка листа для 6.3.907.11

Node, fmt = XM.Node, XM.fmt_num
FT_EPOCH = datetime.datetime(1601, 1, 1)


# =====================================================================================  чтение (decompile)
def _geo_payload(gb, addr):
    cl = struct.unpack_from("<H", gb, addr + 18)[0]
    q = addr + 16 + SV.al8(4 + cl)
    nl = struct.unpack_from("<H", gb, q + 18)[0]
    return q + 16 + SV.al8(4 + nl)


def read_shape(e, gb, sb):
    k, h = e.tag, int(e.get("Handle"))
    p = _geo_payload(gb, int(e.get("GeoAddr")))
    s = dict(handle=h, kind=k, layer_name=e.get("LayerName"))
    if k == "Line":
        v = struct.unpack_from("<I2dI2d", gb, p)
        s.update(p1=(v[1], v[2]), p2=(v[4], v[5]))
    elif k == "Circle":
        v = struct.unpack_from("<I3dId", gb, p)
        s.update(c=(v[1], v[2]), r=v[3], a0=v[5])
    else:
        sp, fl, n = struct.unpack_from("<dII", gb, p)
        s.update(sp=sp, flag=fl, verts=[struct.unpack_from("<3d", gb, p + 16 + 32 * i + 4) for i in range(n)])
    # Shapes2D: свой разбор по раскладке записи
    a = int(e.get("DataAddr"))
    L = struct.unpack_from("<I", sb, a + 8)[0]
    ob = sb[a:a + L]
    cls_sz = SV.al8(4 + struct.unpack_from("<H", ob, 18)[0])
    o = 16 + cls_sz                      # Object
    assert struct.unpack_from("<I", ob, o + 32)[0] == h
    w = struct.unpack_from("<13I", ob, o + 40 + 32)          # Shape words (Shape name field 16 bytes)
    q = o + 40 + 88
    nl = struct.unpack_from("<I", ob, q)[0]
    lead = None
    if nl:
        lead = ob[q + 4 + 32:q + 4 + 96 - 4]              # LeadParam payload (60 bytes)
        q += 96
    cw = struct.unpack_from("<9I", ob, q + 8 + 32)
    s.update(layer=w[0], coedge=w[5], flag64=w[8], outer=cw[0], lead=lead)
    return s


def decompile(raw):
    zf = zipfile.ZipFile(io.BytesIO(raw))
    X = lambda n: ET.fromstring(zf.read(n))
    entries, meta = XZ.parse(raw)
    gb, sb = zf.read("Geometry2D/data.bin"), zf.read("Shapes2D/data.bin")
    shapes = {int(e.get("Handle")): read_shape(e, gb, sb) for e in X("Shapes2D/content.xml") if e.tag != "MD5"}
    info = X("info.xml")
    hdr = X("content.xml").find("Header")
    M = dict(app_ver=info.find("Application").get("AppVer"), user=info.find("SavedBy").get("User"),
             computer=info.find("SavedBy").get("Computer"), header_id=hdr.get("ID"),
             org_app=(hdr.get("OrgAppName"), hdr.get("OrgAppVer")) if hdr.get("OrgAppName") else None,
             vport=int(X("Viewports/content.xml").find("VPort").get("Handle")),
             technical=zf.read("Technical/content.xml"),
             zip_order=[e["name"] for e in entries],
             zip_mtimes=[struct.unpack_from("<Q", bytes.fromhex(e["central_extra"]), 12)[0] for e in entries],
             utc_offset_h=10)
    # EMF: экран сохранявшего ПК и мусорный хвост имени шрифта — свойства окружения, не модели
    e1 = zf.read("Nest2D/Results/1/thumbnail.emf")
    h1 = XE.header(e1)
    M["emf"] = dict(device=tuple(h1["device"]), mm=tuple(h1["mm"]), face_tail=e1[124 + 12 + 28 + 14:124 + 12 + 28 + 64])
    # блоки
    parts_x = X("Nest2D/Parts/content.xml")
    part_blocks = {p.find("Insert").findtext("BlockName") for p in parts_x}
    res_x = X("Nest2D/Results/content.xml")
    ins_blocks, grp_blocks = set(), set()
    results = []
    for r in res_x:
        rc = X("Nest2D/Results/%s/content.xml" % r.get("Index"))
        R = dict(index=int(r.get("Index")), handle=int(rc.get("Handle")), id=rc.get("ID"), flags=rc.get("Flags"),
                 plate_amount=int(rc.get("PlateAmount")), util_str=rc.get("Utilization"), inserts=[],
                 given=dict(PartCount=r.get("PartCount"), PlanCount=r.get("PlanCount"), SizeX=r.get("SizeX"),
                            SizeY=r.get("SizeY"), ExtMax=(rc.find("ExtMax").get("X"), rc.find("ExtMax").get("Y"))))
        for s in rc.find("Shapes"):
            if s.get("Class") != "Insert":
                R["plate"], R["plate_shape_handle"] = int(s.get("NestPlate")), int(s.get("Handle"))
                continue
            ref = ("NestPart", int(s.get("NestPart"))) if s.get("NestPart") else ("NestGroup", int(s.get("NestGroup")))
            R["inserts"].append(dict(handle=int(s.get("Handle")), ref=ref, block=s.findtext("BlockName"),
                                     channelport=s.get("ChannelPort") is not None, selected=s.get("Selected")))
            (ins_blocks if ref[0] == "NestPart" else grp_blocks).add(s.findtext("BlockName"))
        results.append(R)
    M["results"] = results
    blocks = []
    for b in X("Blocks/content.xml"):
        nm = b.get("Name")
        role = "part" if nm in part_blocks else "insert" if nm in ins_blocks else "group" if nm in grp_blocks else "stale"
        blocks.append(dict(handle=int(b.get("Handle")), name=nm, role=role,
                           # необъяснённое исключение (m30 «Деталь1» и его копии): OutlineID не записан
                           outline_override=None if (b.get("OutlineID") is None and role in ("part", "insert")) else "derive",
                           given=dict(OutlineID=b.get("OutlineID"), Flags=b.get("Flags"),
                                      ShapesHandle=b.find("Shapes").get("Handle")),
                           shapes=[shapes[int(s.get("Handle"))] for s in b.find("Shapes")]))
    M["blocks"] = blocks
    M["parts"] = [dict(handle=int(p.get("Handle")), insert_handle=int(p.find("Insert").get("Handle")),
                       name=p.get("Name"), guid=p.get("GUID"), block=p.find("Insert").findtext("BlockName"),
                       given=dict(Amount=p.get("Amount"), AmountUsed=p.get("AmountUsed"))) for p in parts_x]
    M["groups"] = []
    if "Nest2D/Parts/Groups/content.xml" in zf.namelist():
        for g in X("Nest2D/Parts/Groups/content.xml"):
            M["groups"].append(dict(handle=int(g.get("Handle")), name=g.get("Name"), amount=g.get("Amount"),
                                    amount_used=g.get("AmountUsed"), guid=g.get("GUID"),
                                    objects=[int(o.get("Handle")) for o in g]))
    M["plates"] = []
    for p in X("Nest2D/Plates/content.xml"):
        lw = p.find("LwPolyline")
        pts = [(float(q.get("X", 0)), float(q.get("Y", 0))) for q in lw.findall("Point")]
        M["plates"].append(dict(handle=int(p.get("Handle")), poly_handle=int(lw.get("Handle")), guid=p.get("GUID"),
                                W=pts[2][0], L=pts[2][1], poly_has_nestplate=lw.get("NestPlate") is not None,
                                given=dict(Amount=p.get("Amount"), AmountUsed=p.get("AmountUsed"), pts=pts)))
    return M


# =====================================================================================  геометрия
def poly_area(verts, closed=True):
    """signed area of a closed LwPolyline with DXF bulges (CCW > 0)"""
    n = len(verts)
    A = 0.0
    for i in range(n):
        x1, y1, b = verts[i]
        x2, y2, _ = verts[(i + 1) % n]
        A += (x1 * y2 - x2 * y1) / 2
        if b:
            th = 4 * math.atan(b)
            ch = math.hypot(x2 - x1, y2 - y1)
            r = ch / (2 * math.sin(abs(th) / 2))
            A += math.copysign(r * r / 2 * (abs(th) - math.sin(abs(th))), b)
    return A


def shape_area(s):
    if s["kind"] == "Circle":
        return math.pi * s["r"] ** 2
    if s["kind"] == "LwPolyline" and s["flag"] & 1:
        return abs(poly_area(s["verts"]))
    return None


def block_util_area(shapes):
    """площадь детали для Utilization: внешний (наибольший замкнутый) минус ВСЕ прочие замкнутые"""
    ar = [a for a in (shape_area(s) for s in shapes) if a is not None]
    if not ar:
        return 0.0
    m = max(ar)
    return m - (sum(ar) - m)


def derived_outline(shapes):
    best = None
    for s in shapes:
        a = shape_area(s)
        if a is not None and s["layer"] == 1 and (best is None or a > best[0]):
            best = (a, s["handle"])
    return best[1] if best else None


ROT = {0: lambda x, y: (x, y), 90: lambda x, y: (-y, x), 180: lambda x, y: (-x, -y), 270: lambda x, y: (y, -x)}


def transform_shape(s, th, d, handle):
    t = dict(s, handle=handle)
    f = ROT[th]
    if s["kind"] == "Line":
        a, b = f(*s["p1"]), f(*s["p2"])
        t.update(p1=(a[0] + d[0], a[1] + d[1]), p2=(b[0] + d[0], b[1] + d[1]))
    elif s["kind"] == "Circle":
        c = f(*s["c"])
        t.update(c=(c[0] + d[0], c[1] + d[1]), a0=(s["a0"] + math.radians(th)) % (2 * math.pi) if th else s["a0"])
    else:
        t["verts"] = [(f(x, y)[0] + d[0], f(x, y)[1] + d[1], b) for x, y, b in s["verts"]]
    return t


def key_pts(s):
    if s["kind"] == "Line":
        return [s["p1"], s["p2"]]
    if s["kind"] == "Circle":
        return [s["c"]]
    return [(x, y) for x, y, b in s["verts"]]


def find_placement(pb, rb):
    """part block shapes, result block shapes -> (theta, d, order) with order[i] = part index of result shape i"""
    for th in (0, 90, 180, 270):
        o_p, o_r = pb[-1], rb[-1]
        if o_p["kind"] != o_r["kind"]:
            continue
        kp, kr = key_pts(o_p)[0], key_pts(o_r)[0]
        rp = ROT[th](*kp)
        d = (kr[0] - rp[0], kr[1] - rp[1])
        order, used = [], set()
        ok = True
        for s in rb:
            hit = None
            for j, q in enumerate(pb):
                if j in used or q["kind"] != s["kind"] or len(key_pts(q)) != len(key_pts(s)):
                    continue
                tq = transform_shape(q, th, d, 0)
                if all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6 for a, b in zip(key_pts(tq), key_pts(s))):
                    if q["kind"] == "Circle" and abs(((tq["a0"] - s["a0"] + math.pi) % (2 * math.pi)) - math.pi) > 1e-6:
                        continue
                    hit = j
                    break
            if hit is None:
                ok = False
                break
            used.add(hit)
            order.append(hit)
        if ok:
            return th, d, order
    raise ValueError("no rigid placement found")


# =====================================================================================  запись (compile)
def geo_bytes(s):
    if s["kind"] == "Line":
        return SV.geo_line(s["p1"], s["p2"])
    if s["kind"] == "Circle":
        return SV.geo_circle(s["c"][0], s["c"][1], s["r"], s["a0"])
    return SV.geo_lw(s["verts"], s["flag"], s["sp"])


def attr_bytes(s):
    coedge = int(s["kind"] == "LwPolyline" and not (s["flag"] & 1) and s["layer"] == 1)
    return SV.attr_rec(s["handle"], s["kind"], s["layer"], coedge, s["flag64"], s["outer"], s["lead"])


def plate_shape(handle, W, L):
    return dict(handle=handle, kind="LwPolyline", layer_name=None, verts=[(0.0, 0.0, 0.0), (W, 0.0, 0.0), (W, L, 0.0), (0.0, L, 0.0)],
                flag=1, sp=0.0, layer=0, coedge=0, flag64=0, outer=0, lead=None)


def xml(root):
    return XM.serialize(root)


def emf_shape(s):
    if s["kind"] == "Line":
        return dict(kind="Line", pts=[s["p1"], s["p2"]], bulge=[0, 0], closed=False)
    if s["kind"] == "Circle":
        cx, cy = s["c"]
        return dict(kind="Circle", pts=[(cx + s["r"] * math.cos(s["a0"]), cy + s["r"] * math.sin(s["a0"]))], bulge=[0.0],
                    closed=True, circle=(cx, cy, s["r"], s["a0"]))
    return dict(kind="LwPolyline", pts=[(x, y) for x, y, b in s["verts"]], bulge=[b for x, y, b in s["verts"]],
                closed=bool(s["flag"] & 1))


def compile_lxds(M, checks, util_mode="given"):
    C = checks
    v11 = M["app_ver"].endswith(".11")
    blocks_by_name = {b["name"]: b for b in M["blocks"]}
    part_by_h = {p["handle"]: p for p in M["parts"]}
    grp_by_h = {g["handle"]: g for g in M["groups"]}
    plate_by_h = {p["handle"]: p for p in M["plates"]}

    # ---- Shapes2D / Geometry2D: порядок = блоки (по возрастанию хэндла) -> листы -> копии листов в раскладках
    seq = []
    for b in M["blocks"]:
        seq += b["shapes"]
    for p in M["plates"]:
        seq.append(plate_shape(p["poly_handle"], p["W"], p["L"]))
    for r in M["results"]:
        pl = plate_by_h[r["plate"]]
        seq.append(plate_shape(r["plate_shape_handle"], pl["W"], pl["L"]))
    gbin, gaddr = SV.build_bin([geo_bytes(s) for s in seq])
    sbin, saddr = SV.build_bin([attr_bytes(s) for s in seq])
    sx = Node("Shapes2D", children=[Node(s["kind"], [("Handle", str(s["handle"]))] + ([("LayerName", s["layer_name"])] if s["layer_name"] is not None else [])
                                         + [("DataAddr", str(da)), ("GeoAddr", str(ga))]) for s, da, ga in zip(seq, saddr, gaddr)]
              + [Node("MD5", text=hashlib.md5(sbin).hexdigest().upper())])
    gx = ('<?xml version="1.0" encoding="utf-8"?>\r\n<Geometry2D>\r\n\t<MD5>%s</MD5>\r\n</Geometry2D>\r\n'
          % hashlib.md5(gbin).hexdigest().upper()).encode()

    # ---- Blocks
    bnodes = []
    for b in M["blocks"]:
        at = [("Handle", str(b["handle"])), ("Name", b["name"])]
        if b["role"] in ("part", "insert"):
            ol = b.get("outline_override", "derive")
            oid = derived_outline(b["shapes"]) if ol == "derive" else ol
            C["OutlineID derived == given (part/insert blocks)"][str(derived_outline(b["shapes"])) == str(b["given"]["OutlineID"])] += 1
            if oid is not None:
                at.append(("OutlineID", str(oid)))
                C["OutlineID is the LAST shape of the block"][b["shapes"][-1]["handle"] == oid] += 1
        elif b["given"]["OutlineID"] is not None:
            at.append(("OutlineID", b["given"]["OutlineID"]))       # группы / устаревшие: как дано
        flags = "512" if (b["role"] == "part" and v11) else None
        if b["role"] in ("part", "insert", "group"):
            C["Block Flags derived (512 = part block in .11) == given"][flags == b["given"]["Flags"]] += 1
        else:
            flags = b["given"]["Flags"]
        if flags:
            at.append(("Flags", flags))
        C["Shapes Handle == Block+1"][str(b["handle"] + 1) == b["given"]["ShapesHandle"]] += 1
        bnodes.append(Node("Block", at, children=[Node("BasePoint"), Node("Shapes", [("Handle", str(b["handle"] + 1))],
                       children=[Node("Shape", [("Class", s["kind"]), ("Handle", str(s["handle"]))]) for s in b["shapes"]])]))
    blocks_xml = xml(Node("Blocks", children=bnodes))

    # ---- количества
    part_used = collections.Counter()
    plate_used = collections.Counter()
    grp_used = collections.Counter()
    util_calc = {}
    for r in M["results"]:
        plate_used[r["plate"]] += r["plate_amount"]
        tot = 0.0
        pc = 0
        for i in r["inserts"]:
            if i["ref"][0] == "NestPart":
                part_used[i["ref"][1]] += r["plate_amount"]
                tot += block_util_area(blocks_by_name[part_by_h[i["ref"][1]]["block"]]["shapes"])
                pc += 1
            else:
                g = grp_by_h[i["ref"][1]]
                grp_used[g["handle"]] += r["plate_amount"]
                for o in g["objects"]:
                    part_used[o] += r["plate_amount"]
                    if o not in part_by_h:
                        C["group object -> missing NestPart"][True] += 1
                        continue
                    tot += block_util_area(blocks_by_name[part_by_h[o]["block"]]["shapes"])
                    pc += 1
        pl = plate_by_h[r["plate"]]
        util_calc[r["index"]] = (fmt(100.0 * tot / (pl["W"] * pl["L"])), pc)

    # ---- Nest2D/Parts
    pn = []
    for p in M["parts"]:
        amt = str(part_used[p["handle"]])
        C["NestPart Amount == AmountUsed == sum(used x PlateAmount)"][amt == p["given"]["Amount"] == p["given"]["AmountUsed"]] += 1
        ins = lambda tag: Node(tag, ([("Class", "Insert")] if tag == "Shape" else []) + [("Handle", str(p["insert_handle"])), ("ChannelPort", "1")],
                               children=[Node("BlockName", text=p["block"]), Node("XScale", text="1"), Node("YScale", text="1")])
        pn.append(Node("NestPart", [("Handle", str(p["handle"])), ("Name", p["name"]), ("Amount", amt), ("AmountUsed", amt),
                                    ("GUID", p["guid"]), ("ShapeCls", "Insert")], children=[ins("Insert"), ins("Shape"), Node("ExtShapes")]))
    parts_xml = xml(Node("Parts", children=pn))

    # ---- Groups (только как данные: генератор групп не делает)
    groups_xml = None
    if M["groups"]:
        gn = []
        for g in M["groups"]:
            used = grp_used[g["handle"]]
            au = str(1 + used) if used else g["amount_used"]
            C["NestGroup AmountUsed == 1 + sum(PlateAmount) (used groups)"][au == g["amount_used"]] += 1
            gn.append(Node("NestGroup", [("Handle", str(g["handle"])), ("Name", g["name"]), ("Amount", g["amount"])]
                           + ([("AmountUsed", au)] if au is not None else []) + [("GUID", g["guid"])],
                           children=[Node("Object", [("Handle", str(o))]) for o in g["objects"]]))
        groups_xml = xml(Node("Groups", children=gn))

    # ---- Plates
    pln = []
    for p in M["plates"]:
        amt = str(plate_used[p["handle"]])
        C["NestPlate Amount == AmountUsed == sum(PlateAmount)"][amt == p["given"]["Amount"] == p["given"]["AmountUsed"]] += 1
        pts = [(0, 0), (p["W"], 0), (p["W"], p["L"]), (0, p["L"])]
        C["plate XML points == (0,0),(W,0),(W,L),(0,L)"][pts == p["given"]["pts"]] += 1
        ptn = [Node("Point", ([("X", fmt(x))] if x else []) + ([("Y", fmt(y))] if y else [])) for x, y in pts]
        npa = [("NestPlate", str(p["handle"]))] if p["poly_has_nestplate"] else []
        pln.append(Node("NestPlate", [("Handle", str(p["handle"])), ("Name", "Rectangle"), ("Amount", amt), ("AmountUsed", amt),
                                      ("GUID", p["guid"]), ("ShapeCls", "LwPolyline")],
                        children=[Node("LwPolyline", [("Handle", str(p["poly_handle"]))] + npa + [("LeadInOptimizeFlag", "6"), ("PointCount", "4"), ("PolyFlag", "1")],
                                       children=[Node("ToolCompensation")] + ptn),
                                  Node("Shape", [("Class", "LwPolyline"), ("Handle", str(p["poly_handle"]))] + npa), Node("ExtShapes")]))
    plates_xml = xml(Node("Plates", children=pln))

    # ---- Results
    summary, rfiles, emfs = [], {}, {}
    for r in M["results"]:
        pl = plate_by_h[r["plate"]]
        u, pc = util_calc[r["index"]]
        C["Utilization computed == stored string"][u == r["util_str"]] += 1
        if r["util_str"] is not None and u != r["util_str"]:
            C["Utilization rel.err max x1e9"][0] = max(C["Utilization rel.err max x1e9"][0], int(1e9 * abs(float(u) - float(r["util_str"])) / float(r["util_str"])))
        util = u if util_mode == "computed" else r["util_str"]
        W, L = fmt(pl["W"]), fmt(pl["L"])
        g = r["given"]
        C["PartCount/PlanCount/SizeX/SizeY/ExtMax derived == given"][(str(pc), str(r["plate_amount"]), W, L, (W, L)) == (g["PartCount"], g["PlanCount"], g["SizeX"], g["SizeY"], g["ExtMax"])] += 1
        summary.append(Node("NestResult", [("Index", str(r["index"])), ("Name", "Nest result"), ("PartCount", str(pc)), ("Utilization", util),
                                           ("PlanCount", str(r["plate_amount"])), ("SizeX", W), ("SizeY", L), ("ID", r["id"])]))
        C["result plate copy Handle == R+3, inserts R+4.."][[r["plate_shape_handle"]] + [i["handle"] for i in r["inserts"]] == list(range(r["handle"] + 3, r["handle"] + 4 + len(r["inserts"])))] += 1
        sh = [Node("Shape", [("Class", "LwPolyline"), ("Handle", str(r["plate_shape_handle"])), ("NestPlate", str(r["plate"]))])]
        for i in r["inserts"]:
            at = [("Class", "Insert"), ("Handle", str(i["handle"]))] + ([("ChannelPort", "1")] if i["channelport"] else []) \
                 + [(i["ref"][0], str(i["ref"][1]))] + ([("Selected", i["selected"])] if i["selected"] else [])
            sh.append(Node("Shape", at, children=[Node("BlockName", text=i["block"]), Node("XScale", text="1"), Node("YScale", text="1")]))
        rat = [("Handle", str(r["handle"])), ("Name", "Nest result"), ("ID", r["id"])] + ([("Flags", r["flags"])] if r["flags"] else []) \
              + [("PlateAmount", str(r["plate_amount"])), ("Utilization", util), ("MaterialName", "Material Name")]
        rfiles[r["index"]] = xml(Node("NestResult", rat, children=[Node("ExtMin"), Node("ExtMax", [("X", W), ("Y", L)]),
                                                                    Node("HomeRef", [("RefType", "515")]), Node("Shapes", children=sh)]))
        cut = []
        for i in r["inserts"]:
            cut += [emf_shape(s) for s in blocks_by_name[i["block"]]["shapes"]]
        gen = XT.generate2 if v11 else XE.generate     # 6.3.907.11: лист — от округлённых углов (spec_emf_tie2)
        emfs[r["index"]] = gen(pl["W"], pl["L"], cut, device=M["emf"]["device"], mm=M["emf"]["mm"],
                               plate=emf_shape(plate_shape(0, pl["W"], pl["L"])), face_tail=M["emf"]["face_tail"])
    results_xml = xml(Node("NestResults", children=summary))
    nest_xml = xml(Node("NestInfo", children=[Node("Parts", [("Count", str(len(M["parts"])))]),
                                              Node("NestGroups", [("Count", str(len(M["groups"])))] if M["groups"] else []),
                                              Node("Plates", [("Count", str(len(M["plates"])))]),
                                              Node("Results", [("Count", str(len(M["results"])))])]))

    # ---- content.xml / info.xml / Viewports / Layers / TextStyles
    all_h = [2, 3, 4, 5, 6, 12]
    for b in M["blocks"]:
        all_h += [b["handle"], b["handle"] + 1] + [s["handle"] for s in b["shapes"]]
    for p in M["parts"]:
        all_h += [p["handle"], p["insert_handle"]]
    for g in M["groups"]:
        all_h.append(g["handle"])
    for p in M["plates"]:
        all_h += [p["handle"], p["poly_handle"]]
    for r in M["results"]:
        all_h += [r["handle"], r["plate_shape_handle"]] + [i["handle"] for i in r["inserts"]]
    C["handles unique"][len(all_h) == len(set(all_h))] += 1
    seed = max(all_h)
    vport = M["vport"] if M.get("vport") is not None else seed + 1
    C["VPort == HandleSeed+1"][vport == seed + 1] += 1
    hat = [("DefaultChannel", "1"), ("HandleSeed", str(seed)), ("ID", M["header_id"]), ("Version", "419963393")]
    if M["org_app"]:
        hat += [("OrgAppName", M["org_app"][0]), ("OrgAppVer", M["org_app"][1])]
    content_xml = xml(Node("PackData", [("DocType", "Model2D")], children=[
        Node("Header", hat, children=[Node("InsertBase")]), Node("Technical", [("Handle", "2")]), Node("Viewports", [("Handle", "3")]),
        Node("Layers", [("Handle", "5")]), Node("TextStyles", [("Handle", "6")]), Node("Blocks", [("Handle", "4")]),
        Node("Portions", [("Handle", "12"), ("ActiveModelID", M["results"][-1]["id"])])]))
    save_utc = FT_EPOCH + datetime.timedelta(microseconds=M["zip_mtimes"][0] // 10)
    local = save_utc + datetime.timedelta(hours=M["utc_offset_h"])
    info_xml = xml(Node("PackData", children=[Node("DocVersion", [("Major", "1")]),
                                              Node("Application", [("AppName", "CypCut"), ("AppVer", M["app_ver"])]),
                                              Node("SavedBy", [("User", M["user"]), ("UserLangID", "1049"), ("Computer", M["computer"]),
                                                               ("SysLangID", "1049"), ("SaveTime", local.strftime("%Y-%m-%dT%H:%M:%SZ"))])]))
    vp_xml = xml(Node("Viewports", [("Handle", "3"), ("Active", "1")], children=[Node("VPort", [("Handle", str(vport)), ("Name", "1")], children=[
        Node("ViewCenter"), Node("ZoomCoeff", text="1"), Node("ViewHeight", text="100"), Node("AspectRatio", text="1"),
        Node("DisplayRect", children=[Node("Right", text="1024"), Node("Bottom", text="768")])])]))
    files = {"info.xml": info_xml, "content.xml": content_xml, "TextStyles/content.xml": xml(Node("TextStyles", [("Handle", "6")])),
             "Layers/content.xml": xml(Node("Layers", [("Handle", "5")])), "Technical/content.xml": M["technical"],
             "Viewports/content.xml": vp_xml, "Blocks/content.xml": blocks_xml, "Shapes2D/data.bin": sbin,
             "Shapes2D/content.xml": xml(sx), "Geometry2D/data.bin": gbin, "Geometry2D/content.xml": gx,
             "Nest2D/content.xml": nest_xml, "Nest2D/Parts/content.xml": parts_xml, "Nest2D/Plates/content.xml": plates_xml,
             "Nest2D/Results/content.xml": results_xml}
    if groups_xml:
        files["Nest2D/Parts/Groups/content.xml"] = groups_xml
    for k, v in rfiles.items():
        files["Nest2D/Results/%d/content.xml" % k] = v
        files["Nest2D/Results/%d/thumbnail.emf" % k] = emfs[k]
    # ---- zip
    if M.get("zip_order"):
        seq_z = [(n, b"" if n.endswith("/") else files[n]) for n in M["zip_order"]]
        assert sorted(n for n, _ in seq_z if not n.endswith("/")) == sorted(files), "file set differs"
        mt = M["zip_mtimes"]
    else:
        st = collections.OrderedDict()
        rank = {"info.xml": 0, "data.bin": 1, "content.xml": 2, "thumbnail.emf": 3}
        for n in sorted(files, key=lambda n: (n.rpartition("/")[0], rank[n.rpartition("/")[2]])):
            folder, _, fn = n.rpartition("/")
            st.setdefault(folder, collections.OrderedDict())[fn] = files[n]
        seq_z = XZ.canonical_order(st)
        base = M["zip_mtimes"][0]
        mt = [base + 10000 * i for i in range(len(seq_z))]          # +1 мс на запись, как растут времена у CypCut
    return XZ.write_new(seq_z, save_utc, M["utc_offset_h"], mtimes=mt), files


# =====================================================================================  уровни L1 / L2
def apply_placements(M, C):
    """L1: блоки вставок NestPart пересчитываются из блоков деталей. Возвращает число пересчитанных блоков."""
    bn = {b["name"]: b for b in M["blocks"]}
    parts = {p["handle"]: p for p in M["parts"]}
    n = 0
    for r in M["results"]:
        for i in r["inserts"]:
            if i["ref"][0] != "NestPart":
                continue
            rb = bn[i["block"]]
            pb = bn[parts[i["ref"][1]]["block"]]
            th, d, order = find_placement(pb["shapes"], rb["shapes"])
            C["placement angle"][th] += 1
            new = []
            for k, (j, old) in enumerate(zip(order, rb["shapes"])):
                t = transform_shape(pb["shapes"][j], th, d, old["handle"])
                t["layer_name"], t["lead"], t["flag64"] = old["layer_name"], old["lead"], 0   # LeadParam/flag64 — свойства раскладки
                new.append(t)
            rb["shapes"] = new
            rb["placement"] = (th, d, order)
            n += 1
    return n


def fresh_identity(M, rng):
    """L2: новые хэндлы по правилу из спецификации, новые GUID/ID, порядок zip канонический."""
    G = lambda: "{%s}" % str(uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    h = [1001]

    def take(k=1):
        a = h[0]
        h[0] += k
        return a
    remap = {}
    blocks_part = [b for b in M["blocks"] if b["role"] == "part"]
    blocks_res = [b for b in M["blocks"] if b["role"] in ("insert", "group")]
    stale = [b for b in M["blocks"] if b["role"] == "stale"]
    newname = {}
    for b in blocks_part:
        b["handle"] = take(2)
        for s in b["shapes"]:
            remap[s["handle"]] = s["handle"] = take()
    for p in M["parts"]:
        p["insert_handle"] = take()
        remap[p["handle"]] = p["handle"] = take()
        take(4)                                   # 4 неиспользуемых хэндла после NestPart, как у CypCut 6.3.907.11
        p["guid"] = G()
    for g in M["groups"]:
        remap[g["handle"]] = g["handle"] = take()
        g["objects"] = [remap[o] if o in remap else remap.setdefault(o, take()) for o in g["objects"]]  # ссылки на удалённые детали
        g["guid"] = G()
    for p in M["plates"]:
        remap[p["handle"]] = p["handle"] = take(3)            # P, P+1 не используется, P+2 = полилиния листа
        p["poly_handle"] = p["handle"] + 2
        p["guid"] = G()
    for b in blocks_res:
        nm = G()
        newname[b["name"]] = nm
        b["name"] = nm
        b["handle"] = take(2)
        for s in b["shapes"]:
            s["handle"] = take()
    for r in M["results"]:
        r["handle"] = take(3)
        r["plate_shape_handle"] = take()
        r["plate"] = remap[r["plate"]]
        r["id"] = G()
        for i in r["inserts"]:
            i["handle"] = take()
            i["ref"] = (i["ref"][0], remap[i["ref"][1]])
            i["block"] = newname[i["block"]]
            i["channelport"] = True
            i["selected"] = None
        r["flags"] = None
    M["blocks"] = blocks_part + blocks_res        # устаревшие блоки не пишем
    M["vport"] = None
    M["header_id"] = G()
    M["org_app"] = None
    M["zip_order"] = None
    return len(stale)


# =====================================================================================  сравнение
def compare(raw, new):
    za, zb = zipfile.ZipFile(io.BytesIO(raw)), zipfile.ZipFile(io.BytesIO(new))
    out = collections.OrderedDict()
    for n in za.namelist():
        if n.endswith("/"):
            continue
        a = za.read(n)
        b = zb.read(n) if n in zb.namelist() else None
        out[n] = "MISSING" if b is None else 0 if a == b else SV.ndiff(a, b)
    return out


def semantic(A, B):
    """сравнение по смыслу (хэндлы/GUID/время игнорируются): детали, листы, раскладки, вставки, контуры"""
    S = collections.Counter()
    pa = {p["handle"]: p for p in A["parts"]}
    pb = {p["handle"]: p for p in B["parts"]}
    S["parts name+Amount equal"] += sum(1 for x, y in zip(A["parts"], B["parts"]) if (x["name"], x["given"]) == (y["name"], y["given"]))
    S["parts total"] += len(A["parts"])
    S["plates W,L,Amount equal"] += sum(1 for x, y in zip(A["plates"], B["plates"]) if (x["W"], x["L"], x["given"]["Amount"]) == (y["W"], y["L"], y["given"]["Amount"]))
    ba = {b["name"]: b for b in A["blocks"]}
    bb = {b["name"]: b for b in B["blocks"]}
    ga = {g["handle"]: g for g in A["groups"]}
    gb = {g["handle"]: g for g in B["groups"]}
    for ra, rb in zip(A["results"], B["results"]):
        S["results"] += 1
        S["result PlateAmount/PartCount/PlanCount/Size equal"] += (ra["plate_amount"], ra["given"]) == (rb["plate_amount"], rb["given"])
        S["result Utilization string equal"] += ra["util_str"] == rb["util_str"]
        for ia, ib in zip(ra["inserts"], rb["inserts"]):
            S["inserts"] += 1
            if ia["ref"][0] == "NestPart":
                S["insert -> same part name"] += pa[ia["ref"][1]]["name"] == pb[ib["ref"][1]]["name"]
            else:
                S["insert -> same group members"] += [pa[o]["name"] for o in ga[ia["ref"][1]]["objects"] if o in pa] == \
                    [pb[o]["name"] for o in gb[ib["ref"][1]]["objects"] if o in pb]
            sa, sb = ba[ia["block"]]["shapes"], bb[ib["block"]]["shapes"]
            for x, y in zip(sa, sb):
                S["contours"] += 1
                S["contour kind/layer/outer/coedge/LayerName equal"] += all(x[k] == y[k] for k in ("kind", "layer", "outer", "coedge", "layer_name"))
                dev = max(max(abs(a[0] - c[0]), abs(a[1] - c[1])) for a, c in zip(key_pts(x), key_pts(y)))
                S["contour geometry within 1e-9 mm"] += dev <= 1e-9 and len(key_pts(x)) == len(key_pts(y))
            S["contour count equal"] += len(sa) == len(sb)
    return S


def main(argv):
    outdir, paths = argv[0], argv[1:]
    import copy
    from . import xml_validate as XV
    for path in paths:
        raw = open(path, "rb").read()
        name = os.path.basename(path)
        print("=" * 100)
        print(name, len(raw), "B")
        M0 = decompile(raw)
        # ---- L0
        C = collections.defaultdict(collections.Counter)
        new0, _ = compile_lxds(copy.deepcopy(M0), C)
        cmp0 = compare(raw, new0)
        print("  L0 replay: whole archive identical: %s (%d of %d B differ); entries differing: %s"
              % (new0 == raw, SV.ndiff(raw, new0), len(raw), {k: v for k, v in cmp0.items() if v} or "none"))
        for k in sorted(C):
            print("     rule %-62s %s" % (k, dict(C[k])))
        # ---- L1
        C1 = collections.defaultdict(collections.Counter)
        M1 = copy.deepcopy(M0)
        nb = apply_placements(M1, C1)
        new1, f1 = compile_lxds(M1, C1)
        cmp1 = compare(raw, new1)
        print("  L1 placed (%d NestPart blocks recomputed, angles %s): identical %s; differing entries: %s"
              % (nb, dict(C1["placement angle"]), new1 == raw, {k: v for k, v in cmp1.items() if v} or "none"))
        # геометрия L1 против оригинала: допуск и биты
        zo = zipfile.ZipFile(io.BytesIO(raw))
        Mo = decompile(raw)
        ob = {b["handle"]: b for b in Mo["blocks"]}
        st = collections.Counter()
        for b in M1["blocks"]:
            if "placement" not in b:
                continue
            for s, o in zip(b["shapes"], ob[b["handle"]]["shapes"]):
                st["shapes"] += 1
                st["kind+handle equal"] += s["kind"] == o["kind"] and s["handle"] == o["handle"]
                ka, kb = key_pts(s), key_pts(o)
                dev = max(max(abs(a[0] - c[0]), abs(a[1] - c[1])) for a, c in zip(ka, kb))
                st["max dev <= 1e-9 mm"] += dev <= 1e-9
                st["Geometry2D object bit-identical"] += geo_bytes(s) == geo_bytes(o)
                st["Shapes2D record identical"] += attr_bytes(s) == attr_bytes(o)
        print("     L1 placed contours:", dict(st))
        # ---- L2
        C2 = collections.defaultdict(collections.Counter)
        M2 = copy.deepcopy(M1)
        nst = fresh_identity(M2, random.Random(12345))
        new2, f2 = compile_lxds(M2, C2, util_mode="computed")
        op = os.path.join(outdir, "spec_L2_" + name)
        open(op, "wb").write(new2)
        R = XV.validate(op, quiet=True)
        fails = [(n, d) for s_, n, d in R.rows if s_ == "FAIL"]
        npass = sum(1 for s_, n, d in R.rows if s_ == "PASS")
        print("  L2 fresh identity (stale blocks dropped: %d): %d B -> %s; xml_validate PASS %d, FAIL %d %s"
              % (nst, len(new2), op, npass, len(fails), [n for n, d in fails]))
        print("     L2 rules:", {k: dict(v) for k, v in C2.items() if k.startswith(("handles", "VPort", "result plate", "Utilization"))})
        print("     L2 per-entry vs original: identical %s" % sorted(k for k, v in compare(raw, new2).items() if v == 0))
        print("     L2 semantic comparison with original:", dict(semantic(Mo, decompile(new2))))
        print("  L1 whole-archive differing bytes (incl. zip CRC/headers): %d" % SV.ndiff(raw, new1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
