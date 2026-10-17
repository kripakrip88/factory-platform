# -*- coding: utf-8 -*-
"""Фигуры программы CypCut (Shapes2D + Geometry2D) для read_lxds — свои декодеры поверх пакетного
spec_rebuild.read_shape (17.10.2026, движок 0.13.0; пакет vent_nesting не правим).

Пакет понимает Line, Circle, LwPolyline; прочие классы он разбирал как полилинию: дуга — struct.error, текст без
GeoAddr — TypeError, и вся программа выходила «повреждённой»; а кривые Безье читатель молча выбрасывал. Формат
выяснен по архиву завода (2104 программы: 19 133 дуги, 15 214 кривых, 4951 надпись):

- Arc — <I3dI2d>: метка, центр x, y, радиус, направление (0 — против часовой, 1 — по часовой), угол начала, размах
  (рад, 0…2π). Так дуги одной окружности стоят на равных промежутках и не перекрываются (отверстия с перемычками),
  а зеркальная дуга — направление 1 с углом π − a0. → открытая LwPolyline с bulge (больше полуоборота — два участка);
  полный оборот — Circle; нулевой размах — пропуск с предупреждением.
- PolyBezier — <dIII>: начало (sp: участок + доля, с нуля), флаг (бит 1 — замкнута), 0, число участков; участок —
  номер (с 1), 4 точки (метка + x, y) кубической кривой, 0; в конце 0. → LwPolyline: прямой участок (управляющие
  точки на хорде) — отрезком, кривой — ломаной с отклонением ≤ CURVE_TOL (как сплайн в read_dxf); у замкнутой первая
  вершина — точка начала sp. Участки не сходятся (3 кривые из 15 214) — отдельные куски.
- Text — геометрии в файле нет (надпись шрифтом CypCut): пометка kind="Text" со словом и слоем (ChannelPort).
- Прочее (неизвестный класс, запись не читается) — пометка kind="?" с причиной: деталь с ней — ошибка у читателя
  (молча не выбрасываем ничего).

Склейка (glue): открытые куски одного слоя (не общего реза), концы которых сходятся (≤ NODE_TOL) в узле без ветвления,
— одна фигура: замкнулась — замкнутая LwPolyline, нет — открытая. Так контур, нарисованный кусками (кривые Безье с
отрезками у «Безье»-деталей), становится одним контуром: одна врезка вместо нескольких, отверстие видно как отверстие.
"""
import math, struct
from . import geom as G

PT = 0x00020010             # метка точки в записях Geometry2D
NODE_TOL = 0.01             # мм: концы ближе — один узел (как read_dxf.NODE_TOL)
CURVE_TOL = 0.01            # мм: отклонение ломаной от кривой Безье (как read_dxf.CURVE_TOL)
_FLAT = 0.0075              # рабочий допуск: отклонение кривой от хорды ≤ ¾ отклонения управляющих точек ≤ CURVE_TOL
_MAX_POINTS = 200000        # вершин одной кривой — больше: запись испорчена
_MAX_COORD = 1e9            # мм: дальше — числа испорчены
KNOWN = ("Line", "Circle", "LwPolyline", "Arc", "PolyBezier", "Text")


class ShapeFormatError(ValueError):
    """Запись фигуры не того вида, что выяснен по архиву (новая версия CypCut или порча)."""


def _al8(n):
    return (n + 7) & ~7


def _payload(gb, addr):
    cl = struct.unpack_from("<H", gb, addr + 18)[0]
    q = addr + 16 + _al8(4 + cl)
    nl = struct.unpack_from("<H", gb, q + 18)[0]
    return q + 16 + _al8(4 + nl)


