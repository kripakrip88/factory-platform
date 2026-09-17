import json
out = {}

# ── Шаг 1. Точность количества 2 → 3 знака ────────────────────────────────
# Нужна, чтобы хранить миллиметры: 0.790 м, а не 0.79.
# Настройка ГЛОБАЛЬНАЯ — влияет на все единицы сразу.
prec = env['decimal.precision'].search([('name', '=', 'Product Unit')], limit=1)
prec.digits = 3
out['precision'] = prec.digits

# ── Шаг 2. Категория с методом себестоимости ──────────────────────────────
cat = env['product.category'].search([('name', '=', 'Металлопрокат')], limit=1)
if not cat:
    cat = env['product.category'].create({'name': 'Металлопрокат'})
try:
    cat.property_cost_method = 'fifo'
    out['cost_method'] = cat.property_cost_method
except Exception as e:
    out['cost_method_error'] = str(e)[:200]

uom_m   = env['uom.uom'].browse(9)    # m
uom_m2  = env['uom.uom'].browse(11)   # m²
out['uoms'] = [uom_m.name, uom_m2.name]

# ── Шаг 3. Четыре позиции ─────────────────────────────────────────────────
# Веса — настоящие, из нашего metal_calculator/seed_data.py.
SPEC = [
    ("Труба профильная 100x100x3 ГОСТ 8639-82", uom_m,  9.02),
    ("Уголок равнополочный 63x63x5 ГОСТ 8509-93", uom_m, 4.81),
    ("Лист горячекатаный 4 мм ГОСТ 19903-2015", uom_m2, 31.4),
    ("Лист горячекатаный 8 мм ГОСТ 19903-2015", uom_m2, 62.8),
]
made = []
for name, uom, weight in SPEC:
    p = env['product.template'].search([('name', '=', name)], limit=1)
    if not p:
        p = env['product.template'].create({
            'name': name,
            'type': 'consu',
            'is_storable': True,
            'uom_id': uom.id,
            'tracking': 'lot',        # каждый кусок — отдельная партия
            'weight': weight,         # кг на одну базовую единицу (метр / м²)
            'categ_id': cat.id,
            'list_price': 0.0,
        })
    # Оценка по партиям — включать ДО появления остатков, потом необратимо
    try:
        p.lot_valuated = True
    except Exception as e:
        out.setdefault('lot_valuated_errors', []).append(f"{name}: {str(e)[:150]}")
    made.append({'id': p.id, 'name': p.name, 'uom': p.uom_id.name,
                 'tracking': p.tracking, 'weight': p.weight,
                 'lot_valuated': p.lot_valuated})
out['products'] = made

# ── Локации: прокат и деловые остатки ─────────────────────────────────────
# Многоскладские локации включаются в НАСТРОЙКАХ, а не на складе.
env['res.config.settings'].create({'group_stock_multi_locations': True}).execute()
wh = env['stock.warehouse'].search([], limit=1)
stock = wh.lot_stock_id
locs = {}
for code in ('METAL', 'REMNANT'):
    l = env['stock.location'].search([('name', '=', code), ('location_id', '=', stock.id)], limit=1)
    if not l:
        l = env['stock.location'].create({'name': code, 'location_id': stock.id, 'usage': 'internal'})
    locs[code] = {'id': l.id, 'path': l.complete_name}
out['locations'] = locs
out['warehouse'] = wh.name

env.cr.commit()
print("SETUP_START")
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
print("SETUP_END")
