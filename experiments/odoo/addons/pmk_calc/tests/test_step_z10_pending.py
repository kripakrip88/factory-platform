# -*- coding: utf-8 -*-
"""Позиция «на разнос» — разбор UX, шаг З-10 (09.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk_z10_test -i pmk_tech --test-enable \\
         --test-tags /pmk_calc:TestStepZ10Pending,/pmk_bridge:TestStepZ10Card,/pmk_tech:TestStepZ10Request \\
         --stop-after-init --http-port 8099

Синтетические данные (позиции заводятся в тесте; справочник модуля — из
его CSV одноразовой базы).

Что ловим:
  • «завести новую» из поля позиции детали (как присылает окно — контекст
    default_pmk_pending / default_pmk_pending_name / form_view_ref):
    прокат, лист, метиз встают «на разнос», с названием как в чертеже,
    видом «Прочее» по умолчанию, стандартом «—», массой листа толщина ×
    7,85; кто завёл и где завели; сразу выбраны в детали и считаются в весе
    (вес задан) или весят 0 с пометкой «нет веса» — без ошибки;
  • сотрудник заводит только «на разнос»; обычные позиции не правит, метку
    не снимает; список «Новые позиции на разнос» и кнопки — только админ;
  • плашка расчёта «Позиции на разнос: N — их проверит администратор»;
  • умный поиск (шаг 56) прежний и находит позицию «на разнос» по словам;
  • «Привязать к существующей»: все детали всех расчётов (и доборки) —
    на выбранную позицию, заметка в ленту, временная — в архив;
  • «Принять в справочник»: без вида / стандарта / массы — отказ со списком,
    с ними — метка снята, имя обычное, вид детали — из позиции;
  • виды: строка «завести» в окне изделия и в редакторе состава, окна
    «Новая позиция на разнос» (одна залитая), меню — администратору.

Сама выпадашка (строка, метка, окно) — JS (static/src/js/pending_create.js),
её смотрит основной агент глазами в светлой и тёмной теме.
"""
from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_path

PENDING_CTX = {"default_pmk_pending": True}


def _read(path):
    with open(file_path(path), encoding="utf-8") as f:
        return f.read()


def _filled(node):
    return bool({"btn-primary", "oe_highlight"} & set((node.get("class") or "").split()))


