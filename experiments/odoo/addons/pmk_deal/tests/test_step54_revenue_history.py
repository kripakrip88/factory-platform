# -*- coding: utf-8 -*-
"""История сделки: доход от расчёта (разбор UX, шаг 54, 07.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), не на боевой odoo:
    odoo -d pmk_deal_test -i pmk_deal --test-enable \\
         --test-tags /pmk_deal:TestRevenueHistoryStep54,/pmk_deal:TestRevenueHistoryHttpStep54 \\
         --stop-after-init --http-port 8099
Путь стенда (список полей держит tracking_manager) — вторым прогоном с
-i pmk_deal,tracking_manager: test_stage_tracking_manager иначе пропускается.

Что проверяем. Доход сделки (expected_revenue) меняется сам — от цены
клиенту главного расчёта. Такая смена должна попадать в ленту сделки той же
строкой, что и ручная правка: «Цена клиенту: было → стало», от имени
того, кто сохранил расчёт, ровно одна строка на сохранение. Пишет её
штатный механизм ядра (mail.thread._compute_field_value → _track_prepare →
_track_finalize перед фиксацией) — своих сообщений нет.

Как устроен тест. Строка пишется перед фиксацией транзакции (precommit).
Поэтому каждое «сохранение» — _save(): действие в окружении менеджера,
flush_all() в нём же (пересчёт идёт от имени менеджера, как в запросе) и
cr.flush() — он запускает precommit, как фиксация в запросе. Сделка
создаётся и сразу фиксируется (_deal): ядро глушит историю записи,
созданной в этой же транзакции (_track_discard в mail.thread.create), —
из-за этого в тесте шага 31 строки и «не было».

Основа — TransactionCase, а не MailCommon: от mail-набора нужен только
flush_tracking (те же flush_all + cr.flush), а MailCommon переименовывает
admin, включает мультикомпанию и почтовые серверы — лишнее для истории.
"""
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import Form, HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import html2plaintext

# Поля сделки, которые зависят от расчёта, но в историю НЕ идут (решение по
# умолчанию шага 54: «не засорять ленту»).
NOT_TRACKED = (
    "pmk_spec_id", "pmk_margin_pct", "pmk_weight_t", "pmk_no_price_count",
    "pmk_price_incomplete", "pmk_spec_price", "pmk_no_price_label",
    "pmk_spec_summary", "pmk_spec_card", "pmk_kpi_weight", "pmk_kpi_price",
    "pmk_kpi_metal", "pmk_kpi_margin", "prorated_revenue",
)


