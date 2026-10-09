# -*- coding: utf-8 -*-
"""Черновая раскладка листа: сколько заготовок влезает и сколько листов купить.

ЗАЧЕМ. Себестоимость материала упирается в вопрос «сколько металла реально
придётся купить». До этого файла ответ давал один коэффициент использования на
весь документ, и владелец сразу назвал его слабое место: «коэффициент
использования от 50% до 97% бывает».

Разброс объясняется не материалом, а укладкой: крупная деталь 1400×2900 из
листа 1500×6000 даёт под 95%, десяток мелких — половину. Значит коэффициент
надо не угадывать, а считать из габаритов.

ПОЧЕМУ ЭТО ЧЕСТНЫЙ РАСЧЁТ, А НЕ ОЦЕНКА. Менеджер вводит в спецификацию ГАБАРИТ
детали: круг Ø100 записывается как квадрат 100×100 (решение владельца). То есть
в расчёте и так лежат прямоугольники — ровно то, что потом выкраивают. Укладка
прямоугольников здесь не упрощение задачи, а её точная постановка.

⚠️ ЭТО НЕ РАСКРОЙ И НЕ ЗАМЕНА ТЕХНОЛОГУ. Технолог раскладывает детали плотнее:
поворачивает, вкладывает мелкие в вырезы крупных, объединяет разные позиции на
одном листе. Поэтому наш ответ — ВЕРХНЯЯ оценка закупки. Для коммерческого
предложения это безопасная сторона: лучше заложить чуть больше, чем уйти в
минус. Слово «черновая» в названии кнопки стоит намеренно.

С шага З-13 (09.10.2026) детали ОДНОГО листа (толщина, вид, габарит) мы тоже
кладём вместе — полосами через весь лист (раздел «Совместная раскладка» в
конце файла). Повод — прогон Кытмановой: Z-полоса 560 мм оставляла обрезок
380 мм на каждом из 67 листов, а в него встают три П-полосы по 120 мм;
раздельно выходило 93 листа, вместе — 76. Вложения в вырезы и раскрой
CypCut мы не повторяем: ответ остаётся верхней оценкой, только честнее.

Файл без ORM и без обращений к базе — как cutting.py в модуле раскроя
сортамента: те же функции проверяются тестами без стенда.
"""

import math

# Ширина реза по умолчанию — лазер. Значение то же, что в модуле лазерной
# резки (0,2 мм подтверждено техпараметрами CypCut в файлах завода).
# ⚠️ Дублировать нельзя: при расхождении два числа разъедутся молча. Значение
# приходит параметром, здесь только запасное на случай вызова без него.
DEFAULT_KERF_MM = 0.2

# Отступ от кромки листа на сторону. Ноль по решению владельца 23.09.2026:
# «пока что считаем лист от самого края. не усложняем». Параметр оставлен,
# чтобы появившееся требование не потребовало переписывать расчёт.
DEFAULT_EDGE_MM = 0.0

# Допуск «деталь в размер листа». Заготовка шириной ровно в лист не оставляет
# места ни под рез, ни под кромку, и формула дала бы ноль штук. На деле такую
# деталь режет прокатный стан, а не наш станок: лист приходит нужной ширины.
DEFAULT_TOLERANCE_MM = 5.0


