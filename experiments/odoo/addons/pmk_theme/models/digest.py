# -*- coding: utf-8 -*-
"""«Сводка» Odoo (digest) выключается один раз — разбор UX, шаг 29 (02.10.2026).

Сводка — письмо с показателями модулей («Ваш периодический сборник Odoo»):
выручка, счета, лиды… На заводе эти модули пустые, и письмо шло ни о чём:
16.09 ушло первое, следующее стояло на 30.10 (раз в месяц, получатель —
admin). Новые пользователи подписывались на него сами (параметр
digest.default_digest_emails).

КАК. data/digest_off.xml зовёт _pmk_digest_off_once при каждом -u pmk_theme,
но работает метод один раз: после первого прохода в системных параметрах
остаётся метка pmk_theme.digest_off (дата). Поэтому включённую владельцем
сводку деплой больше не выключит. Без миграции намеренно: миграция
привязана к номеру версии модуля, а его поднимают и соседние шаги.

Что делает: штатная сводка (digest.digest_digest_default) — «Деактивировано»
(штатная кнопка action_deactivate, получатели и показатели не трогаются);
параметр «новых пользователей подписывать на сводку» снимается (set_param с
False удаляет параметр — галочка в Настройках становится пустой). Галочку
«Сводка» в Настройках прячет models/hidden_nodes.py.

ВЕРНУТЬ: режим разработчика → Настройки → Технический → Электронная почта →
Digest Emails → «Ваш периодический сборник Odoo» → «Активировать»; подписка новых —
добавить себя в «Убранное (показать)», Настройки → Общие → «Сводка» —
поставить галочку. Метку pmk_theme.digest_off не удалять: без неё следующий
деплой снова выключит сводку.
"""
from odoo import api, fields, models

MARK = "pmk_theme.digest_off"


class Digest(models.Model):
    _inherit = "digest.digest"

    @api.model
    def _pmk_digest_off_once(self):
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(MARK):
            return False
        digest = self.env.ref("digest.digest_digest_default", raise_if_not_found=False)
        if digest and digest.state == "activated":
            digest.sudo().action_deactivate()
        params.set_param("digest.default_digest_emails", False)
        params.set_param(MARK, fields.Date.to_string(fields.Date.context_today(self)))
        return True