class RevenueHistoryMixin:
    """Помощники: сделка, расчёт, «сохранение» и строки истории дохода."""

    def _setup_people(self, password=None):
        values = {"name": "Сергей Расчётов (шаг 54)"}
        if password:
            values["password"] = password
        self.manager = new_test_user(
            self.env, login="pmk54_manager",
            groups="base.group_user,sales_team.group_sale_salesman", **values)
        self.customer = self.env["res.partner"].create({
            "name": "ООО «Тайга-Металл» (шаг 54)", "is_company": True})
        self.revenue_field = self.env["ir.model.fields"]._get("crm.lead", "expected_revenue")

    def _commit_tracking(self, env=None):
        """Как фиксация запроса: пересчёт и precommit (история пишется в нём)."""
        env = env or self.env
        env.flush_all()
        env.cr.flush()

    def _deal(self, name="Каркас склада (шаг 54)"):
        """Сделка менеджера, уже «сохранённая»: создание отдельной транзакцией."""
        deal = self.env["crm.lead"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True,
        ).create({
            "name": name, "type": "opportunity",
            "partner_id": self.customer.id, "user_id": self.manager.id,
        })
        self._commit_tracking()
        return self.env["crm.lead"].browse(deal.id)

    def _save(self, action, user=None):
        """Одно сохранение от имени менеджера: action(env) → пересчёт → precommit."""
        env = self.env(user=user or self.manager)
        result = action(env)
        self._commit_tracking(env)
        self.env.invalidate_all()
        return result

    def _spec(self, deal=None, price=0.0, qty=1, date=None):
        """Расчёт с одним изделием (или без изделий при price=0)."""
        def create(env):
            products = []
            if price:
                products.append(Command.create({
                    "name": "Колонна К-1", "qty": qty, "price_customer_unit": price}))
            spec = env["pmk.metal.spec"].create({
                "opportunity_id": deal.id if deal else False,
                "partner_id": self.customer.id,
                "date": date or fields.Date.today(),
                "product_ids": products,
            })
            return spec.id
        spec_id = self._save(create)
        return self.env["pmk.metal.spec"].browse(spec_id)

    def _revenue_lines(self, deal):
        return self.env["mail.tracking.value"].sudo().search([
            ("field_id", "=", self.revenue_field.id),
            ("mail_message_id.model", "=", "crm.lead"),
            ("mail_message_id.res_id", "=", deal.id),
        ], order="id")

    def _tracking_messages(self, deal):
        """Все сообщения с отметками «было → стало» по сделке (любое поле)."""
        return self.env["mail.message"].sudo().search([
            ("model", "=", "crm.lead"), ("res_id", "=", deal.id),
            ("tracking_value_ids", "!=", False),
        ], order="id")

    def _new_line(self, deal, before, old, new, author=None):
        """Ровно одна новая строка дохода old → new — как у ручной правки."""
        lines = self._revenue_lines(deal) - before
        self.assertEqual(len(lines), 1, "Одно сохранение — одна строка дохода: %s" % [
            (line.old_value_float, line.new_value_float) for line in lines])
        self.assertAlmostEqual(lines.old_value_float, old, places=2)
        self.assertAlmostEqual(lines.new_value_float, new, places=2)
        self.assertEqual(lines.currency_id, deal.company_currency,
                         "Сумма в рублях компании — как у ручной правки.")
        message = lines.mail_message_id
        self.assertEqual(message.author_id, (author or self.manager).partner_id,
                         "Автор — тот, кто сохранил расчёт, а не OdooBot.")
        self.assertEqual(message.message_type, "notification")
        self.assertFalse(html2plaintext(message.body or "").strip(),
                         "Своего текста нет — стандартная отметка «было → стало».")
        self.assertEqual(message.tracking_value_ids, lines,
                         "В строке только доход: вес, металл, маржа, расчёт — не пишутся.")
        return lines

    def _no_new_line(self, deal, before, why):
        self.assertFalse(self._revenue_lines(deal) - before, why)


