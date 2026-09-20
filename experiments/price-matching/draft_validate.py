# -*- coding: utf-8 -*-
"""Валидатор ответа модели на задаче «черновик карточки».

Смысл: ответ модели не попадает в справочник напрямую. Сначала код доказывает,
что КАЖДОЕ число и КАЖДОЕ решающее слово в ответе физически присутствует во
входной строке — и взято оттуда, откуда контракт разрешает его брать. Что не
доказано — отбрасывается, а не «принимается на веру, раз выглядит разумно».

Валидатор не умнее модели, он просто недоверчив. И недоверчив дважды: форму
ответа задаёт схема из prompt.py, но исполняет схему ollama, а меряем мы
модель — поэтому форму здесь перепроверяет свой код. Ответ, пришедший мимо
грамматики (руками, из другого прогона, из другой сборки ollama), не должен
проезжать только потому, что его никто не пересмотрел.

Ни одна проверка не имеет права упасть на кривом ответе: трейсбек посреди
прогона — это потерянные двадцать минут и соблазн «прогнать без валидатора».
Поэтому дальше по ответу идут только поля, доказавшие свою цитату.
"""
import json
import re

from match import TYPE_RULES, normalise
from prompt import KINDS, SCHEMA, PIPE_KINDS, SIZE_FIELDS, TRAITS

# Какие размерные поля допустимы у какого вида. Всё остальное — брак разбора.
FIELDS_BY_KIND = {
    "Труба ВГП": {"диаметр", "стенка"},
    "Труба профильная прямоугольная": {"высота", "ширина", "стенка"},
    "Труба профильная квадратная": {"высота", "ширина", "стенка"},
    "Труба круглая": {"диаметр", "стенка"},
    "Уголок неравнополочный": {"высота", "ширина", "стенка"},
    "Уголок равнополочный": {"высота", "ширина", "стенка"},
    "Швеллер": {"номер_профиля", "серия"},
    "Двутавр": {"номер_профиля", "серия"},
    "Арматура": {"диаметр"},
    "Шестигранник": {"сторона"},
    "Квадрат": {"сторона"},
    "Круг": {"диаметр"},
}

# Список видов обязан совпадать с контрактом. Разъедется — вид из prompt.py
# останется без размерных полей, и каждый его размер станет «не бывает у вида».
# Падать тут не страшно: импорт случается до первого вопроса модели, а не на
# двадцатой минуте прогона.
assert set(FIELDS_BY_KIND) == set(KINDS), "FIELDS_BY_KIND разошёлся с prompt.KINDS"

NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)?")

# Жалоба на выдуманное число — блокер. Формулировку задаёт validate() ниже,
# и regexp держим рядом с ней: разъедутся — счётчик в разборе выгрузки молча
# обнулится и покажет чистый результат там, где числа берутся из воздуха.
INVENTED = re.compile(r"число «.+?» отсутствует во входной строке")

# Ответ молчуна: константный отказ без единого поля. Валидатору к нему не
# придраться — придираться не к чему, — и в этом весь смысл: столько же
# «чистых» ответов даёт модель, которая не сказала ничего. Тем же ответом
# меряет фон llm_assist (MUTE), но держим мы его своим: разбор выгрузки
# обязан считать фон и тогда, когда стенд правят рядом.
MUTE_ANSWER = {"статус": "не_хватает_данных", "вид": None, "вид_цитата": None,
               "труба_вид": None, "размеры": {}, "марка_стали": None,
               "гост": None, "признаки": [], "чего_не_хватает": "нужен человек"}

TRAIT_ROOT = {"оцинкованный": r"оцинк", "горячекатаный": r"г/к|горячекатан",
              "холоднокатаный": r"х/к|холоднокатан", "калиброванный": r"калибр"}

# Слово, которым строка доказывает вид трубы. Бесшовная и электросварная —
# разные позиции справочника с разной ценой, и «похоже на бесшовную» тут не
# аргумент. Своего списка сокращений здесь намеренно нет: normalise() из
# match.py уже свела «б/ш», «бесш.», «э/с», «в/г» к одному написанию
# (см. match.ABBR), а второй список синонимов разъехался бы с разборщиком.
PIPE_ROOT = {
    "Бесшовная": r"\bбесшовная\b",
    "Электросварная": r"\bэлектросварная\b",
    # ВГП в прайсах пишут и словом, и условным проходом: «Ду25».
    "ВГП": r"\bвгп\b|\bду\s?\d",
}
assert set(PIPE_ROOT) == set(PIPE_KINDS), "PIPE_ROOT разошёлся с prompt.PIPE_KINDS"

