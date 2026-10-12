# -*- coding: utf-8 -*-
"""Расшифровщик управляющих программ CypCut (.lxds) — копия ~/Downloads/lxds_report/lxds_report.py.

В пакете служит НЕЗАВИСИМОЙ проверкой каждой собранной программы (lxds_write.verify): читает её
своим кодом и сверяет с раскроем. Отдельная версия отчётного инструмента развивается в lxds_report.

    python3 -m vent_nesting.lxds_reader файл.lxds -t 0.65      # отчёт PNG + JSON рядом с файлом

Что считает по каждой раскладке и по программе целиком: листы, детали, загрузку (как CypCut и
по металлу), длину реза и гравировки, пробивки, холостой ход, подводы, отступ от края листа,
остаток листа и возможный деловой остаток (наибольшие свободные прямоугольники), массу.

Исходный файл только читается (zip в памяти). Отчёт пишется отдельными файлами *_отчёт.png/json.
Формат CypCut закрытый; расшифровано: Line, LwPolyline (с дугами), технологические слои, подводы.
Другие типы контуров (Arc, Text, Spline…) отчёт перечислит как «не разобрано» — пришлите такой файл.
"""
import sys, os, io, re, math, json, struct, zipfile, argparse, collections
import xml.etree.ElementTree as ET

RHO = 7.85e-6          # кг/мм³ (сталь)
CONT_TOL = 0.05        # мм: следующий контур продолжает предыдущий без отрыва


# ---------------------------------------------------------------- чтение двоичных данных
class Unsupported(Exception):
    pass


def _geo(buf, off, kind):
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
            if j < 0:
                raise Unsupported(kind)
            pts.append(struct.unpack_from("<2d", rec, j + 4)); j += 20
        return {"pts": pts, "bulge": [0.0, 0.0], "closed": False}
    if kind == "Circle":
        # метка точки, центр x, y, радиус, (4 служ.), угол точки старта, рад
        j = rec.find(b"\x10\x00\x02\x00", i)
        if j < 0:
            raise Unsupported(kind)
        cx, cy, r = struct.unpack_from("<3d", rec, j + 4)
        a0 = struct.unpack_from("<d", rec, j + 32)[0]
        if not (r > 0) or not math.isfinite(a0):
            raise Unsupported(kind)
        start = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        return {"pts": [start], "bulge": [0.0], "closed": True, "circle": (cx, cy, r, a0)}
    if kind == "LwPolyline":
        # флаг, n, затем n вершин по 32 байта: номер, x, y, bulge, служебные 4 байта
        for k in range(i + len(name), len(rec) - 12):
            n = struct.unpack_from("<I", rec, k + 4)[0]
            if 1 <= n <= 200000 and struct.unpack_from("<I", rec, k + 8)[0] == 1 and \
                    all(struct.unpack_from("<I", rec, k + 8 + 32 * q)[0] == q + 1 for q in range(min(n, 4))):
                flag = struct.unpack_from("<I", rec, k)[0]
                pts, bul = [], []
                for q in range(n):
                    x, y, b = struct.unpack_from("<3d", rec, k + 12 + 32 * q)
                    pts.append((x, y)); bul.append(b)
                return {"pts": pts, "bulge": bul, "closed": bool(flag & 1)}
    raise Unsupported(kind)


def _attrs(buf, off):
    """Технологический слой (1..16) и подвод из записи Shapes2D/data.bin."""
    size = struct.unpack_from("<I", buf, off + 8)[0]
    rec = buf[off:off + size]
    out = {"layer": None, "lead": False, "lead_start": None}
    i = rec.find(b"S\x00\x05\x00Shape")
    if i >= 0:
        out["layer"] = struct.unpack_from("<I", rec, i + 16)[0]
    i = rec.find(b"S\x00\x09\x00LeadParam")
    if i >= 0:
        out["lead"] = True
        out["lead_start"] = struct.unpack_from("<d", rec, i + 36)[0]
    return out


def points(sh, n_arc=16):
    """Точки контура для длины/отрисовки; дуги LwPolyline — по bulge."""
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
            if ch < 1e-9:
                continue
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


