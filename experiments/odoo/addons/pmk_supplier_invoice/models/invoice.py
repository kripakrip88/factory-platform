# -*- coding: utf-8 -*-
"""Счёт поставщика (СП-00001) — распознанный счёт на оплату и цены из него.

Антон 25.10.2026: «распознавание входящих счетов на оплату от поставщиков… для
постоянного обновления цен». Решения: счета — с pmkpark@mail.ru; проверяет и жмёт
«Обновить цены» Голубенко; первые недели — только по кнопке. Цена из счёта — просто
новая цена поставщика с датой счёта (как прайс), скидку отдельно не считаем.

Жизнь документа: draft (загружен вручную, ещё не отдан) → queued (в очереди ассистента) → running → review (распознан, ждёт
проверки) → applied (цены записаны) | skipped (не счёт / повтор) | error.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Новый"), ("queued", "В очереди"), ("running", "Читается"), ("review", "Ждёт проверки"),
          ("applied", "Цены обновлены"), ("skipped", "Не счёт"), ("error", "Ошибка")]
LINE_KINDS = [("metal", "Металл"), ("service", "Услуга"), ("other", "Прочее")]
MATCH_STATES = [("matched", "Сопоставлено"), ("manual", "Выбрано вручную"), ("none", "Не найдено"),
                ("skip", "Не металл")]
DIFF_WARN_PCT = 15.0


class SupplierInvoice(models.Model):
    _name = "pmk.supplier.invoice"
    _description = "Счёт поставщика"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    state = fields.Selection(STATES, "Состояние", required=True, default="draft", index=True, tracking=True)
    partner_id = fields.Many2one("res.partner", "Поставщик", index=True, tracking=True)
    supplier_name = fields.Char("Поставщик в счёте")
    supplier_inn = fields.Char("ИНН поставщика")
    number = fields.Char("Номер счёта", index=True)
    date = fields.Date("Дата счёта", index=True)
    payer = fields.Char("Плательщик")
    amount_total = fields.Float("Итого с НДС", digits=(14, 2))
    amount_vat = fields.Float("НДС", digits=(14, 2))
    vat_rate = fields.Float("Ставка НДС, %", digits=(5, 2))
    message_id = fields.Many2one("mail.client.message", "Письмо", index=True, ondelete="set null")
    email_from = fields.Char("От кого")
    subject = fields.Char("Тема письма")
    file = fields.Binary("Счёт (файл)", attachment=True, copy=False)
    file_name = fields.Char("Имя файла")
    line_ids = fields.One2many("pmk.supplier.invoice.line", "invoice_id", "Строки", copy=False)
    reason = fields.Text("Пометки ассистента")
    error = fields.Text("Ошибка")
    data_json = fields.Text("Ответ ассистента (JSON)")
    usage_id = fields.Many2one("pmk.ai.usage", "Запрос ассистента", readonly=True)
    cost = fields.Float(related="usage_id.cost", string="Стоимость, $")
    started = fields.Datetime("Начато")
    seconds = fields.Float("Секунд", digits=(8, 1))
    applied_on = fields.Datetime("Цены записаны", readonly=True, copy=False)
    applied_by = fields.Many2one("res.users", "Записал", readonly=True, copy=False)

    line_count = fields.Integer("Строк", compute="_compute_summary")
    apply_count = fields.Integer("К записи", compute="_compute_summary")
    problem_count = fields.Integer("Требуют внимания", compute="_compute_summary")
    diff_pct = fields.Float("Разница, %", compute="_compute_summary", digits=(6, 1),
                            help="Средняя разница цен строк к записи против текущих цен поставщика, по сумме.")
    diff_text = fields.Char("Против текущих цен", compute="_compute_summary")

    _sql_constraints = [("message_uniq", "unique(message_id)", "Письмо уже разобрано как счёт поставщика.")]

    @api.depends("line_ids.apply", "line_ids.match_state", "line_ids.warning", "line_ids.diff_pct",
                 "line_ids.amount")
    def _compute_summary(self):
        for inv in self:
            lines = inv.line_ids
            metal = lines.filtered(lambda l: l.kind == "metal")
            inv.line_count = len(lines)
            inv.apply_count = len(metal.filtered("apply"))
            inv.problem_count = len(metal.filtered(lambda l: l.match_state == "none" or l.warning))
            compared = metal.filtered(lambda l: l.apply and l.current_price)
            weight = sum(compared.mapped("amount")) or 0.0
            inv.diff_pct = (sum(l.diff_pct * l.amount for l in compared) / weight) if weight else 0.0
            inv.diff_text = ("%+.1f %%" % inv.diff_pct).replace(".", ",") if compared else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.supplier.invoice") or "Черновик"
        return super().create(vals_list)

    def _compute_display_name(self):
        for inv in self:
            bits = [inv.name]
            if inv.number:
                bits.append("№ %s" % inv.number)
            inv.display_name = " · ".join(bits)

    def action_recognize(self):
        """«Распознать заново» / загруженный вручную файл — в очередь ассистента."""
        for inv in self:
            if inv.state == "applied":
                raise UserError(_("Цены из %s уже записаны — распознавать заново нельзя.") % inv.name)
            if not inv.file and not inv.message_id:
                raise UserError(_("Прикрепите файл счёта (PDF, картинку или Excel)."))
        self.line_ids.unlink()
        self.write({"state": "queued", "error": False, "reason": False})
        return True

    def action_skip(self):
        self.filtered(lambda i: i.state != "applied").write({"state": "skipped"})
        return True


class SupplierInvoiceLine(models.Model):
    _name = "pmk.supplier.invoice.line"
    _description = "Строка счёта поставщика"
    _order = "invoice_id, sequence, id"

    invoice_id = fields.Many2one("pmk.supplier.invoice", "Счёт", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("№", default=10)
    name = fields.Char("Строка счёта", required=True)
    unit = fields.Char("Ед.")
    qty = fields.Float("Кол-во", digits=(14, 3))
    price = fields.Float("Цена в счёте", digits=(14, 2))
    amount = fields.Float("Сумма", digits=(14, 2))
    note = fields.Char("Прим.")
    kind = fields.Selection(LINE_KINDS, "Вид", default="metal", required=True)
    catalog_name = fields.Char("По справочнику (ассистент)")
    grade_text = fields.Char("Марка в счёте")
    length_mm = fields.Float("Длина хлыста, мм", digits=(10, 0))
    metres = fields.Float("Погонных метров", digits=(12, 2))

    product_tmpl_id = fields.Many2one("product.template", "Позиция в системе", index=True)
    product_id = fields.Many2one("product.product", "Вариант (марка)")
    uom_id = fields.Many2one("uom.uom", "Единица цены")
    price_uom = fields.Char("Ед. цены", compute="_compute_price_uom",
                            help="Единица карточки, за которую записывается цена: метр, лист 1500×6000…")
    match_state = fields.Selection(MATCH_STATES, "Сопоставление", default="none")
    match_note = fields.Char("Почему так")
    price_ton = fields.Float("В счёте, ₽/т", digits=(14, 0))
    mass_unit = fields.Float("Масса единицы, кг", digits=(12, 4))
    new_price = fields.Float("Новая, ₽", digits=(14, 2), help="За единицу карточки, с НДС.")
    current_price = fields.Float("Сейчас, ₽", digits=(14, 2), help="Действующая цена этого поставщика на дату счёта.")
    current_price_ton = fields.Float("Сейчас, ₽/т", digits=(14, 0))
    current_date = fields.Date("Действует с")
    diff_pct = fields.Float("Разница, %", digits=(6, 1))
    warning = fields.Char("Пометка")
    apply = fields.Boolean("Записать")
    supplierinfo_id = fields.Many2one("product.supplierinfo", "Записанная цена", readonly=True)

    @api.depends("uom_id", "product_tmpl_id", "product_id")
    def _compute_price_uom(self):
        for line in self:
            uom = line.uom_id or (line.product_id or line.product_tmpl_id).uom_id
            line.price_uom = uom.name if uom else False
