# Разовый скрипт v1.118.2 (odoo shell): дубль «ЦЕНТР КРОВЛИ» (sale@ck.ru) → ООО «ЦЕНТР КРОВЛИ» (ИНН 2540249518).
# Почта/телефон переносятся в пустые поля, потом штатный мастер объединения. Запуск — только по «да» Антона.
P = env["res.partner"].with_context(active_test=False)
dst = P.search([("name", "=", "ООО «ЦЕНТР КРОВЛИ»"), ("vat", "=", "2540249518")])
src = P.search([("name", "=", "ЦЕНТР КРОВЛИ"), ("email", "=", "sale@ck.ru")])
assert len(dst) == 1 and len(src) == 1, (dst, src)
vals = {f: src[f] for f in ("email", "phone", "website") if src[f] and not dst[f]}
if vals:
    dst.write(vals)
env["base.partner.merge.automatic.wizard"]._merge((src | dst).ids, dst_partner=dst)
print("merged ->", dst.id, dst.name, dst.vat, dst.email, dst.phone, "| src exists:", src.exists().ids)
env.cr.commit()
