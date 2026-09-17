import json
out = {}
truba = env['product.product'].search([('name','like','Труба профильная 100x100x3')], limit=1)
metal = env['stock.location'].search([('name','=','METAL')], limit=1)
supp  = env['stock.location'].search([('usage','=','supplier')], limit=1)
wh    = env['stock.warehouse'].search([], limit=1)

def try_generate(total, qty_per_lot, first):
    """Штатный генератор: сколько строк и с какими количествами он сделает."""
    pick = env['stock.picking'].create({
        'picking_type_id': wh.in_type_id.id,
        'location_id': supp.id, 'location_dest_id': metal.id})
    mv = env['stock.move'].create({
        'picking_id': pick.id, 'product_id': truba.id,
        'product_uom': truba.uom_id.id, 'product_uom_qty': total,
        'location_id': supp.id, 'location_dest_id': metal.id})
    pick.action_confirm()
    ctx = {
        'default_product_id': truba.id,
        'default_tracking': 'lot',
        'default_quantity': total,
        'default_location_dest_id': metal.id,
        'default_product_uom_id': truba.uom_id.id,
        'default_move_id': mv.id,
    }
    try:
        vals = mv.action_generate_lot_line_vals(ctx, 'generate', first, qty_per_lot, False)
        res = {'строк': len(vals), 'партии': [(v.get('lot_name'), v.get('quantity')) for v in vals]}
    except Exception as e:
        res = {'ошибка': f"{type(e).__name__}: {str(e)[:220]}"}
    pick.action_cancel()
    return res

# 42 м, по 6 м на партию → ожидаем 7 партий по 6
out['по_6м_из_42'] = try_generate(42.0, 6.0, 'G6-001')
# 30 м, по 12 м на партию → ожидаем 2 по 12 и остаток 6
out['по_12м_из_30'] = try_generate(30.0, 12.0, 'G12-001')
# 1800 м пачкой, по 6 → 300 строк? проверяем, не ляжет ли
out['по_6м_из_1800'] = try_generate(1800.0, 6.0, 'GP-001')
if 'партии' in out['по_6м_из_1800']:
    out['по_6м_из_1800'] = {'строк': out['по_6м_из_1800']['строк'],
                            'первые_3': out['по_6м_из_1800']['партии'][:3],
                            'последняя': out['по_6м_из_1800']['партии'][-1]}
env.cr.rollback()
print("GEN_START"); print(json.dumps(out, ensure_ascii=False, default=str, indent=1)); print("GEN_END")
