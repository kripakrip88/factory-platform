// Карточка сделки/лида — «красивая панель на грузовике». Отдельная Frappe-страница
// поверх РЕАЛЬНЫХ данных ERPNext (Opportunity/Lead + Communication/Comment/ToDo/
// Quotation/Version), а не декор формы. Порт утверждённых прототипов.
// Вкладки: Активность (единая лента) · Письма (тред) · Задачи · Заметки.
// Тред/лента писем = привязанные к записи ПЛЮС по адресу контакта.
// Иконки — инлайн-SVG (без зависимости от шрифта Font Awesome). Цвета — desk-темы.
const DEAL_VIEW_BUILD = "dv4";

let DV_PAGE = null;
let DV = null; // {dt, doc, comms, comments, todos, quotations, versions}

frappe.pages["deal_view"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Карточка сделки"), single_column: true });
	DV_PAGE = page;
	inject_deal_view_styles();
	deal_view_render(page);
};
frappe.pages["deal_view"].on_page_show = function () {
	if (DV_PAGE) deal_view_render(DV_PAGE);
};

// ── Инлайн-SVG иконки (stroke, currentColor) ──────────────────────────────
const DV_ICONS = {
	send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
	mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
	message: '<path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2z"/>',
	check: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
	phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.6A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.3 1.8.6 2.6a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.4-1.1a2 2 0 0 1 2.1-.5c.8.3 1.7.5 2.6.6a2 2 0 0 1 1.7 2z"/>',
	flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
	file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
	plus: '<path d="M12 5v14M5 12h14"/>',
	pencil: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
	paperclip: '<path d="M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.6 8.5a2 2 0 0 1-3-3L15 6"/>',
};
function dv_svg(name, size) {
	size = size || 15;
	return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (DV_ICONS[name] || "") + "</svg>";
}

const DEAL_VIEW_FIELDS = {
	Opportunity: [
		{ fn: "contact_display", label: "Контакт" },
		{ fn: "mw_categories_display", label: "Категория" },
		{ fn: "mw_estimated_volume", label: "Объём", suffix: " т" },
		{ fn: "mw_desired_delivery_date", label: "Желаемая поставка", date: 1 },
		{ fn: "mw_drawing_status", label: "Чертежи" },
		{ fn: "sales_stage", label: "Этап" },
		{ fn: "expected_closing", label: "Ожид. закрытие", date: 1 },
		{ fn: "utm_source", label: "Источник" },
		{ fn: "territory", label: "Территория" },
		{ fn: "opportunity_owner", label: "Ответственный" },
	],
	Lead: [
		{ fn: "email_id", label: "Email" },
		{ fn: "mobile_no", label: "Телефон", alt: "phone" },
		{ fn: "type", label: "Тип лида" },
		{ fn: "request_type", label: "Запрос" },
		{ fn: "industry", label: "Отрасль" },
		{ fn: "market_segment", label: "Сегмент" },
		{ fn: "qualification_status", label: "Квалификация" },
		{ fn: "utm_source", label: "Источник" },
		{ fn: "territory", label: "Территория" },
	],
};
const DEAL_VIEW_STATUS_COLOR = {
	Open: "#4D94FF", Quotation: "#F5A623", Converted: "#22A06B", Lost: "#E5484D",
	Replied: "#12A5B0", Closed: "#8B95A5", Lead: "#8B95A5", Interested: "#22A06B",
	Opportunity: "#4D94FF", "Do Not Contact": "#E5484D",
};

