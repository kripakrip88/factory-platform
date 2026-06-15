frappe.pages["metal_calculator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Калькулятор металла"),
		single_column: true,
	});

	new MetalCalculator(page);
};

const LINEAR_TYPES = [
	"Арматура",
	"Двутавр",
	"Швеллер",
	"Уголок равнополочный",
	"Уголок неравнополочный",
	"Труба круглая",
	"Труба профильная квадратная",
	"Труба профильная прямоугольная",
	"Круг",
	"Квадрат",
	"Шестигранник",
];
const SHEET_TYPE = "Лист";

class MetalCalculator {
	constructor(page) {
		this.page = page;
		this.controls = {};
		this.render();
		this.make_controls();
		this.toggle_mode();
	}

	render() {
		$(this.page.body).html(`
			<div class="mc-wrap" style="max-width:640px; margin:0 auto;">
				<div class="mc-field" data-field="profile_type"></div>
				<div class="mc-field" data-field="ref_profile"></div>
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
					<button class="btn btn-primary mc-calc">${__("Рассчитать")}</button>
				</div>
				<div class="mc-result" style="margin-top:24px;"></div>
			</div>
		`);

		this.page.body.find(".mc-calc").on("click", () => this.calculate());
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

		this._mount("profile_type", {
			fieldname: "profile_type",
			label: __("Тип сортамента"),
			fieldtype: "Select",
			options: [...LINEAR_TYPES, SHEET_TYPE].join("\n"),
			default: "Двутавр",
			change: () => me.toggle_mode(),
		});
		this.controls.profile_type.set_value("Двутавр");

		this._mount("ref_profile", {
			fieldname: "ref_profile",
			label: __("Типоразмер"),
			fieldtype: "Link",
			options: "Metal Profile",
			get_query: () => ({
				filters: { profile_type: me.controls.profile_type.get_value() },
			}),
		});

		this._mount("ref_sheet", {
			fieldname: "ref_sheet",
			label: __("Толщина листа"),
			fieldtype: "Link",
			options: "Metal Sheet Grade",
		});

		this._mount("length_mm", {
			fieldname: "length_mm",
			label: __("Длина L, мм"),
			fieldtype: "Float",
			default: 6000,
		});
		this.controls.length_mm.set_value(6000);

		this._mount("a_mm", {
			fieldname: "a_mm",
			label: __("Сторона a, мм"),
			fieldtype: "Float",
			default: 1500,
		});

		this._mount("b_mm", {
			fieldname: "b_mm",
			label: __("Сторона b, мм"),
			fieldtype: "Float",
			default: 6000,
		});

		this._mount("qty", {
			fieldname: "qty",
			label: __("Количество, шт"),
			fieldtype: "Int",
			default: 1,
		});
		this.controls.qty.set_value(1);

		this._mount("steel_grade", {
			fieldname: "steel_grade",
			label: __("Марка стали"),
			fieldtype: "Link",
			options: "Steel Grade",
		});
		this.set_default_grade();
	}

	set_default_grade() {
		frappe.db
			.get_value("Steel Grade", { is_default: 1 }, "name")
			.then((r) => {
				const grade = (r && r.message && r.message.name) || "Ст3сп";
				this.controls.steel_grade.set_value(grade);
			});
	}

	is_sheet() {
		return this.controls.profile_type.get_value() === SHEET_TYPE;
	}

	toggle_mode() {
		const sheet = this.is_sheet();
		this.page.body.find('[data-field="ref_profile"]').toggle(!sheet);
		this.page.body.find('[data-field="ref_sheet"]').toggle(sheet);
		this.page.body.find('[data-field="length_mm"]').closest(".mc-row").toggle(!sheet);
		this.page.body.find(".mc-sheet-sides").css("display", sheet ? "flex" : "none");
		// Сбрасываем выбор типоразмера при смене типа сортамента.
		if (!sheet && this.controls.ref_profile) {
			this.controls.ref_profile.set_value("");
		}
		this.page.body.find(".mc-result").empty();
	}

	calculate() {
		const sheet = this.is_sheet();
		const args = {
			mode: sheet ? "sheet" : "linear",
			qty: this.controls.qty.get_value(),
			steel_grade: this.controls.steel_grade.get_value(),
		};

		if (sheet) {
			args.ref = this.controls.ref_sheet.get_value();
			args.a_mm = this.controls.a_mm.get_value();
			args.b_mm = this.controls.b_mm.get_value();
			if (!args.ref) {
				frappe.msgprint(__("Выберите толщину листа"));
				return;
			}
		} else {
			args.ref = this.controls.ref_profile.get_value();
			args.length_mm = this.controls.length_mm.get_value();
			if (!args.ref) {
				frappe.msgprint(__("Выберите типоразмер"));
				return;
			}
		}

		frappe.call({
			method: "metal_calculator.api.calculate",
			args: args,
			freeze: true,
			freeze_message: __("Считаем..."),
			callback: (r) => {
				if (r.message) this.show_result(r.message);
			},
		});
	}

	show_result(res) {
		const fmt = (v) => frappe.format(v, { fieldtype: "Float", precision: 3 });
		this.page.body.find(".mc-result").html(`
			<div class="frappe-card" style="padding:16px;">
				<div style="display:flex; justify-content:space-between; padding:6px 0;">
					<span class="text-muted">${__("Вес 1 шт")}</span>
					<b>${fmt(res.weight_one_kg)} ${res.unit}</b>
				</div>
				<div style="display:flex; justify-content:space-between; padding:6px 0; border-top:1px solid var(--border-color);">
					<span class="text-muted">${__("Общий вес")} (${res.qty} ${__("шт")})</span>
					<b style="font-size:1.2em;">${fmt(res.weight_total_kg)} ${res.unit}</b>
				</div>
				<div style="display:flex; justify-content:space-between; padding:6px 0; border-top:1px solid var(--border-color);">
					<span class="text-muted">${__("Марка стали")}</span>
					<span>${frappe.utils.escape_html(res.steel_grade || "—")}</span>
				</div>
			</div>
		`);
	}
}
