# -*- coding: utf-8 -*-
"""Тестовые чертежи DXF — собираются здесь же, библиотекой ezdxf, в памяти.

Ни одного файла с диска: чертёж «как от клиента» описан кодом — русские
тексты в cp1251, слои всех цветов, блоки во блоках с масштабом и поворотом,
дуги в полилинии, размеры, штриховка, точка, тело 3D (не рисуется — должно
попасть в «не показано»), выключенный слой.
"""
import io
import re


def _to_bytes(doc, encoding=None):
    """Текст DXF в байтах — в кодировке, которой его пишет ezdxf (R2007+ —
    UTF-8, раньше — кодовая страница заголовка)."""
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode(encoding or doc.output_encoding)


def new_doc(version='R2010', units=4, setup=False):
    """Пустой чертёж в миллиметрах (ezdxf.new по умолчанию ставит метры)."""
    import ezdxf

    doc = ezdxf.new(version, setup=setup)
    doc.header['$INSUNITS'] = units
    return doc


def to_bytes(doc):
    return _to_bytes(doc)


def factory_doc():
    """Чертёж «как от клиента», R2000, кодовая страница ANSI_1251."""
    import ezdxf

    doc = ezdxf.new('R2000', setup=True)
    doc.encoding = 'cp1251'
    doc.header['$INSUNITS'] = 4                      # мм
    msp = doc.modelspace()
    doc.layers.add('КОНТУР', color=1)                # красный
    doc.layers.add('Размеры', color=3)               # зелёный
    doc.layers.add('Белый', color=7)                 # белый/чёрный
    doc.layers.add('Жёлтый', color=2)                # жёлтый
    doc.layers.add('Истинный', true_color=ezdxf.rgb2int((200, 100, 50)))
    hidden = doc.layers.add('Скрытый', color=5)
    hidden.off()

    msp.add_line((0, 0), (200, 0), dxfattribs={'layer': 'КОНТУР'})
    # Полилиния с дугой (bulge = 1 — полуокружность).
    msp.add_lwpolyline([(0, 0, 0, 0, 0), (100, 0, 0, 0, 1), (100, 50, 0, 0, 0)],
                       format='xyseb', dxfattribs={'layer': 'КОНТУР'})
    msp.add_circle((50, 50), 10, dxfattribs={'layer': 'Белый'})
    msp.add_arc((150, 50), 20, 0, 90, dxfattribs={'layer': 'Истинный'})
    msp.add_ellipse((50, 100), major_axis=(30, 0), ratio=0.5, dxfattribs={'layer': 'Жёлтый'})
    msp.add_spline([(0, 0), (10, 20), (30, 10), (50, 40)], dxfattribs={'layer': 'Жёлтый'})
    msp.add_text('Деталь №1 — лист 3 мм', height=5,
                 dxfattribs={'layer': 'Белый'}).set_placement((10, 120))
    msp.add_mtext('Многострочный\\Pтекст: кронштейн', dxfattribs={
        'layer': 'Белый', 'char_height': 4}).set_location((10, 140))
    # Блок во блоке, вставка с масштабом и поворотом.
    node = doc.blocks.new('УЗЕЛ')
    node.add_circle((0, 0), 5)                        # слой «0» — слой вставки
    node.add_line((-5, 0), (5, 0))
    outer = doc.blocks.new('ВНЕШ')
    outer.add_blockref('УЗЕЛ', (10, 10))
    msp.add_blockref('ВНЕШ', (300, 0), dxfattribs={
        'layer': 'КОНТУР', 'xscale': 2, 'yscale': 2, 'rotation': 30})
    dim = msp.add_linear_dim(base=(0, -20), p1=(0, 0), p2=(200, 0),
                             dxfattribs={'layer': 'Размеры'})
    dim.render()
    hatch = msp.add_hatch(color=2, dxfattribs={'layer': 'Жёлтый'})
    hatch.paths.add_polyline_path([(0, 0), (20, 0), (20, 20), (0, 20)], is_closed=True)
    msp.add_point((5, 5), dxfattribs={'layer': 'Белый'})
    msp.add_line((0, 200), (50, 200), dxfattribs={'layer': 'Скрытый'})
    return doc


