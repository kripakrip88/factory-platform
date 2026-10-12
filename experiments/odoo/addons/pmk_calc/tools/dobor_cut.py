# -*- coding: utf-8 -*-
"""Раскрой доборных элементов на листы — гильотина (12.10.2026).

Решения Антона 12.10.2026:
  • доборки рубят на ГИЛЬОТИНЕ со стандартного листа 1250 × 2500 (зонты — на лазере,
    их раскрой отдельный, pmk_vent_nest; не смешиваем);
  • вариант «бухта»: лист рубят с рулона 1250 нужной длины — длина кратна 50 мм;
  • гильотина режет до 2500 мм, гибка — до 2500 мм: планка длиннее 2500 невозможна,
    лист с рулона — не длиннее 2500.

Раскрой — двухэтапный гильотинный (так режут на деле):
  1) лист рубится поперёк на ПОЛОСЫ-ЛЕНТЫ длиной L (рез 1250 мм);
  2) лента режется вдоль на заготовки шириной «развёртка» (рез L ≤ 2500 мм).
  Заготовка = развёртка × длина планки; в ленту идут заготовки её длины, а если места
  поперёк осталось — и короче (лишняя длина — отход). Ленты складываются в листы
  «первым подходящим» по убыванию длины, заготовки в ленты — так же по убыванию ширины.
Простая жадная раскладка: на типовых заказах (десятки позиций, сотни планок) даёт
листы без лишнего; оптимальность не обещаем — сравнение «склад / бухта» честное,
считается одним правилом.
"""
import math

SHEET_W = 1250.0          # ширина листа и рулона, мм
SHEET_L = 2500.0          # стандартный лист, мм
MAX_LEN = 2500.0          # гильотина и гибка — не длиннее, мм
COIL_STEP = 50.0          # лист с рулона — длина кратна 50 мм


class CutError(ValueError):
    """Ошибка заказа словами — показать как есть."""


