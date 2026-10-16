# -*- coding: utf-8 -*-
"""Контракт sheet_nest.job/1 — раскрой листа отдельным процессом для Odoo (ERP.md, «Как считать» и «Контракт»).

    python -m sheet_nest.job <папка прогона>        или        from sheet_nest import job; job.main(папка)

Odoo кладёт в папку input.json (и входы в in/), запускает процесс как у pmk_vent_nest
(sh -c 'nohup python runner.py <папка> > <папка>/run.log 2>&1 &') и опрашивает папку. Процесс пишет:
    pid            — свой номер, сразу при старте;
    progress.json  — {"stage": read|pack|route|build|check|render, "text": "маршрут: Безопасный, 2/4"} (атомарно);
    out/           — программа .lxds, картинки .png, отчёт .json (имена — в result.json → files);
    result.json    — ПОСЛЕДНИМ и атомарно (.tmp → os.replace): итог по контракту (ниже, RESULT_KEYS);
    error.json     — вместо результата: {kind, user, message, trace, run_id, input}.
Лог — в stdout/stderr (Odoo направляет их в run.log; сам job.py run.log не открывает).

Ошибки (error.json, kind):
    input     — плохой DXF или .lxds (DxfError, LxdsError) — user=true, текст показать как есть; какой вход — в
                error.json → input {index, key} (и имя детали в тексте);
    params    — ошибка параметров: деталь больше листа, мост вместе с общим резом, неизвестное имя детали (перемычки,
                подписи, добивка), количество, допуск разрыва < 0 (SheetNestError) — user=true; input.json не по контракту (неизвестный contract, kind или стратегия,
                нет полей, не те типы, повтор имени DXF, нет файла входа) — user=false: ошибка вызывающего;
    config    — нет пакета vent_nesting, нет таблицы шрифта при подписях, плохой профиль станка, файл входа не
                читается — user=false (текст администратору);
    cancelled — SIGTERM («Остановить»), timeout — предел time_limit_s (сторож: SIGALRM; не ответил ещё HARD_GRACE_S с —
                поток-сторож пишет error.json и снимает процесс; главный поток держит GIL в C и поток-сторож не
                просыпается — ещё через FAULT_GRACE_S faulthandler (без GIL) пишет стек в лог и снимает процесс без
                итога) — user=true;
    engine    — всё остальное — user=false, trace — хвост трассировки ≤ TRACE_MAX знаков.
Переменные окружения VENT_NESTING_LIB и SHEET_NEST_FONT ставятся из input.json ДО импорта движка (libpath читает
VENT_NESTING_LIB при импорте). Один прогон = один процесс: движок на время вызова подменяет функции пакета.
"""
import os, sys, json, time, signal, threading, traceback, platform, faulthandler

CONTRACT = "sheet_nest.job/1"
KINDS = ("plan", "build")
TRACE_MAX = 4000            # знаков хвоста трассировки в error.json
MESSAGE_MAX = 1000          # знаков текста ошибки движка (kind engine)
HARD_GRACE_S = 60.0         # сверх time_limit_s: процесс не вышел по SIGALRM (застрял в C) — снимает поток-сторож
FAULT_GRACE_S = 30.0        # ещё сверх того: поток-сторож не проснулся (C держит GIL) — снимает faulthandler, без итога
TIME_LIMIT_MAX = 86400.0    # time_limit_s не больше суток (больше — заведомо ошибка; setitimer падал на 1e10)
TITLE_MAX = 60              # знаков названия в имени файла (кириллица — 2 байта; имя файла ≤ 255 байт)
BAD_TITLE = '/\\:*?"<>|'

INPUT_KEYS = ("contract", "kind", "run_id", "engine_lib", "vent_nesting_lib", "title", "inputs", "sheet", "gap", "edge",
              "thickness", "strategy", "compare", "coedge", "bridge", "small_mm", "microjoints", "labels", "label_opts",
              "font", "machines", "time_limit_s", "heal_gap_mm", "fill", "fill_gap")
