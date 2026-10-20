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

DOBOR_RX = r"отлив|планк|добор|капельн|карни[зц]|колпак|отбойн|сандрик|кон[её]к|ендов|нащельник|откос|парапет|примыкан|желоб|жёлоб|фартук"
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
    text = name or ""
    for m in LEN_RX.finditer(text):
        # «Колпак шириной 300 мм» — 300 это ширина, не длина планки.
        if re.search(r"ширин\w*\s*$", text[:m.start()].lower()):
            continue
        value = int(m.group(1) or m.group(2))
        if value >= 200:
            return value
    return 0


class MetalSpecProductMove(models.Model):
    _inherit = "pmk.metal.spec.product"

    pmk_pick = fields.Boolean("Перенести", copy=False,
                              help="Отметить, чтобы перенести изделие в доборку или вентзонты расчёта.")
    pmk_move_hint = fields.Selection([("dobor", "→ доборка"), ("vent", "→ вентзонт")],
                                     "Подсказка", compute="_compute_pmk_move_hint")

    @api.depends("name")
    def _compute_pmk_move_hint(self):
        for product in self:
            product.pmk_move_hint = move_hint(product.name)

    def action_pmk_copy(self):
        """«Копировать» (значок в строке, Антон 13.10.2026): копия изделия со всеми
        деталями — сразу под исходной."""
        for product in self:
            after = product.spec_id.product_ids.filtered(lambda p, s=product: p.sequence > s.sequence)
            for other in after:
                other.sequence += 1
            product.copy({"spec_id": product.spec_id.id, "sequence": product.sequence + 1})
        return True

    def _pmk_price(self):
        """Цена клиенту за шт — поле моста (pmk_bridge), если он стоит."""
        self.ensure_one()
        return self["price_customer_unit"] if "price_customer_unit" in self._fields else 0.0


