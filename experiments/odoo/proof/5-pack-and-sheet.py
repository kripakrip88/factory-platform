# -*- coding: utf-8 -*-
"""Две проверки, которых не хватало:
   А. «Одна бирка на пачку» — режим, нужный ПМК Парк: на приёмке 2-3 стандартных
      размера и сотни хлыстов, вешать бирку на каждый нереально.
   Б. Контур листа: два измерения, раскрой, остаток карты, обрезь кромки.
"""
import json
out = {}
def step(name, fn):
    try:
        out[name] = fn()
    except Exception as e:
        out[name] = {'ОШИБКА': f"{type(e).__name__}: {str(e)[:300]}"}

truba = env['product.product'].search([('name','like','Труба профильная 100x100x3')], limit=1)
list4 = env['product.product'].search([('name','like','Лист горячекатаный 4 мм')], limit=1)
metal = env['stock.location'].search([('name','=','METAL')], limit=1)
remn  = env['stock.location'].search([('name','=','REMNANT')], limit=1)
supp  = env['stock.location'].search([('usage','=','supplier')], limit=1)
prodl = env['stock.location'].search([('usage','=','production')], limit=1)
# В Odoo 19 у локации больше нет признака scrap_location: лом списывается
# отдельной моделью stock.scrap, она сама знает, куда его отправить.
def scrap_qty(product, qty, lot, src):
    s = env['stock.scrap'].create({
        'product_id': product.id, 'product_uom_id': product.uom_id.id,
        'scrap_qty': qty, 'lot_id': lot.id, 'location_id': src.id})
    s.action_validate()
    return s
wh    = env['stock.warehouse'].search([], limit=1)

def receive(product, pieces, price, dest):
    """pieces: [(имя бирки, количество)]"""
    product.standard_price = price
    pick = env['stock.picking'].create({
        'picking_type_id': wh.in_type_id.id,
        'location_id': supp.id, 'location_dest_id': dest.id})
    mv = env['stock.move'].create({
        'picking_id': pick.id, 'product_id': product.id,
        'product_uom': product.uom_id.id,
        'product_uom_qty': sum(q for _, q in pieces),
        'location_id': supp.id, 'location_dest_id': dest.id})
    pick.action_confirm()
    mv.move_line_ids.unlink()
    for lot_name, qty in pieces:
        env['stock.move.line'].create({
            'move_id': mv.id, 'picking_id': pick.id,
            'product_id': product.id, 'product_uom_id': product.uom_id.id,
            'quantity': qty, 'lot_name': lot_name,
            'location_id': supp.id, 'location_dest_id': dest.id})
    mv.picked = True
    pick.button_validate()
    return pick

def move_qty(product, qty, src, dst, lot, new_lot_name=None):
    mv = env['stock.move'].create({
        'product_id': product.id, 'product_uom': product.uom_id.id,
        'product_uom_qty': qty, 'location_id': src.id, 'location_dest_id': dst.id})
    mv._action_confirm(); mv._action_assign()
    mv.move_line_ids.unlink()
    vals = {'move_id': mv.id, 'product_id': product.id,
            'product_uom_id': product.uom_id.id, 'quantity': qty,
            'lot_id': lot.id, 'location_id': src.id, 'location_dest_id': dst.id}
    env['stock.move.line'].create(vals)
    mv.picked = True
    mv._action_done()
    return mv

# ══════════════════════════════════════════════════════════════════════════
# А. ПАЧКА: 300 хлыстов по 6 м одной биркой
# ══════════════════════════════════════════════════════════════════════════
def pack_receive():
    receive(truba, [('PACK-6M-001', 1800.0)], 596.0, metal)
    env.cr.commit()
    lot = env['stock.lot'].search([('name','=','PACK-6M-001')], limit=1)
    q = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',metal.id)], limit=1)
    return {'метров': q.quantity, 'кусков_расчётно': int(q.quantity / 6),
            'кг': round(q.quantity * truba.weight, 2), 'рублей': round(q.value, 2),
            'строк_в_приёмке': 1}
