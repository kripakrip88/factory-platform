/*
 * SaaS Theme - Dual Sidebar + User Menu
 *
 * Architecture:
 *   [Workspace Rail 56px] [Sidebar Panel ~220px] [Main Content]
 *
 * The rail shows workspace icons from frappe.boot.desktop_icons.
 * Clicking an icon switches the sidebar panel to that workspace.
 * Rail only shows when the sidebar panel is also visible.
 */

$(document).ready(function () {
	if (!frappe.boot.setup_complete) return;

	frappe.after_ajax(function () {
		saas_theme.sidebar.init();
		saas_theme.attachments.init();
		saas_theme.columns.init();
	});

	// Re-init on sidebar_setup in case frappe.after_ajax fired too early
	$(document).on("sidebar_setup", function () {
		if (!saas_theme.sidebar.rail_built) {
			saas_theme.sidebar.init();
		}
		saas_theme.sidebar.setup_user_menu();
	});
});

frappe.provide("saas_theme.sidebar");
frappe.provide("saas_theme.attachments");

saas_theme.sidebar = {
	rail_built: false,

	init() {
		this.build_workspace_rail();
		this.setup_user_menu();
		if (!this._listeners_bound) {
			this.listen_for_changes();
			this._listeners_bound = true;
		}
		this.toggle_rail_visibility();
	},

	/* ============================================
	   WORKSPACE RAIL
	   ============================================ */

	/* Color palette for workspace modules — keyed by lowercase label */
	WORKSPACE_COLORS: {
		// Core
		"home":            "#64748B",
		"desk":            "#64748B",
		// CRM & Sales
		"crm":             "#6366F1",
		"selling":         "#3B82F6",
		"sales":           "#3B82F6",
		// Buying & Procurement
		"buying":          "#F59E0B",
		"purchase":        "#F59E0B",
		"procurement":     "#F59E0B",
		// Stock & Warehouse
		"stock":           "#10B981",
		"warehouse":       "#10B981",
		"inventory":       "#10B981",
		// Manufacturing
		"manufacturing":   "#EF4444",
		"production":      "#EF4444",
		// HR & Payroll
		"hr":              "#8B5CF6",
		"human resources": "#8B5CF6",
		"payroll":         "#8B5CF6",
		// Projects
		"projects":        "#06B6D4",
		"project":         "#06B6D4",
		// Accounting
		"accounting":      "#EC4899",
		"accounts":        "#EC4899",
		"finance":         "#EC4899",
		// Assets
		"assets":          "#F97316",
		// Support
		"support":         "#14B8A6",
		"helpdesk":        "#14B8A6",
		// Settings / Tools
		"settings":        "#94A3B8",
		"tools":           "#94A3B8",
		"integrations":    "#94A3B8",
	},

	get_workspace_color(label) {
		const key = (label || "").toLowerCase();
		if (this.WORKSPACE_COLORS[key]) return this.WORKSPACE_COLORS[key];
		// Partial match
		for (const [k, v] of Object.entries(this.WORKSPACE_COLORS)) {
			if (key.includes(k) || k.includes(key)) return v;
		}
		// Deterministic fallback from label hash
		const palette = ["#3B82F6","#10B981","#F59E0B","#EF4444","#8B5CF6","#06B6D4","#EC4899","#F97316","#14B8A6"];
		let hash = 0;
		for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) & 0xffffffff;
		return palette[Math.abs(hash) % palette.length];
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
					<div class="st-rail-item st-theme-toggle" title="">
						<div class="st-rail-icon st-theme-icon"></div>
						<span class="st-rail-tooltip">${__("Toggle theme")}</span>
					</div>
				</div>
			</div>
		`);

		$(".body-sidebar-container").before(this.$rail);

		// Apply icon colors
		this.$rail.find(".st-rail-item[data-color]").each(function () {
			const color = $(this).data("color");
			$(this).find("svg, .icon").css({ color, stroke: color });
			$(this).find(".st-rail-initials").css({ color });
		});

		// Workspace click handler
		this.$rail.find(".st-rail-item:not(.st-theme-toggle)").on("click", function () {
			const ws_name = $(this).data("workspace");
			saas_theme.sidebar.switch_workspace(ws_name);
		});

		// Theme toggle
		this.render_theme_icon();
		this.$rail.find(".st-theme-toggle").on("click", () => {
			saas_theme.sidebar.toggle_theme();
		});

		// Tooltips — move to body and position with JS
		this.$rail.find(".st-rail-tooltip").each(function () {
			$(this).appendTo("body");
		});

		this.$rail.find(".st-rail-item").on("mouseenter", function () {
			const label = $(this).data("workspace");
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

		this.rail_built = true;
		this.update_rail_active();
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

	render_theme_icon() {
		const is_dark = document.documentElement.getAttribute("data-theme") === "dark";
		const icon_html = is_dark
			? `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
			: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
		this.$rail.find(".st-theme-icon").html(icon_html);
	},

	toggle_theme() {
		const current = document.documentElement.getAttribute("data-theme");
		const next = current === "dark" ? "light" : "dark";
		if (frappe.ui && frappe.ui.set_theme) {
			frappe.ui.set_theme(next);
		} else {
			document.documentElement.setAttribute("data-theme", next);
			localStorage.setItem("app_theme", next);
		}
		setTimeout(() => this.render_theme_icon(), 50);
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
		this.update_rail_active();
	},

	update_rail_active() {
		const current = (frappe.app.sidebar.sidebar_title || "").toLowerCase();

		$(".st-rail-item").removeClass("active").css({
			"background": "",
			"box-shadow": "",
		});
		// reset active indicator color
		$(".st-rail-item::before").css("background", "");

		$(".st-rail-item").each(function () {
			const ws = $(this).data("workspace");
			if (ws && ws.toLowerCase() === current) {
				const color = $(this).data("color") || "#3B82F6";
				$(this).addClass("active");
				// colored tint background + glow
				$(this).css({
					"background": `${color}22`,
					"box-shadow": `0 0 0 1px ${color}33`,
				});
				// colored left indicator via CSS variable
				$(this).css("--st-active-color", color);
			}
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
		// If sidebar panel is visible but has no items, force a re-setup
		const $top = $(".body-sidebar .body-sidebar-top");
		if (!$top.length) return;

		const has_items = $top.find(".standard-sidebar-item").length > 0;
		if (has_items) return;

		// Try to find the right workspace for the current route
		const route = frappe.get_route();
		if (!route || !route.length) return;

		const entity = route.length >= 2 ? route[1] : route[0];
		if (!entity || !frappe.app.sidebar) return;

		// Check if entity maps to a workspace
		const sidebars = frappe.app.sidebar.get_workspace_sidebars
			? frappe.app.sidebar.get_workspace_sidebars(entity)
			: [];

		if (sidebars.length) {
			frappe.app.sidebar.setup(sidebars[0]);
		} else if (frappe.app.sidebar.sidebar_title) {
			// Re-setup current sidebar to force re-render
			frappe.app.sidebar.setup(frappe.app.sidebar.sidebar_title);
		}
	},

	listen_for_changes() {
		const me = this;

		$(document).on("sidebar_setup", () => {
			setTimeout(() => {
				me.update_rail_active();
				me.toggle_rail_visibility();
			}, 50);
		});

		$(document).on("page-change", () => {
			setTimeout(() => {
				me.update_rail_active();
				me.toggle_rail_visibility();
				me.ensure_sidebar_content();
			}, 100);
		});

		$(document).on("form-refresh", () => {
			setTimeout(() => {
				me.toggle_rail_visibility();
				me.ensure_sidebar_content();
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

		// Replace entire pill content with clean structure
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

		// Catch form loads
		$(document).on("form-refresh", () => setTimeout(debounced, 300));
		$(document).on("page-change", () => setTimeout(debounced, 500));

		// Observe entire body for attachment rows appearing
		const observer = new MutationObserver(debounced);
		observer.observe(document.body, { childList: true, subtree: true });
	},
};

/* ============================================
   RESIZABLE LIST COLUMNS
   ============================================ */

frappe.provide("saas_theme.columns");

saas_theme.columns = {
	_observers: [],

	STORAGE_PREFIX: "st_col_w__",
	MIN_WIDTH: 60,
	HANDLE_WIDTH: 6,

	init() {
		if (this._listeners_bound) return;
		this._listeners_bound = true;

		$(document).on("page-change", () => {
			setTimeout(() => this.try_attach(), 300);
		});

		$(document).on("list-update", () => {
			setTimeout(() => this.try_attach(), 150);
		});

		const observer = new MutationObserver(
			frappe.utils.debounce(() => this.try_attach(), 200)
		);
		observer.observe(document.body, { childList: true, subtree: true });
		this._observers.push(observer);
	},

	get_doctype() {
		const route = frappe.get_route();
		if (route && route[0] === "List" && route[1]) {
			return route[1];
		}
		return null;
	},

	storage_key(doctype) {
		return this.STORAGE_PREFIX + doctype.replace(/\s+/g, "_");
	},

	load(doctype) {
		try {
			return JSON.parse(
				localStorage.getItem(this.storage_key(doctype)) || "{}"
			);
		} catch (e) {
			return {};
		}
	},

	save(doctype, widths) {
		try {
			localStorage.setItem(
				this.storage_key(doctype),
				JSON.stringify(widths)
			);
		} catch (e) {}
	},

	try_attach() {
		const doctype = this.get_doctype();
		if (!doctype) return;

		const $table = $(".list-row-head, .dt-header, .datatable .dt-head");
		const $ths = $table.find(".list-header-subject, .dt-cell--header, th");
		const $thead = $("table.list-table thead th, .list-logical-row th");
		const $headers = $ths.length ? $ths : $thead;
		if (!$headers.length) return;

		if ($headers.first().find(".st-col-resizer").length) return;

		const saved = this.load(doctype);
		$headers.each((i, th) => {
			const $th = $(th);
			const key = this._col_key($th, i);

			if (saved[key]) {
				$th.css("width", saved[key] + "px");
				$th.css("min-width", saved[key] + "px");
			}

			if (!$th.find(".st-col-resizer").length) {
				$th.css("position", "relative");
				$th.append('<div class="st-col-resizer" aria-hidden="true"></div>');
			}

			this._bind_drag($th, i, doctype);
		});
	},

	_col_key($th, index) {
		return (
			$th.attr("data-fieldname") ||
			$th.attr("data-col") ||
			$th.find("[data-fieldname]").attr("data-fieldname") ||
			"col_" + index
		);
	},

	_bind_drag($th, index, doctype) {
		const handle = $th.find(".st-col-resizer")[0];
		if (!handle || handle._st_bound) return;
		handle._st_bound = true;

		let startX, startW;

		handle.addEventListener("mousedown", (e) => {
			e.preventDefault();
			e.stopPropagation();

			startX = e.clientX;
			startW = $th.outerWidth();
			$th.addClass("st-col-resizing");
			$("body").addClass("st-col-resizing-body");

			const onMove = (e) => {
				const newW = Math.max(this.MIN_WIDTH, startW + e.clientX - startX);
				$th.css({ width: newW + "px", "min-width": newW + "px" });
			};

			const onUp = () => {
				$th.removeClass("st-col-resizing");
				$("body").removeClass("st-col-resizing-body");

				const saved = this.load(doctype);
				const key = this._col_key($th, index);
				saved[key] = $th.outerWidth();
				this.save(doctype, saved);

				document.removeEventListener("mousemove", onMove);
				document.removeEventListener("mouseup", onUp);
			};

			document.addEventListener("mousemove", onMove);
			document.addEventListener("mouseup", onUp);
		});

		handle.addEventListener("touchstart", (e) => {
			const touch = e.touches[0];
			startX = touch.clientX;
			startW = $th.outerWidth();

			const onMove = (e) => {
				const t = e.touches[0];
				const newW = Math.max(this.MIN_WIDTH, startW + t.clientX - startX);
				$th.css({ width: newW + "px", "min-width": newW + "px" });
			};

			const onEnd = () => {
				const saved = this.load(doctype);
				const key = this._col_key($th, index);
				saved[key] = $th.outerWidth();
				this.save(doctype, saved);

				handle.removeEventListener("touchmove", onMove);
				handle.removeEventListener("touchend", onEnd);
			};

			handle.addEventListener("touchmove", onMove, { passive: true });
			handle.addEventListener("touchend", onEnd);
		}, { passive: true });
	},
};
