# -*- coding: utf-8 -*-
"""Метизы из разбора чата «Прайс листы поставщиков» (26.10.2026) → справочник и цены.

Вход: «Крепёж — цена за штуку.xlsx», лист «Список», строки с отметкой «Ходовая» (316
позиций, утверждены Антоном 26.10: «давай брать всё»). Выход:
  fasteners_rows.csv — строки pmk_calc/data/pmk.metal.fastener.csv (дописать);
  fasteners_prices.csv — цена за штуку: на позицию одна строка от поставщика (минимум ₽/шт
  среди его строк), с исходным названием, ценой и единицей прайса.

Решения Антона (26.10): классы 5.8/8.8/10.9 — отдельные позиции; покрытие не указано = без
покрытия (чёрный); масса — по таблицам ГОСТ (болт 7798, гайка 5915 — наибольшая); цены с НДС.
Не берём: строки без ₽/шт (единица неизвестна), «проверить … дешевле соседей», уценку,
мелкий шаг (масса по крупному), потайные DIN 7504 и DACROMET у саморезов.

    python3 build_fasteners.py "<путь к xlsx>" <папка вывода>
"""
import csv
import re
import sys
from collections import defaultdict

import openpyxl

DATES = {"МК-27": "2026-10-26", "Метиз Центр": "2026-10-22"}
COAT = {None: "black", "без покрытия": "black", "цинк": "zinc", "гор. цинк": "hot_zinc", "окраш.": "painted"}
COAT_WORD = {"black": "", "zinc": "цинк", "hot_zinc": "гор. цинк", "painted": "RAL"}
RAL_RE = re.compile(r"\bRAL\b|(?<![\d,.])(?:10|20|30|50|60|70|80|90)\d\d(?!\s*(?:шт|кг|\d))", re.I)
FINE_PITCH_RE = re.compile(r"\d\s*[хx]\s*1[,.]\d+\s*[хx]", re.I)
# Масса самореза — оценка (в прайсах нет; коробка Метиз Центра «19 кг ≈ 9846 шт» — 1,93 г).
SCREW_KG = {(4.2, 16): 0.0019, (4.8, 35): 0.0045, (5.5, 19): 0.004, (6.3, 280): 0.06}
LEGACY_ANCHOR = {(10, 100): "fast_anchor_m10_100", (12, 120): "fast_anchor_m12_120"}


def num(v):
    return ("%g" % float(v)) if v not in (None, "") else ""


