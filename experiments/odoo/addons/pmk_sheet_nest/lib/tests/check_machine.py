# -*- coding: utf-8 -*-
"""Профили станков (machine.py) и их сборщик по программам (machine_stats.py) — только синтетика: скорости, имена
компьютеров и программы завода в репозиторий не кладутся (он открытый).

    python3 tests/check_machine.py

1) machine.load: новые поля (preliminary, source, updated, note, k_total) — по умолчанию и проверка с понятным текстом
   (без питоновского repr и флагов командной строки); справочные поля строк cut (fsm, programs, gas, lift_mm) — проверены
   и сохранены; толщина дважды — ошибка;
2) estimate_detail: составляющие (рез, врезки, гравировка, холостой с возвратом, подъёмы) — с поправкой k, их сумма =
   total = k × сумма без поправки, estimate = total (профиль без новых полей — как прежде); почему нет времени — «в
   профиле нет толщины 0,65 мм», «нет скорости гравировки», «толщина листа не задана»;
3) сводка run(): machine_s и machine_detail у каждой стратегии (сумма = итогу с точностью округления), предварительный
   профиль — «станок «Х» (предварительно), мин» и «≈», обычный — без них; res.machines — эхо профилей;
4) контракт sheet_nest.job/1: result.json → machines (эхо: name, preliminary, source, updated, note, k_total,
   thicknesses), strategies[].machine_detail, summary.machine_s и summary.machine_detail = строке выбранной стратегии;
   сборка — то же время, что строка плана; плохой профиль (k_total 0, preliminary «да») — config, user=false;
5) machine_stats: толщина из имени режима (в начале, с «мм», дробная; номер сопла — нет; MaterialParams — только если
   совпал с числом в имени); на программах, собранных тут же (программа движка + свои info.xml и Technical/content.xml):
   компьютер, месяц, шаблон офиса, гравировка («грав», «грайв») и её другие скорости, скорость с запятой, врезка по
   ступеням, газ, повторы одного сохранения, странные значения (скорость ≈ 0, врезка < 0, подъём < 0), повреждённые
   файлы (не zip, нет части, плохой XML, DTD с сущностями, UTF-16), предупреждения (копии режимов, мало программ),
   ошибки параметров (--travel обязателен), --out: не поверх без --force, с --force — имя прежнее и что потеряно,
   не записать — «ошибка: …»; профиль грузится machine.load, preliminary=true, source «N программ …».
"""
import sys, os, io, re, json, shutil, zipfile, tempfile, subprocess, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import dxf_writer as DW
from sheet_nest import machine as MC
from sheet_nest import job as J

fails = []
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=ROOT)
ENV.pop("VENT_NESTING_LIB", None)
ENV.pop("SHEET_NEST_FONT", None)


def check(name, cond, detail=""):
    print("%s %-78s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def quiet(*a):
    pass


BASE = dict(name="Синт", travel_mm_s=500, lift_s=0.2, return_to_zero=True, mark_mm_s=250,
            cut=[dict(t=2, mm_s=200, pierce_s=0.3), dict(t=0.65, mm_s=400, pierce_s=0)])


def bad_text(s):
    """Текст ошибки для человека: без флагов командной строки и питоновского repr."""
    return bool(re.search(r"--[a-z]|\{'|None\b|\bError\b|True\b|False\b", s))


# ============================================================================================ 1) load
def unit_load():
    p = MC.load(dict(BASE))
    check("load: без новых полей — preliminary false, k_total 1, справочных нет",
          p["preliminary"] is False and p["k_total"] == 1.0 and "source" not in p and "note" not in p)
    row = dict(t=3, mm_s=120, pierce_s=0.2, fsm="3мм.fsm", programs=12, gas="воздух", lift_mm=12, своё="x")
    p = MC.load(dict(BASE, preliminary=True, source="12 программ X с 2025-04", updated="2026-10-15", note="заметка", k_total=1.25,
                     cut=[row]))
    check("load: новые поля приняты, строка cut со справочными полями — как есть",
          p["preliminary"] is True and p["k_total"] == 1.25 and p["source"].startswith("12 программ") and p["cut"][0] == row)
    p = MC.load(dict(BASE, name=None, preliminary=None, k_total=None, source=None))
    check("load: null у необязательных — как не задано (имя по умолчанию, false, 1)",
          p["name"] == "станок" and p["preliminary"] is False and p["k_total"] == 1.0)
    cases = [("preliminary «да»", dict(preliminary="да"), "preliminary"),
             ("preliminary 1", dict(preliminary=1), "preliminary"),
             ("k_total 0", dict(k_total=0), "k_total"),
             ("k_total −1", dict(k_total=-1), "k_total"),
             ("k_total строкой", dict(k_total="1.2"), "k_total"),
             ("k_total NaN", dict(k_total=float("nan")), "k_total"),
             ("k_total true", dict(k_total=True), "k_total"),
             ("source числом", dict(source=5), "source"),
             ("updated числом", dict(updated=20261015), "updated"),
             ("note списком", dict(note=["a"]), "note"),
             ("name пустое", dict(name="  "), "name"),
             ("name числом", dict(name=7), "name"),
             ("толщина дважды", dict(cut=[dict(t=2, mm_s=1), dict(t=2.0, mm_s=2)]), "дважды"),
             ("cut.programs −1", dict(cut=[dict(t=2, mm_s=1, programs=-1)]), "programs"),
             ("cut.programs 1.5", dict(cut=[dict(t=2, mm_s=1, programs=1.5)]), "programs"),
             ("cut.lift_mm строкой", dict(cut=[dict(t=2, mm_s=1, lift_mm="10")]), "lift_mm"),
             ("cut.fsm числом", dict(cut=[dict(t=2, mm_s=1, fsm=3)]), "fsm"),
             ("cut.gas числом", dict(cut=[dict(t=2, mm_s=1, gas=2)]), "gas")]
    bad = []
    for title, kw, word in cases:
        try:
            MC.load(dict(BASE, **kw))
            bad.append("принят: " + title)
        except MC.MachineError as e:
            if word not in str(e) or bad_text(str(e)) or "профиль станка" not in str(e):
                bad.append("%s: %s" % (title, e))
        except Exception as e:
            bad.append("%s: %s: %s" % (title, type(e).__name__, e))
    check("load: плохие новые поля — MachineError с понятным текстом (%d случаев)" % len(cases), not bad, "; ".join(bad)[:300])
    try:
        MC.load(dict(BASE, k_total=0))
        msg = ""
    except MC.MachineError as e:
        msg = str(e)
    check("текст: «k_total — нужно число больше 0, а не 0»", msg.endswith("k_total — нужно число больше 0, а не 0"), msg)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "лазер.json")
        json.dump(dict(BASE, name=None, preliminary=True), open(path, "w", encoding="utf-8"), ensure_ascii=False)
        p = MC.load(path)
    check("load из файла: имя по умолчанию — имя файла, preliminary true", p["name"] == "лазер" and p["preliminary"] is True)
    i = MC.info(MC.load(dict(BASE, preliminary=True, k_total=1.1, updated="2026-10-15")))
    check("info: эхо профиля — ровно поля и толщины по возрастанию",
          tuple(i) == MC.INFO_KEYS and i["thicknesses"] == [0.65, 2.0] and i["k_total"] == 1.1 and i["source"] is None, str(i))
    check("job.py знает те же поля эха и разбора (MACHINE_KEYS, DETAIL_KEYS)",
          J.MACHINE_KEYS == MC.INFO_KEYS and J.DETAIL_KEYS == MC.DETAIL_KEYS)


