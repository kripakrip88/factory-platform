# -*- coding: utf-8 -*-
"""Контракт sheet_nest.job/1 (ERP.md, «Контракт» и «Что сделать до переноса») — как его вызывает Odoo: отдельный процесс
`python -m sheet_nest.job <папка>` (один раз — ровно как pmk_vent_nest: sh -c 'nohup … > run.log 2>&1 &').

    python3 tests/check_job.py [КАТАЛОГ_ОБРАЗЦОВ]     (по умолчанию ~/Downloads/vent_nesting/samples; нет — без .lxds-образца)

1) plan и build на синтетическом DXF (fixtures/dxf_writer): result.json — ровно поля контракта (все уровни), run_id
   эхом, ключи деталей (key) на месте, сводка — 4 стратегии по порядку (холостой выбранной = summary.idle_m), сборка —
   без сводки, те же листы, что у плана; файлы out/ есть; лог — в run.log (его пишет перенаправление, не job.py);
2) plan и build на образце .lxds (m8_plates), общий рез на синтетике (applied.coedge), мост (и bridge: {} — мост со
   значениями по умолчанию), имена-номера («2») против имён файлов Odoo (in/2.dxf): перемычки и подписи — только по
   имени; подписи (если есть таблица шрифта), в том числе у DXF из двух контуров по имени Odoo; добивка остатков листа
   (fill → result.json fill и parts[].fill, предел max) с закрытием разрыва внешнего контура (heal_gap_mm), без
   добивки — fill = [], без heal_gap_mm разрыв — ошибка входа с номером входа;
3) ошибки: битый DXF (имя детали и номер входа, без «Ð°Ð±Ð²») и .lxds (input, без английского), деталь больше листа,
   мост + общий рез, чужое имя у перемычек, отступ подписи < 0, количество 0 и миллион (params, user), не тот contract /
   kind / стратегия / лишнее поле / DXF без qty / повтор имени DXF / предел времени 1e10 (params, не user), подписи без
   шрифта, плохой профиль станка, нет vent_nesting, файл не читается (config), SIGTERM посреди расчёта и в первые
   0,25 с (cancelled, в т. ч. во время импорта numpy), крошечный предел времени (timeout), сторож при застрявшем
   процессе (timeout), C держит GIL — faulthandler снимает процесс, сбой движка (engine, trace ≤ 4000); run_id и
   input {index, key} — в error.json;
4) атомарность: progress.json всегда читается целиком, result.json — последний файл, без .tmp, старый итог из той же
   папки убирается при старте;
5) run(): входы {path, name, qty, key} — имя и количество не из имени файла, без ложного «количество не указано»;
   --qty снимает ложное предупреждение, --qty ИМЯ=0 — отказ, а не трассировка; повтор имён — уникальные имена
   (X, X, «X (2)»); перемычки по имени со знаками &"; прогресс по этапам и стратегиям «k/4»; у раскладок W, L,
   util_pct (= загрузке в файле), cut_m, mark_m, pierces, mass_kg; картинка не нарисовалась — предупреждение, программа
   и отчёт есть; общий рез не применён — причина в warnings, requested ≠ applied; сводка: у одной стратегии не
   построился общий рез — не построена только её строка (п. 8); ошибки — SheetNestError без флагов командной строки
   и без питоновского repr; libpath — соседний аддон.
"""
import sys, os, io, json, time, shutil, signal, tempfile, subprocess, contextlib, re, shlex
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import dxf_writer as DW
from sheet_nest import job as J
from sheet_nest.libpath import LIB

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/vent_nesting/samples")
FONT = next((p for p in (os.environ.get("SHEET_NEST_FONT"), os.path.expanduser("~/Downloads/vent_nesting/labels/gost_type_a_strokes.json"))
             if p and os.path.exists(p) and p.endswith(".json")), None)
fails = []
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=ROOT)
ENV.pop("VENT_NESTING_LIB", None)
ENV.pop("SHEET_NEST_FONT", None)


def check(name, cond, detail=""):
    print("%s %-74s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


# ============================================================================================ фикстуры
def dxf_plate(path, w=600, h=400, holes=4, slot=True):
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    e = doc.entities
    e.lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], closed=True)
    for x, y in ((50, 50), (w - 50, 50), (w - 50, h - 50), (50, h - 50))[:holes]:
        e.circle((x, y), 9)
    if slot:
        e.lwpolyline([(w / 2 - 50, h / 2 - 10, 0), (w / 2 + 50, h / 2 - 10, 1), (w / 2 + 50, h / 2 + 10, 0), (w / 2 - 50, h / 2 + 10, 1)],
                     closed=True)
    open(path, "wb").write(doc.dxf_bytes())
    return path


def dxf_grille(path):
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.layer("ГРАВИРОВКА")
    e = doc.entities
    e.lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], closed=True)
    for k in range(3):
        y = 60 + 80 * k
        e.lwpolyline([(60, y + 30), (60, y), (440, y), (440, y + 30)], closed=False)
        e.line((5, y + 29), (40, y + 29), layer="ГРАВИРОВКА")
    open(path, "wb").write(doc.dxf_bytes())
    return path


def dxf_washer(path, r=40, r0=10):
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.entities.circle((0, 0), r)
    doc.entities.circle((0, 0), r0)
    open(path, "wb").write(doc.dxf_bytes())
    return path


