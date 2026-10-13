# -*- coding: utf-8 -*-
"""Листалка картинок в одном сообщении бота (14.10.2026).

Зачем. У Телеграма к альбому из нескольких картинок нельзя прикрепить кнопки,
а у сообщения с кнопками — только одна картинка. Задание оператору лазера —
это несколько раскладок листа И кнопки «Взял / Пауза / Закончил». Решение:
в сообщении одна картинка, кнопки «◀ 3/7 ▶» меняют её прямо в сообщении
(editMessageMedia), подпись и кнопки задания остаются.

Картинки лежат вложениями записи. Первый показ каждой загружается файлом,
Телеграм возвращает её file_id — дальше листается по нему, без повторной
загрузки.

Отправка: env["pmk.telegram.carousel"].pmk_send(chat_id, [(имя, байты)…],
caption, extra_rows) — extra_rows — ряды своих кнопок под листалкой.
"""
import json

from odoo import api, fields, models

CB = "car:"


class PmkTelegramCarousel(models.Model):
    _name = "pmk.telegram.carousel"
    _description = "Листалка картинок в Телеграме"

    chat_id = fields.Char(required=True)
    message_id = fields.Integer()
    caption = fields.Text(help="Подпись (HTML), одна на все картинки.")
    slide_ids = fields.Many2many("ir.attachment", string="Картинки")
    file_ids = fields.Text(default="{}", help="Номер картинки → file_id Телеграма.")
    extra_rows = fields.Text(default="[]", help="Свои ряды кнопок под листалкой (JSON).")
    index = fields.Integer(default=0)

    # ── отправка ─────────────────────────────────────────────────────────

    @api.model
    def pmk_send(self, chat_id, images, caption="", extra_rows=None, thread_id=None):
        """Отправить листалку. images — [(имя, байты)]. Вернёт запись или False."""
        if not images:
            return False
        bot = self.env["pmk.telegram.bot"]
        api_ = bot._pmk_api()
        if not api_:
            return False
        slides = self.env["ir.attachment"].sudo().create([{
            "name": name, "raw": raw, "res_model": self._name,
        } for name, raw in images])
        rec = self.sudo().create({
            "chat_id": str(chat_id), "caption": caption, "slide_ids": [(6, 0, slides.ids)],
            "extra_rows": json.dumps(extra_rows or [], ensure_ascii=False),
        })
        slides.write({"res_id": rec.id})
        res = api_.send_photo(chat_id, rec._pmk_photo(0), caption, rec._pmk_markup(),
                              thread_id=thread_id)
        if not res:
            return False
        rec._pmk_remember(0, res)
        rec.message_id = res.get("message_id")
        return rec

    # ── листание ─────────────────────────────────────────────────────────

    def pmk_show(self, api_, index):
        self.ensure_one()
        n = len(self.slide_ids)
        index %= n
        res = api_.edit_photo(self.chat_id, self.message_id, self._pmk_photo(index),
                              self.caption, self._pmk_markup(index))
        if res:
            self._pmk_remember(index, res)
            self.index = index
        return bool(res)

    # ── устройство ───────────────────────────────────────────────────────

    def _pmk_slides(self):
        return self.slide_ids.sorted("id")

    def _pmk_photo(self, index):
        """file_id, если картинку уже загружали, иначе (имя, байты) — загрузить."""
        known = json.loads(self.file_ids or "{}")
        if str(index) in known:
            return known[str(index)]
        slide = self._pmk_slides()[index]
        return (slide.name, slide.raw)

    def _pmk_remember(self, index, message):
        sizes = (message or {}).get("photo") or []
        if not sizes:
            return
        known = json.loads(self.file_ids or "{}")
        known[str(index)] = max(sizes, key=lambda p: p.get("file_size") or 0)["file_id"]
        self.file_ids = json.dumps(known)

    def _pmk_markup(self, index=0):
        n = len(self.slide_ids)
        rows = []
        if n > 1:
            rows.append([
                {"text": "◀", "callback_data": f"{CB}{self.id}:{(index - 1) % n}"},
                {"text": f"{index + 1} / {n}", "callback_data": f"{CB}{self.id}:{index}"},
                {"text": "▶", "callback_data": f"{CB}{self.id}:{(index + 1) % n}"},
            ])
        rows += json.loads(self.extra_rows or "[]")
        return {"inline_keyboard": rows}
