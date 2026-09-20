# -*- coding: utf-8 -*-
"""Стенд: прогнать локальную модель по корзинам A-F и посчитать, где она врёт.

Модель здесь делает ровно одно: по строке прайса собирает черновик карточки
номенклатуры — контракт лежит в prompt.py. Сопоставлением занимается match.py,
там модель не нужна и не зовётся.

Судит ответ не человек и не вторая модель, а draft_validate.py: каждое число
ответа обязано дословно быть во входной строке. Стенд за моделью ничего не
чинит и не дописывает — подправленный ответ мерить бессмысленно, так меришь
себя, а не модель. Ответ либо проходит валидатор целиком, либо это брак.

Числа из воздуха — блокер: неверная масса погонного метра уезжает в КП и в
цех, и отличить выдуманное число от верного по виду нельзя.

Главная цифра прогона — ЗАЧЁТ: ответ прошёл валидатор целиком И статус совпал
с ожидаемым для этой строки. Одного «прошёл валидатор» мало: молчащая модель,
на всё отвечающая «не_хватает_данных, нужен человек», проходит валидатор на
100% — ей просто нечем ошибиться. Поэтому рядом с зачётом всегда печатается
фон: тот самый константный отказ, посчитанный по этим же строкам. Прогон,
не обогнавший фон, — это не замер модели, а замер молчания. Обогнавший на
одну строку — тоже: одна строка из 139 приходит и уходит сама, см. BEAT_SHARE.

    python3 llm_assist.py                       # весь набор, qwen3:8b
    python3 llm_assist.py --limit 3             # по 3 строки из каждой корзины
    python3 llm_assist.py --bucket D E F        # только ловушки на отказ
    python3 llm_assist.py --out /tmp/answers.jsonl
    python3 llm_assist.py --line "Труба профильная 60х30х1,5"   # одна строка

Коды возврата:
    0 — ни одного выдуманного числа И зачёт ЗНАЧИМО выше фона немой модели
    1 — есть выдуманные числа (блокер, модель в таком виде не едет) либо зачёт
        не обогнал фон значимо: модель не лучше ответа «нужен человек» на всё
        или лучше на считаные строки, что неотличимо от случая (порог и
        объяснение — beat_margin);
        в режиме --line — любая жалоба валидатора, это отладка, а не замер
    2 — мерить нечем: нет набора, набор битый, пустой фильтр — ИЛИ выбран срез,
        на котором фон забирает все строки (см. --bucket D), и обогнать его
        физически нечем. Это не приговор модели, а неверно выбранный срез
    3 — ollama не отвечает, модель не скачана или подставлена не та
"""
import argparse
import hashlib
import json
import math
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

# Стенд зовут и из корня репозитория, а соседние модули ищутся по sys.path,
# не по текущей папке. Поэтому папку скрипта добавляем до импортов.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from draft_validate import cross_check, validate                   # noqa: E402
from prompt import FEWSHOT, REQUEST, SCHEMA, SYSTEM, build_messages  # noqa: E402

CASES = os.path.join(HERE, "llm_cases.json")
HOST = "http://127.0.0.1:11434"

# Блокер считается по тексту ошибки валидатора — формулировка из
# draft_validate.validate(). Если она там изменится, счётчик молча обнулится и
# прогон покажет чистый результат там, где модель выдумывает числа. Поэтому
# перед прогоном проверяем, что формулировка ещё та же — см. blocker_alive.
INVENTED = re.compile(r"число «.+?» отсутствует во входной строке")

# Ответ молчуна: статус «не_хватает_данных» и объяснение без единой цифры.
# Валидатор к такому ответу придраться не может — придираться не к чему, полей
# нет. Это и есть нижняя планка, с которой сравнивается любой прогон.
MUTE = {"статус": "не_хватает_данных", "вид": None, "вид_цитата": None,
        "труба_вид": None, "размеры": {}, "марка_стали": None, "гост": None,
        "признаки": [], "чего_не_хватает": "нужен человек"}

# Ниже этого числа строк проценты не печатаем. На двух строках «50%» — это
# одна строка, а выглядит как замер целого класса отказов.
MIN_ROWS = 10

# Шаблон строки: все числа зачищены. Набор уже, чем кажется — одна и та же
# форма записи повторяется с разными размерами, и процент по строкам
# перевешивает в пользу того, что чаще встречается, а не того, что труднее.
TEMPLATE = re.compile(r"[\d.,]+")

