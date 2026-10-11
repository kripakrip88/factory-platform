# Чертёж заготовок зонта с размерами + спецификация материала (PNG).
# Запуск: python3 drawing.py 750 4000 out.png
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vent_hood as G
from PIL import Image, ImageDraw, ImageFont

FN = "/System/Library/Fonts/Supplemental/Arial.ttf"
FB = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
# Перенос в Odoo (11.10.2026) — единственная правка файла: на сервере нет
# шрифтов macOS, берём DejaVu Sans (есть в образе Odoo). Рисование не тронуто.
if not os.path.exists(FN):
    FN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
f = lambda s, b=False: ImageFont.truetype(FB if b else FN, s)
INK, DIM, HOLE7, HOLE45, SLOT = (20, 20, 20), (30, 90, 200), (200, 40, 40), (20, 140, 80), (40, 60, 210)



def part_local(p):
    xs = [x for x, _ in p["poly"]]; ys = [y for _, y in p["poly"]]
    x0, y0 = min(xs), min(ys)
    return x0, y0, max(xs) - x0, max(ys) - y0


class Canvas:
    def __init__(self, W, H):
        self.img = Image.new("RGB", (W, H), "white"); self.d = ImageDraw.Draw(self.img)

    def arrow(self, a, b):
        d = self.d; ang = math.atan2(b[1] - a[1], b[0] - a[0]); L = 11; w = 4
        for p, s in ((a, 1), (b, -1)):
            ux, uy = math.cos(ang) * s, math.sin(ang) * s
            d.polygon([p, (p[0] + ux * L - uy * w, p[1] + uy * L + ux * w), (p[0] + ux * L + uy * w, p[1] + uy * L - ux * w)], fill=DIM)
        d.line([a, b], fill=DIM, width=1)

    def hdim(self, x1, x2, y_edge, y_dim, text):
        d = self.d
        for x in (x1, x2):
            d.line([(x, y_edge), (x, y_dim + (6 if y_dim > y_edge else -6))], fill=DIM)
        self.arrow((x1, y_dim), (x2, y_dim))
        fn = f(17); tw = d.textlength(text, font=fn)
        d.text(((x1 + x2) / 2 - tw / 2, y_dim - 22), text, fill=DIM, font=fn)

    def vdim(self, y1, y2, x_edge, x_dim, text):
        d = self.d
        for y in (y1, y2):
            d.line([(x_edge, y), (x_dim + (6 if x_dim > x_edge else -6), y)], fill=DIM)
        self.arrow((x_dim, y1), (x_dim, y2))
        fn = f(17); tw = int(d.textlength(text, font=fn)) + 4
        t = Image.new("RGBA", (tw, 22), (255, 255, 255, 0)); ImageDraw.Draw(t).text((2, 0), text, fill=DIM, font=fn)
        t = t.rotate(90, expand=True)
        self.img.paste(t, (int(x_dim - 24), int((y1 + y2) / 2 - tw / 2)), t)


def draw_part(cv, p, ox, oy, sc, title, qty, extra=None):
    x0, y0, w, h = part_local(p)
    T = lambda x, y: (ox + (x - x0) * sc, oy + (h - (y - y0)) * sc)
    P = p["poly"]
    cv.d.line([T(*q) for q in P + [P[0]]], fill=INK, width=2)
    for x, y, dd in p["holes"]:
        cx, cy = T(x, y); r = max(2.2, dd / 2 * sc)
        cv.d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=HOLE7 if dd > 5 else HOLE45, width=2)
    for c, u in p["slots"]:
        for e in G.slot_entities(c, u):
            if e[0] == "L":
                cv.d.line([T(*e[1]), T(*e[2])], fill=SLOT, width=2)
            else:
                _, cc, r, a0, a1 = e
                pts = [T(cc[0] + r * math.cos(math.radians(a0 + (a1 - a0) * t / 8)), cc[1] + r * math.sin(math.radians(a0 + (a1 - a0) * t / 8))) for t in range(9)]
                cv.d.line(pts, fill=SLOT, width=2)
    L, Tp = T(x0, y0 + h), T(x0 + w, y0)    # левый-верх, правый-низ (экранные)
    cv.hdim(L[0], Tp[0], Tp[1], Tp[1] + 45, "%.1f" % w)
    cv.vdim(L[1], Tp[1], L[0], L[0] - 40, "%.1f" % h)
    cv.d.text((L[0], L[1] - 62), title, fill=INK, font=f(22, True))
    cv.d.text((L[0], L[1] - 34), "%d шт · заготовка %.1f × %.1f мм" % (qty, w, h), fill=INK, font=f(17))
    if extra:
        extra(cv, T, x0, y0, w, h)
    return T


