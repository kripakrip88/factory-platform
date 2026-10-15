# -*- coding: utf-8 -*-
"""Подписка окна почты на шину снимается при закрытии окна (15.10.2026).

UncaughtPromiseError «Component is destroyed» на боевом: окно почты
подписывалось на «mail_client.sync» и не отписывалось. Шина живёт всю сессию,
и синхронизация ящика после ухода из почты звала закрытое окно. Сторож: у
каждой подписки окна на шину есть отписка в onWillDestroy.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

ACTION_JS = "mail_client/static/src/mail_client_action.js"


@tagged("post_install", "-at_install")
class TestBusUnsubscribe(TransactionCase):

    def test_sync_subscription_released(self):
        with open(file_path(ACTION_JS), encoding="utf-8") as fh:
            src = fh.read()
        subscribed = re.findall(r'busService\.subscribe\("([\w.]+)",\s*(\w+)\)', src)
        self.assertTrue(subscribed, "подписка — именованным обработчиком, чтобы её можно было снять")
        self.assertNotRegex(src, r'busService\.subscribe\("[\w.]+",\s*\(',
                            "обработчик-стрелку в subscribe не снять — не отписаться")
        for name, handler in subscribed:
            self.assertRegex(
                src, r'onWillDestroy\(\(\) => this\.busService\.unsubscribe\("%s",\s*%s\)\)'
                % (re.escape(name), re.escape(handler)),
                "подписка %s без отписки при закрытии окна" % name)