# Семьи ошибок — только чтобы сгруппировать итог и было видно, что чинить
# в промпте.
#
# Таблица живёт отдельно от валидатора и отстаёт от него: он свои формулировки
# переписывает, а здесь об этом узнать неоткуда. Раньше неопознанная жалоба
# печаталась «как есть» — и, обрезанная по ширине колонки, выглядела копией
# соседней: «вид трубы не подтверждён строкой» дважды подряд с разными
# счётчиками. Поэтому неопознанное теперь не маскируется под семью, а уходит в
# отдельную строку «без имени» со списком (см. family и report).
FAMILIES = [
    (INVENTED, "число из воздуха"),
    (re.compile(r"кусок другого числа"), "число-обрезок"),
    (re.compile(r"размер взят из игнорируемого куска"),
     "размер из запретного куска"),
    (re.compile(r"взято из связки размеров"), "размер назван не размером"),
    (re.compile(r"значения «.+?» нет в цитате"), "значение мимо цитаты"),
    (re.compile(r"признака «.+?» нет в строке"), "признак из воздуха"),
    (re.compile(r"вид не подтверждён цитатой"), "вид не доказан цитатой"),
    (re.compile(r"вид трубы не подтверждён строкой"),
     "вид трубы не доказан строкой"),
    (re.compile(r"труба_вид указан у вида"), "труба_вид не у трубы"),
    (re.compile(r"для ВГП труба_вид"), "у ВГП чужой труба_вид"),
    # Ниже общее правило про цитату — оно должно стоять ПОСЛЕ признака и вида,
    # иначе съест их: формулировки у них похожи.
    (re.compile(r"нет в строке"), "цитата мимо строки"),
    (re.compile(r"порядок размеров"), "перепутаны роли размеров"),
    (re.compile(r"стенка «.+?» не тоньше габарита"), "стенка толще габарита"),
    (re.compile(r"серия полок не стоит рядом"), "серия полок не у номера"),
    (re.compile(r"не бывает у вида"), "поле не того вида"),
    (re.compile(r"вне (?:закрытого )?списка"), "значение вне списка"),
    # «черновик швеллера/двутавра без серии полок» — беда не пустого ответа, а
    # ровно та ловушка корзины D, ради которой она собрана; общее «черновик
    # без» его и так не ловит, но стоять оно обязано раньше.
    (re.compile(r"черновик швеллера/двутавра без"),
     "черновик без серии полок"),
    (re.compile(r"черновик без|отказ без объяснения"), "пустой ответ"),
    (re.compile(r"но поля заполнены|но вид или размеры заполнены"),
     "отказ с заполненными полями"),
    (re.compile(r"«чего_не_хватает» содержит число"),
     "число в свободном тексте"),
    (re.compile(r"по числам это"), "квадрат против прямоугольной"),
    (re.compile(r"правила прочли"), "разошлось с правилами"),
    (re.compile(r"размер не читается как число"), "размер не читается"),
    (re.compile(r"лишнее поле в ответе"), "лишнее поле в ответе"),
    (re.compile(r"форма ответа нарушена|ответ не объект JSON"
                r"|^размеры: не объект"), "форма ответа нарушена"),
    (re.compile(r"не объект \{значение, цитата\}|пустое значение или цитата"),
     "поле без пары значение+цитата"),
    # Последние три — жалобы самого стенда, не валидатора: до проверок ответ
    # не дожил. Причина у них другая, и лечатся они не промптом.
    (re.compile(r"обрезан на лимите"), "ответ обрезан по num_predict"),
    (re.compile(r"нет JSON-объекта|JSON не разбирается|JSON не объект"),
     "ответ не JSON"),
    (re.compile(r"вернула пустой ответ"), "модель промолчала"),
]

# Имя строки-свалки в таблице причин. Её появление — не мелочь: значит,
# валидатор научился новой жалобе, а стенд её не знает.
NAMELESS = "без имени — нет в FAMILIES"

# Порог значимости обгона фона. Обгон ровно на одну строку из 139 — это не
# «модель едет»: набор пересобирается (строки приходят и выбывают), одна и та
# же форма записи в нём повторяется, и случайно угаданный статус на одной
# строке даёт точно такой же «+1».
#
# Строгого статистического критерия у нас нет и взяться ему неоткуда: прогон
# один, разброс между прогонами не измерен, а p-value по одному замеру — то же
# враньё, только в цифрах. Поэтому порог здесь инженерный, и назван честно:
# обгон значим, если он не меньше двадцатой части среза И не меньше пяти строк.
# Пять — потому что это уже несколько РАЗНЫХ форм записи, а не одна удачная;
# 5% — потому что на полном наборе это 7 строк из 139, такой перевес переживает
# и пересборку набора, и правку пары строк. Цифры не священны, но менять их
# нужно вместе с этим объяснением, а не ради красивого итога.
BEAT_SHARE = 0.05
BEAT_FLOOR = 5

THINK_TAG = re.compile(r"<think>.*?</think>", re.S)
FENCE = re.compile(r"^```(?:json)?|```$", re.M)


def _plural(n, one, few, many):
    """Окончание по числу — чтобы отчёт читался как фраза, а не как робот."""
    tail = n % 10
    if tail == 1 and n % 100 != 11:
        return "%d %s" % (n, one)
    if tail in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "%d %s" % (n, few)
    return "%d %s" % (n, many)


def _rows(n):
    """«2 строки», «5 строк» — именительный: «набор 139 строк»."""
    return _plural(n, "строка", "строки", "строк")


def _rows_acc(n):
    """То же, но винительный: «обогнал фон на 1 строку». Именительный в этой
    фразе читается как сбой шаблона, а отчёт читает владелец."""
    return _plural(n, "строку", "строки", "строк")


def beat_margin(total):
    """Сколько строк обгона фона считаем значимым на срезе в total строк.

    Почему именно столько — см. BEAT_SHARE/BEAT_FLOOR. На крошечном срезе
    (`--limit 2`) порог заведомо недостижим, и это правда: быстрый прогон
    проверяет, что стенд жив, а не меряет модель.
    """
    return max(BEAT_FLOOR, int(math.ceil(total * BEAT_SHARE)))


class StandError(Exception):
    """Ошибка, которую человек читает как фразу, а не как трейсбек."""


class SetupError(StandError):
    """Беда со стендом, а не с моделью: нет набора, фильтр пустой. Отдельный
    класс нужен ради кода возврата — скрипту в CI важно различать «модель не
    доехала» и «сам стенд запущен неправильно»."""


# ── РАЗГОВОР С OLLAMA ──────────────────────────────────────────────────────

