# -*- coding: utf-8 -*-
"""ПРАВКА ПМК (шаг 45б разбора удобства, 06.10.2026): просмотр архивов RAR.

Архивы собираются здесь же байтами по спецификации (tests/rar_samples.py):
программы, которая СОЗДАЁТ RAR, на сервере нет, а чужие архивы из почты в
репозиторий не кладём. RAR5 и RAR4; «без сжатия» и настоящий сжатый поток
(каждый байт — свой код Хаффмана), обычный и «непрерывный» (solid); имена
WinRAR (OEM + UTF-16), UTF-8, cp866 и cp1251 без флага; папки, «..» и путь
от корня, служебные файлы; пароль на файл и на оглавление; тома; ссылки и
копии (копия открывается байтами оригинала); комментарий архива любой
кодировки и под паролем; одинаковые имена и имена DOS, которые rarfile
сводил в одно; порча контрольной суммы, поддельный размер, обрезанный и
битый архив; 5001 файл и оглавление больше 4 МБ; срок; нет rarfile или
unrar.

- TestRarReader — tools/archive_reader.list_rar / read_rar_member без базы
  (настоящие rarfile и unrar отдельным процессом; без них — пропуск, кроме
  проверок отказа «недоступен»);
- TestRarPreview — preview()/price_scan() с member у вложения RAR;
- TestRarDrawing — чертёж DXF из RAR окном pmk_drawing (без модуля — пропуск);
- TestRarRoute — маршрут /mail_client/attachment/<id>/member/<n> для RAR.

Гонять на одноразовой базе образом odoo-ru:19.0-20261006 (в нём rarfile 4.5
и unrar):
    odoo -d mc_test -i mail_client,pmk_drawing --test-enable \\
         --test-tags /mail_client:TestRarReader,/mail_client:TestRarPreview,/mail_client:TestRarDrawing,/mail_client:TestRarRoute \\
         --stop-after-init
"""
import os
import shutil
import stat
import tempfile
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.mail_client.tools import archive_reader as ar
from odoo.addons.mail_client.tools.archive_reader import ArchiveError

from . import rar_samples as rs
from .test_step45_archive import CSV, _MailboxMixin, make_zip, tiny_pdf, tiny_png
from .test_step46_drawing import DXF_R12

PDF = tiny_pdf()
PNG = tiny_png()
# Байты всех значений, включая 255 (у RAR4 у него свой 9-битный код).
MIXED = bytes(range(256)) * 4 + ('Чертёж узла 1 — лист 2'.encode('utf-8')) * 30
# 1790000000 — 21.09.2026 14:13:20 UTC = 22.09.2026 00:13 во Владивостоке.
VLADIVOSTOK = 'Asia/Vladivostok'


def _order_rar5():
    """Архив «как от клиента», RAR5: папки, русские имена, служебные файлы,
    «..» и путь от корня, пароль, вложенный архив, сжатый файл."""
    return rs.rar5([
        ('Чертежи', None),
        ('Чертежи/Лист 10.pdf', PDF),
        ('Чертежи/Лист 2.pdf', PDF),
        {'name': 'Чертежи/Узел.pdf', 'data': PDF, 'packed': True},
        ('Схема.png', PNG),
        ('Прайс/Металл.csv', CSV),
        ('Старое.zip', make_zip([('a.txt', b'1')])),
        {'name': 'Договор.pdf', 'data': PDF, 'encrypted': True},
        ('../../Счёт.pdf', PDF),
        ('/etc/Корень.pdf', PDF),
        ('Thumbs.db', b'x'),
        ('__MACOSX/._Схема.png', b'x'),
    ])


def _order_rar4():
    """То же в RAR4: имена так, как их пишут WinRAR, rar из Linux и DOS."""
    return rs.rar4([
        {'name': 'Чертежи', 'is_dir': True},
        {'name': 'Чертежи\\Узел 1.pdf', 'data': PDF},
        {'name': 'Счёт.pdf', 'data': PDF, 'packed': True},
        {'name': 'Ведомость.pdf', 'data': PDF, 'encoding': 'utf8'},
        {'name': 'Старое.pdf', 'data': PDF, 'encoding': 'cp866'},
        {'name': 'Прайс.pdf', 'data': PDF, 'encoding': 'Прайс.pdf'.encode('cp1251')},
        {'name': 'readme.txt', 'data': b'hello', 'encoding': 'latin-1'},
        {'name': 'Пароль.pdf', 'data': PDF, 'flags': rs.R4_FILE_PASSWORD},
    ])


class _RarMixin:

    def _need_rar(self):
        if not ar.rar_available():
            self.skipTest("в образе нет rarfile или unrar")

    @staticmethod
    def _rows(listing):
        return {entry['path']: entry for entry in listing['entries']}

    def _read(self, blob, path, **kwargs):
        """Байты файла по пути в списке — как окно: сперва список, потом номер."""
        rows = self._rows(ar.list_rar(blob))
        return ar.read_rar_member(blob, rows[path]['index'], **kwargs)

    def _refused(self, words, call, *args, **kwargs):
        with self.assertRaises(ArchiveError) as caught:
            call(*args, **kwargs)
        self.assertIn(words, str(caught.exception))
        return caught.exception


