# -*- coding: utf-8 -*-
"""«Технический расчёт» и «Заявка на металл» (разбор UX, шаг З-4), pmk_tech.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

Цены — свои, проверяются в уме:
  • уголок 100×8: 10 кг/м, прайс 1 000 ₽/м, хлыст 12 м;
  • лист 2 мм: 15,7 кг/м², карточка 141,3 кг (1500×6000), 14 130 ₽/лист →
    100 ₽/кг;
  • болт: 0,1 кг, 50 ₽/шт;
  • уголок 200×20: 60 кг/м, в прайсах нет (сигнал «в городе нет»).
Изделие «Рама» × 2: уголок 1 000 мм × 3, пластина 490×590 × 10 (20 заготовок
— один лист 1500×6000), болт × 8, балка 200×20 2 000 мм × 1.

Что ловим:
  • технический расчёт — копия расчёта КП (изделия, детали, листы,
    раскладка, отпечаток) у той же сделки, клиента, организации, со ссылкой
    на счёт; номер свой; ровно один на счёт (повтор открывает его, второй
    не заводится); правка технического не трогает расчёт КП; главным
    расчётом сделки он не становится, КП из него не двигает сделку;
  • «Заявка на металл»: прокат в метрах, листы числом листов раскладки,
    метизы штуками; черновики по назначенному поставщику с ценой прайса;
    позиция без цены — черновик «Поставщик не выбран» с ценой 0; ссылки на
    технический расчёт, счёт, сделку, строку планировщика, клиента; писем нет;
  • повтор после правки — те же черновики обновлены (не дубли); листы без
    раскладки — по весу и плашкой; отправленная/подтверждённая заявка не
    меняется — плашка расхождения «в заявке 6 м, у инженера 15 м»;
    позиция, у которой появилась цена, уезжает к поставщику, опустевший
    черновик «Поставщик не выбран» отменяется;
  • планировщик: «Очередь» → «Ждём металл», «Металл» — «Ждём»; строка «В
    работе» этап не меняет; без строки — ничего не падает;
  • доводка: правки снабженца в черновике (количество, цена, описание)
    повтор не затирает и плашку «состав изменился» они не включают;
    расхождение — плашкой; строку, которую правил снабженец, не удаляет;
    служебной пометки «по весу» в описании строки нет (его видит
    поставщик); лист не 1500×6000 — цена ручная; строка планировщика —
    только своего счёта, этап без кода не трогаем; технический знает, что
    счёт выставили заново (новая редакция); «Дублировать» технический —
    технический, не главный расчёт сделки; сравнение «в заявку» одной мерой
    (без правок — числа совпадают);
  • права: инженер (продажи, проекты, закупки) — всё; продавец без закупок
    заводит технический и видит его, кнопок и счётчиков заявок у него нет;
  • виды: залитая в шапке технического — одна («Заявка на металл»), КП
    спрятаны; меню «Закупки → Заявки на металл»; колонка «Вид»; «Связи».

Глазами (технический расчёт, счёт в работе, строка планировщика, заявка,
список «Заявки на металл», светлая и тёмная тема) — основной агент на копии.
"""
import datetime

import psycopg2
from lxml import etree

from odoo import Command, fields
from odoo.tests import new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.pmk_orders.tests.test_step_z2_invoice import Z2Common


def _filled(node):
    return bool({"btn-primary", "oe_highlight"} & set((node.get("class") or "").split()))


