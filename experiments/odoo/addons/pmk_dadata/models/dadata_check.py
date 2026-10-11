# -*- coding: utf-8 -*-
"""«Сверить по ИНН» — окно сверки реквизитов с ЕГРЮЛ (шаг З-17, 11.10.2026).

ЗАЧЕМ. После объединения карточек (окно «Объединить контакты») у
оставшейся могут быть чужие КПП, адрес или название — Антон 11.10: «либо
принимать какой-то ИНН как истинно верный». ИНН — источник правды: по нему
справочник DaData отдаёт выписку, а это окно показывает, ЧТО поменяется:
строка на поле — «Сейчас» / «По ЕГРЮЛ» / «Заменить». Ничего не пишется,
пока человек не нажмёт «Применить», и пишется только отмеченное.

  • Название по умолчанию НЕ отмечено: привычное имя карточки («А ГРУПП»)
    часто удобнее выписочного «ООО «А ГРУПП МАРКЕТ»».
  • КПП у карточки уже есть и другой — строка по умолчанию НЕ отмечена,
    подпись «у филиала свой КПП»: DaData по ИНН первой отдаёт головную
    организацию, а у обособленного подразделения (у завода таких карточек
    9) КПП свой, и он печатается в УПД, счёте и заказе.
  • Код ФИАС, индекс, город и улицу с карточки сняли шагом 8 — строками их
    не показываем (сверять то, чего не видно, нельзя). Пишутся молча вместе
    с юридическим адресом: код ФИАС — по выписке, индекс, город и улица —
    только в пустые (как у «Заполнить по ИНН»): разложенный адрес правят
    руками под доставку.
  • Поля, которых в выписке нет, не предлагаются к очистке.
  • Организация не действует по ЕГРЮЛ — плашка (красная «Ликвидирована» /
    «Банкротство», жёлтая «В стадии …» — цвет повторён словом), но
    применить можно: старого контрагента иногда держат ради документов.

Строки временные (TransientModel), свои у каждого окна.
"""

from odoo import Command, _, api, fields, models

# (поле, подпись, «Заменить» по умолчанию)
CHECK_FIELDS = (
    ("name", "Название", False),
    ("pmk_legal_name", "Полное наименование", True),
    ("kpp", "КПП", True),
    ("ogrn", "ОГРН", True),
    ("okpo", "ОКПО", True),
    ("pmk_legal_address", "Юридический адрес", True),
    ("pmk_dadata_status", "Состояние по ЕГРЮЛ", True),
)
# Разложенный адрес — без строк, молча вместе с юридическим адресом:
# (поле, подпись для ленты, только в пустое).
ADDRESS_PARTS = (("fias_id", "код ФИАС", False), ("zip", "индекс", True),
                 ("city", "город", True), ("street", "улица", True))
STATUS_DANGER = ("LIQUIDATED", "BANKRUPT")


def _same(current, new):
    return " ".join(str(current or "").split()) == " ".join(str(new or "").split())


class PmkDadataCheck(models.TransientModel):
    _name = "pmk.dadata.check"
    _description = "Сверка реквизитов с ЕГРЮЛ"

    partner_id = fields.Many2one("res.partner", "Контрагент", required=True,
                                 readonly=True, ondelete="cascade")
    inn = fields.Char("ИНН", readonly=True)
    status_warn = fields.Char("Состояние по ЕГРЮЛ", readonly=True)
    status_level = fields.Selection(
        [("danger", "Не действует"), ("warning", "Внимание")], readonly=True)
    line_ids = fields.One2many("pmk.dadata.check.line", "check_id", "Что поменяется")
    # Код ФИАС, индекс, город, улица из выписки — пишутся молча вместе с
    # юридическим адресом (ADDRESS_PARTS).
    address_values = fields.Json(readonly=True)

    @api.model
    def _pmk_lines(self, partner, found):
        """Строки сверки: только различия и только там, где выписке есть что
        сказать."""
        lines = []
        for sequence, (name, label, apply) in enumerate(CHECK_FIELDS):
            if name not in partner._fields:
                continue
            new = found.get(name)
            current = partner[name]
            if not new or _same(current, new):
                continue
            if name == "kpp" and current:
                # Головная против филиала: у подразделения свой КПП.
                apply = False
                label = _("КПП — у филиала свой, проверьте")
            lines.append({"sequence": sequence, "field_name": name, "label": label,
                          "current": current or "", "new": new, "apply": apply})
        return lines

    @api.model
    def _pmk_open(self, partner, inn, found, status):
        lines = self._pmk_lines(partner, found)
        if not lines:
            return partner._pmk_notify(
                "success", _("Реквизиты совпадают с ЕГРЮЛ"),
                _("По ИНН %s менять нечего.", inn))
        values = {"partner_id": partner.id, "inn": inn,
                  "line_ids": [Command.create(line) for line in lines],
                  "address_values": {name: found.get(name) or False
                                     for name, *_rest in ADDRESS_PARTS}}
        if status and status != "ACTIVE":
            values["status_level"] = "danger" if status in STATUS_DANGER else "warning"
            values["status_warn"] = _(
                "По ЕГРЮЛ организация «%s». Проверьте, тот ли это контрагент.",
                partner._pmk_status_label(status))
        check = self.create(values)
        return {
            "type": "ir.actions.act_window",
            "name": _("Сверить по ИНН %s", inn),
            "res_model": self._name,
            "res_id": check.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
        }

    def action_apply(self):
        """Записать отмеченное одним write и заметку в ленту карточки."""
        self.ensure_one()
        allowed = {name for name, *_rest in CHECK_FIELDS}
        chosen = self.line_ids.filtered(
            lambda line: line.apply and line.field_name in allowed).sorted("sequence")
        if chosen:
            partner = self.partner_id
            values = {line.field_name: line.new for line in chosen}
            changes = ["%s: «%s» → «%s»" % (line.label, line.current or "пусто", line.new)
                       for line in chosen]
            if "pmk_legal_address" in values:
                parts = self._pmk_address_parts(partner)
                if parts:
                    values.update(parts)
                    labels = [label for name, label, _only_empty in ADDRESS_PARTS
                              if name in parts]
                    changes.append(_("%s — по выписке вместе с адресом", ", ".join(labels)))
            partner.write(values)
            changes = "; ".join(changes)
            self.partner_id.message_post(
                body=_("Сверено по ИНН %(inn)s: %(changes)s.", inn=self.inn, changes=changes),
                subtype_xmlid="mail.mt_note")
        return {"type": "ir.actions.act_window_close"}

    def _pmk_address_parts(self, partner):
        """Разложенный адрес из выписки, который запишется вместе с
        юридическим: код ФИАС — по выписке, остальное — только в пустое."""
        found = self.address_values or {}
        values = {}
        for name, _label, only_empty in ADDRESS_PARTS:
            new = found.get(name)
            if (name in partner._fields and new and not _same(partner[name], new)
                    and not (only_empty and partner[name])):
                values[name] = new
        return values


class PmkDadataCheckLine(models.TransientModel):
    _name = "pmk.dadata.check.line"
    _description = "Строка сверки реквизитов"
    _order = "sequence, id"

    check_id = fields.Many2one("pmk.dadata.check", required=True, ondelete="cascade")
    sequence = fields.Integer()
    field_name = fields.Char(readonly=True)
    label = fields.Char("Что", readonly=True)
    current = fields.Text("Сейчас", readonly=True)
    new = fields.Text("По ЕГРЮЛ", readonly=True)
    apply = fields.Boolean("Заменить")