def workdir(base, name, inp, files=()):
    """Папка прогона как у Odoo: in/ (входы), input.json."""
    wd = os.path.join(base, name)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(os.path.join(wd, "in"))
    for src, dst in files:
        shutil.copy(src, os.path.join(wd, dst))
    job = dict(contract=J.CONTRACT, kind="plan", run_id="run-%s" % name, engine_lib=ROOT, vent_nesting_lib=LIB, title="2мм тест",
               inputs=[], sheet=dict(W=1250, L=2500), gap=2, edge=2, thickness=2.0, strategy="short", compare=True, coedge=False,
               bridge=None, small_mm=100, microjoints=[], labels=None, label_opts=dict(H=15, H_min=10, margin=3), font=None,
               machines=[], time_limit_s=600)
    job.update(inp)
    if job.get("compare") is not None and "compare" not in inp:
        job["compare"] = job["kind"] == "plan"
    with open(os.path.join(wd, "input.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    return wd


def run_job(wd, timeout=600):
    """Как Odoo: отдельный процесс, лог — перенаправлением в run.log. Вернуть (код выхода, result | None, error | None)."""
    with open(os.path.join(wd, "run.log"), "w") as log:
        p = subprocess.run([sys.executable, "-m", "sheet_nest.job", wd], stdout=log, stderr=subprocess.STDOUT, env=ENV,
                           cwd=ROOT, timeout=timeout)
    return p.returncode, _read(wd, "result.json"), _read(wd, "error.json")


def _read(wd, name):
    p = os.path.join(wd, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


# ============================================================================================ проверка формы result.json
def validate_result(r, kind, compare):
    """Поля result.json по контракту (ERP.md + уточнения job.py). Вернуть список расхождений."""
    bad = []

    def keys(obj, want, where):
        if not isinstance(obj, dict):
            bad.append("%s — не объект" % where); return
        if set(obj) != set(want):
            bad.append("%s: лишние %s, нет %s" % (where, sorted(set(obj) - set(want)), sorted(set(want) - set(obj))))
    keys(r, J.RESULT_KEYS, "result")
    if bad:
        return bad
    if r["contract"] != J.CONTRACT or r["kind"] != kind:
        bad.append("contract/kind %r/%r" % (r["contract"], r["kind"]))
    keys(r["engine"], ("sheet_nest", "vent_nesting", "python"), "engine")
    if not re.match(r"^\d+\.\d+\.\d+$", r["engine"]["sheet_nest"] or ""):
        bad.append("engine.sheet_nest %r" % r["engine"]["sheet_nest"])
    if not isinstance(r["ok"], bool):
        bad.append("ok не bool")
    keys(r["requested"], ("strategy", "coedge", "bridge", "labels"), "requested")
    keys(r["applied"], ("strategy", "coedge", "bridge_groups", "labels_ok", "labels_failed"), "applied")
    keys(r["files"], ("lxds", "png_layouts", "png_order", "report"), "files")
    keys(r["summary"], J.SUMMARY_KEYS, "summary")
    if compare:
        if not isinstance(r["strategies"], list) or [s.get("name") for s in r["strategies"]] != ["short", "safe", "safe0", "hill"]:
            bad.append("strategies: %r" % ([s.get("name") for s in r["strategies"]] if isinstance(r["strategies"], list) else r["strategies"]))
        else:
            for s in r["strategies"]:
                keys(s, J.STRATEGY_KEYS, "strategies[%s]" % s["name"])
                if not s["error"]:
                    keys(s["danger"], J.DANGER_KEYS, "strategies[%s].danger" % s["name"])
                    for k in ("sheets", "cut_m", "idle_m", "return_m", "pierces"):
                        if not isinstance(s[k], (int, float)) or isinstance(s[k], bool):
                            bad.append("strategies[%s].%s = %r" % (s["name"], k, s[k]))
                if not isinstance(s["warnings"], list) or not isinstance(s["machine_s"], dict):
                    bad.append("strategies[%s]: warnings/machine_s" % s["name"])
    elif r["strategies"] is not None:
        bad.append("strategies у сборки не null")
    for l in r["layouts"]:
        keys(l, J.LAYOUT_KEYS, "layouts[%s]" % l.get("index"))
    if [l["index"] for l in r["layouts"]] != list(range(1, len(r["layouts"]) + 1)):
        bad.append("layouts: номера")
    for c in r["checks"]:
        keys(c, ("name", "status", "detail"), "checks")
        if c.get("status") not in ("ok", "warn", "fail"):
            bad.append("checks: status %r" % c.get("status"))
    if r["ok"] != all(c["status"] != "fail" for c in r["checks"]):
        bad.append("ok не сходится с checks")
    for p in r["parts"]:
        keys(p, J.PART_KEYS, "parts")
        if not isinstance(p.get("fill"), bool):
            bad.append("parts[].fill не bool")
    if not isinstance(r["fill"], list):
        bad.append("fill — не список")
    else:
        for f in r["fill"]:
            keys(f, J.FILL_KEYS, "fill")
    keys(r["timing"], ("total_s", "route_s"), "timing")
    if not isinstance(r["warnings"], list) or not isinstance(r["labels"], list):
        bad.append("warnings/labels — не списки")
    if r["summary"]["sheets"] != sum(l["amount"] for l in r["layouts"]):
        bad.append("summary.sheets ≠ Σ amount")
    cut = sum(l["cut_m"] * l["amount"] for l in r["layouts"])
    if abs(cut - r["summary"]["cut_m"]) > 0.02:
        bad.append("Σ cut_m раскладок %.3f ≠ summary %.3f" % (cut, r["summary"]["cut_m"]))
    if sum(l["pierces"] * l["amount"] for l in r["layouts"]) != r["summary"]["pierces"]:
        bad.append("Σ pierces раскладок ≠ summary")
    return bad


def files_ok(wd, r):
    return all(v is None or os.path.isfile(os.path.join(wd, v)) for v in r["files"].values()) and r["files"]["lxds"] is not None


# ============================================================================================ 1) plan и build, синтетика
def synthetic(base):
    t0 = time.time()
    td = os.path.join(base, "_src")
    os.makedirs(td, exist_ok=True)
    a = dxf_plate(os.path.join(td, "a.dxf"))
    b = dxf_grille(os.path.join(td, "b.dxf"))
    inputs = [dict(file="in/1.dxf", name="Пластина 600x400_12шт", qty=5, key="pmk.laser.job.part,57"),
              dict(file="in/2.dxf", name="Решётка", qty=7, key="pmk.laser.job.part,58"),
              dict(file="in/3.dxf", name="Решётка Б", qty=2, key="pmk.laser.job.part,59")]
    files = [(a, "in/1.dxf"), (b, "in/2.dxf"), (b, "in/3.dxf")]
    # как Odoo: sh -c 'nohup python … > run.log 2>&1 &', опрос папки
    wd = workdir(base, "plan", dict(inputs=inputs, kind="plan", strategy="safe"), files)
    log = os.path.join(wd, "run.log")
    subprocess.run(["sh", "-c", "nohup %s -m sheet_nest.job %s > %s 2>&1 &" % (shlex.quote(sys.executable), shlex.quote(wd), shlex.quote(log))],
                   env=ENV, cwd=ROOT)
    end = time.time() + 300
    while time.time() < end and not os.path.exists(os.path.join(wd, "result.json")) and not os.path.exists(os.path.join(wd, "error.json")):
        time.sleep(0.1)
    time.sleep(0.3)
    r, err = _read(wd, "result.json"), _read(wd, "error.json")
    check("plan (как Odoo: nohup … > run.log &): result.json, error.json нет", r is not None and err is None, str(err)[:200])
    if r is None:
        return None
    bad = validate_result(r, "plan", True)
    check("plan: result.json — ровно поля контракта на всех уровнях", not bad, "; ".join(bad)[:300])
    check("plan: run_id эхом, ok, все проверки программы", r["run_id"] == "run-plan" and r["ok"],
          "%r, ok=%s" % (r["run_id"], r["ok"]))
    names = [(p["name"], p["qty"], p["key"]) for p in r["parts"]]
    check("plan: детали — имена как заданы (из имени ничего), количество, ключи",
          names == [("Пластина 600x400_12шт", 5, "pmk.laser.job.part,57"), ("Решётка", 7, "pmk.laser.job.part,58"),
                    ("Решётка Б", 2, "pmk.laser.job.part,59")], str(names))
    s_safe = next(s for s in r["strategies"] if s["name"] == "safe")
    check("plan: холостой строки выбранной стратегии = summary.idle_m (без двойного округления)",
          s_safe["idle_m"] == r["summary"]["idle_m"], "%s / %s" % (s_safe["idle_m"], r["summary"]["idle_m"]))
    check("plan: без ложного «количество не указано»", not any("количество не указано" in w for w in r["warnings"]), str(r["warnings"])[:200])
    check("plan: файлы out/ (программа, 2 картинки, отчёт) на месте", files_ok(wd, r) and all(r["files"].values()), str(r["files"]))
    check("plan: лог в run.log (stdout движка), сам job.py run.log не трогает", "result.json" in open(log, encoding="utf-8").read())
    pid = open(os.path.join(wd, "pid")).read().strip()
    check("plan: pid — число", pid.isdigit(), pid)
    prog = _read(wd, "progress.json")
    check("plan: progress.json — {stage, text}, этап из списка", prog and set(prog) == {"stage", "text"} and prog["stage"] in J.STAGES, str(prog))
    names = sorted(os.listdir(wd)) + sorted("out/" + f for f in os.listdir(os.path.join(wd, "out")))
    check("plan: нет .tmp", not [f for f in names if f.endswith(".tmp")], str(names))
    mt = os.path.getmtime(os.path.join(wd, "result.json"))
    later = [f for f in names if f not in ("run.log", "result.json") and os.path.isfile(os.path.join(wd, f))
             and os.path.getmtime(os.path.join(wd, f)) > mt]
    check("plan: result.json — последний файл прогона", not later, str(later))
    check("plan: requested = applied (без общего реза и моста)", r["requested"]["strategy"] == r["applied"]["strategy"] == "safe" and
          r["requested"]["coedge"] is False and r["applied"]["coedge"] is False and r["applied"]["bridge_groups"] == 0)
    check("plan: масса = W×L×t×7,85 × листов", abs(r["summary"]["mass_kg"] - sum(1.25 * 2.5 * 2 * 7.85 * l["amount"] for l in r["layouts"])) < 0.2,
          "%s кг" % r["summary"]["mass_kg"])

    wd2 = workdir(base, "build", dict(inputs=inputs, kind="build", strategy="safe0", compare=None), files)
    code, r2, err = run_job(wd2)
    check("build: result.json, код 0", r2 is not None and code == 0 and err is None, str(err)[:200])
    if r2:
        bad = validate_result(r2, "build", False)
        check("build: ровно поля контракта, strategies = null", not bad, "; ".join(bad)[:300])
        check("build: те же листы и раскладки, что у плана; applied.coedge тот же",
              r2["summary"]["sheets"] == r["summary"]["sheets"] and [l["parts"] for l in r2["layouts"]] == [l["parts"] for l in r["layouts"]]
              and r2["applied"]["coedge"] == r["applied"]["coedge"])
        s0 = next(s for s in r["strategies"] if s["name"] == "safe0")
        check("build safe0 = строка safe0 сводки плана (холостой, врезки, возврат)",
              (r2["summary"]["idle_m"], r2["summary"]["pierces"], r2["summary"]["return_m"]) == (s0["idle_m"], s0["pierces"], s0["return_m"]),
              "%s / %s" % ((r2["summary"]["idle_m"], r2["summary"]["pierces"], r2["summary"]["return_m"]), (s0["idle_m"], s0["pierces"], s0["return_m"])))
    print("    (%.1f с)" % (time.time() - t0))
    return files, inputs


# ============================================================================================ 2) образец .lxds, общий рез, подписи
def sample_and_modes(base):
    m8 = os.path.join(SAMPLES, "m8_plates.lxds")
    if os.path.exists(m8):
        for kind in ("plan", "build"):
            wd = workdir(base, "m8_" + kind, dict(inputs=[dict(file="in/m8.lxds", key="pmk.laser.job,7")], kind=kind, sheet=dict(W=1500, L=3000),
                                                 thickness=8, strategy="safe", compare=None, title="8мм m8"), [(m8, "in/m8.lxds")])
            code, r, err = run_job(wd)
            bad = validate_result(r, kind, kind == "plan") if r else ["нет result.json: %s" % err]
            check("m8_plates.lxds, %s: result.json по контракту, ok, ключ у деталей программы" % kind,
                  not bad and r["ok"] and all(p["key"] == "pmk.laser.job,7" for p in r["parts"]) and r["summary"]["sheets"] >= 1,
                  "; ".join(bad)[:200] or "листов %d, деталей %d" % (r["summary"]["sheets"], len(r["parts"])))
    else:
        print("— образец m8_plates.lxds: нет, пропуск")
    td = os.path.join(base, "_src")
    a = dxf_plate(os.path.join(td, "co.dxf"), 400, 300, holes=2, slot=False)
    wd = workdir(base, "coedge", dict(inputs=[dict(file="in/1.dxf", name="Плита", qty=6, key=1)], coedge=True, strategy="safe"), [(a, "in/1.dxf")])
    code, r, err = run_job(wd)
    bad = validate_result(r, "plan", True) if r else ["нет result.json: %s" % err]
    check("общий рез: по контракту, applied.coedge = true, строки сводки без error",
          not bad and r["applied"]["coedge"] and r["requested"]["coedge"] and all(s["error"] is None for s in r["strategies"]),
          "; ".join(bad)[:200])
    w = dxf_washer(os.path.join(td, "w.dxf"))
    wd = workdir(base, "coedge_round", dict(inputs=[dict(file="in/1.dxf", name="Шайба", qty=6), dict(file="in/2.dxf", name="Плита", qty=2)],
                                             coedge=True, kind="build", compare=None), [(w, "in/1.dxf"), (a, "in/2.dxf")])
    code, r, err = run_job(wd)
    check("общий рез не применён (круглая деталь): причина в warnings, requested ≠ applied",
          r is not None and r["requested"]["coedge"] and not r["applied"]["coedge"] and
          any(x.startswith("общий рез не применён") for x in r["warnings"]), str(r and r["warnings"])[:200])
    wd = workdir(base, "bridge", dict(inputs=[dict(file="in/1.dxf", name="Шайба", qty=12)], bridge=dict(width=2, group=5), sheet=dict(W=600, L=900),
                                       strategy="hill", kind="build", compare=None), [(w, "in/1.dxf")])
    code, r, err = run_job(wd)
    check("мост: applied.bridge_groups > 0, bridge в итоге, ok", r is not None and r["ok"] and r["applied"]["bridge_groups"] > 0 and
          r["bridge"] and r["bridge"]["groups"] == r["applied"]["bridge_groups"], str(err or (r and r["bridge"]))[:200])
    wd = workdir(base, "bridge_empty", dict(inputs=[dict(file="in/1.dxf", name="Шайба", qty=12)], bridge={}, sheet=dict(W=600, L=900),
                                             kind="build", compare=None), [(w, "in/1.dxf")])
    code, r, err = run_job(wd)
    check("мост {} — включён со значениями по умолчанию (2 мм, 5 деталей), а не выключен молча",
          r is not None and r["requested"]["bridge"] == dict(width=2.0, group=5) and r["applied"]["bridge_groups"] > 0,
          str(err or (r and (r["requested"], r["applied"])))[:200])
    # имена-номера (позиции чертежа) и файлы Odoo in/1.dxf, in/2.dxf: перемычки «2» — только у детали «2», не у файла 2.dxf
    num = [dict(file="in/1.dxf", name="2", qty=1, key="part,101"), dict(file="in/2.dxf", name="Шайба", qty=20, key="part,102")]
    wd = workdir(base, "names_mj", dict(inputs=num, microjoints=["2"], bridge=dict(width=2, group=5), sheet=dict(W=1000, L=1000),
                                         kind="build", compare=None), [(a, "in/1.dxf"), (w, "in/2.dxf")])
    code, r, err = run_job(wd)
    rep_ = json.load(open(os.path.join(wd, r["files"]["report"]), encoding="utf-8")) if r else {}
    check("перемычки по имени «2» — только у детали «2», не у файла in/2.dxf (шайбы идут в мост)",
          r is not None and rep_.get("microjoints") == ["2"] and r["applied"]["bridge_groups"] > 0,
          str(err or (rep_.get("microjoints"), r["applied"]))[:200])
    if FONT:
        wd = workdir(base, "labels", dict(inputs=[dict(file="in/1.dxf", name="Плита", qty=2)], labels={"*": "ВЗ-3"}, font="in/font.json",
                                           kind="build", compare=None), [(a, "in/1.dxf"), (FONT, "in/font.json")])
        code, r, err = run_job(wd)
        check("подписи: таблица шрифта из in/font.json, labels_ok = 1, ok", r is not None and r["ok"] and r["applied"]["labels_ok"] == 1
              and r["applied"]["labels_failed"] == 0 and r["labels"] and r["labels"][0]["height"], str(err or (r and r["labels"]))[:200])
        b = dxf_plate(os.path.join(td, "b3.dxf"), 300, 200, holes=1, slot=False)
        wd = workdir(base, "names_lab", dict(inputs=[dict(file="in/1.dxf", name="2", qty=1), dict(file="in/2.dxf", name="Косынка", qty=1)],
                                              labels={"2": "П2"}, font="in/font.json", kind="build", compare=None),
                     [(a, "in/1.dxf"), (b, "in/2.dxf"), (FONT, "in/font.json")])
        code, r, err = run_job(wd)
        check("подпись по имени «2» — только у детали «2», не у файла in/2.dxf («Косынка» без подписи)",
              r is not None and [(l["part"], l["text"]) for l in r["labels"]] == [("2", "П2")] and r["applied"]["labels_ok"] == 1,
              str(err or (r and r["labels"]))[:200])
        two = os.path.join(td, "two.dxf")
        doc = DW.DxfDoc(version="AC1015", insunits=4)
        doc.entities.lwpolyline([(0, 0), (300, 0), (300, 200), (0, 200)], closed=True)
        doc.entities.lwpolyline([(400, 0), (700, 0), (700, 200), (400, 200)], closed=True)
        open(two, "wb").write(doc.dxf_bytes())
        wd = workdir(base, "multi_lab", dict(inputs=[dict(file="in/1.dxf", name="Двойная", qty=1, key="k")], labels={"Двойная": "Д"},
                                              font="in/font.json", kind="build", compare=None), [(two, "in/1.dxf"), (FONT, "in/font.json")])
        code, r, err = run_job(wd)
        check("DXF из двух контуров: подпись по имени Odoo — обеим деталям «#1», «#2» (ключ у обеих)",
              r is not None and r["applied"]["labels_ok"] == 2 and sorted(l["part"] for l in r["labels"]) == ["Двойная #1", "Двойная #2"]
              and all(p["key"] == "k" for p in r["parts"]), str(err or (r and r["labels"]))[:200])
    else:
        print("— подписи: нет таблицы шрифта, пропуск")


def fill_and_heal(base):
    """Добивка остатков листа и разрыв внешнего контура (16.10.2026): поля fill и heal_gap_mm во входе, fill и
    parts[].fill в итоге."""
    td = os.path.join(base, "_src")
    a = dxf_plate(os.path.join(td, "fp.dxf"), 1000, 1100, holes=2, slot=False)
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.entities.lwpolyline([(10, 0), (70, 0), (70, 1000), (0, 1000), (0, 0)], closed=False)    # разрыв 10 мм на кромке
    doc.entities.circle((35, 500), 6)
    st = os.path.join(td, "stand.dxf")
    open(st, "wb").write(doc.dxf_bytes())
    inputs = [dict(file="in/1.dxf", name="Плита", qty=3, key="part,1"), dict(file="in/2.dxf", name="Стойка", qty=1, key="stock,9")]
    wd = workdir(base, "fill", dict(inputs=inputs, fill=[dict(name="Стойка", max=7)], heal_gap_mm=20, kind="build", compare=None,
                                     strategy="safe"), [(a, "in/1.dxf"), (st, "in/2.dxf")])
    code, r, err = run_job(wd)
    bad = validate_result(r, "build", False) if r else ["нет result.json: %s" % err]
    f = (r or {}).get("fill") or [{}]
    check("добивка: result.json по контракту, fill — {name, placed, per_layout, max, why}, стоек ≤ 7, ok",
          not bad and r["ok"] and [x["name"] for x in r["fill"]] == ["Стойка"] and 0 < f[0]["placed"] <= 7 and f[0]["max"] == 7
          and sum(n * l["amount"] for n, l in zip(f[0]["per_layout"], r["layouts"])) == f[0]["placed"], "; ".join(bad)[:200] or str(f))
    check("добивка: parts — fill у стойки (qty = поставлено, ключ входа), у плиты — нет; разрыв закрыт — предупреждение",
          r is not None and [(p["name"], p["qty"], p["key"], p["fill"]) for p in r["parts"]] ==
          [("Плита", 3, "part,1", False), ("Стойка", f[0].get("placed"), "stock,9", True)] and
          any("закрыт прямой" in w for w in r["warnings"]) and any(c["name"] == "добивка не добавила листов" and c["status"] == "ok"
                                                                  for c in r["checks"]), str(r and r["parts"])[:200])
    wd = workdir(base, "nofill", dict(inputs=inputs[:1], kind="build", compare=None), [(a, "in/1.dxf")])
    code, r2, err = run_job(wd)
    check("без добивки: fill = [], parts[].fill = false, листов столько же, сколько с добивкой",
          r2 is not None and r2["fill"] == [] and all(p["fill"] is False for p in r2["parts"]) and r and
          r2["summary"]["sheets"] == r["summary"]["sheets"], str(err)[:160])
    wd = workdir(base, "heal_off", dict(inputs=inputs, fill=[dict(name="Стойка")], kind="build", compare=None),
                 [(a, "in/1.dxf"), (st, "in/2.dxf")])
    code, r3, err = run_job(wd)
    check("разрыв без heal_gap_mm — ошибка входа (input, user) у стойки: input {index 1, key stock,9}",
          err is not None and err["kind"] == "input" and err["user"] and err["input"] == dict(index=1, key="stock,9")
          and "не замкнут" in err["message"], json.dumps(err, ensure_ascii=False)[:200] if err else "")
    # склад: qty у позиции добивки — null или 0 (в заказ не идёт); у детали заказа null — по-прежнему ошибка вызывающего
    for q in (None, 0):
        inp = [inputs[0], dict(inputs[1], qty=q)]
        if q is None:
            del inp[1]["qty"]
        wd = workdir(base, "fill_qty_%s" % q, dict(inputs=inp, fill=[dict(name="Стойка")], heal_gap_mm=20, kind="build", compare=None),
                     [(a, "in/1.dxf"), (st, "in/2.dxf")])
        code, rq, err = run_job(wd)
        check("добивка: qty у её DXF %s — принято, стойки стоят, «количество не указано» нет" % ("не задан" if q is None else "0"),
              rq is not None and rq["ok"] and rq["fill"][0]["placed"] > 0 and not any("количество не указано" in w for w in rq["warnings"]),
              json.dumps(err, ensure_ascii=False)[:200] if err else "")
    wd = workdir(base, "order_qty_none", dict(inputs=[dict(inputs[0], qty=None)], kind="build", compare=None), [(a, "in/1.dxf")])
    code, rq, err = run_job(wd)
    check("деталь заказа без qty — ошибка вызывающего (params, user=false), как было",
          err is not None and err["kind"] == "params" and err["user"] is False and "qty" in err["message"], str(err)[:160])
    # позиция из нескольких контуров: max — на все её детали, в fill — одна строка с именем из входа
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.entities.lwpolyline([(0, 0), (60, 0), (60, 600), (0, 600)], closed=True)
    doc.entities.lwpolyline([(100, 0), (160, 0), (160, 600), (100, 600)], closed=True)
    doc.entities.circle((130, 300), 6)
    two = os.path.join(td, "two.dxf")
    open(two, "wb").write(doc.dxf_bytes())
    wd = workdir(base, "fill_multi", dict(inputs=[inputs[0], dict(file="in/2.dxf", name="Две", qty=1, key="s,2")], fill=[dict(name="Две", max=5)],
                                           kind="build", compare=None), [(a, "in/1.dxf"), (two, "in/2.dxf")])
    code, rm, err = run_job(wd)
    fp = [p for p in (rm or {}).get("parts", []) if p["fill"]]
    check("добивка из DXF с двумя контурами: fill — одна строка «Две», поставлено ≤ max 5 = Σ qty её деталей в parts (ключ s,2)",
          rm is not None and [(f["name"], f["max"]) for f in rm["fill"]] == [("Две", 5)] and 0 < rm["fill"][0]["placed"] <= 5 and
          sum(p["qty"] for p in fp) == rm["fill"][0]["placed"] and all(p["key"] == "s,2" and p["name"].startswith("Две #") for p in fp),
          str((rm or {}).get("fill") or err)[:200])


# ============================================================================================ 3) ошибки
def errors(base, files, inputs):
    td = os.path.join(base, "_src")
    a, b = files[0][0], files[1][0]
    broken = os.path.join(td, "broken.dxf"); open(broken, "w", encoding="utf-8").write("  0\nSECTION\n  2\nENTITIES\n  0\nLINE\n 10\nабв\n")
    locked = os.path.join(td, "locked.dxf"); shutil.copy(a, locked)
    badlx = os.path.join(td, "broken.lxds"); open(badlx, "wb").write(b"PK\x03\x04 not a zip")
    big = dxf_plate(os.path.join(td, "big.dxf"), 3000, 400)
    one = [dict(file="in/1.dxf", name="Пластина", qty=2)]
    empty_lib = os.path.join(td, "empty_lib"); os.makedirs(empty_lib, exist_ok=True)
    cases = [
        ("битый DXF", dict(inputs=one), [(broken, "in/1.dxf")], "input", True, "DXF"),
        ("битый .lxds", dict(inputs=[dict(file="in/1.lxds")]), [(badlx, "in/1.lxds")], "input", True, "CypCut"),
        ("деталь больше листа", dict(inputs=one), [(big, "in/1.dxf")], "params", True, "не помещается"),
        ("мост + общий рез", dict(inputs=one, coedge=True, bridge=dict(width=2, group=5)), [(a, "in/1.dxf")], "params", True, "мост"),
        ("перемычки: чужое имя", dict(inputs=one, microjoints=["Нет такой"]), [(a, "in/1.dxf")], "params", True, "нет такой детали"),
        ("подпись: чужое имя", dict(inputs=one, labels={"Нет такой": "Х"}, font="in/font.json"), [(a, "in/1.dxf")] + ([(FONT, "in/font.json")] if FONT else []),
         "params" if FONT else "config", bool(FONT), "нет такой детали" if FONT else "шрифт"),
        ("плохой профиль станка", dict(inputs=one, machines=[dict(name="С1", travel_mm_s=0, cut=[])]), [(a, "in/1.dxf")], "config", False, "профиль"),
        ("неизвестная стратегия", dict(inputs=one, strategy="fast"), [(a, "in/1.dxf")], "params", False, "strategy"),
        ("лист меньше края", dict(inputs=one, sheet=dict(W=3, L=2500)), [(a, "in/1.dxf")], "params", True, "отступ"),
        ("подписи без шрифта", dict(inputs=one, labels={"*": "Х"}, font=None), [(a, "in/1.dxf")], "config", False, "шрифт"),
        ("подписи: нет файла шрифта", dict(inputs=one, labels={"*": "Х"}, font="in/нет.json"), [(a, "in/1.dxf")], "config", False, "шрифт"),
        ("нет vent_nesting", dict(inputs=one, vent_nesting_lib=empty_lib), [(a, "in/1.dxf")], "config", False, "vent_nesting"),
        ("не тот contract", dict(inputs=one, contract="sheet_nest.job/2"), [(a, "in/1.dxf")], "params", False, "контракт"),
        ("неизвестный kind", dict(inputs=one, kind="nest"), [(a, "in/1.dxf")], "params", False, "kind"),
        ("лишнее поле", dict(inputs=one, small=50), [(a, "in/1.dxf")], "params", False, "small"),
        ("DXF без qty", dict(inputs=[dict(file="in/1.dxf", name="Пластина")]), [(a, "in/1.dxf")], "params", False, "qty"),
        ("нет файла входа", dict(inputs=[dict(file="in/9.dxf", name="Х", qty=1)]), [(a, "in/1.dxf")], "params", False, "нет файла"),
        ("plan с compare=false", dict(inputs=one, compare=False), [(a, "in/1.dxf")], "params", False, "compare"),
        ("количество 0", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=0)]), [(a, "in/1.dxf")], "params", True, "количество"),
        ("количество строкой", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty="5")]), [(a, "in/1.dxf")], "params", False, "qty"),
        ("количество миллион", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=10 ** 6)]), [(a, "in/1.dxf")], "params", True, "за один раз"),
        ("повтор имени DXF", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1), dict(file="in/2.dxf", name=" Пластина ", qty=2)]),
         [(a, "in/1.dxf"), (b, "in/2.dxf")], "params", False, "разными"),
        ("предел времени 1e10", dict(inputs=one, time_limit_s=1e10), [(a, "in/1.dxf")], "params", False, "time_limit_s"),
        ("мост: группа строкой", dict(inputs=one, bridge=dict(width=2, group="abc")), [(a, "in/1.dxf")], "params", True, "«abc»"),
        ("файл входа не читается", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1)]), [(locked, "in/1.dxf")], "config", False, "не читается"),
        # добивка и разрыв внешнего контура (16.10.2026): имя и пределы — инженеру; форма поля — вызывающему
        ("добивка: чужое имя", dict(inputs=one, fill=[dict(name="Нет такой")]), [(a, "in/1.dxf")], "params", True, "нет такой детали"),
        ("добивка «*»", dict(inputs=one, fill=[dict(name="*")]), [(a, "in/1.dxf")], "params", True, "«*» нельзя"),
        ("добивка: все детали", dict(inputs=one, fill=[dict(name="Пластина")]), [(a, "in/1.dxf")], "params", True, "все детали"),
        ("добивка: max < 0", dict(inputs=one, fill=[dict(name="Пластина", max=-1)]), [(a, "in/1.dxf")], "params", True, "предел"),
        ("добивка — не список", dict(inputs=one, fill="Пластина"), [(a, "in/1.dxf")], "params", False, "fill"),
        ("добивка: лишнее поле", dict(inputs=one, fill=[dict(name="Пластина", qty=2)]), [(a, "in/1.dxf")], "params", False, "fill[0]"),
        ("добивка: max строкой", dict(inputs=one, fill=[dict(name="Пластина", max="2")]), [(a, "in/1.dxf")], "params", False, "max"),
        ("разрыв: heal_gap_mm строкой", dict(inputs=one, heal_gap_mm="20"), [(a, "in/1.dxf")], "params", False, "heal_gap_mm"),
        ("разрыв: heal_gap_mm < 0", dict(inputs=one, heal_gap_mm=-1), [(a, "in/1.dxf")], "params", True, "не меньше 0"),
    ]
    if FONT:
        cases.append(("отступ подписи < 0", dict(inputs=one, labels={"*": "Р1"}, font="in/font.json", label_opts=dict(margin=-3)),
                      [(a, "in/1.dxf"), (FONT, "in/font.json")], "params", True, "отступ"))
    for k, (name, inp, fl, kind, user, word) in enumerate(cases):
        wd = workdir(base, "err%02d" % k, inp, fl)
        if name == "файл входа не читается":
            os.chmod(os.path.join(wd, "in", "1.dxf"), 0)
        code, r, err = run_job(wd)
        ok = (r is None and err is not None and code == 1 and set(err) == set(J.ERROR_KEYS) and err["kind"] == kind and err["user"] is user
              and err["run_id"] == "run-err%02d" % k and word.lower() in err["message"].lower() and len(err["trace"]) <= J.TRACE_MAX
              and (not user or "--" not in err["message"]) and (not user or not re.search(r"\{'|Error\b|[A-Z][a-z]+ [a-z]+ [a-z]+", err["message"])))
        check("ошибка: %s → %s, user=%s" % (name, kind, user), ok, (json.dumps(err, ensure_ascii=False)[:220] if err else "result: ok=%s" % (r and r["ok"])))
    # какой вход сломан: имя детали в тексте, input {index, key} в error.json; кириллица в испорченном числе — как в файле
    three = [dict(file="in/1.dxf", name="Пластина", qty=1, key="k1"), dict(file="in/2.dxf", name="Косынка", qty=1, key="k2"),
             dict(file="in/3.dxf", name="Уголок", qty=1, key="k3")]
    wd = workdir(base, "err_which", dict(inputs=three, kind="build", compare=None), [(a, "in/1.dxf"), (broken, "in/2.dxf"), (b, "in/3.dxf")])
    code, r, err = run_job(wd)
    check("битый DXF второй из трёх: «деталь «Косынка»: …», input = {index 1, key k2}, «абв» без искажения",
          err and err["kind"] == "input" and err["message"].startswith("деталь «Косынка»: ") and err["input"] == dict(index=1, key="k2")
          and "«абв»" in err["message"], json.dumps(err, ensure_ascii=False)[:220] if err else "")
    wd = workdir(base, "err_which_lx", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1), dict(file="in/2.lxds", key="job,3")], kind="build",
                                             compare=None), [(a, "in/1.dxf"), (badlx, "in/2.lxds")])
    code, r, err = run_job(wd)
    check("битый .lxds вторым: input = {index 1, key job,3}, текст по-русски («не zip-архив»), без «File is not a zip file»",
          err and err["kind"] == "input" and err["input"] == dict(index=1, key="job,3") and "zip-архив" in err["message"]
          and "File is not" not in err["message"] and "BadZipFile" in err["trace"], json.dumps(err, ensure_ascii=False)[:220] if err else "")
    wd = workdir(base, "err_which_big", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1), dict(file="in/2.dxf", name="Длинная", qty=1, key=7)],
                                              kind="build", compare=None), [(a, "in/1.dxf"), (big, "in/2.dxf")])
    code, r, err = run_job(wd)
    check("деталь больше листа: input = {index 1, key 7}", err and err["kind"] == "params" and err["input"] == dict(index=1, key=7),
          json.dumps(err, ensure_ascii=False)[:220] if err else "")
    # input.json — не JSON: run_id взять неоткуда
    wd = workdir(base, "err_json", dict(inputs=one), [(a, "in/1.dxf")])
    open(os.path.join(wd, "input.json"), "w").write("{не json")
    code, r, err = run_job(wd)
    check("ошибка: input.json не JSON → params, user=false, run_id null", err and err["kind"] == "params" and not err["user"] and err["run_id"] is None,
          str(err)[:160])


