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


def _clean(s, keep_flag64):
    """Фигура для записи: только поля сборщика, значения по умолчанию где их нет."""
    t = dict(handle=None, kind=s["kind"], layer_name=s.get("layer_name", "0"), layer=int(s.get("layer", 1)),
             coedge=int(s.get("coedge", 0)), flag64=int(s.get("flag64", 0)) if keep_flag64 else 0,
             outer=int(s.get("outer", 0)), lead=None)
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
                                       [(l["W"], l["L"], l["amount"], [i for i, _ in l["seq"]]) for l in layouts]],
                                      ensure_ascii=False).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    guid = lambda: "{%s}" % str(SR.uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    tmp = iter(range(-100, -10 ** 8, -1))
    used = sorted({i for l in layouts for i, _ in l["seq"]})
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
    results = []
    for ri, l in enumerate(layouts):
        ins = []
        for i, sh in l["seq"]:
            sh2 = [_clean(s, False) for s in sh]
            for s in sh2:
                s["handle"] = next(tmp)
            bn = "{TMP-R%d-%d}" % (ri, len(ins))
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
             blocks=blocks, parts=nparts, groups=[], plates=list(plates.values()), results=results)
    SR.fresh_identity(M, rng)
    with exact_coedge():
        raw, _ = SR.compile_lxds(M, collections.defaultdict(collections.Counter), util_mode="computed")
    return raw, M