class Z4Common(Z2Common):
    """Данные и помощники шага З-4 — их же берёт шаг З-5 (test_step_z5.py).
    Своих тестов нет: класс без test_-методов не гоняется."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        today = fields.Date.context_today(env["res.partner"])
        old = today - datetime.timedelta(days=100)
        cls.engineer = new_test_user(
            env, login="pmkz4_engineer", name="Инженер (шаг З-4)",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads,"
                   "project.group_project_user,purchase.group_purchase_user")
        cls.supplier = env["res.partner"].create({
            "name": "Металлсервис (тест З-4)", "is_company": True, "pmk_supplier_rank": 10})
        Info = env["product.supplierinfo"]
        meter = env.ref("uom.product_uom_meter")

        ptype = env["pmk.metal.profile.type"].create({"name": "Уголок (тест З-4)"})
        angle_tmpl = env["product.template"].create({
            "name": "Уголок 100×8 (тест З-4)", "uom_id": meter.id})
        cls.angle = env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест З-4)", "gost": "ГОСТ тест",
            "size_label": "100×8", "mass_per_meter": 10.0, "product_tmpl_id": angle_tmpl.id})
        Info.create({"partner_id": cls.supplier.id, "product_tmpl_id": angle_tmpl.id,
                     "price": 1000.0, "date_start": old, "pmk_bar_length_mm": 12000.0})

        sheet_tmpl = env["product.template"].create({
            "name": "Лист 2 мм (тест З-4)", "weight": 141.3})
        cls.sheet = env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест З-4)", "thickness_mm": 2.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 15.7, "product_tmpl_id": sheet_tmpl.id})
        Info.create({"partner_id": cls.supplier.id, "product_tmpl_id": sheet_tmpl.id,
                     "price": 14130.0, "date_start": old})

        bolt_tmpl = env["product.template"].create({"name": "Болт М16 (тест З-4)"})
        cls.bolt = env["pmk.metal.fastener"].create({
            "name": "Болт М16 (тест З-4)", "weight_kg": 0.1, "product_tmpl_id": bolt_tmpl.id})
        Info.create({"partner_id": cls.supplier.id, "product_tmpl_id": bolt_tmpl.id,
                     "price": 50.0, "date_start": old})

        cls.bare_tmpl = env["product.template"].create({
            "name": "Уголок 200×20 (тест З-4)", "uom_id": meter.id})
        cls.bare = env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест З-4)", "gost": "ГОСТ тест",
            "size_label": "200×20", "mass_per_meter": 60.0, "product_tmpl_id": cls.bare_tmpl.id})
        cls.old = old

        cls.placeholder = env.ref("pmk_tech.partner_no_supplier")
        cls.metal_stage = env.ref("pmk_orders.orders_stage_metal")
        cls.work_stage = env.ref("pmk_orders.orders_stage_work")
        cls.Spec = env["pmk.metal.spec"]

    # ─── помощники ──────────────────────────────────────────────────────
    def _flow(self, won=True):
        """Сделка → расчёт с раскладкой → «КП отправлено» (счёт) → «Выиграно»
        (строка планировщика в «Очереди»)."""
        deal = self._deal()
        spec = self._spec(deal, products=[], product_ids=[Command.create({
            "name": "Рама", "qty": 2, "price_customer_unit": 50000.0,
            "line_ids": [
                Command.create({"calc_mode": "linear", "detail_name": "Стойка",
                                "profile_id": self.angle.id, "length_mm": 1000.0, "qty": 3}),
                Command.create({"calc_mode": "sheet", "detail_name": "Пластина",
                                "sheet_id": self.sheet.id, "a_mm": 490.0, "b_mm": 590.0,
                                "qty": 10}),
                Command.create({"calc_mode": "fastener", "detail_name": "Болт",
                                "fastener_id": self.bolt.id, "qty": 8}),
                Command.create({"calc_mode": "linear", "detail_name": "Балка",
                                "profile_id": self.bare.id, "length_mm": 2000.0, "qty": 1}),
            ],
        })])
        spec.action_draft_layout()
        # Шаг З-9: счёт сам по переносу сделки не заводится — «Отправить КП»
        # (после отправки письма мост зовёт _pmk_kp_move_stage) заводит его из
        # расчёта и отмечает «Отправлен».
        spec._pmk_kp_move_stage(deal)
        self.assertEqual(deal.stage_id, self.stage_kp)
        order = self._invoices(deal)
        self.assertEqual(len(order), 1, "Посылка: счёт выставлен.")
        row = self.env["project.task"]
        if won:
            deal.with_user(self.manager).action_set_won()
            row = self._rows(deal)
            self.assertEqual(len(row), 1, "Посылка: строка планировщика.")
        return deal, spec, order, row

    def _tech(self, order, user=None):
        action = order.with_user(user or self.engineer).action_pmk_tech_spec()
        self.assertEqual(action["res_model"], "pmk.metal.spec")
        return self.Spec.browse(action["res_id"])

    def _request(self, tech, user=None):
        return tech.with_user(user or self.engineer).action_pmk_metal_request()

    def _requests(self, tech):
        return tech.sudo().pmk_metal_request_ids.filtered(lambda o: o.state != "cancel")

    def _line(self, order, tmpl_name):
        found = order.order_line.filtered(
            lambda l: l.pmk_request_key and l.product_id.product_tmpl_id.name == tmpl_name)
        self.assertEqual(len(found), 1, tmpl_name)
        return found

    def _signals(self, tech):
        tech.invalidate_recordset([
            "pmk_request_warn_text", "pmk_request_stale", "pmk_request_diff_text",
            "pmk_kp_compare_weight", "pmk_kp_compare_cost", "pmk_kp_compare_unpriced",
            "pmk_tech_outdated_text"])
        return tech


@tagged("post_install", "-at_install")
class TestStepZ4(Z4Common):

    # ─── Технический расчёт ─────────────────────────────────────────────
    def test_tech_is_a_copy_of_kp_spec(self):
        deal, spec, order, row = self._flow()
        tech = self._tech(order)
        self.assertEqual(tech.pmk_kind, "tech")
        self.assertEqual(spec.pmk_kind, "kp", "Расчёт КП — «Для КП».")
        self.assertEqual(tech.pmk_tech_source_id, spec)
        self.assertEqual(tech.pmk_tech_order_id, order)
        self.assertEqual(tech.opportunity_id, deal, "Та же сделка.")
        self.assertEqual(tech.partner_id, self.client)
        self.assertEqual(tech.pmk_org_id, self.org_vat)
        self.assertNotEqual(tech.name, spec.name, "Номер СМ- свой.")
        self.assertEqual(tech.product_ids.mapped("name"), spec.product_ids.mapped("name"))
        self.assertEqual(sorted(tech.product_ids.line_ids.mapped("detail_name")),
                         sorted(spec.product_ids.line_ids.mapped("detail_name")))
        plate, plate_kp = tech.sheet_line_ids, spec.sheet_line_ids
        self.assertEqual(plate_kp.layout_state, "ok", "Посылка: раскладка КП посчитана.")
        self.assertEqual(plate.layout_state, "ok", "Раскладка перенесена.")
        self.assertEqual(plate.layout_sheets, plate_kp.layout_sheets)
        self.assertEqual(plate.layout_per_sheet, plate_kp.layout_per_sheet)
        self.assertEqual(tech.layout_fingerprint, spec.layout_fingerprint)
        self.assertFalse(tech.layout_stale, "Раскладка не устарела: детали те же.")
        self.assertAlmostEqual(tech.total_weight, spec.total_weight, places=3)
        order.invalidate_recordset(["message_ids"])
        self.assertIn(tech.name, " ".join(str(m.body) for m in order.message_ids))

        # Главный расчёт сделки — по-прежнему расчёт КП.
        deal.invalidate_recordset(["pmk_spec_id"])
        self.assertEqual(deal.pmk_spec_id, spec, "Технический главным не становится.")
        self.assertAlmostEqual(deal.expected_revenue, spec.price_customer_total)
        self.assertEqual(deal.spec_count, 2, "У сделки «Расчёты» — оба.")

        # Один на счёт: повтор (из счёта и из строки) открывает тот же.
        self.assertEqual(self._tech(order), tech)
        self.assertEqual(row.with_user(self.engineer).action_pmk_tech_spec()["res_id"], tech.id)
        self.assertEqual(order.pmk_tech_spec_id, tech)
        self.assertEqual(row.pmk_tech_spec_id, tech)
        self.assertEqual(spec.pmk_tech_count, 1, "У расчёта КП — счётчик «Технический».")

        # Инженер правит технический — расчёт КП не меняется.
        weight_kp = spec.total_weight
        tech.with_user(self.engineer).product_ids.write({"qty": 5})
        stand = tech.product_ids.line_ids.filtered(lambda l: l.detail_name == "Стойка")
        stand.with_user(self.engineer).length_mm = 1500.0
        self.assertEqual(spec.product_ids.qty, 2)
        self.assertEqual(spec.product_ids.line_ids.filtered(
            lambda l: l.detail_name == "Стойка").length_mm, 1000.0)
        self.assertAlmostEqual(spec.total_weight, weight_kp, places=3)
        self.assertEqual(plate_kp.layout_state, "ok", "Раскладка КП цела.")

        # Второй технический к тому же счёту база не пустит (уникальный индекс).
        with self.assertRaises(psycopg2.IntegrityError), mute_logger("odoo.sql_db"), \
                self.cr.savepoint():
            self.Spec.create({"pmk_kind": "tech", "pmk_tech_order_id": order.id})
            self.env.flush_all()

    def test_tech_never_issues_invoice(self):
        deal, spec, order, _row = self._flow(won=False)
        tech = self._tech(order)
        self.assertFalse(tech._pmk_kp_move_stage(deal), "КП из технического стадию не двигает.")
        self.assertEqual(order.pmk_revision, 1, "И новую редакцию счёта не выставляет.")
        self.assertEqual(order.pmk_spec_id, spec)

    def test_order_without_spec_gets_empty_tech(self):
        order = self.env["sale.order"].with_user(self.manager).create({
            "partner_id": self.client.id,
            "order_line": [Command.create({"product_id": self.service.id, "name": "Каркас",
                                           "product_uom_qty": 1, "price_unit": 5000.0})]})
        tech = self._tech(order)
        self.assertEqual(tech.pmk_kind, "tech")
        self.assertFalse(tech.pmk_tech_source_id)
        self.assertFalse(tech.product_ids, "Состав набирается в техническом.")
        self._request(tech)
        self.assertFalse(self._requests(tech), "Металла нет — заказывать нечего.")

    # ─── Заявка на металл ───────────────────────────────────────────────
    def test_request_builds_drafts_per_supplier(self):
        deal, spec, order, row = self._flow()
        tech = self._tech(order)
        mails = self.env["mail.mail"].sudo().search_count([])
        action = self._request(tech)
        self.assertEqual(action["res_model"], "purchase.order")

        orders = self._requests(tech)
        self.assertEqual(len(orders), 2, "Поставщик позиций и «Поставщик не выбран».")
        po = orders.filtered(lambda o: o.partner_id == self.supplier)
        empty = orders.filtered(lambda o: o.partner_id == self.placeholder)
        self.assertEqual((len(po), len(empty)), (1, 1))
        for order_po in orders:
            with self.subTest(order=order_po.partner_id.name):
                self.assertEqual(order_po.state, "draft", "Черновик — отправляет снабженец.")
                self.assertEqual(order_po.pmk_tech_spec_id, tech)
                self.assertEqual(order_po.pmk_sale_order_id, order)
                self.assertEqual(order_po.pmk_deal_id, deal)
                self.assertEqual(order_po.pmk_task_id, row)
                self.assertEqual(order_po.pmk_client_id, self.client)
                self.assertIn(tech.name, order_po.origin)
                self.assertIn(order.name, order_po.origin)
                self.assertEqual(order_po.pmk_request_state_label, "Заявка")

        angle = self._line(po, "Уголок 100×8 (тест З-4)")
        self.assertAlmostEqual(angle.product_qty, 6.0, msg="1 м × 3 × 2 изделия.")
        self.assertEqual(angle.product_uom_id, self.env.ref("uom.product_uom_meter"))
        self.assertAlmostEqual(angle.price_unit, 1000.0, msg="Цена прайса за метр.")
        self.assertIn("1 хлыст по 12 м", angle.name)

        plate = self._line(po, "Лист 2 мм (тест З-4)")
        self.assertEqual(plate.product_qty, tech.sheet_line_ids.layout_sheets,
                         "Листы — числом листов раскладки.")
        self.assertEqual(plate.product_qty, 1.0)
        self.assertAlmostEqual(plate.price_unit, 14130.0, places=2,
                               msg="₽/т × масса листа = цена листа в прайсе.")
        self.assertIn("1500 × 6000", plate.name)

        bolt = self._line(po, "Болт М16 (тест З-4)")
        self.assertEqual(bolt.product_qty, 16.0)
        self.assertAlmostEqual(bolt.price_unit, 50.0)

        beam = self._line(empty, "Уголок 200×20 (тест З-4)")
        self.assertAlmostEqual(beam.product_qty, 4.0)
        self.assertEqual(beam.price_unit, 0.0, "Без цены — ноль, соседний размер не подставляем.")
        self.assertTrue(empty.pmk_no_supplier)
        self.assertFalse(po.pmk_no_supplier)

        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails, "Писем нет.")
        self.assertEqual(row.stage_id, self.metal_stage, "«Очередь» → «Ждём металл».")
        self.assertEqual(row.pmk_metal, "wait", "«Металл» — «Ждём».")
        self.assertEqual(tech.with_user(self.engineer).pmk_metal_request_count, 2)
        self.assertEqual(order.with_user(self.engineer).pmk_metal_request_count, 2)
        self.assertEqual(row.with_user(self.engineer).pmk_metal_request_count, 2)
        tech.invalidate_recordset(["message_ids"])
        notes = " ".join(str(m.body) for m in tech.message_ids)
        self.assertIn("Заявка на металл", notes)
        self.assertIn("Поставщик не выбран", notes)

        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale)
        self.assertFalse(tech.pmk_request_diff_text)
        self.assertIn("→", tech.pmk_kp_compare_weight)
        self.assertIn("без цены 1 поз.", tech.pmk_kp_compare_cost)

    def test_repeat_updates_drafts_no_duplicates(self):
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        first = self._requests(tech)
        po = first.filtered(lambda o: o.partner_id == self.supplier)

        tech.product_ids.write({"qty": 5})          # раскладка листов гаснет
        self._signals(tech)
        self.assertTrue(tech.pmk_request_stale, "Состав изменился после заявки — плашка.")
        self.assertIn("без раскладки", tech.pmk_request_warn_text)

        self._request(tech)
        self.assertEqual(self._requests(tech), first, "Не дубли — те же черновики.")
        self.assertAlmostEqual(self._line(po, "Уголок 100×8 (тест З-4)").product_qty, 15.0)
        self.assertAlmostEqual(self._line(po, "Уголок 100×8 (тест З-4)").price_unit, 1000.0,
                               msg="Цена не съехала на оптовый порог.")
        self.assertEqual(self._line(po, "Болт М16 (тест З-4)").product_qty, 40.0)
        plate = self._line(po, "Лист 2 мм (тест З-4)")
        # 50 пластин без раскладки: 0,49 × 0,59 × 15,7 × 50 = 226,9 кг → 2 листа по 141,3.
        self.assertEqual(plate.product_qty, 2.0, "Без раскладки — по весу, до целого листа.")
        self.assertNotIn("по весу", plate.name,
                         "Заметка завода — не в описании строки: его видит поставщик.")
        self.assertNotIn("без раскладки", plate.name)
        tech.invalidate_recordset(["message_ids"])
        self.assertIn("без раскладки", " ".join(str(m.body) for m in tech.message_ids),
                      "Пометка — в ленте технического расчёта.")
        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale, "После повтора черновики совпадают.")

    def test_buyer_edits_survive_repeat(self):
        """Снабженец округлил уголок до хлыста, вписал договорную цену болта и
        своё описание листа — повтор это не затирает, плашка «состав
        изменился» от его правки не загорается, расхождение — словами."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        angle = self._line(po, "Уголок 100×8 (тест З-4)")
        bolt = self._line(po, "Болт М16 (тест З-4)")
        plate = self._line(po, "Лист 2 мм (тест З-4)")
        self.assertAlmostEqual(angle.pmk_request_qty, 6.0, msg="Заявка помнит, что записала.")
        angle.with_user(self.engineer).product_qty = 12.0        # целый хлыст
        bolt.with_user(self.engineer).price_unit = 45.0          # договорная цена
        plate.with_user(self.engineer).name = "Лист 2 мм х/к, 1500×6000 — 1 лист"

        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale, "Правка снабженца — не «состав изменился».")
        self.assertIn("12 м, у инженера 6 м", tech.pmk_request_diff_text or "")
        self.assertIn("количество правил снабженец", tech.pmk_request_diff_text or "")

        tech.product_ids.write({"qty": 5})
        self._signals(tech)
        self.assertTrue(tech.pmk_request_stale, "Инженер поменял состав — плашка.")
        self._request(tech)
        self.assertAlmostEqual(angle.product_qty, 12.0, msg="Количество снабженца цело.")
        self.assertAlmostEqual(angle.pmk_request_qty, 15.0, msg="Заявлено инженером — новое.")
        self.assertEqual(bolt.product_qty, 40.0, "Не правленое количество — обновлено.")
        self.assertAlmostEqual(bolt.price_unit, 45.0, msg="Цена снабженца цела.")
        self.assertEqual(plate.name, "Лист 2 мм х/к, 1500×6000 — 1 лист", "Описание снабженца цело.")
        self.assertEqual(plate.product_qty, 2.0, "Количество листа — по инженеру.")
        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale, "После повтора плашки нет.")
        self.assertIn("12 м, у инженера 15 м", tech.pmk_request_diff_text or "")
        tech.invalidate_recordset(["message_ids"])
        self.assertIn("Правки снабженца", " ".join(str(m.body) for m in tech.message_ids))

        # Позицию убрали у инженера, а строку правил снабженец — не удаляем.
        stand = tech.product_ids.line_ids.filtered(lambda l: l.detail_name == "Стойка")
        stand.unlink()
        self._signals(tech)
        self.assertTrue(tech.pmk_request_stale)
        self._request(tech)
        self.assertTrue(angle.exists(), "Строку снабженца молча не удаляем.")
        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale)
        self.assertIn("у инженера нет", tech.pmk_request_diff_text or "")

    def test_odd_sheet_price_is_manual(self):
        """Лист 1500×3000: цена — наша (₽/кг × масса листа габарита), не
        строки прайса за лист 1500×6000; правка количества её не удвоит."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        plate_line = tech.sheet_line_ids
        size = "1500x3000"
        sizes = dict(plate_line._fields["layout_sheet_size"].selection)
        if size not in sizes:
            self.skipTest("Габарита 1500×3000 в выборе нет.")
        plate_line.write({"layout_sheet_size": size})
        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        plate = self._line(po, "Лист 2 мм (тест З-4)")
        price = plate.price_unit
        self.assertAlmostEqual(price, 100.0 * 15.7 * 1.5 * 3.0, places=0,
                               msg="₽/кг × масса листа 1500×3000.")
        self.assertNotEqual(plate.technical_price_unit, plate.price_unit, "Цена ручная.")
        plate.with_user(self.engineer).product_qty = plate.product_qty + 1
        self.assertAlmostEqual(plate.price_unit, price, places=2,
                               msg="Ядро не подставило цену листа 1500×6000.")

    def test_repeat_price_keeps_core_reprice(self):
        """Повтор пишет цену вместе с technical_price_unit: смена поставщика в
        черновике по-прежнему перечитывает цену по его прайсу."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        tech.product_ids.write({"qty": 5})
        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        angle = self._line(po, "Уголок 100×8 (тест З-4)")
        self.assertEqual(angle.technical_price_unit, angle.price_unit, "Цена не ручная.")

    def test_sent_request_is_kept_and_diff_shown(self):
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        po.button_confirm()
        self.assertIn(po.state, ("purchase", "to approve"))

        tech.product_ids.write({"qty": 5})
        self._request(tech)
        self.assertEqual(len(self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)), 1,
                         "Подтверждённую не дублируем.")
        self.assertAlmostEqual(self._line(po, "Уголок 100×8 (тест З-4)").product_qty, 6.0,
                               msg="Подтверждённая заявка не меняется.")
        self._signals(tech)
        diff = tech.pmk_request_diff_text or ""
        self.assertIn(po.name, diff)
        self.assertIn("в заявке", diff.lower())
        self.assertIn("6 м, у инженера 15 м", diff)
        self.assertIn("1 лист, у инженера 2 листа", diff)

    def test_priced_position_moves_to_supplier(self):
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        empty = self._requests(tech).filtered(lambda o: o.partner_id == self.placeholder)
        self.env["product.supplierinfo"].create({
            "partner_id": self.supplier.id, "product_tmpl_id": self.bare_tmpl.id,
            "price": 2000.0, "date_start": self.old})
        tech.action_refresh_prices()
        self._request(tech)
        self.assertEqual(empty.state, "cancel", "Опустевший черновик отменён, не удалён.")
        po = self._requests(tech)
        self.assertEqual(po.partner_id, self.supplier)
        beam = self._line(po, "Уголок 200×20 (тест З-4)")
        self.assertAlmostEqual(beam.product_qty, 4.0)
        self.assertAlmostEqual(beam.price_unit, 2000.0)

    def test_planner_row_further_keeps_stage(self):
        _deal, _spec, order, row = self._flow()
        row.write({"stage_id": self.work_stage.id})
        tech = self._tech(order)
        self._request(tech)
        self.assertEqual(row.stage_id, self.work_stage, "«В работе» — этап не трогаем.")
        self.assertEqual(row.pmk_metal, "wait")

    def test_planner_stage_without_code_kept(self):
        """Этап без кода («Разобрать: прошлые месяцы») — только «Металл: Ждём»."""
        _deal, _spec, order, row = self._flow()
        loose = self.env["project.task.type"].create({
            "name": "Разобрать (тест З-4)", "project_ids": [Command.link(row.project_id.id)]})
        self.assertFalse(loose.pmk_order_stage)
        row.write({"stage_id": loose.id})
        tech = self._tech(order)
        self._request(tech)
        self.assertEqual(row.stage_id, loose, "Этап без кода не трогаем.")
        self.assertEqual(row.pmk_metal, "wait")

    def test_planner_other_invoice_row_untouched(self):
        """У сделки второй счёт со своей строкой — заявка по первому её не трогает."""
        deal, _spec, order, row = self._flow()
        other = self.env["sale.order"].create({
            "partner_id": self.client.id, "opportunity_id": deal.id,
            "order_line": [Command.create({"product_id": self.service.id, "name": "Доп. изделия",
                                           "product_uom_qty": 1, "price_unit": 1000.0})]})
        queue = row.stage_id
        other_row = row.copy({"name": "Второй счёт (тест З-4)", "pmk_sale_order_id": other.id,
                              "pmk_deal_id": deal.id, "pmk_metal": False})
        other_row.write({"stage_id": queue.id})
        tech = self._tech(order)
        self._request(tech)
        self.assertEqual(row.stage_id, self.metal_stage)
        self.assertEqual(other_row.stage_id, queue, "Строку другого счёта не трогаем.")
        self.assertNotEqual(other_row.pmk_metal, "wait")
        self.assertEqual(self._requests(tech).pmk_task_id, row, "Заявка — к строке своего счёта.")

    def test_tech_knows_invoice_reissued(self):
        """Технический снят с выставленного счёта, потом счёт выставили заново
        (новая редакция) — плашка «сверьте состав», ничего не блокирует."""
        deal, spec, order, _row = self._flow(won=False)
        tech = self._tech(order)
        self._signals(tech)
        self.assertFalse(tech.pmk_tech_outdated_text)
        self.assertEqual(tech.pmk_tech_revision, order.pmk_revision)
        spec.product_ids.write({"price_customer_unit": 60000.0})
        spec._pmk_kp_move_stage(deal)
        self.assertEqual(order.pmk_revision, 2, "Посылка: новая редакция.")
        self._signals(tech)
        self.assertIn("ред. 2", tech.pmk_tech_outdated_text or "")
        self.assertIn("сверьте состав", tech.pmk_tech_outdated_text or "")

    def test_duplicate_tech_stays_tech(self):
        deal, spec, order, _row = self._flow()
        tech = self._tech(order)
        twin = tech.with_user(self.engineer).copy()
        self.assertEqual(twin.pmk_kind, "tech", "Копия технического — технический.")
        self.assertEqual(twin.pmk_tech_source_id, spec)
        self.assertFalse(twin.pmk_tech_order_id, "Счёт — один технический.")
        deal.invalidate_recordset(["pmk_spec_id"])
        self.assertEqual(deal.pmk_spec_id, spec, "Главным остаётся расчёт КП.")

    def test_compare_same_measure(self):
        """Состав не трогали — «в заявку по КП» и «сейчас» совпадают."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._signals(tech)
        left, right = (part.strip() for part in tech.pmk_kp_compare_weight.split("→"))
        self.assertEqual(left, right, "Одна мера: целые листы с обеих сторон.")
        self.assertTrue(tech.pmk_kp_compare_unpriced, "Балка без цены — жёлтая карточка.")

    def test_without_planner_row(self):
        _deal, _spec, order, row = self._flow(won=False)
        self.assertFalse(row)
        tech = self._tech(order)
        self._request(tech)
        orders = self._requests(tech)
        self.assertTrue(orders)
        self.assertFalse(orders.pmk_task_id, "Строки нет — ссылки нет, ошибки нет.")

    # ─── Права ──────────────────────────────────────────────────────────
    def test_salesman_without_purchase(self):
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order, user=self.salesman)
        self.assertEqual(tech.pmk_kind, "tech", "Технический заводит и продавец.")
        views = tech.with_user(self.salesman).get_views([(False, "form")])["views"]
        arch = etree.fromstring(views["form"]["arch"])
        self.assertFalse(arch.xpath("//button[@name='action_pmk_metal_request']"),
                         "Заявки — только «Закупкам».")
        self.assertFalse(arch.xpath("//field[@name='pmk_metal_request_count']"))
        self.assertFalse(arch.xpath("//div[@name='pmk_request_stale']"),
                         "Призыв нажать «Заявку на металл» — только тем, у кого она есть.")
        data = tech.with_user(self.salesman).read(["pmk_kp_compare_weight", "pmk_request_warn_text"])
        self.assertTrue(data[0]["pmk_kp_compare_weight"])
        order_views = order.with_user(self.salesman).get_views([(False, "form")])["views"]
        order_arch = etree.fromstring(order_views["form"]["arch"])
        self.assertFalse(order_arch.xpath("//field[@name='pmk_metal_request_count']"))

    # ─── Виды ───────────────────────────────────────────────────────────
    def test_views(self):
        for xmlid in ("pmk_tech.view_metal_spec_form_tech", "pmk_tech.view_metal_spec_list_tech",
                      "pmk_tech.view_metal_spec_search_tech", "pmk_tech.view_order_form_pmk_tech",
                      "pmk_tech.view_task_order_form_pmk_tech", "pmk_tech.purchase_order_form_pmk_tech",
                      "pmk_tech.purchase_order_filter_pmk_tech", "pmk_tech.view_metal_request_list",
                      "pmk_tech.view_metal_request_search"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active, "Вид не выключен при загрузке.")

        spec_arch = etree.fromstring(self.Spec.with_user(self.engineer).get_views(
            [(False, "form")])["views"]["form"]["arch"])
        header = spec_arch.find(".//header")
        filled = [b for b in header.iter("button") if _filled(b)]
        tech_only = [b.get("name") for b in filled if b.get("invisible") == "pmk_kind != 'tech'"]
        kp_only = [b.get("name") for b in filled if b.get("invisible") == "pmk_kind == 'tech'"]
        self.assertEqual(tech_only, ["action_pmk_metal_request"], "У технического залитая одна.")
        self.assertEqual(kp_only, ["action_print_quotation"], "У расчёта КП — «КП (PDF)».")
        send = header.xpath("./button[@name='action_send_quotation']")[0]
        self.assertEqual(send.get("invisible"), "pmk_kind == 'tech'")
        self.assertTrue(spec_arch.xpath("//div[@name='pmk_tech_ref']"))
        self.assertTrue(spec_arch.xpath("//div[@name='pmk_kp_compare']"))
        self.assertTrue(spec_arch.xpath("//div[@name='pmk_tech_outdated']"))
        # Сравнение — на месте карточки моста «Металл к закупке»: у
        # технического карточек четыре (сетка 2×2), одно «к закупке».
        kpi = spec_arch.xpath("//div[contains(@class, 'pmk-kpi') and not(contains(@class, 'pmk-kpi__'))]")[0]
        cards = [c for c in kpi if c.tag == "div" and "pmk-kpi__card" in (c.get("class") or "")]
        labels = [c.xpath("string(./div[contains(@class, 'pmk-kpi__label')])").strip() for c in cards]
        metal = [c for c, lab in zip(cards, labels) if lab == "Металл к закупке"]
        self.assertEqual(len(metal), 2)
        for card in metal:
            self.assertIn("pmk_kind == 'tech'", card.get("invisible"))
        compare = [lab for lab in labels if lab == "Металл в заявку, т"]
        self.assertEqual(len(compare), 2, "Обычная и жёлтая (без цены).")
        self.assertEqual(labels.index("Металл в заявку, т"), labels.index("Металл к закупке") + 2,
                         "Сразу за карточками моста — на их месте.")

        listing = etree.fromstring(self.Spec.get_views([(False, "list")])["views"]["list"]["arch"])
        kind = listing.xpath("//field[@name='pmk_kind']")[0]
        self.assertEqual(kind.get("string"), "Вид")
        self.assertEqual(kind.get("widget"), "badge")

        menu = self.env.ref("pmk_tech.menu_metal_requests")
        self.assertEqual(menu.parent_id, self.env.ref("pmk_theme.menu_pmk_purchase"))
        self.assertEqual(menu.action, self.env.ref("pmk_tech.action_metal_requests"))
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_tech.action_metal_requests")
        self.assertEqual(action["name"], "Заявки на металл")
        self.assertIn("pmk_tech_spec_id", action["domain"])
        request_list = self.env.ref("pmk_tech.view_metal_request_list")
        columns = [f.get("name") for f in etree.fromstring(request_list.arch).iter("field")
                   if f.get("column_invisible") != "1"]
        for name in ("name", "partner_id", "pmk_deal_number", "pmk_client_id", "pmk_sale_order_id",
                     "pmk_tech_spec_id", "amount_total", "date_planned", "pmk_request_state_label"):
            self.assertIn(name, columns)

        po_arch = etree.fromstring(self.env["purchase.order"].with_user(self.engineer).get_views(
            [(self.env.ref("purchase.purchase_order_form").id, "form")])["views"]["form"]["arch"])
        labels = po_arch.xpath("//div[contains(@class, 'oe_title')]/span")
        texts = [(s.text or "").strip() for s in labels]
        self.assertIn("Заявка на металл", texts, "У заявки — своё слово, не «Запрос КП».")
        # С шага З-6 штатные кнопки всех закупок — тем же словом (pmk_purchase);
        # у заявки они спрятаны условием, свои — «not pmk_tech_spec_id».
        send = [b for b in po_arch.xpath("//header/button[@name='action_rfq_send']"
                                         "[@string='Отправить заявку поставщику']")
                if "not pmk_tech_spec_id" in (b.get("invisible") or "")]
        self.assertEqual(len(send), 2, "Черновик (залитая) и отправленная (контурная).")
        self.assertEqual([_filled(b) for b in send], [True, False])
        for button in send:
            self.assertIn("pmk_no_supplier", button.get("invisible"),
                          "«Поставщик не выбран»: следующий шаг — выбрать поставщика.")

        search = etree.fromstring(self.env.ref("pmk_tech.view_metal_request_search").arch)
        confirmed = search.xpath("//filter[@name='pmk_confirmed']")[0]
        self.assertNotIn("to approve", confirmed.get("domain"),
                         "«Подтверждены» без «На согласовании».")
        self.assertTrue(search.xpath("//filter[@name='pmk_to_approve']"))

        so_arch = etree.fromstring(self.env["sale.order"].with_user(self.engineer).get_views(
            [(False, "form")])["views"]["form"]["arch"])
        so_buttons = [b for b in so_arch.find(".//header") if b.tag == "button"]
        tech_buttons = [b for b in so_buttons if b.get("name") == "action_pmk_tech_spec"]
        self.assertEqual(len(tech_buttons), 2)
        self.assertTrue(_filled(tech_buttons[0]))
        confirm = so_arch.xpath("//header/button[@id='action_confirm']")[0]
        self.assertLess(so_buttons.index(tech_buttons[0]), so_buttons.index(confirm),
                        "Залитая (счёт в работе) — в начале шапки.")
        self.assertGreater(so_buttons.index(tech_buttons[1]), so_buttons.index(confirm),
                           "Контурная — после «Оплата пришла»: на узком экране первой "
                           "видна главная кнопка.")

        task_arch = etree.fromstring(self.env["project.task"].with_user(self.engineer).get_views(
            [(self.env.ref("pmk_orders.view_task_order_form").id, "form")])["views"]["form"]["arch"])
        names = {b.get("name") for b in task_arch.xpath("//header/button") if _filled(b)}
        self.assertEqual(names, {"action_pmk_tech_spec", "action_pmk_metal_request"})

    def test_flow_map(self):
        if "pmk.flow.builder" not in self.env:
            self.skipTest("pmk_flow не стоит.")
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        graph = self.env["pmk.flow.builder"].get_flow_graph("pmk.metal.spec", tech.id)
        nodes = {(n["model"], n["res_id"]): n for n in graph["nodes"]}
        self.assertEqual(nodes[("pmk.metal.spec", tech.id)]["kind"], "Технический расчёт")
        self.assertIn(("sale.order", order.id), nodes)
        for po in self._requests(tech):
            self.assertEqual(nodes[("purchase.order", po.id)]["kind"], "Заявка на металл")
            self.assertEqual(nodes[("purchase.order", po.id)]["state"], "Заявка",
                             "Состояние — словами списка (= строки состояния формы), не «Запрос КП».")
        kp = self.env["pmk.flow.builder"].get_flow_graph("sale.order", order.id)
        self.assertIn(("pmk.metal.spec", tech.id), {(n["model"], n["res_id"]) for n in kp["nodes"]})
