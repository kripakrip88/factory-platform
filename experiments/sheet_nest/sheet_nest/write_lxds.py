# -*- coding: utf-8 -*-
"""Раскрой + порядок резки → программа CypCut (.lxds) эталонным сборщиком пакета (spec_rebuild, байт в байт
с заводскими программами). Детали — блоки деталей как есть; раскладки — вставки с фигурами в порядке резки.

Признак общего реза (coedge) пишется ТАК, КАК ОН ЗАДАН в фигуре (у прорезей — 0, как у CypCut инженера).
Сборщик пакета выводит его сам: «открытая полилиния слоя 1 = цепочка общего реза» — правило из образцов с общим
резом, для обычных прорезей неверное. Пока пакет не исправлен, на время сборки подставляется своя запись атрибутов.
"""
import os, json, random, hashlib, datetime, collections, contextlib
from .libpath import vn

FACTORY_UTC_OFFSET_H = 10
BAD_NAME = str.maketrans({c: "" for c in "&<>\"'"})


def _attr_exact(s):
    return vn.spec_verify.attr_rec(s["handle"], s["kind"], s["layer"], s.get("coedge", 0), s.get("flag64", 0),
                                   s.get("outer", 0), s.get("lead"))


@contextlib.contextmanager
def exact_coedge():
    """На время сборки/разбора — признак общего реза как в фигуре (не выводить из «открытая полилиния слоя 1»)."""
    SR = vn.spec_rebuild
    old = SR.attr_bytes
    SR.attr_bytes = _attr_exact
    try:
        yield
    finally:
        SR.attr_bytes = old


def technical_template():
    with open(os.path.join(os.path.dirname(vn.spec_rebuild.__file__), "technical_template.xml"), "rb") as f:
        return f.read()


def _clean(s, keep_flag64, keep_lead=False):
    """Фигура для записи: только поля сборщика, значения по умолчанию где их нет. LeadParam — только у замкнутых
    контуров групп общего реза (keep_lead): 5 нулевых u32 + f64 sp + 4 нулевых f64, как у CypCut."""
    t = dict(handle=None, kind=s["kind"], layer_name=s.get("layer_name", "0"), layer=int(s.get("layer", 1)),
             coedge=int(s.get("coedge", 0)), flag64=int(s.get("flag64", 0)) if keep_flag64 else 0,
             outer=int(s.get("outer", 0)), lead=s.get("lead") if (keep_lead and isinstance(s.get("lead"), (bytes, bytearray))) else None)
    if s["kind"] == "Line":
        t.update(p1=tuple(map(float, s["p1"])), p2=tuple(map(float, s["p2"])))
    elif s["kind"] == "Circle":
        t.update(c=tuple(map(float, s["c"])), r=float(s["r"]), a0=float(s["a0"]))
    else:
        t.update(verts=[(float(x), float(y), float(b)) for x, y, b in s["verts"]], flag=int(s["flag"]), sp=float(s.get("sp", 0.0)))
    return t


