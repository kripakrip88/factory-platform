import json
out = {}
truba = env['product.product'].search([('name','like','Труба профильная 100x100x3')], limit=1)
metal = env['stock.location'].search([('name','=','METAL')], limit=1)
remn  = env['stock.location'].search([('name','=','REMNANT')], limit=1)
# xmlid stock.location_production в Odoo 19 отсутствует — берём по назначению.
prod_loc = env['stock.location'].search([('usage','=','production')], limit=1)
lot4 = env['stock.lot'].search([('name','=','L-004')], limit=1)

before = {'длина': lot4.product_qty, 'стоимость': round(lot4.total_value, 2)}

# ── Шаг 7. Отрез: 4 детали по 2.8 м = 11.200 м уходит в производство ──────
mv = env['stock.move'].create({
    'product_id': truba.id, 'product_uom': truba.uom_id.id,
    'product_uom_qty': 11.2,
    'location_id': metal.id, 'location_dest_id': prod_loc.id,
})
mv._action_confirm(); mv._action_assign()
mv.move_line_ids.unlink()
env['stock.move.line'].create({
    'move_id': mv.id, 'product_id': truba.id, 'product_uom_id': truba.uom_id.id,
    'quantity': 11.2, 'lot_id': lot4.id,
    'location_id': metal.id, 'location_dest_id': prod_loc.id,
})
mv.picked = True
mv._action_done()
env.cr.commit()

lot4.invalidate_recordset()
after = {'длина': lot4.product_qty, 'стоимость': round(lot4.total_value, 2),
         'себестоимость_метра': round(lot4.standard_price, 2)}
ушло = round(before['стоимость'] - after['стоимость'], 2)
out['L-004'] = {'было': before, 'стало': after,
                'ушло_в_себестоимость': ушло,
                'проверка_суммы': round(ушло + after['стоимость'], 2)}

# ── Шаг 8. Обрезок 0.800 м переезжает на склад деловых остатков ───────────
mv2 = env['stock.move'].create({
    'product_id': truba.id, 'product_uom': truba.uom_id.id,
    'product_uom_qty': 0.8,
    'location_id': metal.id, 'location_dest_id': remn.id,
})
mv2._action_confirm(); mv2._action_assign()
mv2.move_line_ids.unlink()
env['stock.move.line'].create({
    'move_id': mv2.id, 'product_id': truba.id, 'product_uom_id': truba.uom_id.id,
    'quantity': 0.8, 'lot_id': lot4.id,
    'location_id': metal.id, 'location_dest_id': remn.id,
})
mv2.picked = True
mv2._action_done()
env.cr.commit()

q = env['stock.quant'].search([('product_id','=',truba.id),('location_id.usage','=','internal')])
out['остатки'] = sorted([{
    'склад': x.location_id.complete_name.replace('WH/Stock/',''),
    'бирка': x.lot_id.name, 'длина_м': round(x.quantity,3),
    'кг': round(x.quantity * truba.weight, 2), 'рублей': round(x.value, 2),
} for x in q], key=lambda r: (r['склад'], r['бирка']))
out['итого'] = {
    'кусков': len(q), 'метров': round(sum(q.mapped('quantity')),3),
    'кг': round(sum(q.mapped('quantity'))*truba.weight,2),
    'рублей': round(sum(q.mapped('value')),2),
}
out['новых_номенклатур_создано'] = env['product.product'].search_count([('name','like','Труба профильная 100x100x3')])
print("CUT_START"); print(json.dumps(out, ensure_ascii=False, default=str, indent=1)); print("CUT_END")
