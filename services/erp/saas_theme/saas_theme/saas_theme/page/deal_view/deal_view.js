// Карточка сделки/лида — «красивая панель на грузовике». Отдельная Frappe-страница
// поверх РЕАЛЬНЫХ данных ERPNext (Opportunity/Lead + Communication), а не декор формы.
// Порт утверждённого прототипа. Тред писем = привязанные к записи ПЛЮС по адресу
// контакта (переписка всплывает, даже если формально не привязана). Цвета — desk-темы.
// Маркер сборки страницы: DEAL_VIEW_BUILD.
const DEAL_VIEW_BUILD = "dv1";

frappe.pages["deal_view"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Карточка сделки"), single_column: true });
	wrapper.__deal_page = page;
	inject_deal_view_styles();
	deal_view_render(page);
};

frappe.pages["deal_view"].on_page_show = function (wrapper) {
	const page = wrapper.__deal_page;
	if (page) deal_view_render(page);
};

// Поля правой панели (как в saas_theme kanban/details). Имена выверены по doctype.
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

function deal_view_initials(s) {
	s = (s || "").trim();
	if (!s) return "?";
	const p = s.split(/[\s@._-]+/).filter(Boolean);
	return ((p[0] ? p[0][0] : "") + (p[1] ? p[1][0] : "")).toUpperCase() || s[0].toUpperCase();
}
function deal_view_color(s) {
	let h = 0;
	for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
	return "hsl(" + h + ",42%,52%)";
}
function deal_view_esc(t) {
	return frappe.utils.escape_html(String(t == null ? "" : t));
}

function deal_view_render(page) {
	const route = frappe.get_route(); // ['deal_view', <doctype>, <name>]
	let dt = route[1] || "Opportunity";
	let name = route[2];
	// Совместимость: deal_view/<name> без доктайпа → по префиксу
	if (!name && route[1]) {
		name = route[1];
		dt = /LEAD/i.test(name) ? "Lead" : "Opportunity";
	}
	const $body = $(page.body);
	if (!name) {
		$body.html('<div class="dv-empty">' + deal_view_esc(__("Откройте сделку или лид из списка — или из формы кнопкой «Открыть карточку».")) + "</div>");
		return;
	}
	$body.html('<div class="dv-empty">' + deal_view_esc(__("Загрузка…")) + "</div>");

	frappe.call({ method: "frappe.client.get", args: { doctype: dt, name: name } }).then(function (r) {
		const doc = r && r.message;
		if (!doc) {
			$body.html('<div class="dv-empty">' + deal_view_esc(__("Запись не найдена")) + "</div>");
			return;
		}
		const isLead = dt === "Lead";
		const email = doc.contact_email || doc.email_id ||
			(/@/.test(doc.contact_display || "") ? doc.contact_display : "") || "";

		const or_filters = [["reference_name", "=", name]];
		if (email) {
			or_filters.push(["sender", "like", "%" + email + "%"]);
			or_filters.push(["recipients", "like", "%" + email + "%"]);
		}
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Communication",
				filters: { communication_type: "Communication" },
				or_filters: or_filters,
				fields: ["name", "sender", "sender_full_name", "recipients", "subject", "content",
					"communication_date", "sent_or_received", "has_attachment", "creation"],
				order_by: "communication_date asc, creation asc",
				limit_page_length: 50,
			},
		}).then(function (cr) {
			deal_view_paint(page, dt, doc, (cr && cr.message) || []);
		});
	});
}

function deal_view_paint(page, dt, doc, comms) {
	const isLead = dt === "Lead";
	const org = isLead ? (doc.company_name || doc.lead_name || doc.name) : (doc.customer_name || doc.party_name || doc.name);
	const amount = !isLead && doc.opportunity_amount ? format_currency(doc.opportunity_amount, doc.currency) : "";
	const status = doc.status || "";
	page.set_title(org);

	const $body = $(page.body).empty();
	const $wrap = $('<div class="dv-wrap"></div>').appendTo($body);

	// Шапка
	const scol = DEAL_VIEW_STATUS_COLOR[status] || "#8B95A5";
	const $head = $('<div class="dv-head"></div>');
	$head.append($('<div class="dv-av"></div>').text(deal_view_initials(org)).css("background", deal_view_color(org)));
	const $hc = $('<div class="dv-head-col"></div>');
	const $title = $('<div class="dv-title-row"></div>');
	$title.append($('<span class="dv-org"></span>').text(org));
	if (status) $title.append($('<span class="dv-pill"></span>').text(__(status)).css({ "background-color": scol + "22", color: scol }));
	$hc.append($title);
	$hc.append($('<div class="dv-sub"></div>').text(doc.name + (amount ? " · " + amount : "")));
	$head.append($hc);
	// Действие: Сделка → Создать КП; Лид → Открыть форму
	if (!isLead) {
		$head.append($('<button class="btn btn-sm btn-primary dv-btn"></button>').html('<i class="fa fa-file-text-o"></i> ' + __("Создать КП")).on("click", function () {
			frappe.call({ method: "erpnext.crm.doctype.opportunity.opportunity.make_quotation", args: { source_name: doc.name } })
				.then(function (r) { if (r.message) { frappe.model.sync(r.message); frappe.set_route("Form", "Quotation", r.message.name); } });
		}));
	}
	$head.append($('<button class="btn btn-sm dv-btn-sec"></button>').html('<i class="fa fa-pencil"></i> ' + __("Форма")).on("click", function () {
		frappe.set_route("Form", dt, doc.name);
	}));
	$wrap.append($head);

	// Вкладки
	const $tabs = $('<div class="dv-tabs"></div>');
	[["mail", "Письма"], ["act", "Активность"], ["task", "Задачи"], ["note", "Заметки"]].forEach(function (t, i) {
		$('<button class="dv-tab' + (i === 0 ? " on" : "") + '"></button>').text(__(t[1])).attr("data-t", t[0]).appendTo($tabs);
	});
	$wrap.append($tabs);

	// Тело: две колонки
	const $cols = $('<div class="dv-cols"></div>');
	const $left = $('<div class="dv-left"></div>');
	const $right = $('<div class="dv-right"></div>');
	$cols.append($left).append($right);
	$wrap.append($cols);

	// Левая — тред писем
	deal_view_thread($left, dt, doc, comms);

	// Правая — детали
	$right.append($('<div class="dv-det-title"></div>').text(__("Детали")));
	const list = DEAL_VIEW_FIELDS[dt] || [];
	if (amount) deal_view_row($right, "Сумма", amount);
	list.forEach(function (item) {
		let v = doc[item.fn];
		if ((v == null || v === "") && item.alt) v = doc[item.alt];
		if (v == null || v === "") return;
		let out = String(v);
		if (item.date) { try { out = frappe.datetime.str_to_user(v); } catch (e) {} }
		if (item.suffix) out = out + item.suffix;
		deal_view_row($right, item.label, out);
	});

	// Переключение вкладок
	const saved = $left.html();
	const stub = {
		act: "Хроника по сделке — письма, задачи, изменения статуса и комментарии в одной ленте (следующий шаг).",
		task: "Задачи по сделке (следующий шаг).",
		note: "Заметки менеджера (следующий шаг).",
	};
	$tabs.find(".dv-tab").on("click", function () {
		$tabs.find(".dv-tab").removeClass("on");
		$(this).addClass("on");
		const t = $(this).attr("data-t");
		if (t === "mail") { $left.html(saved); deal_view_bind_quotes($left); deal_view_bind_reply($left, dt, doc); }
		else $left.html('<div class="dv-stub">' + deal_view_esc(__(stub[t])) + "</div>");
	});
}

