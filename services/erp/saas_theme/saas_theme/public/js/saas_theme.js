/*
 * SaaS Theme - Horizontal Navigation
 *
 * Architecture:
 *   [Module Bar — top, dark] [Submenu Bar — sections] [Main Content — full width]
 *
 * Module bar: workspace icons from frappe.boot.desktop_icons.
 * Clicking a module switches the submenu bar to that workspace's items.
 * Original build_workspace_rail() preserved but not called — easy rollback.
 */

// Build marker — bump together with ?v=N in hooks.py; CI smoke-test greps for it.
const SAAS_THEME_BUILD = "v141";

// Apply persisted theme-mode immediately — prevents flash on page reload.
// Frappe uses data-theme-mode as source of truth; data-theme is derived from it.
(function () {
	var t = localStorage.getItem("st_theme_mode");
	if (t) {
		document.documentElement.setAttribute("data-theme-mode", t);
		document.documentElement.setAttribute("data-theme", t);
	}
})();

/* ============================================
   ПОЧТОВЫЙ СПИСОК (Communication) — аватары, прочитано, дата
   Через нативный frappe.listview_settings (форматтер темы письма). Один
   отправитель → стабильный цвет (HSL из адреса, не хардкод-hex). Непрочитанные
   жирным. Дата письма в строке. Задаём на загрузке скрипта (до рендера списка).
   ============================================ */
(function () {
	if (typeof frappe === "undefined" || !frappe.provide) return;
	frappe.provide("saas_theme");
	saas_theme.mail_avatar_color = function (s) {
		s = (s || "?").toLowerCase();
		let h = 0;
		for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
		return "hsl(" + h + ", 52%, 45%)"; // алгоритмический цвет, не новый hex
	};
	// "2026-06-13 11:05:29" → "13.06 11:05" (компактная абсолютная дата/время)
	saas_theme.short_datetime = function (s) {
		const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
		return m ? m[3] + "." + m[2] + " " + m[4] + ":" + m[5] : String(s || "");
	};

	// add_fields — чтобы seen/sender/communication_date попали в cur_list.data.
	// Визуал (аватар/жирный/дата) делаем JS-декорацией строк: инбокс НЕ применяет
	// formatters темы для своей колонки.
	frappe.listview_settings = frappe.listview_settings || {};
	const prev = frappe.listview_settings["Communication"] || {};
	const add = new Set([...(prev.add_fields || []), "seen", "sender", "sender_full_name", "communication_date"]);
	frappe.listview_settings["Communication"] = Object.assign({}, prev, { add_fields: [...add] });
})();

$(document).ready(function () {
	if (!frappe.boot.setup_complete) return;

	frappe.after_ajax(function () {
		saas_theme.sidebar.init();
		saas_theme.attachments.init();
		saas_theme.columns.init();
		saas_theme.list_controls.init();
	});

	// Re-init on sidebar_setup in case frappe.after_ajax fired too early
	$(document).on("sidebar_setup", function () {
		if (!saas_theme.sidebar.module_bar_built) {
			saas_theme.sidebar.init();
		}
		saas_theme.sidebar.setup_user_menu();
	});

	// Global "Отмена" button on every NEW document form — replaces the per-doctype
	// Client Scripts (previously only Lead/Opportunity). form-refresh fires with frm.
	// We use our OWN button next to Save (.st-cancel-btn) rather than the page's
	// secondary action: heavier forms (Quotation/BOM/PO) hide btn_secondary in a
	// later refresh cycle, but our standalone button persists. Deferred 50ms so it
	// lands after Frappe's header render.
	$(document).on("form-refresh", function (e, frm) {
		if (!frm || !frm.page || !frm.page.btn_primary) return;
		setTimeout(function () {
			const $primary = frm.page.btn_primary;
			if (!$primary || !$primary.length) return;
			const $actions = $primary.parent();
			const $existing = $actions.find(".st-cancel-btn");
			if (frm.is_new()) {
				if (!$existing.length) {
					const $btn = $('<button class="btn btn-secondary btn-default btn-sm st-cancel-btn">' + frappe.utils.escape_html(__("Отмена")) + "</button>");
					$btn.on("click", function () {
						frappe.set_route("List", frm.doctype);
					});
					$primary.before($btn);
				}
			} else {
				// Saved or existing doc → remove ours
				$existing.remove();
			}
		}, 50);
	});

	// Карточка письма для чтения: переоформляет родную форму Communication.
	// Классы слетают при перерисовке формы — переприменяем с ретраями.
	$(document).on("form-refresh", function (e, frm) {
		if (!frm || frm.doctype !== "Communication") return;
		[60, 300, 900].forEach(function (d) {
			setTimeout(function () { saas_theme.reshape_mail(frm); }, d);
		});
	});

	// Карточка сделки/лида: лента истории на видном месте + скрытие техн. вкладок.
	$(document).on("form-refresh", function (e, frm) {
		if (!frm || (frm.doctype !== "Opportunity" && frm.doctype !== "Lead")) return;
		[80, 350, 900].forEach(function (d) {
			setTimeout(function () { saas_theme.reshape_crm_card(frm); }, d);
		});
	});
});

frappe.provide("saas_theme");

// Карточка сделки/лида в стиле amo: лента истории (timeline) вынесена из вкладки
// «Операции» в всегда-видимый блок под формой; технические вкладки скрыты.
saas_theme.CRM_HIDDEN_TABS = ["activities_tab", "notes_tab", "dashboard_tab"];

saas_theme.reshape_crm_card = function (frm) {
	const $w = frm.$wrapper;

	// Маркер карточки CRM — для scoped-CSS (читаемость тёмной темы: подписи/лента).
	// Только лид/сделка, не задевает другие формы и Покупателя.
	$w.addClass("fp-crm-card");

	// 1. Лента истории: родной .new-timeline лежит внутри вкладки «Операции»
	//    (#<dt>-activities_tab). Переносим её узел в всегда-видимый блок под
	//    формой (.form-layout), чтобы менеджер видел хронику, не проваливаясь
	//    во вкладку. Перенос узла сохраняет обработчики timeline.
	const $timeline = $w.find(".new-timeline").first();
	const $layout = $w.find(".form-layout").first();
	if ($timeline.length && $layout.length) {
		let $feed = $layout.children(".fp-crm-feed").first();
		if (!$feed.length) {
			$feed = $('<div class="fp-crm-feed"><div class="fp-crm-feed-title">История по сделке</div></div>');
			$layout.append($feed);
		}
		if (!$feed[0].contains($timeline[0])) {
			$feed.append($timeline);
		}
		if (frm.doctype === "Lead") {
			$feed.find(".fp-crm-feed-title").text("История по лиду");
		}
	}

	// 2. Технические вкладки (Операции/Примечания/Соединения) — скрыть из UI
	//    (НЕ удаляя): шум для менеджера. Контакты и Реквизиты оставляем.
	//    Ленту уже вынесли выше, поэтому скрытие «Операции» её не прячет.
	saas_theme.CRM_HIDDEN_TABS.forEach(function (fn) {
		$w.find('.form-tabs .nav-item').has('[data-fieldname="' + fn + '"]').addClass("fp-hidden-tab");
	});
};

saas_theme.reshape_mail = function (frm) {
	if (!frm.fields_dict || !frm.fields_dict.content) return;
	const sec_of = (fn) =>
		frm.fields_dict[fn] && frm.fields_dict[fn].$wrapper
			? frm.fields_dict[fn].$wrapper.closest(".form-section")
			: $();

	// 1. Тема — read-only заголовок (без звёздочки обязательности)
	if (frm.fields_dict.subject) {
		frm.set_df_property("subject", "reqd", 0);
		frm.set_df_property("subject", "read_only", 1);
		sec_of("subject").addClass("st-mail-subject");
	}

	// 1b. Мета «от кого, когда» под темой (как в обычном почтовике).
	// ВАЖНО: форма переиспользуется между письмами — старую мету убираем и ставим
	// заново из ТЕКУЩЕГО frm.doc, иначе показывается отправитель/дата прошлого письма.
	const $subjSec = sec_of("subject");
	if ($subjSec.length) {
		$subjSec.find(".st-mail-meta").remove();
		const sender = frm.doc.sender_full_name || frm.doc.sender || "";
		const when = frm.doc.communication_date ? frappe.datetime.str_to_user(frm.doc.communication_date) : "";
		if (sender || when) {
			const esc = frappe.utils.escape_html;
			const parts = [];
			if (sender) parts.push('<span class="st-mail-meta-from">' + esc(sender) + "</span>");
			if (when) parts.push('<span class="st-mail-meta-when">' + esc(when) + "</span>");
			$subjSec.append('<div class="st-mail-meta">' + parts.join(' · ') + "</div>");
		}
	}

	// 1c. Акцент на кнопку «Ответить» (основное действие в карточке письма)
	frm.page.wrapper.find(".page-actions .btn").filter(function () {
		return $(this).text().trim() === "Ответить" || $(this).text().trim() === "Reply";
	}).addClass("st-mail-reply");

	// 1d. Отметить письмо прочитанным (seen=1) при открытии — чтобы в списке оно
	//     стало обычным (не жирным). Пишем в обход валидации (битые адреса).
	if (frm.doc && frm.doc.name && !frm.doc.seen && !frm._st_seen_marked) {
		frm._st_seen_marked = true;
		frappe.call({
			method: "saas_theme.api.mark_seen",
			args: { name: frm.doc.name },
			callback: function () { frm.doc.seen = 1; },
		});
	}

	// 2. Тело письма — обуздать ширину/картинки/пустоту (CSS по .st-mail-body)
	frm.fields_dict.content.$wrapper.addClass("st-mail-body");

	// 3. Скрыть служебные секции (НЕ удаляя поля): Статус, Доп. информация,
	//    Связи шкалы времени, Входящие эл. почты. «Ссылка» оставляем —
	//    через неё привязка письма к лиду.
	["text_content", "communication_date", "timeline_links", "message_id"].forEach((fn) => {
		sec_of(fn).addClass("st-mail-hide");
	});

	// 4. Блок классификации — оформить карточкой (позиция «после темы» задана
	//    порядком полей в доктайпе: custom_classifier_sb insert_after subject)
	const cls = frm.fields_dict.custom_claude_classification;
	if (cls) {
		cls.$wrapper.closest(".form-section").addClass("st-mail-classify");
	}

	// 5. Приглушить кнопку «Переподключить» (правка письма не нужна; Save
	//    оставляем для сохранения оценки)
	frm.page.wrapper.find(".btn:contains('Переподключить'), .btn:contains('Reconnect')").addClass("st-mail-hide");

	// 5b. Скрыть кнопку «Закрыть» (Close-действие Open→Closed): читается как
	//    «закрыть карточку», менеджер случайно меняет статус письма. Для нашего
	//    процесса (чтение + оценка) смена статуса не нужна. Точное совпадение
	//    текста, чтобы не зацепить другие кнопки. «Ответить»/«Действия»/«Создать»/
	//    «Сохранить» остаются.
	frm.page.wrapper.find(".custom-actions .btn, .page-actions .btn").filter(function () {
		const t = $(this).text().trim();
		return t === "Закрыть" || t === "Close";
	}).addClass("st-mail-hide");

	// 6. Длинные письма (рассылки из вложенных таблиц на тысячи px) — кламп
	//    высоты + кнопка «Показать полностью», чтобы не скроллить простыни.
	const $bodyWrap = frm.fields_dict.content.$wrapper;
	const ed = $bodyWrap.find(".ql-editor.read-mode")[0];
	if (ed && ed.scrollHeight > 760 && !$bodyWrap.next(".st-mail-expand").length) {
		$bodyWrap.addClass("st-mail-clampable st-mail-clamped");
		const $btn = $('<button type="button" class="btn btn-default btn-sm st-mail-expand">Показать письмо полностью ▾</button>');
		$btn.on("click", function () {
			$bodyWrap.toggleClass("st-mail-clamped");
			const clamped = $bodyWrap.hasClass("st-mail-clamped");
			$btn.html(clamped ? "Показать письмо полностью ▾" : "Свернуть письмо ▴");
		});
		$bodyWrap.after($btn);
	}
};

