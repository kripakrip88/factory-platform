# -*- coding: utf-8 -*-
"""19.0.1.2.1 — марка из ячейки «Конструкций» по словарю написаний (Антон 25.10.2026:
«С345 считаем как 09Г2С»). Уже вписанные текстом марки («С345», «ст3», «С255») —
получают марку справочника, текст остаётся; цена строки пересчитывается по марке."""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_bridge.tools import grades

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True})
    Grade = env["pmk.metal.grade"]
    lines = env["pmk.metal.spec.line"].search([("pmk_grade_text", "!=", False), ("grade_id", "=", False)])
    done = {}
    for line in lines:
        mapped = grades.map_grade(line.pmk_grade_text)
        grade = Grade.search([("name", "=", mapped)], limit=1) if mapped else Grade
        if grade:
            line.write({"grade_id": grade.id, "pmk_grade_text": line.pmk_grade_text})
            key = "%s → %s" % (line.pmk_grade_text, grade.name)
            done[key] = done.get(key, 0) + 1
    _logger.info("pmk_butik 19.0.1.2.1: марка по словарю %s (строк с текстом марки %s)", done, len(lines))