def main(path, out):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb["Список"].iter_rows(values_only=True))
    H = rows[0]
    I = {h: i for i, h in enumerate(H)}
    pos, prices, skipped = {}, defaultdict(list), defaultdict(int)
    for r in rows[1:]:
        kind, sub, name = r[I["Вид"]] or "", r[I["Подвид"]] or "", r[I["Наименование (как в прайсе)"]] or ""
        # Антон 26.10 (вечер): «мало позиций, нет М6» — болты, гайки, шайбы — ВСЕ размеры прайсов;
        # анкеры, саморезы — пока только ходовые (в прайсах вперемешку разные изделия).
        if not r[I["Ходовая (предложение)"]] and not kind.startswith(("болт", "гайка", "шайба")):
            continue
        d, length, cls = r[I["Ø / М"]], r[I["Длина"]], r[I["Класс"]]
        ppc, check = r[I["₽/шт"]], r[I["Проверить"]] or ""
        low = name.lower()
        if not ppc:
            skipped["нет ₽/шт"] += 1
            continue
        if "дешевле" in check:
            skipped["проверить: дешевле соседей"] += 1
            continue
        if "уценк" in low:
            skipped["уценка"] += 1
            continue
        if FINE_PITCH_RE.search(name):
            skipped["мелкий шаг"] += 1
            continue
        coat = COAT.get(r[I["Покрытие"]], "black")
        full = r[I["Резьба"]] == "полная"
        mass = (r[I["Масса шт, г"]] or 0) / 1000.0
        if kind.startswith("болт"):
            hs = "52644" in sub
            ftype, gost = "bolt", ("ГОСТ Р 52644-2006" if hs else "ГОСТ 7798-70")
            size = "М%s×%s" % (num(d), num(length))
            title = "Болт %s%s%s" % ("высокопрочный " if hs else "", size, " полная резьба" if full else "")
            key = ("bolt", hs, d, length, cls, coat, full)
        elif kind.startswith("гайка") and (length or "мелкий шаг" in sub):
            skipped["мелкий шаг"] += 1          # «Гайка 48х3» — шаг резьбы в колонке длины
            continue
        elif kind.startswith("гайка"):
            hs, lock = "52645" in sub, "стопор" in sub
            ftype = "nut"
            gost = "ГОСТ Р 52645-2006" if hs else ("DIN 985" if lock else "ГОСТ 5915-70")
            size = "М%s" % num(d)
            title = "Гайка %s%s" % ("высокопрочная " if hs else ("стопорная " if lock else ""), size)
            key = ("nut", "hs" if hs else ("lock" if lock else ""), d, None, cls, coat, False)
        elif kind.startswith("шайба"):
            spring, hs, big, oblique = "пружин" in sub, "52646" in sub, "увелич" in sub, "кос" in sub
            ftype = "washer"
            gost = ("ГОСТ Р 52646-2006" if hs else "ГОСТ 6402-70" if spring else "ГОСТ 6958-78" if big
                    else "ГОСТ 10906-78" if oblique else "ГОСТ 11371-78")
            size = "М%s" % num(d)
            title = "Шайба %s%s" % ("высокопрочная " if hs else "пружинная " if spring else "увеличенная " if big
                                    else "косая " if oblique else "", size)
            key = ("washer", "hs" if hs else "spring" if spring else "big" if big else "oblique" if oblique else "",
                   d, None, None, coat, False)
            cls = None
        elif kind.startswith("анкер"):
            xmlid = LEGACY_ANCHOR.get((d, length))
            if not xmlid:
                skipped["анкер вне справочника"] += 1
                continue
            prices[xmlid].append(r)
            continue
        elif kind.startswith("самор"):
            if "din7504" in low or "dacromet" in low or "без шайбы" in low:
                skipped["саморез: потайной DIN 7504 / DACROMET"] += 1
                continue
            if (d, length) == (4.2, 16) and ("п/ш" in low or "пресс" in low):
                what = "с прессшайбой"
            elif (d, length) in ((4.8, 35), (5.5, 19)) and ("ш/г" in low or "кровельн" in low):
                what = "кровельный"
            elif (d, length) == (6.3, 280) and "сэндвич" in low:
                what = "для сэндвич-панелей"
            else:
                skipped["саморез: другой вид"] += 1
                continue
            coat = "painted" if RAL_RE.search(name) else "zinc"
            ftype, gost, cls, full = "screw", "", None, False
            size = "%s×%s" % (num(d), num(length))
            title = "Саморез %s %s" % (what, size)
            mass = SCREW_KG[(d, length)]
            key = ("screw", what, d, length, None, coat, False)
        else:
            skipped["вид не нужен"] += 1
            continue
        # Единое название (Антон 26.10): «Болт М6×30 кл. 5.8 цинк ГОСТ 7798-70».
        name_full = " ".join(p for p in (title, ("кл. %s" % cls) if cls else "", COAT_WORD[coat], gost) if p)
        slug = re.sub(r"[^a-z0-9]+", "_", "fast2 %s %s %s %s %s %s %s" % (
            ftype, key[1] if isinstance(key[1], str) else ("hs" if key[1] else ""), num(d), num(length),
            (cls or "").replace(".", ""), coat, "full" if full else "")).strip("_")
        if slug not in pos:
            pos[slug] = {"id": slug, "name": name_full, "fastener_type": ftype, "gost": gost, "size_label": size,
                         "weight_kg": 0.0, "strength_class": cls or "", "coating": coat,
                         "full_thread": "True" if full else "False", "active": "True"}
        # Масса позиции — наибольшая из строк группы (строка «цена за шт» бывает без массы).
        pos[slug]["weight_kg"] = max(pos[slug]["weight_kg"], round(mass, 5))
        prices[slug].append(r)
    # Без массы во всей группе: гайка — таблица ГОСТ 5915 (наибольшая, решение Антона), иначе позицию не заводим.
    import json, os
    gm = json.load(open(os.path.join(os.path.dirname(path), "gost_masses.json")))
    nut = {float(d): kg for d, kg in gm["nut_gost5915"]["data"].items()}
    big = {float(d): kg for d, kg in (gm.get("washer_gost6958", {}).get("data") or {}).items()}
    for slug, p in list(pos.items()):
        if not p["weight_kg"]:
            d = float(re.search(r"\d+(?:\.\d+)?", p["size_label"]).group(0))
            if p["fastener_type"] == "nut" and d in nut and "5915" in p["gost"]:
                p["weight_kg"] = round(nut[d], 5)
            elif p["fastener_type"] == "washer" and "6958" in p["gost"] and d in big:
                p["weight_kg"] = round(big[d], 5)
            else:
                print("  нет массы — позиция не заводится:", p["name"])
                del pos[slug]
                prices.pop(slug, None)
    with open(out + "/fasteners_rows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["id", "name", "fastener_type", "gost", "size_label", "weight_kg",
                               "strength_class", "coating", "full_thread", "active"])
        for row in sorted(pos.values(), key=lambda p: p["id"]):
            w.writerow(row)
    n = 0
    with open(out + "/fasteners_prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fastener", "supplier", "date", "price_pc", "src_name", "src_price", "src_unit", "method", "code"])
        for slug, rs in sorted(prices.items()):
            best = {}
            for r in rs:
                sup = r[I["Поставщик"]]
                if sup not in best or r[I["₽/шт"]] < best[sup][I["₽/шт"]]:
                    best[sup] = r
            for sup, r in sorted(best.items()):
                unit = r[I["Ед."]] or ""
                if r[I["Единица"]]:
                    unit += " (%s)" % r[I["Единица"]]
                w.writerow([slug, sup, DATES[sup], round(r[I["₽/шт"]], 2), r[I["Наименование (как в прайсе)"]],
                            r[I["Цена прайса, ₽"]], unit, r[I["Как получена ₽/шт"]], r[I["Код поставщика"]] or ""])
                n += 1
    print("позиций:", len(pos), "| цен:", n, "| пропущено строк:", dict(skipped))
    print("по видам:", dict(sorted(defaultdict(int, {t: sum(1 for p in pos.values() if p["fastener_type"] == t)
                                                     for t in ("bolt", "nut", "washer", "screw")}).items())))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