def sigterm_and_timeout(base, files):
    td = os.path.join(base, "_src")
    small = dxf_plate(os.path.join(td, "small.dxf"), 120, 90, holes=4, slot=True)
    many = [dict(file="in/1.dxf", name="Косынка", qty=400, key="k")]
    wd = workdir(base, "sigterm", dict(inputs=many, strategy="safe"), [(small, "in/1.dxf")])
    log = open(os.path.join(wd, "run.log"), "w")
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-m", "sheet_nest.job", wd], stdout=log, stderr=subprocess.STDOUT, env=ENV, cwd=ROOT)
    torn, stages, seen_route = 0, set(), None
    while p.poll() is None and time.time() - t0 < 120:
        try:
            pr = json.load(open(os.path.join(wd, "progress.json"), encoding="utf-8"))
            stages.add(pr["stage"])
            if pr["stage"] == "route" and seen_route is None:
                seen_route = time.time()
        except FileNotFoundError:
            pass
        except ValueError:
            torn += 1
        if seen_route and time.time() - seen_route > 0.5:
            check("SIGTERM: до сигнала нет ни result.json, ни error.json", not os.path.exists(os.path.join(wd, "result.json"))
                  and not os.path.exists(os.path.join(wd, "error.json")))
            p.send_signal(signal.SIGTERM)
            break
        time.sleep(0.01)
    p.wait(60)
    log.close()
    err, r = _read(wd, "error.json"), _read(wd, "result.json")
    check("SIGTERM посреди маршрута → cancelled, user=true, run_id, result.json нет",
          seen_route and err and err["kind"] == "cancelled" and err["user"] and err["run_id"] == "run-sigterm" and r is None,
          "этапы %s; %s" % (sorted(stages), json.dumps(err, ensure_ascii=False)[:160] if err else "result ok=%s" % (r and r["ok"])))
    check("progress.json всегда читается целиком (атомарно)", torn == 0, "рваных чтений %d" % torn)
    check("после сигнала нет .tmp", not [f for f in os.listdir(wd) if f.endswith(".tmp")], str(os.listdir(wd)))

    # серия SIGTERM в первые 0,25 с после pid: попадает и в импорт numpy (он превращает исключение обработчика в
    # ImportError — без st.stop_kind выходило «config: движок не загрузился»)
    import random
    rnd, kinds = random.Random(3), {}
    for k in range(12):
        wd = workdir(base, "sig%02d" % k, dict(inputs=[dict(file="in/1.dxf", name="Косынка", qty=3)], time_limit_s=None), [(small, "in/1.dxf")])
        p = subprocess.Popen([sys.executable, "-m", "sheet_nest.job", wd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, cwd=ROOT)
        while not os.path.exists(os.path.join(wd, "pid")) and p.poll() is None:
            time.sleep(0.001)
        time.sleep(rnd.uniform(0, 0.25))
        try:
            p.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        p.wait(60)
        e = _read(wd, "error.json")
        kinds[(e and e["kind"], os.path.exists(os.path.join(wd, "result.json")))] = kinds.get((e and e["kind"], os.path.exists(os.path.join(wd, "result.json"))), 0) + 1
    check("SIGTERM в первые 0,25 с (12 раз, и во время импорта numpy) — всегда cancelled, result.json нет",
          set(kinds) <= {("cancelled", False)}, str(kinds))
    st = J._State(base)
    st.stop_kind = "cancelled"
    e1 = J._classify(st, ImportError("Error importing numpy: you should not try to import numpy from its source directory"), "")
    try:
        st.progress("pack", "раскрой")
        e2 = None
    except J._Stop as e:
        e2 = e.kind
    check("остановка, которую проглотил C (импорт numpy): ImportError → cancelled; следующий этап progress → _Stop",
          e1["kind"] == "cancelled" and e2 == "cancelled", "%s / %s" % (e1["kind"], e2))

    wd = workdir(base, "timeout", dict(inputs=many, time_limit_s=0.05), [(small, "in/1.dxf")])
    code, r, err = run_job(wd)
    check("предел времени 0,05 с → timeout, user=true", err and err["kind"] == "timeout" and err["user"] and r is None and code == 1,
          json.dumps(err, ensure_ascii=False)[:160] if err else "")
    # сторож: главный поток не отвечает (SIGALRM заблокирован, как при долгом вызове C) — снимает поток-сторож
    wd = workdir(base, "hard", dict(inputs=many, time_limit_s=0.2), [(small, "in/1.dxf")])
    code = subprocess.run([sys.executable, "-c", "import signal, sys; from sheet_nest import job; job.HARD_GRACE_S = 0.5; "
                           "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM, signal.SIGTERM}); sys.exit(job.main(%r))" % wd],
                          env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120).returncode
    err = _read(wd, "error.json")
    check("сторож: процесс не ответил на SIGALRM → error.json timeout, выход 3", code == 3 and err and err["kind"] == "timeout" and
          "главный поток" in err["trace"] and not os.path.exists(os.path.join(wd, "result.json")), "код %s, %s" % (code, str(err)[:120]))
    # C держит GIL (долгий цикл без байт-кодов): ни SIGALRM, ни поток-сторож не просыпаются — снимает faulthandler
    wd = workdir(base, "gil", dict(inputs=many, time_limit_s=0.2), [(small, "in/1.dxf")])
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-c", "import sys; from sheet_nest import job, cli; job.HARD_GRACE_S = 0.5; job.FAULT_GRACE_S = 0.5\n"
                            "cli.run = lambda *a, **k: sum(range(10 ** 10))\nsys.exit(job.main(%r))" % wd],
                           env=ENV, cwd=ROOT, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        p = subprocess.CompletedProcess([], "не снят за 60 с", "", "")
    dt = time.time() - t0
    check("C держит GIL: faulthandler снимает процесс через предел + 2 ступени (стек в stderr), итога нет — Odoo: «прервался»",
          p.returncode == 1 and dt < 20 and "Timeout" in p.stderr and not os.path.exists(os.path.join(wd, "result.json"))
          and not os.path.exists(os.path.join(wd, "error.json")), "код %s, %.1f с, %s" % (p.returncode, dt, p.stderr[:80]))


