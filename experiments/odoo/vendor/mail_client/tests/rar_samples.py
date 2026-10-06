# -*- coding: utf-8 -*-
# ПРАВКА ПМК (шаг 45б разбора удобства, 06.10.2026) к вендорскому модулю mail_client.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Архивы RAR4 и RAR5, собранные байтами по спецификации, — для тестов шага 45б.

ЗАЧЕМ СВОЙ СБОРЩИК
Программы rar, которая СОЗДАЁТ архивы, на сервере нет (unrar только
распаковывает, а rar — платный), и класть в репозиторий чужие архивы из
почты нельзя: это переписка клиентов. Поэтому архивы собираются здесь, в
памяти, по описанию формата (technote RAR 5.0 и RAR 2.9/3.x):

- заголовки, числа переменной длины (vint), контрольные суммы заголовков
  (CRC32 у RAR5, младшие 16 бит CRC32 у RAR4) и данных;
- имена: RAR5 — всегда UTF-8; RAR4 — как пишет WinRAR (байты OEM, ноль и
  «сжатый» UTF-16), с флагом Unicode в UTF-8, без флага в cp866 (DOS) и
  просто байтами (cp1251 и что угодно);
- папки, «..» и путь от корня, служебные файлы архиваторов, флаг пароля у
  файла, пароль на оглавление, тома (первый и второй), «непрерывный» (solid)
  архив, ссылки и копии (RAR5), комментарий архива (RAR5 и RAR4),
  обрезанный и испорченный архив.

СЖАТЫЕ ФАЙЛЫ БЕЗ АРХИВАТОРА
Файл «без сжатия» система читает сама, без unrar. Чтобы проверить путь через
unrar (сжатый файл обычного архива и «непрерывный» архив), здесь же
собирается настоящий сжатый поток — самый простой из возможных: таблицы
Хаффмана, где каждый байт кодируется сам собой (8 бит), и ни одной ссылки
назад. unrar распаковывает его как любой другой; формат потока описан у
rar5_packed() и rar4_packed().

Модуль без импортов Odoo и без rarfile: им пользуются тесты
(test_step45b_rar.py) и пробы в контейнере.
"""
import struct
import zlib


# ═══════════════════════════════════════════════════════════════════════════
# БИТЫ
# ═══════════════════════════════════════════════════════════════════════════
class _Bits:
    """Запись битов старшим вперёд — так их читает распаковщик RAR."""

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.count = 0

    def put(self, value, width):
        for shift in range(width - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> shift) & 1)
            self.count += 1
            if self.count == 8:
                self.out.append(self.acc)
                self.acc = self.count = 0

    def tail_bits(self):
        """Сколько битов занято в последнем байте (1..8)."""
        return self.count or 8

    def done(self):
        if self.count:
            self.out.append(self.acc << (8 - self.count))
            self.acc = self.count = 0
        return bytes(self.out)


def _crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


# ═══════════════════════════════════════════════════════════════════════════
# RAR5
# ═══════════════════════════════════════════════════════════════════════════
RAR5_SIG = b'Rar!\x1a\x07\x01\x00'

# Флаги блока
R5_EXTRA, R5_DATA, R5_SPLIT_BEFORE, R5_SPLIT_AFTER = 0x01, 0x02, 0x08, 0x10
# Флаги архива (MAIN)
R5_VOLUME, R5_VOLNUMBER, R5_SOLID = 0x01, 0x02, 0x04
# Виды ссылок (запись redir)
R5_SYMLINK, R5_WINLINK, R5_JUNCTION, R5_HARDLINK, R5_COPY = 1, 2, 3, 4, 5


def vint(value):
    """Число переменной длины: по 7 бит, старший бит — «есть ещё байт»."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def rar5_block(htype, hflags, body, extra=b'', data=None):
    """Блок RAR5: CRC32, размер заголовка, тип, флаги, [extra], [данные]."""
    flags = hflags
    if extra:
        flags |= R5_EXTRA
    if data is not None:
        flags |= R5_DATA
    fields = vint(htype) + vint(flags)
    if extra:
        fields += vint(len(extra))
    if data is not None:
        fields += vint(len(data))
    fields += body + extra
    size = vint(len(fields))
    return struct.pack('<I', _crc(size + fields)) + size + fields + (data or b'')


