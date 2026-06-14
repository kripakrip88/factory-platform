frappe.pages["module_in_progress"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Модуль в разработке"),
		single_column: true,
	});

	$(page.body).html(`
		<div style="text-align:center; padding:80px 20px; color:var(--text-muted);">
			<div style="font-size:48px; margin-bottom:16px;">🛠️</div>
			<h3 style="margin-bottom:8px;">Модуль в разработке</h3>
			<p>Этот раздел появится в одной из следующих итераций.</p>
		</div>
	`);
};