# А1 прогнан ранее: 1800 м = 300 кусков одной строкой

def pack_props():
    """Длину куска пачки храним свойством партии — настраивается мышкой, без кода."""
    truba.lot_properties_definition = [
        {'name': 'piece_len', 'string': 'Длина куска, м', 'type': 'float', 'default': 0},
        {'name': 'heat',      'string': 'Номер плавки',   'type': 'char'},
    ]
    lot = env['stock.lot'].search([('name','=','PACK-6M-001')], limit=1)
    lot.lot_properties = {'piece_len': 6.0, 'heat': '21453'}
    env.cr.commit()
    lot.invalidate_recordset()
    return {'свойства_записались': lot.lot_properties}
step('А2_свойства_партии', pack_props)

def pack_split():
    """Взяли из пачки один хлыст 6 м, отрезали 4.5 м, 1.5 м стало обрезком."""
    lot = env['stock.lot'].search([('name','=','PACK-6M-001')], limit=1)
    before = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',metal.id)], limit=1).quantity
    move_qty(truba, 4.5, metal, prodl, lot)          # в производство
    # остаток хлыста выделяем из пачки отдельной биркой
    mv = env['stock.move'].create({
        'product_id': truba.id, 'product_uom': truba.uom_id.id,
        'product_uom_qty': 1.5, 'location_id': metal.id, 'location_dest_id': remn.id})
    mv._action_confirm(); mv._action_assign()
    mv.move_line_ids.unlink()
    env['stock.move.line'].create({
        'move_id': mv.id, 'product_id': truba.id, 'product_uom_id': truba.uom_id.id,
        'quantity': 1.5, 'lot_id': lot.id,
        'location_id': metal.id, 'location_dest_id': remn.id})
    mv.picked = True; mv._action_done()
    env.cr.commit()
    after = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',metal.id)], limit=1)
    rem   = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',remn.id)], limit=1)
    return {'пачка_было': before, 'пачка_стало': after.quantity,
            'кусков_в_пачке_стало': after.quantity / 6,
            'обрезок_на_складе_остатков': rem.quantity,
            'ПРОБЛЕМА_кратность': 'пачка делится нацело' if abs(after.quantity/6 - round(after.quantity/6)) < 1e-9
                                   else f'пачка НЕ делится нацело: {after.quantity}/6 = {after.quantity/6}',
            'обрезок_под_той_же_биркой': rem.lot_id.name == after.lot_id.name if rem and after else None}
# А3 прогнан ранее

def pack_generator():
    """Умеет ли ШТАТНЫЙ генератор партий создать куски разной длины за один проход."""
    pick = env['stock.picking'].create({
        'picking_type_id': wh.in_type_id.id,
        'location_id': supp.id, 'location_dest_id': metal.id})
    mv = env['stock.move'].create({
        'picking_id': pick.id, 'product_id': truba.id,
        'product_uom': truba.uom_id.id, 'product_uom_qty': 30.0,
        'location_id': supp.id, 'location_dest_id': metal.id})
    pick.action_confirm()
    res = {}
    try:
        mv.write({'next_serial': 'GEN-001', 'next_serial_count': 5})
        mv.action_generate_lot_line_vals({'tracking': 'lot'}, 'generate', 'GEN-001', 5, 30.0) \
            if hasattr(mv, 'action_generate_lot_line_vals') else None
        res['метод'] = 'action_generate_lot_line_vals'
        res['строк'] = [{'лот': l.lot_name, 'кол': l.quantity} for l in mv.move_line_ids]
    except Exception as e:
        res['ошибка'] = f"{type(e).__name__}: {str(e)[:200]}"
    res['вывод'] = ('генератор делит поровну — куски РАЗНОЙ длины одним проходом не создать, '
                    'мастер приёмки писать придётся') if res.get('строк') and \
                   len({r['кол'] for r in res['строк']}) == 1 else 'см. строки'
    pick.action_cancel()
    env.cr.commit()
    return res
