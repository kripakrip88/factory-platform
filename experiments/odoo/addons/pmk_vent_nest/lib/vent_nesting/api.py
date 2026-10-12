# -*- coding: utf-8 -*-
"""Программный интерфейс раскроя вентзонтов для ERP: байты на входе, словари и байты на выходе.

    from vent_nesting import api
    order = api.order_from_zip(zip_bytes)                       # «Скачать всё»: DXF генератора + *_сборка.xlsx
    order = api.order_from_dxf([(имя_dxf, dxf_bytes), ...], {имя_dxf: зонтов, ...})
    p = api.plan(order, gap=2, edge=2)                          # варианты склад/бухта по материалам, кг, картинка
    t = api.sves_table(order)                                   # (по запросу) перебор свеса 150…125 × склад/бухта
    files = api.build_lxds(order, "coil", name="ВЗ-00002")      # после выбора инженера: программы CypCut

Правило Антона: «сначала решение, потом файл» — plan() только показывает, build_lxds() собирает выбранное.
Свес меньше 150 меняет изделие — его выбирает инженер (sves=...), система сама не меняет.

Любая ошибка входа или параметров — VentNestingError (подкласс ValueError) с русским текстом для пользователя.
Каждый DXF при создании заказа сверяется с генератором зонтов (тот же, что в ERP): состав деталей, отверстий и пазов,
габариты. Битый, обрезанный, чужой или переименованный DXF не пройдёт — раскроя «не тех деталей» не будет.

Внутри — глобальное состояние раскроя (зазор, кэши), поэтому вызовы сериализуются блокировкой; в Odoo
запускать в отдельном процессе (фоновое задание), см. README.
"""
import os, io, re, math, json, zipfile, tempfile, threading, collections, contextlib

try:
    import PIL  # noqa: F401 — Pillow нужен самому раскрою (растр деталей), не только картинке
except ImportError as e:
    raise ImportError("для раскроя нужен Pillow (pip install Pillow; в Odoo он есть)") from e

from . import nest as N
from . import parts as PT
from . import model as LM
from . import lxds_write as LW
from . import hood_sves as V

_LOCK = threading.Lock()
SVES_LIST = (150, 145, 140, 135, 130, 125)
MAX_DXF_BYTES = 5 * 2 ** 20          # генератор даёт 9–20 КБ; больше — не наш файл
MAX_XLSX_BYTES = 5 * 2 ** 20
MAX_ZIP_ENTRIES = 500
MAX_HOODS = 1000                     # зонтов одного размера в заказе
DEFAULT_GAP, DEFAULT_EDGE = 2.0, 2.0


class VentNestingError(ValueError):
    """Ошибка входа или параметров — текст можно показывать пользователю."""


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise VentNestingError("%s: нужно число, получено %r" % (what, v))
    return float(v)


def color_key(c):
    """Цвет из имени DXF («RAL8017», «оц») и из ведомости («RAL 8017 Шоколад», «Оцинковка») → общий ключ."""
    s = str(c or "").strip().lower()
    m = re.search(r"ral\s*-?\s*(\d{4})", s) or re.match(r"^(\d{4})\b", s)
    if m:
        return "ral" + m.group(1)
    if not s or s.startswith(("оц", "zn", "цинк", "без покрыт")):
        return "оц"                                   # у генератора пустой цвет = оцинковка
    return re.sub(r"[\s_\-]+", "", s)


def _size_key(s):
    s = str(s).strip().lower().replace("х", "x").replace("×", "x").replace("*", "x").replace(" ", "")
    m = re.fullmatch(r"(\d+)x(\d+)", s)
    return "%dx%d" % (int(m.group(1)), int(m.group(2))) if m else None