// ── helpers ───────────────────────────────────────────────────────────────
function dv_esc(t) { return frappe.utils.escape_html(String(t == null ? "" : t)); }
function dv_initials(s) {
	s = (s || "").trim();
	if (!s) return "?";
	const p = s.split(/[\s@._-]+/).filter(Boolean);
	return ((p[0] ? p[0][0] : "") + (p[1] ? p[1][0] : "")).toUpperCase() || s[0].toUpperCase();
}
function dv_color(s) {
	let h = 0;
	for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
	return "hsl(" + h + ",42%,52%)";
}
function dv_strip(html) {
	const d = document.createElement("div");
	d.innerHTML = html || "";
	return (d.textContent || "").replace(/\s+/g, " ").trim();
}
function dv_snip(html, n) {
	const t = dv_strip(html);
	n = n || 170;
	return t.length > n ? t.slice(0, n) + "…" : t;
}
function dv_time(ts) {
	try { return (frappe.datetime.str_to_user(ts).split(" ")[1] || "").slice(0, 5); } catch (e) { return ""; }
}
function dv_day(ts) {
	try {
		const d = frappe.datetime.str_to_user(ts).split(" ")[0];
		const today = frappe.datetime.str_to_user(frappe.datetime.now_datetime()).split(" ")[0];
		const yst = frappe.datetime.str_to_user(frappe.datetime.add_to_date(frappe.datetime.now_datetime(), { days: -1 })).split(" ")[0];
		if (d === today) return __("Сегодня");
		if (d === yst) return __("Вчера");
		return d;
	} catch (e) { return ""; }
}
function dv_list(doctype, filters, fields, order, limit, or_filters) {
	const args = { doctype: doctype, filters: filters, fields: fields, order_by: order || "creation desc", limit_page_length: limit || 50 };
	if (or_filters) args.or_filters = or_filters;
	return frappe.call({ method: "frappe.client.get_list", args: args }).then(function (r) { return (r && r.message) || []; }, function () { return []; });
}

// ── загрузка ────────────────────────────────────────────────────────────────
function deal_view_render(page) {
	const route = frappe.get_route(); // ['deal_view', <doctype>, <name>]
	let dt = route[1] || "Opportunity";
	let name = route[2];
	if (!name && route[1]) { name = route[1]; dt = /LEAD/i.test(name) ? "Lead" : "Opportunity"; }
	const $body = $(page.body);
	if (!name) { $body.html('<div class="dv-empty">' + dv_esc(__("Откройте сделку или лид из формы кнопкой «Открыть карточку».")) + "</div>"); return; }
	$body.html('<div class="dv-empty">' + dv_esc(__("Загрузка…")) + "</div>");

	frappe.call({ method: "frappe.client.get", args: { doctype: dt, name: name } }).then(function (r) {
		const doc = r && r.message;
		if (!doc) { $body.html('<div class="dv-empty">' + dv_esc(__("Запись не найдена")) + "</div>"); return; }
		const email = doc.contact_email || doc.email_id || (/@/.test(doc.contact_display || "") ? doc.contact_display : "") || "";
		const or_f = [["reference_name", "=", name]];
		if (email) { or_f.push(["sender", "like", "%" + email + "%"]); or_f.push(["recipients", "like", "%" + email + "%"]); }

		Promise.all([
			dv_list("Communication", { communication_type: "Communication" },
				["name", "sender", "sender_full_name", "recipients", "subject", "content", "communication_date", "sent_or_received", "has_attachment", "creation"],
				"communication_date asc, creation asc", 50, or_f),
			dv_list("Comment", { reference_doctype: dt, reference_name: name, comment_type: "Comment" },
				["content", "comment_by", "owner", "creation"], "creation desc", 50),
			dv_list("ToDo", { reference_type: dt, reference_name: name },
				["name", "description", "status", "owner", "allocated_to", "date", "creation"], "creation desc", 100),
			dt === "Opportunity" ? dv_list("Quotation", { opportunity: name },
				["name", "grand_total", "currency", "status", "owner", "creation"], "creation desc", 20) : Promise.resolve([]),
			dv_list("Version", { ref_doctype: dt, docname: name }, ["data", "owner", "creation"], "creation desc", 40),
		]).then(function (res) {
			DV = { dt: dt, doc: doc, comms: res[0], comments: res[1], todos: res[2], quotations: res[3], versions: res[4] };
			deal_view_paint(page);
		});
	});
}