def elen(e):
    """длина контура точно: окружность — 2πR, дуга полилинии — R·угол (а не ломаная из points())"""
    if e.get("circle"):
        return 2 * math.pi * e["circle"][2]
    P, B = e["pts"], e["bulge"]
    if e["kind"] == "Line":
        return math.dist(P[0], P[1])
    t = 0.0
    for i in range(len(P) if e["closed"] else len(P) - 1):
        a, c = P[i], P[(i + 1) % len(P)]
        ch = math.dist(a, c)
        bu = B[i] if i < len(B) else 0.0
        if abs(bu) > 1e-9 and ch > 1e-9:
            th = abs(4 * math.atan(bu))
            t += ch / (2 * math.sin(th / 2)) * th
        else:
            t += ch
    return t


def earea(e):
    """площадь замкнутого контура: окружность — точно πR²"""
    return math.pi * e["circle"][2] ** 2 if e.get("circle") else parea(points(e))


def plen(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def parea(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


# ---------------------------------------------------------------- модель файла
class Program:
    """Разобранная программа CypCut. src — путь к .lxds, байты (вложение ERP) или файловый объект;
    name — имя для отчёта (по умолчанию имя файла)."""
    def __init__(self, src, name=None):
        if isinstance(src, (bytes, bytearray)):
            src = io.BytesIO(src)
        self.name = name or (os.path.basename(src) if isinstance(src, str) else "программа.lxds")
        z = zipfile.ZipFile(src)
        X = lambda n: ET.fromstring(z.read(n))
        inf = X("info.xml")
        app, sv = inf.find("Application"), inf.find("SavedBy")
        self.app = "%s %s" % (app.get("AppName", "?"), app.get("AppVer", "")) if app is not None else "?"
        self.saved = {k: sv.get(k) for k in ("User", "Computer", "SaveTime")} if sv is not None else {}
        geo, dat = z.read("Geometry2D/data.bin"), z.read("Shapes2D/data.bin")
        self.shapes, self.unknown = {}, collections.Counter()
        for el in X("Shapes2D/content.xml"):
            if el.tag == "MD5" or el.get("GeoAddr") is None:
                continue
            h, kind = el.get("Handle"), el.tag
            try:
                g = _geo(geo, int(el.get("GeoAddr")), kind)
            except Unsupported:
                self.unknown[kind] += 1
                continue
            g.update(kind=kind, handle=h, **_attrs(dat, int(el.get("DataAddr"))))
            self.shapes[h] = g
        self.blocks, self.nested_inserts = {}, 0
        for b in X("Blocks/content.xml"):
            hs = []
            for s in b.iter("Shape"):
                if s.get("Class") == "Insert":
                    self.nested_inserts += 1
                else:
                    hs.append(s.get("Handle"))
            self.blocks[b.get("Name")] = hs
        # листы: их может быть несколько разного размера (так пишет CypNest; CypCut такие файлы открывает)
        self.plates = {}
        for pl in X("Nest2D/Plates/content.xml").findall("NestPlate"):
            pts = [(float(p.get("X", 0)), float(p.get("Y", 0))) for p in pl.iter("Point")]
            self.plates[pl.get("Handle")] = {"name": pl.get("Name"), "amount": int(pl.get("Amount", 0)),
                                             "x0": min(p[0] for p in pts), "x1": max(p[0] for p in pts),
                                             "y0": min(p[1] for p in pts), "y1": max(p[1] for p in pts)}
        self.plate = next(iter(self.plates.values()))
        # детали
        self.parts = {}
        for p in X("Nest2D/Parts/content.xml").findall("NestPart"):
            ins = p.find("Insert")
            self.parts[p.get("Handle")] = {"name": p.get("Name"), "amount": int(p.get("Amount", 0)),
                                           "block": ins.findtext("BlockName") if ins is not None else None}
        self.groups = {}
        try:
            for g in X("Nest2D/Parts/Groups/content.xml").findall("NestGroup"):
                self.groups[g.get("Handle")] = [o.get("Handle") for o in g.findall("Object")]
        except KeyError:
            pass
        # раскладки
        self.layouts = []
        for r in X("Nest2D/Results/content.xml").findall("NestResult"):
            idx = r.get("Index")
            rc = X("Nest2D/Results/%s/content.xml" % idx)
            inserts, counts = [], collections.Counter()
            plate = None
            for s in rc.find("Shapes"):
                if s.get("NestPlate") and plate is None:
                    plate = self.plates.get(s.get("NestPlate"))
                if s.get("Class") != "Insert":
                    continue
                inserts.append(s.findtext("BlockName"))
                if s.get("NestGroup"):
                    for o in self.groups.get(s.get("NestGroup"), []):
                        counts[o] += 1
                elif s.get("NestPart"):
                    counts[s.get("NestPart")] += 1
            if plate is None and r.get("SizeX") and r.get("SizeY"):
                plate = {"name": "Size", "amount": 0, "x0": 0.0, "x1": float(r.get("SizeX")), "y0": 0.0, "y1": float(r.get("SizeY"))}
            self.layouts.append({"index": int(idx), "sheets": int(rc.get("PlateAmount", r.get("PlanCount", 1))),
                                 "util_cypcut": float(r.get("Utilization", 0)), "inserts": inserts, "counts": counts,
                                 "plate": plate or self.plate})


# ---------------------------------------------------------------- расчёт
def part_areas(prog, part_handle, engrave_layers):
    hs = [h for h in prog.blocks.get(prog.parts[part_handle]["block"], []) if h in prog.shapes]
    closed = [prog.shapes[h] for h in hs if prog.shapes[h]["closed"]]
    if not closed:
        return 0.0, 0.0
    outer = max(closed, key=earea)
    A = earea(outer)
    holes_cut = sum(earea(s) for s in closed if s is not outer and s["layer"] not in engrave_layers)
    holes_all = sum(earea(s) for s in closed if s is not outer)
    return A - holes_cut, A - holes_all        # металл детали; «как CypCut» (вычитает и замкнутую гравировку)


def remnants(plate, ents, res, margin, min_side, max_n=3):
    """Свободные прямоугольники листа: растр res мм, отступ margin мм от любых контуров,
    только область, связанная с краем листа (внутренности деталей и замкнутые карманы — не остаток)."""
    x0, y0 = plate["x0"], plate["y0"]
    W, L = plate["x1"] - x0, plate["y1"] - y0
    nx, ny = int(math.ceil(W / res)), int(math.ceil(L / res))
    blk = bytearray(nx * ny)
    for e in ents:
        P = points(e, 8)
        for i in range(len(P) - 1):
            (ax, ay), (bx, by) = P[i], P[i + 1]
            n = max(1, int(math.hypot(bx - ax, by - ay) / (res / 2)))
            for t in range(n + 1):
                cx = int((ax + (bx - ax) * t / n - x0) / res); cy = int((ay + (by - ay) * t / n - y0) / res)
                if 0 <= cx < nx and 0 <= cy < ny:
                    blk[cy * nx + cx] = 1
    r = int(math.ceil(margin / res))
    if r:
        rowd = bytearray(nx * ny)
        for y in range(ny):
            run = [0] * (nx + 1)
            for x in range(nx):
                run[x + 1] = run[x] + blk[y * nx + x]
            for x in range(nx):
                if run[min(nx, x + r + 1)] - run[max(0, x - r)]:
                    rowd[y * nx + x] = 1
        dil = bytearray(nx * ny)
        for x in range(nx):
            run = [0] * (ny + 1)
            for y in range(ny):
                run[y + 1] = run[y] + rowd[y * nx + x]
            for y in range(ny):
                if run[min(ny, y + r + 1)] - run[max(0, y - r)]:
                    dil[y * nx + x] = 1
        blk = dil
    free = bytearray(nx * ny)
    stack = [(x, y) for x in range(nx) for y in (0, ny - 1)] + [(x, y) for y in range(ny) for x in (0, nx - 1)]
    while stack:
        x, y = stack.pop()
        k = y * nx + x
        if 0 <= x < nx and 0 <= y < ny and not blk[k] and not free[k]:
            free[k] = 1
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    found = []
    for _ in range(max_n):
        best, h = None, [0] * nx
        for y in range(ny):
            for x in range(nx):
                h[x] = h[x] + 1 if free[y * nx + x] else 0
            st = []
            for x in range(nx + 1):
                cur = h[x] if x < nx else 0
                while st and h[st[-1]] >= cur:
                    top = st.pop(); left = st[-1] + 1 if st else 0
                    a = h[top] * (x - left)
                    if a and (best is None or a > best[0]):
                        best = (a, left, y - h[top] + 1, x - left, h[top])
                st.append(x)
        if not best:
            break
        _, cx, cy, cw, chh = best
        w_mm, l_mm = cw * res, chh * res
        if min(w_mm, l_mm) < min_side:
            break
        found.append({"x": x0 + cx * res, "y": y0 + cy * res, "w": w_mm, "l": l_mm})
        for yy in range(cy, cy + chh):
            for xx in range(cx, cx + cw):
                free[yy * nx + xx] = 0
    return found


def analyze(prog, engrave_layers, t, res, margin, min_side):
    areas = {h: part_areas(prog, h, engrave_layers) for h in prog.parts}
    out = []
    for lay in prog.layouts:
        pl = lay["plate"]                                   # у каждой раскладки свой лист
        sheet_area = (pl["x1"] - pl["x0"]) * (pl["y1"] - pl["y0"])
        ents = [prog.shapes[h] for b in lay["inserts"] for h in prog.blocks.get(b, []) if h in prog.shapes]
        cut = [e for e in ents if e["layer"] not in engrave_layers]
        eng = [e for e in ents if e["layer"] in engrave_layers]
        # длины, пробивки/включения, холостой ход — по порядку записей (у CypCut это порядок обработки)
        cut_len = sum(elen(e) for e in cut)
        eng_len = sum(elen(e) for e in eng)
        pierce = eng_on = 0; idle = 0.0; pos = (pl["x0"], pl["y0"]); prev_end = {}
        for e in ents:
            a = e["pts"][0]; b = e["pts"][0] if e["closed"] else e["pts"][-1]
            is_cut = e["layer"] not in engrave_layers
            cont = math.dist(pos, a) < CONT_TOL
            if not cont:
                if is_cut: pierce += 1
                else: eng_on += 1
            idle += math.dist(pos, a); pos = b
        allp = [p for e in ents for p in e["pts"]]
        outside = [p for p in allp if not (pl["x0"] - 1 <= p[0] <= pl["x1"] + 1 and pl["y0"] - 1 <= p[1] <= pl["y1"] + 1)]
        edge = min(min(p[0] - pl["x0"], pl["x1"] - p[0], p[1] - pl["y0"], pl["y1"] - p[1]) for p in allp) if allp else None
        parts = [{"name": prog.parts[h]["name"], "qty": n, "metal_m2": round(areas[h][0] * n / 1e6, 4)}
                 for h, n in sorted(lay["counts"].items(), key=lambda kv: -kv[1]) if h in prog.parts]
        metal = sum(areas[h][0] * n for h, n in lay["counts"].items() if h in areas)
        cyp = sum(areas[h][1] * n for h, n in lay["counts"].items() if h in areas)
        rem = remnants(pl, ents, res, margin, min_side) if min_side else []
        rem_area = sum(r["w"] * r["l"] for r in rem)
        d = {"index": lay["index"], "sheets": lay["sheets"], "plate_mm": [pl["x1"] - pl["x0"], pl["y1"] - pl["y0"]], "parts": parts,
             "util_cypcut": round(lay["util_cypcut"], 2), "util_calc_cypcut": round(100 * cyp / sheet_area, 2),
             "util_metal": round(100 * metal / sheet_area, 2), "leftover_pct": round(100 - 100 * metal / sheet_area, 2),
             "cut_m": round(cut_len / 1000, 2), "cut_contours": len(cut), "pierces": pierce,
             "engrave_m": round(eng_len / 1000, 2), "engrave_contours": len(eng), "engrave_starts": eng_on,
             "idle_m": round(idle / 1000, 1), "leads": sum(1 for e in cut if e["lead"]),
             "edge_min_mm": round(edge, 1) if edge is not None else None, "outside_points": len(outside),
             "remnants": [{k: round(v) for k, v in r.items()} for r in rem],
             "remnant_pct": round(100 * rem_area / sheet_area, 1),
             "scrap_pct": round(100 - 100 * metal / sheet_area - 100 * rem_area / sheet_area, 1)}
        if t:
            d["mass_sheet_kg"] = round(sheet_area * t * RHO, 1)
            d["mass_parts_kg"] = round(metal * t * RHO, 1)
            d["mass_remnant_kg"] = round(rem_area * t * RHO, 1)
            d["mass_scrap_kg"] = round(d["mass_sheet_kg"] - d["mass_parts_kg"] - d["mass_remnant_kg"], 1)
        d["_ents"] = ents; d["_rem"] = rem; d["_plate"] = pl
        out.append(d)
    return out


def thickness_guess(prog):
    for s in [prog.name] + [p["name"] or "" for p in prog.parts.values()]:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*мм", s)
        if m:
            return float(m.group(1).replace(",", ".")), "из имени «%s»" % s
    return None, None


# ---------------------------------------------------------------- вывод
def totals(lays):
    T = collections.Counter()
    for d in lays:
        n = d["sheets"]
        for k in ("cut_m", "engrave_m", "idle_m", "pierces", "engrave_starts", "mass_sheet_kg", "mass_parts_kg",
                  "mass_remnant_kg", "mass_scrap_kg"):
            if k in d:
                T[k] += d[k] * n
        T["sheets"] += n
    parts = collections.Counter()
    for d in lays:
        for p in d["parts"]:
            parts[p["name"]] += p["qty"] * d["sheets"]
    return T, parts


def warnings_for(prog, lays, t_src):
    w = []
    if prog.unknown:
        w.append("не разобраны контуры: %s — пришлите файл, допишу" % dict(prog.unknown))
    if prog.nested_inserts:
        w.append("вложенные вставки в блоках (%d) — их геометрия не учтена" % prog.nested_inserts)
    for d in lays:
        if d["outside_points"]:
            w.append("раскладка %d: %d точек вне листа — проверить вставки" % (d["index"], d["outside_points"]))
        if d["edge_min_mm"] is not None and d["edge_min_mm"] < 5:
            w.append("раскладка %d: детали в %.1f мм от края листа" % (d["index"], d["edge_min_mm"]))
        if abs(d["util_calc_cypcut"] - d["util_cypcut"]) > 0.05:
            w.append("раскладка %d: загрузка не сошлась с CypCut (%.2f против %.2f) — часть деталей не разобрана"
                     % (d["index"], d["util_calc_cypcut"], d["util_cypcut"]))
    if t_src is None:
        w.append("толщина не задана (ключ -t) — масса не посчитана")
    return w


def render_png(prog, lays, T, parts, warns, t, t_src, out, engrave_layers):
    from PIL import Image, ImageDraw, ImageFont
    def f(s, b=False):                     # шрифт с кириллицей: macOS Arial, Linux (контейнер Odoo) DejaVu
        for p in (("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if b else "/System/Library/Fonts/Supplemental/Arial.ttf"),
                  ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
            if os.path.exists(p):
                return ImageFont.truetype(p, s)
        return ImageFont.load_default()
    sizes = [(d["_plate"]["x1"] - d["_plate"]["x0"], d["_plate"]["y1"] - d["_plate"]["y0"]) for d in lays]
    W_mm, L_mm = max(w for w, l in sizes), max(l for w, l in sizes)     # масштаб по самому длинному листу
    IW = 1900; sc = (IW - 120) / L_mm
    Hs = int(W_mm * sc)
    sheet_txt = ("лист %.0f×%.0f" % sizes[0]) if len(set(sizes)) == 1 else "листы " + ", ".join("%.0f×%.0f" % wl for wl in sorted(set(sizes), key=lambda wl: -wl[1]))
    blockH = Hs + 175
    H = 150 + len(lays) * blockH + 330 + 26 * len(warns)
    img = Image.new("RGB", (IW, H), "white"); dr = ImageDraw.Draw(img)
    name = prog.name
    dr.text((60, 20), "Отчёт по УП лазера: %s" % name, fill=(0, 0, 0), font=f(30, True))
    dr.text((60, 62), "%s · сохранено %s %s (%s) · %s%s × %d шт" % (
        prog.app, prog.saved.get("SaveTime", "")[:16].replace("T", " "), prog.saved.get("User", ""),
        prog.saved.get("Computer", ""), sheet_txt, (" × %g мм" % t) if t else "", T["sheets"]), fill=(70, 70, 70), font=f(19))
    dr.text((60, 92), "Чёрный — рез, синий — гравировка (слой %s), зелёный — возможный деловой остаток" %
            ", ".join(map(str, sorted(engrave_layers))), fill=(70, 70, 70), font=f(19))
    y = 140
    for d in lays:
        pl = d["_plate"]
        dr.text((60, y), "Раскладка %d — %s · загрузка %.1f%% (CypCut), по металлу %.1f%% · остаток листа %.1f%%" % (
            d["index"], ("%d листа" if 2 <= d["sheets"] <= 4 else "%d лист" if d["sheets"] == 1 else "%d листов") % d["sheets"],
            d["util_cypcut"], d["util_metal"], d["leftover_pct"]) + ("" if len(set(sizes)) == 1 else " · лист %.0f×%.0f" % (pl["x1"] - pl["x0"], pl["y1"] - pl["y0"])),
            fill=(0, 0, 0), font=f(24, True))
        # подводы в отчёт не выводятся: их ставят операторы на станке (в JSON поле leads есть)
        dr.text((60, y + 34), "рез %.1f м · пробивок %d · гравировка %.1f м (включений %d) · холостой ход ≈ %.0f м · до края листа %.1f мм" % (
            d["cut_m"], d["pierces"], d["engrave_m"], d["engrave_starts"], d["idle_m"],
            d["edge_min_mm"] or 0), fill=(50, 50, 50), font=f(19))
        rem_txt = "; ".join("%d×%d мм (%.2f м²)" % (min(r["w"], r["l"]), max(r["w"], r["l"]), r["w"] * r["l"] / 1e6) for r in d["remnants"])
        dr.text((60, y + 60), "детали: %s · деловой остаток: %s · в отход %.1f%%" % (
            ", ".join("%s ×%d" % (p["name"], p["qty"]) for p in d["parts"]), (rem_txt + " (%.1f%% листа)" % d["remnant_pct"]) if rem_txt else "нет",
            d["scrap_pct"]), fill=(50, 50, 50), font=f(17))
        oy = y + 92
        Tm = lambda X, Y: (60 + (Y - pl["y0"]) * sc, oy + (pl["x1"] - X) * sc)
        dr.rectangle([Tm(pl["x0"], pl["y0"])[0], Tm(pl["x1"], pl["y0"])[1], Tm(pl["x0"], pl["y1"])[0], Tm(pl["x0"], pl["y0"])[1]],
                     outline=(150, 150, 150), width=2)
        for r in d["_rem"]:
            a = Tm(r["x"], r["y"]); b = Tm(r["x"] + r["w"], r["y"] + r["l"])
            box = [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]
            dr.rectangle(box, fill=(222, 245, 222), outline=(40, 150, 60), width=2)
            for k in range(int(box[0]) - int(box[3] - box[1]), int(box[2]), 14):
                dr.line([(max(box[0], k), box[3] - max(0, box[0] - k)), (min(box[2], k + box[3] - box[1]), box[1] + max(0, k + box[3] - box[1] - box[2]))],
                        fill=(170, 215, 170))
            txt = "%d×%d" % (min(r["w"], r["l"]), max(r["w"], r["l"]))
            tw = dr.textlength(txt, font=f(20, True))
            dr.text(((box[0] + box[2]) / 2 - tw / 2, (box[1] + box[3]) / 2 - 12), txt, fill=(20, 110, 40), font=f(20, True))
        for e in d["_ents"]:
            cut = e["layer"] not in engrave_layers
            dr.line([Tm(*p) for p in points(e, 10)], fill=(10, 10, 10) if cut else (40, 90, 230), width=2 if cut else 1)
        y += blockH
    # итог
    y += 4
    dr.line([(60, y), (IW - 60, y)], fill=(190, 190, 190)); y += 14
    dr.text((60, y), "ИТОГО ПО ПРОГРАММЕ (%d листов)" % T["sheets"], fill=(0, 0, 0), font=f(24, True)); y += 38
    rows = [("Детали", ", ".join("%s — %d шт" % kv for kv in parts.most_common())),
            ("Рез / пробивок", "%.1f м / %d" % (T["cut_m"], T["pierces"])),
            ("Гравировка / включений", "%.1f м / %d" % (T["engrave_m"], T["engrave_starts"])),
            ("Холостой ход (по порядку в файле)", "≈ %.0f м" % T["idle_m"])]
    if t:
        rows.append(("Металл, кг (лист %g мм)" % t, "листы %.0f · детали %.0f · деловой остаток %.0f · отход %.0f   (толщина %s)" % (
            T["mass_sheet_kg"], T["mass_parts_kg"], T["mass_remnant_kg"], T["mass_scrap_kg"], t_src or "")))
    for a, b in rows:
        dr.text((60, y), a, fill=(0, 0, 0), font=f(19, True)); dr.text((470, y), b, fill=(0, 0, 0), font=f(19)); y += 30
    for wmsg in warns:
        dr.text((60, y), "Внимание: " + wmsg, fill=(170, 110, 0), font=f(17)); y += 26
    img = img.crop((0, 0, IW, y + 20))
    img.save(out)


def build(src, name=None, thickness=None, engrave_layers=(2,), min_side=300, margin=10, res=5):
    """Главная функция для ERP: разобрать программу и вернуть отчёт (dict, сериализуется в JSON).
    min_side=None — не искать деловой остаток (логику остатков задаёт ERP).
    Второе значение — внутренности для render_png()."""
    prog = Program(src, name)
    eng = set(engrave_layers)
    t, t_src = (thickness, "задана") if thickness else thickness_guess(prog)
    lays = analyze(prog, eng, t, res, margin, min_side)
    T, parts = totals(lays)
    warns = warnings_for(prog, lays, t_src)
    rep = {"file": prog.name, "app": prog.app, "saved": prog.saved,
           "plate_mm": [prog.plate["x1"] - prog.plate["x0"], prog.plate["y1"] - prog.plate["y0"]],
           "plates_mm": sorted({tuple(d["plate_mm"]) for d in lays}, key=lambda wl: -wl[1]),
           "thickness_mm": t, "thickness_source": t_src, "engrave_layers": sorted(eng),
           "remnants_enabled": bool(min_side), "remnant_rule": {"min_side_mm": min_side, "margin_mm": margin} if min_side else None,
           "sheets": T["sheets"], "parts_total": dict(parts),
           "totals": {k: round(v, 1) for k, v in T.items()},
           "layouts": [{k: v for k, v in d.items() if not k.startswith("_")} for d in lays],
           "unparsed_shapes": dict(prog.unknown), "warnings": warns}
    return rep, {"prog": prog, "lays": lays, "T": T, "parts": parts, "warns": warns, "t": t, "t_src": t_src, "eng": eng}


def main():
    ap = argparse.ArgumentParser(description="Отчёт по УП лазера CypCut (.lxds)")
    ap.add_argument("file")
    ap.add_argument("-o", "--out", help="куда писать отчёт (без расширения); по умолчанию рядом с файлом")
    ap.add_argument("-t", "--thickness", type=float, help="толщина листа, мм (по умолчанию — из имени файла)")
    ap.add_argument("--engrave-layers", default="2", help="технологические слои гравировки, через запятую (по умолч. 2)")
    ap.add_argument("--min-side", type=float, default=300, help="мин. сторона делового остатка, мм (300); 0 — не искать")
    ap.add_argument("--margin", type=float, default=10, help="отступ остатка от контуров, мм (10)")
    ap.add_argument("--res", type=float, default=5, help="шаг сетки поиска остатка, мм (5)")
    a = ap.parse_intermixed_args()
    src = os.path.abspath(a.file)
    base = a.out or os.path.splitext(src)[0] + "_отчёт"
    png, js = os.path.abspath(base + ".png"), os.path.abspath(base + ".json")
    assert src not in (png, js), "отчёт не должен перезаписать исходный файл"
    os.makedirs(os.path.dirname(png), exist_ok=True)
    rep, c = build(src, None, a.thickness, [int(x) for x in a.engrave_layers.split(",") if x.strip()],
                   a.min_side or None, a.margin, a.res)
    json.dump(rep, open(js, "w"), ensure_ascii=False, indent=1)
    try:
        render_png(c["prog"], c["lays"], c["T"], c["parts"], c["warns"], c["t"], c["t_src"], png, c["eng"])
    except ImportError:
        png = None; print(" ⚠ нет Pillow — PNG не построен, только JSON")
    print("Отчёт: %s" % (png or js))
    for d in c["lays"]:
        print(" раскладка %d ×%d: загрузка %.1f%% (CypCut %.1f%%), рез %.1f м, пробивок %d, гравировка %.1f м, холостой ≈%.0f м, остаток листа %.1f%%, деловой: %s"
              % (d["index"], d["sheets"], d["util_metal"], d["util_cypcut"], d["cut_m"], d["pierces"], d["engrave_m"], d["idle_m"],
                 d["leftover_pct"], ", ".join("%d×%d" % (min(r["w"], r["l"]), max(r["w"], r["l"])) for r in d["remnants"]) or "нет"))
    for w in c["warns"]:
        print(" ⚠", w)


if __name__ == "__main__":
    main()