def in_process(base, files):
    """Сбой движка (engine) и старый итог в папке — вызовом job.main() в этом же процессе."""
    import sheet_nest.cli as CLI
    a = files[0][0]
    wd = workdir(base, "engine", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1)]), [(a, "in/1.dxf")])
    open(os.path.join(wd, "result.json"), "w").write('{"stale": true}')
    orig = CLI.run

    def boom(*a, **k):
        raise RuntimeError("сбой " + "x" * 9000)
    CLI.run = boom
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = J.main(wd)
    finally:
        CLI.run = orig
    err = _read(wd, "error.json")
    check("сбой движка → engine, user=false, trace ≤ 4000, message ≤ 1000; старый result.json убран",
          code == 1 and err and err["kind"] == "engine" and not err["user"] and 0 < len(err["trace"]) <= J.TRACE_MAX
          and len(err["message"]) <= J.MESSAGE_MAX and "RuntimeError" in err["message"] and not os.path.exists(os.path.join(wd, "result.json")),
          "%s, trace %d" % (err and err["message"][:40], len(err["trace"]) if err else -1))
    wd = workdir(base, "unser", dict(inputs=[dict(file="in/1.dxf", name="Пластина", qty=1)], kind="build", compare=None), [(a, "in/1.dxf")])
    orig = J.make_result
    J.make_result = lambda *x, **k: dict(orig(*x, **k), warnings={"не", "сериализуется"})
    env0 = os.environ.get("VENT_NESTING_LIB")
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = J.main(wd)
    finally:
        J.make_result = orig
    err = _read(wd, "error.json")
    check("result.json не сериализовался → error.json engine, ни result.json, ни .tmp",
          code == 1 and err and err["kind"] == "engine" and "result.json не записан" in err["message"] and
          not os.path.exists(os.path.join(wd, "result.json")) and not os.path.exists(os.path.join(wd, "result.json.tmp")), str(err)[:160])
    check("окружение после main() — как было (VENT_NESTING_LIB)", os.environ.get("VENT_NESTING_LIB") == env0, str(os.environ.get("VENT_NESTING_LIB")))
    check("сигналы после main() — прежние", signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None) and
          signal.getsignal(signal.SIGALRM) in (signal.SIG_DFL, None), str(signal.getsignal(signal.SIGTERM)))


