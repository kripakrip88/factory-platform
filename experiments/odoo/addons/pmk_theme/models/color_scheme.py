# -*- coding: utf-8 -*-
"""Тема у человека, а не у браузера (разбор UX, шаг 40, 05.10.2026).

Было: тёмную тему включал скрипт чужой темы theme_nexus ПОСЛЕ загрузки
страницы (класс o_nexus_dark на body, выбор — в localStorage браузера):
страница на долю секунды белая, а на другом компьютере — другая тема.

Стало: выбор хранится у пользователя (pmk_color_scheme), сервер сразу рисует
body с классом (views/webclient_color_scheme.xml), переключатель в шапке
пишет выбор сюда (static/src/js/color_scheme.js).

Пусто — ещё не выбирал: показываем светлую. Значения по умолчанию у поля
НЕТ намеренно: иначе -u заполнит всех «светлой», и сохранённый в браузере
выбор (тёмная у Антона) не перенесётся при первом входе.

Штатный механизм Odoo (ir.http.color_scheme() → бандл web.assets_web_dark)
НЕ включаем: в бесплатной версии он отдаёт файлы *.dark.scss, написанные под
тёмные переменные платной web_enterprise, — с нашими светлыми они дают
светлые плашки, а смена бандла требует перезагрузки страницы. Поэтому
color_scheme() ядра здесь не трогаем: он по-прежнему «light».

Вернуть прежнее (тема только в браузере): см. docs/disabled-features.md,
раздел «шаг 40».
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request

COLOR_SCHEMES = [("light", "Светлая"), ("dark", "Тёмная")]


class ResUsers(models.Model):
    _inherit = "res.users"

    # copy=False: новую учётку заводят «Дублировать» от существующей (те же
    # права) — тема копировалась бы вместе с ними, и сотрудник с первого входа
    # сидел бы в чужой тёмной: выбор на сервере главнее браузера. Новому —
    # пусто, как у всех, кто ещё не выбирал (доводка шага 40).
    pmk_color_scheme = fields.Selection(
        COLOR_SCHEMES,
        string="Тема оформления",
        copy=False,
        help="Светлая или тёмная тема интерфейса у этого человека — на любом "
             "компьютере. Меняется переключателем в шапке. Пусто — ещё не "
             "выбирал, показывается светлая.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["pmk_color_scheme"]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ["pmk_color_scheme"]

    @api.model
    def pmk_set_color_scheme(self, scheme):
        """Переключатель темы в шапке: выбор — текущему человеку, и только ему."""
        if scheme not in dict(COLOR_SCHEMES):
            raise ValidationError(
                "Тема оформления — «светлая» или «тёмная», а не %r." % (scheme,))
        # Своя запись и поле из SELF_WRITEABLE_FIELDS: res.users.write сам
        # переходит в sudo, прав на пользователей не нужно. Запись идёт только
        # при смене (переключатель зовёт метод лишь тогда), лишних строк в
        # базе нет.
        self.env.user.write({"pmk_color_scheme": scheme})
        return scheme


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        # Веб-клиенту — для шаблона загрузки (класс на body) и для
        # переключателя. Без входа (страница входа, публичные) — ничего.
        if request and request.session.uid:
            scheme = self.env.user.pmk_color_scheme or False
            if not self._pmk_dark_mode_available():
                scheme = False
            info["pmk_color_scheme"] = scheme
        return info

    def _pmk_dark_mode_available(self):
        """Есть ли чем рисовать тёмную тему и чем её выключить.

        Тёмную основу страницы и сам переключатель даёт чужая тема
        theme_nexus (dark_mode.scss, dark_mode.js). Её снимут — без этой
        проверки человек с выбранной тёмной темой остался бы в недоделанной
        тёмной без кнопки возврата. Выбор в базе при этом не стирается:
        вернут тему — вернётся и он.
        """
        return "theme_nexus" in self.env["ir.module.module"]._installed()
