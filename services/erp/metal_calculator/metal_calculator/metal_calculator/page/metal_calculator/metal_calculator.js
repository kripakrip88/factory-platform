frappe.pages["metal_calculator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Калькулятор металла"),
		single_column: true,
	});
	new MetalCalculator(page);
};

const SHEET_TYPE = "Лист";

// Группы сортамента: [полное имя, короткая подпись плитки, ключ иконки]
const TILES = [
	["Арматура", "Арматура", "armatura"],
	["Двутавр", "Двутавр", "ibeam"],
	["Швеллер", "Швеллер", "channel"],
	["Уголок равнополочный", "Уголок равноп.", "angle"],
	["Уголок неравнополочный", "Уголок неравноп.", "angle"],
	["Труба круглая", "Труба круглая", "pipe"],
	["Труба профильная квадратная", "Профтруба кв.", "sqpipe"],
	["Труба профильная прямоугольная", "Профтруба прям.", "rectpipe"],
	["Круг", "Круг", "circle"],
	["Квадрат", "Квадрат", "square"],
	["Шестигранник", "Шестигранник", "hex"],
	[SHEET_TYPE, "Лист", "sheet"],
];

// Простые SVG-иконки (силуэты сечений), наследуют цвет через currentColor.
const ICONS = {
	armatura: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><path d="M4 20h32M12 12l-4 16M22 12l-4 16M32 12l-4 16"/></svg>',
	ibeam: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><path d="M8 8h24M8 32h24M20 8v24"/></svg>',
	channel: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><path d="M28 8H12v24h16"/></svg>',
	angle: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><path d="M12 8v24h20"/></svg>',
	pipe: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><circle cx="20" cy="20" r="13"/><circle cx="20" cy="20" r="7"/></svg>',
	sqpipe: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><rect x="7" y="7" width="26" height="26" rx="2"/><rect x="14" y="14" width="12" height="12" rx="1"/></svg>',
	rectpipe: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><rect x="5" y="11" width="30" height="18" rx="2"/><rect x="11" y="16" width="18" height="8" rx="1"/></svg>',
	circle: '<svg viewBox="0 0 40 40" fill="currentColor"><circle cx="20" cy="20" r="13"/></svg>',
	square: '<svg viewBox="0 0 40 40" fill="currentColor"><rect x="8" y="8" width="24" height="24" rx="2"/></svg>',
	hex: '<svg viewBox="0 0 40 40" fill="currentColor"><path d="M14 7h12l6 13-6 13H14L8 20z"/></svg>',
	sheet: '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="3"><rect x="6" y="12" width="28" height="16" rx="1"/></svg>',
};

class MetalCalculator {
	constructor(page) {
		this.page = page;
		this.controls = {};
		this.spec = []; // накопленные позиции спецификации
		this.current_type = "Двутавр";
		this.inject_styles();
		this.render();
		this.make_controls();
		this.select_type(this.current_type);
	}

	inject_styles() {
		if (document.getElementById("mc-styles")) return;
		const css = `
		.mc-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:10px;margin-bottom:20px}
		.mc-tile{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
			padding:12px 6px;border:1px solid var(--border-color);border-radius:10px;cursor:pointer;
			background:var(--card-bg);transition:all .12s;text-align:center;min-height:84px}
		.mc-tile:hover{border-color:var(--primary);transform:translateY(-1px)}
		.mc-tile.active{border-color:var(--primary);background:var(--primary);color:#fff}
		.mc-tile.active svg{color:#fff}
		.mc-tile svg{width:34px;height:34px;color:var(--text-muted)}
		.mc-tile span{font-size:.72rem;line-height:1.05;color:var(--text-color)}
		.mc-tile.active span{color:#fff}
		.mc-spec-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.86rem}
		.mc-spec-table th,.mc-spec-table td{padding:7px 9px;border-bottom:1px solid var(--border-color);text-align:left}
		.mc-spec-table th{color:var(--text-muted);font-weight:600;white-space:nowrap}
		.mc-spec-table td.num,.mc-spec-table th.num{text-align:right;white-space:nowrap}
		.mc-spec-table tfoot td,.mc-spec-total{font-weight:700}
		.mc-del{cursor:pointer;color:var(--text-muted);border:none;background:none;font-size:1rem}
		.mc-del:hover{color:var(--red,#e24c4c)}
		.mc-empty{color:var(--text-muted);padding:16px 0;text-align:center}
		`;
		const el = document.createElement("style");
		el.id = "mc-styles";
		el.textContent = css;
		document.head.appendChild(el);
	}

