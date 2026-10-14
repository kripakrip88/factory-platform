# -*- coding: utf-8 -*-
"""Командная строка: детали (DXF и/или программы CypCut) → раскрой на листы → программа CypCut.

    python3 -m sheet_nest.cli ВХОД... [--sheet 1250x2500] [--gap 2] [--edge 2] [--thickness 1.5] [--qty ИМЯ=N] [--out DIR] [--name ИМЯ]
                              [--coedge] [--bridge [--bridge-width 2] [--bridge-group 5]]
                              [--strategy short|safe|safe0|hill] [--compare] [--small 100] [--microjoints ИМЯ|*]
                              [--machine ПРОФИЛЬ.json ...]

ВХОД — .dxf (одна или несколько деталей; гравировка — слой «ГРАВИРОВКА»; количество — из имени «…_12шт.dxf»
или --qty) и/или .lxds (детали с количеством из программы; раскладки в ней не важны).
В DIR: <имя>_<дата>.lxds (одна программа на все листы), картинка раскладок .png, отчёт .json.
Порядок резки — по стратегии (route.STRATEGIES), --compare — сводка по всем стратегиям (текст и отчёт).
Из Odoo движок вызывается не отсюда, а через sheet_nest/job.py (контракт sheet_nest.job/1, ERP.md).
"""
import sys, os, json, math, errno, argparse, datetime, collections
from . import geom as G
from .errors import SheetNestError

DENSITY = 7.85e-6           # кг/мм³ — сталь (как RHO расшифровщика пакета): масса листа раскладки; в Odoo — справочник листа
QTY_MAX = 20000             # деталей в одном прогоне (сумма количеств): лишние нули в количестве не должны съесть память


def _input(item):
    """Вход run(): путь или словарь {path, name, qty, key} → (путь, имя | None, количество | None, ключ | None)."""
    if isinstance(item, dict):
        extra = sorted(set(item) - {"path", "name", "qty", "key"})
        if extra:
            raise SheetNestError("вход %s: лишние поля %s (есть path, name, qty, key)" % (item.get("path"), ", ".join(extra)))
        if not item.get("path"):
            raise SheetNestError("вход без файла (нужен path): %r" % (item,))
        return item["path"], item.get("name"), item.get("qty"), item.get("key")
    return item, None, None, None


def _explicit_qty(qty, who):
    """Количество, заданное явно: целое ≥ 1 (77 и 77.0 — да; True, 0, 1.5 — нет) → int; иначе SheetNestError."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        q = None
    if isinstance(qty, bool) or q is None or not math.isfinite(q) or q < 1 or q != int(q):
        raise SheetNestError("деталь «%s»: количество %s — нужно целое число не меньше 1" % (who, _show(qty)), flag="--qty")
    if q > QTY_MAX:
        raise SheetNestError("деталь «%s»: количество %d — больше, чем движок раскладывает за один раз (%d)" % (who, q, QTY_MAX),
                             flag="--qty")
    return int(q)


def _show(v):
    """Значение для текста ошибки — без питоновского repr: пусто, число, «строка»."""
    if v is None:
        return "пусто"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "%g" % v
    if isinstance(v, str):
        return "«%s»" % v[:40]
    return {dict: "объект", list: "список"}.get(type(v), type(v).__name__)


def _oserr(e):
    """OSError → по-русски: нет файла, нет прав; прочее — текст системы."""
    return {errno.ENOENT: "нет файла", errno.EACCES: "нет прав на чтение", errno.EPERM: "нет прав на чтение",
            errno.EISDIR: "это папка"}.get(e.errno, e.strerror or str(e))


def _read_input(path, fn, pname, pqty, engrave_layers):
    """Один вход → (детали, технология CypCut | None, предупреждения программы)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SheetNestError("%s: файл не открывается (%s)" % (fn, _oserr(e)))
    if fn.lower().endswith(".lxds"):
        if pname is not None or pqty is not None:
            raise SheetNestError("%s: у программы CypCut детали и количества берутся из неё — имя и количество не "
                                 "задаются" % fn)
        from .read_lxds import parts_from_lxds
        ps, info = parts_from_lxds(data, fn)
        return ps, info["technical"], info["warnings"]
    if fn.lower().endswith(".dxf"):
        if pname is not None and (not isinstance(pname, str) or not pname.strip()):
            raise SheetNestError("%s: имя детали %s — нужна непустая строка" % (fn, _show(pname)))
        if pqty is not None:
            pqty = _explicit_qty(pqty, pname.strip() if pname is not None else fn)
        from .read_dxf import parts_from_dxf
        return parts_from_dxf(data, fn, pqty, engrave_layers, name=pname.strip() if pname is not None else None), None, []
    raise SheetNestError("%s: нужен .dxf или .lxds" % fn)


def _where(e, k, item, fn, pname):
    """Ошибка входа k: номер входа (e.input — для error.json) и чей это текст: у словаря с именем — «деталь «имя»: …»
    (имя файла в папке Odoo ничего не скажет), у DXF по пути — «файл.dxf: …» (у .lxds имя файла в тексте уже есть)."""
    if e.input is None:
        e.input = k
    msg = str(e)
    if isinstance(item, dict) and isinstance(pname, str) and pname.strip() and not fn.lower().endswith(".lxds"):
        who = "деталь «%s»" % pname.strip()
        if msg.startswith(fn + ": "):
            msg = msg[len(fn) + 2:]
    elif fn.lower().endswith(".dxf"):
        who = fn
    else:
        return
    if not msg.startswith(who):
        e.args = ("%s: %s" % (who, msg),) + e.args[1:]


