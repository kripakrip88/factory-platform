# -*- coding: utf-8 -*-
"""Настройки ящика: одна залитая кнопка на экран (разбор UX, шаг 30).

Главная кнопка ящика — «Синхронизировать сейчас» в шапке. «Создать токен» на
вкладке «Push-уведомления» была второй залитой; теперь контурная
(views/mail_client_account_views.xml). Разметка — собранная, как её получает
браузер (get_views с правами администратора: вкладка видна только ему).
Ловится то, что ломается молча: xpath перестал находить кнопку (вид
выключился бы при загрузке), наш вид выключен, у кнопки снова btn-primary.
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTokenButtonStep30(TransactionCase):

    def _form(self):
        admin = self.env.ref("base.user_admin")
        views = self.env["mail.client.account"].with_user(admin).get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_view_active(self):
        view = self.env.ref("pmk_mail_ui.view_mail_client_account_form_pmk_token")
        self.assertTrue(view.active)
        self.assertEqual(view.inherit_id, self.env.ref("mail_client.mail_client_account_view_form"))

    def test_one_filled_button(self):
        form = self._form()
        token = form.xpath("//button[@name='action_generate_notify_token']")
        self.assertEqual(len(token), 1, "кнопка «Создать токен» на месте")
        classes = (token[0].get("class") or "").split()
        self.assertIn("btn-secondary", classes)
        self.assertNotIn("btn-primary", classes)
        filled = [b.get("name") for b in form.iter("button")
                  if {"btn-primary", "oe_highlight"} & set((b.get("class") or "").split())]
        # «Авторизовать» (OAuth Gmail и Microsoft 365) — в плашке, видна
        # только у такого ящика, пока доступ не дан; у mail.ru её нет.
        self.assertEqual(sorted(filled), ["action_authorise_oauth", "action_sync_now"])