# ------------------------------------------------------------------ сверка DXF с генератором
def _signature(parts):
    """Состав DXF: по детали — габарит, площадь, отверстия (центр от угла габарита + диаметр), пазы (центр, рёбер),
    вершины внешнего контура; округление 0,1 мм — сортировано. Генератор ERP пишет DXF байт в байт как эталон."""
    sig = []
    for p in parts:
        xs = [q[0] for q in p["poly"]]; ys = [q[1] for q in p["poly"]]
        x0, y0 = min(xs), min(ys)
        r1 = lambda v: round(v + 0.0, 1) + 0.0
        holes = tuple(sorted((r1(h[0] - x0), r1(h[1] - y0), r1(h[2])) for h in p["holes"]))
        slots = tuple(sorted((r1((s["bbox"][0] + s["bbox"][1]) / 2 - x0), r1((s["bbox"][2] + s["bbox"][3]) / 2 - y0), len(s["edges"]))
                             for s in p["slots"]))
        verts = tuple(sorted({(r1(q[0] - x0), r1(q[1] - y0)) for e in p["edges"] for q in (e["p0"], e["p1"])}))
        sig.append((r1(max(xs) - x0), r1(max(ys) - y0), round(N._area(p["poly"]) / 100.0), holes, slots, verts))
    return sorted(sig)


def _analyze_dxf(name, data, tmp):
    p = os.path.join(tmp, "check.dxf")
    open(p, "wb").write(data)
    report = []
    try:
        parts, small = PT.analyze(p, report)
    except Exception as e:
        raise VentNestingError("DXF %s не читается: %s" % (name, e))
    problems = [r["warn"] for r in report if isinstance(r, dict) and r.get("warn")]
    if any(r.get("virtual") for r in report if isinstance(r, dict)):
        problems.append("разрывы в контурах (достроены отрезки)")
    for k, q in enumerate(parts):
        if q["poly"] is None:
            problems.append("деталь %d: контур не замкнут" % (k + 1))
        if q["smalls"]:
            problems.append("деталь %d: %d мелких контуров без дуг (их раскрой не режет)" % (k + 1, len(q["smalls"])))
    if not parts:
        problems.append("ни одной детали")
    return parts, problems


_REF = {}


def _reference(W, L):
    """Состав DXF генератора зонтов для размера (свес 150 — как в ERP; генератор совпадает с ERP 51/51)."""
    if (W, L) not in _REF:
        try:
            dxf = V.to_dxf(V.hood(W, L)).encode()
        except Exception as e:
            raise VentNestingError("генератор не строит зонт %dx%d: %s" % (W, L, e))
        with tempfile.TemporaryDirectory(prefix="vent_nesting_") as tmp:
            parts, problems = _analyze_dxf("эталон", dxf, tmp)
        _REF[(W, L)] = (_signature(parts), len(parts))
    return _REF[(W, L)]


