# -*- coding: utf-8 -*-
"""Время работы станка по профилю (решение Антона 13.10.2026: станков два, скорости — с каждого отдельно; 15.10.2026:
«добавим к модулю хотя бы те параметры которые получилось выяснить … предварительными, потом подредактируем по мере
накопления статистики»).

Профиль станка — JSON, один файл на станок (`--machine` повторяется — строка времени на каждый станок):

    {"name": "Станок 1",
     "preliminary": true,          предварительный: собран по статистике программ, со станком не сверен (в сводке «≈»)
     "source": "…",                откуда взят (machine_stats пишет «N программ <компьютер> с <месяц>»)
     "updated": "2026-10-15",      когда обновлён
     "note": "…",                  что известно, что нет — справочно
     "k_total": 1.0,               поправка ко всему времени (калибровка по реальному времени или по CypCut; нет — 1)
     "travel_mm_s": 1000,          холостой ход, мм/с
     "lift_s": 0.3,                подъём и опускание головки на каждый переход, с (нет — 0)
     "return_to_zero": true,       после листа головка возвращается в (0,0) (настройка CypCut)
     "mark_mm_s": 300,             гравировка, мм/с
     "cut": [{"t": 1.5, "mm_s": 400, "pierce_s": 0.1},       рез и врезка по толщинам (из .fsm слоя)
             {"t": 3,   "mm_s": 120, "pierce_s": 0.5,
              "fsm": "3мм.fsm", "programs": 12, "gas": "воздух", "lift_mm": 12}]}   справочно: режим, программ, газ, подъём
    (числа — пример, не режимы завода: профили станков в открытый репозиторий не кладутся)

    время = k_total × (рез / mm_s + врезки × pierce_s + гравировка / mark_mm_s + (холостой + возврат) / travel_mm_s
                       + переходы × lift_s)

В разборе (estimate_detail) каждое слагаемое уже умножено на k_total — сумма разбора равна итогу.
Справочные поля (preliminary, source, updated, note; у строки cut — fsm, programs, gas, lift_mm) модель не читает, а
хранит и показывает. Времени нет (None, в разборе — почему), а не «примерно»: толщины нет в профиле (не «ближайшая»);
в программе есть гравировка, а скорости гравировки в профиле нет; толщина листа не задана.
Предварительный профиль собирает `machine_stats.py` по программам станка.
"""
import json, os, numbers
from .errors import SheetNestError

DETAIL_KEYS = ("cut_s", "pierce_s", "mark_s", "travel_s", "lift_s", "k", "total_s", "why")
INFO_KEYS = ("name", "preliminary", "source", "updated", "note", "k_total", "thicknesses")
T_EPS = 1e-6                # мм: толщины равны


class MachineError(SheetNestError):
    """Плохой профиль станка. Профиль — настройка станка (в Odoo — поле станка, его правит администратор, а не
    инженер раскроя): в контракте sheet_nest.job/1 — kind «config», user=false."""
    kind = "config"

    def __init__(self, message):
        super().__init__(message, flag="--machine")


def _show(v):
    """Значение для текста ошибки — без питоновского repr: пусто, число, «строка», список, объект."""
    if v is None:
        return "пусто"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, numbers.Real):
        return "%g" % v
    if isinstance(v, str):
        return "«%s»" % v[:40]
    return {dict: "объект", list: "список"}.get(type(v), type(v).__name__)


def mm(t):
    """Толщина для текста: 0,65 (запятая, без лишних нулей)."""
    return ("%g" % float(t)).replace(".", ",")


def _num(v, name, where, zero_ok=False):
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or v != v or v < 0 or (v == 0 and not zero_ok) or v == float("inf"):
        raise MachineError("%s: %s — нужно число %s, а не %s" % (where, name, "не меньше 0" if zero_ok else "больше 0", _show(v)))
    return float(v)


def _text(v, name, where):
    """Справочное поле — строка или пусто."""
    if v is not None and not isinstance(v, str):
        raise MachineError("%s: %s — строка, а не %s" % (where, name, _show(v)))


