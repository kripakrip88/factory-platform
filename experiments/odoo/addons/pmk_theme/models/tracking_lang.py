# -*- coding: utf-8 -*-
"""История: значения этапов и списков — на языке того, кто смотрит.

Антон 12.10.2026 в окне «История»: «что за надписи на английском?» —
«Pending → Won», «Quote sent → Won». Причина: mail.tracking.value хранит
ГОТОВЫЙ текст значения (old/new_value_char) на языке того, кто менял запись;
служебные скрипты (odoo shell без языка, крон) пишут по-английски.

Показ исправляем, не трогая сохранённое (и старые записи сразу по-русски):
  • many2one (этап, ответственный…) — по коду записи (old/new_value_integer)
    берём её название на языке смотрящего; записи больше нет — текст как был;
  • selection («Выиграно/проиграно» и т.п.) — сохранённый текст сверяем с
    метками списка на всех включённых языках, находим ключ и показываем
    метку на языке смотрящего; не нашли — текст как был.
Остальные типы (числа, деньги, даты, текст) языка не имеют — без изменений.
"""
from odoo import models


class MailTrackingValueLang(models.Model):
    _inherit = "mail.tracking.value"

    def _tracking_value_format_model(self, model):
        formatted = super()._tracking_value_format_model(model)
        if not formatted or not model or model not in self.env:
            return formatted
        by_id = {tracking.id: tracking for tracking in self}
        Model = self.env[model]
        langs = None
        for item in formatted:
            tracking = by_id.get(item.get("id"))
            ftype = item.get("fieldInfo", {}).get("fieldType")
            if not tracking or not tracking.field_id or ftype not in ("many2one", "selection"):
                continue
            field = Model._fields.get(tracking.field_id.name)
            if not field:
                continue
            if ftype == "many2one" and field.comodel_name in self.env:
                Comodel = self.env[field.comodel_name].sudo()
                for key, rec_id in (("oldValue", tracking.old_value_integer),
                                    ("newValue", tracking.new_value_integer)):
                    if rec_id:
                        rec = Comodel.browse(rec_id).exists()
                        if rec:
                            item[key] = rec.display_name
            elif ftype == "selection":
                if langs is None:
                    langs = [code for code, _name in self.env["res.lang"].get_installed()]
                to_key = {}
                for lang in langs:
                    for key, label in field._description_selection(self.env(context=dict(self.env.context, lang=lang))) or []:
                        to_key.setdefault(label, key)
                labels = dict(field._description_selection(self.env) or [])
                for key in ("oldValue", "newValue"):
                    text = item.get(key)
                    sel = to_key.get(text) if text else None
                    if sel is not None and sel in labels:
                        item[key] = labels[sel]
        return formatted