class MetalSpecMove(models.Model):
    _inherit = "pmk.metal.spec"

    pmk_pick_count = fields.Integer("Отмечено изделий", compute="_compute_pmk_pick_count")
    pmk_hint_count = fields.Integer("С подсказкой", compute="_compute_pmk_pick_count")
    pmk_product_count = fields.Integer("Изделий в списке", compute="_compute_pmk_pick_count")

    @api.depends("product_ids.pmk_pick", "product_ids.name")
    def _compute_pmk_pick_count(self):
        for spec in self:
            spec.pmk_pick_count = len(spec.product_ids.filtered("pmk_pick"))
            spec.pmk_hint_count = len(spec.product_ids.filtered("pmk_move_hint"))
            spec.pmk_product_count = len(spec.product_ids)

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
        return self._pmk_move_dobor(self._pmk_picked())

    def action_pmk_pick_to_vent(self):
        self.ensure_one()
        return self._pmk_move_vent(self._pmk_picked())

    def action_pmk_pick_all(self):
        """«Выбрать всё» (Антон 13.10.2026): отметить все изделия «Перенести»."""
        self.product_ids.write({"pmk_pick": True})
        return True

    def action_pmk_pick_none(self):
        self.product_ids.write({"pmk_pick": False})
        return True

    # ------------------------------------------------------------ общее: строки списков
    # Список позиций расчёта: (поле строк, модель). Новый калькулятор — строка здесь,
    # ветки в _pmk_items / _pmk_put и пункт в меню «Перенести в» (static/src/js/pick_bar.js).
    PMK_SOURCES = {
        "metal": ("Конструкции", "pmk.metal.spec.product"),
        "dobor": ("Доборные элементы", "pmk.dobor.order.line"),
        "vent": ("Вентзонты", "pmk.vent.hood"),
    }

    def _pmk_lines(self, source):
        self.ensure_one()
        if source == "metal":
            return self.product_ids
        if source == "dobor":
            return self.dobor_order_ids.line_ids
        if source == "vent":
            return self.vent_order_ids.line_ids
        raise UserError("Неизвестный список: %s" % source)

    def _pmk_items(self, source, recs):
        """Строки списка → описания позиций для другого калькулятора."""
        items = []
        for rec in recs:
            if source == "metal":
                items.append({"name": rec.name, "qty": rec.qty or 1, "price": rec._pmk_price()})
            elif source == "dobor":
                items.append({"name": rec.title or rec.display_name, "qty": rec.qty or 1,
                              "price": rec.price_unit, "length": rec.plank_length,
                              "coating": rec.coating_id})
            else:
                name = "Зонт %s×%s, %s" % (rec.width or "?", rec.length or "?", rec.coating_id.name or "")
                items.append({"name": name.strip(", "), "qty": rec.qty or 1, "price": rec.price_unit,
                              "width": rec.width, "shaft_length": rec.length, "coating": rec.coating_id})
        return items

    def _pmk_put(self, target, items, notes):
        """Позиции — в калькулятор target этого расчёта (категория включается сама)."""
        self.ensure_one()
        if target == "metal":
            vals = []
            for it in items:
                v = {"name": it["name"][:250], "qty": it["qty"]}
                if "price_customer_unit" in self.env["pmk.metal.spec.product"]._fields:
                    v["price_customer_unit"] = it["price"]
                vals.append((0, 0, v))
            self.write({"product_ids": vals, "cat_metal": True})
            return "металлоизделия"
        if target == "dobor":
            if not self.cat_dobor:
                self.cat_dobor = True
            order = self.dobor_order_ids[:1]
            lines = []
            for it in items:
                length = it.get("length") or parse_length(it["name"])
                if not length:
                    length = C.MAX_LEN
                    notes.append("%s — длина не найдена, поставлено %d мм" % (it["name"], length))
                elif length > C.MAX_LEN:
                    notes.append("%s — длина %d больше %d (гильотина и гибка), поставлено %d" % (
                        it["name"], length, C.MAX_LEN, C.MAX_LEN))
                    length = C.MAX_LEN
                coating = it.get("coating") or (self._pmk_coating(it["name"], []) if (
                    parse_ral(it["name"]) or re.search(r"цинк", it["name"].lower())) else False)
                lines.append((0, 0, {"title": it["name"][:250], "plank_length": float(length),
                                     "qty": it["qty"], "price_unit": it["price"],
                                     "coating_id": coating.id if coating else False}))
            order.write({"line_ids": lines})
            notes.append("Профиль доборки — нарисовать в калькуляторе %s." % order.name)
            return "доборку %s" % order.name
        if target == "vent":
            if not self.cat_vent:
                self.cat_vent = True
            order = self.vent_order_ids[:1]
            lines = []
            for it in items:
                width, length = it.get("width"), it.get("shaft_length")
                if not width:
                    width, length = parse_size(it["name"])
                if not width:
                    notes.append("%s — размер шахты не найден, впишите" % it["name"])
                coating = it.get("coating") or self._pmk_coating(it["name"], notes)
                lines.append((0, 0, {"width": width, "length": length, "qty": it["qty"],
                                     "price_unit": it["price"], "coating_id": coating.id}))
            order.write({"line_ids": lines})
            return "вентзонты %s" % order.name
        raise UserError("Неизвестный калькулятор: %s" % target)

    def pmk_bulk(self, source, action, target=None, ids=None):
        """Действие над отмеченными строками списка source (действия в заголовке колонки галочек, pick_bar.js):
        move (в target), copy, delete. ids — отмеченные строки; нет — по pmk_pick."""
        self.ensure_one()
        lines = self._pmk_lines(source)
        recs = lines.browse(ids or []) & lines if ids is not None else lines.filtered("pmk_pick")
        if not recs:
            raise UserError("Отметьте строки галочкой.")
        if action == "delete":
            recs.unlink()
        elif action == "copy":
            for rec in recs.sorted(lambda r: (r.sequence, r.id)):
                rec.action_pmk_copy()
        elif action == "move":
            if target == source or target not in self.PMK_SOURCES:
                raise UserError("Куда переносить?")
            notes = []
            names = [it["name"] for it in self._pmk_items(source, recs)]
            what = self._pmk_put(target, self._pmk_items(source, recs), notes)
            recs.unlink()
            self._pmk_log_move(what, names, notes)
        else:
            raise UserError("Неизвестное действие: %s" % action)
        self._pmk_lines(source).filtered("pmk_pick").write({"pmk_pick": False})
        return True

    def _pmk_move_dobor(self, picked):
        return self.pmk_bulk("metal", "move", "dobor", picked.ids)

    def _pmk_move_vent(self, picked):
        return self.pmk_bulk("metal", "move", "vent", picked.ids)


class LinePickCopy(models.AbstractModel):
    """Галочка «отмечено» и «Копировать» у строки доборки и зонта (13.10.2026)."""
    _name = "pmk.line.pick.mixin"
    _description = "Отметка и копирование строки калькулятора"

    pmk_pick = fields.Boolean("Отмечено", copy=False)

    def action_pmk_copy(self):
        """Копия строки — сразу под исходной, в том же калькуляторе."""
        for line in self:
            after = line.order_id.line_ids.filtered(lambda l, s=line: l.sequence > s.sequence)
            for other in after:
                other.sequence += 1
            line.copy({"order_id": line.order_id.id, "sequence": line.sequence + 1})
        return True

    def action_pmk_delete(self):
        self.unlink()
        return True


class DoborLineBack(models.Model):
    _name = "pmk.dobor.order.line"
    _inherit = ["pmk.dobor.order.line", "pmk.line.pick.mixin"]

    def action_pmk_back_to_metal(self):
        """Строка доборки — обратно изделием в «Конструкции» своего расчёта."""
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
    _name = "pmk.vent.hood"
    _inherit = ["pmk.vent.hood", "pmk.line.pick.mixin"]

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