def _fit_in_line(usable_mm, size_mm, kerf_mm, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Сколько заготовок размера size встанет в отрезок usable.

    Между n заготовками n−1 резов, а не n: последний край — это край листа.
    Отсюда n = (usable + kerf) // (size + kerf), а не usable // (size + kerf):
    вторая формула теряет одну заготовку на каждом ряду.

    ⚠️ ДОПУСК НА РЯД ОБЯЗАТЕЛЕН, И ВОТ ПОЧЕМУ. Строгая формула на заготовке
    500 мм в листе 1500 даёт ДВА ряда: три заготовки плюс два реза — это
    1500,4 мм, на 0,4 мм больше листа. Арифметически верно, практически
    неверно: технолог посадит три, потому что рез съедает металл заготовки,
    а не добавляет длины, и четыре десятых миллиметра уходят в допуск проката.
    Без этой поправки расчёт систематически покупает лишний лист — на 500-й
    заготовке ровно вдвое больше нужного.

    Поэтому разрешаем превышение до tolerance_mm (5 мм): ряд на одну
    заготовку длиннее принимается, если он выходит за лист не больше чем на
    допуск. Заготовка 600 мм так не пройдёт: четвёртая даёт перебор в 300 мм.
    """
    if size_mm <= 0 or usable_mm < size_mm:
        return 0
    count = int(math.floor((usable_mm + kerf_mm) / (size_mm + kerf_mm)))
    # Одна лишняя заготовка, если она выходит за край в пределах допуска.
    over = (count + 1) * size_mm + count * kerf_mm
    if over <= usable_mm + tolerance_mm:
        count += 1
    return count


def _fit_axis(sheet_mm, size_mm, kerf_mm, edge_mm, tolerance_mm):
    """Заготовки вдоль одной оси листа, с учётом кромки и правила «в размер»."""
    count = _fit_in_line(sheet_mm - 2 * edge_mm, size_mm, kerf_mm, tolerance_mm)
    # Деталь занимает лист по этой оси целиком — кромку по ней не обрезают.
    # Без этого правила заготовка 1000×1000 из листа 1000×4000 давала бы ноль
    # штук вместо трёх: по ширине не хватало бы миллиметров на отступ.
    if 0 < size_mm <= sheet_mm + tolerance_mm:
        count = max(count, 1)
    return count


def fit_rows(sheet_w, sheet_l, part_a, part_b, kerf_mm, edge_mm, tolerance_mm):
    """Укладка рядами, оба поворота заготовки. Возвращает (штук, схема)."""
    args = (kerf_mm, edge_mm, tolerance_mm)
    across_0 = _fit_axis(sheet_w, part_a, *args)
    along_0 = _fit_axis(sheet_l, part_b, *args)
    across_90 = _fit_axis(sheet_w, part_b, *args)
    along_90 = _fit_axis(sheet_l, part_a, *args)

    straight = (across_0 * along_0, "%d×%d" % (across_0, along_0))
    turned = (across_90 * along_90, "%d×%d, поворот" % (across_90, along_90))
    return max(straight, turned)


def fit_mixed(sheet_w, sheet_l, part_a, part_b, kerf_mm, edge_mm, tolerance_mm):
    """Основная зона плюс остаток полосой — заготовки в ней лежат поперёк.

    Схема гильотинная, из двух блоков: отрезаем полосу через весь лист и
    кладём в неё заготовки другим поворотом. Выполнимо на любом станке, это
    не вложенный раскрой.

    Замер на 45 парах (три ходовых габарита × пятнадцать размеров заготовок):
    выигрывает в восьми случаях, лучший — заготовка 90×460, где укладка растёт
    со 198 штук до 210, а использование с 91,1% до 96,6%.
    """
    args = (kerf_mm, edge_mm, tolerance_mm)
    usable_w = sheet_w - 2 * edge_mm
    usable_l = sheet_l - 2 * edge_mm
    best = (0, "")

    for first, second, turn in ((part_a, part_b, ""), (part_b, part_a, ", поворот")):
        # Полоса отрезается по ширине листа.
        rows = _fit_in_line(usable_w, first, kerf_mm, tolerance_mm)
        if rows:
            rest = usable_w - (rows * (first + kerf_mm) - kerf_mm) - kerf_mm
            total = rows * _fit_in_line(usable_l, second, kerf_mm, tolerance_mm)
            extra = _fit_in_line(rest, second, kerf_mm, tolerance_mm) * _fit_in_line(usable_l, first, kerf_mm, tolerance_mm)
            if extra:
                best = max(best, (total + extra, "%d рядами + %d полосой%s"
                                  % (total, extra, turn)))

        # Полоса отрезается по длине листа.
        cols = _fit_in_line(usable_l, second, kerf_mm, tolerance_mm)
        if cols:
            rest = usable_l - (cols * (second + kerf_mm) - kerf_mm) - kerf_mm
            total = cols * _fit_in_line(usable_w, first, kerf_mm, tolerance_mm)
            extra = _fit_in_line(rest, first, kerf_mm, tolerance_mm) * _fit_in_line(usable_w, second, kerf_mm, tolerance_mm)
            if extra:
                best = max(best, (total + extra, "%d рядами + %d полосой%s"
                                  % (total, extra, turn)))

    # Ряды без полосы — тоже допустимый исход смешанной схемы.
    return max(best, fit_rows(sheet_w, sheet_l, part_a, part_b, *args))


def fit_sheet(sheet_w, sheet_l, part_a, part_b,
              kerf_mm=DEFAULT_KERF_MM, edge_mm=DEFAULT_EDGE_MM,
              tolerance_mm=DEFAULT_TOLERANCE_MM, mixed=True):
    """Сколько заготовок a×b влезает в лист W×L.

    Возвращает (штук, схема, состояние). Состояния:
      ok       — посчитано;
      no_size  — габарит заготовки не задан;
      too_big  — заготовка не помещается в лист ни одним поворотом;
      exact    — заготовка в размер листа, одна штука.
    """
    if part_a <= 0 or part_b <= 0:
        return 0, "", "no_size"
    if sheet_w <= 0 or sheet_l <= 0:
        return 0, "", "no_size"

    args = (kerf_mm, edge_mm, tolerance_mm)
    if mixed:
        count, scheme = fit_mixed(sheet_w, sheet_l, part_a, part_b, *args)
    else:
        count, scheme = fit_rows(sheet_w, sheet_l, part_a, part_b, *args)

    if count == 0:
        return 0, "", "too_big"
    if count == 1 and part_a >= sheet_w - tolerance_mm and part_b >= sheet_l - tolerance_mm:
        return 1, "лист в размер", "exact"
    return count, scheme, "ok"


def plan_sheets(sheet_w, sheet_l, part_a, part_b, qty, **kwargs):
    """Раскладка под нужное количество заготовок.

    Возвращает словарь: сколько влезает в лист, сколько листов купить, какая
    доля металла уходит в заготовки и по какой схеме.

    ⚠️ ИСПОЛЬЗОВАНИЕ СЧИТАЕТСЯ ПО ФАКТИЧЕСКОМУ КОЛИЧЕСТВУ, А НЕ ПО ПОЛНОМУ
    ЛИСТУ. Нужна одна заготовка, а влезает шесть — купить придётся целый лист,
    и в затраты изделия он войдёт целиком: годный остаток владелец решил
    относить на изделие. Поэтому доля здесь = площадь нужных заготовок ÷
    площадь купленных листов, и на маленьком заказе она честно низкая.
    """
    per_sheet, scheme, state = fit_sheet(sheet_w, sheet_l, part_a, part_b, **kwargs)
    qty = int(qty or 0)

    if state in ("no_size", "too_big") or per_sheet <= 0 or qty <= 0:
        return {
            "per_sheet": per_sheet, "sheets": 0, "utilization_pct": 0.0,
            "scheme": scheme, "state": state if qty > 0 else "no_qty",
        }

    sheets = int(math.ceil(qty / float(per_sheet)))
    part_area = (part_a / 1000.0) * (part_b / 1000.0) * qty
    sheet_area = (sheet_w / 1000.0) * (sheet_l / 1000.0) * sheets
    utilization = (part_area / sheet_area * 100.0) if sheet_area else 0.0

    return {
        "per_sheet": per_sheet,
        "sheets": sheets,
        "utilization_pct": round(utilization, 1),
        "scheme": scheme,
        "state": state,
    }


# ─── Сигнал «лист используется плохо» (разбор UX, шаг 32) ──────────────────
#
# ЗАЧЕМ. На вкладке «Раскладка» лист 6 мм ради 20 кг деталей (использование
# 4,7 %) выглядел так же, как лист, уложенный на 96 %. А это прямо про
# замороженные деньги: лист покупается целиком, и остаток лежит на складе.
#
# Пороги — из вопроса «Пороги сигналов» (29.09.2026), взяты предложенные в
# документе: меньше 50 % — жёлтым («больше половины листа уйдёт в остаток»),
# меньше 20 % — красным («лист покупается ради малой детали»). Цвет повторён
# словом — «мало» / «очень мало», — чтобы сигнал читался и без цвета.
# Сигнал только показывает: ни раскладку, ни КП он не останавливает.
SHEET_USE_LOW_PCT = 50.0
SHEET_USE_BAD_PCT = 20.0

# Раскладка посчитана: обычная укладка и «деталь в размер листа». Остальные
# состояния (нет габарита, нет количества, деталь больше листа, не считалась)
# процента не дают — и сигнала по ним нет.
SHEET_USE_COUNTED = ("ok", "exact")

NBSP = " "


def _pct_text(value):
    """56.0 → «56», 38.5 → «38,5», 4.66 → «4,7»: один знак, «,0» отбрасываем."""
    text = "%.1f" % float(value or 0.0)
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def sheet_use_label(pct, state):
    """Подпись и уровень использования листа: («4,7 % · очень мало», "bad").

    Уровни: ok — от 50 % и выше, low — от 20 до 50, bad — меньше 20,
    none — раскладка не посчитана (подписи нет).
    """
    if state not in SHEET_USE_COUNTED:
        return False, "none"
    pct = float(pct or 0.0)
    text = "%s%s%%" % (_pct_text(pct), NBSP)
    if pct < SHEET_USE_BAD_PCT:
        return "%s · очень мало" % text, "bad"
    if pct < SHEET_USE_LOW_PCT:
        return "%s · мало" % text, "low"
    return text, "ok"


# ─── Совместная раскладка (шаг З-13, 09.10.2026) ──────────────────────────
#
# ЗАЧЕМ. Раскладка по каждой детали отдельно покупала лишнее там, где у одной
# детали остаётся обрезок, а другая деталь того же листа в него встаёт.
# Прогон Кытмановой (СМ-00037/38, лист 3 мм 1500×6000): Z 560×3000 — две по
# ширине, обрезок 380 мм на каждом из 67 листов; П 120×3000 встаёт в него
# по три. Раздельно 26 + 67 = 93 листа, вместе 76 (≈17 листов, ~3,6 т).
#
# КАК. Полосы (полки) через весь лист — гильотинный раскрой, который режется
# на любом станке:
#   1. каждая деталь ложится одним из двух поворотов; высота полки — меньшая
#      сторона детали («low») или большая («high»);
#   2. детали по убыванию высоты укладываются в первую полку, где хватает
#      длины (сразу пачкой: сколько влезает), остаток — в новые полки;
#   3. полки по убыванию высоты — в первый лист, где хватает ширины
#      (first-fit decreasing).
# Полосы идут вдоль длины листа («L») или поперёк («W»); из четырёх
# вариантов берём тот, где листов меньше. Отдельно — вариант «полные листы
# каждой детали отдельно, вместе только остатки».
#
# НИКОГДА НЕ ХУЖЕ ПРЕЖНЕГО. Совместную укладку берём, только если листов
# СТРОГО меньше, чем сумма раздельных (plan_sheets по каждой детали). Одна
# деталь в группе — тот же plan_sheets один в один.
#
# Рез и кромка — те же, что у раздельной: рез 0,2 мм между деталями в полке и
# между полками, кромка 0 (решение владельца 23.09), допуск ряда 5 мм — то же
# правило, что _fit_in_line: рез съедает металл заготовки (3000 + 0,2 + 3000
# в листе 6000 — две заготовки, а не одна).
#
# Деталь, у которой своя раскладка не «Посчитана» (в размер листа, больше
# листа, без габарита, без количества), в совместную укладку не идёт: лист в
# размер — по листу на штуку, как раньше; остальные листов не дают. Иначе
# одна деталь «больше листа» роняла бы всю группу.

_EPS = 1e-9


def _plural_ru(number, one, few, many):
    """1 лист, 2 листа, 5 листов (копия spec_layout._plural: файл без ORM)."""
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def _mm_text(value):
    text = "%.1f" % float(value or 0.0)
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def part_label(part_a, part_b):
    """Размер детали словами схемы: «560×3000», «120,5×210»."""
    return "%s×%s" % (_mm_text(part_a), _mm_text(part_b))


def _row_count(room_mm, size_mm, kerf_mm, tolerance_mm, first):
    """Сколько заготовок size встанет в остаток ряда room.

    first — ряд пуст: n заготовок и n−1 резов; иначе перед каждой новой
    заготовкой ещё рез. Допуск ряда — как в _fit_in_line: ряд может выйти за
    лист не больше чем на tolerance_mm.
    """
    if size_mm <= 0:
        return 0
    room = room_mm + tolerance_mm + (kerf_mm if first else 0.0)
    return max(int(math.floor(room / (size_mm + kerf_mm) + _EPS)), 0)


def _pack_shelves(stack_mm, run_mm, parts, rule, kerf_mm, tolerance_mm):
    """Полки поперёк stack (высоты складываются по stack), детали вдоль run.

    parts — [(key, a, b, qty)]. Возвращает список листов; лист — список
    полок (высота, [(key, штук, высота детали, длина детали), ...]), или
    None, если какая-то деталь не ложится ни одним поворотом.
    """
    items = []
    for key, part_a, part_b, qty in parts:
        if qty <= 0:
            continue
        options = [(h, l) for h, l in ((part_a, part_b), (part_b, part_a))
                   if 0 < h <= stack_mm + tolerance_mm and 0 < l <= run_mm + tolerance_mm]
        if not options:
            return None
        pick = min if rule == "low" else max
        height, length = pick(options, key=lambda option: option[0])
        items.append((height, length, key, int(qty)))
    # Высокие — первыми: полку открывает самая высокая деталь, низкие
    # добирают её длину.
    items.sort(key=lambda item: (-item[0], -item[1]))

    shelves = []        # [высота, занято по длине, [(key, штук, h, l)]]
    for height, length, key, qty in items:
        for shelf in shelves:
            if not qty:
                break
            if shelf[0] + _EPS < height:
                continue
            fit = min(qty, _row_count(run_mm - shelf[1], length, kerf_mm,
                                      tolerance_mm, first=False))
            if fit <= 0:
                continue
            shelf[1] += fit * (length + kerf_mm)
            shelf[2].append((key, fit, height, length))
            qty -= fit
        per_shelf = _row_count(run_mm, length, kerf_mm, tolerance_mm, first=True)
        if qty and per_shelf <= 0:
            return None
        while qty:
            fit = min(qty, per_shelf)
            shelves.append([height, fit * length + (fit - 1) * kerf_mm,
                            [(key, fit, height, length)]])
            qty -= fit

    # Полки — в листы: первый лист, где хватает ширины (полки уже по
    # убыванию высоты). Между полками — рез. Указатель «первый лист, куда
    # ещё может встать полка этой высоты» держим между полками одной высоты:
    # иначе на тысячах полок перебор листов шёл бы с начала каждый раз.
    shelves.sort(key=lambda shelf: -shelf[0])
    sheets = []         # [занято по ширине, [полки]]
    limit = stack_mm + tolerance_mm
    start = {}
    for height, _used, content in shelves:
        index = start.get(height, 0)
        while index < len(sheets) and sheets[index][0] + kerf_mm + height > limit + _EPS:
            index += 1
        start[height] = index
        if index == len(sheets):
            sheets.append([height, [(height, content)]])
        else:
            sheets[index][0] += kerf_mm + height
            sheets[index][1].append((height, content))
    return [sheet[1] for sheet in sheets]


def pack_group(sheet_w, sheet_l, parts, kerf_mm=DEFAULT_KERF_MM,
               edge_mm=DEFAULT_EDGE_MM, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Совместная укладка деталей одного листа полосами.

    parts — [(key, a, b, qty)]. Лучший из четырёх вариантов (полосы вдоль /
    поперёк листа × высота полки по меньшей / большей стороне) или None,
    если какая-то деталь не ложится ни одним поворотом.

    Возвращает {"sheets": n, "axis": "L"|"W", "rule": "low"|"high",
    "bins": [[(высота полки, [(key, штук, h, l), ...]), ...], ...]}.
    Ось «L»: полка — полоса поперёк ширины листа, детали в ней лежат вдоль
    длины; «W» — наоборот.
    """
    usable_w = sheet_w - 2 * edge_mm
    usable_l = sheet_l - 2 * edge_mm
    if usable_w <= 0 or usable_l <= 0:
        return None
    best = None
    for axis in ("L", "W"):
        stack, run = (usable_w, usable_l) if axis == "L" else (usable_l, usable_w)
        for rule in ("low", "high"):
            bins = _pack_shelves(stack, run, parts, rule, kerf_mm, tolerance_mm)
            if bins is None:
                continue
            if best is None or len(bins) < best["sheets"]:
                best = {"sheets": len(bins), "axis": axis, "rule": rule, "bins": bins}
    return best


def iter_placements(sheet_w, sheet_l, packed, kerf_mm=DEFAULT_KERF_MM,
                    edge_mm=DEFAULT_EDGE_MM):
    """Координаты деталей укладки pack_group — для проверки (тесты).

    Выдаёт (лист №, key, x, y, w, l): x и w — поперёк листа (по ширине),
    y и l — вдоль (по длине), миллиметры от угла листа.
    """
    axis = packed["axis"]
    for number, shelves in enumerate(packed["bins"], 1):
        offset = edge_mm
        for height, content in shelves:
            position = edge_mm
            for key, count, part_h, part_l in content:
                for _index in range(count):
                    if axis == "L":
                        yield number, key, offset, position, part_h, part_l
                    else:
                        yield number, key, position, offset, part_l, part_h
                    position += part_l + kerf_mm
            offset += height + kerf_mm


def _bin_patterns(bins, order):
    """Листы укладки → {вариант: листов}; вариант — ((key, штук), ...)."""
    counts = {}
    for shelves in bins:
        content = {}
        for _height, items in shelves:
            for key, count, _h, _l in items:
                content[key] = content.get(key, 0) + count
        pattern = tuple((key, content[key]) for key in order if key in content)
        counts[pattern] = counts.get(pattern, 0) + 1
    return counts


def _sorted_patterns(counts, order):
    """Варианты по убыванию листов, при равенстве — по порядку деталей."""
    rank = {key: index for index, key in enumerate(order)}
    return sorted(counts.items(), key=lambda item: (
        -item[1], [rank.get(key, 0) for key, _count in item[0]]))


def _shares(total, weights):
    """Разделить total целых листов по весам методом наибольшего остатка.

    Сумма долей ровно total; доля может быть нулём.
    """
    keys = list(weights)
    if not keys or total <= 0:
        return {key: 0 for key in keys}
    whole = sum(weights.values())
    if whole <= 0:
        quotas = {key: float(total) / len(keys) for key in keys}
    else:
        quotas = {key: total * weights[key] / whole for key in keys}
    shares = {key: int(math.floor(quotas[key] + _EPS)) for key in keys}
    rest = total - sum(shares.values())
    rank = {key: index for index, key in enumerate(keys)}
    order = sorted(keys, key=lambda key: (-(quotas[key] - shares[key]), rank[key]))
    for key in order[:rest]:
        shares[key] += 1
    return shares


def plan_group(sheet_w, sheet_l, parts, kerf_mm=DEFAULT_KERF_MM,
               edge_mm=DEFAULT_EDGE_MM, tolerance_mm=DEFAULT_TOLERANCE_MM,
               joint=True):
    """Раскладка группы деталей одного листа и габарита: вместе или раздельно.

    parts — [(key, a, b, qty)], qty — на весь заказ. Возвращает словарь:
      sheets            — листов купить на группу;
      sheets_separate   — сумма раздельных plan_sheets (как было до З-13);
      mode              — "joint" (вместе) или "separate" (отдельно);
      utilization_pct   — площадь посчитанных деталей / площадь листов;
      lines             — {key: per_sheet, sheets (доля), scheme, state,
                           utilization_pct, joint}; сумма долей = sheets
                          группы; joint — деталь легла в совместную укладку
                          (её «Листов» — доля общих листов);
      patterns          — [(((key, штук), ...), листов), ...] по убыванию
                          листов: что лежит на листе.

    Доля детали в совместной укладке — листы, разделённые по площади
    деталей (наибольший остаток): «Заявка на металл» складывает доли строк
    листа и получает листы группы, без задвоения. «В листе» и «Схема» строки
    остаются своими — «если резать эту деталь отдельно».

    joint=False — только раздельно (как до З-13): так раскладываются детали
    без выбранного листа — толщина неизвестна, класть их на общий лист
    нельзя.
    """
    kwargs = {"kerf_mm": kerf_mm, "edge_mm": edge_mm, "tolerance_mm": tolerance_mm}
    order = [part[0] for part in parts]
    sizes = {key: (float(part_a or 0.0), float(part_b or 0.0), int(qty or 0))
             for key, part_a, part_b, qty in parts}
    plans = {key: plan_sheets(sheet_w, sheet_l, sizes[key][0], sizes[key][1],
                              sizes[key][2], **kwargs)
             for key in order}
    sheet_area = (sheet_w / 1000.0) * (sheet_l / 1000.0)

    def area(key, count=None):
        part_a, part_b, qty = sizes[key]
        return (part_a / 1000.0) * (part_b / 1000.0) * (qty if count is None else count)

    counted_area = sum(area(key) for key in order
                       if plans[key]["state"] in SHEET_USE_COUNTED)

    def utilization(sheets):
        if not sheets or not sheet_area:
            return 0.0
        return round(counted_area / (sheets * sheet_area) * 100.0, 1)

    separate = sum(plans[key]["sheets"] for key in order)
    separate_patterns = {}
    for key in order:
        if plans[key]["sheets"]:
            pattern = ((key, plans[key]["per_sheet"]),)
            separate_patterns[pattern] = separate_patterns.get(pattern, 0) + plans[key]["sheets"]
    result = {
        "sheets": separate,
        "sheets_separate": separate,
        "mode": "separate",
        "utilization_pct": utilization(separate),
        "lines": {key: dict(plans[key], joint=False) for key in order},
        "patterns": _sorted_patterns(separate_patterns, order),
    }

    joint_keys = [key for key in order if plans[key]["state"] == "ok"]
    if not joint or len(joint_keys) < 2:
        return result
    own_exact = {key: plans[key]["sheets"] for key in order
                 if plans[key]["state"] == "exact"}

    candidates = []     # (листов, свои полные листы, укладка, площади)
    # 1. Все «посчитанные» детали — вместе.
    packed = pack_group(sheet_w, sheet_l,
                        [(key,) + sizes[key] for key in joint_keys], **kwargs)
    if packed is not None:
        candidates.append((packed["sheets"], {}, packed,
                           {key: area(key) for key in joint_keys}))
    # 2. Полные листы каждой детали — отдельно, вместе только остатки.
    full, rest = {}, []
    for key in joint_keys:
        per_sheet = plans[key]["per_sheet"]
        qty = sizes[key][2]
        full[key] = qty // per_sheet if per_sheet else 0
        left = qty - full[key] * per_sheet
        if left > 0:
            rest.append((key, sizes[key][0], sizes[key][1], left))
    if len(rest) >= 2:
        packed_rest = pack_group(sheet_w, sheet_l, rest, **kwargs)
        if packed_rest is not None:
            candidates.append((sum(full.values()) + packed_rest["sheets"], full, packed_rest,
                               {key: area(key, left) for key, _a, _b, left in rest}))
    best = None
    for candidate in candidates:
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        return result
    joint_sheets = best[0] + sum(own_exact.values())
    if joint_sheets >= separate:
        return result

    _total, own, packed, weights = best
    shares = _shares(packed["sheets"], weights)
    patterns = _bin_patterns(packed["bins"], order)
    for key, count in list(own.items()) + list(own_exact.items()):
        if count:
            pattern = ((key, plans[key]["per_sheet"]),)
            patterns[pattern] = patterns.get(pattern, 0) + count

    util = utilization(joint_sheets)
    lines = {}
    for key in order:
        # «Вместе» — только детали, вошедшие в совместную укладку (weights):
        # деталь варианта 2 без остатка режется на своих полных листах, и
        # «в размер листа» — тоже на своих.
        line = dict(plans[key], joint=key in weights)
        if key in joint_keys:
            line["sheets"] = own.get(key, 0) + shares.get(key, 0)
            line["utilization_pct"] = util
        lines[key] = line
    result.update({
        "sheets": joint_sheets,
        "mode": "joint",
        "utilization_pct": util,
        "lines": lines,
        "patterns": _sorted_patterns(patterns, order),
        "axis": packed["axis"],
        "rule": packed["rule"],
    })
    return result


def group_scheme_text(patterns, labels, limit=3):
    """Схема группы словами: «66 листов: 560×3000 — 4, 120×3000 — 6;
    9 листов: 120×3000 — 24; ещё 1 вариант».

    patterns — из plan_group, labels — {key: подпись детали}. Показываем
    limit самых частых вариантов листа, остальные — числом.
    """
    parts = []
    for pattern, sheets in patterns[:limit]:
        content = ", ".join("%s — %s" % (labels.get(key, key), count)
                            for key, count in pattern)
        parts.append("%s %s: %s" % (
            sheets, _plural_ru(sheets, "лист", "листа", "листов"), content))
    more = len(patterns) - limit
    if more > 0:
        parts.append("ещё %s %s" % (more, _plural_ru(more, "вариант", "варианта", "вариантов")))
    return "; ".join(parts)
