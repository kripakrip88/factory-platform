# -*- coding: utf-8 -*-
"""Метрики раскройного чертежа: знаменатель для замеров времени резки.

Зачем это нужно. Чёткой статистики резки на участке нет, поэтому модуль
строится «от замера»: оператор засекает, сколько реально резался лист.
Но голое «лист резался 47 минут» не переносится на другой заказ, пока не
известно, СКОЛЬКО в этом листе было метров реза, сколько проколов и какая
толщина. Здесь считаются метры и проколы — знаменатель каждого замера.

Толщина сюда не попадает намеренно. В DXF её нет вообще, а в управляющем
файле .lxds блок Technical/content.xml побайтово одинаков во всех заказах
(у технолога демо-режим), и Thickness="1.5" стоит даже на файле 10 мм.
Толщину берут из имени файла — это делает вызывающий код, не этот модуль.

Почему длина считается аналитически, а не через flattening(). У ezdxf.path
нет свойства length, и очевидный путь — разложить всё на отрезки через
flattening() и сложить. Но flattening систематически ЗАНИЖАЕТ длину: хорда
всегда короче дуги. На реальной дуге r=2.25 с distance=0.01 это 7.0638
вместо 7.0686 — 0.07%. Для одной дуги пустяк, но в чертеже вентзонта таких
дуг и скруглений сотни, а результат идёт в знаменатель норматива, который
потом умножают на тысячи листов. Поэтому LINE, CIRCLE, ARC и полилинии с
выпуклостью считаются формулой точно, а flattening() остаётся только для
SPLINE и ELLIPSE, где аналитики нет. Габарит по-прежнему берётся по
flattening(): дуга выпирает за свои концы, и по вершинам габарит соврёт.

Отдельно про выпуклость (bulge) полилиний. В живых чертежах скруглённые
пазы записаны как LWPOLYLINE из 4 вершин с bulge=-1 на двух сегментах.
Если сложить расстояния между вершинами, получится 18.0 мм вместо
настоящих 23.14 — занижение на 22% на каждом пазе. Полилинии обязаны
считаться с учётом bulge, иначе метрика тихо врёт.

Правила очистки вынесены в CleanupRules и задаются снаружи, а не зашиты
в код: на разных чертежах мусор разный, и подбирать его должен технолог
настройкой, а не программист правкой модуля.
"""

from __future__ import annotations

import fnmatch
import math
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import ezdxf
from ezdxf import path as ezpath
from ezdxf.math import Vec2

# ── ЕДИНИЦЫ ────────────────────────────────────────────────────────────────

# $INSUNITS из заголовка DXF. Все живые чертежи приходят в миллиметрах
# ($INSUNITS=4), но чужой файл может прийти в дюймах, и тогда «длина реза
# 300» будет означать 7620 мм. Молча считать число мм нельзя — метрика уедет
# в 25 раз. Ноль означает «единицы не заданы»: такой файл считаем
# миллиметровым, но помечаем в предупреждениях.
_UNITS_TO_MM = {
    0: 1.0,       # не задано — считаем мм, но предупреждаем
    1: 25.4,      # дюймы
    2: 304.8,     # футы
    4: 1.0,       # миллиметры
    5: 10.0,      # сантиметры
    6: 1000.0,    # метры
    8: 0.0254,    # микродюймы
    13: 0.001,    # микроны
}