@tagged("post_install", "-at_install")
class TestRevenueHistoryStep54(RevenueHistoryMixin, TransactionCase):

    def setUp(self):
        super().setUp()
        self._setup_people()

    # ─── что вообще пишется в историю ────────────────────────────────────
    def test_only_revenue_is_tracked(self):
        Lead = self.env["crm.lead"]
        tracked = Lead._track_get_fields()
        self.assertIn("expected_revenue", tracked)
        self.assertTrue(Lead._fields["expected_revenue"].tracking,
                        "tracking=True прописан у поля (pmk_deal), не только в crm.")
        for fname in NOT_TRACKED:
            with self.subTest(field=fname):
                self.assertNotIn(fname, tracked, "Не засоряем ленту полями расчёта.")

    def test_history_label_is_customer_price(self):
        """Одно понятие — одно слово: в ленте та же подпись, что на карточке
        и в колонке списка, — «Цена клиенту», а не «Ожидаемый доход»."""
        Lead = self.env["crm.lead"]
        self.assertEqual(Lead._fields["expected_revenue"].string, "Цена клиенту")
        self.assertEqual(self.revenue_field.with_context(lang="en_US").field_description,
                         "Цена клиенту")
        for lang in ("en_US", "ru_RU"):
            if not self.env["res.lang"]._lang_get(lang):
                continue
            with self.subTest(lang=lang):
                label = Lead.with_context(lang=lang).fields_get(
                    ["expected_revenue"], ["string"])["expected_revenue"]["string"]
                self.assertEqual(label, "Цена клиенту",
                                 "Подпись строки ленты берётся отсюда (fields_get).")
        same = [name for name, field in Lead._fields.items()
                if field.string == "Цена клиенту" and name != "expected_revenue"]
        self.assertFalse(same, "Две одинаковые подписи — предупреждение ядра при загрузке.")

    def test_history_line_shows_customer_price_label(self):
        deal = self._deal()
        before = self._revenue_lines(deal)
        self._spec(deal, price=1000.0)
        line = self._new_line(deal, before, 0.0, 1000.0)
        formatted = line._tracking_value_format()
        self.assertEqual(formatted[0]["fieldInfo"]["changedField"], "Цена клиенту")

    # ─── доход меняется от расчёта ───────────────────────────────────────
    def test_attach_spec_writes_line(self):
        deal = self._deal()
        before = self._revenue_lines(deal)
        self._spec(deal, price=1000.0)
        self._new_line(deal, before, 0.0, 1000.0)

    def test_customer_price_change(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).product_ids.write(
            {"price_customer_unit": 9500000.0}))
        self.assertEqual(deal.expected_revenue, 9500000.0)
        self._new_line(deal, before, 1000.0, 9500000.0)
        # И обратно — ещё одна строка.
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).product_ids.write(
            {"price_customer_unit": 1000.0}))
        self._new_line(deal, before, 9500000.0, 1000.0)

    def test_quantity_change(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).product_ids.write({"qty": 3}))
        self._new_line(deal, before, 1000.0, 3000.0)

    def test_composition_add_and_remove(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).write({"product_ids": [Command.create({
            "name": "Ригель Р-1", "qty": 2, "price_customer_unit": 250.0})]}))
        self._new_line(deal, before, 1000.0, 1500.0)

        extra = spec.product_ids.filtered(lambda p: p.name == "Ригель Р-1")
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).write({
            "product_ids": [Command.delete(extra.id)]}))
        self._new_line(deal, before, 1500.0, 1000.0)

    def test_attach_detach_and_move(self):
        deal = self._deal()
        other = self._deal("Навес (шаг 54)")
        spec = self._spec(price=5000.0)  # без сделки
        self.assertFalse(self._tracking_messages(deal))

        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).write({"opportunity_id": deal.id}))
        self._new_line(deal, before, 0.0, 5000.0)

        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).write({"opportunity_id": False}))
        self._new_line(deal, before, 5000.0, 0.0)

        self._save(lambda env: spec.with_env(env).write({"opportunity_id": deal.id}))
        before, before_other = self._revenue_lines(deal), self._revenue_lines(other)
        self._save(lambda env: spec.with_env(env).write({"opportunity_id": other.id}))
        self._new_line(deal, before, 5000.0, 0.0)
        self._new_line(other, before_other, 0.0, 5000.0)

    def test_second_spec_becomes_main_and_unlink(self):
        today = fields.Date.today()
        deal = self._deal()
        first = self._spec(deal, price=1000.0, date=today - timedelta(days=5))
        before = self._revenue_lines(deal)
        second = self._spec(deal, price=2000.0, date=today)
        self.assertEqual(deal.pmk_spec_id, second)
        self._new_line(deal, before, 1000.0, 2000.0)

        # Удалили главный — доход вернулся к цене предыдущего.
        before = self._revenue_lines(deal)
        self._save(lambda env: second.with_env(env).unlink())
        self.assertEqual(deal.pmk_spec_id, first)
        self._new_line(deal, before, 2000.0, 1000.0)

        # Удалили последний — доход к нулю.
        before = self._revenue_lines(deal)
        self._save(lambda env: first.with_env(env).unlink())
        self._new_line(deal, before, 1000.0, 0.0)

    def test_copy_with_same_price_writes_nothing(self):
        today = fields.Date.today()
        deal = self._deal()
        spec = self._spec(deal, price=1000.0, date=today - timedelta(days=3))
        before = self._revenue_lines(deal)
        copy_id = self._save(lambda env: spec.with_env(env).copy().id)
        self.assertEqual(deal.pmk_spec_id.id, copy_id, "Копия стала главной (R4).")
        self._no_new_line(deal, before, "Сумма та же — строки нет.")
        # Удалили копию — главным снова оригинал с той же ценой.
        self._save(lambda env: env["pmk.metal.spec"].browse(copy_id).unlink())
        self.assertEqual(deal.pmk_spec_id, spec)
        self._no_new_line(deal, before, "Сумма та же — строки нет.")

    # ─── без изменения суммы — записи нет ────────────────────────────────
    def test_no_line_without_sum_change(self):
        today = fields.Date.today()
        deal = self._deal()
        spec = self._spec(deal, price=1000.0, date=today - timedelta(days=1))
        before = self._revenue_lines(deal)
        before_messages = self._tracking_messages(deal)
        cases = [
            ("та же цена", lambda env: spec.with_env(env).product_ids.write(
                {"price_customer_unit": 1000.0})),
            ("название изделия", lambda env: spec.with_env(env).product_ids.write(
                {"name": "Колонна К-1а"})),
            ("заметка для себя", lambda env: spec.with_env(env).product_ids.write(
                {"note": "уточнить толщину у технолога"})),
            ("предмет КП", lambda env: spec.with_env(env).write(
                {"note": "Металлоконструкции склада"})),
            ("дата расчёта", lambda env: spec.with_env(env).write(
                {"date": today - timedelta(days=2)})),
        ]
        for why, action in cases:
            with self.subTest(why):
                self._save(action)
                self._no_new_line(deal, before, why)
        # Главным стал другой расчёт с той же суммой — дохода в ленте нет, и
        # смена главного расчёта тоже не пишется (решение по умолчанию).
        same = self._spec(deal, price=1000.0, date=today)
        self.assertEqual(deal.pmk_spec_id, same)
        self._no_new_line(deal, before, "Главный сменился, сумма та же.")
        self.assertEqual(self._tracking_messages(deal), before_messages,
                         "Ни одной отметки «было → стало» в сделке.")

    def test_weight_and_metal_change_writes_nothing(self):
        profile = self.env["pmk.metal.profile"].search([("mass_per_meter", ">", 0)], limit=1)
        if not profile:
            self.skipTest("Нет сортамента в справочнике pmk_calc")
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        weight = spec.total_weight
        self._save(lambda env: spec.with_env(env).product_ids.write({"line_ids": [
            Command.create({"calc_mode": "linear", "profile_id": profile.id,
                            "length_mm": 6000.0, "qty": 2})]}))
        self.assertGreater(spec.total_weight, weight, "Вес вырос.")
        self.assertEqual(deal.expected_revenue, 1000.0)
        self._no_new_line(deal, before, "Вес и металл — не доход, в ленту не идут.")
        self.assertFalse(self._tracking_messages(deal) - self._revenue_lines(deal).mail_message_id,
                         "И отдельных строк про вес/маржу нет.")

    # ─── одно сохранение — одна строка ───────────────────────────────────
    def test_one_save_one_line(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)

        def many_edits(env):
            record = spec.with_env(env)
            record.product_ids.write({"price_customer_unit": 2000.0})
            env.flush_all()  # промежуточный пересчёт — без фиксации
            record.product_ids.write({"qty": 2})
            env.flush_all()
            record.write({"product_ids": [Command.create({
                "name": "Связь С-1", "qty": 1, "price_customer_unit": 500.0})]})
        self._save(many_edits)
        self.assertEqual(deal.expected_revenue, 4500.0)
        self._new_line(deal, before, 1000.0, 4500.0)

    def test_back_and_forth_in_one_save_writes_nothing(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)

        def there_and_back(env):
            record = spec.with_env(env)
            record.product_ids.write({"price_customer_unit": 2000.0})
            env.flush_all()
            record.product_ids.write({"price_customer_unit": 1000.0})
        self._save(there_and_back)
        self._no_new_line(deal, before, "1000 → 2000 → 1000 за одно сохранение — строки нет.")

    # ─── ручная правка — как раньше ──────────────────────────────────────
    def test_manual_edit_then_spec(self):
        deal = self._deal("Без расчёта (шаг 54)")
        before = self._revenue_lines(deal)
        self._save(lambda env: deal.with_env(env).write({"expected_revenue": 777.0}))
        self._new_line(deal, before, 0.0, 777.0)

        before = self._revenue_lines(deal)
        self._spec(deal, price=5000.0)
        self._new_line(deal, before, 777.0, 5000.0)

    # ─── форма расчёта: правка цены и «Сохранить» ────────────────────────
    def test_form_save_writes_one_line(self):
        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        env = self.env(user=self.manager)
        try:
            form = Form(spec.with_env(env))
            with form.product_ids.edit(0) as product:
                product.price_customer_unit = 3000.0
        except (AssertionError, KeyError, ValueError, TypeError, NotImplementedError) as error:
            self.skipTest("Форма расчёта не собирается в тестовом Form: %s" % error)
        # Промежуточные onchange до сохранения ничего не пишут.
        self._commit_tracking(env)
        self._no_new_line(deal, before, "До сохранения формы строки нет.")
        form.save()
        self._commit_tracking(env)
        self.env.invalidate_all()
        self._new_line(deal, before, 1000.0, 3000.0)

    # ─── как на стенде: список полей держит tracking_manager ─────────────
    def test_stage_tracking_manager(self):
        if "custom_tracking" not in self.env["ir.model.fields"]._fields:
            self.skipTest("tracking_manager не установлен (второй прогон: -i pmk_deal,tracking_manager)")
        model = self.env["ir.model"]._get("crm.lead")
        model.write({"active_custom_tracking": True})
        model.write({"automatic_custom_tracking": True})
        model.update_custom_tracking()
        self.env.registry.clear_cache()
        tracked = self.env["crm.lead"]._track_get_fields()
        self.assertIn("expected_revenue", tracked, "Как на стенде: доход в списке tracking_manager.")
        for fname in NOT_TRACKED:
            with self.subTest(field=fname):
                self.assertNotIn(fname, tracked)

        deal = self._deal()
        spec = self._spec(deal, price=1000.0)
        before = self._revenue_lines(deal)
        self._save(lambda env: spec.with_env(env).product_ids.write(
            {"price_customer_unit": 9500000.0}))
        self._new_line(deal, before, 1000.0, 9500000.0)