// ── отрисовка каркаса ────────────────────────────────────────────────────────
function deal_view_paint(page) {
	const dt = DV.dt, doc = DV.doc, isLead = dt === "Lead";
	const org = isLead ? (doc.company_name || doc.lead_name || doc.name) : (doc.customer_name || doc.party_name || doc.name);
	const amount = !isLead && doc.opportunity_amount ? format_currency(doc.opportunity_amount, doc.currency) : "";
	const status = doc.status || "";
	page.set_title(org);
	DV.amount = amount;

	const $body = $(page.body).empty();
	const $wrap = $('<div class="dv-wrap"></div>').appendTo($body);

	// шапка
	const scol = DEAL_VIEW_STATUS_COLOR[status] || "#8B95A5";
	const $head = $('<div class="dv-head"></div>');
	$head.append($('<div class="dv-av"></div>').text(dv_initials(org)).css("background", dv_color(org)));
	const $hc = $('<div class="dv-head-col"></div>');
	const $tr = $('<div class="dv-title-row"></div>').append($('<span class="dv-org"></span>').text(org));
	if (status) $tr.append($('<span class="dv-pill"></span>').text(__(status)).css({ "background-color": scol + "22", color: scol }));
	$hc.append($tr).append($('<div class="dv-sub"></div>').text(doc.name + (amount ? " · " + amount : "")));
	$head.append($hc);
	// Переход по воронке: зовём штатный make_* (get_mapped_doc) → открываем черновик.
	const dvConvert = function (method, target) {
		frappe.call({ method: method, args: { source_name: doc.name } })
			.then(function (r) { if (r.message) { frappe.model.sync(r.message); frappe.set_route("Form", target, r.message.name); } });
	};
	if (!isLead) {
		$head.append($('<button class="btn btn-sm btn-primary dv-btn"></button>').html(dv_svg("file", 14) + " " + dv_esc(__("Создать КП"))).on("click", function () {
			dvConvert("erpnext.crm.doctype.opportunity.opportunity.make_quotation", "Quotation");
		}));
	} else {
		// Воронка лида: Письмо → Лид → Покупатель → Сделка.
		$head.append($('<button class="btn btn-sm btn-primary dv-btn"></button>').html(dv_svg("file", 14) + " " + dv_esc(__("Создать сделку"))).on("click", function () {
			dvConvert("erpnext.crm.doctype.lead.lead.make_opportunity", "Opportunity");
		}));
		$head.append($('<button class="btn btn-sm dv-btn-sec"></button>').html(dv_svg("plus", 14) + " " + dv_esc(__("Покупатель"))).on("click", function () {
			dvConvert("erpnext.crm.doctype.lead.lead.make_customer", "Customer");
		}));
	}
	$head.append($('<button class="btn btn-sm dv-btn-sec"></button>').html(dv_svg("pencil", 14) + " " + dv_esc(__("Форма"))).on("click", function () {
		frappe.set_route("Form", dt, doc.name);
	}));
	$wrap.append($head);

	// вкладки
	const $tabs = $('<div class="dv-tabs"></div>');
	[["act", "Активность"], ["mail", "Письма"], ["task", "Задачи"], ["note", "Заметки"]].forEach(function (t) {
		$('<button class="dv-tab"></button>').text(__(t[1])).attr("data-t", t[0]).appendTo($tabs);
	});
	$wrap.append($tabs);

	// две колонки
	const $cols = $('<div class="dv-cols"></div>');
	const $left = $('<div class="dv-left"></div>');
	const $right = $('<div class="dv-right"></div>');
	$cols.append($left).append($right);
	$wrap.append($cols);
	DV.$left = $left;

	// правая — детали
	$right.append($('<div class="dv-det-title"></div>').text(__("Детали")));
	const list = DEAL_VIEW_FIELDS[dt] || [];
	if (amount) dv_row($right, "Сумма", amount);
	list.forEach(function (item) {
		let v = doc[item.fn];
		if ((v == null || v === "") && item.alt) v = doc[item.alt];
		if (v == null || v === "") return;
		let out = String(v);
		if (item.date) { try { out = frappe.datetime.str_to_user(v); } catch (e) {} }
		if (item.suffix) out = out + item.suffix;
		dv_row($right, item.label, out);
	});

	$tabs.find(".dv-tab").on("click", function () {
		$tabs.find(".dv-tab").removeClass("on");
		$(this).addClass("on");
		dv_show_tab($(this).attr("data-t"));
	});
	$tabs.find('.dv-tab[data-t="act"]').addClass("on");
	dv_show_tab("act");
}