def rar5_main(archive_flags=0, volume=None):
    body = vint(archive_flags)
    if archive_flags & R5_VOLNUMBER:
        body += vint(volume or 0)
    return rar5_block(1, 0, body)


def rar5_packed(data):
    """Сжатый поток RAR5 (способ 1): один блок, каждый байт — свой код.

    Блок: байт флагов (0x80 — есть таблицы, 0x40 — последний блок файла,
    биты 3–4 — длина поля размера минус 1, биты 0–2 — занятых битов в
    последнем байте минус 1), контрольный байт 0x5A ^ флаги ^ байты размера,
    размер блока, затем биты. Таблица длин для таблиц (20 кодов по 4 бита):
    длина 8 — код «0», «20 и больше нулей» (19) — код «1». Затем 430 длин
    (306 основных + 64 + 16 + 44): 256 байтов по 8 бит, остальное нули. Код
    байта при 256 длинах по 8 бит — сам байт, поэтому за таблицами (ровно 44
    байта) идут данные как есть.
    """
    bits = _Bits()
    for symbol in range(20):
        bits.put(1 if symbol in (8, 19) else 0, 4)
    for _ in range(256):
        bits.put(0, 1)                     # длина 8
    for run in (138, 36):                  # 174 нуля = 430 - 256
        bits.put(1, 1)
        bits.put(run - 11, 7)
    for byte in data:
        bits.put(byte, 8)
    tail = bits.tail_bits()
    body = bits.done()
    size = len(body)
    count = 1 if size < 0x100 else 2 if size < 0x10000 else 3
    flags = 0x80 | 0x40 | ((count - 1) << 3) | (tail - 1)
    check = 0x5A ^ flags ^ (size & 0xFF) ^ ((size >> 8) & 0xFF) ^ ((size >> 16) & 0xFF)
    return bytes([flags, check]) + size.to_bytes(count, 'little') + body


def rar5_file(name, data=b'', is_dir=False, mtime=1790000000, encrypted=False,
              block_flags=0, solid=False, packed=False, method=None, declared=None,
              host_os=0, crc=None, version=None, redir=None, htype=2):
    """Запись файла RAR5.

    packed — сжать (rar5_packed), иначе «без сжатия»; method — подменить
    способ в заголовке; declared — подменить распакованный размер; crc —
    подменить контрольную сумму; redir — (вид, цель): ссылка или копия;
    mtime=None — без даты; version — запись старой версии файла (-ver);
    htype=3 — служебная запись того же устройства (rar5_comment).
    """
    raw = name.encode('utf-8') if isinstance(name, str) else name
    payload = rar5_packed(data) if packed and not is_dir else data
    file_flags = (0x01 if is_dir else 0x04) | (0x02 if mtime is not None else 0)
    body = vint(file_flags) + vint(len(data) if declared is None else declared)
    body += vint(0x10 if is_dir else 0x20)
    if mtime is not None:
        body += struct.pack('<I', mtime)
    if file_flags & 0x04:
        body += struct.pack('<I', _crc(data) if crc is None else crc)
    if method is None:
        method = 1 if packed else 0
    comp = (method & 7) << 7
    if solid:
        comp |= 0x40
    body += vint(comp) + vint(host_os) + vint(len(raw)) + raw
    records = []
    if encrypted:
        records.append(vint(0x01) + vint(0) + vint(0) + bytes([15]) + b'S' * 16 + b'I' * 16)
    if version is not None:
        records.append(vint(0x04) + vint(0) + vint(version))
    if redir is not None:
        kind, target = redir
        target = target.encode('utf-8')
        records.append(vint(0x05) + vint(kind) + vint(0) + vint(len(target)) + target)
    extra = b''.join(vint(len(record)) + record for record in records)
    return rar5_block(htype, block_flags, body, extra=extra,
                      data=None if is_dir else payload)