def _down(host, reason):
    """Понятное объяснение вместо стека: чаще всего ollama просто не запущена."""
    text = str(reason).lower()
    if isinstance(reason, ConnectionRefusedError) or "refused" in text:
        return ("ollama не отвечает на %s — похоже, она не запущена.\n"
                "@@ запустить: `ollama serve` (или открыть приложение Ollama)\n"
                "@@ проверить: `curl -s %s/api/tags`" % (host, host))
    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
        return ("ollama на %s не ответила вовремя. Первый запрос после старта\n"
                "@@ грузит модель с диска и идёт дольше остальных — попробуйте\n"
                "@@ `--timeout 600` или прогрейте её: `ollama run <модель> ok`"
                % host)
    return "не достучались до ollama на %s: %s" % (host, reason)


def _http(err, model):
    body = err.read().decode("utf-8", "replace").strip()[:400]
    if err.code == 404:
        return ("ollama не нашла модель «%s» (404).\n"
                "@@ скачать: `ollama pull %s`\n"
                "@@ посмотреть, что уже есть: `ollama list`\n"
                "@@ ответ сервера: %s" % (model, model, body))
    return "ollama ответила %s %s: %s" % (err.code, err.reason, body)


def _post(url, payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    host = url.split("/api/")[0]     # в подсказках человеку нужен адрес, не ручка
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:          # подкласс URLError, ловим первым
        raise StandError(_http(err, payload.get("model")))
    except socket.timeout as err:                  # чтение ответа затянулось
        raise StandError(_down(host, err))
    except urllib.error.URLError as err:
        raise StandError(_down(host, err.reason))


def _get(url, timeout):
    """GET к ollama с теми же человеческими объяснениями, что и POST."""
    host = url.split("/api/")[0]
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        # Живой сервер, но не тот: так выглядит чужая служба на этом порту.
        raise StandError("по адресу %s отвечает не ollama: на %s пришло %s %s"
                         % (host, url[len(host):], err.code, err.reason))
    except socket.timeout as err:
        raise StandError(_down(host, err))
    except urllib.error.URLError as err:
        raise StandError(_down(host, getattr(err, "reason", err)))


def probe(host, model, timeout):
    """Спросить ollama, что у неё есть, ДО прогона.

    Дешевле упасть здесь одной фразой, чем узнать про отсутствующую модель
    на первой же строке набора и разбирать 404 из середины прогона.

    Подставлять близкое по имени нельзя. Мы меряем «числа из воздуха», а для
    этого замера размер и квантизация модели — не деталь запуска, а сама
    измеряемая величина: qwen3:4b выдумывает не так, как qwen3:8b. Поэтому
    подбор по префиксу разрешён ровно в одном случае — тег не указан и
    кандидат ровно один. Тег указан — требуем совпадения символ в символ.
    Сработавший подбор печатаем вслух, а не подставляем молча.

    Возвращает словарь с именем, digest, квантизацией и размером — они уходят
    в шапку прогона, по ней потом опознают файл ответов.
    """
    tags = _get(host.rstrip("/") + "/api/tags", timeout)
    have = {m.get("name", ""): m for m in tags.get("models", [])
            if isinstance(m, dict) and m.get("name")}
    installed = ", ".join(sorted(have)) or "ничего"

    if model in have:
        found, substituted = model, False
    elif ":" in model:
        # Тег назван явно — значит, он и есть предмет замера.
        raise StandError(
            "модель «%s» на этой машине не скачана, а тег указан явно — "
            "подставлять соседнюю нельзя.\n"
            "@@ скачать: `ollama pull %s`\n"
            "@@ сейчас есть: %s" % (model, model, installed))
    else:
        same = sorted(n for n in have if n.split(":")[0] == model)
        if len(same) == 1:
            found, substituted = same[0], True
        elif not same:
            raise StandError("модель «%s» на этой машине не скачана.\n"
                             "@@ скачать: `ollama pull %s`\n"
                             "@@ сейчас есть: %s" % (model, model, installed))
        else:
            raise StandError(
                "под именем «%s» стоит несколько моделей: %s.\n"
                "@@ какая из них — решает не стенд: укажите тег целиком, "
                "например `--model %s`" % (model, ", ".join(same), same[0]))

    info = have[found]
    details = info.get("details") or {}
    return {"имя": found, "просили": model, "подставили": substituted,
            "digest": info.get("digest") or "неизвестен",
            "квантизация": details.get("quantization_level") or "неизвестна",
            "параметров": details.get("parameter_size") or "неизвестно",
            "размер": info.get("size") or 0}


def ollama_version(host, timeout):
    """Версия ollama для шапки. Ручка /api/version появилась не сразу, и
    старая сборка — сама по себе факт прогона, а не повод его валить."""
    try:
        return _get(host.rstrip("/") + "/api/version", timeout).get(
            "version") or "не сказала"
    except StandError:
        return "ручки /api/version нет (сборка старше 0.1.14)"


def payload_for(model, line, think):
    """Запрос к /api/chat. Параметры берём из prompt.REQUEST целиком: там
    temperature 0, repeat_penalty 1.0 и num_ctx подобраны под этот промпт, и
    расходиться стенду с контрактом нельзя."""
    body = json.loads(json.dumps(REQUEST))     # копия: REQUEST правим не мы
    body["model"] = model
    body["messages"] = build_messages(line)
    if not think:
        body.pop("think", None)
    return body


def parse(text):
    """Текст ответа -> словарь.

    Схема в поле format делает ответ JSON-ом принудительно, но сборки ollama
    без поддержки think кладут рассуждение прямо в content, перед объектом.
    """
    cleaned = FENCE.sub("", THINK_TAG.sub("", text or "")).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None, "в ответе нет JSON-объекта: %r" % cleaned[:120]
    try:
        answer = json.loads(cleaned[start:end + 1])
    except ValueError as err:
        return None, "JSON не разбирается: %s" % err
    if not isinstance(answer, dict):
        return None, "JSON не объект"
    return answer, None


def ask(host, model, line, timeout, state):
    """Одна строка прайса -> (ответ-словарь, сырой текст, ошибка, пометки)."""
    url = host.rstrip("/") + "/api/chat"
    try:
        data = _post(url, payload_for(model, line, state["think"]), timeout)
    except StandError as err:
        # Поле think появилось в ollama 0.9. На сборке постарше запрос с ним
        # отлетает целиком — снимаем поле и живём на «/no_think» в system.
        if state["think"] and "think" in str(err).lower():
            state["think"] = False
            print("@@ сборка ollama не понимает поле think — сняли, "
                  "рассуждение гасим строкой «/no_think» в промпте")
            data = _post(url, payload_for(model, line, False), timeout)
        else:
            raise
    message = data.get("message") or {}
    text = message.get("content") or ""
    thought = (message.get("thinking") or "").strip()
    done = data.get("done_reason") or ""
    meta = {"done_reason": done}

    # Рассуждение вслух — это и есть тот механизм, которым модель «выводит»
    # недостающее число. Мы просили think=False; если оно всё равно пришло,
    # сборка поле игнорирует, и весь прогон измеряет не тот режим. Говорим
    # об этом один раз и кладём факт в хвост файла ответов.
    if thought or "<think>" in text:
        if not state["вслух"]:
            print("@@ рассуждение не выключено, сборка ollama игнорирует поле "
                  "think — модель думает вслух, а в этом режиме она охотнее "
                  "домысливает числа. Прогон считается, но режим не тот.")
        state["вслух"] = True
        meta["вслух"] = True

    if done == "length":
        # Обрыв по лимиту неотличим от «модель не умеет JSON»: и там и там
        # объект не разбирается. Разница дорогая — лимит чинится числом в
        # REQUEST, а неумение не чинится вовсе.
        return None, text, ("ответ обрезан на лимите num_predict=%s "
                            "(done_reason=length), а не поломан"
                            % REQUEST["options"].get("num_predict")), meta
    if not text.strip():
        return None, text, ("модель вернула пустой ответ%s"
                            % (" — весь вывод ушёл в рассуждение"
                               if thought else "")), meta
    answer, err = parse(text)
    return answer, text, err, meta


# ── ШАПКА ПРОГОНА ──────────────────────────────────────────────────────────

def prompt_fingerprint():
    """Отпечаток контракта: system + примеры + схема.

    Промпт правят чаще самой модели, и два файла ответов с одинаковой моделью,
    но разными промптами — это два разных замера. Без отпечатка их не
    различить ничем.
    """
    body = (SYSTEM + repr(FEWSHOT)
            + json.dumps(SCHEMA, ensure_ascii=False, sort_keys=True))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_fingerprint(path):
    """Отпечаток набора: строки в llm_cases.json меняются, и процент,
    посчитанный по другому набору, сравнивать со вчерашним нельзя."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except (IOError, OSError) as err:
        return "не прочитан (%s)" % err


def run_header(args, info, version, cases):
    """Первая строка jsonl и одна строка в шапке отчёта.

    Через месяц два файла ответов отличаются только этим: модель с точностью
    до digest и квантизации, параметры запроса, версия ollama, отпечаток
    промпта и самого набора, дата. Без шапки файл — просто текст, и
    «у нас было 40%» нечем подтвердить.
    """
    return {
        "запись": "шапка",
        "дата": time.strftime("%Y-%m-%d %H:%M:%S"),
        "модель": info["имя"],
        "модель_просили": info["просили"],
        "модель_подставлена": info["подставили"],
        "digest": info["digest"],
        "квантизация": info["квантизация"],
        "параметров": info["параметров"],
        "размер_байт": info["размер"],
        "ollama": {"адрес": args.host, "версия": version},
        "options": REQUEST["options"],
        "think_запрошен": REQUEST.get("think"),
        "промпт_sha256": prompt_fingerprint(),
        "набор": {"путь": os.path.abspath(args.cases),
                  "sha256": file_fingerprint(args.cases),
                  "строк": len(cases),
                  "корзины": sorted({c["bucket"] for c in cases}),
                  "limit": args.limit},
    }


def header_line(head):
    """Та же шапка в одну строку — её читают глазами в консоли."""
    opt, box = head["options"], head["набор"]
    return ("прогон %s: %s (%s, %s, digest %s) | ollama %s на %s | "
            "промпт %s | набор %s %s, %s | temp %s, seed %s, "
            "num_ctx %s, num_predict %s, think=%s" % (
                head["дата"], head["модель"], head["параметров"],
                head["квантизация"], str(head["digest"])[:19],
                head["ollama"]["версия"], head["ollama"]["адрес"],
                head["промпт_sha256"][:12], os.path.basename(box["путь"]),
                str(box["sha256"])[:12], _rows(box["строк"]),
                opt.get("temperature"),
                opt.get("seed"), opt.get("num_ctx"), opt.get("num_predict"),
                head["think_запрошен"]))


# ── ПРОГОН ─────────────────────────────────────────────────────────────────

def blocker_alive():
    """Проверить, что стенд всё ещё умеет считать свой блокер.

    Берём заведомо выдуманное число и смотрим, опознали ли мы жалобу
    валидатора. Молчащий счётчик выдуманных чисел хуже отсутствующего.
    """
    fake = {"статус": "черновик", "вид": "Круг", "вид_цитата": "Круг",
            "труба_вид": None,
            "размеры": {"диаметр": {"значение": "77", "цитата": "Круг 77"}},
            "марка_стали": None, "гост": None, "признаки": [],
            "чего_не_хватает": None}
    return any(INVENTED.search(e) for e in validate("Круг 20 мм", fake))


def load_cases(path, buckets, limit):
    """Прочитать набор строк — и упасть фразой на любом чужом файле.

    Сюда регулярно подсовывают не тот json: оборванный на середине, вывод
    другого скрипта, набор старой сборки. Все три случая должны читаться
    человеком, а не трейсбеком поверх трейсбека.
    """
    # Имя файла в подсказке — не украшение: по ней человек и соберёт набор.
    # Канон один и тот же в трёх местах — шапка llm_cases.json («built»),
    # docstring buckets.py и эта строка; подсказка на «ts.json» уводила сборку
    # в файл, который стенд потом не читает. Свой --cases подставляем как есть,
    # чтобы команда собирала ровно тот файл, который просили.
    target = ("llm_cases.json"
              if os.path.abspath(path) == os.path.abspath(CASES) else path)
    tip = ("@@ пересобрать: python3 build_ref.py ref.json && "
           "python3 buckets.py ref.json real-names.json %s" % target)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (IOError, OSError) as err:
        raise SetupError("не открывается набор %s: %s\n%s" % (path, err, tip))
    except ValueError as err:
        # json.JSONDecodeError — подкласс ValueError; так выглядит файл,
        # дописанный не до конца, и любой не-JSON.
        raise SetupError("набор %s не разбирается как JSON: %s\n"
                         "@@ похоже, файл оборван или это вообще не набор\n%s"
                         % (path, err, tip))
    if not isinstance(data, dict):
        raise SetupError("в %s лежит %s, а набор — объект с ключами cases и "
                         "buckets\n%s" % (path, type(data).__name__, tip))
    known = data.get("buckets")
    if not isinstance(known, dict):
        raise SetupError("в %s нет описания корзин (ключ buckets) — это не "
                         "набор строк\n%s" % (path, tip))
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SetupError("в %s нет списка cases — это не набор строк" % path)
    if not isinstance(cases[0], dict):
        raise SetupError("cases в %s — список %s, а не строк набора"
                         % (path, type(cases[0]).__name__))
    missing = {"bucket", "raw", "expect"} - set(cases[0])
    if missing:
        raise SetupError("в строках набора нет полей %s — набор собран старой "
                         "версией скрипта" % ", ".join(sorted(missing)))
    if buckets:
        cases = [c for c in cases if c["bucket"] in buckets]
    if limit:
        # Ограничиваем по каждой корзине, а не первые N подряд: набор
        # отсортирован по корзинам, и «первые 10» — это одна корзина A.
        seen, out = {}, []
        for c in cases:
            n = seen.get(c["bucket"], 0)
            if n < limit:
                seen[c["bucket"]] = n + 1
                out.append(c)
        cases = out
    if not cases:
        raise SetupError("после фильтров в наборе не осталось ни одной строки.\n"
                         "@@ корзины набора: %s" % ", ".join(sorted(known)))
    return data, cases


def judge(case, answer, parse_error):
    """Вердикт по одному ответу. Ничего не прощаем и ничего не досочиняем."""
    if answer is None:
        return {"errors": [parse_error], "warnings": [], "diverged": [],
                "status": None, "invented": False, "status_ok": False,
                "scored": False}
    # Дословно одинаковые жалобы схлопываем: выдуманное число стоит и в
    # значении, и в цитате, валидатор жалуется дважды — в счётчике причин это
    # выглядело бы как две разные беды. Разные жалобы не трогаем.
    errors = list(dict.fromkeys(validate(case["raw"], answer)))
    diverged = cross_check(case["raw"], answer)
    # Корзина A — это строки, которые правила разбирают ВЕРНО, она для того и
    # собрана. Значит, расхождение с правилами там — не «два мнения», а ошибка
    # модели, и место ей в браке. На остальных корзинах правила как раз и
    # ошибаются, там расхождение остаётся предупреждением.
    if case["bucket"] == "A":
        errors += [e for e in diverged if e not in errors]
        warnings = []
    else:
        warnings = diverged
    status = answer.get("статус")
    status_ok = status in case["expect"]
    return {"errors": errors, "warnings": warnings, "diverged": diverged,
            "status": status, "status_ok": status_ok,
            "invented": any(INVENTED.search(e) for e in errors),
            # Зачёт — и валидатор целиком, и попадание в ожидаемый статус.
            # Порознь каждая половина обманывает: молчун берёт первую, а
            # угадавший статус с выдуманным числом — вторую.
            "scored": not errors and status_ok}


def run(args):
    data, cases = load_cases(args.cases, args.bucket, args.limit)
    info = probe(args.host, args.model, args.timeout)
    head = run_header(args, info, ollama_version(args.host, args.timeout),
                      cases)
    print("@@ %s" % header_line(head))
    if info["подставили"]:
        print("@@ просили «%s», взяли «%s» — тег не указан, кандидат оказался "
              "один" % (info["просили"], info["имя"]))
    for key in sorted({c["bucket"] for c in cases}):
        print("@@   %s — %s" % (key, data["buckets"].get(key, "?")))

    state = {"think": "think" in REQUEST, "вслух": False}
    rows, stop, stop_err = [], None, None
    # Файл ответов открываем ДО цикла и флашим каждую строку: полный набор
    # идёт 15-25 минут, и любое исключение в середине не должно уносить всё
    # уже полученное. Шапка — первой строкой, чтобы оборванный файл всё равно
    # говорил, чем он получен.
    fh = open(args.out, "w", encoding="utf-8") if args.out else None
    try:
        if fh:
            fh.write(json.dumps(head, ensure_ascii=False) + "\n")
            fh.flush()
        for i, case in enumerate(cases, 1):
            began = time.time()
            try:
                answer, text, parse_error, meta = ask(
                    args.host, info["имя"], case["raw"], args.timeout, state)
            except KeyboardInterrupt:
                # Обрывать прогон не жалко, а терять уже полученные ответы —
                # жалко: считаем по тому, что успели.
                stop = "прервано на строке %d" % i
                break
            except Exception as err:
                # Не только Ctrl+C: ollama может умереть, сеть — отвалиться,
                # ответ — оказаться не тем. Час прогона это не стоит.
                stop, stop_err = "оборвалось на строке %d: %s" % (i, err), err
                break
            row = {"запись": "ответ", "bucket": case["bucket"],
                   "raw": case["raw"], "expect": case["expect"],
                   "answer": answer, "text": text,
                   "seconds": round(time.time() - began, 2), **meta}
            try:
                row.update(judge(case, answer, parse_error))
            except Exception as err:
                # Сам ответ уже получен и стоит минуты — записываем его в файл
                # даже если вердикт не сложился, и только потом останавливаемся.
                row["сбой_разбора"] = "%s: %s" % (type(err).__name__, err)
            if fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            if "сбой_разбора" in row:
                stop = "валидатор упал на строке %d (%s), ответ записан" % (
                    i, row["сбой_разбора"])
                break
            rows.append(row)
            mark = ("БРАК" if row["errors"] else
                    "зачёт" if row["status_ok"] else "мимо")
            print("@@ [%3d/%d] %s %-17s %-5s %5.1fс %-46s %s" % (
                i, len(cases), case["bucket"], row["status"] or "—", mark,
                row["seconds"], case["raw"][:46],
                (row["errors"][0] if row["errors"] else "")[:70]))
            sys.stdout.flush()
    finally:
        if fh:
            # Хвост: сколько ответов в файле, чем кончилось и думала ли модель
            # вслух. Про рассуждение до первого ответа знать нельзя — оттого
            # оно и в хвосте, а не в шапке.
            fh.write(json.dumps({"запись": "хвост", "ответов": len(rows),
                                 "рассуждение_просочилось": state["вслух"],
                                 "обрыв": stop},
                                ensure_ascii=False) + "\n")
            fh.close()
            print("@@ ответы записаны: %s" % args.out)

    if not rows:
        # Считать нечего. Если беда была своя (ollama не поднялась) — пусть
        # объясняется сама, своим текстом и своим кодом возврата.
        if stop_err is not None:
            raise stop_err
        raise SetupError("ни одного ответа не получено%s"
                         % (": %s" % stop if stop else ""))
    if stop:
        print("@@ %s" % stop)
        print("@@ считаю по тому, что успели: %s из %d" % (_rows(len(rows)),
                                                          len(cases)))
    return report(rows, head, state)


# ── ОТЧЁТ ──────────────────────────────────────────────────────────────────

def _pct(n, total):
    return "%5.1f%%" % (100.0 * n / total) if total else "    —"


def _share(n, total):
    """«n из total (X%)» — но процент только там, где есть что считать."""
    if total < MIN_ROWS:
        return "%d из %d (строк мало, процент не считаем)" % (n, total)
    return "%d из %d (%.1f%%)" % (n, total, 100.0 * n / total)


def family(message):
    """Имя семьи для жалобы — или None, если формулировка стенду незнакома.

    None здесь важнее имени: незнакомая жалоба обязана быть ЗАМЕТНА, а не
    подставиться в таблицу под видом собственного имени.
    """
    for pattern, name in FAMILIES:
        if pattern.search(message):
            return name
    return None


def skeleton(message):
    """Незнакомая жалоба без переменной части: содержимое «кавычек» вырезано.

    Иначе десять жалоб одной и той же формы, но с разными числами внутри,
    займут в отчёте десять строк и утопят всё остальное.
    """
    return re.sub(r"«[^»]*»", "«…»", message)


def mute_baseline(rows):
    """Тот же набор, но вместо модели — константный отказ «нужен человек».

    Это не украшение отчёта, а единица измерения. Валидатору у такого ответа
    не к чему придраться: полей нет, чисел нет, объяснение есть. Значит,
    «чисто 100%» ничего не говорит о модели, а зачёт молчуна — это ровно доля
    строк, где отказ и был правильным ответом. Всё, что модель набрала сверх
    этой цифры, она набрала сама.
    """
    clean = status = scored = 0
    for row in rows:
        case = {"bucket": row["bucket"], "raw": row["raw"],
                "expect": row["expect"]}
        verdict = judge(case, dict(MUTE), None)
        clean += int(not verdict["errors"])
        status += int(verdict["status_ok"])
        scored += int(verdict["scored"])
    return {"чисто": clean, "статус": status, "зачёт": scored}


def report(rows, head, state):
    stat, causes, nameless = {}, {}, {}
    for row in rows:
        b = stat.setdefault(row["bucket"], {"всего": 0, "зачёт": 0, "чисто": 0,
                                            "статус": 0, "воздух": 0,
                                            "расхождений": 0, "время": 0.0,
                                            "шаблоны": {}})
        b["всего"] += 1
        b["зачёт"] += int(row["scored"])
        b["чисто"] += int(not row["errors"])
        b["статус"] += int(row["status_ok"])
        b["воздух"] += int(row["invented"])
        b["расхождений"] += int(bool(row["diverged"]))
        b["время"] += row["seconds"]
        # Шаблон засчитан, только если В ЗАЧЁТЕ ВСЕ его строки: одна и та же
        # форма записи, которая то проходит, то нет, — это монетка, а не умение.
        key = TEMPLATE.sub("#", row["raw"])
        b["шаблоны"][key] = b["шаблоны"].get(key, True) and row["scored"]
        for err in row["errors"]:
            name = family(err)
            if name is None:
                key = skeleton(err)
                nameless[key] = nameless.get(key, 0) + 1
                name = NAMELESS
            causes[name] = causes.get(name, 0) + 1

    total = len(rows)
    scored = sum(1 for r in rows if r["scored"])
    invented = sum(1 for r in rows if r["invented"])
    clean = sum(1 for r in rows if not r["errors"])
    base = mute_baseline(rows)
    # Ловушка на выдумку: там, где данных нет, модель обязана отказаться.
    card_instead = [r for r in rows
                    if r["status"] == "черновик" and "черновик" not in r["expect"]]
    # Обратная беда, тише и дороже: строка разбирается, а модель отказалась.
    refused = [r for r in rows
               if r["expect"] == ["черновик"] and r["status"] not in (None, "черновик")]
    wanted_card = [r for r in rows if r["expect"] == ["черновик"]]
    wanted_refusal = [r for r in rows if "черновик" not in r["expect"]]

    # Шапку повторяем в отчёте: прогон длинный, начало уехало из экрана, а
    # копируют обычно отчёт целиком — он обязан говорить, чем получен.
    print("@@ ── отчёт")
    print("@@ %s" % header_line(head))
    if state["вслух"]:
        print("@@ ВНИМАНИЕ: модель думала вслух — сборка ollama проигнорировала "
              "think=False, замер сделан не в том режиме")

    print("@@ ── по корзинам")
    print("@@ %-2s %5s %5s %8s %8s %8s %8s %6s %7s %5s" % (
        "", "строк", "шабл", "зачёт", "шаблоны", "чисто", "статус", "воздух",
        "расхожд", "сек"))
    for key in sorted(stat):
        b = stat[key]
        forms = b["шаблоны"]
        forms_ok = sum(1 for good in forms.values() if good)
        if b["всего"] < MIN_ROWS:
            # Процент на горстке строк выглядит как замер целого класса —
            # печатаем счёт, а не долю.
            print("@@ %-2s %s, процент не считаем: зачёт %d, чисто %d, "
                  "статус %d, воздух %d, расхожд %d, %.1fс" % (
                      key, _rows(b["всего"]), b["зачёт"], b["чисто"],
                      b["статус"], b["воздух"], b["расхождений"],
                      b["время"] / b["всего"]))
            continue
        print("@@ %-2s %5d %5d %8s %8s %8s %8s %6d %7d %5.1f" % (
            key, b["всего"], len(forms), _pct(b["зачёт"], b["всего"]),
            _pct(forms_ok, len(forms)), _pct(b["чисто"], b["всего"]),
            _pct(b["статус"], b["всего"]), b["воздух"], b["расхождений"],
            b["время"] / b["всего"]))
    print("@@   зачёт   — валидатор пройден ЦЕЛИКОМ и статус совпал; главная")
    print("@@   шаблоны — тот же зачёт по уникальным формам строки (цифры")
    print("@@             зачищены): повторяющаяся форма иначе перевешивает")
    print("@@   чисто   — только валидатор, без статуса; молчун берёт тут 100%")
    print("@@   статус  — совпал с ожидаемым для этой строки")
    print("@@   расхожд — числа модели разошлись с числами правил; на A это")
    print("@@             ошибка (правила там верны), на прочих — предупреждение")

    print("@@ ── главное")
    print("@@   ЗАЧЁТ (валидатор + статус):     %s <- главная цифра прогона"
          % _share(scored, total))
    print("@@   фон немой модели: чисто %s, статус %s, зачёт %s" % (
        _pct(base["чисто"], total).strip(), _pct(base["статус"], total).strip(),
        _pct(base["зачёт"], total).strip()))
    print("@@     ^ столько даёт ответ «не_хватает_данных, нужен человек» на")
    print("@@       ВСЕ строки; прогон ниже этой планки модель не оправдывает")
    print("@@   ЧИСЛА ИЗ ВОЗДУХА:              %-4d <- блокер, допустим только 0"
          % invented)
    print("@@   карточка вместо отказа:        %s <- вторая по цене"
          % _share(len(card_instead), len(wanted_refusal)))
    print("@@   отказ там, где всё написано:   %s"
          % _share(len(refused), len(wanted_card)))
    print("@@   прошли валидатор целиком:      %s <- НЕ результат: молчун 100%%"
          % _share(clean, total))

    if causes:
        print("@@ ── причины брака")
        for name, n in sorted(causes.items(), key=lambda kv: -kv[1]):
            print("@@   %-30s %d" % (name[:30], n))
        if nameless:
            # Свалку печатаем целиком и пошире: это не «прочее», а список
            # формулировок, которых стенд не знает. Пока они здесь, таблица
            # причин неполна — её чинят дописыванием в FAMILIES.
            print("@@   ^ «%s»: так говорит валидатор," % NAMELESS)
            print("@@     а таблица причин этих формулировок не знает и валит "
                  "их в одну кучу.")
            print("@@     Допишите их в llm_assist.FAMILIES — иначе следующая "
                  "правка валидатора")
            print("@@     потеряется здесь же, молча:")
            for text, n in sorted(nameless.items(), key=lambda kv: -kv[1]):
                print("@@       %-74s %d" % (text[:74], n))

    bad = [r for r in rows if r["errors"]][:12]
    if bad:
        print("@@ ── примеры брака")
        for row in bad:
            print("@@   %s %-46s %s" % (row["bucket"], row["raw"][:46],
                                        "; ".join(row["errors"][:2])[:90]))
    if card_instead:
        print("@@ ── завела карточку там, где нечего заводить")
        for row in card_instead[:10]:
            print("@@   %s %-46s ждали %s" % (row["bucket"], row["raw"][:46],
                                              "/".join(row["expect"])))

    # Код возврата: блокер по выдуманным числам — как было, плюс сравнение с
    # фоном. Прогон, не обогнавший константный отказ ЗНАЧИМО, ничего не измерил.
    margin = scored - base["зачёт"]
    need = beat_margin(total)
    # Срез, где правильный ответ везде один и тот же отказ (типичный
    # «--bucket D»): фон забирает все строки, и обогнать его нечем физически.
    # Раньше отсюда уходила единица — безупречная модель получала тот же код,
    # что и выдумывающая числа. Это беда среза, а не модели, и код у неё свой.
    blind = base["зачёт"] == total
    print("@@ ── итог")
    if invented:
        print("@@   БЛОКЕР: %s — в таком виде модель не едет"
              % _plural(invented, "выдуманное число", "выдуманных числа",
                        "выдуманных чисел"))
    if blind:
        print("@@   на этом срезе фон берёт ВСЕ строки: правильный ответ везде "
              "один и тот же отказ,")
        print("@@   обогнать его нечем — замер ничего не показывает, нужен "
              "срез шире")
        # Про код возврата говорим только когда он и правда двойка: при
        # блокере уходит единица, и обещать здесь двойку — врать в отчёте.
        if invented:
            print("@@   код возврата всё равно 1: выдуманные числа важнее "
                  "неудачного среза")
        else:
            print("@@   код возврата 2 (мерить нечем) — это не приговор модели: "
                  "здесь её не с чем")
            print("@@   сравнить, возьмите корзины пошире, например "
                  "«--bucket A B C D»")
    elif margin >= need:
        print("@@   зачёт обогнал фон на %s из %d — порог значимости в %s взят"
              % (_rows_acc(margin), total, _rows_acc(need)))
    elif margin > 0:
        print("@@   зачёт обогнал фон всего на %s из %d, а значимым считаем "
              "обгон от %s:" % (_rows_acc(margin), total, _rows_acc(need)))
        print("@@   такой перевес даёт и случайность — считаем, что модель фон "
              "не обогнала")
    elif margin == 0:
        print("@@   зачёт вровень с фоном (%d против %d): столько же даёт ответ "
              "«нужен человек» на всё" % (scored, base["зачёт"]))
    else:
        print("@@   зачёт НИЖЕ фона (%d против %d): ответ «нужен человек» на "
              "всё даёт больше" % (scored, base["зачёт"]))
    if invented:
        return 1                       # блокер важнее всех прочих исходов
    if blind:
        return 2
    return 0 if margin >= need else 1


def one_line(args):
    """Отладочный режим: одна строка, весь ответ целиком и жалобы валидатора.

    Нужен, когда правишь промпт: по таблице видно «стало хуже», а по ответу —
    почему именно. Код возврата здесь не 0 при ЛЮБОЙ жалобе, не только на
    выдуманное число: это отладка одной строки, а не замер модели.
    """
    info = probe(args.host, args.model, args.timeout)
    if info["подставили"]:
        print("@@ просили «%s», взяли «%s» — тег не указан, кандидат оказался "
              "один" % (info["просили"], info["имя"]))
    print("@@ модель %s (%s, digest %s) | строка: %s"
          % (info["имя"], info["квантизация"], str(info["digest"])[:19],
             args.line))
    began = time.time()
    answer, text, parse_error, meta = ask(
        args.host, info["имя"], args.line, args.timeout,
        {"think": "think" in REQUEST, "вслух": False})
    print("@@ ответ за %.1fс%s:" % (
        time.time() - began,
        "" if meta["done_reason"] in ("stop", "") else
        " (done_reason=%s)" % meta["done_reason"]))
    print(json.dumps(answer, ensure_ascii=False, indent=1) if answer else text)
    errors = [parse_error] if answer is None else (
        validate(args.line, answer) + cross_check(args.line, answer))
    print("@@ валидатор: %s" % ("ошибок нет" if not errors else "ошибки:"))
    for err in errors:
        print("@@   %s" % err)
    return 1 if errors else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Прогон локальной модели по набору строк прайсов.")
    p.add_argument("--model", default=REQUEST["model"],
                   help="модель ollama (по умолчанию %s)" % REQUEST["model"])
    p.add_argument("--host", default=HOST, help="адрес ollama (%s)" % HOST)
    p.add_argument("--cases", default=CASES, help="набор строк (llm_cases.json)")
    p.add_argument("--bucket", nargs="+", metavar="A",
                   help="только эти корзины: A B C D E F")
    p.add_argument("--limit", type=int, metavar="N",
                   help="не больше N строк из КАЖДОЙ корзины — быстрый прогон")
    p.add_argument("--out", metavar="ФАЙЛ",
                   help="записать ответы построчным JSON (jsonl); первая "
                        "строка — шапка прогона")
    p.add_argument("--timeout", type=int, default=300, metavar="СЕК",
                   help="ожидание одного ответа, сек (по умолчанию 300)")
    p.add_argument("--line", metavar="СТРОКА",
                   help="разобрать одну строку и показать ответ целиком")
    args = p.parse_args(argv)

    if not blocker_alive():
        print("@@ стенд не опознаёт жалобу валидатора на выдуманное число —\n"
              "@@ значит, формулировка в draft_validate.py изменилась, а стенд\n"
              "@@ показал бы чистый прогон. Поправьте INVENTED в llm_assist.py.")
        return 2
    try:
        return one_line(args) if args.line else run(args)
    except SetupError as err:
        print("@@ %s" % err)
        return 2
    except StandError as err:
        print("@@ %s" % err)
        return 3
    except KeyboardInterrupt:
        print("@@ прервано")
        return 2


if __name__ == "__main__":
    sys.exit(main())
