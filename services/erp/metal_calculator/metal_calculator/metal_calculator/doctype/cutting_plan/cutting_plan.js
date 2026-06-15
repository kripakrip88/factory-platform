// Раскрой металла — единое окно: линейный + листовой раскрой по одной спецификации.
// Карты рисуем НА КЛИЕНТЕ из JSON (Frappe-санитайзер режет fill/style у SVG).

const CUT_PALETTE = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899",
	"#14B8A6", "#6366F1", "#0EA5E9", "#E2683C"];
const g = (v) => (v % 1 === 0 ? String(Math.round(v)) : String(Math.round(v * 100) / 100));
const E = (s) => frappe.utils.escape_html(s == null ? "" : String(s));

frappe.ui.form.on("Cutting Plan", {
	refresh(frm) {
		inject_cut_styles();
		frm.add_custom_button(__("Рассчитать раскрой"), () => run_calc(frm)).addClass("btn-primary");
		if (frm.doc.metal_spec) {
			frm.add_custom_button(__("Открыть спецификацию"), () => frappe.set_route("Form", "Metal Spec", frm.doc.metal_spec));
		}
		render_result(frm);
	},
});

function run_calc(frm) {
	const save = frm.is_dirty() ? frm.save() : Promise.resolve();
	save.then(() => frappe.call({
		method: "metal_calculator.cutting.api.calculate",
		args: { plan_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Считаем раскрой..."),
		callback: (r) => {
			if (!r.message) return;
			frm.reload_doc().then(() => {
				render_result(frm);
				frappe.show_alert({ message: __("Готово: {0} заготовок, отход ~{1}%", [r.message.total_stock, r.message.waste_percent]), indicator: "green" });
			});
		},
	}));
}

function render_result(frm) {
	const field = frm.get_field("result_display");
	if (!field || !field.$wrapper) return;
	let payload = null;
	try { payload = JSON.parse(frm.doc.result_html || "null"); } catch (e) { payload = null; }
	if (!payload || (!payload.linear && !payload.sheet)) {
		field.$wrapper.html(`<div class="text-muted">${__("Задайте детали и размеры заготовки (хлыст для линейного, лист для листового), затем «Рассчитать раскрой».")}</div>`);
		return;
	}
	let html = "";
	if (payload.linear) html += `<div class="cut-section"><h6>${__("Линейный прокат")}</h6>${render_linear(payload.linear.meta, payload.linear.result, payload.kerf)}</div>`;
	if (payload.sheet) html += `<div class="cut-section"><h6>${__("Листовой прокат")}</h6>${render_sheet(payload.sheet.meta, payload.sheet.result, payload.kerf)}</div>`;
	field.$wrapper.html(`<div class="cut-result">${html}</div>`);
}

function piece_label(p) {
	const dim = g(p.length);
	return p.label ? `${dim}<span class="cut-nm">(${E(p.label)})</span>` : dim;
}

function render_linear(meta, result, kerf) {
	let out = `<div class="cut-summary">${__("Хлыстов")}: <b>${result.total_stock}</b> · ${__("Отход")}: <b>${result.waste_percent}%</b> · ${__("хлыст")} ${g(meta.stock_length)} ${__("мм")}, ${__("рез")} ${g(kerf)} ${__("мм")}</div>`;
	for (const grp of result.groups) {
		const title = `${grp.profile_type || ""} ${grp.size_label || ""}`.trim();
		if (grp.error) { out += `<div class="cut-group cut-error"><b>${E(title)}</b>: ⚠️ ${E(grp.error)}</div>`; continue; }
		let rows = "";
		for (const p of grp.patterns) {
			const pieces = p.pieces.map(piece_label).join(" + ");
			rows += `<div class="cut-pat">[${pieces} <span class="cut-w">+ ${g(p.waste)} ${__("отход")}</span>] ×${p.count}</div>`;
		}
		out += `<div class="cut-group"><div class="cut-gtitle">${E(title)} — ${grp.stock_count} ${__("хлыст(ов)")}, ${__("отход")} ${grp.waste_percent}%</div>${rows}</div>`;
	}
	return out;
}

function render_sheet(meta, result, kerf) {
	let out = `<div class="cut-summary">${__("Листов")}: <b>${result.total_stock}</b> · ${__("Отход")}: <b>${result.waste_percent}%</b> · ${__("лист")} ${g(meta.sheet_length)}×${g(meta.sheet_width)} ${__("мм")}, ${__("рез")} ${g(kerf)} ${__("мм")}</div>`;
	for (const grp of result.groups) {
		const title = `${__("Лист")} ${grp.size_label || ""} ${__("мм")}`.trim();
		if (grp.error) { out += `<div class="cut-group cut-error"><b>${E(title)}</b>: ⚠️ ${E(grp.error)}</div>`; continue; }
		out += `<div class="cut-group"><div class="cut-gtitle">${E(title)} — ${grp.sheet_count} ${__("лист(ов)")}, ${__("отход")} ${grp.waste_percent}%</div>`;
		for (const s of grp.sheets) {
			const cnt = s.count > 1 ? ` <b>× ${s.count} ${__("шт")}</b>` : "";
			out += `<div class="cut-sheet-no">${__("Раскрой листа")}${cnt}</div>`;
			out += svg_sheet(meta.sheet_length, meta.sheet_width, s.placements);
			out += sheet_summary(s.summary);
		}
		out += `</div>`;
	}
	return out;
}

function sheet_summary(summary) {
	if (!summary || !summary.length) return "";
	const items = summary.map((d) => `<li>${d.label ? E(d.label) + " — " : ""}${g(d.L)}×${g(d.W)} ${__("мм")} × ${d.count} ${__("шт")}</li>`).join("");
	return `<ul class="cut-sum-list">${items}</ul>`;
}

function svg_sheet(sl, sw, placements, max_w = 520) {
	const scale = sl ? max_w / sl : 1;
	const W = sl * scale, H = sw * scale;
	let parts = `<rect x="0" y="0" width="${W.toFixed(1)}" height="${H.toFixed(1)}" fill="#e5e7eb" stroke="#9ca3af"/>`;
	placements.forEach((p, i) => {
		const x = p.x * scale, y = p.y * scale, w = p.w * scale, h = p.h * scale;
		const color = CUT_PALETTE[i % CUT_PALETTE.length];
		const dl = p.rot ? p.h : p.w, dw = p.rot ? p.w : p.h;
		const txt = p.label ? p.label : `${g(dl)}×${g(dw)}${p.rot ? "↻" : ""}`;
		parts += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" fill="${color}" fill-opacity="0.78" stroke="#1f2937" stroke-width="0.7"/>`;
		if (w > 30 && h > 13) parts += `<text x="${(x + w / 2).toFixed(1)}" y="${(y + h / 2 + 4).toFixed(1)}" text-anchor="middle" font-size="11" fill="#fff">${E(txt)}</text>`;
	});
	return `<svg viewBox="0 0 ${W.toFixed(1)} ${H.toFixed(1)}" width="${W.toFixed(1)}" height="${H.toFixed(1)}" style="max-width:100%;height:auto;margin:6px 0;border-radius:4px">${parts}</svg>`;
}

function inject_cut_styles() {
	if (document.getElementById("cut-styles")) return;
	const css = `
	.cut-result .cut-section{margin-bottom:18px}
	.cut-result .cut-section h6{margin:0 0 6px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted)}
	.cut-result .cut-summary{font-size:1rem;margin-bottom:10px;padding:8px 12px;border-radius:8px;background:color-mix(in srgb, var(--text-color) 6%, transparent)}
	.cut-result .cut-group{margin:10px 0;padding:8px 12px;border:1px solid color-mix(in srgb,var(--text-color) 12%,transparent);border-radius:8px}
	.cut-result .cut-gtitle{font-weight:600;margin-bottom:6px}
	.cut-result .cut-pat{font-family:monospace;padding:2px 0}
	.cut-result .cut-nm{color:var(--text-muted);margin-left:2px}
	.cut-result .cut-w{color:var(--text-muted)}
	.cut-result .cut-error{border-color:var(--red,#e24c4c);color:var(--red,#e24c4c)}
	.cut-result .cut-sheet-no{font-weight:600;margin-top:8px;font-size:.9rem}
	.cut-result .cut-sum-list{margin:2px 0 8px 18px;color:var(--text-muted);font-size:.85rem}
	`;
	const el = document.createElement("style");
	el.id = "cut-styles";
	el.textContent = css;
	document.head.appendChild(el);
}
