# -*- coding: utf-8 -*-
"""История расчётов и доборок по-русски (разбор UX, шаг 30).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk30_test -i pmk_calc,tracking_manager --test-enable \\
         --test-tags /pmk_calc,/tracking_manager --stop-after-init --http-port 8099
Без tracking_manager в базе тесты шаблона и сквозные пропускаются.

Что проверяем:
  • имя позиции доборки — её название, а не «pmk.dobor.order.line,20»;
  • правка старых записей (tools/tracking_ru.py) на настоящих телах из
    боевой базы и сама миграция 19.0.1.0.4: чужие сообщения не тронуты,
    повторный запуск ничего не меняет;
  • перевод шаблона tracking_manager (vendor/.../i18n_extra/ru.po):
    «Добавлено / Удалено / Изменено» по-русски, английский — как был;
  • сквозной путь с правками tracking_manager: новая позиция — «Добавлено:
    Доборка 1» без шума «Изменено: … Название доборки»; детали изделия —
    числом строк, замена детали — с разницей «(+1, −1)»; удалённое изделие —
    по имени;
  • доводка: удалили позицию доборки или изделие расчёта и тем же
    сохранением поменяли статус / «Предмет КП» — обычные отметки ядра в
    ленте есть (раньше MissingError выбрасывала их все), удалённая строка в
    них — по названию;
  • доводка: история без языка в контексте (скрипт, OdooBot) — на языке
    базы по умолчанию; запись ядра «… created» — «Создано: …».

Тесты автора tracking_manager гонять на базе с языком по умолчанию en_US
(так её создаёт odoo -d … -i …): запасной язык истории — язык базы по
умолчанию, а тесты автора пишут без языка в контексте и ждут «New», «Delete».
"""
import importlib.util
import re

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.pmk_calc.models.deleted_names import KEY as DELETED_NAMES
from odoo.addons.pmk_calc.tools.tracking_ru import (
    NO_TITLE, created_ru, dobor_ids, rewrite, titles_from_history)

ARROW = ('<div class="o_Message_trackingValueSeparator o_Message_trackingValueItem'
         ' fa fa-long-arrow-right" title="Changed"></div>')
# Настоящие тела записей истории боевой базы (mail_message 2276, 2224, 266,
# 2291; пробелы схлопнуты).
DELETE_ATHV = '<div><ul><li><b>Изделия: </b><br><ul><b>Delete :</b> athv </ul></li></ul></div>'
SPEC_LINES = ('<div><ul><li><b>Изделия: </b><br><ul><b>Change :</b> труба шатал <ul><li>'
              'Детали : pmk.metal.spec.line(66, 67, 68) ' + ARROW
              + ' pmk.metal.spec.line(66, 67, 68, 69) </li></ul></ul></li></ul></div>')
EMPTY_LINES = ('<div><ul><li><b>Изделия: </b><br><ul><b>New :</b> Секция ограждения ОГ-1 </ul>'
               '<ul><b>Change :</b> Секция ограждения ОГ-1 <ul><li>Детали : pmk.metal.spec.line() '
               + ARROW + ' pmk.metal.spec.line(56, 57, 58, 59) </li></ul></ul></li></ul></div>')
DOBOR_NEW = ('<div><ul><li><b>Доборки: </b><br><ul><b>New :</b> pmk.dobor.order.line,%(new)d </ul>'
             '<ul><b>Change :</b> pmk.dobor.order.line,%(new)d <ul><li>Название доборки : '
             + ARROW + ' Доборка %(n)d </li></ul></ul></li></ul></div>')
DOBOR_DELETE = ('<div><ul><li><b>Доборки: </b><br><ul><b>Delete :</b> pmk.dobor.order.line,%(a)d </ul>'
                '<ul><b>Delete :</b> pmk.dobor.order.line,%(b)d </ul></li></ul></div>')
ENGLISH = ("<b>New :</b>", "<b>Delete :</b>", "<b>Change :</b>", 'title="Changed"',
           "pmk.dobor.order.line", "pmk.metal.spec.line")