# ============================================================================================ 5) run() и движок
def engine_api(base, files):
    from sheet_nest.cli import run
    from sheet_nest import cli as CLI, render, route as RT, SheetNestError, __version__
    from sheet_nest.read_dxf import DxfError
    from sheet_nest.read_lxds import LxdsError
    from sheet_nest.labels import LabelError, FontError
    a, b = files[0][0], files[1][0]
    td = os.path.join(base, "_src")
    q = os.path.join(td, "Косынка_12шт.dxf"); shutil.copy(a, q)
    quiet = lambda *x: None
    res, raw, pl, parts = run([dict(path=q, name="Косынка_12шт", qty=3, key=("ключ", 1))], 1250, 2500, 2, 2, 2.0, log=quiet)
    check("run({path, name, qty, key}): имя как задано, количество — заданное (не 12 из имени), ключ у детали",
          [(p["name"], p["qty"], p.get("key")) for p in parts] == [("Косынка_12шт", 3, ("ключ", 1))], str([(p["name"], p["qty"]) for p in parts]))
    check("run(словарь): ни «количество не указано», ни «в имени файла количество»", not any("количество" in w for w in res["warnings"]),
          str(res["warnings"])[:160])
    res, raw, pl, parts = run([dict(path=a, name="Без количества")], 1250, 2500, 2, 2, 2.0, log=quiet)
    check("run(словарь без qty): 1 шт и предупреждение «не указано»", parts[0]["qty"] == 1 and any("не указано" in w for w in res["warnings"]))
    p_noqty = os.path.join(td, "пласт.dxf"); shutil.copy(a, p_noqty)
    res, *_ = run([p_noqty], 1250, 2500, 2, 2, 2.0, qty={"пласт": 4}, log=quiet)
    check("старый путь + qty (--qty): ложного «количество не указано» нет", not any("не указано" in w for w in res["warnings"]), str(res["warnings"])[:120])
    res, *_ = run([p_noqty], 1250, 2500, 2, 2, 2.0, log=quiet)
    check("старый путь без количества: «количество не указано» осталось", any("не указано" in w for w in res["warnings"]))
    res, raw, pl, parts = run([dict(path=a, name="X", qty=1), dict(path=b, name="X", qty=2), dict(path=b, name="X (2)", qty=3)],
                              1250, 2500, 2, 2, 2.0, log=quiet)
    nm = [p["name"] for p in parts]
    check("повтор имён: X, X, «X (2)» → X, «X (3)», «X (2)» — все разные, раскладка не сливает две детали",
          nm == ["X", "X (3)", "X (2)"] and sum(sum(l["parts"].values()) * l["amount"] for l in res["layouts"]) == 6, str(nm))
    res, raw, pl, parts = run([dict(path=a, name='R&D "50"', qty=1)], 1250, 2500, 2, 2, 2.0, log=quiet, microjoints=['R&D "50"'])
    check("перемычки по имени, как задано (со знаками &\"), хотя в программе имя «RD 50»", res["microjoints"] == ["RD 50"], str(res["microjoints"]))
    check("мост {} — по умолчанию; None, False — нет", CLI.bridge_options({}) == dict(width=2.0, group=5) and CLI.bridge_options(None) is None
          and CLI.bridge_options(False) is None and CLI.bridge_options(dict(width=None, group=None)) == dict(width=2.0, group=5))

    stages = []
    out = os.path.join(base, "api_out")
    res, raw, pl, parts = run([dict(path=a, name="П", qty=4), dict(path=b, name="Р", qty=3)], 1250, 2500, 2, 2, 2.0, title="api", out=out,
                              log=quiet, compare=True, strategy="safe", progress=lambda s, t: stages.append((s, t)))
    st = [s for s, t in stages]
    routes = [t for s, t in stages if s == "route"]
    check("прогресс: этапы read → pack → route → build → check → render по порядку",
          [s for k, s in enumerate(st) if k == 0 or st[k - 1] != s] == ["read", "pack", "route", "build", "check", "render"], str(st))
    check("прогресс: маршрут по каждой стратегии «маршрут: …, k/4», выбранная — первой",
          routes == ["маршрут: Безопасный, 1/4", "маршрут: Минимум холостого, 2/4", "маршрут: Безопасный, конец у нуля, 3/4",
                     "маршрут: Горкой, 4/4"], str(routes))
    lay = res["layouts"][0]
    util_file = next(c[2] for c in res["checks"] if c[0].startswith("загрузка в файле"))
    check("раскладка: W, L, util_pct (= загрузке в файле), cut_m, mark_m, pierces, mass_kg",
          (lay["W"], lay["L"]) == (1250.0, 2500.0) and ("%.1f%%" % lay["util_pct"]) == util_file.split(",")[0]
          and lay["mass_kg"] == round(1250 * 2500 * 2 * 7.85e-6, 1) and lay["pierces"] > 0 and lay["mark_m"] > 0,
          "%s; в файле %s" % ({k: lay[k] for k in ("util_pct", "cut_m", "mark_m", "pierces", "mass_kg")}, util_file))
    check("отчёт .json: files, requested, applied, timing", set(res["files"]) == {"lxds", "png_layouts", "png_order", "report"} and
          all(os.path.isfile(os.path.join(out, f)) for f in res["files"].values()) and res["timing"]["route_s"] >= 0)
    # картинка не нарисовалась — предупреждение, программа и отчёт есть
    orig = render.png_model
    render.png_model = lambda *x, **k: (_ for _ in ()).throw(MemoryError("нет памяти"))
    try:
        out2 = os.path.join(base, "api_out2")
        res, *_ = run([dict(path=a, name="П", qty=2)], 1250, 2500, 2, 2, 2.0, title="png", out=out2, log=quiet)
    finally:
        render.png_model = orig
    check("картинка упала → предупреждение, программа, вторая картинка и отчёт записаны, ok",
          res["ok"] and any(w.startswith("картинка") and "MemoryError" in w for w in res["warnings"]) and res["files"]["png_layouts"] is None
          and all(os.path.isfile(os.path.join(out2, res["files"][k])) for k in ("lxds", "png_order", "report")) and
          any(w.startswith("картинка") for w in json.load(open(os.path.join(out2, res["files"]["report"]), encoding="utf-8"))["warnings"]),
          str(res["warnings"])[:160])
    # п. 8: у одной стратегии сводки порядок группы общего реза не нашёлся — не построена только её строка
    co = dxf_plate(os.path.join(td, "co2.dxf"), 400, 300, holes=2, slot=False)
    orig = RT.route_sheet_coedge

    def picky(*x, **k):
        if k.get("strategy") == "safe0":
            raise RT.CoedgeRouteError("группу из 6 деталей не удалось разрезать общим резом ни одним порядком")
        return orig(*x, **k)
    RT.route_sheet_coedge = picky
    try:
        res, raw, pl, parts = run([dict(path=co, name="Плита", qty=6)], 1250, 2500, 2, 2, 3.0, log=quiet, coedge=True, compare=True)
        S = res["strategies"]
        check("п. 8: «safe0» с общим резом не строится — его строка с error, остальные и программа — с общим резом",
              res["coedge"] and res["ok"] and S["safe0"]["error"] and S["safe0"]["sheets"] is None and
              all(S[n]["error"] is None and S[n]["sheets"] == res["sheets"] for n in ("short", "safe", "hill")) and
              any("«Безопасный, конец у нуля» с общим резом не строится" in w for w in res["warnings"]), str(res["warnings"])[:200])
        txt = CLI.summary_text(list(S.values()))
        check("п. 8: сводка текстом — «—» и строка «общий рез: не строится»", "не строится" in txt and "—" in txt)
        res, *_ = run([dict(path=co, name="Плита", qty=6)], 1250, 2500, 2, 2, 3.0, log=quiet, coedge=True, strategy="safe0")
        check("п. 8: не строится у выбранной стратегии — весь раскрой с зазором, причина в warnings",
              not res["coedge"] and res["requested"]["coedge"] and not res["applied"]["coedge"] and
              any(w.startswith("общий рез не применён") for w in res["warnings"]))
    finally:
        RT.route_sheet_coedge = orig

    check("ошибки: DxfError, LxdsError, LabelError → SheetNestError → ValueError; FontError — kind config",
          issubclass(DxfError, SheetNestError) and issubclass(LxdsError, SheetNestError) and issubclass(LabelError, SheetNestError)
          and issubclass(SheetNestError, ValueError) and FontError.kind == "config" and DxfError.kind == LxdsError.kind == "input")
    texts = []
    for kw in (dict(qty={"нет": 2}), dict(microjoints=["нет"]), dict(bridge=dict(width=2, group=1)), dict(labels={"нет": "Х"}),
               dict(bridge=dict(width=0, group=5)), dict(coedge=True, bridge=dict(width=2, group=5)), dict(strategy="x"),
               dict(machine=dict(travel_mm_s=1)), dict(labels={"*": "Х"}, label_opts=dict(font_path="/нет/шрифта.json")),
               dict(labels={"*": "Х"}, label_opts=dict(H=0)), dict(labels={"*": "Х"}, label_opts=dict(margin=-3)),
               dict(labels={"*": "Х"}, label_opts=dict(H=1e6, H_min=1e5)), dict(qty={"a": 0}), dict(bridge=dict(width=2, group="abc")),
               dict(machine=dict(travel_mm_s=None, cut=[dict(t=2, mm_s=1)])), dict(fill=["*"]), dict(fill=["нет"]),
               dict(fill=[dict(name="нет", max=-1)]), dict(heal_gap_mm=-1)):
        try:
            run([a], 1250, 2500, 2, 2, 2.0, log=quiet, **kw)
            texts.append("принято: %s" % kw)
        except SheetNestError as e:
            if re.search(r"--[a-z]", str(e)):
                texts.append("флаг в тексте: %s" % e)
            if re.search(r"\{'|None\b|\bError\b", str(e)):
                texts.append("питоновский repr в тексте: %s" % e)
        except Exception as e:
            texts.append("%s: %s" % (type(e).__name__, e))
    check("тексты ошибок пользователя — SheetNestError, без флагов командной строки", not texts, "; ".join(texts)[:240])
    from sheet_nest.cli import main
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            main([a, "--qty", "нет=2", "--out", os.path.join(base, "cli_out")])
        code = None
    except SystemExit as e:
        code = e.code
    check("командная строка: подсказку флагом добавляет сама («… (--qty)»)", isinstance(code, str) and code.endswith("(--qty)"), str(code)[:120])
    p_cli = os.path.join(td, "плита_5шт.dxf"); shutil.copy(a, p_cli)
    for q, want in (("плита_5шт=0", "количество 0"), ("плита_5шт=x", "--qty")):
        try:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                main([p_cli, "--qty", q, "--out", os.path.join(base, "cli_out")])
            code = None
        except SystemExit as e:
            code = e.code
        except Exception as e:
            code = "трассировка: %s: %s" % (type(e).__name__, e)
        check("командная строка --qty %s — сообщение «ошибка: …», а не трассировка" % q,
              isinstance(code, str) and code.startswith("ошибка:") and want in code, str(code)[:120])
    from sheet_nest.machine import MachineError
    check("MachineError — SheetNestError, kind config (профиль станка — настройка администратора)",
          issubclass(MachineError, SheetNestError) and MachineError.kind == "config")
    check("__version__ — semver", bool(re.match(r"^\d+\.\d+\.\d+$", __version__)), __version__)


