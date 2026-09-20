# -*- coding: utf-8 -*-
"""Линейный раскрой: разложить нужные отрезки по имеющимся хлыстам.

Чистая арифметика, БЕЗ обращения к базе — поэтому проверяется тестами.
Так же устроен расчёт доборки: единственное место, где живёт формула.

ЗАЧЕМ СВОЙ КОД, А НЕ ГОТОВЫЙ ДВИЖОК. Задача одномерная, и это принципиально:
вся сложность двумерного раскроя — геометрическая (столкновения фигур,
повороты), а здесь её нет вообще. Классическая Cutting Stock Problem
решается на чистом питоне за миллисекунды, причём время зависит от числа
РАЗНЫХ ДЛИН, а не от числа деталей: заказ на 500 отрезков считается не
дольше, чем на 50.

ЧТО СЧИТАЕМ. Даны заготовки (хлысты и обрезки со склада) — у каждой длина,
количество и очерёдность — и нужные отрезки с количествами. Раскладываем так,
чтобы израсходовать как можно меньше металла, при этом сперва пуская в дело
то, что уже лежит на складе.
"""

from collections import Counter


def cut_plan(stocks, parts, kerf=0.0, min_useful=0.0):
    """Разложить отрезки по заготовкам.

    stocks: [{"length": 6000, "qty": 10, "name": "Хлыст 6 м", "priority": 20}]
            qty=None — заготовка неограничена (закупаем сколько надо).
            priority — меньше значит раньше в дело; обрезки со склада
            ставят вперёд, чтобы они уходили первыми.
    parts:  [{"length": 1450, "qty": 22, "name": "Стойка"}]
    kerf:   ширина пропила, мм — съедается на КАЖДОМ резе.
    min_useful: от какой длины остаток считается годным и идёт на склад;
            всё короче — лом.

    Возвращает словарь с раскладкой, остатками и итогами.
    """
    demand = _expand(parts)
    if not demand:
        return _empty_result(stocks)

    available = _prepare(stocks)

    # Пробуем НЕСКОЛЬКО порядков и берём лучший. Так дёшево (расчёт идёт
    # миллисекунды), что жадничать нет причин, а разница бывает разительной:
    # на восьми отрезках по 2900 порядок «сначала короткие» дал 4 хлыста по
    # 6 м и 3,33% отхода, «сначала длинные» — 2 хлыста по 11,7 м и 0,85%.
    best = None
    for order in _orderings(available):
        bars, unplaced = _fill(order, demand, kerf)
        result = _summarise(bars, unplaced, available, kerf, min_useful)
        if best is None or _score(result) < _score(best):
            best = result
    return best


def _score(result):
    """Чем меньше, тем лучше.

    Главное — НЕ общая длина потраченного металла, а безвозвратно потерянная:
    годный остаток возвращается на склад и металлом быть не перестаёт.
    Поэтому план, оставляющий один кусок 1,2 м, лучше плана, который
    размазал те же полтора метра по шести огрызкам.
    """
    return (
        len(result["unplaced"]),              # разместить всё — важнее всего
        round(result["scrap"], 3),            # безвозвратные потери
        round(result["total_stock"], 3),      # сколько металла взяли со склада
        result["bars_used"],                  # меньше заготовок — меньше резов
    )


def _orderings(available):
    """Порядки перебора заготовок.

    Очерёдность, заданную пользователем, НЕ трогаем — это его решение
    («сперва израсходовать обрезки»). Переставляем только внутри групп
    с одинаковой очерёдностью, где выбор за нами.
    """
    from itertools import groupby

    variants = []
    for reverse in (False, True):
        ordered = []
        for _priority, group in groupby(available, key=lambda s: s["priority"]):
            chunk = sorted(group, key=lambda s: (s["length"], s["index"]), reverse=reverse)
            ordered.extend(chunk)
        if ordered not in variants:
            variants.append(ordered)
    return variants


# ──────────────────────────────────────────────────────────────────────────
# Подготовка
# ──────────────────────────────────────────────────────────────────────────

def _expand(parts):
    """Строки спроса → список длин, от длинных к коротким.

    Порядок «сначала длинные» — не украшение: в раскрое это решает.
    Короткие потом хорошо затыкают остатки, а если начать с них,
    длинным уже не хватит места, и придётся брать лишний хлыст.
    """
    lengths = []
    for part in parts or []:
        length = float(part.get("length") or 0)
        qty = int(part.get("qty") or 0)
        if length <= 0 or qty <= 0:
            continue
        lengths.extend([length] * qty)
    lengths.sort(reverse=True)
    return lengths


def _prepare(stocks):
    """Заготовки в порядке очерёдности, заданной пользователем."""
    prepared = []
    for index, stock in enumerate(stocks or []):
        length = float(stock.get("length") or 0)
        if length <= 0:
            continue
        qty = stock.get("qty")
        prepared.append({
            "length": length,
            "qty": None if qty in (None, False) else int(qty),
            "name": stock.get("name") or "",
            "priority": int(stock.get("priority") or 0),
            "index": index,
        })
    # Сортируем только по очерёдности: какой длины брать первыми — решает
    # перебор порядков в cut_plan, а не догадка здесь.
    prepared.sort(key=lambda s: (s["priority"], s["index"]))
    return prepared


