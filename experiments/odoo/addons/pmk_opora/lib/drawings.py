# -*- coding: utf-8 -*-
"""Чертежи опор — точка входа генератора в.2 (правила по чертежам И. Бутова, 27.10.2026).

    draw(kind, dn, exe, steel, out_dir) -> dict
        kind  — "kx" (exe "А12"), "kp" (exe "А12"), "opp1" (exe "100" или "70" — высота Н);
        dn    — Дн трубы по ОСТ (57, 219, 21.3 …);
        steel — марка стали для спецификации («Ст3пс»);
        out_dir — папка, куда лягут файлы (создаётся).
    Возвращает:
        pdf  — путь к PDF (А3, 1–2 листа);
        png  — пути PNG листов (110 dpi), лист 1 первым;
        dxf  — [{"file", "pos", "name", "thickness", "qty"}] — развёртки и детали для лазера (R12,
               слои CUT — рез, BEND — риски гибов, MARK — разметка), qty — штук на одну опору;
        dims — все размеры (ОСТ и выведенные правилами в.2);
        checks — {название: {"value", "ref", "ok"}} — сверки со вторым источником;
        assumptions — открытые вопросы (стоят и в ТТ чертежа);
        rules — "v2".
    Чего генератор не умеет — ValueError("пока нет: …").

Работает без Odoo: Python 3 + PyMuPDF (контейнер чертёжного процесса). Таблицы ОСТ — из
pmk_opora/tools по пути файла (_std.py), рисование — pmk_zakladnye/lib/gost_draw.py (_common.py).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rules_v2 as rv  # noqa: E402
from _std import ost146, ost94  # noqa: E402

SUPPORTED = {"kx": ("А12",), "kp": ("А12",), "opp1": ("100", "70")}


def _exe(kind, exe):
    e = str(exe or "").strip().upper().replace("A", "А")
    if kind == "opp1":
        e = e.split(".")[0]
    return e


def _dn(dn):
    v = float(str(dn).replace(",", "."))
    return int(v) if v == int(v) else v


def supported(kind, exe):
    return _exe(kind, exe) in SUPPORTED.get(kind, ())


def geometry(kind, dn, exe):
    """Размеры марки по правилам в.2 (без рисования): то, что уходит в dims и в чертёж."""
    kind = (kind or "").strip().lower()
    exe = _exe(kind, exe)
    dn = _dn(dn)
    if exe not in SUPPORTED.get(kind, ()):
        raise ValueError("пока нет: чертежи в.2 есть для КХ А12, КП А12 и ОПП1 (Н 100/70), а не %s %s"
                         % (kind, exe))
    if kind in ("kx", "kp"):
        err = ost146.check(kind, dn, exe)
        if err:
            raise ValueError("пока нет: %s" % err)
        body = ost146.body(kind, dn, exe)
        B, S, L = body["B"], body["S"], body["L"]
        if kind == "kx":
            h, _b1, bd, bl, _m = ost146.KX[(dn, exe)]
            m, cs, B1, M, d, dev_ost = ost146.CLAMP[dn]
            geo = rv.kx(dn, h, B, S, L, cs, m, B1, M, d, rv.CLAMP_F[dn], bd, bl,
                        bolt_kg=ost146.BOLT_KG[(bd, bl)], nut_kg=ost146.NUT_KG[bd])
            geo["clamp"]["dev_ost"] = dev_ost
        else:
            geo = rv.kp(dn, body["h"], body["h1"], B, S, L)
        geo.update(h1_ost=body["h1"], r_ost=body["r"], mass_ost=ost146.ost_mass(kind, dn, exe),
                   mark=ost146.designation(kind, dn, exe), standard=ost146.STANDARD)
    else:
        err = ost94.check(kind, dn, exe)
        if err:
            raise ValueError("пока нет: %s" % err)
        h100, h70, B, R = ost94.TABLE1[dn]
        H = int(exe)
        geo = rv.opp1(dn, H, h100 if H == 100 else h70, ost94.H2[H], B, R)
        geo.update(mass_ost=ost94.ost_mass(kind, dn, exe), mark=ost94.mark(kind, dn, exe),
                   standard=ost94.STANDARD)
    geo.update(exe=exe, assumptions=rv.assumptions(kind), rules=rv.RULES)
    return geo


def checks(geo):
    """Сверки: значение / второй источник / в порядке ли."""
    out = {}

    def add(name, value, ref, ok):
        out[name] = dict(value=value, ref=ref, ok=bool(ok))

    mass_ok = not geo["mass_ost"] or geo["mass"] <= geo["mass_ost"]
    add("масса по деталям / по ОСТ не более, кг", geo["mass"], geo["mass_ost"], mass_ok)
    if geo["kind"] == "kx":
        cl, rib = geo["clamp"], geo["rib"]
        add("стенка h1: правило в.2 / табл. 4 ОСТ", geo["h1"], geo["h1_ost"], True)
        add("ось трубы: h + Дн/2 / хомут на кромках стенок", round(geo["axis"], 2), round(geo["axis_contact"], 2),
            0 <= geo["axis"] - geo["axis_contact"] < 1.0)
        gap = round(geo["axis_contact"] - (geo["axis"] - rv.RIB_CLEARANCE), 2)
        add("ребро ниже хомута по оси, мм / задано", gap, rv.RIB_CLEARANCE, gap > 0)
        add("верх ребра у стенки / верх стенки", round(rib["edge_abs"], 2), geo["h1"], rib["edge_abs"] <= geo["h1"])
        stack = 2 * cl["S"] + 2 * cl["f"] + {12: 10, 16: 13, 20: 16, 24: 19}[geo["bolt"]["d"]]
        add("болт: лапки + зазор + гайка / длина", stack, geo["bolt"]["l"], stack <= geo["bolt"]["l"])
        add("отверстие на прямом участке лапки: край / начало гиба", round(cl["hole"] + cl["d"] / 2.0, 2),
            round(cl["flat"], 2), cl["hole"] + cl["d"] / 2.0 < cl["flat"])
        add("полухомут: развёртка в.2 / табл. 15 ОСТ", round(cl["total"], 3), cl["dev_ost"], True)
    elif geo["kind"] == "kp":
        rib = geo["rib"]
        add("стенка h1: принята / по касанию трубы", geo["h1"], geo["h1_contact"], abs(geo["h1"] - geo["h1_contact"]) <= 1)
        add("верх ребра у стенки / верх стенки", round(rib["edge_abs"], 2), geo["h1"], not rib["clipped"])
    else:
        rib = geo["rib"]
        add("ложе: хорда по верху / B стенки", round(geo["chord"], 2), geo["B"], geo["chord"] < geo["B"])
        add("ребро: верх / низ ложа", geo["H2"], geo["H"], geo["H2"] < geo["H"])
        add("ребро: длина + 2 зазора / L − 2S", rib["l"] + 2 * rib["gap"], geo["L"] - 2 * geo["S"],
            abs(rib["l"] + 2 * rib["gap"] - (geo["L"] - 2 * geo["S"])) < 1e-6)
    add("развёртка корпуса, мм", round(geo["corpus"]["total"], 3), None, geo["corpus"]["total"] > 0)
    return out


def _dims(geo):
    """dims — без служебных ключей, числа округлены до 0,001."""
    def clean(v):
        if isinstance(v, float):
            return round(v, 3)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        return v
    return clean({k: v for k, v in geo.items() if k not in ("assumptions",)})


def draw(kind, dn, exe, steel, out_dir):
    """Чертёж марки: PDF + PNG листов + DXF деталей в out_dir. См. описание модуля."""
    geo = geometry(kind, dn, exe)
    steel = steel or "Ст3пс"
    os.makedirs(out_dir, exist_ok=True)
    if geo["kind"] == "kx":
        import draw_kx_a12 as mod
    elif geo["kind"] == "kp":
        import draw_kp_a12 as mod
    else:
        import draw_opp1 as mod
    res = mod.draw(geo, steel, out_dir)
    return dict(pdf=res["pdf"], png=res["png"], dxf=res["dxf"], dims=_dims(geo), checks=checks(geo),
                assumptions=list(geo["assumptions"]), rules=rv.RULES)


def marks():
    """Все марки, которые умеет генератор: [(kind, dn, exe)]."""
    out = [("kx", dn, "А12") for dn in ost146.diameters("kx") if (dn, "А12") in ost146.KX]
    out += [("kp", dn, "А12") for dn in ost146.diameters("kp") if (dn, "А12") in ost146.KP]
    out += [("opp1", dn, h) for dn in ost94.diameters("opp1") for h in ("100", "70")]
    return out


if __name__ == "__main__":   # python3 drawings.py kx 219 А12 [сталь] [папка]
    import json
    a = sys.argv[1:]
    r = draw(a[0], a[1], a[2], a[3] if len(a) > 3 else "Ст3пс", a[4] if len(a) > 4 else os.path.join(os.getcwd(), "out"))
    print(json.dumps({k: r[k] for k in ("pdf", "png", "dxf", "checks", "assumptions")}, ensure_ascii=False, indent=1))
