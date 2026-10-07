# -*- coding: utf-8 -*-
"""«Product created» в ленте товара — по-русски (разбор UX, шаг 53).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Ловим:
  • английские записи ядра о создании шаблона и варианта товара становятся
    «Создано: Товар» / «Создано: Вариант товара» (как пишет ядро по-русски);
  • число изменённых записей возвращается по моделям;
  • повторный вызов ничего не меняет (0 записей);
  • чужое не трогается: «Contact created», «Product created» у контрагента,
    комментарий с тем же текстом, запись с разметкой вокруг.
"""
from odoo.tests import TransactionCase, tagged
from odoo.tools.translate import code_translations

from odoo.addons.pmk_bridge.tools.product_created_ru import translate_product_created


@tagged("post_install", "-at_install")
class TestProductCreatedRu(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Имена моделей по-русски — как на боевой базе. На свежей базе без
        # загруженного перевода их может не быть: кладём штатные слова ядра
        # (product/i18n/ru.po), только если русского имени нет.
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.env.flush_all()
        for model, ru in (("product.template", "Товар"), ("product.product", "Вариант товара")):
            cls.env.cr.execute(
                "UPDATE ir_model SET name = name || jsonb_build_object('ru_RU', %s::text)"
                " WHERE model = %s AND NOT (name ? 'ru_RU')", [ru, model])
        cls.template =cls.env["product.template"].create({"name": "Лист 53 (тест)"})
        cls.variant = cls.template.product_variant_id
        cls.partner = cls.env["res.partner"].create({"name": "Контрагент 53 (тест)"})

    def _message(self, record, body, message_type="notification"):
        return self.env["mail.message"].create({
            "model": record._name, "res_id": record.id,
            "message_type": message_type, "body": body,
        })

    def _body(self, message):
        self.env.flush_all()
        message.invalidate_recordset(["body"])
        return str(message.body)

    def test_translate_once(self):
        template_msg = self._message(self.template, "<p>Product created</p>")
        variant_msg = self._message(self.variant, "<p>Product Variant created</p>")
        self.env.flush_all()
        changed = translate_product_created(self.env.cr)
        # Не меньше двух: ядро само могло записать создание товара из
        # setUpClass по-английски (контекст без языка) — и это наш случай.
        self.assertGreaterEqual(changed.get("product.template", 0), 1)
        self.assertGreaterEqual(changed.get("product.product", 0), 1)
        self.assertEqual(self._body(template_msg), "<p>Создано: Товар</p>")
        self.assertEqual(self._body(variant_msg), "<p>Создано: Вариант товара</p>")
        again = translate_product_created(self.env.cr)
        self.assertEqual(sum(again.values()), 0, "Повторный запуск ничего не меняет.")
        self.assertEqual(self._body(template_msg), "<p>Создано: Товар</p>")
        left = self.env["mail.message"].search_count([
            ("model", "in", ["product.template", "product.product"]),
            ("body", "in", ["<p>Product created</p>", "<p>Product Variant created</p>"]),
        ])
        self.assertEqual(left, 0, "Английских записей о создании товара не осталось.")

    def test_others_untouched(self):
        others = [
            self._message(self.partner, "<p>Contact created</p>"),
            self._message(self.partner, "<p>Product created</p>"),
            self._message(self.template, "<p>Product created</p>", message_type="comment"),
            self._message(self.template, "<p>Product created</p><p>и ещё строка</p>"),
        ]
        before = [self._body(message) for message in others]
        translate_product_created(self.env.cr)
        self.assertEqual([self._body(message) for message in others], before)

    def test_matches_core_wording(self):
        """Ядро по-русски пишет «Создано: %s» (mail/i18n/ru.po) — замена та же."""
        words = code_translations.get_python_translations("mail", "ru_RU")
        if "%s created" not in words:
            self.skipTest("Нет русского перевода mail в этой сборке.")
        self.assertEqual(words["%s created"], "Создано: %s")
        names = self.env["ir.model"].with_context(lang="ru_RU").search(
            [("model", "in", ["product.template", "product.product"])]).mapped("name")
        if "Товар" in names:
            self.assertIn("Вариант товара", names)
