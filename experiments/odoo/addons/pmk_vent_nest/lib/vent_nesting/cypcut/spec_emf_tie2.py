# -*- coding: utf-8 -*-
"""spec_emf_tie2 — гипотеза: опорные точки ЛИСТА (первая POLYBEZIER16) CypCut считает между уже
округлёнными углами листа (1/3 и 2/3 от целых пикселей), а контуры деталей — как в xml_emf.
usage: python3 -I spec_emf_tie2.py samples/*.lxds"""
import sys, os, struct, zipfile
import xml.etree.ElementTree as ET
from . import xml_emf as XE
def plate_records(W, H):
    M = XE.Mapper(W, H)
    corners = [(XE.rnd(x), XE.rnd(y)) for x, y in (M(0, 0), M(W, 0), M(W, H), M(0, H))]
    pts = [corners[0]]
    for i in range(4):
        a, c = corners[i], corners[(i + 1) % 4]
        pts += [(a[0] + (c[0] - a[0]) / 3, a[1] + (c[1] - a[1]) / 3), (a[0] + 2 * (c[0] - a[0]) / 3, a[1] + 2 * (c[1] - a[1]) / 3), c]
    return XE.polybezier16([(XE.rnd(x), XE.rnd(y)) for x, y in pts])


def generate2(W, H, shapes, **kw):
    b = bytearray(XE.generate(W, H, shapes, **kw))
    old = XE.shape_records(dict(kind='LwPolyline', pts=[(0, 0), (W, 0), (W, H), (0, H)], bulge=[0] * 4, closed=True), XE.Mapper(W, H))[0]
    new = plate_records(W, H)
    i = bytes(b).find(old)
    assert i > 0 and len(old) == len(new)
    b[i:i + len(new)] = new
    return bytes(b)


if __name__ == '__main__':
    tot = ident = nd_all = 0
    for path in sys.argv[1:]:
        z = zipfile.ZipFile(path)
        for r in ET.fromstring(z.read('Nest2D/Results/content.xml')):
            idx = r.get('Index')
            real = z.read('Nest2D/Results/%s/thumbnail.emf' % idx)
            hr = XE.header(real)
            W, H, plate, shapes = XE.result_shapes(z, idx)
            tail = real[124 + 12 + 28 + 14:124 + 12 + 28 + 64]
            gen = generate2(W, H, shapes, device=tuple(hr['device']), mm=tuple(hr['mm']), plate=plate, face_tail=tail)
            nd = sum(1 for a, b in zip(real, gen) if a != b) + abs(len(real) - len(gen))
            tot += 1; ident += nd == 0; nd_all += nd
            print('  %-15s R%-3s W=%g H=%g differing bytes %d' % (os.path.basename(path), idx, W, H, nd))
    print('plate-from-rounded-corners: thumbnails byte-identical %d/%d, differing bytes total %d' % (ident, tot, nd_all))
