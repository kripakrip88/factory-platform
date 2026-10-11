# -*- coding: utf-8 -*-
"""Строка «Заказов в работе»: название, срок, предоплата (разбор UX, шаг З-15,
11.10.2026), pmk_orders.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

Что ловим:
  • название новой строки — «Предмет КП» расчёта счёта; пусто — первое
    изделие и «+N»; нет расчёта — имя сделки; клиент — своим полем;
  • старт и сдача (план) — из срока счёта в рабочих днях: «с момента
    оплаты» — от «Выиграно», «с даты счёта» — от отправки счёта (а не от
    date_order, которую ядро переписывает при подтверждении), «с
    согласования чертежей» и срок 0 — без дат, подсказка в ленте строки;
    праздник календаря компании пропускается; пятница + 1 = понедельник;
  • первая дата оплаты пересчитывает старт и сдачу, вторая — нет; ручная
    правка сдачи — флаг, дальше без пересчёта; очистили — тоже ручная
    правка: пусто, в ленте расчётная дата; гарантийное письмо — оплата
    сдачу не двигает; галочка в строке и правка старта такой строки —
    пересчёт от старта (дня письма);
  • найденная строка (заведена кнопкой «Заказ» / до «Выиграно») и форма
    «Новое» со счётом «с согласования чертежей» — подсказка в ленте, один раз;
  • кнопка «Выиграно» на сделке открывает окно «Оплата / гарантия»;
    «Готово» — сделка выиграна, сумма и дата оплаты в строке, сдача от даты
    оплаты, заметки в ленте сделки и счёта, писем нет; оплата в день
    «Выиграно» — итоговая заметка «от даты оплаты» в ленте строки; у сделки
    две строки — оплата в одну (действующую со счётом); гарантийное письмо —
    галочка, старт от письма; «Пропустить» и перетаскивание — как раньше;
  • продавец без «Проектов» проходит окно;
  • виды: наша кнопка на месте штатной (та же видимость, контурная, w),
    штатная спрятана, а не удалена; в окне одна залитая «Готово»; в форме
    строки «Гарантийное письмо» и «Срок изготовления»; подписи окна и строки
    одинаковые («Сумма оплаты», «Дата оплаты»), срок — как в счёте;
  • строка импорта (сдача из Excel) — «правили руками», дата оплаты её не
    двигает; форма «Новое» с подсказанной сдачей — не «руками».

Глазами (окно в светлой и тёмной теме, форма строки, канбан) — основной
агент на копии.
"""
import datetime

import pytz
from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import freeze_time

from ..models.work_days import add_work_days
from .test_step_z2_invoice import Z2Common

D = datetime.date
WON_MOMENT = "2026-10-09 06:00:00"  # пятница; в любом поясе от −6 до +17 — тот же день
PROFILES = [
    ("Профиль П-образный 30×60, стенка 3 мм, L=3000", 1850, 120.0),
    ("Профиль Z-образный 400×80, стенка 3 мм, L=3000", 795, 900.0),
]
WON_INVISIBLE = "won_status == 'won' or type == 'lead' or not active"


def hidden(node):
    return (node.get("invisible") or "").strip() in ("1", "True", "true")


