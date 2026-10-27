# -*- coding: utf-8 -*-
"""Таблицы ОСТ из pmk_opora/tools — загрузка по пути файла, без Odoo.

Чертёжный процесс работает в отдельном контейнере (python + PyMuPDF), где Odoo нет, поэтому
`odoo.addons.pmk_opora.tools` недоступен. Папка tools регистрируется под своим именем-пакетом
(_pmk_opora_tools): ost36_94 импортирует соседа относительно (`from .ost36_94_mass import MASS`).
В самих файлах tools импортов из odoo нет (проверено 27.10.2026).
"""
import importlib.util
import os
import sys

TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
PKG = "_pmk_opora_tools"


def _load(name):
    full = "%s.%s" % (PKG, name)
    if full in sys.modules:
        return sys.modules[full]
    if PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(PKG, os.path.join(TOOLS, "__init__.py"),
                                                      submodule_search_locations=[TOOLS])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[PKG] = pkg
        spec.loader.exec_module(pkg)
    spec = importlib.util.spec_from_file_location(full, os.path.join(TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


ost146 = _load("ost36_146")
ost94 = _load("ost36_94")
