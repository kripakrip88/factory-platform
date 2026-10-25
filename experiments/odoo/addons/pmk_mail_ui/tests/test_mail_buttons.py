# -*- coding: utf-8 -*-
"""Почта проще (25.10.2026): меньше кнопок, ни одна не потерялась.

Антон: «очень много кнопок, в которых путаешься». Прототип в чате → «делай везде».
Здесь — что разметка такая, как договорились, и что действия и клавиши живы:
  • верхняя строка: «Написать», поиск с «Фильтр ▾», кружки «Непрочитанные» и
    «Ждут ответа», меню вида ⚙ (переписками, раскладка, папки, проверить почту);
  • строка над письмом: «←», тема, «В работу ▾», ☆, «⋯» — без «Ответить / Всем /
    Переслать», ↑ ↓ и ⤢;
  • «Ответить / Всем / Переслать» — в строке ответа, с клавишами R / A / F;
  • «Лид» — только в «В работу ▾» (не у строки списка и не в карточке справа).
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

ACTION_XML = "mail_client/static/src/mail_client_action.xml"
READING_XML = "mail_client/static/src/panes/reading_pane.xml"
OURS = "pmk_mail_ui/static/src/xml/"


def _tree(path):
    with file_open(path, "rb") as f:
        return etree.fromstring(f.read())


def _template(path, name):
    return _tree(path).find("t[@t-name='%s']" % name)


def _has_class(cls):
    return "contains(concat(' ', @class, ' '), ' %s ')" % cls


@tagged("post_install", "-at_install")
class TestMailButtons(TransactionCase):

    def test_topbar(self):
        inbox = _template(ACTION_XML, "mail_client.Inbox")
        topbar = inbox.xpath(".//div[%s]" % _has_class("o_mail_client_topbar"))[0]
        chips = topbar.xpath(".//div[%s]" % _has_class("o_mail_client_chips"))[0]
        # Кружки — только закреплённые (chipFilters), без «Все».
        self.assertEqual(chips.xpath(".//button/@t-foreach"), ["chipFilters"])
        self.assertNotIn(">All<", etree.tostring(chips, encoding="unicode"))
        # Все фильтры — в меню у поиска, вид и проверка почты — в ⚙.
        search = topbar.xpath(".//div[%s]" % _has_class("o_mail_client_search"))[0]
        self.assertTrue(search.xpath(".//*[@t-foreach='menuFilters']"))
        view = topbar.xpath(".//button[%s]" % _has_class("o_mail_client_view_toggle"))
        self.assertEqual(len(view), 1)
        menu = etree.tostring(view[0].getparent(), encoding="unicode")
        for call in ("toggleThreaded()", "toggleReaderLayout()", "toggleFolders()", "syncNow()"):
            self.assertIn(call, menu)
        # Кнопка папок в строке — только на телефоне.
        folders = topbar.xpath(".//button[%s]" % _has_class("o_mail_client_folders_toggle"))[0]
        self.assertEqual(folders.get("t-if"), "isPhone")

    def test_reading_toolbar_and_reply_bar(self):
        pane = _template(READING_XML, "mail_client.ReadingPane")
        toolbar = pane.xpath(".//div[%s]" % _has_class("o_mail_client_toolbar"))[0]
        self.assertFalse(toolbar.xpath(".//*[@data-mc-key]"), "ответы — не в строке над письмом")
        for gone in ("o_mail_client_prev", "o_mail_client_next", "o_mail_client_layout_toggle"):
            self.assertFalse(toolbar.xpath(".//*[%s]" % _has_class(gone)), gone)
        # Якорь «В работу» pmk_mail_ui — один разделитель.
        self.assertEqual(len(toolbar.xpath("./div[%s]" % _has_class("vr"))), 1)
        bar = pane.xpath(".//div[%s]" % _has_class("o_mail_client_reply_bar"))[0]
        self.assertEqual(sorted(bar.xpath(".//button/@data-mc-key")), ["a", "f", "r"])

    def test_work_menu_is_the_only_lead(self):
        ours = _tree(OURS + "reading_pane.xml")
        menu = ours.xpath("//Dropdown[.//button[%s]]" % _has_class("pmk-mail-lead"))
        self.assertEqual(len(menu), 1)
        text = etree.tostring(menu[0], encoding="unicode")
        for item in ("Лид из письма", "Привязать к сделке", "Создать контрагента", "Открыть контрагента"):
            self.assertIn(item, text)
        # Клавиша L — на кнопке меню.
        step41 = etree.tostring(_tree(OURS + "step41_mail.xml"), encoding="unicode")
        self.assertIn("hasclass('pmk-mail-lead')", step41)
        self.assertNotIn("pmk-mail-row-lead", step41, "значок «Лид» у строки списка убран")
        card = etree.tostring(_tree(OURS + "partner_card.xml"), encoding="unicode")
        self.assertNotIn("pmk-pcard__actions", card, "действия карточки — в «В работу ▾»")
