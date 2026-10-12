# -*- coding: utf-8 -*-
"""ZIP container of CypCut .lxds: parse -> metadata, rebuild byte-exact, and write NEW archives.

    python3 -I xml_zip.py roundtrip  FILE.lxds [EXTRACTED_DIR]   # parse + rebuild (from own bytes and from extracted dir)
    python3 -I xml_zip.py meta       FILE.lxds                   # print captured metadata (JSON)
    python3 -I xml_zip.py selftest   FILE.lxds ...               # roundtrip all + 'minimal rules' writer check

Container facts (all 5 samples, CypCut 6.3.907.8 / .11):
  * entries are STORED (method 0), general flags 0 (no data descriptor, no UTF-8 bit), no encryption;
  * local header: version needed 10 (file) / 20 (directory), NO extra field;
  * central header: version made by 0x003F (host 0 = MS-DOS, spec 6.3), same needed/flags/method/time/crc/sizes,
    internal attr 0, external attr 0 (also for directories), no comment,
    extra field = NTFS (0x000A) 32 bytes: reserved u32 0, attr tag 1 size 24, Mtime, Atime = 0, Ctime = Mtime;
  * all entries share ONE DOS time/date = local wall-clock time of the save (UTC+10 on the factory PCs),
    seconds rounded UP to even: dos_sec = 2*ceil(t/2); NTFS Mtime = real UTC FILETIME (1 ms resolution),
    increases monotonically along the archive (write order);
  * directory entries ("Name/", size 0, crc 0) precede their files; no gaps, central dir right after the last
    entry, EOCD with no comment, no zip64.
"""
import sys, os, io, json, struct, zlib, math, datetime, hashlib

LFH = struct.Struct('<IHHHHHIIIHH')            # local file header (30 bytes)
CDH = struct.Struct('<IHHHHHHIIIHHHHHII')      # central directory header (46 bytes)
EOCD = struct.Struct('<IHHHHIIH')              # end of central directory (22 bytes)
FILETIME_EPOCH = datetime.datetime(1601, 1, 1)


class ZipFormatError(Exception):
    pass


def parse(raw):
    """bytes -> (entries, archive_meta). Each entry: dict(name, data, + every header field). Strict: any
    structure CypCut did not produce in the samples raises ZipFormatError instead of being silently lost."""
    e = raw.rfind(b'PK\x05\x06')
    if e < 0:
        raise ZipFormatError('no EOCD')
    sig, disk, cddisk, n_this, n_tot, cd_size, cd_off, clen = EOCD.unpack_from(raw, e)
    comment = raw[e + 22:e + 22 + clen]
    if e + 22 + clen != len(raw):
        raise ZipFormatError('trailing bytes after EOCD')
    entries, p, expect_lho = [], cd_off, 0
    for i in range(n_tot):
        f = CDH.unpack_from(raw, p)
        (csig, made, need, flags, meth, t, d, crc, csz, usz, fnl, exl, cml, dsk, iattr, eattr, lho) = f
        if csig != 0x02014B50:
            raise ZipFormatError('bad CD signature')
        name_b = raw[p + 46:p + 46 + fnl]
        cextra = raw[p + 46 + fnl:p + 46 + fnl + exl]
        ccomment = raw[p + 46 + fnl + exl:p + 46 + fnl + exl + cml]
        p += 46 + fnl + exl + cml
        l = LFH.unpack_from(raw, lho)
        (lsig, lneed, lflags, lmeth, lt, ld, lcrc, lcsz, lusz, lfnl, lexl) = l
        if lsig != 0x04034B50:
            raise ZipFormatError('bad LFH signature')
        lname = raw[lho + 30:lho + 30 + lfnl]
        lextra = raw[lho + 30 + lfnl:lho + 30 + lfnl + lexl]
        dstart = lho + 30 + lfnl + lexl
        data = raw[dstart:dstart + csz]
        if meth != 0:
            raise ZipFormatError('method %d (only STORED seen)' % meth)
        if flags & 8:
            raise ZipFormatError('data descriptor not supported')
        entries.append(dict(
            name=name_b.decode('cp437' if not flags & 0x800 else 'utf-8'), name_raw=name_b.hex(), data=data,
            gap_before=lho - expect_lho,
            version_made=made, version_needed=need, flags=flags, method=meth, dos_time=t, dos_date=d,
            crc=crc, csize=csz, usize=usz, disk=dsk, int_attr=iattr, ext_attr=eattr,
            central_extra=cextra.hex(), central_comment=ccomment.hex(),
            local=dict(version_needed=lneed, flags=lflags, method=lmeth, dos_time=lt, dos_date=ld, crc=lcrc,
                       csize=lcsz, usize=lusz, name_same=(lname == name_b)), local_extra=lextra.hex()))
        expect_lho = dstart + csz
    meta = dict(cd_gap=cd_off - expect_lho, cd_size=cd_size, eocd_gap=e - p, disk=disk, cddisk=cddisk,
                n_this=n_this, comment=comment.hex())
    return entries, meta