def rar5_comment(text, encrypted=False):
    """Комментарий архива RAR5: служебная запись «CMT» без сжатия (так её
    пишет WinRAR); encrypted — с записью шифрования, как у файла под паролем.
    text — байты как есть: WinRAR пишет UTF-8, другие программы — что угодно."""
    return rar5_file('CMT', text, mtime=None, encrypted=encrypted, htype=3)


def rar5_end(more=False):
    return rar5_block(5, 0, vint(0x01 if more else 0))


def rar5_header_encryption():
    """Блок «оглавление зашифровано» (rar -hp): AES-256, соль."""
    return rar5_block(4, 0, vint(0) + vint(0) + bytes([15]) + b'S' * 16)


def rar5(entries, archive_flags=0, volume=None, more=False):
    """[(имя, байты)] или [(имя, None)] — папка; dict — параметры rar5_file."""
    out = RAR5_SIG + rar5_main(archive_flags, volume)
    for item in entries:
        if isinstance(item, dict):
            out += rar5_file(**item)
        else:
            name, data = item
            out += rar5_file(name, data or b'', is_dir=data is None)
    return out + rar5_end(more)


# ═══════════════════════════════════════════════════════════════════════════
# RAR4 (RAR 2.9 / 3.x)
# ═══════════════════════════════════════════════════════════════════════════
RAR4_SIG = b'Rar!\x1a\x07\x00'

# Флаги архива (MAIN)
R4_VOLUME, R4_SOLID, R4_NEWNUMBERING, R4_PASSWORD, R4_FIRSTVOLUME = 0x01, 0x08, 0x10, 0x80, 0x100
# Флаги файла
R4_SPLIT_BEFORE, R4_SPLIT_AFTER, R4_FILE_PASSWORD, R4_FILE_SOLID = 0x01, 0x02, 0x04, 0x10
R4_UNICODE, R4_LONG = 0x0200, 0x8000
# Флаги конца архива
R4_NEXT_VOLUME = 0x0001


def _rar4_block(htype, flags, body, data=b''):
    size = 7 + len(body)
    head = struct.pack('<BHH', htype, flags, size) + body
    return struct.pack('<H', zlib.crc32(head) & 0xFFFF) + head + data


def rar4_main(flags=0):
    return _rar4_block(0x73, flags, b'\0' * 6)


