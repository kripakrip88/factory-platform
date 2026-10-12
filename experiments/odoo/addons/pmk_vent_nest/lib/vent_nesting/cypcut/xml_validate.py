# -*- coding: utf-8 -*-
"""Validator of a CypCut .lxds program: every cross-reference / invariant found in the 5 factory samples.

    python3 -I xml_validate.py FILE.lxds [FILE2.lxds ...] [-q]

Prints PASS / FAIL per check (INFO lines carry observations that are not rules). Exit code 1 if any FAIL.
The archive is read as zip in memory; nothing is extracted or executed. Uses own helper modules from this
folder: xml_zip (container), xml_model (XML format), xml_geom (geometry reader), xml_emf (thumbnails).
"""
import sys, os, re, io, math, struct, hashlib, zipfile, datetime, collections
from . import xml_zip, xml_model, xml_geom as G, xml_emf
GUID_RE = re.compile(r'^\{[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}\}$')
NUM_RE = re.compile(r'^-?(\d+)?(\.\d+)?$')
FIXED = {'Technical': 2, 'Viewports': 3, 'Blocks': 4, 'Layers': 5, 'TextStyles': 6, 'Portions': 12}
HEADER_VERSION = '419963393'          # 0x19082201 -- constant in all samples (looks like a 2019-08-22 format stamp)


class Report:
    def __init__(self, quiet=False):
        self.rows, self.quiet = [], quiet

    def check(self, name, ok, detail=''):
        self.rows.append(('PASS' if ok else 'FAIL', name, detail))
        return ok

    def info(self, name, detail):
        self.rows.append(('INFO', name, detail))

    def dump(self, title):
        print('=' * 100)
        print(title)
        for st, n, d in self.rows:
            if self.quiet and st == 'PASS':
                continue
            print('  %-4s %-58s %s' % (st, n, d))
        nf = sum(1 for r in self.rows if r[0] == 'FAIL')
        npass = sum(1 for r in self.rows if r[0] == 'PASS')
        print('  -> %d PASS, %d FAIL, %d INFO' % (npass, nf, sum(1 for r in self.rows if r[0] == 'INFO')))
        return nf


def bin_records(buf):
    """walk a BCMP data.bin: header + contiguous objects (d1d1d1d1, u32 0, u32 len, ...), 8-aligned."""
    starts, p = [], 0x1000
    while p < len(buf):
        if buf[p:p + 4] != b'\xd1' * 4:
            return starts, p
        ln = struct.unpack_from('<I', buf, p + 8)[0]
        starts.append(p)
        p += (ln + 7) & ~7
    return starts, p