function deal_view_row($p, label, val) {
	$p.append($('<div class="dv-row"></div>')
		.append($('<div class="dv-l"></div>').text(__(label)))
		.append($('<div class="dv-v"></div>').text(val).attr("title", val)));
}

function deal_view_thread($left, dt, doc, comms) {
	if (!comms.length) {
		$left.append('<div class="dv-stub">' + deal_view_esc(__("Писем по этой записи пока нет. Напишите первое — оно появится здесь.")) + "</div>");
	}
	comms.forEach(function (c) {
		const outgoing = c.sent_or_received === "Sent";
		const who = outgoing ? (c.sender_full_name || "Мы") : (c.sender_full_name || c.sender || "");
		const $card = $('<div class="dv-mail"></div>');
		const $mh = $('<div class="dv-mail-head"></div>');
		$mh.append($('<div class="dv-mav"></div>').text(deal_view_initials(who)).css("background", deal_view_color(who)));
		const $mc = $('<div class="dv-mail-who"></div>');
		$mc.append($('<div class="dv-mail-name"></div>').text(who));
		$mc.append($('<div class="dv-mail-addr"></div>').text((c.sender || "") + " → " + (c.recipients || "")).attr("title", (c.sender || "") + " → " + (c.recipients || "")));
		$mh.append($mc);
		let when = "";
		try { when = frappe.datetime.str_to_user(c.communication_date || c.creation); } catch (e) {}
		$mh.append($('<div class="dv-mail-date"></div>').text(when));
		$card.append($mh);
		if (c.subject) $card.append($('<div class="dv-mail-subj"></div>').text(c.subject));
		const $b = $('<div class="dv-body"></div>').html(c.content || "");
		$card.append($b);
		if (c.has_attachment) $card.append('<span class="dv-chip"><i class="fa fa-paperclip"></i> ' + deal_view_esc(__("Вложение")) + "</span>");
		$left.append($card);
	});
	// Ответ
	const $rep = $('<div class="dv-reply"></div>');
	$rep.append($('<div class="dv-reply-title"></div>').text(__("Ответить")));
	$rep.append($('<button class="btn btn-sm btn-primary"></button>').html('<i class="fa fa-envelope-o"></i> ' + __("Написать письмо")));
	$left.append($rep);
	deal_view_bind_quotes($left);
	deal_view_bind_reply($left, dt, doc);
}

// Свернуть цитируемую историю (blockquote / gmail_quote) под «··· цитата»
function deal_view_bind_quotes($scope) {
	$scope.find(".dv-body").each(function () {
		const $b = $(this);
		const $q = $b.find("blockquote, .gmail_quote, .gmail_extra").first();
		if (!$q.length || $b.data("qbound")) return;
		$b.data("qbound", 1);
		$q.nextAll().addBack().hide();
		const $t = $('<button class="dv-quote-toggle">··· ' + deal_view_esc(__("цитата")) + "</button>");
		$t.on("click", function () { const on = $q.is(":visible"); $q.nextAll().addBack()[on ? "hide" : "show"](); });
		$q.before($t);
	});
}
function deal_view_bind_reply($scope, dt, doc) {
	$scope.find(".dv-reply .btn").off("click.dv").on("click.dv", function () {
		const email = doc.contact_email || doc.email_id || (/@/.test(doc.contact_display || "") ? doc.contact_display : "") || "";
		new frappe.views.CommunicationComposer({ doctype: dt, name: doc.name, recipients: email });
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
.dv-btn,.dv-btn-sec{white-space:nowrap}
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
@media(max-width:900px){.dv-cols{flex-direction:column}.dv-right{width:100%;flex-basis:auto;position:static}}
`;
	$("<style id='deal-view-styles'></style>").text(css).appendTo(document.head);
}
