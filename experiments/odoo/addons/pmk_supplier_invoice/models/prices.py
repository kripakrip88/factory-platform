# -*- coding: utf-8 -*-
"""Строки счёта → позиции и цены; «Обновить цены» — запись цен поставщика.

Цена — С НДС, в единице карточки, как у прайсов (pmk_bridge/tools/load_prices.py):
прокат — руб за метр, лист в м² — руб за лист габарита (единица «Лист WxL»). Запись —
тот же ряд цен, что ведёт загрузчик прайсов: (поставщик, позиция, уровень 1), новая
цена с датой счёта закрывает прошлый период. Позицию, выбранную вручную, модуль
запоминает для поставщика (pmk.supplier.invoice.alias) — второй раз не спросит.
"""
import datetime
import re

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_bridge.tools.grades import BASE_GRADE, grade_family, map_grade

from ..tools import match as M
from .invoice import DIFF_WARN_PCT

TON_UNITS = {"т", "тн", "тонн", "тонна", "теор.т", "теорт", "т.", "тн."}
KG_UNITS = {"кг", "кг."}
M_UNITS = {"м", "м.", "п.м", "пм", "п.м.", "мп", "м.п."}
PCS_UNITS = {"шт", "шт."}
PCS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*шт", re.I)


def _unit(text):
    return re.sub(r"\s+", "", (text or "").lower())


def invoice_grade(text):
    """Марка из счёта: «Ст3пс/сп5» → Ст3пс (общий словарь её целиком не знает)."""
    text = (text or "").strip()
    if not text:
        return None
    return map_grade(text) or map_grade(re.split(r"[/\\,;\s]+", text)[0])


def _key(text):
    """Ключ запоминания: строка счёта без длины, количества и регистра."""
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:250]