# ═══════════════════════════════════════════════════════════════════════════
# 1. Чтение RAR без базы
# ═══════════════════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestRarReader(_RarMixin, TransactionCase):

    # --- список -------------------------------------------------------------
    def test_rar5_listing(self):
        self._need_rar()
        listing = ar.list_rar(_order_rar5(), tz=VLADIVOSTOK)
        paths = [entry['path'] for entry in listing['entries']]
        self.assertEqual(paths, [
            'Договор.pdf', 'Старое.zip', 'Схема.png', 'Счёт.pdf',
            'etc/Корень.pdf', 'Прайс/Металл.csv',
            'Чертежи/Лист 2.pdf', 'Чертежи/Лист 10.pdf', 'Чертежи/Узел.pdf',
        ], "папки по порядку, «Лист 2» раньше «Лист 10», служебные скрыты")
        rows = self._rows(listing)
        self.assertEqual(listing['hidden'], 2)
        self.assertEqual(listing['total'], 9)
        self.assertEqual(rows['Счёт.pdf']['warn'], ar.WARN_UP)
        self.assertEqual(rows['etc/Корень.pdf']['warn'], ar.WARN_ROOT)
        self.assertEqual(rows['Договор.pdf']['reason'], 'закрыт паролем')
        self.assertIn('Файлов под паролем: 1', listing['notes'][0])
        self.assertEqual(rows['Чертежи/Узел.pdf']['date'], '22.09.2026 00:13',
                         "RAR5 хранит UTC — дата в поясе человека")
        self.assertEqual(ar.list_rar(_order_rar5())['entries'][0]['date'], '21.09.2026 14:13',
                         "без пояса — UTC")
        self.assertEqual(rows['Чертежи/Лист 2.pdf']['index'], 2, "номер — позиция с папками")
        self.assertEqual(rows['Чертежи/Лист 2.pdf']['size'], len(PDF))
        self.assertEqual(rows['Чертежи/Лист 2.pdf']['dir'], 'Чертежи')

    def test_rar4_names(self):
        self._need_rar()
        rows = self._rows(ar.list_rar(_order_rar4()))
        self.assertEqual(sorted(rows), sorted([
            'Чертежи/Узел 1.pdf', 'Счёт.pdf', 'Ведомость.pdf', 'Старое.pdf',
            'Прайс.pdf', 'readme.txt', 'Пароль.pdf',
        ]), "WinRAR (Unicode), UTF-8, cp866 и cp1251 без флага, латиница — без кракозябр")
        self.assertEqual(rows['Счёт.pdf']['date'], '01.10.2026 12:30', "время DOS — как есть")
        self.assertEqual(rows['Пароль.pdf']['reason'], 'закрыт паролем')

    def test_empty_and_dates_missing(self):
        self._need_rar()
        listing = ar.list_rar(rs.rar5([('Папка', None)]))
        self.assertEqual((listing['entries'], listing['total']), ([], 0))
        nodate = ar.list_rar(rs.rar5([{'name': 'a.pdf', 'data': PDF, 'mtime': None}]))
        self.assertEqual(nodate['entries'][0]['date'], '')
        versions = ar.list_rar(rs.rar5([('a.pdf', PDF), {'name': 'a.pdf', 'data': b'old', 'version': 1}]))
        self.assertEqual(versions['total'], 1, "старые версии файла (-ver) не показываются")

    # --- чтение -------------------------------------------------------------
    def test_read_stored(self):
        self._need_rar()
        payload, row = self._read(_order_rar5(), 'Чертежи/Лист 2.pdf', tz=VLADIVOSTOK)
        self.assertEqual(payload, PDF)
        self.assertEqual((row['name'], row['path'], row['reason']),
                         ('Лист 2.pdf', 'Чертежи/Лист 2.pdf', ''))
        self.assertEqual(row['date'], '22.09.2026 00:13')
        self.assertEqual(self._read(_order_rar5(), 'Счёт.pdf')[0], PDF, "«..» — сигнал, не запрет")
        for path in ('Чертежи/Узел 1.pdf', 'Старое.pdf', 'Прайс.pdf', 'readme.txt'):
            with self.subTest(path=path):
                expected = b'hello' if path == 'readme.txt' else PDF
                self.assertEqual(self._read(_order_rar4(), path)[0], expected)

    def test_read_through_unrar_by_name(self):
        """--force-tool: и файл без сжатия читает unrar по имени — так
        работает «непрерывный» архив. Русские имена находятся (C.UTF-8)."""
        self._need_rar()
        for blob, path in ((_order_rar5(), 'Чертежи/Лист 2.pdf'),
                           (_order_rar4(), 'Чертежи/Узел 1.pdf'),
                           (_order_rar4(), 'Ведомость.pdf'),
                           (_order_rar4(), 'Старое.pdf'),
                           (_order_rar4(), 'Прайс.pdf')):
            with self.subTest(path=path):
                self.assertEqual(self._read(blob, path, force_tool=True)[0], PDF)

    def test_read_compressed(self):
        """Сжатый файл обычного архива — unrar на «мини-архиве» без имени."""
        self._need_rar()
        for build in (rs.rar5, rs.rar4):
            with self.subTest(build=build.__name__):
                blob = build([{'name': 'Папка/Узел.dat', 'data': MIXED, 'packed': True},
                              {'name': 'Второй.pdf', 'data': PDF, 'packed': True}])
                self.assertEqual(self._read(blob, 'Папка/Узел.dat')[0], MIXED)
                self.assertEqual(self._read(blob, 'Второй.pdf')[0], PDF)

    def test_read_solid(self):
        """«Непрерывный» архив — unrar разжимает всё до нужного файла по имени."""
        self._need_rar()
        r5 = rs.rar5([{'name': 'Первый.dat', 'data': MIXED, 'packed': True},
                      {'name': 'Чертежи/Второй.pdf', 'data': PDF, 'packed': True, 'solid': True}],
                     archive_flags=rs.R5_SOLID)
        r4 = rs.rar4([{'name': 'Первый.dat', 'data': MIXED, 'packed': True},
                      {'name': 'Чертежи\\Второй.pdf', 'data': PDF, 'packed': True,
                       'flags': rs.R4_FILE_SOLID}], main_flags=rs.R4_SOLID)
        r4_dos = rs.rar4([{'name': 'Первый.dat', 'data': MIXED, 'packed': True, 'encoding': 'cp866'},
                          {'name': 'Чертежи\\Второй.pdf', 'data': PDF, 'packed': True,
                           'encoding': 'cp866', 'flags': rs.R4_FILE_SOLID}], main_flags=rs.R4_SOLID)
        for label, blob in (('rar5', r5), ('rar4', r4), ('rar4 cp866', r4_dos)):
            with self.subTest(label=label):
                self.assertEqual(self._read(blob, 'Чертежи/Второй.pdf')[0], PDF)
                self.assertEqual(self._read(blob, 'Первый.dat')[0], MIXED)

    def test_bad_index_folder_and_duplicates(self):
        self._need_rar()
        blob = _order_rar5()
        for index in (999, -1, True):
            with self.subTest(index=index):
                error = self._refused('нет такого файла', ar.read_rar_member, blob, index)
                self.assertEqual(error.status, 404)
        self.assertEqual(self._refused('папка', ar.read_rar_member, blob, 0).status, 404)
        # Одинаковые имена: каждый файл открывается своим номером (раньше —
        # только последний, у остальных «не удалось достать»).
        for build in (rs.rar5, rs.rar4):
            with self.subTest(build=build.__name__):
                twins = build([('a.pdf', PDF + b'1'), ('a.pdf', PDF)])
                self.assertEqual([entry['reason'] for entry in ar.list_rar(twins)['entries']],
                                 ['', ''])
                self.assertEqual(ar.read_rar_member(twins, 0)[0], PDF + b'1')
                self.assertEqual(ar.read_rar_member(twins, 1)[0], PDF)

    def test_dos_names_rarfile_merged(self):
        """RAR4 без флага Unicode, имя нечётной длины в cp866: rarfile
        разбирал его запасной cp1252, где Б, Н, П, Р, Э — один «�», и три
        разных файла получали одно имя: «Посмотреть» открывал только
        последний. Теперь каждый — свой (и у сжатого «непрерывного», где
        unrar ищет по имени байтами)."""
        self._need_rar()
        names = ('Узел Б1.dxf', 'Узел Н1.dxf', 'Узел П1.dxf', 'Узел Р1.dxf', 'Узел Э1.dxf')
        plain = rs.rar4([{'name': name, 'data': b'x%d' % number, 'encoding': 'cp866'}
                         for number, name in enumerate(names)])
        solid = rs.rar4([{'name': name, 'data': MIXED + b'%d' % number, 'encoding': 'cp866',
                          'packed': True, 'flags': rs.R4_FILE_SOLID if number else 0}
                         for number, name in enumerate(names)], main_flags=rs.R4_SOLID)
        for label, blob, expected in (('обычный', plain, lambda n: b'x%d' % n),
                                      ('непрерывный', solid, lambda n: MIXED + b'%d' % n)):
            with self.subTest(label=label):
                rows = self._rows(ar.list_rar(blob))
                self.assertEqual(sorted(rows), sorted(names))
                self.assertEqual({row['reason'] for row in rows.values()}, {''})
                for number, name in enumerate(names):
                    self.assertEqual(ar.read_rar_member(blob, rows[name]['index'])[0],
                                     expected(number), name)

    def test_solid_name_clash(self):
        """Сжатый файл «непрерывного» архива unrar ищет по имени: если имя
        ловит и другой файл, причина видна в строке, а кнопок нет."""
        self._need_rar()
        twins = rs.rar5([{'name': 'a.pdf', 'data': PDF, 'packed': True},
                         {'name': 'a.pdf', 'data': PDF, 'packed': True, 'solid': True},
                         {'name': 'b.pdf', 'data': PDF, 'packed': True, 'solid': True}],
                        archive_flags=rs.R5_SOLID)
        listing = ar.list_rar(twins)
        self.assertEqual([(entry['path'], entry['reason']) for entry in listing['entries']],
                         [('a.pdf', ar.CLASH['twin'][0]), ('a.pdf', ar.CLASH['twin'][0]),
                          ('b.pdf', '')])
        error = self._refused('сжат «непрерывно»', ar.read_rar_member, twins, 0)
        self.assertEqual(error.status, 422)
        self.assertEqual(ar.read_rar_member(twins, 2)[0], PDF)
        masks = rs.rar5([{'name': 'Узел?.pdf', 'data': PDF, 'packed': True},
                         {'name': 'Узел1.pdf', 'data': MIXED, 'packed': True, 'solid': True},
                         {'name': 'Схема*.pdf', 'data': PDF, 'packed': True, 'solid': True}],
                        archive_flags=rs.R5_SOLID)
        rows = self._rows(ar.list_rar(masks))
        self.assertEqual(rows['Узел?.pdf']['reason'], ar.CLASH['mask'][0])
        self.assertEqual((rows['Узел1.pdf']['reason'], rows['Схема*.pdf']['reason']), ('', ''),
                         "маска, которая никого не ловит, — не помеха")
        self.assertEqual(ar.read_rar_member(masks, rows['Узел1.pdf']['index'])[0], MIXED)
        stored = rs.rar5([('a.pdf', PDF + b'1'), ('a.pdf', PDF)], archive_flags=rs.R5_SOLID)
        self.assertEqual([entry['reason'] for entry in ar.list_rar(stored)['entries']], ['', ''],
                         "без сжатия rarfile читает сам, имя unrar не нужно")
        many = rs.rar5([{'name': 'f%d?.pdf' % number, 'data': PDF, 'packed': True,
                         'solid': number > 0} for number in range(70)], archive_flags=rs.R5_SOLID)
        self.assertEqual({entry['reason'] for entry in ar.list_rar(many)['entries']},
                         {ar.CLASH['mask'][0]}, "масок больше 64 — не сверяем, сразу причина")

    def test_comment_does_not_break_listing(self):
        """Комментарий архива не читается вовсе. Раньше RAR5 с комментарием
        не в UTF-8 или под паролем был «повреждён» целиком."""
        self._need_rar()
        cases = (
            ('RAR5, UTF-8', rs.RAR5_SIG + rs.rar5_main() + rs.rar5_comment('Привет'.encode('utf-8'))
             + rs.rar5_file('a.pdf', PDF) + rs.rar5_end()),
            ('RAR5, cp1251', rs.RAR5_SIG + rs.rar5_main()
             + rs.rar5_comment('Привет'.encode('cp1251')) + rs.rar5_file('a.pdf', PDF) + rs.rar5_end()),
            ('RAR5, мусор', rs.RAR5_SIG + rs.rar5_main() + rs.rar5_comment(b'\xff\xfe\x00' * 50)
             + rs.rar5_file('a.pdf', PDF) + rs.rar5_end()),
            ('RAR4, сжатый', rs.RAR4_SIG + rs.rar4_main()
             + rs.rar4_comment('Привет'.encode('cp1251')) + rs.rar4_file('a.pdf', PDF) + rs.rar4_end()),
            ('RAR4, без сжатия', rs.RAR4_SIG + rs.rar4_main()
             + rs.rar4_comment('Привет'.encode('cp1251'), packed=False)
             + rs.rar4_file('a.pdf', PDF) + rs.rar4_end()),
        )
        for label, blob in cases:
            with self.subTest(label=label):
                listing = ar.list_rar(blob)
                self.assertEqual(([entry['path'] for entry in listing['entries']], listing['notes']),
                                 (['a.pdf'], []))
                self.assertEqual(ar.read_rar_member(blob, 0)[0], PDF)
        locked = rs.RAR5_SIG + rs.rar5_main() + rs.rar5_comment(b'\x01' * 16, encrypted=True) \
            + rs.rar5_file('a.pdf', PDF, encrypted=True) + rs.rar5_file('b.pdf', PDF) + rs.rar5_end()
        rows = self._rows(ar.list_rar(locked))
        self.assertEqual((rows['a.pdf']['reason'], rows['b.pdf']['reason']), ('закрыт паролем', ''),
                         "комментарий под паролем — не «повреждён», а пароль у своего файла")
        self._refused('закрыт паролем', ar.read_rar_member, locked, rows['a.pdf']['index'])
        self.assertEqual(ar.read_rar_member(locked, rows['b.pdf']['index'])[0], PDF)

    # --- отказы ---------------------------------------------------------------
    def test_crc_and_forged_size(self):
        self._need_rar()
        for label, item in (('без сжатия', {'name': 'a.pdf', 'data': PDF, 'crc': 1}),
                            ('сжатый', {'name': 'a.pdf', 'data': MIXED, 'packed': True, 'crc': 1})):
            with self.subTest(label=label):
                self._refused('контрольная сумма', ar.read_rar_member, rs.rar5([item]), 0)
        forged = rs.rar5([{'name': 'a.pdf', 'data': PDF, 'declared': len(PDF) + 100}])
        self._refused('повреждён', ar.read_rar_member, forged, 0)
        smaller = rs.rar5([{'name': 'a.dat', 'data': MIXED, 'packed': True, 'declared': 100}])
        error = self._refused('a.dat', ar.read_rar_member, smaller, 0)
        self.assertIn('повреждён', str(error), "больше заявленного — выдача обрезана, сумма не сошлась")

    def test_passwords(self):
        self._need_rar()
        blob = _order_rar5()
        error = self._refused('закрыт паролем', self._read, blob, 'Договор.pdf')
        self.assertEqual(error.status, 422)
        both = rs.rar5([{'name': 'a.pdf', 'data': PDF, 'encrypted': True},
                        {'name': 'b.pdf', 'data': PDF, 'encrypted': True}])
        self.assertIn('Архив закрыт паролем: список файлов виден', ar.list_rar(both)['notes'][0])
        header5 = rs.RAR5_SIG + rs.rar5_header_encryption() + rs.rar5_main() \
            + rs.rar5_file('a.pdf', PDF) + rs.rar5_end()
        header4 = rs.rar4([('a.pdf', PDF)], main_flags=rs.R4_PASSWORD)
        for label, encrypted in (('rar5', header5), ('rar4', header4)):
            with self.subTest(label=label):
                self._refused('даже список файлов не виден', ar.list_rar, encrypted)

    def test_volumes(self):
        self._need_rar()
        part1 = rs.rar5([{'name': 'Большой.pdf', 'data': PDF, 'block_flags': rs.R5_SPLIT_AFTER}],
                        archive_flags=rs.R5_VOLUME, more=True)
        part2 = rs.rar5([{'name': 'Большой.pdf', 'data': PDF, 'block_flags': rs.R5_SPLIT_BEFORE}],
                        archive_flags=rs.R5_VOLUME | rs.R5_VOLNUMBER, volume=1)
        part1_r4 = rs.rar4([{'name': 'Большой.pdf', 'data': PDF, 'flags': rs.R4_SPLIT_AFTER}],
                           main_flags=rs.R4_VOLUME | rs.R4_NEWNUMBERING | rs.R4_FIRSTVOLUME,
                           end_flags=0x4000 | rs.R4_NEXT_VOLUME)
        part2_r4 = rs.rar4([{'name': 'Большой.pdf', 'data': PDF, 'flags': rs.R4_SPLIT_BEFORE}],
                           main_flags=rs.R4_VOLUME | rs.R4_NEWNUMBERING)
        old_part1 = rs.rar4([{'name': 'Большой.pdf', 'data': PDF, 'flags': rs.R4_SPLIT_AFTER}],
                            main_flags=rs.R4_VOLUME)
        for label, blob in (('rar5 part1', part1), ('rar5 part2', part2), ('rar4 part1', part1_r4),
                            ('rar4 part2', part2_r4), ('rar 2.x part1', old_part1)):
            with self.subTest(label=label):
                self._refused('из нескольких частей', ar.list_rar, blob)
        single = rs.rar5([('a.pdf', PDF)], archive_flags=rs.R5_VOLUME)
        self.assertEqual(ar.read_rar_member(single, 0)[0], PDF,
                         "«многотомный» архив, которому хватило одной части, открывается")

    def test_broken_and_truncated(self):
        self._need_rar()
        good = rs.rar5([('a.pdf', PDF), ('b.pdf', PDF * 3)])
        cut = ar.list_rar(good[:-30])
        self.assertEqual([entry['path'] for entry in cut['entries']], ['a.pdf', 'b.pdf'])
        self.assertEqual(cut['notes'][0], ar.PARTIAL, "обрезан — список и оговорка первой")
        self.assertEqual(self._read(good[:-30], 'a.pdf')[0], PDF, "целый файл обрезанного читается")
        self._refused('повреждён', self._read, good[:-30], 'b.pdf')
        head = len(rs.RAR5_SIG + rs.rar5_main() + rs.rar5_file('a.pdf', PDF))
        partial = ar.list_rar(good[:head + 10])
        self.assertEqual(([e['path'] for e in partial['entries']], partial['notes'][0]),
                         (['a.pdf'], ar.PARTIAL))
        unknown = rs.RAR5_SIG + rs.rar5_main() + rs.rar5_file('a.pdf', PDF) \
            + rs.rar5_block(9, 0, b'') + rs.rar5_file('b.pdf', PDF) + rs.rar5_end()
        self.assertEqual(ar.list_rar(unknown)['notes'][0], ar.PARTIAL,
                         "блок незнакомого вида обрывает разбор — не молчим")
        spoiled = bytearray(good)
        spoiled[len(rs.RAR5_SIG + rs.rar5_main()) + 6] ^= 0xFF
        only_folder = rs.RAR5_SIG + rs.rar5_main() + rs.rar5_file('Папка', is_dir=True)
        for label, blob in (('сигнатура и нули', rs.RAR5_SIG + b'\0' * 64),
                            ('rar4 сигнатура и нули', rs.RAR4_SIG + b'\0' * 64),
                            ('порча заголовка', bytes(spoiled)),
                            ('обрезан после папки', only_folder)):
            with self.subTest(label=label):
                self.assertEqual(self._refused('повреждён', ar.list_rar, blob).status, 422)

    def test_too_many_files_and_huge_directory(self):
        self._need_rar()
        many = rs.rar5([('%d.txt' % number, b'') for number in range(ar.MAX_ENTRIES + 1)])
        error = self._refused('больше 5000', ar.list_rar, many)
        self.assertEqual(error.status, 413)
        enough = rs.rar5([('%d.txt' % number, b'') for number in range(ar.MAX_ENTRIES)])
        self.assertEqual(ar.list_rar(enough)['total'], ar.MAX_ENTRIES)
        long_names = rs.rar5([('Папка/%s%d.pdf' % ('Я' * 2000, number), b'') for number in range(1100)])
        self.assertEqual(self._refused('Оглавление архива весит больше', ar.list_rar,
                                       long_names).status, 413)

    def test_member_limits(self):
        self._need_rar()
        blob = rs.rar5([
            {'name': 'Огромный.pdf', 'data': PDF, 'declared': ar.MEMBER_MAX_BYTES + 1},
            {'name': 'Бомба.dat', 'data': b'\0' * 1024, 'declared': 2 * 1024 * 1024},
            {'name': 'Странный.dat', 'data': PDF, 'method': 6},
            {'name': 'Непрерывный.dat', 'data': b'\0' * 1024, 'declared': 2 * 1024 * 1024,
             'solid': True},
        ])
        rows = self._rows(ar.list_rar(blob))
        self.assertEqual(rows['Огромный.pdf']['reason'], 'больше 50,0 МБ')
        self.assertEqual(rows['Бомба.dat']['reason'], 'сжат в 2048 раз — похоже на подделку')
        self.assertEqual(rows['Странный.dat']['reason'], 'сжат неизвестным способом')
        self.assertEqual(rows['Непрерывный.dat']['reason'], '',
                         "у «непрерывного» сжатие считается вместе с предыдущими — не «бомба»")
        self.assertEqual(self._refused('больше предела', self._read, blob, 'Огромный.pdf').status, 413)
        self.assertEqual(self._refused('бомб', self._read, blob, 'Бомба.dat').status, 413)

    def test_links(self):
        """Копия и жёсткая ссылка RAR5 (WinRAR «сохранять одинаковые файлы
        как ссылки») — обычный файл: открываются байты оригинала. Символьная
        ссылка и копия без оригинала — причина с целью словами."""
        self._need_rar()
        blob = rs.rar5([
            ('Чертёж.pdf', PDF),
            {'name': 'Ссылка.pdf', 'redir': (rs.R5_SYMLINK, 'Чертёж.pdf')},
            {'name': 'Копия.pdf', 'data': b'', 'redir': (rs.R5_COPY, 'Чертёж.pdf'),
             'declared': len(PDF)},
            {'name': 'Папка/Жёсткая.pdf', 'redir': (rs.R5_HARDLINK, 'Чертёж.pdf')},
            {'name': 'Копия копии.pdf', 'redir': (rs.R5_COPY, 'Копия.pdf')},
            {'name': 'Пропала.pdf', 'redir': (rs.R5_COPY, 'Нет/Такого.pdf')},
            {'name': 'Копия ссылки.pdf', 'redir': (rs.R5_COPY, 'Ссылка.pdf')},
            {'name': 'Круг 1.pdf', 'redir': (rs.R5_COPY, 'Круг 2.pdf')},
            {'name': 'Круг 2.pdf', 'redir': (rs.R5_COPY, 'Круг 1.pdf')},
            {'name': 'Проценты.pdf', 'redir': (rs.R5_SYMLINK, '100%s %d.pdf')},
            {'name': 'Далеко.pdf', 'redir': (rs.R5_WINLINK, 'C:\\' + 'Длинная папка\\' * 6 + 'Узел.pdf')},
            {'name': 'Пароль.pdf', 'data': PDF, 'encrypted': True},
            {'name': 'Копия пароля.pdf', 'redir': (rs.R5_COPY, 'Пароль.pdf')},
            {'name': 'Бомба.dat', 'data': b'\0' * 1024, 'declared': 2 * 1024 * 1024},
            {'name': 'Копия бомбы.dat', 'redir': (rs.R5_COPY, 'Бомба.dat')},
        ])
        listing = ar.list_rar(blob)
        rows = self._rows(listing)
        reasons = {path: row['reason'] for path, row in rows.items()}
        self.assertEqual(reasons, {
            'Чертёж.pdf': '', 'Копия.pdf': '', 'Папка/Жёсткая.pdf': '', 'Копия копии.pdf': '',
            'Ссылка.pdf': 'ссылка на «Чертёж.pdf», а не файл',
            'Пропала.pdf': 'копия файла «Нет/Такого.pdf», а его в архиве нет',
            'Копия ссылки.pdf': 'копия «Ссылка.pdf» — открыть нечего',
            'Круг 1.pdf': 'копия «Круг 2.pdf» — открыть нечего',
            'Круг 2.pdf': 'копия «Круг 1.pdf» — открыть нечего',
            'Проценты.pdf': 'ссылка на «100%s %d.pdf», а не файл',
            'Далеко.pdf': 'ссылка на «…' + ('C:\\' + 'Длинная папка\\' * 6 + 'Узел.pdf')[-59:]
                          + '», а не файл',
            'Пароль.pdf': 'закрыт паролем', 'Копия пароля.pdf': 'закрыт паролем',
            'Бомба.dat': 'сжат в 2048 раз — похоже на подделку',
            'Копия бомбы.dat': 'сжат в 2048 раз — похоже на подделку',
        })
        self.assertEqual(rows['Копия.pdf']['size'], len(PDF))
        self.assertEqual(rows['Копия копии.pdf']['size'], len(PDF), "размер — оригинала")
        self.assertEqual(listing['encrypted'], 2, "копия файла под паролем — тоже под паролем")
        for path in ('Копия.pdf', 'Папка/Жёсткая.pdf', 'Копия копии.pdf'):
            with self.subTest(path=path):
                payload, row = self._read(blob, path)
                self.assertEqual(payload, PDF)
                self.assertEqual(row['path'], path, "строка — сама копия, байты — оригинала")
        self._refused('ссылка на «Чертёж.pdf», а не сам файл', self._read, blob, 'Ссылка.pdf')
        self._refused('самого файла в архиве нет', self._read, blob, 'Пропала.pdf')
        self._refused('«100%s %d.pdf»', self._read, blob, 'Проценты.pdf')
        self.assertEqual(self._refused('бомб', self._read, blob, 'Копия бомбы.dat').status, 413)
        self._refused('закрыт паролем', self._read, blob, 'Копия пароля.pdf')
        solid = rs.rar5([{'name': 'a.dat', 'data': MIXED, 'packed': True},
                         {'name': 'b.dat', 'redir': (rs.R5_COPY, 'a.dat')}],
                        archive_flags=rs.R5_SOLID)
        self.assertEqual(self._read(solid, 'b.dat')[0], MIXED,
                         "копия в «непрерывном» — unrar достаёт оригинал по имени")
        unix = rs.rar4([{'name': 'link.pdf', 'data': b'target.pdf', 'host_os': 3,
                         'mode': 0o120777, 'encoding': 'utf8'}])
        self.assertEqual(ar.list_rar(unix)['entries'][0]['reason'], 'ссылка, а не файл',
                         "ссылка RAR4 из Linux — цель в данных записи, её не читаем")

    # --- процесс и временная папка -----------------------------------------------
    def test_temp_folder_private_and_removed(self):
        self._need_rar()
        blob = _order_rar5()
        index = self._rows(ar.list_rar(blob))['Чертежи/Узел.pdf']['index']
        base = tempfile.mkdtemp(prefix='mc45b-test-')
        self.addCleanup(shutil.rmtree, base, True)
        seen = []
        run = ar._run

        def spy(args, data=None, folder=None, slow=''):
            if folder:
                seen.append((stat.S_IMODE(os.stat(folder).st_mode),
                             stat.S_IMODE(os.stat(os.path.join(folder, 'archive.rar')).st_mode)))
            return run(args, data=data, folder=folder, slow=slow)

        with patch.object(tempfile, 'tempdir', base), patch.object(ar, '_run', spy):
            self.assertEqual(ar.read_rar_member(blob, index)[0], PDF)
            self._refused('закрыт паролем', self._read, blob, 'Договор.pdf')
            broken = rs.rar5([{'name': 'a.pdf', 'data': PDF, 'crc': 1}])
            self._refused('контрольная сумма', ar.read_rar_member, broken, 0)
        self.assertEqual(seen, [(0o700, 0o600)] * 2, "папка 0700, копия архива 0600")
        self.assertEqual(os.listdir(base), [], "временная папка удалена и при отказе")

    def test_timeout(self):
        self._need_rar()
        blob = rs.rar5([('a.pdf', PDF)])
        with patch.object(ar, 'RAR_TIMEOUT', 0.0001):
            self.assertEqual(self._refused('читается дольше', ar.list_rar, blob).status, 413)
        solid = rs.rar5([{'name': 'a.dat', 'data': MIXED, 'packed': True},
                         {'name': 'b.pdf', 'data': PDF, 'packed': True, 'solid': True}],
                        archive_flags=rs.R5_SOLID)
        for label, archive, words in (('обычный', blob, 'распаковка остановлена'),
                                      ('непрерывный', solid, 'сжат «непрерывно»')):
            with self.subTest(label=label):
                listing = ar._rar_list(archive)
                index = len(listing['items']) - 1
                base = tempfile.mkdtemp(prefix='mc45b-test-')
                self.addCleanup(shutil.rmtree, base, True)
                with patch.object(ar, '_rar_list', return_value=listing), \
                        patch.object(ar, 'RAR_TIMEOUT', 0.0001), \
                        patch.object(tempfile, 'tempdir', base):
                    error = self._refused(words, ar.read_rar_member, archive, index)
                self.assertEqual(error.status, 413)
                self.assertEqual(os.listdir(base), [], "по сроку папка тоже удалена")

    def test_unavailable(self):
        """Образ откатили — прежние слова, ничего не запускается."""
        with patch.object(ar, 'rar_available', return_value=False), \
                patch.object(ar, '_run', side_effect=AssertionError("процесс не нужен")):
            for call in (ar.list_rar, lambda blob: ar.read_rar_member(blob, 0)):
                error = self._refused('', call, _order_rar5())
                self.assertEqual(str(error), 'Просмотр архивов RAR пока недоступен — скачайте архив.')

    def test_legacy_names_like_zip(self):
        """Порядок разбора имени без отметки кодировки — тот же, что у ZIP."""
        self.assertEqual(ar._legacy_name('Счёт.pdf'.encode('cp866'), 'cp1251'), 'Счёт.pdf')
        self.assertEqual(ar._legacy_name('Прайс.pdf'.encode('cp1251'), 'cp1251'), 'Прайс.pdf')
        self.assertEqual(ar._legacy_name('Чертёж.pdf'.encode('utf-8'), 'cp1251'), 'Чертёж.pdf')
        self.assertEqual(ar._legacy_name(b'\x98\xcf.pdf', 'cp1251'), '\N{REPLACEMENT CHARACTER}П.pdf',
                         "незанятый байт cp1251 — знак замены, а не ошибка")
        self.assertEqual(ar._rar_name({'name': 'a\ud800b.pdf'}), 'a\N{REPLACEMENT CHARACTER}b.pdf')