def validate(path, quiet=False):
    R = Report(quiet)
    raw = open(path, 'rb').read()
    # ------------------------------------------------------------ A. container
    try:
        entries, zmeta = xml_zip.parse(raw)
        R.check('A1 zip parses (strict, STORED, no data descriptor)', True, '%d entries' % len(entries))
    except Exception as e:
        R.check('A1 zip parses', False, repr(e)); return R
    rules = xml_zip.describe(entries, zmeta)
    bad = [k for k, v in rules.items() if not v]
    R.check('A2 container rules (made 0x3F, need 10/20, flags 0, NTFS extra, attrs 0, one DOS time, no gaps)',
            not bad, 'violated: %s' % bad if bad else ', '.join(rules))
    R.check('A3 parse->build byte-identical', xml_zip.build(entries, zmeta) == raw)
    names = [e['name'] for e in entries]
    data = {e['name']: e['data'] for e in entries}
    z = zipfile.ZipFile(io.BytesIO(raw))
    R.check('A4 zipfile CRC check (testzip)', z.testzip() is None)
    files = set(n for n in names if not n.endswith('/'))
    dirs = set(n for n in names if n.endswith('/'))
    R.check('A5 every folder of a file has its own directory entry',
            all(n.rsplit('/', 1)[0] + '/' in dirs for n in files if '/' in n),
            'missing: %s' % sorted(n for n in files if '/' in n and n.rsplit('/', 1)[0] + '/' not in dirs)[:5])
    R.check('A6 no empty / unused directory entries', all(any(f.startswith(d) for f in files) for d in dirs))
    X = lambda n: xml_model.parse(data[n], strict=False)
    res_idx = sorted(int(m.group(1)) for n in files for m in [re.match(r'Nest2D/Results/(\d+)/content\.xml$', n)] if m)
    required = ['info.xml', 'content.xml', 'Technical/content.xml', 'Viewports/content.xml', 'Layers/content.xml',
                'TextStyles/content.xml', 'Blocks/content.xml', 'Shapes2D/content.xml', 'Shapes2D/data.bin',
                'Geometry2D/content.xml', 'Geometry2D/data.bin', 'Nest2D/content.xml', 'Nest2D/Plates/content.xml',
                'Nest2D/Parts/content.xml', 'Nest2D/Results/content.xml']
    required += ['Nest2D/Results/%d/%s' % (i, f) for i in res_idx for f in ('content.xml', 'thumbnail.emf')]
    optional = ['Nest2D/Parts/Groups/content.xml']
    miss = [n for n in required if n not in files]
    extra = sorted(files - set(required) - set(optional))
    R.check('A7 all required entries present', not miss, 'missing %s' % miss)
    R.check('A8 no unknown entries', not extra, 'extra %s' % extra)
    if miss:
        return R
    order_dirs = [n for n in names if n.endswith('/')]
    R.info('A9 folder order in archive (hash-like, preserved as metadata)', ' '.join(d.rstrip('/') for d in order_dirs))
    R.check('A10 root files first: info.xml, content.xml', names[:2] == ['info.xml', 'content.xml'])
    R.check('A11 data.bin before content.xml (Shapes2D, Geometry2D); content.xml before thumbnail.emf',
            all(names.index(a) < names.index(b) for a, b in
                [('Shapes2D/data.bin', 'Shapes2D/content.xml'), ('Geometry2D/data.bin', 'Geometry2D/content.xml')] +
                [('Nest2D/Results/%d/content.xml' % i, 'Nest2D/Results/%d/thumbnail.emf' % i) for i in res_idx]))
    # ------------------------------------------------------------ B. XML format
    xmls = [n for n in names if n.endswith('.xml')]
    def _rt(n):
        try:
            return xml_model.serialize(xml_model.parse(data[n])) == data[n]
        except Exception:
            return False
    rt_bad = [n for n in xmls if not _rt(n)]
    R.check('B1 every XML == serialize(parse(XML)) (CRLF, TAB indent, decl, <x/>)', not rt_bad, 'differ: %s' % rt_bad)
    nn = nbad = 0; badv = []
    for n in xmls:
        for el in xml_model.parse(data[n], strict=False).iter():
            vals = list(el.attrs) + ([('#text', el.text)] if el.text else [])
            for k, v in vals:
                if v and NUM_RE.match(v) and v not in ('-', '.'):
                    nn += 1
                    if xml_model.fmt_num(float(v) if ('.' in v or len(v.lstrip('-')) > 15) else int(v)) != v:
                        nbad += 1; badv.append((n, el.tag, k, v))
    R.check('B2 numbers formatted as %.9g without leading 0 (".5")', nbad == 0, '%d numeric values, %d bad %s' % (nn, nbad, badv[:3]))
    # ------------------------------------------------------------ C. info.xml / content.xml
    info = X('info.xml'); content = X('content.xml')
    app = info.find('Application'); sb = info.find('SavedBy')
    R.check('C1 info.xml: DocVersion Major=1, AppName=CypCut, AppVer 6.3.907.N',
            info.find('DocVersion').get('Major') == '1' and app.get('AppName') == 'CypCut'
            and re.match(r'^6\.3\.907\.\d+$', app.get('AppVer') or '') is not None, app.get('AppVer'))
    st = sb.get('SaveTime') or ''
    R.check('C2 SaveTime format YYYY-MM-DDTHH:MM:SSZ', re.match(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$', st) is not None, st)
    e0 = entries[0]
    ex = bytes.fromhex(e0['central_extra']); mt = struct.unpack_from('<Q', ex, 12)[0]
    utc = xml_zip.FILETIME_EPOCH + datetime.timedelta(microseconds=mt // 10)
    if st:
        loc = datetime.datetime.strptime(st, '%Y-%m-%dT%H:%M:%SZ')
        off = (loc - utc.replace(microsecond=0)).total_seconds() / 3600
        t, d = e0['dos_time'], e0['dos_date']
        dos = datetime.datetime(1980 + (d >> 9), (d >> 5) & 15, d & 31, t >> 11, (t >> 5) & 63, (t & 31) * 2)
        R.check('C3 SaveTime = LOCAL save time (despite "Z") = NTFS UTC + whole hours', abs(off - round(off)) < 1e-9,
                'offset %+g h (NTFS %s UTC)' % (off, utc))
        exp_dos = xml_zip.dos_datetime(utc + datetime.timedelta(hours=round(off)))
        R.check('C4 zip DOS time = local save time rounded up to even second', exp_dos == (t, d), 'DOS %s' % dos)
    hdr = content.find('Header')
    R.check('C5 PackData DocType=Model2D; Header DefaultChannel=1, Version=%s' % HEADER_VERSION,
            content.get('DocType') == 'Model2D' and hdr.get('DefaultChannel') == '1' and hdr.get('Version') == HEADER_VERSION,
            'Version=%s' % hdr.get('Version'))
    R.check('C6 Header ID = uppercase GUIDv4 in braces', GUID_RE.match(hdr.get('ID') or '') is not None, hdr.get('ID'))
    R.check('C7 OrgAppName/OrgAppVer both or none', (hdr.get('OrgAppName') is None) == (hdr.get('OrgAppVer') is None),
            '%s %s' % (hdr.get('OrgAppName'), hdr.get('OrgAppVer')))
    R.check('C8 Header attr order DefaultChannel HandleSeed ID Version [OrgAppName OrgAppVer]; <InsertBase/>',
            [a for a, _ in hdr.attrs][:4] == ['DefaultChannel', 'HandleSeed', 'ID', 'Version'] and
            [c.tag for c in hdr.children] == ['InsertBase'] and not hdr.children[0].attrs)
    sec = [(c.tag, c.get('Handle')) for c in content.children if c.tag != 'Header']
    R.check('C9 section handles Technical2 Viewports3 Layers5 TextStyles6 Blocks4 Portions12 (this order)',
            sec == [('Technical', '2'), ('Viewports', '3'), ('Layers', '5'), ('TextStyles', '6'), ('Blocks', '4'), ('Portions', '12')], str(sec))
    R.check('C10 section files repeat their handle (Technical/Viewports/Layers/TextStyles)',
            X('Technical/content.xml').get('Handle') == '2' and X('Viewports/content.xml').get('Handle') == '3'
            and X('Layers/content.xml').get('Handle') == '5' and X('TextStyles/content.xml').get('Handle') == '6'
            and X('Blocks/content.xml').get('Handle') is None)
    vp = X('Viewports/content.xml')
    R.check('C11 Viewports constant (Active=1, one VPort Name=1, ZoomCoeff 1, ViewHeight 100, 1024x768)',
            vp.get('Active') == '1' and len(vp.children) == 1 and xml_model.serialize(vp).replace(
                vp.children[0].get('Handle').encode(), b'H') == xml_model.serialize(xml_model.Node('Viewports', [('Handle', '3'), ('Active', '1')], None, [
                    xml_model.Node('VPort', [('Handle', 'H'), ('Name', '1')], None, [
                        xml_model.Node('ViewCenter'), xml_model.Node('ZoomCoeff', [], '1'), xml_model.Node('ViewHeight', [], '100'),
                        xml_model.Node('AspectRatio', [], '1'),
                        xml_model.Node('DisplayRect', [], None, [xml_model.Node('Right', [], '1024'), xml_model.Node('Bottom', [], '768')])])])))
    R.check('C12 Layers/TextStyles are empty sections', not X('Layers/content.xml').children and not X('TextStyles/content.xml').children)
    tech = X('Technical/content.xml')
    R.info('C13 Technical: channels / material', '%d Channel, MaterialParams %s' % (
        len(tech.find('Channels').children), [m.get('MaterialName') for m in tech.iter('MaterialParams')]))
    # ------------------------------------------------------------ D. load model
    shapes2d = X('Shapes2D/content.xml')
    blocks_x = X('Blocks/content.xml')
    nest = X('Nest2D/content.xml')
    plates_x = X('Nest2D/Plates/content.xml')
    parts_x = X('Nest2D/Parts/content.xml')
    groups_x = X('Nest2D/Parts/Groups/content.xml') if 'Nest2D/Parts/Groups/content.xml' in files else None
    ress_x = X('Nest2D/Results/content.xml')
    res_x = {i: X('Nest2D/Results/%d/content.xml' % i) for i in res_idx}
    geo, dat = data['Geometry2D/data.bin'], data['Shapes2D/data.bin']
    sh = [e for e in shapes2d.children if e.tag != 'MD5']
    shp = {e.get('Handle'): e for e in sh}
    blocks = {b.get('Name'): b for b in blocks_x.children}
    parts = {p.get('Handle'): p for p in parts_x.children}
    groups = {g.get('Handle'): g for g in (groups_x.children if groups_x else [])}
    plates = {p.get('Handle'): p for p in plates_x.children}
    # ------------------------------------------------------------ E. handles
    defs = [(int(h), 'section ' + k) for k, h in [(c.tag, c.get('Handle')) for c in content.children if c.get('Handle')]]
    vport = int(vp.children[0].get('Handle'))
    for b in blocks_x.children:
        defs += [(int(b.get('Handle')), 'Block'), (int(b.find('Shapes').get('Handle')), 'Block/Shapes')]
    defs += [(int(e.get('Handle')), 'Shape ' + e.tag) for e in sh]
    for p in parts_x.children:
        defs += [(int(p.get('Handle')), 'NestPart'), (int(p.find('Insert').get('Handle')), 'NestPart/Insert')]
    defs += [(int(g.get('Handle')), 'NestGroup') for g in groups.values()]
    defs += [(int(p.get('Handle')), 'NestPlate') for p in plates.values()]
    for i, rc in res_x.items():
        defs.append((int(rc.get('Handle')), 'NestResult'))
        defs += [(int(s.get('Handle')), 'Result insert') for s in rc.find('Shapes').children if s.get('Class') == 'Insert']
    cnt = collections.Counter(h for h, _ in defs)
    dups = [h for h, n in cnt.items() if n > 1]
    R.check('E1 handles unique in ONE global namespace (sections, blocks, shapes, parts, inserts, groups, plates, results)',
            not dups, '%d definitions, dup %s' % (len(defs), dups[:5]))
    seed = int(hdr.get('HandleSeed'))
    mx = max(h for h, _ in defs)
    R.check('E2 Header HandleSeed == max handle in use (VPort excluded)', seed == mx, 'HandleSeed %d, max %d' % (seed, mx))
    R.check('E3 VPort handle unique', vport not in cnt, 'VPort %d' % vport)
    R.info('E4 VPort vs HandleSeed', 'VPort = HandleSeed+1' if vport == seed + 1 else 'VPort %d < HandleSeed %d (doc re-saved; VPort kept from load)' % (vport, seed))
    R.check('E5 all object handles > 1000 except fixed sections', all(h > 1000 for h, k in defs if not k.startswith('section')))
    R.check('E6 Block/Shapes handle == Block handle + 1', all(int(b.find('Shapes').get('Handle')) == int(b.get('Handle')) + 1 for b in blocks_x.children))
    # ------------------------------------------------------------ F. bins, Shapes2D, Blocks
    for nm, buf in (('Geometry2D', geo), ('Shapes2D', dat)):
        okh = buf[:4] == b'BCMP' and struct.unpack_from('<I', buf, 4)[0] == len(buf) and struct.unpack_from('<I', buf, 8)[0] == 1 \
            and buf[12:0x1000] == b'\0' * (0x1000 - 12)
        R.check('F1 %s/data.bin header: BCMP, u32 size == len, u32 1, zeros to 0x1000' % nm, okh, '%d B' % len(buf))
        md5 = X('%s/content.xml' % nm).findtext('MD5')
        R.check('F2 %s MD5 == uppercase md5(%s/data.bin)' % (nm, nm), md5 == hashlib.md5(buf).hexdigest().upper(), md5)
    R.check('F3 Geometry2D/content.xml is exactly <Geometry2D><MD5/></Geometry2D>', [c.tag for c in X('Geometry2D/content.xml').children] == ['MD5'])
    R.check('F4 Shapes2D: MD5 is the last child, one element per shape', [c.tag for c in shapes2d.children].count('MD5') == 1 and shapes2d.children[-1].tag == 'MD5')
    gstarts, gend = bin_records(geo); dstarts, dend = bin_records(dat)
    R.check('F5 bins = contiguous 8-aligned objects from 0x1000 to EOF', gend == len(geo) and dend == len(dat),
            'geo %d objs, data %d objs' % (len(gstarts), len(dstarts)))
    ga = [int(e.get('GeoAddr')) for e in sh]; da = [int(e.get('DataAddr')) for e in sh]
    R.check('F6 GeoAddr/DataAddr = the i-th object of each bin (1:1, in Shapes2D order)', ga == gstarts and da == dstarts,
            '%d shapes' % len(sh))
    okc = okh = 0
    for e in sh:
        cname = ('TGks' + e.tag).encode()
        g0, d0 = int(e.get('GeoAddr')), int(e.get('DataAddr'))
        okc += geo[g0 + 20:g0 + 20 + len(cname)] == cname and dat[d0 + 20:d0 + 20 + len(cname)] == cname
        rec = dat[d0:d0 + struct.unpack_from('<I', dat, d0 + 8)[0]]
        j = rec.find(b'S\x00\x06\x00Object')
        okh += j >= 0 and struct.unpack_from('<I', rec, j + 16)[0] == int(e.get('Handle'))
    R.check('F7 both bin objects carry class name "TGks"+tag', okc == len(sh), '%d/%d' % (okc, len(sh)))
    R.check('F8 Shapes2D/data.bin "Object" sub-record holds the shape Handle', okh == len(sh), '%d/%d' % (okh, len(sh)))
    R.check('F9 Shapes2D attr order Handle [LayerName] DataAddr GeoAddr; tags Line/LwPolyline/Circle',
            all([a for a, _ in e.attrs] in (['Handle', 'LayerName', 'DataAddr', 'GeoAddr'], ['Handle', 'DataAddr', 'GeoAddr']) for e in sh)
            and all(e.tag in ('Line', 'LwPolyline', 'Circle') for e in sh), str(collections.Counter(e.tag for e in sh)))
    R.info('F10 LayerName values', str(dict(collections.Counter(e.get('LayerName') for e in sh))))
    geoms, unk = {}, collections.Counter()
    for e in sh:
        try:
            g = G.geo(geo, int(e.get('GeoAddr')), e.tag)
            g['layer'] = G.layer_of(dat, int(e.get('DataAddr')))
            geoms[e.get('Handle')] = g
        except G.Unsupported:
            unk[e.tag] += 1
    R.check('F11 geometry of every shape decodes (Line/LwPolyline/Circle)', not unk, str(dict(unk)))
    # blocks
    bh = [int(b.get('Handle')) for b in blocks_x.children]
    R.check('F12 Blocks sorted by handle; names unique', bh == sorted(bh) and len(blocks) == len(blocks_x.children))
    owner = collections.Counter()
    clsok = True
    for b in blocks_x.children:
        for s in b.find('Shapes').children:
            owner[s.get('Handle')] += 1
            clsok &= s.get('Handle') in shp and shp[s.get('Handle')].tag == s.get('Class') and [a for a, _ in s.attrs] == ['Class', 'Handle']
    plate_sh = [p.find('LwPolyline').get('Handle') for p in plates.values()]
    res_plate_sh = [s.get('Handle') for rc in res_x.values() for s in rc.find('Shapes').children if s.get('Class') != 'Insert']
    for h in plate_sh + res_plate_sh:
        owner[h] += 1
    R.check('F13 Block <Shape Class Handle> -> Shapes2D element of that class', clsok)
    R.check('F14 every Shapes2D shape owned exactly once (block / plate / result plate)',
            set(owner) == set(shp) and all(v == 1 for v in owner.values()),
            'orphans %d, multi %d' % (len(set(shp) - set(owner)), sum(1 for v in owner.values() if v > 1)))
    order = [s.get('Handle') for b in blocks_x.children for s in b.find('Shapes').children] + plate_sh + res_plate_sh
    R.check('F15 Shapes2D order = blocks (in order, shapes in block order), then plates, then result plates',
            order == [e.get('Handle') for e in sh])
    R.check('F16 Block: <BasePoint/> (0,0) then <Shapes>; attr order Handle Name [OutlineID] [Flags]',
            all([c.tag for c in b.children] == ['BasePoint', 'Shapes'] and not b.find('BasePoint').attrs
                and [a for a, _ in b.attrs] in (['Handle', 'Name', 'OutlineID', 'Flags'], ['Handle', 'Name', 'OutlineID'],
                                                ['Handle', 'Name', 'Flags'], ['Handle', 'Name']) for b in blocks_x.children))
    oid_ok = oid_n = 0; oid_bad = []
    for b in blocks_x.children:
        oid = b.get('OutlineID')
        if oid is None:
            continue
        oid_n += 1
        hs = [s.get('Handle') for s in b.find('Shapes').children]
        closed = [h for h in hs if h in geoms and geoms[h]['closed']]
        big = max(closed, key=lambda h: G.area(geoms[h])) if closed else None
        if oid in hs and oid == big:
            oid_ok += 1
        else:
            oid_bad.append(b.get('Name'))
    R.check('F17 Block OutlineID = handle of its closed contour with the largest area (outer contour)', oid_ok == oid_n,
            '%d/%d %s' % (oid_ok, oid_n, oid_bad[:3]))
    # block roles
    part_blocks = {p.find('Insert').findtext('BlockName') for p in parts.values()}
    ins_blocks = collections.Counter(s.findtext('BlockName') for rc in res_x.values() for s in rc.find('Shapes').children if s.get('Class') == 'Insert')
    grp_blocks = {s.findtext('BlockName') for rc in res_x.values() for s in rc.find('Shapes').children if s.get('NestGroup')}
    R.check('F18 every referenced BlockName exists', all(n in blocks for n in list(part_blocks) + list(ins_blocks)))
    R.check('F19 each result-insert block used by exactly one insert, never by a part', all(v == 1 for v in ins_blocks.values())
            and not (set(ins_blocks) & part_blocks))
    R.check('F20 result-insert blocks named {GUID}', all(GUID_RE.match(n) for n in ins_blocks))
    R.check('F21 part blocks named "CloneForNest[<rand>]", "Деталь<n>[<rand>]" or {GUID}',
            all(re.match(r'^(CloneForNest\d*|Деталь\d+|\{[0-9A-F-]{36}\})$', n) for n in part_blocks), str(sorted(part_blocks)[:4]))
    R.check('F22 group-insert blocks have no OutlineID', all(blocks[n].get('OutlineID') is None for n in grp_blocks))
    R.check('F23 Block Flags only 512', all(b.get('Flags') in (None, '512') for b in blocks_x.children))
    fl = collections.Counter(('part' if n in part_blocks else 'insert' if n in ins_blocks else 'unreferenced', b.get('Flags'))
                             for n, b in blocks.items())
    R.info('F24 Block Flags by role (512 = part source block in 6.3.907.11)', str(dict(fl)))
    R.info('F25 unreferenced blocks (left from earlier nest runs)', str(sum(1 for n in blocks if n not in part_blocks and n not in ins_blocks)))
    # ------------------------------------------------------------ G. Nest2D
    ng = nest.find('NestGroups')
    R.check('G1 NestInfo children Parts, NestGroups, Plates, Results', [c.tag for c in nest.children] == ['Parts', 'NestGroups', 'Plates', 'Results'])
    R.check('G2 NestInfo Parts Count == #NestPart', nest.find('Parts').get('Count') == str(len(parts)))
    R.check('G3 NestInfo NestGroups Count == #NestGroup (attr omitted and no Groups file when 0)',
            (ng.get('Count') == str(len(groups)) and groups_x is not None) or (ng.get('Count') is None and not groups and groups_x is None),
            'Count=%s groups=%d file=%s' % (ng.get('Count'), len(groups), groups_x is not None))
    R.check('G4 NestInfo Plates Count == #NestPlate', nest.find('Plates').get('Count') == str(len(plates)))
    R.check('G5 NestInfo Results Count == #NestResult == #Results/N folders', nest.find('Results').get('Count') == str(len(ress_x.children)) == str(len(res_idx)))
    idx = [int(r.get('Index')) for r in ress_x.children]
    R.check('G6 Results Index = 1..N in order', idx == list(range(1, len(idx) + 1)) and res_idx == idx)
    # usage counts
    used_part = collections.Counter(); used_grp = collections.Counter(); plate_used = collections.Counter()
    for r in ress_x.children:
        rc = res_x[int(r.get('Index'))]
        pa = int(rc.get('PlateAmount'))
        for s in rc.find('Shapes').children:
            if s.get('Class') != 'Insert':
                plate_used[s.get('NestPlate')] += pa
            elif s.get('NestGroup'):
                used_grp[s.get('NestGroup')] += pa
                for o in groups[s.get('NestGroup')].findall('Object'):
                    used_part[o.get('Handle')] += pa
            else:
                used_part[s.get('NestPart')] += pa
    # plates
    for ph, p in plates.items():
        lw = p.find('LwPolyline'); shp_el = p.find('Shape')
        pts = [(float(q.get('X', '0')), float(q.get('Y', '0'))) for q in lw.findall('Point')]
        R.check('G7 Plate %s: Name=Rectangle ShapeCls=LwPolyline, GUID' % ph, p.get('ShapeCls') == 'LwPolyline' and GUID_RE.match(p.get('GUID') or '') is not None, p.get('Name'))
        R.check('G8 Plate %s: Amount == AmountUsed == sum PlateAmount over results' % ph,
                p.get('Amount') == p.get('AmountUsed') == str(plate_used[ph]), '%s/%s/%d' % (p.get('Amount'), p.get('AmountUsed'), plate_used[ph]))
        R.check('G9 Plate %s: <LwPolyline> and <Shape> same Handle (+NestPlate=plate if present), PointCount, PolyFlag=1' % ph,
                lw.get('Handle') == shp_el.get('Handle') and shp_el.get('Class') == 'LwPolyline' and lw.get('NestPlate') == shp_el.get('NestPlate')
                and lw.get('NestPlate') in (None, ph) and lw.get('PointCount') == str(len(pts)) and lw.get('PolyFlag') == '1'
                and lw.get('LeadInOptimizeFlag') == '6' and [c.tag for c in p.children] == ['LwPolyline', 'Shape', 'ExtShapes'])
        g = geoms.get(lw.get('Handle'))
        R.check('G10 Plate %s: Points == its geometry in Geometry2D (closed)' % ph,
                g is not None and g['closed'] and len(g['pts']) == len(pts) and all(abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9 for a, b in zip(g['pts'], pts)),
                str(pts))
        R.check('G11 Plate %s: zero coordinates omitted (<Point/>, X/Y absent when 0)' % ph,
                all(q.get('X') != '0' and q.get('Y') != '0' for q in lw.findall('Point')))
    W = H = None
    if len(plates) == 1:
        p0 = list(plates.values())[0]
        pts = [(float(q.get('X', '0')), float(q.get('Y', '0'))) for q in p0.find('LwPolyline').findall('Point')]
        W = max(x for x, _ in pts) - min(x for x, _ in pts); H = max(y for _, y in pts) - min(y for _, y in pts)
    # parts
    names_ = collections.Counter(p.get('Name') for p in parts.values())
    for ph, p in parts.items():
        ins, s2 = p.find('Insert'), p.find('Shape')
        same = ins.get('Handle') == s2.get('Handle') and ins.get('ChannelPort') == s2.get('ChannelPort') and \
            [(c.tag, c.text) for c in ins.children] == [(c.tag, c.text) for c in s2.children] and s2.get('Class') == 'Insert'
        R.check('G12 Part %s: <Insert> == <Shape Class=Insert> (Handle, ChannelPort, BlockName, XScale=YScale=1)' % ph,
                same and ins.findtext('XScale') == '1' and ins.findtext('YScale') == '1' and p.get('ShapeCls') == 'Insert'
                and [c.tag for c in p.children] == ['Insert', 'Shape', 'ExtShapes'])
        R.check('G13 Part %s: Amount == AmountUsed == sum over results (direct+groups) x PlateAmount' % ph,
                p.get('Amount') == p.get('AmountUsed') == str(used_part[ph]), '%s "%s": %s/%s/%d' % (
                    ph, p.get('Name'), p.get('Amount'), p.get('AmountUsed'), used_part[ph]))
        R.check('G14 Part %s: GUID format' % ph, GUID_RE.match(p.get('GUID') or '') is not None)
    R.info('G15 part names unique?', 'yes' if all(v == 1 for v in names_.values()) else 'NO: %s' % [k for k, v in names_.items() if v > 1])
    # groups
    ref_groups = set(used_grp)
    for gh, g in groups.items():
        objs = [o.get('Handle') for o in g.findall('Object')]
        if gh in ref_groups:
            R.check('G16 Group %s (used): Name=CoedgePart, Amount=1, objects are existing parts' % gh,
                    g.get('Name') == 'CoedgePart' and g.get('Amount') == '1' and all(o in parts for o in objs) and GUID_RE.match(g.get('GUID') or ''))
            R.check('G17 Group %s (used): AmountUsed == 1 + sum PlateAmount (observed quirk)' % gh,
                    g.get('AmountUsed') == str(1 + used_grp[gh]), 'AmountUsed=%s used=%d' % (g.get('AmountUsed'), used_grp[gh]))
        else:
            R.check('G18 Group %s (stale, unreferenced): AmountUsed absent or 1' % gh, g.get('AmountUsed') in (None, '1'),
                    'AmountUsed=%s, dangling objects %s' % (g.get('AmountUsed'), sorted(set(o for o in objs if o not in parts))))
    # results
    for r in ress_x.children:
        i = int(r.get('Index')); rc = res_x[i]
        tag = 'R%d' % i
        R.check('G19 %s: summary attr order Index Name PartCount Utilization PlanCount SizeX SizeY ID' % tag,
                [a for a, _ in r.attrs] == ['Index', 'Name', 'PartCount', 'Utilization', 'PlanCount', 'SizeX', 'SizeY', 'ID'])
        R.check('G20 %s: Name, ID, Utilization equal in summary and Results/%d; PlanCount == PlateAmount' % (tag, i),
                r.get('Name') == rc.get('Name') and r.get('ID') == rc.get('ID') and r.get('Utilization') == rc.get('Utilization')
                and r.get('PlanCount') == rc.get('PlateAmount') and GUID_RE.match(r.get('ID') or '') is not None,
                'PlateAmount=%s' % rc.get('PlateAmount'))
        R.check('G21 %s: result attrs Handle Name ID [Flags] PlateAmount Utilization MaterialName="Material Name"' % tag,
                [a for a, _ in rc.attrs] in (['Handle', 'Name', 'ID', 'PlateAmount', 'Utilization', 'MaterialName'],
                                             ['Handle', 'Name', 'ID', 'Flags', 'PlateAmount', 'Utilization', 'MaterialName'])
                and rc.get('MaterialName') == 'Material Name' and [c.tag for c in rc.children] == ['ExtMin', 'ExtMax', 'HomeRef', 'Shapes']
                and rc.find('HomeRef').get('RefType') == '515', 'Flags=%s' % rc.get('Flags'))
        emin = (float(rc.find('ExtMin').get('X', '0')), float(rc.find('ExtMin').get('Y', '0')))
        emax = (float(rc.find('ExtMax').get('X', '0')), float(rc.find('ExtMax').get('Y', '0')))
        R.check('G22 %s: SizeX/SizeY == ExtMax-ExtMin == plate size; ExtMin=<ExtMin/>' % tag,
                float(r.get('SizeX')) == emax[0] - emin[0] and float(r.get('SizeY')) == emax[1] - emin[1] and emin == (0, 0)
                and (W is None or (float(r.get('SizeX')) == W and float(r.get('SizeY')) == H)), '%s x %s' % (r.get('SizeX'), r.get('SizeY')))
        ss = rc.find('Shapes').children
        first = ss[0]
        pg = geoms.get(first.get('Handle'))
        R.check('G23 %s: first shape = own copy of the plate LwPolyline (NestPlate=plate, same rectangle)' % tag,
                first.get('Class') == 'LwPolyline' and first.get('NestPlate') in plates and pg is not None
                and all(s.get('Class') == 'Insert' for s in ss[1:])
                and sorted(pg['pts']) == sorted(geoms[plates[first.get('NestPlate')].find('LwPolyline').get('Handle')]['pts']))
        ins = ss[1:]
        okins = all((s.get('NestPart') is None) != (s.get('NestGroup') is None) and s.findtext('XScale') == '1' and s.findtext('YScale') == '1'
                    and [c.tag for c in s.children] == ['BlockName', 'XScale', 'YScale'] and s.get('ChannelPort') in (None, '1')
                    and (s.get('NestPart') in parts if s.get('NestPart') else s.get('NestGroup') in groups) for s in ins)
        R.check('G24 %s: inserts: exactly one of NestPart/NestGroup (existing), XScale=YScale=1, no position/rotation' % tag, okins,
                '%d inserts' % len(ins))
        pc = sum(len(groups[s.get('NestGroup')].findall('Object')) if s.get('NestGroup') else 1 for s in ins)
        R.check('G25 %s: PartCount == parts on ONE sheet (group objects counted)' % tag, r.get('PartCount') == str(pc), '%s vs %d' % (r.get('PartCount'), pc))
        # geometry inside the plate
        allp = []
        for s in ins:
            for c in blocks[s.findtext('BlockName')].find('Shapes').children:
                g = geoms.get(c.get('Handle'))
                if g:
                    x0, y0, x1, y1 = G.bbox(g); allp += [(x0, y0), (x1, y1)]
        out = [p for p in allp if not (emin[0] - 1e-6 <= p[0] <= emax[0] + 1e-6 and emin[1] - 1e-6 <= p[1] <= emax[1] + 1e-6)]
        R.check('G26 %s: all insert geometry lies on the sheet (blocks are in sheet coordinates)' % tag, not out, '%d points outside' % len(out))
        # part inserts are exact copies of the part block
        okcopy = ncopy = sameorder = 0
        for s in ins:
            if not s.get('NestPart'):
                continue
            ncopy += 1
            a = [geoms[c.get('Handle')] for c in blocks[s.findtext('BlockName')].find('Shapes').children]
            b = [geoms[c.get('Handle')] for c in blocks[parts[s.get('NestPart')].find('Insert').findtext('BlockName')].find('Shapes').children]
            key = lambda g: (g['kind'], round(G.area(g), 3), g['layer'], g['closed'], len(g['pts']))
            okcopy += sorted(map(key, a)) == sorted(map(key, b))
            sameorder += [key(x) for x in a] == [key(y) for y in b]
        R.check('G27 %s: NestPart insert block = moved/rotated copy of the part block (same contours: kind, area, layer)' % tag,
                okcopy == ncopy, '%d/%d; same contour ORDER in %d (CypCut may re-sequence holes)' % (okcopy, ncopy, sameorder))
        # utilization
        tot = 0.0; curved = False
        for s in ins:
            members = [o.get('Handle') for o in groups[s.get('NestGroup')].findall('Object')] if s.get('NestGroup') else [s.get('NestPart')]
            for m in members:
                hs = [c.get('Handle') for c in blocks[parts[m].find('Insert').findtext('BlockName')].find('Shapes').children]
                cl = [geoms[h] for h in hs if h in geoms and geoms[h]['closed']]
                curved |= any(c.get('circle') or any(abs(b) > 1e-12 for b in c['bulge']) for c in cl)
                if cl:
                    ar = [G.area(c) for c in cl]
                    k = max(range(len(cl)), key=lambda q: ar[q])
                    tot += ar[k] - sum(ar[q] for q in range(len(cl)) if q != k)
        util = 100.0 * tot / (float(r.get('SizeX')) * float(r.get('SizeY')))
        stored = float(r.get('Utilization'))
        rel = abs(util - stored) / stored if stored else abs(util)
        exact = xml_model.fmt_num(util) == r.get('Utilization')
        R.check('G28 %s: Utilization = 100*sum(outer - ALL inner closed contours)/(SizeX*SizeY)' % tag,
                exact or (curved and rel < 2e-5), 'stored %s calc %s %s' % (r.get('Utilization'), xml_model.fmt_num(util),
                                                                        'EXACT' if exact else 'rel.err %.1e (arcs/circles polygonised by CypCut)' % rel))
    active = hdr = content.find('Portions').get('ActiveModelID')
    ids = [r.get('ID') for r in ress_x.children]
    R.check('H1 Portions ActiveModelID == ID of a result', active in ids,
            'result #%d of %d%s' % (ids.index(active) + 1 if active in ids else -1, len(ids), ' (the LAST one)' if ids and active == ids[-1] else ''))
    # ------------------------------------------------------------ I. thumbnails
    for r in ress_x.children:
        i = int(r.get('Index'))
        b = data['Nest2D/Results/%d/thumbnail.emf' % i]
        try:
            h, recs, end = xml_emf.parse(b)
            ok = h['sig'] == 0x464D4520 and h['nbytes'] == len(b) == end and h['nrecords'] == len(recs) and recs[-1][0] == 14 and h['nhandles'] == 5
        except Exception as e:
            ok = False; h = {'err': repr(e)}
        R.check('I1 R%d thumbnail.emf: valid EMF (signature, nBytes, nRecords, EOF last)' % i, ok, '%d B, %s records' % (len(b), h.get('nrecords')))
        if ok:
            zz = zipfile.ZipFile(io.BytesIO(raw))
            Wd, Hd, plate, shapes = xml_emf.result_shapes(zz, i)
            gen = xml_emf.generate(Wd, Hd, shapes, device=tuple(h['device']), mm=tuple(h['mm']), plate=plate)
            c = xml_emf.compare(b, gen)
            R.check('I2 R%d thumbnail = drawing of plate + all contours of the result (regenerated: same records, <=1px)' % i,
                    c['same_record_sequence'] and c['bounds'][0] == c['bounds'][1] and c['frame'][0] == c['frame'][1]
                    and c['non_drawing_records_identical'] and c['max_dev_px'] <= 1,
                    '%d/%d points exact, maxdev %dpx, device %s mm %s' % (c['points_exact'], c['points'], c['max_dev_px'], h['device'], h['mm']))
    return R


def main(argv):
    quiet = '-q' in argv
    paths = [a for a in argv if a != '-q']
    nf = 0
    for p in paths:
        R = validate(p, quiet)
        nf += R.dump(os.path.basename(p))
    print('=' * 100)
    print('OVERALL:', 'PASS' if nf == 0 else 'FAIL (%d)' % nf)
    return 0 if nf == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