# Синонимы вида, которых нет в match.ABBR. Список намеренно короткий: каждая
# строка здесь — расхождение с разборщиком, и заводится она только там, где
# без неё бракуется ВЕРНЫЙ ответ. «Разнополочный» — так назван весь раздел
# уголка у Феррума; в match.ABBR есть «неравнопол*» и «н/п», а этого написания
# нет, и из-за него верное «Уголок неравнополочный» отвергалось, а неверное
# «равнополочный» на той же строке проходило. В match.py синоним не несём: по
# нему считается базовая цифра разбора, и менять её посреди замера нельзя.
KIND_SYNONYMS = [
    (re.compile(r"\bразнопол\w*\b"), "неравнополочный"),
    # «Трубы профильные» — название раздела каталога, и match.ABBR разворачивает
    # только «проф.», а не «профильные»: по словам такая строка выглядела
    # круглой трубой, и профильная 160х80х4,0 бракуется, а круглая проходит.
    # Правила спасает третье число (_pmk_reconcile), но слов оно не меняет.
    (re.compile(r"\bпрофильн\w*\b"), "профильная"),
    # «Труба квадратная», «Труба прямоугольная» — та же профильная, только
    # названная формой сечения. Квадратную от прямоугольной всё равно решают
    # числа, а не слово (см. проверку 13).
    (re.compile(r"\bтруба\s+(?:квадратн\w*|прямоугольн\w*)\b"), "профильная труба"),
    (re.compile(r"\b(?:квадратн\w*|прямоугольн\w*)\s+труба\b"), "профильная труба"),
]

# Кириллическая «х» в match.normalise — разделитель размеров, и слово, которое
# с неё начинается, слипается с предыдущим: «бесшовная холоднодеформированная»
# становится «бесшовнаяxолоднодеформированная», а \bбесшовная\b там уже не
# находится. Шесть живых строк теряли вид трубы ни за что. Возвращаем пробел:
# между двумя буквами «x» ничего не разделяет, это буква, а не разделитель.
SPLIT_LETTER = re.compile(r"(?<=[а-яё])x(?=[а-яё])")

# Слово, прилипшее к числу, ломает границу слова: в «вгп40» после «п» нет \b,
# и \bвгп\b не находит ничего — ни как вид, ни как труба_вид. Те же грабли,
# что у SIZE_PREFIX в match.py («ду25x3.2»), только со стороны слова, а не
# числа. Разделяем их пробелом: числам это безразлично, здесь по тексту
# решается только вид.
GLUED = re.compile(r"(?<=[а-яёa-z])(?=\d)", re.I)

# Шаблоны вида, как их видит match.detect_type. Квадратная и прямоугольная
# профильные делят одни и те же слова — по словам они неразличимы, и различают
# их числа (см. проверку 13). Поэтому вид сверяем не с именем правила, а с его
# набором шаблонов: два вида с одним набором друг друга не отменяют.
KIND_WORDS = {name: tuple(patterns) for name, patterns in TYPE_RULES}
# Вид из контракта, которого нет в правилах, доказать нечем — и каждый такой
# вид молча превратился бы в «взят ниоткуда» на всех строках подряд. Лишнее
# правило в match.py, наоборот, не мешает: оно просто нам не встретится.
assert set(KINDS) <= set(KIND_WORDS), "в TYPE_RULES нет слов для видов: %s" % (
    sorted(set(KINDS) - set(KIND_WORDS)))

# Виды, которые различаются не словом поставщика, а числами: (равные, разные).
KIND_BY_NUMBERS = {
    "Труба профильная": ("Труба профильная квадратная",
                         "Труба профильная прямоугольная"),
    "Уголок": ("Уголок равнополочный", "Уголок неравнополочный"),
}

# Размеры, у которых есть порядок: так они и стоят в строке — «60х30х2».
# Номер профиля и серия сюда не входят, они не связка размеров.
ORDERED = ("высота", "ширина", "диаметр", "сторона", "стенка")

# Связка размеров: «133*4,0», «50 х 25 х 2,0», «40х40х2». Внутри одной связки
# порядок чисел — это и есть роли полей, и перестановка внутри неё запрещена.
# Числа из РАЗНЫХ мест строки («Ду15» и «20х2,8») друг другу порядок не диктуют.
GROUP = re.compile(r"\d+(?:[.,]\d+)?(?:\s*[xх×*XХ•]\s*\d+(?:[.,]\d+)?)+")

# Куски строки, из которых размер брать нельзя: контракт велит их игнорировать,
# а число в них настоящее — проверка «число есть в строке» его пропускает.
# Регулярки свои, а не из match.py, потому что работают по СЫРОЙ строке:
# в match.py они живут после normalise(), где марка и ГОСТ уже вырезаны.
IGNORED = [
    # «ст.20», «ст3сп5», «сталь 09Г2С»: отсюда приезжает выдуманная стенка.
    # Числа марок перечислены поимённо, а не как \d+, и это важно: в прайсах
    # «ст.» значит ещё и «стальной» — «Швеллер ст. 14» это номер профиля 14,
    # а не марка Ст14, которой не существует.
    ("марка стали", re.compile(
        r"\b(?:ст|сталь|марка)\s*\.?\s*(?:08|10|15|20|25|30|35|40|45|50|55|60|[0-6])"
        r"(?:\s?(?:кп|пс|сп)\d?)?\b", re.I)),
    ("марка стали", re.compile(
        r"\b(?:09г2с|10хснд|15хснд|17г1с|20кп|40х|s235|s355|с2\d\d|с3\d\d|с440)\b",
        re.I)),
    ("класс арматуры", re.compile(r"\bа\s?\d{3}[а-яёc]?\b|\bа\s?[iv]{1,3}\b", re.I)),
    ("ГОСТ", re.compile(r"\bгост\s*(?:р\s*)?\d+(?:[.\-]\d+)*(?:\s*-\s*\d+)?", re.I)),
    # Длина: «L=6000», «дл. 6м», «11,7м», «12м». «мм» сюда не попадает
    # намеренно — «Круг 20 мм» это диаметр с единицей, а не длина.
    ("длина", re.compile(r"\bl\s*[=:]?\s*\d+(?:[.,]\d+)?", re.I)),
    ("длина", re.compile(r"\bдл(?:ина)?\.?\s*\d+(?:[.,]\d+)?", re.I)),
    ("длина", re.compile(r"\d+(?:[.,]\d+)?\s*м\b", re.I)),
    ("вес, цена, остаток", re.compile(
        r"\d+(?:[.,]\d+)?\s*(?:кг|тн|т|шт|руб|р\.|₽)\b", re.I)),
]


