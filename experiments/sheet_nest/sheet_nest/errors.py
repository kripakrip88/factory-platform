# -*- coding: utf-8 -*-
"""Ошибки пользователя (ERP.md, «Что сделать до переноса», п. 3).

SheetNestError — плохие входные данные или параметры: текст для человека, по-русски, БЕЗ флагов командной строки
(«--qty», «--bridge-group», «--label» …) — его показывают и в Odoo. Флаг, если он помогает в командной строке, лежит
в атрибуте `flag`; его дописывает к тексту сама командная строка (cli.main). `input` — номер входа run() (с 0), к
которому относится ошибка (битый файл, количество, деталь больше листа), иначе None: в контракте sheet_nest.job/1 по
нему error.json называет вход (`input`: {index, key}), и Odoo отмечает строку детали.

Наследники: read_dxf.DxfError и read_lxds.LxdsError (плохой файл — kind «input» контракта sheet_nest.job/1),
labels.LabelError (подпись), labels.FontError и machine.MachineError (таблица шрифта, профиль станка — настройки
администратора, kind «config»). Всё прочее, что не наследует SheetNestError, — ошибка движка или окружения.
"""


class SheetNestError(ValueError):
    """Ошибка пользователя. `flag` — подсказка для командной строки (в тексте ошибки её нет); `input` — номер входа
    run() или None; kind — вид ошибки в контракте sheet_nest.job/1 (params; у наследников — input, config)."""
    kind = "params"

    def __init__(self, message, flag=None, input=None):
        super().__init__(message)
        self.flag = flag
        self.input = input