def build(parts, layouts, title, technical=None, user="sheet_nest", computer="SHEET-NEST", now_utc=None):
    """parts: [Part]; layouts: [{"W", "L", "amount", "seq": [(part_i, [фигуры в порядке резки, внешний последним])]}].
    Вернуть (байты .lxds, модель сборщика)."""
    SR = vn.spec_rebuild
    seed = int(hashlib.md5(json.dumps([title, [p["name"] for p in parts],
                                       [(l["W"], l["L"], l["amount"], [e[0] if len(e) == 2 else [e[0], e[1]] for e in l["seq"]]) for l in layouts]],
                                      ensure_ascii=False).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    guid = lambda: "{%s}" % str(SR.uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    tmp = iter(range(-100, -10 ** 8, -1))
    def entries(l):
        """Элементы маршрута раскладки: ("part", i, фигуры) | ("group", [i…], фигуры); старый вид (i, фигуры) — деталь."""
        for e in l["seq"]:
            if len(e) == 2:
                yield ("part", e[0], e[1])
            else:
                yield e
    used = sorted({i for l in layouts for e in entries(l) for i in (e[1] if e[0] == "group" else [e[1]])})
    blocks, nparts, idx = [], [], {}
    for i in used:
        p = parts[i]
        sh = [_clean(s, True) for s in p["shapes"]]
        for s in sh:
            s["handle"] = next(tmp)
        bn = guid()
        blocks.append(dict(handle=next(tmp), name=bn, role="part", outline_override="derive",
                           given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh))
        nparts.append(dict(handle=next(tmp), insert_handle=next(tmp), name=p["name"].translate(BAD_NAME) or "деталь",
                           guid=None, block=bn, given=dict(Amount=None, AmountUsed=None)))
        idx[i] = len(nparts) - 1
    plates = {}
    for l in layouts:
        key = (float(l["W"]), float(l["L"]))
        if key not in plates:
            plates[key] = dict(handle=next(tmp), poly_handle=next(tmp), guid=None, W=key[0], L=key[1], poly_has_nestplate=True,
                               given=dict(Amount=None, AmountUsed=None, pts=None))
    results, groups = [], []
    for ri, l in enumerate(layouts):
        ins = []
        for kind, i, sh in entries(l):
            sh2 = [_clean(s, False, keep_lead=(kind == "group")) for s in sh]
            for s in sh2:
                s["handle"] = next(tmp)
            bn = "{TMP-R%d-%d}" % (ri, len(ins))
            if kind == "group":
                # блок группы общего реза: без OutlineID и Flags (как у CypCut); запись NestGroup — на каждую вставку
                blocks.append(dict(handle=next(tmp), name=bn, role="group", outline_override="derive",
                                   given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh2))
                g = dict(handle=next(tmp), name="CoedgePart", amount="1", amount_used=None, guid=None,
                         objects=[nparts[idx[m]]["handle"] for m in i])
                groups.append(g)
                ins.append(dict(handle=next(tmp), ref=("NestGroup", g["handle"]), block=bn, channelport=True, selected=None))
                continue
            blocks.append(dict(handle=next(tmp), name=bn, role="insert", outline_override="derive",
                               given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh2))
            ins.append(dict(handle=next(tmp), ref=("NestPart", nparts[idx[i]]["handle"]), block=bn, channelport=True, selected=None))
        results.append(dict(index=ri + 1, handle=next(tmp), id=None, flags=None, plate_amount=int(l["amount"]), util_str=None,
                            inserts=ins, given=dict(PartCount=None, PlanCount=None, SizeX=None, SizeY=None, ExtMax=None),
                            plate=plates[(float(l["W"]), float(l["L"]))]["handle"], plate_shape_handle=next(tmp)))
    save_utc = now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    M = dict(app_ver="6.3.907.11", user=user, computer=computer, header_id=None, org_app=None, vport=None,
             technical=technical or technical_template(), zip_order=None, zip_mtimes=[SR.XZ.filetime(save_utc)],
             utc_offset_h=FACTORY_UTC_OFFSET_H, emf=dict(device=(2560, 1440), mm=(600, 330), face_tail=b""),
             blocks=blocks, parts=nparts, groups=groups, plates=list(plates.values()), results=results)
    _identity(M, rng)
    with exact_coedge():
        raw, _ = SR.compile_lxds(M, collections.defaultdict(collections.Counter), util_mode="computed")
    return raw, M


def _identity(M, rng):
    """Хэндлы, GUID, имена блоков — как spec_rebuild.fresh_identity, но запись группы общего реза получает хэндл
    сразу после вставок своей раскладки (G = R+4+m, следующая раскладка — G+1; так у CypCut 9/9 в заводских)."""
    SR = vn.spec_rebuild
    Gd = lambda: "{%s}" % str(SR.uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    h = [1001]

    def take(k=1):
        a = h[0]
        h[0] += k
        return a
    remap, newname = {}, {}
    blocks_part = [b for b in M["blocks"] if b["role"] == "part"]
    blocks_res = [b for b in M["blocks"] if b["role"] in ("insert", "group")]
    for b in blocks_part:
        b["handle"] = take(2)
        for s in b["shapes"]:
            s["handle"] = take()
    for p in M["parts"]:
        p["insert_handle"] = take()
        remap[p["handle"]] = p["handle"] = take()
        take(4)
        p["guid"] = Gd()
    for p in M["plates"]:
        remap[p["handle"]] = p["handle"] = take(3)
        p["poly_handle"] = p["handle"] + 2
        p["guid"] = Gd()
    for b in blocks_res:
        nm = Gd()
        newname[b["name"]] = nm
        b["name"] = nm
        b["handle"] = take(2)
        for s in b["shapes"]:
            s["handle"] = take()
    gby = {g["handle"]: g for g in M["groups"]}
    for r in M["results"]:
        r["handle"] = take(3)
        r["plate_shape_handle"] = take()
        r["plate"] = remap[r["plate"]]
        r["id"] = Gd()
        for i in r["inserts"]:
            i["handle"] = take()
            i["block"] = newname[i["block"]]
            i["channelport"] = True
            i["selected"] = None
            if i["ref"][0] == "NestPart":
                i["ref"] = ("NestPart", remap[i["ref"][1]])
        for i in r["inserts"]:                        # записи групп — после вставок раскладки
            if i["ref"][0] == "NestGroup":
                g = gby[i["ref"][1]]
                g["handle"] = take()
                g["objects"] = [remap[o] for o in g["objects"]]
                g["guid"] = Gd()
                i["ref"] = ("NestGroup", g["handle"])
        r["flags"] = None
    M["groups"].sort(key=lambda g: g["handle"])
    M["blocks"] = blocks_part + blocks_res
    M["vport"] = None
    M["header_id"] = Gd()
    M["org_app"] = None
    M["zip_order"] = None
