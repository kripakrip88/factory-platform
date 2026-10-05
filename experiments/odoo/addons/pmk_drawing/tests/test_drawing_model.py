# -*- coding: utf-8 -*-
"""Шаг 46: окно чертежа на сервере — права, кэш, пределы, отдельный процесс.

- TestDrawingPreview — pmk.drawing.attachment_preview: права по вложению,
  кэш по контрольной сумме (второй раз — без отрисовки), отказы, которые
  не запоминаются («занято», «долго», «нет библиотеки»), большой файл не
  берётся в память. Отрисовка подменена на render() в процессе теста;
- TestDrawingProcess — настоящий запуск `python3 -I tools/dxf_render.py`
  с пределами памяти и процессора, как на стенде.

Кэш читается и пишется отдельной транзакцией (registry.cursor()). Чтобы
тест не писал мимо своей транзакции в базу, реестр — в режиме теста
(registry_enter_test_mode_cls): «отдельный» курсор — обёртка над курсором
теста, и всё откатывается вместе с ним.

Гонять на одноразовой базе:
    odoo -d dxf_test -i pmk_drawing --test-enable \\
         --test-tags /pmk_drawing --stop-after-init
"""
import datetime
import hashlib
from unittest import mock, skipUnless

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.pmk_drawing.models import drawing as drawing_module
from odoo.addons.pmk_drawing.tests import dxf_samples as S
from odoo.addons.pmk_drawing.tools import dxf_render as R

try:
    import ezdxf  # noqa: F401
    HAS_EZDXF = True
except ImportError:                                        # pragma: no cover
    HAS_EZDXF = False