	render() {
		$(this.page.body).html(`
			<div class="mc-wrap" style="max-width:900px;">
				<div class="mc-tiles"></div>
				<div class="mc-form" style="max-width:560px;">
					<div class="mc-field" data-field="ref_profile"></div>
					<div class="mc-field" data-field="sheet_type" style="display:none;"></div>
					<div class="mc-field" data-field="ref_sheet" style="display:none;"></div>
					<div class="mc-row" style="display:flex; gap:12px;">
						<div class="mc-field" data-field="length_mm" style="flex:1;"></div>
					</div>
					<div class="mc-row mc-sheet-sides" style="display:none; gap:12px;">
						<div class="mc-field" data-field="a_mm" style="flex:1;"></div>
						<div class="mc-field" data-field="b_mm" style="flex:1;"></div>
					</div>
					<div class="mc-field" data-field="qty"></div>
					<div class="mc-field" data-field="steel_grade"></div>
					<div style="margin-top:16px;">
						<button class="btn btn-primary mc-add">${__("Посчитать и добавить")}</button>
					</div>
				</div>

				<div class="mc-spec" style="margin-top:30px;">
					<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
						<h5 style="margin:0;">${__("Спецификация")}</h5>
						<div>
							<button class="btn btn-sm btn-default mc-export">${__("Экспорт CSV")}</button>
							<button class="btn btn-sm btn-default mc-save">${__("Сохранить")}</button>
							<button class="btn btn-sm btn-default mc-clear">${__("Очистить всё")}</button>
						</div>
					</div>
					<div class="mc-spec-body"></div>
				</div>
			</div>
		`);

		// Плитки
		const $tiles = this.page.body.find(".mc-tiles");
		TILES.forEach(([full, short, icon]) => {
			const $t = $(
				`<div class="mc-tile" data-type="${frappe.utils.escape_html(full)}" title="${frappe.utils.escape_html(full)}">${ICONS[icon] || ""}<span>${frappe.utils.escape_html(short)}</span></div>`
			);
			$t.on("click", () => this.select_type(full));
			$tiles.append($t);
		});

		this.page.body.find(".mc-add").on("click", () => this.add_position());
		this.page.body.find(".mc-clear").on("click", () => this.clear_spec());
		this.page.body.find(".mc-export").on("click", () => this.export_csv());
		this.page.body.find(".mc-save").on("click", () => this.save_spec());
		this.render_spec();
	}

	_mount(fieldname, df) {
		const ctrl = frappe.ui.form.make_control({
			df: df,
			parent: this.page.body.find(`[data-field="${fieldname}"]`).get(0),
			render_input: true,
		});
		this.controls[fieldname] = ctrl;
		return ctrl;
	}

