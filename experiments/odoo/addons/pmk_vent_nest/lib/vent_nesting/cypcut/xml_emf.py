# -*- coding: utf-8 -*-
"""thumbnail.emf of a nest result: parse, compare, and GENERATE in CypCut's style.

    python3 -I xml_emf.py compare  FILE.lxds ...       # regenerate every result thumbnail from geometry, compare
    python3 -I xml_emf.py dump     FILE.lxds N          # header + record list of Nest2D/Results/N/thumbnail.emf
    python3 -I xml_emf.py demo     OUT.emf              # write a small synthetic thumbnail (polylines + circle)

What CypCut writes (all 15 thumbnails of the 5 samples):
  EMF 1.0 ('\\x20EMF', ver 0x10000), header 108 bytes (no description, no palette, no pixel format,
  szlMicrometers present). Reference box 320x320 device px: rclFrame = (0,0, round(32000*mm/px)) per axis
  using the SAVING PC's screen (szlDevice px, szlMillimeters) -- e.g. 2560x1440/600x330 -> 7500x7333,
  1920x1080/598x336 -> 9967x9956. rclBounds = bbox of drawn points (= the plate rectangle).
  Mapping: s = 318/max(W,H); px = 160 + (x - W/2)*s; py = 160 - (y - H/2)*s (y up -> down), rounded.
  Fixed preamble (identical in all 15): MOVETOEX(0,0); EXTCREATEFONTINDIRECTW #1 Tahoma -11 (LogFontExDv,
  368 B; tail of lfFaceName after 'Tahoma\\0' holds UNINITIALISED memory -> not reproducible); SELECT #1;
  SETTEXTCOLOR 0; CREATEPEN #2 solid 1px black; SELECT #2; SETROP2 R2_COPYPEN; CREATEBRUSHINDIRECT #3 solid
  white; SELECT #3; SETBKCOLOR white; SETBKMODE OPAQUE; MOVETOEX(0,0); CREATEPEN #4 PS_DASHDOT 1px
  RGB(0,128,0); SELECT #4; SETROP2; SELECT NULL_BRUSH; SETBKCOLOR 0xFF000000; SETBKMODE TRANSPARENT;
  SELECT #1; SETTEXTCOLOR 0; then the plate as POLYBEZIER16; SELECT BLACK_PEN; DELETEOBJECT #4;
  CREATEPEN #4 PS_SOLID 1px RGB(0,128,0); SELECT #4; SETROP2; then every contour of every insert in
  result order (= cut order): LwPolyline/Circle -> one POLYBEZIER16 (straight segment = cubic with
  control points at 1/3 and 2/3; arc split into ceil(sweep/22.5deg) cubic pieces; circle = 16 pieces),
  Line -> MOVETOEX + LINETO; finally SELECT BLACK_PEN, SELECT NULL_BRUSH, SELECT SYSTEM_FONT, EOF.
  All contours (cut and engraving layers alike) use the same green pen.
"""
import sys, os, math, struct, zipfile

RT = {1: 'HEADER', 14: 'EOF', 18: 'SETBKMODE', 20: 'SETROP2', 24: 'SETTEXTCOLOR', 25: 'SETBKCOLOR',
      27: 'MOVETOEX', 37: 'SELECTOBJECT', 38: 'CREATEPEN', 39: 'CREATEBRUSHINDIRECT', 40: 'DELETEOBJECT',
      54: 'LINETO', 82: 'EXTCREATEFONTINDIRECTW', 85: 'POLYBEZIER16'}
GREEN = 0x008000
NULL_BRUSH, BLACK_PEN, SYSTEM_FONT = 0x80000005, 0x80000007, 0x8000000D


# ------------------------------------------------------------------ parsing
def parse(b):
    recs, p = [], 0
    while p < len(b):
        t, sz = struct.unpack_from('<II', b, p)
        if sz < 8 or p + sz > len(b):
            raise ValueError('bad record at %d' % p)
        recs.append((t, b[p:p + sz])); p += sz
        if t == 14:
            break
    return header(b), recs, p


def header(b):
    f = struct.unpack_from('<II4i4iIIIIHHIIIiiii', b, 0)
    h = dict(type=f[0], size=f[1], bounds=f[2:6], frame=f[6:10], sig=f[10], ver=f[11], nbytes=f[12],
             nrecords=f[13], nhandles=f[14], reserved=f[15], ndesc=f[16], offdesc=f[17], npal=f[18],
             device=f[19:21], mm=f[21:23])
    if f[1] >= 108:
        h['pixfmt'] = struct.unpack_from('<III', b, 88)
        h['micrometers'] = struct.unpack_from('<ii', b, 100)
    return h


