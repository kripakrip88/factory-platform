# -*- coding: utf-8 -*-
"""Предварительный профиль станка по его программам CypCut (Антон, 15.10.2026: «добавим к модулю хотя бы те параметры
которые получилось выяснить … предварительными, потом подредактируем по мере накопления статистики»).

    python3 -m sheet_nest.machine_stats ПАПКА --computer ИМЯ --travel ММ_С [--since ГГГГ-ММ] [--name «…»]
                                        [--out profile.json [--force]]

Режим резки записан в программе открытым текстом (Technical/content.xml; файлы .fsm CypCut зашифрованы — их не
читаем). Берутся программы .lxds из ПАПКИ (со вложенными), СОХРАНЁННЫЕ на компьютере станка (info.xml → SavedBy
Computer; на других компьютерах режимы — копии и шаблоны), с месяца --since (SaveTime). По каждому каналу (слою):
    MaterialName — режим (.fsm); CamParams WorkSpeed — скорость реза, мм/с; LiftHeight — подъём, мм; PierceStepCount и
    Pierce1..n TimeStay (мс) — врезка, с; Cut GasType — газ (2 — кислород, 3 — воздух: так у режимов «кис…» и
    «…воздух»); толщина — из имени режима (thickness_of): число в начале («1,2 мм.fsm»), иначе число с «мм»/«mm»
    («А-12мм сопло 5.fsm»), иначе дробное («старое 0.7 сопло 2.fsm»); номер сопла («сопло 1.4», «с1мм», «с.2») —
    не толщина; MaterialParams Thickness — только если совпал с числом в имени (сам по себе ненадёжен: у режимов
    бывает толщина соседнего режима или число в сто раз больше). Нет — «толщина неизвестна».
Не считаются: шаблон офиса (режима нет, 100 мм/с, подъём 10, газа нет), каналы без режима, без толщины, без скорости
(после округления до 0,1 — 0) или с врезкой меньше 0, гравировка (в имени режима «грав» или «грайв» — из неё самая
частая скорость → mark_mm_s, остальные скорости — в таблице с листами, на которых гравировали), повреждённые файлы,
повторы одного сохранения (тот же компьютер, время и режимы — копия файла в другой папке). Всё — со счётом в выводе.
По толщине: самый частый режим (по числу программ), в нём — самая частая пара (скорость, врезка) → строка cut, к ней
справочно fsm, programs (программ с этим режимом), gas, lift_mm. Профиль — preliminary=true, source «N программ
<компьютер> с <месяц>», updated — сегодня; холостой ход в программах не записан — --travel обязателен (замер на
станке); подъём головки на переход (lift_s) и возврат в ноль не известны — 0 и false; k_total 1 — подбирается по
реальному времени (README, «Профили станков»). Похоже на копии режимов или офис, а не на станок (газа нет ни в одной
программе, больше половины каналов — шаблон офиса), или программ с режимами резки мало — предупреждение в выводе и в
note (не запрет). Профиль проверяется machine.load до записи.
--out не перезаписывает файл без --force (в нём может быть калибровка); с --force имя станка берётся из прежнего
профиля (если не задан --name), что из калибровки потеряно — в выводе.

Файлы — недоверенные данные: только чтение двух частей архива (не больше PART_MAX каждая), только UTF-8 без DTD
(сущности DTD разворачиваются при разборе — «миллиард смехов»), разбором XML; сбой файла — пропуск со счётом.
Только стандартная библиотека (без numpy и vent_nesting).
"""
import os, re, sys, json, math, zipfile, hashlib, argparse, datetime, collections
import xml.etree.ElementTree as ET
from . import machine as MC

