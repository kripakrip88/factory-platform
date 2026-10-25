"""Прямоугольная изометрия (ГОСТ 2.317) для сборочных листов: векторная отрисовка алгоритмом художника.

Тела задаются в мм в системе изделия: X — вправо по ширине пластины, Y — вверх, Z — от лицевой грани пластины
в сторону анкеров. Взгляд — со стороны анкеров, сверху-справа (e = (1, 1, 1)): видны тыльная сторона пластины,
анкеры, шайбы и гнутые стержни. Грани режутся на мелкие куски, чтобы сортировка по глубине была правильной;
чёрным обводятся только настоящие рёбра тел (края граней коробок, силуэты и торцы стержней).
"""
import math

import gost_draw as g

E = (1 / math.sqrt(3),) * 3
R = (1 / math.sqrt(2), 0.0, -1 / math.sqrt(2))
U = (-1 / math.sqrt(6), 2 / math.sqrt(6), -1 / math.sqrt(6))
LIGHT = (0.35, 0.85, 0.55)
EDGE = 0.3


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def shade(n):
    k = max(0.0, dot(norm(n), norm(LIGHT)))
    v = 0.62 + 0.33 * k
    return (v, v, v)


class Scene:
    def __init__(self):
        self.faces = []        # (depth, poly3d, fill, edges[(p, q)])

    def quad(self, p0, du, dv, n, step=10.0, edges=(True, True, True, True), fill=None):
        """Прямоугольная грань p0 + s*du + t*dv, нормаль n; режется на куски ≤ step мм."""
        if dot(n, E) <= 1e-9:
            return
        lu, lv = math.sqrt(dot(du, du)), math.sqrt(dot(dv, dv))
        nu, nv = max(1, math.ceil(lu / step)), max(1, math.ceil(lv / step))
        col = fill or shade(n)
        for i in range(nu):
            for j in range(nv):
                a = add(add(p0, du, i / nu), dv, j / nv)
                b = add(a, du, 1 / nu)
                c = add(b, dv, 1 / nv)
                d = add(a, dv, 1 / nv)
                ed = []
                if j == 0 and edges[0]:
                    ed.append((a, b))
                if i == nu - 1 and edges[1]:
                    ed.append((b, c))
                if j == nv - 1 and edges[2]:
                    ed.append((c, d))
                if i == 0 and edges[3]:
                    ed.append((d, a))
                cen = add(add(a, du, 0.5 / nu), dv, 0.5 / nv)
                self.faces.append((dot(cen, E), [a, b, c, d], col, ed))

    def box(self, x0, y0, z0, x1, y1, z1, step=10.0):
        X, Y, Z = (x1 - x0, 0, 0), (0, y1 - y0, 0), (0, 0, z1 - z0)
        o = (x0, y0, z0)
        self.quad(o, Y, X, (0, 0, -1), step)                         # z0
        self.quad(add(o, Z), X, Y, (0, 0, 1), step)                  # z1
        self.quad(o, X, Z, (0, -1, 0), step)                         # y0
        self.quad(add(o, Y), Z, X, (0, 1, 0), step)                  # y1
        self.quad(o, Z, Y, (-1, 0, 0), step)                         # x0
        self.quad(add(o, X), Y, Z, (1, 0, 0), step)                  # x1

    def rod(self, a, b, r, sides=12, step=8.0, cap_a=True, cap_b=True):
        """Цилиндр от a до b радиуса r."""
        ax = sub(b, a)
        L = math.sqrt(dot(ax, ax))
        if L < 1e-6:
            return
        w = norm(ax)
        t = norm(cross(w, (0, 1, 0) if abs(w[1]) < 0.9 else (1, 0, 0)))
        s = cross(w, t)
        ang = [2 * math.pi * k / sides for k in range(sides)]
        ring = [add(add((0, 0, 0), t, r * math.cos(q)), s, r * math.sin(q)) for q in ang]
        nrm = [add(add((0, 0, 0), t, math.cos(q + math.pi / sides)), s, math.sin(q + math.pi / sides)) for q in ang]
        vis = [dot(n, E) > 0 for n in nrm]
        nseg = max(1, math.ceil(L / step))
        for k in range(sides):
            if not vis[k]:
                continue
            k2 = (k + 1) % sides
            sil0 = not vis[(k - 1) % sides]
            sil1 = not vis[k2]
            for j in range(nseg):
                p = add(a, ax, j / nseg)
                q = add(a, ax, (j + 1) / nseg)
                poly = [add(p, ring[k]), add(q, ring[k]), add(q, ring[k2]), add(p, ring[k2])]
                ed = []
                if sil0:
                    ed.append((poly[0], poly[1]))
                if sil1:
                    ed.append((poly[2], poly[3]))
                cen = add(add(p, ax, 0.5 / nseg), nrm[k], r)
                self.faces.append((dot(cen, E), poly, shade(nrm[k]), ed))
        for c, n, ok in ((a, tuple(-x for x in w), cap_a), (b, w, cap_b)):
            if ok and dot(n, E) > 0:
                poly = [add(c, v) for v in ring]
                self.faces.append((dot(c, E) + 0.01, poly, shade(n), list(zip(poly, poly[1:] + poly[:1]))))

    def disk(self, c, n, r, fill=(0.25, 0.25, 0.25), sides=24):
        """Тёмный круг на грани (зенковка), чуть ближе к зрителю."""
        if dot(n, E) <= 0:
            return
        n = norm(n)
        t = norm(cross(n, (0, 1, 0) if abs(n[1]) < 0.9 else (1, 0, 0)))
        s = cross(n, t)
        poly = [add(add(c, t, r * math.cos(2 * math.pi * k / sides)), s, r * math.sin(2 * math.pi * k / sides))
                for k in range(sides)]
        # «наклейка» на грань: глубже всех кусков грани под ней не уйдёт
        self.faces.append((dot(c, E) + 2 * r + 20, poly, fill, list(zip(poly, poly[1:] + poly[:1]))))

    # ------------------------------------------------------------------ вывод
    @staticmethod
    def proj(p):
        return dot(p, R), dot(p, U)

    def bbox(self):
        pts = [self.proj(p) for _, poly, _, _ in self.faces for p in poly]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def render(self, box, balloons=()):
        """Вписать в box=(x0, y0, x1, y1) мм листа; balloons=[(номер, точка3d)] — выноски позиций справа/слева."""
        bx0, by0, bx1, by1 = self.bbox()
        x0, y0, x1, y1 = box
        k = min((x1 - x0 - 30) / (bx1 - bx0), (y1 - y0) / (by1 - by0))
        ox = x0 + (x1 - x0 - 30 - (bx1 - bx0) * k) / 2 - bx0 * k
        oy = y0 + (y1 - y0 - (by1 - by0) * k) / 2 + by1 * k
        to = lambda p: (ox + self.proj(p)[0] * k, oy - self.proj(p)[1] * k)
        sh = g.page.new_shape()                   # одна фигура, порядок путей = порядок рисования
        for _, poly, col, ed in sorted(self.faces, key=lambda f: f[0]):
            sh.draw_polyline([g.P(*to(p)) for p in poly])
            sh.finish(width=0.3, color=col, fill=col, closePath=True)
            for p, q in ed:
                sh.draw_line(g.P(*to(p)), g.P(*to(q)))
            if ed:
                sh.finish(width=EDGE * g.K, color=g.BLACK, closePath=False)
        sh.commit()
        # выноски: номера столбиком справа от изображения, по высоте точки
        pts = sorted(((n, to(p)) for n, p in balloons), key=lambda v: v[1][1])
        xr = ox + bx1 * k + 14
        ylast = -1e9
        for n, (px, py) in pts:
            yy = max(py, ylast + 9)
            ylast = yy
            g.circle(px, py, 0.6, fill=g.BLACK)
            g.line(px, py, xr - 4, yy, g.THIN)
            g.circle(xr, yy, 4, g.THIN)
            g.text(xr, yy + 1.8, str(n), h=5, align="c")
        return k
