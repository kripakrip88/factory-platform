# -*- coding: utf-8 -*-
"""«Возможность» → «Сделка» — разбор UX, шаг 53 (приёмка 07.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), вместе с шагом 39:
  odoo -d pmk53_test -i pmk_theme,pmk_purchase,pmk_deal --test-enable \
       --test-tags /pmk_theme:TestStep53Words,/pmk_theme:TestStep39Words \
       --stop-after-init --http-port 8099

Что ловим:
  • поле «Сделка» у КП и заказа (sale_crm, opportunity_id) — подпись и в
    поиске КП, открытых со сделки (плашка фильтра), и в группировках;
  • форма стадии и поиск отчёта по задачам — без «возможности»;
  • строки кода: тур воронки (браузер) и предупреждение о стадии выигрыша
    (Python) — «сделка»;
  • подписи, подсказки и значения списков у сделки, стадии, команды продаж,
    отчёта по задачам и поля КП — без «возможности», кроме «Возможность
    допродажи» (sale: допродажа — другое понятие, шаг не трогает).
Файлы слов целиком (ссылки, термины видов, совпадение с ядром) проверяют
test_words_files и test_words_still_match_core шага 39 — новые записи
попадают в них сами.

Глазами (сделка → «КП» → плашка поиска; Настройки CRM; стадия воронки) —
основной агент на копии.
"""
import re

from lxml import etree

from odoo.tests import tagged
from odoo.tools.translate import get_translation

from odoo.addons.pmk_theme.models.words import LANG, words_modules
from odoo.addons.pmk_theme.tests.test_step39_words import Step39Common, read_words, visible_texts

OLD = re.compile(r"озможност", re.I)
# Допродажа — другое понятие (sale, invoice_status = upselling).
ALLOWED = ("Возможность допродажи",)
MODELS = ("crm.lead", "crm.stage", "crm.team", "crm.activity.report")


def old(text):
    text = str(text or "")
    for allowed in ALLOWED:
        text = text.replace(allowed, "")
    return OLD.findall(text)


@tagged("post_install", "-at_install")
class TestStep53Words(Step39Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Module._pmk_apply_words()

    def test_sale_crm_words_file(self):
        self.assertIn("sale_crm", words_modules())
        rows = read_words("sale_crm")
        self.assertEqual([(row["src"], row["value"]) for row in rows], [("Opportunity", "Сделка")])

    def test_quotation_deal_field(self):
        if not self._installed("sale_crm"):
            self.skipTest("sale_crm не установлен")
        self.assertEqual(self._label("sale.order", "opportunity_id"), "Сделка")

    def test_views_without_old_word(self):
        for model, xmlid in (("crm.stage", "crm.crm_stage_form"),
                             ("crm.activity.report", "crm.crm_activity_report_view_search")):
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view:
                continue
            arch = view.with_context(lang=LANG).arch_db
            for text in visible_texts(etree.fromstring(arch)):
                with self.subTest(view=xmlid, text=text[:60]):
                    self.assertFalse(old(text), text)
        stage = self.env.ref("crm.crm_stage_form").with_context(lang=LANG).arch_db
        self.assertIn("перехода сделки на эту стадию", stage)
        report = self.env.ref("crm.crm_activity_report_view_search").with_context(lang=LANG).arch_db
        self.assertIn("Показать только сделки", report)

    TOUR = (
        "<b>Create your first opportunity.</b>",
        "<b>Drag &amp; drop opportunities</b> between columns as you progress in your sales cycle.",
        "Drag your opportunity to <b>Won</b> when you get the deal. Congrats!",
        "Let’s have a look at an Opportunity.",
        "Now, <b>add your Opportunity</b> to your Pipeline.",
        "You can make your opportunity advance through your pipeline from here.",
    )
    WON_STAGE = ("Changing the value of 'Is Won Stage' may induce a large number of operations, "
                 "as the probabilities of opportunities in this stage will be recomputed on saving.")

    def test_code_strings_web(self):
        """Тур воронки — в браузере (перевод для веб-клиента, как шаг 39)."""
        translations, _params = self.env["ir.http"]._get_translations_for_webclient(["crm"], LANG)
        crm = {m["id"]: m["string"] for m in translations["crm"]["messages"]}
        for src in self.TOUR:
            with self.subTest(src=src[:40]):
                self.assertIn(src, crm, "Строка тура есть в переводе crm.")
                self.assertFalse(old(crm[src]), crm[src])
                self.assertIn("сделк", crm[src])

    def test_code_strings_python(self):
        self.assertEqual(get_translation("crm", LANG, self.WON_STAGE, ()),
                         "Смена поля «Стадия выигрыша» может занять время: при сохранении "
                         "пересчитается вероятность всех сделок на этой стадии.")
        self.assertEqual(get_translation("crm", "en_US", self.WON_STAGE, ()), self.WON_STAGE,
                         "Английский не тронут.")

    def test_labels_help_and_choices(self):
        targets = [(model, None) for model in MODELS if model in self.env]
        if "sale.order" in self.env and "opportunity_id" in self.env["sale.order"]._fields:
            targets.append(("sale.order", ["opportunity_id"]))
        for model, names in targets:
            info = self.ru[model].fields_get(names, ["string", "help", "selection"])
            for fname, desc in info.items():
                texts = [desc.get("string"), desc.get("help")]
                texts += [label for _value, label in desc.get("selection") or []]
                for text in texts:
                    with self.subTest(model=model, field=fname, text=str(text)[:60]):
                        self.assertFalse(old(text), text)
