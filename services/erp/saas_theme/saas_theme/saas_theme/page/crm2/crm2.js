// CRM 2.0 — витрина нового CRM-вида. Полированный список сделок и лидов на
// реальных данных; строка открывает красивую карточку deal_view. Отдельный
// раздел (изолирован от старого CRM для сравнения). Цвета — desk-темы.
const CRM2_BUILD = "c1";

let CRM2_PAGE = null;
const CRM2 = { cur: "deal", q: "", deals: null, leads: null };

frappe.pages["crm2"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("CRM 2.0"), single_column: true });
	CRM2_PAGE = page;
	crm2_styles();
	crm2_shell(page);
	crm2_load();
};
frappe.pages["crm2"].on_page_show = function () {
	if (CRM2_PAGE && CRM2.deals !== null) crm2_load();
};

const CRM2_STATUS_COLOR = {
	Open: "#4D94FF", Quotation: "#F5A623", Converted: "#22A06B", Lost: "#E5484D",
	Replied: "#12A5B0", Closed: "#8B95A5", Lead: "#8B95A5", Interested: "#22A06B",
	Opportunity: "#4D94FF", "Do Not Contact": "#E5484D",
};
function crm2_esc(t) { return frappe.utils.escape_html(String(t == null ? "" : t)); }
function crm2_initials(s) {
	s = (s || "").trim();
	if (!s) return "?";
	const p = s.split(/[\s@._-]+/).filter(Boolean);
	return ((p[0] ? p[0][0] : "") + (p[1] ? p[1][0] : "")).toUpperCase() || s[0].toUpperCase();
}
function crm2_color(s) {
	let h = 0;
	for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
	return "hsl(" + h + ",42%,52%)";
}
function crm2_date(ts) { try { return frappe.datetime.str_to_user(ts).split(" ")[0]; } catch (e) { return ""; } }

function crm2_shell(page) {
	const $body = $(page.body).empty();
	const $wrap = $('<div class="crm2-wrap"></div>').appendTo($body);

	const $head = $('<div class="crm2-head"></div>');
	$head.append('<span class="crm2-title">CRM 2.0</span>');
	$head.append('<span class="crm2-chip">' + crm2_esc(__("новый вид")) + "</span>");
	$head.append('<span style="flex:1"></span>');
	$head.append($('<a class="crm2-old" href="#"></a>').text(__("Старый CRM") + " ↗").on("click", function (e) {
		e.preventDefault(); frappe.set_route("List", "Opportunity", "Kanban", "Продажи");
	}));
	$wrap.append($head);

	const $ctrl = $('<div class="crm2-ctrl"></div>');
	const $seg = $('<div class="crm2-seg"></div>');
	$('<button data-v="deal" class="on"></button>').text(__("Сделки")).appendTo($seg);
	$('<button data-v="lead"></button>').text(__("Лиды")).appendTo($seg);
	$ctrl.append($seg);
	const $q = $('<input type="text" class="crm2-q">').attr("placeholder", __("Поиск по названию или контакту…"));
	$ctrl.append($q);
	const $add = $('<button class="btn btn-sm btn-primary crm2-add"></button>');
	$ctrl.append($add);
	$wrap.append($ctrl);

	$wrap.append('<div class="crm2-list" id="crm2-list"></div>');

	$seg.find("button").on("click", function () {
		$seg.find("button").removeClass("on");
		$(this).addClass("on");
		CRM2.cur = $(this).attr("data-v");
		crm2_render();
	});
	$q.on("input", function () { CRM2.q = this.value || ""; crm2_render(); });
	$add.on("click", function () { frappe.new_doc(CRM2.cur === "deal" ? "Opportunity" : "Lead"); });
	CRM2.$add = $add;
}

function crm2_load() {
	const $list = $("#crm2-list");
	if ($list.length && CRM2.deals === null) $list.html('<div class="crm2-empty">' + crm2_esc(__("Загрузка…")) + "</div>");
	const gl = function (doctype, fields) {
		return frappe.call({ method: "frappe.client.get_list", args: { doctype: doctype, fields: fields, order_by: "modified desc", limit_page_length: 100 } })
			.then(function (r) { return (r && r.message) || []; }, function () { return []; });
	};
	Promise.all([
		gl("Opportunity", ["name", "customer_name", "party_name", "status", "opportunity_amount", "currency", "contact_display", "modified"]),
		gl("Lead", ["name", "company_name", "lead_name", "status", "email_id", "source", "modified"]),
	]).then(function (res) { CRM2.deals = res[0]; CRM2.leads = res[1]; crm2_render(); });
}

