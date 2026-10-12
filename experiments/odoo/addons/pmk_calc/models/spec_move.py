# -*- coding: utf-8 -*-
"""Изделия «Металлоизделий» — в доборку или вентзонты расчёта (Антон 13.10.2026).

В расчёте по счёту из МоегоСклада доборки и зонты приходят строками изделий.
Инженер отмечает строки переключателем «Перенести» и жмёт «В доборки» / «В
вентзонты»: строка уходит в калькулятор этого расчёта (категория включается,
черновик заводится) с названием, количеством и ценой клиента. Из названия
берутся длина планки («L=2000», «2000 мм»), размер шахты («500х1000») и цвет
(«RAL 8017»). Чего нет в названии — подставляется и пишется в историю расчёта.
Обратно — «Вернуть в металлоизделия» на строке доборки или зонта.

Перетаскивание мышкой не делали: вкладки калькуляторов скрыты, пока открыта
«Металлоизделия», и тащить пришлось бы на заголовок вкладки.
"""
import re

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_calc.tools import dobor_cut as C

DOBOR_RX = r"отлив|планк|добор|капельн|кон[её]к|ендов|нащельник|откос|парапет|примыкан|желоб|жёлоб|фартук"
VENT_RX = r"зонт|\bвш\b|дефлектор"
RAL_RX = re.compile(r"ral\s*-?\s*(\d{4})", re.I)
# «500х1000», «550мм x700мм»; у зонта из МоегоСклада — «Зонт 850мм x 1000мм (шахта: 550мм
# x700мм)»: в калькуляторе размер — шахты, его и берём, если он назван.
SIZE_RX = re.compile(r"(\d{2,4})\s*(?:мм)?\s*[хx×*]\s*(\d{2,4})", re.I)
SHAFT_RX = re.compile(r"шахт\w*\s*:?\s*(\d{2,4})\s*(?:мм)?\s*[хx×*]\s*(\d{2,4})", re.I)
LEN_RX = re.compile(r"(?:\bl\s*=?\s*|длин\w*\s*)(\d{3,4})|(\d{3,4})\s*мм", re.I)


def move_hint(name):
    low = (name or "").lower()
    if re.search(VENT_RX, low):
        return "vent"
    if re.search(DOBOR_RX, low):
        return "dobor"
    return False


def parse_ral(name):
    m = RAL_RX.search(name or "")
    return m.group(1) if m else False