def load(src):
    """Профиль станка: путь к JSON или словарь → проверенный словарь (ошибка — MachineError с понятным текстом).
    В проверенном всегда есть name, preliminary (false, если не задан) и k_total (1.0, если не задан); справочные поля
    строк cut (fsm, programs, gas, lift_mm) и прочие ключи сохраняются как есть."""
    if isinstance(src, dict):
        p, name = dict(src), "станок"
        where = "профиль станка «%s»" % p["name"] if isinstance(p.get("name"), str) and p["name"].strip() else "профиль станка"
    else:
        where, name = "профиль станка %s" % src, os.path.splitext(os.path.basename(str(src)))[0]
        try:
            with open(src, encoding="utf-8") as f:
                p = json.load(f)
        except OSError as e:
            raise MachineError("%s: не открывается (%s)" % (where, e.strerror or e))
        except ValueError as e:
            raise MachineError("%s: не JSON%s" % (where, " (строка %d, знак %d)" % (e.lineno, e.colno) if hasattr(e, "lineno") else ""))
    if not isinstance(p, dict):
        raise MachineError("%s: нужен объект {…}, а не %s" % (where, _show(p)))
    if p.get("name") is not None and (not isinstance(p["name"], str) or not p["name"].strip()):
        raise MachineError("%s: name — непустая строка, а не %s" % (where, _show(p["name"])))
    _num(p.get("travel_mm_s"), "travel_mm_s", where)
    cut = p.get("cut")
    if not isinstance(cut, list) or not cut:
        raise MachineError("%s: нужен cut — список [{t, mm_s, pierce_s}] по толщинам" % where)
    seen = []
    for r in cut:
        if not isinstance(r, dict):
            raise MachineError("%s: строка cut %s — нужен объект {t, mm_s, pierce_s}" % (where, _show(r)))
        t = _num(r.get("t"), "cut.t", where)
        if any(abs(t - t0) < T_EPS for t0 in seen):
            raise MachineError("%s: толщина %s мм в cut дважды — оставьте одну строку" % (where, mm(t)))
        seen.append(t)
        _num(r.get("mm_s"), "cut.mm_s (t=%s)" % mm(t), where)
        if "pierce_s" in r:
            _num(r["pierce_s"], "cut.pierce_s (t=%s)" % mm(t), where, zero_ok=True)
        for k in ("fsm", "gas"):
            _text(r.get(k), "cut.%s (t=%s)" % (k, mm(t)), where)
        n = r.get("programs")
        if n is not None and (isinstance(n, bool) or not isinstance(n, numbers.Integral) or n < 0):
            raise MachineError("%s: cut.programs (t=%s) — целое число не меньше 0, а не %s" % (where, mm(t), _show(n)))
        if r.get("lift_mm") is not None:
            _num(r["lift_mm"], "cut.lift_mm (t=%s)" % mm(t), where, zero_ok=True)
    if "lift_s" in p:
        _num(p["lift_s"], "lift_s", where, zero_ok=True)
    if p.get("mark_mm_s") is not None:
        _num(p["mark_mm_s"], "mark_mm_s", where)
    if not isinstance(p.get("return_to_zero", False), bool):
        raise MachineError("%s: return_to_zero — true или false" % where)
    if p.get("preliminary") is not None and not isinstance(p["preliminary"], bool):
        raise MachineError("%s: preliminary — true или false, а не %s" % (where, _show(p["preliminary"])))
    for k in ("source", "updated", "note"):
        _text(p.get(k), k, where)
    k_total = 1.0 if p.get("k_total") is None else _num(p["k_total"], "k_total", where)
    if p.get("name") is None:
        p["name"] = name
    p["preliminary"] = bool(p.get("preliminary"))
    p["k_total"] = k_total
    return p


def info(profile):
    """Профиль для отчёта и result.json (эхо): имя, предварительный ли, источник, дата, заметка, поправка, толщины."""
    return dict(name=profile["name"], preliminary=bool(profile.get("preliminary")), source=profile.get("source"),
                updated=profile.get("updated"), note=profile.get("note"), k_total=float(profile.get("k_total") or 1.0),
                thicknesses=sorted(float(r["t"]) for r in profile.get("cut", ())))


def cut_row(profile, thickness):
    for r in profile.get("cut", ()):
        if thickness is not None and abs(float(r["t"]) - float(thickness)) < T_EPS:
            return r
    return None


def estimate_detail(profile, thickness, cut_mm, mark_mm, idle_mm, ret_mm, pierces, moves):
    """Разбор времени станка, с (числа — суммы по листам × количество: рез, гравировка, холостой, возврат в ноль, мм;
    врезок, переходов): cut_s — рез, pierce_s — врезки, mark_s — гравировка, travel_s — холостой (с возвратом в ноль,
    если он в профиле), lift_s — подъёмы головки; составляющие — уже с поправкой k (k_total профиля), их сумма —
    total_s (без поправки — разделить на k); why — None.
    Посчитать нельзя — составляющие и total_s None, why — почему («в профиле нет толщины 0,65 мм»)."""
    k = float(profile.get("k_total") or 1.0) if profile else None

    def no(why):
        return dict(cut_s=None, pierce_s=None, mark_s=None, travel_s=None, lift_s=None, k=k, total_s=None, why=why)
    if not profile:
        return no("нет профиля станка")
    if thickness is None:
        return no("толщина листа не задана")
    r = cut_row(profile, thickness)
    if r is None:
        return no("в профиле нет толщины %s мм" % mm(thickness))
    if mark_mm and not profile.get("mark_mm_s"):
        return no("нет скорости гравировки")
    raw = (("cut_s", cut_mm / float(r["mm_s"])), ("pierce_s", pierces * float(r.get("pierce_s", 0.0))),
           ("mark_s", mark_mm / float(profile["mark_mm_s"]) if mark_mm else 0.0),
           ("travel_s", (idle_mm + (ret_mm if profile.get("return_to_zero") else 0.0)) / float(profile["travel_mm_s"])),
           ("lift_s", moves * float(profile.get("lift_s", 0.0))))
    d = {n: k * v for n, v in raw}
    d.update(k=k, total_s=k * sum(v for n, v in raw), why=None)
    return d


def estimate(profile, thickness, cut_mm, mark_mm, idle_mm, ret_mm, pierces, moves):
    """Секунды на все листы или None (нет профиля, толщины в нём или скорости гравировки при гравировке) — итог
    estimate_detail (с поправкой k_total)."""
    return estimate_detail(profile, thickness, cut_mm, mark_mm, idle_mm, ret_mm, pierces, moves)["total_s"]


def rounded(d, nd=1):
    """Разбор для сводки: секунды — до 0,1 с (сумма составляющих = total_s с точностью округления)."""
    return {k: (round(v, nd) if isinstance(v, float) and k.endswith("_s") else v) for k, v in d.items()}


def label(profile):
    """«станок «Х»» и «(предварительно)» у предварительного — для текста сводки и лога."""
    return "станок «%s»%s" % (profile["name"], " (предварительно)" if profile.get("preliminary") else "")