@tagged("post_install", "-at_install")
class TestRevenueHistoryHttpStep54(RevenueHistoryMixin, HttpCase):
    """Настоящий запрос веб-клиента: автор строки — пользователь сессии."""

    PASSWORD = "pmk54-manager-pass"

    def setUp(self):
        super().setUp()
        self._setup_people(password=self.PASSWORD)
        self.deal = self._deal()
        self.spec = self._spec(self.deal, price=1000.0)
        self.product = self.spec.product_ids
        self._commit_tracking()
        self.authenticate(self.manager.login, self.PASSWORD)

    def _call(self, method, args, kwargs=None):
        return self.make_jsonrpc_request(
            "/web/dataset/call_kw/pmk.metal.spec/%s" % method, {
                "model": "pmk.metal.spec", "method": method,
                "args": args, "kwargs": kwargs or {},
            }, timeout=60)

    def test_web_save_writes_line_from_session_user(self):
        before = self._revenue_lines(self.deal)
        self._call("web_save", [[self.spec.id], {
            "product_ids": [[Command.UPDATE, self.product.id, {"price_customer_unit": 2000.0}]],
        }], {"specification": {"price_customer_total": {}}})
        self.env.invalidate_all()
        self.assertEqual(self.deal.expected_revenue, 2000.0)
        self._new_line(self.deal, before, 1000.0, 2000.0)

    def test_onchange_without_save_writes_nothing(self):
        before = self._revenue_lines(self.deal)
        result = self._call("onchange", [
            [self.spec.id],
            {"product_ids": [[Command.UPDATE, self.product.id, {"price_customer_unit": 7777.0}]]},
            ["product_ids"],
            {"price_customer_total": {}, "opportunity_id": {},
             "product_ids": {"fields": {"price_customer_unit": {}, "price_customer_total": {}}}},
        ])
        self.assertIsInstance(result, dict)
        self.env.invalidate_all()
        self.assertEqual(self.deal.expected_revenue, 1000.0, "Доход в базе не изменился.")
        self._no_new_line(self.deal, before, "Без сохранения строки нет.")
