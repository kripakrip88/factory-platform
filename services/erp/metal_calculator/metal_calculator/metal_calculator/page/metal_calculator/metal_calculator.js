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
// [полное имя, короткая подпись, ключ иконки, цвет подсветки]
const TILES = [
	["Арматура", "Арматура", "armatura", "#E2683C"],
	["Двутавр", "Двутавр", "ibeam", "#3B82F6"],
	["Швеллер", "Швеллер", "channel", "#8B5CF6"],
	["Уголок равнополочный", "Уголок равноп.", "angle", "#10B981"],
	["Уголок неравнополочный", "Уголок неравноп.", "angle", "#14B8A6"],
	["Труба круглая", "Труба круглая", "pipe", "#0EA5E9"],
	["Труба профильная квадратная", "Профтруба кв.", "sqpipe", "#6366F1"],
	["Труба профильная прямоугольная", "Профтруба прям.", "rectpipe", "#A855F7"],
	["Круг", "Круг", "circle", "#F59E0B"],
	["Квадрат", "Квадрат", "square", "#EF4444"],
	["Шестигранник", "Шестигранник", "hex", "#EC4899"],
	[SHEET_TYPE, "Лист", "sheet", "#64748B"],
];

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

const fmtN = (v) => (v % 1 === 0 ? String(Math.round(v)) : String(v));
// Парсинг номерного типоразмера (двутавр/швеллер): "20Б1"→[20,"Б1"], "16аУ"→[16а,"У"], "6.5У"→[6.5,"У"]
const NUM_RE = /^(\d+(?:\.\d+)?а?)(.*)$/;

class MetalCalculator {
	constructor(page) {
		this.page = page;
		this.controls = {};
		this.spec = [];
		this.current_type = "Двутавр";
		this.profiles = [];
		this.selected_ref = null;
		this.inject_styles();
		this.render();
		this.make_controls();
		this.select_type(this.current_type);
	}

	inject_styles() {
		if (document.getElementById("mc-styles")) return;
		const css = `
		.mc-wrap{padding:18px 16px 0}
		.mc-tiles{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:0 0 24px;max-width:760px}
		.mc-tile{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;
			padding:9px 4px;border:1px solid var(--border-color);border-radius:9px;cursor:pointer;
			background:var(--card-bg);transition:all .12s;text-align:center;min-height:66px}
		.mc-tile:hover{border-color:var(--tile-color);transform:translateY(-1px)}
		.mc-tile.active{border-color:var(--tile-color);background:color-mix(in srgb, var(--tile-color) 14%, transparent);
			box-shadow:inset 0 0 0 1px var(--tile-color)}
		.mc-tile svg{width:26px;height:26px;color:var(--tile-color)}
		.mc-tile span{font-size:.7rem;line-height:1.05;color:var(--text-color)}
		.mc-tile.active span{color:var(--tile-color);font-weight:600}
		.mc-picker{margin-bottom:14px}
		.mc-search{width:100%;margin-bottom:8px}
		.mc-cascade{display:flex;gap:10px;flex-wrap:wrap}
		.mc-cascade > div{flex:1;min-width:150px}
		.mc-cascade label{font-size:.78rem;color:var(--text-muted);display:block;margin-bottom:3px}
		.mc-results{border:1px solid var(--border-color);border-radius:8px;max-height:260px;overflow:auto;margin-bottom:8px}
		.mc-res-row{display:flex;justify-content:space-between;padding:7px 11px;cursor:pointer;border-bottom:1px solid var(--border-color)}
		.mc-res-row:last-child{border-bottom:none}
		.mc-res-row:hover{background:var(--bg-light-gray,rgba(0,0,0,.04))}
		.mc-res-row .m{color:var(--text-muted);white-space:nowrap;margin-left:12px}
		.mc-picked{margin-top:8px;font-size:.9rem;color:var(--text-color)}
		.mc-picked b{color:var(--primary)}
		.mc-spec-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.86rem}
		.mc-spec-table th,.mc-spec-table td{padding:8px 10px;text-align:left;
			border-bottom:1px solid color-mix(in srgb, var(--text-color) 12%, transparent)}
		.mc-spec-table th{color:var(--text-muted);font-weight:600;white-space:nowrap;
			border-bottom:2px solid color-mix(in srgb, var(--text-color) 22%, transparent)}
		.mc-spec-table tbody tr:nth-child(even){background:color-mix(in srgb, var(--text-color) 5%, transparent)}
		.mc-spec-table tbody tr:hover{background:color-mix(in srgb, var(--text-color) 10%, transparent)}
		.mc-spec-table td.num,.mc-spec-table th.num{text-align:right;white-space:nowrap}
		.mc-spec-total td{font-weight:700;border-top:2px solid color-mix(in srgb, var(--text-color) 22%, transparent)}
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
				<div class="mc-form" style="max-width:600px;">
					<div class="mc-picker" data-block="profile">
						<input type="text" class="form-control mc-search" placeholder="${__("Поиск типоразмера, напр. 40x40 или 20Б1…")}">
						<div class="mc-results" style="display:none;"></div>
						<div class="mc-cascade"></div>
						<div class="mc-picked"></div>
					</div>
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

		const $tiles = this.page.body.find(".mc-tiles");
		TILES.forEach(([full, short, icon, color]) => {
			const $t = $(`<div class="mc-tile" data-type="${frappe.utils.escape_html(full)}" style="--tile-color:${color}" title="${frappe.utils.escape_html(full)}">${ICONS[icon] || ""}<span>${frappe.utils.escape_html(short)}</span></div>`);
			$t.on("click", () => this.select_type(full));
			$tiles.append($t);
		});

		this.page.body.find(".mc-search").on("input", (e) => this.on_search(e.target.value));
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
		this._mount("sheet_type", {
			fieldname: "sheet_type", label: __("Тип листа"), fieldtype: "Select",
			options: ["Гладкий", "Рифлёный", "Просечно-вытяжной"].join("\n"), default: "Гладкий",
			change: () => me.controls.ref_sheet.set_value(""),
		});
		this._mount("ref_sheet", {
			fieldname: "ref_sheet", label: __("Лист (типоразмер)"), fieldtype: "Link", options: "Metal Sheet Grade",
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
		this.selected_ref = null;
		this.page.body.find(".mc-tile").removeClass("active");
		this.page.body.find(`.mc-tile[data-type="${type.replace(/"/g, '\\"')}"]`).addClass("active");

