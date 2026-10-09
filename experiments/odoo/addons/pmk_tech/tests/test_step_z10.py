# -*- coding: utf-8 -*-
"""Позиция «на разнос» в «Заявке на металл» — разбор UX, шаг З-10 (09.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные
шага З-4 (Z4Common) + позиция «на разнос», заведённая инженером.

Что ловим:
  • позиция «на разнос» (карточки товара нет) идёт в заявку, а не в «нет
    карточки — в заявку не идёт»: строкой своего названия на служебный товар
    «Позиция на разнос (прокат)» в черновике «Поставщик не выбран», с меткой
    «на разнос», количество — метрами, как у проката; плашка технического
    расчёта называет её;
  • в заявке — счётчик строк «на разнос» (плашка и колонка формы);
  • «Привязать к существующей» → заметка в ленте технического расчёта
    («нажмите «Заявка на металл»»); повторная заявка ставит настоящую
    позицию: строка «на разнос» уходит, метры — к настоящему товару;
  • доводка: строка «на разнос», ушедшая поставщику до разноса, второй раз
    не заказывается — ключ переписан, повтор дозаказывает остаток;
  • слова: «снабженец», не «закупщик».
"""
from lxml import etree

from odoo import Command
from odoo.tests import new_test_user, tagged

from .test_step_z4 import Z4Common