RESULT_KEYS = ("contract", "kind", "run_id", "engine", "ok", "requested", "applied", "files", "summary", "strategies",
               "machines", "layouts", "checks", "warnings", "labels", "bridge", "parts", "fill", "fill_coedge", "timing")
SUMMARY_KEYS = ("sheets", "lower_bound", "optimal", "method", "cut_m", "mark_m", "idle_m", "return_m", "pierces", "mass_kg",
                "machine_s", "machine_detail")
STRATEGY_KEYS = ("name", "title", "sheets", "cut_m", "idle_m", "return_m", "pierces", "bridges", "danger", "strip", "ret",
                 "warnings", "machine_s", "machine_detail", "error")
MACHINE_KEYS = ("name", "preliminary", "source", "updated", "note", "k_total", "thicknesses")    # result.json → machines[]
DETAIL_KEYS = ("cut_s", "pierce_s", "mark_s", "travel_s", "lift_s", "k", "total_s", "why")      # machine_detail{станок}
DANGER_KEYS = ("tongues", "small", "parts", "holes", "holes_s", "near", "short", "mj")
LAYOUT_KEYS = ("index", "amount", "parts", "W", "L", "util_pct", "cut_m", "mark_m", "pierces", "mass_kg")
PART_KEYS = ("name", "qty", "key", "fill")                                                     # result.json → parts[]
FILL_KEYS = ("name", "placed", "per_layout", "max", "why")                                     # result.json → fill[]
FILL_CO_KEYS = ("by_name", "in_groups", "order_contacts", "shared_m", "gap_only", "no_order_touch",
                "gap_variant")                                                                   # → fill_coedge
ERROR_KEYS = ("kind", "user", "message", "trace", "run_id", "input")
STAGES = ("read", "pack", "route", "build", "check", "render")


class ContractError(Exception):
    """input.json не по контракту — kind «params», user=false (ошибка вызывающего). input — номер входа или None."""
    kind, user = "params", False

    def __init__(self, message, input=None):
        super().__init__(message)
        self.input = input


class ConfigError(ContractError):
    """Окружение: нет пакета vent_nesting, нет таблицы шрифта, файл входа не читается — kind «config», user=false."""
    kind, user = "config", False


class _Stop(BaseException):
    """SIGTERM или предел времени. BaseException — чтобы не проглотили «except Exception» движка (check_safe и др.)."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def _log(*a):
    print(*a, flush=True)


def _write_json(path, obj):
    """Атомарно: .tmp рядом, затем os.replace — читатель видит либо старый файл, либо новый целиком."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _tail(text, n=TRACE_MAX):
    return text if len(text) <= n else "…" + text[-(n - 1):]


class _State:
    """Папка прогона и завершение: result.json или error.json пишется ровно один раз (замок + флаг), сигналы после
    начала записи игнорируются."""

    def __init__(self, workdir):
        self.workdir = workdir
        self.run_id = None
        self.limit = None
        self.lock = threading.Lock()
        self.done = False
        self.armed = True               # сигнал → _Stop, пока идёт работа; при записи итога — нет
        self.stop_kind = None           # пришёл SIGTERM / SIGALRM: cancelled | timeout (даже если _Stop проглотил C)
        self.timer = None
        self.fault = False              # faulthandler взведён (снять в конце)
        self.items = []                 # входы input.json: номер → key (для error.json → input)

    def path(self, name):
        return os.path.join(self.workdir, name)

    def progress(self, stage, text):
        if self.armed and self.stop_kind:
            # остановка пришла, но её проглотил код на C (импорт numpy превращает исключение обработчика в ImportError,
            # и его кто-то поймал) — исполнить на ближайшем этапе
            raise _Stop(self.stop_kind)
        _log("[%s] %s" % (stage, text))
        try:
            _write_json(self.path("progress.json"), dict(stage=stage, text=text))
        except OSError as e:            # прогресс — не итог: не записался — не повод падать
            print("progress.json не записан: %s" % e, file=sys.stderr, flush=True)

    def finish(self, name, obj):
        """Записать итог (result.json или error.json), если его ещё нет. Вернуть True, если записали. Не записалось
        (диск, не сериализуется) — исключение, итога нет: можно записать другой (error.json)."""
        with self.lock:
            if self.done:
                return False
            self.armed = False
            try:
                _write_json(self.path(name), obj)
            except BaseException:
                try:
                    os.remove(self.path(name) + ".tmp")
                except OSError:
                    pass
                raise
            self.done = True
            return True

    def error(self, kind, user, message, trace="", input=None):
        where = None
        if isinstance(input, int) and not isinstance(input, bool) and 0 <= input < len(self.items):
            where = dict(index=input, key=self.items[input].get("key"))
        return dict(kind=kind, user=bool(user), message=message, trace=_tail(trace or ""), run_id=self.run_id, input=where)

    def hard_timeout(self):
        """Поток-сторож: процесс не вышел по SIGALRM за HARD_GRACE_S — error.json timeout и выход без очистки."""
        frames = sys._current_frames()
        main = next((f for t, f in frames.items() if t == threading.main_thread().ident), None)
        stack = "".join(traceback.format_stack(main)) if main is not None else ""
        try:
            wrote = self.finish("error.json", self.error(
                "timeout", True, "раскрой не уложился в %g с — процесс снят (не ответил на остановку)" % self.limit,
                "главный поток:\n" + stack))
        except OSError:
            wrote = True                # записать не вышло — всё равно снять: процесс завис
        if wrote:                       # итог уже записан главным потоком — ничего не трогать
            _log("✗ timeout: процесс снят сторожем")
            os._exit(3)


