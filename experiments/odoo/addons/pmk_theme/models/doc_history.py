# -*- coding: utf-8 -*-
"""«История» кнопкой в строке пути, лента из формы убрана — разбор UX,
шаг 65 (11.10.2026). Серверная часть.

Антон 11.10: «блок история уведём в отдельную кнопку в шапке документа …
файлы — можно перенести во вкладку, где стоят Заметки и Связи (добавить
счётчик)». Клиент — static/src/js/doc_tools.js (значок, окно «История»,
«Задача» в «⚙ Действия»), doc_files.js (файлы), стили — forms_nexus.scss и
dark.scss, раздел «Шаг 65».

1. ВКЛАДКА «ФАЙЛЫ» — всем формам с лентой разом, без наследника на каждую.
   Тем же приёмом, что models/base.py (шаг 26) и hidden_nodes.py (шаг 29):
   правим собранную разметку в _get_view — после ВСЕХ наследников (поэтому
   вкладка встаёт последней, после «Связей» pmk_flow с priority 99), до кэша
   видов. Условия:
     • вид формы модели с лентой (mail.thread: поле message_ids), не мастер;
     • в разметке есть <chatter> (прямо в форме или в листе);
     • первая вкладочная панель — прямо в листе (sheet/notebook, а не
       //notebook: у расчёта и заказа поставщику внутри строк свои), без
       своего invisible (у карточки клиента панель спрятана шагом 3
       pmk_partner — там скрепка в строке пути) и без нашей вкладки.
   Вкладке ставится groups="!pmk_theme.group_pmk_removed": человеку в группе
   «Убранное (показать)» ядро её вырезает (_postprocess_access_rights) — у
   него лента под формой со скрепкой, как было. Разметка в базе не меняется.
   Формы без вкладок (вентзонты, доборка, «Заказ в работе») — скрепка с
   числом в строке пути (клиент).

2. ВЫКЛЮЧАТЕЛЬ ДЛЯ КЛИЕНТА: session_info.pmk_chatter_in_form — человек в
   группе «Убранное (показать)». Тогда клиент не трогает форму вовсе: лента
   под формой, без значков и без «Задачи» в «Действиях». Группа сейчас
   пустая (0 человек, 11.10.2026); после смены группы — перезагрузить
   страницу.

Вернуть всё разом: удалить этот файл и его импорт в models/__init__.py,
пять строк шага 65 в манифесте pmk_theme — docs/disabled-features.md,
раздел «шаг 65».
"""
from odoo import api, models
from odoo.http import request

REMOVED = "pmk_theme.group_pmk_removed"
FILES_PAGE = "pmk_files"
FILES_LABEL = "Файлы"


def _has_chatter(arch):
    return bool(arch.xpath("./chatter | ./sheet/chatter"))


def _files_notebook(arch):
    """Вкладочная панель листа, в которую встаёт «Файлы», или None."""
    notebooks = arch.xpath("./sheet/notebook")
    if not notebooks:
        return None
    notebook = notebooks[0]
    if notebook.get("invisible") not in (None, "", "0", "False"):
        return None
    if notebook.xpath("./page[@name='%s']" % FILES_PAGE):
        return None
    return notebook


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if arch is not None and view_type == "form":
            self._pmk_add_files_page(arch)
        return arch, view

    @api.model
    def _pmk_add_files_page(self, arch):
        if self._transient or "message_ids" not in self._fields:
            return
        if arch.tag != "form" or not _has_chatter(arch):
            return
        notebook = _files_notebook(arch)
        if notebook is None:
            return
        page = notebook.makeelement("page", {"string": FILES_LABEL, "name": FILES_PAGE})
        # Группы ещё нет (pmk_theme ставится) — вкладка всем, без groups:
        # ссылку на несуществующую группу ядро не разберёт.
        if self.env.ref(REMOVED, raise_if_not_found=False):
            page.set("groups", "!" + REMOVED)
        page.append(page.makeelement("widget", {"name": FILES_PAGE}))
        notebook.append(page)


class ResUsers(models.Model):
    _inherit = "res.users"

    def _pmk_chatter_in_form(self):
        """Лента под формой, как до шага 65: человек в «Убранное (показать)»."""
        self.ensure_one()
        if not self.env.ref(REMOVED, raise_if_not_found=False):
            return False
        return self.has_group(REMOVED)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        # Без входа (страница входа, публичные) — ничего.
        if request and request.session.uid:
            info["pmk_chatter_in_form"] = self.env.user._pmk_chatter_in_form()
        return info
