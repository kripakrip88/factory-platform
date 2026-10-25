# -*- coding: utf-8 -*-
"""Уже распознанные счета без металла (перевозка, услуги) — из «Ждут проверки» в «Не счёт»."""


def migrate(cr, version):
    cr.execute("""
        UPDATE pmk_supplier_invoice s
           SET state = 'skipped', reason = 'В счёте нет металлопроката — цены обновлять нечего.'
         WHERE s.state = 'review'
           AND NOT EXISTS (SELECT 1 FROM pmk_supplier_invoice_line l
                            WHERE l.invoice_id = s.id AND l.kind = 'metal')""")
