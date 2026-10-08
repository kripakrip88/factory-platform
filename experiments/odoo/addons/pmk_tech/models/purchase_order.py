# -*- coding: utf-8 -*-
"""«Заявка на металл» — штатный заказ поставщику (шаг З-4).

Черновик заказа поставщику, собранный из технического расчёта (кнопка
«Заявка на металл», metal_request.py). Окно штатное — «Закупки»; здесь только
то, что заявка знает о заказе клиента:

  • технический расчёт, из которого собрана (pmk_tech_spec_id);
  • счёт покупателю, сделка и строка планировщика «Заказы в работе» —
    чтобы карточка 5 («Материал пришёл») поставила в строке «Металл:
    получен», а «Связи» нарисовали цепочку. Ссылки пишет только код
    (readonly), copy=False: копия заказа — уже не заявка этого расчёта;
  • клиент (хранится — для списка, поиска и группировки «Заявок»);
  • «Поставщик не выбран» — служебный контрагент позиций без цены в
    прайсах (data/partner.xml): признак для фильтра и плашки в форме.

Строка заказа помнит ключ позиции расчёта (pmk_request_key: товар, у листа
ещё габарит) — по нему повторная «Заявка на металл» обновляет черновик, а
не плодит второй.

И помнит, что записала заявка в последний раз (pmk_request_qty / _price /
_name, доводка шага З-4). Снабженец поправил черновик — округлил прокат до
целых хлыстов, вписал договорную цену, своё описание — значение строки
отличается от записанного: повтор это поле не перезаписывает, а расхождение
количества показывает плашкой технического расчёта. Признак «Состав
изменился после заявки» считается от записанного инженером, а не от
текущего количества строки: правка снабженца его не включает.

Слова: над номером и в меню — «Заявка на металл» (свой вид); состояние —
теми же словами, что строка состояния штатной формы (с шага З-6, 09.10.2026:
«Заявка», «Заявка отправлена», «Заказ поставщику», «Отменён»), иначе у одной
стадии одного документа два названия — в списке одно, в форме другое.
"""
from odoo import api, fields, models

NO_SUPPLIER = "pmk_tech.partner_no_supplier"

# Допуск сравнения количеств и цен (метры и рубли — до сотых).
EPS = 0.005

# Состояние заявки (список «Заявки на металл», «Связи», плашка расхождения в
# техническом расчёте). Слова — как в строке состояния формы заказа
# поставщику (файл слов pmk_theme/i18n_words/purchase.po и DATA_WORDS, шаг
# З-6): одно понятие — одно слово; тест pmk_tech test_step_z6
# test_russian_words сверяет. Свой словарь, а не подпись выбора: «Материал
# пришёл» подменяет состояние (ниже), «На согласовании» — как фильтр списка
# (при двойном утверждении; на бою выключено, в строке состояния ядро пишет
# «К согласованию»). Цвет плашки в списке повторён словом.
REQUEST_STATE_LABELS = {
    "draft": "Заявка",
    "sent": "Заявка отправлена",
    "to approve": "На согласовании",
    "purchase": "Заказ поставщику",
    "done": "Заказ поставщику",
    "cancel": "Отменён",
}
# Слово кнопки «Материал пришёл» (шаг З-5): заявка — не только металл, но и
# крепёж, краска. В планировщике то же понятие — «Металл: Получен».
METAL_ARRIVED_LABEL = "Материал пришёл"
# Состояния, в которых заказ уже заказан и отметка прихода считается: у
# черновика и отменённого её нет (черновик ещё не заказан).
ARRIVAL_STATES = ("sent", "to approve", "purchase")

# Контекст «не пересчитывать „Металл“ строки планировщика на этой записи
# заказа» (шаг З-5, metal_arrival.py): пересчёт делает тот, кто его ставит.
SKIP_REFRESH = "pmk_skip_metal_refresh"