function dv_row($p, label, val) {
	$p.append($('<div class="dv-row"></div>')
		.append($('<div class="dv-l"></div>').text(__(label)))
		.append($('<div class="dv-v"></div>').text(val).attr("title", val)));
}

function dv_show_tab(t) {
	const $left = DV.$left.empty();
	if (t === "mail") dv_build_thread($left);
	else if (t === "task") dv_build_tasks($left);
	else if (t === "note") dv_build_notes($left);
	else dv_build_activity($left);
}

// ── Активность (единая лента) ───────────────────────────────────────────────
function dv_build_activity($left) {
	const dt = DV.dt, doc = DV.doc, ev = [];
	DV.comms.forEach(function (c) {
		const out = c.sent_or_received === "Sent";
		ev.push({ ts: c.communication_date || c.creation, icon: out ? "send" : "mail",
			bg: out ? "var(--bg-accent, #E6F1FB)" : "#E1F5EE", col: out ? "var(--primary)" : "#0F6E56",
			actor: out ? (c.sender_full_name || "Мы") : (c.sender_full_name || c.sender || ""),
			action: out ? "отправил письмо" : "входящее письмо", snip: dv_snip(c.content) });
	});
	DV.comments.forEach(function (c) {
		ev.push({ ts: c.creation, icon: "message", bg: "#F1EFE8", col: "#444441",
			actor: c.comment_by || c.owner || "", action: "комментарий", snip: dv_snip(c.content) });
	});
	DV.todos.forEach(function (t) {
		const done = t.status === "Closed" || t.status === "Cancelled";
		ev.push({ ts: t.creation, icon: "check", bg: done ? "#EAF3DE" : "#F1EFE8", col: done ? "#3B6D11" : "#8A8780",
			actor: t.allocated_to || t.owner || "", action: (done ? "выполнил задачу «" : "задача «") + dv_strip(t.description).slice(0, 70) + "»" });
	});
	(DV.quotations || []).forEach(function (q) {
		ev.push({ ts: q.creation, icon: "file", bg: "#E6F1FB", col: "#0C447C", actor: q.owner || "",
			action: "создал КП", link: q.name + (q.grand_total ? " · " + format_currency(q.grand_total, q.currency) : "") });
	});
	(DV.versions || []).forEach(function (v) {
		let data;
		try { data = JSON.parse(v.data || "{}"); } catch (e) { return; }
		const ch = (data.changed || []).filter(function (r) { return r[0] === "status"; })[0];
		if (ch) ev.push({ ts: v.creation, icon: "flag", bg: "#FAEEDA", col: "#633806", statusChange: [ch[1], ch[2]] });
	});
	ev.push({ ts: doc.creation, icon: "plus", bg: "#F1EFE8", col: "#444441", action: (dt === "Lead" ? "Лид создан" : "Сделка создана") });

	ev.sort(function (a, b) { return a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0; });
	if (!ev.length) { $left.append('<div class="dv-stub">' + dv_esc(__("Событий по сделке пока нет.")) + "</div>"); return; }

	let day = null;
	ev.forEach(function (e) {
		const dl = dv_day(e.ts);
		if (dl !== day) { day = dl; $left.append($('<div class="dv-day"></div>').text(day)); }
		const $row = $('<div class="dv-ev"></div>');
		$row.append($('<div class="dv-ev-rail"></div>').append($('<div class="dv-dot"></div>').css({ background: e.bg, color: e.col }).html(dv_svg(e.icon, 15))));
		const $b = $('<div class="dv-ev-body"></div>');
		const $line = $('<div class="dv-ev-line"></div>');
		if (e.statusChange) {
			$line.append(document.createTextNode(__("Статус") + ": "));
			$line.append($('<span style="color:var(--text-muted)"></span>').text(__(e.statusChange[0]) || "—"));
			$line.append(document.createTextNode(" → "));
			$line.append($('<span style="font-weight:500"></span>').text(__(e.statusChange[1])));
		} else {
			if (e.actor) $line.append($('<span style="font-weight:500"></span>').text(e.actor)).append(document.createTextNode(" "));
			$line.append(document.createTextNode(e.action || ""));
			if (e.link) $line.append(document.createTextNode(" ")).append($('<span style="color:var(--primary)"></span>').text(e.link));
		}
		$line.append($('<span class="dv-ev-time"></span>').text(dv_time(e.ts)));
		$b.append($line);
		if (e.snip) $b.append($('<div class="dv-ev-snip"></div>').text(e.snip));
		$row.append($b);
		$left.append($row);
	});
}