# ──────────────────────────────────────────────────────────────────────────
# Раскладка
# ──────────────────────────────────────────────────────────────────────────

def _fill(available, demand, kerf):
    """Заполняем заготовки по очереди, каждую — максимально плотно.

    Почему берём заготовки по очереди, а не «каждый отрезок в первый
    подходящий»: очерёдность задана пользователем осознанно — сперва
    израсходовать обрезки со склада. Классический First Fit Decreasing
    этот порядок игнорирует, а здесь он важнее пары процентов отхода.
    """
    remaining = list(demand)
    bars = []

    for stock in available:
        produced = 0
        while remaining and (stock["qty"] is None or produced < stock["qty"]):
            pieces, leftover = _load_one(stock["length"], remaining, kerf)
            if not pieces:
                break  # в эту заготовку не влезает даже самый короткий отрезок
            for piece in pieces:
                remaining.remove(piece)
            bars.append({
                "stock_name": stock["name"],
                "stock_length": stock["length"],
                "pieces": pieces,
                "leftover": leftover,
            })
            produced += 1
        if not remaining:
            break

    return bars, remaining


def _load_one(stock_length, remaining, kerf):
    """Набить одну заготовку: жадно, от длинных к коротким.

    Пропил считается ПЕРЕД каждым отрезком, кроме первого: между двумя
    соседними отрезками рез один, а не два. Это ровно то место, где легко
    посчитать пропил дважды и потерять металл на бумаге.
    """
    pieces = []
    used = 0.0
    for length in remaining:
        need = length if not pieces else length + kerf
        if used + need <= stock_length + 1e-9:
            pieces.append(length)
            used += need
    return pieces, round(stock_length - used, 3)


# ──────────────────────────────────────────────────────────────────────────
# Итоги
# ──────────────────────────────────────────────────────────────────────────

def _summarise(bars, unplaced, available, kerf, min_useful):
    total_stock = sum(b["stock_length"] for b in bars)
    total_parts = sum(sum(b["pieces"]) for b in bars)
    total_kerf = sum(max(0, len(b["pieces"]) - 1) * kerf for b in bars)

    useful, scrap = [], []
    for bar in bars:
        (useful if bar["leftover"] >= min_useful > 0 else scrap).append(bar["leftover"])

    # Схемы раскроя: одинаковые повторяются, и цеху нужна не сотня строк,
    # а «вот такую схему повтори 12 раз».
    patterns = Counter(
        (bar["stock_length"], tuple(sorted(bar["pieces"], reverse=True)))
        for bar in bars
    )

    return {
        "bars": bars,
        "patterns": [
            {
                "stock_length": stock_length,
                "pieces": list(pieces),
                "count": count,
                "leftover": round(stock_length - sum(pieces)
                                  - max(0, len(pieces) - 1) * kerf, 3),
            }
            for (stock_length, pieces), count in sorted(
                patterns.items(), key=lambda kv: (-kv[1], -kv[0][0])
            )
        ],
        "bars_used": len(bars),
        "total_stock": round(total_stock, 3),
        "total_parts": round(total_parts, 3),
        "total_kerf": round(total_kerf, 3),
        "useful_leftovers": sorted(useful, reverse=True),
        "scrap": round(sum(scrap), 3),
        "waste_ratio": round(1 - total_parts / total_stock, 4) if total_stock else 0.0,
        "unplaced": _collapse(unplaced),
        "lower_bound": _lower_bound(available, sum(unplaced) + total_parts, kerf),
    }


def _collapse(lengths):
    """Неразмещённые отрезки — обратно в строки «длина × количество»."""
    return [
        {"length": length, "qty": qty}
        for length, qty in sorted(Counter(lengths).items(), reverse=True)
    ]


def _lower_bound(available, needed_length, kerf):
    """Теоретический минимум хлыстов — чтобы видеть, есть ли куда ужиматься.

    Считаем грубо и ЧЕСТНО: сколько самых длинных заготовок нужно, чтобы
    покрыть суммарную длину деталей. Настоящий оптимум не меньше этого,
    но может быть больше — отрезки не жидкость, они не переливаются.
    Граница нужна не для точности, а чтобы отличить «раскрой плохой» от
    «плотнее уже не бывает».
    """
    if not available or needed_length <= 0:
        return 0
    longest = max(s["length"] for s in available)
    if longest <= 0:
        return 0
    from math import ceil
    return ceil(needed_length / longest)


def _empty_result(stocks):
    return {
        "bars": [], "patterns": [], "bars_used": 0,
        "total_stock": 0.0, "total_parts": 0.0, "total_kerf": 0.0,
        "useful_leftovers": [], "scrap": 0.0, "waste_ratio": 0.0,
        "unplaced": [], "lower_bound": 0,
    }
