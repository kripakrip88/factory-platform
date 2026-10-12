# -*- coding: utf-8 -*-
"""Командная строка поверх api (те же проверки, что у ERP).

    python3 -m vent_nesting.cli plan ВЗ-00002.zip [--gap 2 --edge 2] [--sves 145] [--out DIR]
        варианты склад/бухта: картинка, JSON и DXF каждого листа в DIR (по умолчанию ./out/<заказ>/)
    python3 -m vent_nesting.cli sves ВЗ-00002.zip [--sves 150 145 140]
        перебор свеса × склад/бухта (таблица + JSON)
    python3 -m vent_nesting.cli lxds ВЗ-00002.zip --source coil [--material ral8017|0.65] [--sves 145] [--out DIR]
        программы CypCut выбранного варианта

Количество: из *_сборка.xlsx в zip, иначе --qty ИМЯ_DXF=n или --qty ШxД=n (повторять). Вход — zip или DXF-файлы.
"""
import sys, os, json, argparse
from . import api


def _order(inputs, qty_args):
    qty = {}
    for q in qty_args:
        k, _, v = q.partition("=")
        try:
            qty[k.strip()] = int(v)
        except ValueError:
            raise api.VentNestingError("--qty %r: нужно ИМЯ=число" % q)
    if len(inputs) == 1 and inputs[0].lower().endswith(".zip"):
        return api.order_from_zip(open(inputs[0], "rb").read(), qty or None), os.path.splitext(os.path.basename(inputs[0]))[0]
    if any(i.lower().endswith(".zip") for i in inputs):
        raise api.VentNestingError("zip — только один и без других файлов")
    return api.order_from_dxf([(os.path.basename(p), open(p, "rb").read()) for p in inputs], qty), "заказ"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m vent_nesting.cli")
    ap.add_argument("action", choices=("plan", "sves", "lxds"))
    ap.add_argument("inputs", nargs="+", help="zip выгрузки заказа или DXF генератора")
    ap.add_argument("--qty", action="append", default=[], help="ИМЯ_DXF=n или ШxД=n (если нет ведомости)")
    ap.add_argument("--gap", type=float, default=api.DEFAULT_GAP, help="зазор между деталями, мм (2)")
    ap.add_argument("--edge", type=float, default=api.DEFAULT_EDGE, help="отступ от края листа, мм (2)")
    ap.add_argument("--sves", type=float, nargs="*", default=None, help="свес торцов 125…150 (lxds/plan — одно значение)")
    ap.add_argument("--source", choices=("stock", "coil"), help="для lxds: stock — склад 2500, coil — бухта")
    ap.add_argument("--material", default=None, help="для lxds: ключ материала из plan (например ral8017|0.65)")
    ap.add_argument("--out", default=None)
    a = ap.parse_intermixed_args(argv)
    try:
        order, name = _order(a.inputs, a.qty)
        if a.action in ("plan", "lxds") and a.sves and len(a.sves) > 1:
            raise api.VentNestingError("для %s — один свес (перебор нескольких — действие sves)" % a.action)
        if a.action == "lxds" and not a.source:
            raise api.VentNestingError("для lxds нужен --source stock|coil (сначала посмотрите plan)")
        api._params(a.gap, a.edge, a.sves[0] if a.sves else None)          # проверить параметры до создания папки
        outd = a.out or os.path.join(os.getcwd(), "out", name)
        one_sves = (a.sves[0] if a.sves else None)
        if a.action == "plan":
            p = api.plan(order, a.gap, a.edge, sves=one_sves, png=True, sheet_dxf=True)
            os.makedirs(outd, exist_ok=True)
            tag = "" if (a.gap, a.edge) == (2.0, 2.0) else "_зазор%g_край%g" % (a.gap, a.edge)
            tag += "" if one_sves in (None, 150) else "_свес%g" % one_sves
            open(os.path.join(outd, name + tag + "_раскрой.png"), "wb").write(p["png"])
            json.dump({k: v for k, v in p.items() if k not in ("png", "dxf")}, open(os.path.join(outd, name + tag + "_раскрой.json"), "w"),
                      ensure_ascii=False, indent=1)
            for fn, txt in p["dxf"].items():
                open(os.path.join(outd, fn), "w").write(txt)
            for m in p["materials"]:
                print("%s %g мм: деталей %d" % (m["color"], m["thickness"], m["items"]))
                for k, lab in (("stock", "склад 2500"), ("coil", "бухта")):
                    x = m[k]
                    if "error" in x:
                        print("   %-10s невозможно: %s" % (lab, x["error"])); continue
                    print("   %-10s %2d листов  %-40s %7.1f кг  загрузка %.0f%%" % (lab, x["sheets"], x["lengths"], x["kg"], x["util_pct"]))
                if m["saving"]:
                    print("   экономия бухты %.1f кг (%.0f%%)" % (m["saving"]["kg"], m["saving"]["pct"]))
                print("   совет: %s" % ("бухта" if m["recommend"] == "coil" else "склад"))
            print("→ %s" % outd)
        elif a.action == "sves":
            rows = api.sves_table(order, a.gap, a.edge, sves_list=tuple(a.sves) if a.sves else api.SVES_LIST)
            os.makedirs(outd, exist_ok=True)
            json.dump(rows, open(os.path.join(outd, name + "_варианты.json"), "w"), ensure_ascii=False, indent=1)
            for r in rows:
                if "error" in r:
                    print("свес %-4g %-14s %-6s невозможно: %s" % (r["sves"], r.get("key", ""), {"stock": "склад", "coil": "бухта"}.get(r.get("source"), ""), r["error"]))
                    continue
                print("свес %-4g %-14s %-6s %2d листов  %-40s %7.1f кг" % (r["sves"], r["key"], "склад" if r["source"] == "stock" else "бухта",
                                                                       r["sheets"], r["lengths"][:40], r["kg"]))
        else:
            files = api.build_lxds(order, a.source, a.gap, a.edge, sves=one_sves, material=a.material, name=name)
            os.makedirs(outd, exist_ok=True)
            bad = 0
            for f in files:
                p = os.path.join(outd, f["filename"]); open(p, "wb").write(f["bytes"])
                print("%s  %s" % ("✓" if f["ok"] else "✗ НЕ ВЫДАВАТЬ", p))
                print("   раскладки CypCut ← листы раскроя: %s" % "; ".join(
                    "№%d %d×1250%s ← %s" % (l["no"], l["length_mm"], (" ×%d" % l["sheets"]) if l["sheets"] > 1 else "",
                                            ",".join(map(str, l["sheet_nos"]))) for l in f["layouts"]))
                for nm, ok, det in f["checks"]:
                    print("   %s %-50s %s" % ("✓" if ok else "✗", nm, det))
                bad += not f["ok"]
            sys.exit(1 if bad else 0)
    except api.VentNestingError as e:
        sys.exit("ошибка: %s" % e)


if __name__ == "__main__":
    main()