// ── Письма (тред) ────────────────────────────────────────────────────────────
function dv_build_thread($left) {
	const comms = DV.comms;
	if (!comms.length) $left.append('<div class="dv-stub">' + dv_esc(__("Писем по этой записи пока нет.")) + "</div>");
	comms.forEach(function (c) {
		const out = c.sent_or_received === "Sent";
		const who = out ? (c.sender_full_name || "Мы") : (c.sender_full_name || c.sender || "");
		const $card = $('<div class="dv-mail"></div>');
		const $mh = $('<div class="dv-mail-head"></div>');
		$mh.append($('<div class="dv-mav"></div>').text(dv_initials(who)).css("background", dv_color(who)));
		const $mc = $('<div class="dv-mail-who"></div>');
		$mc.append($('<div class="dv-mail-name"></div>').text(who));
		$mc.append($('<div class="dv-mail-addr"></div>').text((c.sender || "") + " → " + (c.recipients || "")).attr("title", (c.sender || "") + " → " + (c.recipients || "")));
		$mh.append($mc);
		let when = ""; try { when = frappe.datetime.str_to_user(c.communication_date || c.creation); } catch (e) {}
		$mh.append($('<div class="dv-mail-date"></div>').text(when));
		$card.append($mh);
		if (c.subject) $card.append($('<div class="dv-mail-subj"></div>').text(c.subject));
		$card.append($('<div class="dv-body"></div>').html(c.content || ""));
		if (c.has_attachment) $card.append('<span class="dv-chip">' + dv_svg("paperclip", 13) + " " + dv_esc(__("Вложение")) + "</span>");
		$left.append($card);
	});
	const $rep = $('<div class="dv-reply"></div>');
	$rep.append($('<div class="dv-reply-title"></div>').text(__("Ответить")));
	$rep.append($('<button class="btn btn-sm btn-primary"></button>').html(dv_svg("mail", 14) + " " + dv_esc(__("Написать письмо"))).on("click", function () {
		const email = DV.doc.contact_email || DV.doc.email_id || (/@/.test(DV.doc.contact_display || "") ? DV.doc.contact_display : "") || "";
		new frappe.views.CommunicationComposer({ doctype: DV.dt, name: DV.doc.name, recipients: email });
	}));
	$left.append($rep);
	dv_bind_quotes($left);
}
function dv_bind_quotes($scope) {
	$scope.find(".dv-body").each(function () {
		const $b = $(this);
		const $q = $b.find("blockquote, .gmail_quote, .gmail_extra").first();
		if (!$q.length || $b.data("qbound")) return;
		$b.data("qbound", 1);
		$q.nextAll().addBack().hide();
		$('<button class="dv-quote-toggle">··· ' + dv_esc(__("цитата")) + "</button>").insertBefore($q).on("click", function () {
			const on = $q.is(":visible"); $q.nextAll().addBack()[on ? "hide" : "show"]();
		});
	});
}