# ── ПРАВИЛА ОЧИСТКИ ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CleanupRules:
    """Что выкидывать из чертежа перед подсчётом метров.

    Это настройка, а не константы кода. Значения по умолчанию подобраны по
    29 живым чертежам развёрток вентзонтов; на чертежах другого происхождения
    технолог меняет их, не трогая модуль.
    """

    # Слои, которых в резе нет никогда. Defpoints — служебный слой AutoCAD
    # под точки определения размеров, он не печатается и не режется.
    skip_layers: Tuple[str, ...] = ("Defpoints",)

    # Маски имён слоёв (fnmatch, регистр не важен) — для случаев вроде
    # «Размеры», «DIM*», «Рамка». Пусто по умолчанию: вслепую выкидывать
    # слой по имени опасно, см. примечание к сервисным слоям ниже.
    skip_layer_patterns: Tuple[str, ...] = ()

    # Если задано — считаем ТОЛЬКО эти слои, всё остальное мимо. Белый список
    # надёжнее чёрного, когда точно известно, на каком слое лежит рез.
    only_layers: Tuple[str, ...] = ()

    # Выключенные и замороженные слои не печатаются, значит и не режутся.
    skip_invisible_layers: bool = True

    # Линии гиба. Их чертят, чтобы гибщик знал, где ломать лист, но лазер их
    # не режет — иначе деталь развалится. Метры гиба считаются отдельно.
    bend_layers: Tuple[str, ...] = ()
    bend_layer_patterns: Tuple[str, ...] = ("*гиб*", "*сгиб*", "*bend*", "*fold*")

    # Незамкнутая цепочка физически не может быть контуром реза: рез либо
    # замыкается, либо деталь не отделится от листа. Значит открытая цепочка —
    # разметка: гиб, ось, надсечка. Считаем её гибом, а не резом.
    open_chain_is_bend: bool = True

    # Один и тот же отрезок, начерченный дважды, даёт двойной рез на бумаге
    # и одинарный на станке. Дубликаты убираем.
    drop_duplicates: bool = True

    # Крошки короче этого — мусор импорта (вырожденные отрезки нулевой длины,
    # артефакты конвертации), станок их не режет.
    min_entity_length_mm: float = 0.05

    # Контур короче этого не прорезается физически: пятно лазера и так
    # порядка 0.2 мм. Такой контур — грязь, а не отверстие.
    min_contour_length_mm: float = 1.0

    # Рамка раскройной программы — контур ЛИСТА, а не детали. Её режут
    # только в редких случаях, в метры детали она попадать не должна.
    # Опознаём геометрически: прямоугольник размером со стандартный лист,
    # внутри которого лежит всё остальное. По имени слоя рамку не ищем —
    # см. «Системный слой» в примечании модуля к тестам.
    drop_sheet_frame: bool = True
    sheet_frame_sizes_mm: Tuple[Tuple[float, float], ...] = (
        (1000.0, 2000.0),
        (1250.0, 2500.0),
        (1500.0, 3000.0),
        (1000.0, 4000.0),
        (1500.0, 6000.0),
    )
    # Допуск на габарит рамки: раскройщик ставит её по краю листа, но может
    # отступить пару миллиметров на кромку.
    sheet_frame_tolerance_mm: float = 5.0

    # Допуск стыковки концов при сборке контура. В живых файлах концы сходятся
    # точно, но после конвертации из другой CAD появляются расхождения в
    # сотых. Слишком большой допуск склеит соседние детали в одну.
    join_tolerance_mm: float = 0.05

    # Шаг линеаризации для габарита и для SPLINE/ELLIPSE.
    flattening_distance_mm: float = 0.01

    def to_dict(self) -> Dict:
        """Для хранения настройки в Odoo (ir.config_parameter, JSON-поле)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "CleanupRules":
        """Собрать правила из настройки. Неизвестные ключи игнорируем: так
        старая настройка не уронит новый код и наоборот."""
        if not data:
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        clean = {}
        for key, value in data.items():
            if key not in known:
                continue
            # Кортежи в JSON приезжают списками — приводим обратно, иначе
            # dataclass перестанет быть хешируемым.
            if isinstance(value, list):
                value = tuple(tuple(v) if isinstance(v, list) else v for v in value)
            clean[key] = value
        return cls(**clean)


# ── РЕЗУЛЬТАТ ──────────────────────────────────────────────────────────────


@dataclass
class Contour:
    """Один замкнутый или открытый путь чертежа."""

    length_mm: float
    closed: bool
    layer: str
    entity_count: int
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    # Глубина вложенности: 0 — наружный контур детали, 1 — отверстие в ней,
    # 2 — островок внутри отверстия. Нужна, чтобы отличить деталь от дырки.
    depth: int = 0
    role: str = "cut"  # cut | bend | frame | debris

    @property
    def width_mm(self) -> float:
        return self.max_x - self.min_x

    @property
    def height_mm(self) -> float:
        return self.max_y - self.min_y

    def contains(self, other: "Contour") -> bool:
        """Строго ли габарит другого контура лежит внутри нашего.

        Сравнение по габаритам, а не по настоящей геометрии. Для раскроя
        этого достаточно: отверстие всегда внутри габарита своей детали, а
        детали в чертеже разнесены. Настоящий point-in-polygon стоил бы
        заметно дороже и на этих чертежах дал бы тот же ответ.
        """
        return (
            self.min_x < other.min_x
            and self.min_y < other.min_y
            and self.max_x > other.max_x
            and self.max_y > other.max_y
        )


@dataclass
class DrawingMetrics:
    """Метрики одного чертежа."""

    source: str
    cut_length_mm: float = 0.0
    pierce_count: int = 0
    part_count: int = 0
    hole_count: int = 0
    bend_length_mm: float = 0.0
    # Габарит всей резки в файле и габарит самой крупной детали.
    width_mm: float = 0.0
    height_mm: float = 0.0
    part_width_mm: float = 0.0
    part_height_mm: float = 0.0
    parse_seconds: float = 0.0
    units_factor: float = 1.0
    contours: List[Contour] = field(default_factory=list)
    # Что и сколько выкинула очистка: причина -> (штук, мм). Нужно, чтобы
    # технолог видел, за счёт чего изменилось число, и мог поспорить.
    dropped: Dict[str, Tuple[int, float]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def cut_length_m(self) -> float:
        return self.cut_length_mm / 1000.0

    @property
    def raw_cut_length_mm(self) -> float:
        """Длина до очистки — чтобы показать, что очистка вообще сделала."""
        return self.cut_length_mm + sum(mm for _, mm in self.dropped.values())

    def summary(self) -> str:
        return (
            "%s: рез %.1f мм, проколов %d, деталей %d (отверстий %d), "
            "габарит %.1fx%.1f мм, гиб %.1f мм, разбор %.3f с"
            % (
                os.path.basename(self.source),
                self.cut_length_mm,
                self.pierce_count,
                self.part_count,
                self.hole_count,
                self.width_mm,
                self.height_mm,
                self.bend_length_mm,
                self.parse_seconds,
            )
        )


# ── ДЛИНА И ТОЧКИ ПРИМИТИВОВ ───────────────────────────────────────────────


def _arc_length_from_bulge(start: Vec2, end: Vec2, bulge: float) -> float:
    """Длина дуги сегмента полилинии, заданного выпуклостью.

    Выпуклость — тангенс четверти угла дуги, поэтому угол = 4*atan(bulge),
    а радиус выводится из хорды. Формула точная, приближения не нужно.
    """
    chord = (end - start).magnitude
    if chord <= 0.0:
        return 0.0
    angle = 4.0 * math.atan(bulge)
    half = math.sin(angle / 2.0)
    if abs(half) < 1e-12:
        return chord
    radius = chord / (2.0 * half)
    return abs(angle * radius)


def _polyline_points(entity) -> Tuple[List[Tuple[Vec2, float]], bool]:
    """Вершины полилинии вместе с выпуклостью каждого сегмента."""
    result: List[Tuple[Vec2, float]] = []
    if entity.dxftype() == "LWPOLYLINE":
        for x, y, _start_w, _end_w, bulge in entity.get_points("xyseb"):
            result.append((Vec2(float(x), float(y)), float(bulge)))
        return result, bool(entity.closed)
    # Старый тяжёлый POLYLINE: вершины лежат отдельными объектами.
    for vertex in entity.vertices:
        location = vertex.dxf.location
        result.append((Vec2(float(location[0]), float(location[1])),
                       float(getattr(vertex.dxf, "bulge", 0.0) or 0.0)))
    return result, bool(entity.is_closed)


def entity_length_mm(entity, flattening_distance: float = 0.01) -> float:
    """Длина реза одного примитива, в единицах чертежа.

    Прямые, окружности, дуги и полилинии считаются формулой — точно.
    Всё остальное (SPLINE, ELLIPSE) линеаризуется: аналитической длины у
    них нет, эллиптический интеграл здесь не нужен.
    """
    kind = entity.dxftype()

    if kind == "LINE":
        return (Vec2(entity.dxf.end) - Vec2(entity.dxf.start)).magnitude

    if kind == "CIRCLE":
        return 2.0 * math.pi * abs(entity.dxf.radius)

    if kind == "ARC":
        # Дуга в DXF всегда против часовой от start_angle к end_angle,
        # поэтому развёрнутый угол берём по модулю 360.
        sweep = (entity.dxf.end_angle - entity.dxf.start_angle) % 360.0
        if sweep == 0.0:
            sweep = 360.0
        return math.radians(sweep) * abs(entity.dxf.radius)

    if kind in ("LWPOLYLINE", "POLYLINE"):
        points, closed = _polyline_points(entity)
        if len(points) < 2:
            return 0.0
        total = 0.0
        for index in range(1, len(points)):
            start, bulge = points[index - 1]
            end = points[index][0]
            total += (_arc_length_from_bulge(start, end, bulge) if bulge
                      else (end - start).magnitude)
        if closed:
            start, bulge = points[-1]
            end = points[0][0]
            total += (_arc_length_from_bulge(start, end, bulge) if bulge
                      else (end - start).magnitude)
        return total

    # Запасной путь: линеаризация. Занижает на доли процента, но лучше,
    # чем потерять примитив целиком.
    try:
        flat = list(ezpath.make_path(entity).flattening(distance=flattening_distance))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return sum((flat[i] - flat[i - 1]).magnitude for i in range(1, len(flat)))


def _entity_extent_points(entity, flattening_distance: float) -> List[Vec2]:
    """Точки для габарита. По вершинам считать нельзя: дуга выпирает наружу."""
    kind = entity.dxftype()
    if kind == "CIRCLE":
        center = Vec2(entity.dxf.center)
        radius = abs(entity.dxf.radius)
        return [center + Vec2(-radius, -radius), center + Vec2(radius, radius)]
    if kind == "LINE":
        return [Vec2(entity.dxf.start), Vec2(entity.dxf.end)]
    try:
        return [Vec2(p) for p in
                ezpath.make_path(entity).flattening(distance=flattening_distance)]
    except (TypeError, ValueError, AttributeError):
        return []


def _entity_ends(entity) -> Optional[Tuple[Vec2, Vec2]]:
    """Концы примитива, или None если он замкнут сам на себя.

    Замкнутый сам на себя примитив (окружность, замкнутая полилиния) — уже
    готовый контур, его не надо ни с чем стыковать.
    """
    kind = entity.dxftype()
    if kind == "LINE":
        return Vec2(entity.dxf.start), Vec2(entity.dxf.end)
    if kind == "CIRCLE":
        return None
    if kind == "ARC":
        center = Vec2(entity.dxf.center)
        radius = entity.dxf.radius
        start = math.radians(entity.dxf.start_angle)
        end = math.radians(entity.dxf.end_angle)
        return (
            center + Vec2(radius * math.cos(start), radius * math.sin(start)),
            center + Vec2(radius * math.cos(end), radius * math.sin(end)),
        )
    if kind in ("LWPOLYLINE", "POLYLINE"):
        points, closed = _polyline_points(entity)
        if closed or len(points) < 2:
            return None
        return points[0][0], points[-1][0]
    try:
        path = ezpath.make_path(entity)
    except (TypeError, ValueError, AttributeError):
        return None
    if path.is_closed:
        return None
    return Vec2(path.start), Vec2(path.end)


def _dedup_key(entity) -> Tuple:
    """Ключ совпадения примитивов. Отрезок AB и BA — один и тот же рез."""
    kind = entity.dxftype()
    r = lambda v: round(float(v), 4)
    if kind == "LINE":
        a = (r(entity.dxf.start[0]), r(entity.dxf.start[1]))
        b = (r(entity.dxf.end[0]), r(entity.dxf.end[1]))
        return ("LINE",) + tuple(sorted([a, b]))
    if kind == "CIRCLE":
        return ("CIRCLE", r(entity.dxf.center[0]), r(entity.dxf.center[1]),
                r(entity.dxf.radius))
    if kind == "ARC":
        return ("ARC", r(entity.dxf.center[0]), r(entity.dxf.center[1]),
                r(entity.dxf.radius), r(entity.dxf.start_angle),
                r(entity.dxf.end_angle))
    if kind in ("LWPOLYLINE", "POLYLINE"):
        points, closed = _polyline_points(entity)
        return ("POLY", closed,
                tuple((r(p.x), r(p.y), r(b)) for p, b in points))
    return ("OTHER", id(entity))


# ── СБОР КОНТУРОВ ──────────────────────────────────────────────────────────


class _UnionFind:
    """Склейка примитивов в цепочки по совпадающим концам."""

    def __init__(self) -> None:
        self._parent: Dict = {}

    def find(self, item):
        parent = self._parent.setdefault(item, item)
        while parent != item:
            item = parent
            parent = self._parent.setdefault(item, item)
        return item

    def union(self, left, right) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self._parent[root_left] = root_right


def _matches(name: str, exact: Sequence[str], patterns: Sequence[str]) -> bool:
    """Имя слоя против списка имён и списка масок, без учёта регистра."""
    lowered = name.strip().lower()
    if any(lowered == item.strip().lower() for item in exact):
        return True
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)


def _layer_visible(doc, layer_name: str) -> bool:
    """Виден ли слой. Отсутствующий в таблице слой считаем видимым: рисунок
    важнее записи в таблице, и терять геометрию из-за неё нельзя."""
    try:
        layer = doc.layers.get(layer_name)
    except (KeyError, ezdxf.DXFTableEntryError):
        return True
    return layer.is_on() and not layer.is_frozen()


def _iter_drawable(msp) -> Iterable:
    """Примитивы модели, включая содержимое вставленных блоков.

    В живых 29 файлах блоков нет, но чертёж из чужой CAD приходит собранным
    из INSERT, и без разворота блоков метрика окажется нулевой.
    """
    for entity in msp:
        if entity.dxftype() == "INSERT":
            try:
                for sub in entity.virtual_entities():
                    yield sub
            except (TypeError, ValueError, AttributeError):
                continue
        else:
            yield entity


_SUPPORTED = {"LINE", "CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"}


def analyze(source: str, rules: Optional[CleanupRules] = None) -> DrawingMetrics:
    """Посчитать метрики чертежа: рез, проколы, габарит, число деталей."""
    rules = rules or CleanupRules()
    started = time.perf_counter()
    metrics = DrawingMetrics(source=source)

    doc = ezdxf.readfile(source)
    msp = doc.modelspace()

    insunits = doc.header.get("$INSUNITS", 0)
    factor = _UNITS_TO_MM.get(int(insunits or 0), 1.0)
    metrics.units_factor = factor
    if not insunits:
        metrics.warnings.append(
            "$INSUNITS не задан — чертёж посчитан как миллиметровый")
    elif factor != 1.0:
        metrics.warnings.append(
            "чертёж в единицах $INSUNITS=%s, длины пересчитаны в мм (x%.4f)"
            % (insunits, factor))

    def drop(reason: str, count: int, millimetres: float) -> None:
        was_count, was_mm = metrics.dropped.get(reason, (0, 0.0))
        metrics.dropped[reason] = (was_count + count, was_mm + millimetres)

    # ── отбор примитивов ───────────────────────────────────────────────────
    cut_entities: List = []
    bend_entities: List = []
    seen: Dict[Tuple, bool] = {}

    for entity in _iter_drawable(msp):
        kind = entity.dxftype()
        if kind not in _SUPPORTED:
            # TEXT, DIMENSION, HATCH и прочая оформительская обвязка резом
            # не является; молча пропускать нельзя — пусть будет видно.
            drop("не режущийся объект (%s)" % kind, 1, 0.0)
            continue

        length = entity_length_mm(entity, rules.flattening_distance_mm) * factor
        layer = entity.dxf.layer

        if rules.only_layers and not _matches(layer, rules.only_layers, ()):
            drop("слой вне белого списка (%s)" % layer, 1, length)
            continue
        if _matches(layer, rules.skip_layers, rules.skip_layer_patterns):
            drop("служебный слой (%s)" % layer, 1, length)
            continue
        if rules.skip_invisible_layers and not _layer_visible(doc, layer):
            drop("выключенный слой (%s)" % layer, 1, length)
            continue
        if length < rules.min_entity_length_mm:
            drop("вырожденный объект", 1, length)
            continue
        if rules.drop_duplicates:
            key = _dedup_key(entity)
            if key in seen:
                drop("дубликат объекта", 1, length)
                continue
            seen[key] = True

        if _matches(layer, rules.bend_layers, rules.bend_layer_patterns):
            bend_entities.append((entity, length))
        else:
            cut_entities.append((entity, length))

    # ── сборка цепочек ─────────────────────────────────────────────────────
    tolerance = rules.join_tolerance_mm / factor if factor else rules.join_tolerance_mm
    union = _UnionFind()
    chain_members: Dict = {}

    def node_key(point: Vec2) -> Tuple[int, int]:
        step = tolerance if tolerance > 0 else 1e-9
        return (int(round(point.x / step)), int(round(point.y / step)))

    for index, (entity, _length) in enumerate(cut_entities):
        item = ("entity", index)
        ends = _entity_ends(entity)
        if ends is None:
            # Сам по себе замкнут — отдельная цепочка.
            union.find(item)
            continue
        for point in ends:
            union.union(item, node_key(point))

    for index, (entity, _length) in enumerate(cut_entities):
        chain_members.setdefault(union.find(("entity", index)), []).append(index)

    # ── описание цепочек ───────────────────────────────────────────────────
    contours: List[Contour] = []
    for members in chain_members.values():
        total = sum(cut_entities[i][1] for i in members)
        degree: Dict[Tuple[int, int], int] = {}
        xs: List[float] = []
        ys: List[float] = []
        layers: Dict[str, int] = {}
        for i in members:
            entity, _length = cut_entities[i]
            layers[entity.dxf.layer] = layers.get(entity.dxf.layer, 0) + 1
            for point in _entity_extent_points(entity, rules.flattening_distance_mm):
                xs.append(point.x * factor)
                ys.append(point.y * factor)
            ends = _entity_ends(entity)
            if ends is not None:
                for point in ends:
                    key = node_key(point)
                    degree[key] = degree.get(key, 0) + 1
        if not xs:
            continue
        # Замкнута цепочка тогда, когда у неё нет свободных концов: в каждой
        # точке стыка сходятся минимум два примитива.
        closed = all(count >= 2 for count in degree.values())
        layer = max(layers.items(), key=lambda kv: kv[1])[0] if layers else "0"
        contours.append(Contour(
            length_mm=total, closed=closed, layer=layer, entity_count=len(members),
            min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys),
        ))

    # ── разбраковка цепочек ────────────────────────────────────────────────
    kept: List[Contour] = []
    for contour in contours:
        if contour.length_mm < rules.min_contour_length_mm:
            contour.role = "debris"
            drop("контур короче %.2f мм" % rules.min_contour_length_mm,
                 contour.entity_count, contour.length_mm)
            continue
        if not contour.closed and rules.open_chain_is_bend:
            contour.role = "bend"
            metrics.bend_length_mm += contour.length_mm
            drop("открытая цепочка (линия гиба)", contour.entity_count,
                 contour.length_mm)
            continue
        kept.append(contour)

    # Рамка листа. Ищем геометрически — прямоугольник размером со
    # стандартный лист, внутри которого лежит ВСЁ остальное. По имени слоя
    # рамку не ищем: на живых чертежах сервисный слой оказался настоящей
    # третьей панелью корпуса, и фильтр по имени срезал бы реальную деталь.
    if rules.drop_sheet_frame and len(kept) > 1:
        for contour in list(kept):
            if not _looks_like_sheet(contour, rules):
                continue
            others = [c for c in kept if c is not contour]
            if not all(contour.contains(other) for other in others):
                continue
            contour.role = "frame"
            kept.remove(contour)
            drop("рамка листа %.0fx%.0f" % (contour.width_mm, contour.height_mm),
                 contour.entity_count, contour.length_mm)
            break

    # ── вложенность: деталь или отверстие ──────────────────────────────────
    for contour in kept:
        contour.depth = sum(1 for other in kept
                            if other is not contour and other.contains(contour))

    metrics.contours = contours
    metrics.cut_length_mm = sum(c.length_mm for c in kept)
    metrics.pierce_count = len(kept)
    # Деталь — контур, внутри которого никто не лежит сверху, то есть
    # глубина 0. Считать деталями любую чётную глубину (деталь-отверстие-
    # островок) заманчиво, но на живых чертежах не работает: развёртки
    # разложены с наложением габаритов — крышка перекрывает корпус, — и
    # отверстие, попавшее в зону наложения, получает глубину 2 и уходит
    # в детали. На вш 1000х1200 такая арифметика дала 40 деталей вместо
    # четырёх. Островок внутри отверстия при этом посчитается отверстием;
    # в развёртках вентзонтов их нет, а на число проколов это не влияет.
    parts = [c for c in kept if c.depth == 0]
    metrics.part_count = len(parts)
    metrics.hole_count = len(kept) - len(parts)
    metrics.bend_length_mm += sum(e_len for _e, e_len in bend_entities)

    if kept:
        metrics.width_mm = max(c.max_x for c in kept) - min(c.min_x for c in kept)
        metrics.height_mm = max(c.max_y for c in kept) - min(c.min_y for c in kept)
    if parts:
        largest = max(parts, key=lambda c: c.width_mm * c.height_mm)
        metrics.part_width_mm = largest.width_mm
        metrics.part_height_mm = largest.height_mm

    metrics.parse_seconds = time.perf_counter() - started
    return metrics


def _looks_like_sheet(contour: Contour, rules: CleanupRules) -> bool:
    """Похож ли контур на прямоугольник размером со стандартный лист."""
    tolerance = rules.sheet_frame_tolerance_mm
    width, height = contour.width_mm, contour.height_mm
    for sheet_w, sheet_h in rules.sheet_frame_sizes_mm:
        for a, b in ((sheet_w, sheet_h), (sheet_h, sheet_w)):
            if abs(width - a) <= tolerance and abs(height - b) <= tolerance:
                # Периметр прямоугольника — контрольная проверка, что контур
                # действительно прямоугольный, а не сложная деталь в тот же
                # габарит: у детали периметр заметно больше.
                perimeter = 2.0 * (width + height)
                if abs(contour.length_mm - perimeter) <= 4.0 * tolerance:
                    return True
    return False


# ── ПРЕВЬЮ ─────────────────────────────────────────────────────────────────


def render_svg(source: str, rules: Optional[CleanupRules] = None,
               output: Optional[str] = None,
               width_mm: Optional[float] = None,
               height_mm: Optional[float] = None,
               max_page_mm: float = 800.0) -> str:
    """Отрисовать чертёж в SVG — «смотреть файлы, которые уходят на резку».

    Рисуется ровно то, что осталось после очистки, тем же набором правил:
    картинка должна совпадать с цифрами, иначе по ней нельзя спорить.

    Размер страницы по умолчанию берётся по пропорции самого чертежа, а не
    фиксированным A3. Развёртка вентзонта — это лента 3455x1581, и на
    альбомном листе 420x297 она заняла бы половину высоты, оставив остальное
    чёрным полем: мелкие отверстия Ø4.5 в такой картинке уже не разглядеть,
    а смотрят её именно ради них.

    Импорт бэкенда отложен внутрь функции сознательно: ezdxf.addons.drawing
    безусловно тянет PIL, и на машине без Pillow импорт модуля целиком
    свалился бы на ровном месте. Метрики от картинки не зависят и должны
    считаться всегда.
    """
    from ezdxf.addons.drawing import Frontend, RenderContext, layout
    from ezdxf.addons.drawing import svg as svg_backend

    rules = rules or CleanupRules()
    doc = ezdxf.readfile(source)
    msp = doc.modelspace()

    keep = _drawable_for_preview(doc, msp, rules)

    if width_mm is None or height_mm is None:
        width_mm, height_mm = _preview_page_size(keep, rules, max_page_mm)

    context = RenderContext(doc)
    backend = svg_backend.SVGBackend()
    frontend = Frontend(context, backend)
    frontend.draw_entities(keep)

    page = layout.Page(width_mm, height_mm, layout.Units.mm,
                       margins=layout.Margins.all(5))
    content = backend.get_string(page)

    if output:
        directory = os.path.dirname(os.path.abspath(output))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(content)
    return content


def _preview_page_size(entities: Sequence, rules: CleanupRules,
                       max_page_mm: float) -> Tuple[float, float]:
    """Страница по пропорции чертежа, длинной стороной в max_page_mm."""
    xs: List[float] = []
    ys: List[float] = []
    for entity in entities:
        for point in _entity_extent_points(entity, rules.flattening_distance_mm):
            xs.append(point.x)
            ys.append(point.y)
    if not xs:
        return 297.0, 210.0
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return 297.0, 210.0
    scale = max_page_mm / max(width, height)
    # Поля страницы по 5 мм с каждой стороны — чтобы контур не лип к краю.
    return width * scale + 10.0, height * scale + 10.0


def _drawable_for_preview(doc, msp, rules: CleanupRules) -> List:
    """Примитивы, попавшие в рез или в гиб, — то же сито, что и в analyze."""
    keep: List = []
    seen: Dict[Tuple, bool] = {}
    for entity in _iter_drawable(msp):
        if entity.dxftype() not in _SUPPORTED:
            continue
        layer = entity.dxf.layer
        if rules.only_layers and not _matches(layer, rules.only_layers, ()):
            continue
        if _matches(layer, rules.skip_layers, rules.skip_layer_patterns):
            continue
        if rules.skip_invisible_layers and not _layer_visible(doc, layer):
            continue
        if entity_length_mm(entity, rules.flattening_distance_mm) < rules.min_entity_length_mm:
            continue
        if rules.drop_duplicates:
            key = _dedup_key(entity)
            if key in seen:
                continue
            seen[key] = True
        keep.append(entity)
    return keep
