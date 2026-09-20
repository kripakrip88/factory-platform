# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Modified UTF-7 codec for IMAP mailbox names (RFC 3501 section 5.1.3).

SOGo and mobile clients happily create folders named "Entwürfe", "Papierkorb"
or "Arsip Terkirim". Those arrive over the wire as modified UTF-7 and must be
converted, otherwise folder names show up mangled and SELECT fails.
"""
import binascii


def _b64_encode(chunk):
    encoded = binascii.b2a_base64(chunk.encode('utf-16-be')).decode('ascii').rstrip('\n=')
    return encoded.replace('/', ',')


def _b64_decode(chunk):
    padding = '=' * ((4 - len(chunk) % 4) % 4)
    data = (chunk.replace(',', '/') + padding).encode('ascii')
    return binascii.a2b_base64(data).decode('utf-16-be')


def imap_utf7_encode(name):
    """Encode a Python string into an IMAP mailbox name (returns str)."""
    if isinstance(name, bytes):
        name = name.decode('ascii')
    result = []
    buffer = []

    def flush():
        if buffer:
            result.append('&' + _b64_encode(''.join(buffer)) + '-')
            buffer.clear()

    for char in name:
        ordinal = ord(char)
        if char == '&':
            flush()
            result.append('&-')
        elif 0x20 <= ordinal <= 0x7E:
            flush()
            result.append(char)
        else:
            buffer.append(char)
    flush()
    return ''.join(result)


def imap_utf7_decode(name):
    """Decode an IMAP mailbox name into a Python string."""
    if isinstance(name, (bytes, bytearray)):
        name = bytes(name).decode('ascii', errors='replace')
    result = []
    buffer = []
    in_shift = False

    for char in name:
        if in_shift:
            if char == '-':
                if buffer:
                    try:
                        result.append(_b64_decode(''.join(buffer)))
                    except (binascii.Error, UnicodeDecodeError):
                        # Malformed name: keep it visible rather than crashing sync.
                        result.append('&' + ''.join(buffer) + '-')
                else:
                    result.append('&')
                buffer = []
                in_shift = False
            else:
                buffer.append(char)
        elif char == '&':
            in_shift = True
        else:
            result.append(char)

    if in_shift:  # unterminated shift sequence
        result.append('&' + ''.join(buffer))
    return ''.join(result)