# ═══════════════════════════════════════════════════════════════════════════
# 2. Окно просмотра: preview() и price_scan() у вложения RAR
# ═══════════════════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestRarPreview(_RarMixin, _MailboxMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._mailbox(cls.env.user)
        cls.env.user.tz = VLADIVOSTOK
        cls.Attachment = cls.env['mail.client.attachment']
        cls.order = cls._attach('Чертежи дефлекторов.rar', _order_rar5(), 'application/x-rar')

    def setUp(self):
        super().setUp()
        self._need_rar()

    def _entries(self, payload):
        return {entry['path']: entry for entry in payload['archive']['entries']}

    def test_archive_is_listed(self):
        payload = self.Attachment.preview(self.order.id)
        self.assertEqual((payload['kind'], payload['format'], payload['format_title']),
                         ('archive', 'rar', 'архив RAR'))
        entries = self._entries(payload)
        kinds = {path: entry['kind'] for path, entry in entries.items()}
        self.assertEqual(kinds, {
            'Договор.pdf': 'pdf', 'Счёт.pdf': 'pdf', 'Старое.zip': 'archive', 'Схема.png': 'image',
            'etc/Корень.pdf': 'pdf', 'Прайс/Металл.csv': 'sheet', 'Чертежи/Лист 2.pdf': 'pdf',
            'Чертежи/Лист 10.pdf': 'pdf', 'Чертежи/Узел.pdf': 'pdf',
        })
        self.assertEqual(entries['Чертежи/Узел.pdf']['date'], '22.09.2026 00:13', "пояс человека")
        self.assertEqual(entries['Счёт.pdf']['warn'], 'путь вёл за пределы архива')

    def test_member_pdf_image_sheet(self):
        entries = self._entries(self.Attachment.preview(self.order.id))
        pdf = entries['Чертежи/Узел.pdf']
        payload = self.Attachment.preview(self.order.id, member=pdf['index'])
        url = '/mail_client/attachment/%d/member/%d' % (self.order.id, pdf['index'])
        self.assertEqual((payload['kind'], payload['name'], payload['archive_name']),
                         ('pdf', 'Узел.pdf', 'Чертежи дефлекторов.rar'))
        self.assertEqual((payload['url'], payload['download_url']), (url, url + '?download=1'))
        self.assertEqual(payload['member'], {'index': pdf['index'], 'path': 'Чертежи/Узел.pdf'})
        self.assertEqual(payload['pages'], 1)
        image = self.Attachment.preview(self.order.id, member=entries['Схема.png']['index'])
        self.assertEqual((image['kind'], image['width'], image['height']), ('image', 1, 1))
        csv_index = entries['Прайс/Металл.csv']['index']
        sheet = self.Attachment.preview(self.order.id, member=csv_index)
        self.assertEqual((sheet['kind'], sheet['sheets'][0]['rows'][0][0]), ('sheet', 'Труба 40х40х2'))
        more = self.Attachment.preview(self.order.id, member=csv_index, sheet=0, offset=1)
        self.assertEqual(more['sheets'][0]['rows'][0][0], 'Лист 3 мм', "«Показать ещё» у файла RAR")
        self.assertTrue(self.Attachment.price_scan(self.order.id, sheet=0, member=csv_index)['is_price'])

    def test_member_refusals(self):
        entries = self._entries(self.Attachment.preview(self.order.id))
        nested = self.Attachment.preview(self.order.id, member=entries['Старое.zip']['index'])
        self.assertEqual(nested['kind'], 'none')
        self.assertIn('архив внутри архива', nested['reason'])
        locked = self.Attachment.preview(self.order.id, member=entries['Договор.pdf']['index'])
        self.assertEqual((locked['kind'], locked['url'], locked['download_url']), ('none', '', ''))
        self.assertIn('закрыт паролем', locked['reason'])
        folder = self.Attachment.preview(self.order.id, member=0)
        self.assertIn('папка', folder['reason'])
        missing = self.Attachment.preview(self.order.id, member=999)
        self.assertIn('нет такого файла', missing['reason'])

    def test_copy_opens_like_file(self):
        """Копия RAR5 в окне — как обычный файл: вид, «Посмотреть», байты."""
        attachment = self._attach('Копии.rar', rs.rar5([
            ('Чертёж.pdf', PDF),
            {'name': 'Копия/Чертёж.pdf', 'redir': (rs.R5_COPY, 'Чертёж.pdf'), 'declared': len(PDF)},
        ]))
        entries = self._entries(self.Attachment.preview(attachment.id))
        copy = entries['Копия/Чертёж.pdf']
        self.assertEqual((copy['kind'], copy['reason']), ('pdf', ''))
        member = self.Attachment.preview(attachment.id, member=copy['index'])
        self.assertEqual((member['kind'], member['pages']), ('pdf', 1), member.get('reason'))

    def test_rar4_attachment(self):
        attachment = self._attach('Заказ.rar', _order_rar4())
        payload = self.Attachment.preview(attachment.id)
        entries = self._entries(payload)
        self.assertIn('Старое.pdf', entries)
        member = self.Attachment.preview(attachment.id, member=entries['Старое.pdf']['index'])
        self.assertEqual((member['kind'], member['name']), ('pdf', 'Старое.pdf'))

    def test_refusals_of_whole_archive_in_words(self):
        cases = (
            ('Тома.part1.rar', rs.rar5([{'name': 'a.pdf', 'data': PDF, 'block_flags': rs.R5_SPLIT_AFTER}],
                                       archive_flags=rs.R5_VOLUME, more=True), 'из нескольких частей'),
            ('Битый.rar', rs.RAR5_SIG + b'\0' * 64, 'повреждён'),
            ('Пароль.rar', rs.rar4([('a.pdf', PDF)], main_flags=rs.R4_PASSWORD), 'закрыт паролем целиком'),
        )
        for name, blob, words in cases:
            with self.subTest(name=name):
                payload = self.Attachment.preview(self._attach(name, blob).id)
                self.assertEqual(payload['kind'], 'none')
                self.assertIn(words, payload['reason'])

    def test_unavailable_falls_back(self):
        with patch.object(ar, 'rar_available', return_value=False):
            payload = self.Attachment.preview(self.order.id)
            self.assertEqual((payload['kind'], payload['reason']),
                             ('none', 'Просмотр архивов RAR пока недоступен — скачайте архив.'))
            member = self.Attachment.preview(self.order.id, member=1)
            self.assertEqual(member['reason'], 'Просмотр архивов RAR пока недоступен — скачайте архив.')
            self.assertTrue(payload['download_url'], "«Скачать архив» остаётся")

    def test_member_of_something_else(self):
        refused = self.Attachment.preview(self._attach('Схема.png', PNG, 'image/png').id, member=0)
        self.assertEqual(refused['kind'], 'none')
        self.assertIn('не архив ZIP или RAR', refused['reason'])

    def test_foreign_mailbox(self):
        stranger = new_test_user(self.env, login='mc45b_stranger',
                                 groups='base.group_user,mail_client.group_mail_client_user')
        with self.assertRaises(AccessError):
            self.Attachment.with_user(stranger).preview(self.order.id, member=1)