class PurchaseOrderTech(models.Model):
    _inherit = "purchase.order"

    pmk_tech_spec_id = fields.Many2one(
        "pmk.metal.spec", "Технический расчёт", index=True, ondelete="set null",
        copy=False, readonly=True,
        help="Из какого технического расчёта собрана заявка на металл.")
    pmk_sale_order_id = fields.Many2one(
        "sale.order", "Счёт покупателю", index=True, ondelete="set null",
        copy=False, readonly=True,
        help="Под какой заказ клиента покупаем металл.")
    pmk_deal_id = fields.Many2one(
        "crm.lead", "Сделка", index=True, ondelete="set null", copy=False,
        readonly=True)
    pmk_deal_number = fields.Char(related="pmk_deal_id.pmk_number", string="Номер сделки")
    pmk_task_id = fields.Many2one(
        "project.task", "Заказ в работе", index=True, ondelete="set null",
        copy=False, readonly=True,
        help="Строка планировщика «Заказы в работе»: после заявки — «Ждём "
             "металл», после прихода металла — «Металл: получен».")
    pmk_client_id = fields.Many2one(
        "res.partner", "Клиент", compute="_compute_pmk_client_id", store=True,
        index=True, help="Клиент счёта покупателю (без счёта — сделки).")
    pmk_no_supplier = fields.Boolean(
        "Поставщик не выбран", compute="_compute_pmk_no_supplier", store=True,
        help="Позиции без цены в прайсах (в городе нет): выберите поставщика "
             "в черновике — цены строк перечитаются по его прайсу.")
    pmk_request_state_label = fields.Char(
        "Состояние заявки", compute="_compute_pmk_request_state_label")

    @api.depends("pmk_sale_order_id.partner_id", "pmk_deal_id.partner_id")
    def _compute_pmk_client_id(self):
        for order in self:
            partner = order.pmk_sale_order_id.partner_id or order.pmk_deal_id.partner_id
            order.pmk_client_id = partner.commercial_partner_id

    @api.depends("partner_id")
    def _compute_pmk_no_supplier(self):
        placeholder = self._pmk_no_supplier_partner(create=False)
        for order in self:
            order.pmk_no_supplier = bool(placeholder) and order.partner_id == placeholder

    @api.depends("state", "pmk_metal_date")
    def _compute_pmk_request_state_label(self):
        # «Материал пришёл» — отметка снабженца (шаг З-5, metal_arrival.py);
        # только у заказанного (черновик, отменённый — их слово).
        for order in self:
            if order.pmk_metal_date and order.state in ARRIVAL_STATES:
                order.pmk_request_state_label = METAL_ARRIVED_LABEL
                continue
            order.pmk_request_state_label = REQUEST_STATE_LABELS.get(order.state, order.state or "")

    @api.model
    def _pmk_no_supplier_partner(self, create=True):
        """Служебный «Поставщик не выбран». Удалили запись — заводим заново
        (архивной, как в data/partner.xml): заявка без контрагента не
        сохранится, а позиции без цены не должны пропасть молча."""
        partner = self.env.ref(NO_SUPPLIER, raise_if_not_found=False)
        if partner or not create:
            return partner or self.env["res.partner"]
        partner = self.env["res.partner"].sudo().create({
            "name": "Поставщик не выбран", "is_company": True, "active": False})
        self.env["ir.model.data"].sudo().create({
            "module": "pmk_tech", "name": "partner_no_supplier", "model": "res.partner",
            "res_id": partner.id, "noupdate": True})
        return partner.with_env(self.env)


class PurchaseOrderLineTech(models.Model):
    _inherit = "purchase.order.line"

    pmk_request_key = fields.Char(
        "Позиция технического расчёта", index=True, copy=False, readonly=True,
        help="Какая позиция технического расчёта легла в строку: товар, у "
             "листа — ещё габарит. По ней повторная «Заявка на металл» "
             "обновляет черновик.")
    pmk_request_qty = fields.Float(
        "Заявлено инженером", digits="Product Unit", copy=False, readonly=True,
        help="Количество позиции в техническом расчёте при последней «Заявке на "
             "металл». Количество строки отличается — его правил снабженец: "
             "повтор его не меняет, расхождение видно в техническом расчёте.")
    pmk_request_price = fields.Float(
        # Без digits — как у price_unit ядра (он не округляется при записи):
        # иначе сравнение «правил ли снабженец» ловило бы округление.
        "Цена заявки", copy=False, readonly=True,
        help="Цена, которую записала «Заявка на металл». Цена строки отличается "
             "— её правил снабженец (или сменил поставщика): повтор её не меняет.")
    pmk_request_name = fields.Text(
        "Описание заявки", copy=False, readonly=True,
        help="Описание, которое записала «Заявка на металл». Отличается — его "
             "правил снабженец: повтор его не меняет.")

    def _pmk_request_requested_qty(self):
        """Что заявил инженер в последний раз. Строка до доводки (ничего не
        записано) — её текущее количество."""
        self.ensure_one()
        return self.pmk_request_qty if self.pmk_request_name else self.product_qty

    def _pmk_request_edits(self):
        """Какие поля строки правил снабженец: подмножество {"qty", "price",
        "name"}. Строка до доводки — правок не различаем (пусто)."""
        self.ensure_one()
        if not self.pmk_request_name:
            return set()
        edits = set()
        if abs(self.product_qty - self.pmk_request_qty) > EPS:
            edits.add("qty")
        if abs(self.price_unit - self.pmk_request_price) >= EPS:
            edits.add("price")
        if (self.name or "") != self.pmk_request_name:
            edits.add("name")
        return edits

    def _pmk_stamp_request(self, qty=None, keep=()):
        """Запомнить, что записала заявка: текущие значения строки. qty —
        заявленное инженером, когда количество строки правил снабженец; keep —
        поля, которые правил снабженец: их записанное не трогаем, иначе его
        правка стала бы «нашей» и следующий повтор её перезаписал бы."""
        for line in self:
            vals = {"pmk_request_qty": line.product_qty if qty is None else qty}
            if "price" not in keep:
                vals["pmk_request_price"] = line.price_unit
            if "name" not in keep:
                vals["pmk_request_name"] = line.name or ""
            line.write(vals)