PART_MAX = 4 << 20          # байт: info.xml и Technical/content.xml больше — не программа CypCut
PIERCE_STEPS_MAX = 20       # ступеней врезки (у CypCut — Pierce1..9)
T_MAX = 100.0               # мм: число в имени режима больше — не толщина
FEW_PROGRAMS = 20           # программ с режимами резки меньше — предупреждение «мало»
GAS = {2: "кислород", 3: "воздух"}
ENGRAVE = ("грав", "грайв")
TEMPLATE_SPEED, TEMPLATE_LIFT = 100.0, 10.0     # шаблон офиса: 6 м/мин, подъём 10 мм, без газа и без режима
NUM = re.compile(r"\d+(?:[.,]\d+)?")
UNIT = re.compile(r"\s*(?:мм|mm)", re.I)
NOZZLE = re.compile(r"(?:^|[^a-zа-яё])(?:сопло|soplo|nozzle|с|c)\.?[\s-]*$", re.I)     # перед числом — сопло: не толщина
XML_ENC = re.compile(r"﻿?\s*<\?xml[^>]*?\bencoding\s*=\s*[\"']([^\"']*)[\"']")
SINCE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
SKIP_TITLES = (("template", "шаблон офиса"), ("no_fsm", "без режима (.fsm)"), ("no_thickness", "толщина неизвестна"),
               ("no_speed", "без скорости"), ("bad_pierce", "врезка меньше 0"))
CALIBRATED = ("travel_mm_s", "lift_s", "return_to_zero", "k_total", "preliminary")   # правят руками после калибровки


class StatsError(Exception):
    """Нечего считать или плохие параметры — текст для человека (командная строка: «ошибка: …», выход 1)."""


def _f(v):
    """Число из атрибута XML (CypCut пишет и «0,2», и «.5») или None."""
    if v is None:
        return None
    try:
        x = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _part(z, name):
    """Часть архива целиком, но не больше PART_MAX (недоверенный архив: размер в заголовке может врать)."""
    with z.open(name) as f:
        data = f.read(PART_MAX + 1)
    if len(data) > PART_MAX:
        raise ValueError("%s больше %d байт" % (name, PART_MAX))
    return data


def _xml(z, name):
    """Часть архива → (корень XML, байты). Только UTF-8 без DTD и сущностей: CypCut их не пишет, а сущности
    разворачиваются при разборе (килобайт → гигабайты; expat старше 2.4 это не ограничивает). Иначе — ValueError."""
    data = _part(z, name)
    text = data.decode("utf-8")                         # UTF-16 с не-ASCII и прочее — UnicodeDecodeError (ValueError)
    enc = XML_ENC.match(text)
    if "\x00" in text or "<!DOCTYPE" in text or "<!ENTITY" in text or (enc and enc.group(1).lower() not in ("utf-8", "utf8")):
        raise ValueError("%s: DTD, сущности или не UTF-8 — не программа CypCut" % name)
    return ET.fromstring(data), data


def read_program(path):
    """Программа CypCut → dict(computer, saved, digest, channels=[{fsm, t_mat, speed, lift, pierce_s, gas}]); врезка
    со ступенью меньше 0 — pierce_s None, подъём меньше 0 — lift None. Не программа (не zip, нет частей, испорчен XML,
    DTD) — исключение (вызывающий считает файл повреждённым)."""
    with zipfile.ZipFile(path) as z:
        info, _ = _xml(z, "info.xml")
        tech, tech_raw = _xml(z, "Technical/content.xml")
    sb = info.find("SavedBy")
    chans = []
    for ch in tech.iter("Channel"):
        cp = ch.find("CamParams")
        if cp is None:
            continue
        n = int(min(max(_f(cp.get("PierceStepCount")) or 0, 0), PIERCE_STEPS_MAX))
        stays = []
        for i in range(1, n + 1):
            pe = cp.find("Pierce%d" % i)
            stays.append((_f(pe.get("TimeStay")) or 0.0) if pe is not None else 0.0)
        ms = sum(stays)
        mp, cut = ch.find("MaterialParams"), cp.find("Cut")
        gas = _f(cut.get("GasType")) if cut is not None else None
        lift = _f(cp.get("LiftHeight"))
        chans.append(dict(fsm=(ch.findtext("MaterialName") or "").strip() or None,
                          t_mat=_f(mp.get("Thickness")) if mp is not None else None, speed=_f(cp.get("WorkSpeed")),
                          lift=lift if lift is None or lift >= 0 else None,
                          pierce_s=round(ms / 1000.0, 3) if min(stays, default=0) >= 0 and math.isfinite(ms) else None,
                          gas=int(gas) if gas is not None and gas == int(gas) else None))
    return dict(computer=sb.get("Computer") if sb is not None else None, saved=sb.get("SaveTime") if sb is not None else None,
                digest=hashlib.md5(tech_raw).hexdigest(), channels=chans)


