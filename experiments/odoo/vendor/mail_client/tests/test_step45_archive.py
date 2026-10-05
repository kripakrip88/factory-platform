# -*- coding: utf-8 -*-
"""ПРАВКА ПМК (шаг 45 разбора удобства, 05.10.2026): просмотр архивов ZIP и RAR.

Все архивы собираются здесь же, в памяти: имена в cp866 (Проводник, WinRAR,
7-Zip под русской Windows), в UTF-8 с флагом и без, с полем «Unicode Path»;
вложенные папки, «..» и путь от корня диска; служебные файлы архиваторов;
«бомба» по коэффициенту, поддельный размер (deflate и bzip2), словарь LZMA
на 4 ГБ, наложение записей, зашифрованный, повреждённый, обрезанный, 5001
файл, подделанный конец архива (метки Zip64 без записи Zip64, край окна
поиска); архив без сжатия с PDF первым, книга ODS со сжатым mimetype.

- TestArchiveReader — tools/archive_reader.py без базы (имена, пути, пределы,
  отказы, книги Excel/OpenDocument);
- TestArchivePreview — preview()/price_scan() с member, вид строк списка,
  RAR, документы Office — не архив, права;
- TestArchiveRoute — маршрут /mail_client/attachment/<id>/member/<n>:
  заголовки, ?download=1, чужой ящик, отказы кодами.

Гонять на одноразовой базе:
    odoo -d mc_test -i mail_client --test-enable \\
         --test-tags /mail_client:TestArchiveReader,/mail_client:TestArchivePreview,/mail_client:TestArchiveRoute \\
         --stop-after-init
"""
import bz2
import io
import lzma
import struct
import tracemalloc
import zipfile
import zlib
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.mail_client.models.mail_client_attachment_preview import detect_format, title_of
from odoo.addons.mail_client.tools import archive_reader as ar
from odoo.addons.mail_client.tools.archive_reader import ArchiveError

DATE = (2026, 10, 1, 12, 30, 0)