def main(W, L, out, t=None, color=None):
    g = G.hood(W, L)
    s = G.spec(g, t, color)
    m = s["material"]
    parts = {}
    for kind, p in g["parts"]:
        parts.setdefault(kind, []).append(p)
    cap = parts["cap"][0]; end = parts["end"][0]; mid = parts.get("mid", [None])[0]
    names = {"cap": "Крышка торцевая", "end": "Тело зонта" if g["N"] == 1 else "Панель торцевая", "mid": "Панель средняя"}
    views = [("cap", cap, len(parts["cap"])), ("end", end, len(parts["end"]))] + ([("mid", mid, len(parts["mid"]))] if mid else [])
    sizes = [part_local(p) for _, p, _ in views]
    sc = min(1000.0 / max(h for *_, h in sizes), 2300.0 / (sum(w for _, _, w, _ in sizes) + 120 * len(views)))
    Wc = 2600; Hc = int(max(h for *_, h in sizes) * sc) + 1080
    cv = Canvas(Wc, Hc)
    cv.d.text((40, 24), "Зонт вентшахты %s — заготовки (размеры в мм)" % s["hood"], fill=INK, font=f(30, True))
    cv.d.text((40, 66), "Материал: %s, лист 1250 мм" % (m["full_name"] if m["t_mm"] else m["name"] + ", толщина не задана"),
              fill=INK, font=f(21, True))
    cv.d.text((40, 98), "Раскладка %s, панелей %d · отв. Ø7 — лапки (пара 40 мм), Ø4.5 — клёпки крышки, овал 9×4.5 — пазы тела"
              % (s["layout"], s["panels"]), fill=(80, 80, 80), font=f(18))
    x = 110; top = 190

    def end_extra(cv, T, x0, y0, w, h):
        # глубина V, первая лапка от торца, шаг лапок, фальц
        a = T(x0, y0 + h / 2); b = T(x0 + g["dV"], y0 + h / 2)
        cv.hdim(a[0], b[0], a[1], a[1] - 30, "V %.1f" % g["dV"])
        c1 = g["cols"][0]; c2 = g["cols"][1]
        p1 = T(x0 + c1, y0 + h); p2 = T(x0 + c2, y0 + h); p0 = T(x0, y0 + h)
        cv.hdim(p0[0], p1[0], p0[1], p0[1] - 0 + 95, "%.0f" % c1)
        if c2 < g["Pn"]:
            cv.hdim(p1[0], p2[0], p0[1], p0[1] + 95, "%.1f" % (c2 - c1))
        if g["N"] > 1:
            q = T(x0 + w, y0 + h - 42)
            cv.d.text((q[0] + 8, q[1] - 10), "фальц +14,\nвырез 42×14", fill=DIM, font=f(15))

    def mid_extra(cv, T, x0, y0, w, h):
        q = T(x0 + w, y0 + h / 2)
        cv.d.text((q[0] + 8, q[1] - 30), "V-вырез\nконька\n15×30", fill=DIM, font=f(15))

    for kind, p, q in views:
        _, _, w, h = part_local(p)
        draw_part(cv, p, x, top + 40, sc, names[kind], q,
                  end_extra if kind == "end" else (mid_extra if kind == "mid" else None))
        x += w * sc + 150

    # ---------- спецификация ----------
    along, rows = s["sheet_1250_m"] * 1000, s["sheet_layout"]
    gross, strip_m2 = s["metal_blanks_m2"], s["sheet_1250_m2"]
    y = top + 40 + int(max(h for *_, h in sizes) * sc) + 150
    cv.d.text((40, y), "СПЕЦИФИКАЦИЯ НА 1 ЗОНТ", fill=INK, font=f(24, True)); y += 42
    cols = [40, 110, 520, 860, 960, 1210]
    hdr = ["№", "Деталь", "Заготовка, мм", "Кол.", "Металл 1 шт, м²", "Металл всего, м²"]
    for cx, t in zip(cols, hdr):
        cv.d.text((cx, y), t, fill=(90, 90, 90), font=f(18, True))
    y += 30; cv.d.line([(40, y), (1500, y)], fill=(180, 180, 180)); y += 8
    for i, r in enumerate(s["parts"], 1):
        vals = [str(i), r["name"], "%.1f × %.1f" % tuple(r["size_mm"]), str(r["qty"]), "%.4f" % r["area_m2_each"], "%.3f" % (r["area_m2_each"] * r["qty"])]
        for cx, t in zip(cols, vals):
            cv.d.text((cx, y), t, fill=INK, font=f(19))
        y += 30
    cv.d.line([(40, y), (1500, y)], fill=(180, 180, 180)); y += 12
    lines = [
        ("Материал", m["full_name"] if m["t_mm"] else m["name"] + " (толщина не задана)"),
        ("Лапки крепления", "%d шт  (отверстий Ø7: %d)" % (s["lapki"], s["lapki_holes_d7"])),
        ("Клёпки", "%d шт  (Ø4.5 на крышках ↔ пазы на торцевых панелях)" % s["klepki"]),
        ("Металл нетто (детали за вычетом отверстий)", "%.3f м²" % s["metal_net_m2"]
         + ("  →  %.1f кг" % s["mass_net_kg"] if m["t_mm"] else "")),
        ("Металл по габаритам заготовок", "%.3f м²" % gross),
        ("Расход листа 1250 (простая раскладка, зазор 10)", "%.2f м погонных = %.2f м²" % (along / 1000, strip_m2)
         + ("  →  %.1f кг" % s["mass_sheet_kg"] if m["t_mm"] else "") + "  · использование %.0f%%" % (100 * s["metal_net_m2"] / strip_m2)),
    ]
    for a, b in lines:
        cv.d.text((40, y), a, fill=INK, font=f(19, True)); cv.d.text((560, y), b, fill=INK, font=f(19)); y += 30
    y += 6
    cv.d.text((40, y), "Раскладка: " + " | ".join("%s %d поперёк × %d вдоль" % (r["what"], r["across_mm"], r["along_mm"]) for r in rows),
              fill=(90, 90, 90), font=f(16))
    for wmsg in m["warnings"]:
        y += 26; cv.d.text((40, y), "Внимание: " + wmsg, fill=(170, 110, 0), font=f(16))
    if g["flags"]:
        y += 26; cv.d.text((40, y), "Внимание: шаг клёпок %.1f — по правилу (шаг ≤150): исходника ширины %d нет" % (g["p"], g["W"]), fill=(170, 110, 0), font=f(16))
    cv.img = cv.img.crop((0, 0, Wc, min(Hc, y + 50)))
    cv.img.save(out)
    return out, along, strip_m2, gross


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Чертёж заготовок вентзонта + спецификация (PNG)")
    ap.add_argument("W", type=int); ap.add_argument("L", type=int); ap.add_argument("out")
    ap.add_argument("-t", "--thickness", type=float, help="толщина листа, мм")
    ap.add_argument("-c", "--color", help="оцинковка (по умолчанию) или код RAL")
    a = ap.parse_intermixed_args()
    o, along, strip_m2, gross = main(a.W, a.L, a.out, a.thickness, a.color)
    print(o, "лента %.0f мм, %.2f м², габариты %.3f м²" % (along, strip_m2, gross))