def rec_points(t, r):
    if t == 85:
        n = struct.unpack_from('<I', r, 24)[0]
        return [struct.unpack_from('<hh', r, 28 + 4 * i) for i in range(n)]
    if t in (27, 54):
        return [struct.unpack_from('<ii', r, 8)]
    return []


# ------------------------------------------------------------------ writing
def _rec(t, payload):
    return struct.pack('<II', t, 8 + len(payload)) + payload


def _u32(*v):
    return struct.pack('<%dI' % len(v), *v)


def font_record(face_tail=b''):
    lf = struct.pack('<5i8B', -11, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0)
    face = 'Tahoma'.encode('utf-16-le') + b'\0\0'
    face = (face + face_tail)[:64].ljust(64, b'\0')
    body = _u32(1) + lf + face + b'\0' * (128 + 64 + 64) + _u32(0x08007664, 0)
    return _rec(82, body)


def pen(ih, style, color):
    return _rec(38, _u32(ih, style) + struct.pack('<ii', 1, 0) + _u32(color))


def polybezier16(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    body = struct.pack('<4i', min(xs), min(ys), max(xs), max(ys)) + _u32(len(pts))
    body += b''.join(struct.pack('<hh', x, y) for x, y in pts)
    return _rec(85, body)


def rnd(v):
    return int(round(v))          # round half to even (80.5 -> 80, 239.5 -> 240 as in the samples)


class Mapper:
    def __init__(self, W, H, box=320):
        self.W, self.H, self.s, self.c = W, H, (box - 2) / max(W, H), box / 2

    def __call__(self, x, y):
        return (self.c + (x - self.W / 2) * self.s, self.c - (y - self.H / 2) * self.s)


def _arc_beziers(cx, cy, r, a0, sweep, M):
    """cubic pieces (in device float coords, excluding start point) for an arc in world coords."""
    n = max(1, int(math.ceil(abs(sweep) / (math.pi / 8) - 1e-9)))
    d = sweep / n
    k = 4.0 / 3.0 * math.tan(d / 4) * r
    out = []
    for i in range(n):
        t0, t1 = a0 + d * i, a0 + d * (i + 1)
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p3 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        c1 = (p0[0] - k * math.sin(t0), p0[1] + k * math.cos(t0))
        c2 = (p3[0] + k * math.sin(t1), p3[1] - k * math.cos(t1))
        out += [M(*c1), M(*c2), M(*p3)]
    return out


def shape_records(sh, M):
    """sh: dict(kind='Line'|'LwPolyline'|'Circle', pts, bulge, closed, circle=(cx,cy,r,a0)) in sheet coords."""
    if sh['kind'] == 'Line':
        (x0, y0), (x1, y1) = sh['pts'][:2]
        a, b = M(x0, y0), M(x1, y1)
        return [_rec(27, struct.pack('<ii', rnd(a[0]), rnd(a[1]))), _rec(54, struct.pack('<ii', rnd(b[0]), rnd(b[1])))]
    if sh['kind'] == 'Circle':
        cx, cy, r, a0 = sh['circle']
        pts = [M(cx + r * math.cos(a0), cy + r * math.sin(a0))] + _arc_beziers(cx, cy, r, a0, 2 * math.pi, M)
    else:
        P, B = sh['pts'], sh['bulge']
        m = len(P) if sh['closed'] else len(P) - 1
        pts = [M(*P[0])]
        for i in range(m):
            a, c = P[i], P[(i + 1) % len(P)]
            b = B[i] if i < len(B) else 0.0
            if abs(b) < 1e-12:
                pa, pc = M(*a), M(*c)
                pts += [(pa[0] + (pc[0] - pa[0]) / 3, pa[1] + (pc[1] - pa[1]) / 3),
                        (pa[0] + 2 * (pc[0] - pa[0]) / 3, pa[1] + 2 * (pc[1] - pa[1]) / 3), pc]
            else:
                th = 4 * math.atan(b); ch = math.hypot(c[0] - a[0], c[1] - a[1])
                r = ch / (2 * math.sin(abs(th) / 2))
                mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
                ux, uy = (c[0] - a[0]) / ch, (c[1] - a[1]) / ch
                dd = r * math.cos(th / 2) * (1 if b > 0 else -1)
                cx, cy = mx - uy * dd, my + ux * dd
                a0 = math.atan2(a[1] - cy, a[0] - cx)
                pts += _arc_beziers(cx, cy, r, a0, th, M)
    return [polybezier16([(rnd(x), rnd(y)) for x, y in pts])]


def generate(W, H, shapes, device=(2560, 1440), mm=(600, 330), plate=None, face_tail=b''):
    """W,H: plate size (mm); shapes: contours in sheet coords in cut order; plate: LwPolyline dict of the
    plate (default rectangle 0..W x 0..H). device/mm: screen of the 'saving PC' (only rclFrame/szl*)."""
    M = Mapper(W, H)
    if plate is None:
        plate = dict(kind='LwPolyline', pts=[(0, 0), (W, 0), (W, H), (0, H)], bulge=[0] * 4, closed=True)
    body = []
    body.append(_rec(27, struct.pack('<ii', 0, 0)))
    body.append(font_record(face_tail))
    body += [_rec(37, _u32(1)), _rec(24, _u32(0)), pen(2, 0, 0), _rec(37, _u32(2)), _rec(20, _u32(13)),
             _rec(39, _u32(3, 0, 0xFFFFFF, 0)), _rec(37, _u32(3)), _rec(25, _u32(0xFFFFFF)), _rec(18, _u32(2)),
             _rec(27, struct.pack('<ii', 0, 0)), pen(4, 4, GREEN), _rec(37, _u32(4)), _rec(20, _u32(13)),
             _rec(37, _u32(NULL_BRUSH)), _rec(25, _u32(0xFF000000)), _rec(18, _u32(1)), _rec(37, _u32(1)),
             _rec(24, _u32(0))]
    drawn = shape_records(plate, M)
    body += drawn
    body += [_rec(37, _u32(BLACK_PEN)), _rec(40, _u32(4)), pen(4, 0, GREEN), _rec(37, _u32(4)), _rec(20, _u32(13))]
    for sh in shapes:
        recs = shape_records(sh, M)
        body += recs; drawn += recs
    body += [_rec(37, _u32(BLACK_PEN)), _rec(37, _u32(NULL_BRUSH)), _rec(37, _u32(SYSTEM_FONT))]
    eof = _rec(14, _u32(0, 16, 20))
    # rclBounds = bbox of all drawn points (preamble MOVETOEX(0,0) does not count)
    allp = []
    for r in drawn:
        allp += rec_points(struct.unpack_from('<I', r)[0], r)
    bl = (min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp))
    nbytes = 108 + sum(len(r) for r in body) + len(eof)
    nrec = 1 + len(body) + 1
    fr = (0, 0, rnd(32000.0 * mm[0] / device[0]), rnd(32000.0 * mm[1] / device[1]))
    hdr = struct.pack('<II4i4iIIIIHHIIIiiii', 1, 108, *bl, *fr, 0x464D4520, 0x10000, nbytes, nrec, 5, 0, 0, 0, 0,
                      device[0], device[1], mm[0], mm[1])
    hdr += _u32(0, 0, 0) + struct.pack('<ii', mm[0] * 1000, mm[1] * 1000)
    return hdr + b''.join(body) + eof


