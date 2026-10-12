# -*- coding: utf-8 -*-
"""Перенос МойСклад → Odoo на подставных ответах API (сеть не нужна)."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_moysklad.models import moysklad as ms

H = "https://api.moysklad.ru/api/remap/1.2/entity/"


def meta(kind, mid):
    return {"meta": {"href": H + "%s/%s" % (kind, mid)}}


ORGS = [dict(meta("organization", "o-chulkov"), name="ИП Чулков (тест МС)", inn="272107382162"),
        dict(meta("organization", "o-butov"), name="ИП Бутов (тест МС)", inn="272191216900")]
AGENTS = [dict(meta("counterparty", "c-1"), name="ООО «Тест МойСклад»", inn="2700000001", kpp="270001001",
               companyType="legal", legalAddress="г. Хабаровск", updated="2026-10-01 10:00:00.000")]


def pos(name, qty, price, vat, discount=0):
    return {"assortment": {"name": name, "uom": {"name": "шт"}}, "quantity": qty, "price": price * 100,
            "discount": discount, "vat": vat, "vatEnabled": bool(vat)}


INVOICES = [
    dict(meta("invoiceout", "i-1"), name="00101", moment="2026-10-05 12:00:00.000",
         updated="2026-10-05 12:00:00.000", organization=meta("organization", "o-chulkov"),
         agent=meta("counterparty", "c-1"), state={"name": "Оплачен"}, sum=(2 * 1000 + 500) * 100,
         shippedSum=0, vatEnabled=True, vatIncluded=True, description="срочно",
         attributes=[{"name": "Срок изготовления:", "value": "15-20 рабочих дней"},
                     {"name": "Условия оплаты:", "value": "100% предоплата"},
                     {"name": "Условия доставки:", "value": "Самовывоз со склада поставщика"},
                     {"name": "Объект:", "value": "Подстанция"}],
         positions={"rows": [pos("Закладная деталь Зд3", 2, 1000, 22), pos("Доставка", 1, 500, 22)]}),
    dict(meta("invoiceout", "i-2"), name="00102", moment="2026-10-06 12:00:00.000",
         updated="2026-10-06 12:00:00.000", organization=meta("organization", "o-butov"),
         agent=meta("counterparty", "c-1"), state={"name": "Согласование"}, sum=300 * 100,
         shippedSum=0, vatEnabled=True, vatIncluded=True,
         positions={"rows": [pos("Ворота распашные", 1, 300, 22)]}),
    dict(meta("invoiceout", "i-3"), name="00103", moment="2025-03-01 09:00:00.000",
         updated="2026-10-07 12:00:00.000", organization=meta("organization", "o-chulkov"),
         agent=meta("counterparty", "c-1"), state={"name": "Не актуальна"}, sum=120 * 100,
         shippedSum=0, vatEnabled=True, vatIncluded=True,
         positions={"rows": [pos("Лист 2 мм", 1, 120, 20)]}),
]
DEMANDS = [dict(meta("demand", "d-1"), moment="2026-10-08 15:00:00.000", updated="2026-10-08 15:00:00.000",
                invoicesOut=[meta("invoiceout", "i-1")])]


def fake_get(self, path, params=None):
    table = {"entity/organization": ORGS, "entity/counterparty": AGENTS,
             "entity/invoiceout": INVOICES, "entity/demand": DEMANDS}
    if path.startswith("entity/counterparty/"):
        return AGENTS[0]
    rows = table[path]
    return {"rows": rows if not (params or {}).get("offset") else [], "meta": {"size": len(rows)}}


@tagged("post_install", "-at_install")
class TestMoysklad(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("pmk_moysklad.token", "test")
        patcher = patch.object(type(self.env["pmk.moysklad"]), "_ms_get", fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_groups(self):
        self.assertEqual(ms.group_of("Закладная деталь Зд3"), "embed")
        self.assertEqual(ms.group_of("Соединительный элемент колодец МС-6 ТПР 902"), "tpr")
        self.assertEqual(ms.group_of("Отмет гофрированный d150 RAL7004"), "roof")
        self.assertEqual(ms.group_of("Транспортные расходы"), "service")
        self.assertEqual(ms.lead_days("15-20 рабочих дней"), 20)

    def test_sync_all(self):
        report = self.env["pmk.moysklad"].with_context(pmk_ms_no_commit=True).sync_all(full=True)
        self.assertEqual(report, {"partners": 1, "invoices": 3, "demands": 1})
        Order = self.env["sale.order"].with_context(active_test=False)
        o1 = Order.search([("pmk_ms_id", "=", "i-1")])
        self.assertEqual(o1.name, "00101")
        self.assertEqual(o1.partner_id.vat, "2700000001")
        self.assertIn(self.env.ref("pmk_moysklad.partner_tag_ms"), o1.partner_id.category_id)
        self.assertEqual(o1.pmk_org_id.inn, "272107382162")
        self.assertAlmostEqual(o1.amount_total, 2500.0, places=2, msg="НДС в цене — сумма как в МоёмСкладе")
        self.assertEqual(o1.order_line.mapped("tax_ids.pmk_regime"), ["vat22"])
        self.assertEqual(o1.order_line[0].pmk_ms_group, "embed")
        self.assertFalse(o1.pmk_ms_note)
        self.assertEqual((o1.pmk_ms_state, o1.pmk_lead_days, o1.pmk_delivery, o1.pmk_ms_object),
                         ("Оплачен", 20, "pickup", "Подстанция"))
        self.assertEqual(str(o1.pmk_ms_shipped_date), "2026-10-08")
        # Бутов — без НДС, а в счёте 22%: пометка.
        o2 = Order.search([("pmk_ms_id", "=", "i-2")])
        self.assertIn("22% вместо 0%", o2.pmk_ms_note)
        self.assertEqual(o2.pmk_org_id.regime_ids.mapped("regime"), ["usn0"])
        # 2025, Чулков — НДС 20% (режим по дате), «Не актуальна» — отменён.
        o3 = Order.search([("pmk_ms_id", "=", "i-3")])
        self.assertEqual(o3.order_line.tax_ids.pmk_regime, "vat20")
        self.assertFalse(o3.pmk_ms_note)
        self.assertEqual(o3.state, "cancel")
        # Повторный прогон — обновляет, не дублирует.
        self.env["pmk.moysklad"].with_context(pmk_ms_no_commit=True).sync_all(full=True)
        self.assertEqual(Order.search_count([("pmk_ms_id", "!=", False)]), 3)
        self.assertEqual(self.env["res.partner"].search_count([("pmk_ms_id", "=", "c-1")]), 1)
        # Поиск счёта по клиенту — для «Заказов в работе».
        self.assertIn(o1, Order.search([("display_name", "ilike", "Тест МойСклад")]))

    def test_tech_spec_from_ms_invoice(self):
        self.env["pmk.moysklad"].with_context(pmk_ms_no_commit=True).sync_all(full=True)
        order = self.env["sale.order"].search([("pmk_ms_id", "=", "i-1")])
        action = order.action_pmk_tech_spec()
        tech = self.env["pmk.metal.spec"].browse(action["res_id"])
        self.assertEqual(tech.pmk_kind, "tech")
        self.assertEqual(tech.product_ids.mapped("name"), ["Закладная деталь Зд3", "Доставка"])
        self.assertEqual(tech.product_ids.mapped("qty"), [2, 1])
        self.assertEqual(tech.product_ids[0].price_customer_unit, 1000.0)
