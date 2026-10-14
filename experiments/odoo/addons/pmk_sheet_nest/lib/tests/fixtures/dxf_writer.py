# -*- coding: utf-8 -*-
"""Писатель DXF-текста для тестов read_dxf: ровно столько, сколько нужно фикстурам (не для производства).

    doc = DxfDoc(version="AC1015", insunits=4, codepage="ANSI_1251")
    doc.layer("Гравировка")
    doc.entities.line((0, 0), (100, 0))
    blk = doc.block("HOLE", base=(0, 0)); blk.circle((0, 0), 3)
    doc.entities.insert("HOLE", (50, 50), sx=2, rot=30)
    data = doc.dxf_bytes(encoding="cp1251", crlf=True, pad=True)

Коды групп можно писать с ведущими пробелами (pad=True, как AutoCAD: «  0», « 10») и концом строки CRLF.
"""
import math


def u_escape(s):
    """Не-ASCII символы → \\U+XXXX (так AutoCAD пишет имена в старых DXF)."""
    return "".join(c if ord(c) < 128 else "\\U+%04X" % ord(c) for c in s)


def _v(x):
    if isinstance(x, float):
        return repr(x)
    return str(x)


class Ents(object):
    """Список сущностей (секция ENTITIES или содержимое блока). Каждая сущность — список (код, значение)."""

    def __init__(self):
        self.items = []

    def _add(self, typ, tags, layer="0", ltype=None, invisible=False, paper=False, extrusion=None):
        t = [(0, typ), (8, layer)]
        if ltype is not None:
            t.append((6, ltype))
        if invisible:
            t.append((60, 1))
        if paper:
            t.append((67, 1))
        t += list(tags)
        if extrusion is not None:
            t += [(210, float(extrusion[0])), (220, float(extrusion[1])), (230, float(extrusion[2]))]
        self.items.append(t)
        return self

    def raw(self, tags):
        self.items.append(list(tags))
        return self

    def line(self, p0, p1, layer="0", **kw):
        return self._add("LINE", [(10, float(p0[0])), (20, float(p0[1])), (30, 0.0),
                                  (11, float(p1[0])), (21, float(p1[1])), (31, 0.0)], layer, **kw)

    def circle(self, c, r, layer="0", **kw):
        return self._add("CIRCLE", [(10, float(c[0])), (20, float(c[1])), (30, 0.0), (40, float(r))], layer, **kw)

    def arc(self, c, r, a0, a1, layer="0", **kw):
        """Дуга против часовой от a0 до a1 (градусы), центр/углы — в OCS (при extrusion)."""
        return self._add("ARC", [(10, float(c[0])), (20, float(c[1])), (30, 0.0), (40, float(r)),
                                 (50, float(a0)), (51, float(a1))], layer, **kw)

    def point(self, p, layer="0", **kw):
        return self._add("POINT", [(10, float(p[0])), (20, float(p[1])), (30, 0.0)], layer, **kw)

    def lwpolyline(self, verts, closed=False, layer="0", width=None, elevation=None, **kw):
        """verts: [(x, y) | (x, y, bulge)]."""
        tags = [(90, len(verts)), (70, 1 if closed else 0)]
        if width is not None:
            tags.append((43, float(width)))
        if elevation is not None:
            tags.append((38, float(elevation)))
        for v in verts:
            tags += [(10, float(v[0])), (20, float(v[1]))]
            if len(v) > 2 and v[2]:
                tags.append((42, float(v[2])))
        return self._add("LWPOLYLINE", tags, layer, **kw)

    def polyline(self, verts, closed=False, layer="0", flags3d=False, **kw):
        """R12: POLYLINE + VERTEX… + SEQEND; verts: [(x, y) | (x, y, bulge)]."""
        fl = (1 if closed else 0) | (8 if flags3d else 0)
        self._add("POLYLINE", [(66, 1), (10, 0.0), (20, 0.0), (30, 0.0), (70, fl)], layer, **kw)
        for v in verts:
            t = [(0, "VERTEX"), (8, layer), (10, float(v[0])), (20, float(v[1])), (30, 0.0)]
            if len(v) > 2 and v[2]:
                t.append((42, float(v[2])))
            if flags3d:
                t.append((70, 32))
            self.items.append(t)
        self.items.append([(0, "SEQEND"), (8, layer)])
        return self

    def spline(self, ctrl, knots, degree=3, weights=None, fit=None, closed=False, periodic=False, tangents=None,
               layer="0", **kw):
        fl = 8 | (1 if closed else 0) | (2 if periodic else 0) | (4 if weights else 0)
        tags = [(70, fl), (71, degree), (72, len(knots)), (73, len(ctrl)), (74, len(fit or []))]
        if tangents:
            if tangents[0] is not None:
                tags += [(12, float(tangents[0][0])), (22, float(tangents[0][1])), (32, 0.0)]
            if tangents[1] is not None:
                tags += [(13, float(tangents[1][0])), (23, float(tangents[1][1])), (33, 0.0)]
        tags += [(40, float(k)) for k in knots]
        if weights:
            tags += [(41, float(w)) for w in weights]
        for p in ctrl:
            tags += [(10, float(p[0])), (20, float(p[1])), (30, 0.0)]
        for p in fit or []:
            tags += [(11, float(p[0])), (21, float(p[1])), (31, 0.0)]
        return self._add("SPLINE", tags, layer, **kw)

    def ellipse(self, c, major, ratio, start=0.0, end=2 * math.pi, layer="0", **kw):
        return self._add("ELLIPSE", [(10, float(c[0])), (20, float(c[1])), (30, 0.0),
                                     (11, float(major[0])), (21, float(major[1])), (31, 0.0),
                                     (40, float(ratio)), (41, float(start)), (42, float(end))], layer, **kw)

    def text(self, at, s, layer="0", **kw):
        return self._add("TEXT", [(10, float(at[0])), (20, float(at[1])), (30, 0.0), (40, 5.0), (1, s)], layer, **kw)

    def mtext(self, at, s, layer="0", **kw):
        return self._add("MTEXT", [(10, float(at[0])), (20, float(at[1])), (30, 0.0), (40, 5.0), (1, s)], layer, **kw)

    def dimension(self, block, p0=(0, 0), p1=(10, 0), layer="0", **kw):
        return self._add("DIMENSION", [(2, block), (10, float(p0[0])), (20, float(p0[1])), (30, 0.0),
                                       (13, float(p0[0])), (23, float(p0[1])), (33, 0.0),
                                       (14, float(p1[0])), (24, float(p1[1])), (34, 0.0), (70, 32)], layer, **kw)

    def hatch(self, layer="0", **kw):
        return self._add("HATCH", [(10, 0.0), (20, 0.0), (30, 0.0), (2, "SOLID"), (70, 1), (71, 0), (91, 0)],
                         layer, **kw)

    def insert(self, name, at=(0, 0), sx=1.0, sy=1.0, rot=0.0, layer="0", cols=1, rows=1, col_sp=0.0, row_sp=0.0,
               attribs=0, **kw):
        tags = [(2, name), (10, float(at[0])), (20, float(at[1])), (30, 0.0), (41, float(sx)), (42, float(sy)),
                (43, 1.0), (50, float(rot))]
        if cols != 1 or rows != 1:
            tags += [(70, cols), (71, rows), (44, float(col_sp)), (45, float(row_sp))]
        if attribs:
            tags.insert(0, (66, 1))
        self._add("INSERT", tags, layer, **kw)
        for k in range(attribs):
            self.items.append([(0, "ATTRIB"), (8, layer), (10, 0.0), (20, 0.0), (30, 0.0), (40, 3.0),
                               (1, "A%d" % k), (2, "TAG%d" % k), (70, 0)])
        if attribs:
            self.items.append([(0, "SEQEND"), (8, layer)])
        return self