def parse_size(name):
    m = SHAFT_RX.search(name or "") or SIZE_RX.search(name or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def parse_length(name):
    for m in LEN_RX.finditer(name or ""):
        value = int(m.group(1) or m.group(2))
        if value >= 200:
            return value
    return 0


class MetalSpecProductMove(models.Model):
    _inherit = "pmk.metal.spec.product"

    pmk_pick = fields.Boolean("Перенести", copy=False,
                              help="Отметить, чтобы перенести изделие в доборку или вентзонты расчёта.")
    pmk_move_hint = fields.Selection([("dobor", "похоже на доборку"), ("vent", "похоже на вентзонт")],
                                     "Подсказка", compute="_compute_pmk_move_hint")

    @api.depends("name")
    def _compute_pmk_move_hint(self):
        for product in self:
            product.pmk_move_hint = move_hint(product.name)

    def _pmk_price(self):
        """Цена клиенту за шт — поле моста (pmk_bridge), если он стоит."""
        self.ensure_one()
        return self["price_customer_unit"] if "price_customer_unit" in self._fields else 0.0


class MetalSpecMove(models.Model):
    _inherit = "pmk.metal.spec"

    pmk_pick_count = fields.Integer("Отмечено изделий", compute="_compute_pmk_pick_count")

    @api.depends("product_ids.pmk_pick")
    def _compute_pmk_pick_count(self):
        for spec in self:
            spec.pmk_pick_count = len(spec.product_ids.filtered("pmk_pick"))

    def _pmk_picked(self):
        self.ensure_one()
        picked = self.product_ids.filtered("pmk_pick")
        if not picked:
            raise UserError("Отметьте изделия переключателем «Перенести».")
        return picked

    def _pmk_coating(self, name, notes):
        Coating = self.env["pmk.dobor.coating"]
        ral = parse_ral(name)
        coating = ral and Coating.search([("ral_code", "=", ral)], limit=1)
        if not coating and re.search(r"цинк|оцинк", (name or "").lower()):
            coating = Coating.search([("ral_code", "in", (False, "")), ("name", "ilike", "цинк")], limit=1)
        if not coating:
            coating = Coating.search([("ral_code", "=", "8017")], limit=1) or Coating.search([], limit=1)
            notes.append("%s — цвет %s (в названии не найден, проверьте)" % (name, coating.name))
        return coating

    def _pmk_log_move(self, what, picked_names, notes):
        body = Markup("Перенесено в %s: %s.") % (what, ", ".join(picked_names))
        if notes:
            body += Markup("<br/>") + Markup("<br/>").join(escape(n) for n in notes)
        self.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_note")

    def action_pmk_pick_to_dobor(self):
        self.ensure_one()
        picked = self._pmk_picked()
        if not self.cat_dobor:
            self.cat_dobor = True
        order = self.dobor_order_ids[:1]
        notes, lines = [], []
        for product in picked:
            length = parse_length(product.name)
            if not length:
                length = C.MAX_LEN
                notes.append("%s — длина не найдена, поставлено %d мм" % (product.name, length))
            elif length > C.MAX_LEN:
                notes.append("%s — длина %d больше %d (гильотина и гибка), поставлено %d" % (
                    product.name, length, C.MAX_LEN, C.MAX_LEN))
                length = C.MAX_LEN
            coating = self._pmk_coating(product.name, []) if (
                parse_ral(product.name) or re.search(r"цинк", product.name.lower())) else False
            lines.append((0, 0, {"title": product.name[:250], "plank_length": float(length),
                                 "qty": product.qty or 1, "price_unit": product._pmk_price(),
                                 "coating_id": coating.id if coating else False}))
        order.write({"line_ids": lines})
        names = picked.mapped("name")
        picked.unlink()
        self._pmk_log_move("доборку %s" % order.name, names, notes + [
            "Профиль доборки — нарисовать в калькуляторе %s." % order.name])
        return True

    def action_pmk_pick_to_vent(self):
        self.ensure_one()
        picked = self._pmk_picked()
        if not self.cat_vent:
            self.cat_vent = True
        order = self.vent_order_ids[:1]
        notes, lines = [], []
        for product in picked:
            width, length = parse_size(product.name)
            if not width:
                notes.append("%s — размер шахты не найден, впишите" % product.name)
            lines.append((0, 0, {"width": width, "length": length, "qty": product.qty or 1,
                                 "price_unit": product._pmk_price(),
                                 "coating_id": self._pmk_coating(product.name, notes).id}))
        order.write({"line_ids": lines})
        names = picked.mapped("name")
        picked.unlink()
        self._pmk_log_move("вентзонты %s" % order.name, names, notes)
        return True


class DoborLineBack(models.Model):
    _inherit = "pmk.dobor.order.line"

    def action_pmk_back_to_metal(self):
        """Строка доборки — обратно изделием в «Металлоизделия» своего расчёта."""
        for line in self:
            spec = line.order_id.spec_id
            if not spec:
                raise UserError("Доборка не привязана к расчёту — возвращать некуда.")
            vals = {"name": line.title or line.display_name, "qty": line.qty or 1}
            if "price_customer_unit" in self.env["pmk.metal.spec.product"]._fields:
                vals["price_customer_unit"] = line.price_unit
            spec.write({"product_ids": [(0, 0, vals)], "cat_metal": True})
            line.unlink()
        return True


class VentLineBack(models.Model):
    _inherit = "pmk.vent.hood"

    def action_pmk_back_to_metal(self):
        for line in self:
            spec = line.order_id.spec_id
            if not spec:
                raise UserError("Заказ вентзонтов не привязан к расчёту — возвращать некуда.")
            name = "Зонт %s×%s, %s" % (line.width or "?", line.length or "?", line.coating_id.name or "")
            vals = {"name": name.strip(", "), "qty": line.qty or 1}
            if "price_customer_unit" in self.env["pmk.metal.spec.product"]._fields:
                vals["price_customer_unit"] = line.price_unit
            spec.write({"product_ids": [(0, 0, vals)], "cat_metal": True})
            line.unlink()
        return True
