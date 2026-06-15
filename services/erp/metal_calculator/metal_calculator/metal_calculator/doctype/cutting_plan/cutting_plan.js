// Раскрой металла — форма плана: кнопка «Рассчитать раскрой» + отрисовка карт.
frappe.ui.form.on("Cutting Plan", {
	refresh(frm) {
		inject_cut_styles();
		frm.add_custom_button(__("Рассчитать раскрой"), () => run_calc(frm)).addClass("btn-primary");
		render_result(frm);
	},
	cut_type(frm) {
		// подсказка по обязательным размерам заготовки
		frm.refresh_fields();
	},
});

function run_calc(frm) {
	if (frm.is_dirty()) {
		frm.save().then(() => do_calc(frm));
	} else {
		do_calc(frm);
	}
}

function do_calc(frm) {
	frappe.call({
		method: "metal_calculator.cutting.api.calculate",
		args: { plan_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Считаем раскрой..."),
		callback: (r) => {
			if (!r.message) return;
			frm.reload_doc().then(() => {
				frappe.show_alert({
					message: __("Готово: {0} заготовок, отход {1}%", [r.message.total_stock, r.message.waste_percent]),
					indicator: "green",
				});
			});
		},
	});
}

function render_result(frm) {
	const wrapper = frm.get_field("result_display") && frm.get_field("result_display").$wrapper;
	if (!wrapper) return;
	const html = frm.doc.result_html;
	wrapper.html(html ? `<div class="cut-result">${html}</div>` : `<div class="text-muted">${__("Задайте детали и размеры заготовки, затем «Рассчитать раскрой».")}</div>`);
}

function inject_cut_styles() {
	if (document.getElementById("cut-styles")) return;
	const css = `
	.cut-result .cut-summary{font-size:1rem;margin-bottom:12px;padding:8px 12px;border-radius:8px;
		background:color-mix(in srgb, var(--text-color) 6%, transparent)}
	.cut-result .cut-group{margin:10px 0;padding:8px 12px;border:1px solid color-mix(in srgb,var(--text-color) 12%,transparent);border-radius:8px}
	.cut-result .cut-gtitle{font-weight:600;margin-bottom:6px}
	.cut-result .cut-pat{font-family:var(--font-stack,monospace);padding:2px 0}
	.cut-result .cut-w{color:var(--text-muted)}
	.cut-result .cut-error{border-color:var(--red,#e24c4c);color:var(--red,#e24c4c)}
	.cut-result .cut-sheet-no{font-weight:600;margin-top:8px;font-size:.9rem}
	`;
	const el = document.createElement("style");
	el.id = "cut-styles";
	el.textContent = css;
	document.head.appendChild(el);
}