def _install_signals(st):
    """SIGTERM/SIGINT → cancelled, SIGALRM → timeout (только в главном потоке; иначе — только поток-сторож)."""
    def stop(kind):
        def h(signum, frame):
            if st.armed:
                st.stop_kind = st.stop_kind or kind     # запомнить: _Stop может проглотить код на C (см. progress)
                raise _Stop(kind)
        return h
    old = {}
    try:
        for sig, kind in ((signal.SIGTERM, "cancelled"), (signal.SIGINT, "cancelled"), (signal.SIGALRM, "timeout")):
            old[sig] = signal.signal(sig, stop(kind))
    except ValueError:                  # не главный поток
        pass
    return old


def _restore_signals(old):
    try:
        signal.setitimer(signal.ITIMER_REAL, 0)
    except ValueError:
        pass
    for sig, h in old.items():
        try:
            signal.signal(sig, h)
        except (ValueError, TypeError):
            pass


def _arm_timer(st, limit):
    """Три ступени предела: SIGALRM (главный поток, между байт-кодами) → поток-сторож через HARD_GRACE_S (пишет
    error.json; нужен GIL — не проснётся, пока C держит GIL) → faulthandler ещё через FAULT_GRACE_S (поток на C, без
    GIL: стек всех потоков в stderr, т. е. run.log, и выход с кодом 1 без итога — Odoo видит «процесс умер»)."""
    st.limit = limit
    try:
        signal.setitimer(signal.ITIMER_REAL, limit)
    except ValueError:                  # не главный поток — остаётся поток-сторож
        pass
    st.timer = threading.Timer(limit + HARD_GRACE_S, st.hard_timeout)
    st.timer.daemon = True
    st.timer.start()
    try:
        faulthandler.dump_traceback_later(limit + HARD_GRACE_S + FAULT_GRACE_S, exit=True, file=sys.__stderr__)
        st.fault = True
    except (AttributeError, ValueError, OSError, RuntimeError):     # нет настоящего stderr — остаются две ступени
        pass