function crm2_render() {
	const $list = $("#crm2-list");
	if (!$list.length) return;
	if (CRM2.$add) CRM2.$add.html('<i></i>+ ' + crm2_esc(CRM2.cur === "deal" ? __("Сделка") : __("Лид")));
	const isDeal = CRM2.cur === "deal";
	const data = (isDeal ? CRM2.deals : CRM2.leads) || [];
	const q = (CRM2.q || "").toLowerCase();
	$list.empty();

	const rows = data.map(function (x) {
		if (isDeal) {
			const org = x.customer_name || x.party_name || x.name;
			const amt = x.opportunity_amount ? format_currency(x.opportunity_amount, x.currency) : "";
			const sub = [x.contact_display, amt].filter(Boolean).join(" · ");
			return { dt: "Opportunity", name: x.name, org: org, sub: sub, status: x.status, date: crm2_date(x.modified) };
		}
		const org = x.company_name || x.lead_name || x.name;
		const sub = [x.email_id, x.source].filter(Boolean).join(" · ");
		return { dt: "Lead", name: x.name, org: org, sub: sub, status: x.status, date: crm2_date(x.modified) };
	}).filter(function (r) { return !q || (r.org + " " + r.sub).toLowerCase().indexOf(q) >= 0; });

	if (!rows.length) { $list.append('<div class="crm2-empty">' + crm2_esc(__("Ничего не найдено")) + "</div>"); return; }

	rows.forEach(function (r) {
		const scol = CRM2_STATUS_COLOR[r.status] || "#8B95A5";
		const $row = $('<div class="crm2-row"></div>').on("click", function () { frappe.set_route("deal_view", r.dt, r.name); });
		$row.append($('<span class="crm2-av"></span>').text(crm2_initials(r.org)).css("background", crm2_color(r.org)));
		const $mid = $('<div class="crm2-mid"></div>');
		$mid.append($('<div class="crm2-name"></div>').text(r.org));
		if (r.sub) $mid.append($('<div class="crm2-sub"></div>').text(r.sub).attr("title", r.sub));
		$row.append($mid);
		if (r.status) $row.append($('<span class="crm2-pill"></span>').text(__(r.status)).css({ "background-color": scol + "22", color: scol }));
		$row.append($('<span class="crm2-rdate"></span>').text(r.date));
		$row.append('<span class="crm2-chev">›</span>');
		$list.append($row);
	});
}

function crm2_styles() {
	if (document.getElementById("crm2-styles")) return;
	const css = `
.crm2-wrap{max-width:920px;margin:0 auto}
.crm2-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.crm2-title{font-size:18px;font-weight:600;color:var(--text-color)}
.crm2-chip{padding:2px 9px;border-radius:20px;font-size:11px;font-weight:500;background:rgba(77,148,255,0.14);color:var(--primary)}
.crm2-old{font-size:12px;color:var(--text-muted)}
.crm2-ctrl{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.crm2-seg{display:inline-flex;border:1px solid var(--border-color);border-radius:8px;overflow:hidden}
.crm2-seg button{border:none;background:none;font-size:13px;padding:6px 14px;cursor:pointer;color:var(--text-muted)}
.crm2-seg button.on{background:var(--control-bg);color:var(--text-color)}
.crm2-q{flex:1;min-width:180px;height:34px;font-size:13px;padding:6px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--control-bg);color:var(--text-color)}
.crm2-q:focus{outline:none;border-color:var(--primary)}
.crm2-add{white-space:nowrap}
.crm2-empty{color:var(--text-muted);font-size:13px;padding:20px 4px}
.crm2-row{display:flex;align-items:center;gap:12px;padding:10px 8px;border-bottom:1px solid var(--border-color);cursor:pointer;border-radius:8px}
.crm2-row:hover{background:var(--control-bg)}
.crm2-av{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:500;font-size:12px;flex:none}
.crm2-mid{flex:1;min-width:0}
.crm2-name{font-size:13px;font-weight:500;color:var(--text-color);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.crm2-sub{font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.crm2-pill{padding:2px 9px;border-radius:20px;font-size:11px;font-weight:500;white-space:nowrap}
.crm2-rdate{font-size:12px;color:var(--text-muted);white-space:nowrap}
.crm2-chev{color:var(--text-muted);font-size:18px;line-height:1}
`;
	$("<style id='crm2-styles'></style>").text(css).appendTo(document.head);
}