def libpath_sibling(base):
    """Движок как аддон: addons/pmk_sheet_nest/lib/sheet_nest → addons/pmk_vent_nest/lib (без VENT_NESTING_LIB)."""
    root = os.path.join(base, "addons")
    pkg = os.path.join(root, "pmk_sheet_nest", "lib", "sheet_nest")
    os.makedirs(pkg)
    shutil.copy(os.path.join(ROOT, "sheet_nest", "libpath.py"), pkg)
    open(os.path.join(pkg, "__init__.py"), "w").close()
    vn = os.path.join(root, "pmk_vent_nest", "lib", "vent_nesting")
    os.makedirs(vn)
    open(os.path.join(vn, "__init__.py"), "w").write('__version__ = "9.9.9"\n')
    code = "import sys; sys.path.insert(0, %r); from sheet_nest import libpath as L; print(L.LIB); print(L.vent_nesting_version())" % os.path.dirname(pkg)
    env = dict(ENV); env.pop("PYTHONPATH", None)
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=base)
    lines = p.stdout.split()
    check("libpath: соседний аддон pmk_vent_nest/lib найден без VENT_NESTING_LIB",
          p.returncode == 0 and lines and os.path.realpath(lines[0]) == os.path.realpath(os.path.dirname(vn)) and lines[-1] == "9.9.9",
          (p.stdout + p.stderr)[-200:])
    env["VENT_NESTING_LIB"] = os.path.join(base, "нет")
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=base)
    check("libpath: VENT_NESTING_LIB задана неверно — ImportError, дальше не ищет", p.returncode != 0 and "VENT_NESTING_LIB" in p.stderr,
          p.stderr.strip().splitlines()[-1][:160] if p.stderr.strip() else p.stdout)


def main():
    t0 = time.time()
    base = tempfile.mkdtemp(prefix="sheet_nest_job_")
    try:
        r = synthetic(base)
        if r is None:
            print("ОШИБКИ: %s" % fails)
            return 1
        files, inputs = r
        sample_and_modes(base)
        fill_and_heal(base)
        errors(base, files, inputs)
        sigterm_and_timeout(base, files)
        in_process(base, files)
        engine_api(base, files)
        libpath_sibling(base)
    finally:
        if not fails:
            shutil.rmtree(base, ignore_errors=True)
        else:
            print("папка прогонов оставлена: %s" % base)
    print("(%.0f с)" % (time.time() - t0))
    print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