def thickness_of(fsm, t_mat):
    """Толщина канала, мм, из имени режима: число в начале («0.7.fsm», «1,2 мм.fsm»), иначе первое число с «мм»/«mm»
    за ним («А-12мм сопло 5.fsm»), иначе первое дробное («старое 0.7 сопло 2.fsm»); число после «сопло», «soplo», «с»
    («с1мм», «с.2») — номер сопла, не толщина. Иначе MaterialParams Thickness (t_mat) — только если в имени есть такое
    же число (сам по себе он ненадёжен: у режима «0.7.fsm» бывает 70). Нет или вне (0, T_MAX] — None."""
    name = fsm or ""
    unit, dec, other = [], [], []
    for m in NUM.finditer(name):
        x = round(float(m.group().replace(",", ".")), 3)
        if not 0 < x <= T_MAX:
            continue
        before = name[:m.start()]
        if not before.strip():
            return x
        if NOZZLE.search(before):
            continue
        (unit if UNIT.match(name, m.end()) else dec if not m.group().isdigit() else other).append(x)
    if unit or dec:
        return (unit or dec)[0]
    if t_mat is not None and any(abs(t_mat - x) < MC.T_EPS for x in other):
        return round(float(t_mat), 3)
    return None


def is_template(ch):
    """Шаблон офиса: режима нет, 100 мм/с, подъём 10 мм, газа нет."""
    return (ch["fsm"] is None and ch["speed"] is not None and abs(ch["speed"] - TEMPLATE_SPEED) < 0.05 and
            ch["lift"] is not None and abs(ch["lift"] - TEMPLATE_LIFT) < 1e-6 and ch["gas"] is None)


def is_engraving(fsm):
    low = (fsm or "").lower()
    return any(w in low for w in ENGRAVE)


def gas_name(g):
    return None if g is None else GAS.get(g, "газ %d" % g)


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _lxds(folder):
    out = []
    for dp, dn, fn in os.walk(folder):
        dn.sort()
        out += [os.path.join(dp, f) for f in sorted(fn) if f.lower().endswith(".lxds")]
    return out


def collect(folder, computer, since=None):
    """Каналы программ компьютера → (записи реза, записи гравировки, счёт, программ по компьютерам). Запись реза —
    dict(t, fsm, speed, pierce_s, gas, lift, saved, prog); гравировки — dict(fsm, speed, saved, prog, ts — толщины
    реза той же программы)."""
    st = collections.Counter()
    computers = collections.Counter()
    seen, cut, marks = set(), [], []
    for path in _lxds(folder):
        st["files"] += 1
        try:
            p = read_program(path)
        except Exception:                               # недоверенный файл: что угодно внутри — пропуск со счётом
            st["corrupt"] += 1
            continue
        computers[p["computer"] or "?"] += 1
        if (p["computer"] or "").casefold() != computer.casefold():
            st["other"] += 1
            continue
        if since:
            if not p["saved"]:
                st["no_date"] += 1
                continue
            if p["saved"][:len(since)] < since:
                st["before"] += 1
                continue
        key = (p["saved"], p["digest"])
        if key in seen:
            st["copies"] += 1
            continue
        seen.add(key)
        st["programs"] += 1
        prog, ts, pm = len(seen), set(), []
        for ch in p["channels"]:
            if is_template(ch):
                st["template"] += 1
            elif ch["fsm"] is None:
                st["no_fsm"] += 1
            elif ch["speed"] is None or round(ch["speed"], 1) <= 0:
                st["no_speed"] += 1
            elif is_engraving(ch["fsm"]):
                st["engraving"] += 1
                pm.append(dict(fsm=ch["fsm"], speed=round(ch["speed"], 1), saved=p["saved"] or "", prog=prog))
            else:
                t = thickness_of(ch["fsm"], ch["t_mat"])
                if t is None:
                    st["no_thickness"] += 1
                elif ch["pierce_s"] is None:
                    st["bad_pierce"] += 1
                else:
                    ts.add(t)
                    cut.append(dict(t=t, fsm=ch["fsm"], speed=round(ch["speed"], 1), pierce_s=ch["pierce_s"], gas=ch["gas"],
                                    lift=ch["lift"], saved=p["saved"] or "", prog=prog))
        for r in pm:
            r["ts"] = ts
        marks += pm
    return cut, marks, st, computers


def _progs(lst):
    return len({r["prog"] for r in lst})


def _last(lst):
    return max(r["saved"] for r in lst)


