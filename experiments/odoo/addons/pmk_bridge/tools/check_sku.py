# -*- coding: utf-8 -*-
"""Прогон генератора артикулов по всему справочнику pmk_calc.

Тесты проверяют штучные случаи. Этот скрипт отвечает на другой вопрос: что
будет, когда через генератор пройдут все 752 строки разом. Интересует ровно
одно — СТОЛКНОВЕНИЯ. Два сортамента с одним артикулом означают, что при
загрузке прайса цена одной позиции молча ляжет на другую, и заметят это на
отгрузке.

Скрипт читает CSV модуля pmk_calc напрямую и ничего никуда не пишет — ни в
базу, ни в файлы. Запуск:

    python3 experiments/odoo/addons/pmk_bridge/tools/check_sku.py
"""

import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from models import sku  # noqa: E402

DATA_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "pmk_calc", "data"))

# Ожидаемые количества строк. Не украшение: если CSV поедет (кто-то дольёт
# сортамент и забудет сказать), цифры в отчёте разойдутся с решением владельца
# «752 карточки», и это будет видно сразу, а не после заливки.
EXPECTED = {
    "pmk.metal.profile": 665,
    "pmk.metal.sheet": 56,
    "pmk.metal.fastener": 25,
    "pmk.paint.coating": 6,
}

# Габариты листа. Лист считаем штуками, поэтому габарит — характеристика
# варианта наравне с маркой стали.
SHEET_SIZES = ["1500x3000", "1500x6000", "1000x4000"]


def read_csv(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def describe(title, pairs):
    """Печатает сводку по набору пар (артикул, что за позиция).

    Возвращает словарь столкновений, чтобы вызывающий мог посчитать итог.
    """
    codes = [code for code, _ in pairs]
    lengths = [len(c) for c in codes]
    non_ascii = sum(1 for c in codes for ch in c if ord(ch) > 127)

    by_code = defaultdict(list)
    for code, label in pairs:
        by_code[code].append(label)
    collisions = {c: labels for c, labels in by_code.items() if len(labels) > 1}

    # Регистр проверяем отдельно: поиск в Odoo и половина прайсов
    # регистронезависимы, так что DVT-20B1 и dvt-20b1 для человека — одно и
    # то же, хотя для базы разное.
    ci = Counter(c.upper() for c in codes)
    ci_collisions = {c: n for c, n in ci.items() if n > 1 and c not in
                     {k.upper() for k in collisions}}

    print("\n=== %s ===" % title)
    print("  строк: %d   уникальных артикулов: %d" % (len(codes), len(by_code)))
    print("  длина: максимум %d, средняя %.1f" % (max(lengths), sum(lengths) / len(lengths)))
    print("  не-ASCII символов в артикулах: %d" % non_ascii)
    if collisions:
        print("  СТОЛКНОВЕНИЯ (%d):" % len(collisions))
        for code in sorted(collisions):
            print("    %-24s <- %s" % (code, "  |  ".join(collisions[code])))
    else:
        print("  столкновений: нет")
    if ci_collisions:
        print("  СТОЛКНОВЕНИЯ без учёта регистра (%d): %s"
              % (len(ci_collisions), ", ".join(sorted(ci_collisions))))
    else:
        print("  столкновений без учёта регистра: нет")
    return collisions


def main():
    print("Справочник: %s" % DATA_DIR)

    profiles = read_csv("pmk.metal.profile.csv")
    sheets = read_csv("pmk.metal.sheet.csv")
    fasteners = read_csv("pmk.metal.fastener.csv")
    paints = read_csv("pmk.paint.coating.csv")
    grades = read_csv("pmk.metal.grade.csv")

    actual = {
        "pmk.metal.profile": len(profiles),
        "pmk.metal.sheet": len(sheets),
        "pmk.metal.fastener": len(fasteners),
        "pmk.paint.coating": len(paints),
    }
    print("\nСтрок в CSV: " + ", ".join("%s=%d" % (k.split(".")[-1], v)
                                        for k, v in actual.items()))
    if actual != EXPECTED:
        print("  ВНИМАНИЕ: расходится с ожидаемым %s" % (EXPECTED,))
    print("Марок стали: %d" % len(grades))
    print("Всего карточек: %d" % sum(actual.values()))
    print("\nДубль листа id=57 в живой базе (близнец строки sheet_оцинк_0_6,")
    print("оцинкованный 0.6 мм) в прогон НЕ входит: XML-id принадлежит id=58,")
    print("57-я — сирота без ссылок, подлежит удалению. В CSV её нет, поэтому")
    print("листов ровно 56. Если бы вошла — дала бы столкновение LST-ZN-0.6.")

    # --- артикулы карточек ---
    profile_pairs = [
        (sku.sku_for_row("pmk.metal.profile", r), "%s %s" % (r["profile_type"], r["size_label"]))
        for r in profiles]
    sheet_pairs = [
        (sku.sku_for_row("pmk.metal.sheet", r),
         ("Лист %s %s %s" % (r["sheet_type"], r["thickness_mm"], r["size_label"])).strip())
        for r in sheets]
    fastener_pairs = [
        (sku.sku_for_row("pmk.metal.fastener", r), r["name"]) for r in fasteners]
    paint_pairs = [
        (sku.sku_for_row("pmk.paint.coating", r), r["name"]) for r in paints]

    bad = 0
    bad += len(describe("Прокат (профили)", profile_pairs))
    bad += len(describe("Лист", sheet_pairs))
    bad += len(describe("Метизы", fastener_pairs))
    bad += len(describe("ЛКП", paint_pairs))

    all_pairs = profile_pairs + sheet_pairs + fastener_pairs + paint_pairs
    bad += len(describe("ВСЕ КАРТОЧКИ ВМЕСТЕ", all_pairs))

    # --- артикулы вариантов ---
    # Марка стали — характеристика с dynamic-вариантами: карточка одна,
    # вариантов у неё столько, сколько марок закажут. Артикул варианта =
    # артикул карточки + марка через дефис.
    grade_codes = [(g["name"], sku.grade_code(g["name"])) for g in grades]
    print("\n=== Марки стали ===")
    for name, code in grade_codes:
        print("  %-8s -> %s" % (name, code))

    variant_pairs = []
    for base, label in all_pairs:
        for grade_name, grade in grade_codes:
            variant_pairs.append(
                (sku.variant_sku(base, grade), "%s / %s" % (label, grade_name)))
    bad += len(describe("ВАРИАНТЫ: %d карточек x %d марок"
                        % (len(all_pairs), len(grade_codes)), variant_pairs))

    # Отдельно лист: у него характеристик две — марка И габарит, потому что
    # лист считаем штуками листа определённого размера. Проверяем, что третья
    # координата не рождает двойников.
    sheet_variants = []
    for base, label in sheet_pairs:
        for grade_name, grade in grade_codes:
            for size in SHEET_SIZES:
                sheet_variants.append(
                    (sku.variant_sku(base, grade, size),
                     "%s / %s / %s" % (label, grade_name, size)))
    bad += len(describe("ВАРИАНТЫ ЛИСТА: %d x %d марок x %d габаритов"
                        % (len(sheet_pairs), len(grade_codes), len(SHEET_SIZES)),
                        sheet_variants))

    print("\n" + "=" * 60)
    print("ИТОГО столкновений во всех прогонах: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