def _loose(s):
    """Схлопнуть пробелы: в прайсах из PDF их бывает по два-три подряд,
    и модель их обычно нормализует. Цифры это не затрагивает."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def _spans(text):
    """Куски строки, которые контракт велит игнорировать, с их именами."""
    out = []
    for name, rx in IGNORED:
        for m in rx.finditer(text):
            out.append((m.start(), m.end(), name))
    return out


def _source(pos, spans):
    """Имя игнорируемого куска, внутри которого стоит символ pos, иначе None."""
    for start, end, name in spans:
        if start <= pos < end:
            return name
    return None


def _groups(text):
    return [(m.start(), m.end()) for m in GROUP.finditer(text)]


def _group_at(pos, groups):
    for i, (start, end) in enumerate(groups):
        if start <= pos < end:
            return i
    return None


def _places(text, obj):
    """Позиции в строке, где стоит значение поля.

    Не «где угодно в строке», а внутри своей цитаты: цитата — это место, на
    которое модель показала пальцем, и судим мы именно его. Число ищем целым
    токеном, чтобы «6» из «60» не считалось.
    """
    quote, val = _loose(obj.get("цитата")), _loose(obj.get("значение"))
    if not quote or not val:
        return []
    needle = (r"(?<![\d.,])%s(?![\d.,])" % re.escape(val)
              if NUM_TOKEN.fullmatch(val) else re.escape(val))
    out = set()
    for q in re.finditer(re.escape(quote), text):
        for v in re.finditer(needle, text[q.start():q.end()]):
            out.add(q.start() + v.start())
    return sorted(out)


def _number(obj):
    """Число из поля {значение, цитата}, если оно вообще число.

    Ни одна проверка не имеет права упасть на кривом поле, поэтому «не число»
    здесь — это None, а не исключение: значение без числа судят другие
    проверки, а эта просто молчит.
    """
    if not isinstance(obj, dict):
        return None
    try:
        return float(_loose(obj.get("значение")).replace(",", "."))
    except (AttributeError, TypeError, ValueError):
        return None


def _shape_errors(node, schema, path):
    """Схема prompt.py, исполненная своим кодом — вторая линия обороны.

    В прогоне схему держит ollama: там она превращается в грамматику, и лишнее
    поле физически невозможно. Но валидатор судит и ответы, которые грамматику
    не проходили, а именно лишним полем выдуманная «масса_метра» и заезжает:
    проверка чисел её пропустит, если цифры случайно есть в строке или если их
    в ней нет вовсе.
    """
    if "anyOf" in schema:
        for variant in schema["anyOf"]:
            if not _shape_errors(node, variant, path):
                return []
        return ["форма ответа нарушена: %s не подходит ни под один вариант" % path]

    kind = schema.get("type")
    if kind == "object":
        if not isinstance(node, dict):
            return ["форма ответа нарушена: %s — не объект" % path]
        props, errors = schema.get("properties", {}), []
        for key in node:
            if key not in props:
                errors.append("лишнее поле в ответе: %s.%s — такого поля в "
                              "контракте нет" % (path, key))
        for key in schema.get("required", []):
            if key not in node:
                errors.append("форма ответа нарушена: нет поля %s.%s" % (path, key))
        for key, sub in props.items():
            if key in node:
                errors += _shape_errors(node[key], sub, "%s.%s" % (path, key))
        return errors
    if kind == "array":
        if not isinstance(node, list):
            return ["форма ответа нарушена: %s — не список" % path]
        errors = []
        for i, item in enumerate(node):
            errors += _shape_errors(item, schema["items"], "%s[%d]" % (path, i))
        return errors
    if kind == "string":
        if not isinstance(node, str):
            return ["форма ответа нарушена: %s — не строка" % path]
        if "enum" in schema and node not in schema["enum"]:
            return ["%s: «%s» вне закрытого списка" % (path, node)]
        return []
    if kind == "null":
        return [] if node is None else ["форма ответа нарушена: %s — не null" % path]
    return []


def _quoted_ok(field, obj, raw, errors):
    """True, если поле доказало цитатой и значение, и число.

    Возвращаемое значение важнее сообщений: дальше по ответу идут только те
    поля, по которым эта функция сказала «да». Поле, признанное браком,
    остальные проверки не трогают — иначе один кривой ответ роняет весь прогон.
    """
    if not isinstance(obj, dict):
        errors.append("%s: не объект {значение, цитата}" % field)
        return False
    val, quote = obj.get("значение"), obj.get("цитата")
    if not isinstance(val, str) or not isinstance(quote, str) or not val or not quote:
        errors.append("%s: пустое значение или цитата" % field)
        return False
    if quote not in raw and _loose(quote) not in _loose(raw):
        errors.append("%s: цитаты «%s» нет в строке" % (field, quote))
        return False
    if val not in quote and _loose(val) not in _loose(quote):
        errors.append("%s: значения «%s» нет в цитате «%s»" % (field, val, quote))
        return False
    # Число должно быть целым токеном: «6» из «60» не считается.
    if NUM_TOKEN.fullmatch(val):
        edges = re.search(r"(?<![\d.,])%s(?![\d.,])" % re.escape(val), quote)
        if not edges:
            errors.append("%s: «%s» — кусок другого числа" % (field, val))
            return False
    return True


def _kind_text(s):
    """Текст, по которому решают вид: нормализация match.py плюс три поправки.

    Поправки живут здесь, а не в match.py, и все три — про написание, а не про
    смысл: слипшиеся слова (SPLIT_LETTER), синонимы вида (KIND_SYNONYMS) и
    слово, прилипшее к числу (GLUED). Числа и позиции по этому тексту не
    считаются — только слова вида, поэтому лишний пробел ничему не мешает.
    """
    text = SPLIT_LETTER.sub(" х", normalise(s)["text"])
    for pattern, repl in KIND_SYNONYMS:
        text = pattern.sub(repl, text)
    return GLUED.sub(" ", text)


def _kind_words(text):
    """Набор шаблонов правила, которое первым узнало вид в тексте.

    Ровно тот же выбор, что делает match.detect_type: порядок правил в
    TYPE_RULES — это и есть решение, узкие раньше общих.
    """
    for name, patterns in TYPE_RULES:
        if any(re.search(p, text) for p in patterns):
            return tuple(patterns)
    return None


def _kind_proved(kind, quote, raw):
    """Следует ли вид из процитированного слова — и не спорит ли с ним строка.

    Опираемся на те же ключевые слова, по которым вид определяет match.py:
    свой словарь синонимов разъехался бы с разборщиком на первой же правке.
    normalise() приводит «Балка» к «двутавр», «профтруба» к «профильная труба»,
    поэтому сравнивать можно прямо правилами TYPE_RULES.

    Но «шаблон вида нашёлся» — ещё не доказательство: у «Трубы круглой» шаблон
    ловит просто слово «труба», и цитата «Труба» из строки «Труба профильная
    70х70х4,0» доказывала круглую трубу. На корзине B это значит, что любая
    профильная труба могла быть выдана за круглую. Поэтому узкое слово бьёт
    общее — и бьёт по ВСЕЙ строке, а не по одной цитате: вырезать «профильная»
    из цитаты модель может, из строки поставщика — нет.
    """
    patterns = KIND_WORDS.get(kind)
    if not patterns:
        return False
    if not any(re.search(p, _kind_text(quote)) for p in patterns):
        return False
    winner = _kind_words(_kind_text(raw))
    # Вид того же набора шаблонов — не спор: квадратную от прямоугольной
    # отличают числа. Строка, не узнанная правилами вовсе, права отменять
    # цитату не имеет — там доказательство только одно, и оно уже проверено.
    return winner is None or winner == patterns


def validate(raw, answer):
    """Вернуть список ошибок. Пустой список — ответ можно показывать человеку."""
    errors = []
    if not isinstance(answer, dict):
        return ["ответ не объект JSON"]
    raw = raw if isinstance(raw, str) else ""

    # 1. Ни одного числа мимо строки — главная проверка, ради неё всё затеяно.
    #    Идёт по всему ответу целиком, какой бы формы он ни был: выдуманное
    #    число обязано попасть в счётчик блокера даже из кривого ответа.
    in_raw = set(NUM_TOKEN.findall(raw)) | set(NUM_TOKEN.findall(_loose(raw)))
    for token in NUM_TOKEN.findall(json.dumps(answer, ensure_ascii=False)):
        if token not in in_raw:
            errors.append("число «%s» отсутствует во входной строке" % token)

    # 2. Форма ответа — по схеме контракта, своим кодом (см. _shape_errors).
    errors += _shape_errors(answer, SCHEMA, "ответ")

    status = answer.get("статус")
    kind = answer.get("вид")
    # Вид вне закрытого списка уже назван схемой. Дальше он не роль, а мусор:
    # по нему нельзя ни выбрать поля размеров, ни спросить справочник.
    known_kind = kind if kind in FIELDS_BY_KIND else None

    # 3. Каждое значение — с доказанной цитатой. Дальше работаем только с теми.
    sizes = answer.get("размеры")
    if not isinstance(sizes, dict):
        if sizes is not None:
            errors.append("размеры: не объект")
        sizes = {}
    proven = {}
    for name, obj in sizes.items():
        if name not in SIZE_FIELDS:
            continue            # про лишнее поле размеров уже сказала схема
        if _quoted_ok("размеры." + name, obj, raw, errors):
            proven[name] = obj
    # Марка и ГОСТ — не размеры, но и они доказывают цитату, и по ним тоже
    # надо будет посмотреть, ОТКУДА взято число (см. проверку 6б).
    extra = {}
    for name in ("марка_стали", "гост"):
        if answer.get(name) is not None and _quoted_ok(name, answer[name], raw,
                                                       errors):
            extra[name] = answer[name]

    # 4. Вид обязан опираться на слово ИЗ СТРОКИ, а не на любую подстроку.
    #    Без этой проверки полоса становится уголком, а болт — кругом: цитата
    #    «Полоса» лежит в строке, и больше её никто ни с чем не сверяет.
    quote = answer.get("вид_цитата")
    if isinstance(quote, str) and quote:
        if quote not in raw and _loose(quote) not in _loose(raw):
            errors.append("вид_цитата: «%s» нет в строке" % quote)
        elif known_kind and not _kind_proved(known_kind, quote, raw):
            errors.append("вид не подтверждён цитатой: из «%s» не следует «%s»"
                          % (quote, known_kind))
    elif known_kind:
        errors.append("вид не подтверждён цитатой: «%s» взят ниоткуда" % known_kind)

    # 5. Поля размеров должны подходить виду.
    if known_kind:
        allowed = FIELDS_BY_KIND[known_kind]
        for name in proven:
            if name not in allowed:
                errors.append("поле «%s» не бывает у вида «%s»" % (name, known_kind))

    # ── дальше всё считаем по одной и той же нормализованной строке, чтобы
    #    позиции чисел, игнорируемые куски и связки размеров не разъезжались.
    text = _loose(raw)
    spans, groups = _spans(text), _groups(text)
    places = {name: _places(text, obj) for name, obj in proven.items()}

    # 6. Число настоящее, но взято из куска, который контракт велит пропускать:
    #    стенка из марки стали («ст. 20») или из длины («12м»). Проверка чисел
    #    такое пропускает — число-то в строке есть, — поэтому смотрим ОТКУДА.
    for name in sorted(proven):
        if name == "серия":
            continue
        found = places.get(name) or []
        # Номеру профиля длина не запрещена намеренно: «Балка 24М» — это серия
        # М, а не 24 метра; отличить их в тексте нечем, и вычеркнуть живой
        # номер дороже, чем пропустить номер, взятый из «12м».
        tolerated = ("длина",) if name == "номер_профиля" else ()
        sources = [None if _source(pos, spans) in tolerated else _source(pos, spans)
                   for pos in found]
        if found and all(sources):
            errors.append("размер взят из игнорируемого куска: %s ← %s"
                          % (name, sources[0]))

    # 6б. Обратный случай: число настоящее и взято из связки размеров, но
    #     названо не размером. Проверка выше ходит только по answer["размеры"],
    #     и мимо неё проезжала марка стали, списанная с габарита: «Труба
    #     профильная 60х30х1,5», марка_стали «60» — цитата честная, число в
    #     строке есть, валидатор молчал. Марки Ст60 в той строке нет, есть
    #     первое число размера. То же и с ГОСТом: номер стандарта из связки
    #     размеров — это размер, чем бы его ни назвали.
    for name in sorted(extra):
        value = _loose(extra[name].get("значение"))
        if not NUM_TOKEN.fullmatch(value):
            continue
        spots = _places(text, extra[name])
        if spots and all(_group_at(pos, groups) is not None for pos in spots):
            errors.append("%s: «%s» взято из связки размеров — это размер"
                          % (name, value))

    # 7. Порядок размеров — по позиции в САМОЙ строке, а не внутри общей
    #    цитаты. Если у каждого размера своя цитата, диаметр со стенкой можно
    #    поменять местами, и подмена пройдёт чисто: «Труба 60 х 3,5» с
    #    диаметром 3,5 и стенкой 60. Сравниваем только числа из одной связки:
    #    «Ду15» и «20х2,8» стоят в разных местах и порядок друг другу не диктуют.
    present = [f for f in ORDERED if places.get(f)]
    for i, first in enumerate(present):
        swapped = None
        for second in present[i + 1:]:
            # Порядок в строке — воля поставщика, и часть из них пишет толщину
            # ПЕРВОЙ: «Уголок стальной, 4х25 мм» — это уголок 25x25x4, шесть
            # живых строк корзины C. Переставить роли там нельзя физически:
            # толщина полки не бывает больше самой полки. Проверку ставили
            # против ДРУГОГО случая — там стенке досталось БОЛЬШЕЕ число
            # («Труба 60 х 3,5» со стенкой 60), и он остаётся браком: поблажка
            # спрашивает именно про числа, а не про порядок. Обратную сторону
            # той же физики стережёт проверка 7б.
            wall, size = _number(proven.get(second)), _number(proven.get(first))
            if second == "стенка" and wall is not None and size is not None \
                    and wall < size:
                continue
            pairs = [(a, b) for a in places[first] for b in places[second]
                     if _group_at(a, groups) is not None
                     and _group_at(a, groups) == _group_at(b, groups)]
            # Равные позиции — это одно и то же число в двух ролях: «Уголок
            # равнополочный 20 х 4», где полка названа один раз. Переставлять
            # там нечего, и брак это не перестановка, а совпадение.
            if pairs and not any(a <= b for a, b in pairs):
                swapped = second
                break
        if swapped:
            errors.append("порядок размеров не совпадает со строкой: «%s» стоит "
                          "в ней позже, чем «%s»" % (first, swapped))
            break

    # 7б. Стенка тоньше габарита — это физика, а не предпочтение поставщика.
    #     Проверка нужна в паре с поблажкой выше: раз меньшее число мы пускаем
    #     в стенку без оглядки на порядок, большее обязано быть остановлено
    #     здесь — иначе «Уголок 4х25» с полкой 4 и стенкой 25 проехал бы
    #     мимо обеих проверок.
    wall = _number(proven.get("стенка"))
    for name in ("высота", "ширина", "диаметр", "сторона"):
        size = _number(proven.get(name))
        if wall is not None and size is not None and wall >= size:
            errors.append("стенка «%s» не тоньше габарита «%s» — так не бывает"
                          % (proven["стенка"]["значение"], proven[name]["значение"]))
            break

    # 8. Серия полок обязана стоять вплотную к номеру — так она и пишется:
    #    20Ш1, 16аУ, 14 У. Поиск подстрокой находит «Б» внутри «Балка», а «П»
    #    внутри «СТ3СП5», и на строке «Балка 10» рождается готовый черновик
    #    «Двутавр 10Б». 10Б1 и 10П — разные профили с разной массой метра.
    series = proven.get("серия")
    if series:
        letters = _loose(series["значение"])
        number = _loose((proven.get("номер_профиля") or {}).get("значение"))
        if number and places.get("номер_профиля"):
            # Смотрим не «есть ли где-то в строке цифра с этой буквой», а стоит
            # ли буква вплотную к ТОМУ САМОМУ номеру, который модель процитировала.
            # Иначе на «Балка 12 12м» серия «М» находится в длине.
            near = re.compile(r"%s\s?%s" % (re.escape(number), re.escape(letters)),
                              re.I)
            hit = [p for p in places["номер_профиля"] if near.match(text, p)]
        else:
            # Номера в ответе нет — тогда хотя бы рядом с любым числом, но не
            # внутри марки: «П» из «СТ3СП5» это не серия полок.
            hit = [m for m in re.finditer(r"\d\s?%s" % re.escape(letters), text, re.I)
                   if _source(m.start(), spans) not in ("марка стали", "ГОСТ",
                                                        "класс арматуры")]
        if not hit:
            errors.append("серия полок не стоит рядом с номером: «%s» в строке "
                          "не написана" % letters)

    # 9. Статусы: у черновика должен быть вид и хоть один размер,
    #    у отказа «не_прокат» — ничего, кроме объяснения.
    if status == "черновик":
        if not kind:
            errors.append("черновик без вида")
        if not sizes:
            errors.append("черновик без единого размера")
        if known_kind in ("Швеллер", "Двутавр") and "серия" not in sizes:
            errors.append("черновик швеллера/двутавра без серии полок")
    if status == "не_прокат" and (kind or sizes):
        errors.append("не_прокат, но поля заполнены")
    if status == "вид_вне_списка" and (kind or sizes):
        errors.append("вид_вне_списка, но вид или размеры заполнены")
    if status != "черновик" and not answer.get("чего_не_хватает"):
        errors.append("отказ без объяснения")

    # 10. Свободный текст — без цифр: иначе число просочится мимо цитат.
    note = answer.get("чего_не_хватает") or ""
    if isinstance(note, str) and NUM_TOKEN.search(note):
        errors.append("«чего_не_хватает» содержит число")

    # 11. Признаки: слово должно быть в строке, а не в памяти модели.
    traits = answer.get("признаки")
    for trait in traits if isinstance(traits, list) else []:
        if trait not in TRAITS:
            continue            # про значение вне списка уже сказала схема
        if not re.search(TRAIT_ROOT[trait], raw, re.I):
            errors.append("признака «%s» нет в строке" % trait)

    # 12. Труба бесшовная или электросварная — у нас разные позиции, и слово
    #     должно быть в строке ровно так же, как слово признака. Для признаков
    #     такая проверка была с самого начала, для труба_вид её забыли: модель
    #     писала «Бесшовная» там, где буквами написано «электросварная».
    pipe = answer.get("труба_вид")
    if isinstance(pipe, str) and pipe in PIPE_ROOT:
        # Ищем по тому же тексту, что и вид: на «Труба ВГП40*3.5» слово ВГП
        # прилипло к числу, границы слова нет, и раньше обе ветки ответа были
        # тупиком — «ВГП» бракована как неназванная, а null бракован тем, что
        # у вида «Труба ВГП» труба_вид обязан быть «ВГП».
        if not re.search(PIPE_ROOT[pipe], _kind_text(raw)):
            errors.append("вид трубы не подтверждён строкой: «%s» в ней не "
                          "названа" % pipe)
        if known_kind and not known_kind.startswith("Труба"):
            errors.append("труба_вид указан у вида «%s» — это не труба" % known_kind)
    if known_kind == "Труба ВГП" and pipe != "ВГП":
        errors.append("для ВГП труба_вид должен быть «ВГП»")

    # 13. Квадратная или прямоугольная решают числа, а не слово поставщика.
    #     У уголка ровно то же: «равнополочный» — это равные полки, и 63х40
    #     ими быть не может, как бы строку ни назвали. Раньше проверка была
    #     только у трубы, и уголок с разными полками проходил равнополочным.
    for prefix, (same_kind, diff_kind) in sorted(KIND_BY_NUMBERS.items()):
        if not known_kind or not known_kind.startswith(prefix):
            continue
        h, w = _number(proven.get("высота")), _number(proven.get("ширина"))
        if h is None or w is None:
            continue
        need = same_kind if h == w else diff_kind
        if known_kind != need:
            errors.append("по числам это «%s»" % need)
    return errors


def cross_check(raw, answer):
    """Сверка с правилами match.py: если детерминированный разборщик тоже
    достал числа, они обязаны совпасть. Расхождение — не повод верить кому-то
    одному, а повод показать строку человеку."""
    from match import normalise, extract_numbers
    rule_nums = extract_numbers(normalise(raw)["text"])
    if not rule_nums:
        return []
    model_nums = []
    for name, obj in (answer.get("размеры") or {}).items():
        if name == "серия" or not isinstance(obj, dict):
            continue
        try:
            model_nums.append(float(obj["значение"].replace(",", ".")))
        except (ValueError, KeyError, AttributeError):
            return ["размер не читается как число"]
    if model_nums and sorted(model_nums) != sorted(rule_nums):
        return ["правила прочли %s, модель %s" % (rule_nums, model_nums)]
    return []


# ── «ТАКОЕ У НАС УЖЕ ЕСТЬ» ─────────────────────────────────────────────────
# Единственное, что пережило смерть старого validate.py. Это не ошибка разбора
# и не брак: ответ может быть безупречным, но задача была — ЗАВЕСТИ НОВУЮ
# позицию, а модель собрала карточку той, что уже лежит в справочнике. Такой
# черновик человеку нести незачем, и в валидатор он не входит намеренно:
# корзина A целиком состоит из строк, которые в справочнике есть, и черновик
# там — правильный ответ, а не брак.
_REF = {}


def _matcher():
    """Справочник для проверки «а нет ли такой позиции уже».

    Собираем из тех же CSV модуля pmk_calc, что и build_ref.py: отдельный
    reference.json может быть не собран, а CSV в репозитории лежат всегда.
    Не собрался — возвращаем None, и проверка честно говорит «не проверено»,
    а не «чисто»: молчаливый пропуск и есть та самая красивая ложь.
    """
    if "matcher" not in _REF:
        try:
            from build_ref import build
            from match import Matcher
            _REF["matcher"] = Matcher(build())
        except (OSError, ValueError, KeyError, ImportError) as err:
            _REF["matcher"], _REF["почему"] = None, str(err)
    return _REF["matcher"]


def known_position(answer):
    """Позиции справочника, совпавшие с черновиком модели.

    Вернёт None, если справочник не собрался (это «не проверено»), список
    названий — если такая позиция уже заведена, и пустой список, если нет.
    Ключ строим теми же profile_key/_pmk_reconcile, что и разборщик: свой
    способ сложить размеры в ключ разъехался бы с match.py, и «дубликата»
    переставало бы хватать ровно там, где он есть.
    """
    matcher = _matcher()
    if matcher is None:
        return None
    if not isinstance(answer, dict):
        return []
    kind = answer.get("вид")
    if kind not in FIELDS_BY_KIND:
        return []
    sizes = answer.get("размеры")
    if not isinstance(sizes, dict):
        return []

    def value(name):
        obj = sizes.get(name)
        return obj.get("значение") if isinstance(obj, dict) else None

    if kind in ("Швеллер", "Двутавр"):
        number, series = value("номер_профиля"), value("серия")
        if not number or not series:
            return []
        try:
            nums = (float(str(number).replace(",", ".")),)
        except ValueError:
            return []
        hits = matcher.by_type_letters.get(
            (kind, nums, re.sub(r"\s+", "", str(series)).lower()), [])
        return ["%s %s" % (h["type"], h["size"]) for h in hits]

    nums = []
    for name in ORDERED:
        raw_value = value(name)
        if raw_value is None:
            continue
        try:
            nums.append(float(str(raw_value).replace(",", ".")))
        except ValueError:
            return []
    if not nums:
        return []
    nums, kind = matcher._pmk_reconcile(kind, nums)
    hits = matcher.by_type_nums.get((kind, tuple(nums)), [])
    return ["%s %s" % (h["type"], h["size"]) for h in hits]


def _selftest():
    """Самопроверка контракта: few-shot примеры обязаны проходить собственный
    валидатор. Если не проходят — учим модель тому, что сами же отвергаем."""
    from prompt import FEWSHOT
    bad = 0
    for raw, answer in FEWSHOT:
        errs = validate(raw, answer) + cross_check(raw, answer)
        known = known_position(answer)
        note = ("справочник не собран" if known is None else
                ("уже есть: " + known[0]) if known else "")
        print("%-58s %-28s %s" % (raw[:58], "ок" if not errs else "; ".join(errs),
                                  note))
        bad += bool(errs)
    print("@@ примеров с ошибками: %s из %s" % (bad, len(FEWSHOT)))
    return 1 if bad else 0


def _check_file(path):
    """Пересудить выгрузку прогона (llm_assist.py --out answers.jsonl).

    Это ПЕРЕСУД записанных ответов текущим валидатором, а не замер модели:
    прогон идёт в llm_assist.py, там же считается и главная цифра. Раньше тут
    печаталась одна строка «прошли валидатор: N», и на выгрузке немой модели
    она показывала 139 из 139 — ту самую красивую ложь, ради которой в отчёте
    стенда и заведён фон: ответу «не_хватает_данных, нужен человек» валидатору
    придраться не к чему, полей в нём нет. Поэтому фон считаем и здесь, по тем
    же строкам, и «чисто» без него не печатаем.

    Считает заодно то, чего в самом прогоне нет: сколько черновиков описывают
    позицию, которая в справочнике уже есть. Это не брак, а промах задачи,
    поэтому и живёт отдельно.
    """
    total = clean = dup = invented = graded = scored = background = 0
    unchecked = False
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        answer = row.get("answer")
        if answer is None:
            continue
        total += 1
        raw = row.get("raw", "")
        errors = list(dict.fromkeys(validate(raw, answer)))
        # Корзина A — строки, которые правила разбирают ВЕРНО. Расхождение с
        # ними там не «два мнения», а ошибка модели: так судит и стенд, и
        # считать здесь мягче значило бы показывать другую цифру.
        if row.get("bucket") == "A":
            errors += [e for e in cross_check(raw, answer) if e not in errors]
        clean += not errors
        invented += sum(1 for e in errors if INVENTED.search(e))
        # Зачёт и фон считаются только там, где известно, какой ответ на эту
        # строку верный. Выгрузка без ожидаемого статуса судить себя не даёт.
        expect = row.get("expect")
        if isinstance(expect, list) and expect:
            graded += 1
            scored += int(not errors and answer.get("статус") in expect)
            background += int(not validate(raw, MUTE_ANSWER)
                              and MUTE_ANSWER["статус"] in expect)
        # Дубликат считаем только по чистым черновикам: у забракованного
        # ответа и совпадение с позицией справочника ничего не значит.
        known = None if errors or answer.get("статус") != "черновик" \
            else known_position(answer)
        if known is None and not errors and answer.get("статус") == "черновик":
            unchecked = True
        elif known:
            dup += 1
            if dup <= 10:
                print("@@ уже в справочнике: %-46s -> %s"
                      % (str(row.get("raw", ""))[:46], known[0]))
    print("@@ ответов: %s | прошли валидатор: %s <- НЕ результат: столько же "
          "даёт отказ «нужен человек» на всё" % (total, clean))
    print("@@ черновиков на позицию, которая уже есть: %s" % dup)
    if unchecked:
        print("@@ справочник не собрался (%s) — дубликаты НЕ проверены"
              % _REF.get("почему", "причина неизвестна"))
    if invented:
        print("@@ ЧИСЛА ИЗ ВОЗДУХА: %d — блокер, допустим только 0" % invented)
    if not graded:
        print("@@ ожидаемых статусов в выгрузке нет (старая сборка или чужой "
              "файл) — зачёт и фон считать не из чего")
        print("@@ то есть это разбор ответов, а не замер: цифру прогона даёт "
              "llm_assist.py")
        return 1 if invented else 0
    print("@@ зачёт (валидатор + ожидаемый статус): %s из %s" % (scored, graded))
    print("@@ фон немой модели на этих же строках: %s из %s" % (background,
                                                                graded))
    print("@@   ^ столько берёт константный отказ; ниже этой планки выгрузка "
          "не измерила ничего")
    if scored <= background:
        print("@@ ИТОГ: зачёт не обогнал фон — в этой выгрузке мерить нечего")
    else:
        print("@@ ИТОГ: зачёт обогнал фон (%s против %s); насколько это "
              "значимо, считает llm_assist.py — здесь только грубая планка"
              % (scored, background))
    return 1 if invented or scored <= background else 0


if __name__ == "__main__":
    import sys
    sys.exit(_check_file(sys.argv[1]) if len(sys.argv) > 1 else _selftest())