class Z10Common(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.engineer = new_test_user(
            env, login="pmkz10_engineer", name="Инженер (шаг З-10)",
            groups="base.group_user")
        cls.admin = new_test_user(
            env, login="pmkz10_admin", name="Администратор (шаг З-10)",
            groups="base.group_user,base.group_system")
        cls.Profile = env["pmk.metal.profile"]
        cls.Sheet = env["pmk.metal.sheet"]
        cls.Fastener = env["pmk.metal.fastener"]
        cls.other = env.ref("pmk_calc.profile_type_other")
        cls.angle_type = env.ref("pmk_calc.ptype_уголок_равнополочный")
        cls.angle = env.ref("pmk_calc.profile_уголок_равнополочный_50x50x5")
        cls.sheet4 = env.ref("pmk_calc.sheet_гладкий_4")
        cls.Spec = env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    # ─── помощники ──────────────────────────────────────────────────────
    def _new(self, model, vals, user=None, **ctx):
        """Позиция из окна «Новая позиция на разнос» — как её пишет браузер."""
        context = dict(PENDING_CTX, **ctx)
        return self.env[model].with_user(user or self.engineer).with_context(
            context).create(vals)

    def _spec(self, lines, user=None, qty=1):
        return self.Spec.with_user(user or self.engineer).create({"product_ids": [
            Command.create({"name": "Рама", "qty": qty,
                            "line_ids": [Command.create(vals) for vals in lines]})]})


@tagged("post_install", "-at_install")
class TestStepZ10Pending(Z10Common):

    # ─── Заведение ──────────────────────────────────────────────────────
    def test_engineer_creates_pending_profile(self):
        profile = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6 09Г2С"})
        self.assertTrue(profile.pmk_pending)
        self.assertEqual(profile.display_name, "Уголок 75×6 09Г2С", "Название как в чертеже.")
        self.assertEqual(profile.type_id, self.other, "Вид по умолчанию — «Прочее».")
        self.assertEqual(profile.profile_type, "Прочее")
        self.assertEqual(profile.gost, "—")
        self.assertEqual(profile.mass_per_meter, 0.0)
        self.assertEqual(profile.create_uid, self.engineer, "Кто завёл.")
        self.assertEqual(profile.pmk_pending_label, "на разнос")
        self.assertTrue(profile.pmk_no_weight)

    def test_type_from_previous_line(self):
        """Вид предыдущей строки (pmk_prefer_type_id → default_type_id окна)."""
        profile = self._new("pmk.metal.profile",
                            {"pmk_pending_name": "Уголок 75×6", "mass_per_meter": 6.89},
                            default_type_id=self.angle_type.id)
        self.assertEqual(profile.type_id, self.angle_type)
        self.assertEqual(profile.profile_type, self.angle_type.name)
        self.assertAlmostEqual(profile.mass_per_meter, 6.89)

    def test_pending_sheet_mass_from_thickness(self):
        sheet = self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист ПВ 506",
                                              "thickness_mm": 5.0})
        self.assertTrue(sheet.pmk_pending)
        self.assertAlmostEqual(sheet.mass_per_sqm, 39.25, places=4, msg="5 × 7,85.")
        self.assertEqual(sheet.sheet_type, "Прочее")
        self.assertEqual(sheet.display_name, "Лист ПВ 506")
        with self.assertRaises(ValidationError):
            self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист без толщины"})

    def test_pending_sheet_onchange(self):
        """Окно: толщина → масса м² (её можно поправить)."""
        sheet = self.Sheet.with_user(self.engineer).with_context(PENDING_CTX).new(
            {"pmk_pending": True, "thickness_mm": 3.0})
        sheet._onchange_pmk_pending_thickness()
        self.assertAlmostEqual(sheet.mass_per_sqm, 23.55, places=4)

    def test_pending_fastener(self):
        bolt = self._new("pmk.metal.fastener", {"pmk_pending_name": "Болт М20×80 8.8"})
        self.assertTrue(bolt.pmk_pending)
        self.assertEqual(bolt.name, "Болт М20×80 8.8", "Имя метиза — название из чертежа.")
        self.assertEqual(bolt.display_name, "Болт М20×80 8.8")
        self.assertEqual(bolt.fastener_type, "other")
        self.assertEqual(bolt.weight_kg, 0.0)

    def test_employee_creates_only_pending(self):
        """Из списка справочника или кодом — всё равно «на разнос»."""
        profile = self.Profile.with_user(self.engineer).create({
            "type_id": self.angle_type.id, "profile_type": self.angle_type.name,
            "gost": "ГОСТ 8509-93", "size_label": "77x7", "mass_per_meter": 8.0,
            "pmk_pending": False})
        self.assertTrue(profile.pmk_pending, "Сотрудник заводит только «на разнос».")
        self.assertEqual(profile.pmk_pending_name, "77x7")
        with self.assertRaises(AccessError):
            profile.with_user(self.engineer).write({"pmk_pending": False})
        with self.assertRaises(AccessError):
            self.angle.with_user(self.engineer).write({"mass_per_meter": 1.0})
        with self.assertRaises(AccessError):
            profile.with_user(self.engineer).unlink()
        # Администратор заводит обычную позицию, как прежде.
        plain = self.Profile.with_user(self.admin).create({
            "type_id": self.angle_type.id, "profile_type": self.angle_type.name,
            "gost": "ГОСТ 8509-93", "size_label": "78x7", "mass_per_meter": 8.1})
        self.assertFalse(plain.pmk_pending)
        self.assertEqual(plain.display_name, "Уголок равнополочный 78x7")

    # ─── В детали ───────────────────────────────────────────────────────
    def test_pending_in_detail_weight_and_marks(self):
        bare = self._new("pmk.metal.profile", {"pmk_pending_name": "Швеллер 14П 09Г2С"})
        heavy = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6",
                                                "mass_per_meter": 6.89})
        spec = self._spec([
            {"calc_mode": "linear", "detail_name": "Стойка", "profile_id": bare.id,
             "length_mm": 2000.0, "qty": 2},
            {"calc_mode": "linear", "detail_name": "Связь", "profile_id": heavy.id,
             "length_mm": 1000.0, "qty": 1},
            {"calc_mode": "linear", "detail_name": "Ригель", "profile_id": self.angle.id,
             "length_mm": 1000.0, "qty": 1},
        ])
        lines = spec.product_ids.line_ids
        stand = lines.filtered(lambda l: l.detail_name == "Стойка")
        tie = lines.filtered(lambda l: l.detail_name == "Связь")
        beam = lines.filtered(lambda l: l.detail_name == "Ригель")
        self.assertEqual(stand.weight_total, 0.0, "Без веса — 0, без ошибки.")
        self.assertEqual(stand.pmk_item_note, "на разнос · нет веса")
        self.assertTrue(stand.pmk_no_weight)
        self.assertAlmostEqual(tie.weight_total, 6.89, places=3, msg="С весом — считается.")
        self.assertEqual(tie.pmk_item_note, "на разнос")
        self.assertFalse(beam.pmk_item_note, "Обычная позиция — без пометки.")
        self.assertTrue(spec.product_ids.pmk_has_pending)
        self.assertEqual(spec.pmk_pending_count, 2)
        self.assertEqual(
            spec.pmk_pending_text,
            "Позиции на разнос: 2 — их проверит администратор · без веса: 1 (вес таких деталей 0)")
        self.assertEqual(bare.pmk_pending_spec_id, spec, "Где завели.")
        self.assertEqual(bare.pmk_pending_spec_count, 1)
        self.assertEqual(bare.pmk_pending_line_count, 1)
        # Вес дописали в позиции «на разнос» (администратор) — деталь пересчиталась.
        bare.with_user(self.admin).mass_per_meter = 12.3
        self.assertAlmostEqual(stand.weight_total, 2 * 2 * 12.3, places=3)

    def test_spec_without_pending_has_no_plaque(self):
        spec = self._spec([{"calc_mode": "linear", "profile_id": self.angle.id,
                            "length_mm": 1000.0, "qty": 1}])
        self.assertEqual(spec.pmk_pending_count, 0)
        self.assertFalse(spec.pmk_pending_text)
        self.assertFalse(spec.product_ids.pmk_has_pending)

    # ─── Поиск ──────────────────────────────────────────────────────────
    def test_smart_search_unchanged_and_finds_pending(self):
        before = self.Profile.name_search("уг 50 5", limit=8)
        self.assertEqual(before[0][0], self.angle.id)
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6 09Г2С"})
        after = self.Profile.name_search("уг 50 5", limit=8)
        self.assertEqual(after, before, "Слова не совпали — выдача прежняя.")
        found = [row[0] for row in self.Profile.name_search("уголок 75", limit=8)]
        self.assertIn(pending.id, found, "«на разнос» — по словам названия.")
        self.assertEqual(found[-1], pending.id, "В конце подсказки.")
        self.assertLessEqual(len(found), 8, "Лимит соблюдён.")
        rows = self.Profile.web_name_search(
            "уголок 75 09г2с", {"display_name": {}, "pmk_pending": {}}, limit=8)
        flags = {r["id"]: r["pmk_pending"] for r in rows}
        self.assertIn(pending.id, flags)
        self.assertTrue(flags[pending.id], "Признак для метки в выпадашке.")
        self.assertFalse(any(v for k, v in flags.items() if k != pending.id))
        # Отбор поля соблюдается: окно «Привязать» ищет только настоящие.
        found = [row[0] for row in self.Profile.name_search(
            "уголок 75", domain=[("pmk_pending", "=", False)], limit=50)]
        self.assertNotIn(pending.id, found)
        sheet = self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист ПВ 506",
                                              "thickness_mm": 5.0})
        found = [row[0] for row in self.Sheet.name_search("пв 506", limit=8)]
        self.assertIn(sheet.id, found)

    def test_pending_do_not_crowd_out_real(self):
        """Доводка З-10: позиции «на разнос» с частым словом («лист 4») не
        вытесняют настоящие — не больше двух мест из восьми."""
        before = [row[0] for row in self.Sheet.name_search("лист 4", limit=8)]
        self.assertIn(self.sheet4.id, before)
        pending = self.Sheet
        for number in range(8):
            pending |= self._new("pmk.metal.sheet", {
                "pmk_pending_name": "Лист 4 мм черновик %s" % number, "thickness_mm": 4.0})
        after = [row[0] for row in self.Sheet.name_search("лист 4", limit=8)]
        self.assertLessEqual(len(after), 8, "Лимит соблюдён.")
        kept = before[:6]
        self.assertEqual(after[:len(kept)], kept, "Настоящие — первыми и на своих местах.")
        self.assertEqual(after[0], self.sheet4.id)
        shown = set(after) & set(pending.ids)
        self.assertTrue(shown, "«На разнос» видны.")
        self.assertLessEqual(len(shown), max(2, 8 - len(before)),
                             "Не больше двух мест, если настоящих хватает.")

    def test_profile_type_follows_type(self):
        """Доводка З-10: в форме справочника нет «Вид проката (текст)» — он
        следует за «Вид проката»: новая позиция администратора сохраняется,
        смена вида меняет имя (и порядок, и фильтры по тексту)."""
        other_type = self.env["pmk.metal.profile.type"].search(
            [("id", "not in", (self.angle_type.id, self.other.id))], limit=1)
        self.assertTrue(other_type)
        form = Form(self.Profile.with_user(self.admin))
        form.type_id = self.angle_type
        form.size_label = "77x7 (тест З-10)"
        form.gost = "ГОСТ 8509-93"
        form.mass_per_meter = 8.0
        self.assertEqual(form.display_name, "%s 77x7 (тест З-10)" % self.angle_type.name,
                         "Имя в окне до сохранения.")
        rec = form.save()
        self.assertFalse(rec.pmk_pending)
        self.assertEqual(rec.profile_type, self.angle_type.name)
        rec.with_user(self.admin).write({"type_id": other_type.id})
        self.assertEqual(rec.profile_type, other_type.name, "Сменили вид — текст за ним.")
        self.assertEqual(rec.display_name, "%s 77x7 (тест З-10)" % other_type.name)
        # Загрузка справочника передаёт текст явно — его не трогаем.
        rec.with_user(self.admin).write({"type_id": self.angle_type.id,
                                         "profile_type": "Особый текст"})
        self.assertEqual(rec.profile_type, "Особый текст")

    def test_reference_create_admin_only(self):
        """Доводка З-10: «Новый» в списках и формах справочников — только
        администратору; сотрудник заводит из детали (право создавать у него
        есть — ради «на разнос»)."""
        for model in ("pmk.metal.profile", "pmk.metal.sheet", "pmk.metal.fastener"):
            for user, want in ((self.engineer, "0"), (self.admin, "1")):
                with self.subTest(model=model, user=user.login):
                    views = self.env[model].with_user(user).get_views(
                        [(False, "list"), (False, "form")])["views"]
                    for kind in ("list", "form"):
                        arch = etree.fromstring(views[kind]["arch"])
                        self.assertEqual(arch.get("create"), want, kind)

    def test_bind_sheet_layout_reset_said(self):
        """Доводка З-10: «Привязать» у листа гасит раскладку (лист входит в
        неё) — и говорит об этом в ленте расчёта."""
        pending = self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист 4 черновик (З-10)",
                                                "thickness_mm": 4.0})
        spec = self._spec([{"calc_mode": "sheet", "detail_name": "Косынка",
                            "sheet_id": pending.id, "a_mm": 200.0, "b_mm": 200.0, "qty": 4}])
        spec.with_user(self.engineer).action_draft_layout()
        line = spec.product_ids.line_ids
        self.assertNotEqual(line.layout_state, "none")
        pending.with_user(self.admin)._pmk_pending_bind(self.sheet4)
        self.assertEqual(line.sheet_id, self.sheet4)
        self.assertEqual(line.layout_state, "none")
        spec.invalidate_recordset(["message_ids"])
        text = " ".join(str(m.body) for m in spec.message_ids)
        self.assertIn("Раскладка листов сброшена у 1 детали", text)

    def test_pending_list_row_opens_position(self):
        arch = etree.fromstring(self.env["pmk.metal.pending"].with_user(self.admin).get_views(
            [(False, "list")])["views"]["list"]["arch"])
        self.assertEqual(arch.get("action"), "action_pmk_accept")
        self.assertEqual(arch.get("type"), "object")

    def test_badges_before_name(self):
        """Метка «на разнос» — перед названием: многоточие её не съедает."""
        xml = _read("pmk_calc/static/src/xml/product_lines_field.xml")
        cell = xml[xml.index('<td class="pmk-c-what"'):]
        cell = cell[:cell.index("</td>")]
        self.assertLess(cell.index("pmk-pending-badge--lead"), cell.index('t-esc="info[0]"'))
        self.assertIn("pendingNote(line) ? info[0]", cell, "Метка — и в подсказке ячейки.")
        js = _read("pmk_calc/static/src/js/pending_create.js")
        self.assertIn("htmlJoin([badge, suggestion.label", js)

    # ─── Список и права ─────────────────────────────────────────────────
    def test_pending_list_admin_only(self):
        profile = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6"})
        sheet = self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист ПВ 506",
                                              "thickness_mm": 5.0})
        bolt = self._new("pmk.metal.fastener", {"pmk_pending_name": "Болт М20×80"})
        self._spec([{"calc_mode": "linear", "profile_id": profile.id,
                     "length_mm": 1000.0, "qty": 1}])
        self.env.flush_all()
        Pending = self.env["pmk.metal.pending"]
        rows = Pending.with_user(self.admin).search([])
        mine = rows.filtered(lambda r: r.user_id == self.engineer)
        self.assertEqual(sorted(mine.mapped("kind")), ["fastener", "linear", "sheet"])
        row = mine.filtered(lambda r: r.kind == "linear")
        self.assertEqual(row.name, "Уголок 75×6")
        self.assertEqual(row.spec_count, 1)
        self.assertEqual(row.weight_label, "нет веса")
        sheet_row = mine.filtered(lambda r: r.kind == "sheet")
        self.assertEqual(sheet_row.weight_label, "39,25 кг/м²")
        self.assertEqual(sheet_row._pmk_source(), sheet)
        self.assertEqual(mine.filtered(lambda r: r.kind == "fastener")._pmk_source(), bolt)
        with self.assertRaises(AccessError):
            Pending.with_user(self.engineer).search([])
        with self.assertRaises(AccessError):
            row.with_user(self.engineer).action_pmk_bind()
        menu = self.env.ref("pmk_calc.menu_pmk_calc_pending")
        self.assertEqual(menu.name, "Новые позиции на разнос")
        self.assertEqual(menu.parent_id, self.env.ref("pmk_calc.menu_pmk_calc_reference"))
        self.assertEqual(menu.group_ids, self.env.ref("base.group_system"))

    # ─── Привязать к существующей ───────────────────────────────────────
    def test_bind_moves_all_details(self):
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 50×5 Ст3"})
        spec_a = self._spec([
            {"calc_mode": "linear", "detail_name": "Стойка", "profile_id": pending.id,
             "length_mm": 1000.0, "qty": 2},
            {"calc_mode": "linear", "detail_name": "Связь", "profile_id": pending.id,
             "length_mm": 500.0, "qty": 1},
        ])
        spec_b = self._spec([{"calc_mode": "linear", "detail_name": "Ригель",
                              "profile_id": pending.id, "length_mm": 1000.0, "qty": 1}])
        self.assertEqual(spec_a.total_weight, 0.0)
        with self.assertRaises(AccessError):
            pending.with_user(self.engineer)._pmk_pending_bind(self.angle)
        with self.assertRaises(UserError):
            pending.with_user(self.admin)._pmk_pending_bind(
                self._new("pmk.metal.profile", {"pmk_pending_name": "Другая"}))
        row = self.env["pmk.metal.pending"].with_user(self.admin).search(
            [("res_model", "=", "pmk.metal.profile"), ("res_id", "=", pending.id)])
        action = row.action_pmk_bind()
        wizard = self.env["pmk.metal.pending.bind"].with_user(self.admin).browse(action["res_id"])
        self.assertIn("3 детали в 2 расчётах", wizard.usage_text)
        wizard.profile_id = self.angle
        wizard.action_bind()
        lines = (spec_a | spec_b).product_ids.line_ids
        self.assertEqual(lines.profile_id, self.angle, "Все детали всех расчётов.")
        self.assertAlmostEqual(spec_a.total_weight, (2 * 1.0 + 0.5) * self.angle.mass_per_meter,
                               places=3, msg="Вес пересчитан.")
        self.assertEqual(lines.type_id, self.angle.type_id, "Вид детали — из позиции.")
        self.assertFalse(pending.active, "Временная — в архив.")
        self.assertFalse(spec_a.pmk_pending_count)
        for spec, count in ((spec_a, "2 детали"), (spec_b, "1 деталь")):
            spec.invalidate_recordset(["message_ids"])
            text = " ".join(str(m.body) for m in spec.message_ids)
            self.assertIn("Уголок 50×5 Ст3", text)
            self.assertIn(count, text)
        self.assertFalse(self.env["pmk.metal.pending"].with_user(self.admin).search(
            [("res_model", "=", "pmk.metal.profile"), ("res_id", "=", pending.id)]))

    def test_bind_sheet_also_in_dobor(self):
        """Ссылки на справочник вне расчёта (доборка) тоже переводятся."""
        galv = self.env["pmk.metal.sheet"].search([("sheet_type", "=", "Оцинкованный")], limit=1)
        pending = self._new("pmk.metal.sheet", {"pmk_pending_name": "Оцинковка 0,7",
                                                "thickness_mm": 0.7})
        targets = pending._pmk_bind_targets()
        self.assertIn(("pmk.metal.spec.line", "sheet_id"), targets)
        self.assertIn(("pmk.dobor.order.line", "sheet_id"), targets)
        self.assertNotIn("pmk.metal.pending.bind", [model for model, _f in targets])
        spec = self._spec([{"calc_mode": "sheet", "sheet_id": pending.id,
                            "a_mm": 500.0, "b_mm": 500.0, "qty": 1}])
        pending.with_user(self.admin)._pmk_pending_bind(galv)
        self.assertEqual(spec.product_ids.line_ids.sheet_id, galv)

    # ─── Принять в справочник ───────────────────────────────────────────
    def test_accept(self):
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6 09Г2С"})
        spec = self._spec([{"calc_mode": "linear", "profile_id": pending.id,
                            "length_mm": 1000.0, "qty": 1}])
        line = spec.product_ids.line_ids
        self.assertEqual(line.type_id, self.other)
        with self.assertRaises(AccessError):
            pending.with_user(self.engineer).action_pmk_accept()
        with self.assertRaises(UserError) as caught:
            pending.with_user(self.admin).action_pmk_accept()
        for word in ("вид проката", "стандарт", "масса"):
            self.assertIn(word, str(caught.exception))
        pending.with_user(self.admin).write({
            "type_id": self.angle_type.id, "size_label": "75x6",
            "gost": "ГОСТ 8509-93", "mass_per_meter": 6.89})
        pending.with_user(self.admin).action_pmk_accept()
        self.assertFalse(pending.pmk_pending)
        self.assertTrue(pending.active)
        self.assertEqual(pending.display_name, "Уголок равнополочный 75x6", "Обычное имя.")
        self.assertEqual(pending.pmk_pending_name, "Уголок 75×6 09Г2С", "Как в чертеже — помнит.")
        self.assertEqual(line.type_id, self.angle_type, "Вид детали — из принятой позиции.")
        self.assertAlmostEqual(line.weight_total, 6.89, places=3)
        self.assertFalse(line.pmk_item_note)
        self.assertEqual(spec.pmk_pending_count, 0)
        spec.invalidate_recordset(["message_ids"])
        self.assertIn("принята в справочник", " ".join(str(m.body) for m in spec.message_ids))

    def test_archive_unused(self):
        used = self._new("pmk.metal.fastener", {"pmk_pending_name": "Болт М24 (тест З-10)"})
        spare = self._new("pmk.metal.fastener", {"pmk_pending_name": "Болт М30 (тест З-10)"})
        self._spec([{"calc_mode": "fastener", "fastener_id": used.id, "qty": 4}])
        with self.assertRaises(UserError):
            used.with_user(self.admin).action_pmk_archive_unused()
        spare.with_user(self.admin).action_pmk_archive_unused()
        self.assertFalse(spare.active)
        self.assertFalse(self.Fastener.name_search("Болт М30 (тест З-10)"), "Из выпадашки ушла.")

    # ─── Виды ───────────────────────────────────────────────────────────
    def _spec_arch(self):
        view = self.env.ref("pmk_calc.view_metal_spec_form")
        return etree.fromstring(self.env["pmk.metal.spec"].get_view(view.id, "form")["arch"])

    def test_product_window_fields_allow_pending(self):
        arch = self._spec_arch()
        window = arch.xpath("//field[@name='product_ids']/form")[0]
        for page, fname in (("linear", "profile_id"), ("sheet", "sheet_id"),
                            ("fastener", "fastener_id")):
            with self.subTest(field=fname):
                node = window.xpath(".//page[@name='%s']//list/field[@name='%s']" % (page, fname))[0]
                options = node.get("options") or ""
                self.assertNotIn("no_create", options.replace("no_quick_create", ""))
                self.assertIn("no_quick_create", options, "Только окно, не по тексту.")
                self.assertIn("'pmk_pending_create': True", node.get("context"))
                note = window.xpath(".//page[@name='%s']//list/field[@name='pmk_item_note']" % page)
                self.assertTrue(note, "Колонка «Разнос».")
                self.assertEqual(note[0].get("column_invisible"), "not parent.pmk_has_pending")
        # Вид, марка, покрытие — по-прежнему без заведения.
        for fname in ("type_id", "grade_id", "paint_id"):
            for node in window.xpath(".//field[@name='%s']" % fname):
                self.assertIn("no_create", node.get("options") or "", fname)
        self.assertTrue(arch.xpath("//div[@name='pmk_pending_alert']"))
        self.assertTrue(arch.xpath("//field[@name='pmk_pending_text']"))

    def test_composition_editor_allows_pending(self):
        js = _read("pmk_calc/static/src/js/product_lines_field.js")
        self.assertEqual(js.count("pending: true"), 3, "Прокат, лист, метиз.")
        self.assertIn("pmk_pending_create: true", js)
        xml = _read("pmk_calc/static/src/xml/product_lines_field.xml")
        self.assertIn('canCreateEdit="!!input.pending"', xml)
        self.assertIn('canQuickCreate="false"', xml)
        self.assertIn("pendingNote(line)", xml)
        patch_js = _read("pmk_calc/static/src/js/pending_create.js")
        self.assertIn("Нет в справочнике — завести новую…", patch_js)
        self.assertIn("Новая позиция на разнос", patch_js)
        for ref in ("view_metal_profile_pending_form", "view_metal_sheet_pending_form",
                    "view_metal_fastener_pending_form"):
            self.assertIn("pmk_calc.%s" % ref, patch_js)
            self.env.ref("pmk_calc.%s" % ref)

    def test_pending_forms(self):
        for model, ref in (("pmk.metal.profile", "view_metal_profile_pending_form"),
                           ("pmk.metal.sheet", "view_metal_sheet_pending_form"),
                           ("pmk.metal.fastener", "view_metal_fastener_pending_form")):
            with self.subTest(model=model):
                view = self.env.ref("pmk_calc.%s" % ref)
                got = self.env[model].with_user(self.engineer).with_context(
                    form_view_ref="pmk_calc.%s" % ref).get_views([(False, "form")])
                self.assertEqual(got["views"]["form"]["id"], view.id, "form_view_ref окна.")
                arch = etree.fromstring(got["views"]["form"]["arch"])
                self.assertEqual(arch.get("string"), "Новая позиция на разнос")
                name = arch.xpath("//field[@name='pmk_pending_name']")[0]
                self.assertEqual(name.get("required"), "1")
                buttons = arch.xpath("//footer/button")
                self.assertEqual([b.get("string") for b in buttons], ["Завести", "Отмена"])
                self.assertEqual(len([b for b in buttons if _filled(b)]), 1)
                default = self.env[model].with_user(self.engineer).get_views([(False, "form")])
                self.assertNotEqual(default["views"]["form"]["id"], view.id,
                                    "Окно заведения формой по умолчанию не стало.")

    def test_accept_forms_one_filled_button(self):
        for model in ("pmk.metal.profile", "pmk.metal.sheet", "pmk.metal.fastener"):
            with self.subTest(model=model):
                arch = etree.fromstring(self.env[model].with_user(self.admin).get_views(
                    [(False, "form")])["views"]["form"]["arch"])
                filled = [b for b in arch.iter("button") if _filled(b)]
                self.assertEqual([b.get("string") for b in filled], ["Принять в справочник"])

    def test_words(self):
        for path in ("pmk_calc/views/pending_views.xml", "pmk_calc/static/src/js/pending_create.js"):
            text = _read(path).lower()
            for word in ("закупщик", "спецификац", "покупател"):
                self.assertNotIn(word, text, path)