def part_aliases(p):
    """По каким именам деталь находят количество (--qty), перемычки и подписи: у входа-словаря с именем — только это
    имя (его знает вызывающий: Odoo; имя файла в его папке — «1.dxf» — не имя детали, ERP.md п. 2), у программы-словаря
    — имя детали; у пути — имя детали и имя файла без расширения (как было в командной строке)."""
    return p.get("aliases") or (p["name"], os.path.splitext(p.get("src") or "")[0])


def _have(parts):
    """«(есть: …)» в тексте ошибки — имена, по которым детали можно назвать."""
    return ", ".join(dict.fromkeys(part_aliases(p)[0] for p in parts))


def load_parts(inputs, qty_over=None, engrave_layers=None):
    """inputs — пути или словари {path, name, qty, key} (см. run). Вернуть (детали, технология CypCut, предупреждения).
    У деталей — ещё input (номер входа), aliases (part_aliases) и key (если задан). Ошибка входа — SheetNestError с
    номером входа (input) и именем детали или файла в тексте."""
    from .read_dxf import QTY_MISSING
    parts, technical, warns = [], None, []
    for k, item in enumerate(inputs):
        pname = item.get("name") if isinstance(item, dict) else None
        fn = ""
        try:
            path, pname, pqty, key = _input(item)
            fn = os.path.basename(path)
            ps, tech, w = _read_input(path, fn, pname, pqty, engrave_layers)
        except SheetNestError as e:
            _where(e, k, item, fn, pname)
            raise
        technical = technical or tech
        warns += w
        given = pname.strip() if isinstance(item, dict) and pname is not None else None
        for p in ps:
            p["input"] = k
            if key is not None:
                p["key"] = key
            if given is not None:
                p["aliases"] = tuple(dict.fromkeys((given, pname)))     # и как прислано (с пробелами по краям)
            elif isinstance(item, dict):
                p["aliases"] = None                     # программа-словарь — имя детали (после переименования, ниже)
        parts += ps
    # имена — уникальные (по ним в программе считаются количества): повтор — « (2)», « (3)» …, мимо имён, которые уже
    # есть (X, X, «X (2)» → X, «X (3)», «X (2)», а не два «X (2)»)
    orig = set(p["name"] for p in parts)
    seen, used = collections.Counter(), set()
    for p in parts:
        nm = p["name"]
        seen[nm] += 1
        if seen[nm] > 1:
            n = seen[nm]
            while "%s (%d)" % (nm, n) in used or "%s (%d)" % (nm, n) in orig:
                n += 1
            p["name"] = "%s (%d)" % (nm, n)
        used.add(p["name"])
    for p in parts:
        if "aliases" in p and p["aliases"] is None:
            p["aliases"] = (p["name"],)
    for k, v in (qty_over or {}).items():
        hit = [p for p in parts if k in part_aliases(p)]
        if not hit:
            raise SheetNestError("количество для «%s»: нет такой детали (есть: %s)" % (k, _have(parts)), flag="--qty")
        v = _explicit_qty(v, k)
        for p in hit:
            p["qty"] = v
            # количество задано явно — «не указано» было бы ложным (ERP.md, п. 2)
            p["warnings"] = [w for w in p.get("warnings", []) if w != QTY_MISSING]
    for p in parts:
        warns += ["%s: %s" % (p["name"], w) for w in p.get("warnings", [])]
    return parts, technical, warns


def mark_microjoints(parts, names):
    """Детали с микроперемычками (держатся в листе): ИМЯ детали или файла без расширения (у входа-словаря — заданное
    имя, part_aliases); «*» — все."""
    for k in names or ():
        hit = parts if k == "*" else [p for p in parts if k in part_aliases(p)]
        if not hit:
            raise SheetNestError("микроперемычки для «%s»: нет такой детали (есть: %s)" % (k, _have(parts)), flag="--microjoints")
        for p in hit:
            p["microjoints"] = True
    for p in parts:
        p.setdefault("microjoints", False)


def check_params(W, L, gap, edge, thickness=None, small=None):
    """Лист, зазор, край, толщина, мелкая деталь — числа в своих пределах; иначе SheetNestError (до чтения деталей)."""
    def num(v, what):
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = None
        if isinstance(v, bool) or x is None or not math.isfinite(x):
            raise SheetNestError("%s — нужно число, а не %r" % (what, v))
        return x
    W_, L_, g, e = num(W, "ширина листа"), num(L, "длина листа"), num(gap, "зазор"), num(edge, "отступ от края")
    if W_ <= 0 or L_ <= 0:
        raise SheetNestError("лист %g×%g мм: размеры должны быть больше 0" % (W_, L_))
    if g < 0 or e < 0:
        raise SheetNestError("зазор %g мм и отступ от края %g мм не могут быть отрицательными" % (g, e))
    if W_ - 2 * e <= 0 or L_ - 2 * e <= 0:
        raise SheetNestError("лист %g×%g мм не вмещает отступ от края %g мм" % (W_, L_, e))
    if thickness is not None and not num(thickness, "толщина") > 0:
        raise SheetNestError("толщина %r — нужно число больше 0" % (thickness,))
    if small is not None and num(small, "мелкая деталь") < 0:
        raise SheetNestError("мелкая деталь %r мм — нужно число не меньше 0" % (small,))


def sheet_mass(W, L, thickness):
    """Масса листа W×L (кг) по плотности стали; без толщины — None."""
    return round(W * L * float(thickness) * DENSITY, 1) if thickness else None