		const sheet = this.is_sheet();
		this.page.body.find('[data-block="profile"]').toggle(!sheet);
		this.page.body.find('[data-field="sheet_type"]').toggle(sheet);
		this.page.body.find('[data-field="ref_sheet"]').toggle(sheet);
		this.page.body.find('[data-field="length_mm"]').closest(".mc-row").toggle(!sheet);
		this.page.body.find(".mc-sheet-sides").css("display", sheet ? "flex" : "none");
		if (sheet) return;

		this.page.body.find(".mc-search").val("");
		this.page.body.find(".mc-results").hide().empty();
		this.page.body.find(".mc-cascade").html(`<div class="text-muted">${__("Загрузка…")}</div>`);
		frappe.db
			.get_list("Metal Profile", {
				filters: { profile_type: type },
				fields: ["name", "size_label", "height_mm", "width_mm", "wall_mm", "mass_per_meter"],
				limit: 0,
				order_by: "height_mm asc, width_mm asc, wall_mm asc",
			})
			.then((rows) => {
				if (this.current_type !== type) return; // успели переключить
				this.profiles = rows || [];
				this.build_cascade();
			});
	}

	_mode() {
		const r = this.profiles;
		const anyWall = r.some((x) => x.wall_mm);
		const anyWidth = r.some((x) => x.width_mm);
		const anyHeight = r.some((x) => x.height_mm);
		if (!anyHeight) return "numseries"; // двутавр/швеллер
		if (anyWall && anyWidth) return "section_wall"; // профтруба, уголок
		if (anyWall && !anyWidth) return "dia_wall"; // труба круглая
		return "single"; // круг/квадрат/арматура/шестигранник
	}

	_groups() {
		// Вернуть [{key,label,records:[]}] в порядке возрастания, по режиму.
		const mode = this._mode();
		const map = new Map();
		const order = [];
		const add = (key, label, rec) => {
			if (!map.has(key)) { map.set(key, { key, label, records: [] }); order.push(key); }
			map.get(key).records.push(rec);
		};
		this.profiles.forEach((rec) => {
			if (mode === "section_wall") add(`${rec.height_mm}x${rec.width_mm}`, `${fmtN(rec.height_mm)}×${fmtN(rec.width_mm)}`, rec);
			else if (mode === "dia_wall") add(String(rec.height_mm), `⌀${fmtN(rec.height_mm)}`, rec);
			else if (mode === "numseries") { const m = (rec.size_label || "").match(NUM_RE); const num = m ? m[1] : rec.size_label; add(num, num, rec); }
			else add(rec.name, rec.size_label, rec); // single: каждая запись — своя
		});
		const groups = order.map((k) => map.get(k));
		const numKey = (g) => parseFloat(String(g.key).replace(/[^\d.]/g, "")) || 0;
		groups.sort((a, b) => numKey(a) - numKey(b) || String(a.key).localeCompare(b.key, "ru"));
		return { mode, groups };
	}

	_leaf_label(mode, rec) {
		// Подпись второго уровня (конкретная запись внутри группы).
		const bes = (rec.size_label || "").includes("бесш") ? " (бесш)" : "";
		if (mode === "section_wall" || mode === "dia_wall") return `${fmtN(rec.wall_mm)} мм${bes}`;
		if (mode === "numseries") { const m = (rec.size_label || "").match(NUM_RE); return (m && m[2]) || rec.size_label; }
		return rec.size_label;
	}

	_group_key_of(mode, rec) {
		if (mode === "section_wall") return `${rec.height_mm}x${rec.width_mm}`;
		if (mode === "dia_wall") return String(rec.height_mm);
		if (mode === "numseries") { const m = (rec.size_label || "").match(NUM_RE); return m ? m[1] : rec.size_label; }
		return rec.name;
	}

	build_cascade(preselect) {
		const { mode, groups } = this._groups();
		const $c = this.page.body.find(".mc-cascade");
		if (!groups.length) { $c.html(`<div class="text-muted">${__("Нет данных")}</div>`); this.render_picked(); return; }
		const preRec = preselect && this.profiles.find((r) => r.name === preselect);

		if (mode === "single") {
			const opts = groups.map((g) => `<option value="${frappe.utils.escape_html(g.records[0].name)}">${frappe.utils.escape_html(g.label)}</option>`).join("");
			$c.html(`<div><label>${__("Типоразмер")}</label><select class="form-control mc-c1">${opts}</select></div>`);
			const $c1 = $c.find(".mc-c1");
			if (preRec) $c1.val(preRec.name);
			const pick = () => { this.selected_ref = $c1.val(); this.render_picked(); };
			$c1.on("change", pick); pick();
			return;
		}

		const lvl1 = mode === "dia_wall" ? __("Диаметр") : mode === "numseries" ? __("Номер") : __("Сечение");
		const lvl2 = mode === "numseries" ? __("Серия") : __("Стенка / толщина");
		const o1 = groups.map((g) => `<option value="${frappe.utils.escape_html(g.key)}">${frappe.utils.escape_html(g.label)}</option>`).join("");
		$c.html(`
			<div><label>${lvl1}</label><select class="form-control mc-c1">${o1}</select></div>
			<div><label>${lvl2}</label><select class="form-control mc-c2"></select></div>
		`);
		const $c1 = $c.find(".mc-c1"), $c2 = $c.find(".mc-c2");
		const byKey = {}; groups.forEach((g) => (byKey[g.key] = g));
		if (preRec) $c1.val(this._group_key_of(mode, preRec));
		const fillC2 = (leaf) => {
			const g = byKey[$c1.val()];
			const recs = g ? g.records.slice() : [];
			recs.sort((a, b) => (a.wall_mm || 0) - (b.wall_mm || 0) || String(a.size_label).localeCompare(b.size_label, "ru"));
			$c2.html(recs.map((r) => `<option value="${frappe.utils.escape_html(r.name)}">${frappe.utils.escape_html(this._leaf_label(mode, r))}</option>`).join(""));
			if (leaf) $c2.val(leaf);
			pickLeaf();
		};
		const pickLeaf = () => { this.selected_ref = $c2.val(); this.render_picked(); };
		$c1.on("change", () => fillC2()); $c2.on("change", pickLeaf);
		fillC2(preRec ? preRec.name : null);
	}

	render_picked() {
		const rec = this.profiles.find((r) => r.name === this.selected_ref);
		const $p = this.page.body.find(".mc-picked");
		if (!rec) { $p.empty(); return; }
		$p.html(`${__("Выбрано")}: <b>${frappe.utils.escape_html(rec.size_label)}</b> — ${fmtN(rec.mass_per_meter)} ${__("кг/м")} <span class="text-muted">(${frappe.utils.escape_html(rec.name)})</span>`);
	}

	on_search(q) {
		const norm = (s) => (s || "").toLowerCase().replace(/[х×]/g, "x").replace(/\s+/g, "");
		const $res = this.page.body.find(".mc-results");
		const $casc = this.page.body.find(".mc-cascade");
		const query = norm(q);
		if (!query) { $res.hide().empty(); $casc.show(); return; }
		$casc.hide();
		const hits = this.profiles.filter((r) => norm(r.size_label).includes(query)).slice(0, 60);
		if (!hits.length) { $res.show().html(`<div class="mc-res-row text-muted">${__("Ничего не найдено")}</div>`); return; }
		$res.show().html(
			hits.map((r) => `<div class="mc-res-row" data-name="${frappe.utils.escape_html(r.name)}"><span>${frappe.utils.escape_html(r.size_label)}</span><span class="m">${fmtN(r.mass_per_meter)} ${__("кг/м")}</span></div>`).join("")
		);
		$res.find(".mc-res-row[data-name]").on("click", (e) => {
			const name = $(e.currentTarget).data("name");
			this.page.body.find(".mc-search").val("");
			$res.hide().empty(); $casc.show();
			this.build_cascade(name); // каскад встаёт на выбранную позицию
		});
	}

	add_position() {
		const sheet = this.is_sheet();
		const qty = this.controls.qty.get_value();
		const grade = this.controls.steel_grade.get_value();
		const args = { mode: sheet ? "sheet" : "linear", qty, steel_grade: grade };
		let ref, dims, label;

		if (sheet) {
			ref = this.controls.ref_sheet.get_value();
			if (!ref) return frappe.msgprint(__("Выберите лист"));
			args.ref = ref;
			args.a_mm = this.controls.a_mm.get_value();
			args.b_mm = this.controls.b_mm.get_value();
			dims = `${args.a_mm}×${args.b_mm} мм`;
			label = ref;
		} else {
			ref = this.selected_ref;
			if (!ref) return frappe.msgprint(__("Выберите типоразмер"));
			args.ref = ref;
			args.length_mm = this.controls.length_mm.get_value();
			dims = `L=${args.length_mm} мм`;
			const rec = this.profiles.find((r) => r.name === ref);
			label = rec ? rec.size_label : ref;
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
					item_ref: label,
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
				<td>${i + 1}</td><td>${esc(r.form)}</td><td>${esc(r.item_ref)}</td><td>${esc(r.steel_grade || "—")}</td>
				<td>${esc(r.dims)}</td><td class="num">${r.qty}</td>
				<td class="num">${fmt(r.weight_one_kg)}</td><td class="num">${fmt(r.weight_total_kg)}</td>
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
				<tfoot><tr class="mc-spec-total"><td colspan="7" class="num">${__("Итого")}:</td><td class="num">${fmt(total)}</td><td></td></tr></tfoot>
			</table>
		`);
		$body.find(".mc-del").on("click", (e) => { this.spec.splice(parseInt($(e.currentTarget).data("i"), 10), 1); this.render_spec(); });
	}

	clear_spec() {
		if (!this.spec.length) return;
		frappe.confirm(__("Очистить всю спецификацию?"), () => { this.spec = []; this.render_spec(); });
	}

	export_csv() {
		if (!this.spec.length) return frappe.msgprint(__("Спецификация пустая"));
		const head = ["#", "Форма", "Типоразмер", "Марка", "Размеры", "Кол-во", "Вес 1 шт, кг", "Вес всего, кг"];
		const lines = [head.join(";")];
		this.spec.forEach((r, i) => lines.push([i + 1, r.form, r.item_ref, r.steel_grade || "", r.dims, r.qty, r.weight_one_kg, r.weight_total_kg].join(";")));
		const total = this.spec.reduce((s, r) => s + (r.weight_total_kg || 0), 0);
		lines.push(["", "", "", "", "", "", "Итого", total.toFixed(3)].join(";"));
		const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url; a.download = "specification.csv"; a.click();
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
					freeze: true, freeze_message: __("Сохраняем..."),
					callback: (r) => {
						if (!r.message) return;
						const name = r.message.name;
						frappe.show_alert({ message: __("Спецификация {0} сохранена", [name]), indicator: "green" });
						frappe.msgprint({ title: __("Сохранено"), message: `<a href="/app/metal-spec/${encodeURIComponent(name)}" target="_blank">${frappe.utils.escape_html(name)}</a> — ${__("открыть для печати/PDF")}` });
					},
				});
			},
			__("Сохранить спецификацию"), __("Сохранить")
		);
	}
}