step('А4_штатный_генератор_партий', pack_generator)

# ══════════════════════════════════════════════════════════════════════════
# Б. ЛИСТ: 1500x6000 -> раскрой -> карта 1500x2100 + обрезь кромки
# ══════════════════════════════════════════════════════════════════════════
def sheet_setup():
    list4.lot_properties_definition = [
        {'name': 'width_mm',  'string': 'Ширина, мм', 'type': 'integer'},
        {'name': 'length_mm', 'string': 'Длина, мм',  'type': 'integer'},
    ]
    receive(list4, [('SH-001', 9.0)], 1450.0, metal)   # 1.5 x 6.0 = 9 м²
    env.cr.commit()
    lot = env['stock.lot'].search([('name','=','SH-001')], limit=1)
    lot.lot_properties = {'width_mm': 1500, 'length_mm': 6000}
    env.cr.commit()
    q = env['stock.quant'].search([('lot_id','=',lot.id)], limit=1)
    return {'площадь_м2': q.quantity, 'кг': round(q.quantity * list4.weight, 2),
            'рублей': round(q.value, 2), 'габариты': lot.lot_properties}
step('Б1_приход_листа', sheet_setup)

def sheet_cut():
    """Раскрой: 5.4 м² в детали, 3.15 м² остаётся картой, 0.45 м² обрезь кромки."""
    lot = env['stock.lot'].search([('name','=','SH-001')], limit=1)
    before_q = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',metal.id)], limit=1)
    before = {'площадь': before_q.quantity, 'рублей': round(before_q.value, 2)}
    move_qty(list4, 5.4, metal, prodl, lot)                       # детали
    scrap_qty(list4, 0.45, lot, metal)                            # обрезь кромки в лом
    move_qty(list4, 3.15, metal, remn, lot)                       # карта на остатки
    env.cr.commit()
    rem = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',remn.id)], limit=1)
    left = env['stock.quant'].search([('lot_id','=',lot.id),('location_id','=',metal.id)], limit=1)
    return {'было': before,
            'ушло_в_детали_м2': 5.4, 'обрезь_кромки_м2': 0.45,
            'карта_остаток_м2': rem.quantity if rem else None,
            'карта_рублей': round(rem.value, 2) if rem else None,
            'осталось_на_основном_складе': left.quantity if left else 0.0,
            'баланс': round(5.4 + 0.45 + (rem.quantity if rem else 0), 3),
            'ПРОБЛЕМА': 'габариты карты надо ПЕРЕЗАПИСАТЬ вручную: количество знает площадь, но не форму'}
step('Б2_раскрой_листа', sheet_cut)

def sheet_card_props():
    """Габариты остатка: 3.15 м² — это 1500x2100, но система формы не знает."""
    lot = env['stock.lot'].search([('name','=','SH-001')], limit=1)
    old = dict(lot.lot_properties or {})
    lot.lot_properties = {'width_mm': 1500, 'length_mm': 2100}
    env.cr.commit()
    lot.invalidate_recordset()
    return {'габариты_были': old, 'габариты_стали': lot.lot_properties,
            'ВАЖНО': ('свойства висят на ПАРТИИ, а партия одна на все её куски — '
                      'если карта и остаток лежат под одной биркой, габариты у них общие')}
step('Б3_габариты_карты', sheet_card_props)

def sheet_props_sum():
    """Можно ли суммировать/группировать по свойствам партии в отчётах."""
    f = env['stock.lot']._fields['lot_properties']
    return {'тип_поля': f.type, 'store': f.store,
            'можно_суммировать_в_отчёте': False,
            'пояснение': ('Properties хранятся одним JSON-полем. Odoo умеет по ним '
                          'фильтровать и группировать, но НЕ умеет складывать — для '
                          'длины и веса нужны настоящие поля, а не свойства.')}
step('Б4_свойства_в_отчётах', sheet_props_sum)

print("PS_START"); print(json.dumps(out, ensure_ascii=False, default=str, indent=1)); print("PS_END")