# ============================================================================================ 2) estimate_detail
def unit_detail():
    p = MC.load(dict(BASE, k_total=1.25))
    d = MC.estimate_detail(p, 2.0, 10000, 500, 20000, 2000, 30, 40)
    want = dict(cut_s=50.0, pierce_s=9.0, mark_s=2.0, travel_s=44.0, lift_s=8.0)          # без поправки
    check("разбор: рез, врезки, гравировка, холостой с возвратом, подъёмы — каждое × k (1,25)",
          all(abs(d[k] - 1.25 * v) < 1e-9 for k, v in want.items()), str({k: round(d[k], 3) for k in want}))
    check("разбор: сумма составляющих = total = k × сумма без поправки, why нет, ключи — DETAIL_KEYS",
          tuple(d) == MC.DETAIL_KEYS and d["k"] == 1.25 and abs(d["total_s"] - 1.25 * 113.0) < 1e-9 and d["why"] is None and
          abs(sum(d[k] for k in want) - d["total_s"]) < 1e-9, "%.3f" % d["total_s"])
    check("estimate = итог разбора (с k_total)", MC.estimate(p, 2.0, 10000, 500, 20000, 2000, 30, 40) == d["total_s"])
    old = MC.load(dict(BASE))
    t = MC.estimate(old, 2.0, 10000, 500, 20000, 2000, 30, 40)
    check("профиль без k_total — как прежде (10000/200 + 30×0,3 + 500/250 + 22000/500 + 40×0,2)", abs(t - 113.0) < 1e-9, "%s" % t)
    nz = MC.load(dict(BASE, return_to_zero=False))
    check("возврат в ноль не в профиле — холостой без него", abs(MC.estimate_detail(nz, 2, 0, 0, 20000, 2000, 0, 0)["travel_s"] - 40) < 1e-9)
    d = MC.estimate_detail(p, 0.65, 1, 0, 1, 0, 1, 1)
    check("толщина 0,65 есть в профиле — считается (сравнение с допуском)", d["total_s"] is not None)
    whys = [MC.estimate_detail(p, 1.5, 1, 0, 1, 0, 1, 1), MC.estimate_detail(dict(p, mark_mm_s=None), 2, 1, 5, 1, 0, 1, 1),
            MC.estimate_detail(p, None, 1, 0, 1, 0, 1, 1), MC.estimate_detail(None, 2, 1, 0, 1, 0, 1, 1)]
    check("нет времени — составляющие и итог null, почему — по-русски",
          [w["why"] for w in whys] == ["в профиле нет толщины 1,5 мм", "нет скорости гравировки", "толщина листа не задана",
                                       "нет профиля станка"] and all(w["total_s"] is None and w["cut_s"] is None for w in whys),
          str([w["why"] for w in whys]))
    q = MC.load(dict(BASE, cut=[dict(t=0.55, mm_s=500)]))
    check("«в профиле нет толщины 0,65 мм» — запятая", MC.estimate_detail(q, 0.65, 1, 0, 1, 0, 1, 1)["why"] == "в профиле нет толщины 0,65 мм")
    check("без гравировки скорость гравировки не нужна", MC.estimate_detail(dict(p, mark_mm_s=None), 2, 1, 0, 1, 0, 1, 1)["total_s"] is not None)
    r = MC.rounded(MC.estimate_detail(p, 2.0, 12345, 77, 23456, 999, 31, 47))
    check("rounded: секунды до 0,1, k и why — как есть", all(r[k] == round(r[k], 1) for k in MC.DETAIL_KEYS if k.endswith("_s")) and r["k"] == 1.25)


# ============================================================================================ фикстуры
def dxf_plate_marked(path):
    """Пластина 600×400 с 4 отверстиями и риской гравировки."""
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.layer("ГРАВИРОВКА")
    e = doc.entities
    e.lwpolyline([(0, 0), (600, 0), (600, 400), (0, 400)], closed=True)
    for x, y in ((50, 50), (550, 50), (550, 350), (50, 350)):
        e.circle((x, y), 9)
    e.line((100, 200), (300, 200), layer="ГРАВИРОВКА")
    open(path, "wb").write(doc.dxf_bytes())
    return path


