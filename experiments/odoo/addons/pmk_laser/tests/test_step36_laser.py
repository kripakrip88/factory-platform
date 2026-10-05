# -*- coding: utf-8 -*-
"""Лазер: компактный верх, одна кнопка на лист, «Очередь листов», лом в кг и
₽ — разбор UX, шаг 36 (02.10.2026), с доводкой.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
Деньги металла с ценой — только с мостом номенклатуры на тестовой базе
(-i pmk_laser,pmk_bridge,pmk_flow --test-tags /pmk_laser): связь с мостом
мягкая (models/job.py, _pmk_price_ready), без моста эти проверки
пропускаются, а проверка «цены нет — слово, а не ноль» идёт в обоих случаях.

Вид (высоту верха на 1440×900, карточки в обеих темах) смотрит основной
агент глазами. Здесь — то, что ломается молча: вторая кнопка у листа,
отрезанный лист в очереди, ноль вместо «нет цены», длинные подписи
состояний, вернувшаяся вкладка «Баланс металла» и абзацы теории.

Доводка: сумма номеров листов в строке группы очереди и группы станков по
этой сумме, второй замер на отрезанном листе с устаревшей страницы, «много
лома» после смены порога, поиск станка по «6 кВт», цена расчёта против
заново выбранной строки прайса, отрицательные деньги лома, листы брошенного
задания и устаревшего файла в очереди, строки-действия, которые велят
сделать сделанное, разные слова одного понятия.
"""
import ast
from datetime import date, timedelta
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from ..models import labels, money

NBSP = " "
HIDDEN = ("1", "True", "true")