class SupplierInvoiceAlias(models.Model):
    _name = "pmk.supplier.invoice.alias"
    _description = "Счёт поставщика — запомненная позиция"

    partner_id = fields.Many2one("res.partner", "Поставщик", required=True, index=True, ondelete="cascade")
    key = fields.Char("Строка счёта", required=True, index=True)
    product_tmpl_id = fields.Many2one("product.template", "Позиция", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Вариант", ondelete="set null")

    _sql_constraints = [("alias_uniq", "unique(partner_id, key)", "Строка уже запомнена.")]


class SupplierInvoiceLinePrices(models.Model):
    _inherit = "pmk.supplier.invoice.line"

    # ─── сопоставление ───────────────────────────────────────────────────
    def _pmk_match(self):
        matcher = None
        for line in self:
            if line.kind != "metal":
                line.write({"match_state": "skip", "apply": False, "match_note": _("услуга") if
                            line.kind == "service" else _("не металл")})
                continue
            alias = self.env["pmk.supplier.invoice.alias"].sudo().search([
                ("partner_id", "=", line.invoice_id.partner_id.id), ("key", "=", _key(line.name))], limit=1) \
                if line.invoice_id.partner_id else False
            if alias:
                line.write({"product_tmpl_id": alias.product_tmpl_id.id, "product_id": alias.product_id.id,
                            "match_state": "manual", "match_note": _("как в прошлый раз")})
                line._pmk_price()
                continue
            if matcher is None:
                matcher = M.matcher(self.env)
            try:
                found = M.match_line(self.env, matcher, line.name, line.catalog_name, line.grade_text)
                variant, uom = line._pmk_target(found["tmpl"], invoice_grade(line.grade_text) or found["grade"],
                                                found["is_sheet"], found["item"])
            except M.MatchError as exc:
                line.write({"match_state": "none", "product_tmpl_id": False, "product_id": False,
                            "apply": False, "match_note": "%s%s" % (exc.kind, (": " + exc.detail) if exc.detail else "")})
                continue
            line.write({"product_tmpl_id": found["tmpl"].id, "product_id": variant.id, "uom_id": uom.id if uom else False,
                        "match_state": "matched", "match_note": False})
            if not found["is_sheet"] and not line.grade_text:
                line.match_note = _("марки в счёте нет — %s, как у цен поставщика") % line._pmk_grade()
            line._pmk_price()

    def _pmk_target(self, tmpl, grade, is_sheet, item=None):
        """Вариант марки и единица цены.

        Цена из счёта ложится в ТОТ ЖЕ ряд, где уже лежат цены этого поставщика той же
        марки (Ст3сп = Ст3пс, grade_family): у Металлсервиса трубы — на варианте Ст3пс,
        уголок — на Ст3сп. Иначе рядом остался бы второй ряд, и старая цена прайса
        действовала бы дальше. Ряда нет — как загрузчик прайсов (resolve_linear, №313):
        вариант марки; без характеристики марки — шаблон, только для обычной стали."""
        Product = self.env["product.product"]
        grade = grade or BASE_GRADE
        family = grade_family(grade)
        uom = None
        if is_sheet and tmpl._pmk_is_sqm():
            gab = self._pmk_gabarit()
            uom = self.env["uom.uom"]._pmk_sheet_uom(gab) if gab else None
            if not uom:
                raise M.MatchError("габарит листа не опознан", "«%s» — нужен габарит 1500x6000 и т. п." % (
                    self.catalog_name or self.name))
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        partner = self.invoice_id.partner_id
        if partner:
            def grade_of(info):
                names = info.product_id.product_template_attribute_value_ids.filtered(
                    lambda v: v.attribute_id == attr).mapped("name")
                return names[0] if names else None
            series = tmpl.seller_ids.filtered(lambda s: s.partner_id == partner and (
                (grade_of(s) in family) or (grade_of(s) is None and BASE_GRADE in family))
                and (not uom or s.product_uom_id == uom))
            if series:
                return series.sorted(lambda s: (s.date_start or datetime.date.min, s.id))[-1:].product_id, uom
        has_line = bool(attr and tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr))
        if not has_line:
            if BASE_GRADE in family:
                return Product.browse(), uom
            raise M.MatchError("у карточки нет характеристики марки",
                               "%s — цена легла бы на обычную сталь" % grade)
        variant = tmpl._pmk_grade_variant(grade, create=False)
        if not variant and BASE_GRADE in family:
            variant = tmpl._pmk_grade_variant(BASE_GRADE, create=False)
        if not variant and tmpl._pmk_grade_value_exists(grade):
            # Марку из счёта заведём вариантом при записи (как загрузчик прайсов).
            return Product.browse(), uom
        if not variant:
            raise M.MatchError("варианта марки нет", "%s у карточки %s" % (grade, tmpl.default_code or tmpl.name))
        return variant, uom

    def _pmk_gabarit(self):
        for text in (self.catalog_name, self.name):
            nums = re.findall(r"\d+(?:[.,]\d+)?", (text or "").replace(",", "."))
            big = [n for n in nums if float(n) >= 500]
            if len(big) >= 2:
                return "%dx%d" % (float(big[0]), float(big[1]))
        return None

    def _pmk_reference(self):
        """Строка справочника под карточку (масса единицы)."""
        tmpl = self.product_tmpl_id
        for model in ("pmk.metal.profile", "pmk.metal.sheet"):
            rec = self.env[model].sudo().search([("product_tmpl_id", "=", tmpl.id)], limit=1)
            if rec:
                return rec
        return None

    def _pmk_grade(self):
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        names = self.product_id.product_template_attribute_value_ids.filtered(
            lambda v: v.attribute_id == attr).mapped("name")
        return names[0] if names else (invoice_grade(self.grade_text) or BASE_GRADE)

    def _pmk_pieces(self):
        """Штук в строке: единица «шт» или «Прим.» («4 шт», «26шт x 12м»). Нет — 0."""
        if _unit(self.unit) in PCS_UNITS:
            return self.qty or 0.0
        found = PCS_RE.search(self.note or "")
        return float(found.group(1).replace(",", ".")) if found else 0.0

    # ─── цена ────────────────────────────────────────────────────────────
    def _pmk_price(self):
        """Цена в единице карточки и сравнение с текущей ценой поставщика."""
        for line in self:
            tmpl = line.product_tmpl_id
            ref = line._pmk_reference() if tmpl else None
            if not tmpl or not ref:
                line.write({"apply": False, "warning": _("позиция не из справочника проката и листа")})
                continue
            is_sheet = ref._name == "pmk.metal.sheet"
            unit = _unit(line.unit)
            warn = []
            tonnes = line.qty if unit in TON_UNITS else (line.qty / 1000.0 if unit in KG_UNITS else 0.0)
            pieces = line._pmk_pieces()
            if is_sheet:
                gab = line._pmk_gabarit()
                if tmpl._pmk_is_sqm():
                    w, l = [float(x) for x in gab.split("x")] if gab else (0, 0)
                    mass_ref = (ref.mass_per_sqm or 0.0) * w * l / 1e6
                    uom = line.env["uom.uom"]._pmk_sheet_uom(gab) if gab else None
                else:
                    mass_ref = (line.product_id or tmpl).weight
                    uom = None
                # Масса листа — поставщика (тонны счёта / штуки), как у прайсов: Металлсервис
                # 26.10 выставил 4 листа 3×1500×6000 на 0,872 т = 218 кг, а по справочнику 211,95.
                amount_of = pieces
                what = "кг/лист"
            else:
                mass_ref = ref.mass_per_meter or 0.0
                # Метры: из счёта, иначе штуки × длина хлыста («4 шт», дл 6 м).
                amount_of = line.metres or (pieces * line.length_mm / 1000.0 if pieces and line.length_mm else 0.0)
                what = "кг/м"
                uom = None
            mass = mass_ref
            if tonnes and amount_of:
                mass_inv = tonnes * 1000.0 / amount_of
                try:
                    M.check_mass(mass_inv, mass_ref, what)
                    mass = mass_inv       # поставщик считает по своей массе (как у прайсов)
                except M.MatchError as exc:
                    warn.append("%s: %s" % (exc.kind, exc.detail))
            if unit in TON_UNITS:
                price_ton = line.price
            elif unit in KG_UNITS:
                price_ton = line.price * 1000.0
            elif unit in M_UNITS and not is_sheet and mass:
                price_ton = line.price / mass * 1000.0
            else:
                line.write({"apply": False, "warning": _("цена за «%s» — пересчитать в тонну не из чего") % (line.unit or "?")})
                continue
            new_price = price_ton * mass / 1000.0 if mass else 0.0
            if not new_price:
                line.write({"apply": False, "warning": _("нет массы позиции")})
                continue
            inv = line.invoice_id
            date = inv.date or fields.Date.context_today(line)
            grade = line._pmk_grade() if not (is_sheet and not tmpl._pmk_is_sqm()) else None
            seller = tmpl._pmk_find_seller(date, supplier=inv.partner_id or None, uom=uom,
                                           grade=grade) if inv.partner_id else line.env["product.supplierinfo"]
            # Текущая — в той же единице, что новая. price_discounted приводит к единице карточки
            # (м² у листа), а новая цена листа — за «Лист 1500×6000»: 26.10 вышло «+755 %» вместо −2 %.
            target = uom or (line.product_id or tmpl).uom_id
            if seller:
                src = seller.product_uom_id or (seller.product_id or tmpl).uom_id
                current = src._compute_price(seller.price, target) * (1 - (seller.discount or 0.0) / 100.0)
            else:
                current = 0.0
            diff = (new_price / current - 1.0) * 100.0 if current else 0.0
            if current and abs(diff) > DIFF_WARN_PCT:
                warn.append(_("цена отличается от текущей на %+.0f %%") % diff)
            if not inv.partner_id:
                warn.append(_("поставщик не определён"))
            line.write({
                "price_ton": price_ton, "mass_unit": mass, "new_price": new_price, "uom_id": uom.id if uom else False,
                "current_price": current, "current_date": seller.date_start if seller else False,
                "current_price_ton": current / mass * 1000.0 if current and mass else 0.0,
                "diff_pct": diff, "warning": "; ".join(warn) or False,
                "apply": not warn,
            })

    @api.onchange("product_tmpl_id")
    def _onchange_product_tmpl_id(self):
        for line in self:
            if line.product_tmpl_id and line.product_id.product_tmpl_id != line.product_tmpl_id:
                line.product_id = False

    def write(self, vals):
        res = super().write(vals)
        # Выбрали позицию вручную — пересчитать цену и пометить «выбрано вручную».
        if "product_tmpl_id" in vals and not self.env.context.get("pmk_si_internal") and vals.get("product_tmpl_id") \
                and "match_state" not in vals:
            for line in self.with_context(pmk_si_internal=True):
                if line.kind == "metal":
                    try:
                        variant, uom = line._pmk_target(line.product_tmpl_id, invoice_grade(line.grade_text),
                                                        bool(line.product_tmpl_id._pmk_is_sqm()))
                        if not line.product_id:
                            line.product_id = variant
                        line.write({"match_state": "manual", "match_note": _("выбрано вручную")})
                        line._pmk_price()
                    except M.MatchError as exc:
                        line.write({"apply": False, "warning": "%s: %s" % (exc.kind, exc.detail)})
        return res


