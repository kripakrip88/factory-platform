# -*- coding: utf-8 -*-
"""Проверка чертежей — где есть PyMuPDF (контейнер odoo-zk-worker), без Odoo:

    python3 tests/check_drawings.py [папка] [--all]

По умолчанию — каждое 25-е изделие эталона и все погонные; --all — все 786 изделий эталона.
Проверки (HANDOFF §6): PDF ровно 2 листа; ни одна горизонтальная/вертикальная линия
листа 1 не проходит через надпись в поле чертежа (x < 228 мм); текст техтребований — в рамке
(x ≤ 415 мм). Код выхода 1 — есть нарушения.
"""
import csv
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import catalog  # noqa: E402
import fitz  # noqa: E402

K = 72 / 25.4


def crossings(page):
    words = [w for w in page.get_text("words") if w[0] < 228 * K and w[1] > 8 * K]
    segs = [(it[1], it[2]) for d in page.get_drawings() for it in d["items"] if it[0] == "l"]
    bad = []
    for x0, y0, x1, y1, t, *_ in words:
        w, h = x1 - x0, y1 - y0
        if w * h < 4:
            continue
        for a, b in segs:
            hor, ver = abs(a.y - b.y) < 0.1, abs(a.x - b.x) < 0.1
            if (hor and y0 + h * 0.25 < a.y < y1 - h * 0.25 and min(a.x, b.x) < x0 + w * 0.4 and max(a.x, b.x) > x1 - w * 0.4) or \
               (ver and x0 + w * 0.25 < a.x < x1 - w * 0.25 and min(a.y, b.y) < y0 + h * 0.4 and max(a.y, b.y) > y1 - h * 0.4):
                bad.append(t)
                break
    return bad


def marks(all_):
    out = []
    for name in ("index_15.csv", "index_676.csv", "index_15_pogon.csv"):
        with open(os.path.join(HERE, "data", name), encoding="utf-8-sig") as f:
            rows = [r["Изделие"] for r in csv.DictReader(f, delimiter=";")]
            out += rows if all_ or "pogon" in name else rows[::25]
    return out


def main(folder, all_):
    g = catalog.gen()
    print("шрифт:", g.g.FONT)
    problems = []
    todo = marks(all_)
    for i, full in enumerate(todo, 1):
        m = re.match(r"(.+?)(?: L(\d+))?$", full)
        M, ms, why = catalog.model(catalog.series_of(m[1]), m[1], float(m[2] or 0))
        if not M:
            problems.append("%s: не построено — %s" % (full, why))
            continue
        pdf = os.path.join(folder, full + ".pdf")
        g.draw(M, ms, pdf)
        doc = fitz.open(pdf)
        if doc.page_count != 2:
            problems.append("%s: листов %d" % (full, doc.page_count))
        bad = crossings(doc[0])
        if bad:
            problems.append("%s: линия через надпись %s" % (full, bad[:5]))
        wide = [w[4] for w in doc[0].get_text("words") if w[0] > 230 * K and w[2] > 415 * K and w[1] < 234 * K]
        if wide:
            problems.append("%s: текст за рамкой %s" % (full, wide[:5]))
        if i % 100 == 0:
            print(i, "из", len(todo), flush=True)
    print("изделий:", len(todo), "нарушений:", len(problems))
    for p in problems:
        print("  ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    with tempfile.TemporaryDirectory() as tmp:
        sys.exit(main(args[0] if args else tmp, "--all" in sys.argv))
