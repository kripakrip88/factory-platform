# -*- coding: utf-8 -*-
"""Собрать справочник (reference.json) для match.py из данных модуля pmk_calc.

Справочник в репозитории лежит как CSV Odoo-модуля, а разборщику нужен JSON:
    python3 build_ref.py reference.json
Проверка: selftest.py на этом файле даёт 665 из 665.
"""
import csv, json, os, sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "odoo", "addons", "pmk_calc", "data")


def build():
    profiles, sheets = [], []
    with open(os.path.join(DATA, "pmk.metal.profile.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            profiles.append({"id": r["id"], "type": r["profile_type"],
                             "size": r["size_label"], "gost": r["gost"],
                             "mass": float(r["mass_per_meter"] or 0)})
    with open(os.path.join(DATA, "pmk.metal.sheet.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sheets.append({"id": r["id"], "type": r["sheet_type"],
                           "th": float(r["thickness_mm"]), "gost": r["gost"],
                           "mass": float(r["mass_per_sqm"] or 0)})
    return {"profiles": profiles, "sheets": sheets}


if __name__ == "__main__":
    ref = build()
    json.dump(ref, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
    print("profiles=%d sheets=%d" % (len(ref["profiles"]), len(ref["sheets"])))
