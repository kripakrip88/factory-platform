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
FREE = ("Free", None)       # вставка без NestPart/NestGroup — группа моста (так пишет CypCut 6.3.907.11)
FREE_MARK = -1              # метка такой вставки на время разбора пакетом (decompile_free)


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


def compile_free(M, checks=None, util_mode="given"):
    """spec_rebuild.compile_lxds + вставки без NestPart/NestGroup (мост CypCut, ref FREE; members — NestPart деталей
    моста, если известны). Пакет таких вставок не знает (у него вставка — деталь или группа), поэтому на время сборки
    вставка моста ссылается на первую деталь программы, затем в XML — как у CypCut: у вставки ссылки нет; PartCount
    раскладки — без деталей мостов; NestPart AmountUsed — без них, Amount — с ними (заказ; у разобранной программы, где
    детали моста неизвестны, — как в ней); Utilization — с деталями мостов (у CypCut после моста загрузка та же).
    Архив собирается заново тем же правилом, что в пакете (порядок записей и времена). Без мостов — пакет как есть."""
    SR, XM, XZ = vn.spec_rebuild, vn.xml_model, vn.xml_zip
    checks = collections.defaultdict(collections.Counter) if checks is None else checks
    free = [(r, i) for r in M["results"] for i in r["inserts"] if i["ref"] == FREE]
    if not free:
        return SR.compile_lxds(M, checks, util_mode=util_mode)
    rep = M["parts"][0]["handle"]
    for r, i in free:
        i["ref"] = ("NestPart", rep)
    try:
        _, files = SR.compile_lxds(M, checks, util_mode=util_mode)
    finally:
        for r, i in free:
            i["ref"] = FREE
    bn = {b["name"]: b for b in M["blocks"]}
    pby = {p["handle"]: p for p in M["parts"]}
    gby = {g["handle"]: g for g in M["groups"]}
    plates = {p["handle"]: p for p in M["plates"]}
    known = all("members" in i for r, i in free)
    used, bridged, util, nfree = collections.Counter(), collections.Counter(), {}, collections.Counter()
    for r in M["results"]:
        tot, a = 0.0, r["plate_amount"]
        for i in r["inserts"]:                         # загрузка — тем же счётом, что в пакете, детали моста — на месте моста
            if i["ref"][0] == "NestPart":
                hs = [i["ref"][1]]
                used[hs[0]] += a
            elif i["ref"][0] == "NestGroup":
                hs = gby[i["ref"][1]]["objects"]
                for o in hs:
                    used[o] += a
            else:
                hs = list(i.get("members", ()))
                nfree[r["index"]] += 1
                for o in hs:
                    bridged[o] += a
            for h in hs:
                if h in pby:
                    tot += SR.block_util_area(bn[pby[h]["block"]]["shapes"])
        pl = plates[r["plate"]]
        util[r["index"]] = XM.fmt_num(100.0 * tot / (pl["W"] * pl["L"]))
    fh = {i["handle"] for r, i in free}
    for r in M["results"]:
        if not nfree[r["index"]]:
            continue
        n = "Nest2D/Results/%d/content.xml" % r["index"]
        root = XM.parse(files[n])
        for s in root.find("Shapes").children:
            if s.get("Class") == "Insert" and int(s.get("Handle")) in fh:
                s.attrs = [(k, v) for k, v in s.attrs if k != "NestPart"]
        if util_mode == "computed":
            root.set("Utilization", util[r["index"]])
        files[n] = XM.serialize(root)
    root = XM.parse(files["Nest2D/Results/content.xml"])
    for x in root.children:
        k = int(x.get("Index"))
        if nfree[k]:
            x.set("PartCount", str(int(x.get("PartCount")) - nfree[k]))
            if util_mode == "computed":
                x.set("Utilization", util[k])
    files["Nest2D/Results/content.xml"] = XM.serialize(root)
    root = XM.parse(files["Nest2D/Parts/content.xml"])
    for x in root.children:
        h = int(x.get("Handle"))
        given = pby[h]["given"].get("Amount")
        amt = used[h] + bridged[h] if known or given is None else int(given)
        x.set("Amount", str(amt))
        x.set("AmountUsed", str(used[h]))
    files["Nest2D/Parts/content.xml"] = XM.serialize(root)
    # архив — как в конце spec_rebuild.compile_lxds
    save_utc = SR.FT_EPOCH + datetime.timedelta(microseconds=M["zip_mtimes"][0] // 10)
    if M.get("zip_order"):
        seq_z = [(n, b"" if n.endswith("/") else files[n]) for n in M["zip_order"]]
        mt = M["zip_mtimes"]
    else:
        st = collections.OrderedDict()
        rank = {"info.xml": 0, "data.bin": 1, "content.xml": 2, "thumbnail.emf": 3}
        for n in sorted(files, key=lambda n: (n.rpartition("/")[0], rank[n.rpartition("/")[2]])):
            folder, _, fn = n.rpartition("/")
            st.setdefault(folder, collections.OrderedDict())[fn] = files[n]
        seq_z = XZ.canonical_order(st)
        base = M["zip_mtimes"][0]
        mt = [base + 10000 * i for i in range(len(seq_z))]
    return XZ.write_new(seq_z, save_utc, M["utc_offset_h"], mtimes=mt), files


class _ETFree:
    """xml.etree для spec_rebuild.decompile: вставке без NestPart/NestGroup (мост CypCut) — метка NestPart=FREE_MARK
    (пакет ждёт одну из двух ссылок и падает)."""

    def __init__(self, et):
        self._et = et

    def __getattr__(self, n):
        return getattr(self._et, n)

    def fromstring(self, data):
        root = self._et.fromstring(data)
        if root.tag == "NestResult" and root.find("Shapes") is not None:
            for s in root.find("Shapes"):
                if s.get("Class") == "Insert" and s.get("NestPart") is None and s.get("NestGroup") is None:
                    s.set("NestPart", str(FREE_MARK))
        return root


def decompile_free(raw):
    """spec_rebuild.decompile, который не падает на вставках мостов: их ref — FREE (на время разбора модуль xml.etree
    пакета подменяется — как exact_coedge, в процессе с потоками небезопасно; исправить в пакете)."""
    SR = vn.spec_rebuild
    old = SR.ET
    SR.ET = _ETFree(old)
    try:
        M = SR.decompile(raw)
    finally:
        SR.ET = old
    for r in M["results"]:
        for i in r["inserts"]:
            if i["ref"] == ("NestPart", FREE_MARK):
                i["ref"] = FREE
    return M


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
        """Элементы маршрута раскладки: ("part", i, фигуры) | ("group", [i…], фигуры) | ("bridge", [i…], фигуры); старый
        вид (i, фигуры) — деталь."""
        for e in l["seq"]:
            if len(e) == 2:
                yield ("part", e[0], e[1])
            else:
                yield e
    used = sorted({i for l in layouts for e in entries(l) for i in (e[1] if e[0] in ("group", "bridge") else [e[1]])})
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
            if kind == "bridge":
                # мост (как у CypCut): вставка без NestPart/NestGroup, блок — роль вставки (OutlineID = общий контур, без
                # Flags), имя — число (после _identity); детали моста — members (для Amount и загрузки)
                blocks.append(dict(handle=next(tmp), name=bn, role="insert", outline_override="derive", bridge=True,
                                   given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh2))
                ins.append(dict(handle=next(tmp), ref=FREE, block=bn, channelport=True, selected=None,
                                members=[nparts[idx[m]]["handle"] for m in i]))
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
    import copy as _copy
    M0, st = _copy.deepcopy(M), rng.getstate()
    for start in (1001, 1002, 1003):
        # номер окна просмотра = HandleSeed+1; 768 и 1024 совпали бы с размерами экрана в том же XML, и проверка
        # C11 пакета (xml_validate заменяет номер в тексте целиком) ложно падает — такие номера обходим
        M = _copy.deepcopy(M0); rng.setstate(st)
        _identity(M, rng, start)
        with exact_coedge():
            raw, files = compile_free(M, collections.defaultdict(collections.Counter), util_mode="computed")
        if b'Handle="768"' not in files["Viewports/content.xml"] and b'Handle="1024"' not in files["Viewports/content.xml"]:
            break
    return raw, M


def _identity(M, rng, start=1001):
    """Хэндлы, GUID, имена блоков — как spec_rebuild.fresh_identity, но запись группы общего реза получает хэндл
    сразу после вставок своей раскладки (G = R+4+m, следующая раскладка — G+1; так у CypCut 9/9 в заводских)."""
    SR = vn.spec_rebuild
    Gd = lambda: "{%s}" % str(SR.uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    h = [start]

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
    names = set()
    for b in blocks_res:
        nm = Gd()
        if b.get("bridge"):                            # блок моста — число (у CypCut: 1518434396, 11665997262 …)
            nm = str(rng.randrange(10 ** 9, 2 * 10 ** 10))
            while nm in names:
                nm = str(rng.randrange(10 ** 9, 2 * 10 ** 10))
        names.add(nm)
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
            elif i["ref"] == FREE:
                i["members"] = [remap[h] for h in i.get("members", ())]
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