@tagged("post_install", "-at_install")
class TestStepZ10Request(Z4Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ref_admin = new_test_user(
            cls.env, login="pmkz10_ref_admin", name="Администратор справочника (З-10)",
            groups="base.group_user,base.group_system")

    def _pending(self, **vals):
        values = {"pmk_pending_name": "Уголок 75×6 09Г2С", "mass_per_meter": 6.89}
        values.update(vals)
        return self.env["pmk.metal.profile"].with_user(self.engineer).with_context(
            default_pmk_pending=True).create(values)

    def _add_line(self, tech, profile, length=1500.0, qty=2):
        product = tech.product_ids[:1]
        product.with_user(self.engineer).write({"line_ids": [Command.create({
            "calc_mode": "linear", "detail_name": "Связь", "profile_id": profile.id,
            "length_mm": length, "qty": qty})]})
        return product.line_ids.filtered(lambda l: l.profile_id == profile)

    def test_pending_in_request_then_bound(self):
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        pending = self._pending()
        self.assertTrue(pending.pmk_pending, "Инженер завёл позицию «на разнос».")
        line = self._add_line(tech, pending)
        self.assertEqual(line.pmk_item_note, "на разнос")
        self.assertEqual(tech.pmk_pending_count, 1)

        self._request(tech)
        orders = self._requests(tech)
        rows = orders.order_line.filtered("pmk_pending")
        self.assertEqual(len(rows), 1, "Позиция «на разнос» — в заявке, а не выпала.")
        self.assertEqual(rows.product_id, self.env.ref("pmk_tech.product_pending_linear"))
        self.assertEqual(rows.order_id.partner_id, self.placeholder, "Цены нет — поставщик не выбран.")
        self.assertIn("Уголок 75×6 09Г2С", rows.name, "Название из чертежа — в описании.")
        self.assertEqual(rows.pmk_pending_label, "на разнос")
        self.assertEqual(rows.product_uom_id, self.env.ref("uom.product_uom_meter"))
        share = (line.utilization_pct or 100.0) / 100.0
        self.assertAlmostEqual(rows.product_qty, round(1.5 * 2 * 2 / share, 2), places=2,
                               msg="Метры: длина × кол-во × изделий.")
        self.assertEqual(rows.price_unit, 0.0)
        self.assertEqual(rows.order_id.pmk_pending_line_count, 1)
        self.assertTrue(rows.pmk_request_key.startswith("linear:pending:pmk.metal.profile:"))
        self._signals(tech)
        self.assertIn("Позиции на разнос", tech.pmk_request_warn_text or "")
        self.assertIn("Уголок 75×6 09Г2С", tech.pmk_request_warn_text)
        self.assertNotIn("в заявку не идут: Уголок 75×6", tech.pmk_request_warn_text,
                         "Не «нет карточки — не идёт».")

        angle_line = self._line(orders.filtered(lambda o: o.partner_id == self.supplier),
                                "Уголок 100×8 (тест З-4)")
        meters_before = angle_line.product_qty

        pending.with_user(self.ref_admin)._pmk_pending_bind(self.angle)
        tech.invalidate_recordset(["message_ids"])
        notes = " ".join(str(m.body) for m in tech.message_ids)
        self.assertIn("нажмите «Заявка на металл»", notes)
        self._signals(tech)
        self.assertTrue(tech.pmk_request_stale, "Состав изменился после заявки.")

        self._request(tech)
        orders = self._requests(tech)
        self.assertFalse(orders.order_line.filtered("pmk_pending"), "Строка «на разнос» ушла.")
        angle_line = self._line(orders.filtered(lambda o: o.partner_id == self.supplier),
                                "Уголок 100×8 (тест З-4)")
        self.assertGreater(angle_line.product_qty, meters_before, "Метры — к настоящему товару.")

    def test_sent_pending_line_not_ordered_twice(self):
        """Доводка З-10: строка «на разнос» ушла поставщику, потом позицию
        привязали к существующей. Ключ ушедшей строки переписан на настоящую
        позицию, повтор «Заявки на металл» не заказывает этот металл второй
        раз — дозаказывает только остаток (та же позиция стоит в расчёте и
        сама), и плашка «нажмите «Заявка на металл»» после повтора гаснет."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        pending = self._pending()
        self._add_line(tech, pending)
        self._request(tech)
        orders = self._requests(tech)
        sent = orders.order_line.filtered("pmk_pending")
        self.assertEqual(len(sent), 1)
        sent.order_id.sudo().write({"state": "sent"})
        sent_qty = sent.product_qty

        pending.with_user(self.ref_admin)._pmk_pending_bind(self.angle)
        real_key = "linear:%s" % self.angle.product_tmpl_id.id
        self.assertEqual(sent.pmk_request_key, real_key, "Ключ ушедшей строки — настоящий.")
        self.assertTrue(sent.pmk_pending, "Метка остаётся: это заказанная часть.")

        rows, _notes = tech._pmk_metal_rows()
        total = {row["key"]: row["qty"] for row in rows}[real_key]
        self._request(tech)
        orders = self._requests(tech)
        self.assertEqual(orders.order_line.filtered("pmk_pending"), sent,
                         "Новой строки «на разнос» нет, ушедшая осталась.")
        angle_line = self._line(orders.filtered(lambda o: o.partner_id == self.supplier),
                                "Уголок 100×8 (тест З-4)")
        self.assertAlmostEqual(angle_line.product_qty, round(total - sent_qty, 2), places=2,
                               msg="Дозаказан только остаток, не второй раз целиком.")
        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale, "После повтора состав совпадает с заявкой.")
        self.assertNotIn("Уголок 100×8", tech.pmk_request_diff_text or "",
                         "Расхождения нет: «на разнос» + остаток = потребность.")

    def test_draft_pending_line_not_rekeyed(self):
        """Черновик не переписываем: повтор ставит настоящий товар."""
        _deal, _spec, order, _row = self._flow()
        tech = self._tech(order)
        pending = self._pending()
        self._add_line(tech, pending)
        self._request(tech)
        draft = self._requests(tech).order_line.filtered("pmk_pending")
        pending.with_user(self.ref_admin)._pmk_pending_bind(self.angle)
        self.assertTrue(draft.pmk_request_key.startswith("linear:pending:"))

    def test_pending_product_recreated(self):
        """Служебный товар удалили — заявка заведёт его заново, не упадёт."""
        PO = self.env["purchase.order"]
        product = PO._pmk_pending_product("sheet")
        self.assertEqual(product, self.env.ref("pmk_tech.product_pending_sheet"))
        self.assertFalse(product.is_storable, "Без склада.")
        self.assertFalse(product.sale_ok)
        self.env["ir.model.data"].search([
            ("module", "=", "pmk_tech"), ("name", "=", "product_pending_sheet")]).unlink()
        self.assertFalse(PO._pmk_pending_product("sheet", create=False))
        again = PO._pmk_pending_product("sheet")
        self.assertTrue(again)
        self.assertEqual(again, self.env.ref("pmk_tech.product_pending_sheet"))

    def test_request_form_pending_marks(self):
        arch = etree.fromstring(self.env["purchase.order"].get_view(
            self.env.ref("purchase.purchase_order_form").id, "form")["arch"])
        self.assertTrue(arch.xpath("//div[@name='pmk_pending_lines']"))
        col = arch.xpath("//field[@name='order_line']/list/field[@name='pmk_pending_label']")
        self.assertTrue(col)
        self.assertEqual(col[0].get("column_invisible"), "not parent.pmk_pending_line_count")
        text = " ".join(arch.xpath("//div[@name='pmk_pending_lines']//text()"))
        self.assertNotIn("закупщик", text.lower())
