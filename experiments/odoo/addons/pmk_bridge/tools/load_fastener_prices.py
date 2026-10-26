# -*- coding: utf-8 -*-
"""Цены метизов (₽/шт) из разбора прайсов МК-27 и Метиз Центр — odoo shell.

26.10.2026, передача чата «Прайс листы поставщиков»: прайсы крепежа дают цену за кг, за штуку
и за упаковку; ₽/шт посчитаны там по массам ГОСТ (experiments/odoo/scripts_v1183/
build_fasteners.py → fasteners_prices.csv). Здесь — только запись: одна строка цены на позицию
от поставщика (минимум ₽/шт среди его строк), с исходным названием и кодом поставщика,
тем же рядом, что ведёт загрузчик прайсов (поставщик, товар, уровень 1): цена с новой датой
закрывает прошлый период. Цены С НДС (Антон 26.10).

    PMK_FAST_FILE=/tmp/fasteners_prices.csv [PMK_FAST_APPLY=1] [PMK_LIVE=1] odoo shell < этот файл

Без PMK_FAST_APPLY — отчёт без записи. На боевой — только с PMK_LIVE=1 (предохранитель).
"""
import csv
import datetime
import os
import sys

REHEARSAL_DBS = ("odoo_stage", "odoo_rehearsal")
if env.cr.dbname not in REHEARSAL_DBS and os.environ.get("PMK_LIVE") != "1":  # noqa: F821
    sys.exit("ОТКАЗ: %r не копия; боевая заливка — с PMK_LIVE=1." % env.cr.dbname)  # noqa: F821

SUPPLIER_INN = {"МК-27": "2723096876", "Метиз Центр": "2724224190"}
path = os.environ.get("PMK_FAST_FILE", "")
apply = os.environ.get("PMK_FAST_APPLY") == "1"
if not os.path.exists(path):
    sys.exit("ОТКАЗ: нет файла %r" % path)

Partner = env["res.partner"].with_context(active_test=False)  # noqa: F821
partners = {}
for name, inn in SUPPLIER_INN.items():
    found = Partner.search([("vat", "=", inn), ("is_company", "=", True), ("parent_id", "=", False)])
    if len(found) != 1:
        sys.exit("ОТКАЗ: поставщик %s (ИНН %s) — карточек %d; сначала свести дубли." % (name, inn, len(found)))
    partners[name] = found

SI = env["product.supplierinfo"]  # noqa: F821
stat, missing = {}, []
for row in csv.DictReader(open(path, encoding="utf-8")):
    fastener = env.ref("pmk_calc.%s" % row["fastener"], raise_if_not_found=False)  # noqa: F821
    tmpl = fastener.product_tmpl_id if fastener else None
    if not tmpl:
        missing.append(row["fastener"])
        continue
    partner, date = partners[row["supplier"]], datetime.date.fromisoformat(row["date"])
    price = round(float(row["price_pc"]), 2)
    vals = {"partner_id": partner.id, "product_tmpl_id": tmpl.id, "product_id": False, "sequence": 1,
            "min_qty": 0.0, "price": price, "date_start": date, "product_uom_id": tmpl.uom_id.id,
            "currency_id": env.company.currency_id.id,  # noqa: F821
            # Исходная строка прайса — проверить цифру глазами: «… 337 ₽/кг × 0,123 кг».
            "product_name": ("%s — %s ₽/%s; %s" % (row["src_name"], row["src_price"], row["src_unit"],
                                                   row["method"]))[:250],
            "product_code": row["code"] or False}
    series = SI.search([("partner_id", "=", partner.id), ("product_tmpl_id", "=", tmpl.id),
                        ("product_id", "=", False), ("sequence", "=", 1)], order="date_start")
    same = series.filtered(lambda r: r.date_start == date)
    if same:
        what = "без изменений" if abs(same[0].price - price) < 0.005 else "исправлено"
        if apply and what != "без изменений":
            same[0].write(vals)
    else:
        what = "создано"
        if apply:
            for rec in series.filtered(lambda r: r.date_start and r.date_start < date
                                       and (not r.date_end or r.date_end >= date)):
                rec.date_end = date - datetime.timedelta(days=1)
            SI.create(vals)
    stat[what] = stat.get(what, 0) + 1
print("режим:", "ЗАПИСЬ" if apply else "без записи", "| база:", env.cr.dbname)  # noqa: F821
print("итог:", stat, "| позиций без карточки:", len(missing), missing[:10])
if apply:
    env.cr.commit()  # noqa: F821
    print("зафиксировано")