frappe.provide("saas_theme.sidebar");
frappe.provide("saas_theme.attachments");

saas_theme.sidebar = {
	rail_built: false,
	module_bar_built: false,

	init() {
		this.build_module_bar();
		this.setup_user_menu();
		if (!this._listeners_bound) {
			this.listen_for_changes();
			this._listeners_bound = true;
		}
		this.toggle_module_bar_visibility();
		// Frappe may re-render the header after load and drop our bar — rebuild
		[500, 1500, 3000].forEach((delay) => {
			setTimeout(() => this.build_module_bar(), delay);
		});
	},

	/* ============================================
	   HORIZONTAL MODULE BAR
	   ============================================ */

	build_module_bar() {
		// Frappe may re-render the header and remove our bar — check DOM, not just the flag
		if ($('.fp-module-bar').length) return;
		this.module_bar_built = false;

		// Insertion point: .main-section (body is a flex row — .navbar doesn't exist on desk pages)
		const $main = $('.main-section');
		if (!$main.length) return;

		const workspaces = this.get_workspaces();
		if (!workspaces.length) return;

		const items_html = workspaces.map(ws => {
			const icon = this.get_icon_for_workspace(ws);
			const label = frappe.utils.escape_html(__(ws.label));
			return `<div class="fp-module-item" data-workspace="${frappe.utils.escape_html(ws.label)}" title="${label}">
				<div class="st-rail-icon">${icon}</div>
				<span class="fp-module-label">${label}</span>
			</div>`;
		}).join('');

		const search_icon = frappe.utils.icon('es-line-search', 'sm', '', '', '', true);
		const notif_icon = frappe.utils.icon('es-line-notifications', 'sm', '', '', '', true);

		this.$module_bar = $(`
			<div class="fp-module-bar">
				<div class="fp-module-items">${items_html}</div>
				<div class="fp-module-bar-actions">
					<div class="fp-bar-action-icon fp-bar-search" title="Поиск">
						${search_icon}
					</div>
					<div class="fp-bar-action-icon fp-bar-notifications" title="Уведомления">
						${notif_icon}
					</div>
					<div class="fp-bar-action-icon fp-bar-theme" title="Сменить тему"></div>
				</div>
			</div>
		`);
		$main.prepend(this.$module_bar);
		this.update_theme_icon();

		const me = this;
		this.$module_bar.find('.fp-module-item').on('click', function() {
			const ws_name = $(this).data('workspace');
			me.switch_workspace(ws_name);
			me.update_module_bar_active();
			me.show_submenu(ws_name);
			// Навигация на сам воркспейс (дашборд модуля) — клик по модулю должен
			// вести в раздел, а не только переключать строку подменю.
			if (ws_name) frappe.set_route('Workspaces', ws_name);
		});

		this.$module_bar.find('.fp-bar-search').on('click', (e) => {
			e.stopPropagation();
			if (frappe.ui?.toolbar?.search?.show) {
				frappe.ui.toolbar.search.show();
			} else {
				$('#navbar-modal-search').trigger('click');
			}
		});

		this.$module_bar.find('.fp-bar-notifications').on('click', (e) => {
			e.stopPropagation();
			setTimeout(() => {
				$('.sidebar-notification .item-anchor').first().trigger('click');
				// The dropdown lives inside the hidden sidebar — move it to body so it's visible
				const $dd = $('.body-sidebar-container .dropdown-notifications').first();
				if ($dd.length) {
					$dd.addClass('fp-notifications-dropdown').appendTo('body');
				}
			}, 10);
		});

		this.$module_bar.find('.fp-bar-theme').on('click', (e) => {
			e.stopPropagation();
			this.toggle_theme();
			this.update_theme_icon();
		});

		// Flag only after the bar is actually in the DOM
		this.module_bar_built = $('.fp-module-bar').length > 0;
		this.update_module_bar_active();

		const current_ws = this.resolve_workspace(frappe.app.sidebar?.sidebar_title);
		if (current_ws && current_ws !== 'Desk') this.show_submenu(current_ws);
	},

	update_theme_icon() {
		const is_dark = document.documentElement.getAttribute("data-theme-mode") === "dark";
		// moon = switch to dark (shown in light theme), sun = switch to light
		const icon = frappe.utils.icon(is_dark ? "sun" : "moon", "sm", "", "", "", true);
		$(".fp-bar-theme").html(icon);
	},

	// Communication (инбокс List/Communication И форма письма Form/Communication)
	// держим в контексте CRM — там пункт «Электронная почта»; подменю CRM не
	// должно пропадать/подменяться воркспейсом «Email».
	is_email_inbox_route() {
		const r = frappe.get_route() || [];
		return r[1] === 'Communication';
	},

	resolve_workspace(ws) {
		if (this.is_email_inbox_route()) return 'CRM';
		return ws;
	},

	update_module_bar_active() {
		const current = (this.resolve_workspace(frappe.app.sidebar?.sidebar_title) || '').toLowerCase();
		const me = this;
		$('.fp-module-item').each(function () {
			const label = $(this).data('workspace') || '';
			const isActive = label.toLowerCase() === current;
			$(this).toggleClass('active', isActive);
			const $icon = $(this).find('.st-rail-icon svg, .st-rail-icon .icon');
			if (isActive) {
				// Per-module colour (same palette as the old left rail)
				const color = me.get_workspace_color(label);
				this.style.setProperty('background', color + '2e', 'important'); // ~18% tint
				this.style.setProperty('--fp-active-color', color); // used by ::after underline
				$icon.css({ color: color, stroke: color });
			} else {
				this.style.removeProperty('background');
				this.style.removeProperty('--fp-active-color');
				$icon.css({ color: '', stroke: '' });
			}
		});
	},

	toggle_module_bar_visibility() {
		if (!this.$module_bar) return;
		const page = frappe.container?.page?.page;
		if (page?.hide_sidebar) {
			this.$module_bar.hide();
			$('.fp-submenu-bar').hide();
		} else {
			this.$module_bar.show();
			$('.fp-submenu-bar').show();
		}
	},

	get_route_for_item(item) {
		// Синтетические пункты (например «Электронная почта») несут готовый маршрут
		if (item.custom_route) return item.custom_route;
		if (!item.link_to && !item.url) return null;
		switch (item.link_type) {
			// Сделка открывается канбаном по умолчанию (доска «Продажи» по этапам).
			// Список остаётся доступен переключателем представлений на самой доске.
			case 'DocType':
				if (item.link_to === 'Opportunity') {
					return ['List', 'Opportunity', 'Kanban', 'Продажи'];
				}
				return ['List', item.link_to];
			// Workspace pages live at slugified routes: "Frappe CRM" → /desk/frappe-crm
			case 'Workspace': return [frappe.router.slug(item.link_to)];
			case 'Page': return [item.link_to];
			case 'Dashboard': return ['dashboard-view', item.link_to];
			case 'Report': return ['query-report', item.link_to];
			default: return item.link_to ? [item.link_to] : null;
		}
	},

	get_sidebar_items_for(workspace_name) {
		// Structure: wsi[label.toLowerCase()].items — flat array.
		// child: 0 = top-level link or section header (link_to may be null)
		// child: 1 = child of preceding section header
		const wsi = frappe.boot.workspace_sidebar_item || {};
		const key = (workspace_name || '').toLowerCase();
		const ws_data = wsi[key] || {};
		const raw = ws_data.items || [];

		const result = [];
		let current_section = null;

		for (const item of raw) {
			if (item.type === 'Card Break' || item.type === 'Section Break') continue;
			if (item.child === 1) {
				// Sub-item — attach to current section
				if (current_section) {
					current_section.children.push(item);
				}
			} else {
				// Top-level
				if (!item.link_to && item.link_type !== 'URL') {
					// Section header with children
					current_section = { ...item, children: [] };
					result.push(current_section);
				} else {
					current_section = null;
					result.push(item);
				}
			}
		}
		// Filter out section headers with no children and no link
		const filtered = result.filter(i => i.link_to || i.url || (i.children && i.children.length));

		// Внедряем «Электронная почта» в CRM — между «Главная» (idx 0) и остальными,
		// маршрут на штатный инбокс Communication.
		if (key === 'crm') {
			const email_item = {
				label: 'Электронная почта',
				custom_route: ['List', 'Communication', 'Inbox'],
			};
			const pos = filtered.length ? 1 : 0; // после «Главная», если она есть
			filtered.splice(pos, 0, email_item);
		}
		return filtered;
	},

	show_submenu(workspace_name) {
		$('.fp-submenu-bar').remove();
		$('.fp-submenu-dropdown').remove();

		const items = this.get_sidebar_items_for(workspace_name);
		if (!items.length) return;

		const me = this;
		const items_html = items.map((item, idx) => {
			const label = frappe.utils.escape_html(__(item.label || ''));
			if (item.children && item.children.length) {
				return `<span class="fp-submenu-item fp-has-dropdown" data-idx="${idx}">${label} <span class="fp-submenu-arrow">▾</span></span>`;
			}
			// Items without a buildable route are not rendered at all
			const route = me.get_route_for_item(item);
			if (!route) return '';
			const route_str = frappe.utils.escape_html(route.join('/'));
			return `<a class="fp-submenu-item" data-idx="${idx}" data-route="${route_str}" href="#">${label}</a>`;
		}).join('');

		const $submenu = $(`<div class="fp-submenu-bar">${items_html}</div>`);
		this.$module_bar.after($submenu);

		$submenu.find('.fp-submenu-item:not(.fp-has-dropdown)').on('click', function(e) {
			e.preventDefault();
			const item = items[$(this).data('idx')];
			const route = me.get_route_for_item(item);
			if (route) frappe.set_route(...route);
		});

		$submenu.find('.fp-has-dropdown').on('click', function(e) {
			e.stopPropagation();
			const idx = $(this).data('idx');
			me.toggle_submenu_dropdown($(this), items[idx].children);
		});

		if (!this._dropdown_close_bound) {
			$(document).on('click.fp_dropdown', () => $('.fp-submenu-dropdown').remove());
			this._dropdown_close_bound = true;
		}

		this.update_submenu_active();
	},

	toggle_submenu_dropdown($trigger, children) {
		const existing = $('.fp-submenu-dropdown');
		const was_open = parseInt(existing.data('trigger-idx')) === parseInt($trigger.data('idx'));
		existing.remove();
		if (was_open) return;

		const me = this;
		// Only routable children
		children = children.filter(c => me.get_route_for_item(c));
		if (!children.length) return;
		const items_html = children.map(child => {
			const label = frappe.utils.escape_html(__(child.label || ''));
			return `<a class="fp-dropdown-item" href="#">${label}</a>`;
		}).join('');

		const $dropdown = $(`<div class="fp-submenu-dropdown" data-trigger-idx="${$trigger.data('idx')}">${items_html}</div>`);
		$('body').append($dropdown);

		const rect = $trigger[0].getBoundingClientRect();
		$dropdown.css({ top: rect.bottom + 2, left: rect.left });

		$dropdown.find('.fp-dropdown-item').each(function(i) {
			$(this).on('click', function(e) {
				e.preventDefault();
				const route = me.get_route_for_item(children[i]);
				if (route) frappe.set_route(...route);
				$dropdown.remove();
			});
		});
	},

	update_submenu_active() {
		// Exact match or prefix match only — includes() gives false positives
		// ("lead" is inside "lead-source") and matches everything for empty routes
		const current = frappe.get_route_str() || '';
		$('.fp-submenu-item').each(function() {
			const route = String($(this).attr('data-route') || '');
			const is_active = route.length > 0 && (
				current === route ||
				current.startsWith(route + '/')
			);
			$(this).toggleClass('active', is_active);
		});
	},

	/* ============================================
	   WORKSPACE RAIL (preserved for easy rollback — not called)
	   ============================================ */

	WORKSPACE_COLORS: {
		"crm":            "#6366F1",
		"selling":        "#3B82F6",
		"buying":         "#F59E0B",
		"stock":          "#10B981",
		"manufacturing":  "#EF4444",
		"hr":             "#8B5CF6",
		"human":          "#8B5CF6",
		"projects":       "#06B6D4",
		"accounting":     "#EC4899",
		"assets":         "#F97316",
		"support":        "#14B8A6",
		"retail":         "#F43F5E",
		"quality":        "#84CC16",
	},

	get_workspace_color(label) {
		const key = (label || "").toLowerCase();
		for (const [word, color] of Object.entries(this.WORKSPACE_COLORS)) {
			if (key.includes(word)) return color;
		}
		const palette = ["#6366F1","#3B82F6","#10B981","#F59E0B","#EF4444","#8B5CF6","#06B6D4","#EC4899"];
		return palette[key.charCodeAt(0) % palette.length];
	},

	build_workspace_rail() {
		if (this.rail_built) return;

		const workspaces = this.get_workspaces();
		if (!workspaces.length) return;

		let icons_html = "";
		workspaces.forEach((ws) => {
			const icon_content = this.get_icon_for_workspace(ws);
			const escaped_label = frappe.utils.escape_html(ws.label);
			const color = this.get_workspace_color(ws.label);
			icons_html += `
				<div class="st-rail-item"
					data-workspace="${escaped_label}"
					data-color="${color}">
					<div class="st-rail-icon">
						${icon_content}
					</div>
					<span class="st-rail-tooltip">${escaped_label}</span>
				</div>`;
		});

		this.$rail = $(`
			<div class="st-workspace-rail">
				<div class="st-rail-top">
					${icons_html}
				</div>
				<div class="st-rail-bottom">
					<div class="st-rail-item st-theme-toggle" title="Сменить тему">
						<div class="st-rail-icon"></div>
					</div>
				</div>
			</div>
		`);

		$(".body-sidebar-container").before(this.$rail);

		// Цвета иконок
		this.$rail.find(".st-rail-item[data-color]").each(function () {
			const color = $(this).data("color");
			$(this).find("svg, .icon").css({ color, stroke: color });
			$(this).find(".st-rail-initials").css({ color });
		});

		// Клик — переключение workspace
		this.$rail.find(".st-rail-item[data-workspace]").on("click", function () {
			const ws_name = $(this).data("workspace");
			saas_theme.sidebar.switch_workspace(ws_name);
		});

		// Тултипы
		this.$rail.find(".st-rail-tooltip").each(function () {
			$(this).appendTo("body");
		});

		this.$rail.find(".st-rail-item").on("mouseenter", function () {
			const label = $(this).data("workspace");
			if (!label) return;
			const $tip = $("body > .st-rail-tooltip").filter(function () {
				return $(this).text().trim() === label;
			});
			if (!$tip.length) return;
			const rect = this.getBoundingClientRect();
			$tip.css({
				top: rect.top + rect.height / 2 - $tip.outerHeight() / 2,
				left: rect.right + 10,
			}).addClass("visible");
		}).on("mouseleave", function () {
			$("body > .st-rail-tooltip").removeClass("visible");
		});

		// Кнопка темы
		const theme_icon = frappe.utils.icon("es-line-darkmode", "md", "", "", "", true);
		this.$rail.find(".st-theme-toggle .st-rail-icon").html(theme_icon);
		this.$rail.find(".st-theme-toggle").on("click", () => this.toggle_theme());

		this.rail_built = true;
		this.update_rail_active();
		this.inject_rail_bottom_icons();
	},

	toggle_theme() {
		const current = document.documentElement.getAttribute("data-theme-mode") || "light";
		const next = current === "dark" ? "light" : "dark";
		document.documentElement.setAttribute("data-theme-mode", next);
		// Let Frappe derive and apply data-theme from data-theme-mode
		frappe.ui.set_theme();
		localStorage.setItem("st_theme_mode", next);
		// Persist to user profile — survives page reload
		frappe.xcall("frappe.core.doctype.user.user.switch_theme", {
			theme: next === "dark" ? "Dark" : "Light",
		});
	},

	get_workspaces() {
		const icons = frappe.boot.desktop_icons || [];
		const sidebar_items = frappe.boot.workspace_sidebar_item || {};

		return icons.filter((icon) => {
			return (
				icon.hidden !== 1 &&
				icon.link_type === "Workspace Sidebar" &&
				sidebar_items[icon.label.toLowerCase()]
			);
		});
	},

	get_icon_for_workspace(ws) {
		const sidebar_data = frappe.boot.workspace_sidebar_item[ws.label.toLowerCase()];
		if (sidebar_data && sidebar_data.header_icon) {
			return frappe.utils.icon(sidebar_data.header_icon, "md", "", "", "", true);
		}
		const letter = ws.label.charAt(0).toUpperCase();
		return `<span class="st-rail-initials">${letter}</span>`;
	},

	switch_workspace(workspace_name) {
		if (!workspace_name) return;
		frappe.app.sidebar.setup(workspace_name);
		this.update_module_bar_active();
	},

	update_rail_active() {
		const current = (frappe.app.sidebar.sidebar_title || "").toLowerCase();

		$(".st-rail-item[data-workspace]").removeClass("active").css({ background: "", "box-shadow": "" });

		$(".st-rail-item[data-workspace]").each(function () {
			const ws = $(this).data("workspace");
			if (!ws || ws.toLowerCase() !== current) return;

			const color = $(this).data("color") || "#3B82F6";
			$(this).addClass("active").css({
				background: color + "22",
				"box-shadow": `inset 3px 0 0 ${color}`,
			});
			$(this).find("svg, .icon").css({ color, stroke: color, opacity: 1 });
			$(this).find(".st-rail-initials").css({ color });
		});
	},

	toggle_rail_visibility() {
		if (!this.$rail) return;

		const sidebar_visible = $(".body-sidebar-container").is(":visible");
		const page = frappe.container?.page?.page;
		const hide = page?.hide_sidebar;

		if (sidebar_visible && !hide) {
			this.$rail.show();
			$("body").addClass("st-dual-sidebar");
		} else {
			this.$rail.hide();
			$("body").removeClass("st-dual-sidebar");
		}
	},

	ensure_sidebar_content() {
		const $top = $(".body-sidebar .body-sidebar-top");
		if (!$top.length) return;

		const has_items = $top.find(".standard-sidebar-item").length > 0;
		if (has_items) return;

		const route = frappe.get_route();
		if (!route || !route.length) return;

		const entity = route.length >= 2 ? route[1] : route[0];
		if (!entity || !frappe.app.sidebar) return;

		const sidebars = frappe.app.sidebar.get_workspace_sidebars
			? frappe.app.sidebar.get_workspace_sidebars(entity)
			: [];

		if (sidebars.length) {
			frappe.app.sidebar.setup(sidebars[0]);
		} else if (frappe.app.sidebar.sidebar_title) {
			frappe.app.sidebar.setup(frappe.app.sidebar.sidebar_title);
		}
	},

	/* ============================================
	   HIDE SIDEBAR DUPLICATES (Search / Notifications)
	   Frappe renders search as .navbar-search-bar and
	   notifications as .sidebar-notification inside .standard-items-sections.
	   ============================================ */

	hide_sidebar_duplicates() {
		// Hide search item — Frappe adds class "navbar-search-bar" to it
		$(".body-sidebar .navbar-search-bar").closest("li, .standard-sidebar-item").hide();
		// Hide notifications item — Frappe wraps it in .sidebar-notification
		$(".body-sidebar .sidebar-notification").hide();
	},

	/* ============================================
	   RAIL BOTTOM ICONS (Search + Notifications)
	   Injected into .st-rail-bottom by saas_theme.js itself.
	   ============================================ */

	inject_rail_bottom_icons() {
		if (!this.$rail) return;
		const $bottom = this.$rail.find(".st-rail-bottom");
		if (!$bottom.length || $bottom.find(".fp-rail-search").length) return;

		const $theme = $bottom.find(".st-theme-toggle");

		const $search = $(`
			<div class="fp-rail-icon fp-rail-search st-rail-item" title="Поиск (Ctrl+K)">
				<div class="st-rail-icon">${frappe.utils.icon("es-line-search", "md", "", "", "", true)}</div>
			</div>
		`);
		$search.on("click", () => {
			// frappe.ui.toolbar.search — SearchDialog instance created in toolbar.js
			if (frappe.ui?.toolbar?.search?.show) {
				frappe.ui.toolbar.search.show();
			} else {
				$("#navbar-modal-search").click();
			}
		});

		const $notif = $(`
			<div class="fp-rail-icon fp-rail-notifications st-rail-item" title="Уведомления">
				<div class="st-rail-icon">${frappe.utils.icon("es-line-notifications", "md", "", "", "", true)}</div>
			</div>
		`);
		$notif.on("click", (e) => {
			// stopPropagation prevents Frappe's document click handler from closing the dropdown immediately
			e.stopPropagation();
			setTimeout(() => {
				$(".sidebar-notification .item-anchor").first().trigger("click");
			}, 10);
		});

		if ($theme.length) {
			$search.insertBefore($theme);
			$notif.insertBefore($theme);
		} else {
			$bottom.append($search).append($notif);
		}
	},

	listen_for_changes() {
		const me = this;

		$(document).on("sidebar_setup", () => {
			setTimeout(() => {
				me.build_module_bar();
				me.update_module_bar_active();
				me.toggle_module_bar_visibility();
				const ws = me.resolve_workspace(frappe.app?.sidebar?.sidebar_title);
				if (ws && ws !== 'Desk') me.show_submenu(ws);
			}, 50);
		});

		$(document).on("page-change", () => {
			setTimeout(() => {
				me.build_module_bar();
				me.update_module_bar_active();
				me.toggle_module_bar_visibility();
				// На маршруте инбокса Frappe мог подставить подменю «Email» —
				// принудительно держим CRM-контекст.
				if (me.is_email_inbox_route()) {
					me.show_submenu('CRM');
				}
				me.update_submenu_active();
				$('.fp-submenu-dropdown').remove();
			}, 100);
		});

		$(document).on("form-refresh", () => {
			setTimeout(() => {
				me.toggle_module_bar_visibility();
			}, 200);
		});
	},

	/* ============================================
	   USER MENU
	   ============================================ */

	setup_user_menu() {
		const $sidebar = $(".body-sidebar");
		const $user_btn = $sidebar.find(
			".dropdown-navbar-user .sidebar-user-button"
		);

		if (!$user_btn.length) return;

		$user_btn.removeAttr("onclick");
		$user_btn.off("click");

		$user_btn.on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.toggle_user_menu();
		});

		if (!this._user_menu_doc_bound) {
			$(document).on("click.saas_user_menu", (e) => {
				if (
					!$(e.target).closest(".saas-user-menu").length &&
					!$(e.target).closest(".dropdown-navbar-user").length
				) {
					this.close_user_menu();
				}
			});
			this._user_menu_doc_bound = true;
		}
	},

	toggle_user_menu() {
		if ($(".saas-user-menu").length) {
			$(".saas-user-menu").remove();
			return;
		}
		this.show_user_menu();
	},

	close_user_menu() {
		$(".saas-user-menu").remove();
	},

	show_user_menu() {
		const user_fullname = frappe.session.user_fullname;
		const user_email = frappe.session.user_email;
		const user_avatar = frappe.avatar(frappe.session.user, "avatar-large");
		const version = frappe.boot.versions?.frappe
			? `v${frappe.boot.versions.frappe}`
			: "";

		const menu_items = [
			{ label: __("Integrations"), icon: "folder", href: "/app/installed-applications" },
			{ label: __("History"), icon: "clock", href: "/app/activity-log" },
			{ label: __("Upgrade to Pro"), star: true, action: "upgrade" },
			{ highlight: true, label: __("Update App"), action: "update" },
			{ divider: true },
			{ label: __("Logout"), icon: "logout", action: "logout" },
		];

		let items_html = "";
		menu_items.forEach((item) => {
			if (item.divider) {
				items_html += '<div class="saas-user-menu-divider"></div>';
			} else if (item.highlight) {
				items_html += `
					<a class="saas-user-menu-item highlight"
						${item.href ? `href="${item.href}"` : ""}
						data-action="${item.action || ""}">
						<span class="saas-menu-dot"></span>
						<span>${item.label}</span>
					</a>`;
			} else {
				items_html += `
					<a class="saas-user-menu-item"
						${item.href ? `href="${item.href}"` : ""}
						data-action="${item.action || ""}">
						${item.icon ? `<span class="saas-menu-icon">${frappe.utils.icon(item.icon, "sm")}</span>` : ""}
						${item.star ? '<span class="saas-menu-star">&#9734;</span>' : ""}
						<span>${item.label}</span>
					</a>`;
			}
		});

		const $menu = $(`
			<div class="saas-user-menu">
				<div class="saas-user-menu-header">
					<div class="saas-user-menu-avatar">${user_avatar}</div>
					<div class="saas-user-menu-info">
						<div class="saas-user-menu-name">${user_fullname}</div>
						<div class="saas-user-menu-email">${user_email}</div>
					</div>
				</div>
				<div class="saas-user-menu-divider"></div>
				<div class="saas-user-menu-items">${items_html}</div>
				${version ? `<div class="saas-user-menu-footer">${version} &middot; Terms &amp; Conditions</div>` : ""}
			</div>
		`);

		$(".body-sidebar").append($menu);

		$menu.find(".saas-user-menu-item").on("click", function (e) {
			const action = $(this).data("action");
			if (action) {
				e.preventDefault();
				saas_theme.sidebar.handle_menu_action(action);
				saas_theme.sidebar.close_user_menu();
			}
		});
	},

	handle_menu_action(action) {
		switch (action) {
			case "logout":
				frappe.app.logout();
				break;
			case "upgrade":
				frappe.msgprint(__("Upgrade to Pro is not available yet."));
				break;
			case "update":
				frappe.msgprint(__("App is up to date."));
				break;
		}
	},
};

