import json
out = {}
PRICE = 596.0          # ₽ за метр
truba = env['product.product'].search([('name', 'like', 'Труба профильная 100x100x3')], limit=1)
wh    = env['stock.warehouse'].search([], limit=1)
metal = env['stock.location'].search([('name','=','METAL')], limit=1)
supplier = env['res.partner'].search([], limit=1)

# ── Приёмка: 3 куска по 6 м + 2 по 12 м = 42.000 м ────────────────────────
pick = env['stock.picking'].create({
    'picking_type_id': wh.in_type_id.id,
    'partner_id': supplier.id,
    'location_id': env.ref('stock.stock_location_suppliers').id,
    'location_dest_id': metal.id,
})
move = env['stock.move'].create({
    'picking_id': pick.id,
    'product_id': truba.id,
    'product_uom_qty': 42.0,
    'product_uom': truba.uom_id.id,
    'price_unit': PRICE,
    'location_id': env.ref('stock.stock_location_suppliers').id,
    'location_dest_id': metal.id,
})
pick.action_confirm()

# Каждый кусок — отдельная строка с собственной биркой.
move.move_line_ids.unlink()
PIECES = [('L-001', 6.0), ('L-002', 6.0), ('L-003', 6.0), ('L-004', 12.0), ('L-005', 12.0)]
for lot_name, qty in PIECES:
    env['stock.move.line'].create({
        'move_id': move.id, 'picking_id': pick.id,
        'product_id': truba.id, 'product_uom_id': truba.uom_id.id,
        'quantity': qty, 'lot_name': lot_name,
        'location_id': move.location_id.id, 'location_dest_id': metal.id,
    })
move.picked = True
pick.button_validate()
env.cr.commit()

out['picking'] = {'name': pick.name, 'state': pick.state}
lots = env['stock.lot'].search([('product_id','=',truba.id)], order='name')
out['lots'] = [{
    'бирка': l.name, 'длина_м': l.product_qty,
    'себестоимость_за_м': round(l.standard_price, 2),
    'стоимость_всего': round(l.total_value, 2),
} for l in lots]
quants = env['stock.quant'].search([('product_id','=',truba.id),('location_id.usage','=','internal')])
out['итого'] = {
    'кусков': len(quants),
    'метров': round(sum(quants.mapped('quantity')), 3),
    'кг': round(sum(quants.mapped('quantity')) * truba.weight, 2),
    'рублей': round(sum(lots.mapped('total_value')), 2),
}
print("RECEIPT_START"); print(json.dumps(out, ensure_ascii=False, default=str, indent=1)); print("RECEIPT_END")
