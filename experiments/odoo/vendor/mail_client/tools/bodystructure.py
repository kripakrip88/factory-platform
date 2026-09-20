# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Parser for the IMAP BODYSTRUCTURE response (RFC 3501 section 7.4.2).

This is what makes attachments cheap. BODYSTRUCTURE describes every MIME part
of a message - type, size, filename, and its part number - without
transferring a single byte of content. Armed with the part number the client
can then ask for exactly one part (``BODY.PEEK[2]``) instead of downloading a
20 MB message to read a two-line reply.

This is what makes body-on-demand practical: the attachment list can be
shown from the structure alone, and only the part the user clicks is fetched.
"""
from email.header import decode_header, make_header
from email.utils import collapse_rfc2231_value

NIL = object()

# Content types that are part of the message body rather than an attachment,
# unless the server explicitly marks them with a disposition of "attachment".
_INLINE_TYPES = {('text', 'plain'), ('text', 'html')}


class BodyStructureError(Exception):
    pass


def _tokenize(data):
    """Yield tokens from a parenthesised IMAP list."""
    index, length = 0, len(data)
    while index < length:
        char = data[index:index + 1]
        if char in b' \t\r\n':
            index += 1
        elif char in b'()':
            yield char.decode()
            index += 1
        elif char == b'"':
            index += 1
            chunk = bytearray()
            while index < length:
                current = data[index:index + 1]
                if current == b'\\' and index + 1 < length:
                    chunk += data[index + 1:index + 2]
                    index += 2
                    continue
                if current == b'"':
                    index += 1
                    break
                chunk += current
                index += 1
            yield bytes(chunk)
        elif char == b'{':
            end = data.find(b'}', index)
            if end == -1:
                raise BodyStructureError("Unterminated literal")
            try:
                size = int(data[index + 1:end])
            except ValueError as exc:
                raise BodyStructureError("Unreadable literal length") from exc
            start = end + 1
            # The bound is not decoration. Past the end of the buffer the slice
            # is b'', and `b'' in b'\r\n'` is True, so without it a response
            # truncated right after "{9}" spins here for ever - which hangs the
            # sync worker on a pegged core rather than failing the folder.
            while start < length and data[start:start + 1] in b'\r\n':
                start += 1
            if start + size > length:
                raise BodyStructureError("Literal runs past the end of the response")
            yield data[start:start + size]
            index = start + size
        else:
            end = index
            while end < length and data[end:end + 1] not in b' \t\r\n()':
                end += 1
            atom = data[index:end]
            yield NIL if atom.upper() == b'NIL' else atom
            index = end


def _build(tokens):
    """Turn a token stream into nested Python lists."""
    root = []
    stack = [root]
    for token in tokens:
        if token == '(':
            nested = []
            stack[-1].append(nested)
            stack.append(nested)
        elif token == ')':
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(token)
    if len(root) == 1 and isinstance(root[0], list):
        return root[0]
    return root


def parse(data):
    """Parse a raw BODYSTRUCTURE payload into nested lists."""
    if isinstance(data, str):
        data = data.encode()
    start = data.find(b'(')
    if start == -1:
        raise BodyStructureError("No BODYSTRUCTURE found in response")
    return _build(_tokenize(data[start:]))


def _text(value):
    if value is NIL or value is None:
        return ''
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode('utf-8', errors='replace')
    return str(value)


def _decode_filename(raw):
    """Decode a filename that may use RFC 2047 or RFC 2231 encoding."""
    if not raw:
        return ''
    try:
        value = collapse_rfc2231_value(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        value = raw
    try:
        return str(make_header(decode_header(value))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return value.strip()


def _pairs(values):
    """Convert an IMAP parameter list into a lowercase-keyed dict."""
    result = {}
    if not isinstance(values, list):
        return result
    for index in range(0, len(values) - 1, 2):
        key = _text(values[index]).lower()
        result[key] = _text(values[index + 1])
    return result


def _walk(node, prefix, parts):
    """Recursively collect leaf parts, numbering them as IMAP does."""
    if not isinstance(node, list) or not node:
        return

    if isinstance(node[0], list):
        # Multipart: the child parts come first, then the subtype string, then
        # the parameter list. Only the lists *before* the subtype are children -
        # the parameter list after it is not a MIME part.
        subtype_index = next(
            (i for i, item in enumerate(node) if not isinstance(item, list)), len(node)
        )
        for number, child in enumerate(node[:subtype_index], start=1):
            child_prefix = f"{prefix}.{number}" if prefix else str(number)
            _walk(child, child_prefix, parts)
        return

    # Single part: (type subtype params id description encoding size ...)
    maintype = _text(node[0]).lower()
    subtype = _text(node[1]).lower() if len(node) > 1 else ''
    params = _pairs(node[2]) if len(node) > 2 else {}
    encoding = _text(node[5]).lower() if len(node) > 5 else ''
    try:
        # Length-checked like every other index here: a truncated response can
        # tokenize into a short node, and an IndexError would escape as
        # something no caller catches.
        size = int(_text(node[6]) or 0) if len(node) > 6 else 0
    except ValueError:
        size = 0

    # The disposition sits at a different index for text parts (which carry an
    # extra line-count field) than for everything else.
    disposition_index = 9 if maintype == 'text' else 8
    if maintype == 'message' and subtype == 'rfc822':
        disposition_index = 11
    disposition, disposition_params = '', {}
    if len(node) > disposition_index and isinstance(node[disposition_index], list):
        block = node[disposition_index]
        if block:
            disposition = _text(block[0]).lower()
            disposition_params = _pairs(block[1]) if len(block) > 1 else {}

    filename = _decode_filename(
        disposition_params.get('filename') or params.get('name') or ''
    )
    content_id = _text(node[3]).strip('<>') if len(node) > 3 else ''

    if disposition == 'attachment':
        is_attachment = True
    elif disposition == 'inline':
        # An inline part carrying a Content-ID is referenced from the HTML by
        # cid: - a signature logo, say - and belongs to the body. Without one
        # it is an ordinary attachment that the sender happened to mark inline,
        # which Outlook does routinely.
        is_attachment = bool(filename) and not content_id
    else:
        # No disposition at all: a filename is the only hint we have.
        is_attachment = bool(filename) and (maintype, subtype) not in _INLINE_TYPES

    parts.append({
        'part_number': prefix or '1',
        'content_type': f"{maintype}/{subtype}" if subtype else maintype,
        'maintype': maintype,
        'subtype': subtype,
        'encoding': encoding,
        'size': size,
        'charset': params.get('charset', ''),
        'filename': filename,
        'disposition': disposition,
        'content_id': content_id,
        'is_attachment': is_attachment,
    })


def parse_parts(data):
    """Return a flat list of MIME parts described by a BODYSTRUCTURE."""
    tree = parse(data)
    parts = []
    _walk(tree, '', parts)
    return parts


def pick_body_parts(parts):
    """Return ``(html_part, text_part)`` - the parts to render as the body."""
    html_part = text_part = None
    for part in parts:
        if part['is_attachment']:
            continue
        if part['content_type'] == 'text/html' and html_part is None:
            html_part = part
        elif part['content_type'] == 'text/plain' and text_part is None:
            text_part = part
    return html_part, text_part


def attachments(parts):
    """Return only the parts a user would consider a real attachment."""
    return [part for part in parts if part['is_attachment']]
