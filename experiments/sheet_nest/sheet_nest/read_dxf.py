# -*- coding: utf-8 -*-
"""DXF (КОМПАС, AutoCAD и др.) → детали раскроя (Part) для sheet_nest.

    from sheet_nest.read_dxf import parts_from_dxf, DxfError
    parts = parts_from_dxf(open(path, "rb").read(), "Фланец_12шт.dxf")

Договорённость — DESIGN.md, раздел «read_dxf.py». Что делает модуль:

- Текстовый DXF R12…R2018 (двоичный DXF и DWG — ошибка). Конец строки CRLF/LF/CR, пробелы перед кодами групп.
  Строки (имена слоёв и блоков): если строка корректна в UTF-8 — UTF-8 (AC1021+ всегда пишет так), иначе
  кодировка $DWGCODEPAGE (ANSI_1251 → cp1251; если не указана — cp1251). Escape \\U+XXXX раскрывается.
- Единицы — $INSUNITS: 4 мм; 0 или нет переменной — мм с предупреждением; 1 дюйм ×25,4; 2 фут; 5 см ×10; 6 м ×1000;
  14 дм; 13 мкм; прочие — мм с предупреждением.
- Сущности: LINE, ARC, CIRCLE, LWPOLYLINE (bulge, флаг 70&1; ширина не учитывается), POLYLINE+VERTEX+SEQEND
  (2D с bulge; 3D — проекция на XY; сети — пропуск), SPLINE (NURBS по управляющим точкам/узлам/весам или кубическая
  интерполяция по опорным точкам), ELLIPSE (полный и дуга), INSERT (вложенные блоки: точка вставки, базовая точка,
  масштаб X/Y, в т.ч. отрицательный — зеркало, поворот, массив MINSERT). POINT — молча пропускается.
  Дуги ARC/bulge остаются ТОЧНЫМИ дугами (bulge); сплайн, эллипс и дуги в блоке с разным масштабом X/Y — ломаная
  с отклонением ≤ 0,01 мм (предупреждение). Если искажение окружности ничтожно (≤ 0,001 мм: эллипс с почти равными
  осями, масштаб вставки 1 / 1.0000001 из-за округления в CAD) — точная дуга/окружность.
- Испорченные числа (координаты дальше 1000 км, огромный bulge/радиус, параметры эллипса, переполнение при
  пересчёте единиц/масштаба) — DxfError; дуга огромного радиуса со стрелкой ≤ 0,0001 мм — отрезок.
- Выдавливание 210/220/230 (OCS) — по «произвольной оси» AutoCAD: Z = −1 даёт x → −x (дуги зеркалятся).
  Наклонные объекты (нормаль не по Z) проецируются на XY с предупреждением.
- Не режется — пропуск с предупреждением (одно на тип, с числом): TEXT, MTEXT, DIMENSION, HATCH, LEADER, MLEADER,
  ATTRIB, ATTDEF, SOLID, 3DFACE, VIEWPORT и др.; содержимое анонимных блоков размеров *D… не читается.
  Ещё пропускаются с предупреждением: объекты пространства листа (67=1), невидимые (60=1), на выключенных или
  замороженных слоях, линии прерывистого типа (осевые, штриховые, линии сгиба: тип линии с промежутками в таблице
  LTYPE, а без таблицы — по имени CENTER/DASH/HIDDEN/ОСЕВАЯ/…).
- Слой: объекты слоя «0» внутри блока получают слой вставки (как в AutoCAD). Гравировка — is_engrave_layer(),
  остальные слои — рез.
- Сцепка рёбер в контуры с допуском 0,01 мм (vn.contours._node_ids). Замкнутая цепочка → LwPolyline flag=1 (замкнутая
  цепочка дуг одной окружности → Circle), окружность → Circle (a0 = π/4); незамкнутая → LwPolyline flag=0 (один прямой
  отрезок → Line). Отрезки нулевой длины выбрасываются; точные дубли — тоже, с предупреждением (дубль на слоях
  реза и гравировки — остаётся рез): одинаковые рёбра, а также замкнутые контуры в разной записи (окружность CIRCLE
  и та же окружность двумя дугами или полилинией с bulge и т.п.: та же линия в пределах 0,01 мм).
  Ветвление (3+ ребра в узле): на слое реза — DxfError с координатами (рамка/штамп/размеры, разбитые на линии,
  касание деталей); на слое гравировки (разбитый на линии текст) — детерминированное деление на цепочки между
  узлами ветвления. Конец незамкнутого реза, упёршийся в другой контур реза без общего узла (Т-примыкание:
  прорезь до разгрузочного отверстия, надрез от края — или рамка/выносная линия), — предупреждение с координатой,
  рез остаётся открытым резом детали.
- Детали: внешний контур — замкнутый контур слоя реза, не лежащий внутри другого замкнутого контура реза; всё прочее
  относится к наименьшему внешнему контуру, который его содержит (проверка точкой на кривой). Контур реза внутри
  отверстия остаётся внутренним резом этой детали (предупреждение). Незамкнутая цепочка реза вне деталей — разрыв
  внешнего контура (DxfError с координатами концов). Прочее вне деталей — DxfError (число и координата).
  Выход элемента за габарит внешнего контура или вершина одной детали внутри другой — DxfError (контуры пересекаются).
- Направление: внешний — против часовой (площадь > 0), внутренние замкнутые — по часовой. Part.shapes: внутренние
  (в порядке файла), внешний — ПОСЛЕДНИМ (outer=1, layer=1). Деталь сдвигается так, что минимум габарита внешнего
  контура (с учётом дуг) = (0, 0).
- Имя детали — имя файла без расширения и без количества, без символов &<>"'; при нескольких деталях — « #k»
  (порядок — по левому краю, затем по низу габарита). Количество: аргумент qty; иначе из имени файла
  (`…_12шт`, `… 12 шт`, `… x12` / `… х12`, `…(12)`; размер «1500 х 3000» — не количество); иначе 1
  с предупреждением. Количество файла — каждой его детали.
- Предупреждения файла (пропуски, приближения, единицы) пишутся в warnings каждой детали этого файла.
"""
import codecs
import math
import os
import re
from collections import defaultdict

import numpy as np

from sheet_nest.libpath import vn

__all__ = ["parts_from_dxf", "DxfError", "ENGRAVE_LAYERS", "ENGRAVE_SUBSTRINGS", "is_engrave_layer",
           "qty_from_filename", "NODE_TOL", "CURVE_TOL"]

NODE_TOL = 0.01          # мм: концы рёбер ближе — один узел
CURVE_TOL = 0.01         # мм: допустимое отклонение ломаной от сплайна/эллипса
_APPROX_TOL = 0.008      # рабочий допуск приближения (запас до CURVE_TOL)
_PIP_TOL = 0.005         # мм: стрелка прогиба при разбиении дуг для проверки «точка внутри»
_MAX_POINTS = 200000     # предел точек одной приближённой кривой
_MAX_DEPTH = 32          # предел вложенности блоков
_MAX_INSERTS = 200000    # предел развёрнутых вставок блоков (вложенные массивы растут как произведение)
_MAX_ITEMS = 2000000     # предел рёбер и окружностей в файле
_MAX_EXTENT = 1e7        # мм: кривая больше 10 км — заведомо ошибка координат/единиц (не приближаем)
_MAX_COORD = 1e9         # мм: точка дальше 1000 км от начала — числа в DXF испорчены (иначе переполнение в узлах)
_MAX_RADIUS = 1e12       # мм: дуга большего радиуса — почти прямая (если стрелка ничтожна) или испорченные числа
_FLAT_SAG = 1e-4         # мм: дуга с такой стрелкой прогиба и огромным радиусом — отрезок
_SIM_TOL = 0.001         # мм: искажение окружности вставкой (разный масштаб X/Y) не больше — дуга остаётся точной
_TWO_PI = 2.0 * math.pi

ENGRAVE_LAYERS = ["ГРАВИРОВКА", "GRAV", "ENGRAVE", "MARK", "МАРКИРОВКА"]
ENGRAVE_SUBSTRINGS = ("грав", "engrav")


class DxfError(Exception):
    """Ошибка чтения DXF. Текст — по-русски, для человека; координаты — в единицах чертежа."""


# =====================================================================================  слой, количество
def is_engrave_layer(name, engrave_layers=None):
    """Слой гравировки? Без учёта регистра (кириллица тоже). По умолчанию — имя из ENGRAVE_LAYERS или содержит
    «грав»/«engrav». Если передан engrave_layers — только точное совпадение с одним из его имён (без регистра)."""
    n = (name or "").strip().casefold()
    if engrave_layers is not None:
        return any(n == (x or "").strip().casefold() for x in engrave_layers)
    if any(n == x.casefold() for x in ENGRAVE_LAYERS):
        return True
    return any(s in n for s in ENGRAVE_SUBSTRINGS)


_QTY_RES = (
    re.compile(r"(?<![\d.,])(\d+)\s*(?:шт|pcs|pc)\.?\s*\)?\s*$", re.I),     # _12шт, 12 шт., (12 шт)
    re.compile(r"(?:^|(?<=[\s_\-]))[xXхХ×]\s*(\d+)\s*$"),                   # " x12", "_х12" (не 500x1000)
    re.compile(r"\(\s*(\d+)\s*\)\s*$"),                                       # (12)
)
_QTY_X = 1                                                                    # номер шаблона « x12» в _QTY_RES
_NUM_TAIL = re.compile(r"(?:^|[\s_\-])\d+(?:[.,]\d+)?$")                      # «… 1500» — перед « х» стоит число


