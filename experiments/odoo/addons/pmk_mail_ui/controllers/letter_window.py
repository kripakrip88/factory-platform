# -*- coding: utf-8 -*-
"""Письмо в отдельном окне — кнопка вкладки «Письма» сделки (15.10.2026).

Антон 15.10: «иметь возможность открыть письмо в отдельном окне из сделки» —
письмо рядом со сделкой, без переключения. Лёгкая страница без Odoo-клиента:
шапка письма, вложения ссылками, текст.

Текст — то же, что в окне почты (get_message_detail: права на письмо, тело
очищено на отдаче, картинки «к нам» заглушены) и так же в рамке sandbox без
скриптов (mail_client, message_card.js). Сама страница — тоже без скриптов
(CSP script-src 'none'): чужому HTML исполнять нечего ни в рамке, ни вокруг.
"""
from markupsafe import Markup, escape

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request
from odoo.tools.misc import format_datetime

CSP = ("default-src 'none'; script-src 'none'; style-src 'unsafe-inline' *; "
       "img-src * data: blob:; font-src * data:; frame-src 'self' about:; "
       "form-action 'none'; frame-ancestors 'self'")

CLIP = Markup('<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              'stroke-width="2" aria-hidden="true"><path d="M21 12.5l-8.5 8.5a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 '
              '5.7 5.7l-9 9a2 2 0 0 1-2.8-2.8l8.3-8.3"/></svg>')

PAGE = Markup("""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>%(title)s</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
html, body { height: 100%%; margin: 0; }
body { display: flex; flex-direction: column; background: #f4f1ea; color: #1f2328;
       font: 13px/1.45 Inter, "Segoe UI", Roboto, Arial, sans-serif; }
header { padding: 14px 18px 10px; background: #fff; border-bottom: 1px solid #e3ded3; }
h1 { margin: 0 0 6px; font-size: 17px; font-weight: 600; }
.meta { color: #59636e; display: grid; grid-template-columns: max-content 1fr; gap: 2px 10px; }
.meta b { font-weight: 500; color: #1f2328; }
.files { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.files a { display: inline-flex; gap: 6px; align-items: center; padding: 4px 10px; border: 1px solid #e3ded3;
           border-radius: 10px; background: #faf8f4; color: #1f2328; text-decoration: none; }
.files a:hover { border-color: #b9b2a3; }
.files small { color: #8a8f96; }
main { flex: 1 1 auto; padding: 12px 18px 18px; min-height: 0; }
iframe { width: 100%%; height: 100%%; min-height: 300px; border: 1px solid #e3ded3; border-radius: 10px;
         background: #fff; }
.empty { color: #8a8f96; padding: 20px; }
</style></head>
<body>
<header>
  <h1>%(subject)s</h1>
  <div class="meta">
    <span>От:</span><b>%(email_from)s</b>
    <span>Кому:</span><span>%(email_to)s</span>
    %(cc)s
    <span>Дата:</span><span>%(date)s</span>
  </div>
  %(files)s
</header>
<main>%(body)s</main>
</body></html>""")


def _size(value):
    value = value or 0
    if value >= 1024 * 1024:
        return "%.1f МБ" % (value / 1024 / 1024)
    if value >= 1024:
        return "%d КБ" % round(value / 1024)
    return "%d Б" % value


class PmkLetterWindow(http.Controller):

    @http.route("/pmk_mail/letter/<int:message_id>", type="http", auth="user", methods=["GET"])
    def letter(self, message_id, **kwargs):
        try:
            detail = request.env["mail.client.message"].get_message_detail(message_id)
        except (AccessError, MissingError, UserError):
            return request.not_found()
        files = [
            Markup('<a href="/mail_client/attachment/%d/raw" target="_blank" rel="noopener">'
                   '%s %s <small>%s</small></a>') % (item["id"], CLIP, item["name"] or "файл", _size(item.get("size")))
            for item in detail.get("attachments") or []
        ]
        body = detail.get("body") or ""
        if body:
            frame = Markup('<iframe sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" '
                           'srcdoc="%s" title="Текст письма"></iframe>') % escape(str(body))
        else:
            frame = Markup('<p class="empty">Текста нет или он ещё не загрузился с почты.</p>')
        date = detail.get("date")
        page = PAGE % {
            "title": detail.get("subject") or "Письмо",
            "subject": detail.get("subject") or "(без темы)",
            "email_from": detail.get("email_from") or "",
            "email_to": detail.get("email_to") or "",
            "cc": (Markup("<span>Копия:</span><span>%s</span>") % detail["email_cc"]) if detail.get("email_cc") else "",
            "date": format_datetime(request.env, date, dt_format="dd.MM.yyyy HH:mm") if date else "",
            "files": Markup('<div class="files">%s</div>') % Markup("").join(files) if files else "",
            "body": frame,
        }
        return request.make_response(str(page), headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Security-Policy", CSP),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Cache-Control", "private, max-age=0, no-store"),
        ])