def layout_stats(l, r, parts, thickness):
    """Раскладка (ERP.md, п. 6), на ОДИН её лист: размер, загрузка (как Utilization CypCut: внешний контур минус
    замкнутые внутри, все детали — и детали мостов), рез, гравировка, врезки (по маршруту), масса листа."""
    from .libpath import vn
    c, m, p_, m_, n = _cut_len(dict(seq=r["seq"]))
    area = sum(vn.spec_rebuild.block_util_area(parts[q["part"]]["shapes"]) for q in l["placed"])
    return dict(W=float(l["W"]), L=float(l["L"]), util_pct=round(100.0 * area / (float(l["W"]) * float(l["L"])), 2),
                cut_m=round(c / 1000, 3), mark_m=round(m / 1000, 3), pierces=p_, mass_kg=sheet_mass(l["W"], l["L"], thickness))


def _cut_len(l):
    """По маршруту раскладки: (длина реза, гравировки, врезок, начал гравировки, переходов), мм."""
    cut = mark = 0.0
    pierces = marks = n = 0
    for e in l["seq"]:
        for s in (e[1] if len(e) == 2 else e[2]):
            n += 1
            if s["layer"] == 2:
                mark += G.length(s); marks += 1
            else:
                cut += G.length(s); pierces += 1
    return cut, mark, pierces, marks, n


def summary_row(pl, rs, name, title, secs, thickness=None, machines=(), warnings=()):
    """Строка сводки стратегии: листы, рез, холостой, возврат, врезки, опасные переходы по классам, время станков
    (machine_s — {станок: секунды или None}; без профилей — пусто)."""
    from . import risk as RK, machine as MC, bridge as BR
    amounts = [l["amount"] for l in pl["layouts"]]
    tot = RK.total([r["risk"] for r in rs], amounts)
    cut = mark = 0.0
    pierces = marks = moves = 0
    for l, r in zip(pl["layouts"], rs):
        c, m, p_, m_, n = _cut_len(dict(seq=r["seq"]))
        cut += c * l["amount"]; mark += m * l["amount"]; pierces += p_ * l["amount"]; marks += m_ * l["amount"]
        moves += n * l["amount"]
    # холостой — сумма маршрутов, как res["idle_m"] (summary.idle_m): risk.total уже округлил его до 3 знаков, и второе
    # округление расходилось с итогом на 0,01 м
    idle = sum(r["idle"] * l["amount"] for l, r in zip(pl["layouts"], rs))
    ms = {}
    for prof in machines or ():
        t = MC.estimate(prof, thickness, cut, mark, tot["idle_m"] * 1000, tot["ret"]["m"] * 1000, pierces, moves)
        ms[prof["name"]] = round(t, 1) if t is not None else None
    # конец листа (risk.end_strip): листов с узкой полосой в конце; худший остаток — полоса, затем самый вытянутый
    strips = [(r.get("strip"), l["amount"]) for l, r in zip(pl["layouts"], rs)]
    worst = max((s for s, a in strips if s), key=lambda s: (s["strip"], s["aspect"]), default=None)
    return dict(name=name, title=title, sheets=pl["sheets"], cut_m=round(cut / 1000, 2), mark_m=round(mark / 1000, 2),
                idle_m=round(idle / 1000, 2), return_m=round(tot["ret"]["m"], 2), pierces=pierces, marks=marks,
                danger={c: tot[c] for c in RK.CLASSES}, over_parts_m=tot["over_parts_m"],
                ret=dict(over_m=tot["ret"]["over_m"], tongues_crossed=tot["ret"]["tongues_crossed"], over=tot["ret"]["over"]),
                strip=dict(sheets=sum(a for s, a in strips if s and s["strip"]), worst=worst),
                bridges=BR.stats(pl["layouts"]) if any(l.get("bridges") for l in pl["layouts"]) else None,
                warnings=list(warnings), route_s=round(secs, 2), machine_s=ms,
                error=None)                             # строка построена (failed_row — нет: общий рез не строится)


def failed_row(name, title, why, secs, machines=()):
    """Строка сводки стратегии, которую с общим резом не построить (порядок группы не нашёлся, ERP.md, п. 8): показатели
    — None, причина — error; раскрой остальных стратегий при этом не откатывается на зазор."""
    return dict(name=name, title=title, error=why, sheets=None, cut_m=None, mark_m=None, idle_m=None, return_m=None, pierces=None,
                marks=None, danger=None, over_parts_m=None, ret=None, strip=None, bridges=None,
                warnings=["общий рез с этой стратегией не строится: %s" % why], route_s=round(secs, 2),
                machine_s={m["name"]: None for m in machines})


def summary_text(rows):
    """Сводка по стратегиям текстом: строки — показатели, столбцы — стратегии (не построенная — «—»)."""
    from . import risk as RK

    def col(f):
        return ["—" if r.get("error") else f(r) for r in rows]
    lines = [("", ["%s (%s)" % (r["title"], r["name"]) for r in rows]),
             ("листов", col(lambda r: str(r["sheets"]))),
             ("рез, м", col(lambda r: "%.2f" % r["cut_m"])),
             ("холостой, м", col(lambda r: "%.2f" % r["idle_m"])),
             ("возврат в ноль, м", col(lambda r: "%.2f" % r["return_m"])),
             ("врезок", col(lambda r: str(r["pierces"])))]
    if any(r.get("bridges") for r in rows):             # мост — кнопка, у всех стратегий одни и те же группы
        lines.append(("мосты: групп / перемычек / деталей", col(lambda r: "%d / %d / %d" % (r["bridges"]["groups"], r["bridges"]["bridges"],
                                                                                          r["bridges"]["parts"]) if r.get("bridges") else "—")))
    lines += [(RK.TITLES[c], col(lambda r, c=c: str(r["danger"][c]))) for c in RK.CLASSES]
    lines += [("конец листа: остаток, мм", col(lambda r: "—" if not r["strip"]["worst"] else "%.0f×%.0f" % (r["strip"]["worst"]["w"],
                                                                                                          r["strip"]["worst"]["l"]))),
              ("узкая полоса в конце, листов", col(lambda r: str(r["strip"]["sheets"])))]
    lines += [("возврат над деталями, м", col(lambda r: "%.2f" % r["ret"]["over_m"])),
              ("предупреждений", [str(len(r["warnings"])) for r in rows]),
              ("маршрут, с", ["%.1f" % r["route_s"] for r in rows])]
    if any(r.get("error") for r in rows):
        lines.append(("общий рез", ["не строится" if r.get("error") else "да" for r in rows]))
    names = list(rows[0]["machine_s"]) if rows else []
    if not names:
        lines.append(("станок, мин", ["—" for r in rows]))
    for nm in names:                                    # строка на каждый станок
        lines.append(("станок «%s», мин" % nm, ["—" if r["machine_s"].get(nm) is None else "%.1f" % (r["machine_s"][nm] / 60)
                                                for r in rows]))
    w0 = max(len(k) for k, v in lines)
    ws = [max(len(v[j]) for k, v in lines) for j in range(len(rows))]
    return "\n".join(k.ljust(w0) + " | " + " | ".join((x.ljust if not k else x.rjust)(w) for x, w in zip(v, ws)) for k, v in lines)