// ── Задачи (реальные ToDo: инлайн-добавление + выполнение галочкой + группы) ──
function dv_build_tasks($left) {
	const $bar = $('<div class="dv-task-add"></div>');
	const $in = $('<input type="text" class="dv-task-in">').attr("placeholder", __("Новая задача — например, «Отправить финальное КП»"));
	const $btn = $('<button class="btn btn-sm btn-primary dv-task-addbtn"></button>').html(dv_svg("plus", 14) + " " + dv_esc(__("Добавить")));
	$bar.append($in).append($btn);
	$left.append($bar);
	const $list = $('<div class="dv-task-list"></div>');
	$left.append($list);

	const reload = function () {
		dv_list("ToDo", { reference_type: DV.dt, reference_name: DV.doc.name },
			["name", "description", "status", "owner", "allocated_to", "date", "creation"], "creation desc", 100)
			.then(function (l) { DV.todos = l; dv_paint_tasks($list); });
	};
	const add = function () {
		const v = ($in.val() || "").trim();
		if (!v) return;
		$btn.prop("disabled", true);
		frappe.call({ method: "frappe.client.insert", args: { doc: {
			doctype: "ToDo", description: v, reference_type: DV.dt, reference_name: DV.doc.name,
			allocated_to: frappe.session.user, date: frappe.datetime.get_today(),
		} } }).then(function () { $in.val(""); $btn.prop("disabled", false); reload(); },
			function () { $btn.prop("disabled", false); });
	};
	$btn.on("click", add);
	$in.on("keydown", function (e) { if (e.key === "Enter") add(); });
	dv_paint_tasks($list);
}

function dv_paint_tasks($list) {
	$list.empty();
	const todos = DV.todos || [];
	if (!todos.length) { $list.append('<div class="dv-stub">' + dv_esc(__("Задач по сделке нет. Добавьте первую выше.")) + "</div>"); return; }
	const today = frappe.datetime.get_today();
	const g = { over: [], today: [], next: [], done: [] };
	todos.forEach(function (t) {
		if (t.status === "Closed" || t.status === "Cancelled") g.done.push(t);
		else if (!t.date) g.next.push(t);
		else if (t.date < today) g.over.push(t);
		else if (t.date === today) g.today.push(t);
		else g.next.push(t);
	});
	[["over", "Просрочено", 1], ["today", "Сегодня", 0], ["next", "Предстоит", 0], ["done", "Выполнено", 0]].forEach(function (grp) {
		const arr = g[grp[0]];
		if (!arr.length) return;
		const $h = $('<div class="dv-grp"></div>').text(__(grp[1]));
		if (grp[2]) $h.css("color", "#E5484D");
		$list.append($h);
		arr.forEach(function (t) { $list.append(dv_task_row(t, $list)); });
	});
}

function dv_task_row(t, $list) {
	const done = t.status === "Closed" || t.status === "Cancelled";
	const $row = $('<div class="dv-task' + (done ? " done" : "") + '"></div>');
	const $chk = $('<button class="dv-task-check" aria-label="' + dv_esc(__("Выполнить")) + '"></button>').html(done ? dv_svg("check", 13) : "");
	if (!done) $chk.on("click", function () {
		$chk.prop("disabled", true);
		frappe.call({ method: "frappe.client.set_value", args: { doctype: "ToDo", name: t.name, fieldname: "status", value: "Closed" } })
			.then(function () { t.status = "Closed"; frappe.show_alert({ message: __("Задача выполнена"), indicator: "green" }); dv_paint_tasks($list); });
	});
	$row.append($chk);
	$row.append($('<span class="dv-task-t"></span>').text(dv_strip(t.description) || "—"));
	if (t.date && !done) {
		const over = t.date < frappe.datetime.get_today();
		let lbl; try { lbl = frappe.datetime.str_to_user(t.date).split(" ")[0]; } catch (e) { lbl = t.date; }
		$row.append($('<span class="dv-task-due' + (over ? " over" : "") + '"></span>').text(lbl));
	}
	const who = t.allocated_to || t.owner || "";
	if (who) $row.append($('<span class="dv-av dv-task-av"></span>').text(dv_initials(who)).css("background", dv_color(who)).attr("title", who));
	return $row;
}

