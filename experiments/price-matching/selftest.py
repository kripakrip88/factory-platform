# -*- coding: utf-8 -*-
"""Сплошная проверка: каждую позицию справочника прогоняем через разборщик
в том виде, в каком её написал бы поставщик, и смотрим, вернётся ли она сама.

Если разборщик не узнаёт нашу же номенклатуру, на чужих прайсах он тем более
не справится. Это нижняя планка, а не доказательство.
"""
import json, random, sys
from match import Matcher

ref = json.load(open(sys.argv[1], encoding="utf-8"))
m = Matcher(ref)

# Как поставщик написал бы позицию: несколько правдоподобных стилей.
STYLES = [
    lambda t, s: "%s %s" % (t, s),
    lambda t, s: "%s %s" % (t.lower(), s.replace("x", "х")),
    lambda t, s: "%s %s" % (t, s.replace("x", "*").replace(".", ",")),
    lambda t, s: "%s %s ГОСТ 8509-93" % (t, s),
    lambda t, s: "%s %s ст3сп" % (t, s.replace("x", " х ")),
]

stat = {"совпало": 0, "неоднозначно": 0, "промах": 0}
misses = []
random.seed(7)
for p in ref["profiles"]:
    if not p["size"]:
        continue
    style = random.choice(STYLES)
    line = style(p["type"], p["size"])
    r = m.match(line)
    ids = [x["id"] for x in r["matches"]]
    if r["status"] == "совпало" and ids == [p["id"]]:
        stat["совпало"] += 1
    elif p["id"] in ids:
        stat["неоднозначно"] += 1
    else:
        stat["промах"] += 1
        if len(misses) < 12:
            misses.append((line, r["status"], r["type"], [x["size"] for x in r["matches"]][:2]))

total = sum(stat.values())
print("@@ прогнано позиций: %s" % total)
for k, v in stat.items():
    print("@@   %-14s %-4s (%.1f%%)" % (k, v, 100.0 * v / total))
if misses:
    print("@@ ── промахи:")
    for line, st, t, got in misses:
        print("@@   %-44s -> %-26s %s %s" % (line[:44], st, t or "?", got))