/* ============================================
   ATTACHMENT ENHANCEMENTS
   ============================================ */

/* ============================================
   LIST CONTROLS — unified Filters and Sort buttons (МойСклад style)

   Recon (Frappe v16, live server, /desk/work-order):
   - cur_list.view_name === 'List'
   - filter_area: .get() → [[doctype, field, op, value]], .filter_button ($),
     .filter_x_button ($). Native popover (.filter-popover) already contains
     per-filter remove, "+ Add a Filter" and "Clear Filters" — we keep it as
     the panel and only relabel the button + hide the dangerous X.
   - sort_selector: .args.options [{fieldname, label}], .sort_by, .sort_order,
     .set_value(by, order) updates state WITHOUT refreshing; .onchange(by, order)
     triggers the list refresh. Native DOM: .sort-selector > .btn-group
     (.btn-order + .sort-selector-button).
   Source of truth stays in Frappe — this layer only changes presentation.
   ============================================ */

frappe.provide("saas_theme.list_controls");

saas_theme.list_controls = {
	init() {
		if (this._bound) return;
		this._bound = true;
		const me = this;
		$(document).on("page-change", () => {
			[200, 600, 1500].forEach((d) => setTimeout(() => me.try_render(), d));
		});
		$(document).on("click.st_sort_menu", (e) => {
			if (!$(e.target).closest(".st-sort-menu, .st-sort-button").length) {
				$(".st-sort-menu").remove();
			}
		});
		[300, 900, 2000].forEach((d) => setTimeout(() => me.try_render(), d));
	},

	get_list_view() {
		const lv = window.cur_list;
		// Standard lists И инбокс почты (Inbox — подкласс ListView с
		// filter_area/sort_selector/$filter_section). НЕ reports/kanban/calendar.
		// Раньше гейт был только "List" → причёсанные контролы (фильтры/сортировка
		// + скрытие крестика) не доезжали до инбокса (разнобой с лидом).
		// + Kanban: у него есть filter_area/$filter_section (но нет sort_selector —
		//   setup_sort_button безопасно выходит). Так кнопка «Фильтры • N» и
		//   скрытие крестика доезжают и до доски сделок (единый вид с лидом).
		if (!lv || !["List", "Inbox", "Kanban"].includes(lv.view_name)) return null;
		if (!lv.$filter_section || !lv.$filter_section.length) return null;
		// КРИТИЧНО: на форме cur_list остаётся стале-списком (не очищается). Без
		// этой проверки list_controls (особенно compact_header_buttons) протекал
		// на форму письма и превращал кнопки «Ответить/Действия/Создать» в
		// иконки-закладки. Работаем только когда активная страница — список.
		if (!frappe.get_route || frappe.get_route()[0] !== "List") return null;
		return lv;
	},

	try_render() {
		const lv = this.get_list_view();
		if (lv) {
			this.setup_filter_button(lv);
			this.setup_sort_button(lv);
			this.compact_header_buttons(lv);
		}
		// Инбокс: чинить плохой дефолт сортировки (по классификации → дата письма)
		this.fix_inbox_sort(window.cur_list);
		// Фильтр по полкам нужен и на инбоксе (view_name === 'Inbox', не 'List')
		this.setup_shelf_filter(window.cur_list);
		// Папки-вкладки Входящие/Отправленные (только инбокс Communication)
		this.setup_folder_tabs(window.cur_list);
		// Чистка лишних кнопок инбокса (переключатель представлений, родная
		// выпадашка папок, закладка сохранения фильтра)
		this.cleanup_inbox_buttons(window.cur_list);
		// Аватары/прочитано/дата в строках инбокса (JS-декорация + наблюдатель)
		this.decorate_inbox_rows(window.cur_list);
		// Канбан сделок: аватар/статус-чип/метрики/чистые значения (JS-декорация)
		this.decorate_kanban_cards(window.cur_list);
		// Скрыть лишние стандартные фильтры-строки (per-doctype)
		this.hide_standard_filters(window.cur_list);
		// Скрыть глючное «Представление отчёта» из меню (CRM-списки)
		this.hide_report_view(window.cur_list);
	},

	/* ----- Скрыть лишние стандартные фильтры-строки (per-doctype) -----
	   Шум: ID, тип/медиум коммуникации, и т.п. Оставляем только осмысленные
	   (KEEP). Скрываем из UI (display:none), фильтрация не ломается. Полки
	   классификации и папки — отдельные бары, их не трогаем.                  */
	STANDARD_FILTER_KEEP: {
		Lead: ["status", "company_name"],
		Opportunity: ["status", "party_name"],
		Communication: ["subject"],
	},

	hide_standard_filters(lv) {
		if (!lv || !lv.page || !lv.page.wrapper) return;
		// Скоуп — обёртка АКТИВНОГО списка (lv.page.wrapper). В SPA DOM неактивных
		// списков остаётся (напр. фильтры инбокса при переходе на лид) — глобальный
		// поиск цеплял чужие поля и скрывал нужные. Плюс сбрасываем прошлые
		// пометки перед применением — иначе при смене доктайпа поля не возвращались.
		const $scope = $(lv.page.wrapper);
		$scope.find(".st-hide-std-filter").removeClass("st-hide-std-filter");
		const keep = this.STANDARD_FILTER_KEEP[lv.doctype];
		if (!keep) return;
		$scope.find(".standard-filter-section .form-group.frappe-control[data-fieldname]").each(function () {
			const fn = $(this).attr("data-fieldname");
			if (fn && keep.indexOf(fn) === -1) {
				$(this).addClass("st-hide-std-filter");
			}
		});
	},

	/* ----- Аватары / прочитано / дата в строках инбокса (Задачи 3-5) -----
	   Инбокс не применяет formatters темы, поэтому декорируем строки в DOM:
	   буквенный аватар (HSL из адреса), непрочитанные жирным (seen), дата письма.
	   MutationObserver переисполняет декор при перерисовке строк (фильтр/скролл). */
	// Имя отправителя: sender_full_name; если нет/=email — локальная часть адреса
	// (а НЕ весь email — иначе дубль с колонкой «Почта»).
	mail_display_name(sender, full) {
		sender = (sender || "").trim();
		let nm = (full || "").trim();
		if (!nm || nm.toLowerCase() === sender.toLowerCase()) {
			const lp = (sender.split("@")[0] || sender || "?").replace(/[._\-]+/g, " ").trim();
			nm = lp ? lp.charAt(0).toUpperCase() + lp.slice(1) : "?";
		}
		return nm;
	},

	// Переименовать заголовок колонки списка, сохранив иконку сортировки
	set_col_header($head, colClass, label) {
		const $c = $head.find(".list-row-col." + colClass).first();
		if (!$c.length || $c.attr("data-st-relabel") === label) return;
		let done = false;
		$c.contents().each(function () {
			if (this.nodeType === 3 && this.textContent.trim()) { this.textContent = label; done = true; return false; }
		});
		if (!done) {
			const $sp = $c.find("span").filter(function () { return $(this).text().trim(); }).first();
			if ($sp.length) $sp.text(label); else $c.text(label);
		}
		$c.attr("data-st-relabel", label);
	},

	decorate_inbox_rows(lv) {
		if (!lv || lv.doctype !== "Communication" || lv.view_name !== "Inbox") return;
		if (!lv.page || !lv.page.wrapper) return;
		const me = this;
		const byName = {};
		(lv.data || []).forEach((d) => (byName[d.name] = d));

		// Инбокс грузит свой набор полей без sender_full_name — подтягиваем его одним
		// запросом, иначе имя всегда падает в fallback (локальная часть адреса).
		const need = (lv.data || []).filter((d) => d.sender_full_name === undefined).map((d) => d.name);
		if (need.length && !lv._st_names_loading) {
			lv._st_names_loading = true;
			frappe.call({
				method: "frappe.client.get_list",
				args: { doctype: "Communication", filters: [["name", "in", need]], fields: ["name", "sender_full_name"], limit_page_length: 0 },
				callback: (r) => {
					lv._st_names_loading = false;
					const m = {};
					(r.message || []).forEach((x) => (m[x.name] = x.sender_full_name || ""));
					(lv.data || []).forEach((d) => { if (d.sender_full_name === undefined) d.sender_full_name = m[d.name] || ""; });
					me.decorate_inbox_rows(lv);
				},
			});
		}

		$(lv.page.wrapper).find(".list-row-container").each(function () {
			const $r = $(this);
			if ($r.find(".list-row-head").length) return; // шапка списка
			const $subj = $r.find(".list-subject");
			if (!$subj.length) return;
			const name = $r.find("[data-name]").attr("data-name");
			const doc = byName[name];
			if (!doc) return;
			const sender = (doc.sender || "").trim();
			const fullname = me.mail_display_name(sender, doc.sender_full_name);
			// уже декорирована — обновим только имя (после подгрузки sender_full_name)
			if ($subj.find(".st-mail-avatar").length) {
				$subj.find(".st-mail-sender").text(fullname).attr("title", sender);
				return;
			}
			const initial = (fullname.replace(/[^\p{L}\p{N}]/u, "")[0] || fullname[0] || "?").toUpperCase();
			const $av = $('<span class="st-mail-avatar"></span>')
				.css("background", saas_theme.mail_avatar_color(sender))
				.text(initial)
				.attr("title", sender);
			// имя отправителя — отдельный «столбец» текста (не только аватар)
			const $from = $('<span class="st-mail-sender"></span>').text(fullname).attr("title", sender);
			// блок: [точка] аватар  имя отправителя. Точка ВСЕГДА занимает место
			// (у прочитанных прозрачная) — чтобы столбцы не съезжали по строкам.
			const $block = $('<span class="st-mail-rowhead"></span>');
			const $dot = $('<span class="st-mail-dot"></span>');
			if (!doc.seen) $dot.addClass("st-mail-dot-on").attr("title", "Непрочитано");
			$block.append($dot).append($av).append($from);
			// после чекбокса/«звезды», перед текстом темы
			const $anchor = $subj.find(".level-item").first();
			if ($anchor.length) $anchor.after($block);
			else $subj.prepend($block);

			if (!doc.seen) $subj.addClass("st-mail-unseen");
			else $subj.addClass("st-mail-seen");

			// Дата — отдельный правый столбец: нативный .frappe-timestamp («1 д»
			// относительный) делаем абсолютным коротким (13.06 11:05) и снимаем
			// класс, чтобы Frappe не перекрашивал обратно в относительный.
			const $ts = $r.find(".frappe-timestamp");
			if ($ts.length) {
				const raw = $ts.attr("data-timestamp") || doc.communication_date;
				if (raw) {
					$ts.text(saas_theme.short_datetime(raw)).removeClass("frappe-timestamp").addClass("st-mail-rowdate");
				}
			}
		});

		// Заголовки колонок под содержимое: «Тема»→«Отправитель / тема», «С»→«Почта»
		const $head = $(lv.page.wrapper).find(".list-row-head");
		this.set_col_header($head, "list-subject", __("Отправитель / тема"));
		this.set_col_header($head, "sender", __("Почта"));

		// Наблюдатель — переисполнить декор после перерисовки строк (один раз на список)
		if (!lv._st_rows_observed) {
			const target = lv.$result && lv.$result.length ? lv.$result[0] : null;
			if (target) {
				lv._st_rows_observed = true;
				const obs = new MutationObserver(() => {
					clearTimeout(lv._st_rows_t);
					lv._st_rows_t = setTimeout(() => me.decorate_inbox_rows(lv), 150);
				});
				obs.observe(target, { childList: true, subtree: true });
			}
		}
	},

	decorate_kanban_cards(lv) {
		// Только наш канбан сделок (Opportunity/Kanban). Меняем ТОЛЬКО внутренности
		// карточки — сам draggable-элемент и data-name не трогаем (драг-дроп цел).
		if (!lv || lv.view_name !== "Kanban" || lv.doctype !== "Opportunity") return;
		if (!lv.page || !lv.page.wrapper) return;
		const me = this;
		$(lv.page.wrapper).find(".kanban-card-wrapper").each(function () {
			const $wrapper = $(this);
			const $card = $wrapper.find(".kanban-card").first();
			if (!$card.length || $card.hasClass("st-kb-done")) return;
			try {
			const $titleArea = $card.find(".kanban-title-area").first();
			const $doc = $card.find(".kanban-card-doc").first();
			const $link = $titleArea.find("> a").first();
			const title = ($card.find(".kanban-card-title").text() || "").trim();
			if (!title || !$titleArea.length) return;

			// Аватар: инициалы организации (до 2 слов) + стабильный HSL-цвет.
			const initials =
				title.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
			const $av = $('<span class="st-kb-avatar"></span>')
				.css("background", saas_theme.mail_avatar_color(title))
				.text(initials);

			// Разбор «Подпись: значение» → чистые значения по типу поля (до шапки —
			// контакт нужен для подстроки под организацией).
			const f = {};
			$doc.find(".text-truncate").each(function () {
				const raw = ($(this).text() || "").trim();
				const i = raw.indexOf(":");
				const label = i >= 0 ? raw.slice(0, i) : "";
				const val = (i >= 0 ? raw.slice(i + 1) : raw).trim();
				if (/контакт|contact/i.test(label)) f.contact = val;
				else if (/категор/i.test(label)) f.category = val;
				else if (/об[ъь]?[её]м/i.test(label)) f.volume = val;
				else if (/сумм/i.test(label)) f.amount = val;
				else if (/дат/i.test(label)) f.date = val;
			});

			// Шапка: [аватар] [организация + контакт (2 строки)] [чип-статуса].
			const $namecol = $('<div class="st-kb-namecol"></div>');
			if ($link.length) $namecol.append($link);
			else $namecol.append($('<span class="kanban-card-title"></span>').text(title));
			if (f.contact) $namecol.append($('<div class="st-kb-contact"></div>').text(f.contact).attr("title", f.contact));
			const $head = $('<div class="st-kb-head"></div>').append($av).append($namecol);
			const $col = $wrapper.closest(".kanban-column");
			let status = ($col.attr("data-column-value") || "").trim();
			if (!status) status = ($col.find("[title]").first().attr("title") || "").trim();
			if (status) {
				const st = __(status); // перевод статуса (Open→Открыта и т.п.) из залитых переводов
				$head.append($('<span class="st-kb-chip"></span>').text(st).attr("title", st));
			}
			$titleArea.prepend($head);

			// Пересобираем тело: тег категории + метрики (без серых чипов и подписей).
			$doc.empty();
			if (f.category) $doc.append($('<div class="st-kb-tag"></div>').text(f.category));
			if (f.volume || f.amount) {
				const $m = $('<div class="st-kb-metrics"></div>');
				if (f.volume)
					$m.append(
						$('<div class="st-kb-metric"><div class="st-kb-metric-l">Объём</div></div>').append(
							$('<div class="st-kb-metric-v"></div>').text((f.volume || "0") + " т")
						)
					);
				if (f.amount)
					$m.append(
						$('<div class="st-kb-metric"><div class="st-kb-metric-l">Сумма</div></div>').append(
							$('<div class="st-kb-metric-v"></div>').text(
								(function (s) {
									const n = parseFloat((s || "").replace(/[^\d,.-]/g, "").replace(",", "."));
									if (isNaN(n)) return s;
									if (n >= 1e6) return (n / 1e6).toFixed(2).replace(".", ",") + " млн ₽";
									if (n >= 1e3) return Math.round(n / 1e3) + " тыс ₽";
									return n.toLocaleString("ru-RU") + " ₽";
								})(f.amount)
							)
						)
					);
				$doc.append($m);
			}

			// Подвал: дата (относительная) + быстрые действия (письмо / задача / комментарий).
			const $meta = $card.find(".kanban-card-meta").first();
			if ($meta.length) {
				$meta.find(".st-kb-date, .st-kb-actions").remove();
				if (f.date) {
					// Поле modified иногда приходит HTML-ом frappe-timestamp
					// (<span data-timestamp="2026-07-05 10:22:00" ...>6 часов назад</span>),
					// иногда абсолютом «05-07-2026 10:22:50». Приводим к «N назад».
					let dtxt = String(f.date);
					const cw = (iso) => {
						try {
							return frappe.datetime && frappe.datetime.comment_when ? frappe.datetime.comment_when(iso) : null;
						} catch (e2) {
							return null;
						}
					};
					const tsm = dtxt.match(/data-timestamp="([^"]+)"/); // ISO из HTML frappe-timestamp
					const dm = dtxt.match(/(\d{2})[-.](\d{2})[-.](\d{4})[ T](\d{2}):(\d{2})/); // DD-MM-YYYY абсолют
					if (tsm) {
						dtxt = cw(tsm[1]) || dtxt.replace(/<[^>]+>/g, "").trim();
					} else if (dm) {
						const iso = dm[3] + "-" + dm[2] + "-" + dm[1] + " " + dm[4] + ":" + dm[5] + ":00";
						dtxt = cw(iso) || dm[1] + "." + dm[2] + " " + dm[4] + ":" + dm[5];
					} else {
						dtxt = dtxt.replace(/<[^>]+>/g, "").trim(); // на всякий — снять любые теги
					}
					$meta.append($('<span class="st-kb-date"></span>').text(dtxt));
				}
				let dealname = "";
				try { dealname = decodeURIComponent($wrapper.attr("data-name") || ""); } catch (ex) {}
				const rcpt = /@/.test(f.contact || "") ? f.contact : "";
				// Инлайн-SVG — не зависим от имён иконок Frappe (в спрайте нет mail/todo/check).
				const SVG_MAIL =
					'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>';
				const SVG_TASK =
					'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-5"/></svg>';
				const SVG_COMMENT =
					'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/></svg>';
				const mkAct = (svg, label, fn) =>
					$('<span class="st-kb-act" role="button" tabindex="0"></span>')
						.attr("title", label)
						.html(svg)
						.on("click", function (ev) {
							ev.stopPropagation();
							ev.preventDefault();
							fn();
						});
				const $acts = $('<span class="st-kb-actions"></span>');
				if (dealname) {
					$acts.append(
						mkAct(SVG_MAIL, "Написать письмо", () =>
							new frappe.views.CommunicationComposer({ doctype: "Opportunity", name: dealname, recipients: rcpt })
						)
					);
					$acts.append(
						mkAct(SVG_TASK, "Задача-напоминание", () =>
							frappe.new_doc("ToDo", { reference_type: "Opportunity", reference_name: dealname })
						)
					);
					$acts.append(
						mkAct(SVG_COMMENT, "Добавить комментарий", () =>
							frappe.prompt(
								{ fieldname: "c", fieldtype: "Small Text", label: __("Комментарий"), reqd: 1 },
								(v) =>
									frappe.call({
										method: "frappe.desk.form.utils.add_comment",
										args: {
											reference_doctype: "Opportunity",
											reference_name: dealname,
											content: v.c,
											comment_email: frappe.session.user,
											comment_by: frappe.session.user_fullname || frappe.session.user,
										},
										callback: () =>
											frappe.show_alert({ message: __("Комментарий добавлен"), indicator: "green" }),
									}),
								__("Комментарий к сделке"),
								__("Добавить")
							)
						)
					);
				}
				$meta.append($acts);
			}

			$card.addClass("st-kb-done");
			} catch (e) {
				$card.addClass("st-kb-done"); // при ошибке всё равно показать карточку (не прятать анти-FOUC-ом)
			}
		});

		// Наблюдатель — перерисовать декор после ре-рендера канбана (один раз на список).
		if (!lv._st_kb_observed) {
			const target = lv.$result && lv.$result.length ? lv.$result[0] : null;
			if (target) {
				lv._st_kb_observed = true;
				const obs = new MutationObserver(() => {
					clearTimeout(lv._st_kb_t);
					lv._st_kb_t = setTimeout(() => me.decorate_kanban_cards(lv), 150);
				});
				obs.observe(target, { childList: true, subtree: true });
			}
		}
	},

	/* ----- Чистка лишних кнопок инбокса (Задача 6) -----
	   Переключатель представлений (не нужен в инбоксе), родная выпадашка папок
	   (её заменяют наши вкладки-папки), закладка «Сохранённые фильтры» (для
	   фильтра есть кнопка «Фильтры»). Скрываем из UI, механику не трогаем.
	   Полки классификации и наши папки-вкладки НЕ затрагиваются.               */
	cleanup_inbox_buttons(lv) {
		if (!lv || lv.doctype !== "Communication" || lv.view_name !== "Inbox") return;
		if (!lv.page || !lv.page.wrapper) return;
		const $pa = $(lv.page.wrapper).find(".page-actions");
		// Переключатель представлений — имеет .custom-btn-group-label (иконки списка)
		$pa.find(".btn.ellipsis").has(".custom-btn-group-label").addClass("st-hide-inbox-btn");
		// Выпадашка папок и «Сохранённые фильтры» — по тексту
		$pa.find(".btn.ellipsis").each(function () {
			const t = $(this).text().trim();
			if (/Сохранённые фильтр|Saved Filter|Выберите|Select Inbox|Новый почтовый/.test(t)) {
				$(this).addClass("st-hide-inbox-btn");
			}
		});
	},

	/* ----- Папки-вкладки инбокса (нативный механизм Frappe) -----
	   Папка инбокса = route[3] (email_account / "Sent" / "Spam" / "Trash");
	   фильтры (sent_or_received / email_status) Frappe печёт сам в
	   get_inbox_filters(). Поэтому переключаем папки РОУТИНГОМ, а не своим
	   фильтром поверх (раньше так Отправленные не работали — родной фильтр
	   "Received" перебивал). «Черновиков» у Communication нет — пропускаем.
	   Полки классификации (что это) — отдельный бар, сосуществуют.            */
	FOLDERS: [
		{ label: "Входящие",     folder: "__account__" },
		{ label: "Отправленные", folder: "Sent" },
		{ label: "Спам",         folder: "Spam" },
		{ label: "Корзина",      folder: "Trash" },
	],

	get_inbox_account() {
		// Реальный почтовый ящик (а не виртуальные Sent/Spam/Trash/All Accounts)
		const acc = (frappe.boot.email_accounts || []).find((a) => a.email_id !== "All Accounts");
		return acc ? acc.email_account : "All Accounts";
	},

	setup_folder_tabs(lv) {
		if (!lv || lv.doctype !== "Communication" || lv.view_name !== "Inbox") return;
		if (!lv.$filter_section || !lv.$filter_section.length) return;
		const $pf = lv.$filter_section.closest(".page-form");
		if (!$pf.length || $pf.prev(".st-folder-tabs").length) return;

		const account = this.get_inbox_account();
		const current = frappe.get_route()[3]; // текущая папка
		const resolve = (f) => (f === "__account__" ? account : f);

		const tabs = this.FOLDERS.map((f) => {
			const target = resolve(f.folder);
			return `<button type="button" class="st-folder-tab" data-folder="${frappe.utils.escape_html(target)}">${frappe.utils.escape_html(f.label)}</button>`;
		}).join("");
		const $bar = $(`<div class="st-folder-tabs">${tabs}</div>`);
		$pf.before($bar);

		$bar.find(".st-folder-tab").on("click", function () {
			const folder = $(this).data("folder");
			frappe.set_route("List", "Communication", "Inbox", folder);
		});

		// Активная папка = текущий route[3] (любой реальный аккаунт ⇒ Входящие)
		const isFolder = ["Sent", "Spam", "Trash"].includes(current);
		const activeTarget = isFolder ? current : account;
		$bar.find(`.st-folder-tab[data-folder="${activeTarget}"]`).addClass("active");
	},

	/* ----- Скрыть пункт «Представление отчёта» из меню «...» -----
	   На отчётном представлении ломается возврат/маршрут (как было с «Главной»);
	   менеджеру оно не нужно. Скрываем из UI только на CRM-списках. Пункт меню
	   не имеет data-атрибута — матчим по тексту (перевод проекта стабилен).     */
	REPORT_VIEW_LABELS: ["Представление отчёта", "Report View"],

	hide_report_view(lv) {
		if (!lv || (lv.doctype !== "Opportunity" && lv.doctype !== "Lead")) return;
		const labels = this.REPORT_VIEW_LABELS;
		$(".menu-btn-group .dropdown-menu a.dropdown-item, .page-actions .dropdown-menu a.dropdown-item").each(function () {
			const t = $(this).text().trim();
			if (labels.indexOf(t) !== -1) {
				$(this).closest("li, .dropdown-item").addClass("fp-hidden-menu-item");
				$(this).addClass("fp-hidden-menu-item");
			}
		});
	},

	/* ----- Быстрый фильтр по полкам классификации (только Communication) ----- */

	SHELVES: [
		{ label: "Все",             value: "",                 color: "" },
		{ label: "Новая заявка",    value: "Новая заявка",     color: "#10B981" },
		{ label: "Вопрос по заказу", value: "Вопрос по заказу", color: "#3B82F6" },
		{ label: "Поставщик",       value: "Поставщик",        color: "#F59E0B" },
		{ label: "Спам",            value: "Спам",             color: "#EF4444" },
		{ label: "Прочее",          value: "Прочее",           color: "#8B949E" },
	],

	setup_shelf_filter(lv) {
		if (!lv || lv.doctype !== "Communication") return;
		if (!lv.$filter_section || !lv.$filter_section.length || !lv.filter_area) return;
		// поле классификации существует?
		const has_field = frappe.meta.has_field("Communication", "custom_claude_classification");
		if (!has_field) return;
		const $pf = lv.$filter_section.closest(".page-form");
		if ($pf.next(".st-shelf-filter").length) return;

		const me = this;
		const chips = this.SHELVES.map((s) => {
			const dot = s.color ? `<span class="st-shelf-dot" style="background:${s.color}"></span>` : "";
			return `<button type="button" class="st-shelf-chip" data-shelf="${frappe.utils.escape_html(s.value)}">${dot}${frappe.utils.escape_html(s.label)}</button>`;
		}).join("");
		const $bar = $(`<div class="st-shelf-filter">${chips}</div>`);
		lv.$filter_section.closest(".page-form").after($bar);

		$bar.find(".st-shelf-chip").on("click", function () {
			const shelf = $(this).data("shelf");
			$bar.find(".st-shelf-chip").removeClass("active");
			$(this).addClass("active");
			lv.filter_area.remove("custom_claude_classification");
			if (shelf) {
				lv.filter_area.add([["Communication", "custom_claude_classification", "=", shelf]]);
			} else {
				lv.refresh();
			}
		});
		// «Все» активна по умолчанию
		$bar.find('.st-shelf-chip[data-shelf=""]').addClass("active");
	},

	/* ----- Compact secondary header buttons to icons ----- */

	compact_header_buttons(lv) {
		// Скоуп — страница активного списка (lv.page.wrapper). Глобальный
		// $(".btn.ellipsis") калечил кнопки формы письма (Ответить/Действия/
		// Создать тоже .btn.ellipsis) — оборачивал текст и вешал закладку-иконку.
		const $scope = lv && lv.page && lv.page.wrapper ? $(lv.page.wrapper) : $(document);
		// "Представление списка" — text lives in .custom-btn-group-label, hide via CSS.
		// Just tag the button and add a tooltip.
		$scope.find(".btn.ellipsis").each(function () {
			const $btn = $(this);
			const $label = $btn.find(".custom-btn-group-label");
			if ($label.length && !$btn.hasClass("st-lc-iconbtn")) {
				$btn.addClass("st-lc-iconbtn").attr("title", $label.text().trim());
			}
		});

		// "Сохранённые фильтры" — text is a bare text node, no icon. Wrap text in a
		// hideable span and prepend a bookmark icon (once).
		$scope.find(".btn.ellipsis").each(function () {
			const $btn = $(this);
			if ($btn.find(".custom-btn-group-label").length) return; // that's the list-view btn
			if ($btn.hasClass("st-lc-saved")) return;
			// Find the bare text node holding the label
			const node = Array.from(this.childNodes).find(
				(n) => n.nodeType === 3 && n.textContent.trim().length
			);
			if (!node) return;
			const text = node.textContent.trim();
			$(node).replaceWith(`<span class="st-lc-saved-label">${frappe.utils.escape_html(text)}</span>`);
			const icon = frappe.utils.icon("bookmark", "sm", "", "", "", true);
			$btn.prepend(`<span class="st-lc-saved-icon">${icon}</span>`);
			$btn.addClass("st-lc-iconbtn st-lc-saved").attr("title", text);
		});
	},

	/* ----- Filters: relabel native button, hide only the X ----- */

	setup_filter_button(lv) {
		const fa = lv.filter_area;
		if (!fa || !fa.filter_button || !fa.filter_button.length) return;

		this.update_filter_label(lv);

		const btn = fa.filter_button[0];
		if (!btn._st_observed) {
			btn._st_observed = true;
			// Frappe rewrites the label on filter changes — re-apply ours
			const mo = new MutationObserver(() => this.update_filter_label(lv));
			mo.observe(btn, { childList: true, characterData: true, subtree: true });
		}

		// Hide the dangerous clear-all X only after our label is in place
		// (clear-all stays available inside the native popover)
		lv.$filter_section.addClass("st-lc-filters");
	},

	update_filter_label(lv) {
		const fa = lv.filter_area;
		const $label = fa.filter_button.find(".button-label");
		if (!$label.length) return;
		const n = (fa.get() || []).length;
		const text = n ? `Фильтры • ${n}` : "Фильтры";
		// Guard against MutationObserver loops — only touch DOM on change
		if ($label.text() !== text) $label.text(text);
		if (!fa.filter_button.find(".st-lc-caret").length) {
			fa.filter_button.append('<span class="st-lc-caret">▾</span>');
		}
	},

	/* ----- Sort: one combined button with custom menu ----- */

	setup_sort_button(lv) {
		const ss = lv.sort_selector;
		if (!ss || !ss.wrapper || !ss.wrapper.length) return;
		if (ss.wrapper.find(".st-sort-button").length) {
			this.update_sort_label(lv);
			return;
		}

		const $btn = $('<button type="button" class="btn btn-default btn-sm st-sort-button"></button>');
		ss.wrapper.append($btn);
		const me = this;
		$btn.on("click", (e) => {
			e.stopPropagation();
			me.toggle_sort_menu(lv, $btn);
		});

		this.update_sort_label(lv);
		// Graceful fallback: hide native pair only after ours rendered
		if (ss.wrapper.find(".st-sort-button").length) {
			ss.wrapper.addClass("st-lc-sort");
		}
	},

	// Понятные подписи для полей, которых нет в дропдауне сортировки
	SORT_LABELS: { communication_date: "Дата письма" },

	get_sort_label(lv) {
		const ss = lv.sort_selector;
		if (this.SORT_LABELS[ss.sort_by]) return this.SORT_LABELS[ss.sort_by];
		const opt = (ss.args.options || []).find((o) => o.fieldname === ss.sort_by);
		return opt ? __(opt.label) : ss.sort_by;
	},

	/* ----- Инбокс: дефолт сортировки по дате письма (новые сверху) -----
	   Дефолт «съехал» на custom_claude_classification (группировал по классам) —
	   менеджеру нужна хроника: новые письма сверху. communication_date нет в
	   дропдауне, но сортировать по нему можно. Чиним только этот плохой случай
	   (другие сортировки пользователя не трогаем). apply_sort персистит выбор.   */
	// Технические дефолты сортировки — для них принудительно дата письма.
	// «Контентные» поля (subject/sender/status…) пользователь выбирает сам — не трогаем.
	INBOX_SORT_DEFAULTS: ["custom_claude_classification", "creation", "modified", "name", "idx"],

	fix_inbox_sort(lv) {
		if (!lv || lv.doctype !== "Communication" || lv.view_name !== "Inbox") return;
		const ss = lv.sort_selector;
		if (!ss) return;
		if (this.INBOX_SORT_DEFAULTS.includes(ss.sort_by)) {
			this.apply_sort(lv, "communication_date", "desc");
		}
	},

	update_sort_label(lv) {
		const ss = lv.sort_selector;
		const $btn = ss.wrapper.find(".st-sort-button");
		if (!$btn.length) return;
		const arrow = ss.sort_order === "asc" ? "↑" : "↓";
		$btn.html(
			`<span class="st-sort-field">${frappe.utils.escape_html(this.get_sort_label(lv))}</span>` +
			` <span class="st-sort-arrow">${arrow}</span><span class="st-lc-caret">▾</span>`
		);
	},

	apply_sort(lv, sort_by, sort_order) {
		const ss = lv.sort_selector;
		ss.set_value(sort_by, sort_order);
		// set_value updates state only — onchange triggers the actual refresh
		if (typeof ss.onchange === "function") ss.onchange(sort_by, sort_order);
		this.update_sort_label(lv);
	},

	toggle_sort_menu(lv, $btn) {
		const existing = $(".st-sort-menu");
		if (existing.length) {
			existing.remove();
			return;
		}

		const ss = lv.sort_selector;
		const me = this;
		const options_html = (ss.args.options || []).map((o) => {
			const check = o.fieldname === ss.sort_by ? '<span class="st-sort-check">✓</span>' : "";
			return `<a class="st-sort-item" data-field="${frappe.utils.escape_html(o.fieldname)}" href="#">
				${frappe.utils.escape_html(__(o.label))}${check}
			</a>`;
		}).join("");

		const dir_arrow = ss.sort_order === "asc" ? "↑" : "↓";
		const dir_title = ss.sort_order === "asc" ? "По возрастанию — нажмите для убывания" : "По убыванию — нажмите для возрастания";
		const $menu = $(`
			<div class="st-sort-menu">
				<div class="st-sort-menu-title">
					<span>Сортировать по:</span>
					<button type="button" class="st-sort-dir-toggle" title="${dir_title}">${dir_arrow}</button>
				</div>
				${options_html}
			</div>
		`);
		$("body").append($menu);

		const rect = $btn[0].getBoundingClientRect();
		const menu_w = $menu.outerWidth() || 220;
		const left = Math.max(8, Math.min(rect.left, window.innerWidth - menu_w - 8));
		$menu.css({ top: rect.bottom + 4, left });

		$menu.find(".st-sort-item").on("click", function (e) {
			e.preventDefault();
			me.apply_sort(lv, $(this).data("field"), lv.sort_selector.sort_order);
			$menu.remove();
		});

		// Direction toggle: flips order, keeps the menu open, updates its own arrow
		$menu.find(".st-sort-dir-toggle").on("click", function (e) {
			e.stopPropagation();
			const next = lv.sort_selector.sort_order === "asc" ? "desc" : "asc";
			me.apply_sort(lv, lv.sort_selector.sort_by, next);
			$(this).text(next === "asc" ? "↑" : "↓");
		});
	},
};

