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


def _bands(strips):
    """Заготовки → ленты. strips: [(ширина, длина, метка)]. Ленты: {L, used, items}."""
    bands = []
    for w, length, label in sorted(strips, key=lambda s: (-s[1], -s[0])):
        # Сначала лента той же длины, потом самая короткая из более длинных.
        fit = [b for b in bands if b["L"] >= length and SHEET_W - b["used"] >= w - 1e-9]
        fit.sort(key=lambda b: (b["L"] - length, -b["used"]))
        if fit:
            band = fit[0]
        else:
            band = {"L": length, "used": 0.0, "items": []}
            bands.append(band)
        band["items"].append({"x": band["used"], "w": w, "l": length, "label": label})
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
    return tuple((round(b["L"], 1), tuple((round(i["w"], 1), round(i["l"], 1), i["label"])
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
        flat.extend([(float(w), float(length), label)] * int(qty))
    if not flat:
        return None
    bands = _bands(flat)
    stock = _variant(_sheets(bands, SHEET_L), mass_per_m2, coil=False)
    coil = _variant(_sheets(bands, MAX_LEN), mass_per_m2, coil=True)
    save = stock["kg"] - coil["kg"]
    return {"stock": stock, "coil": coil,
            "saving": {"kg": round(save, 1), "pct": round(100.0 * save / stock["kg"], 1) if stock["kg"] else 0.0},
            "recommend": "coil" if save > 0.05 else "stock"}


def sheet_svg(card, title=""):
    """Карта раскроя одного листа: лента — поперёк, заготовки — вдоль; подписи — номер
    позиции и размер. Лист рисуется лёжа (длина — по горизонтали), как его кладут."""
    L = card["length"]
    scale = 560.0 / max(L, 1.0)
    W_px, H_px = L * scale, SHEET_W * scale
    pad_top = 22
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.1f %.1f" width="100%%" '
             'class="pmk-cut-sheet">' % (W_px + 2, H_px + pad_top + 2)]
    parts.append('<text x="1" y="14" font-size="12" font-weight="600" fill="currentColor">%s</text>'
                 % _esc(title or ("%d × %d мм%s" % (SHEET_W, L, (" — листов: %d" % card["count"])
                                                     if card["count"] > 1 else ""))))
    parts.append('<rect x="1" y="%d" width="%.1f" height="%.1f" fill="#f3f1ec" stroke="#8a857a" '
                 'stroke-width="1"/>' % (pad_top, W_px, H_px))
    for b in card["bands"]:
        x0 = 1 + b["y"] * scale
        for it in b["items"]:
            x, y = x0, pad_top + it["x"] * scale
            w, h = it["l"] * scale, it["w"] * scale
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#dfe9c4" '
                         'stroke="#5d6b2a" stroke-width="0.8"/>' % (x, y, w, h))
            # Заготовка короче ленты — остаток её длины в ленте тоже отход.
            if b["L"] - it["l"] > 0.5:
                parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="url(#h)" '
                             'stroke="none"/>' % (x + w, y, (b["L"] - it["l"]) * scale, h))
            if h >= 9:
                parts.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="#2b3312">%s · %g×%g</text>' % (
                    x + 3, y + min(h - 2, 11), min(10, h - 2), _esc(it["label"]), it["w"], it["l"]))
        # Отход ленты поперёк (ширина, оставшаяся после заготовок).
        if SHEET_W - b["used"] > 0.5:
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="url(#h)" '
                         'stroke="none"/>' % (x0, pad_top + b["used"] * scale, b["L"] * scale,
                                               (SHEET_W - b["used"]) * scale))
    parts.insert(1, '<defs><pattern id="h" width="6" height="6" patternUnits="userSpaceOnUse" '
                    'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#c9c2b2" '
                    'stroke-width="2"/></pattern></defs>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