PRELIM = dict(name="Лазер А", preliminary=True, source="7 программ ТЕСТ с 2025-04", updated="2026-10-15", note="синтетика",
              k_total=1.25, travel_mm_s=500, lift_s=0.1, return_to_zero=True, mark_mm_s=300,
              cut=[dict(t=2, mm_s=200, pierce_s=0.3, fsm="2.fsm", programs=7, gas="воздух", lift_mm=28)])
PLAIN = dict(name="Лазер Б", travel_mm_s=800, cut=[dict(t=3, mm_s=100, pierce_s=0.5)])
NOMARK = dict(name="Лазер В", travel_mm_s=800, cut=[dict(t=2, mm_s=150)])


# ============================================================================================ 3) сводка run()
def summary(td):
    from sheet_nest.cli import run, summary_text, failed_row
    a = dxf_plate_marked(os.path.join(td, "a.dxf"))
    res, raw, pl, parts = run([dict(path=a, name="Пластина", qty=6)], 1250, 2500, 2, 2, 2.0, log=quiet, compare=True, strategy="safe",
                              machine=[PRELIM, PLAIN, NOMARK])
    S = res["strategies"]
    bad = []
    for n, r in S.items():
        d = r["machine_detail"]["Лазер А"]
        if set(r["machine_s"]) != {"Лазер А", "Лазер Б", "Лазер В"} or r["machine_s"]["Лазер А"] != d["total_s"]:
            bad.append("%s: machine_s %s" % (n, r["machine_s"]))
        s = d["cut_s"] + d["pierce_s"] + d["mark_s"] + d["travel_s"] + d["lift_s"]
        if not (d["k"] == 1.25 and abs(s - d["total_s"]) <= 0.3 and d["mark_s"] > 0 and d["why"] is None):
            bad.append("%s: %s" % (n, d))
        if r["machine_detail"]["Лазер Б"]["why"] != "в профиле нет толщины 2 мм" or r["machine_s"]["Лазер Б"] is not None:
            bad.append("%s: Б %s" % (n, r["machine_detail"]["Лазер Б"]))
        if r["machine_detail"]["Лазер В"]["why"] != "нет скорости гравировки":
            bad.append("%s: В %s" % (n, r["machine_detail"]["Лазер В"]))
    check("сводка: machine_s и machine_detail у всех стратегий; сумма разбора = итог (±0,3 с); почему нет — у каждого",
          not bad and len(S) == 4, "; ".join(bad)[:300])
    d, r0 = S["safe"]["machine_detail"]["Лазер А"], S["safe"]
    cut_s = 1.25 * r0["cut_m"] * 1000 / 200
    check("разбор по строке сводки: рез = k × cut_m / скорость, врезки = k × врезок × 0,3", abs(d["cut_s"] - cut_s) < 0.2 and
          abs(d["pierce_s"] - 1.25 * r0["pierces"] * 0.3) < 0.06, "рез %.1f с против %.1f, врезки %s" % (d["cut_s"], cut_s, d["pierce_s"]))
    check("res.risk: время и разбор — строка выбранной стратегии",
          res["risk"]["machine_s"] == S["safe"]["machine_s"] and res["risk"]["machine_detail"] == S["safe"]["machine_detail"])
    check("res.machines — эхо профилей (предварительный, источник, поправка, толщины)",
          [m["name"] for m in res["machines"]] == ["Лазер А", "Лазер Б", "Лазер В"] and res["machines"][0]["preliminary"] is True and
          res["machines"][1]["preliminary"] is False and res["machines"][0]["k_total"] == 1.25 and res["machines"][0]["thicknesses"] == [2.0]
          and res["machines"][0]["source"] == PRELIM["source"])
    machines = [MC.load(m) for m in (PRELIM, PLAIN, NOMARK)]
    txt = summary_text(list(S.values()), machines)
    line_a = next((l for l in txt.split("\n") if "Лазер А" in l), "")
    line_b = next((l for l in txt.split("\n") if "Лазер Б" in l), "")
    check("текст сводки: «станок «Лазер А» (предварительно), мин» и «≈» у времени",
          line_a.startswith("станок «Лазер А» (предварительно), мин") and line_a.count("≈") == 4, line_a[:90])
    check("текст сводки: обычный профиль — без «(предварительно)» и «≈», нет толщины — «—»",
          line_b.startswith("станок «Лазер Б», мин") and "≈" not in line_b and "предварительно" not in line_b and line_b.count("—") == 4)
    check("текст сводки без профилей (как раньше) — «станок, мин» и «—»", "станок, мин" in summary_text([dict(S["safe"], machine_s={})]))
    fr = failed_row("safe0", "Безопасный, конец у нуля", "нет порядка", 0.1, machines)
    check("строка, которую не построить (общий рез): machine_s и machine_detail — null по каждому станку",
          fr["machine_s"] == {m["name"]: None for m in machines} and fr["machine_detail"] == {m["name"]: None for m in machines})
    out = []
    run([dict(path=a, name="Пластина", qty=6)], 1250, 2500, 2, 2, 2.0, log=out.append, strategy="short", machine=[PRELIM, PLAIN])
    tl = [l for l in out if l.startswith("время:")]
    check("лог без сводки: время по каждому станку — «≈» и откуда у предварительного, почему нет — у другого",
          len(tl) == 2 and "(предварительно) — ≈ " in tl[0] and "с поправкой ×1.25" in tl[0] and PRELIM["source"] in tl[0] and
          tl[1] == "время: станок «Лазер Б» — нет (в профиле нет толщины 2 мм)", " | ".join(tl)[:240])
    return a


