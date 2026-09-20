# -*- coding: utf-8 -*-
"""Заполнение реквизитов контрагента по ИНН через DaData."""

import logging

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
TIMEOUT = 10


class ResPartner(models.Model):
    _inherit = "res.partner"

    pmk_legal_name = fields.Text(
        "Полное наименование",
        help="Как в ЕГРЮЛ, с организационно-правовой формой. "
             "Идёт в договоры и печатные формы.",
    )
    pmk_legal_address = fields.Text(
        "Юридический адрес",
        help="Одной строкой, как в выписке. Адрес доставки и почтовый "
             "заполняются отдельно в блоке контактов.",
    )
    pmk_address_note = fields.Char(
        "Комментарий к адресу",
        help="Ориентир, номер офиса, как проехать — то, чего нет в выписке.",
    )
    pmk_dadata_status = fields.Char(
        "Состояние по ЕГРЮЛ", readonly=True,
        help="Что ответил справочник при последнем заполнении по ИНН.",
    )

    # ------------------------------------------------------------------
    def action_pmk_fill_by_inn(self):
        """Заполнить реквизиты по ИНН."""
        self.ensure_one()
        inn = (self.inn or "").strip()
        if not inn:
            raise UserError(_("Сначала укажите ИНН."))
        if not inn.isdigit() or len(inn) not in (10, 12):
            raise UserError(_(
                "ИНН должен быть из 10 цифр у организации или 12 у "
                "предпринимателя. Сейчас там «%s».", inn))

        data = self._pmk_dadata_find(inn)

        name = data.get("name") or {}
        address = data.get("address") or {}
        addr_data = address.get("data") or {}
        state = data.get("state") or {}

        vals = {
            "pmk_legal_name": name.get("full_with_opf") or False,
            "pmk_legal_address": address.get("value") or False,
            "pmk_dadata_status": self._pmk_status_label(state.get("status")),
        }
        # Короткое имя подставляем только в пустое поле: у заведённых вручную
        # контрагентов название часто привычнее выписочного.
        if not self.name or self.name == inn:
            vals["name"] = name.get("short_with_opf") or name.get("full_with_opf")

        for field, value in (
            ("kpp", data.get("kpp")),
            ("ogrn", data.get("ogrn")),
            ("okpo", data.get("okpo")),
            ("fias_id", addr_data.get("fias_id")),
        ):
            if value and field in self._fields:
                vals[field] = value

        # Разложенный адрес нужен Odoo для доставки и печатных форм —
        # заполняем, но не затираем уже введённое руками.
        if not self.zip and addr_data.get("postal_code"):
            vals["zip"] = addr_data["postal_code"]
        if not self.city and (addr_data.get("city") or addr_data.get("settlement")):
            vals["city"] = addr_data.get("city") or addr_data.get("settlement")
        if not self.street and addr_data.get("street_with_type"):
            house = addr_data.get("house_with_type") or ""
            vals["street"] = " ".join(x for x in (addr_data["street_with_type"], house) if x)
        if not self.country_id:
            ru = self.env.ref("base.ru", raise_if_not_found=False)
            if ru:
                vals["country_id"] = ru.id

        self.write(vals)

        status = state.get("status")
        if status and status != "ACTIVE":
            # Не ошибка: ликвидированного контрагента иногда заводят намеренно,
            # чтобы закрыть старые документы. Но сказать об этом надо громко.
            return self._pmk_notify(
                "warning", _("Реквизиты заполнены"),
                _("Внимание: по ЕГРЮЛ организация «%s». Проверьте, тот ли это контрагент.",
                  self._pmk_status_label(status)))
        return self._pmk_notify(
            "success", _("Реквизиты заполнены"),
            _("Данные получены из справочника по ИНН %s.", inn))

    # ------------------------------------------------------------------
    def _pmk_dadata_find(self, inn):
        ICP = self.env["ir.config_parameter"].sudo()
        api_key = ICP.get_param("pmk.dadata.api_key")
        if not api_key:
            raise UserError(_(
                "Не задан ключ DaData. Системный параметр pmk.dadata.api_key пуст."))
        try:
            response = requests.post(
                API_URL,
                json={"query": inn},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": "Token %s" % api_key,
                },
                timeout=TIMEOUT,
            )
        except requests.Timeout:
            raise UserError(_(
                "Справочник не ответил за %s секунд. Попробуйте ещё раз.", TIMEOUT))
        except requests.RequestException as exc:
            _logger.warning("DaData недоступна: %s", exc)
            raise UserError(_("Не удалось связаться со справочником: %s", exc))

        if response.status_code == 401:
            raise UserError(_("Справочник не принял ключ. Проверьте pmk.dadata.api_key."))
        if response.status_code == 403:
            raise UserError(_(
                "Справочник отказал в доступе — обычно это исчерпанный дневной лимит."))
        if response.status_code != 200:
            raise UserError(_("Справочник ответил ошибкой %s.", response.status_code))

        suggestions = (response.json() or {}).get("suggestions") or []
        if not suggestions:
            raise UserError(_(
                "По ИНН %s ничего не нашлось. Проверьте номер.", inn))
        if len(suggestions) > 1:
            _logger.info("DaData вернула %s записей по ИНН %s, берём первую",
                         len(suggestions), inn)
        return suggestions[0].get("data") or {}

    @staticmethod
    def _pmk_status_label(status):
        return {
            "ACTIVE": "Действующая",
            "LIQUIDATING": "В стадии ликвидации",
            "LIQUIDATED": "Ликвидирована",
            "REORGANIZING": "В стадии реорганизации",
            "BANKRUPT": "Банкротство",
        }.get(status, status or "")

    def _pmk_notify(self, kind, title, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"type": kind, "title": title, "message": message, "sticky": False},
        }