def orient(dev, length):
    """Как положить заготовку «развёртка × длина» на лист: (поперёк, вдоль листа).

    Вдоль: лента длиной с планку, поперёк в ней полосы по развёртке (остаток ширины —
    отход). Поперёк (планка не длиннее ширины листа 1250): лента шириной в развёртку,
    в ней планки поперёк листа — планка 1250 рубится сразу полосой 1250 × развёртка, без
    второго реза и без отхода по ширине (Антон 12.10.2026: «почему 150 × 1250 не
    нарубить сразу с бухты полосками?»). Берётся положение с меньшим отходом на штуку.
    """
    along_waste = length * (SHEET_W % dev) / max(1, SHEET_W // dev)
    if length <= SHEET_W:
        across_waste = dev * (SHEET_W % length) / max(1, SHEET_W // length)
        if across_waste < along_waste - 1e-6:
            return length, dev
    return dev, length


def _bands(strips):
    """Заготовки → ленты. strips: [(поперёк, вдоль, метка, размер)]. Ленты: {L, used, items}."""
    bands = []
    for w, length, label, dims in sorted(strips, key=lambda s: (-s[1], -s[0])):
        # Сначала лента той же длины, потом самая короткая из более длинных.
        fit = [b for b in bands if b["L"] >= length and SHEET_W - b["used"] >= w - 1e-9]
        fit.sort(key=lambda b: (b["L"] - length, -b["used"]))
        if fit:
            band = fit[0]
        else:
            band = {"L": length, "used": 0.0, "items": []}
            bands.append(band)
        band["items"].append({"x": band["used"], "w": w, "l": length, "label": label, "dims": dims})
        band["used"] += w
    return bands


def _sheets(bands, cap):
    """Ленты → листы ёмкостью cap по длине (первый подходящий по убыванию длины)."""
    sheets = []
    for band in sorted(bands, key=lambda b: -b["L"]):
        target = next((s for s in sheets if cap - s["used"] >= band["L"] - 1e-9), None)
        if target is None:
            target = {"used": 0.0, "bands": []}
            sheets.append(target)
        target["bands"].append(dict(band, y=target["used"]))
        target["used"] += band["L"]
    return sheets


def _signature(sheet):
    return tuple((round(b["L"], 1), tuple((round(i["w"], 1), round(i["l"], 1), i["label"], i["dims"])
                                          for i in b["items"])) for b in sheet["bands"])


def group_lengths(lengths):
    """[2000, 2000, 1500] → «2000 × 2 + 1500»."""
    out, prev, n = [], None, 0
    for L in sorted(lengths, reverse=True) + [None]:
        if L == prev:
            n += 1
            continue
        if prev is not None:
            out.append("%d × %d" % (prev, n) if n > 1 else "%d" % prev)
        prev, n = L, 1
    return " + ".join(out)


def _variant(sheets, mass, coil):
    lengths = [math.ceil(s["used"] / COIL_STEP - 1e-9) * COIL_STEP if coil else SHEET_L for s in sheets]
    area_parts = sum(i["w"] * i["l"] for s in sheets for b in s["bands"] for i in b["items"]) / 1e6
    area = sum(SHEET_W * L for L in lengths) / 1e6
    # Одинаковые листы — одна карта «× N» (так их и рубят пачкой).
    maps, index = [], {}
    for s, L in zip(sheets, lengths):
        key = (_signature(s), L)
        if key in index:
            maps[index[key]]["count"] += 1
        else:
            index[key] = len(maps)
            maps.append({"length": L, "count": 1, "bands": s["bands"]})
    return {
        "sheets": len(sheets), "lengths_mm": lengths, "lengths": group_lengths(lengths),
        "length_m": round(sum(lengths) / 1000.0, 3), "m2": round(area, 3),
        "kg": round(area * mass, 1), "util_pct": round(100.0 * area_parts / area, 1) if area else 0.0,
        "maps": maps,
    }


def plan(strips, mass_per_m2):
    """Раскрой одного материала.

    strips: [(развёртка мм, длина планки мм, метка, количество)].
    Возврат: {"stock": вариант, "coil": вариант, "saving": {kg, pct}, "recommend"}.
    Вариант: sheets, lengths_mm, lengths («2000 × 3 + 1500»), length_m, m2, kg, util_pct,
    maps — карты раскроя (одинаковые листы — одна карта с count).
    """
    flat = []
    for w, length, label, qty in strips:
        if length > MAX_LEN + 1e-9:
            raise CutError("%s: длина планки %d мм — больше %d (гибка и гильотина до %d мм)."
                           % (label, length, MAX_LEN, MAX_LEN))
        if w > SHEET_W + 1e-9:
            raise CutError("%s: развёртка %g мм шире листа %d мм." % (label, w, SHEET_W))
        if w <= 0 or length <= 0 or qty <= 0:
            continue
        across, along = orient(float(w), float(length))
        flat.extend([(across, along, label, "%g×%g" % (w, length))] * int(qty))
    if not flat:
        return None
    bands = _bands(flat)
    stock = _variant(_sheets(bands, SHEET_L), mass_per_m2, coil=False)
    coil = _variant(_sheets(bands, MAX_LEN), mass_per_m2, coil=True)
    save = stock["kg"] - coil["kg"]
    return {"stock": stock, "coil": coil,
            "saving": {"kg": round(save, 1), "pct": round(100.0 * save / stock["kg"], 1) if stock["kg"] else 0.0},
            "recommend": "coil" if save > 0.05 else "stock"}


def sheet_svg(card, title="", bw=False, width=560.0):
    """Карта раскроя одного листа: лента — поперёк, заготовки — вдоль; подписи — номер
    позиции и размер. Лист рисуется лёжа (длина — по горизонтали), как его кладут."""
    L = card["length"]
    scale = width / max(L, 1.0)
    # bw — для чёрно-белой печати: без заливок, чёрный контур, отход — чёрной штриховкой.
    sheet_fill, part_fill, part_line, text_fill, hatch = (
        ("#ffffff", "#ffffff", "#000000", "#000000", "#000000") if bw else
        ("#f3f1ec", "#dfe9c4", "#5d6b2a", "#2b3312", "#c9c2b2"))
    fs = 13.0 if bw else 10.0
    W_px, H_px = L * scale, SHEET_W * scale
    pad_top = 22
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" width="100%%" '
             'class="pmk-cut-sheet">' % (W_px + 2, H_px + pad_top + 2)]
    head = title or ("%d × %d мм%s" % (SHEET_W, L, (" — листов: %d" % card["count"]) if card["count"] > 1 else ""))
    parts.append('<text x="1" y="14" font-size="12" font-weight="600" fill="%s">%s</text>'
                 % ("#000000" if bw else "currentColor", _esc(head)))
    parts.append('<rect x="1" y="%d" width="%.1f" height="%.1f" fill="%s" stroke="%s" '
                 'stroke-width="%s"/>' % (pad_top, W_px, H_px, sheet_fill, "#000000" if bw else "#8a857a",
                                          "1.6" if bw else "1"))
    for b in card["bands"]:
        x0 = 1 + b["y"] * scale
        for it in b["items"]:
            x, y = x0, pad_top + it["x"] * scale
            w, h = it["l"] * scale, it["w"] * scale
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" '
                         'stroke="%s" stroke-width="%s"/>' % (x, y, w, h, part_fill, part_line,
                                                              "1.2" if bw else "0.8"))
            # Заготовка короче ленты — остаток её длины в ленте тоже отход.
            if b["L"] - it["l"] > 0.5:
                parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="url(#h)" '
                             'stroke="none"/>' % (x + w, y, (b["L"] - it["l"]) * scale, h))
            if h >= 9:
                f = min(fs, h - 2)
                parts.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="%s">%s · %s</text>' % (
                    x + 3, y + min(h - 2, f + 1), f, text_fill, _esc(it["label"]), it["dims"]))
        # Отход ленты поперёк (ширина, оставшаяся после заготовок).
        if SHEET_W - b["used"] > 0.5:
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="url(#h)" '
                         'stroke="none"/>' % (x0, pad_top + b["used"] * scale, b["L"] * scale,
                                               (SHEET_W - b["used"]) * scale))
    parts.insert(1, '<defs><pattern id="h" width="6" height="6" patternUnits="userSpaceOnUse" '
                    'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="%s" '
                    'stroke-width="%s"/></pattern></defs>' % (hatch, "0.8" if bw else "2"))
    parts.append("</svg>")
    return "".join(parts)