saas_theme.attachments = {
	ext_map: {
		pdf:  { label: "PDF",  cls: "st-pdf" },
		doc:  { label: "DOC",  cls: "st-doc" },
		docx: { label: "DOC",  cls: "st-doc" },
		xls:  { label: "XLS",  cls: "st-xls" },
		xlsx: { label: "XLS",  cls: "st-xls" },
		csv:  { label: "CSV",  cls: "st-xls" },
		png:  { label: "PNG",  cls: "st-img" },
		jpg:  { label: "JPG",  cls: "st-img" },
		jpeg: { label: "JPG",  cls: "st-img" },
		gif:  { label: "GIF",  cls: "st-img" },
		svg:  { label: "SVG",  cls: "st-img" },
		webp: { label: "IMG",  cls: "st-img" },
		zip:  { label: "ZIP",  cls: "st-zip" },
		gz:   { label: "GZ",   cls: "st-zip" },
		rar:  { label: "RAR",  cls: "st-zip" },
		"7z": { label: "7Z",   cls: "st-zip" },
		js:   { label: "JS",   cls: "st-code" },
		py:   { label: "PY",   cls: "st-code" },
		json: { label: "JSON", cls: "st-code" },
		html: { label: "HTML", cls: "st-code" },
		css:  { label: "CSS",  cls: "st-code" },
		txt:  { label: "TXT",  cls: "st-file" },
		ppt:  { label: "PPT",  cls: "st-doc" },
		pptx: { label: "PPT",  cls: "st-doc" },
	},

	init() {
		this.listen();
	},

	get_file_info(filename) {
		if (!filename) return { label: "FILE", cls: "st-file" };
		const ext = filename.split(".").pop().toLowerCase();
		return this.ext_map[ext] || { label: ext.substring(0, 4).toUpperCase(), cls: "st-file" };
	},

	enhance_all() {
		const me = this;
		$(".form-sidebar .attachment-row:not(.st-enhanced)").each(function () {
			me.enhance_row($(this));
		});
	},

	enhance_row($row) {
		const $pill = $row.find(".data-pill");
		if (!$pill.length) return;

		const $label_link = $pill.find(".attachment-file-label");
		if (!$label_link.length) return;

		$row.addClass("st-enhanced");

		const file_url = $label_link.attr("href") || "";
		const filename = $label_link.attr("title") || $label_link.text().trim();
		const file_info = this.get_file_info(filename);

		const $lock_icon = $pill.find(".attachment-icon");
		const lock_use = $lock_icon.find("use");
		const lock_href_attr = lock_use.length ? lock_use.attr("href") : "";
		const is_private = lock_href_attr === "#es-line-lock";
		const lock_href = $lock_icon.attr("href") || "";

		const $remove = $pill.find(".remove-btn").clone(true);
		const escaped_name = frappe.utils.escape_html(filename);
		const escaped_url = frappe.utils.escape_html(file_url);

		$pill.empty().addClass("st-attach-card").append(`
			<div class="st-file-icon ${file_info.cls}">${file_info.label}</div>
			<div class="st-attach-details">
				<a class="st-attach-name" href="${escaped_url}" target="_blank" title="${escaped_name}">${escaped_name}</a>
				<span class="st-attach-lock">
					<a href="${frappe.utils.escape_html(lock_href)}" style="color:inherit;text-decoration:none">${is_private ? "Private" : "Public"}</a>
				</span>
			</div>
		`);
		if ($remove.length) {
			$pill.append($remove);
		}
	},

	listen() {
		const me = this;
		const debounced = frappe.utils.debounce(() => me.enhance_all(), 150);

		$(document).on("form-refresh", () => setTimeout(debounced, 300));
		$(document).on("page-change", () => setTimeout(debounced, 500));

		const observer = new MutationObserver(debounced);
		observer.observe(document.body, { childList: true, subtree: true });
	},
};