// ── Заметки ──────────────────────────────────────────────────────────────
function dv_build_notes($left) {
	$left.append($('<button class="btn btn-sm btn-primary" style="margin-bottom:10px"></button>').html(dv_svg("message", 14) + " " + dv_esc(__("Добавить заметку"))).on("click", function () {
		frappe.prompt({ fieldname: "c", fieldtype: "Small Text", label: __("Заметка"), reqd: 1 }, function (v) {
			frappe.call({ method: "frappe.desk.form.utils.add_comment", args: { reference_doctype: DV.dt, reference_name: DV.doc.name, content: v.c, comment_email: frappe.session.user, comment_by: frappe.session.user_fullname || frappe.session.user } })
				.then(function () { frappe.show_alert({ message: __("Добавлено"), indicator: "green" }); deal_view_render(DV_PAGE); });
		}, __("Заметка к сделке"), __("Добавить"));
	}));
	if (!DV.comments.length) { $left.append('<div class="dv-stub">' + dv_esc(__("Заметок нет.")) + "</div>"); return; }
	DV.comments.forEach(function (c) {
		$left.append($('<div class="dv-note"></div>')
			.append($('<div class="dv-note-h"></div>').text((c.comment_by || c.owner || "") + " · " + dv_time(c.creation)))
			.append($('<div class="dv-note-b"></div>').text(dv_strip(c.content))));
	});
}