def build(entries, meta):
    """(entries, archive_meta) -> bytes. Inverse of parse(); every captured field is written back."""
    out = io.BytesIO()
    lhos = []
    for en in entries:
        out.write(b'\0' * en['gap_before'])
        lhos.append(out.tell())
        loc = en['local']
        name_b = bytes.fromhex(en['name_raw'])
        lextra = bytes.fromhex(en['local_extra'])
        out.write(LFH.pack(0x04034B50, loc['version_needed'], loc['flags'], loc['method'], loc['dos_time'],
                           loc['dos_date'], loc['crc'], loc['csize'], loc['usize'], len(name_b), len(lextra)))
        out.write(name_b); out.write(lextra); out.write(en['data'])
    out.write(b'\0' * meta['cd_gap'])
    cd_off = out.tell()
    for en, lho in zip(entries, lhos):
        name_b = bytes.fromhex(en['name_raw'])
        cextra = bytes.fromhex(en['central_extra']); ccom = bytes.fromhex(en['central_comment'])
        out.write(CDH.pack(0x02014B50, en['version_made'], en['version_needed'], en['flags'], en['method'],
                           en['dos_time'], en['dos_date'], en['crc'], en['csize'], en['usize'], len(name_b),
                           len(cextra), len(ccom), en['disk'], en['int_attr'], en['ext_attr'], lho))
        out.write(name_b); out.write(cextra); out.write(ccom)
    cd_size = out.tell() - cd_off
    out.write(b'\0' * meta['eocd_gap'])
    com = bytes.fromhex(meta['comment'])
    out.write(EOCD.pack(0x06054B50, meta['disk'], meta['cddisk'], meta['n_this'], len(entries), cd_size, cd_off, len(com)))
    out.write(com)
    return out.getvalue()


def metadata_only(entries, meta):
    """JSON-able metadata without file data (what we must 'capture' to rebuild from extracted files)."""
    ents = [{k: v for k, v in en.items() if k != 'data'} for en in entries]
    return dict(archive=meta, entries=ents)


def rebuild_from_dir(md, root):
    """Rebuild archive from an extracted directory + captured metadata (data comes from the files)."""
    entries = []
    for en in md['entries']:
        e = dict(en)
        if en['name'].endswith('/'):
            e['data'] = b''
        else:
            with open(os.path.join(root, *en['name'].split('/')), 'rb') as f:
                e['data'] = f.read()
            if zlib.crc32(e['data']) != en['crc']:
                raise ZipFormatError('extracted file differs (crc): ' + en['name'])
        entries.append(e)
    return build(entries, md['archive'])