def _most(values):
    """Самое частое значение (не None); ничья — большее; нет значений — None."""
    c = collections.Counter(v for v in values if v is not None)
    return max(c, key=lambda v: (c[v], v)) if c else None


def summarize(cut, marks):
    """Записи → (строки cut профиля, mark_mm_s, разбор для таблицы, разбор гравировки). По толщине — самый частый
    режим (по числу программ; ничья — где сохранение позже), в нём — самая частая пара (скорость, врезка) (так же).
    Гравировка — самая частая скорость; остальные — в разборе (каналов, режимы, толщины листов)."""
    by_t = collections.defaultdict(list)
    for r in cut:
        by_t[r["t"]].append(r)
    rows, info = [], []
    for t in sorted(by_t):
        procs = collections.defaultdict(list)
        for r in by_t[t]:
            procs[r["fsm"]].append(r)
        fsm = max(procs, key=lambda f: (_progs(procs[f]), _last(procs[f]), f))
        lst = procs[fsm]
        pairs = collections.defaultdict(list)
        for r in lst:
            pairs[(r["speed"], r["pierce_s"])].append(r)
        speed, pierce = max(pairs, key=lambda k: (_progs(pairs[k]), _last(pairs[k]), k))
        sel = pairs[(speed, pierce)]
        lift = _most(r["lift"] for r in sel)
        rows.append(dict(t=t, mm_s=speed, pierce_s=pierce, fsm=fsm, programs=_progs(lst), gas=gas_name(_most(r["gas"] for r in sel)),
                         lift_mm=lift))
        info.append(dict(t=t, pair_programs=_progs(sel), speeds=len(pairs),
                         others=sorted(((f, _progs(v)) for f, v in procs.items() if f != fsm), key=lambda x: (-x[1], x[0]))))
    mark, mark_info = None, None
    if marks:
        sp = collections.defaultdict(list)
        for r in marks:
            sp[r["speed"]].append(r)
        mark = max(sp, key=lambda k: (len(sp[k]), _last(sp[k]), k))
        one = lambda s: dict(speed=s, n=len(sp[s]), fsm=sorted({r["fsm"] for r in sp[s]}),
                             ts=sorted(set().union(*(r["ts"] for r in sp[s]))))
        mark_info = dict(one(mark), of=len(marks),
                         others=[one(s) for s in sorted((s for s in sp if s != mark), key=lambda s: (-len(sp[s]), -s))])
    return rows, mark, info, mark_info


def warnings_of(cut, marks, st):
    """Предупреждения о профиле (не запрет): похоже на копии режимов или офис, а не на станок — газа нет ни в одной
    программе или больше половины каналов — шаблон офиса; программ с режимами резки мало."""
    out, why = [], []
    if not any(r["gas"] is not None for r in cut):
        why.append("газ не записан ни в одной программе")
    chans = len(cut) + st["engraving"] + sum(st[k] for k, t in SKIP_TITLES)
    if st["template"] * 2 > chans:
        why.append("шаблон офиса — %d из %d каналов" % (st["template"], chans))
    if why:
        variants = collections.defaultdict(set)
        for r in cut:
            variants[r["fsm"]].add((r["speed"], r["pierce_s"]))
        if all(len(v) == 1 for v in variants.values()):
            why.append("у каждого режима одна скорость и врезка")
        if not marks:
            why.append("гравировки нет")
        out.append("%s — похоже на копии режимов (рабочее место технолога, офис), а не на программы станка: проверьте "
                   "--computer" % ", ".join(why))
    n = _progs(cut)
    if n < FEW_PROGRAMS:
        out.append("программ с режимами резки мало (%d) — скорости ненадёжны" % n)
    return out


