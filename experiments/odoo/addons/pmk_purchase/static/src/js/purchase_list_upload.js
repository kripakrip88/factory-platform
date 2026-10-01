/** @odoo-module **/
// «Запросы КП»: запрос КП из файла погашен целиком (разбор UX, шаг 26,
// 01.10.2026; доводка — перетаскивание и вставка).
//
// Штатно список «Запросов КП» (purchase_dashboard_list) собирает запрос КП
// из файла счёта тремя путями. Все три ведут в одну точку —
// purchase.order.create_document_from_attachment: она САМА коммитит запрос
// КП, где поставщиком стоит партнёр текущего пользователя, прикладывает к
// нему файл и открывает его форму. Снабженец бросил в список PDF-прайс — в
// базе мусорный запрос КП «от» сотрудника. На заводе запросы заводят руками
// и рассылкой прайсов, загрузка не нужна:
//   1. «Загрузить» в строке кнопок (account.DocumentViewUploadButton) —
//      флаг ядра hideUploadButton, им же пользуется sale
//      (sale_file_upload_list_controller.js);
//   2. перетаскивание файла в список — зона «Перетащите, и ИИ автоматически
//      обработает ваши счета» (account.FileUploadListRenderer, onDragStart);
//   3. вставка файла из буфера (onPaste).
// Пара к ним — «Загрузить счёт» над отмеченными строками — погашена в
// xml/purchase_list_upload.xml: счета поставщиков ведутся не в Odoo (шаг 25
// по той же причине скрыл «Создать счета» в «Заказах поставщикам»).
//
// Брошенный в список файл браузер при этом НЕ открывает вместо системы:
// pmkSwallowFileDrop висит на dragover и drop корня таблицы
// (xml/purchase_list_upload.xml) — курсор «нельзя», файл никуда не уходит.
// Канбан «Запросов КП» не трогаем: браузеру он не отдаётся (VIEW_MODES в
// models/ir_actions_act_window.py).
//
// Вернуть: убрать этот файл и xml/purchase_list_upload.xml из
// __manifest__.py, выложить pmk_purchase. Таблица — docs/disabled-features.md.

import { patch } from "@web/core/utils/patch";
import {
    PurchaseDashBoardRenderer,
    PurchaseFileUploadListController,
} from "@purchase/views/purchase_listview";

patch(PurchaseFileUploadListController.prototype, {
    setup() {
        super.setup(...arguments);
        this.hideUploadButton = true;
    },
});

patch(PurchaseDashBoardRenderer.prototype, {
    // Зона «Перетащите, и ИИ…» не появляется.
    onDragStart() {},
    // Файл из буфера не превращается в запрос КП; обычная вставка текста
    // не тронута (preventDefault не зовём).
    onPaste() {},
    pmkSwallowFileDrop(ev) {
        if (!ev.dataTransfer?.types?.includes("Files")) {
            return;
        }
        ev.preventDefault();
        if (ev.type === "dragover") {
            ev.dataTransfer.dropEffect = "none";
        }
    },
});