	make_controls() {
		const me = this;

		this._mount("ref_profile", {
			fieldname: "ref_profile",
			label: __("Типоразмер"),
			fieldtype: "Link",
			options: "Metal Profile",
			get_query: () => ({ filters: { profile_type: me.current_type } }),
		});

		this._mount("sheet_type", {
			fieldname: "sheet_type",
			label: __("Тип листа"),
			fieldtype: "Select",
			options: ["Гладкий", "Рифлёный", "Просечно-вытяжной"].join("\n"),
			default: "Гладкий",
			change: () => me.controls.ref_sheet.set_value(""),
		});

		this._mount("ref_sheet", {
			fieldname: "ref_sheet",
			label: __("Лист (типоразмер)"),
			fieldtype: "Link",
			options: "Metal Sheet Grade",
			get_query: () => ({ filters: { sheet_type: me.controls.sheet_type.get_value() || "Гладкий" } }),
		});

		this._mount("length_mm", { fieldname: "length_mm", label: __("Длина L, мм"), fieldtype: "Float", default: 6000 });
		this.controls.length_mm.set_value(6000);
		this._mount("a_mm", { fieldname: "a_mm", label: __("Сторона a, мм"), fieldtype: "Float", default: 1500 });
		this._mount("b_mm", { fieldname: "b_mm", label: __("Сторона b, мм"), fieldtype: "Float", default: 6000 });
		this._mount("qty", { fieldname: "qty", label: __("Количество, шт"), fieldtype: "Int", default: 1 });
		this.controls.qty.set_value(1);
		this._mount("steel_grade", { fieldname: "steel_grade", label: __("Марка стали"), fieldtype: "Link", options: "Steel Grade" });
		this.set_default_grade();
	}

	set_default_grade() {
		frappe.db.get_value("Steel Grade", { is_default: 1 }, "name").then((r) => {
			const grade = (r && r.message && r.message.name) || "Ст3сп";
			this.controls.steel_grade.set_value(grade);
		});
	}

	is_sheet() {
		return this.current_type === SHEET_TYPE;
	}

	select_type(type) {
		this.current_type = type;
		this.page.body.find(".mc-tile").removeClass("active");
		this.page.body.find(`.mc-tile[data-type="${type.replace(/"/g, '\\"')}"]`).addClass("active");

		const sheet = this.is_sheet();
		this.page.body.find('[data-field="ref_profile"]').toggle(!sheet);
		this.page.body.find('[data-field="sheet_type"]').toggle(sheet);
		this.page.body.find('[data-field="ref_sheet"]').toggle(sheet);
		this.page.body.find('[data-field="length_mm"]').closest(".mc-row").toggle(!sheet);
		this.page.body.find(".mc-sheet-sides").css("display", sheet ? "flex" : "none");
		if (!sheet && this.controls.ref_profile) this.controls.ref_profile.set_value("");
	}

	add_position() {
		const sheet = this.is_sheet();
		const qty = this.controls.qty.get_value();
		const grade = this.controls.steel_grade.get_value();
		const args = { mode: sheet ? "sheet" : "linear", qty, steel_grade: grade };
		let ref, dims;

		if (sheet) {
			ref = this.controls.ref_sheet.get_value();
			if (!ref) return frappe.msgprint(__("Выберите лист"));
			args.ref = ref;
			args.a_mm = this.controls.a_mm.get_value();
			args.b_mm = this.controls.b_mm.get_value();
			dims = `${args.a_mm}×${args.b_mm} мм`;
		} else {
			ref = this.controls.ref_profile.get_value();
			if (!ref) return frappe.msgprint(__("Выберите типоразмер"));
			args.ref = ref;
			args.length_mm = this.controls.length_mm.get_value();
			dims = `L=${args.length_mm} мм`;
		}

		frappe.call({
			method: "metal_calculator.api.calculate",
			args,
			freeze: true,
			freeze_message: __("Считаем..."),
			callback: (r) => {
				if (!r.message) return;
				const res = r.message;
				this.spec.push({
					form: this.current_type,
					item_ref: ref,
					size_label: ref,
					steel_grade: res.steel_grade || grade || "",
					dims,
					qty: res.qty,
					weight_one_kg: res.weight_one_kg,
					weight_total_kg: res.weight_total_kg,
				});
				this.render_spec();
			},
		});
	}