def build_profile(folder, computer, since=None, name=None, travel=None, today=None):
    """Папка программ → (профиль станка — проверенный machine.load, разбор для вывода). Нечего считать или плохие
    параметры — StatsError."""
    if not os.path.isdir(folder):
        raise StatsError("нет папки %s" % folder)
    if not computer or not computer.strip():
        raise StatsError("не задан компьютер станка")
    computer = computer.strip()
    if since is not None and not SINCE.match(since):
        raise StatsError("месяц «%s» — нужно ГГГГ-ММ (например 2025-04)" % since)
    if name is not None and not name.strip():
        raise StatsError("имя станка пустое — уберите --name (будет «Станок <компьютер>») или задайте имя")
    if travel is None:
        raise StatsError("холостой ход в программах не записан — задайте --travel, мм/с (замер на станке: длина холостого "
                         "хода / его время по журналу CypCut)")
    if not (isinstance(travel, (int, float)) and math.isfinite(travel) and travel > 0):
        raise StatsError("холостой ход %s мм/с — нужно число больше 0" % travel)
    cut, marks, st, computers = collect(folder, computer, since)
    if not st["files"]:
        raise StatsError("в папке %s нет программ .lxds" % folder)
    same = [c for c in computers if c.casefold() == computer.casefold()]
    if not same:
        top = ", ".join("%s (%d)" % kv for kv in computers.most_common(12))
        raise StatsError("программ, сохранённых на компьютере «%s», нет; есть (компьютер — программ): %s" % (computer, top or "—"))
    computer = max(same, key=lambda c: (computers[c], c))       # имя — как в программах (Windows не различает регистр)
    if not st["programs"]:
        raise StatsError("программ компьютера «%s» с %s нет (раньше — %d, без даты — %d)" % (computer, since, st["before"], st["no_date"]))
    rows, mark, info, mark_info = summarize(cut, marks)
    n = st["programs"]
    if not rows:
        raise StatsError("в %d %s компьютера «%s» нет ни одного режима резки с толщиной (каналы: %s; гравировка %d)" % (
            n, plural(n, "программе", "программах", "программах"), computer,
            ", ".join("%s %d" % (t, st[k]) for k, t in SKIP_TITLES), st["engraving"]))
    warn = warnings_of(cut, marks, st)
    today = today or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=10))).date().isoformat()
    prof = dict(name=name.strip() if name else "Станок %s" % computer, preliminary=True,
                source="%d %s %s%s" % (n, plural(n, "программа", "программы", "программ"), computer, (" с %s" % since) if since else ""),
                updated=today,
                note="скорость реза и врезка — самый частый режим толщины в программах станка (machine_stats); холостой %g мм/с "
                     "задан (--travel); подъём головки на переход и возврат в ноль не известны (0, нет); k_total — подобрать по "
                     "реальному времени%s" % (travel, "".join("; внимание: %s" % w for w in warn)),
                k_total=1.0, travel_mm_s=float(travel), lift_s=0.0, return_to_zero=False, mark_mm_s=mark, cut=rows)
    MC.load(prof)                                       # профиль должен грузиться — иначе это ошибка разбора
    return prof, dict(stats=st, info=info, mark=mark_info, computer=computer, since=since, warnings=warn)


def _sheets(ts):
    """Толщины листов программ с этой гравировкой — для таблицы."""
    return ("листы %s мм" % ", ".join("%g" % t for t in ts)) if ts else "реза в этих программах нет"