function inject_deal_view_styles() {
	if (document.getElementById("deal-view-styles")) return;
	const css = `
.dv-wrap{max-width:1040px;margin:0 auto}
.dv-empty,.dv-stub{color:var(--text-muted);font-size:13px;padding:24px 4px;line-height:1.7}
.dv-head{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.dv-av{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:14px;flex:none}
.dv-head-col{flex:1;min-width:0}
.dv-title-row{display:flex;align-items:center;gap:8px}
.dv-org{font-size:17px;font-weight:600;color:var(--text-color)}
.dv-pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600;line-height:1.5}
.dv-sub{font-size:12px;color:var(--text-muted);margin-top:2px}
.dv-btn,.dv-btn-sec{white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.dv-tabs{display:flex;gap:18px;border-bottom:1px solid var(--border-color);margin-bottom:14px}
.dv-tab{padding:8px 2px;font-size:13px;color:var(--text-muted);background:none;border:none;border-bottom:2px solid transparent;cursor:pointer}
.dv-tab.on{color:var(--text-color);border-bottom-color:var(--text-color)}
.dv-cols{display:flex;gap:18px;align-items:flex-start}
.dv-left{flex:1;min-width:0}
.dv-right{width:270px;flex:0 0 270px;background:var(--fg-color);border:1px solid var(--border-color);border-radius:12px;padding:14px 16px;position:sticky;top:12px}
.dv-det-title{font-size:13px;font-weight:600;color:var(--text-color);margin-bottom:8px}
.dv-row{display:grid;grid-template-columns:42% 1fr;gap:10px;align-items:baseline;padding:5px 0}
.dv-l{font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dv-v{font-size:13px;font-weight:500;color:var(--text-color);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dv-day{font-size:12px;color:var(--text-muted);margin:14px 0 8px 40px}
.dv-ev{display:flex;gap:12px}
.dv-ev:not(:last-child){padding-bottom:14px}
.dv-ev-rail{position:relative;width:28px;flex:none;display:flex;justify-content:center}
.dv-ev-rail:before{content:"";position:absolute;top:28px;bottom:-14px;width:2px;background:var(--border-color)}
.dv-ev:last-child .dv-ev-rail:before{display:none}
.dv-dot{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;z-index:1}
.dv-ev-body{flex:1;min-width:0;padding-top:4px}
.dv-ev-line{font-size:13px;color:var(--text-color);line-height:1.5}
.dv-ev-time{font-size:12px;color:var(--text-muted);margin-left:6px}
.dv-ev-snip{font-size:13px;color:var(--text-muted);line-height:1.6;margin-top:5px;background:var(--fg-color);border:1px solid var(--border-color);border-radius:10px;padding:8px 12px}
.dv-mail{background:var(--fg-color);border:1px solid var(--border-color);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.dv-mail-head{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.dv-mav{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:12px;flex:none}
.dv-mail-who{flex:1;min-width:0}
.dv-mail-name{font-size:14px;font-weight:600;color:var(--text-color)}
.dv-mail-addr{font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dv-mail-date{font-size:12px;color:var(--text-muted);white-space:nowrap}
.dv-mail-subj{font-size:13px;font-weight:600;color:var(--text-color);margin-bottom:8px}
.dv-body{font-size:13px;color:var(--text-color);line-height:1.65;overflow-x:auto}
.dv-body img{max-width:100% !important;height:auto !important}
.dv-body table{max-width:100% !important;border-collapse:collapse}
.dv-body *{max-width:100% !important}
.dv-body a{color:var(--primary)}
.dv-quote-toggle{display:inline-block;margin:8px 0 4px;padding:2px 10px;border-radius:20px;font-size:12px;color:var(--text-muted);background:var(--control-bg);border:1px solid var(--border-color);cursor:pointer}
.dv-chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--text-muted);background:var(--control-bg);border:1px solid var(--border-color);border-radius:20px;padding:3px 10px;margin-top:10px}
.dv-reply{background:var(--fg-color);border:1px solid var(--border-color);border-radius:12px;padding:12px 14px;margin-top:4px}
.dv-reply-title{font-size:12px;color:var(--text-muted);margin-bottom:8px}
.dv-task-add{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.dv-task-in{flex:1;height:34px;font-size:13px;padding:6px 10px;border-radius:8px;border:1px solid var(--border-color);background:var(--control-bg);color:var(--text-color)}
.dv-task-in:focus{outline:none;border-color:var(--primary)}
.dv-task-addbtn{white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.dv-grp{font-size:12px;color:var(--text-muted);margin:14px 0 4px}
.dv-task{display:flex;align-items:center;gap:10px;padding:8px 2px;border-bottom:1px solid var(--border-color)}
.dv-task-check{width:20px;height:20px;border-radius:50%;border:1.5px solid var(--border-color);background:none;cursor:pointer;flex:none;display:flex;align-items:center;justify-content:center;color:#fff;padding:0}
.dv-task.done .dv-task-check{background:var(--primary);border-color:var(--primary)}
.dv-task-t{font-size:13px;color:var(--text-color);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dv-task.done .dv-task-t{text-decoration:line-through;color:var(--text-muted)}
.dv-task-due{font-size:11px;padding:2px 8px;border-radius:20px;background:var(--control-bg);color:var(--text-muted);white-space:nowrap;flex:none}
.dv-task-due.over{background:#E5484D22;color:#E5484D}
.dv-task-av{width:22px;height:22px;font-size:10px;flex:none}
.dv-note{background:var(--fg-color);border:1px solid var(--border-color);border-radius:12px;padding:10px 14px;margin-bottom:10px}
.dv-note-h{font-size:12px;color:var(--text-muted);margin-bottom:4px}
.dv-note-b{font-size:13px;color:var(--text-color);line-height:1.6}
@media(max-width:900px){.dv-cols{flex-direction:column}.dv-right{width:100%;flex-basis:auto;position:static}}
`;
	$("<style id='deal-view-styles'></style>").text(css).appendTo(document.head);
}