# ------------------------------------------------------------------ comparison against a real thumbnail
def result_shapes(z, idx):
    """geometry of result idx (plate + contours in cut order) via xml_geom (own reader)."""
    import xml.etree.ElementTree as ET
    from . import xml_geom as G
    X = lambda n: ET.fromstring(z.read(n))
    geo = z.read('Geometry2D/data.bin')
    info = {e.get('Handle'): (e.tag, int(e.get('GeoAddr'))) for e in X('Shapes2D/content.xml') if e.tag != 'MD5'}
    blocks = {b.get('Name'): [s.get('Handle') for s in b.find('Shapes')] for b in X('Blocks/content.xml')}
    r = [r for r in X('Nest2D/Results/content.xml') if r.get('Index') == str(idx)][0]
    rc = X('Nest2D/Results/%s/content.xml' % idx)
    plate, shapes = None, []
    for s in rc.find('Shapes'):
        if s.get('Class') == 'Insert':
            for h in blocks[s.findtext('BlockName')]:
                shapes.append(G.geo(geo, info[h][1], info[h][0]))
        else:
            plate = G.geo(geo, info[s.get('Handle')][1], info[s.get('Handle')][0])
    return float(r.get('SizeX')), float(r.get('SizeY')), plate, shapes


def compare(real, gen):
    hr, rr, _ = parse(real)
    hg, rg, _ = parse(gen)
    seq_r = [RT.get(t, t) for t, _ in rr]; seq_g = [RT.get(t, t) for t, _ in rg]
    out = dict(len_real=len(real), len_gen=len(gen), same_record_sequence=seq_r == seq_g,
               nrecords=(hr['nrecords'], hg['nrecords']), bounds=(hr['bounds'], hg['bounds']),
               frame=(hr['frame'], hg['frame']))
    hdr_keys = ('type', 'size', 'sig', 'ver', 'nhandles', 'reserved', 'ndesc', 'offdesc', 'npal', 'pixfmt')
    out['fixed_header_fields_equal'] = all(hr[k] == hg[k] for k in hdr_keys)
    out['nbytes_ok'] = (hr['nbytes'] == len(real), hg['nbytes'] == len(gen))
    nonpt = [(a, b) for (ta, a), (tb, b) in zip(rr, rg) if ta == tb and ta not in (85, 27, 54, 1, 82)]
    out['non_drawing_records_identical'] = all(a == b for a, b in nonpt)
    fr_r = [r for t, r in rr if t == 82][0]; fr_g = [r for t, r in rg if t == 82][0]
    out['font_record_diff_bytes'] = sum(1 for a, b in zip(fr_r, fr_g) if a != b)
    dmax, npts, nexact, cnt_mismatch = 0, 0, 0, 0
    for (ta, a), (tb, b) in zip(rr, rg):
        if ta != tb:
            continue
        pa, pb = rec_points(ta, a), rec_points(tb, b)
        if len(pa) != len(pb):
            cnt_mismatch += 1; continue
        for p, q in zip(pa, pb):
            d = max(abs(p[0] - q[0]), abs(p[1] - q[1]))
            dmax = max(dmax, d); npts += 1; nexact += d == 0
    out.update(points=npts, points_exact=nexact, max_dev_px=dmax, point_count_mismatch_records=cnt_mismatch)
    dr = [(a, b) for (ta, a), (tb, b) in zip(rr, rg) if ta == tb and ta in (85, 27, 54)]
    out['drawing_records'] = len(dr)
    out['drawing_records_identical'] = sum(1 for a, b in dr if a == b)
    out['byte_identical_except_font'] = (real[:124] == gen[:124] and real[492:] == gen[492:])
    return out


