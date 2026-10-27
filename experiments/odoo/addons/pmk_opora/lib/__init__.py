# -*- coding: utf-8 -*-
"""Генератор чертежей опор, правила в.2 (по чертежам И. Бутова).

Работает вне Odoo (чертёжный процесс: Python 3 + PyMuPDF). Подключать по пути папки, а не как
odoo.addons.pmk_opora.lib (пакет pmk_opora тянет Odoo):
    sys.path.insert(0, "<…>/pmk_opora/lib"); import drawings; drawings.draw("kx", 219, "А12", "Ст3пс", out)
Здесь ничего не импортируется намеренно — Odoo этот пакет не грузит.
"""
