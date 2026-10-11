# -*- coding: utf-8 -*-
"""«Возможные дубли» контрагентов (шаг З-14, 10.10.2026).

Перенос таблицы заказов 08.10 (карточка 3) завёл 108 компаний, сравнивая
названия буквально: «МЕРИДИАН» и ООО «МЕРИДИАН», «БСМ-МОСТ» и ООО
«БСМ-МОСТ» стали двумя карточками, а «ТРУБНОЕ РЕШЕНИЕ» (159) — второй
карточкой филиала «ООО ПО «Трубное решение», филиал Хабаровск» (18) из
реестра поставщиков. Разбор боевой базы 10.10: 26 групп, 55 карточек.

ЭКРАН ПОКАЗЫВАЕТ, А НЕ ОБЪЕДИНЯЕТ. Кнопка «Возможные дубли» в списке
«Клиенты» собирает группы похожих карточек — одинаковый ИНН, одинаковый
ключ названия (tools/partner_keys.name_key), один корпоративный домен
почты или сайта — и открывает их списком. Объединяет человек: отмечает две
или три строки и нажимает «Объединить…» — открывается штатный мастер Odoo
«Объединить контакты» (base.partner.merge.automatic.wizard) с этими
карточками. Мастер переносит на оставшуюся карточку всё, что ссылается на
остальные (лиды, сделки, расчёты, заказы, письма в ленте), и удаляет их.
Автоматически не объединяется ничего.

Какая карточка останется, по умолчанию решает мастер: «активная, самая
свежая» — для 18/159 это была бы 159 с названием из таблицы. Здесь по
умолчанию остаётся та, к которой привязано больше документов (лиды и
сделки, заказы, расчёты); при равенстве — штатный порядок. Мастер даёт
выбрать другую.

Строки экрана — временные (TransientModel) и свои у каждого: кнопка
пересобирает их заново. После объединения строки этих карточек убирает
мастер (models/partner_merge.py, _merge); удалённая другим путём карточка
уносит свою строку сама (ondelete="cascade").

Права: экран — всем, кто работает с продажами (наблюдать может каждый);
кнопка «Объединить…» и сам мастер — только «Управление контактами»
(base.group_partner_manager, у завода — администратор): ядро даёт мастер
только этой группе.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import partner_keys

MERGE_MIN, MERGE_MAX = 2, 3  # мастер ядра объединяет не больше трёх


class ResPartnerDuplicates(models.Model):
    _inherit = "res.partner"

    @api.model
    def _pmk_duplicate_groups(self):
        """[(подпись, [(контрагент, причина)])] — группы похожих карточек.

        В сравнении — организации и физлица верхнего уровня (контакт внутри
        компании дублем компании не бывает), архив тоже: реестр поставщиков
        лежит там. Свои организации, их контакты и пользователи — нет."""
        Partner = self.with_context(active_test=False)
        own = self._pmk_own_partner_ids()
        public = self._pmk_public_domains() | self._pmk_own_domains()
        partners = Partner.search([("parent_id", "=", False), ("id", "not in", list(own))])
        children = Partner.search([("parent_id", "in", partners.ids)])
        child_domains = {}
        for child in children:
            child_domains.setdefault(child.parent_id.id, set()).update(child._pmk_domains())
        rows = []
        for partner in partners:
            domains = partner._pmk_domains() | child_domains.get(partner.id, set())
            rows.append({
                "id": partner.id,
                "name": partner_keys.name_key(partner.name),
                "inn": partner_keys.inn_of(partner.vat),
                "domains": {domain for domain in domains if domain not in public},
            })
        groups = []
        for label, lines in partner_keys.duplicate_groups(rows):
            groups.append((label, [(Partner.browse(pid), reason) for pid, reason in lines]))
        return groups

    @api.model
    def action_pmk_duplicates(self, *_args):
        """Кнопка «Возможные дубли»: пересобрать свои строки и открыть их.

        *_args: кнопка в шапке списка (type="object") передаёт отмеченные
        строки списка — они здесь не нужны, но без *_args вызов падал
        «takes 1 positional argument but 2 were given» (найдено на копии 11.10)."""
        Duplicate = self.env["pmk.partner.duplicate"]
        Duplicate.search([("create_uid", "=", self.env.uid)]).unlink()
        values = []
        for number, (label, lines) in enumerate(self._pmk_duplicate_groups(), start=1):
            for partner, reason in lines:
                values.append({
                    "group_no": number,
                    # Заголовок группы в списке — само значение (имя поля
                    # группировки Odoo не показывает), поэтому слово здесь.
                    "group_label": _("Похожие: %s", label),
                    "partner_id": partner.id,
                    "reason": reason,
                })
        Duplicate.create(values)
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pmk_partner.action_partner_duplicates")
        action["domain"] = [("create_uid", "=", self.env.uid)]
        return action


class PmkPartnerDuplicate(models.TransientModel):
    _name = "pmk.partner.duplicate"
    _description = "Возможный дубль контрагента"
    _order = "group_no, partner_id"

    group_no = fields.Integer("Группа", readonly=True)
    group_label = fields.Char("Похожие", readonly=True)
    reason = fields.Char("Причина", readonly=True,
                         help="Что совпало с другими карточками группы: название "
                              "(без ООО/ИП, кавычек и «филиал …»), ИНН или домен почты.")
    partner_id = fields.Many2one(
        "res.partner", "Контрагент", required=True, readonly=True, ondelete="cascade",
        context={"active_test": False})
    vat = fields.Char("ИНН", related="partner_id.vat")
    city = fields.Char("Город", related="partner_id.city")
    email = fields.Char("Эл. почта", related="partner_id.email")
    website = fields.Char("Сайт", related="partner_id.website")
    partner_create_date = fields.Datetime("Заведён", related="partner_id.create_date")
    pmk_deal_count = fields.Integer("Сделок", related="partner_id.pmk_deal_count")
    partner_archived = fields.Char("В архиве", compute="_compute_partner_archived")

    @api.depends("partner_id.active")
    def _compute_partner_archived(self):
        for row in self:
            row.partner_archived = "Да" if row.partner_id and not row.partner_id.active else ""

    # ------------------------------------------------------------------
    # объединение — только штатным мастером и только руками
    # ------------------------------------------------------------------
    @api.model
    def _pmk_documents(self, partners):
        """Сколько документов привязано к каждой карточке (с контактами):
        лиды и сделки (и архивные), заказы, расчёты."""
        counts = dict.fromkeys(partners.ids, 0)
        sources = [("crm.lead", "partner_id"), ("sale.order", "partner_id"),
                   ("pmk.metal.spec", "partner_id"), ("purchase.order", "partner_id")]
        for model, field in sources:
            if model not in self.env or field not in self.env[model]._fields:
                continue
            Model = self.env[model].sudo().with_context(active_test=False)
            for partner in partners:
                counts[partner.id] += Model.search_count(
                    [(field, "child_of", partner.id)])
        return counts

    def action_pmk_merge(self):
        partners = self.partner_id.with_context(active_test=False)
        if not MERGE_MIN <= len(partners) <= MERGE_MAX:
            raise UserError(_(
                "Отметьте две или три карточки одной группы: штатный мастер "
                "объединяет не больше трёх за раз. Отмечено карточек: %s.",
                len(partners)))
        if len(set(self.mapped("group_no"))) > 1:
            # Промах галочкой в длинном списке: мастер необратим (исходные
            # карточки удаляет), а целевая в нём уже выбрана — предупреждаем.
            labels = ", ".join(dict.fromkeys(self.sorted("group_no").mapped("group_label")))
            raise UserError(_(
                "Отмечены карточки из разных групп (%s). Объединяйте карточки "
                "одной группы — снимите лишние отметки.", labels))
        if not self.env.user.has_group("base.group_partner_manager"):
            raise UserError(_(
                "Объединяет карточки администратор (право «Управление "
                "контактами»). Покажите ему эту группу."))
        counts = self._pmk_documents(partners)
        best = max(counts.values())
        leaders = [pid for pid, count in counts.items() if count == best]
        dst = leaders[0] if best and len(leaders) == 1 else False
        action = self.env["ir.actions.act_window"]._for_xml_id("base.action_partner_merge")
        action["name"] = _("Объединить контакты")
        action["context"] = {
            "active_model": "res.partner",
            "active_ids": partners.ids,
            "active_id": partners.ids[0],
            "active_test": False,
            "pmk_merge_dst_id": dst,
        }
        return action

    def action_pmk_open_partner(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "views": [[False, "form"]],
            "target": "current",
        }