# ============================================================================================ input.json
def _num(v, what, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ContractError("input.json: %s — нужно число, а не %r" % (what, v))
    return v


def _is(v, typ, what, allow_none=True):
    if v is None and allow_none:
        return v
    if not isinstance(v, typ):
        raise ContractError("input.json: %s — %s, а не %r" % (what, {dict: "объект {…}", list: "список […]", str: "строка",
                                                                     bool: "true или false"}.get(typ, typ), v))
    return v


def read_input(st):
    """input.json → проверенный словарь задания (форма — ContractError; значения проверяет движок)."""
    try:
        with open(st.path("input.json"), encoding="utf-8") as f:
            job = json.load(f)
    except OSError as e:
        raise ContractError("input.json не открывается: %s" % (e.strerror or e))
    except ValueError as e:
        raise ContractError("input.json — не JSON: %s" % e)
    if not isinstance(job, dict):
        raise ContractError("input.json: нужен объект {…}")
    st.run_id = job.get("run_id")
    if job.get("contract") != CONTRACT:
        raise ContractError("контракт %r не поддерживается: движок %s понимает %s" % (job.get("contract"), _version(), CONTRACT))
    if job.get("kind") not in KINDS:
        raise ContractError("kind %r: нужен plan или build" % (job.get("kind"),))
    extra = sorted(set(job) - set(INPUT_KEYS))
    if extra:
        raise ContractError("input.json: неизвестные поля %s (контракт %s)" % (", ".join(extra), CONTRACT))
    if isinstance(st.run_id, (dict, list)):
        raise ContractError("input.json: run_id — строка или число")
    inputs = _is(job.get("inputs"), list, "inputs", allow_none=False)
    if not inputs:
        raise ContractError("input.json: inputs пуст — нет ни одной детали")
    items, names = [], {}
    st.items = [it if isinstance(it, dict) else {} for it in inputs]
    # позиции добивки: у их DXF qty можно не задавать (склад — не заказ; форму fill проверяет ниже)
    fill_names = {f["name"].strip() for f in job.get("fill") or () if isinstance(f, dict) and isinstance(f.get("name"), str)} \
        if isinstance(job.get("fill"), list) else set()
    for k, it in enumerate(inputs):
        try:
            items.append(_read_item(st, k, it, names, fill_names))
        except ContractError as e:
            if e.input is None:
                e.input = k
            raise
    sheet = _is(job.get("sheet"), dict, "sheet", allow_none=False)
    if set(sheet) != {"W", "L"}:
        raise ContractError("input.json: sheet — {\"W\": ширина, \"L\": длина}, а не %r" % (sheet,))
    W, L = _num(sheet["W"], "sheet.W"), _num(sheet["L"], "sheet.L")
    kind = job["kind"]
    compare = _is(job.get("compare"), bool, "compare")
    if compare is not None and compare != (kind == "plan"):
        raise ContractError("input.json: compare=%s при kind=%s — план всегда со сводкой (true), сборка — без неё (false)"
                            % (json.dumps(compare), kind))
    bridge = _is(job.get("bridge"), dict, "bridge")
    labels = _is(job.get("labels"), dict, "labels")
    if labels and not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        raise ContractError("input.json: labels — {имя детали или \"*\": текст}")
    label_opts = _is(job.get("label_opts"), dict, "label_opts") or {}
    extra = sorted(set(label_opts) - {"H", "H_min", "margin", "gap"})
    if extra:
        raise ContractError("input.json: label_opts — неизвестные поля %s (есть H, H_min, margin, gap)" % ", ".join(extra))
    for k, v in label_opts.items():
        _num(v, "label_opts.%s" % k)
    micro = _is(job.get("microjoints"), list, "microjoints") or []
    if not all(isinstance(x, str) for x in micro):
        raise ContractError("input.json: microjoints — список имён деталей (или \"*\")")
    machines = _is(job.get("machines"), list, "machines") or []
    for k, m in enumerate(machines):
        _is(m, dict, "machines[%d]" % k, allow_none=False)
    limit = _num(job.get("time_limit_s"), "time_limit_s", allow_none=True)
    if limit is not None and not (0 < limit <= TIME_LIMIT_MAX):
        raise ContractError("input.json: time_limit_s — больше 0 и не больше %g с (или null — без предела)" % TIME_LIMIT_MAX)
    strategy = _is(job.get("strategy"), str, "strategy")
    for k in ("engine_lib", "vent_nesting_lib", "font", "title"):
        _is(job.get(k), str, k)
    heal = _num(job.get("heal_gap_mm"), "heal_gap_mm", allow_none=True)     # ≥ 0 — проверяет движок (params, user)
    fill = _is(job.get("fill"), list, "fill") or []
    for k, f in enumerate(fill):
        _is(f, dict, "fill[%d]" % k, allow_none=False)
        extra = sorted(set(f) - {"name", "max"})
        if extra:
            raise ContractError("input.json: fill[%d] — неизвестные поля %s (есть name, max)" % (k, ", ".join(extra)))
        _is(f.get("name"), str, "fill[%d].name" % k, allow_none=False)
        if f.get("max") is not None and (isinstance(f["max"], bool) or not isinstance(f["max"], int)):
            raise ContractError("input.json: fill[%d].max — целое число или null, а не %r" % (k, f["max"]))
    return dict(kind=kind, run_id=st.run_id, items=items, W=W, L=L,
                gap=_num(_dflt(job.get("gap"), 2.0), "gap"), edge=_num(_dflt(job.get("edge"), 2.0), "edge"),
                thickness=_num(job.get("thickness"), "thickness", allow_none=True),
                strategy=strategy, compare=(kind == "plan"), coedge=bool(_is(job.get("coedge"), bool, "coedge")),
                bridge=bridge, small=_num(job.get("small_mm"), "small_mm", allow_none=True), microjoints=micro or None,
                labels=labels or None, label_opts=label_opts, font=job.get("font"), machines=machines,
                time_limit_s=limit, title=_title(job.get("title")), vent_nesting_lib=job.get("vent_nesting_lib"),
                engine_lib=job.get("engine_lib"), heal_gap_mm=heal, fill=[dict(name=f["name"], max=f.get("max")) for f in fill] or None,
                # с общим резом добивка вплотную (0.12.0); true — с зазором, общий рез только у деталей заказа (как прежде)
                fill_gap=bool(_is(job.get("fill_gap"), bool, "fill_gap")))


def _read_item(st, k, it, names, fill_names=()):
    """inputs[k] → {path, name?, qty?, key?} для run(). names — имена DXF уже прочитанных входов (повтор — ошибка);
    fill_names — имена позиций добивки (у их DXF qty можно не задавать: в заказ не идёт)."""
    _is(it, dict, "inputs[%d]" % k, allow_none=False)
    extra = sorted(set(it) - {"file", "name", "qty", "key"})
    if extra:
        raise ContractError("input.json: inputs[%d] — неизвестные поля %s" % (k, ", ".join(extra)))
    f = _is(it.get("file"), str, "inputs[%d].file" % k, allow_none=False)
    path = f if os.path.isabs(f) else os.path.join(st.workdir, f)
    if not os.path.isfile(path):
        raise ContractError("input.json: inputs[%d] — нет файла %s" % (k, f))
    try:                                # не читается (права, диск) — дело окружения, не инженера
        open(path, "rb").close()
    except OSError as e:
        raise ConfigError("файл входа %s не читается: %s" % (f, e.strerror or e))
    low = f.lower()
    if low.endswith(".dxf"):
        if not isinstance(it.get("name"), str) or not it["name"].strip():
            raise ContractError("input.json: inputs[%d] (%s) — у DXF нужно name (имя детали)" % (k, f))
        nm = it["name"].strip()
        if it.get("qty") is None:
            if nm not in fill_names:
                raise ContractError("input.json: inputs[%d] (%s) — у DXF нужно qty (количество)" % (k, f))
        else:                                       # число; целое ≥ 1 — проверяет движок (инженер ввёл 0 — params, user;
            _num(it["qty"], "inputs[%d].qty" % k)   # у добивки 0 — можно)
        if nm in names:
            # по имени находят перемычки и подписи (microjoints, labels): у двух деталей одно имя — чья галочка, не понять
            raise ContractError("input.json: inputs[%d] (%s) — имя «%s» уже у inputs[%d]: имена DXF должны быть разными "
                                "(по ним находят перемычки и подписи)" % (k, f, nm, names[nm]))
        names[nm] = k
    elif low.endswith(".lxds"):
        if it.get("name") is not None or it.get("qty") is not None:
            raise ContractError("input.json: inputs[%d] (%s) — у программы CypCut name и qty не задаются: детали и "
                                "количества берутся из неё" % (k, f))
    else:
        raise ContractError("input.json: inputs[%d] — нужен .dxf или .lxds, а не %s" % (k, f))
    if isinstance(it.get("key"), (dict, list)):
        raise ContractError("input.json: inputs[%d].key — строка или число" % k)
    d = dict(path=path)
    for key in ("name", "qty", "key"):
        if it.get(key) is not None:
            d[key] = it[key]
    return d


def _dflt(v, d):
    return d if v is None else v


def _title(t):
    """Название программы — в имя файла: без / \\ : * ? " < > | и управляющих знаков, не длиннее TITLE_MAX."""
    t = "".join("_" if (c in BAD_TITLE or ord(c) < 32) else c for c in (t or "")).strip(" ._")
    return (t[:TITLE_MAX].rstrip(" ._") or "раскрой")


def _resolve(st, p):
    return p if os.path.isabs(p) else os.path.join(st.workdir, p)


def _setup_env(st, job):
    """VENT_NESTING_LIB и SHEET_NEST_FONT — до импорта движка (libpath читает переменную при импорте)."""
    if job["vent_nesting_lib"]:
        lib = os.path.abspath(_resolve(st, job["vent_nesting_lib"]))
        if not os.path.isdir(os.path.join(lib, "vent_nesting")):
            raise ConfigError("пакет vent_nesting не найден в %s (vent_nesting_lib из input.json)" % lib)
        lp = sys.modules.get("sheet_nest.libpath")
        if lp is not None and os.path.abspath(lp.LIB) != lib:
            raise ConfigError("движок в этом процессе уже загружен с пакетом из %s, а задан %s — один прогон = один процесс"
                              % (lp.LIB, lib))
        os.environ["VENT_NESTING_LIB"] = lib
    font = None
    if job["labels"]:
        if not job["font"]:
            raise ConfigError("подписи заданы, а таблицы шрифта нет (поле font в input.json) — загрузите таблицу штрихов "
                              "шрифта в настройках раскроя")
        font = os.path.abspath(_resolve(st, job["font"]))
        if not os.path.isfile(font):
            raise ConfigError("нет файла таблицы шрифта %s (поле font в input.json)" % font)
        os.environ["SHEET_NEST_FONT"] = font
    return font


def _version():
    from . import __version__
    return __version__


# ============================================================================================ result.json
def _strategy_row(r):
    row = {k: r.get(k) for k in STRATEGY_KEYS}
    if r.get("danger") is not None:
        row["danger"] = {k: r["danger"].get(k) for k in DANGER_KEYS}
    return row


def _status(v):
    return "ok" if v else "warn" if v is None else "fail"


def make_result(job, res, parts, t0):
    """Отчёт run() → result.json (контракт sheet_nest.job/1, поля — RESULT_KEYS и ниже)."""
    from .libpath import vent_nesting_version
    from .route import STRATEGIES
    rk = res["risk"]
    strategies = None
    if res.get("strategies") is not None:
        order = list(STRATEGIES) + [n for n in res["strategies"] if n not in STRATEGIES]
        strategies = [_strategy_row(res["strategies"][n]) for n in order if n in res["strategies"]]
    return dict(
        contract=CONTRACT, kind=job["kind"], run_id=job["run_id"],
        engine=dict(sheet_nest=_version(), vent_nesting=vent_nesting_version(), python=platform.python_version()),
        ok=bool(res["ok"]),
        requested=res["requested"], applied=res["applied"],
        files={k: ("out/" + v) if v else None for k, v in res["files"].items()},
        summary=dict(sheets=res["sheets"], lower_bound=res["lower_bound"], optimal=bool(res["optimal"]), method=res["method"],
                     cut_m=rk["cut_m"], mark_m=rk["mark_m"], idle_m=res["idle_m"], return_m=round(rk["ret"]["m"], 2),
                     pierces=rk["pierces"], mass_kg=res["mass_kg"],
                     # время станков выбранной стратегии (= её строке сводки): {станок: с | null}, {станок: разбор}
                     machine_s=dict(rk.get("machine_s") or {}), machine_detail=dict(rk.get("machine_detail") or {})),
        strategies=strategies,
        # профили станков (эхо machine.info): предварительный ли (в сводке «≈»), откуда, когда, поправка, толщины
        machines=[{k: m.get(k) for k in MACHINE_KEYS} for m in res.get("machines") or []],
        layouts=[{k: l[k] for k in LAYOUT_KEYS} for l in res["layouts"]],
        checks=[dict(name=n, status=_status(v), detail=d) for n, v, d in res["checks"]],
        warnings=list(res["warnings"]), labels=res["labels"], bridge=res.get("bridge"),
        # деталь добивки (fill: true) — складская позиция в остатках листа, не заказ; её qty — сколько поставлено
        parts=[dict(name=p["name"], qty=p["qty"], key=p.get("key"), fill=bool(p.get("fill"))) for p in parts],
        # добивка остатков листа (16.10.2026): [{name, placed, per_layout, max, why}] по порядку из input.json; без неё — []
        fill=[{k: f.get(k) for k in FILL_KEYS} for f in res.get("fill") or []],
        # общий рез с добивкой (16.10.2026, 0.12.0): добивка вплотную — по позициям с зазором было / поставлено, в группах,
        # касаний с деталями заказа, общих кромок (м, на все листы), раскладки без касаний; со сводкой (compare) — ещё
        # gap_variant: тот же раскрой с добивкой с зазором выбранной стратегией (опасные, рез, холостой); без общего реза
        # или добивки — null
        fill_coedge=({k: res["fill_coedge"].get(k) for k in FILL_CO_KEYS} if res.get("fill_coedge") else None),
        timing=dict(total_s=round(time.time() - t0, 2), route_s=res["timing"]["route_s"]))


# ============================================================================================ запуск
def _work(st, t0):
    for name in ("result.json", "error.json", "progress.json"):     # остатки прошлого запуска в той же папке
        for p in (st.path(name), st.path(name) + ".tmp"):
            if os.path.exists(p):
                os.remove(p)
    _write_pid(st)
    st.progress("read", "задание принято")
    job = read_input(st)
    if job["time_limit_s"]:
        _arm_timer(st, float(job["time_limit_s"]))
    _log("%s: kind=%s run_id=%s, sheet_nest %s, Python %s, папка %s" % (CONTRACT, job["kind"], job["run_id"], _version(),
                                                                       platform.python_version(), st.workdir))
    font = _setup_env(st, job)
    try:
        from . import cli
        from .libpath import LIB
        from .route import STRATEGIES
    except ImportError as e:
        raise ConfigError("движок не загрузился: %s" % e)
    _log("vent_nesting: %s; engine_lib: %s" % (LIB, job["engine_lib"]))
    if job["strategy"] is not None and job["strategy"] not in STRATEGIES:
        # стратегию выбирает щелчок по столбцу сводки — чужое имя значит ошибку вызывающего, а не инженера
        raise ContractError("input.json: strategy «%s» — есть %s" % (job["strategy"], ", ".join(STRATEGIES)))
    label_opts = dict(job["label_opts"])
    if font:
        label_opts["font_path"] = font
    res, raw, pl, parts = cli.run(
        job["items"], job["W"], job["L"], job["gap"], job["edge"], job["thickness"], None, job["title"],
        os.path.join(st.workdir, "out"), log=_log, coedge=job["coedge"], labels=job["labels"], label_opts=label_opts,
        strategy=job["strategy"], compare=job["compare"], small=job["small"], microjoints=job["microjoints"],
        machine=job["machines"] or None, bridge=job["bridge"], progress=st.progress, heal_gap_mm=job["heal_gap_mm"],
        fill=job["fill"], fill_gap=job["fill_gap"])
    return make_result(job, res, parts, t0)


def _write_pid(st):
    tmp = st.path("pid") + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % os.getpid())
    os.replace(tmp, st.path("pid"))