def plain(html):
    """Текст без тегов, пробелы схлопнуты."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html))).strip()


@tagged("post_install", "-at_install")
class TestTrackingRuStep30(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Оцинкованный", "thickness_mm": 0.7,
            "gost": "ГОСТ 14918-2020 (тест)", "mass_per_sqm": 5.495})
        cls.Order = cls.env["pmk.dobor.order"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    # ─── помощники ──────────────────────────────────────────────────────
    def _line(self, **values):
        return {"sheet_id": self.sheet.id, "plank_length": 2000.0, "qty": 1, **values}

    def _tm(self):
        if self.env["ir.module.module"]._get("tracking_manager").state != "installed":
            self.skipTest("tracking_manager не установлен")

    def _ru(self):
        """Русский в базе и перевод вендора — как после выкладки."""
        self.env["res.lang"]._activate_lang("ru_RU")
        self.env["ir.module.module"]._load_module_terms(["tracking_manager"], ["ru_RU"], overwrite=True)
        self.env.registry.clear_cache("templates")

    def _track(self, model, names):
        """Своё отслеживание tracking_manager, как на стенде (настройка базы)."""
        ir_model = self.env["ir.model"]._get(model)
        ir_model.active_custom_tracking = True
        fields = ir_model.field_id.filtered(lambda f: f.name in names)
        self.assertEqual(set(fields.mapped("name")), set(names))
        fields.custom_tracking = True

    def _flush(self):
        """Записи истории пишутся перед фиксацией транзакции (precommit)."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _migration(self):
        path = file_path("pmk_calc/migrations/19.0.1.0.4/post-migrate.py")
        spec = importlib.util.spec_from_file_location("pmk_calc_migration_19_0_1_0_4", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.migrate

    # ─── имя позиции доборки ────────────────────────────────────────────
    def test_line_display_name(self):
        order = self.Order.create({"customer": "Тест имени", "line_ids": [
            Command.create(self._line()), Command.create(self._line(title="Конёк"))]})
        auto, named = order.line_ids.sorted("id")
        self.assertEqual(auto.title, "Доборка 1")
        self.assertEqual(auto.display_name, "Доборка 1")
        self.assertEqual(named.display_name, "Конёк")
        auto.title = "  "
        self.assertEqual(auto.display_name, "Доборка без названия")
        for line in order.line_ids:
            self.assertNotIn("pmk.dobor.order.line", line.display_name)

        # Удалённая позиция (доводка): имя запомнено перед удалением — не
        # MissingError; не запомнили (удалили в обход unlink) — слово.
        named.unlink()
        self.assertEqual(named.display_name, "Конёк")
        self.env.cr.precommit.data.pop(DELETED_NAMES)
        self.env.invalidate_all()
        self.assertEqual(named.display_name, "удалённая позиция")

    def test_deleted_product_display_name(self):
        spec = self.Spec.create({"product_ids": [Command.create({"name": "athv", "qty": 1})]})
        product = spec.product_ids
        self.assertEqual(product.display_name, "athv", "имя изделия — название, как у ядра")
        product.unlink()
        self.assertEqual(product.display_name, "athv")
        self.env.cr.precommit.data.pop(DELETED_NAMES)
        self.env.invalidate_all()
        self.assertEqual(product.display_name, "удалённое изделие")

    # ─── правка старых записей ──────────────────────────────────────────
    def test_rewrite_samples(self):
        self.assertEqual(plain(rewrite(DELETE_ATHV, {})), "Изделия: Удалено: athv")
        self.assertIn("Детали : 3 4", plain(rewrite(SPEC_LINES, {})))
        self.assertIn("Детали : 0 4", plain(rewrite(EMPTY_LINES, {})))
        self.assertIn('title="Изменено"', rewrite(SPEC_LINES, {}))
        new = rewrite(DOBOR_NEW % {"new": 20, "n": 5}, {20: "Доборка 5"})
        self.assertEqual(plain(new), "Доборки: Добавлено: Доборка 5 Изменено: Доборка 5 "
                                     "Название доборки : Доборка 5")
        for body in (DELETE_ATHV, SPEC_LINES, EMPTY_LINES, DOBOR_NEW % {"new": 20, "n": 5}):
            out = rewrite(body, {20: "Доборка 5"})
            with self.subTest(body=body[:60]):
                for word in ENGLISH:
                    self.assertNotIn(word, out)
                self.assertEqual(rewrite(out, {20: "Доборка 5"}), out, "повтор ничего не меняет")
        # Название — текст, а не разметка.
        self.assertIn("&lt;b&gt;", rewrite(DOBOR_DELETE % {"a": 7, "b": 8}, {7: "<b>"}))
        # Удалённая позиция без названия в истории — слово, а не номер записи.
        self.assertIn("Удалено: %s" % NO_TITLE, plain(rewrite(DOBOR_DELETE % {"a": 7, "b": 8}, {7: "x"})))
        # Значение отслеживания — простой текст, без экранирования.
        self.assertEqual(rewrite("pmk.dobor.order.line,7, pmk.dobor.order.line,8", {7: "A&B"}, html=False),
                         "A&B, %s" % NO_TITLE)

    def test_created_samples(self):
        """Запись ядра о создании — как ядро пишет по-русски (mail/i18n/ru.po)."""
        self.assertEqual(created_ru("<p>Заказ доборных элементов created</p>"),
                         "<p>Создано: Заказ доборных элементов</p>")
        self.assertEqual(created_ru("<p>ООО &quot;Ромашка&quot; created</p>"),
                         "<p>Создано: ООО &quot;Ромашка&quot;</p>", "экранированное — как было")
        done = "<p>Создано: Заказ доборных элементов</p>"
        self.assertEqual(created_ru(done), done, "повтор ничего не меняет")
        bank = '<p>Bank Account <a href="#" data-oe-model="res.partner.bank" data-oe-id="1">#1</a> created</p>'
        self.assertEqual(created_ru(bank), bank, "запись с разметкой — не запись о создании документа")
        self.assertEqual(created_ru("<p>Отлив created и ещё текст</p>"), "<p>Отлив created и ещё текст</p>")
        self.assertIsNone(created_ru(None))

    def test_titles_from_history(self):
        bodies = [DOBOR_NEW % {"new": 14, "n": 2}, DOBOR_DELETE % {"a": 14, "b": 15},
                  DOBOR_NEW % {"new": 14, "n": 3}]
        self.assertEqual(titles_from_history(bodies), {14: "Доборка 3"}, "последнее название")
        self.assertEqual(dobor_ids(bodies[1]), {14, 15})

    def test_migration(self):
        order = self.Order.create({"customer": "Тест миграции", "line_ids": [
            Command.create(self._line(title="Отлив"))]})
        live = order.line_ids
        gone, nameless = live.id + 1000, live.id + 1001
        Message = self.env["mail.message"].sudo()

        def note(body, message_type="notification"):
            return Message.create({"model": "pmk.dobor.order", "res_id": order.id,
                                   "message_type": message_type, "body": body})

        created = note(DOBOR_NEW % {"new": gone, "n": 7})
        deleted = note(DOBOR_DELETE % {"a": gone, "b": nameless})
        added = note(DOBOR_NEW % {"new": live.id, "n": 1})
        spec_lines = note(SPEC_LINES)
        born = note("<p>Заказ доборных элементов created</p>")
        # Чужой документ: запись о создании не наша, вне шага.
        foreign = Message.create({"model": "res.partner", "res_id": self.env.user.partner_id.id,
                                  "message_type": "notification", "body": "<p>Contact created</p>"})
        letter = note("<p><b>New :</b> письмо клиента про pmk.dobor.order.line,%d</p>" % live.id, "comment")
        field = self.env["ir.model.fields"]._get("pmk.dobor.order", "line_ids")
        value = self.env["mail.tracking.value"].sudo().create({
            "field_id": field.id, "mail_message_id": added.id,
            "old_value_char": "pmk.dobor.order.line,%d" % gone,
            "new_value_char": "pmk.dobor.order.line,%d, pmk.dobor.order.line,%d" % (gone, live.id)})
        letter_body = letter.body
        self.env.flush_all()

        migrate = self._migration()
        migrate(self.env.cr, "19.0.1.0.3")
        self.env.invalidate_all()

        for message in (created, deleted, added, spec_lines):
            with self.subTest(message=message.id):
                for word in ENGLISH:
                    self.assertNotIn(word, str(message.body))
        self.assertIn("Добавлено: Доборка 7", plain(created.body))
        self.assertIn("Удалено: Доборка 7 Удалено: %s" % NO_TITLE, plain(deleted.body),
                      "удалённая позиция — по названию из истории, без него — словом")
        self.assertIn("Добавлено: Отлив Изменено: Отлив", plain(added.body), "живая — название из базы")
        self.assertIn("Детали : 3 4", plain(spec_lines.body))
        self.assertEqual(value.old_value_char, "Доборка 7")
        self.assertEqual(value.new_value_char, "Доборка 7, Отлив")
        self.assertEqual(letter.body, letter_body, "письмо — не запись истории, не трогаем")
        self.assertEqual(str(born.body), "<p>Создано: Заказ доборных элементов</p>")
        self.assertEqual(str(foreign.body), "<p>Contact created</p>", "только документы pmk.*")

        bodies = {m.id: str(m.body) for m in (created, deleted, added, spec_lines, born)}
        migrate(self.env.cr, "19.0.1.0.3")
        self.env.invalidate_all()
        self.assertEqual({m.id: str(m.body) for m in (created, deleted, added, spec_lines, born)}, bodies,
                         "повторный запуск ничего не меняет")

    # ─── перевод шаблона (vendor/tracking_manager/i18n_extra/ru.po) ─────
    def _render(self, lang):
        return str(self.env["ir.qweb"].with_context(lang=lang)._render(
            "tracking_manager.track_o2m_m2m_template", {
                "object": None,
                "lines": [{"name": "Доборки", "messages": [
                    {"mode": "create", "record": "Доборка 1"},
                    {"mode": "unlink", "record": "Конёк"},
                    {"mode": "update", "record": "Отлив",
                     "changes": [{"name": "Количество, шт", "old": 1, "new": 2}]},
                ]}],
            }, minimal_qcontext=True))

    def test_template_russian(self):
        self._tm()
        self._ru()
        ru = self._render("ru_RU")
        for label in ("<b>Добавлено:</b>", "<b>Удалено:</b>", "<b>Изменено:</b>", 'title="Изменено"'):
            with self.subTest(label=label):
                self.assertIn(label, ru)
        self.assertNotIn("New :", ru)
        en = self._render("en_US")
        self.assertIn("<b>New :</b>", en, "английский шаблон — как был (тесты автора на нём)")

    # ─── сквозной путь с правками tracking_manager ──────────────────────
    def test_new_dobor_line_in_history(self):
        self._tm()
        self._ru()
        self._track("pmk.dobor.order", ["line_ids"])
        self._track("pmk.dobor.order.line", ["title", "qty"])
        order = self.Order.with_context(lang="ru_RU").create({"customer": "Тест истории"})
        self._flush()

        before = order.message_ids
        order.with_context(lang="ru_RU").write({"line_ids": [Command.create(self._line(qty=2))]})
        self._flush()
        new = order.message_ids - before
        body = " ".join(str(m.body) for m in new)
        self.assertIn("<b>Добавлено:</b>", body)
        self.assertIn("Доборка 1", body, "имя новой позиции — после «Доборка N», не середина create")
        self.assertNotIn("Название доборки", body, "служебное имя без отметки «Изменено»")
        self.assertNotIn("pmk.dobor.order.line", body)
        values = new.tracking_value_ids.filtered(lambda v: v.field_id.name == "line_ids")
        for value in values:
            self.assertNotIn("pmk.dobor.order.line", value.new_value_char or "")

        before = order.message_ids
        order.line_ids.with_context(lang="ru_RU").write({"qty": 3})
        self._flush()
        body = plain(" ".join(str(m.body) for m in order.message_ids - before))
        self.assertIn("Изменено: Доборка 1", body)
        self.assertIn("Количество, шт : 2 3", body)

    def test_spec_products_in_history(self):
        self._tm()
        self._ru()
        self._track("pmk.metal.spec", ["product_ids"])
        self._track("pmk.metal.spec.product", ["line_ids", "name", "qty"])
        spec = self.Spec.with_context(lang="ru_RU").create({
            "product_ids": [Command.create({"name": "Ферма-тест", "qty": 1})]})
        self._flush()
        product = spec.product_ids

        before = spec.message_ids
        spec.with_context(lang="ru_RU").write({"product_ids": [Command.update(product.id, {
            "line_ids": [Command.create({"calc_mode": "linear", "detail_name": "Стойка",
                                         "length_mm": 3500.0})]})]})
        self._flush()
        body = " ".join(str(m.body) for m in spec.message_ids - before)
        self.assertNotIn("pmk.metal.spec.line", body)
        self.assertIn("Изменено: Ферма-тест Детали : 0 1", plain(body), "состав — числом строк")
        self.assertNotIn("(+", plain(body), "только добавили — разница видна по числам")

        # Заменили деталь (доводка): «1 → 1» читалось как «ничего не
        # поменялось» — теперь с разницей.
        stand = product.line_ids
        before = spec.message_ids
        spec.with_context(lang="ru_RU").write({"product_ids": [Command.update(product.id, {
            "line_ids": [Command.delete(stand.id),
                         Command.create({"calc_mode": "linear", "detail_name": "Раскос",
                                         "length_mm": 1200.0})]})]})
        self._flush()
        self.assertIn("Изменено: Ферма-тест Детали : 1 1 (+1, −1)",
                      plain(" ".join(str(m.body) for m in spec.message_ids - before)))

        before = spec.message_ids
        spec.with_context(lang="ru_RU").write({"product_ids": [Command.delete(product.id)]})
        self._flush()
        self.assertIn("Удалено: Ферма-тест", plain(" ".join(str(m.body) for m in spec.message_ids - before)))

    # ─── доводка: удаление строки не уносит остальные отметки ───────────
    def test_delete_line_keeps_other_tracking(self):
        """ДОБ-…: удалили позицию корзиной и нажали «В работе» в строке
        статусов — ядро сохраняет это одной записью. Имена прежних позиций
        ядро читает уже после удаления; MissingError выбрасывала из ленты
        ВСЕ отметки этого сохранения (статус, клиента, дату)."""
        self._tm()
        self._ru()
        self._track("pmk.dobor.order", ["line_ids", "state", "customer"])
        self._track("pmk.dobor.order.line", ["title", "qty"])
        order = self.Order.with_context(lang="ru_RU").create({"customer": "Тест удаления", "line_ids": [
            Command.create(self._line(title="Отлив")), Command.create(self._line(title="Конёк"))]})
        self._flush()
        gone = order.line_ids.filtered(lambda line: line.title == "Конёк")

        before = order.message_ids
        order.with_context(lang="ru_RU").write({
            "state": "confirmed", "customer": "Тест удаления, изм.",
            "line_ids": [Command.delete(gone.id)]})
        self._flush()
        new = order.message_ids - before
        values = {value.field_id.name: value for value in new.tracking_value_ids}
        self.assertIn("state", values, "статус пропал из ленты: тем же сохранением удалили позицию")
        self.assertEqual(values["state"].new_value_char, "В работе")
        self.assertIn("customer", values)
        self.assertEqual(values["line_ids"].old_value_char, "Отлив, Конёк", "удалённая — по названию")
        self.assertEqual(values["line_ids"].new_value_char, "Отлив")
        self.assertIn("Удалено: Конёк", plain(" ".join(str(m.body) for m in new)))

    def test_delete_product_keeps_other_tracking(self):
        """То же в расчёте (СМ-00024, 01.10.2026): удалили изделие и тем же
        сохранением поменяли «Предмет КП» — в ленте была только «Удалено: …»."""
        self._tm()
        self._ru()
        self._track("pmk.metal.spec", ["product_ids", "note"])
        spec = self.Spec.with_context(lang="ru_RU").create({"product_ids": [
            Command.create({"name": "Ферма-тест", "qty": 1}), Command.create({"name": "athv", "qty": 1})]})
        self._flush()
        gone = spec.product_ids.filtered(lambda product: product.name == "athv")

        before = spec.message_ids
        spec.with_context(lang="ru_RU").write({
            "note": "Ферма для склада", "product_ids": [Command.delete(gone.id)]})
        self._flush()
        new = spec.message_ids - before
        values = {value.field_id.name: value for value in new.tracking_value_ids}
        self.assertIn("note", values, "«Предмет КП» пропал из ленты: тем же сохранением удалили изделие")
        self.assertEqual(values["product_ids"].old_value_char, "Ферма-тест, athv")
        self.assertEqual(values["product_ids"].new_value_char, "Ферма-тест")
        self.assertIn("Удалено: athv", plain(" ".join(str(m.body) for m in new)))

    # ─── доводка: язык записи истории ───────────────────────────────────
    def test_history_language_without_context(self):
        """Скрипт без языка в контексте (odoo shell, миграция — OdooBot) писал
        «New :» и в русской базе (ДОБ-00007, 2189–2192). Теперь — язык базы
        по умолчанию; язык, переданный явно, — как был."""
        self._tm()
        self._ru()
        self.env["ir.default"].set("res.partner", "lang", "ru_RU")
        self._track("pmk.dobor.order", ["line_ids"])
        order = self.Order.create({"customer": "Тест языка"})
        self._flush()

        before = order.message_ids
        order.with_context(lang=False).write({"line_ids": [Command.create(self._line(title="Отлив"))]})
        self._flush()
        body = " ".join(str(m.body) for m in order.message_ids - before)
        self.assertIn("<b>Добавлено:</b>", body)
        self.assertNotIn("New :", body)

        before = order.message_ids
        order.with_context(lang="en_US").write({"line_ids": [Command.create(self._line(title="Конёк"))]})
        self._flush()
        body = " ".join(str(m.body) for m in order.message_ids - before)
        self.assertIn("<b>New :</b>", body, "язык, переданный явно, — как был")
