import json
out = {}
truba = env['product.product'].search([('name','like','Труба профильная 100x100x3')], limit=1)
remn  = env['stock.location'].search([('name','=','REMNANT')], limit=1)
metal = env['stock.location'].search([('name','=','METAL')], limit=1)

# ── Шаг 9. Перемер рулеткой: расчётные 0.800 оказались 0.790 ──────────────
# Именно эту операцию схема «длина = вариант товара» не проходит:
# там количество всегда «1 шт», и провести перемер нечем.
q = env['stock.quant'].search([('product_id','=',truba.id),('location_id','=',remn.id)], limit=1)
до = {'длина': q.quantity, 'рублей': round(q.value,2)}
q.inventory_quantity = 0.790
q.action_apply_inventory()
q.invalidate_recordset()
out['перемер'] = {
    'было': до,
    'стало': {'длина': round(q.quantity,3), 'рублей': round(q.value,2),
              'кг': round(q.quantity*truba.weight,2)},
    'проводка_создана': bool(env['stock.move.line'].search_count([
        ('product_id','=',truba.id), ('lot_id','=',q.lot_id.id),
        ('location_id.usage','=','inventory')]) or
        env['stock.move.line'].search_count([
        ('product_id','=',truba.id), ('lot_id','=',q.lot_id.id),
        ('location_dest_id.usage','=','inventory')])),
}

# ── Шаг 10. Резерв конкретного куска ──────────────────────────────────────
cust = env['stock.location'].search([('usage','=','customer')], limit=1)
def try_reserve(qty, lot_name):
    lot = env['stock.lot'].search([('name','=',lot_name)], limit=1)
    mv = env['stock.move'].create({
        'product_id': truba.id, 'product_uom': truba.uom_id.id,
        'product_uom_qty': qty,
        'location_id': metal.id if lot_name != 'L-004' else remn.id,
        'location_dest_id': cust.id,
    })
    mv._action_confirm()
    try:
        mv.lot_ids = [(6, 0, [lot.id])]      # штатное ограничение по партии
        restricted = True
    except Exception as e:
        restricted = str(e)[:150]
    mv._action_assign()
    mv.invalidate_recordset()
    res = {'запрошено': qty, 'бирка': lot_name,
           'ограничение_партией': restricted,
           'зарезервировано': round(mv.quantity, 3), 'состояние': mv.state}
    mv._action_cancel()
    return res

out['резерв_целого_12м']   = try_reserve(12.0, 'L-005')
out['резерв_обрезка_079м'] = try_reserve(0.790, 'L-004')
env.cr.commit()

# ── Итоговая картина склада ───────────────────────────────────────────────
qs = env['stock.quant'].search([('product_id','=',truba.id),('location_id.usage','=','internal'),('quantity','>',0)])
out['остатки'] = sorted([{
    'склад': x.location_id.complete_name.replace('WH/Stock/',''), 'бирка': x.lot_id.name,
    'длина_м': round(x.quantity,3), 'кг': round(x.quantity*truba.weight,2),
    'рублей': round(x.value,2)} for x in qs], key=lambda r:(r['склад'], r['бирка']))
out['итого'] = {'кусков': len(qs), 'метров': round(sum(qs.mapped('quantity')),3),
                'кг': round(sum(qs.mapped('quantity'))*truba.weight,2),
                'рублей': round(sum(qs.mapped('value')),2)}
print("FIN_START"); print(json.dumps(out, ensure_ascii=False, default=str, indent=1)); print("FIN_END")