class SupplierInvoicePrices(models.Model):
    _inherit = "pmk.supplier.invoice"

    def write(self, vals):
        res = super().write(vals)
        # Сменили поставщика у распознанного счёта — его цены другие: сопоставить заново.
        if "partner_id" in vals and not self.env.context.get("pmk_si_internal"):
            for inv in self.filtered(lambda i: i.state == "review"):
                inv.line_ids._pmk_match()
        return res

    def action_rematch(self):
        for inv in self:
            inv.line_ids._pmk_match()
        return True

    def action_apply_prices(self):
        """«Обновить цены»: строки с галочкой — цены поставщика с датой счёта."""
        self.ensure_one()
        if self.state not in ("review",):
            raise UserError(_("Записать цены можно у распознанного счёта, который ждёт проверки."))
        if not self.partner_id:
            raise UserError(_("Укажите поставщика — без него цену записать некуда."))
        if not self.date:
            raise UserError(_("Укажите дату счёта — с неё действует цена."))
        lines = self.line_ids.filtered(lambda l: l.apply and l.kind == "metal")
        if not lines:
            raise UserError(_("Нет строк с галочкой «Записать»."))
        bad = lines.filtered(lambda l: not l.product_tmpl_id or not l.new_price)
        if bad:
            raise UserError(_("Без позиции или цены: %s") % ", ".join(bad.mapped("name"))[:300])
        Alias = self.env["pmk.supplier.invoice.alias"].sudo()
        done = []
        for line in lines:
            tmpl, variant = line.product_tmpl_id, line.product_id
            grade = invoice_grade(line.grade_text)
            if not variant and grade and BASE_GRADE not in grade_family(grade) \
                    and tmpl._pmk_grade_value_exists(grade):
                variant = tmpl._pmk_grade_variant(grade, create=True)
                line.product_id = variant
            rec = self._pmk_upsert(tmpl, variant, line)
            line.supplierinfo_id = rec
            if line.match_state == "manual":
                key = _key(line.name)
                old = Alias.search([("partner_id", "=", self.partner_id.id), ("key", "=", key)])
                vals = {"product_tmpl_id": tmpl.id, "product_id": variant.id or False}
                old.write(vals) if old else Alias.create(dict(vals, partner_id=self.partner_id.id, key=key))
            done.append(line)
        # Выбор поставщика запоминается самим счётом: следующий счёт с этим ИНН возьмёт
        # того же поставщика (recognize._find_partner). ИНН карточкам не пишем — у
        # фирмы бывает вторая карточка с тем же ИНН (из МойСклада).
        self.write({"state": "applied", "applied_on": fields.Datetime.now(), "applied_by": self.env.uid})
        rows = Markup("").join(Markup("<li>%s — %s ₽ (%s)</li>") % (
            l.product_tmpl_id.display_name, ("%.2f" % l.new_price).replace(".", ","),
            ("%+.1f %%" % l.diff_pct).replace(".", ",") if l.current_price else _("новая")) for l in done)
        self.message_post(body=Markup("%s<ul>%s</ul>") % (
            escape(_("Цены записаны с %s:") % self.date.strftime("%d.%m.%Y")), rows), subtype_xmlid="mail.mt_note")
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": _("Цены записаны — позиций: %d.") % len(done), "type": "success",
                           "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def _pmk_upsert(self, tmpl, variant, line):
        """Ряд цен поставщика (как load_prices.upsert_supplierinfo): уровень 1, дата счёта.
        Счёт старше последней цены ряда — встаёт в свой период, не перекрывая новую."""
        SI = self.env["product.supplierinfo"].sudo()
        domain = [("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id),
                  ("product_id", "=", variant.id if variant else False), ("sequence", "=", 1)]
        if line.uom_id:
            domain.append(("product_uom_id", "=", line.uom_id.id))
        series = SI.search(domain, order="date_start")
        date = self.date
        vals = {
            "partner_id": self.partner_id.id, "product_tmpl_id": tmpl.id,
            "product_id": variant.id if variant else False, "sequence": 1, "min_qty": 0.0,
            "price": line.new_price, "date_start": date, "product_name": line.name[:250],
            "currency_id": self.env.company.currency_id.id,
            "product_uom_id": (line.uom_id or (variant or tmpl).uom_id).id,
        }
        if "pmk_bar_length_mm" in SI._fields:
            length = line.length_mm or M.bar_length_mm(line.name)
            if length:
                vals["pmk_bar_length_mm"] = length
        same = series.filtered(lambda r: r.date_start == date)
        if same:
            same[0].write(vals)
            return same[0]
        later = series.filtered(lambda r: r.date_start and r.date_start > date)
        if later:
            vals["date_end"] = later[0].date_start - datetime.timedelta(days=1)
        for rec in series.filtered(lambda r: (not r.date_start or r.date_start < date)
                                   and (not r.date_end or r.date_end >= date)):
            rec.date_end = date - datetime.timedelta(days=1)
        return SI.create(vals)
