# -*- coding: utf-8 -*-
"""Отпечаток раскладки у уже разложенных расчётов (разбор UX, шаг 56).

Поле layout_fingerprint новое: у расчётов, разложенных до выкладки шага 56,
его нет, и сигнал «Раскладка устарела» у них не загорелся бы никогда. Решаем
по дате последней раскладки (запись «Раскладка листов…» в истории расчёта)
против даты исправления 30.09.2026 — с доводки шага 32 (коммит 2e189a8,
v1.11.0, 30.09 22:20 по Владивостоку = 12:20 UTC) правка деталей гасит
раскладку в базе:

  • разложен ПОСЛЕ исправления — отпечаток от текущих деталей: раскладка
    считается актуальной. Детали, погашенные правкой после неё (layout_state
    «Не считалась»), сигнал всё равно дадут;
  • разложен ДО исправления или записи в истории нет (раскладка старше самой
    записи, 27.09) — LEGACY_FINGERPRINT: «посчитана до исправления 30.09 и
    могла устареть». Это СМ-00021…24 из отчёта к шагу 34 — кроме тех, что
    разложены заново позже (боевая база, SELECT 08.10: СМ-00024 — 05.10,
    СМ-00025 — 01.10, они актуальны; СМ-00021, 22, 23 — «могла устареть»);
  • не раскладывался (все листовые детали «Не считалась») — без отпечатка,
    без плашки (СМ-00015, СМ-00016).

Пишем SQL-ом, а не write(): дата изменения расчёта и автор остаются прежними —
это служебное поле, а не правка документа. Только где отпечатка нет —
повторный запуск ничего не меняет. Вернуть — UPDATE pmk_metal_spec SET
layout_fingerprint = NULL.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.pmk_calc.models.spec_layout import LEGACY_FINGERPRINT

_logger = logging.getLogger(__name__)

# Доводка шага 32 (2e189a8) — с неё правка деталей гасит раскладку в базе.
FIXED_AT_UTC = "2026-09-30 12:20:00"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT s.id,
               (SELECT max(m.date) FROM mail_message m
                 WHERE m.model = 'pmk.metal.spec' AND m.res_id = s.id
                   AND m.body LIKE %s) AS laid_at
          FROM pmk_metal_spec s
         WHERE s.layout_fingerprint IS NULL
           AND EXISTS (SELECT 1 FROM pmk_metal_spec_line l
                        WHERE l.spec_id = s.id AND l.calc_mode = 'sheet'
                          AND l.layout_state IS NOT NULL AND l.layout_state <> 'none')
    """, ["%Раскладка листов%"])
    for spec_id, laid_at in cr.fetchall():
        spec = env["pmk.metal.spec"].browse(spec_id)
        if laid_at and str(laid_at) >= FIXED_AT_UTC:
            value = " ".join(sorted(spec._pmk_layout_keys())) or None
            verdict = "актуальна (разложен %s UTC)" % laid_at
        else:
            value = LEGACY_FINGERPRINT
            verdict = "могла устареть (%s)" % (
                "разложен %s UTC" % laid_at if laid_at else "записи о раскладке нет")
        cr.execute("UPDATE pmk_metal_spec SET layout_fingerprint = %s WHERE id = %s",
                   [value, spec_id])
        _logger.info("Шаг 56: %s — раскладка %s", spec.name, verdict)
    env.invalidate_all()