	render_spec() {
		const $body = this.page.body.find(".mc-spec-body");
		if (!this.spec.length) {
			$body.html(`<div class="mc-empty">${__("Позиций пока нет — выберите сортамент и нажмите «Посчитать и добавить»")}</div>`);
			return;
		}
		const fmt = (v) => frappe.format(v, { fieldtype: "Float", precision: 3 });
		const esc = frappe.utils.escape_html;
		const total = this.spec.reduce((s, r) => s + (r.weight_total_kg || 0), 0);
		let rows = "";
		this.spec.forEach((r, i) => {
			rows += `<tr>
				<td>${i + 1}</td>
				<td>${esc(r.form)}</td>
				<td>${esc(r.item_ref)}</td>
				<td>${esc(r.steel_grade || "—")}</td>
				<td>${esc(r.dims)}</td>
				<td class="num">${r.qty}</td>
				<td class="num">${fmt(r.weight_one_kg)}</td>
				<td class="num">${fmt(r.weight_total_kg)}</td>
				<td><button class="mc-del" data-i="${i}" title="${__("Удалить")}">✕</button></td>
			</tr>`;
		});
		$body.html(`
			<table class="mc-spec-table">
				<thead><tr>
					<th>#</th><th>${__("Форма")}</th><th>${__("Типоразмер")}</th><th>${__("Марка")}</th>
					<th>${__("Размеры")}</th><th class="num">${__("Кол-во")}</th>
					<th class="num">${__("Вес 1 шт, кг")}</th><th class="num">${__("Вес всего, кг")}</th><th></th>
				</tr></thead>
				<tbody>${rows}</tbody>
				<tfoot><tr class="mc-spec-total">
					<td colspan="7" class="num">${__("Итого")}:</td>
					<td class="num">${fmt(total)}</td><td></td>
				</tr></tfoot>
			</table>
		`);
		$body.find(".mc-del").on("click", (e) => {
			const i = parseInt($(e.currentTarget).data("i"), 10);
			this.spec.splice(i, 1);
			this.render_spec();
		});
	}

	clear_spec() {
		if (!this.spec.length) return;
		frappe.confirm(__("Очистить всю спецификацию?"), () => {
			this.spec = [];
			this.render_spec();
		});
	}

	export_csv() {
		if (!this.spec.length) return frappe.msgprint(__("Спецификация пустая"));
		const head = ["#", "Форма", "Типоразмер", "Марка", "Размеры", "Кол-во", "Вес 1 шт, кг", "Вес всего, кг"];
		const lines = [head.join(";")];
		this.spec.forEach((r, i) => {
			lines.push([i + 1, r.form, r.item_ref, r.steel_grade || "", r.dims, r.qty, r.weight_one_kg, r.weight_total_kg].join(";"));
		});
		const total = this.spec.reduce((s, r) => s + (r.weight_total_kg || 0), 0);
		lines.push(["", "", "", "", "", "", "Итого", total.toFixed(3)].join(";"));
		const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = "specification.csv";
		a.click();
		URL.revokeObjectURL(url);
	}

	save_spec() {
		if (!this.spec.length) return frappe.msgprint(__("Спецификация пустая"));
		frappe.prompt(
			[{ fieldname: "customer", label: __("Клиент / изделие"), fieldtype: "Data" }],
			(values) => {
				frappe.call({
					method: "metal_calculator.api.save_spec",
					args: { items: JSON.stringify(this.spec), customer: values.customer || null },
					freeze: true,
					freeze_message: __("Сохраняем..."),
					callback: (r) => {
						if (!r.message) return;
						const name = r.message.name;
						frappe.show_alert({ message: __("Спецификация {0} сохранена", [name]), indicator: "green" });
						frappe.msgprint({
							title: __("Сохранено"),
							message: `<a href="/app/metal-spec/${encodeURIComponent(name)}" target="_blank">${frappe.utils.escape_html(name)}</a> — ${__("открыть для печати/PDF")}`,
						});
					},
				});
			},
			__("Сохранить спецификацию"),
			__("Сохранить")
		);
	}
}
