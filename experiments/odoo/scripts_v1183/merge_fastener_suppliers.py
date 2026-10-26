# Разовый скрипт v1.119 (odoo shell): дубли поставщиков крепежа → карточки с ИНН (Антон 26.10.2026):
# «ООО «Метиз Комплект» (МК-27)» → ООО «МЕТИЗ КОМПЛЕКТ» (ИНН 2723096876),
# «ООО «Метиз Центр»» → ООО «МЕТИЗ ЦЕНТР ДВ» (ИНН 2724224190). Почта/телефон — в пустые поля,
# потом штатный мастер объединения. Запуск на боевом — только по «да» Антона.
P = env["res.partner"].with_context(active_test=False)
for src_name, inn in (("ООО «Метиз Комплект» (МК-27)", "2723096876"), ("ООО «Метиз Центр»", "2724224190")):
    dst = P.search([("vat", "=", inn), ("parent_id", "=", False)])
    src = P.search([("name", "=", src_name), ("parent_id", "=", False)])
    assert len(dst) == 1, (inn, dst)
    if not src:
        print("уже слито:", src_name)
        continue
    assert len(src) == 1, (src_name, src)
    vals = {f: src[f] for f in ("email", "phone", "website") if src[f] and not dst[f]}
    if vals:
        dst.write(vals)
    env["base.partner.merge.automatic.wizard"]._merge((src | dst).ids, dst_partner=dst)
    print("слито ->", dst.id, dst.name, dst.vat, dst.phone or "", "| исходная есть:", src.exists().ids)
env.cr.commit()