def qty_from_filename(filename):
    """Имя файла → (количество | None, имя без количества и расширения).
    Шаблоны в конце имени: «_12шт», «12 шт», « x12» / «_х12» (х латинская или русская; перед ней пробел,
    «_» или «-», чтобы «500x1000» не читалось как количество), «(12)». Если перед « х» стоит отдельное число —
    это размер («Лист 1500 х 3000», «Уголок 50 x 50 x 5»), а не количество: (None, имя целиком)."""
    base = os.path.basename((filename or "").replace("\\", "/"))
    stem = os.path.splitext(base)[0].strip()
    # « (1)» в конце — так браузер и Windows помечают повторную загрузку: если перед ним есть «12шт» / « x12»,
    # количество — оттуда («Фланец_12шт (1).dxf» → 12), а не 1
    dup = re.match(r"^(.*\S)\s+\(\s*\d+\s*\)$", stem)
    if dup:
        q, rest = qty_from_filename(dup.group(1) + ".dxf")
        if q is not None and not re.search(r"\(\s*\d+\s*\)$", dup.group(1)):
            return q, rest
    for k, rx in enumerate(_QTY_RES):
        m = rx.search(stem)
        if m:
            if k == _QTY_X and _NUM_TAIL.search(stem[:m.start()].rstrip(" \t_-")):
                continue                                                      # размер через « х », не количество
            q = int(m.group(1))
            if q >= 1:
                rest = stem[:m.start()].rstrip(" \t_-.,(")
                return q, (rest or stem)
    return None, stem


def _part_name(s):
    s = re.sub(r"[&<>\"']", "", s or "").strip()
    return s or "Деталь"


# =====================================================================================  аффинные преобразования
# M = (a, b, c, d, e, f):  x' = a·x + b·y + e,  y' = c·x + d·y + f
_ID = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(M, N):
    """M∘N (сначала N)."""
    a, b, c, d, e, f = M
    A, B, C, D, E, F = N
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, a * E + b * F + e, c * E + d * F + f)


def _ap(M, p):
    return (M[0] * p[0] + M[1] * p[1] + M[4], M[2] * p[0] + M[3] * p[1] + M[5])


def _lin(M, v):
    return (M[0] * v[0] + M[1] * v[1], M[2] * v[0] + M[3] * v[1])


def _tr(x, y):
    return (1.0, 0.0, 0.0, 1.0, x, y)


def _rot(deg):
    r = deg % 360.0
    exact = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}
    c, s = exact.get(r, (math.cos(math.radians(r)), math.sin(math.radians(r))))
    return (c, -s, s, c, 0.0, 0.0)


def _sim(M):
    """Ближайшее подобие линейной части M → (масштаб k, угол φ, знак s: +1 / −1 зеркало, искажение e) или None.
    Линейная часть = подобие + «антиподобие»; e — длина второй части: окружность радиуса r уходит в эллипс, который
    отстоит от окружности радиуса k·r (центр — образ центра) не дальше e·r. Точное подобие — e = 0 (с точностью до
    округления); разный масштаб X/Y даёт e = |sx − sy| / 2."""
    a, b, c, d = M[0], M[1], M[2], M[3]
    E, F, G, H = (a + d) / 2.0, (a - d) / 2.0, (c + b) / 2.0, (c - b) / 2.0
    Q, R = math.hypot(E, H), math.hypot(F, G)
    if not (math.isfinite(Q) and math.isfinite(R)) or max(Q, R) <= 0.0:
        return None
    if Q >= R:
        return Q, math.atan2(H, E), 1, R
    return R, math.atan2(G, F), -1, Q


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _unit(v):
    L = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / L, v[1] / L, v[2] / L)


def _ocs(N, elev=0.0):
    """Система координат объекта (OCS) → мировая XY, по «произвольной оси» AutoCAD. → (M, наклонён?)."""
    nx, ny, nz = N
    L = math.sqrt(nx * nx + ny * ny + nz * nz)
    if L < 1e-12:
        return _ID, False
    nx, ny, nz = nx / L, ny / L, nz / L
    if abs(nx) < 1e-12 and abs(ny) < 1e-12:
        return ((_ID if nz > 0 else (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)), False)
    if abs(nx) < 1.0 / 64 and abs(ny) < 1.0 / 64:
        ax = _unit(_cross((0.0, 1.0, 0.0), (nx, ny, nz)))
    else:
        ax = _unit(_cross((0.0, 0.0, 1.0), (nx, ny, nz)))
    ay = _unit(_cross((nx, ny, nz), ax))
    return (ax[0], ay[0], ax[1], ay[1], elev * nx, elev * ny), abs(abs(nz) - 1.0) > 1e-9


# =====================================================================================  геометрия
def _bad(p):
    """Точка не годится: не число, бесконечность или дальше _MAX_COORD (сравнение с NaN — ложь)."""
    return not (abs(p[0]) <= _MAX_COORD and abs(p[1]) <= _MAX_COORD)


