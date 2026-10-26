# -*- coding: utf-8 -*-
"""Доборки и вентзонты с цветом RAL — на окрашенный лист той же толщины (26.10.2026,
sheet_coating.py). SQL, без ORM: масса и толщина те же, пересчитывать развёртки
вентзонтов (генератор) незачем. Пары нет (0,55 / 0,6 / 0,7) — лист не меняется."""


def migrate(cr, version):
    for table in ("pmk_dobor_order_line", "pmk_vent_hood"):
        cr.execute("""
            UPDATE %s t
               SET sheet_id = p.id
              FROM pmk_dobor_coating c, pmk_metal_sheet z, pmk_metal_sheet p
             WHERE c.id = t.coating_id AND coalesce(trim(c.ral_code), '') <> ''
               AND z.id = t.sheet_id AND z.sheet_type = 'Оцинкованный'
               AND p.sheet_type = 'Окрашенный' AND abs(p.thickness_mm - z.thickness_mm) < 0.000001
        """ % table)
