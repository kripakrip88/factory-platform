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

	build_workspace_rail() {
		if (this.rail_built) return;

		const workspaces = this.get_workspaces();
		if (!workspaces.length) return;

		let icons_html = "";
		workspaces.forEach((ws) => {
			const icon_content = this.get_icon_for_workspace(ws);
			const escaped_label = frappe.utils.escape_html(ws.label);
			icons_html += `
				<div class="st-rail-item"
					data-workspace="${escaped_label}">
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
			</div>
		`);

		$(".body-sidebar-container").before(this.$rail);

		// Click handler
		this.$rail.find(".st-rail-item").on("click", function () {
			const ws_name = $(this).data("workspace");
			saas_theme.sidebar.switch_workspace(ws_name);
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

		$(".st-rail-item").removeClass("active");
		$(".st-rail-item").each(function () {
			const ws = $(this).data("workspace");
			if (ws && ws.toLowerCase() === current) {
				$(this).addClass("active");
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