def main(argv):
    if not argv:
        print(__doc__); return 2
    cmd = argv[0]
    if cmd == 'dump':
        z = zipfile.ZipFile(argv[1]); b = z.read('Nest2D/Results/%s/thumbnail.emf' % argv[2])
        h, recs, end = parse(b)
        print(h)
        for t, r in recs:
            pts = rec_points(t, r)
            print(' ', RT.get(t, t), len(r), pts[:8] if pts else r[8:40].hex())
        return 0
    if cmd == 'demo':
        shapes = [dict(kind='LwPolyline', pts=[(100, 100), (700, 100), (700, 400), (100, 400)], bulge=[0, 0.4142, 0, 0], closed=True),
                  dict(kind='Circle', circle=(400, 250, 50, 0.0), pts=[(450, 250)], bulge=[0], closed=True),
                  dict(kind='Line', pts=[(150, 150), (300, 150)], bulge=[0, 0], closed=False)]
        b = generate(1250, 2500, shapes)
        open(argv[1], 'wb').write(b)
        h, recs, end = parse(b)
        print('wrote', argv[1], len(b), 'bytes,', len(recs), 'records; header', h)
        return 0
    if cmd == 'compare':
        allok = True
        for path in argv[1:]:
            z = zipfile.ZipFile(path)
            import xml.etree.ElementTree as ET
            for r in ET.fromstring(z.read('Nest2D/Results/content.xml')):
                idx = r.get('Index')
                real = z.read('Nest2D/Results/%s/thumbnail.emf' % idx)
                hr = header(real)
                W, H, plate, shapes = result_shapes(z, idx)
                gen = generate(W, H, shapes, device=tuple(hr['device']), mm=tuple(hr['mm']), plate=plate)
                c = compare(real, gen)
                tail = real[124 + 12 + 28 + 14:124 + 12 + 28 + 64]       # lfFaceName after 'Tahoma\0' (garbage)
                gen2 = generate(W, H, shapes, device=tuple(hr['device']), mm=tuple(hr['mm']), plate=plate, face_tail=tail)
                nd2 = sum(1 for a, b in zip(real, gen2) if a != b) + abs(len(real) - len(gen2))
                ok = c['same_record_sequence'] and c['fixed_header_fields_equal'] and c['non_drawing_records_identical'] \
                    and c['bounds'][0] == c['bounds'][1] and c['frame'][0] == c['frame'][1] and c['len_real'] == c['len_gen']
                allok &= ok
                print('%-14s R%-2s %s real %6d B gen %6d B | seq %s | hdr %s | bounds %s frame %s | other recs %s | font diff %dB | pts %d exact %d (%.1f%%) maxdev %dpx | draw recs %d/%d byte-equal | with captured font tail: %s' % (
                    os.path.basename(path), idx, 'OK ' if ok else 'BAD', c['len_real'], c['len_gen'], c['same_record_sequence'],
                    c['fixed_header_fields_equal'], c['bounds'][0] == c['bounds'][1], c['frame'][0] == c['frame'][1],
                    c['non_drawing_records_identical'], c['font_record_diff_bytes'], c['points'], c['points_exact'],
                    100.0 * c['points_exact'] / max(1, c['points']), c['max_dev_px'], c['drawing_records_identical'],
                    c['drawing_records'], 'BYTE-IDENTICAL' if nd2 == 0 else '%d bytes differ' % nd2))
        print('STRUCTURE:', 'PASS' if allok else 'FAIL')
        return 0 if allok else 1
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