def bridge_options(bridge):
    """Мост: None | False — нет; True | dict(width=2, group=5) → dict(width, group) (пустой словарь и поля null —
    значения по умолчанию: словарь = мост включён); плохие значения — SheetNestError с текстом."""
    b = dict(width=2.0, group=5)
    if isinstance(bridge, dict):
        extra = sorted(set(bridge) - {"width", "group"})
        if extra:
            raise SheetNestError("мост: лишние поля %s (есть width — ширина перемычки, group — деталей в группе)" % ", ".join(extra))
        b.update({k: v for k, v in bridge.items() if v is not None})
    elif not bridge:
        return None
    try:
        if isinstance(b["width"], bool) or isinstance(b["group"], bool):
            raise TypeError
        b["width"], g = float(b["width"]), float(b["group"])
    except (TypeError, ValueError):
        raise SheetNestError("мост: ширина перемычки и число деталей в группе — числа (ширина %s, деталей в группе %s)"
                             % (_show(b["width"]), _show(b["group"])))
    if not (math.isfinite(b["width"]) and b["width"] > 0):
        raise SheetNestError("мост: ширина перемычки должна быть больше 0 мм (дано %g)" % b["width"], flag="--bridge-width")
    if not math.isfinite(g) or g != int(g) or g < 2:
        raise SheetNestError("мост: в группе не меньше 2 деталей (дано %g)" % g, flag="--bridge-group")
    b["group"] = int(g)
    return b