def card_steps(card):
    """Порядок рубки карты словами — для печати у гильотины. Одинаковые ленты подряд —
    одной строкой «× N»; лента, которая сама и есть заготовка, — «сразу заготовка»."""
    rows = []
    for b in card["bands"]:
        if len(b["items"]) == 1 and b["used"] >= SHEET_W - 0.5 and b["items"][0]["l"] >= b["L"] - 0.5:
            it = b["items"][0]
            text = "Полоса %g мм поперёк листа — сразу заготовка %s (%s)" % (b["L"], it["label"], it["dims"])
        else:
            groups, order = {}, []
            for it in b["items"]:
                key = (it["label"], it["dims"], it["w"], it["l"])
                if key not in groups:
                    groups[key] = 0
                    order.append(key)
                groups[key] += 1
            parts = []
            for label, dims, w, l in order:
                n = groups[(label, dims, w, l)]
                parts.append("%s %g мм%s (%s)" % (label, w, " × %d" % n if n > 1 else "", dims))
            rest = SHEET_W - b["used"]
            text = "Лента %g мм поперёк листа, вдоль на: %s%s" % (
                b["L"], " + ".join(parts), "; отход %g мм" % rest if rest > 0.5 else "")
        if rows and rows[-1][0] == text:
            rows[-1][1] += 1
        else:
            rows.append([text, 1])
    steps = [t if n == 1 else "%s — %d %s" % (t, n, _times(n)) for t, n in rows]
    tail = card["length"] - sum(b["L"] for b in card["bands"])
    if tail > 0.5:
        steps.append("Остаток листа по длине — %g мм (отход)" % tail)
    return steps


def _times(n):
    return "раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "раз"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
