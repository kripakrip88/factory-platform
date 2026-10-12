# -*- coding: utf-8 -*-
"""CypCut .lxds XML documents: parse -> model -> serialize (byte-exact) + number formatting rules.

    python3 -I xml_model.py FILE.lxds ...     # round-trip every *.xml entry of every archive, report diffs

Model = nested Node(tag, attrs [ordered list of (name, value)], text, children). The serializer reproduces
CypCut's writer exactly:
  * b'<?xml version="1.0" encoding="utf-8"?>' + CRLF, no BOM, UTF-8 text (Cyrillic raw, no char refs);
  * one element per line, indentation = one TAB per depth, line end CRLF, also after the root end tag;
  * element without children and without text -> '<Tag a="1"/>' (no space before '/>');
  * element with text only -> '<Tag>text</Tag>' on one line; element with children -> open tag line,
    children, '</Tag>' line; mixed content never occurs;
  * attribute order is significant and kept as written; values in double quotes;
  * no entity/char references occur in any sample, so escaping of & < > " is UNKNOWN; serializer escapes
    them the standard way (& -> &amp; < -> &lt; > -> &gt; " -> &quot;) -- writers should avoid these chars.
Numbers (all 27 378 numeric values in the samples): fmt_num() == '%.9g' with the leading zero dropped
('.5', '-.5'); integers plain; zero/default attributes are usually OMITTED (see report).
"""
import sys, os, zipfile
import xml.etree.ElementTree as ET

DECL = b'<?xml version="1.0" encoding="utf-8"?>\r\n'


class Node:
    __slots__ = ('tag', 'attrs', 'text', 'children')

    def __init__(self, tag, attrs=None, text=None, children=None):
        self.tag = tag
        self.attrs = list(attrs or [])
        self.text = text
        self.children = list(children or [])

    def get(self, k, default=None):
        for a, v in self.attrs:
            if a == k:
                return v
        return default

    def set(self, k, v):
        for i, (a, _) in enumerate(self.attrs):
            if a == k:
                self.attrs[i] = (k, v); return
        self.attrs.append((k, v))

    def find(self, tag):
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def findall(self, tag):
        return [c for c in self.children if c.tag == tag]

    def findtext(self, tag, default=None):
        c = self.find(tag)
        return c.text if c is not None and c.text is not None else default

    def iter(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for c in self.children:
            yield from c.iter(tag)


def fmt_num(x):
    """CypCut number format: integers as int, otherwise '%.9g' without the leading zero."""
    if isinstance(x, int):
        return str(x)
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    s = '%.9g' % x
    if 'e' in s:
        raise ValueError('exponent form never seen in CypCut XML: %r' % x)
    if s.startswith('0.'):
        s = s[1:]
    elif s.startswith('-0.'):
        s = '-' + s[2:]
    return s


def _esc(s, attr):
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return s.replace('"', '&quot;') if attr else s


def parse(raw, strict=True):
    if strict and not raw.startswith(DECL):
        raise ValueError('unexpected XML declaration')
    def conv(e):
        t = e.text
        if t is not None and not t.strip() and len(e):
            t = None                      # pure indentation
        if len(e) and t is not None:
            if strict:
                raise ValueError('mixed content in <%s>' % e.tag)
            t = None
        return Node(e.tag, list(e.attrib.items()), t, [conv(c) for c in e])
    return conv(ET.fromstring(raw))


def serialize(root):
    out = [DECL]
    def w(n, depth):
        ind = b'\t' * depth
        a = ''.join(' %s="%s"' % (k, _esc(v, True)) for k, v in n.attrs)
        if n.children:
            out.append(ind + ('<%s%s>' % (n.tag, a)).encode('utf-8') + b'\r\n')
            for c in n.children:
                w(c, depth + 1)
            out.append(ind + ('</%s>' % n.tag).encode('utf-8') + b'\r\n')
        elif n.text is not None and n.text != '':
            out.append(ind + ('<%s%s>%s</%s>' % (n.tag, a, _esc(n.text, False), n.tag)).encode('utf-8') + b'\r\n')
        else:
            out.append(ind + ('<%s%s/>' % (n.tag, a)).encode('utf-8') + b'\r\n')
    w(root, 0)
    return b''.join(out)


def roundtrip_archive(path):
    z = zipfile.ZipFile(path)
    res = []
    for n in z.namelist():
        if not n.endswith('.xml'):
            continue
        raw = z.read(n)
        out = serialize(parse(raw))
        nd = sum(1 for a, b in zip(out, raw) if a != b) + abs(len(out) - len(raw))
        res.append((n, len(raw), out == raw, nd))
    return res


if __name__ == '__main__':
    tot = ok = 0
    for path in sys.argv[1:]:
        r = roundtrip_archive(path)
        bad = [x for x in r if not x[2]]
        tot += len(r); ok += len(r) - len(bad)
        print('%-16s %2d XML entries, %8d bytes: %d identical, %d different %s' % (
            os.path.basename(path), len(r), sum(x[1] for x in r), len(r) - len(bad), len(bad),
            ['%s (diff %d B)' % (x[0], x[3]) for x in bad]))
    print('TOTAL: %d/%d XML entries byte-identical -> %s' % (ok, tot, 'PASS' if ok == tot else 'FAIL'))
