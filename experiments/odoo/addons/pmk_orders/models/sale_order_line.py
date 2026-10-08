# -*- coding: utf-8 -*-
"""Строка счёта покупателю ↔ изделие расчёта (шаги З-2 и З-9).

Строка счёта — одно изделие расчёта: состав, вес и металл живут в расчёте,
строка помнит, из какого изделия она пришла. По этой связи редакция знает,
какие строки заменить заново из расчёта, а какие (услуги: доставка, монтаж)
оставить. Строки прежней редакции (снимка) только для чтения.

ШАГ З-9 (решение Антона 08.10.2026): «две правды» — правка цены или
количества прямо в счёте расходится с расчётом. Строки-изделия в счёте только
для чтения: в форме (readonly по pmk_from_spec) и на сервере — запись ДРУГОГО
значения названия, количества, цены, товара, единицы, скидки и удаление
такой строки — ошибкой с подсказкой «Изменить в расчёте». Свои операции
(пересборка черновика из расчёта, редакция, снимок) идут через sudo с флагом
контекста (sale_order.spec_lines_allowed) — флаг без sudo не действует.
Порядок строк (sequence) и налог правятся свободно: налог ставит режим
организации, порядок ничего не меняет в сумме.

«ДОБАВИТЬ УСЛУГУ». Кнопка под строками ставит контекст pmk_add_service —
новая строка сразу с товаром «Услуга» (data/product.xml): описание, количество
и цену пишут в счёте, налог — режим организации (pmk_org). Строка без товара
и без типа (раздел, заметка) у нашего счёта тоже получает «Услугу» —
страховка, если кнопку подменят.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .sale_order import ADD_SERVICE, freeze_allowed, snapshot_error, spec_lines_allowed

# Поля строки-изделия, которые меняют в расчёте, а не в счёте.
SPEC_LOCKED_FIELDS = ("name", "product_uom_qty", "price_unit", "product_id",
                      "product_uom_id", "discount", "pmk_spec_product_id", "pmk_from_spec")


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    pmk_spec_product_id = fields.Many2one(
        "pmk.metal.spec.product", "Изделие расчёта", index=True,
        ondelete="set null", copy=False,
        help="Изделие расчёта, из которого пришла строка. Состав и вес — в расчёте.")
    # Отдельный признак, а не «есть изделие»: изделие удалили из расчёта —
    # ссылка обнулится (set null), а строка всё равно расчётная, и новая
    # редакция должна её заменить, а не оставить как ручную.
    pmk_from_spec = fields.Boolean(
        "Из расчёта", copy=False,
        help="Строка выставлена из расчёта: меняют её в расчёте, новая редакция заменит "
             "её заново. Услуги (доставка, монтаж) правятся в счёте, редакция их "
             "переносит.")

    def _pmk_check_not_snapshot(self, orders=None):
        if freeze_allowed(self.env):
            return
        for order in (orders if orders is not None else self.order_id):
            if order.pmk_is_revision:
                raise snapshot_error(order)

    def _pmk_spec_line_error(self):
        self.ensure_one()
        return UserError(_(
            "«%(name)s» пришло из расчёта %(spec)s: название, количество и цену изделия "
            "меняют в расчёте — кнопка «Изменить в расчёте». В счёте правятся только "
            "услуги.", name=self.name or _("Изделие"),
            spec=self.order_id.pmk_spec_id.name or _("(расчёт удалён)")))

    def _pmk_check_spec_lines(self, vals):
        """Запись другого значения в строку-изделие — ошибкой (шаг З-9)."""
        if spec_lines_allowed(self.env):
            return
        names = [name for name in SPEC_LOCKED_FIELDS if name in vals]
        if not names:
            return
        for line in self.filtered("pmk_from_spec"):
            for name in names:
                field = line._fields[name]
                old = line[name]
                new = vals[name]
                if field.type == "many2one":
                    same = (old.id or False) == (new or False)
                elif field.type in ("float", "monetary"):
                    same = abs((old or 0.0) - (new or 0.0)) < 1e-6
                elif field.type == "boolean":
                    same = bool(old) == bool(new)
                else:
                    same = (old or "") == (new or "")
                if not same:
                    raise line._pmk_spec_line_error()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if (self.env.context.get(ADD_SERVICE) and "product_id" in fields_list
                and not res.get("product_id") and not res.get("display_type")):
            product = self.env["sale.order"]._pmk_extra_service_product()
            if product:
                res["product_id"] = product.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        if not freeze_allowed(self.env):
            ids = {vals["order_id"] for vals in vals_list if vals.get("order_id")}
            self._pmk_check_not_snapshot(self.env["sale.order"].browse(ids))
        # Строка без товара и без типа у счёта из расчёта — «Услуга».
        service = None
        for vals in vals_list:
            if (vals.get("order_id") and not vals.get("product_id")
                    and not vals.get("display_type") and not vals.get("is_downpayment")):
                order = self.env["sale.order"].browse(vals["order_id"])
                if order.pmk_spec_id or order.opportunity_id:
                    if service is None:
                        service = self.env["sale.order"]._pmk_extra_service_product()
                    if service:
                        vals["product_id"] = service.id
        return super().create(vals_list)

    def write(self, vals):
        self._pmk_check_not_snapshot()
        self._pmk_check_spec_lines(vals)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _pmk_unlink_except_revision(self):
        self._pmk_check_not_snapshot()

    @api.ondelete(at_uninstall=False)
    def _pmk_unlink_except_spec_line(self):
        """Изделие из счёта не удаляют — его удаляют из расчёта (шаг З-9).
        Счёт целиком (черновик, отменённый) удалить можно: его строки уходят
        каскадом базы, мимо этой проверки."""
        if spec_lines_allowed(self.env):
            return
        for line in self.filtered("pmk_from_spec"):
            if line.order_id.pmk_is_revision:
                continue  # снимок — своя ошибка выше
            raise line._pmk_spec_line_error()