class Order:
    """Заказ: DXF генератора зонтов (vsh_ШxД_tТОЛЩ_ЦВЕТ.dxf) и количество зонтов на каждый DXF."""
    def __init__(self, dxf, qty, parts_per_hood=None):
        self.dxf, seen, mats = [], set(), {}
        try:
            dxf = [tuple(x) for x in dxf]
        except TypeError:
            raise VentNestingError("DXF заказа: нужен список пар (имя, байты)")
        if any(len(x) != 2 for x in dxf):
            raise VentNestingError("DXF заказа: каждый элемент — пара (имя, байты)")
        for name, data in dxf:
            name = os.path.basename(str(name).replace("\\", "/"))
            mat = N.material_of(name)
            if not mat:
                raise VentNestingError("%s: не DXF генератора зонтов — нужно имя vsh_ШxД_tТОЛЩ_ЦВЕТ.dxf" % name)
            if isinstance(data, str):
                data = data.encode()
            try:
                data = bytes(data)
            except Exception:
                raise VentNestingError("%s: содержимое DXF должно быть байтами" % name)
            if len(data) > MAX_DXF_BYTES:
                raise VentNestingError("%s: %d байт — слишком большой для DXF зонта" % (name, len(data)))
            W, L, t, col = mat
            key = (W, L, round(t, 6), color_key(col))
            if name.lower() in seen or key in mats:
                raise VentNestingError("%s: зонт %dx%d %s %g мм передан дважды — количество задаётся числом, а не повтором DXF"
                                       % (name, W, L, col, t))
            seen.add(name.lower()); mats[key] = name
            self.dxf.append((name, data))
        if not self.dxf:
            raise VentNestingError("в заказе нет DXF зонтов")
        # количество: каждому DXF — целое 1…MAX_HOODS; ключ — имя DXF или «ШxД» (если размер в заказе один)
        if not isinstance(qty, dict) or not qty:
            raise VentNestingError("не задано количество зонтов (нужно на каждый DXF)")
        by_size = collections.defaultdict(list)
        for name, _ in self.dxf:
            W, L, t, col = N.material_of(name)
            by_size["%dx%d" % (W, L)].append(name)
        self.qty = {}
        for k, v in qty.items():
            if isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= MAX_HOODS):
                raise VentNestingError("количество для %r: нужно целое 1…%d, получено %r" % (k, MAX_HOODS, v))
            target = None
            kb = os.path.basename(str(k).replace("\\", "/")).lower() if isinstance(k, str) else None
            if kb in seen:
                target = next(n for n, _ in self.dxf if n.lower() == kb)
            elif isinstance(k, str) and _size_key(k):
                names = by_size.get(_size_key(k), [])
                if len(names) > 1:
                    raise VentNestingError("размер %s есть в нескольких материалах (%s) — количество задайте по имени DXF"
                                           % (_size_key(k), ", ".join(names)))
                target = names[0] if names else None
            if target is None:
                raise VentNestingError("количество для %r: в заказе нет такого DXF или размера" % (k,))
            if target in self.qty:
                raise VentNestingError("количество для %s задано дважды" % target)
            self.qty[target] = v
        missing = [n for n, _ in self.dxf if n not in self.qty]
        if missing:
            raise VentNestingError("нет количества для: %s" % ", ".join(missing))
        # сверка каждого DXF с генератором (и с ведомостью «Деталей на зонт», если она есть)
        self.parts_per_hood = {}
        with tempfile.TemporaryDirectory(prefix="vent_nesting_") as tmp:
            for name, data in self.dxf:
                W, L, t, col = N.material_of(name)
                parts, problems = _analyze_dxf(name, data, tmp)
                if problems:
                    raise VentNestingError("%s: %s" % (name, "; ".join(problems[:4])))
                ref_sig, ref_n = _reference(W, L)
                sig = _signature(parts)
                if sig != ref_sig:
                    raise VentNestingError("%s: состав не совпадает с генератором зонта %dx%d (деталей %d, у генератора %d) — "
                                           "файл обрезан, испорчен или от другого размера" % (name, W, L, len(sig), ref_n))
                self.parts_per_hood[name] = ref_n
                pph = (parts_per_hood or {}).get(name)
                if pph is not None and pph != ref_n:
                    raise VentNestingError("%s: в ведомости %d деталей на зонт, а генератор даёт %d" % (name, pph, ref_n))

    def hoods(self):
        out = []
        for name, _ in self.dxf:
            W, L, t, col = N.material_of(name)
            out.append({"dxf": name, "size": "%dx%d" % (W, L), "color": col, "thickness": t, "qty": self.qty[name],
                        "parts_per_hood": self.parts_per_hood[name]})
        return out

    def expected_per_hood(self, color, t, sves=None):
        """Сколько деталей каждого зонта должно быть в программе материала: зонтов × деталей на зонт. Со свесом
        меньше 150 число панелей может измениться (тело L + 2·свес короче) — берётся у генератора с этим свесом."""
        out = {}
        for name, _ in self.dxf:
            W, L, tt, col = N.material_of(name)
            if color_key(col) == color_key(color) and abs(tt - t) < 1e-6:
                n = self.parts_per_hood[name] if sves is None else len(V.hood(W, L, sves=sves)["parts"])
                out["%d×%d" % (W, L)] = self.qty[name] * n
        return out

    def items(self, sves=None):
        """Детали заказа для раскроя (×количество). sves — пересобрать детали со свесом (копия генератора)."""
        with tempfile.TemporaryDirectory(prefix="vent_nesting_") as tmp:
            paths = []
            for name, data in self.dxf:
                p = os.path.join(tmp, name)
                if sves is None:
                    open(p, "wb").write(data)
                else:
                    W, L, t, col = N.material_of(name)
                    try:
                        open(p, "w").write(V.to_dxf(V.hood(W, L, sves=sves)))
                    except ValueError as e:
                        raise VentNestingError("зонт %dx%d со свесом %g: %s" % (W, L, sves, e))
                paths.append((p, name))
            return N.load_order(paths, self.qty)


MAX_XLSX_ROWS = 5000                 # ведомость заказа — десятки строк; больше — не наша
MAX_XLSX_SHEET = 20 * 2 ** 20        # распакованный лист внутри xlsx (защита от «бомбы»)


