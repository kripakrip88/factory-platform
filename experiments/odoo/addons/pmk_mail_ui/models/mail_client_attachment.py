# -*- coding: utf-8 -*-
from odoo import fields, models


class MailClientAttachment(models.Model):
    """Картинки, вставленные в текст письма (подпись, логотип, скриншот).

    Такая картинка приходит отдельной частью письма со своим Content-ID, а
    текст ссылается на неё как `<img src="cid:image001.png@01DD…">`. Модуль
    почты этот номер не запоминал, поэтому в окне письма на её месте была
    пустая рамка, а сама картинка — в лучшем случае вложением внизу, чаще
    нигде (разбор UX, шаг 12, 29.09.2026).
    """

    _inherit = "mail.client.attachment"

    pmk_content_id = fields.Char(
        "Content-ID", index="btree_not_null", readonly=True,
        help="Номер, по которому текст письма ссылается на эту часть (cid:).")
    # Часть, которую модуль почты вложением не считал и строки для неё не
    # заводил: её место в тексте письма, а не в списке вложений.
    pmk_inline = fields.Boolean("Картинка в тексте", readonly=True)
