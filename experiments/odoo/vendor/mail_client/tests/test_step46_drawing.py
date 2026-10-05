# -*- coding: utf-8 -*-
"""ПРАВКА ПМК (шаг 46 разбора удобства, 06.10.2026): чертежи DXF в почте.

Вложение .dxf и файл .dxf из архива ZIP открываются «Посмотреть» — окном
чертежа модуля pmk_drawing (вид 'drawing' с готовыми путями по слоям).
Модуля нет — честное «Просмотр DXF недоступен», в архиве — только
«Скачать», как до шага 46.

Чертёж собран здесь же текстом (DXF R12, русский слой в cp1251) — без
ezdxf и без файлов с диска.

- TestDrawingKinds — чистые правила вида (wire_kind, entry_kind), без базы;
- TestDrawingMail — preview() вложения и файла из архива; без модуля
  просмотра чертежей (подмена _drawing_available); порча — словами.

Гонять на одноразовой базе (pmk_drawing нужен для TestDrawingMail):
    odoo -d mc_test -i mail_client,pmk_drawing --test-enable \\
         --test-tags /mail_client:TestDrawingKinds,/mail_client:TestDrawingMail \\
         --stop-after-init
"""
from unittest import mock

from odoo.tests import TransactionCase, tagged

from odoo.addons.mail_client.models import mail_client_attachment_preview as mp
from odoo.addons.mail_client.tests.test_step45_archive import _MailboxMixin, make_zip

# Минимальный DXF R12: слой «КОНТУР» (красный), линия 100 × 50, текст.
DXF_R12 = '\n'.join([
    '  0', 'SECTION', '  2', 'HEADER',
    '  9', '$ACADVER', '  1', 'AC1009',
    '  9', '$DWGCODEPAGE', '  3', 'ANSI_1251',
    '  0', 'ENDSEC',
    '  0', 'SECTION', '  2', 'TABLES',
    '  0', 'TABLE', '  2', 'LAYER', ' 70', '1',
    '  0', 'LAYER', '  2', 'КОНТУР', ' 70', '0', ' 62', '1', '  6', 'CONTINUOUS',
    '  0', 'ENDTAB',
    '  0', 'ENDSEC',
    '  0', 'SECTION', '  2', 'ENTITIES',
    '  0', 'LINE', '  8', 'КОНТУР',
    ' 10', '0.0', ' 20', '0.0', ' 30', '0.0',
    ' 11', '100.0', ' 21', '50.0', ' 31', '0.0',
    '  0', 'TEXT', '  8', 'КОНТУР',
    ' 10', '0.0', ' 20', '60.0', ' 30', '0.0', ' 40', '5.0', '  1', 'Деталь 1',
    '  0', 'ENDSEC',
    '  0', 'EOF', '',
]).encode('cp1251')


@tagged('post_install', '-at_install')
class TestDrawingKinds(TransactionCase):

    def test_wire_and_entry_kind(self):
        self.assertEqual(mp.wire_kind('dxf', 'cad2d'), 'drawing')
        self.assertIn('drawing', mp.WIRE_KINDS)
        self.assertEqual(mp.entry_kind('Чертежи/Кронштейн.DXF'), 'drawing')
        self.assertEqual(mp.entry_kind('Сборка.dwg'), 'other', "DWG — шаг не этот")
        self.assertEqual(mp.detect_format(DXF_R12, 'a.dxf')[:2], ('dxf', 'cad2d'))
        self.assertEqual(mp.title_of('dxf'), 'чертёж DXF')


@tagged('post_install', '-at_install')
class TestDrawingMail(_MailboxMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # pmk_drawing читает и пишет кэш чертежей отдельной транзакцией —
        # в режиме теста она обёртка над курсором теста и откатится с ним.
        cls.registry_enter_test_mode_cls()
        cls._mailbox(cls.env.user)
        cls.Attachment = cls.env['mail.client.attachment']
        cls.dxf = cls._attach('Кронштейн.dxf', DXF_R12, content_type='application/octet-stream')
        cls.order = cls._attach('Заказ 46.zip', make_zip([
            ('Чертежи/Кронштейн.dxf', DXF_R12),
            ('Чертежи/Обрезок.dxf', DXF_R12[:200]),
            ('Пояснение.txt', 'Режем из листа 3 мм'.encode('cp1251')),
        ]))

    def setUp(self):
        super().setUp()
        if 'pmk.drawing' not in self.env:
            self.skipTest("нет модуля pmk_drawing")

    def _entries(self, payload):
        return {entry['path']: entry for entry in payload['archive']['entries']}

    def test_dxf_attachment_is_drawn(self):
        payload = self.Attachment.preview(self.dxf.id)
        self.assertEqual((payload['kind'], payload['format'], payload['format_title']),
                         ('drawing', 'dxf', 'чертёж DXF'), payload['reason'])
        drawing = payload['drawing']
        self.assertTrue(drawing['ok'])
        self.assertEqual([layer['name'] for layer in drawing['layers']], ['КОНТУР'])
        self.assertEqual(drawing['palette'], ['#ff0000'])
        self.assertAlmostEqual(drawing['size_mm'][1], 65.0, delta=3.0)
        self.assertNotIn('cache', drawing)
        # Второй раз — из кэша pmk_drawing, без отрисовки.
        with mock.patch.object(type(self.env['pmk.drawing']), '_run_renderer',
                               autospec=True, side_effect=AssertionError("рисует заново")):
            again = self.Attachment.preview(self.dxf.id)
        self.assertEqual(again['drawing']['items'], drawing['items'])

    def test_dxf_in_archive(self):
        listing = self.Attachment.preview(self.order.id)
        entries = self._entries(listing)
        self.assertEqual(entries['Чертежи/Кронштейн.dxf']['kind'], 'drawing')
        member = self.Attachment.preview(self.order.id, member=entries['Чертежи/Кронштейн.dxf']['index'])
        self.assertEqual((member['kind'], member['archive_name']), ('drawing', 'Заказ 46.zip'))
        self.assertEqual(member['drawing']['layers'][0]['name'], 'КОНТУР')
        self.assertTrue(member['download_url'].endswith('?download=1'))
        broken = self.Attachment.preview(self.order.id, member=entries['Чертежи/Обрезок.dxf']['index'])
        self.assertEqual(broken['kind'], 'none')
        self.assertIn('обрезан', broken['reason'])
        self.assertTrue(broken['download_url'], "не нарисовался — скачать можно")

    def test_without_drawing_module(self):
        with mock.patch.object(type(self.Attachment), '_drawing_available',
                               autospec=True, return_value=False):
            payload = self.Attachment.preview(self.dxf.id)
            listing = self.Attachment.preview(self.order.id)
        self.assertEqual((payload['kind'], payload['reason']), ('none', mp.DRAWING_UNAVAILABLE))
        self.assertIsNone(payload['drawing'])
        self.assertEqual(self._entries(listing)['Чертежи/Кронштейн.dxf']['kind'], 'other',
                         "без окна чертежа — только «Скачать»")

    def test_refusal_words(self):
        with mock.patch.object(type(self.env['pmk.drawing']), '_run_renderer', autospec=True,
                               return_value={'ok': False, 'reason': 'Чертёж рисуется слишком долго',
                                             'cache': False}):
            payload = self.Attachment.preview(self.dxf.id)
        self.assertEqual((payload['kind'], payload['reason']),
                         ('none', 'Чертёж рисуется слишком долго'))
