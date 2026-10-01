# -*- coding: utf-8 -*-
"""Панель над «Запросами КП»: пусто — прочерк (разбор UX, шаг 26, 01.10.2026).

Ядро (purchase, retrieve_dashboard) отдаёт показатели готовыми строками:
  • «Дней до заказа» — float_repr(…, 2): «0.00» с точкой, и «0.00» же,
    когда за три месяца не было ни одного заказа;
  • «Поставки в срок» (purchase_stock) — «100 %», когда поставок не было
    вовсе: «… if purchases else 100». Ложная хорошая цифра.
Отличить «ноль» от «нечего считать» по самой строке нельзя (заказ,
подтверждённый в день запроса, тоже даёт 0), поэтому считаем, были ли
заказы, тем же отбором, что ядро.

  • «Дней до заказа» — подпись в pmk_days_to_order (у карточек «Все» и
    «Мои»): прочерк, если заказов не было; иначе число с одним знаком в
    формате языка пользователя (formatLang, у ru_RU — «2,5»). Сырое
    значение ядра остаётся на месте: по нему шаблон сравнивает со сроком
    компании и красит карточку жёлтым. Шаблон берёт подпись —
    static/src/xml/purchase_dashboard.xml.
  • «Поставки в срок» — прочерк прямо в значении ядра: процент целый,
    запятой в нём нет, а шаблон карточки чужой (purchase_stock), и xpath к
    нему из нашего модуля зависел бы от порядка бандла.

Какие карточки показывать — pmk_show (разбор UX, шаг 29, 02.10.2026):
  • «Не подтверждены поставщиком» (обе: «Все» и «Мои») — только с
    «Убранным (показать)»: отметить «поставщик получил заказ» шаг 29 убрал
    (кнопка «Подтвердить», фильтр «Не принято»), портал закрыт шагом 23 —
    счётчик рос бы с каждым заказом, а щелчок по карточке искал бы
    фильтр, которого нет;
  • «Поставки в срок» — только со «Складом (показать)»: без приёмок ядро
    считает 0 %, и это тот же «% своевременной поставки», что шаг 29
    прячет в заказе.
Решает сервер (has_group), шаблон только читает флаг
(static/src/xml/purchase_dashboard.xml); флага нет (окно выкладки) —
карточки как у ядра.

Вернуть штатное: удалить этот файл и строку в models/__init__.py, убрать
xpath с pmk_days_to_order и pmk_show из шаблона. Таблица —
docs/disabled-features.md.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.tools.misc import formatLang

DASH = "—"
# Группы-выключатели шага 29 (pmk_theme/security/pmk_step29_groups.xml).
REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    @api.model
    def retrieve_dashboard(self):
        result = super().retrieve_dashboard()
        since = fields.Datetime.now() - relativedelta(months=3)
        mine = [("user_id", "=", self.env.uid)]

        # Отбор — как у ядра для «Дней до заказа» (purchase/models/purchase_order.py).
        ordered = [("state", "=", "purchase"), ("create_date", ">=", since),
                   ("date_approve", "!=", False)]
        labels = {}
        for scope, domain in (("global", ordered), ("my", ordered + mine)):
            if self.search_count(domain):
                labels[scope] = formatLang(self.env, float(result[scope]["days_to_order"]), digits=1)
            else:
                labels[scope] = DASH
        result["pmk_days_to_order"] = labels

        # Отбор — как у purchase_stock для «Поставок в срок».
        if "otd" in result["global"]:
            delivered = [("state", "=", "purchase"), ("date_planned", ">=", since)]
            for scope, domain in (("global", delivered), ("my", delivered + mine)):
                if not self.search_count(domain):
                    result[scope]["otd"] = DASH

        user = self.env.user
        result["pmk_show"] = {
            "not_acknowledged": user.has_group(REMOVED),
            "otd": user.has_group(STOCK),
        }
        return result
