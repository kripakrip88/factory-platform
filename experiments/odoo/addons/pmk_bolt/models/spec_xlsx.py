# -*- coding: utf-8 -*-
"""Болты в «Расчёт (Excel)» (pmk_orders spec_xlsx.py; Антон 22.10.2026: «да делаем всё»).

- «Состав» — раздел «Фундаментные болты»: болт блоком, под ним его состав (круг с длиной
  заготовки и ценой за тонну, гайки, шайба, плита), «нет цены» — жёлтым;
- «Металл и деньги» — материалы болтов (круг в метрах, вес, стоимость) в общей таблице.
Лист «Изделия» и деньги по изделиям болты получают из сводки «Металлоизделия».
"""
from odoo import _, models


class MetalSpecBoltXlsx(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_xlsx_composition_more(self, rows, section, block):
        super()._pmk_xlsx_composition_more(rows, section, block)
        lines = self._pmk_bolt_lines().sorted(lambda l: (l.sequence, l.id))
        if not lines:
            return
        section(_("Фундаментные болты"))
        for line in lines:
            parts = []
            for part in line.part_ids.filtered("name").sorted(lambda p: (p.sequence, p.id)):
                stud = part.auto_key == "stud"
                price = part.price_ton if stud else part.price_unit
                parts.append(("", part.name, line.blank_mm if stud else "", part.qty,
                              (line.steel or "") if stud else "", part.mass * line.qty,
                              round(price) if stud and price else (None if price else 0)))
            block(line.qty, line.name, parts)

    def _pmk_xlsx_money_more(self, rows, add):
        super()._pmk_xlsx_money_more(rows, add)
        for line in self._pmk_bolt_lines():
            for part in line.part_ids.filtered("name"):
                stud = part.auto_key == "stud"
                add(part.name, m=(line.blank_mm * part.qty * line.qty / 1000.0) if stud else 0,
                    kg=part.mass * line.qty, rub=part.cost * line.qty)