def report_text(prof, rep):
    """Таблица для человека: откуда, что пропущено, строка на толщину, гравировка, другие режимы, предупреждения."""
    st = rep["stats"]
    lines = ["программ компьютера %s%s: %d (повторов одного сохранения %d; всего файлов %d, повреждённых %d, с других "
             "компьютеров %d%s)" % (rep["computer"], (" с %s" % rep["since"]) if rep["since"] else "", st["programs"], st["copies"],
                                   st["files"], st["corrupt"], st["other"],
                                   (", раньше %s — %d, без даты — %d" % (rep["since"], st["before"], st["no_date"])) if rep["since"] else "")]
    lines.append("каналы не в счёт: " + ", ".join("%s %d" % (t, st[k]) for k, t in SKIP_TITLES) + "; гравировка %d" % st["engraving"])
    head = ("толщина, мм", "режим (.fsm)", "программ", "скорость, мм/с (м/мин)", "врезка, с", "газ", "подъём, мм", "пара: программ")
    body = []
    for r, i in zip(prof["cut"], rep["info"]):
        body.append(("%g" % r["t"], r["fsm"], str(r["programs"]), "%.1f (%.1f)" % (r["mm_s"], r["mm_s"] * 0.06), "%g" % r["pierce_s"],
                     r["gas"] or "—", "—" if r["lift_mm"] is None else "%g" % r["lift_mm"],
                     "%d из %d%s" % (i["pair_programs"], r["programs"], (", скоростей %d" % i["speeds"]) if i["speeds"] > 1 else "")))
    ws = [max(len(x[j]) for x in [head] + body) for j in range(len(head))]
    for x in [head] + body:
        lines.append("  " + " | ".join(v.ljust(w) for v, w in zip(x, ws)))
    mk = rep["mark"]
    if mk:
        lines.append("гравировка: %.1f мм/с (%.1f м/мин) — %d из %d каналов (%s; %s)" % (
            prof["mark_mm_s"], prof["mark_mm_s"] * 0.06, mk["n"], mk["of"], ", ".join(mk["fsm"]), _sheets(mk["ts"])))
        for o in mk["others"]:                          # в профиле одна скорость гравировки — остальные видно здесь
            lines.append("  ещё гравировка: %.1f мм/с (%.1f м/мин) — %d %s (%s; %s)" % (
                o["speed"], o["speed"] * 0.06, o["n"], plural(o["n"], "канал", "канала", "каналов"), ", ".join(o["fsm"]), _sheets(o["ts"])))
    else:
        lines.append("гравировка: в программах нет — mark_mm_s не известна")
    for r, i in zip(prof["cut"], rep["info"]):
        if i["others"]:
            lines.append("толщина %g: ещё режимы — %s" % (r["t"], ", ".join("«%s» (%d)" % o for o in i["others"])))
    lines.append("холостой %g мм/с — задан (--travel); подъём головки (lift_s) и возврат в ноль — не известны; "
                 "профиль предварительный: %s" % (prof["travel_mm_s"], prof["source"]))
    lines += ["⚠ %s" % w for w in rep.get("warnings") or ()]
    return "\n".join(lines)


def _write(path, prof, keep_name):
    """Профиль → файл (через .tmp). Файл уже есть (main пускает сюда только с --force) и это профиль: keep_name —
    имя станка из прежнего профиля (имя — ключ времени в сводке и станка в Odoo); что из правок калибровки теряется —
    строки для вывода. Не записать — StatsError."""
    lines = []
    if os.path.exists(path):
        try:
            old = MC.load(path)
        except MC.MachineError:
            old = None
        if old is not None:
            if keep_name:
                prof["name"] = old["name"]
            lost = ["%s %s → %s" % (k, MC._show(old.get(k)), MC._show(prof.get(k))) for k in CALIBRATED if old.get(k) != prof.get(k)]
            if lost:
                lines.append("из прежнего профиля не перенесено (--force): " + ", ".join(lost))
    text = json.dumps(prof, ensure_ascii=False, indent=1)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise StatsError("не записать %s: %s" % (path, e.strerror or e))
    return lines + ["→ %s" % path]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m sheet_nest.machine_stats",
                                 description="Предварительный профиль станка по его программам CypCut (.lxds)")
    ap.add_argument("folder", help="папка с программами .lxds (со вложенными)")
    ap.add_argument("--computer", required=True, help="имя компьютера станка (info.xml → SavedBy Computer)")
    ap.add_argument("--travel", type=float, default=None,
                    help="холостой ход, мм/с — обязательно: в программах его нет (замер на станке)")
    ap.add_argument("--since", default=None, help="с какого месяца, ГГГГ-ММ (по времени сохранения программы)")
    ap.add_argument("--name", default=None, help="имя станка в профиле (по умолчанию «Станок <компьютер>»)")
    ap.add_argument("--out", default=None, help="куда записать профиль (JSON); без него — профиль в вывод")
    ap.add_argument("--force", action="store_true", help="перезаписать --out, если он есть (калибровка в нём потеряется)")
    a = ap.parse_args(argv)
    try:
        if a.out and os.path.exists(a.out) and not a.force:
            raise StatsError("%s уже есть — в нём может быть калибровка (%s): запишите в другой файл и сравните или добавьте "
                             "--force" % (a.out, ", ".join(CALIBRATED)))
        prof, rep = build_profile(a.folder, a.computer, a.since, a.name, a.travel)
        print(report_text(prof, rep))
        if a.out:
            for line in _write(a.out, prof, keep_name=a.name is None):
                print(line)
        else:
            print(json.dumps(prof, ensure_ascii=False, indent=1))
    except StatsError as e:
        print("ошибка: %s" % e, file=sys.stderr)
        return 1
    except MC.MachineError as e:                        # профиль не собрался из странных значений — текст, не трассировка
        print("ошибка: профиль не собрался: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