# ============================================================================================ 4) контракт
def workdir(base, name, inp, files):
    wd = os.path.join(base, name)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(os.path.join(wd, "in"))
    for src, dst in files:
        shutil.copy(src, os.path.join(wd, dst))
    job = dict(contract=J.CONTRACT, kind="plan", run_id="run-%s" % name, title="2мм станки", sheet=dict(W=1250, L=2500),
               thickness=2.0, strategy="safe", inputs=[dict(file="in/1.dxf", name="Пластина", qty=6, key="part,1")], time_limit_s=600)
    job.update(inp)
    with open(os.path.join(wd, "input.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    return wd


def run_job(wd):
    with open(os.path.join(wd, "run.log"), "w") as log:
        p = subprocess.run([sys.executable, "-m", "sheet_nest.job", wd], stdout=log, stderr=subprocess.STDOUT, env=ENV, cwd=ROOT,
                           timeout=600)
    rd = lambda n: json.load(open(os.path.join(wd, n), encoding="utf-8")) if os.path.exists(os.path.join(wd, n)) else None
    return p.returncode, rd("result.json"), rd("error.json")


def contract(base, a):
    files = [(a, "in/1.dxf")]
    code, r, err = run_job(workdir(base, "plan", dict(machines=[PRELIM, PLAIN]), files))
    check("job plan с профилями: result.json, ok", r is not None and r["ok"] and code == 0, str(err)[:200])
    if not r:
        return
    check("result.json: поля верхнего уровня — RESULT_KEYS (есть machines), summary — SUMMARY_KEYS",
          set(r) == set(J.RESULT_KEYS) and "machines" in r and set(r["summary"]) == set(J.SUMMARY_KEYS))
    m = r["machines"]
    check("machines — эхо: name, preliminary, source, updated, note, k_total, thicknesses",
          [set(x) == set(J.MACHINE_KEYS) for x in m] == [True, True] and
          m[0] == dict(name="Лазер А", preliminary=True, source=PRELIM["source"], updated="2026-10-15", note="синтетика",
                       k_total=1.25, thicknesses=[2.0]) and
          m[1] == dict(name="Лазер Б", preliminary=False, source=None, updated=None, note=None, k_total=1.0, thicknesses=[3.0]),
          json.dumps(m, ensure_ascii=False)[:200])
    bad = []
    for s in r["strategies"]:
        md = s["machine_detail"]
        if set(md) != {"Лазер А", "Лазер Б"} or any(set(v) != set(J.DETAIL_KEYS) for v in md.values()):
            bad.append("%s: %s" % (s["name"], md))
        elif md["Лазер А"]["total_s"] != s["machine_s"]["Лазер А"] or md["Лазер Б"]["why"] != "в профиле нет толщины 2 мм":
            bad.append("%s: %s / %s" % (s["name"], md, s["machine_s"]))
    check("strategies[].machine_detail — разбор по каждому станку, итог = machine_s", not bad, "; ".join(bad)[:240])
    safe = next(s for s in r["strategies"] if s["name"] == "safe")
    check("summary.machine_s и machine_detail = строке выбранной стратегии (safe)",
          r["summary"]["machine_s"] == safe["machine_s"] and r["summary"]["machine_detail"] == safe["machine_detail"],
          "%s / %s" % (r["summary"]["machine_s"], safe["machine_s"]))
    code, r2, err = run_job(workdir(base, "build", dict(machines=[PRELIM, PLAIN], kind="build", strategy="safe0"), files))
    s0 = next(s for s in r["strategies"] if s["name"] == "safe0")
    check("job build safe0: время станков = строке safe0 плана, machines то же",
          r2 is not None and r2["strategies"] is None and r2["summary"]["machine_s"] == s0["machine_s"] and
          r2["summary"]["machine_detail"] == s0["machine_detail"] and r2["machines"] == m, str(err or (r2 and r2["summary"]["machine_s"]))[:200])
    code, r3, err = run_job(workdir(base, "none", dict(kind="build"), files))
    check("без профилей: machines [], summary.machine_s и machine_detail — {}",
          r3 is not None and r3["machines"] == [] and r3["summary"]["machine_s"] == {} and r3["summary"]["machine_detail"] == {})
    for title, prof, word in (("k_total 0", dict(PRELIM, k_total=0), "k_total"), ("preliminary «да»", dict(PRELIM, preliminary="да"), "preliminary")):
        code, r4, err = run_job(workdir(base, "bad", dict(machines=[prof]), files))
        check("плохой профиль (%s): error.json config, user=false, текст про поле" % title,
              r4 is None and err is not None and err["kind"] == "config" and err["user"] is False and word in err["message"]
              and not bad_text(err["message"]), str(err and err["message"])[:160])


# ============================================================================================ 5) machine_stats
# Всё — синтетика: имена режимов, компьютеров, скорости, подпись приложения — не заводские.
INFO = ('<?xml version="1.0" encoding="utf-8"?>\n<PackData>\n\t<DocVersion Major="1"/>\n\t<Application AppName="CypCut" '
        'AppVer="9.9.9.9"/>\n\t<SavedBy User="OPERATOR" UserLangID="1049" Computer="%s" SysLangID="1049" SaveTime="%s"/>\n</PackData>\n')
# «миллиард смехов» в малом: сущность в сущности — разбор её развернул бы; программ CypCut с DTD не бывает
LOL = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE PackData [<!ENTITY a "xxxxxxxxxx"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;'
       '&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>\n<PackData><SavedBy User="&c;" Computer="%s" SaveTime="%s"/>'
       '</PackData>\n')


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def tech(chans):
    """Technical/content.xml: канал — dict(fsm, t (MaterialParams), speed (строкой, как в файле), lift, steps [мс], gas)."""
    x = ['<?xml version="1.0" encoding="utf-8"?>', '<Technical Handle="2" MaterialName="сталь" Thickness="1">', "\t<Channels>",
         '\t\t<Channel ParamFlag="256"/>']
    for k, c in enumerate(chans, 1):
        steps = c.get("steps")
        cam = 'CutGap="0,1" LiftHeight="%s"%s WorkSpeed="%s"' % (c.get("lift", 33), (' PierceStepCount="%d"' % len(steps)) if steps is not None else "",
                                                               c["speed"])
        inner = '<Cut %sGasPressure="1" LaserCurrent="50"/>' % (('GasType="%d" ' % c["gas"]) if c.get("gas") else "")
        for i, ms in enumerate(steps or [], 1):
            inner += '<Pierce%d Height="1" TimeStay="%s"/>' % (i, ms)
        inner += '<Pierce%d Height="1" TimeStay="9999"/>' % (len(steps or []) + 1)         # за PierceStepCount — не в счёт
        x.append('\t\t<Channel ChannelPort="%d" ParamFlag="768" OEM="1"><CamParams %s>%s</CamParams>%s%s</Channel>' % (
            k, cam, inner, ("<MaterialName>%s</MaterialName>" % esc(c["fsm"])) if c.get("fsm") else "",
            ('<MaterialParams MaterialName="сталь" NozzleSpec="1.0" Thickness="%s"/>' % c["t"]) if c.get("t") else ""))
    x += ['\t\t<Channel ChannelPort="9"/>', "\t</Channels>", "</Technical>"]
    return "\n".join(x)


def program(base_raw, path, computer, saved, chans, drop=(), tech_text=None, info_raw=None):
    """Программа = программа движка, у которой info.xml и Technical/content.xml заменены (или выброшены — drop)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    src = zipfile.ZipFile(io.BytesIO(base_raw))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for it in src.infolist():
            if it.filename in ("info.xml", "Technical/content.xml"):
                continue
            z.writestr(it, src.read(it.filename))
        if "info.xml" not in drop:
            z.writestr("info.xml", info_raw if info_raw is not None else INFO % (computer, saved))
        if "Technical/content.xml" not in drop:
            z.writestr("Technical/content.xml", tech_text if tech_text is not None else tech(chans))
    return path


def unit_thickness():
    from sheet_nest.machine_stats import thickness_of
    cases = [("0.7.fsm", 70, 0.7, "в начале имени; MaterialParams 70 — нет"), ("1,2 мм А.fsm", None, 1.2, "запятая"),
             ("2.5мм азот сопло1.2.fsm", 1, 2.5, "в начале; сопло — нет"), ("сс-4мм сопло 2.fsm", None, 4.0, "с «мм» за ним"),
             ("cc-7mm-soplo 1,3.fsm", 7, 7.0, "с «mm»"), ("старое 0.7 сопло 2.fsm", 70, 0.7, "дробное, сопло 2 — нет"),
             ("кис сопло 1.4.fsm", 12, None, "только сопло, MaterialParams не совпал"), ("кис с1мм.fsm", 1, None, "«с1мм» — сопло"),
             ("кис с.5мм.fsm", None, None, "«с.5мм» — сопло"), ("14мм-сопло 5 кис.fsm", 5, 14.0, "в начале"),
             ("лист 2 Ст.fsm", 2, 2.0, "MaterialParams = число в имени"), ("лист 2 Ст.fsm", 3, None, "MaterialParams не совпал"),
             ("Ст лист.fsm", 2, None, "чисел нет — MaterialParams один не в счёт"), ("0.0001 мм.fsm", 2, None, "≈ 0"),
             ("300 серия.fsm", 3, None, "больше T_MAX; 3 в имени нет"), ("серия 300 лист 3.fsm", 3, 3.0, "MaterialParams = 3 в имени"),
             ("сопло-1.4 лист.fsm", 1.4, None, "MaterialParams = номер сопла — нет"), (None, 2, None, "без имени")]
    bad = ["%s (MP %s): %s, а не %s — %s" % (n, mp, thickness_of(n, mp), want, why) for n, mp, want, why in cases
           if thickness_of(n, mp) != want or (want is not None and not isinstance(thickness_of(n, mp), float))]
    check("толщина из имени режима (%d случаев): в начале, с «мм», дробная; сопло — нет; MaterialParams — только "
          "совпавший с числом имени" % len(cases), not bad, "; ".join(bad)[:300])


def quiet_main(argv):
    from sheet_nest import machine_stats as MS
    so, se = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
        code = MS.main(argv)
    return code, so.getvalue(), se.getvalue()


def stats(base, a):
    from sheet_nest.cli import run
    from sheet_nest import machine_stats as MS
    unit_thickness()
    res, raw, pl, parts = run([dict(path=a, name="Пластина", qty=2)], 1250, 2500, 2, 2, 2.0, log=quiet)
    names = set(zipfile.ZipFile(io.BytesIO(raw)).namelist())
    check("основа программ — программа движка с info.xml и Technical/content.xml", {"info.xml", "Technical/content.xml"} <= names)
    d = os.path.join(base, "программы")
    PC, T = "LASER-TEST-1", "2025-%02d-%02dT10:00:00Z"
    mk = lambda name, chans, pc=PC, saved=T % (5, 10), **kw: program(raw, os.path.join(d, name), pc, saved, chans, **kw)
    s12 = lambda sp, **kw: dict(fsm="1.2 мм А.fsm", t=1.2, speed=sp, lift=20, gas=3, **kw)
    grav = dict(fsm="гравировка Т.fsm", speed="500", lift=15, gas=3)
    mk("01.10/p1.lxds", [s12("433.333"), grav], saved=T % (5, 1))
    mk("01.10/p2.lxds", [s12("433.333"), grav], saved=T % (5, 2))
    mk("02.10/p3.lxds", [s12("433.333")], saved=T % (5, 3))
    mk("02.10/p4.lxds", [s12("433.333333")], saved=T % (5, 4))                  # та же скорость 433,3 после округления
    mk("03.10/p5.lxds", [s12("383.333")], saved=T % (5, 5))
    mk("03.10/p6.lxds", [s12("383.333")], saved=T % (5, 6))
    for k in range(3):                                                           # копии p5 в других папках — не в счёт
        shutil.copy(os.path.join(d, "03.10/p5.lxds"), os.path.join(d, "01.10" if k == 0 else "02.10", "копия%d.lxds" % k))
    s25 = dict(fsm="2.5мм воздух Б.fsm", t=2.5, speed="120,46", lift=12, steps=[200, 300])
    mk("04.10/p7.lxds", [s25], saved=T % (6, 1))
    mk("04.10/p8.lxds", [dict(s25, gas=3)], saved=T % (6, 2))
    mk("04.10/p9.lxds", [dict(s25, gas=3)], saved=T % (6, 3))
    mk("04.10/p10.lxds", [dict(fsm="2.5мм кис Б.fsm", t=2.5, speed="50", lift=25, steps=[2000], gas=2)], saved=T % (6, 4))
    mk("05.10/p11.lxds", [dict(fsm="0.7.fsm", t=70, speed="550", lift=25, gas=3)], saved=T % (7, 1))        # в MaterialParams 70
    mk("05.10/p12.lxds", [dict(fsm="лист 2 Ст.fsm", t=2, speed="240", lift=25, gas=2)], saved=T % (7, 2))   # MaterialParams = 2 в имени
    mk("05.10/p13.lxds", [dict(fsm="грайв тест.fsm", speed="450", lift=15)], saved=T % (7, 3))
    mk("05.10/p14.lxds", [dict(speed="100", lift=10, t=5), dict(speed="200", lift=25, t=4)], saved=T % (7, 4))   # шаблон офиса и без режима
    mk("05.10/ПРОГ.LXDS", [dict(fsm="1,2мм старый.fsm", speed="300", lift=25)], saved=T % (7, 5))            # 1,2 — второй режим толщины
    mk("05.10/p15.lxds", [dict(fsm="старое 0.7 сопло 2.fsm", t=70, speed="550", lift=25, gas=3),             # 0,7 — не 70
                          dict(fsm="Ст3 лист.fsm", t=2, speed="240"),                                       # толщина неизвестна
                          dict(fsm="кис сопло 1.4.fsm", t=12, speed="20", gas=2)], saved=T % (7, 6))       # толщина неизвестна
    mk("05.10/p16.lxds", [dict(fsm="сс-4мм сопло 2.fsm", speed="90", lift=-5, gas=2),                      # подъём < 0 — не в справку
                          dict(fsm="3 мм Х.fsm", t=3, speed="0.01"),                                        # скорость ≈ 0
                          dict(fsm="3 мм Y.fsm", t=3, speed="100", steps=[-500]),                           # врезка < 0
                          dict(fsm="0.0001 мм.fsm", t=2, speed="100")], saved=T % (7, 7))                  # толщина ≈ 0
    for k in range(5):
        mk("офис/o%d.lxds" % k, [s12("300")], pc="XE-OFFICE")                    # другой компьютер
        mk("старые/s%d.lxds" % k, [s12("200")], saved="2025-03-%02dT10:00:00Z" % (k + 1))   # раньше --since
    open(os.path.join(d, "05.10", "битый.lxds"), "wb").write(b"PK\x03\x04 not a zip")
    mk("05.10/без_техники.lxds", [], drop=("Technical/content.xml",))
    mk("05.10/плохой_xml.lxds", [], tech_text="<Technical><Channels>")
    mk("05.10/сущности.lxds", [s12("433.333")], info_raw=LOL % (PC, T % (7, 8)))
    mk("05.10/utf16.lxds", [s12("433.333")], info_raw=(INFO % (PC, T % (7, 9))).replace("utf-8", "utf-16").encode("utf-16"))
    open(os.path.join(d, "05.10", "заметка.txt"), "w").write("не программа")
    try:
        MS.read_program(os.path.join(d, "05.10", "сущности.lxds"))
        lol = "прочитана"
    except ValueError as e:
        lol = str(e)
    check("DTD с сущностями — не разбирается (ValueError, файл повреждён)", "DTD" in lol, lol[:120])
    prof, rep = MS.build_profile(d, "laser-test-1", "2025-04", travel=700, today="2026-10-15")
    st = rep["stats"]
    rows = {r["t"]: r for r in prof["cut"]}
    check("machine_stats: файлов 35, повреждённых 5 (не zip, нет части, плохой XML, DTD, UTF-16), других компьютеров 5, "
          "раньше месяца 5, копий 3, программ 17",
          (st["files"], st["corrupt"], st["other"], st["before"], st["copies"], st["programs"]) == (35, 5, 5, 5, 3, 17), str(dict(st)))
    check("толщины 0,7 (не 70), 1,2, 2 (MaterialParams = число в имени), 2,5, 4 (сс-4мм); шаблон 1, без режима 1, толщина "
          "неизвестна 3, скорость ≈ 0 — 1, врезка < 0 — 1",
          sorted(rows) == [0.7, 1.2, 2.0, 2.5, 4.0] and (st["template"], st["no_fsm"], st["no_thickness"], st["no_speed"],
                                                          st["bad_pierce"]) == (1, 1, 3, 1, 1), "%s %s" % (sorted(rows), dict(st)))
    r12 = rows.get(1.2, {})
    check("1,2: самый частый режим «1.2 мм А.fsm» (6 программ против 1), пара 433,3 (4 из 6; копии 383,3 не в счёт)",
          (r12.get("fsm"), r12.get("programs"), r12.get("mm_s"), r12.get("pierce_s"), r12.get("gas"), r12.get("lift_mm")) ==
          ("1.2 мм А.fsm", 6, 433.3, 0.0, "воздух", 20.0), str(r12))
    r25 = rows.get(2.5, {})
    check("2,5: «2.5мм воздух Б.fsm» (3 против 1), скорость «120,46» → 120,5, врезка 0,2 + 0,3 = 0,5 с (ступень за счётом — "
          "нет), газ — самый частый из заданных", (r25.get("fsm"), r25.get("programs"), r25.get("mm_s"), r25.get("pierce_s"),
                                                   r25.get("gas"), r25.get("lift_mm")) == ("2.5мм воздух Б.fsm", 3, 120.5, 0.5, "воздух", 12.0), str(r25))
    r07, r4 = rows.get(0.7, {}), rows.get(4.0, {})
    check("2: газ 2 — кислород; 0,7: 550 (ничья режимов — сохранённый позже); 4: подъём < 0 — пусто, а не ошибка профиля",
          rows.get(2.0, {}).get("gas") == "кислород" and r07.get("mm_s") == 550.0 and r07.get("fsm") == "старое 0.7 сопло 2.fsm" and
          (r4.get("fsm"), r4.get("mm_s"), r4.get("lift_mm"), r4.get("gas")) == ("сс-4мм сопло 2.fsm", 90.0, None, "кислород"), "%s %s" % (r07, r4))
    mk_ = rep["mark"]
    check("гравировка («грав», «грайв») — не толщина; mark_mm_s — самая частая (500: 2 из 3), другая скорость — в разборе",
          prof["mark_mm_s"] == 500.0 and st["engraving"] == 3 and mk_["n"] == 2 and mk_["of"] == 3 and mk_["ts"] == [1.2] and
          [(o["speed"], o["n"], o["fsm"], o["ts"]) for o in mk_["others"]] == [(450.0, 1, ["грайв тест.fsm"], [])], str(mk_))
    check("профиль: preliminary, source «17 программ LASER-TEST-1 с 2025-04», updated, k_total 1, холостой 700, подъём 0",
          prof["preliminary"] is True and prof["source"] == "17 программ LASER-TEST-1 с 2025-04" and prof["updated"] == "2026-10-15"
          and prof["k_total"] == 1.0 and prof["travel_mm_s"] == 700.0 and prof["lift_s"] == 0.0 and prof["return_to_zero"] is False
          and prof["name"] == "Станок LASER-TEST-1", prof["source"])
    check("предупреждение: программ с режимами резки мало (15) — в выводе и в note; копий режимов — нет (газ есть)",
          rep["warnings"] == ["программ с режимами резки мало (15) — скорости ненадёжны"] and "внимание: программ с режимами" in prof["note"],
          str(rep["warnings"]))
    p = MC.load(prof)
    check("профиль грузится machine.load, справочные поля строк на месте", p["cut"][0].get("fsm") == "старое 0.7 сопло 2.fsm" and p["preliminary"])
    txt = MS.report_text(prof, rep)
    check("таблица: строка на толщину, гравировка и её другая скорость, другие режимы толщины, пропуски, предупреждение",
          "1.2 мм А.fsm" in txt and "433.3 (26.0)" in txt and "гравировка: 500.0" in txt and "листы 1.2 мм" in txt and
          "ещё гравировка: 450.0 мм/с (27.0 м/мин) — 1 канал (грайв тест.fsm; реза в этих программах нет)" in txt and
          "«1,2мм старый.fsm» (1)" in txt and "«2.5мм кис Б.fsm» (1)" in txt and "«0.7.fsm» (1)" in txt and "шаблон офиса 1" in txt and
          "врезка меньше 0 1" in txt and "повреждённых 5" in txt and "\n⚠ программ с режимами резки мало (15)" in txt,
          txt.split("\n")[0][:120])
    prof2, rep2 = MS.build_profile(d, PC, None, name="Лазер тест", travel=800, today="2026-10-15")
    check("без --since: старые программы в счёте (1,2 → 200 мм/с: 5 программ против 4), холостой 800, имя",
          {r["t"]: r for r in prof2["cut"]}[1.2]["mm_s"] == 200.0 and prof2["travel_mm_s"] == 800.0 and prof2["name"] == "Лазер тест"
          and prof2["source"] == "22 программы LASER-TEST-1", prof2["source"])
    # копии режимов: газа нет, у режима одна скорость, гравировки нет — предупреждение (не запрет)
    dc = os.path.join(base, "копии")
    for k in range(3):
        program(raw, os.path.join(dc, "c%d.lxds" % k), "TECH-PC", T % (8, k + 1), [dict(fsm="1 мм К.fsm", t=1, speed="300")])
    prof3, rep3 = MS.build_profile(dc, "TECH-PC", travel=700, today="2026-10-15")
    w = rep3["warnings"]
    check("похоже на копии режимов — предупреждение в выводе и в note, профиль всё равно собран",
          len(w) == 2 and w[0].startswith("газ не записан ни в одной программе, у каждого режима одна скорость и врезка, гравировки нет"
                                          " — похоже на копии режимов") and "мало (3)" in w[1] and prof3["note"].count("внимание:") == 2, str(w))
    # одна программа со странными значениями (врезка < 0, скорость ≈ 0) — не трассировка, а «ошибка: …»
    ds = os.path.join(base, "странные")
    program(raw, os.path.join(ds, "s.lxds"), "PC1", T % (8, 1), [dict(fsm="2 мм Ж.fsm", t=2, speed="200", steps=[-500], gas=3),
                                                                 dict(fsm="2 мм З.fsm", t=2, speed="0.01", gas=3)])
    code, out, err = quiet_main([ds, "--computer", "PC1", "--travel", "700"])
    check("одна программа со странными значениями: выход 1, «ошибка: … нет ни одного режима резки» со счётом каналов",
          code == 1 and err.startswith("ошибка: в 1 программе компьютера «PC1» нет ни одного режима резки") and
          "врезка меньше 0 1" in err and "без скорости 1" in err and "Traceback" not in err, err[:200])
    errs = []
    for kw, word in ((dict(computer="НЕТ-ТАКОГО"), "XE-OFFICE (5)"), (dict(since="2025/04"), "ГГГГ-ММ"), (dict(since="2027-01"), "с 2027-01 нет"),
                     (dict(folder=os.path.join(base, "нет")), "нет папки"), (dict(travel=0), "холостой"),
                     (dict(travel=None), "задайте --travel"), (dict(name="  "), "имя станка пустое")):
        args = dict(folder=d, computer=PC, since="2025-04", travel=700, name=None)
        args.update(kw)
        try:
            MS.build_profile(args["folder"], args["computer"], args["since"], name=args["name"], travel=args["travel"])
            errs.append("принято: %s" % kw)
        except MS.StatsError as e:
            if word not in str(e):
                errs.append("%s: %s" % (kw, e))
    check("ошибки параметров — понятный текст (чужой компьютер — список тех, что есть; месяц; папка; холостой не задан или 0; "
          "пустое имя)", not errs, "; ".join(errs)[:300])
    empty = os.path.join(base, "пусто"); os.makedirs(empty)
    try:
        MS.build_profile(empty, PC, travel=700)
        msg = ""
    except MS.StatsError as e:
        msg = str(e)
    check("пустая папка — «нет программ .lxds»", "нет программ .lxds" in msg, msg)
    out_ = os.path.join(base, "профиль.json")
    code, so, se = quiet_main([d, "--computer", PC, "--since", "2025-04", "--name", "Лазер тест", "--travel", "700", "--out", out_])
    p = MC.load(out_) if os.path.exists(out_) else {}
    check("командная строка --out: выход 0, таблица, профиль записан и грузится, updated — сегодня",
          code == 0 and "толщина, мм" in so and p.get("preliminary") is True and p.get("name") == "Лазер тест" and
          bool(re.match(r"^\d{4}-\d{2}-\d{2}$", p.get("updated") or "")) and not os.path.exists(out_ + ".tmp"), se[:120])
    code, so, se = quiet_main([d, "--computer", PC, "--since", "2025-04", "--travel", "700", "--out", out_])
    check("--out уже есть, без --force: выход 1, «уже есть … --force», файл не тронут",
          code == 1 and "уже есть" in se and "--force" in se and MC.load(out_)["name"] == "Лазер тест", se[:160])
    cal = dict(json.load(open(out_, encoding="utf-8")), k_total=1.3, lift_s=0.2, preliminary=False)
    json.dump(cal, open(out_, "w", encoding="utf-8"), ensure_ascii=False)
    code, so, se = quiet_main([d, "--computer", PC, "--since", "2025-04", "--travel", "700", "--out", out_, "--force"])
    p = MC.load(out_)
    check("--force без --name: имя станка — из прежнего профиля, потерянная калибровка — в выводе",
          code == 0 and p["name"] == "Лазер тест" and p["k_total"] == 1.0 and p["preliminary"] is True and
          "не перенесено (--force): lift_s 0.2 → 0, k_total 1.3 → 1, preliminary false → true" in so, (so + se)[-240:])
    code, so, se = quiet_main([d, "--computer", PC, "--travel", "700", "--out", out_, "--force", "--name", "Другой"])
    check("--force с --name — имя новое", code == 0 and MC.load(out_)["name"] == "Другой", se[:120])
    nowhere = os.path.join(base, "нет", "x.json")
    code, so, se = quiet_main([d, "--computer", PC, "--travel", "700", "--out", nowhere])
    check("--out не записать: выход 1, «ошибка: не записать …», без трассировки и без .tmp",
          code == 1 and se.startswith("ошибка: не записать") and "Traceback" not in se and not os.path.exists(nowhere + ".tmp"), se[:160])
    code, so, se = quiet_main([d, "--computer", PC])
    check("без --travel: выход 1, «ошибка: холостой ход в программах не записан — задайте --travel»",
          code == 1 and se.startswith("ошибка: холостой ход в программах не записан — задайте --travel"), se[:160])
    keep = MS.build_profile

    def broken(*a, **kw):
        raise MC.MachineError("профиль станка: cut.mm_s (t=1) — нужно число больше 0, а не 0")
    MS.build_profile = broken
    try:
        code, so, se = quiet_main([d, "--computer", PC, "--travel", "700"])
    finally:
        MS.build_profile = keep
    check("профиль не собрался (MachineError) — «ошибка: профиль не собрался: …», выход 1",
          code == 1 and se.startswith("ошибка: профиль не собрался: профиль станка"), se[:160])
    code, so, se = quiet_main([d, "--computer", "НЕТ", "--travel", "700"])
    check("командная строка: чужой компьютер — выход 1, «ошибка: …», без трассировки",
          code == 1 and se.startswith("ошибка: программ, сохранённых на компьютере «НЕТ», нет"), se[:120])
    p = subprocess.run([sys.executable, "-c", "import sys; from sheet_nest import machine_stats; "
                        "print('numpy' in sys.modules, 'vent_nesting' in sys.modules)"], env=ENV, cwd=ROOT, capture_output=True, text=True)
    check("machine_stats — только стандартная библиотека (без numpy и vent_nesting)", p.stdout.split() == ["False", "False"],
          " ".join(p.stdout.split()) + p.stderr.strip()[-200:])
    p = subprocess.run([sys.executable, "-m", "sheet_nest.machine_stats", d, "--computer", PC, "--since", "2025-04", "--travel", "700"],
                       env=ENV, cwd=ROOT, capture_output=True, text=True)
    js = p.stdout[p.stdout.find("\n{") + 1:] if "\n{" in p.stdout else ""
    try:
        jp = json.loads(js)
    except ValueError:
        jp = {}
    check("python -m sheet_nest.machine_stats без --out: таблица и профиль JSON в вывод",
          p.returncode == 0 and jp.get("source") == "17 программ LASER-TEST-1 с 2025-04",
          "выход %s%s" % (p.returncode, (", " + p.stderr.strip()[-160:]) if p.returncode else ""))


def main():
    import time
    t0 = time.time()
    unit_load()
    unit_detail()
    base = tempfile.mkdtemp(prefix="sheet_nest_machine_")
    try:
        a = summary(base)
        contract(base, a)
        stats(base, a)
    finally:
        if not fails:
            shutil.rmtree(base, ignore_errors=True)
        else:
            print("папка оставлена: %s" % base)
    print("(%.0f с)" % (time.time() - t0))
    print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
