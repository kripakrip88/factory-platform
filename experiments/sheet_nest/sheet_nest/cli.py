# -*- coding: utf-8 -*-
"""Командная строка: детали (DXF и/или программы CypCut) → раскрой на листы → программа CypCut.

    python3 -m sheet_nest.cli ВХОД... [--sheet 1250x2500] [--gap 2] [--edge 2] [--thickness 1.5] [--qty ИМЯ=N] [--out DIR] [--name ИМЯ]

ВХОД — .dxf (одна или несколько деталей; гравировка — слой «ГРАВИРОВКА»; количество — из имени «…_12шт.dxf»
или --qty) и/или .lxds (детали с количеством из программы; раскладки в ней не важны).
В DIR: <имя>_<дата>.lxds (одна программа на все листы), картинка раскладок .png, отчёт .json.
"""
import sys, os, json, argparse, datetime, collections
from . import geom as G


def load_parts(inputs, qty_over=None, engrave_layers=None):
    parts, technical, warns = [], None, []
    for path in inputs:
        data = open(path, "rb").read()
        name = os.path.basename(path)
        if name.lower().endswith(".lxds"):
            from .read_lxds import parts_from_lxds
            ps, info = parts_from_lxds(data, name)
            technical = technical or info["technical"]
            warns += info["warnings"]
        elif name.lower().endswith(".dxf"):
            from .read_dxf import parts_from_dxf
            ps = parts_from_dxf(data, name, None, engrave_layers)
        else:
            raise ValueError("%s: нужен .dxf или .lxds" % name)
        parts += ps
    # имена — уникальные (по ним в программе считаются количества)
    seen = collections.Counter()
    for p in parts:
        seen[p["name"]] += 1
        if seen[p["name"]] > 1:
            p["name"] = "%s (%d)" % (p["name"], seen[p["name"]])
    for k, v in (qty_over or {}).items():
        hit = [p for p in parts if p["name"] == k or os.path.splitext(p["src"])[0] == k]
        if not hit:
            raise ValueError("--qty %s: нет такой детали (есть: %s)" % (k, ", ".join(p["name"] for p in parts)))
        for p in hit:
            p["qty"] = v
    for p in parts:
        warns += ["%s: %s" % (p["name"], w) for w in p.get("warnings", [])]
    return parts, technical, warns


def run(inputs, W=1250.0, L=2500.0, gap=2.0, edge=2.0, thickness=None, qty=None, title=None, out=None, methods=("rect", "raster"),
        engrave_layers=None, log=print):
    from .pack import plan
    from .route import route_sheet
    from .write_lxds import build
    from .verify import check
    from . import render
    parts, technical, warns = load_parts(inputs, qty, engrave_layers)
    for w in warns:
        log("  ⚠ " + w)
    log("деталей: %d видов, %d шт" % (len(parts), sum(p["qty"] for p in parts)))
    pl = plan(parts, W, L, gap, edge, methods)
    for t in pl["tried"]:
        log("  раскрой %-40s %s" % (t["method"], ("%d листов, %d раскладок" % (t["sheets"], t["layouts"])) if "sheets" in t
                                    else ("пропущен: " + t["skipped"]) if "skipped" in t else t.get("error")))
    log("раскрой: %s — %d листов %g×%g (нижняя граница %d %s%s)" % (pl["method"], pl["sheets"], W, L, pl["lower_bound"],
                                                                     pl["bound_kind"], ", минимум" if pl["optimal"] else ""))
    route_warn, x_tongue, x_parts = [], 0, 0
    for l in pl["layouts"]:
        r = route_sheet(l["placed"], parts, l["W"], l["L"])
        l["seq"], l["idle"] = r["seq"], r["idle"]
        x_tongue += r["crossings"] * l["amount"]; x_parts += r["crossings_parts"] * l["amount"]
        route_warn += r["warnings"]
    idle = sum(l["idle"] * l["amount"] for l in pl["layouts"])
    log("порядок резки: холостой ход %.1f м; переходов над вырезанными язычками %d, над вырезанными деталями %d" % (idle / 1000, x_tongue, x_parts))
    for w in sorted(set(route_warn)):
        log("  ⚠ " + w)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=10))).strftime("%Y-%m-%d_%H%M")
    title = title or os.path.splitext(os.path.basename(inputs[0]))[0]
    tag = "" if (gap, edge) == (2.0, 2.0) else "_зазор%g_край%g" % (gap, edge)
    fname = "%s_лист%gx%g%s_%s" % (title, W, L, tag, stamp)
    raw, M = build(parts, pl["layouts"], fname, technical)
    rep, rr, ctx = check(raw, parts, pl["layouts"], gap, edge, thickness)
    ok = all(x[1] is not False for x in rep)
    for n, o, d in rep:
        log("  %s %-62s %s" % ("✓" if o else "⚠" if o is None else "✗", n, d))
    res = dict(file=fname + ".lxds", ok=ok, sheets=pl["sheets"], lower_bound=pl["lower_bound"], optimal=pl["optimal"],
               method=pl["method"], tried=pl["tried"], idle_m=round(idle / 1000, 2), crossings=dict(tongues=x_tongue, parts=x_parts),
               layouts=[dict(index=k + 1, amount=l["amount"], parts=dict(collections.Counter(parts[q["part"]]["name"] for q in l["placed"])),
                             idle_m=round(l["idle"] / 1000, 3)) for k, l in enumerate(pl["layouts"])],
               totals={k: v for k, v in rr["totals"].items()}, checks=[(n, o, d) for n, o, d in rep], warnings=warns + route_warn)
    if out:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, fname + ".lxds"), "wb").write(raw)
        json.dump(res, open(os.path.join(out, fname + ".json"), "w"), ensure_ascii=False, indent=1)
        try:
            render.png(ctx, os.path.join(out, fname + ".png"), "%s — %d листов %g×%g, холостой ход %.0f м" % (title, pl["sheets"], W, L, idle / 1000))
        except ImportError:
            pass
        log("→ %s" % os.path.join(out, fname + ".lxds"))
    return res, raw, pl, parts


def main(argv=None):
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
    a = ap.parse_args(argv)
    try:
        W, L = (float(x) for x in a.sheet.lower().replace("х", "x").split("x"))
    except ValueError:
        sys.exit("ошибка: --sheet ШxД, например 1250x2500")
    qty = {}
    for q in a.qty:
        k, _, v = q.rpartition("=")
        qty[k] = int(v)
    methods = ("rect", "raster") if a.method == "auto" else (a.method,)
    try:
        res, *_ = run(a.inputs, W, L, a.gap, a.edge, a.thickness, qty, a.name, a.out or os.getcwd(), methods)
    except ValueError as e:
        sys.exit("ошибка: %s" % e)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