def _subs(ob, pos):
    """Части записи объекта с позиции pos: {имя: (версия, данные)} — по их длинам, а не по смещениям одной версии
    (у CypCut 2023 часть Shape — версии 5, 11 слов; у нынешнего — 6, 13 слов: пакет читает только её). Между частями —
    слова-счётчики (подвод: 0 или 1 и часть LeadParam)."""
    out = {}
    end = len(ob)
    while pos + 4 <= end:
        m = struct.unpack_from("<I", ob, pos)[0]
        if m == 0xD0D0D0D0:
            break
        if m != 0xC1C1C1C1:
            pos += 4
            continue
        ver, L = struct.unpack_from("<II", ob, pos + 4)
        nl = struct.unpack_from("<H", ob, pos + 18)[0]
        name = ob[pos + 20:pos + 20 + nl].decode("latin-1")
        body = pos + 16 + _al8(4 + nl)
        if L < body - pos + 4 or pos + L > end or struct.unpack_from("<I", ob, pos + L - 4)[0] != 0xC0C0C0C0:
            raise ShapeFormatError("часть %s записи Shapes2D" % name)
        out.setdefault(name, (ver, ob[body:pos + L - 4]))
        pos += L
    return out


def _attrs(e, sb, h):
    """Признаки фигуры из Shapes2D: слой, общий рез, флаг, внешний, подвод (как spec_rebuild.read_shape у записей
    нынешней версии; старые — по частям: у Shape версии 5 общего реза и флага нет — 0)."""
    a = int(e.get("DataAddr"))
    L = struct.unpack_from("<I", sb, a + 8)[0]
    ob = sb[a:a + L]
    S = _subs(ob, 16 + _al8(4 + struct.unpack_from("<H", ob, 18)[0]))
    if "Object" not in S or "Shape" not in S or "Curve" not in S:
        raise ShapeFormatError("в записи Shapes2D нет %s" % ", ".join(k for k in ("Object", "Shape", "Curve") if k not in S))
    if struct.unpack_from("<I", S["Object"][1], 0)[0] != h:
        raise ShapeFormatError("хэндл в Shapes2D не тот")
    sv, sw = S["Shape"]
    w = struct.unpack_from("<%dI" % (len(sw) // 4), sw)
    new = sv >= 6 and len(w) >= 9
    lead = S["LeadParam"][1] if "LeadParam" in S else None
    return dict(layer=w[0], coedge=w[5] if new else 0, flag64=w[8] if new else 0,
                outer=struct.unpack_from("<I", S["Curve"][1], 0)[0], lead=lead)


def _read_basic(e, gb, sb):
    """Line, Circle, LwPolyline: геометрия — как spec_rebuild.read_shape, признаки — _attrs. Пакет читает признаки по
    смещениям записи нынешней версии: на записях CypCut 2023 (Shape версии 5) падает — 6 программ архива «повреждены»,
    а у записей с частью Shape длиннее обычной (96 байт вместо 88; 9548 фигур архива) молча теряет подвод и берёт
    признак «внешний» не из того слова. На прочих 821 633 фигурах архива результат тот же, что у пакета (проверено)."""
    k, h = e.tag, int(e.get("Handle"))
    p = _payload(gb, int(e.get("GeoAddr")))
    s = dict(handle=h, kind=k, layer_name=e.get("LayerName"))
    if k == "Line":
        v = struct.unpack_from("<I2dI2d", gb, p)
        s.update(p1=(v[1], v[2]), p2=(v[4], v[5]))
    elif k == "Circle":
        v = struct.unpack_from("<I3dId", gb, p)
        s.update(c=(v[1], v[2]), r=v[3], a0=v[5])
    else:
        sp, fl, n = struct.unpack_from("<dII", gb, p)
        if n > _MAX_POINTS:
            raise ShapeFormatError("полилиния: %d вершин" % n)
        s.update(sp=sp, flag=fl, verts=[struct.unpack_from("<3d", gb, p + 16 + 32 * i + 4) for i in range(n)])
    s.update(_attrs(e, sb, h))
    return s


def _ok(*v):
    return all(abs(x) <= _MAX_COORD for x in v)        # NaN — ложь


def arc_shape(base, c, r, ccw, a0, sweep):
    """Дуга → открытая LwPolyline с bulge (≤ полуоборота на участок), полный оборот — Circle; нулевая — None."""
    s = sweep if ccw else -sweep
    if r * abs(s) < 1e-6:
        return None
    if abs(s) >= 2 * math.pi - 1e-9:
        return dict(base, kind="Circle", c=c, r=r, a0=a0 % (2 * math.pi))
    P = lambda a: (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
    if abs(s) <= math.pi:
        V = [P(a0) + (math.tan(s / 4),), P(a0 + s) + (0.0,)]
    else:
        b = math.tan(s / 8)
        V = [P(a0) + (b,), P(a0 + s / 2) + (b,), P(a0 + s) + (0.0,)]
    return dict(base, kind="LwPolyline", verts=V, flag=0, sp=0.0)


def _read_arc(gb, p):
    t, cx, cy, r, u, a0, sw = struct.unpack_from("<I3dI2d", gb, p)
    if t != PT or u not in (0, 1) or not _ok(cx, cy, r, a0, sw) or r < 0 or not (-1e-9 <= sw <= 2 * math.pi + 1e-6):
        raise ShapeFormatError("дуга: метка %#x, направление %d, радиус %g, размах %g" % (t, u, r, sw))
    return (cx, cy), r, u == 0, a0, sw


def _read_bezier(gb, p, end):
    """→ (sp, замкнута, [[4 точки] …])."""
    sp, fl, z, n = struct.unpack_from("<dIII", gb, p)
    if z != 0 or not _ok(sp) or n > _MAX_POINTS or p + 20 + n * 88 + 4 > end:
        raise ShapeFormatError("кривая Безье: заголовок %d, участков %d" % (z, n))
    q = p + 20
    segs = []
    for i in range(n):
        k = struct.unpack_from("<I", gb, q)[0]
        if k != i + 1:
            raise ShapeFormatError("кривая Безье: участок %d под номером %d" % (i + 1, k))
        P = []
        for j in range(4):
            t, x, y = struct.unpack_from("<I2d", gb, q + 4 + 20 * j)
            if t != PT or not _ok(x, y):
                raise ShapeFormatError("кривая Безье: точка %d участка %d" % (j, i + 1))
            P.append((x, y))
        if struct.unpack_from("<I", gb, q + 84)[0] != 0:
            raise ShapeFormatError("кривая Безье: хвост участка %d" % (i + 1))
        segs.append(P)
        q += 88
    return sp, bool(fl & 1), segs


def _split(P, t):
    """Кубическая кривая → две по параметру t (де Кастельжо)."""
    L = lambda a, b: (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    a, b, c = L(P[0], P[1]), L(P[1], P[2]), L(P[2], P[3])
    d, e = L(a, b), L(b, c)
    f = L(d, e)
    return [P[0], a, d, f], [f, e, c, P[3]]


def _dev(P):
    """Наибольшее удаление управляющих точек от хорды P0→P3 (кривая — в их выпуклой оболочке, её отклонение ≤ ¾ этого)."""
    return max(G.seg_point_dist(P[1], P[0], P[3]), G.seg_point_dist(P[2], P[0], P[3]))


def flatten(P, out, depth=0):
    """Кубическая кривая → вершины ломаной (без первой точки) в out; отклонение ≤ CURVE_TOL."""
    if _dev(P) <= _FLAT or depth >= 40:
        if math.dist(P[0], P[3]) > 1e-9 or not out:
            out.append(P[3])
        if len(out) > _MAX_POINTS:
            raise ShapeFormatError("кривая Безье: больше %d вершин при допуске %g мм" % (_MAX_POINTS, CURVE_TOL))
        return
    a, b = _split(P, 0.5)
    flatten(a, out, depth + 1)
    flatten(b, out, depth + 1)


def bezier_shapes(base, sp, closed, segs):
    """Кривая Безье → [LwPolyline] (разрыв между участками — отдельные куски). У замкнутой первая вершина — точка
    начала sp (участок с нуля + доля)."""
    segs = list(segs)
    if closed and 0 < sp < len(segs):                  # точка начала — первой: участок k с долей t
        k, t = int(math.floor(sp)), sp - math.floor(sp)
        if t > 1e-9:
            a, b = _split(segs[k], t)
            segs[k:k + 1] = [a, b]
            k += 1
        segs = segs[k:] + segs[:k]
    segs = [S for S in segs if max(math.dist(S[0], q) for q in S[1:]) > 1e-9]     # участок-точка
    if not segs:
        return []
    runs, cur = [], [segs[0]]
    for S in segs[1:]:
        if math.dist(cur[-1][3], S[0]) > NODE_TOL:
            runs.append(cur)
            cur = [S]
        else:
            cur.append(S)
    runs.append(cur)
    if closed and len(runs) > 1 and math.dist(runs[-1][-1][3], runs[0][0][0]) <= NODE_TOL:
        runs[0] = runs.pop() + runs[0]                  # разрыв не на стыке начала: конец кривой переходит в начало
    out = []
    for R in runs:
        pts = [R[0][0]]
        for S in R:
            flatten(S, pts)
        V = [(x, y, 0.0) for x, y in pts]
        shut = closed and len(runs) == 1
        if shut and len(V) > 1 and math.dist(V[0][:2], V[-1][:2]) <= NODE_TOL:
            V = V[:-1]
        if len(V) < 2 or (shut and len(V) < 3):
            continue
        if shut:
            out.append(dict(base, kind="LwPolyline", verts=V, sp=0.0, flag=1 | (2 if G.poly_area(V) < 0 else 0)))
        else:
            out.append(dict(base, kind="LwPolyline", verts=V, sp=0.0, flag=0))
    return out


def read_shapes(content, gb, sb):
    """Shapes2D/content.xml (корень) → {хэндл: [фигуры]} — список: кривая с разрывом даёт несколько кусков, нулевая
    дуга — пустой; пометки Text и «?» — одной фигурой. Нечитаемая запись не роняет программу: пометка «?» с причиной
    (ошибка — только если фигура в детали)."""
    out = {}
    for e in content:
        if e.tag == "MD5":
            continue
        try:
            h = int(e.get("Handle"))
        except (TypeError, ValueError):
            continue
        k = e.tag
        try:
            if k in ("Line", "Circle", "LwPolyline"):
                out[h] = [_read_basic(e, gb, sb)]
            elif k == "Text":
                out[h] = [dict(handle=h, kind="Text", text=e.get("Text") or "", layer=int(e.get("ChannelPort") or 0))]
            elif k in ("Arc", "PolyBezier"):
                a = int(e.get("GeoAddr"))
                p = _payload(gb, a)
                base = dict(handle=h, layer_name=e.get("LayerName"), **_attrs(e, sb, h))
                if k == "Arc":
                    s = arc_shape(base, *_read_arc(gb, p))
                    out[h] = [s] if s is not None else []
                else:
                    end = a + struct.unpack_from("<I", gb, a + 8)[0]
                    sp, closed, segs = _read_bezier(gb, p, end)
                    out[h] = bezier_shapes(dict(base, bezier=True), sp, closed, segs)
                    if not out[h]:
                        out[h] = [dict(handle=h, kind="?", cls=k, why="кривая Безье без длины")]
            else:
                out[h] = [dict(handle=h, kind="?", cls=k, why="класс фигуры %s программа раскроя не читает" % k)]
        except (struct.error, ShapeFormatError, TypeError, ValueError, KeyError, AssertionError, IndexError) as x:
            out[h] = [dict(handle=h, kind="?", cls=k, why="запись не читается%s" % (
                ": %s" % x if isinstance(x, ShapeFormatError) else ""))]
    return out


# ================================================================================================== склейка кусков
def _ends(s):
    return G.ends(s)


def verts_of(s):
    """Вершины открытого куска [(x, y, bulge)] (отрезок — две)."""
    if s["kind"] == "Line":
        return [(s["p1"][0], s["p1"][1], 0.0), (s["p2"][0], s["p2"][1], 0.0)]
    return [tuple(v) for v in s["verts"]]


def glue(shapes, tol=NODE_TOL):
    """Склеить открытые куски, концы которых сходятся: → (фигуры, [(хэндлы кусков, склеенная фигура)]). Куски — Line
    и открытые LwPolyline одного слоя, не общего реза (coedge — линии общего реза CypCut, их не трогаем); узел — концы
    ближе tol; через узел с двумя концами цепочка идёт дальше, узел с одним или тремя и больше — её конец. Цепочка из
    двух и больше кусков — одна фигура (место — место первого куска; признаки — его); замкнулась — флаг 1 и бит 2 по
    часовой, как у heal_outer. Куска самого с собой (концы совпали) склейка не касается — это heal_outer."""
    idx = [i for i, s in enumerate(shapes) if s["kind"] in ("Line", "LwPolyline") and not G.is_closed(s)
           and not s.get("coedge") and G.length(s) > 1e-9]
    if len(idx) < 2:
        return list(shapes), []
    # узлы: концы ближе tol (сетка tol, соседние клетки), объединение
    E = []
    for i in idx:
        a, z = _ends(shapes[i])
        E += [(i, 0, a), (i, 1, z)]
    par = list(range(len(E)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    cell = {}
    for k, (i, side, p) in enumerate(E):
        gx, gy = int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in cell.get((gx + dx, gy + dy), ()):
                    j = E[m]
                    if shapes[j[0]]["layer"] == shapes[i]["layer"] and math.dist(j[2], p) <= tol:
                        par[find(m)] = find(k)
        cell.setdefault((gx, gy), []).append(k)
    node = [find(k) for k in range(len(E))]
    at = {}
    for k, n in enumerate(node):
        at.setdefault(n, []).append(k)
    end_of = {(E[k][0], E[k][1]): k for k in range(len(E))}
    used = set()
    out_groups = []

    def walk(i, side_in):
        """От куска i, вошли концом side_in: [(кусок, развернуть)] до конца цепочки или замыкания."""
        chain = []
        cur, enter = i, side_in
        while True:
            used.add(cur)
            chain.append((cur, enter == 1))
            k_out = end_of[(cur, 1 - enter)]
            nb = [m for m in at[node[k_out]] if m != k_out]
            if len(nb) != 1:
                return chain, False
            j, s = E[nb[0]][0], E[nb[0]][1]
            if j == i and s == side_in:
                return chain, True
            if j in used:
                return chain, False
            cur, enter = j, s
    for i in idx:                                       # цепочки от концов (узел не из двух концов)
        if i in used:
            continue
        for side in (0, 1):
            k = end_of[(i, side)]
            if len(at[node[k]]) != 2:
                chain, shut = walk(i, side)
                if len(chain) >= 2:
                    out_groups.append((chain, shut))
                break
    for i in idx:                                       # остались кольца: все узлы по два конца
        if i in used:
            continue
        chain, shut = walk(i, 0)
        if len(chain) >= 2:
            out_groups.append((chain, shut))
    if not out_groups:
        return list(shapes), []
    repl, drop, made = {}, set(), []
    for chain, shut in out_groups:
        V = []
        for i, rev in chain:
            s = G.reverse(shapes[i]) if rev else shapes[i]
            v = verts_of(s)
            if V:
                V[-1] = (V[-1][0], V[-1][1], v[0][2])       # стык: точка — конец прежнего куска, bulge — нового
                V += v[1:]
            else:
                V = list(v)
        first = shapes[chain[0][0]]
        base = {k: first[k] for k in ("handle", "layer_name", "layer", "flag64", "lead") if k in first}
        if shut:
            V = V[:-1]
            g = dict(base, kind="LwPolyline", verts=V, sp=0.0, coedge=0, outer=0,
                     flag=1 | (2 if G.poly_area(V) < 0 else 0))
            if len(V) < 3 or abs(G.poly_area(V)) < 1e-9:
                continue                                # кольцо без площади (туда-обратно) — не склеиваем
        else:
            g = dict(base, kind="LwPolyline", verts=V, sp=0.0, coedge=0, outer=0, flag=0)
        repl[chain[0][0]] = g
        drop.update(i for i, _ in chain[1:])
        made.append(([shapes[i].get("handle") for i, _ in chain], g))
    return [repl.get(i, s) for i, s in enumerate(shapes) if i not in drop], made
