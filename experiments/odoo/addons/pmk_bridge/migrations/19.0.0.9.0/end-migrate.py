# -*- coding: utf-8 -*-
"""19.0.0.9.0 — одна цена на позицию в каждом прайсе: самая низкая (19.10.2026).

Антон: «нам всегда считают по самой низкой цене, тк мы оптовики»;
«промежуточные цены поставщиков на нас не распространяются»; удалять можно —
расчёты в тестовом режиме, их «поменяй на новые цены»; цены старых прайсов
сохранить — «видно динамику, как меняется цена из года в год».

Ряд прайса — поставщик × карточка × вариант × единица × даты действия (один
прайс одной даты). В ряду остаётся самая дешёвая строка (порог 0, уровень 1),
остальные удаляются. История — ряды прежних дат — остаётся, по одной строке.

⚠️ END-миграция, не post: перечитывание считает стоимость, а её правила
дополняют модули, что грузятся после моста (pmk_cut_cost — хлысты раскроя,
pmk_tech — доля раскладки). end- идёт, когда загружены все.

Расчёты, чьи строки ссылаются на удаляемые цены, перечитываются кнопкой
«Перечитать цены» (action_refresh_prices: снимок «было», лента, итог) — их цены
встают на оставшиеся строки. Кто остался на удаляемой строке (поставщик или дата
расчёта выбирают иначе) — переводится на оставшуюся строку того же ряда.
"""
import logging
from collections import defaultdict

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"active_test": False, "tracking_disable": True})
    SI = env["product.supplierinfo"]
    groups = defaultdict(list)
    for rec in SI.search([]):
        key = (rec.partner_id.id, rec.product_tmpl_id.id, rec.product_id.id,
               rec.product_uom_id.id, rec.date_start, rec.date_end)
        groups[key].append(rec)
    keep_of, keep, drop = {}, SI, SI
    for rows in groups.values():
        rows.sort(key=lambda r: (r.price_discounted, r.id))
        head = rows[0]
        keep |= head
        for other in rows[1:]:
            drop |= other
            keep_of[other.id] = head.id
    if not drop:
        _logger.info("pmk_bridge 19.0.0.9.0: промежуточных цен нет — пропуск")
        return
    keep.filtered(lambda r: r.min_qty or r.sequence != 1).write({"min_qty": 0.0, "sequence": 1})
    Line = env["pmk.metal.spec.line"]
    specs = Line.search([("price_source_id", "in", drop.ids)]).spec_id
    if specs:
        specs.action_refresh_prices()
        env.flush_all()
    stuck = Line.search([("price_source_id", "in", drop.ids)])
    for line in stuck:
        cr.execute("UPDATE pmk_metal_spec_line SET price_source_id=%s WHERE id=%s",
                   (keep_of[line.price_source_id.id], line.id))
    env.invalidate_all()
    n_drop = len(drop)
    drop.unlink()
    _logger.info("pmk_bridge 19.0.0.9.0: рядов прайса %s, оставлено строк %s, удалено промежуточных %s; "
                 "расчётов перечитано %s; строк переведено на оставшуюся цену %s",
                 len(groups), len(keep), n_drop, len(specs), len(stuck))