@tagged('post_install', '-at_install')
@skipUnless(HAS_EZDXF, "нет ezdxf")
class TestDrawingPreview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry_enter_test_mode_cls()
        cls.partner = cls.env['res.partner'].create({'name': 'Заказчик чертежа'})
        cls.blob = S.factory_dxf()
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'Кронштейн.dxf', 'raw': cls.blob,
            'res_model': 'res.partner', 'res_id': cls.partner.id,
        })
        cls.Drawing = cls.env['pmk.drawing']
        cls.Cache = cls.env['pmk.drawing.preview'].sudo()
        cls.checksum = hashlib.sha1(cls.blob).hexdigest()

    def _in_process(self):
        """Отрисовка в процессе теста вместо отдельного — со счётчиком."""
        return mock.patch.object(type(self.Drawing), '_run_renderer', autospec=True,
                                 side_effect=lambda _self, blob: R.render(blob))

    def test_preview_and_cache(self):
        with self._in_process() as run:
            first = self.Drawing.attachment_preview(self.attachment.id)
            second = self.Drawing.attachment_preview(self.attachment.id)
        self.assertTrue(first['ok'], first.get('reason'))
        self.assertEqual(run.call_count, 1, "второй раз — из кэша, без отрисовки")
        self.assertEqual((first['name'], first['file_size']), ('Кронштейн.dxf', len(self.blob)))
        self.assertEqual(first['download_url'], '/web/content/%d?download=true' % self.attachment.id)
        self.assertNotIn('cache', first, "служебный признак кэша окну не нужен")
        self.assertEqual(second['items'], first['items'])
        self.assertIn('КОНТУР', [layer['name'] for layer in second['layers']])
        cached = self.Cache.search([('checksum', '=', self.checksum)])
        self.assertEqual(len(cached), 1)
        self.assertTrue(cached.ok)
        self.assertFalse(cached.expires, "готовый чертёж — до автоочистки")
        self.assertTrue(cached.version.startswith('%d/' % R.PAYLOAD_VERSION))

    def test_same_bytes_other_attachment_from_cache(self):
        other = self.env['ir.attachment'].create({
            'name': 'копия.DXF', 'raw': self.blob,
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        with self._in_process() as run:
            self.Drawing.attachment_preview(self.attachment.id)
            payload = self.Drawing.attachment_preview(other.id)
        self.assertEqual(run.call_count, 1, "кэш — по содержимому, а не по вложению")
        self.assertEqual(payload['name'], 'копия.DXF')

    def test_refusals_not_cached(self):
        busy = {'ok': False, 'reason': 'долго', 'cache': False}
        with mock.patch.object(type(self.Drawing), '_run_renderer', autospec=True,
                               return_value=busy) as run:
            self.Drawing.attachment_preview(self.attachment.id)
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertEqual(run.call_count, 2, "отказ по времени не запоминается")
        self.assertEqual((payload['ok'], payload['reason']), (False, 'долго'))
        self.assertFalse(self.Cache.search([('checksum', '=', self.checksum)]))

    def test_broken_file_cached(self):
        broken = self.env['ir.attachment'].create({
            'name': 'обрезок.dxf', 'raw': S.broken_dxf(),
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        with self._in_process() as run:
            first = self.Drawing.attachment_preview(broken.id)
            self.Drawing.attachment_preview(broken.id)
        self.assertEqual(first['reason'], R.TRUNCATED)
        self.assertEqual(run.call_count, 1, "порча повторится на тех же байтах — запоминаем")

    def test_unavailable_library(self):
        with mock.patch.object(type(self.Drawing), '_available', autospec=True, return_value=False):
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertFalse(payload['ok'])
        self.assertIn('Просмотр DXF недоступен', payload['reason'])
        self.assertFalse(self.Cache.search([('checksum', '=', self.checksum)]),
                         "поставят библиотеку — откроется сразу")

    def test_busy_server(self):
        with mock.patch.object(type(self.Drawing), '_acquire_lock', autospec=True, return_value=False):
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertEqual(payload['reason'], drawing_module.BUSY)
        self.assertTrue(self.Drawing._acquire_lock(), "свободная блокировка берётся сразу")

    def test_wait_fits_proxy_timeout(self):
        # Ждём коротко: пока запрос спит, он держит один из двух рабочих
        # процессов. Ожидание + отрисовка — меньше срока nginx (60 с), иначе
        # браузер получил бы 504 и английское «Connection lost».
        self.assertLessEqual(drawing_module.LOCK_WAIT, 2)
        self.assertLess(drawing_module.LOCK_WAIT + drawing_module.RENDER_TIMEOUT + 5,
                        drawing_module.NGINX_READ_TIMEOUT)

    def test_neighbour_result_seen_after_wait(self):
        # Пока ждали блокировку, сосед дорисовал этот же чертёж и записал
        # ответ — второй раз не рисуем (кэш перечитывается после ожидания).
        Drawing = type(self.Drawing)
        neighbour = R.render(self.blob)

        def neighbour_finished(model):
            model._cache_put(self.checksum, model._cache_version(), neighbour)
            return True

        with mock.patch.object(Drawing, '_acquire_lock', autospec=True,
                               side_effect=neighbour_finished), \
                mock.patch.object(Drawing, '_run_renderer', autospec=True,
                                  side_effect=AssertionError("рисует второй раз")):
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertTrue(payload['ok'], payload.get('reason'))

    def test_slow_refusal_remembered_for_a_day(self):
        slow = {'ok': False, 'reason': 'долго', 'cache': False, 'slow': True}
        Drawing = type(self.Drawing)
        with mock.patch.object(Drawing, '_run_renderer', autospec=True, return_value=slow) as run:
            first = self.Drawing.attachment_preview(self.attachment.id)
            second = self.Drawing.attachment_preview(self.attachment.id)
        self.assertEqual(run.call_count, 1, "тяжёлый файл не занимает процесс при каждом открытии")
        self.assertEqual((first['reason'], second['reason']), ('долго', 'долго'))
        self.assertNotIn('slow', first)
        cached = self.Cache.search([('checksum', '=', self.checksum)])
        self.assertTrue(cached.expires)
        left = cached.expires - fields.Datetime.now()
        self.assertTrue(datetime.timedelta(hours=23) < left <= datetime.timedelta(hours=24))
        # Сутки прошли — пробуем нарисовать снова.
        cached.expires = fields.Datetime.now() - datetime.timedelta(minutes=1)
        cached.flush_recordset(['expires'])     # кэш читается отдельным курсором
        with self._in_process() as run:
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(payload['ok'], payload.get('reason'))

    def test_cache_trimmed_to_recent_not_wiped(self):
        # Штатная уборка временной модели по числу стирает ВСЁ старше 5 минут —
        # она выключена; своя оставляет MAX_CACHE_ROWS последних.
        self.assertEqual(self.env['pmk.drawing.preview']._transient_max_count, 0)
        self.Cache.search([]).unlink()
        version = self.Drawing._cache_version()
        with mock.patch.object(drawing_module, 'MAX_CACHE_ROWS', 2):
            for checksum in ('a' * 40, 'b' * 40, 'c' * 40):
                self.Drawing._cache_put(checksum, version, {'ok': False, 'reason': checksum})
        self.assertEqual(sorted(self.Cache.search([]).mapped('checksum')), ['b' * 40, 'c' * 40])
        self.assertEqual(self.Drawing._cache_get('c' * 40, version)['reason'], 'c' * 40)

    def test_opening_marks_recent_use(self):
        version = self.Drawing._cache_version()
        self.Drawing._cache_put('d' * 40, version, {'ok': False, 'reason': 'старый'})
        record = self.Cache.search([('checksum', '=', 'd' * 40)])
        old = fields.Datetime.now() - datetime.timedelta(days=10)
        self.env.cr.execute("UPDATE pmk_drawing_preview SET write_date = %s WHERE id = %s",
                            (old, record.id))
        self.assertEqual(self.Drawing._cache_get('d' * 40, version)['reason'], 'старый')
        record.invalidate_recordset(['write_date'])
        self.assertGreater(record.write_date, old + datetime.timedelta(days=9),
                           "ходовой чертёж не уходит вместе с забытыми")

    def test_cache_version_follows_renderer_source(self):
        version = self.Drawing._cache_version()
        self.assertNotEqual(drawing_module.RENDERER_DIGEST, '-')
        self.assertTrue(version.endswith('/' + drawing_module.RENDERER_DIGEST),
                        "правка tools/dxf_render.py сбрасывает кэш без ручного шага")

    def test_too_big_not_loaded(self):
        # Предел известен по размеру вложения — байты не читаются вовсе.
        with mock.patch.object(R, 'MAX_FILE_BYTES', 100), \
                mock.patch.object(type(self.Drawing), '_render_blob', autospec=True,
                                  side_effect=AssertionError("байты в память")):
            payload = self.Drawing.attachment_preview(self.attachment.id)
        self.assertFalse(payload['ok'])
        self.assertIn('больше предела просмотра', payload['reason'])

    def test_not_a_drawing(self):
        pdf = self.env['ir.attachment'].create({
            'name': 'чертёж.dxf', 'raw': b'%PDF-1.4\n%\xe2\xe3\n1 0 obj\n',
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        payload = self.Drawing.attachment_preview(pdf.id)
        self.assertEqual((payload['ok'], payload['reason']), (False, R.NOT_DXF))
        url = self.env['ir.attachment'].create({
            'name': 'ссылка.dxf', 'type': 'url', 'url': 'https://example.org/a.dxf',
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        self.assertIn('ссылка', self.Drawing.attachment_preview(url.id)['reason'])

    def test_missing_attachment(self):
        with self.assertRaises(UserError):
            self.Drawing.attachment_preview(999999999)

    def test_rights(self):
        portal = new_test_user(self.env, login='dxf_portal', groups='base.group_portal')
        with self.assertRaises(AccessError):
            self.Drawing.with_user(portal).attachment_preview(self.attachment.id)
        # Вложение без документа-владельца видит только его автор (и админ).
        orphan = self.env['ir.attachment'].create({'name': 'ничьё.dxf', 'raw': self.blob})
        clerk = new_test_user(self.env, login='dxf_clerk', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.Drawing.with_user(clerk).attachment_preview(orphan.id)
        with self._in_process():
            payload = self.Drawing.with_user(clerk).attachment_preview(self.attachment.id)
        self.assertTrue(payload['ok'], "контрагента сотрудник видит — и чертёж его")


@tagged('post_install', '-at_install')
@skipUnless(HAS_EZDXF, "нет ezdxf")
class TestDrawingProcess(TransactionCase):
    """Настоящий отдельный процесс — как на стенде."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry_enter_test_mode_cls()

    def test_subprocess_renders(self):
        result = self.env['pmk.drawing']._run_renderer(S.factory_dxf())
        self.assertTrue(result['ok'], result.get('reason') or result.get('detail'))
        self.assertIn('Размеры', [layer['name'] for layer in result['layers']])
        self.assertTrue(result['cache'])

    def test_subprocess_refuses_words(self):
        result = self.env['pmk.drawing']._run_renderer(b'hello')
        self.assertEqual((result['ok'], result['reason']), (False, R.NOT_DXF))

    def test_subprocess_timeout(self):
        with mock.patch.object(drawing_module, 'RENDER_TIMEOUT', 0.001):
            result = self.env['pmk.drawing']._run_renderer(S.many_lines_dxf(2000))
        self.assertFalse(result['ok'])
        self.assertIn('слишком долго', result['reason'])
        self.assertFalse(result['cache'])
        self.assertTrue(result['slow'], "отказ по времени помнится сутки")

    def test_subprocess_skips_broken_entity(self):
        doc = S.new_doc()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], close=True)
        msp.add_spline(fit_points=[(0, 0), (10, 10), (10, 10)])
        result = self.env['pmk.drawing']._run_renderer(S.to_bytes(doc))
        self.assertTrue(result['ok'], result.get('reason') or result.get('detail'))
        self.assertEqual(result['skipped']['total'], 1)