def dostime(year=2026, month=10, day=1, hour=12, minute=30, second=0):
    return ((year - 1980) << 25) | (month << 21) | (day << 16) | (hour << 11) | (minute << 5) | (second // 2)


def encode_unicode_name(name, oem):
    """Имя как пишет WinRAR: байты OEM, ноль и «сжатый» UTF-16.

    Старший байт 0x04 (кириллица) записан один раз; дальше на каждые четыре
    знака байт флагов (по 2 бита на знак: 0 — младший байт и ноль, 1 —
    младший байт и общий старший, 2 — оба байта) и сами байты.
    """
    high = 0x04
    out = bytearray([high])
    chars = list(name)
    for start in range(0, len(chars), 4):
        group = chars[start:start + 4]
        flags, payload = 0, bytearray()
        for number, char in enumerate(group):
            code = ord(char)
            if code < 0x100:
                mode, payload = 0, payload + bytes([code])
            elif code >> 8 == high:
                mode, payload = 1, payload + bytes([code & 0xFF])
            else:
                mode, payload = 2, payload + bytes([code & 0xFF, code >> 8])
            flags |= mode << (6 - 2 * number)
        out.append(flags)
        out += payload
    return oem + b'\0' + bytes(out)


def rar4_packed(data, last=True):
    """Сжатый поток RAR 2.9 (способ 0x33, распаковщик 29): только байты.

    Бит «не PPM», бит «таблицы не наследовать», 20 длин по 4 бита для таблиц
    (8 — код «0», 9 — «10», «11 и больше нулей» (19) — «11»), затем 404 длины
    (299 основных + 60 + 17 + 28): байты 0–254 по 8 бит, байт 255 и конец
    блока (256) по 9 бит, остальное нули. Код байта b < 255 — сам байт, у
    255 — 9 бит «111111110», конец блока — «111111111». После него «01» —
    «новый файл, таблицы заново»: следующий файл «непрерывного» архива
    начнётся со своих таблиц.
    """
    bits = _Bits()
    bits.put(0, 1)                         # LZ, не PPM
    bits.put(0, 1)                         # старую таблицу не наследовать
    lengths = {8: 1, 9: 2, 19: 2}
    for symbol in range(20):
        bits.put(lengths.get(symbol, 0), 4)
    for _ in range(255):
        bits.put(0b0, 1)                   # длина 8
    for _ in range(2):
        bits.put(0b10, 2)                  # длина 9 (байт 255 и конец блока)
    for run in (136, 11):                  # 147 нулей = 404 - 257
        bits.put(0b11, 2)
        bits.put(run - 11, 7)
    for byte in data:
        if byte == 255:
            bits.put(0b111111110, 9)
        else:
            bits.put(byte, 8)
    bits.put(0b111111111, 9)               # конец блока
    bits.put(0b01, 2)                      # новый файл, новые таблицы
    return bits.done()


def rar4_file(name, data=b'', is_dir=False, encoding='unicode', flags=0, host_os=2,
              method=None, declared=None, crc=None, packed=False, mode=None,
              when=None, htype=0x74):
    """Запись файла RAR4.

    encoding: 'unicode' — как WinRAR (OEM + 0 + UTF-16), 'utf8' — флаг
    Unicode без нуля, 'cp866' и любая кодировка — без флага, bytes — имя
    как есть. packed — сжать (rar4_packed). mode — атрибуты (у ссылки Unix
    — 0o120777 при host_os=3). htype=0x7A — служебная запись (rar4_comment).
    """
    if isinstance(encoding, bytes):
        raw = encoding
    elif encoding == 'unicode':
        raw = encode_unicode_name(name, name.encode('cp866', 'replace'))
        flags |= R4_UNICODE
    elif encoding == 'utf8':
        raw = name.encode('utf-8')
        flags |= R4_UNICODE
    else:
        raw = name.encode(encoding)
    flags |= R4_LONG
    if is_dir:
        flags |= 0x00E0
        data = b''
    payload = rar4_packed(data) if packed and not is_dir else data
    if method is None:
        method = 0x33 if packed else 0x30
    if mode is None:
        mode = 0x10 if is_dir else 0x20
    body = struct.pack('<LLBLLBBHL', len(payload), len(data) if declared is None else declared,
                       host_os, _crc(data) if crc is None else crc, when or dostime(),
                       29, method, len(raw), mode) + raw
    return _rar4_block(htype, flags, body, payload)


def rar4_comment(text, packed=True):
    """Комментарий архива RAR 3.x: служебная запись «CMT» (WinRAR сжимает
    её как файл)."""
    return rar4_file('CMT', text, encoding='latin-1', packed=packed, htype=0x7A)


def rar4_end(flags=0x4000):
    return _rar4_block(0x7B, flags, b'')


def rar4(entries, main_flags=0, end_flags=0x4000):
    out = RAR4_SIG + rar4_main(main_flags)
    for item in entries:
        if isinstance(item, dict):
            out += rar4_file(**item)
        else:
            name, data = item
            out += rar4_file(name, data or b'', is_dir=data is None)
    return out + rar4_end(end_flags)
