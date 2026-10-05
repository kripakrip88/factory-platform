# -*- coding: utf-8 -*-
"""Шаг 46: чертёж DXF -> пути по слоям (tools/dxf_render.py), без базы.

Чертежи собираются ezdxf прямо в тесте (tests/dxf_samples.py): русские
тексты в cp1251 и кодировка, указанная неверно или не указанная вовсе;
UTF-8 (R2010) и двоичный DXF; слои всех цветов, выключенный слой; блок во
блоке с масштабом и поворотом; дуга в полилинии; размер; штриховка; тело 3D
и подложка (не рисуются — «не показано»); лист вместо пустой модели;
обрезанный файл; пределы размера, числа объектов и времени. Доводка шага:
объект, на котором ezdxf падает (вырожденный сплайн, вставка), пропускается
и считается, а не роняет чертёж; габарит — по слоям, включённым в файле;
бесконечный габарит — отказ словами, а не «Infinity» в JSON.

render() гоняется прямо в процессе теста — его отдельный процесс
проверяет test_drawing_model.py (TestDrawingProcess).

Гонять на одноразовой базе:
    odoo -d dxf_test -i pmk_drawing --test-enable \\
         --test-tags /pmk_drawing --stop-after-init
"""
import io
import json
import re
import sys
from unittest import mock, skipUnless

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_drawing.tests import dxf_samples as S
from odoo.addons.pmk_drawing.tools import dxf_render as R

try:
    import ezdxf  # noqa: F401
    HAS_EZDXF = True
except ImportError:                                        # pragma: no cover
    HAS_EZDXF = False

D_RE = re.compile(r'^[MLHVCSQTAZmlhvcsqtaz0-9eE.,\s+-]*$')


def by_layer(result):
    """{имя слоя: [(вид, цвет, d), …]}"""
    out = {}
    for layer, kind, color, d in result['items']:
        out.setdefault(result['layers'][layer]['name'], []).append(
            (kind, result['palette'][color], d))
    return out


@tagged('post_install', '-at_install')
class TestDxfSniff(TransactionCase):
    """До разбора: что за файл и сколько в нём объектов — без ezdxf."""

    def test_sniff(self):
        self.assertEqual(R.sniff(b'  0\nSECTION\n  2\nHEADER\n'), 'ascii')
        self.assertEqual(R.sniff(b'999\ndxfrw 0.6\n  0\nSECTION\n'), 'ascii', "комментарий 999 перед SECTION")
        self.assertEqual(R.sniff(b'\xef\xbb\xbf  0\r\nSECTION\r\n'), 'ascii', "BOM и CRLF")
        self.assertEqual(R.sniff(R.BINARY_SIGNATURE + b'\x00\x00'), 'binary')
        for blob in (b'%PDF-1.4\n', b'PK\x03\x04', b'hello', b''):
            with self.subTest(blob=blob):
                self.assertIsNone(R.sniff(blob))

    def test_count_zero_tags_ignores_zero_values(self):
        # «0» как ЗНАЧЕНИЕ группы (70, 100…) — не объект: за ним номер группы.
        blob = b'  0\nSECTION\n  2\nENTITIES\n  0\nLINE\n 70\n0\n100\nAcDbLine\n  0\n3DFACE\n  0\nENDSEC\n'
        self.assertEqual(R.count_zero_tags(blob), 3, "LINE, 3DFACE, ENDSEC (первая строка без \\n перед ней)")
        self.assertEqual(R.count_zero_tags(blob, stop_after=1), 2, "счёт обрывается на пределе")

    @skipUnless(HAS_EZDXF, "нет ezdxf")
    def test_refusals_before_parsing(self):
        blob = S.factory_dxf()
        size = R.render(blob, limits={'file_bytes': 1000})
        self.assertFalse(size['ok'])
        self.assertIn('больше предела просмотра', size['reason'])
        tags = R.render(S.many_lines_dxf(300), limits={'zero_tags': 100})
        self.assertIn('больше 100 объектов', tags['reason'])
        self.assertTrue(tags['cache'], "отказ по размеру повторится на тех же байтах")
        self.assertEqual(R.render(b'%PDF-1.4 ...')['reason'], R.NOT_DXF)
        self.assertEqual(R.render(b'')['reason'], "Файл пустой.")