@tagged("post_install", "-at_install")
class TestStepZ15OrderRow(Z2Common):

    # ─── помощники ──────────────────────────────────────────────────────
    def _sent(self, days=15, lead_from="payment", user=None, **spec_values):
        """Сделка → расчёт → «Отправить КП» (счёт «Отправлен») → условия."""
        deal = self._deal(user=user)
        spec = self._spec(deal, user=user, **spec_values)
        self._send_kp(deal, spec, user=user)
        invoice = self._invoices(deal)
        self.assertEqual(len(invoice), 1, "Посылка: счёт отправлен.")
        invoice.sudo().write({"pmk_lead_days": days, "pmk_lead_from": lead_from,
                              "pmk_payment_note": "50% предоплата, 50% перед отгрузкой"})
        return deal, spec, invoice

    def _won(self, deal):
        with freeze_time(WON_MOMENT):
            deal.action_set_won()
        return self._rows(deal)

    def _row_notes(self, row):
        row.invalidate_recordset(["message_ids"])
        return " ".join(str(m.body) for m in row.message_ids)

    def _wizard(self, deal, user=None, **values):
        vals = {"lead_id": deal.id}
        vals.update(values)
        return self.env["pmk.orders.won.wizard"].with_user(user or self.manager).create(vals)

    def _deal_arch(self):
        views = self.env["crm.lead"].with_user(self.manager).get_views(
            [(self.env.ref("crm.crm_lead_view_form").id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    # ─── Название строки ────────────────────────────────────────────────
    def test_name_from_kp_subject(self):
        deal, _spec, _invoice = self._sent()
        row = self._won(deal)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.name, "Ограждение лестницы", "«Предмет КП» расчёта, не имя сделки.")
        self.assertEqual(row.partner_id, self.client, "Клиент — своим полем.")

    def test_name_from_products(self):
        deal, _spec, _invoice = self._sent(note="", products=PROFILES)
        row = self._won(deal)
        self.assertEqual(row.name, "Профиль П-образный 30×60, стенка 3 мм, L=3000 +1",
                         "Первое изделие целиком и «+N» остальных.")
        single = self._deal(name="Одно изделие (шаг З-15)")
        self._spec(single, note="", products=PROFILES[:1])
        self._send_kp(single)
        self.assertEqual(self._won(single).name, PROFILES[0][0], "Одно изделие — без «+N».")

    def test_name_without_spec_is_deal(self):
        deal = self._deal()
        row = self._won(deal)
        self.assertEqual(row.name, "Ограждение лестницы (шаг З-2)", "Без расчёта — как раньше.")
        self.assertFalse(row.pmk_date_due, "Без счёта срока нет.")

    def test_name_from_deal_spec_when_invoice_has_none(self):
        deal = self._deal()
        self._spec(deal, note="Площадка обслуживания")
        Task = self.env["project.task"]
        self.assertEqual(Task._pmk_row_name(deal, self.env["sale.order"]), "Площадка обслуживания",
                         "Счёта нет — расчёт сделки.")

    # ─── Даты ───────────────────────────────────────────────────────────
    def test_dates_from_won_payment_term(self):
        deal, _spec, invoice = self._sent(days=15, lead_from="payment")
        row = self._won(deal)
        self.assertEqual(row.pmk_date_start, D(2026, 10, 9), "Старт — день «Выиграно».")
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30), "Пятница + 15 рабочих дней.")
        self.assertFalse(row.pmk_date_due_manual)
        self.assertEqual(row.pmk_lead_text, "15 раб. дней с момента оплаты")
        notes = self._row_notes(row)
        self.assertIn("30.10.2026", notes)
        self.assertIn("15 раб. дней с момента оплаты", notes)
        self.assertIn("пересчитаем", notes, "Подсказка: придёт оплата — пересчёт.")
        self.assertEqual(invoice.state, "sale")

    def test_dates_from_invoice_sent_day(self):
        with freeze_time("2026-10-05 06:00:00"):
            deal, _spec, invoice = self._sent(days=15, lead_from="invoice")
        row = self._won(deal)
        self.assertEqual(invoice.date_order.date(), D(2026, 10, 9),
                         "Посылка: ядро переписало дату счёта при подтверждении.")
        self.assertEqual(row.pmk_date_start, D(2026, 10, 5), "Старт — день отправки счёта.")
        self.assertEqual(row.pmk_date_due, D(2026, 10, 26))
        self.assertIn("отправки счёта", self._row_notes(row))

    def test_drawings_and_no_term_without_dates(self):
        deal, _spec, _invoice = self._sent(days=10, lead_from="drawings")
        row = self._won(deal)
        self.assertFalse(row.pmk_date_start)
        self.assertFalse(row.pmk_date_due)
        self.assertIn("согласуют чертежи", self._row_notes(row))
        other, _spec, _invoice = self._sent(days=0)
        row = self._won(other)
        self.assertFalse(row.pmk_date_due)
        self.assertIn("не указан срок изготовления", self._row_notes(row))

    def test_holiday_skipped(self):
        calendar = self.company.resource_calendar_id
        self.assertTrue(calendar, "Посылка: у компании есть календарь рабочего времени.")
        tz = pytz.timezone(calendar.tz or "UTC")

        def utc(moment):
            return tz.localize(moment).astimezone(pytz.utc).replace(tzinfo=None)
        self.env["resource.calendar.leaves"].create({
            "name": "Праздник (шаг З-15)", "calendar_id": calendar.id,
            "date_from": utc(datetime.datetime(2026, 10, 30)),
            "date_to": utc(datetime.datetime(2026, 10, 30, 23, 59, 59)),
        })
        deal, _spec, _invoice = self._sent(days=15)
        row = self._won(deal)
        self.assertEqual(row.pmk_date_due, D(2026, 11, 2), "30.10 нерабочий — сдача в понедельник.")

    def test_add_work_days(self):
        self.assertEqual(add_work_days(D(2026, 10, 9), 1), D(2026, 10, 12), "Пятница + 1 = понедельник.")
        self.assertEqual(add_work_days(D(2026, 10, 10), 1), D(2026, 10, 12), "Суббота + 1 = понедельник.")
        self.assertEqual(add_work_days(D(2026, 10, 9), 0), D(2026, 10, 9))
        self.assertEqual(add_work_days(D(2026, 10, 9), 15), D(2026, 10, 30))
        self.assertEqual(add_work_days(D(2026, 10, 9), 1, holidays={D(2026, 10, 12)}), D(2026, 10, 13))
        self.assertEqual(add_work_days(D(2026, 10, 9), 3, workdays=set()), D(2026, 10, 14),
                         "Календарь без рабочих дней — пн–пт.")

    # ─── Пересчёт от оплаты ─────────────────────────────────────────────
    def test_first_payment_replans(self):
        deal, _spec, invoice = self._sent(days=15)
        row = self._won(deal)
        row.write({"pmk_paid_date": D(2026, 10, 14), "pmk_paid_amount": invoice.amount_total / 2})
        self.assertEqual(row.pmk_date_start, D(2026, 10, 14), "Старт — дата оплаты.")
        # 04.11 — рабочий: праздник 4 ноября в календаре не заведён.
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4))
        self.assertFalse(row.pmk_date_due_manual)
        self.assertIn("Пришла оплата", self._row_notes(row))
        row.write({"pmk_paid_date": D(2026, 10, 20), "pmk_paid_amount": invoice.amount_total})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4), "Вторая оплата / правка даты сдачу не двигают.")

    def test_manual_due_kept_and_cleared(self):
        deal, _spec, _invoice = self._sent(days=15)
        row = self._won(deal)
        row.write({"pmk_date_due": D(2026, 11, 20)})
        self.assertTrue(row.pmk_date_due_manual, "Поправили руками — флаг.")
        row.write({"pmk_paid_date": D(2026, 10, 14)})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 20), "Ручная сдача не пересчитывается.")
        self.assertEqual(row.pmk_date_start, D(2026, 10, 9))
        row.write({"pmk_date_due": False})
        self.assertTrue(row.pmk_date_due_manual, "Очистка — тоже ручная правка.")
        self.assertFalse(row.pmk_date_due, "Срок неизвестен — пусто, сами не заполняем.")
        self.assertIn("было бы 04.11.2026", self._row_notes(row), "Расчётная дата — в ленте.")
        row.write({"pmk_paid_date": D(2026, 10, 20)})
        self.assertFalse(row.pmk_date_due, "Очищенную не заполняем и потом.")
        invoice = row.pmk_sale_order_id
        invoice._pmk_ensure_planner_row()
        self.assertFalse(row.pmk_date_due, "Повторная связка со счётом — тоже нет.")

    def test_guarantee_ignores_payment(self):
        deal, _spec, _invoice = self._sent(days=15)
        row = self._won(deal)
        row.write({"pmk_guarantee": True})
        self.assertIn("Гарантийное письмо. Сдача (план) 30.10.2026", self._row_notes(row),
                      "Галочка — итоговая заметка, даже если даты те же.")
        row.write({"pmk_paid_date": D(2026, 10, 14)})
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30), "По гарантийному письму оплата срок не двигает.")

    def test_guarantee_in_row_replans(self):
        """Выиграли перетаскиванием, письмо пришло позже — галочка и старт в строке."""
        deal, _spec, _invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            deal.write({"stage_id": self.stage_won.id})
        row = self._rows(deal)
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30))
        row.write({"pmk_guarantee": True, "pmk_date_start": D(2026, 10, 14)})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4), "Срок — от дня письма.")
        self.assertFalse(row.pmk_date_due_manual)
        self.assertIn("отсчёт от 14.10.2026 (гарантийного письма)", self._row_notes(row))
        row.write({"pmk_date_start": D(2026, 10, 15)})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 5), "Поправили день письма — сдача следом.")
        row.write({"pmk_paid_date": D(2026, 10, 20)})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 5), "Оплата после письма срок не двигает.")
        row.write({"pmk_date_start": D(2026, 10, 16), "pmk_date_due": D(2026, 11, 27)})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 27), "Сдачу правят тут же — ручная, не трогаем.")

    # ─── Окно «Оплата / гарантия» ───────────────────────────────────────
    def test_won_button_opens_window(self):
        deal, _spec, _invoice = self._sent()
        action = deal.with_user(self.manager).action_pmk_won()
        self.assertEqual(action["res_model"], "pmk.orders.won.wizard")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_lead_id"], deal.id)
        self.assertEqual(action["views"][0][0],
                         self.env.ref("pmk_orders.view_pmk_orders_won_wizard_form").id)
        self.assertEqual(deal.won_status, "pending", "Окно ещё ничего не выиграло.")
        self.assertFalse(self._rows(deal))
        self._won(deal)
        again = deal.with_user(self.manager).action_pmk_won()
        self.assertNotEqual(again.get("res_model") if isinstance(again, dict) else None,
                            "pmk.orders.won.wizard", "Выигранная — без окна, как штатная.")

    def test_window_done_with_prepayment(self):
        deal, _spec, invoice = self._sent(days=15)
        half = invoice.currency_id.round(invoice.amount_total / 2)
        mails = self.env["mail.mail"].search_count([])
        with freeze_time(WON_MOMENT):
            wizard = self._wizard(deal, amount=half, date=D(2026, 10, 14))
            self.assertIn("50 %% от счёта %s" % invoice.display_name, wizard.pct_hint)
            self.assertIn("04.11.2026", wizard.due_hint)
            result = wizard.action_done()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(deal.won_status, "won")
        row = self._rows(deal)
        self.assertEqual(len(row), 1)
        self.assertAlmostEqual(row.pmk_paid_amount, half, places=2)
        self.assertEqual(row.pmk_paid_date, D(2026, 10, 14))
        self.assertAlmostEqual(row.pmk_paid_pct, 50.0, places=0)
        self.assertFalse(row.pmk_guarantee)
        self.assertEqual(row.pmk_date_start, D(2026, 10, 14), "Сдача — от даты оплаты.")
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4))
        for name, notes in (("сделки", self._notes(deal)), ("счёта", self._notes(invoice))):
            with self.subTest(feed=name):
                self.assertIn("Выиграно: оплата", notes)
                self.assertIn("50 % от счёта", notes)
                self.assertIn("14.10.2026", notes)
        self.assertEqual(self.env["mail.mail"].search_count([]), mails, "Писем нет.")
        self.assertIn("Пришла оплата. Сдача (план) 04.11.2026", self._row_notes(row))

    def test_window_same_day_payment_note(self):
        """Оплата в день «Выиграно»: даты не меняются, но в ленте строки —
        итоговая заметка «от даты оплаты», а не только «придёт оплата —
        пересчитаем»."""
        deal, _spec, invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            wizard = self._wizard(deal, amount=invoice.amount_total / 2)
            self.assertEqual(wizard.date, D(2026, 10, 9), "Дата оплаты по умолчанию — сегодня.")
            wizard.action_done()
        row = self._rows(deal)
        self.assertEqual(row.pmk_paid_date, D(2026, 10, 9))
        self.assertEqual((row.pmk_date_start, row.pmk_date_due), (D(2026, 10, 9), D(2026, 10, 30)))
        notes = self._row_notes(row)
        self.assertIn("Пришла оплата. Сдача (план) 30.10.2026", notes)
        self.assertIn("отсчёт от 09.10.2026 (даты оплаты)", notes)
        self.assertEqual(notes.count("Пришла оплата"), 1, "Заметка одна.")

    def test_window_writes_one_row(self):
        """У сделки две строки (объединение, архивная) — оплата в одну."""
        deal, _spec, invoice = self._sent(days=15)
        Task = self.env["project.task"]
        live = Task.create({"name": "Действующая (шаг З-15)", "project_id": self.project.id,
                            "stage_id": self.queue.id, "pmk_deal_id": deal.id})
        archived = Task.create({"name": "Архивная (шаг З-15)", "project_id": self.project.id,
                                "stage_id": self.queue.id, "pmk_deal_id": deal.id,
                                "active": False})
        with freeze_time(WON_MOMENT):
            self._wizard(deal, amount=500000.0, date=D(2026, 10, 14)).action_done()
        self.assertEqual(self._rows(deal), live | archived, "Новая строка не заводится.")
        self.assertEqual(live.pmk_paid_amount, 500000.0)
        self.assertEqual(live.pmk_paid_date, D(2026, 10, 14))
        self.assertFalse(archived.pmk_paid_amount, "Чужую оплату в архивную не пишем.")
        self.assertFalse(archived.pmk_paid_date)
        self.assertIn("Записано в строку «Действующая (шаг З-15)»", self._notes(deal))
        self.assertIn("Записано в строку", self._notes(invoice))

    def test_window_hint_without_amount(self):
        deal, _spec, invoice = self._sent()
        wizard = self._wizard(deal)
        self.assertEqual(wizard.amount, 0.0, "Предоплата по умолчанию пустая.")
        self.assertIn("Счёт %s" % invoice.display_name, wizard.pct_hint)
        self.assertIn("50% предоплата", wizard.pct_hint, "Условие оплаты счёта — подсказкой.")
        bare = self._deal(name="Без счёта (шаг З-15)")
        self.assertIn("Счёта у сделки нет", self._wizard(bare).pct_hint)

    def test_window_less_than_kopeck_is_no_payment(self):
        deal, _spec, _invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            self._wizard(deal, amount=0.0025, date=D(2026, 10, 14)).action_done()
        self.assertEqual(deal.won_status, "won")
        row = self._rows(deal)
        self.assertFalse(row.pmk_paid_amount, "Меньше копейки — не оплата.")
        self.assertFalse(row.pmk_paid_date)
        self.assertNotIn("оплата 0,00", self._notes(deal))

    def test_window_guarantee(self):
        deal, _spec, invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            self._wizard(deal, guarantee=True, date=D(2026, 10, 14)).action_done()
        row = self._rows(deal)
        self.assertTrue(row.pmk_guarantee)
        self.assertFalse(row.pmk_paid_date)
        self.assertFalse(row.pmk_paid_amount)
        self.assertEqual(row.pmk_date_start, D(2026, 10, 14), "Старт — день гарантийного письма.")
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4))
        self.assertIn("гарантийное письмо от 14.10.2026", self._notes(deal))
        self.assertIn("гарантийное письмо от 14.10.2026", self._notes(invoice))
        row.write({"pmk_paid_date": D(2026, 10, 20), "pmk_paid_amount": invoice.amount_total})
        self.assertEqual(row.pmk_date_due, D(2026, 11, 4), "Оплата после письма срок не двигает.")

    def test_window_skip_and_drag(self):
        deal, _spec, _invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            result = self._wizard(deal, amount=1000.0).action_skip()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(deal.won_status, "won")
        row = self._rows(deal)
        self.assertFalse(row.pmk_paid_amount, "«Пропустить» — без предоплаты.")
        self.assertFalse(row.pmk_paid_date)
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30))
        dragged, _spec, _invoice = self._sent(days=15)
        with freeze_time(WON_MOMENT):
            dragged.write({"stage_id": self.stage_won.id})
        row = self._rows(dragged)
        self.assertEqual(len(row), 1, "Перетаскивание — строка как раньше.")
        self.assertFalse(row.pmk_paid_amount)
        self.assertFalse(row.pmk_guarantee)
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30))

    def test_window_negative_amount_refused(self):
        from odoo.exceptions import UserError
        deal, _spec, _invoice = self._sent()
        with self.assertRaises(UserError):
            self._wizard(deal, amount=-5.0).action_done()

    def test_salesman_without_projects(self):
        deal, _spec, invoice = self._sent(days=15, user=self.salesman)
        with freeze_time(WON_MOMENT):
            self._wizard(deal, user=self.salesman, amount=invoice.amount_total,
                         date=D(2026, 10, 9)).action_done()
        self.assertEqual(deal.won_status, "won")
        row = self._rows(deal)
        self.assertAlmostEqual(row.pmk_paid_pct, 100.0, places=0)
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30))
        self.assertIn("(даты оплаты)", self._row_notes(row), "Итоговая заметка и у продавца.")

    def test_found_row_gets_dates(self):
        deal, _spec, invoice = self._sent(days=15)
        row = self.env["project.task"].create({
            "name": "Заведена руками (шаг З-15)", "project_id": self.project.id,
            "stage_id": self.queue.id, "pmk_deal_id": deal.id})
        with freeze_time(WON_MOMENT):
            invoice.action_confirm()  # «Оплата пришла — в работу»
        self.assertEqual(self._rows(deal), row, "Строка одна — найденная.")
        self.assertEqual(row.pmk_sale_order_id, invoice)
        self.assertEqual(row.name, "Заведена руками (шаг З-15)", "Название не переписываем.")
        self.assertEqual(row.pmk_date_due, D(2026, 10, 30), "Пустая сдача — от срока счёта.")

    def test_found_row_gets_drawings_hint_once(self):
        deal, _spec, invoice = self._sent(days=10, lead_from="drawings")
        row = self.env["project.task"].create({
            "name": "Заведена до «Выиграно» (шаг З-15)", "project_id": self.project.id,
            "stage_id": self.queue.id, "pmk_deal_id": deal.id})
        with freeze_time(WON_MOMENT):
            deal.action_set_won()
        self.assertEqual(self._rows(deal), row)
        self.assertEqual(row.pmk_sale_order_id, invoice)
        self.assertFalse(row.pmk_date_due)
        self.assertIn("согласуют чертежи", self._row_notes(row), "Подсказка и найденной строке.")
        invoice._pmk_ensure_planner_row()
        self.assertEqual(self._row_notes(row).count("согласуют чертежи"), 1, "Подсказка — один раз.")

    def test_new_row_form_hint(self):
        deal, _spec, invoice = self._sent(days=0)
        Task = self.env["project.task"]
        ctx = Task._pmk_row_defaults(deal=deal, order=invoice)
        self.assertNotIn("default_pmk_date_due", ctx)
        row = Task.with_context(**ctx).create({"name": ctx["default_name"]})
        self.assertEqual(row.pmk_sale_order_id, invoice)
        self.assertFalse(row.pmk_date_due)
        self.assertIn("не указан срок изготовления", self._row_notes(row), "«Новое» — тоже с подсказкой.")

    # ─── Виды ───────────────────────────────────────────────────────────
    def test_views(self):
        self.assertTrue(self.env.ref("pmk_orders.view_crm_lead_form_won_dialog").active)
        self.assertTrue(self.env.ref("pmk_orders.view_pmk_orders_won_wizard_form").active)
        header = self._deal_arch().find("header")
        ours = header.find("button[@name='action_pmk_won']")
        self.assertIsNotNone(ours)
        self.assertEqual(ours.get("string"), "Выиграно")
        self.assertEqual(ours.get("invisible"), WON_INVISIBLE, "Видна там же, где штатная.")
        self.assertEqual(ours.get("data-hotkey"), "w")
        classes = ours.get("class") or ""
        self.assertNotIn("oe_highlight", classes, "Контурная: залитая на сделке — «Расчёт и КП».")
        self.assertNotIn("btn-primary", classes)
        core = header.find("button[@name='action_set_won_rainbowman']")
        self.assertIsNotNone(core, "Штатная спрятана, а не удалена.")
        self.assertTrue(hidden(core))
        names = [b.get("name") for b in header.iter("button")]
        self.assertLess(names.index("action_pmk_won"), names.index("action_set_won_rainbowman"))
        if "action_open_specs" in names:
            self.assertLess(names.index("action_open_specs"), names.index("action_pmk_won"))

        views = self.env["pmk.orders.won.wizard"].with_user(self.manager).get_views([(False, "form")])
        form = etree.fromstring(views["views"]["form"]["arch"])
        filled = [b.get("name") for b in form.iter("button")
                  if {"btn-primary", "oe_highlight"} & set((b.get("class") or "").split())]
        self.assertEqual(filled, ["action_done"], "Залитая одна — «Готово».")
        self.assertIsNotNone(form.find(".//button[@name='action_skip']"))
        self.assertEqual(form.find(".//button[@name='action_done']").get("string"), "Готово")
        self.assertEqual(form.find(".//button[@name='action_skip']").get("string"), "Пропустить")

        task_views = self.env["project.task"].with_user(self.manager).get_views(
            [(self.env.ref("pmk_orders.view_task_order_form").id, "form")])
        task_form = etree.fromstring(task_views["views"]["form"]["arch"])
        for name in ("pmk_guarantee", "pmk_lead_text"):
            with self.subTest(field=name):
                self.assertIsNotNone(task_form.find(".//field[@name='%s']" % name))

        # Одно понятие — одно слово: окно, строка и счёт подписаны одинаково.
        Wizard, Task, Order = (self.env[m] for m in ("pmk.orders.won.wizard", "project.task", "sale.order"))
        self.assertEqual(Wizard._fields["amount"].string, Task._fields["pmk_paid_amount"].string)
        self.assertEqual(Wizard._fields["date"].string, Task._fields["pmk_paid_date"].string)
        self.assertEqual(Task._fields["pmk_lead_text"].string, Order._fields["pmk_lead_text"].string)
        self.assertEqual(Task._fields["pmk_lead_text"].string, "Срок изготовления")
        for name in ("amount", "date"):
            with self.subTest(wizard_field=name):
                self.assertIsNone(form.find(".//field[@name='%s']" % name).get("string"),
                                  "Подпись — из поля, без своей в виде.")
        self.assertIsNone(task_form.find(".//field[@name='pmk_date_due_manual']"),
                          "Флаг ручной правки — служебный, не на экране.")

    # ─── Импорт и «Новое» ───────────────────────────────────────────────
    def test_import_row_untouched(self):
        result = self.env["project.task"].load(
            ["name", "project_id/.id", "stage_id/.id", "pmk_date_due"],
            [["Ограждение (импорт, шаг З-15)", str(self.project.id), str(self.queue.id),
              "2026-10-21"]])
        self.assertFalse([m for m in result["messages"] if m.get("type") == "error"], result["messages"])
        row = self.env["project.task"].browse(result["ids"])
        self.assertTrue(row.pmk_date_due_manual, "Сдача из Excel — «правили руками».")
        row.write({"pmk_paid_date": D(2026, 10, 14)})
        self.assertEqual(row.pmk_date_due, D(2026, 10, 21), "Без счёта — не трогаем.")
        self.assertFalse(row.pmk_date_start)

    def test_new_row_form_defaults(self):
        deal, _spec, invoice = self._sent(days=15)
        Task = self.env["project.task"]
        with freeze_time(WON_MOMENT):
            ctx = Task._pmk_row_defaults(deal=deal, order=invoice)
        self.assertEqual(ctx["default_pmk_date_due"], "2026-10-30", "Подсказка формы «Новое».")
        self.assertEqual(ctx["default_name"], "Ограждение лестницы")
        self.assertNotIn("default_pmk_date_due_manual", ctx)
        same = Task.with_context(**ctx).create({"name": ctx["default_name"],
                                                "pmk_date_due": ctx["default_pmk_date_due"]})
        self.assertFalse(same.pmk_date_due_manual, "Подсказанную сдачу не считаем ручной.")
        other = Task.with_context(**ctx).create({"name": "Другая сдача (шаг З-15)",
                                                 "pmk_date_due": "2026-11-13"})
        self.assertTrue(other.pmk_date_due_manual)
        with freeze_time(WON_MOMENT):
            wiped = Task.with_context(**ctx).create({"name": "Стёрли сдачу (шаг З-15)",
                                                     "pmk_date_due": False})
        self.assertTrue(wiped.pmk_date_due_manual, "Стёрли подсказанную — ручная правка.")
        self.assertFalse(wiped.pmk_date_due, "Пусто и остаётся пустым.")
