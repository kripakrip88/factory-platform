"""Скрытие корневых пунктов почтовых модулей из шапки.

Team Inbox убираем не через data-файл, а отсюда: объявить его меню в XML
можно только объявив сам модуль в depends, и тогда pmk_mail_ui перестанет
ставиться, если Team Inbox снесут после сравнения. Мягкая привязка через
ref(..., raise_if_not_found=False) переживает и его отсутствие.
"""

# Корни, которые не должны показываться отдельным приложением. Mail Client
# лежит в data/menus.xml — он в depends, и XML там честнее.
SOFT_HIDE = [
    "northlight_teaminbox.menu_teaminboxbasic_root",
]


def post_init_hook(env):
    for xmlid in SOFT_HIDE:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.active = False