def run(inputs, W=1250.0, L=2500.0, gap=2.0, edge=2.0, thickness=None, qty=None, title=None, out=None, methods=("rect", "raster"),
        engrave_layers=None, log=print, coedge=False, labels=None, label_opts=None, strategy=None, compare=False, small=None,
        microjoints=None, machine=None, bridge=None, progress=None):
    """inputs — пути к .dxf / .lxds или словари {path, name, qty, key}: у словаря имя и количество — как заданы, из имени
    файла ничего не берётся (у .lxds их не задают — детали и количества из программы); key — метка вызывающего (Odoo:
    «pmk.laser.job.part,57»), возвращается у деталей (parts[i]["key"]).
    strategy — порядок резки (route.STRATEGIES: short | safe | safe0 | hill; по умолчанию short); compare — посчитать
    сводку по всем стратегиям (res["strategies"]); small — «мелкая» деталь, мм (100); microjoints — имена деталей с
    микроперемычками («*» — все); machine — профиль станка (словарь или путь к JSON) или список профилей (станков два —
    время в сводке по каждому); bridge — мост (кнопка, как общий рез; от стратегии не зависит): None | dict(width=2 мм,
    group=5 деталей) — соседние круглые детали через зазор соединяются перемычками и режутся одной врезкой (bridge.py).
    progress — fn(этап, текст), этапы read, pack, route, build, check, render; маршрут — по каждой стратегии
    («маршрут: Безопасный, 2/4»).
    Ошибки пользователя — SheetNestError (DxfError, LxdsError, LabelError — его наследники), текст без флагов командной
    строки. В res — ещё requested / applied (что просили и что вышло: стратегия, общий рез, мост, подписи), files (имена
    записанных файлов), timing; у раскладок — W, L, util_pct, cut_m, mark_m, pierces, mass_kg (на один лист)."""
    import time
    t_run = time.time()
    from .pack import plan, plan_coedge, check_fit
    from .route import route_sheet, route_sheet_coedge, STRATEGIES, options
    from .write_lxds import build
    from .verify import check_safe as check
    from . import render, risk as RK
    from . import machine as MC
    from . import bridge as BR
    prog = progress or (lambda stage, text: None)
    check_params(W, L, gap, edge, thickness, small)
    o = options(strategy)
    br = bridge_options(bridge)
    if br and coedge:
        raise SheetNestError("мост и общий рез вместе пока нельзя: перемычке нужен зазор между деталями, а общий рез ставит их "
                             "вплотную — выберите что-то одно")
    small = RK.SMALL if small is None else float(small)
    machines = [MC.load(m) for m in (machine if isinstance(machine, (list, tuple)) else [machine] if machine else [])]
    if len({m["name"] for m in machines}) < len(machines):
        raise MC.MachineError("профили станков: имена повторяются (%s) — задайте name в профиле" % ", ".join(m["name"] for m in machines))
    if labels:
        from .labels import check_opts
        lo_ = dict(H=15.0, H_min=10.0, margin=3.0, gap=1.0)
        lo_.update({k: v for k, v in (label_opts or {}).items() if k in lo_})
        check_opts(**lo_)                               # до чтения деталей: плохие высоты — отказ сразу
    prog("read", "чтение деталей: файлов %d" % len(inputs))
    parts, technical, warns = load_parts(inputs, qty, engrave_layers)
    n_total = sum(p["qty"] for p in parts)
    if n_total > QTY_MAX:
        raise SheetNestError("деталей %d — больше, чем движок раскладывает за один раз (%d): разбейте задание на несколько"
                             % (n_total, QTY_MAX))
    mark_microjoints(parts, microjoints)
    for w in warns:
        log("  ⚠ " + w)
    log("деталей: %d видов, %d шт" % (len(parts), sum(p["qty"] for p in parts)))
    lab_rep = []
    if labels:
        prog("read", "подписи деталей")
        from .labels import apply_labels
        lo = dict(H=15.0, H_min=10.0, margin=3.0, gap=1.0, font_path=None)
        lo.update(label_opts or {})
        lab_rep = apply_labels(parts, labels, **lo)
        for name, text, h, why in lab_rep:
            log("  подпись %-30s «%s» %s" % (name, text, ("%g мм" % h) if h else "⚠ " + why))
            if not h:
                warns.append("%s: %s — деталь без подписи" % (name, why))
    check_fit(parts, W, L, edge)                        # понятный отказ и для общего реза (его раскрой — без этой проверки)
    pl = None
    cwarn = []                                          # общий рез не применён — причина в предупреждения (ERP.md, п. 4)
    if coedge:
        prog("pack", "раскрой под общий рез, лист %g×%g" % (W, L))
        pl, why = plan_coedge(parts, W, L, edge)
        if pl is None:
            log("  ⚠ общий рез не применён: %s — раскладываю с зазором %g мм" % (why, gap))
            cwarn.append("общий рез не применён: %s — раскладка с зазором %g мм" % (why, gap))
    if pl is None:
        prog("pack", "раскрой, лист %g×%g" % (W, L))
        pl = plan(parts, W, L, gap, edge, methods)
    for t in pl["tried"]:
        log("  раскрой %-40s %s" % (t["method"], ("%d листов, %d раскладок" % (t["sheets"], t["layouts"])) if "sheets" in t
                                    else ("пропущен: " + t["skipped"]) if "skipped" in t else t.get("error")))
    log("раскрой: %s — %d листов %g×%g (нижняя граница %d %s%s)" % (pl["method"], pl["sheets"], W, L, pl["lower_bound"],
                                                                     pl["bound_kind"], ", минимум" if pl["optimal"] else ""))
    from .route import CoedgeRouteError
    bwarn = []
    if br:
        prog("pack", "мост: группы деталей")
        for l in pl["layouts"]:
            l["bridges"] = BR.plan(parts, l["placed"], gap, br["width"], br["group"])
            bwarn += l["bridges"]["skipped"]
        bwarn = sorted(set(bwarn))
        st_ = BR.stats(pl["layouts"])
        log("мост %g мм, до %d деталей в группе: групп %d, перемычек %d, деталей в мостах %d — врезок меньше на %d" % (
            br["width"], br["group"], st_["groups"], st_["bridges"], st_["parts"], st_["pierces_saved"]))
        if not st_["groups"]:
            bwarn.append("мост не применён: нет соседних круглых деталей через зазор %g мм%s" % (
                gap, " (детали с микроперемычками в мост не идут)" if any(p.get("microjoints") for p in parts) else ""))
        for w in bwarn:
            log("  ⚠ " + w)

    def route_all(pl, st, caches):
        """Маршруты всех раскладок по стратегии st: ([результат раскладки], секунд). Раскладка с мостами — маршрут по
        группам (bridge.bridged: группа — одна деталь), элементы группы в маршруте — ("bridge", [детали], фигуры)."""
        t0, rs = time.time(), []
        for l, c in zip(pl["layouts"], caches):
            if l.get("groups"):
                rs.append(route_sheet_coedge(l["placed"], l["groups"], parts, l["W"], l["L"], strategy=st, small=small, cache=c))
            elif l.get("bridges") and l["bridges"]["groups"]:
                if "_bridged" not in l:
                    l["_bridged"] = BR.bridged(parts, l)
                placed2, parts2, back = l["_bridged"]
                r = route_sheet(placed2, parts2, l["W"], l["L"], strategy=st, small=small, cache=c)
                r["seq"] = BR.unmap(r["seq"], back)
                rs.append(r)
            else:
                rs.append(route_sheet(l["placed"], parts, l["W"], l["L"], strategy=st, small=small, cache=c))
        return rs, time.time() - t0

    fails = {}                                          # стратегия сводки → (причина, секунд): общий рез не построился

    def route_plan(pl):
        # у каждой стратегии свой кэш листа (планы деталей, пути оптимизатора) — время в сводке честное
        fails.clear()
        names = [o["name"]] + ([n for n in STRATEGIES if n != o["name"]] if compare else [])
        res_ = {}
        for k, name in enumerate(names):
            prog("route", "маршрут: %s, %d/%d" % (o["title"] if k == 0 else STRATEGIES[name]["title"], k + 1, len(names)))
            if k == 0:
                res_[name] = route_all(pl, name if strategy is None or isinstance(strategy, str) else strategy,
                                       [{} for _ in pl["layouts"]])
                continue
            t0 = time.time()
            try:
                res_[name] = route_all(pl, name, [{} for _ in pl["layouts"]])
            except CoedgeRouteError as e:
                # ERP.md, п. 8: порядок группы не нашёлся у стратегии сводки — не построена только её строка; раскрой и
                # программа выбранной стратегии остаются с общим резом (прежде откатывалась вся сводка)
                if not pl.get("coedge"):
                    raise
                fails[name] = (str(e), time.time() - t0)
        return res_
    try:
        by = route_plan(pl)
    except CoedgeRouteError as e:
        log("  ⚠ общий рез не применён: %s — раскладываю с зазором %g мм" % (e, gap))
        cwarn.append("общий рез не применён: %s — раскладка с зазором %g мм" % (e, gap))
        prog("pack", "раскрой с зазором, лист %g×%g" % (W, L))
        pl = plan(parts, W, L, gap, edge, methods)
        log("раскрой: %s — %d листов %g×%g (нижняя граница %d %s%s)" % (pl["method"], pl["sheets"], W, L, pl["lower_bound"],
                                                                         pl["bound_kind"], ", минимум" if pl["optimal"] else ""))
        by = route_plan(pl)
    rs, secs = by[o["name"]]
    for l, r in zip(pl["layouts"], rs):
        l["seq"], l["idle"] = r["seq"], r["idle"]
    route_warn = [w for r in rs for w in r["warnings"]]
    amounts = [l["amount"] for l in pl["layouts"]]

    def opt(n):                                         # переключатели стратегии по имени (своя — из strategy)
        return options(n) if n in STRATEGIES else o

    def risk_warn(name, rs_, safe):
        """Опасные переходы, которые стратегия не обошла (только у безопасных — у «short» безопасность не цель). Обход —
        поиск, а не доказательство: «не удалось обойти»; с --compare — у какой стратегии на этой раскладке их меньше
        (ступени ключа: язычки → мелкие → детали → отверстия)."""
        out_ = []
        for k, (l, r) in enumerate(zip(pl["layouts"], rs_)):
            m = r["risk"]
            bad = ["%s %d" % (RK.TITLES[c], m[c]) for c in ("tongues", "small", "parts", "holes") if m[c]]
            if bad and safe:
                better = [n for n, (rs2, _) in by.items() if n != name and tuple(rs2[k]["risk"]["key"][:4]) < tuple(m["key"][:4])]
                out_.append("раскладка №%d (×%d): опасные переходы остались — %s; эта стратегия их обойти не смогла%s "
                            "(иначе — микроперемычки или другой раскрой)" % (
                                k + 1, l["amount"], ", ".join(bad),
                                ("; меньше у %s" % ", ".join("«%s»" % opt(n)["title"] for n in better)) if better else ""))
        return out_

    def strip_warn(name, rs_):
        """«Узкая полоса в конце» (risk.end_strip) — у любой стратегии; с --compare — у какой стратегии на этой раскладке её
        нет."""
        out_ = []
        for k, (l, r) in enumerate(zip(pl["layouts"], rs_)):
            s = r.get("strip")
            if s and s["strip"]:
                fine = [n for n, (rs2, _) in by.items() if n != name and rs2[k].get("strip") and not rs2[k]["strip"]["strip"]]
                hills = [n for n in by if opt(n).get("hill")]
                if fine:
                    tip = "; без неё — %s" % ", ".join("«%s» (%.0f×%.0f)" % (opt(n)["title"], by[n][0][k]["strip"]["w"],
                                                                           by[n][0][k]["strip"]["l"]) for n in fine)
                elif hills:                             # «Горкой» посчитан и полосу не убрал — совет был бы неверным
                    tip = "; у «Горкой» (ступенька и порядки безопасных) она тоже есть — убрать её может другой раскрой"
                else:
                    tip = "; против неё — попробовать порядок «Горкой»"
                out_.append("раскладка №%d (×%d): к концу резки остаётся узкая полоса %.0f×%.0f мм (последние %d из %d деталей; "
                            "не больше %d деталей поперёк, длиннее половины листа) — её может повести от нагрева%s" % (
                                k + 1, l["amount"], s["w"], s["l"], s["parts"], s["of"], RK.STRIP_PARTS, tip))
        return out_
    rwarn = risk_warn(o["name"], rs, o["key"] != "short") + strip_warn(o["name"], rs)
    fwarn = ["сводка: «%s» с общим резом не строится (%s) — эту стратегию с общим резом не выбрать" % (opt(n)["title"], why)
             for n, (why, _) in fails.items()]
    x_tongue = sum(r["crossings"] * a for r, a in zip(rs, amounts))
    x_parts = sum(r["crossings_parts"] * a for r, a in zip(rs, amounts))
    tot = RK.total([r["risk"] for r in rs], amounts)
    idle = sum(l["idle"] * l["amount"] for l in pl["layouts"])
    log("порядок резки (%s «%s»): холостой ход %.1f м, возврат в ноль %.1f м; переходов над вырезанными язычками %d, "
        "над вырезанными деталями %d" % (o["name"], o["title"], idle / 1000, tot["ret"]["m"], x_tongue, x_parts))
    log("  опасные переходы: " + ", ".join("%s %d" % (RK.TITLES[c], tot[c]) for c in RK.CLASSES) +
        "; возврат над деталями %.2f м, под ним язычков %d" % (tot["ret"]["over_m"], tot["ret"]["tongues_crossed"]))
    for w in sorted(set(route_warn)) + rwarn + fwarn:
        log("  ⚠ " + w)
    rows = None
    if compare:
        rows = []
        for name, (rs_, secs_) in by.items():
            oo = opt(name)
            rows.append(summary_row(pl, rs_, name, oo["title"], secs_, thickness, machines,
                                    sorted(set(w for r in rs_ for w in r["warnings"])) + risk_warn(name, rs_, oo["key"] != "short")
                                    + strip_warn(name, rs_)))
        for name, (why, secs_) in fails.items():
            rows.append(failed_row(name, opt(name)["title"], why, secs_, machines))
        order_ = list(STRATEGIES) + [n for n in by if n not in STRATEGIES]
        rows.sort(key=lambda r: order_.index(r["name"]))
        log("сводка по стратегиям (%s):" % ("общий рез" if pl.get("coedge") else "с зазором"))
        for line in summary_text(rows).split("\n"):
            log("  " + line)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=10))).strftime("%Y-%m-%d_%H%M")
    title = title or os.path.splitext(os.path.basename(_input(inputs[0])[0]))[0]
    tag = "" if (gap, edge) == (2.0, 2.0) else "_зазор%g_край%g" % (gap, edge)
    if pl.get("coedge"):
        tag += "_общий_рез"
    bst = BR.stats(pl["layouts"]) if br else None
    if bst and bst["groups"]:
        tag += "_мост"
    fname = "%s_лист%gx%g%s_%s" % (title, W, L, tag, stamp)
    prog("build", "сборка программы")
    raw, M = build(parts, pl["layouts"], fname, technical)
    prog("check", "проверка программы")
    rep, rr, ctx = check(raw, parts, pl["layouts"], gap, edge, thickness)
    ok = all(x[1] is not False for x in rep)
    for n, o_, d in rep:
        log("  %s %-62s %s" % ("✓" if o_ else "⚠" if o_ is None else "✗", n, d))
    main_row = rows[[r["name"] for r in rows].index(o["name"])] if rows else \
        summary_row(pl, rs, o["name"], o["title"], secs, thickness, machines, sorted(set(route_warn)) + rwarn)
    lab_ok = sum(1 for n_, tx, h, why in lab_rep if h)
    res = dict(file=fname + ".lxds", ok=ok, sheets=pl["sheets"], lower_bound=pl["lower_bound"], optimal=pl["optimal"],
               method=pl["method"], tried=pl["tried"], idle_m=round(idle / 1000, 2),
               # tongues, parts — как было (маршрут: над вырезанными язычками; заходы в деталь над вырезанной — с зазором,
               # все переходы — с общим резом); остальное — счёт risk.measure (классы опасных переходов)
               crossings=dict(tongues=x_tongue, parts=x_parts, holes=tot["holes"], holes_small=tot["holes_s"],
                              freed_small=tot["small"], freed_parts=tot["parts"], freed_mj=tot["mj"], near=tot["near"],
                              short=tot["short"], cut_tongues=tot["tongues"]),
               strategy=o["name"], strategy_title=o["title"], coedge=bool(pl.get("coedge")), small_mm=small,
               microjoints=[p["name"] for p in parts if p.get("microjoints")],
               risk=dict({c: tot[c] for c in RK.CLASSES}, moves=tot["moves_n"], over_parts_m=tot["over_parts_m"], ret=tot["ret"],
                         cut_m=main_row["cut_m"], mark_m=main_row["mark_m"], pierces=main_row["pierces"], route_s=main_row["route_s"],
                         machine_s=main_row["machine_s"]),
               layouts=[dict(index=k + 1, amount=l["amount"], parts=dict(collections.Counter(parts[q["part"]]["name"] for q in l["placed"])),
                             idle_m=round(l["idle"] / 1000, 3),
                             # то же, что в итогах (res["risk"]), по раскладке: ret_m, ret_over_m — как были; ret —
                             # возврат целиком (длина, метры над деталями, язычков под ним, классы перехода)
                             risk=dict({c: r["risk"][c] for c in RK.CLASSES}, ret_m=round(r["risk"]["ret"]["m"], 3),
                                       ret_over_m=round(r["risk"]["ret"]["over_m"], 3), over_parts_m=round(r["risk"]["over_parts_m"], 3),
                                       ret={k_: (round(v_, 3) if isinstance(v_, float) else v_) for k_, v_ in r["risk"]["ret"].items()},
                                       key=list(r["risk"]["key"]), key0=list(r["risk"]["key0"])),
                             # остаток к концу резки (risk.end_strip): последние 20 % деталей — габарит, узкая ли полоса
                             strip=r.get("strip"),
                             **({"bridges": BR.stats([l])} if l.get("bridges") else {}),
                             # на один лист раскладки (ERP.md, п. 6): размер, загрузка, рез, гравировка, врезки, масса листа
                             **layout_stats(l, r, parts, thickness))
                        for k, (l, r) in enumerate(zip(pl["layouts"], rs))],
               totals={k: v for k, v in rr["totals"].items()} if rr else {}, checks=[(n, o_, d) for n, o_, d in rep],
               warnings=warns + cwarn + bwarn + route_warn + rwarn + fwarn, strip=main_row["strip"],
               labels=[dict(part=n, text=tx, height=h, rot=next((p["label"]["rot"] for p in parts if p["name"] == n and p.get("label")), None),
                            why=why) for n, tx, h, why in lab_rep],
               # что просили и что вышло (ERP.md, п. 4): общий рез мог откатиться на зазор, мост — не найти соседей
               requested=dict(strategy=o["name"], coedge=bool(coedge), bridge=dict(br) if br else None,
                              labels=dict(labels) if labels else None),
               applied=dict(strategy=o["name"], coedge=bool(pl.get("coedge")), bridge_groups=bst["groups"] if bst else 0,
                            labels_ok=lab_ok, labels_failed=len(lab_rep) - lab_ok),
               mass_kg=(round(sum(l["W"] * l["L"] * l["amount"] for l in pl["layouts"]) * float(thickness) * DENSITY, 1)
                        if thickness else None),
               files=dict(lxds=None, png_layouts=None, png_order=None, report=None))
    if rows is not None:
        res["strategies"] = {r["name"]: r for r in rows}
    if br:
        res["bridge"] = dict(br, **bst)
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, fname + ".lxds"), "wb") as f:
            f.write(raw)
        res["files"]["lxds"] = fname + ".lxds"
        # картинки — после программы и до отчёта: не нарисовались — предупреждение в отчёте, программа остаётся (п. 4)
        prog("render", "картинки раскладок и порядка резки")
        what = (", общий рез" if pl.get("coedge") else "") + ((", мост %g мм: групп %d" % (br["width"], bst["groups"])) if bst and bst["groups"] else "")
        for key_, png_, draw in (
                ("png_layouts", fname + ".png", lambda path: render.png_model(
                    raw, path, "%s — %d листов %g×%g%s, «%s»: холостой ход %.0f м, врезок %d" % (
                        title, pl["sheets"], W, L, what, o["title"], idle / 1000, main_row["pierces"]),
                    moves=[r["risk"]["moves"] for r in rs])),
                ("png_order", fname + "_порядок.png", lambda path: render.png_order(
                    raw, path, "%s — порядок резки «%s»%s: цвет — от первой детали (синий) к последней (красный)" % (
                        title, o["title"], what), strips=[r.get("strip") for r in rs], done_polys=[r.get("done_polys") for r in rs]))):
            try:
                draw(os.path.join(out, png_))
                res["files"][key_] = png_
            except Exception as e:                      # Pillow нет, шрифта нет, память — программа уже записана
                w = "картинка %s не нарисована: %s: %s" % (png_, type(e).__name__, e)
                log("  ⚠ " + w)
                res["warnings"].append(w)
        res["files"]["report"] = fname + ".json"
    res["timing"] = dict(route_s=round(sum(s_ for _, s_ in by.values()) + sum(s_ for _, s_ in fails.values()), 2),
                         total_s=round(time.time() - t_run, 2))
    if out:
        with open(os.path.join(out, fname + ".json"), "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        log("→ %s" % os.path.join(out, fname + ".lxds"))
    return res, raw, pl, parts


def main(argv=None):
    from .route import STRATEGIES, DEFAULT
    ap = argparse.ArgumentParser(prog="python3 -m sheet_nest.cli")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--sheet", default="1250x2500", help="лист ШxД, мм (1250x2500)")
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--edge", type=float, default=2.0)
    ap.add_argument("--thickness", type=float, default=None)
    ap.add_argument("--qty", action="append", default=[], help="ИМЯ=N (имя детали или файла без расширения)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--method", choices=("auto", "rect", "raster"), default="auto")
    ap.add_argument("--coedge", action="store_true", help="общий рез: детали вплотную, общие кромки режутся один раз (группы CypCut)")
    ap.add_argument("--bridge", action="store_true", help="мост: соседние круглые детали через зазор — перемычками в группы, "
                                                          "группа режется одной врезкой (Bridge CypCut)")
    ap.add_argument("--bridge-width", type=float, default=2.0, help="ширина перемычки моста, мм (2)")
    ap.add_argument("--bridge-group", type=int, default=5, help="деталей в группе моста, не больше (5)")
    ap.add_argument("--strategy", choices=list(STRATEGIES), default=DEFAULT,
                    help="порядок резки: " + "; ".join("%s — %s" % (k, v["title"]) for k, v in STRATEGIES.items()))
    ap.add_argument("--compare", action="store_true", help="сводка по всем стратегиям (программа — по --strategy)")
    ap.add_argument("--small", type=float, default=100.0, help="мелкая деталь: меньше стольких мм по одной из сторон (100)")
    ap.add_argument("--microjoints", action="append", default=[], help="ИМЯ детали с микроперемычками (* — все; повторяется)")
    ap.add_argument("--machine", action="append", default=[], help="профиль станка (JSON) — время в сводке (повторяется: "
                                                                   "строка на каждый станок)")
    ap.add_argument("--label", action="append", default=[], help="подпись гравировкой: ИМЯ=ТЕКСТ (имя детали; * — всем)")
    ap.add_argument("--label-height", type=float, default=15.0, help="высота букв, мм (15)")
    ap.add_argument("--label-min", type=float, default=10.0, help="наименьшая высота, если не помещается (10)")
    ap.add_argument("--label-margin", type=float, default=3.0, help="отступ подписи от отверстий, прорезей и края, мм (3)")
    ap.add_argument("--font", default=None, help="файл шрифта GOST.FON (GOST type A plotter)")
    a = ap.parse_args(argv)
    try:
        W, L = (float(x) for x in a.sheet.lower().replace("х", "x").split("x"))
    except ValueError:
        sys.exit("ошибка: --sheet ШxД, например 1250x2500")
    qty = {}
    for q in a.qty:
        k, _, v = q.rpartition("=")
        try:
            qty[k] = int(v)
        except ValueError:
            sys.exit("ошибка: --qty %r: нужно ИМЯ=N (N — целое число)" % q)
    methods = ("rect", "raster") if a.method == "auto" else (a.method,)
    try:
        labels = {}
        for q in a.label:
            k, _, v = q.partition("=")
            if not v.strip() or not k.strip():
                raise ValueError("--label %r: нужно ИМЯ=ТЕКСТ (или *=ТЕКСТ)" % q)
            labels[k.strip()] = v
        res, *_ = run(a.inputs, W, L, a.gap, a.edge, a.thickness, qty, a.name, a.out or os.getcwd(), methods, coedge=a.coedge,
                      labels=labels or None, label_opts=dict(H=a.label_height, H_min=a.label_min, margin=a.label_margin,
                                                             font_path=a.font),
                      strategy=a.strategy, compare=a.compare, small=a.small, microjoints=a.microjoints or None,
                      machine=a.machine or None,
                      bridge=dict(width=a.bridge_width, group=a.bridge_group) if a.bridge else None)
    except ValueError as e:
        # тексты движка — без флагов командной строки (их видит и Odoo); подсказку флагом добавляет командная строка
        flag = getattr(e, "flag", None)
        sys.exit("ошибка: %s%s" % (e, (" (%s)" % flag) if flag else ""))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