class DxfDoc(object):
    def __init__(self, version="AC1015", insunits=4, codepage=None, header=True):
        self.version, self.insunits, self.codepage, self.header = version, insunits, codepage, header
        self.entities = Ents()
        self.blocks = []            # (name, base, flags, Ents)
        self.layers = []            # (name, flags, color, ltype)
        self.ltypes = []            # (name, pattern)

    def layer(self, name, flags=0, color=7, ltype="CONTINUOUS"):
        self.layers.append((name, flags, color, ltype))
        return self

    def ltype(self, name, pattern=()):
        self.ltypes.append((name, list(pattern)))
        return self

    def block(self, name, base=(0.0, 0.0), flags=0):
        e = Ents()
        self.blocks.append((name, base, flags, e))
        return e

    def tags(self):
        T = []
        if self.header:
            T += [(0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, self.version)]
            if self.codepage is not None:
                T += [(9, "$DWGCODEPAGE"), (3, self.codepage)]
            if self.insunits is not None:
                T += [(9, "$INSUNITS"), (70, self.insunits)]
            T += [(0, "ENDSEC")]
        if self.layers or self.ltypes:
            T += [(0, "SECTION"), (2, "TABLES")]
            if self.ltypes:
                T += [(0, "TABLE"), (2, "LTYPE"), (70, len(self.ltypes))]
                for nm, pat in self.ltypes:
                    T += [(0, "LTYPE"), (2, nm), (70, 0), (3, ""), (72, 65), (73, len(pat)),
                          (40, float(sum(abs(x) for x in pat)))]
                    T += [(49, float(x)) for x in pat]
                T += [(0, "ENDTAB")]
            if self.layers:
                T += [(0, "TABLE"), (2, "LAYER"), (70, len(self.layers))]
                for nm, fl, col, lt in self.layers:
                    T += [(0, "LAYER"), (2, nm), (70, fl), (62, col), (6, lt)]
                T += [(0, "ENDTAB")]
            T += [(0, "ENDSEC")]
        if self.blocks:
            T += [(0, "SECTION"), (2, "BLOCKS")]
            for nm, base, fl, ents in self.blocks:
                T += [(0, "BLOCK"), (8, "0"), (2, nm), (70, fl), (10, float(base[0])), (20, float(base[1])),
                      (30, 0.0), (3, nm)]
                for it in ents.items:
                    T += it
                T += [(0, "ENDBLK"), (8, "0")]
            T += [(0, "ENDSEC")]
        T += [(0, "SECTION"), (2, "ENTITIES")]
        for it in self.entities.items:
            T += it
        T += [(0, "ENDSEC"), (0, "EOF")]
        return T

    def dxf_text(self, crlf=False, pad=False):
        nl = "\r\n" if crlf else "\n"
        out = []
        for c, v in self.tags():
            out.append(("%3d" % c) if pad else str(c))
            out.append(_v(v))
        return nl.join(out) + nl

    def dxf_bytes(self, encoding="utf-8", crlf=False, pad=False):
        return self.dxf_text(crlf, pad).encode(encoding)