# ------------------------------------------------------------------ writing NEW archives (minimal rules)
def filetime(dt_utc):
    """datetime (UTC, naive) -> FILETIME (100 ns since 1601), truncated to 1 ms like CypCut."""
    us = (dt_utc - FILETIME_EPOCH) // datetime.timedelta(microseconds=1)
    return (us // 1000) * 10000


def dos_datetime(local_dt):
    """local wall-clock datetime -> (dos_time, dos_date); seconds rounded UP to even (as in all samples)."""
    sec = local_dt.second + local_dt.microsecond / 1e6
    two = math.ceil(sec / 2)
    base = local_dt.replace(second=0, microsecond=0) + datetime.timedelta(seconds=2 * two)
    t = (base.hour << 11) | (base.minute << 5) | (base.second // 2)
    d = ((base.year - 1980) << 9) | (base.month << 5) | base.day
    return t, d


def ntfs_extra(ft):
    return struct.pack('<HHIHHQQQ', 0x000A, 32, 0, 1, 24, ft, 0, ft)


def canonical_order(storages):
    """storages: dict {folder path ('' = root): {stream name: bytes}} -> flat (name, data) list the way CypCut
    lays it out: every folder is ONE flat block 'Folder/' + its own streams; folders are NOT nested blocks
    (e.g. 'Nest2D/Results/1/' may precede 'Nest2D/Results/'). Root streams first. Inside a folder the
    streams go in the order given (CypCut: data.bin before content.xml, content.xml before thumbnail.emf).
    Folder order: the one seen in m3_grpsh/m8_plates/m30 (CypCut's own order is hash-like, not reproducible)."""
    pref = ['', 'TextStyles', 'Technical', 'Layers', 'Nest2D', 'Nest2D/Results/*', 'Viewports', 'Shapes2D',
            'Nest2D/Parts', 'Blocks', 'Nest2D/Parts/Groups', 'Nest2D/Plates', 'Nest2D/Results', 'Geometry2D']
    def key(folder):
        if folder.startswith('Nest2D/Results/') and folder != 'Nest2D/Results':
            return (pref.index('Nest2D/Results/*'), int(folder.rsplit('/', 1)[1]))
        return (pref.index(folder) if folder in pref else len(pref), 0)
    out = []
    for folder in sorted(storages, key=key):
        if folder:
            out.append((folder + '/', b''))
        for fn, data in storages[folder].items():
            out.append(((folder + '/' if folder else '') + fn, data))
    return out


def write_new(seq, save_utc, utc_offset_hours=10, mtimes=None):
    """seq: list of (name, bytes) in archive order, INCLUDING directory entries 'Folder/' (b'') -- see
    canonical_order(). save_utc: naive UTC datetime of the save; mtimes: optional per-entry FILETIMEs
    (default: all = save time). Returns bytes of a .lxds container following every rule observed in
    CypCut 6.3.907 (see module docstring)."""
    t, d = dos_datetime(save_utc + datetime.timedelta(hours=utc_offset_hours))
    ft0 = filetime(save_utc)
    entries = []
    for i, (name, data) in enumerate(seq):
        isdir = name.endswith('/')
        if isdir and data:
            raise ValueError('directory entry with data: ' + name)
        ft = mtimes[i] if mtimes else ft0
        crc = zlib.crc32(data) & 0xffffffff
        need = 20 if isdir else 10
        name_hex = name.encode('ascii').hex()          # CypCut names are ASCII; no UTF-8 flag is ever set
        entries.append(dict(name=name, name_raw=name_hex, data=data, gap_before=0, version_made=0x003F,
                            version_needed=need, flags=0, method=0, dos_time=t, dos_date=d, crc=crc,
                            csize=len(data), usize=len(data), disk=0, int_attr=0, ext_attr=0,
                            central_extra=ntfs_extra(ft).hex(), central_comment='',
                            local=dict(version_needed=need, flags=0, method=0, dos_time=t, dos_date=d, crc=crc,
                                       csize=len(data), usize=len(data), name_same=True), local_extra=''))
    return build(entries, dict(cd_gap=0, cd_size=0, eocd_gap=0, disk=0, cddisk=0, n_this=len(entries), comment=''))


def _ntfs_mtime(en):
    ex = bytes.fromhex(en['central_extra'])
    return struct.unpack_from('<Q', ex, 12)[0]


def check_minimal_rules(raw):
    """Re-create the archive with write_new() using only: file order, file data, per-entry NTFS mtime, and
    the save moment derived from the first mtime. Returns (identical?, n_diff_bytes)."""
    entries, meta = parse(raw)
    seq = [(e['name'], e['data']) for e in entries]
    mt = [_ntfs_mtime(e) for e in entries]
    save_utc = FILETIME_EPOCH + datetime.timedelta(microseconds=mt[0] // 10)
    new = write_new(seq, save_utc, 10, mtimes=mt)
    n = sum(1 for a, b in zip(new, raw) if a != b) + abs(len(new) - len(raw))
    return new == raw, n


def describe(entries, meta):
    rules = dict(
        all_stored=all(e['method'] == 0 for e in entries),
        flags_zero=all(e['flags'] == 0 and e['local']['flags'] == 0 for e in entries),
        made_0x3F=all(e['version_made'] == 0x3F for e in entries),
        need_10_file_20_dir=all(e['version_needed'] == (20 if e['name'].endswith('/') else 10) for e in entries),
        local_eq_central=all(e['local']['version_needed'] == e['version_needed'] and e['local']['dos_time'] == e['dos_time']
                             and e['local']['dos_date'] == e['dos_date'] and e['local']['crc'] == e['crc']
                             and e['local']['csize'] == e['csize'] and e['local']['usize'] == e['usize']
                             and e['local']['name_same'] for e in entries),
        no_local_extra=all(e['local_extra'] == '' for e in entries),
        central_extra_ntfs32=all(e['central_extra'][:24] == '0a00200000000000' + '01001800' and len(e['central_extra']) == 72
                                 for e in entries),
        ntfs_atime0_ctime_eq_mtime=all(bytes.fromhex(e['central_extra'])[20:28] == b'\0' * 8 and
                                       bytes.fromhex(e['central_extra'])[12:20] == bytes.fromhex(e['central_extra'])[28:36]
                                       for e in entries),
        attrs_zero=all(e['int_attr'] == 0 and e['ext_attr'] == 0 for e in entries),
        one_dos_time=len({(e['dos_time'], e['dos_date']) for e in entries}) == 1,
        no_gaps=all(e['gap_before'] == 0 for e in entries) and meta['cd_gap'] == 0 and meta['eocd_gap'] == 0,
        no_comments=meta['comment'] == '' and all(e['central_comment'] == '' for e in entries),
        folder_blocks=all(  # each file directly follows its own folder entry or a sibling file
            ('/' not in e['name'] and all('/' not in x['name'] for x in entries[:i])) or
            (entries[i - 1]['name'] == e['name'].rsplit('/', 1)[0] + '/' or
             (not entries[i - 1]['name'].endswith('/') and entries[i - 1]['name'].rsplit('/', 1)[0] == e['name'].rsplit('/', 1)[0]))
            for i, e in enumerate(entries) if not e['name'].endswith('/')),
        mtime_monotonic=all(_ntfs_mtime(entries[i]) <= _ntfs_mtime(entries[i + 1]) for i in range(len(entries) - 1)),
    )
    return rules


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd, args = argv[0], argv[1:]
    if cmd == 'meta':
        raw = open(args[0], 'rb').read()
        print(json.dumps(metadata_only(*parse(raw)), indent=1)); return 0
    if cmd in ('roundtrip', 'selftest'):
        allok = True
        paths = args if cmd == 'selftest' else args[:1]
        for path in paths:
            raw = open(path, 'rb').read()
            entries, meta = parse(raw)
            out = build(entries, meta)
            ndiff = sum(1 for a, b in zip(out, raw) if a != b) + abs(len(out) - len(raw))
            line = '%-16s %8d B, %2d entries: parse->build %s (diff bytes %d)' % (
                os.path.basename(path), len(raw), len(entries), 'IDENTICAL' if out == raw else 'DIFFERENT', ndiff)
            allok &= out == raw
            xdir = args[1] if cmd == 'roundtrip' and len(args) > 1 else \
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), 'x', os.path.splitext(os.path.basename(path))[0])
            if os.path.isdir(xdir):
                md = json.loads(json.dumps(metadata_only(entries, meta)))  # through JSON = really 'captured'
                out2 = rebuild_from_dir(md, xdir)
                nd2 = sum(1 for a, b in zip(out2, raw) if a != b) + abs(len(out2) - len(raw))
                line += '; extracted-dir+meta->build %s (diff %d)' % ('IDENTICAL' if out2 == raw else 'DIFFERENT', nd2)
                allok &= out2 == raw
            if cmd == 'selftest':
                ok3, nd3 = check_minimal_rules(raw)
                line += '; minimal-rules writer %s (diff %d)' % ('IDENTICAL' if ok3 else 'DIFFERENT', nd3)
                allok &= ok3
                r = describe(entries, meta)
                bad = [k for k, v in r.items() if not v]
                line += '; rules: %s' % ('all hold' if not bad else 'FAIL ' + ','.join(bad))
                allok &= not bad
            print(line)
        print('RESULT:', 'PASS' if allok else 'FAIL')
        return 0 if allok else 1
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
