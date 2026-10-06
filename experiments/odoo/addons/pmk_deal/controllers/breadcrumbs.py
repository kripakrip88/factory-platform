# -*- coding: utf-8 -*-
"""Номер сделки в строке пути после перезагрузки страницы — разбор UX, шаг 48.

ЗАЧЕМ. Пока сделка открыта, подпись её звена — «СД-00001 от 27.09.2026»:
её подменяет контроллер формы на клиенте (static/src/js/deal_form_view.js).
Но если перезагрузить страницу (F5) на расчёте, открытом из сделки
(/odoo/crm/12/action-…/25), прежние звенья пути браузер восстанавливает
запросом /web/action/load_breadcrumbs, а ядро берёт там display_name записи
(web/controllers/action.py) — длинную тему письма. Путь становился «Воронка /
Запрос стоимости изготовления МК п. Горн… / СМ-00025», хотя до перезагрузки
был «Воронка / СД-00001 от 27.09.2026 / СМ-00025».

ЧТО ДЕЛАЕМ. Ответ ядра не меняем, кроме подписи звеньев-сделок: у сделки
(type='opportunity') с номером — pmk_number_label. То же правило, что на
клиенте (static/src/js/deal_head_rules.js): лид, сделка без номера и новая
запись — штатная подпись. Имя сделки (display_name) не трогаем: его берёт
почта темой письма и поле «Сделка» расчёта.

Подпись — украшение: если разобрать звено не вышло, путь остаётся таким,
каким его собрало ядро, и ошибка уходит в журнал, а не пользователю.

⚠️ Наследуем контроллер ядра (Action.load_breadcrumbs) — перепроверять при
обновлении Odoo: ответ — список той же длины, что запрос, по звену на
действие. Сверяет tests/test_step48_deal_head.py (TestDealCrumbsReload).
ВЕРНУТЬ: убрать импорт controllers в __init__.py модуля.
"""
import logging

from odoo.http import request, route

from odoo.addons.web.controllers.action import Action

_logger = logging.getLogger(__name__)

DEAL_MODEL = "crm.lead"


class PmkDealBreadcrumbs(Action):

    @route()
    def load_breadcrumbs(self, actions):
        results = super().load_breadcrumbs(actions)
        try:
            self._pmk_deal_crumbs(actions, results)
        except Exception:  # noqa: BLE001 — подпись не должна ронять путь
            _logger.exception("Шаг 48: номер сделки в строке пути не подставлен")
        return results

    def _pmk_deal_crumbs(self, actions, results):
        """Звенья-сделки с номером → «СД-00001 от 27.09.2026» (на месте)."""
        if len(actions) != len(results):
            return
        Lead = request.env[DEAL_MODEL]
        for action, result in zip(actions, results):
            record_id = action.get("resId")
            if not isinstance(record_id, int) or "display_name" not in result:
                continue
            if self._pmk_crumb_model(action) != DEAL_MODEL:
                continue
            deal = Lead.browse(record_id).exists()
            if deal and deal.type == "opportunity" and deal.pmk_number_label:
                result["display_name"] = deal.pmk_number_label

    def _pmk_crumb_model(self, action):
        """Модель записи звена: из запроса или из окна-действия."""
        if action.get("model"):
            return action["model"]
        if not action.get("action"):
            return None
        act = self.load(action["action"])
        if act and act.get("type") == "ir.actions.act_window":
            return act.get("res_model")
        return None