/* ============================================================
   RESIZABLE LIST COLUMNS
   Drag the handle on column headers to resize.
   Widths are saved to localStorage per DocType.
   ============================================================ */
frappe.provide("saas_theme.columns");

saas_theme.columns = {
	init() {
		this._attach_with_retries();

		$(document).on("page-change", () => this._attach_with_retries());
		frappe.router.on("change", () => this._attach_with_retries());
	},

	_attach_with_retries() {
		// Multiple retries — ListView renders asynchronously
		[300, 800, 1500, 3000, 5000].forEach((delay) => {
			setTimeout(() => this.try_attach(), delay);
		});
	},

	try_attach() {
		const $header = $(".list-row-head .list-header-subject");
		if (!$header.length) return;

		const $cols = $header.find(".list-row-col");
		if (!$cols.length) return;

		// Already attached — skip unless header was re-rendered
		if ($header.find(".st-col-resizer").length) return;

		const doctype = frappe.get_route && frappe.get_route()[1];
		if (!doctype) return;

		this._restore_widths($cols, doctype);
		$cols.each((i, col) => this._bind_drag($(col), i, doctype));
	},

	_storage_key(doctype) {
		return `st_col_w__${doctype}`;
	},

	_restore_widths($cols, doctype) {
		const saved = this._load(doctype);
		if (!saved) return;

		$cols.each((i, col) => {
			const w = saved[i];
			if (!w) return;
			$(col).css({ flex: "none", width: w + "px", "min-width": w + "px" });
			$(`.list-row .list-row-col:nth-child(${i + 1})`)
				.css({ flex: "none", width: w + "px", "min-width": w + "px" });
		});
	},

	_bind_drag($col, index, doctype) {
		const $handle = $('<div class="st-col-resizer"></div>');
		$col.css("position", "relative").append($handle);

		let startX, startW;

		$handle.on("mousedown", (e) => {
			e.preventDefault();
			startX = e.clientX;
			startW = $col.outerWidth();

			$(document).on("mousemove.st_col", (e) => {
				const w = Math.max(60, startW + e.clientX - startX);
				$col.css({ flex: "none", width: w + "px", "min-width": w + "px" });
				$(`.list-row .list-row-col:nth-child(${index + 1})`)
					.css({ flex: "none", width: w + "px", "min-width": w + "px" });
			});

			$(document).on("mouseup.st_col", () => {
				$(document).off("mousemove.st_col mouseup.st_col");
				this._save_widths(doctype);
			});
		});
	},

	_save_widths(doctype) {
		const $cols = $(".list-row-head .list-header-subject .list-row-col");
		const widths = {};
		$cols.each((i, col) => {
			widths[i] = Math.round($(col).outerWidth());
		});
		localStorage.setItem(this._storage_key(doctype), JSON.stringify(widths));
	},

	_load(doctype) {
		try {
			return JSON.parse(localStorage.getItem(this._storage_key(doctype)));
		} catch (e) {
			return null;
		}
	},
};