@tagged('post_install', '-at_install')
@skipUnless(HAS_EZDXF, "нет ezdxf")
class TestDxfRender(TransactionCase):
    """Отрисовка ezdxf: слои, цвета, тексты, блоки, размеры, оговорки."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = R.render(S.factory_dxf())

    def test_contract(self):
        res = self.factory
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertEqual(res['version'], R.PAYLOAD_VERSION)
        width, height = res['viewbox']
        self.assertEqual(max(width, height), 1_000_000, "координаты — целые до миллиона")
        self.assertGreater(min(width, height), 0)
        for layer, kind, color, d in res['items']:
            self.assertLess(layer, len(res['layers']))
            self.assertIn(kind, (0, 1, 2))
            self.assertLess(color, len(res['palette']))
            self.assertRegex(d, D_RE, "в путях только команды и числа")
        for color in res['palette'] + [layer['color'] for layer in res['layers']]:
            self.assertRegex(color, r'^#[0-9a-f]{6}$')
        for layer in res['layers']:
            x0, y0, x1, y1 = layer['box']
            self.assertTrue(all(isinstance(value, int) for value in layer['box']))
            self.assertLessEqual((x0, y0), (x1, y1))
        self.assertTrue(res['cache'])
        self.assertNotIn('slow', res)
        self.assertEqual(res['stats']['items'], len(res['items']))
        json.loads(R.dump(res))

    def test_layers_colors_and_hidden_layer(self):
        res = self.factory
        layers = {layer['name']: layer for layer in res['layers']}
        self.assertEqual(set(layers), {'КОНТУР', 'Размеры', 'Белый', 'Жёлтый', 'Истинный', 'Скрытый'},
                         "русские имена слоёв из cp1251")
        self.assertEqual(layers['КОНТУР']['color'], '#ff0000')
        self.assertEqual(layers['Размеры']['color'], '#00ff00')
        self.assertEqual(layers['Жёлтый']['color'], '#ffff00')
        self.assertEqual(layers['Белый']['color'], '#000000', "ACI 7 на белом листе — чёрный")
        self.assertFalse(layers['Скрытый']['on'], "выключен в файле — галочка снята")
        self.assertTrue(all(layers[name]['on'] for name in layers if name != 'Скрытый'))
        self.assertIn('Скрытый', by_layer(res), "выключенный слой нарисован — его можно включить")
        self.assertIn("Слоёв выключено в самом файле: 1", ' '.join(res['notes']))
        contour = by_layer(res)['КОНТУР']
        self.assertTrue(all(color == '#ff0000' for _kind, color, _d in contour))

    def test_units_and_size(self):
        res = self.factory
        self.assertEqual(res['units'], {'code': 4, 'label': 'мм', 'assumed': False})
        self.assertEqual(res['layout'], 'Model')
        self.assertGreater(res['size_mm'][0], 300)

    def test_texts_are_glyphs(self):
        # Тексты TEXT и MTEXT — залитые контуры шрифта на своём слое.
        fills = [item for item in by_layer(self.factory)['Белый'] if item[0] == 1]
        self.assertGreaterEqual(len(fills), 2)
        # Кириллица — не «пустые квадраты»: «Ж» и «?» дают разные контуры.
        def glyph(text):
            doc = S.new_doc()
            doc.modelspace().add_text(text, height=10)
            return R.render(S.to_bytes(doc))['items'][0]
        cyr, ask = glyph('Ж'), glyph('?')
        self.assertEqual(cyr[1], 1)
        self.assertNotEqual(cyr[3], ask[3])

    def test_dimension_whole_layer(self):
        # Размер целиком на своём слое и своим цветом: выносные и размерная
        # линия лежат в блоке размера слоем «0» и цветом «по блоку».
        doc = S.new_doc(setup=True)
        doc.layers.add('Размеры', color=3)
        dim = doc.modelspace().add_linear_dim(base=(0, -20), p1=(0, 0), p2=(200, 0),
                                              dxfattribs={'layer': 'Размеры'})
        dim.render()
        res = R.render(S.to_bytes(doc))
        self.assertEqual([layer['name'] for layer in res['layers']], ['Размеры'])
        self.assertEqual(res['palette'], ['#00ff00'])
        kinds = {kind for _layer, kind, _color, _d in res['items']}
        self.assertEqual(kinds, {0, 1}, "линии и залитые стрелки с текстом")

    def test_nested_insert_scale_rotation(self):
        doc = S.new_doc()
        doc.layers.add('КОНТУР', color=1)
        node = doc.blocks.new('УЗЕЛ')
        node.add_circle((0, 0), 5)
        node.add_line((-5, 0), (5, 0))
        outer = doc.blocks.new('ВНЕШ')
        outer.add_blockref('УЗЕЛ', (10, 10))
        doc.modelspace().add_blockref('ВНЕШ', (300, 0), dxfattribs={
            'layer': 'КОНТУР', 'xscale': 2, 'yscale': 2, 'rotation': 30})
        res = R.render(S.to_bytes(doc))
        # Окружность r=5 при масштабе 2 — габарит 20 × 20.
        self.assertAlmostEqual(res['size_mm'][0], 20.0, places=1)
        self.assertAlmostEqual(res['size_mm'][1], 20.0, places=1)
        self.assertEqual([layer['name'] for layer in res['layers']], ['КОНТУР'],
                         "слой «0» в блоке — слой вставки")
        self.assertEqual(res['palette'], ['#ff0000'])

    def test_polyline_bulge_arc(self):
        doc = S.new_doc()
        doc.modelspace().add_lwpolyline(
            [(0, 0, 0, 0, 0), (100, 0, 0, 0, 1), (100, 50, 0, 0, 0)], format='xyseb')
        res = R.render(S.to_bytes(doc))
        # Полуокружность на отрезке 100,0 -> 100,50 выпирает вправо на 25.
        self.assertAlmostEqual(res['size_mm'][0], 125.0, places=1)
        self.assertAlmostEqual(res['size_mm'][1], 50.0, places=1)
        self.assertRegex(res['items'][0][3], r'[cC]', "дуга — кривой, а не хордой")

    def test_circle_ellipse_spline_point(self):
        for name, add in (
                ('circle', lambda m: m.add_circle((0, 0), 10)),
                ('arc', lambda m: m.add_arc((0, 0), 10, 0, 90)),
                ('ellipse', lambda m: m.add_ellipse((0, 0), major_axis=(30, 0), ratio=0.5)),
                ('spline', lambda m: m.add_spline([(0, 0), (10, 20), (30, 10), (50, 40)])),
                ('point', lambda m: m.add_point((5, 5)))):
            with self.subTest(entity=name):
                doc = S.new_doc()
                add(doc.modelspace())
                res = R.render(S.to_bytes(doc))
                self.assertTrue(res['ok'], res.get('reason'))
                self.assertEqual(res['skipped']['total'], 0)

    def test_hatch_outline_only(self):
        doc = S.new_doc()
        hatch = doc.modelspace().add_hatch(color=2)
        hatch.paths.add_polyline_path([(0, 0), (20, 0), (20, 20), (0, 20)], is_closed=True)
        res = R.render(S.to_bytes(doc))
        self.assertEqual({kind for _l, kind, _c, _d in res['items']}, {0},
                         "штриховка — контуром, без заливки")

    def test_skipped_counted(self):
        res = R.render(S.solid3d_dxf())
        self.assertTrue(res['ok'])
        self.assertEqual(res['skipped']['total'], 2)
        self.assertEqual(dict(res['skipped']['by_label']), {'тело 3D': 1, 'подложка PDF': 1})
        self.assertIn('Не показано объектов: 2', ' '.join(res['notes']))

    def test_codepage_mislabeled_or_missing(self):
        blob = S.factory_dxf()
        for label, broken in (('ANSI_1252', S.with_codepage(blob, 'ANSI_1252')),
                              ('нет', S.with_codepage(blob, None))):
            with self.subTest(codepage=label):
                fixed, note = R.fix_codepage(broken)
                self.assertIn('прочитали как русскую (cp1251)', note)
                doc, notes, truncated = R.load(broken)
                self.assertFalse(truncated)
                texts = [entity.dxf.text for entity in doc.modelspace().query('TEXT')]
                self.assertEqual(texts, ['Деталь №1 — лист 3 мм'])
                self.assertIn('КОНТУР', [layer.dxf.name for layer in doc.layers])
                res = R.render(broken)
                self.assertIn('КОНТУР', [layer['name'] for layer in res['layers']])
        # Указано верно — без оговорки.
        self.assertEqual(R.fix_codepage(blob), (blob, ''))

    def test_utf8_r2010_and_true_color(self):
        res = R.render(S.utf8_r2010())
        layers = {layer['name']: layer for layer in res['layers']}
        self.assertEqual(layers['Ось']['color'], '#00ffff')
        self.assertEqual(layers['Истинный']['color'], '#c86432', "истинный цвет слоя")
        self.assertEqual(res['units']['label'], 'м')
        self.assertAlmostEqual(res['size_mm'][0], 2500.0, places=0, msg="метры -> миллиметры")
        self.assertEqual(res['notes'], [])

    def test_binary_dxf(self):
        res = R.render(S.binary_dxf())
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertEqual(len(res['layers']), len(self.factory['layers']))
        self.assertIn('КОНТУР', [layer['name'] for layer in res['layers']])

    def test_paperspace_when_model_empty(self):
        res = R.render(S.paperspace_only_dxf())
        self.assertEqual(res['layout'], 'Лист1')
        self.assertIn('В модели пусто — показан лист «Лист1»', ' '.join(res['notes']))

    def test_unitless(self):
        res = R.render(S.unitless_dxf())
        self.assertTrue(res['units']['assumed'])
        self.assertEqual(res['size_mm'], [1500.0, 300.0])
        self.assertIn('Единицы в файле не заданы', ' '.join(res['notes']))

    def test_single_line_has_height(self):
        res = R.render(S.single_line_dxf())
        self.assertTrue(res['ok'])
        self.assertGreater(res['viewbox'][1], 0, "линия без высоты — не пустой лист")
        self.assertEqual(res['size_mm'], [500.0, 0.0])

    def test_empty_and_truncated(self):
        empty = R.render(S.empty_dxf())
        self.assertEqual((empty['ok'], empty['reason']), (False, R.EMPTY))
        truncated = R.render(S.broken_dxf())
        self.assertEqual((truncated['ok'], truncated['reason']), (False, R.TRUNCATED))

    def test_image_file_never_read(self):
        doc = S.new_doc()
        image = doc.add_image_def(filename='/etc/hostname', size_in_pixel=(100, 100))
        doc.modelspace().add_image(image, insert=(0, 0), size_in_units=(10, 10))
        import PIL.Image
        with mock.patch.object(PIL.Image, 'open', side_effect=AssertionError("файл с диска")):
            res = R.render(S.to_bytes(doc))
        self.assertTrue(res['ok'], "картинка — рамкой, файл с диска сервера не читается")

    def test_self_inserted_block(self):
        doc = S.new_doc()
        block = doc.blocks.new('САМ')
        block.add_line((0, 0), (1, 1))
        block.add_blockref('САМ', (1, 1))
        doc.modelspace().add_blockref('САМ', (0, 0))
        res = R.render(S.to_bytes(doc))
        self.assertFalse(res['ok'])
        self.assertIn('вставлен сам в себя', res['reason'])

    def test_entity_limit_counts_block_contents(self):
        res = R.render(S.block_bomb_dxf(20), limits={'entities': 1000})
        self.assertFalse(res['ok'])
        self.assertIn('вместе с содержимым блоков', res['reason'])

    def test_time_limit_not_cached(self):
        res = R.render(S.many_lines_dxf(3000), limits={'deadline': 0.0})
        self.assertFalse(res['ok'])
        self.assertIn('слишком долго', res['reason'])
        self.assertFalse(res['cache'], "занятый сервер — не свойство файла: не на месяц")
        self.assertTrue(res['slow'], "но на сутки — models/drawing.py, SLOW_CACHE_HOURS")

    def test_dashed_lines_fall_back_to_solid(self):
        res = R.render(S.many_lines_dxf(400, dashed=True), limits={'items': 1000, 'chars': 200_000})
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertIn('штриховые линии показаны сплошными', ' '.join(res['notes']))

    def test_layer_names_case_insensitive(self):
        # «контур» у объекта и «КОНТУР» в таблице — один слой, одна галочка,
        # имя — как в таблице; выключен в файле — снятым.
        doc = S.new_doc()
        doc.layers.add('КОНТУР', color=1).off()
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 0), dxfattribs={'layer': 'КОНТУР'})
        msp.add_circle((50, 0), 5, dxfattribs={'layer': 'контур'})
        res = R.render(S.to_bytes(doc))
        self.assertEqual([(layer['name'], layer['on']) for layer in res['layers']],
                         [('КОНТУР', False)])

    def test_merging_keeps_layers_apart(self):
        # 2000 линий одного слоя и цвета — один путь, а не 2000.
        res = R.render(S.many_lines_dxf(2000))
        self.assertEqual(len(res['items']), 1)
        self.assertEqual(res['stats']['entities'], 2000)

    # ------------------------------------------------------------------
    # доводка шага 46
    # ------------------------------------------------------------------
    def _contour_doc(self):
        doc = S.new_doc()
        doc.modelspace().add_lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], close=True)
        return doc

    def test_broken_entity_skipped_not_whole_drawing(self):
        # ezdxf 1.4.2 падает на них делением на ноль и IndexError, а recover
        # их не убирает. Раньше — «Файл повреждён» на весь чертёж и на месяц.
        doc = self._contour_doc()
        msp = doc.modelspace()
        msp.add_spline(fit_points=[(0, 0), (10, 10), (10, 10)])
        msp.add_spline(fit_points=[(5, 5), (5, 5)])
        block = doc.blocks.new('УЗЕЛ')
        block.add_spline(fit_points=[(0, 0), (0, 0), (10, 10), (20, 0)])
        block.add_circle((0, 0), 5)
        msp.add_blockref('УЗЕЛ', (100, 100))
        res = R.render(S.to_bytes(doc))
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertEqual(dict(res['skipped']['by_label']), {R.BROKEN_LABEL: 3})
        self.assertIn('Не показано объектов: 3 (объект с ошибкой — 3)', ' '.join(res['notes']))
        self.assertEqual(res['size_mm'], [500.0, 300.0])
        self.assertTrue(res['cache'])

    def test_failed_insert_does_not_leak_into_neighbours(self):
        # Вставка упала посреди блока: ezdxf открыл её состояние без finally.
        # Следующий объект на слое «0» не должен стать слоем и цветом вставки.
        from ezdxf.entities.insert import Insert
        doc = S.new_doc()
        doc.layers.add('Вставка', color=1)
        block = doc.blocks.new('Б')
        block.add_line((0, 0), (10, 0))
        block.add_line((0, 5), (10, 5))
        msp = doc.modelspace()
        msp.add_blockref('Б', (0, 0), dxfattribs={'layer': 'Вставка'})
        msp.add_line((0, 50), (100, 50))
        original = Insert.virtual_entities

        def broken(self, *args, **kwargs):
            entities = original(self, *args, **kwargs)
            yield next(entities)
            raise ZeroDivisionError("масштаб вставки")

        with mock.patch.object(Insert, 'virtual_entities', broken):
            res = R.render(S.to_bytes(doc))
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertEqual(res['skipped']['total'], 1)
        self.assertEqual(sorted(by_layer(res)), ['0', 'Вставка'])
        self.assertEqual({color for _k, color, _d in by_layer(res)['0']}, {'#000000'})

    def test_recursion_still_refused(self):
        # Перехват сбоя объекта не глотает «блок сам в себе» и пределы.
        doc = S.new_doc()
        block = doc.blocks.new('САМ')
        block.add_line((0, 0), (1, 1))
        block.add_blockref('САМ', (1, 1))
        doc.modelspace().add_blockref('САМ', (0, 0))
        self.assertIn('вставлен сам в себя', R.render(S.to_bytes(doc))['reason'])
        self.assertIn('вместе с содержимым блоков',
                      R.render(S.block_bomb_dxf(20), limits={'entities': 1000})['reason'])

    def test_hidden_layers_not_in_extent(self):
        # Контур 500 × 300 и мусор на замороженном слое в 100 м сбоку: габарит
        # и рамка — по контуру, мусор рисуется в тех же координатах за краем.
        doc = S.new_doc()
        doc.layers.add('Контур', color=1)
        doc.layers.add('Старое', color=3).freeze()
        doc.layers.add('Выкл', color=5).off()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], close=True,
                           dxfattribs={'layer': 'Контур'})
        msp.add_line((100000, 100000), (100010, 100000), dxfattribs={'layer': 'Старое'})
        msp.add_circle((-5000, 0), 10, dxfattribs={'layer': 'Выкл'})
        res = R.render(S.to_bytes(doc))
        self.assertEqual(res['size_mm'], [500.0, 300.0])
        width, height = res['viewbox']
        layers = {layer['name']: layer for layer in res['layers']}
        for got, expected in zip(layers['Контур']['box'], [0, 0, width, height]):
            self.assertAlmostEqual(got, expected, delta=2, msg="контур — во весь лист")
        for name in ('Старое', 'Выкл'):
            self.assertFalse(layers[name]['on'])
            x0, _y0, x1, _y1 = layers[name]['box']
            self.assertTrue(x1 < 0 or x0 > width, "%s — за краем листа" % name)
            self.assertIn(name, by_layer(res), "нарисован — включается галочкой")

    def test_all_layers_off_falls_back_to_everything(self):
        doc = S.new_doc()
        doc.layers.add('Выкл', color=5).off()
        doc.modelspace().add_line((0, 0), (200, 0), dxfattribs={'layer': 'Выкл'})
        res = R.render(S.to_bytes(doc))
        self.assertTrue(res['ok'], res.get('reason'))
        self.assertEqual(res['size_mm'], [200.0, 0.0])

    def test_infinite_extent_refused_in_words(self):
        doc = S.new_doc()
        doc.modelspace().add_line((-1e308, 0), (1e308, 0))
        res = R.render(S.to_bytes(doc))
        self.assertEqual((res['ok'], res['reason']), (False, R.BAD_SIZE))
        # Гигаметры: координаты конечны, а габарит в мм — уже нет.
        doc = S.new_doc(units=17)
        doc.modelspace().add_line((0, 0), (1e300, 1e299))
        self.assertEqual(R.render(S.to_bytes(doc))['reason'], R.BAD_SIZE)

    def test_dump_never_writes_infinity(self):
        def strict(text):
            return json.loads(text, parse_constant=lambda name: self.fail("в JSON %s" % name))
        self.assertEqual(strict(R.dump({'ok': True, 'size_mm': [float('inf'), 1.0]}))['reason'],
                         R.BAD_SIZE)
        self.assertEqual(strict(R.dump({'ok': True, 'size_mm': [1.5, 2]}))['size_mm'], [1.5, 2])

    def test_main_unexpected_failure_not_cached(self):
        # Сбой мог быть нашим — после исправления тот же файл должен открыться.
        out = io.BytesIO()
        with mock.patch.object(R, 'render', side_effect=RuntimeError("сбой")), \
                mock.patch.object(R, '_limit_resources'), \
                mock.patch.object(sys, 'stdin', mock.Mock(buffer=io.BytesIO(b'x'))), \
                mock.patch.object(sys, 'stdout', mock.Mock(buffer=out)):
            R.main()
        result = json.loads(out.getvalue())
        self.assertEqual((result['ok'], result['reason'], result['cache']), (False, R.BROKEN, False))
        self.assertIn('сбой', result['detail'])