def _classify(st, e, trace):
    """Исключение → error.json (kind, user, message). Пришёл сигнал остановки — cancelled / timeout, каким бы ни было
    исключение: импорт numpy превращает _Stop из обработчика сигнала в ImportError («движок не загрузился»)."""
    stop = e.kind if isinstance(e, _Stop) else st.stop_kind
    if stop == "timeout":
        return st.error("timeout", True, "раскрой не уложился в %g с (предел time_limit_s) — остановлен" % (st.limit or 0), trace)
    if stop or isinstance(e, KeyboardInterrupt):
        return st.error("cancelled", True, "раскрой остановлен", trace)
    if isinstance(e, ContractError):
        return st.error(e.kind, e.user, str(e), trace, e.input)
    from .errors import SheetNestError
    if isinstance(e, SheetNestError):
        # DxfError, LxdsError — input; FontError, MachineError — config (таблица шрифта, профиль станка — настройки
        # администратора); прочие — params
        kind = getattr(e, "kind", "params")
        return st.error(kind, kind != "config", str(e), trace, getattr(e, "input", None))
    if isinstance(e, ImportError):
        return st.error("config", False, "движок не загрузился: %s" % e, trace)
    return st.error("engine", False, ("%s: %s" % (type(e).__name__, e))[:MESSAGE_MAX], trace)