def _read_member(z, zi, limit, what):
    """Запись архива с ограничением распакованного размера (file_size в заголовке можно подделать)."""
    try:
        with z.open(zi) as f:
            data = f.read(limit + 1)
    except Exception as e:
        raise VentNestingError("%s в архиве повреждён или зашифрован (%s)" % (what, type(e).__name__))
    if len(data) > limit:
        raise VentNestingError("%s: больше %d МБ — это не файл заказа" % (what, limit // 2 ** 20))
    return data


def _num_cell(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


HEAD = {"num": ("№",), "hood": ("зонт",), "shaft": ("шахта",), "color": ("цвет",), "t": ("металл",),
        "qty": ("зонтов",), "pph": ("деталей на зонт",)}


def assembly_rows(data):
    """Сборочная ведомость ERP (лист «Сборка»). Колонки ищутся по заголовкам — читаются оба макета калькулятора:
    до v1.61 «Зонт» = «вш 500х1000»; с v1.61 «Шахта, мм» = «1000 × 500» (длина × ширина) и «Зонт, мм» = габарит.
    Строка зонта: размер, Цвет, Металл, мм, Зонтов, шт; «Деталей на зонт» — по строкам деталей зонта."""
    if len(data) > MAX_XLSX_BYTES:
        raise VentNestingError("сборочная ведомость больше %d МБ" % (MAX_XLSX_BYTES // 2 ** 20))
    try:                                                     # xlsx — тоже zip: лист не больше MAX_XLSX_SHEET
        xz = zipfile.ZipFile(io.BytesIO(data))
        for zi in xz.infolist():
            if zi.filename.startswith("xl/worksheets/"):
                _read_member(xz, zi, MAX_XLSX_SHEET, "лист ведомости")
    except VentNestingError:
        raise
    except Exception as e:
        raise VentNestingError("сборочная ведомость не читается: %s" % type(e).__name__)
    try:
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True).worksheets[0]
    except Exception as e:
        raise VentNestingError("сборочная ведомость не читается: %s" % e)
    col, out, cur = None, [], None
    for n, r in enumerate(ws.iter_rows(values_only=True)):
        if n > MAX_XLSX_ROWS:
            raise VentNestingError("в ведомости больше %d строк — это не ведомость заказа" % MAX_XLSX_ROWS)
        r = list(r)
        cells = [str(v).strip().lower() if v is not None else "" for v in r]
        if col is None:                                      # строка заголовков
            if any(c.startswith("цвет") for c in cells) and any(c.startswith("зонтов") for c in cells):
                col = {}
                for k, keys in HEAD.items():
                    for i, c in enumerate(cells):
                        if k not in col and any(c.startswith(x) for x in keys) and not (k == "hood" and c.startswith("зонтов")):
                            col[k] = i
                if "qty" not in col or "color" not in col or "t" not in col or not ("shaft" in col or "hood" in col):
                    raise VentNestingError("ведомость: не найдены колонки «Шахта/Зонт», «Цвет», «Металл, мм», «Зонтов, шт»")
            continue
        get = lambda k: r[col[k]] if k in col and col[k] < len(r) else None
        first = " ".join(c for c in cells[:2] if c)
        if first.startswith(("итого", "всего")):              # итоговая строка — до учёта деталей
            cur = None
            continue
        size = None
        if "shaft" in col and get("shaft") not in (None, ""):
            m = re.findall(r"\d+", str(get("shaft")))
            if len(m) >= 2:
                a_, b_ = int(m[0]), int(m[1]); size = (min(a_, b_), max(a_, b_))
        elif "hood" in col and isinstance(get("hood"), str) and re.match(r"(?i)\s*(?:вентзонт\s+)?вш\s*-?\s*\d", get("hood")):
            m = re.findall(r"\d+", get("hood"))
            if len(m) >= 2:
                a_, b_ = int(m[0]), int(m[1]); size = (min(a_, b_), max(a_, b_))
        if size:
            q, t = _num_cell(get("qty")), _num_cell(get("t"))
            if q is None or t is None or q != int(q) or q < 1 or t <= 0:
                raise VentNestingError("ведомость: зонт %dx%d — не разобрать толщину или количество" % size)
            cur = {"W": size[0], "L": size[1], "color": str(get("color") or ""), "t": t, "qty": int(q), "parts": 0}
            out.append(cur)
        if cur is not None and "pph" in col:
            h = _num_cell(get("pph"))
            if h is not None:
                cur["parts"] += int(h)
    if not out:
        raise VentNestingError("в сборочной ведомости не найдено ни одного зонта")
    return out


def order_from_zip(zip_bytes, qty=None):
    """«Скачать всё» заказа: DXF генератора из корня архива + *_сборка.xlsx. qty (по имени DXF или «ШxД»)
    перекрывает ведомость; без ведомости qty обязателен."""
    try:
        z = zipfile.ZipFile(io.BytesIO(bytes(zip_bytes)))
        infos = z.infolist()
    except Exception as e:
        raise VentNestingError("архив заказа не читается: %s" % type(e).__name__)
    if len(infos) > MAX_ZIP_ENTRIES:
        raise VentNestingError("в архиве %d файлов — это не выгрузка заказа" % len(infos))
    dxf, xlsx, skipped = [], None, []
    for zi in infos:
        n = zi.filename.replace("\\", "/")
        b = n.split("/")[-1]
        if not b.lower().endswith((".dxf", ".xlsx")):
            continue
        if "/" in n:
            skipped.append(n); continue
        if b.lower().endswith(".dxf"):
            if N.material_of(b):
                dxf.append((b, _read_member(z, zi, MAX_DXF_BYTES, b)))
            else:
                skipped.append(b)
        elif b.endswith("_сборка.xlsx"):
            xlsx = _read_member(z, zi, MAX_XLSX_BYTES, b)
    if not dxf:
        raise VentNestingError("в архиве нет DXF зонтов в корне" + ((" (пропущены: %s)" % ", ".join(skipped[:5])) if skipped else ""))
    pph = {}
    if qty is None:
        if xlsx is None:
            raise VentNestingError("в архиве нет *_сборка.xlsx — передайте количество зонтов (qty)")
        rows = assembly_rows(xlsx)
        names = {(W, L, round(t, 3), color_key(c)): n for n, _ in dxf for (W, L, t, c) in [N.material_of(n)]}
        qty = {}
        for r in rows:
            k = (r["W"], r["L"], round(r["t"], 3), color_key(r["color"]))
            if k not in names:
                raise VentNestingError("в ведомости зонт %dx%d %s %g мм, а DXF для него в архиве нет" % (r["W"], r["L"], r["color"], r["t"]))
            qty[names[k]] = qty.get(names[k], 0) + r["qty"]
            if r["parts"]:
                if names[k] in pph and pph[names[k]] != r["parts"]:
                    raise VentNestingError("ведомость: у %s разное «Деталей на зонт» в двух строках" % names[k])
                pph[names[k]] = r["parts"]
        for n, _ in dxf:
            if n not in qty:
                raise VentNestingError("%s есть в архиве, но его нет в сборочной ведомости" % n)
    return Order(dxf, qty, pph)


def order_from_dxf(files, qty):
    return Order(files, qty)


# ------------------------------------------------------------------ параметры
def _params(gap, edge, sves):
    gap = DEFAULT_GAP if gap is None else _num(gap, "зазор между деталями, мм")
    edge = DEFAULT_EDGE if edge is None else _num(edge, "отступ от края листа, мм")
    if sves is not None:
        sves = _num(sves, "свес торцов, мм")
        if not (V.SVES_MIN <= sves <= V.SVES):
            raise VentNestingError("свес торцов %.4g мм: допустимо %g…%g" % (sves, V.SVES_MIN, V.SVES))
        if sves == V.SVES:
            sves = None
    try:
        N.set_spacing(gap, edge)
    except ValueError as e:
        raise VentNestingError(str(e))
    return gap, edge, sves


def _by_material(items):
    bymat = collections.OrderedDict()
    for it in items:
        bymat.setdefault(it["material"], []).append(it)
    return bymat


def _mat_key(color, t):
    return "%s|%g" % (color_key(color), t)


def _summary(x):
    return {"sheets": x["n_sheets"], "lengths_mm": [int(L) for L in x["_lens"]], "lengths": N.group_lengths(x["_lens"]),
            "length_m": x["length_m"], "m2": x["m2"], "kg": x["kg"], "util_pct": x["util_pct"],
            "check_errors": sum(len(sh["check"]["errors"]) for sh in x["sheets"]),
            "gap_min_mm": min((sh["check"]["gap_min_mm"] for sh in x["sheets"] if sh["check"]["gap_min_mm"] is not None), default=None),
            "sheet_parts": [[list(p) for p in sh["parts"]] for sh in x["sheets"]],
            "placements": [[[it["hood"], it["role"], r, round(ox, 1), round(oy, 1)] for it, r, ox, oy in s.placed] for s in x["_sheets"]]}


def _run_variants(its, which=("stock", "coil")):
    """Варианты раскроя материала по отдельности: если деталь не лезет на склад 2500 (тело 2500 мм у 500x2200),
    вариант склада получает ошибку, а бухта считается. Оба не вышли — ошибка."""
    res, errs = {}, {}
    for w in which:
        try:
            res[w] = N.scenarios(its, (w,))
        except ValueError as e:
            errs[w] = str(e)
    if not res:
        raise VentNestingError("; ".join("%s: %s" % ("склад" if k == "stock" else "бухта", v) for k, v in errs.items()))
    base = next(iter(res.values()))
    sc = {k: v for k, v in base.items() if k not in ("stock", "coil", "saving")}
    sc["stock"] = res["stock"]["stock"] if "stock" in res else None
    sc["coil"] = res["coil"]["coil"] if "coil" in res else None
    st, co = sc["stock"], sc["coil"]
    sc["saving"] = ({"m": round(st["length_m"] - co["length_m"], 2), "m2": round(st["m2"] - co["m2"], 3),
                     "kg": round(st["kg"] - co["kg"], 1) if st["kg"] is not None else None,
                     "pct": round(100 * (st["m2"] - co["m2"]) / st["m2"], 1)} if st and co else None)
    return sc, errs


def _check_order(order):
    if not isinstance(order, Order):
        raise VentNestingError("нужен заказ из order_from_zip / order_from_dxf")


def plan(order, gap=DEFAULT_GAP, edge=DEFAULT_EDGE, sves=None, png=True, sheet_dxf=False):
    """Варианты раскроя по материалам: склад 2500 и бухта (длины кратно 50 до 3000).
    Возврат: {gap_mm, edge_mm, sves, hoods, materials: [{key, color, thickness, items, stock, coil, saving, recommend}],
              png: байты картинки (если png=True), dxf: {имя_листа.dxf: текст} (если sheet_dxf)}.
    Вариант, который невозможен (деталь длиннее листа 2500), — {"error": текст}; recommend тогда — другой."""
    _check_order(order)
    with _LOCK:
        gap, edge, sves = _params(gap, edge, sves)
        items = order.items(sves)
        mats, res, dxf = [], [], {}
        for mat, its in _by_material(items).items():
            sc, errs = _run_variants(its); res.append(sc)
            st = _summary(sc["stock"]) if sc["stock"] else {"error": errs.get("stock")}
            co = _summary(sc["coil"]) if sc["coil"] else {"error": errs.get("coil")}
            if "error" in st or "error" in co:
                better = "error" in st
            else:
                better = (co["kg"] < st["kg"]) if (co["kg"] is not None and st["kg"] is not None) else (co["m2"] < st["m2"])
            mats.append({"key": _mat_key(sc["color"], sc["thickness"]), "color": sc["color"], "thickness": sc["thickness"],
                         "items": len(its), "stock": st, "coil": co, "saving": sc["saving"], "recommend": "coil" if better else "stock"})
            if sheet_dxf:
                mtag = "%s_%s%s%s" % (sc["color"].replace(" ", ""), sc["thickness"], "" if sves is None else "_свес%g" % sves, N.spacing_tag())
                for key in ("stock", "coil"):
                    if not sc[key]:
                        continue
                    for i, (s_, L) in enumerate(zip(sc[key]["_sheets"], sc[key]["_lens"]), 1):
                        dxf["%s_%s_лист%d_%dx%d.dxf" % (mtag, "склад" if key == "stock" else "бухта", i, int(L), int(N.SHEET_W))] = N.sheet_dxf(s_)
        img = None
        if png:
            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "plan.png")
                N.render(res, "Раскрой: склад 2500 или бухта" + ("" if sves is None else ", свес %g мм (по решению инженера)" % sves), p)
                img = open(p, "rb").read()
        return {"gap_mm": N.GAP, "edge_mm": N.EDGE, "sves": sves or V.SVES, "hoods": order.hoods(), "materials": mats,
                "png": img, "dxf": dxf if sheet_dxf else None}


def sves_table(order, gap=DEFAULT_GAP, edge=DEFAULT_EDGE, sves_list=SVES_LIST):
    """Перебор свеса торцов × склад/бухта (по запросу инженера; время ≈ plan × число свесов).
    Возврат: [{sves, key, color, thickness, source: stock|coil, sheets, lengths, kg, util_pct}]; если свес или вариант
    невозможен — строка {sves, …, error: текст} (таблица не теряется из-за одного свеса)."""
    _check_order(order)
    try:
        sl = [float(x) for x in sves_list]
    except (TypeError, ValueError):
        raise VentNestingError("список свесов: нужна последовательность чисел")
    if not sl:
        raise VentNestingError("список свесов пуст")
    rows = []
    for s_ in sl:
        try:
            p = plan(order, gap, edge, sves=s_, png=False)
        except VentNestingError as e:
            if "свес торцов" in str(e) and "допустимо" in str(e):
                raise
            rows.append({"sves": s_, "error": str(e)}); continue
        for m in p["materials"]:
            for key in ("stock", "coil"):
                x = m[key]
                row = {"sves": p["sves"], "key": m["key"], "color": m["color"], "thickness": m["thickness"], "source": key}
                if "error" in x:
                    row["error"] = x["error"]
                else:
                    row.update({"sheets": x["sheets"], "lengths": x["lengths"], "kg": x["kg"], "util_pct": x["util_pct"]})
                rows.append(row)
    return rows


def _safe_name(name):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name or "заказ")).replace("..", "_").strip(" .") or "заказ"
    b = s.encode("utf-8")[:120]
    return b.decode("utf-8", "ignore")


def build_lxds(order, source, gap=DEFAULT_GAP, edge=DEFAULT_EDGE, sves=None, material=None, name="заказ"):
    """Программы CypCut для ВЫБРАННОГО варианта: по одной на материал. source: 'stock' (склад) | 'coil' (бухта).
    material — ключ материала из plan()['materials'][i]['key'] или точное название цвета; None — все материалы.
    Возврат: [{filename, bytes, ok, checks: [(проверка, ok, подробно)], layouts: [{no, length_mm, sheets, sheet_nos}], key}].
    ok=True — программа цела, соответствует раскрою И заказу (детали по каждому зонту = зонтов × деталей на зонт).
    Файл с ok=False выдавать нельзя — это ошибка сборки (в журнал + разработчику)."""
    _check_order(order)
    if source not in ("stock", "coil"):
        raise VentNestingError("вариант раскроя: 'stock' (склад) или 'coil' (бухта), получено %r" % (source,))
    name = _safe_name(name)
    out = []
    with _LOCK:
        gap, edge, sves = _params(gap, edge, sves)
        items = order.items(sves)
        for mat, its in _by_material(items).items():
            t, col = mat
            key = _mat_key(col, t)
            if material is not None:
                m_ = str(material).strip().lower()
                if ("|" in m_ and m_ != key) or ("|" not in m_ and color_key(m_) != color_key(col)):
                    continue
            sc, errs = _run_variants(its, (source,))
            model = LM.build(sc, N.rot_pt, N.rotated, source, "" if sves is None else " с%g" % sves)
            tag = "%s_%s_%s%s%s" % (sc["color"].replace(" ", ""), sc["thickness"], "склад" if source == "stock" else "бухта",
                                    "" if sves is None else "_свес%g" % sves, N.spacing_tag())
            fname = "%s_%s.lxds" % (name, tag)
            raw, M = LW.to_lxds(model, name)
            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "prog.lxds"); open(p, "wb").write(raw)
                checks, _ = LW.verify(raw, model, p, order.expected_per_hood(col, t, sves))
            out.append({"filename": fname, "key": key, "bytes": raw, "checks": checks,
                        "ok": bool(checks) and all(ok for _, ok, _ in checks),
                        "layouts": [{"no": k, "length_mm": int(x["size"][1]), "sheets": x["amount"], "sheet_nos": x["sheet_nos"]}
                                    for k, x in enumerate(model["results"], 1)]})
    if not out:
        raise VentNestingError("нет материала %r в заказе (ключи: %s)" % (material, ", ".join(_mat_key(c, t) for t, c in _by_material(items))))
    return out