def factory_dxf():
    return _to_bytes(factory_doc(), 'cp1251')


def with_codepage(blob, codepage):
    """Тот же файл, но кодовая страница в заголовке — другая (или нет её)."""
    if codepage is None:
        return re.sub(rb'[ \t]*9\r?\n\$DWGCODEPAGE\r?\n[ \t]*3\r?\n[^\r\n]*\r?\n', b'', blob)
    return re.sub(rb'(\$DWGCODEPAGE\r?\n[ \t]*3\r?\n)[^\r\n]*', rb'\g<1>' + codepage.encode(), blob)


def utf8_r2010():
    import ezdxf

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6                      # метры
    doc.layers.add('Ось', color=4)
    # Истинный цвет (true color) — с R2004; в R2000 он не записывается.
    doc.layers.add('Истинный', true_color=ezdxf.rgb2int((200, 100, 50)))
    msp = doc.modelspace()
    msp.add_text('Привет, UTF-8', height=0.1, dxfattribs={'layer': 'Ось'})
    msp.add_line((0, 0), (2.5, 1.2), dxfattribs={'layer': 'Ось'})
    msp.add_arc((1, 1), 0.2, 0, 90, dxfattribs={'layer': 'Истинный'})
    return _to_bytes(doc, 'utf-8')


def binary_dxf():
    stream = io.BytesIO()
    factory_doc().write(stream, fmt='bin')
    return stream.getvalue()


def solid3d_dxf():
    import ezdxf

    doc = new_doc()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 10))
    # Тело 3D с данными ACIS (пустое recover выбрасывает при проверке).
    solid = msp.add_3dsolid()
    solid.sat = ['400 0 1 0', '16Autodesk AutoCAD 19 ASM 222.0.0.0 NT 0']
    underlay = doc.add_underlay_def('подложка.pdf', fmt='pdf', name='1')
    msp.add_underlay(underlay, insert=(0, 0))
    return _to_bytes(doc)


def paperspace_only_dxf():
    import ezdxf

    doc = new_doc()
    sheet = doc.layouts.new('Лист1')
    sheet.add_line((0, 0), (100, 50))
    sheet.add_text('Штамп', height=5)
    return _to_bytes(doc, 'utf-8')


def unitless_dxf():
    import ezdxf

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 0
    doc.modelspace().add_line((0, 0), (1500, 0))
    doc.modelspace().add_line((0, 0), (0, 300))
    return _to_bytes(doc, 'utf-8')


def single_line_dxf():
    """Линия без высоты: лист нулевой высоты ezdxf нарисовал бы пустым."""
    import ezdxf

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 4
    doc.modelspace().add_line((0, 0), (500, 0))
    return _to_bytes(doc, 'utf-8')


def many_lines_dxf(count, dashed=False):
    import ezdxf

    doc = ezdxf.new('R2010', setup=True)
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    attribs = {'linetype': 'DASHED', 'ltscale': 0.05} if dashed else {}
    for index in range(count):
        msp.add_line((index, 0), (index, 1000), dxfattribs=attribs)
    return _to_bytes(doc, 'utf-8')


def block_bomb_dxf(width=60):
    """Блок на width линий, вставленный width×width раз: файл маленький,
    линий — width³ (при 60 — 216 000)."""
    import ezdxf

    doc = new_doc()
    leaf = doc.blocks.new('ЛИСТ')
    for index in range(width):
        leaf.add_line((index, 0), (index, 1))
    row = doc.blocks.new('РЯД')
    for index in range(width):
        row.add_blockref('ЛИСТ', (0, index * 2))
    msp = doc.modelspace()
    for index in range(width):
        msp.add_blockref('РЯД', (index * 100, 0))
    return _to_bytes(doc, 'utf-8')


def empty_dxf():
    import ezdxf

    return _to_bytes(ezdxf.new('R2010'), 'utf-8')


def broken_dxf():
    """Обрезанный посреди раздела объектов файл."""
    blob = factory_dxf()
    return blob[:len(blob) // 3]