def _bulge_arc(p0, p1, b):
    """Сегмент полилинии с bulge → (центр, радиус, начальный угол, знаковый угол дуги)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy)
    sw = 4.0 * math.atan(b)
    h = d / 4.0 * (1.0 / b - b)                # от середины хорды до центра по левой нормали (= d(1−b²)/4b без b²)
    cx = (p0[0] + p1[0]) / 2.0 - dy / d * h
    cy = (p0[1] + p1[1]) / 2.0 + dx / d * h
    r = d / 4.0 * (1.0 / abs(b) + abs(b))
    return (cx, cy), r, math.atan2(p0[1] - cy, p0[0] - cx), sw


def _dist_seg(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return math.hypot(q[0] - a[0], q[1] - a[1])
    t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(a[0] + t * dx - q[0], a[1] + t * dy - q[1])


_PROBE = (1.0 / 6, 2.0 / 6, 0.5, 4.0 / 6, 5.0 / 6)


def _approx(f, t0, t1, pieces=8, tol=_APPROX_TOL):
    """Параметрическая кривая f(t), t ∈ [t0, t1] → ломаная (точки с обоими концами), отклонение ≤ tol:
    отрезок делится пополам, пока хоть одна из 5 проб кривой дальше tol от хорды."""
    out = [f(t0)]

    def seg(a, b, pa, pb, depth):
        if depth < 48:
            for s in _PROBE:
                if _dist_seg(f(a + (b - a) * s), pa, pb) > tol:
                    m = 0.5 * (a + b)
                    pm = f(m)
                    seg(a, m, pa, pm, depth + 1)
                    seg(m, b, pm, pb, depth + 1)
                    return
        out.append(pb)
        if len(out) > _MAX_POINTS:
            raise DxfError("кривая слишком сложная: больше %d отрезков при допуске %g мм" % (_MAX_POINTS, CURVE_TOL))

    ts = [t0 + (t1 - t0) * k / pieces for k in range(pieces + 1)]
    ps = [out[0]] + [f(t) for t in ts[1:]]
    for k in range(pieces):
        seg(ts[k], ts[k + 1], ps[k], ps[k + 1], 0)
    return out


def _thin(pts):
    """Убрать точки ближе 1,5·NODE_TOL к предыдущей (иначе слились бы в узел); концы сохраняются."""
    if len(pts) < 3:
        return list(pts)
    lim = 1.5 * NODE_TOL
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= lim:
            out.append(p)
    last = pts[-1]
    if len(out) > 1 and math.hypot(last[0] - out[-1][0], last[1] - out[-1][1]) < lim:
        out[-1] = last
    else:
        out.append(last)
    return out


def _deboor(hom, K, p, k, t):
    d = [list(hom[j + k - p]) for j in range(p + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = j + k - p
            den = K[i + p + 1 - r] - K[i]
            al = 0.0 if den == 0 else (t - K[i]) / den
            dj, dm = d[j], d[j - 1]
            d[j] = [(1.0 - al) * dm[0] + al * dj[0], (1.0 - al) * dm[1] + al * dj[1], (1.0 - al) * dm[2] + al * dj[2]]
    x, y, w = d[p]
    if not w:                                   # веса ушли в ноль (испорченные числа) — точка не определена
        return (math.nan, math.nan)
    return (x / w, y / w)


def _nurbs_pts(P, W, K, p):
    """NURBS (точки P, веса W, узлы K, степень p) → ломаная по непустым пролётам узлов."""
    hom = [(x * w, y * w, w) for (x, y), w in zip(P, W)]
    pts = []
    for k in range(p, len(P)):
        a, b = K[k], K[k + 1]
        if b - a <= 1e-14 * max(1.0, abs(a), abs(b)):
            continue
        part = _approx(lambda t, k=k: _deboor(hom, K, p, k, t), a, b, pieces=4)
        pts.extend(part[1:] if pts else part)
    return pts


def _fit_curve(P, closed, d0=None, d1=None):
    """Кубическая интерполяция по опорным точкам (параметр — длина хорды; концы — по касательным, иначе
    «естественные»; замкнутая — периодическая) → ломаная."""
    Q = [P[0]] + [q for a, q in zip(P, P[1:]) if math.hypot(q[0] - a[0], q[1] - a[1]) > 1e-9]
    if closed and len(Q) > 2 and math.hypot(Q[0][0] - Q[-1][0], Q[0][1] - Q[-1][1]) > 1e-9:
        Q.append(Q[0])
    m = len(Q)
    if m < 2:
        return Q
    if m == 2 and d0 is None and d1 is None:
        return Q
    Y = np.array(Q, dtype=float)
    h = np.hypot(np.diff(Y[:, 0]), np.diff(Y[:, 1]))
    u = np.concatenate([[0.0], np.cumsum(h)])
    if closed and m >= 3:
        N = m - 1
        A = np.zeros((N, N))
        R = np.zeros((N, 2))
        for i in range(N):
            hp, hn = h[(i - 1) % N], h[i]
            A[i, (i - 1) % N] += hp
            A[i, i] += 2.0 * (hp + hn)
            A[i, (i + 1) % N] += hn
            R[i] = 6.0 * ((Y[i + 1] - Y[i]) / hn - (Y[i] - Y[(i - 1) % N]) / hp)
        Ms = np.linalg.solve(A, R)
        Mf = np.vstack([Ms, Ms[:1]])
    else:
        A = np.zeros((m, m))
        R = np.zeros((m, 2))
        if d0 is not None:
            A[0, 0], A[0, 1] = 2.0 * h[0], h[0]
            R[0] = 6.0 * ((Y[1] - Y[0]) / h[0] - np.array(d0))
        else:
            A[0, 0] = 1.0
        for i in range(1, m - 1):
            A[i, i - 1], A[i, i], A[i, i + 1] = h[i - 1], 2.0 * (h[i - 1] + h[i]), h[i]
            R[i] = 6.0 * ((Y[i + 1] - Y[i]) / h[i] - (Y[i] - Y[i - 1]) / h[i - 1])
        if d1 is not None:
            A[m - 1, m - 2], A[m - 1, m - 1] = h[m - 2], 2.0 * h[m - 2]
            R[m - 1] = 6.0 * (np.array(d1) - (Y[m - 1] - Y[m - 2]) / h[m - 2])
        else:
            A[m - 1, m - 1] = 1.0
        Mf = np.linalg.solve(A, R)
    pts = []
    for i in range(m - 1):
        hi, u0, u1 = float(h[i]), float(u[i]), float(u[i + 1])
        # S(t) = A·a³ + B·b³ + C·a + D·b,  a = u1 − t,  b = t − u0 (по каждой координате)
        A = [float(Mf[i][j]) / (6 * hi) for j in (0, 1)]
        B = [float(Mf[i + 1][j]) / (6 * hi) for j in (0, 1)]
        C = [float(Y[i][j]) / hi - float(Mf[i][j]) * hi / 6 for j in (0, 1)]
        D = [float(Y[i + 1][j]) / hi - float(Mf[i + 1][j]) * hi / 6 for j in (0, 1)]

        def f(t, u0=u0, u1=u1, A=A, B=B, C=C, D=D):
            a, b = u1 - t, t - u0
            a3, b3 = a * a * a, b * b * b
            return (A[0] * a3 + B[0] * b3 + C[0] * a + D[0] * b, A[1] * a3 + B[1] * b3 + C[1] * a + D[1] * b)
        part = _approx(f, u0, u1, pieces=4)
        part[0], part[-1] = Q[i], Q[i + 1]
        pts.extend(part[1:] if pts else part)
    return pts


def _arc_mid(e):
    a0 = math.atan2(e["p0"][1] - e["c"][1], e["p0"][0] - e["c"][0]) + e["sw"] / 2.0
    return (e["c"][0] + e["r"] * math.cos(a0), e["c"][1] + e["r"] * math.sin(a0))


def _snap(b):
    """bulge из углов (ARC в градусах): 0.9999999999999999 → 1.0; иначе как есть."""
    r = round(b, 12)
    return r if abs(b - r) < 1e-15 else b


def _ang_in(t, a0, sw):
    return (t - a0) % _TWO_PI <= sw if sw >= 0 else (a0 - t) % _TWO_PI <= -sw


def _poly_bbox(verts, closed):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    n = len(verts)
    for k in range(n if closed else n - 1):
        x0, y0, b = verts[k]
        if b:
            x1, y1, _ = verts[(k + 1) % n]
            c, r, a0, sw = _bulge_arc((x0, y0), (x1, y1), b)
            for t, (ux, uy) in ((0.0, (1, 0)), (math.pi / 2, (0, 1)), (math.pi, (-1, 0)), (1.5 * math.pi, (0, -1))):
                if _ang_in(t, a0, sw):
                    xs.append(c[0] + r * ux)
                    ys.append(c[1] + r * uy)
    return (min(xs), min(ys), max(xs), max(ys))


def _flatten(verts, closed, tol=_PIP_TOL):
    out = []
    n = len(verts)
    for k in range(n if closed else n - 1):
        x0, y0, b = verts[k]
        out.append((x0, y0))
        if b:
            x1, y1, _ = verts[(k + 1) % n]
            c, r, a0, sw = _bulge_arc((x0, y0), (x1, y1), b)
            step = 2.0 * math.acos(max(-1.0, 1.0 - tol / r)) if r > tol else math.pi / 2
            m = min(2000, max(1, int(math.ceil(abs(sw) / max(step, 1e-6)))))
            for j in range(1, m):
                a = a0 + sw * j / m
                out.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    if not closed:
        out.append((verts[-1][0], verts[-1][1]))
    return np.array(out, dtype=float)


def _seg_mid(verts, k=0):
    x0, y0, b = verts[k]
    x1, y1, _ = verts[(k + 1) % len(verts)]
    if not b:
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    c, r, a0, sw = _bulge_arc((x0, y0), (x1, y1), b)
    return (c[0] + r * math.cos(a0 + sw / 2), c[1] + r * math.sin(a0 + sw / 2))


def _pip_prep(poly):
    """Многоугольник (np.array (n, 2)) → массивы для быстрых запросов «точка внутри»."""
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        k = (xs2 - xs) / (ys2 - ys)
    return xs, ys, ys2, k


def _pip(pt, prep):
    """Точка внутри многоугольника? Чётность пересечений горизонтального луча."""
    x, y = pt
    xs, ys, ys2, k = prep
    cond = (ys > y) != (ys2 > y)
    with np.errstate(invalid="ignore", over="ignore"):
        xi = xs + (y - ys) * k
    return bool(np.count_nonzero(cond & (x < xi)) % 2)


class _Grid(object):
    """Равномерная сетка над габаритами контуров: «чьи габариты (с запасом pad) накрывают точку» без перебора всех
    (перфорированный лист — десятки тысяч отверстий)."""

    def __init__(self, items, pad=0.0):
        self.items, self.cells, self.g = items, defaultdict(list), 0
        if not items:
            return
        bbs = [it.bbox for it in items]
        self.x0 = min(b[0] for b in bbs) - pad
        self.y0 = min(b[1] for b in bbs) - pad
        x1 = max(b[2] for b in bbs) + pad
        y1 = max(b[3] for b in bbs) + pad
        self.g = max(1, min(256, int(math.sqrt(len(items)))))
        self.sx = max((x1 - self.x0) / self.g, 1e-9)
        self.sy = max((y1 - self.y0) / self.g, 1e-9)
        for i, b in enumerate(bbs):
            ix0, iy0 = self._cell(b[0] - pad, b[1] - pad)
            ix1, iy1 = self._cell(b[2] + pad, b[3] + pad)
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    self.cells[(ix, iy)].append(i)

    def _cell(self, x, y):
        g = self.g - 1
        return (min(g, max(0, int((x - self.x0) / self.sx))), min(g, max(0, int((y - self.y0) / self.sy))))

    def query(self, p):
        if not self.g:
            return []
        return [self.items[i] for i in self.cells.get(self._cell(p[0], p[1]), ())]


def _orient(verts, ccw):
    return vn.contours.orient([tuple(v) for v in verts], ccw)


# =====================================================================================  разбор файла
_U_RE = re.compile(r"\\[Uu]\+([0-9A-Fa-f]{4})")

_NOT_CUT = {
    "TEXT": "надпись", "MTEXT": "надпись", "ATTRIB": "атрибут блока", "ATTDEF": "атрибут блока",
    "DIMENSION": "размер", "ARC_DIMENSION": "размер", "LARGE_RADIAL_DIMENSION": "размер",
    "LEADER": "выноска", "MLEADER": "выноска", "MULTILEADER": "выноска", "TOLERANCE": "допуск формы",
    "HATCH": "штриховка", "MPOLYGON": "штриховка", "SOLID": "заливка", "TRACE": "заливка", "3DFACE": "3D-грань",
    "VIEWPORT": "видовой экран", "IMAGE": "картинка", "WIPEOUT": "маскировка", "OLE2FRAME": "OLE-объект",
    "OLEFRAME": "OLE-объект", "ACAD_TABLE": "таблица", "RAY": "вспомогательная прямая",
    "XLINE": "вспомогательная прямая", "LIGHT": "источник света", "SUN": "источник света",
    "PDFUNDERLAY": "подложка", "DWFUNDERLAY": "подложка", "DGNUNDERLAY": "подложка", "UNDERLAY": "подложка",
    "SHAPE": "символ формы",
}
_EXPLODE = {"REGION", "3DSOLID", "BODY", "SURFACE", "PLANESURFACE", "EXTRUDEDSURFACE", "REVOLVEDSURFACE",
            "LOFTEDSURFACE", "SWEPTSURFACE", "MESH", "MLINE", "HELIX", "ACAD_PROXY_ENTITY", "POLYFACE"}
_SILENT = {"POINT", "SEQEND", "VERTEX", "ENDBLK", "BLOCK"}
_GEOM = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"}
_DASH_NAMES = re.compile(r"CENTER|DASH|HIDDEN|PHANTOM|DOT|DIVIDE|BORDER|ОСЕВ|ШТРИХ|ПУНКТ|ISO0[2-9]|ISO1[0-5]", re.I)

_UNITS = {1: (25.4, "дюймы"), 2: (304.8, "футы"), 4: (1.0, None), 5: (10.0, "сантиметры"), 6: (1000.0, "метры"),
          8: (25.4e-6, "микродюймы"), 9: (0.0254, "милы"), 10: (914.4, "ярды"), 13: (0.001, "микроны"),
          14: (100.0, "дециметры")}


def _num(v, et, code):
    try:
        x = float(v.strip())
    except (ValueError, AttributeError):
        raise DxfError("%s: код %d — не число «%s»; файл DXF повреждён" % (et, code, str(v).strip()[:30]))
    if not math.isfinite(x):
        raise DxfError("%s: код %d — недопустимое число «%s»" % (et, code, v.strip()))
    return x


class _Ent(object):
    __slots__ = ("type", "tags", "verts", "attribs")

    def __init__(self, type_, tags):
        self.type, self.tags, self.verts, self.attribs = type_, tags, None, 0

    def raw(self, code, default=None):
        for c, v in self.tags:
            if c == code:
                return v
        return default

    def f(self, code, default=0.0):
        v = self.raw(code)
        return default if v is None else _num(v, self.type, code)

    def i(self, code, default=0):
        v = self.raw(code)
        return default if v is None else int(round(_num(v, self.type, code)))

    def floats(self, code):
        return [_num(v, self.type, code) for c, v in self.tags if c == code]

    def points(self, cx, cy):
        out = []
        for c, v in self.tags:
            if c == cx:
                out.append([_num(v, self.type, c), 0.0])
            elif c == cy and out:
                out[-1][1] = _num(v, self.type, c)
        return [tuple(p) for p in out]

    def normal(self):
        return (self.f(210, 0.0), self.f(220, 0.0), self.f(230, 1.0))


def _records(pairs):
    out, cur = [], None
    for c, v in pairs:
        if c == 0:
            cur = _Ent(v.strip().upper(), [])
            out.append(cur)
        elif cur is not None:
            cur.tags.append((c, v))
    return out


def _group(recs):
    """POLYLINE + VERTEX… + SEQEND → одна запись; INSERT + ATTRIB… + SEQEND → одна запись."""
    out, i, n = [], 0, len(recs)
    while i < n:
        r = recs[i]
        i += 1
        if r.type == "POLYLINE":
            r.verts = []
            while i < n and recs[i].type == "VERTEX":
                r.verts.append(recs[i])
                i += 1
            if i < n and recs[i].type == "SEQEND":
                i += 1
        elif r.type == "INSERT" and i < n and recs[i].type == "ATTRIB":
            while i < n and recs[i].type == "ATTRIB":
                r.attribs += 1
                i += 1
            if i < n and recs[i].type == "SEQEND":
                i += 1
        out.append(r)
    return out


def _fmt(v):
    if not (abs(v) < 1e12):                    # испорченные числа в сообщении — коротко (1e+300, inf, nan)
        return "%g" % v
    s = ("%.3f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class _Reader(object):
    """Разбор DXF и сбор рёбер в мировых координатах (мм)."""

    def __init__(self, data, engrave_layers):
        self.engrave_layers = engrave_layers
        self.notes = []                      # предупреждения разбора (по порядку)
        self.ign = {}                        # тип → число пропущенных
        self.cnt = defaultdict(int)          # счётчики приближений/пропусков
        self.hidden = {}                     # слой → число объектов
        self.dashed = {}                     # тип линии → число объектов
        self.missing = {}                    # блок → число вставок
        self.edges = []                      # {"t": "L"|"A", p0, p1, [c, r, sw, b], cls, ap, q}
        self.circles = []                    # {"c", "r", "cls", "q"}
        self.q = 0
        self._parse(data)

    # ------------------------------------------------------------------  файл → секции
    def note(self, msg):
        if msg not in self.notes:
            self.notes.append(msg)

    def pt(self, p):
        """Точка (мм) → текст в единицах чертежа."""
        return "(%s; %s)" % (_fmt(p[0] / self.unit), _fmt(p[1] / self.unit))

    def _parse(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        data = bytes(data)
        if not data.strip():
            raise DxfError("файл DXF пуст")
        if data.startswith(b"AutoCAD Binary DXF"):
            raise DxfError("двоичный DXF не поддерживается — сохраните чертёж как текстовый DXF (ASCII)")
        if re.match(rb"AC\d{4}", data[:6]):
            raise DxfError("это файл DWG, а не DXF — сохраните чертёж в CAD как DXF")
        bom = data.startswith(codecs.BOM_UTF8)
        if bom:
            data = data[3:]
        lines = data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        pairs, i, n = [], 0, len(lines)
        while i + 1 < n:
            cs = lines[i].strip()
            if not cs:
                if not any(x.strip() for x in lines[i:]):
                    break
                raise DxfError("строка %d: пустой код группы — файл DXF повреждён" % (i + 1))
            try:
                code = int(cs)
            except ValueError:
                raise DxfError("строка %d: ожидался код группы DXF, а там «%s» — файл повреждён или это не DXF"
                               % (i + 1, cs[:30]))
            val = lines[i + 1]
            i += 2
            if code == 999:
                continue
            if code == 0 and val.strip() == "EOF":
                break
            pairs.append((code, val))
        secs, k = {}, 0
        while k < len(pairs):
            c, v = pairs[k]
            if c == 0 and v.strip() == "SECTION":
                name = pairs[k + 1][1].strip().upper() if k + 1 < len(pairs) and pairs[k + 1][0] == 2 else ""
                j = k + 2
                while j < len(pairs) and not (pairs[j][0] == 0 and pairs[j][1].strip() == "ENDSEC"):
                    j += 1
                secs.setdefault(name, []).extend(pairs[k + 2:j])
                k = j + 1
            else:
                k += 1
        if "ENTITIES" not in secs:
            raise DxfError("в файле нет секции ENTITIES — это не DXF или файл обрезан")
        # HEADER
        hdr, var = {}, None
        for c, v in secs.get("HEADER", []):
            if c == 9:
                var = v.strip().upper()
                hdr[var] = []
            elif var is not None:
                hdr[var].append((c, v))

        def hv(name):
            vals = hdr.get(name)
            return vals[0][1].strip() if vals else None
        self.acadver = (hv("$ACADVER") or "").upper()
        self.codec = self._codec(hv("$DWGCODEPAGE"), bom)
        units = hv("$INSUNITS")
        try:
            u = None if units is None else int(round(float(units)))
        except (ValueError, OverflowError):
            u = None
        if u is None:
            self.unit = 1.0
            self.note("единицы чертежа не указаны ($INSUNITS) — считаю миллиметры")
        elif u == 0:
            self.unit = 1.0
            self.note("единицы чертежа не заданы ($INSUNITS = 0) — считаю миллиметры")
        elif u in _UNITS:
            self.unit, label = _UNITS[u]
            if label:
                self.note("единицы чертежа — %s: пересчитано в мм (×%g)" % (label, self.unit))
        else:
            self.unit = 1.0
            self.note("незнакомые единицы чертежа ($INSUNITS = %d) — считаю миллиметры" % u)
        # TABLES
        self.layers, self.ltypes = {}, {}
        for e in _records(secs.get("TABLES", [])):
            if e.type == "LAYER":
                nm = self.s(e.raw(2, ""))
                self.layers[nm.casefold()] = dict(name=nm, frozen=bool(e.i(70) & 1), off=e.i(62, 7) < 0,
                                                  ltype=self.s(e.raw(6, "CONTINUOUS")))
            elif e.type == "LTYPE":
                self.ltypes[self.s(e.raw(2, "")).casefold()] = any(x < 0 for x in e.floats(49))
        # BLOCKS
        self.blocks, cur = {}, None
        for e in _records(secs.get("BLOCKS", [])):
            if e.type == "BLOCK":
                nm = self.s(e.raw(2) or e.raw(3) or "")
                cur = dict(name=nm, base=(e.f(10), e.f(20)), flags=e.i(70), ents=[])
                self.blocks[nm.casefold()] = cur
            elif e.type == "ENDBLK":
                cur = None
            elif cur is not None:
                cur["ents"].append(e)
        for b in self.blocks.values():
            b["ents"] = _group(b["ents"])
        self.entities = _group(_records(secs["ENTITIES"]))

    def _codec(self, cp, bom):
        m = re.match(r"AC(\d{4})", self.acadver)
        ver = int(m.group(1)) if m else 0
        if bom or ver >= 1021:
            return "utf-8"
        if cp:
            c = cp.lower().replace("-", "").replace("_", "")
            if "utf8" in c:
                return "utf-8"
            m = re.search(r"(\d{3,4})", c)
            if m:
                for name in ("cp" + m.group(1), "iso8859_" + m.group(1)):
                    try:
                        codecs.lookup(name)
                        return name
                    except LookupError:
                        pass
            self.note("незнакомая кодировка $DWGCODEPAGE = %s — читаю как cp1251" % cp)
        return "cp1251"

    def s(self, raw):
        """Строка DXF → текст: UTF-8, если она корректна, иначе кодировка файла; \\U+XXXX раскрывается."""
        raw = (raw or "").strip()
        try:
            raw.encode("ascii")
            out = raw
        except UnicodeEncodeError:
            b = raw.encode("latin-1")
            try:
                out = b.decode("utf-8")
            except UnicodeDecodeError:
                if self.codec == "utf-8":
                    self.note("строки DXF не в UTF-8 — прочитаны как cp1251")
                    out = b.decode("cp1251", "replace")
                else:
                    out = b.decode(self.codec, "replace")
        if "\\" in out:
            out = _U_RE.sub(lambda mm: chr(int(mm.group(1), 16)), out)
        return out

    # ------------------------------------------------------------------  обход объектов
    def walk_all(self):
        u = self.unit
        self.walk(self.entities, (u, 0.0, 0.0, u, 0.0, 0.0), None, None, 0, ())

    def walk(self, ents, M, ctx_layer, ctx_lt, depth, stack):
        for e in ents:
            t = e.type
            if t in _SILENT:
                continue
            if depth == 0 and e.i(67) == 1:
                self.cnt["paper"] += 1
                continue
            layer = self.s(e.raw(8, "0")) or "0"
            if layer == "0" and ctx_layer is not None:
                layer = ctx_layer
            lay = self.layers.get(layer.casefold())
            if lay and (lay["frozen"] or (lay["off"] and t != "INSERT")):
                self.hidden[layer] = self.hidden.get(layer, 0) + 1
                continue
            if e.i(60) == 1:
                self.cnt["invisible"] += 1
                continue
            if t in _NOT_CUT or t in _EXPLODE:
                self.ign[t] = self.ign.get(t, 0) + 1
                continue
            lt = self.s(e.raw(6, "BYLAYER")) or "BYLAYER"
            if lt.upper() == "BYLAYER":
                lt = lay["ltype"] if lay else "CONTINUOUS"
            elif lt.upper() == "BYBLOCK":
                lt = ctx_lt or "CONTINUOUS"
            if t == "INSERT":
                if e.attribs:
                    self.ign["ATTRIB"] = self.ign.get("ATTRIB", 0) + e.attribs
                self._insert(e, M, layer, lt, depth, stack)
                continue
            if t not in _GEOM:
                self.ign[t] = self.ign.get(t, 0) + 1
                continue
            cls = 2 if is_engrave_layer(layer, self.engrave_layers) else 1
            if cls == 1 and self._is_dashed(lt):
                self.dashed[lt] = self.dashed.get(lt, 0) + 1
                continue
            getattr(self, "_e_" + t.lower())(e, M, cls)

    def _is_dashed(self, lt):
        k = (lt or "").casefold()
        if k in ("", "continuous", "bylayer", "byblock"):
            return False
        if k in self.ltypes:
            return self.ltypes[k]
        return bool(_DASH_NAMES.search(lt))

    def _ocs(self, e, M, elev=0.0):
        O, tilted = _ocs(e.normal(), elev)
        if tilted:
            self.cnt["tilted"] += 1
        return M if O is _ID else _mul(M, O)

    # ------------------------------------------------------------------  выдача рёбер
    def _check(self, what, *pts):
        """Точки (мм) конечны и не дальше _MAX_COORD — иначе DxfError (испорченные числа, огромный масштаб/единицы)."""
        for p in pts:
            if _bad(p):
                raise DxfError("%s: координаты (%g; %g) вне допустимого диапазона (±%g мм) — числа в DXF испорчены "
                               "или масштаб вставки/единицы чертежа ошибочны"
                               % (what, p[0] / self.unit, p[1] / self.unit, _MAX_COORD))

    def _extent_ok(self, pts, what):
        self._check(what, *pts)
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        if max(xs) - min(xs) > _MAX_EXTENT or max(ys) - min(ys) > _MAX_EXTENT:
            raise DxfError("%s у точки %s размером больше 10 км — координаты или единицы чертежа ошибочны"
                           % (what, self.pt(pts[0])))

    def _seq(self):
        self.q += 1
        if self.q > _MAX_ITEMS:
            raise DxfError("в DXF больше %d отрезков/дуг/окружностей — слишком много для одной детали; "
                           "проверьте файл (массивы блоков, огромный масштаб сплайнов)" % _MAX_ITEMS)
        return self.q

    def line(self, P0, P1, cls, ap=False):
        self._check("отрезок", P0, P1)
        if P0 != P1:
            self.edges.append(dict(t="L", p0=P0, p1=P1, cls=cls, ap=ap, q=self._seq()))
        elif not ap:
            self.cnt["zero"] += 1

    def points(self, pts, cls):
        pts = _thin(pts)
        for a, b in zip(pts, pts[1:]):
            self.line(a, b, cls, ap=True)

    def arc(self, c, r, a0, sw, M, cls, p0=None, p1=None, b=None):
        """Дуга (центр c, радиус r, начало a0, знаковый угол sw; концы p0/p1 и bulge b — если известны) в координатах
        M → ребро. Если M заметно искажает окружность в эллипс (больше _SIM_TOL) — ломаная."""
        if not (r > 0) or sw == 0:
            self.cnt["zero"] += 1
            return
        if p0 is None:
            p0 = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
            p1 = p0 if abs(sw) >= _TWO_PI else (c[0] + r * math.cos(a0 + sw), c[1] + r * math.sin(a0 + sw))
        sim = _sim(M)
        if sim and sim[3] * r <= _SIM_TOL:
            k, phi, s, _ = sim
            C, R, SW = _ap(M, c), k * r, s * sw
            P0, P1 = _ap(M, p0), _ap(M, p1)          # концы — точным преобразованием (сцепка с соседями)
            self._check("дуга", P0, P1)
            B = s * b if b is not None else _snap(math.tan(SW / 4.0))
            if not (R <= _MAX_RADIUS and math.isfinite(C[0]) and math.isfinite(C[1])):
                # огромный радиус: почти прямая (bulge ≈ 0) — отрезок; иначе числа испорчены
                if abs(B) * math.hypot(P1[0] - P0[0], P1[1] - P0[1]) / 2.0 <= _FLAT_SAG:
                    self.line(P0, P1, cls)
                    return
                raise DxfError("дуга у точки %s радиусом %g — числа в DXF испорчены (огромный bulge или радиус)"
                               % (self.pt(P0), R / self.unit))
            self.edges.append(dict(t="A", p0=P0, p1=P1, c=C, r=R, sw=SW, b=B, cls=cls, ap=False, q=self._seq()))
            return
        u, v, C = _lin(M, (r, 0.0)), _lin(M, (0.0, r)), _ap(M, c)
        self._extent_ok([(C[0] + u[0] + v[0], C[1] + u[1] + v[1]), (C[0] - u[0] - v[0], C[1] - u[1] - v[1])], "дуга")
        pts = _approx(lambda t: (C[0] + u[0] * math.cos(t) + v[0] * math.sin(t),
                                 C[1] + u[1] * math.cos(t) + v[1] * math.sin(t)), a0, a0 + sw, pieces=16)
        pts[0], pts[-1] = _ap(M, p0), _ap(M, p1)
        self.cnt["distorted"] += 1
        self.points(pts, cls)

    def circle(self, c, r, M, cls):
        if not (r > 0):
            self.cnt["zero"] += 1
            return
        sim = _sim(M)
        if sim and sim[3] * r <= _SIM_TOL:
            C, R = _ap(M, c), sim[0] * r
            self._circle(C, R, cls)
            return
        self.arc(c, r, 0.0, _TWO_PI, M, cls)

    def _circle(self, C, R, cls):
        self._check("окружность", C)
        if not (R <= _MAX_COORD):
            raise DxfError("окружность у точки %s радиусом %g — числа в DXF испорчены или единицы ошибочны"
                           % (self.pt(C), R / self.unit))
        self.circles.append(dict(c=C, r=R, cls=cls, q=self._seq()))

    def polyline(self, verts, closed, M, cls):
        if closed and len(verts) > 2 and verts[-1][:2] == verts[0][:2]:
            verts = verts[:-1]                  # замкнутая с повтором первой точки в конце — повтор лишний
        n = len(verts)
        if n < 2:
            return
        for k in range(n if closed else n - 1):
            x0, y0, b = verts[k]
            x1, y1, _ = verts[(k + 1) % n]
            if abs(b) < 1e-12 or (x0 == x1 and y0 == y1):
                self.line(_ap(M, (x0, y0)), _ap(M, (x1, y1)), cls)
            else:
                c, r, a0, sw = _bulge_arc((x0, y0), (x1, y1), b)
                self.arc(c, r, a0, sw, M, cls, p0=(x0, y0), p1=(x1, y1), b=b)

    # ------------------------------------------------------------------  сущности
    def _e_line(self, e, M, cls):
        self.line(_ap(M, (e.f(10), e.f(20))), _ap(M, (e.f(11), e.f(21))), cls)

    def _e_circle(self, e, M, cls):
        self.circle((e.f(10), e.f(20)), e.f(40), self._ocs(e, M, e.f(30)), cls)

    def _e_arc(self, e, M, cls):
        Me = self._ocs(e, M, e.f(30))
        d0, d1 = e.f(50), e.f(51)
        c, r = (e.f(10), e.f(20)), e.f(40)
        diff = d1 - d0
        if math.isfinite(diff) and abs(abs(diff) - 360.0) < 1e-9:
            self.circle(c, r, Me, cls)
            return
        d0, d1 = d0 % 360.0, d1 % 360.0
        sw = math.radians((d1 - d0) % 360.0)
        if sw < 1e-12:
            self.cnt["zero"] += 1
            return
        self.arc(c, r, math.radians(d0), sw, Me, cls)

    def _e_lwpolyline(self, e, M, cls):
        verts = []
        for c, v in e.tags:
            if c == 10:
                verts.append([_num(v, e.type, c), 0.0, 0.0])
            elif c == 20 and verts:
                verts[-1][1] = _num(v, e.type, c)
            elif c == 42 and verts:
                verts[-1][2] = _num(v, e.type, c)
        self.polyline([tuple(v) for v in verts], bool(e.i(70) & 1), self._ocs(e, M, e.f(38)), cls)

    def _e_polyline(self, e, M, cls):
        fl = e.i(70)
        if fl & (16 | 64):
            self.ign["POLYLINE (сеть)"] = self.ign.get("POLYLINE (сеть)", 0) + 1
            return
        vs = [v for v in (e.verts or []) if not (v.i(70) & 16)]        # 16 — рамка сплайна, не точка кривой
        if fl & 8:                                                       # 3D-полилиния: мировые координаты
            self.polyline([(v.f(10), v.f(20), 0.0) for v in vs], bool(fl & 1), M, cls)
        else:
            self.polyline([(v.f(10), v.f(20), v.f(42)) for v in vs], bool(fl & 1), self._ocs(e, M, e.f(30)), cls)

    def _e_spline(self, e, M, cls):
        p = e.i(71, 3)
        fl = e.i(70)
        closed = bool(fl & 1)
        K, W = e.floats(40), e.floats(41)
        P, F = e.points(10, 20), e.points(11, 21)
        pts = None
        if len(P) >= p + 1 >= 2:
            if W and (len(W) != len(P) or any(w <= 0 for w in W)):
                self.note("SPLINE: веса не согласованы с точками — сплайн считан без весов")
                W = []
            W = W or [1.0] * len(P)
            if any(b < a for a, b in zip(K, K[1:])):
                raise DxfError("SPLINE: узлы не по возрастанию — файл повреждён (сплайн у точки %s)"
                               % self.pt(_ap(M, P[0])))
            if len(K) != len(P) + p + 1:
                if len(F) >= 2:
                    P = []
                else:
                    self.note("SPLINE: число узлов не сходится с точками — взят равномерный закреплённый вектор узлов")
                    m = len(P) - p
                    K = [0.0] * (p + 1) + [float(j) for j in range(1, m)] + [float(m)] * (p + 1)
            if P:
                Pw = [_ap(M, q) for q in P]
                self._extent_ok(Pw, "SPLINE")
                if p == 1:
                    pts = list(Pw)
                else:
                    pts = _nurbs_pts(Pw, W, K, p)
                    if not pts:
                        self.note("SPLINE с вырожденными узлами (все пролёты пустые) — пропущен")
                        return
                    if closed and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > NODE_TOL:
                        # периодический сплайн без повтора управляющих точек: дописать первые p точек
                        n = len(Pw)
                        K2 = K + [K[j - n] + (K[n] - K[0]) for j in range(len(K), n + 2 * p + 1)]
                        alt = _nurbs_pts(Pw + Pw[:p], W + W[:p], K2, p)
                        if math.hypot(alt[0][0] - alt[-1][0], alt[0][1] - alt[-1][1]) <= NODE_TOL:
                            pts = alt
                if closed and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > NODE_TOL:
                    self.note("SPLINE: замкнутый сплайн не сошёлся — замкнут отрезком у точки %s" % self.pt(pts[0]))
                    pts.append(pts[0])
        if pts is None and len(F) >= 2:
            Fw = [_ap(M, q) for q in F]
            self._extent_ok(Fw, "SPLINE")
            tg = []
            for cx, cy in ((12, 22), (13, 23)):
                if e.raw(cx) is not None:
                    v = _lin(M, (e.f(cx), e.f(cy)))
                    L = math.hypot(*v)
                    tg.append((v[0] / L, v[1] / L) if L > 0 else None)
                else:
                    tg.append(None)
            try:
                pts = _fit_curve(Fw, closed, tg[0], tg[1])
            except np.linalg.LinAlgError:
                raise DxfError("SPLINE: опорные точки вырождены — сплайн у точки %s не построить" % self.pt(Fw[0]))
            self.cnt["fit"] += 1
        if pts is None:
            self.note("SPLINE без точек — пропущен")
            return
        self.cnt["spline"] += 1
        self.points(pts, cls)

    def _e_ellipse(self, e, M, cls):
        c = (e.f(10), e.f(20))
        mj = (e.f(11), e.f(21), e.f(31))
        ratio = e.f(40, 1.0)
        s0, s1 = e.f(41, 0.0), e.f(42, _TWO_PI)
        if not (abs(s0) <= 1e6 and abs(s1) <= 1e6):
            raise DxfError("ELLIPSE у точки %s: параметры дуги %g … %g недопустимы — файл DXF повреждён"
                           % (self.pt(_ap(M, c)), s0, s1))
        N = e.normal()
        L = math.sqrt(N[0] ** 2 + N[1] ** 2 + N[2] ** 2)
        N = (0.0, 0.0, 1.0) if not (L >= 1e-12) else (N[0] / L, N[1] / L, N[2] / L)
        if abs(abs(N[2]) - 1.0) > 1e-9:
            self.cnt["tilted"] += 1
        mn = _cross(N, mj)
        mn = (mn[0] * ratio, mn[1] * ratio)
        C, u, v = _ap(M, c), _lin(M, mj[:2]), _lin(M, mn)
        self._check("ELLIPSE", C, (C[0] + u[0] + v[0], C[1] + u[1] + v[1]), (C[0] - u[0] - v[0], C[1] - u[1] - v[1]))
        d = (s1 - s0) % _TWO_PI                     # дуга от s0 против часовой (в параметре), без лишних оборотов
        full = d < 1e-9 or _TWO_PI - d < 1e-9
        s0 = s0 % _TWO_PI
        s1 = s0 + (_TWO_PI if full else d)
        ru, rv = math.hypot(*u), math.hypot(*v)
        if ru == 0 or rv == 0:
            self.cnt["zero"] += 1
            return
        sim = _sim((u[0], v[0], u[1], v[1], 0.0, 0.0))
        if sim and sim[3] <= _SIM_TOL:              # оси равны (в пределах 0,001 мм) — окружность, точная дуга
            k, phi, s, _ = sim
            if full:
                self._circle(C, k, cls)
            else:
                P0 = (C[0] + u[0] * math.cos(s0) + v[0] * math.sin(s0), C[1] + u[1] * math.cos(s0) + v[1] * math.sin(s0))
                P1 = (C[0] + u[0] * math.cos(s1) + v[0] * math.sin(s1), C[1] + u[1] * math.cos(s1) + v[1] * math.sin(s1))
                self.arc(C, k, phi + s * s0, s * (s1 - s0), _ID, cls, p0=P0, p1=P1)
            return
        self._extent_ok([(C[0] + u[0] + v[0], C[1] + u[1] + v[1]), (C[0] - u[0] - v[0], C[1] - u[1] - v[1])],
                        "ELLIPSE")
        pts = _approx(lambda t: (C[0] + u[0] * math.cos(t) + v[0] * math.sin(t),
                                 C[1] + u[1] * math.cos(t) + v[1] * math.sin(t)), s0, s1, pieces=16)
        if full:
            pts[-1] = pts[0]
        self.cnt["ellipse"] += 1
        self.points(pts, cls)

    def _insert(self, e, M, layer, lt, depth, stack):
        name = self.s(e.raw(2, ""))
        if name.upper().startswith("*D"):
            return
        blk = self.blocks.get(name.casefold())
        if blk is None:
            self.missing[name] = self.missing.get(name, 0) + 1
            return
        if blk["flags"] & 4:
            self.missing[name + " (внешняя ссылка)"] = self.missing.get(name + " (внешняя ссылка)", 0) + 1
            return
        if name.casefold() in stack:
            raise DxfError("блок «%s» вставлен сам в себя — файл DXF повреждён" % name)
        if depth >= _MAX_DEPTH:
            raise DxfError("вложенность блоков больше %d (блок «%s»)" % (_MAX_DEPTH, name))
        sx, sy = e.f(41, 1.0), e.f(42, 1.0)
        if sx == 0 or sy == 0:
            self.cnt["zero_scale"] += 1
            return
        cols, rows = max(1, e.i(70, 1)), max(1, e.i(71, 1))
        cs, rs = e.f(44, 0.0), e.f(45, 0.0)
        self.n_ins = getattr(self, "n_ins", 0) + cols * rows
        if self.n_ins > _MAX_INSERTS:
            raise DxfError("вставок блоков больше %d (блок «%s», массив %d×%d) — файл слишком сложный или повреждён"
                           % (_MAX_INSERTS, name, cols, rows))
        Mo = self._ocs(e, M, e.f(30))
        head = _mul(_mul(Mo, _tr(e.f(10), e.f(20))), _rot(e.f(50)))
        tail = _mul((sx, 0.0, 0.0, sy, 0.0, 0.0), _tr(-blk["base"][0], -blk["base"][1]))
        for r in range(rows):
            for c in range(cols):
                Mi = _mul(_mul(head, _tr(c * cs, r * rs)), tail)
                self.walk(blk["ents"], Mi, layer, lt, depth + 1, stack + (name.casefold(),))

    # ------------------------------------------------------------------  итог предупреждений
    def summary(self):
        out = list(self.notes)
        for t, n in self.ign.items():
            if t in _EXPLODE:
                out.append("%s ×%d — не читается: если это контур детали, разбейте его в CAD (EXPLODE / «Разрушить»)"
                           % (t, n))
            elif t in _NOT_CUT or t == "ATTRIB":
                out.append("%s ×%d — пропущено (%s, не режется)" % (t, n, _NOT_CUT.get(t, "атрибут блока")))
            elif t == "POLYLINE (сеть)":
                out.append("POLYLINE-сеть ×%d — пропущено (3D-сеть не режется)" % n)
            else:
                out.append("%s ×%d — пропущено (тип не поддерживается)" % (t, n))
        for nm, n in self.hidden.items():
            out.append("слой «%s» выключен или заморожен — пропущено объектов: %d" % (nm, n))
        for nm, n in self.dashed.items():
            out.append("линии прерывистого типа «%s» (осевые/штриховые/сгиб) не режутся — пропущено: %d" % (nm, n))
        for nm, n in self.missing.items():
            out.append("блок «%s» не найден в файле — пропущено вставок: %d" % (nm, n))
        msgs = {
            "paper": "объекты пространства листа не читаются — пропущено: %d",
            "invisible": "невидимые объекты — пропущено: %d",
            "zero_scale": "вставки блоков с нулевым масштабом — пропущено: %d",
            "tilted": "объекты не в плоскости XY (наклонная нормаль) — спроецированы на XY: %d",
            "spline": "SPLINE ×%d — приближено ломаной (отклонение ≤ 0,01 мм)",
            "fit": "из них по опорным точкам (без управляющих): %d — форма между точками может немного отличаться от CAD",
            "ellipse": "ELLIPSE ×%d — приближено ломаной (отклонение ≤ 0,01 мм)",
            "distorted": "дуги в блоках с разным масштабом X/Y (стали эллипсами) — приближено ломаной: %d",
            "zero": "отрезки/дуги нулевой длины — выброшено: %d",
            "dup": "дублирующиеся линии (наложены друг на друга) — выброшено: %d",
        }
        for k in ("paper", "invisible", "zero_scale", "tilted", "spline", "fit", "ellipse", "distorted", "zero", "dup"):
            if self.cnt.get(k):
                out.append(msgs[k] % self.cnt[k])
        return out


# =====================================================================================  контуры
class _Ct(object):
    """Контур: kind 'poly' | 'circle' | 'line'; cls 1 — рез, 2 — гравировка."""
    __slots__ = ("kind", "cls", "closed", "verts", "c", "r", "p1", "p2", "q", "area", "bbox", "flat", "sample")

    def __init__(self, kind, cls, q, closed=False, verts=None, c=None, r=None, p1=None, p2=None):
        self.kind, self.cls, self.q, self.closed = kind, cls, q, closed
        self.verts, self.c, self.r, self.p1, self.p2 = verts, c, r, p1, p2
        self.flat = None
        if kind == "circle":
            self.area = math.pi * r * r
            self.bbox = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
            self.sample = (c[0] + r, c[1])
        elif kind == "line":
            self.area = 0.0
            self.bbox = (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
            self.sample = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        else:
            self.area = abs(vn.contours.area(verts)) if closed else 0.0
            self.bbox = _poly_bbox(verts, closed)
            self.sample = _seg_mid(verts, 0)

    def contains(self, p):
        b = self.bbox
        if not (b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]):
            return False
        if self.kind == "circle":
            return math.hypot(p[0] - self.c[0], p[1] - self.c[1]) < self.r
        if self.flat is None:
            self.flat = _pip_prep(_flatten(self.verts, True))
        return _pip(p, self.flat)

    def key_points(self):
        if self.kind == "circle":
            return [(self.c[0] + self.r, self.c[1]), (self.c[0], self.c[1] + self.r),
                    (self.c[0] - self.r, self.c[1]), (self.c[0], self.c[1] - self.r)]
        return [(v[0], v[1]) for v in self.verts]


def _contours(rd):
    """Рёбра и окружности → контуры (_Ct) по слоям реза и гравировки."""
    E = rd.edges
    pts = [q for e in E for q in (e["p0"], e["p1"])]
    ids = vn.contours._node_ids(pts, NODE_TOL) if pts else []
    n0, n1 = ids[0::2], ids[1::2]
    reps = {}
    for q, nid in zip(pts, ids):
        reps.setdefault(nid, q)
    circles = list(rd.circles)
    keep = []
    for k, e in enumerate(E):
        if n0[k] == n1[k]:
            if e["t"] == "A" and abs(e["sw"]) > math.pi:          # почти полная дуга с совпавшими концами
                circles.append(dict(c=e["c"], r=e["r"], cls=e["cls"], q=e["q"]))
            elif not e["ap"]:
                rd.cnt["zero"] += 1
            continue
        keep.append(k)
    # точные дубли рёбер (рез важнее гравировки)
    arcs = [k for k in keep if E[k]["t"] == "A"]
    mid_ids = dict(zip(arcs, vn.contours._node_ids([_arc_mid(E[k]) for k in arcs], NODE_TOL) if arcs else []))
    seen, alive = {}, {}
    for k in keep:
        a, b = sorted((n0[k], n1[k]))
        key = (E[k]["t"], a, b, mid_ids.get(k))
        if key in seen:
            j = seen[key]
            rd.cnt["dup"] += 1
            if E[j]["cls"] == 2 and E[k]["cls"] == 1:
                del alive[j]
                seen[key] = k
                alive[k] = True
            continue
        seen[key] = k
        alive[k] = True
    keep = [k for k in keep if k in alive]
    out = [_Ct("circle", c["cls"], c["q"], closed=True, c=c["c"], r=c["r"]) for c in circles]
    for cls in (1, 2):
        idx = [k for k in keep if E[k]["cls"] == cls]
        for seq, closed in _decompose(idx, n0, n1, cls, rd, reps):
            out.append(_chain_contour(seq, closed, E, cls))
    out.sort(key=lambda c: c.q)
    return _dedupe_closed(rd, out)


def _probe(ct, limit=64):
    """Точки на линии замкнутого контура для сверки «тот же контур?»: вершины и середины участков (не больше ~limit)."""
    if ct.kind == "circle":
        return [(ct.c[0] + ct.r * math.cos(j * math.pi / 4), ct.c[1] + ct.r * math.sin(j * math.pi / 4))
                for j in range(8)]
    n = len(ct.verts)
    out = []
    for k in range(0, n, max(1, n // max(1, limit // 2))):
        out.append((ct.verts[k][0], ct.verts[k][1]))
        out.append(_seg_mid(ct.verts, k))
    return out


def _same_closed(a, b, tol=NODE_TOL):
    """Два замкнутых контура — одна и та же линия (в пределах tol)? Окружность CIRCLE и та же окружность дугами
    или полилинией с bulge, прямоугольник разной записи и т.п."""
    if a.kind == "circle" and b.kind == "circle":
        return math.hypot(a.c[0] - b.c[0], a.c[1] - b.c[1]) <= tol and abs(a.r - b.r) <= tol
    bb = a.bbox
    if abs(a.area - b.area) > 4.0 * tol * ((bb[2] - bb[0]) + (bb[3] - bb[1])) + 1e-9:
        return False
    return (all(_dist_contour(p, b) <= tol for p in _probe(a)) and
            all(_dist_contour(p, a) <= tol for p in _probe(b)))


def _dedupe_closed(rd, cts):
    """Дубли замкнутых контуров в разной записи (рёбра у них разные, поэтому сверка рёбер их не ловит): остаётся
    первый по файлу; рез важнее гравировки. Кандидаты — контуры с тем же габаритом (±NODE_TOL)."""
    closed = [c for c in cts if c.closed]
    if len(closed) < 2:
        return cts
    lo = vn.contours._node_ids([(c.bbox[0], c.bbox[1]) for c in closed], NODE_TOL)
    hi = vn.contours._node_ids([(c.bbox[2], c.bbox[3]) for c in closed], NODE_TOL)
    groups = defaultdict(list)
    for c, a, b in zip(closed, lo, hi):
        groups[(a, b)].append(c)
    drop = set()
    for g in groups.values():
        if len(g) < 2:
            continue
        kept = []
        for c in g:                                  # g — в порядке файла (cts отсортированы по q)
            j = next((j for j, k in enumerate(kept) if _same_closed(k, c)), None)
            if j is None:
                kept.append(c)
                continue
            rd.cnt["dup"] += 1
            if kept[j].cls == 2 and c.cls == 1:
                drop.add(id(kept[j]))
                kept[j] = c
            else:
                drop.add(id(c))
    return [c for c in cts if id(c) not in drop] if drop else cts


def _decompose(idx, n0, n1, cls, rd, reps):
    """Граф рёбер → цепочки [(ребро, вперёд?)], замкнута?. Сначала пути от узлов степени ≠ 2, затем циклы."""
    adj = defaultdict(list)
    for k in idx:
        adj[n0[k]].append(k)
        adj[n1[k]].append(k)
    deg = {v: len(l) for v, l in adj.items()}
    branch = sorted((v for v, d in deg.items() if d > 2), key=lambda v: min(adj[v]))
    if branch and cls == 1:
        first = branch[0]
        more = ("; ещё узлов ветвления: %d, например %s" % (len(branch) - 1, ", ".join(rd.pt(reps[v]) for v in branch[1:4]))
                if len(branch) > 1 else "")
        raise DxfError("контур реза ветвится: в точке %s сходятся линии (%d шт.)%s. Так бывает, если в файл попали рамка, "
                       "штамп, размеры или вспомогательные линии (разбитые на отрезки), детали касаются друг друга "
                       "или на линию наложен лишний отрезок. Уберите лишнее в CAD; гравировку вынесите на слой "
                       "«Гравировка»." % (rd.pt(reps[first]), deg[first], more))
    used = set()

    def walk(node, k):
        seq, start = [], node
        while True:
            used.add(k)
            fwd = n0[k] == node
            seq.append((k, fwd))
            node = n1[k] if fwd else n0[k]
            if node == start or deg[node] != 2:
                break
            nxt = [j for j in adj[node] if j not in used]
            if not nxt:
                break
            k = nxt[0]
        return seq, node == start

    chains = []
    for v in sorted((v for v in adj if deg[v] != 2), key=lambda v: min(adj[v])):
        for k in adj[v]:
            if k not in used:
                chains.append(walk(v, k))
    for k in idx:
        if k not in used:
            chains.append(walk(n0[k], k))
    return chains


def _chain_contour(seq, closed, E, cls):
    q = min(E[k]["q"] for k, _ in seq)
    if closed and all(E[k]["t"] == "A" for k, _ in seq):          # дуги одной окружности → Circle
        c0, r0 = E[seq[0][0]]["c"], E[seq[0][0]]["r"]
        tol = 1e-6 * max(1.0, r0)
        tot = sum(E[k]["sw"] if f else -E[k]["sw"] for k, f in seq)
        if (all(math.hypot(E[k]["c"][0] - c0[0], E[k]["c"][1] - c0[1]) <= tol and abs(E[k]["r"] - r0) <= tol
                for k, _ in seq) and abs(abs(tot) - _TWO_PI) < 1e-6):
            return _Ct("circle", cls, q, closed=True, c=c0, r=r0)
    verts = []
    for k, fwd in seq:
        e = E[k]
        a = e["p0"] if fwd else e["p1"]
        b = 0.0 if e["t"] == "L" else (e["b"] if fwd else -e["b"])
        verts.append((a[0], a[1], b))
    if not closed:
        k, fwd = seq[-1]
        z = E[k]["p1"] if fwd else E[k]["p0"]
        verts.append((z[0], z[1], 0.0))
        if len(seq) == 1 and E[k]["t"] == "L":
            return _Ct("line", cls, q, p1=(verts[0][0], verts[0][1]), p2=(z[0], z[1]))
    return _Ct("poly", cls, q, closed=closed, verts=verts)


def _dist_contour(p, ct):
    """Расстояние от точки до линии контура (дуги — точно)."""
    if ct.kind == "circle":
        return abs(math.hypot(p[0] - ct.c[0], p[1] - ct.c[1]) - ct.r)
    if ct.kind == "line":
        return _dist_seg(p, ct.p1, ct.p2)
    v, n, best = ct.verts, len(ct.verts), float("inf")
    for k in range(n if ct.closed else n - 1):
        x0, y0, b = v[k]
        x1, y1, _ = v[(k + 1) % n]
        if not b:
            d = _dist_seg(p, (x0, y0), (x1, y1))
        else:
            c, r, a0, sw = _bulge_arc((x0, y0), (x1, y1), b)
            if _ang_in(math.atan2(p[1] - c[1], p[0] - c[0]), a0, sw):
                d = abs(math.hypot(p[0] - c[0], p[1] - c[1]) - r)
            else:
                d = min(math.hypot(p[0] - x0, p[1] - y0), math.hypot(p[0] - x1, p[1] - y1))
        best = min(best, d)
    return best


def _touch_check(rd, cts, tol=NODE_TOL):
    """Конец незамкнутого реза упирается в другой контур реза без общего узла (Т-примыкание) — предупреждение.
    Так выглядят разгрузочные резы (прорезь до отверстия, надрез от края), но и рамка/штамп/выносные линии — пусть
    человек посмотрит. Не ошибка: договор (DESIGN.md) — незамкнутая цепочка реза внутри детали = открытый рез."""
    cut = [c for c in cts if c.cls == 1]
    if all(c.closed for c in cut):
        return
    grid = _Grid(cut, pad=tol)
    hits = []
    for c in cut:
        if c.closed:
            continue
        for p in ((c.p1, c.p2) if c.kind == "line" else (c.verts[0][:2], c.verts[-1][:2])):
            for o in grid.query(p):
                b = o.bbox
                if o is c or not (b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol):
                    continue
                if _dist_contour(p, o) <= tol:
                    hits.append(p)
                    break
    if hits:
        rd.note("концы открытых резов упираются в другой контур реза (Т-примыкание): %d, например в точке %s — "
                "оставлены как прорези (разгрузочный рез, надрез от края). Если это рамка, штамп или "
                "вспомогательные линии — уберите их в CAD" % (len(hits), rd.pt(hits[0])))


# =====================================================================================  детали
def _within(inner, outer, tol=NODE_TOL):
    a, b = inner.bbox, outer.bbox
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def _partition(rd, cts):
    """Контуры → [(внешний, [внутренние])]; проверки замкнутости и принадлежности."""
    closed_cut = [c for c in cts if c.cls == 1 and c.closed]
    if not cts:
        raise DxfError("в DXF нет контуров для резки (LINE, ARC, CIRCLE, LWPOLYLINE, POLYLINE, SPLINE, ELLIPSE)")
    _touch_check(rd, cts)
    containers = {}
    grid = _Grid(closed_cut)
    for c in closed_cut:
        containers[id(c)] = [o for o in grid.query(c.sample) if o is not c and o.area > c.area and o.contains(c.sample)]
    outers = [c for c in closed_cut if not containers[id(c)]]
    outers.sort(key=lambda o: (round(o.bbox[0], 6), round(o.bbox[1], 6), o.q))
    oset = set(id(o) for o in outers)
    groups = dict((id(o), []) for o in outers)
    open_out, outside, nested = [], [], []
    ogrid = _Grid(outers)
    for c in cts:
        if id(c) in oset:
            continue
        if c.cls == 1 and c.closed:
            owners = [o for o in containers[id(c)] if id(o) in oset]
            if len(containers[id(c)]) >= 2:
                nested.append(c)
        else:
            owners = [o for o in ogrid.query(c.sample) if o.contains(c.sample)]
        if not owners:
            (open_out if (c.cls == 1 and not c.closed) else outside).append(c)
            continue
        groups[id(min(owners, key=lambda o: o.area))].append(c)
    if open_out:
        ends = []
        for c in open_out:
            ends += [c.p1, c.p2] if c.kind == "line" else [c.verts[0][:2], c.verts[-1][:2]]
        desc = []
        for c in open_out[:4]:
            a, b = (c.p1, c.p2) if c.kind == "line" else (c.verts[0][:2], c.verts[-1][:2])
            gaps = []
            for p in (a, b):
                d = min((math.hypot(p[0] - q[0], p[1] - q[1]) for q in ends if q is not p and q != p), default=None)
                gaps.append(d)
            g = [d for d in gaps if d is not None]
            desc.append("от %s до %s%s" % (rd.pt(a), rd.pt(b),
                                         (", до ближайшего свободного конца %s" % _fmt(min(g) / rd.unit)) if g else ""))
        raise DxfError("внешний контур не замкнут (разрыв больше %g мм): незамкнутых цепочек реза вне деталей — %d; %s%s. "
                       "Сомкните концы в CAD." % (NODE_TOL, len(open_out), "; ".join(desc),
                                                  "; …" if len(open_out) > 4 else ""))
    if not outers:
        raise DxfError("в DXF нет замкнутого контура на слое реза — нечего вырезать (только гравировка?)")
    if outside:
        raise DxfError("вне контуров деталей элементов: %d, например у точки %s. Уберите их из DXF или "
                       "проверьте, что внешний контур детали замкнут." % (len(outside), rd.pt(outside[0].sample)))
    for o in outers:
        for c in groups[id(o)]:
            if not _within(c, o):
                raise DxfError("элемент у точки %s выходит за внешний контур детали — контуры пересекаются"
                               % rd.pt(c.sample))
    if len(outers) > 1:
        for a in outers:
            for p in a.key_points():
                for b in ogrid.query(p):
                    if b is not a and b.contains(p):
                        raise DxfError("контуры деталей пересекаются: точка %s одной детали лежит внутри другой"
                                       % rd.pt(p))
        for i_, a in enumerate(outers):                  # пересечение по линиям (крест из двух прямоугольников)
            for b in outers[i_ + 1:]:
                x = _cross_pt(a, b)
                if x is not None:
                    raise DxfError("контуры деталей пересекаются в точке %s — это одна деталь, нарисованная "
                                   "наложенными контурами? Обведите её одним контуром" % rd.pt(x))
    for o in outers:
        for c in groups[id(o)]:
            if c.cls == 1 and c.closed:
                x = _cross_pt(c, o)
                if x is not None:
                    raise DxfError("отверстие пересекает внешний контур детали в точке %s" % rd.pt(x))
            elif c.cls == 1 and not c.closed:
                a_, b_ = (c.p1, c.p2) if c.kind == "line" else (c.verts[0][:2], c.verts[-1][:2])
                if _dist_contour(a_, o) <= NODE_TOL and _dist_contour(b_, o) <= NODE_TOL:
                    raise DxfError("открытый рез от %s до %s идёт от кромки до кромки детали и режет её на части — "
                                   "это осевая/вспомогательная линия? Уберите её со слоя реза или разделите деталь"
                                   % (rd.pt(a_), rd.pt(b_)))
    if nested:
        rd.note("контуров внутри отверстий: %d (например у точки %s) — оставлены внутренними резами детали; если это "
                "отдельные детали, вынесите их из отверстий в сторону или в отдельный файл"
                % (len(nested), rd.pt(nested[0].sample)))
    return [(o, groups[id(o)]) for o in outers]


def _ct_pts(ct):
    if ct.kind == "circle":
        n = max(16, int(2 * math.pi * ct.r / 0.5))
        return [(ct.c[0] + ct.r * math.cos(2 * math.pi * k / n), ct.c[1] + ct.r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    if ct.kind == "line":
        return [ct.p1, ct.p2]
    return _flatten(ct.verts, ct.closed)


def _cross_pt(a, b):
    """Точка, где линии контуров a и b пересекаются (не касаются в общей вершине), или None."""
    ba, bb = a.bbox, b.bbox
    if ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
        return None
    A = [(float(x), float(y)) for x, y in _ct_pts(a)]      # _flatten отдаёт массив numpy: «+» сложил бы координаты
    B = [(float(x), float(y)) for x, y in _ct_pts(b)]
    sa = list(zip(A, A[1:] + ([A[0]] if a.closed else [])))
    sb = list(zip(B, B[1:] + ([B[0]] if b.closed else [])))
    sb = [(p, q, (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))) for p, q in sb]
    for p, q in sa:
        x0, y0, x1, y1 = min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])
        for r, s, bx in sb:
            if bx[2] < x0 or x1 < bx[0] or bx[3] < y0 or y1 < bx[1]:
                continue
            d1 = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
            d2 = (q[0] - p[0]) * (s[1] - p[1]) - (q[1] - p[1]) * (s[0] - p[0])
            d3 = (s[0] - r[0]) * (p[1] - r[1]) - (s[1] - r[1]) * (p[0] - r[0])
            d4 = (s[0] - r[0]) * (q[1] - r[1]) - (s[1] - r[1]) * (q[0] - r[0])
            if d1 * d2 < -1e-12 and d3 * d4 < -1e-12:      # строгое пересечение, касание в вершине — не в счёт
                L1, L2 = abs(d3), abs(d4)
                t_ = L1 / (L1 + L2)
                return (p[0] + (q[0] - p[0]) * t_, p[1] + (q[1] - p[1]) * t_)
    return None


def _r(v):
    x = round(v, 9)
    return 0.0 if x == 0 else x


def _shape(ct, dx, dy, outer=False):
    base = dict(handle=None, layer=ct.cls, layer_name="0", coedge=0, flag64=0, outer=1 if outer else 0, lead=None)
    if ct.kind == "circle":
        base.update(kind="Circle", c=(_r(ct.c[0] - dx), _r(ct.c[1] - dy)), r=_r(ct.r), a0=math.pi / 4)
    elif ct.kind == "line":
        base.update(kind="Line", p1=(_r(ct.p1[0] - dx), _r(ct.p1[1] - dy)), p2=(_r(ct.p2[0] - dx), _r(ct.p2[1] - dy)))
    else:
        verts = ct.verts
        if ct.closed:
            verts = _orient(verts, ccw=outer)
        base.update(kind="LwPolyline", verts=[(_r(x - dx), _r(y - dy), b + 0.0) for x, y, b in verts],
                    flag=1 if ct.closed else 0, sp=0.0)
    return base


def parts_from_dxf(data, filename, qty=None, engrave_layers=None):
    """DXF (байты) → [Part]. Part = {"name", "qty", "shapes", "src", "warnings"} (см. DESIGN.md).
    data — содержимое файла; filename — имя (для имени детали и количества); qty — количество (иначе из имени
    файла, иначе 1); engrave_layers — свой список слоёв гравировки (точные имена без учёта регистра).
    Ошибки — DxfError (по-русски)."""
    try:
        return _parts(data, filename, qty, engrave_layers)
    except DxfError:
        raise
    except (ArithmeticError, ValueError, np.linalg.LinAlgError) as ex:
        # страховка: испорченные числа, которые не поймали проверки выше, — тоже DxfError, а не чужое исключение
        raise DxfError("DXF не прочитан: числа в файле испорчены (%s: %s)" % (type(ex).__name__, ex))


def _parts(data, filename, qty, engrave_layers):
    rd = _Reader(data, engrave_layers)
    rd.walk_all()
    cts = _contours(rd)
    groups = _partition(rd, cts)
    q_name, base = qty_from_filename(filename)
    warnings = rd.summary()
    if qty is None:
        if q_name:
            qty = q_name
        else:
            qty = 1
            warnings.append("количество не указано (ни аргументом, ни в имени файла) — 1 шт.")
    else:
        try:
            qf = float(qty)
        except (TypeError, ValueError):
            raise DxfError("количество «%s» — не число" % (qty,))
        if not math.isfinite(qf) or qf < 1 or qf != int(qf):
            raise DxfError("количество должно быть целым ≥ 1, получено %s" % (qty,))
        qty = int(qf)
        if q_name and q_name != qty:
            warnings.append("в имени файла количество %d, взято переданное %d" % (q_name, qty))
    name = _part_name(base)
    parts = []
    for k, (o, inner) in enumerate(groups):
        dx, dy = o.bbox[0], o.bbox[1]
        w, h = o.bbox[2] - o.bbox[0], o.bbox[3] - o.bbox[1]
        pw = list(warnings)
        if max(w, h) < 1.0 or max(w, h) > 20000.0:
            pw.append("габарит детали %s × %s мм — проверьте единицы чертежа" % (_fmt(w), _fmt(h)))
        shapes = [_shape(c, dx, dy) for c in sorted(inner, key=lambda c: c.q)] + [_shape(o, dx, dy, outer=True)]
        parts.append(dict(name=name if len(groups) == 1 else "%s #%d" % (name, k + 1), qty=qty, shapes=shapes,
                          src=filename, warnings=pw))
    return parts