def _safe_classify(st, e, trace):
    try:
        return _classify(st, e, trace)
    except Exception as e2:             # разбор ошибки сам не должен оставить прогон без итога
        return st.error("engine", False, "%s: %s (разбор ошибки: %s)" % (type(e).__name__, e, e2), trace)


def main(workdir):
    """Прогон по контракту sheet_nest.job/1 в папке workdir. Вернуть код выхода: 0 — result.json, 1 — error.json,
    2 — не записано ничего (нет папки, не пишется диск). Процесс снимают и сторожа предела времени: поток-сторож —
    код 3 (error.json timeout), faulthandler — код 1 без error.json (ERP.md, «Контракт»)."""
    t0 = time.time()
    workdir = os.path.abspath(workdir)
    if not os.path.isdir(workdir):
        print("sheet_nest.job: нет папки прогона %s" % workdir, file=sys.stderr, flush=True)
        return 2
    st = _State(workdir)
    env0 = {k: os.environ.get(k) for k in ("VENT_NESTING_LIB", "SHEET_NEST_FONT")}
    old = _install_signals(st)
    try:
        try:
            try:
                result = _work(st, t0)
                if st.stop_kind:        # остановку проглотил код на C, а этапов с проверкой (progress) больше не было
                    raise _Stop(st.stop_kind)
                st.armed = False
                name, obj = "result.json", result
            except BaseException as e:
                st.armed = False
                name, obj = "error.json", _safe_classify(st, e, traceback.format_exc())
        except _Stop as e:              # сигнал успел прийти, пока разбиралась ошибка
            st.armed = False
            name, obj = "error.json", _safe_classify(st, e, traceback.format_exc())
        if name == "error.json":
            print(obj["trace"], file=sys.stderr, flush=True)
            _log("✗ %s%s: %s" % (obj["kind"], "" if obj["user"] else " (не для пользователя)", obj["message"]))
        else:
            _log("✓ result.json: ok=%s, листов %s, %.1f с" % (obj["ok"], obj["summary"]["sheets"], time.time() - t0))
        try:
            st.finish(name, obj)
        except Exception as e:
            print("sheet_nest.job: %s не записан: %s: %s" % (name, type(e).__name__, e), file=sys.stderr, flush=True)
            if name != "result.json" or isinstance(e, OSError):
                return 2
            try:                        # итог не сериализовался — это сбой движка, а не «нет ответа»
                st.finish("error.json", st.error("engine", False, "result.json не записан: %s: %s" % (type(e).__name__, e),
                                                 traceback.format_exc()))
            except Exception:
                return 2
            return 1
        return 0 if name == "result.json" else 1
    finally:
        if st.timer is not None:
            st.timer.cancel()
        if st.fault:
            faulthandler.cancel_dump_traceback_later()
        _restore_signals(old)
        for k, v in env0.items():       # вызов в чужом процессе (тесты) — окружение как было
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("python -m sheet_nest.job <папка прогона>")
    sys.exit(main(sys.argv[1]))
