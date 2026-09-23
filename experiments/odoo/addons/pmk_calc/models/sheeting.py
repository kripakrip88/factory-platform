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
