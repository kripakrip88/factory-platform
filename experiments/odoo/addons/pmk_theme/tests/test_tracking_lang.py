# -*- coding: utf-8 -*-
"""История: этапы и значения списков — на языке смотрящего (12.10.2026).

Антон: «что за надписи на английском?» — «Pending → Won», «Quote sent → Won».
В истории хранится готовый текст на языке того, кто менял (служебный скрипт
— по-английски); показ берёт этап по коду, значение списка — по метке.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrackingLang(TransactionCase):

    def _tracking(self, lead, field_name, **vals):
        field = self.env["ir.model.fields"]._get("crm.lead", field_name)
        message = lead.message_post(body="", message_type="notification")
        return self.env["mail.tracking.value"].sudo().create(dict(
            {"field_id": field.id, "mail_message_id": message.id}, **vals))

    def test_many2one_by_id_not_by_stored_text(self):
        lead = self.env["crm.lead"].create({"name": "Проверка языка истории", "type": "opportunity"})
        stages = self.env["crm.stage"].search([], limit=2)
        self.assertEqual(len(stages), 2)
        track = self._tracking(lead, "stage_id",
                               old_value_integer=stages[0].id, old_value_char="Quote sent",
                               new_value_integer=stages[1].id, new_value_char="Won")
        item = track._tracking_value_format_model("crm.lead")[0]
        self.assertEqual(item["oldValue"], stages[0].display_name)
        self.assertEqual(item["newValue"], stages[1].display_name)

    def test_many2one_deleted_record_keeps_text(self):
        lead = self.env["crm.lead"].create({"name": "Проверка языка истории", "type": "opportunity"})
        track = self._tracking(lead, "stage_id", old_value_integer=999999, old_value_char="Old stage",
                               new_value_integer=0, new_value_char="")
        item = track._tracking_value_format_model("crm.lead")[0]
        self.assertEqual(item["oldValue"], "Old stage")

    def test_selection_english_text_to_user_label(self):
        lead = self.env["crm.lead"].create({"name": "Проверка языка истории", "type": "opportunity"})
        field = self.env["crm.lead"]._fields["won_status"]
        en = dict(field._description_selection(self.env(context=dict(self.env.context, lang="en_US"))))
        here = dict(field._description_selection(self.env))
        track = self._tracking(lead, "won_status",
                               old_value_char=en["pending"], new_value_char=en["won"])
        item = track._tracking_value_format_model("crm.lead")[0]
        self.assertEqual(item["oldValue"], here["pending"])
        self.assertEqual(item["newValue"], here["won"])

    def test_unknown_text_kept(self):
        lead = self.env["crm.lead"].create({"name": "Проверка языка истории", "type": "opportunity"})
        track = self._tracking(lead, "won_status", old_value_char="что-то своё", new_value_char="")
        item = track._tracking_value_format_model("crm.lead")[0]
        self.assertEqual(item["oldValue"], "что-то своё")
