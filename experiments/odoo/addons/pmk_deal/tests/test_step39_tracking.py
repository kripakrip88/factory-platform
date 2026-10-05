# -*- coding: utf-8 -*-
"""Старая история сделок словами завода (разбор UX, шаг 39), pmk_deal.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
    odoo -d pmk_deal_test -i pmk_deal --test-enable \\
         --test-tags /pmk_deal:TestStep39Tracking --stop-after-init --http-port 8099

Что проверяем (hooks.tracking_words_ru — готовая замена старой истории; на боевой запускается только по слову Антона): значения
«Выиграно/проиграно» и «Тип» в истории сделки — «В работе», «Проиграно»,
«Выиграно», «Сделка», «Лид» вместо «Pending / Ожидает», «Lost / Потерян»,
«Won», «Возможность / Opportunity», «Lead» — как на боевой базе («Pending →
Lost» ×7, «Ожидает → Выиграно», «Лид → Возможность» ×2); чужие поля и
модели, своё слово — не трогаются; повтор ничего не меняет.
"""
import importlib.util

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.pmk_deal.hooks import TRACKING_WORDS, tracking_words_ru


@tagged("post_install", "-at_install")
class TestStep39Tracking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env["crm.lead"].create({"name": "История 39", "type": "opportunity"})
        cls.partner = cls.env["res.partner"].create({"name": "Не сделка 39"})

    def _value(self, record, fname, old, new):
        message = self.env["mail.message"].create({
            "model": record._name, "res_id": record.id, "message_type": "notification", "body": ""})
        field = self.env["ir.model.fields"]._get(record._name, fname)
        return self.env["mail.tracking.value"].sudo().create({
            "mail_message_id": message.id, "field_id": field.id,
            "old_value_char": old, "new_value_char": new})

    def _pair(self, value):
        value.invalidate_recordset(["old_value_char", "new_value_char"])
        return value.old_value_char, value.new_value_char

    def test_words(self):
        script = self._value(self.lead, "won_status", "Pending", "Lost")
        person = self._value(self.lead, "won_status", "Ожидает", "Выиграно")
        kind = self._value(self.lead, "type", "Лид", "Возможность")
        english = self._value(self.lead, "type", "Lead", "Opportunity")
        own = self._value(self.lead, "won_status", "Своё слово", "Потерян")
        stage = self._value(self.lead, "name", "Lost", "Возможность")
        foreign = self._value(self.partner, "name", "Pending", "Lost")
        self.env.flush_all()

        changed = tracking_words_ru(self.env)
        self.assertEqual(self._pair(script), ("В работе", "Проиграно"))
        self.assertEqual(self._pair(person), ("В работе", "Выиграно"))
        self.assertEqual(self._pair(kind), ("Лид", "Сделка"))
        self.assertEqual(self._pair(english), ("Лид", "Сделка"))
        self.assertEqual(self._pair(own), ("Своё слово", "Проиграно"), "Своё слово цело.")
        self.assertEqual(self._pair(stage), ("Lost", "Возможность"), "Другое поле сделки — как было.")
        self.assertEqual(self._pair(foreign), ("Pending", "Lost"), "Другая модель — как была.")
        # script 2 + person 1 + kind 1 + english 2 + own 1; на копии боевой
        # базы — и её 10 старых значений.
        self.assertGreaterEqual(changed, 7)
        self.assertEqual(tracking_words_ru(self.env), 0, "Повтор ничего не меняет.")

    def test_words_match_labels(self):
        """Новые слова — те же, что подписи списков сделки (файл слов темы)."""
        if self.env["ir.module.module"]._get("pmk_theme").state != "installed":
            self.skipTest("pmk_theme")
        self.env["res.lang"]._activate_lang("ru_RU")
        # Штатный перевод crm и слова темы поверх — как -u crm на стенде.
        self.env["ir.module.module"]._load_module_terms(["crm", "pmk_theme"], ["ru_RU"])
        self.env.registry.clear_cache("stable")
        Lead = self.env["crm.lead"].with_context(lang="ru_RU")
        for fname, words in TRACKING_WORDS.items():
            labels = set(dict(Lead.fields_get([fname], ["selection"])[fname]["selection"]).values())
            with self.subTest(field=fname):
                self.assertLessEqual(set(words.values()), labels)

