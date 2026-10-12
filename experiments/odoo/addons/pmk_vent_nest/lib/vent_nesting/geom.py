# -*- coding: utf-8 -*-
"""Геометрия стенда: полилинии с дугами (bulge), окружности, жёсткий поворот+сдвиг, точные расстояния.

Контур детали: outer = [(x, y, bulge)] (замкнутый), inner = [[(x, y, bulge)]], circles = [(x, y, r)].
Дуги дискретизуются с отклонением хорды ≤ CHORD_TOL мм — расстояния верны до этой точности.
"""
import math
import numpy as np

CHORD_TOL = 0.005


def arc_points(a, c, bulge, tol=CHORD_TOL):
    """Точки дуги от a к c (без a, с c)."""
    th = 4 * math.atan(bulge)
    ch = math.dist(a, c)
    if ch < 1e-12 or abs(bulge) < 1e-12:
        return [c]
    r = ch / (2 * math.sin(abs(th) / 2))
    n = max(1, int(math.ceil(abs(th) / (2 * math.acos(max(-1.0, min(1.0, 1 - tol / r))))))) if r > tol else 1
    mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
    ux, uy = (c[0] - a[0]) / ch, (c[1] - a[1]) / ch
    d = r * math.cos(th / 2) * (1 if bulge > 0 else -1)
    cx, cy = mx - uy * d, my + ux * d
    a0 = math.atan2(a[1] - cy, a[0] - cx)
    pts = [(cx + r * math.cos(a0 + th * k / n), cy + r * math.sin(a0 + th * k / n)) for k in range(1, n)]
    return pts + [c]


def poly_points(poly, tol=CHORD_TOL):
    """Замкнутая полилиния с bulge → многоугольник (без повтора первой точки)."""
    out = []
    n = len(poly)
    for i in range(n):
        a = poly[i][:2]; c = poly[(i + 1) % n][:2]; b = poly[i][2]
        out.append(tuple(a))
        if abs(b) > 1e-12:
            out += arc_points(a, c, b, tol)[:-1]
    return out


def circle_points(x, y, r, tol=CHORD_TOL):
    n = max(12, int(math.ceil(math.pi / math.acos(max(-1.0, 1 - tol / r))))) if r > tol else 12
    return [(x + r * math.cos(2 * math.pi * k / n), y + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def area(pts):
    p = np.asarray(pts)
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def poly_len(poly):
    t = 0.0
    n = len(poly)
    for i in range(n):
        a = poly[i][:2]; c = poly[(i + 1) % n][:2]; b = poly[i][2]
        ch = math.dist(a, c)
        if abs(b) > 1e-12 and ch > 1e-12:
            th = abs(4 * math.atan(b)); t += ch / (2 * math.sin(th / 2)) * th
        else:
            t += ch
    return t


def transform_pts(pts, theta_deg, tx, ty):
    th = math.radians(theta_deg)
    c, s = math.cos(th), math.sin(th)
    p = np.asarray(pts, dtype=float)
    return np.column_stack((p[:, 0] * c - p[:, 1] * s + tx, p[:, 0] * s + p[:, 1] * c + ty))


def seg_dist_min(A, B):
    """Минимальное расстояние между ломаными замкнутыми контурами A и B (массивы N×2, M×2), точно для отрезков.
    Контуры пересекаются (рёбра режут друг друга) → −1: это наложение при любом зазоре, даже нулевом.
    Касание (общая кромка при зазоре 0) — 0."""
    a0 = A; a1 = np.roll(A, -1, axis=0)
    b0 = B; b1 = np.roll(B, -1, axis=0)

    def pt_seg(P, S0, S1):
        d = S1 - S0
        L2 = (d * d).sum(1); L2[L2 == 0] = 1e-30
        t = np.clip(((P[:, None, :] - S0[None]) * d[None]).sum(2) / L2[None], 0, 1)
        q = S0[None] + t[..., None] * d[None]
        return np.sqrt(((P[:, None, :] - q) ** 2).sum(2)).min()
    # пересечения отрезков → 0
    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    o1 = orient(a0[:, None], a1[:, None], b0[None]); o2 = orient(a0[:, None], a1[:, None], b1[None])
    o3 = orient(b0[None], b1[None], a0[:, None]); o4 = orient(b0[None], b1[None], a1[:, None])
    if np.any((o1 * o2 < 0) & (o3 * o4 < 0)):
        return -1.0
    return float(min(pt_seg(A, b0, b1), pt_seg(B, a0, a1)))


def point_in_poly(x, y, P):
    xs, ys = P[:, 0], P[:, 1]
    x2, y2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xin = xs + (y - ys) * (x2 - xs) / (y2 - ys)
    return bool(np.sum(cond & (x < xin)) % 2)