class LaserStep36Case(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context, tracking_disable=True,
            mail_create_nolog=True, mail_create_nosubscribe=True))
        # Мощность необычная: на копии боевой базы станки 3 и 6 кВт, и
        # короткое имя «6 кВт» не должно спорить с пробным станком.
        cls.machine = cls.env["pmk.laser.machine"].create({
            "name": "Станок-проба 36", "power_kw": 4.7})
        cls.sheet_ref = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий-проба36", "thickness_mm": 3.0,
            "gost": "ГОСТ 19903-2015", "mass_per_sqm": 23.55})

    def _job(self, utilization=73.0, sheets=1, **values):
        vals = {"machine_id": self.machine.id, "sheet_id": self.sheet_ref.id,
                "date": date(2026, 9, 8)}
        vals.update(values)
        job = self.env["pmk.laser.job"].create(vals)
        for number in range(1, sheets + 1):
            self.env["pmk.laser.job.sheet"].create({
                "job_id": job.id, "number": number,
                "width_mm": 1500, "length_mm": 3000, "utilization_pct": utilization,
            })
        return job

    def _arch(self, model, xmlid, view_type):
        views = self.env[model].get_views([(self.env.ref(xmlid).id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _form(self):
        return self._arch("pmk.laser.job", "pmk_laser.view_laser_job_form", "form")

    def _queue_action(self):
        return self.env["ir.actions.act_window"]._for_xml_id("pmk_laser.action_laser_sheet_queue")

    def _queue(self, jobs):
        """Листы этих заданий, которые видит «Очередь листов»."""
        domain = safe_eval(self._queue_action()["domain"]) + [("job_id", "in", jobs.ids)]
        return self.env["pmk.laser.job.sheet"].search(domain)


@tagged("post_install", "-at_install")
class TestSheetCutState(LaserStep36Case):
    """(3) Лист: «Ждёт / Режется / Готов» и одна нужная кнопка."""

    def test_states_follow_measures(self):
        job = self._job()
        sheet = job.sheet_ids
        self.assertEqual(sheet.cut_state, "waiting")
        sheet.action_start_cut()
        self.assertEqual(sheet.cut_state, "running")
        sheet.action_finish_cut()
        self.assertEqual(sheet.cut_state, "done")

    def test_excluded_measure_keeps_sheet_done(self):
        """Решение по умолчанию: исключённый мастером замер — лист «Готов»,
        иначе отрезанный лист вернулся бы в очередь."""
        job = self._job()
        sheet = job.sheet_ids
        sheet.action_start_cut()
        sheet.action_finish_cut()
        sheet.measure_ids.write({"excluded": True, "exclude_reason": "обед внутри замера"})
        self.assertEqual(sheet.cut_state, "done")
        self.assertEqual(sheet.actual_minutes, 0.0, "В норматив и факт не идёт.")

    def test_measure_without_start_is_waiting(self):
        job = self._job()
        sheet = job.sheet_ids
        self.env["pmk.laser.measure"].create({"job_id": job.id, "sheet_line_id": sheet.id})
        self.assertEqual(sheet.cut_state, "waiting", "Замер заведён, но «Начал» не нажат.")

    def test_start_on_cut_sheet_refused(self):
        """Доводка: у станка двое, страница очереди устарела — «Начал» у уже
        отрезанного листа. Отказ словами, второго замера нет (иначе лист снова
        «Режется», а факт и норматив сложили бы оба замера). Лист правда
        режут заново — прежний замер удаляют, и лист снова «Ждёт»."""
        job = self._job()
        sheet = job.sheet_ids
        sheet.action_start_cut()
        sheet.action_finish_cut()
        with self.assertRaisesRegex(UserError, "уже отрезан"):
            sheet.action_start_cut()
        self.assertEqual(len(sheet.measure_ids), 1, "Второго замера нет.")
        self.assertEqual(sheet.cut_state, "done")
        sheet.measure_ids.unlink()
        self.assertEqual(sheet.cut_state, "waiting")
        sheet.action_start_cut()
        self.assertEqual(sheet.cut_state, "running")

    def _check_buttons(self, buttons):
        by_name = {b.get("name"): b for b in buttons}
        self.assertEqual(set(by_name), {"action_start_cut", "action_finish_cut"})
        for button in buttons:
            with self.subTest(button=button.get("name")):
                classes = set((button.get("class") or "").split())
                self.assertFalse({"btn-primary", "oe_highlight"} & classes,
                                 "Строк много — залитых кнопок в строке нет.")
        # ждёт → «Начал», режется → «Закончил», готов → ничего.
        cases = {"waiting": {"action_start_cut"}, "running": {"action_finish_cut"}, "done": set()}
        for state, shown in cases.items():
            with self.subTest(state=state):
                visible = {name for name, node in by_name.items()
                           if not safe_eval(node.get("invisible") or "False", {"cut_state": state})}
                self.assertEqual(visible, shown)

    def test_job_form_one_button(self):
        arch = self._form()
        sheet_list = arch.xpath("//field[@name='sheet_ids']/list")[0]
        self._check_buttons(sheet_list.findall("button"))
        state = sheet_list.find("field[@name='cut_state']")
        self.assertEqual(state.get("widget"), "badge", "Цвет повторён словом.")

    def test_queue_one_button(self):
        arch = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_list", "list")
        self._check_buttons(arch.findall("button"))


@tagged("post_install", "-at_install")
class TestSheetQueue(LaserStep36Case):
    """(4) «Очередь листов»: неотрезанные листы всех заданий по станкам."""

    def test_only_uncut_sheets(self):
        job = self._job(sheets=3)
        first, second, third = job.sheet_ids.sorted("number")
        first.action_start_cut()
        first.action_finish_cut()
        second.action_start_cut()
        action = self._queue_action()
        self.assertEqual(action["res_model"], "pmk.laser.job.sheet")
        self.assertEqual(self._queue(job), second | third, "Готовый лист в очереди не нужен.")

    def test_grouped_by_machine_and_expanded(self):
        action = self._queue_action()
        context = safe_eval(action["context"])
        self.assertTrue(context.get("search_default_group_machine"))
        search = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_search", "search")
        group = search.xpath("//filter[@name='group_machine']")[0]
        self.assertEqual(ast.literal_eval(group.get("context")), {"group_by": "machine_id"})
        arch = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_list", "list")
        self.assertIn(arch.get("expand"), HIDDEN, "Группы станков раскрыты сразу.")
        self.assertEqual(arch.get("create"), "0")
        self.assertEqual(arch.get("delete"), "0", "Удаление листа унесло бы его замеры.")
        self.assertEqual(self.env["pmk.laser.job.sheet"]._fields["machine_id"].store, True,
                         "Группировать список умеет только по хранимому полю.")
        job = self._job(sheets=2)
        groups = self.env["pmk.laser.job.sheet"]._read_group(
            safe_eval(action["domain"]) + [("job_id", "=", job.id)], ["machine_id"], ["__count"])
        self.assertEqual(groups, [(self.machine, 2)])

    def test_group_rows_and_order(self):
        """Доводка: в строке группы станка не складываются «Лист №» и
        «Использование, %», а группы стоят по станку — не по сумме номеров
        листов (web_read_group строит порядок групп из default_order, и
        поле с агрегатором шло туда как «number:sum»)."""
        Sheet = self.env["pmk.laser.job.sheet"]
        for name in ("number", "nest_index", "width_mm", "length_mm", "utilization_pct"):
            with self.subTest(field=name):
                self.assertIsNone(Sheet._fields[name].aggregator)
        for name in ("mass_kg", "actual_minutes"):
            with self.subTest(sum_kept=name):
                self.assertEqual(Sheet._fields[name].aggregator, "sum")
        Machine = self.env["pmk.laser.machine"]
        first = Machine.create({"name": "Очередь-проба А", "sequence": 1})
        second = Machine.create({"name": "Очередь-проба Б", "sequence": 2})
        many = self._job(sheets=8, machine_id=first.id)   # номера 1…8, сумма 36
        few = self._job(sheets=3, machine_id=second.id)   # сумма 6 — по сумме был бы выше
        arch = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_list", "list")
        names = [node.get("name") for node in arch.xpath("/list/field")]
        described = Sheet.fields_get(names, ["aggregator"])
        aggregates = ["%s:%s" % (name, info["aggregator"])
                      for name, info in described.items() if info.get("aggregator")]
        self.assertFalse([spec for spec in aggregates
                          if spec.split(":")[0] in ("number", "utilization_pct")])
        domain = safe_eval(self._queue_action()["domain"]) + [("job_id", "in", (many | few).ids)]
        result = Sheet.web_read_group(domain, ["machine_id"], aggregates,
                                      order=arch.get("default_order"))
        self.assertEqual([group["machine_id"][0] for group in result["groups"]],
                         [first.id, second.id], "Группы — по станку.")

    def test_close_and_open_job(self):
        """Доводка: задание снимают с очереди (брошенное, пробное, отрезанное
        без кнопок, старое после замены файла) — ждущие листы уходят, лист,
        который режется, остаётся до «Закончил». Замеры не трогаются,
        обратимо."""
        job = self._job(sheets=3)
        first, second, third = job.sheet_ids.sorted("number")
        first.action_start_cut()
        # «Мерили часть» считает листы с фактом больше нуля минут: «Начал» и
        # «Закончил» в одну и ту же секунду дают 0 — отодвигаем начало
        # (прогон 05.10 падал тут от скорости, а не от кода).
        first.measure_ids.write({"started_at": fields.Datetime.now() - timedelta(minutes=5)})
        first.action_finish_cut()
        second.action_start_cut()
        second.measure_ids.write({"started_at": fields.Datetime.now() - timedelta(minutes=5)})
        self.assertFalse(job.queue_closed_note)
        job.action_queue_close()
        self.assertTrue(job.queue_closed)
        self.assertEqual(self._queue(job), second, "Режется — «Закончил» должно быть где нажать.")
        self.assertEqual(job.queue_closed_note, "Снято с очереди — ждут: 1" + NBSP + "лист")
        second.action_finish_cut()
        self.assertFalse(self._queue(job))
        self.assertEqual(job.measure_state, "partial", "Замеры не тронуты.")
        job.action_queue_open()
        self.assertEqual(self._queue(job), third)
        self.assertFalse(job.queue_closed_note)

    def test_close_from_gear_menu(self):
        """Снять и вернуть — пунктами ⚙ «Действие» в задании и в списке, а не
        кнопками в шапке."""
        for xmlid, method in (("pmk_laser.action_laser_job_queue_close", "action_queue_close"),
                              ("pmk_laser.action_laser_job_queue_open", "action_queue_open")):
            action = self.env.ref(xmlid)
            with self.subTest(action=xmlid):
                self.assertEqual(action.binding_model_id.model, "pmk.laser.job")
                self.assertEqual(set(action.binding_view_types.split(",")), {"list", "form"})
                self.assertIn(method, action.code)
        job = self._job()
        self.env.ref("pmk_laser.action_laser_job_queue_close").with_context(
            active_model="pmk.laser.job", active_id=job.id, active_ids=job.ids).run()
        self.assertTrue(job.queue_closed)
        self.assertFalse(self._queue(job))
        form = self._form()
        self.assertFalse(form.xpath("//header/button[@name='action_queue_close']"),
                         "В шапке кнопки нет — её шаг 36 и сжимал.")
        chip = form.xpath("//div[@class='pmk-job-signals']/span[field[@name='queue_closed_note']]")
        self.assertEqual(len(chip), 1, "Снятое задание видно сигналом.")
        self.assertEqual(chip[0].get("invisible"), "not queue_closed_note")
        search = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_search", "search")
        self.assertEqual(search.xpath("//filter[@name='queue_closed']/@string"), ["Сняты с очереди"])

    def test_file_replaced_note(self):
        """Доводка: файл в задании заменили, листы от прежнего — в очереди
        «файл заменён» жёлтой плашкой. Сигнал, «Начал» не запрещён."""
        job = self._job()
        sheet = job.sheet_ids
        self.assertFalse(sheet.queue_note)
        job.write({"file_replaced": True})
        self.assertEqual(sheet.queue_note, "файл заменён")
        arch = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_list", "list")
        node = arch.xpath("/list/field[@name='queue_note']")[0]
        self.assertEqual(node.get("widget"), "badge", "Цвет повторён словом.")
        self.assertEqual(node.get("decoration-warning"), "queue_note")
        self.assertEqual(self._queue(job), sheet)
        sheet.action_start_cut()
        self.assertEqual(sheet.cut_state, "running")

    def test_row_opens_job(self):
        arch = self._arch("pmk.laser.job.sheet", "pmk_laser.view_laser_sheet_queue_list", "list")
        self.assertEqual((arch.get("action"), arch.get("type")), ("action_open_job", "object"))
        job = self._job()
        result = job.sheet_ids.action_open_job()
        self.assertEqual((result["res_model"], result["res_id"]), ("pmk.laser.job", job.id))
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names[0], "job_id")
        self.assertEqual(arch.xpath("/list/field[@name='job_id']")[0].get("width"), "105px",
                         "Номер ЛР- не обрезается.")

    def test_default_list_without_buttons(self):
        """Окно выбора листа («Поиск ещё…» у поля «Лист» в замере и
        обрезке) берёт список по умолчанию — в нём кнопок «Начал» нет."""
        views = self.env["pmk.laser.job.sheet"].get_views([(False, "list")])
        arch = etree.fromstring(views["views"]["list"]["arch"])
        self.assertFalse(arch.xpath("//button"))
        self.assertEqual(views["views"]["list"]["id"],
                         self.env.ref("pmk_laser.view_laser_job_sheet_list").id)

    def test_menu_first_in_section(self):
        """Раздел открывается очередью: щелчок по разделу и «Начал» — два
        действия."""
        section = self.env.ref("pmk_laser.menu_pmk_laser")
        queue = self.env.ref("pmk_laser.menu_pmk_laser_queue")
        self.assertEqual(section.child_id.sorted(lambda m: (m.sequence, m.id))[0], queue)
        menus = self.env["ir.ui.menu"].load_web_menus(False)
        self.assertEqual(menus[section.id]["actionID"],
                         self.env.ref("pmk_laser.action_laser_sheet_queue").id)


@tagged("post_install", "-at_install")
class TestScrapAndMoney(LaserStep36Case):
    """(5) Лом в кг и ₽: сигнал «много» в списке, деньги металла в задании.

    Сценарии ниже — лом 27 % («много») и 15 % (норма) — верны для порога
    по умолчанию (20 %) и любого между 15 и 27 %. Сам порог тест не
    закрепляет: он — решение владельца (money.SCRAP_HIGH_PCT)."""

    def test_pure_functions(self):
        threshold = money.SCRAP_HIGH_PCT
        self.assertFalse(money.is_scrap_high(threshold), "Ровно на пороге — ещё не «много».")
        self.assertTrue(money.is_scrap_high(threshold + 0.1))
        self.assertEqual(money.scrap_pct(5.0, 0.0), 0.0)
        self.assertAlmostEqual(money.per_ton(15454.02, 211.95), 72913.52, places=2)
        self.assertEqual(money.per_ton(15454.02, 0.0), 0.0, "Масса неизвестна — без деления.")
        self.assertAlmostEqual(money.rub_from_ton(106.0, 72913.52), 7728.83, places=2)
        self.assertEqual(labels.scrap_label(28.6, 106.0), "27" + NBSP + "% · много")
        self.assertEqual(labels.scrap_label(17.0, 100.0), "17" + NBSP + "%")
        # Сравнивается видимое: доля с одним знаком. Чуть выше порога, но на
        # экране ровно порог — не «много».
        self.assertEqual(labels.scrap_label(threshold + 0.04, 100.0), labels.pct(threshold))
        self.assertEqual(labels.scrap_label(-3.0, 100.0, broken=True), "не сходится")
        self.assertEqual(labels.scrap_label(0.0, 0.0), "", "Металла нет — пусто, не «0 %».")
        self.assertEqual(labels.scrap_signal(27.0, 106.0), ("27" + NBSP + "% · много", True))
        self.assertEqual(labels.scrap_signal(27.0, 106.0, broken=True), ("не сходится", False))
        self.assertEqual(labels.scrap_signal(27.0, 0.0), ("", False))
        self.assertEqual(
            labels.price_note(72913.52, "АО «Металлсервис», филиал Хабаровск", date(2026, 6, 16)),
            "72" + NBSP + "914" + NBSP + "₽/т · АО «Металлсервис», филиал Хабаровск · прайс от 16.06.2026")
        self.assertEqual(
            labels.price_note(80113.3, "Металлсервис", date(2026, 9, 21), source="из расчёта"),
            "80" + NBSP + "113" + NBSP + "₽/т · Металлсервис · прайс от 21.09.2026 · из расчёта")
        self.assertEqual(labels.queue_closed_note(0), "")
        self.assertEqual(labels.queue_closed_note(8), "Снято с очереди — ждут: 8" + NBSP + "листов")
        # Подсказки «?» берут число из порога, а не пишут «20 %» сами.
        model = self.env["pmk.laser.job"]._fields
        for name in ("scrap_high", "scrap_label"):
            with self.subTest(help=name):
                self.assertIn(labels.pct(threshold), model[name].help)

    def test_scrap_high(self):
        job = self._job(utilization=73.0)
        self.assertAlmostEqual(job.mass_kg, 106.0)
        self.assertAlmostEqual(job.scrap_mass_kg, 28.6)
        self.assertAlmostEqual(job.scrap_pct, 27.0)
        self.assertTrue(job.scrap_high)
        self.assertEqual(job.scrap_label, "27" + NBSP + "% · много")
        self.assertEqual(self.env["pmk.laser.job"].search(
            [("id", "=", job.id), ("scrap_high", "=", True)]), job, "Фильтр «Много лома».")

    def test_threshold_change_applies_at_once(self):
        """Доводка: «много» не хранится. Сменили порог — подпись, плашка и
        фильтр согласны сразу, без пересчёта: задание 27 % при пороге 30 % не
        пишет «· много» без жёлтой плашки, и фильтр его не находит."""
        Job = self.env["pmk.laser.job"]
        self.assertFalse(Job._fields["scrap_high"].store)
        self.assertFalse(Job._fields["scrap_label"].store)
        self.assertTrue(Job._fields["scrap_pct"].store, "Сортирует и ищет хранимая доля.")
        job = self._job(utilization=73.0)  # лом 27 %

        def seen():
            job.invalidate_recordset(["scrap_high", "scrap_label"])
            high = bool(Job.search([("id", "=", job.id), ("scrap_high", "=", True)]))
            normal = bool(Job.search([("id", "=", job.id), ("scrap_high", "=", False)]))
            return job.scrap_high, job.scrap_label, high, normal

        self.assertEqual(seen(), (True, "27" + NBSP + "% · много", True, False))
        with patch.object(money, "SCRAP_HIGH_PCT", 30.0):
            self.assertEqual(seen(), (False, "27" + NBSP + "%", False, True))
        with patch.object(money, "SCRAP_HIGH_PCT", 27.0):
            self.assertEqual(seen(), (False, "27" + NBSP + "%", False, True),
                             "Ровно на пороге — ещё не «много».")
        with patch.object(money, "SCRAP_HIGH_PCT", 15.0):
            self.assertEqual(seen(), (True, "27" + NBSP + "% · много", True, False))
        self.assertEqual(seen(), (True, "27" + NBSP + "% · много", True, False))

    def test_scrap_normal_and_offcut(self):
        job = self._job(utilization=85.0)
        self.assertFalse(job.scrap_high)
        self.assertEqual(job.scrap_label, "15" + NBSP + "%")
        # Подтверждённый обрезок больше лома — баланс не сходится: слово
        # вместо доли, и не «много».
        self.env["pmk.laser.offcut"].create({
            "job_id": job.id, "sheet_line_id": job.sheet_ids.id,
            "width_mm": 1500, "length_mm": 1000, "state": "confirmed"})
        self.assertTrue(job.balance_broken)
        self.assertFalse(job.scrap_high)
        self.assertEqual(job.scrap_label, "не сходится")
        self.assertFalse(self.env["pmk.laser.job"].search(
            [("id", "=", job.id), ("scrap_high", "=", True)]))

    def test_offcut_confirmation_turns_signal_off(self):
        """Площадка ГРПШ: лом 27 % — обрезок 1500×800 не подтверждён.
        Подтвердили — лом 0,3 %, сигнал погас сам."""
        job = self._job(utilization=73.0)
        offcut = self.env["pmk.laser.offcut"].create({
            "job_id": job.id, "sheet_line_id": job.sheet_ids.id,
            "width_mm": 1500, "length_mm": 800})
        self.assertTrue(job.scrap_high, "Предложенный обрезок — ещё не металл на стеллаже.")
        offcut.action_confirm()
        self.assertFalse(job.scrap_high)
        self.assertLess(job.scrap_pct, 1.0)

    def test_list_signal(self):
        arch = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_list", "list")
        badge = arch.xpath("/list/field[@name='scrap_label']")[0]
        self.assertEqual(badge.get("widget"), "badge")
        self.assertEqual(badge.get("decoration-warning"), "scrap_high")
        self.assertEqual(badge.get("decoration-danger"), "balance_broken")
        self.assertIn("pmk-job-scrap", badge.get("class"))
        for name in ("scrap_high", "balance_broken"):
            with self.subTest(field=name):
                self.assertIn(arch.xpath("/list/field[@name='%s']" % name)[0].get("column_invisible"),
                              HIDDEN)
        self.assertEqual(arch.xpath("/list/field[@name='scrap_pct']")[0].get("optional"), "hide")
        model = self.env["pmk.laser.job"]._fields
        self.assertIsNone(model["scrap_pct"].aggregator,
                          "Сумма процентов в строке группы ничего не значит.")
        # Доводка: в меню колонок (⚙) одно число не под двумя разными
        # названиями — «Лом, %» словом и «Лом, % (число)».
        self.assertEqual(model["scrap_label"].string, "Лом, %")
        self.assertEqual(model["scrap_pct"].string, "Лом, % (число)")
        search = self._arch("pmk.laser.job", "pmk_laser.view_laser_job_search", "search")
        self.assertEqual(search.xpath("//filter[@name='scrap_high']/@string"), ["Много лома"])

    def _card(self, arch, name):
        return arch.xpath("//div[contains(@class, 'pmk-job-metal')]//label[@for='%s']/.." % name)[0]

    def test_no_price_is_signal_not_zero(self):
        """Цены нет — слово и «нет цены» на карточке, а не 0 ₽."""
        job = self._job()
        self.assertTrue(job.metal_price_missing)
        self.assertEqual((job.metal_rub, job.scrap_rub), (0.0, 0.0))
        if job._pmk_price_ready():
            self.assertEqual(job.metal_price_note, "у листа нет карточки товара")
        else:
            self.assertEqual(job.metal_price_note, "цены поставщиков не подключены")
        arch = self._form()
        expected = {
            "metal_rub": ("metal_price_missing", "not metal_price_missing"),
            "scrap_rub": ("metal_price_missing or balance_broken",
                          "not metal_price_missing or balance_broken"),
        }
        for name, (number_hidden, word_hidden) in expected.items():
            with self.subTest(field=name):
                card = self._card(arch, name)
                self.assertEqual(card.xpath(".//field[@name='%s']" % name)[0].get("invisible"),
                                 number_hidden)
                word = card.xpath(".//span[contains(@class, 'pmk-job-noprice')"
                                  " and normalize-space()='нет цены']")[0]
                self.assertEqual(word.get("invisible"), word_hidden)

    def test_scrap_rub_when_balance_broken(self):
        """Доводка: баланс не сходится — вместо «Лом, ₽ −897» слово «не
        сходится», отрицательных денег нет."""
        job = self._job(utilization=85.0)
        self.env["pmk.laser.offcut"].create({
            "job_id": job.id, "sheet_line_id": job.sheet_ids.id,
            "width_mm": 1500, "length_mm": 1000, "state": "confirmed"})
        self.assertTrue(job.balance_broken)
        self.assertLess(job.scrap_mass_kg, 0.0)
        self.assertEqual(job.scrap_rub, 0.0)
        card = self._card(self._form(), "scrap_rub")
        word = card.xpath(".//span[normalize-space()='не сходится']")
        self.assertEqual(len(word), 1)
        self.assertEqual(word[0].get("invisible"), "not balance_broken")

    def test_bridge_soft_link(self):
        """Мост — мягкая связь: удаление stock_account или модулей RuOdoo,
        на которых он держится, не должно каскадом сносить все задания."""
        self.assertNotIn("pmk_bridge", get_manifest("pmk_laser")["depends"])
        for name in ("metal_rub", "scrap_rub", "metal_price_ton", "metal_price_note",
                     "metal_price_missing"):
            with self.subTest(field=name):
                self.assertFalse(self.env["pmk.laser.job"]._fields[name].store,
                                 "Цена меняется заливкой прайса — хранимое устарело бы молча.")

    # ─── С мостом номенклатуры ─────────────────────────────────────────

    def _bridge(self):
        if not self.env["pmk.laser.job"]._pmk_price_ready():
            self.skipTest("Мост номенклатуры (pmk_bridge) на тестовой базе не установлен")
        tmpl = self.env["product.template"].create({"name": "Лист проба 36", "weight": 211.95})
        self.sheet_ref.product_tmpl_id = tmpl
        supplier = self.env["res.partner"].create({"name": "Поставщик-проба 36", "is_company": True})
        Info = self.env["product.supplierinfo"]
        self.price_june = Info.create({
            "partner_id": supplier.id, "product_tmpl_id": tmpl.id, "price": 15454.02,
            "date_start": date(2026, 6, 16), "date_end": date(2026, 9, 20)})
        self.price_sept = Info.create({
            "partner_id": supplier.id, "product_tmpl_id": tmpl.id, "price": 16980.02,
            "date_start": date(2026, 9, 21)})
        return tmpl, supplier

    def test_money_with_price(self):
        _tmpl, supplier = self._bridge()
        job = self._job(utilization=73.0)
        per_ton = 15454.02 / 211.95 * 1000.0
        self.assertFalse(job.metal_price_missing)
        # Два знака у поля (доводка): кеш Float округляет до знаков поля, с
        # digits=(12, 0) здесь было бы 72 914.
        self.assertAlmostEqual(job.metal_price_ton, per_ton, places=2)
        self.assertAlmostEqual(job.metal_rub, 106.0 * per_ton / 1000.0, places=2)
        self.assertAlmostEqual(job.scrap_rub, 28.6 * per_ton / 1000.0, places=2)
        self.assertIn(supplier.name, job.metal_price_note)
        self.assertIn("прайс от 16.06.2026", job.metal_price_note, "Цена на день резки.")
        self.assertNotIn("из расчёта", job.metal_price_note)
        # Баланс не сходится — лом в рублях не считается, металл — как был.
        metal = job.metal_rub
        self.env["pmk.laser.offcut"].create({
            "job_id": job.id, "sheet_line_id": job.sheet_ids.id,
            "width_mm": 1500, "length_mm": 1500, "state": "confirmed"})
        self.assertTrue(job.balance_broken)
        self.assertEqual(job.scrap_rub, 0.0)
        self.assertAlmostEqual(job.metal_rub, metal, places=2)

    def test_money_follows_spec(self):
        """Привязано к расчёту без этого листа — его дата цен и поставщик:
        тот же выбор строки прайса, что сделал бы расчёт."""
        _tmpl, supplier = self._bridge()
        spec = self.env["pmk.metal.spec"].create({"price_date": date(2026, 9, 25)})
        job = self._job(spec_id=spec.id)
        self.assertAlmostEqual(job.metal_price_ton, 16980.02 / 211.95 * 1000.0, places=2)
        other = self.env["res.partner"].create({"name": "Чужой поставщик 36", "is_company": True})
        spec.supplier_id = other
        job.invalidate_recordset()
        self.assertTrue(job.metal_price_missing, "У поставщика расчёта цены нет — сигнал.")
        self.assertIn(other.display_name, job.metal_price_note)
        spec.supplier_id = supplier
        job.invalidate_recordset()
        self.assertFalse(job.metal_price_missing)
        # «Цены на дату» в расчёте пусты — сегодня, как берёт сам расчёт, а
        # не дата задания (08.09 попала бы на июньский прайс).
        undated = self.env["pmk.metal.spec"].create({"price_date": False})
        self.assertFalse(undated.price_date)
        job = self._job(spec_id=undated.id)
        self.assertAlmostEqual(job.metal_price_ton, 16980.02 / 211.95 * 1000.0, places=2)
        self.assertIn("прайс от 21.09.2026", job.metal_price_note)

    def test_money_from_spec_line(self):
        """Доводка: лист есть в расчёте с ценой — цена его строки, как она в
        расчёте стоит, даже когда прайс сменился, а «Перечитать цены» не
        нажимали. Строка прайса заново не выбирается."""
        tmpl, supplier = self._bridge()
        spec = self.env["pmk.metal.spec"].create({
            "price_date": date(2026, 9, 25),
            "product_ids": [Command.create({
                "name": "Площадка-проба 36", "qty": 1,
                "line_ids": [Command.create({
                    "calc_mode": "sheet", "detail_name": "Настил",
                    "sheet_id": self.sheet_ref.id, "a_mm": 1000.0, "b_mm": 1000.0,
                    "qty": 1})],
            })],
        })
        line = spec.product_ids.line_ids
        self.assertEqual(line.price_state, "ok")
        spec_price = line.price_ton
        self.assertGreater(spec_price, 0.0)
        # Прайс сменился, в расчёте цены не перечитаны: строка держит снимок.
        self.price_sept.date_end = date(2026, 9, 21)
        self.env["product.supplierinfo"].create({
            "partner_id": supplier.id, "product_tmpl_id": tmpl.id, "price": 17500.0,
            "date_start": date(2026, 9, 22)})
        self.assertEqual(line.price_ton, spec_price, "Снимок расчёта сам не перечитывается.")
        job = self._job(spec_id=spec.id)
        self.assertFalse(job.metal_price_missing)
        self.assertEqual(job.metal_price_ton, spec_price,
                         "Металл в задании стоит столько же, сколько в расчёте.")
        self.assertAlmostEqual(job.metal_rub, 106.0 * spec_price / 1000.0, places=2)
        note = job.metal_price_note
        self.assertTrue(note.endswith("из расчёта"), note)
        self.assertIn(supplier.name, note)
        self.assertIn("прайс от 21.09.2026", note, "Дата прайса — та, что в строке расчёта.")

    def test_money_no_price_rows(self):
        if not self.env["pmk.laser.job"]._pmk_price_ready():
            self.skipTest("Мост номенклатуры (pmk_bridge) на тестовой базе не установлен")
        self.sheet_ref.product_tmpl_id = self.env["product.template"].create({
            "name": "Лист без цены 36", "weight": 211.95})
        job = self._job()
        self.assertTrue(job.metal_price_missing)
        self.assertEqual(job.metal_rub, 0.0)
        self.assertTrue(job.metal_price_note.startswith("нет в прайсах"))


@tagged("post_install", "-at_install")
class TestShortWords(LaserStep36Case):
    """(2) Короткие состояния и короткие имена станков в списке."""

    def _selection(self, model, field):
        return dict(self.env[model].fields_get([field])[field]["selection"])

    def test_short_states(self):
        self.assertEqual(self._selection("pmk.laser.job", "plan_state"), {
            "ok": "Норматив есть", "rough": "Норматив грубый",
            "no_norm": "Нет норматива", "no_drawing": "Рез не разобран"})
        self.assertEqual(self._selection("pmk.laser.job", "measure_state"), {
            "none": "Не мерили", "partial": "Мерили часть", "done": "Замерено"})
        self.assertEqual(self._selection("pmk.laser.norm", "mode"), {
            "none": "Нет норматива", "aggregate": "Норматив грубый", "full": "Норматив есть"},
            "Одно понятие — одно слово с планом задания.")
        sheet_words = {"waiting": "Ждёт", "running": "Режется", "done": "Готов"}
        self.assertEqual(self._selection("pmk.laser.job.sheet", "cut_state"), sheet_words)
        # Доводка: вкладки «Листы» и «Замеры» одной формы — о том же листе
        # одними словами (было «Не начат / Режет / Закончен»).
        self.assertEqual(self._selection("pmk.laser.measure", "state"), sheet_words)
        for field in ("plan_state", "measure_state"):
            with self.subTest(field=field):
                self.assertTrue(self.env["pmk.laser.job"]._fields[field].help,
                                "Полный смысл — в подсказке «?».")
        measures = self._form().xpath("//field[@name='measure_ids']/list/field[@name='state']")[0]
        self.assertEqual(measures.get("widget"), "badge", "Цвет — как у листа, повторён словом.")

    def test_machine_short_name(self):
        Machine = self.env["pmk.laser.machine"]
        small = Machine.create({"name": "Лазер-проба А", "power_kw": 3.7})
        twin_a = Machine.create({"name": "Лазер-проба Б", "power_kw": 9.9})
        twin_b = Machine.create({"name": "Лазер-проба В", "power_kw": 9.9})
        bare = Machine.create({"name": "Лазер-проба Г"})
        short = (small | twin_a | twin_b | bare).with_context(pmk_machine_short=True)
        self.assertEqual(short.mapped("display_name"), [
            "3,7" + NBSP + "кВт", "Лазер-проба Б", "Лазер-проба В", "Лазер-проба Г"],
            "Мощность совпала или не задана — полное имя.")
        self.assertEqual(small.display_name, "Лазер-проба А", "Без контекста — полное имя.")
        self.assertEqual(labels.power_label(6.0), "6" + NBSP + "кВт")
        self.assertEqual(labels.power_label(2.5), "2,5" + NBSP + "кВт")

    def test_machine_short_name_search(self):
        """Доводка: колонка показывает «7,3 кВт» — так станок и ищется, в
        поиске заданий и в выпадашке выбора. По имени — как раньше."""
        Machine = self.env["pmk.laser.machine"]
        Job = self.env["pmk.laser.job"]
        machine = Machine.create({"name": "Лазер-проба поиска", "power_kw": 7.3})
        job = self._job(machine_id=machine.id)
        for typed in ("7,3 кВт", "7,3" + NBSP + "кВт", "7,3квт", "7.3 КВТ", "7,3 к"):
            with self.subTest(typed=typed):
                self.assertEqual(Job.search([("id", "=", job.id), ("machine_id", "ilike", typed)]), job)
                self.assertIn(machine.id, [row[0] for row in Machine.name_search(typed)])
        self.assertIn(machine, Machine.search([("display_name", "ilike", "проба поиска")]))
        self.assertNotIn(machine, Machine.search([("display_name", "not ilike", "7,3 кВт")]))
        self.assertFalse(Job.search([("id", "=", job.id), ("machine_id", "ilike", "9,1 кВт")]))
        # Две одинаковые мощности — в колонке полные имена, и по «кВт» их не
        # находим: такого короткого имени на экране нет.
        twin = Machine.create({"name": "Лазер-проба близнец", "power_kw": 7.3})
        self.assertFalse(Job.search([("id", "=", job.id), ("machine_id", "ilike", "7,3 кВт")]))
        self.assertTrue(twin)
        self.assertEqual(labels.search_key("7.3" + NBSP + "кВт"), "7,3квт")

    def test_short_name_only_in_list_columns(self):
        for xmlid in ("pmk_laser.view_laser_job_list", "pmk_laser.view_laser_load_list"):
            arch = self._arch("pmk.laser.job", xmlid, "list")
            with self.subTest(view=xmlid):
                node = arch.xpath("/list/field[@name='machine_id']")[0]
                self.assertEqual(ast.literal_eval(node.get("context")), {"pmk_machine_short": True})
        form = self._form()
        node = form.xpath("//group/field[@name='machine_id']")[0]
        self.assertFalse(ast.literal_eval(node.get("context") or "{}").get("pmk_machine_short"),
                         "В форме — полное имя.")


@tagged("post_install", "-at_install")
class TestJobFormTop(LaserStep36Case):
    """(1) Компактный верх и (6) строка действия вместо абзаца."""

    def test_rows_order(self):
        sheet = self._form().find("sheet")
        top = sheet.findall("group")[0]
        self.assertEqual([g.get("string") for g in top.findall("group")],
                         ["Задание", "Станок и лист"])
        # Только элементы: комментарии разметки — не ряды формы.
        children = [c for c in sheet if isinstance(c.tag, str)]
        names = [c.get("class") or c.tag for c in children]
        metal = [i for i, c in enumerate(children) if "pmk-job-metal" in (c.get("class") or "")]
        self.assertEqual(len(metal), 1, names)
        self.assertLess(children.index(top), metal[0], "«Металл» — вторым рядом.")
        self.assertLess(metal[0], children.index(sheet.find("notebook")))
        self.assertEqual(children[metal[0]].get("invisible"), "not sheet_ids",
                         "До разбора файла металла нет — нет и строки.")

    def test_five_rows_each(self):
        """По пять строк в группах первого ряда — кнопки листа на первом
        экране. «Заказ» виден, только когда заполнен (шаг 29)."""
        top = self._form().find("sheet").findall("group")[0]
        for group in top.findall("group"):
            rows = [node for node in group
                    if node.tag in ("field", "label")
                    and node.get("invisible") not in HIDDEN
                    and node.get("name") != "sale_order_id"]
            with self.subTest(group=group.get("string")):
                self.assertEqual(len(rows), 5, [n.get("name") or n.get("for") for n in rows])

    def test_file_one_grey_line(self):
        arch = self._form()
        task = arch.xpath("//group[@name='pmk_job_task']")[0]
        info = task.xpath(".//field[@name='file_info']")
        self.assertEqual(len(info), 1)
        self.assertIn("pmk-job-note", info[0].get("class"))
        self.assertEqual(info[0].getparent(), task.xpath(".//field[@name='file']")[0].getparent(),
                         "Строка — под полем «Файл».")
        for name in ("file_app", "file_operator", "file_saved_text", "contour_count", "sheet_type",
                     "gross_area_m2", "useful_area_m2"):
            with self.subTest(field=name):
                self.assertFalse(arch.xpath("//sheet//field[@name='%s']" % name),
                                 "Поле в модели на месте, с формы убрано.")
        job = self._job()
        job.write({"file_app": "CypCut 6.3.907.8", "file_operator": "XE",
                   "file_saved_text": "2026-09-08T14:34:05Z", "contour_count": 65})
        self.assertEqual(job.file_info,
                         "CypCut 6.3 · сохранил XE · 08.09.2026 14:34 · 65" + NBSP + "контуров")

    def test_metal_cards(self):
        arch = self._form()
        strip = arch.xpath("//div[contains(@class, 'pmk-job-metal')]")[0]
        labels_for = [node.get("for") for node in strip.xpath(".//label")]
        self.assertEqual(labels_for, [
            "mass_kg", "useful_mass_kg", "offcut_mass_kg", "kerf_mass_kg", "scrap_mass_kg",
            "metal_rub", "scrap_rub", "premium_rub"], "Баланс по порядку, потом деньги.")
        model = self.env["pmk.laser.job"]._fields
        for name in ("mass_kg", "kerf_mass_kg", "premium_rub", "metal_rub", "scrap_rub"):
            with self.subTest(help=name):
                self.assertTrue(model[name].help, "Теория — в подсказке «?» подписи карточки.")
        self.assertIn("детали + обрезки + пропил + лом", model["mass_kg"].help)
        self.assertIn("15,7 г", model["kerf_mass_kg"].help)
        for name in ("offcut_mass_kg", "kerf_mass_kg"):
            with self.subTest(card=name):
                card = strip.xpath(".//label[@for='%s']/.." % name)[0]
                self.assertEqual(card.get("invisible"), "not %s" % name, "Только ненулевые.")

    def test_tabs(self):
        arch = self._form()
        pages = [p.get("name") for p in arch.xpath("//sheet/notebook/page")]
        self.assertNotIn("balance", pages, "«Баланс металла» ушёл строкой карточек наверх.")
        self.assertEqual(pages[:5], ["sheets", "parts", "operators", "offcuts", "measures"])
        offcuts = arch.xpath("//page[@name='offcuts']")[0]
        for name in ("kerf_mm", "min_offcut_mm"):
            with self.subTest(field=name):
                self.assertEqual(len(offcuts.xpath(".//group//field[@name='%s']" % name)), 1)
                self.assertEqual(len(arch.xpath("//field[@name='%s']" % name)), 1)
        # Доводка: «Параметры» — левой половиной пары групп, как «Знаменатель
        # задания | План и факт». Одиночная группа растягивала поля на всю
        # ширину листа.
        params = offcuts.xpath(".//group[@name='offcut_params']")[0]
        inner = params.findall("group")
        self.assertEqual(len(inner), 2, "Пара групп, правая пустая.")
        self.assertEqual(inner[0].get("string"), "Параметры")
        self.assertEqual([f.get("name") for f in inner[0].findall("field")],
                         ["kerf_mm", "min_offcut_mm"])
        self.assertEqual(len(inner[1]), 0)

    def test_one_action_line_per_tab(self):
        arch = self._form()
        self.assertFalse(arch.xpath("//page[@name='sheets']/p"),
                         "У листов строки нет: кнопка в строке и есть действие.")
        for name in ("parts", "operators", "offcuts"):
            with self.subTest(page=name):
                paragraphs = arch.xpath("//page[@name='%s']/p" % name)
                self.assertEqual(len(paragraphs), 1)
                text = " ".join("".join(paragraphs[0].itertext()).split())
                self.assertLess(len(text), 100, text)
        model = self.env["pmk.laser.job.sheet"]._fields
        self.assertIn("физический лист", model["number"].help)
        self.assertIn("исключил", model["cut_state"].help)
        self.assertIn("знаменатель", self.env["pmk.laser.job.part"]._fields["drawing"].help)
        self.assertIn("246,07", self.env["pmk.laser.job.operator"]._fields["amount_rub"].help)

    def test_action_lines_follow_state(self):
        """Доводка: строка-действие — по состоянию и с числом; сделано —
        строки нет. Иначе все чертежи разобраны, а строка велит их
        приложить."""
        arch = self._form()
        line = {name: arch.xpath("//page[@name='%s']/p" % name)[0]
                for name in ("parts", "operators", "offcuts")}
        self.assertEqual(line["parts"].get("invisible"), "not parts_without_drawing")
        self.assertTrue(line["parts"].xpath("field[@name='parts_without_drawing']"), "Число — в строке.")
        text = " ".join("".join(line["parts"].itertext()).split())
        self.assertTrue(text.startswith("Рез не разобран у"), text)
        self.assertEqual(line["operators"].get("invisible"), "operator_ids")
        self.assertEqual(line["offcuts"].get("invisible"), "not offcut_proposed_count")
        self.assertTrue(line["offcuts"].xpath("field[@name='offcut_proposed_count']"))
        job = self._job()
        self.assertEqual(job.offcut_proposed_count, 0)
        offcut = self.env["pmk.laser.offcut"].create({
            "job_id": job.id, "sheet_line_id": job.sheet_ids.id,
            "width_mm": 1500, "length_mm": 800})
        self.assertEqual(job.offcut_proposed_count, 1)
        offcut.action_confirm()
        self.assertEqual(job.offcut_proposed_count, 0, "Подтвердили — строки нет.")


@tagged("post_install", "-at_install")
class TestOffcutDefaults(LaserStep36Case):
    """(7) «Обрезки» открываются с «Ждут подтверждения» + «На стеллаже»."""

    def test_default_filters(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_laser.action_laser_offcut")
        context = safe_eval(action["context"])
        self.assertTrue(context.get("search_default_proposal"))
        self.assertTrue(context.get("search_default_confirmed"))
        search = self._arch("pmk.laser.offcut", "pmk_laser.view_laser_offcut_search", "search")
        proposal = search.xpath("//filter[@name='proposal']")[0]
        following = proposal.getnext()
        while following is not None and not isinstance(following.tag, str):
            following = following.getnext()
        self.assertEqual(following.get("name"), "confirmed",
                         "Соседние фильтры без разделителя — «или», а не «и».")

    def test_confirm_not_filled_in_list(self):
        arch = self._arch("pmk.laser.offcut", "pmk_laser.view_laser_offcut_list", "list")
        confirm = arch.xpath("/list/button[@name='action_confirm']")[0]
        self.assertNotIn("btn-primary", confirm.get("class") or "",
                         "Предложенных в списке много — залитых кнопок нет.")
