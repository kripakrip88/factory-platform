# -*- coding: utf-8 -*-
"""«Листов по факту» в техническом расчёте (шаг З-13, 09.10.2026).

Черновая раскладка (pmk_calc, «Лист раскладки») — верхняя оценка. Инженер
раскладывает детали в CypCut и знает точное число листов. Он вписывает его
в группу «лист × габарит» технического расчёта — и «Заявка на металл» берёт
это число вместо черновика (metal_request.py, _pmk_metal_rows). Пусто —
черновик, как раньше.

ЧИСЛО ИНЖЕНЕРА НЕ ГАСНЕТ. Правка детали гасит черновую раскладку группы
(spec_layout.py), но «Листов по факту» — не наша арифметика, а результат
CypCut: молча его не стираем. Плашка «Раскладка устарела» горит, а после
«Разложить листы» лента напоминает: «Листов по факту оставлено: N
(черновик теперь M) — сверьте с CypCut».

Поменяли число после заявки — та же плашка, что в З-4: черновик заявки —
«Состав изменился после заявки», отправленная / подтверждённая —
«Расходится с заявкой» (количество строки заявки сравнивается с тем, что
посчитал бы сбор сейчас).

В расчёте КП поля нет на экране: КП считается по черновику.
"""
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.pmk_calc.models.spec_layout import _plural


def _sheets_text(count):
    return "%s %s" % (count, _plural(count, "лист", "листа", "листов"))


class MetalSpecSheetGroupTech(models.Model):
    _inherit = "pmk.metal.spec.sheet.group"

    pmk_sheets_fact = fields.Integer(
        "Листов по факту", copy=False,
        help="Сколько листов вышло у инженера в CypCut. Заполнено — «Заявка на "
             "металл» берёт это число вместо черновой раскладки. Пусто (0) — "
             "черновик.")

    @api.constrains("pmk_sheets_fact")
    def _check_pmk_sheets_fact(self):
        for group in self:
            if group.pmk_sheets_fact < 0:
                raise ValidationError(_(
                    "«Листов по факту» не может быть меньше нуля: %s.", group.display_name))

    def write(self, vals):
        """Запись числа инженера — в ленту технического расчёта: по ней видно,
        откуда в заявке не черновое число."""
        before = {}
        if "pmk_sheets_fact" in vals:
            before = {group.id: group.pmk_sheets_fact for group in self}
        result = super().write(vals)
        if before:
            for group in self:
                old, new = before.get(group.id, 0), group.pmk_sheets_fact
                if old == new or group.spec_id.pmk_kind != "tech":
                    continue
                if new:
                    text = _("Листов по факту: %(group)s — %(fact)s (черновик %(draft)s). "
                             "«Заявка на металл» берёт это число.",
                             group=group.display_name, fact=_sheets_text(new),
                             draft=_sheets_text(group.sheets))
                else:
                    text = _("Листов по факту снято: %(group)s — в заявку идёт черновик "
                             "%(draft)s.", group=group.display_name,
                             draft=_sheets_text(group.sheets))
                group.spec_id._message_log(body=Markup("<p>%s</p>") % escape(text))
        return result

    def unlink(self):
        """Группа уходит, когда при «Разложить листы» её листа (или габарита)
        в расчёте больше нет. Число инженера уходит с ней — говорим в ленте."""
        for group in self.filtered(lambda g: g.pmk_sheets_fact and g.spec_id.pmk_kind == "tech"):
            group.spec_id._message_log(body=Markup("<p>%s</p>") % escape(_(
                "Листов по факту снято: %(group)s — %(fact)s; этого листа в расчёте "
                "больше нет.", group=group.display_name,
                fact=_sheets_text(group.pmk_sheets_fact))))
        return super().unlink()


class MetalSpecSheetFact(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_sheets_fact_map(self):
        """{id группы: листов по факту} — только у технического и только
        заполненные.

        По группе, а не по ключу «лист × габарит» (доработка З-13): число
        инженера покрывает только детали, разложенные в эту группу
        (metal_request.py, _pmk_fact_group). Деталь, добавленная после него,
        «больше листа» или без габарита идёт в заявку по весу — с заметкой
        «по весу», как без числа инженера."""
        self.ensure_one()
        if self.pmk_kind != "tech":
            return {}
        return {group.id: group.pmk_sheets_fact
                for group in self.layout_group_ids if group.pmk_sheets_fact}

    def _pmk_layout_log_tail(self):
        tail = super()._pmk_layout_log_tail()
        if self.pmk_kind != "tech":
            return tail
        for group in self.layout_group_ids.filtered("pmk_sheets_fact"):
            tail.append(_(
                "Листов по факту оставлено: %(group)s — %(fact)s (черновик теперь "
                "%(draft)s) — сверьте с CypCut.",
                group=group.display_name, fact=group.pmk_sheets_fact, draft=group.sheets))
        return tail


class MetalSpecSheetGroupTechBuy(models.Model):
    """«Купить» и «Металл к закупке» технического расчёта — по «Листов по
    факту» инженера, если вписано (15.10.2026; доля — pmk_bridge,
    _compute_pmk_layout_share). У расчёта КП — черновик."""
    _inherit = "pmk.metal.spec.sheet.group"

    def _pmk_sheets_buy(self):
        self.ensure_one()
        if self.spec_id.pmk_kind == "tech" and self.pmk_sheets_fact:
            return self.pmk_sheets_fact
        return super()._pmk_sheets_buy()


class MetalSpecLineTechBuy(models.Model):
    _inherit = "pmk.metal.spec.line"

    @api.depends("layout_group_id.pmk_sheets_fact", "spec_id.pmk_kind")
    def _compute_pmk_layout_share(self):
        return super()._compute_pmk_layout_share()


class MetalSpecSheetGroupTechOverview(models.Model):
    """«Листов по факту» во вкладке «Металл» одной таблицей (15.10.2026)."""
    _inherit = "pmk.metal.spec.sheet.group"

    def _pmk_overview_row(self):
        row = super()._pmk_overview_row()
        row["fact"] = self.pmk_sheets_fact or 0
        return row


class MetalSpecTechOverview(models.Model):
    _inherit = "pmk.metal.spec"

    def pmk_metal_set_sheets_fact(self, group_id, value):
        self.ensure_one()
        self.check_access("write")
        group = self.layout_group_ids.filtered(lambda g: g.id == group_id)
        if group:
            group.pmk_sheets_fact = max(0, int(value or 0))
        return True