# ═══════════════════════════════════════════════════════════════════════════
# Сборка архивов
# ═══════════════════════════════════════════════════════════════════════════
def make_zip(entries, method=zipfile.ZIP_DEFLATED):
    """[(имя, байты[, дата])] — архив, как его пишет сам Python (UTF-8 с флагом)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        for item in entries:
            info = zipfile.ZipInfo(item[0], item[2] if len(item) > 2 else DATE)
            info.compress_type = method
            archive.writestr(info, item[1])
    return buf.getvalue()


def raw_name_zip(entries, unicode_path=None, method=zipfile.ZIP_DEFLATED):
    """[(байты имени, данные)] — имя пишется байтами как есть, БЕЗ флага UTF-8.

    Так пишут Проводник Windows и WinRAR. zipfile сам так не умеет: пишем
    латинскую заглушку той же длины и подменяем её байты в обоих заголовках.
    unicode_path — {байты имени: строка} для поля Info-ZIP 0x7075.
    """
    holders, buf = [], io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        for number, (raw, data) in enumerate(entries):
            holder = ('Q%03d' % number).ljust(len(raw), 'x').encode('ascii')
            assert len(holder) == len(raw), raw
            holders.append((holder, raw))
            info = zipfile.ZipInfo(holder.decode('ascii'), DATE)
            info.compress_type = method
            if unicode_path and raw in unicode_path:
                body = struct.pack('<BL', 1, zlib.crc32(raw)) + unicode_path[raw].encode('utf-8')
                info.extra = struct.pack('<HH', 0x7075, len(body)) + body
            archive.writestr(info, data)
    blob = buf.getvalue()
    for holder, raw in holders:
        assert blob.count(holder) == 2, holder
        blob = blob.replace(holder, raw)
    return blob


def cd_offsets(blob):
    """Начала записей центрального оглавления."""
    pos = blob.rfind(b'PK\x05\x06')
    count, _size, start = struct.unpack('<HII', blob[pos + 10:pos + 20])
    out, at = [], start
    for _ in range(count):
        out.append(at)
        name_len, extra_len, comment_len = struct.unpack('<HHH', blob[at + 28:at + 34])
        at += 46 + name_len + extra_len + comment_len
    return out


def local_offset(blob, number):
    return struct.unpack('<I', blob[cd_offsets(blob)[number] + 42:cd_offsets(blob)[number] + 46])[0]


def patch_bytes(blob, at, fmt, value):
    out = bytearray(blob)
    struct.pack_into(fmt, out, at, value)
    return bytes(out)


def set_flag(blob, number, flag, local=True, central=True):
    if central:
        at = cd_offsets(blob)[number] + 8
        blob = patch_bytes(blob, at, '<H', struct.unpack('<H', blob[at:at + 2])[0] | flag)
    if local:
        at = local_offset(blob, number) + 6
        blob = patch_bytes(blob, at, '<H', struct.unpack('<H', blob[at:at + 2])[0] | flag)
    return blob


def set_declared_size(blob, number, size):
    blob = patch_bytes(blob, cd_offsets(blob)[number] + 24, '<I', size)
    return patch_bytes(blob, local_offset(blob, number) + 22, '<I', size)


def tiny_pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>']
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    out += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(out)


def tiny_png():
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00'))
            + chunk(b'IEND', b''))


def tiny_xlsx():
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Металл'
    sheet.append(['Наименование', 'Цена, руб'])
    sheet.append(['Труба 40х40х2', 1000])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


CSV = 'Наименование;Цена\nТруба 40х40х2;1000\nЛист 3 мм;2000\n'.encode('cp1251')

ODS_MIMETYPE = b'application/vnd.oasis.opendocument.spreadsheet'
ODS_CONTENT = (
    '<office:document-content'
    ' xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
    '<office:body><office:spreadsheet><table:table table:name="Металл">'
    '<table:table-row><table:table-cell><text:p>Наименование</text:p></table:table-cell>'
    '<table:table-cell><text:p>Цена</text:p></table:table-cell></table:table-row>'
    '<table:table-row><table:table-cell><text:p>Труба 40х40х2</text:p></table:table-cell>'
    '<table:table-cell office:value="1000"><text:p>1000</text:p></table:table-cell></table:table-row>'
    '</table:table></office:spreadsheet></office:body></office:document-content>'
).encode('utf-8')


def end_record_at(blob):
    """Начало записи конца архива (EOCD) у архива без комментария."""
    pos = len(blob) - 22
    assert blob[pos:pos + 4] == b'PK\x05\x06'
    return pos


def lzma_dict_at(blob, number=0):
    """Где в архиве лежат 4 байта размера словаря LZMA у записи number."""
    at = local_offset(blob, number)
    name_len, extra_len = struct.unpack('<HH', blob[at + 26:at + 30])
    # 2 байта версии, 2 байта длины свойств, байт lc/lp/pb, затем словарь.
    return at + 30 + name_len + extra_len + 5


# ═══════════════════════════════════════════════════════════════════════════
# 1. Чтение архива без базы
# ═══════════════════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestArchiveReader(TransactionCase):

    def _names(self, blob):
        return [entry['path'] for entry in ar.list_zip(blob)['entries']]

    # --- имена ---------------------------------------------------------------
    def test_names_cp866_utf8_and_unicode_path(self):
        cp866 = 'Счёт №5 смета.pdf'.encode('cp866')
        utf8 = 'Расчёт.xlsx'.encode('utf-8')
        mixed = 'Акт сверки.pdf'.encode('cp866')
        garbage = b'\xb0\xb1\xff.txt'
        blob = raw_name_zip([(cp866, b'1'), (utf8, b'2'), (mixed, b'3'), (garbage, b'4'),
                             (b'plain.txt', b'5')],
                            unicode_path={mixed: 'Акт сверки (подписан).pdf'})
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            self.assertFalse(any(info.flag_bits & 0x800 for info in archive.infolist()),
                             "посылка: флага UTF-8 нет, как у Проводника")
        names = set(self._names(blob))
        self.assertIn('Счёт №5 смета.pdf', names, "cp866 без флага — русские буквы")
        self.assertIn('Расчёт.xlsx', names, "UTF-8 без флага (macOS, Linux)")
        self.assertIn('Акт сверки (подписан).pdf', names, "поле Unicode Path главнее байтов")
        self.assertIn(garbage.decode('cp437'), names, "запасной путь — cp437 как есть")
        self.assertIn('plain.txt', names)

    def test_name_with_utf8_flag_as_is(self):
        blob = make_zip([('Чертежи/Узел 1.pdf', b'%PDF-1.4')])
        entry = ar.list_zip(blob)['entries'][0]
        self.assertEqual((entry['dir'], entry['name']), ('Чертежи', 'Узел 1.pdf'))

    def test_unicode_path_with_wrong_crc_is_ignored(self):
        raw = 'Акт.pdf'.encode('cp866')
        blob = raw_name_zip([(raw, b'1')], unicode_path={raw: 'Чужое.pdf'})
        at = cd_offsets(blob)[0]
        name_len, = struct.unpack('<H', blob[at + 28:at + 30])
        extra_at = at + 46 + name_len
        blob = patch_bytes(blob, extra_at + 5, '<L', zlib.crc32(b'other'))
        self.assertEqual(self._names(blob), ['Акт.pdf'])

    # --- пути ----------------------------------------------------------------
    def test_paths_up_root_drive_and_bidi(self):
        blob = make_zip([('../../etc/Счёт.pdf', b'1'), ('/abs/y.pdf', b'2'),
                         ('C:\\Windows\\z.pdf', b'3'), ('Папка\\Вложенная\\w.pdf', b'4'),
                         ('счёт\u202efdp.exe', b'5'), ('\x07звонок.pdf', b'6')])
        entries = {entry['name']: entry for entry in ar.list_zip(blob)['entries']}
        self.assertEqual(entries['Счёт.pdf']['path'], 'etc/Счёт.pdf')
        self.assertEqual(entries['Счёт.pdf']['warn'], ar.WARN_UP)
        self.assertEqual(entries['y.pdf']['warn'], ar.WARN_ROOT)
        self.assertEqual((entries['z.pdf']['dir'], entries['z.pdf']['warn']), ('Windows', ar.WARN_ROOT))
        self.assertEqual((entries['w.pdf']['dir'], entries['w.pdf']['warn']), ('Папка/Вложенная', ''))
        self.assertIn('счётfdp.exe', entries, "символ смены направления вычищен")
        self.assertIn('звонок.pdf', entries, "управляющий символ вычищен")
        # «..» ничего не значит для чтения: байты — в память, по номеру.
        data, entry = ar.read_zip_member(blob, entries['Счёт.pdf']['index'])
        self.assertEqual((data, entry['name']), (b'1', 'Счёт.pdf'))

    # --- список --------------------------------------------------------------
    def test_listing_sorting_dirs_junk_dates(self):
        blob = make_zip([
            ('Лист 10.pdf', b'a'), ('Лист 2.pdf', b'b'), ('лист 1.pdf', b'c'),
            ('Папка/', b''), ('Папка/Подпапка/b.pdf', b'd'), ('Папка/a.pdf', b'e'),
            ('__MACOSX/._Лист 2.pdf', b'f'), ('.DS_Store', b'g'), ('Папка/Thumbs.db', b'h'),
            ('старый.txt', b'i', (1980, 1, 1, 0, 0, 0)),
        ])
        listing = ar.list_zip(blob)
        self.assertEqual([entry['path'] for entry in listing['entries']], [
            'лист 1.pdf', 'Лист 2.pdf', 'Лист 10.pdf', 'старый.txt',
            'Папка/a.pdf', 'Папка/Подпапка/b.pdf'])
        self.assertEqual((listing['total'], listing['hidden'], listing['encrypted']), (6, 3, 0))
        self.assertEqual(listing['size'], 6)
        first = listing['entries'][0]
        self.assertEqual((first['date'], first['size'], first['reason']), ('01.10.2026 12:30', 1, ''))
        self.assertEqual(listing['entries'][3]['date'], '', "01.01.1980 — даты нет")
        self.assertEqual(listing['notes'], [])

    def test_empty_archive(self):
        blob = make_zip([])
        self.assertEqual(ar.archive_format(blob), 'zip')
        self.assertEqual(ar.list_zip(blob)['total'], 0)

    def test_list_is_capped(self):
        blob = make_zip([('%d.txt' % number, b'x') for number in range(5)])
        with patch.object(ar, 'LIST_ROWS', 3):
            listing = ar.list_zip(blob)
        self.assertEqual((len(listing['entries']), listing['total']), (3, 5))
        self.assertIn('Показано файлов: 3 из 5.', listing['notes'])

    # --- чтение одного файла -------------------------------------------------
    def test_read_every_supported_method(self):
        data = ('Труба 40х40х2;1000\n' * 2000).encode('utf-8')
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(method=method):
                blob = make_zip([('прайс.csv', data)], method=method)
                payload, entry = ar.read_zip_member(blob, 0)
                self.assertEqual(payload, data)
                self.assertEqual((entry['name'], entry['size']), ('прайс.csv', len(data)))

    def test_bad_index_and_folder(self):
        blob = make_zip([('Папка/', b''), ('Папка/a.pdf', b'1')])
        for index in (-1, 2, '1', None, True):
            with self.subTest(index=index), self.assertRaises(ArchiveError) as caught:
                ar.read_zip_member(blob, index)
            self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(blob, 0)
        self.assertEqual(caught.exception.status, 404)

    # --- отказы --------------------------------------------------------------
    def test_encrypted(self):
        blob = set_flag(make_zip([('Договор.pdf', b'%PDF-1.4 secret')]), 0, 0x1)
        listing = ar.list_zip(blob)
        self.assertEqual(listing['entries'][0]['reason'], 'закрыт паролем')
        self.assertEqual(listing['encrypted'], 1)
        self.assertIn('Архив закрыт паролем', listing['notes'][0])
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(blob, 0)
        self.assertIn('закрыт паролем', str(caught.exception))
        self.assertEqual(caught.exception.status, 422)

    def test_encrypted_only_in_local_header(self):
        blob = set_flag(make_zip([('a.pdf', b'1'), ('b.pdf', b'2')]), 1, 0x1, central=False)
        self.assertEqual(ar.list_zip(blob)['encrypted'], 0, "посылка: оглавление чистое")
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(blob, 1)
        self.assertIn('паролем', str(caught.exception))
        listing = ar.list_zip(set_flag(make_zip([('a.pdf', b'1'), ('b.pdf', b'2')]), 1, 0x1))
        self.assertIn('Файлов под паролем: 1', listing['notes'][0])

    def test_unknown_method(self):
        blob = make_zip([('a.pdf', b'%PDF-1.4' * 10)])
        blob = patch_bytes(blob, cd_offsets(blob)[0] + 10, '<H', 99)        # AES и т. п.
        self.assertEqual(ar.list_zip(blob)['entries'][0]['reason'], 'сжат неизвестным способом')
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(blob, 0)
        self.assertIn('способом', str(caught.exception))

    def test_ratio_bomb(self):
        blob = make_zip([('нули.bin', b'\0' * (20 * 1024 * 1024))])
        reason = ar.list_zip(blob)['entries'][0]['reason']
        self.assertTrue(reason.startswith('сжат в '), reason)
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(blob, 0)
        self.assertEqual(caught.exception.status, 413)
        self.assertIn('бомб', str(caught.exception))

    def test_times_in_russian(self):
        self.assertEqual([ar._times(n) for n in (100, 1023, 1012, 1001, 104, 114)],
                         ['100 раз', '1023 раза', '1012 раз', '1001 раз', '104 раза', '114 раз'])

    def test_member_over_limit(self):
        blob = make_zip([('большой.csv', b'1;2;3\n' * 1000)], method=zipfile.ZIP_STORED)
        with patch.object(ar, 'MEMBER_MAX_BYTES', 1000):
            self.assertTrue(ar.list_zip(blob)['entries'][0]['reason'].startswith('больше'))
            with self.assertRaises(ArchiveError) as caught:
                ar.read_zip_member(blob, 0)
        self.assertEqual(caught.exception.status, 413)

    def test_forged_size_stops_unpacking(self):
        """Заявлено 1000 байт, внутри 2 МБ (deflate) и 64 МБ нулей (bzip2):
        распаковка встаёт на 1001-м байте, а не после всего файла."""
        cases = (
            (zipfile.ZIP_DEFLATED, b'1;2;3\n' * 350000),
            (zipfile.ZIP_BZIP2, b'\0' * (64 * 1024 * 1024)),
        )
        for method, data in cases:
            with self.subTest(method=method):
                blob = set_declared_size(make_zip([('z.csv', data)], method=method), 0, 1000)
                self.assertEqual(ar.list_zip(blob)['entries'][0]['reason'], '',
                                 "посылка: по оглавлению файл честный")
                tracemalloc.start()
                try:
                    with self.assertRaises(ArchiveError) as caught:
                        ar.read_zip_member(blob, 0)
                    _now, peak = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                self.assertEqual(caught.exception.status, 413)
                self.assertIn('больше заявленного', str(caught.exception))
                self.assertLess(peak, 16 * 1024 * 1024, "память не выросла до размера бомбы")

    def test_lzma_huge_dictionary(self):
        """Словарь LZMA на 4 ГБ в свойствах записи: распаковщик получает
        словарь не больше файла, и файл читается байт в байт."""
        data = ('Труба 40х40х2;1000\n' * 500).encode('utf-8')
        blob = make_zip([('прайс.csv', data)], method=zipfile.ZIP_LZMA)
        forged = patch_bytes(blob, lzma_dict_at(blob), '<I', 0xFFFFFFFF)
        with patch.object(ar.lzma, 'LZMADecompressor', wraps=lzma.LZMADecompressor) as spy:
            payload, _entry = ar.read_zip_member(forged, 0)
        self.assertEqual(payload, data)
        dict_size = spy.call_args.kwargs['filters'][0]['dict_size']
        self.assertLessEqual(dict_size, max(len(data) + 1, ar.LZMA_DICT_FLOOR))

    def test_memory_error_answers_in_words(self):
        blob = make_zip([('a.csv', b'1;2;3\n' * 100)])
        with patch.object(ar, '_unpack', side_effect=MemoryError):
            with self.assertRaises(ArchiveError) as caught:
                ar.read_zip_member(blob, 0)
        self.assertEqual(caught.exception.status, 413)
        self.assertIn('не хватило памяти', str(caught.exception))

    def test_overlapping_entries(self):
        blob = make_zip([('a.txt', b'hello' * 100), ('b.txt', b'world' * 100)])
        forged = patch_bytes(blob, cd_offsets(blob)[1] + 42, '<I', 0)
        for call in (ar.list_zip, lambda b: ar.read_zip_member(b, 1)):
            with self.assertRaises(ArchiveError) as caught:
                call(forged)
            self.assertIn('наложены', str(caught.exception))

    def test_too_many_files_checked_before_parsing(self):
        blob = make_zip([('%d.txt' % number, b'') for number in range(ar.MAX_ENTRIES + 1)],
                        method=zipfile.ZIP_STORED)
        with patch.object(ar.zipfile, 'ZipFile', side_effect=AssertionError("оглавление разобрано")):
            with self.assertRaises(ArchiveError) as caught:
                ar.list_zip(blob)
        self.assertEqual(caught.exception.status, 413)
        self.assertIn('Файлов в архиве: 5001', str(caught.exception))
        # Число записей в конце архива подделано — пересчёт по факту.
        pos = blob.rfind(b'PK\x05\x06')
        forged = patch_bytes(patch_bytes(blob, pos + 8, '<H', 1), pos + 10, '<H', 1)
        with self.assertRaises(ArchiveError) as caught:
            ar.list_zip(forged)
        self.assertEqual(caught.exception.status, 413)

    def test_zipfile_end_record_api(self):
        """Конец архива ищет функция самого zipfile. Пропадёт она при
        обновлении Python — архивы перестанут открываться, а этот тест
        скажет почему."""
        self.assertIs(ar._END_RECORD, zipfile._EndRecData)
        self.assertEqual((ar._ECD_ENTRIES_TOTAL, ar._ECD_SIZE),
                         (zipfile._ECD_ENTRIES_TOTAL, zipfile._ECD_SIZE))

    def test_forged_end_record_checked_before_parsing(self):
        """Метки Zip64 без записи Zip64 и конец архива на краю окна поиска:
        числа берутся так же, как их возьмёт zipfile, и отказ — до разбора
        оглавления (zipfile разбирал бы его по 32-битному размеру)."""
        blob = make_zip([('a.txt', b'1'), ('b.txt', b'2')])
        pos = end_record_at(blob)
        five_mb = 5 * 1024 * 1024
        cases = {
            # Число записей 0xFFFF — «смотри Zip64», а записи Zip64 нет.
            'записей 0xFFFF': (patch_bytes(patch_bytes(blob, pos + 8, '<H', 0xFFFF),
                                           pos + 10, '<H', 0xFFFF), 'Файлов в архиве: 65535'),
            # Смещение 0xFFFFFFFF и огромное оглавление: zipfile сам вычислил
            # бы начало оглавления от конца архива.
            'смещение 0xFFFFFFFF': (patch_bytes(patch_bytes(blob, pos + 16, '<I', 0xFFFFFFFF),
                                                pos + 12, '<I', five_mb), 'Оглавление архива весит 5,0 МБ'),
            # Размер 0xFFFFFFFF без Zip64 — 4 ГБ оглавления.
            'размер 0xFFFFFFFF': (patch_bytes(blob, pos + 12, '<I', 0xFFFFFFFF), 'Оглавление архива весит 4,0 ГБ'),
            # Конец архива ровно на filesize - 65558: комментарий 65535 байт и
            # ещё байт хвоста. Свой поиск не дотягивался сюда на байт, а
            # zipfile находит.
            'край окна': (patch_bytes(blob, pos + 12, '<I', five_mb)[:pos + 20]
                          + struct.pack('<H', 0xFFFF) + b'x' * 0xFFFF + b'\0',
                          'Оглавление архива весит 5,0 МБ'),
        }
        for name, (forged, words) in cases.items():
            with self.subTest(case=name):
                with patch.object(ar.zipfile, 'ZipFile', side_effect=AssertionError("оглавление разобрано")):
                    with self.assertRaises(ArchiveError) as caught:
                        ar.list_zip(forged)
                self.assertEqual(caught.exception.status, 413)
                self.assertIn(words, str(caught.exception))
        # Честный архив с комментарием на 65535 байт и байтом хвоста zipfile
        # открывает — значит, и список есть.
        honest = blob[:pos + 20] + struct.pack('<H', 0xFFFF) + b'x' * 0xFFFF + b'\0'
        self.assertEqual(self._names(honest), ['a.txt', 'b.txt'])

    def test_broken_archives(self):
        good = make_zip([('a.csv', b'1;2;3\n' * 1000)])
        for name, blob in (('обрезан', good[:-30]), ('мусор', b'PK\x03\x04' + b'\x00' * 100)):
            with self.subTest(case=name), self.assertRaises(ArchiveError) as caught:
                ar.list_zip(blob)
            self.assertIn('повреждён', str(caught.exception))

    def test_corrupt_member(self):
        good = make_zip([('a.csv', b'1;2;3;4;5;6\n' * 5000)])
        # Первый байт потока deflate: последний блок неизвестного вида (11).
        broken = patch_bytes(good, 30 + len('a.csv'), '<B', 0x07)
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(broken, 0)
        self.assertIn('повреждён', str(caught.exception))
        stored = make_zip([('b.txt', b'hello')], method=zipfile.ZIP_STORED)
        wrong_crc = patch_bytes(stored, cd_offsets(stored)[0] + 16, '<I', 12345)
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(wrong_crc, 0)
        self.assertIn('контрольная сумма', str(caught.exception))
        renamed = stored.replace(b'b.txt', b'c.txt', 1)            # только локальный заголовок
        with self.assertRaises(ArchiveError) as caught:
            ar.read_zip_member(renamed, 0)
        self.assertIn('повреждён', str(caught.exception))

    def test_formats(self):
        self.assertEqual(ar.archive_format(b'Rar!\x1a\x07\x00rest'), 'rar')
        self.assertEqual(ar.archive_format(b'Rar!\x1a\x07\x01\x00rest'), 'rar')
        self.assertEqual(ar.archive_format(b'7z\xbc\xaf\x27\x1crest'), '7z')
        self.assertIsNone(ar.archive_format(b'%PDF-1.4'))

    # --- книги Excel и OpenDocument -------------------------------------------
    def test_check_book(self):
        book = tiny_xlsx()
        self.assertIsNone(ar.check_book(book), "честная книга проходит")
        with zipfile.ZipFile(io.BytesIO(book)) as archive:
            parts = [(info.filename, archive.read(info)) for info in archive.infolist()]
        self.assertIn('сжата необычным способом',
                      ar.check_book(make_zip(parts, method=zipfile.ZIP_BZIP2)))
        with patch.object(ar, 'BOOK_MAX_UNPACKED', 100):
            self.assertIn('больше предела', ar.check_book(book))
        self.assertEqual(ar.check_book(b'PK\x03\x04' + b'\0' * 50), "Книга повреждена и не открывается.")

    def test_read_part_head(self):
        """mimetype книги OpenDocument — и без сжатия (как велит стандарт), и
        сжатый (нестрогие программы); больше потолка — не читается."""
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(method=method):
                book = make_zip([('mimetype', ODS_MIMETYPE), ('content.xml', b'<x/>')], method=method)
                self.assertEqual(ar.read_part_head(book, 'mimetype', 100), ODS_MIMETYPE)
        self.assertIsNone(ar.read_part_head(make_zip([('content.xml', b'<x/>')]), 'mimetype', 100))
        long_part = make_zip([('mimetype', b'a' * 5000)])
        self.assertIsNone(ar.read_part_head(long_part, 'mimetype', 100),
                          "сжатая часть длиннее потолка не распаковывается дальше него")
        locked = set_flag(make_zip([('mimetype', ODS_MIMETYPE)]), 0, 0x1)
        self.assertIsNone(ar.read_part_head(locked, 'mimetype', 100))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Окно просмотра: preview() и price_scan() с файлом из архива
# ═══════════════════════════════════════════════════════════════════════════
class _MailboxMixin:

    @classmethod
    def _mailbox(cls, user):
        cls.server = cls.env['mail.client.server'].create({
            'name': 'mailcow', 'imap_host': 'mail.example.org',
            'auth_mode': 'master', 'master_user': 'master',
        })
        cls.account = cls.env['mail.client.account'].create({
            'name': 'Заказы', 'email': 'zakaz@example.org',
            'server_id': cls.server.id, 'user_id': user.id,
        })
        cls.folder = cls.env['mail.client.folder'].create({
            'name': 'INBOX', 'account_id': cls.account.id, 'imap_path': 'INBOX', 'role': 'inbox',
        })
        cls.message = cls.env['mail.client.message'].create({
            'account_id': cls.account.id, 'folder_id': cls.folder.id, 'imap_uid': 45,
            'subject': 'Чертежи по заказу', 'email_from': 'client@firm.ru',
        })
        cls.part = 1

    @classmethod
    def _attach(cls, name, blob, content_type='application/zip'):
        """Вложение, уже скачанное в Odoo: IMAP в тестах не нужен."""
        cls.part += 1
        stored = cls.env['ir.attachment'].sudo().create({
            'name': name, 'raw': blob, 'res_model': 'mail.client.message', 'res_id': cls.message.id,
        })
        return cls.env['mail.client.attachment'].sudo().create({
            'message_id': cls.message.id, 'name': name, 'part_number': str(cls.part),
            'content_type': content_type, 'encoding': '', 'file_size': len(blob),
            'attachment_id': stored.id, 'state': 'fetched',
        })

    @classmethod
    def _order_zip(cls):
        """Архив «как от клиента»: русские имена в cp866, папки, вложенный
        архив, чертёж DWG, файл под паролем и «бомба»."""
        inner = make_zip([('a.txt', b'1')])
        files = [
            ('Чертёж узла.pdf', tiny_pdf()), ('Схема.png', tiny_png()),
            ('Прайс/Металл.csv', CSV), ('Прайс/Книга.xlsx', tiny_xlsx()),
            ('Старое.zip', inner), ('Сборка.dwg', b'AC1032' + b'\0' * 64),
            ('Договор.pdf', tiny_pdf()), ('нули.bin', b'\0' * (2 * 1024 * 1024)),
            ('../../Счёт.pdf', tiny_pdf()),
        ]
        blob = raw_name_zip([(name.encode('cp866'), data) for name, data in files])
        return set_flag(blob, 6, 0x1)          # «Договор.pdf» под паролем


@tagged('post_install', '-at_install')
class TestArchivePreview(_MailboxMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._mailbox(cls.env.user)
        cls.Attachment = cls.env['mail.client.attachment']
        cls.order = cls._attach('Заказ 45.zip', cls._order_zip())

    def _entries(self, payload):
        return {entry['path']: entry for entry in payload['archive']['entries']}

    def test_archive_is_listed(self):
        payload = self.Attachment.preview(self.order.id)
        self.assertEqual((payload['kind'], payload['format'], payload['format_title']),
                         ('archive', 'zip', 'архив ZIP'))
        entries = self._entries(payload)
        kinds = {path: entry['kind'] for path, entry in entries.items()}
        self.assertEqual(kinds, {
            'Чертёж узла.pdf': 'pdf', 'Схема.png': 'image', 'Прайс/Металл.csv': 'sheet',
            'Прайс/Книга.xlsx': 'sheet', 'Старое.zip': 'archive', 'Сборка.dwg': 'other',
            'Договор.pdf': 'pdf', 'нули.bin': 'other', 'Счёт.pdf': 'pdf',
        })
        self.assertEqual(entries['Договор.pdf']['reason'], 'закрыт паролем')
        self.assertTrue(entries['нули.bin']['reason'].startswith('сжат в '))
        self.assertEqual(entries['Счёт.pdf']['warn'], 'путь вёл за пределы архива')
        self.assertIn('Файлов под паролем: 1', payload['archive']['notes'][0])

    def test_member_pdf_image_sheet(self):
        entries = self._entries(self.Attachment.preview(self.order.id))
        pdf = entries['Чертёж узла.pdf']
        payload = self.Attachment.preview(self.order.id, member=pdf['index'])
        url = '/mail_client/attachment/%d/member/%d' % (self.order.id, pdf['index'])
        self.assertEqual((payload['kind'], payload['name'], payload['archive_name']),
                         ('pdf', 'Чертёж узла.pdf', 'Заказ 45.zip'))
        self.assertEqual((payload['url'], payload['download_url']), (url, url + '?download=1'))
        self.assertEqual(payload['member'], {'index': pdf['index'], 'path': 'Чертёж узла.pdf'})
        self.assertEqual(payload['pages'], 1)

        image = self.Attachment.preview(self.order.id, member=entries['Схема.png']['index'])
        self.assertEqual((image['kind'], image['width'], image['height']), ('image', 1, 1))

        csv_index = entries['Прайс/Металл.csv']['index']
        sheet = self.Attachment.preview(self.order.id, member=csv_index)
        self.assertEqual(sheet['kind'], 'sheet')
        self.assertEqual(sheet['sheets'][0]['rows'][0][0], 'Труба 40х40х2')
        more = self.Attachment.preview(self.order.id, member=csv_index, sheet=0, offset=1)
        self.assertEqual(more['sheets'][0]['rows'][0][0], 'Лист 3 мм', "«Показать ещё» у файла архива")
        scan = self.Attachment.price_scan(self.order.id, sheet=0, member=csv_index)
        self.assertTrue(scan['is_price'])

        book = self.Attachment.preview(self.order.id, member=entries['Прайс/Книга.xlsx']['index'])
        self.assertEqual((book['kind'], book['sheets'][0]['name']), ('sheet', 'Металл'))

    def test_member_refusals(self):
        entries = self._entries(self.Attachment.preview(self.order.id))
        nested = self.Attachment.preview(self.order.id, member=entries['Старое.zip']['index'])
        self.assertEqual(nested['kind'], 'none')
        self.assertIn('архив внутри архива', nested['reason'])
        for path, words in (('Договор.pdf', 'закрыт паролем'), ('нули.bin', 'бомб')):
            with self.subTest(path=path):
                payload = self.Attachment.preview(self.order.id, member=entries[path]['index'])
                self.assertEqual(payload['kind'], 'none')
                self.assertIn(words, payload['reason'])
                self.assertEqual((payload['url'], payload['download_url']), ('', ''),
                                 "не прочитанный файл не скачать — и не скачать вместо него архив")
        dwg = self.Attachment.preview(self.order.id, member=entries['Сборка.dwg']['index'])
        self.assertEqual(dwg['kind'], 'none')
        self.assertTrue(dwg['download_url'].endswith('?download=1'), "непоказываемое — скачать")
        missing = self.Attachment.preview(self.order.id, member=999)
        self.assertEqual(missing['kind'], 'none')
        self.assertIn('нет такого файла', missing['reason'])

    def test_member_of_something_else(self):
        book = self._attach('Прайс.xlsx', tiny_xlsx(), 'application/octet-stream')
        payload = self.Attachment.preview(book.id)
        self.assertEqual(payload['kind'], 'sheet', "книга Excel — таблица, не архив")
        refused = self.Attachment.preview(book.id, member=0)
        self.assertEqual(refused['kind'], 'none')
        self.assertIn('не архив ZIP', refused['reason'])

    def test_office_documents_are_not_archives(self):
        pptx = make_zip([('[Content_Types].xml', b'<Types/>'), ('ppt/presentation.xml', b'<p/>')])
        odt = make_zip([('mimetype', b'application/vnd.oasis.opendocument.text'),
                        ('content.xml', b'<x/>')], method=zipfile.ZIP_STORED)
        for name, blob, title in (('Презентация.pptx', pptx, 'документ Microsoft Office'),
                                  ('Письмо.odt', odt, 'документ OpenDocument')):
            with self.subTest(name=name):
                payload = self.Attachment.preview(self._attach(name, blob).id)
                self.assertEqual((payload['kind'], payload['format_title']), ('none', title))
                self.assertIsNone(payload['archive'])

    def test_rar_and_7z(self):
        for name, blob, label in (('Чертежи.rar', b'Rar!\x1a\x07\x01\x00' + b'\0' * 64, 'RAR'),
                                  ('Чертежи.7z', b'7z\xbc\xaf\x27\x1c' + b'\0' * 64, '7z')):
            with self.subTest(name=name):
                payload = self.Attachment.preview(self._attach(name, blob).id)
                self.assertEqual(payload['kind'], 'none')
                self.assertEqual(payload['reason'],
                                 'Просмотр архивов %s пока недоступен — скачайте архив.' % label)
        renamed = self.Attachment.preview(self._attach('Чертежи.rar', make_zip([('a.pdf', b'1')])).id)
        self.assertEqual(renamed['kind'], 'archive', "назван .rar, а внутри ZIP — показываем")
        self.assertIn('архив ZIP', renamed['note'])

    def test_broken_and_huge_archives_answer_in_words(self):
        broken = self.Attachment.preview(self._attach('Битый.zip', make_zip([('a.csv', b'1;2\n' * 500)])[:-30]).id)
        self.assertEqual(broken['kind'], 'none')
        self.assertIn('повреждён', broken['reason'])
        many = make_zip([('%d.txt' % n, b'') for n in range(ar.MAX_ENTRIES + 1)], method=zipfile.ZIP_STORED)
        payload = self.Attachment.preview(self._attach('Много.zip', many).id)
        self.assertEqual(payload['kind'], 'none')
        self.assertIn('5001', payload['reason'])

    def test_book_bomb_is_refused(self):
        with zipfile.ZipFile(io.BytesIO(tiny_xlsx())) as archive:
            parts = [(info.filename, archive.read(info)) for info in archive.infolist()]
        bomb = self._attach('Прайс.xlsx', make_zip(parts, method=zipfile.ZIP_BZIP2))
        payload = self.Attachment.preview(bomb.id)
        self.assertEqual(payload['kind'], 'none')
        self.assertIn('Книга сжата необычным способом', payload['reason'])

    def test_stored_archive_with_pdf_first_is_archive(self):
        """Архив без сжатия: байты первого PDF лежат в нём как есть, и %PDF-
        стоит в первом килобайте. Это всё равно архив, а не PDF."""
        blob = make_zip([('Чертёж КМД.pdf', tiny_pdf()), ('Спецификация.csv', CSV)],
                        method=zipfile.ZIP_STORED)
        self.assertIn(b'%PDF-', blob[:1024], "посылка: PDF в первом килобайте")
        self.assertEqual(detect_format(blob, 'Заказ.zip'), ('zip', 'archive', ''))
        payload = self.Attachment.preview(self._attach('Заказ.zip', blob).id)
        self.assertEqual(payload['kind'], 'archive')
        self.assertEqual(len(payload['archive']['entries']), 2)
        rar = b'Rar!\x1a\x07\x01\x00' + b'\0' * 40 + tiny_pdf()
        self.assertEqual(detect_format(rar, 'Чертежи.rar')[0], 'rar', "RAR с несжатым PDF — RAR")
        self.assertEqual(detect_format(b'\r\n' + tiny_pdf(), 'Счёт.pdf')[0], 'pdf',
                         "мусор перед %PDF- — по-прежнему PDF")

    def test_ods_with_compressed_mimetype_is_sheet(self):
        """Нестрогий генератор сжал mimetype — книга остаётся таблицей."""
        book = make_zip([('mimetype', ODS_MIMETYPE), ('content.xml', ODS_CONTENT),
                         ('META-INF/manifest.xml', b'<manifest/>')])
        self.assertEqual(detect_format(book, 'Прайс.ods'), ('ods', 'sheet', ''))
        payload = self.Attachment.preview(self._attach('Прайс.ods', book).id)
        self.assertEqual(payload['kind'], 'sheet')
        self.assertEqual(payload['sheets'][0]['rows'][0][0], 'Труба 40х40х2')

    def test_unknown_file_title_in_words(self):
        """Под заголовком окна — «файл DWG», а не «application/octet-stream»."""
        cases = (('КМД.dwg', 'файл DWG'), ('Модель.step', 'файл STEP'),
                 ('без расширения', 'файл'), ('чертёж.чрт', 'файл'))
        for name, title in cases:
            with self.subTest(name=name):
                payload = self.Attachment.preview(
                    self._attach(name, b'AC1032' + b'\0' * 64, 'application/octet-stream').id)
                self.assertEqual((payload['kind'], payload['format_title']), ('none', title))
        self.assertEqual(title_of('pdf', 'x.dwg'), 'документ PDF', "опознанный — по содержимому")

    def test_foreign_mailbox(self):
        stranger = new_test_user(self.env, login='mc45_stranger',
                                 groups='base.group_user,mail_client.group_mail_client_user')
        with self.assertRaises(AccessError):
            self.Attachment.with_user(stranger).preview(self.order.id, member=0)
        with self.assertRaises(AccessError):
            self.Attachment.with_user(stranger).price_scan(self.order.id, member=0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Маршрут файла из архива
# ═══════════════════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestArchiveRoute(_MailboxMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'mc45-route-pass'
        cls.owner = new_test_user(cls.env, login='mc45_owner', password=cls.password,
                                  groups='base.group_user,mail_client.group_mail_client_user')
        cls.stranger = new_test_user(cls.env, login='mc45_other', password=cls.password,
                                     groups='base.group_user,mail_client.group_mail_client_user')
        cls._mailbox(cls.owner)
        cls.order = cls._attach('Заказ 45.zip', cls._order_zip())
        cls.entries = {entry['path']: entry['index'] for entry in cls.env['mail.client.attachment']
                       .preview(cls.order.id)['archive']['entries']}

    def _get(self, index, query=''):
        return self.url_open('/mail_client/attachment/%d/member/%d%s' % (self.order.id, index, query))

    def test_pdf_image_and_download(self):
        self.authenticate(self.owner.login, self.password)
        pdf = self._get(self.entries['Чертёж узла.pdf'])
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.content, tiny_pdf())
        self.assertEqual(pdf.headers['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.headers['Content-Disposition'].startswith('attachment'))
        self.assertEqual(pdf.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', pdf.headers['Content-Security-Policy'])
        self.assertIn('no-store', pdf.headers['Cache-Control'])

        image = self._get(self.entries['Схема.png'])
        self.assertEqual((image.headers['Content-Type'], image.headers['Content-Disposition'][:6]),
                         ('image/png', 'inline'))

        saved = self._get(self.entries['Счёт.pdf'], '?download=1')
        self.assertEqual(saved.headers['Content-Type'], 'application/octet-stream')
        disposition = saved.headers['Content-Disposition']
        self.assertTrue(disposition.startswith('attachment'))
        self.assertIn("UTF-8''%D0%A1%D1%87%D1%91%D1%82.pdf", disposition, "имя без «../..»")

        raw = self.url_open('/mail_client/attachment/%d/raw' % self.order.id)
        self.assertEqual((raw.status_code, raw.headers['Content-Type']), (200, 'application/octet-stream'))

    def test_refusals_by_status(self):
        self.authenticate(self.owner.login, self.password)
        self.assertEqual(self._get(999).status_code, 404)
        locked = self._get(self.entries['Договор.pdf'])
        self.assertEqual(locked.status_code, 422)
        self.assertIn('закрыт паролем', locked.text)
        self.assertEqual(self._get(self.entries['нули.bin']).status_code, 413)

    def test_foreign_mailbox_is_not_found(self):
        self.authenticate(self.stranger.login, self.password)
        self.assertEqual(self._get(self.entries['Чертёж узла.pdf']).status_code, 404)