@tagged('post_install', '-at_install')
class TestRarDrawing(_RarMixin, _MailboxMixin, TransactionCase):
    """Чертёж DXF из архива RAR — окном pmk_drawing, как из ZIP (шаг 46)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pmk_drawing пишет кэш отдельной транзакцией — в тесте она откатится.
        cls.registry_enter_test_mode_cls()
        cls._mailbox(cls.env.user)
        cls.Attachment = cls.env['mail.client.attachment']
        cls.order = cls._attach('Чертежи.rar', rs.rar5([
            {'name': 'Чертежи/Кронштейн.dxf', 'data': DXF_R12, 'packed': True},
            ('Пояснение.txt', 'Режем из листа 3 мм'.encode('cp1251')),
        ]))

    def setUp(self):
        super().setUp()
        self._need_rar()
        if 'pmk.drawing' not in self.env:
            self.skipTest("нет модуля pmk_drawing")

    def test_dxf_in_rar(self):
        entries = {entry['path']: entry
                   for entry in self.Attachment.preview(self.order.id)['archive']['entries']}
        self.assertEqual(entries['Чертежи/Кронштейн.dxf']['kind'], 'drawing')
        member = self.Attachment.preview(self.order.id,
                                         member=entries['Чертежи/Кронштейн.dxf']['index'])
        self.assertEqual((member['kind'], member['archive_name']), ('drawing', 'Чертежи.rar'),
                         member['reason'])
        self.assertEqual(member['drawing']['layers'][0]['name'], 'КОНТУР')
        self.assertTrue(member['download_url'].endswith('?download=1'))


# ═══════════════════════════════════════════════════════════════════════════
# 3. Маршрут файла из архива RAR
# ═══════════════════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestRarRoute(_RarMixin, _MailboxMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'mc45b-route-pass'
        cls.owner = new_test_user(cls.env, login='mc45b_owner', password=cls.password,
                                  groups='base.group_user,mail_client.group_mail_client_user')
        cls.stranger = new_test_user(cls.env, login='mc45b_other', password=cls.password,
                                     groups='base.group_user,mail_client.group_mail_client_user')
        cls._mailbox(cls.owner)
        cls.order = cls._attach('Чертежи дефлекторов.rar', _order_rar5(), 'application/x-rar')

    def setUp(self):
        super().setUp()
        self._need_rar()
        self.entries = {entry['path']: entry['index']
                        for entry in ar.list_rar(_order_rar5())['entries']}

    def _get(self, index, query=''):
        return self.url_open('/mail_client/attachment/%d/member/%d%s' % (self.order.id, index, query))

    def test_pdf_image_and_download(self):
        self.authenticate(self.owner.login, self.password)
        pdf = self._get(self.entries['Чертежи/Узел.pdf'])
        self.assertEqual((pdf.status_code, pdf.content), (200, PDF))
        self.assertEqual(pdf.headers['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.headers['Content-Disposition'].startswith('attachment'))
        self.assertEqual(pdf.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', pdf.headers['Content-Security-Policy'])
        image = self._get(self.entries['Схема.png'])
        self.assertEqual((image.headers['Content-Type'], image.headers['Content-Disposition'][:6]),
                         ('image/png', 'inline'))
        saved = self._get(self.entries['Счёт.pdf'], '?download=1')
        self.assertEqual(saved.headers['Content-Type'], 'application/octet-stream')
        self.assertIn("UTF-8''%D0%A1%D1%87%D1%91%D1%82.pdf", saved.headers['Content-Disposition'],
                      "имя без «../..»")

    def test_refusals_by_status(self):
        self.authenticate(self.owner.login, self.password)
        self.assertEqual(self._get(999).status_code, 404)
        locked = self._get(self.entries['Договор.pdf'])
        self.assertEqual(locked.status_code, 422)
        self.assertIn('закрыт паролем', locked.text)

    def test_foreign_mailbox_is_not_found(self):
        self.authenticate(self.stranger.login, self.password)
        self.assertEqual(self._get(self.entries['Чертежи/Узел.pdf']).status_code, 404)
