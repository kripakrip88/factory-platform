# -*- coding: utf-8 -*-
"""Прогон разборщика по настоящим названиям с сайтов поставщиков."""
import collections, json, sys
from match import Matcher

ref = json.load(open(sys.argv[1], encoding="utf-8"))
rows = json.load(open(sys.argv[2], encoding="utf-8"))
m = Matcher(ref)

stat = collections.Counter()
by_status = collections.defaultdict(list)
for r in rows:
    raw = (r.get("raw") or "").strip()
    if not raw:
        continue
    res = m.match(raw)
    stat[res["status"]] += 1
    by_status[res["status"]].append((raw, res.get("type"), res.get("nums")))

total = sum(stat.values())
print("@@ прогнано живых строк: %s" % total)
for st, n in stat.most_common():
    print("@@   %-26s %-4s (%.1f%%)" % (st, n, 100.0 * n / total))
print("@@ ── примеры отказов")
for st in ("вид не опознан", "размер не найден", "размера нет в справочнике", "неоднозначно"):
    items = by_status.get(st, [])
    if not items:
        continue
    print("@@ %s (%s):" % (st.upper(), len(items)))
    for raw, t, nums in items[:7]:
        print("@@    %-58s тип=%-28s числа=%s" % (raw[:58], t or "—", nums))
