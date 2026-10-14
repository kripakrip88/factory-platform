# -*- coding: utf-8 -*-
"""Доступ к пакету раскроя зонтов (сборщик .lxds, расшифровщик, растровый раскрой v1).

Пакет лежит в модуле Odoo pmk_vent_nest: lib/vent_nesting. Где искать (каталог, в котором лежит vent_nesting/), по
порядку (ERP.md, «Что сделать до переноса», п. 7):
  1. переменная окружения VENT_NESTING_LIB — если задана, только она (задана неверно — ошибка, без поиска дальше:
     job.py ставит её из input.json, и молча взять другой пакет нельзя);
  2. соседний аддон: движок установлен как addons/pmk_sheet_nest/lib/sheet_nest → addons/pmk_vent_nest/lib;
  3. репозиторий: experiments/sheet_nest/sheet_nest → experiments/odoo/addons/pmk_vent_nest/lib.
Нет пакета — ImportError с перечнем мест.
    from sheet_nest.libpath import vn        # vn.spec_rebuild, vn.lxds_reader, vn.nest, vn.contours …
"""
import os, sys, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [os.path.normpath(os.path.join(HERE, "..", "..", "..", "pmk_vent_nest", "lib")),           # соседний аддон
              os.path.normpath(os.path.join(HERE, "..", "..", "odoo", "addons", "pmk_vent_nest", "lib"))]  # репозиторий


def find_lib():
    """Каталог с пакетом vent_nesting по правилу выше; нет — ImportError с текстом."""
    env = os.environ.get("VENT_NESTING_LIB")
    if env:
        if os.path.isdir(os.path.join(env, "vent_nesting")):
            return env
        raise ImportError("пакет vent_nesting не найден в %s (переменная VENT_NESTING_LIB)" % env)
    for c in CANDIDATES:
        if os.path.isdir(os.path.join(c, "vent_nesting")):
            return c
    raise ImportError("пакет vent_nesting не найден: переменная VENT_NESTING_LIB не задана, нет ни %s" % " ни ".join(CANDIDATES))


LIB = find_lib()
if LIB not in sys.path:
    sys.path.insert(0, LIB)


class _NS:
    def __getattr__(self, name):
        mod = importlib.import_module("vent_nesting.cypcut." + name if name.startswith(("spec_", "xml_")) else "vent_nesting." + name)
        setattr(self, name, mod)
        return mod


vn = _NS()


def vent_nesting_version():
    """Версия пакета vent_nesting (его __version__) — для result.json и прогона в Odoo."""
    return getattr(importlib.import_module("vent_nesting"), "__version__", None)
