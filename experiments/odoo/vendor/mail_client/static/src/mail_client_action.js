import { Component, onMounted, onWillStart, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useDebounced } from "@web/core/utils/timing";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";

import { FolderTree } from "./panes/folder_tree";
import { MessageList } from "./panes/message_list";
import { ReadingPane } from "./panes/reading_pane";
import { mergeListHead, pageAfter, rowKey, showsChange } from "./panes/list_refresh";
import {
    KEY_BUTTONS,
    arrowsMoveRows,
    isSearchKey,
    isTypingTarget,
    neighbourId,
    pickKeyButton,
} from "./panes/hotkeys";
import {
    QUICK_FILTER_IDS,
    SEARCH_DELAY_MS,
    searchDecision,
    toggleQuickFilter,
} from "./panes/quick_filters";
import {
    KEY_STEP,
    PANE_DEFAULTS,
    PANE_LIMITS,
    clampPane,
    paneVars,
    parseWidths,
    widthsKey,
} from "./panes/pane_widths";
import { Composer } from "./composer/composer";
import { readPref, writePref } from "./utils";

const PAGE_SIZE = 50;
// ПРАВКА ПМК (шаг 22): больше строк сервер за раз не отдаёт (get_messages).
const REFRESH_MAX_ROWS = 200;
// ПРАВКА ПМК (шаг 41): прежний ключ «колонка папок видна» — читается один раз,
// чтобы перенести выбор в новый ключ (folders_view): скрытая колонка стала
// узкой полосой значков.
const SIDEBAR_KEY = "mail_client.sidebar_pinned";
// ПРАВКА ПМК (шаг 18, А2): переписки — режим по умолчанию, как в Mail.ru.
// Ключ новый (было "mail_client.threaded", по умолчанию выключено): прежний
// выбор сбрасывается у всех (решение владельца 30.09.2026), а «выключено»
// дальше запоминается.
const THREADED_KEY = "mail_client.threaded.v2";

/**
 * ПРАВКА ПМК (шаг 41): настройки вида шага 41 — у человека в этом браузере,
 * ключ с номером пользователя: на общем компьютере у каждого свои.
 */
function prefKey(name) {
    return `mail_client.${name}.u${user.userId || 0}`;
}

/** ПРАВКА ПМК (шаг 41, доводка): элемент — в окне письма (вместе с рамкой). */
function inReadingPane(el) {
    return Boolean(el && typeof el.closest === "function" && el.closest(".o_mail_client_reading"));
}

// ПРАВКА ПМК (шаг 41, А9): CSS-переменная ширины колонки.
const WIDTH_VARS = { folders: "--mc-folders-w", list: "--mc-list-w", listCompact: "--mc-list-w-compact" };
// Компактный вид списка действует от xl (mail_client.scss).
const COMPACT_MEDIA = "(min-width: 1200px)";

/**
 * Quick filters, in menu order. The names must match MESSAGE_FILTERS in
 * mail_client_folder.py, which rejects anything it does not know.
 *
 * Deliberately not remembered across sessions, unlike the sidebar and the
 * threading toggle: those change how mail is shown, this one changes which
 * mail is shown at all. Coming back a week later to a mailbox still pinned to
 * "Unread" looks like lost mail.
 */
export const MESSAGE_FILTERS = [
    { id: "all", label: _t("All"), icon: "fa-inbox" },
    { id: "unread", label: _t("Unread"), icon: "fa-envelope" },
    { id: "read", label: _t("Read"), icon: "fa-envelope-open-o" },
    // ПРАВКА ПМК (шаг 18, Г10): последнее слово за клиентом, ответа нет.
    { id: "awaiting", label: _t("Awaiting reply"), icon: "fa-reply" },
    { id: "flagged", label: _t("Starred"), icon: "fa-star" },
    { id: "attachments", label: _t("Has attachments"), icon: "fa-paperclip" },
    { id: "contact", label: _t("From a contact"), icon: "fa-address-book-o" },
];

/**
 * Root of the three-pane inbox.
 *
 * All state lives here and flows down as props; the panes are presentational.
 * That is what makes a bus notification able to refresh the whole view without
 * any component having to know about any other.
 */
export class MailClientInbox extends Component {
    static template = "mail_client.Inbox";
    static components = { FolderTree, MessageList, ReadingPane, Composer, Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        // ПРАВКА ПМК (шаг 41): размер экрана (телефон — ui.isSmall, до 767 px)
        // и окно поверх почты (диалог) — у сервиса ui ядра.
        this.ui = useState(useService("ui"));
        this.rootRef = useRef("root");
        this.searchRef = useRef("search");

        this.state = useState({
            accounts: [],
            activeFolderId: null,
            messages: [],
            hasMore: false,
            selectedMessageId: null,
            detail: null,
            search: "",
            loadingList: false,
            loadingDetail: false,
            syncing: false,
            moveTargets: [],
            bulkMoveTargets: [],
            selectedIds: [],
            bulkBusy: false,
            draft: null,
            drafts: [],
            threaded: readPref(THREADED_KEY) !== "false",
            filter: "all",
            unified: false,
            // ПРАВКА ПМК (шаг 18): рассылки одной строкой — с первой страницы
            // списка, при «Загрузить ещё» остаются.
            digests: [],
            thread: [],
            contact: null,
            searchingServer: false,
            // ПРАВКА ПМК (шаг 22): новые строки, которые ждут над прокрученным
            // списком (плашка «N новых писем»), и подсветка открытой
            // переписки, у которой сменилось письмо строки.
            pendingNew: 0,
            selectedRow: null,
            // ПРАВКА ПМК (шаг 41, А7): что набрано в поиске (searchInput) и
            // по чему список ищет сейчас (search) — разные вещи: поиск идёт
            // по мере ввода с паузой. searchScope — где искал сервер
            // ('everywhere' — во всех папках, кроме Спама и Корзины).
            searchInput: "",
            searchScope: false,
            // ПРАВКА ПМК (шаг 41, А8): колонка папок — 'full' или узкая полоса
            // значков 'rail' (помнится). На телефоне папки — шторкой поверх
            // списка (folderDrawer).
            foldersView: this.readFoldersView(),
            folderDrawer: false,
            // ПРАВКА ПМК (шаг 41, А10): письмо на весь экран (помнится; на
            // телефоне — всегда) и открыто ли сейчас письмо, а не список.
            readerFull: readPref(prefKey("reader_full")) === "true",
            readerOpen: false,
            // ПРАВКА ПМК (шаг 41, А9): ширины колонок, которые человек менял.
            widths: parseWidths(readPref(widthsKey(user.userId))),
            resizing: null,
        });

        this.busService.subscribe("mail_client.sync", (payload) =>
            this.onSyncNotification(payload)
        );

        // ПРАВКА ПМК (шаг 41, А7): поиск по мере ввода — после паузы.
        this.debouncedSearch = useDebounced(() => this.applySearch(), SEARCH_DELAY_MS);
        // Строка списка, по которой открыли письмо последней: от неё ↑/↓
        // ищут соседнее, когда открыто письмо из переписки под письмом.
        this.listRowId = null;
        this.listLoads = 0;

        // ПРАВКА ПМК (шаг 41, А6): горячие клавиши. Сервис клавиш ядра сам
        // молчит, пока фокус в поле ввода или в редакторе и пока открыто
        // окно поверх почты (диалог). Без allowRepeat: зажатая стрелка не
        // листает и не помечает прочитанными пачку писем.
        // Доводка: стрелки листают письма, только когда человек «в списке»
        // (arrowsMoveRows, hotkeys.js); щёлкнул по окну письма — стрелки
        // прокручивают письмо, а не открывают соседнее (и не гасят его).
        // Где был последний щелчок — pointerInReader (щелчок по шапке окна
        // фокуса не даёт, а прокрутку браузер ведёт по месту щелчка).
        this.pointerInReader = false;
        useExternalListener(
            window,
            "pointerdown",
            (ev) => {
                this.pointerInReader = inReadingPane(ev.target);
            },
            { capture: true }
        );
        const arrowKeys = (target) =>
            arrowsMoveRows({
                rows: this.state.messages.length,
                current: Boolean(this.rowOnScreen()),
                draft: Boolean(this.state.draft),
                readerCovers: this.fullLayout && this.readerShown,
                inReader:
                    this.pointerInReader ||
                    inReadingPane(target) ||
                    inReadingPane(document.activeElement),
            });
        useHotkey("arrowdown", () => this.moveSelection(1), { isAvailable: arrowKeys });
        useHotkey("arrowup", () => this.moveSelection(-1), { isAvailable: arrowKeys });
        for (const key of KEY_BUTTONS) {
            useHotkey(key, () => this.clickKeyButton(key), {
                isAvailable: () => !this.state.draft && Boolean(this.keyButton(key)),
            });
        }
        useHotkey("escape", () => this.onEscape(), { isAvailable: () => this.canEscape });
        // «/» сервис ядра не принимает — свой слушатель.
        useExternalListener(window, "keydown", (ev) => this.onWindowKeydown(ev));
        onMounted(() => {
            this.ownActiveElement = this.ui.activeElement;
        });

        // ПРАВКА ПМК (шаг 22): обновление списка без сброса (refreshList).
        // listApi — прокрутка списка (MessageList отдаёт её при монтировании;
        // пока открыт редактор письма, списка нет). listGeneration растёт с
        // каждой загрузкой списка с начала: ответ, пришедший после смены
        // папки, фильтра или поиска, выбрасывается. listEdits и listWrites —
        // правки строк на экране и их записи в пути (noteListEdit,
        // trackListWrite): ответ, снятый с базы до записи, не применяется.
        // syncingAccountId / syncSignal — сигнал прохода, который покроет
        // ответ кнопки «Синхронизировать» (syncNow).
        this.listApi = null;
        this.listGeneration = 0;
        this.resetLoads = 0;
        this.listStale = false;
        this.listEdits = 0;
        this.listWrites = new Set();
        this.syncingAccountId = null;
        this.syncSignal = null;
        this.listRefreshing = null;
        this.listRefreshQueued = null;

        onWillStart(async () => {
            await this.loadAccounts();
            const first = this.firstFolderId();
            if (first) {
                await this.selectFolder(first);
            }
        });
    }

    // ------------------------------------------------------------------
    // loading
    // ------------------------------------------------------------------
    async loadAccounts() {
        const result = await this.orm.call("mail.client.account", "get_inbox_state", []);
        this.state.accounts = result.accounts;
        this.inboxUnreadChanged();
    }

    /**
     * ПРАВКА ПМК (шаг 41): крючок — счётчики папок могли измениться
     * (перечитаны ящики, письмо отмечено). У модуля почты пусто; pmk_mail_ui
     * обновляет по нему счётчик новых на пункте «Почта» и во вкладке.
     */
    inboxUnreadChanged() {}

    firstFolderId() {
        for (const account of this.state.accounts) {
            const inbox = account.folders.find((f) => f.role === "inbox");
            if (inbox) {
                return inbox.id;
            }
            if (account.folders.length) {
                return account.folders[0].id;
            }
        }
        return null;
    }

    // ПРАВКА ПМК: подписи вынесены из шаблона в геттеры. Извлекатель
    // переводов Odoo берёт только статические title=/placeholder=/alt=, а
    // литералы внутри выражений t-att-* не видит вовсе — из-за этого подсказки
    // кнопок оставались английскими при полностью переведённом модуле.
    // ПРАВКА ПМК (шаг 41, А8): кнопка сворачивает колонку папок в полосу
    // значков и разворачивает обратно; на телефоне — шторка поверх списка.
    get sidebarTitle() {
        if (this.isPhone) {
            return this.state.folderDrawer ? _t("Hide folders") : _t("Show folders");
        }
        return this.folderRail ? _t("Expand folders") : _t("Collapse folders");
    }

    get sidebarIcon() {
        if (this.isPhone) {
            return "fa-bars";
        }
        return this.folderRail ? "fa-angle-double-right" : "fa-angle-double-left";
    }

    // ------------------------------------------------------------------
    // ПРАВКА ПМК (шаг 41): раскладка — полоса папок, письмо на весь экран,
    // телефон, ширина колонок
    // ------------------------------------------------------------------
    /** Прежний выбор «колонка папок скрыта» становится полосой значков. */
    readFoldersView() {
        const saved = readPref(prefKey("folders_view"));
        if (saved === "full" || saved === "rail") {
            return saved;
        }
        return readPref(SIDEBAR_KEY) === "false" ? "rail" : "full";
    }

    /** Телефон и узкое окно (до 767 px): список и письмо — по очереди. */
    get isPhone() {
        return Boolean(this.ui && this.ui.isSmall);
    }

    get folderRail() {
        return !this.isPhone && this.state.foldersView === "rail";
    }

    /**
     * Письмо не рядом со списком, а вместо него: «на весь экран» на широком
     * экране (кнопка ⤢ в строке над письмом) и всегда на телефоне (вопрос 3
     * плана почты: «справа» на широком, «на весь экран» на телефоне).
     */
    get fullLayout() {
        return this.isPhone || this.state.readerFull;
    }

    /** На экране письмо (а не список) — в раскладке «на весь экран». */
    get readerShown() {
        return Boolean(this.state.readerOpen && (this.state.detail || this.state.loadingDetail));
    }

    get readerLayout() {
        if (this.isPhone) {
            return "phone";
        }
        return this.state.readerFull ? "full" : "right";
    }

    get layoutClass() {
        return {
            o_mc_small: this.isPhone,
            o_mc_rail: this.folderRail,
            o_mc_full: this.fullLayout,
            o_mc_reader_open: this.fullLayout && this.readerShown,
            o_mc_drawer: this.isPhone && this.state.folderDrawer,
            o_mc_resizing: Boolean(this.state.resizing),
        };
    }

    /** Ширины колонок, которые человек менял (не на телефоне). */
    get paneStyle() {
        return this.isPhone ? "" : paneVars(this.state.widths);
    }

    get showFolderPane() {
        return !this.isPhone || this.state.folderDrawer;
    }

    get showFolderResizer() {
        return !this.isPhone && !this.folderRail;
    }

    get showListResizer() {
        return !this.fullLayout && !this.state.draft;
    }

    toggleFolders() {
        if (this.isPhone) {
            this.state.folderDrawer = !this.state.folderDrawer;
            return;
        }
        this.state.foldersView = this.folderRail ? "full" : "rail";
        writePref(prefKey("folders_view"), this.state.foldersView);
    }

    closeDrawer() {
        this.state.folderDrawer = false;
    }

    /** ⤢ в строке над письмом: письмо на весь экран и обратно. */
    toggleReaderLayout() {
        this.state.readerFull = !this.state.readerFull;
        writePref(prefKey("reader_full"), this.state.readerFull);
        this.state.readerOpen = Boolean(this.state.detail);
    }

    /** «← К списку» и Esc: список на место письма, строка — в виду. */
    backToList() {
        this.state.readerOpen = false;
        // Окна письма на экране больше нет — стрелки снова листают список.
        this.pointerInReader = false;
        const id = this.rowOnScreen();
        if (id && this.listApi) {
            this.listApi.revealRow(id);
        }
    }

    get canEscape() {
        if (this.state.draft) {
            return false;
        }
        return (this.isPhone && this.state.folderDrawer) || (this.fullLayout && this.readerShown);
    }

    onEscape() {
        if (this.isPhone && this.state.folderDrawer) {
            this.closeDrawer();
            return;
        }
        this.backToList();
    }

    get resizeTitle() {
        return _t("Drag to change the width; double-click to reset");
    }

    /** Ключ ширины колонки: папки, список или компактный список. */
    widthKeyFor(pane, el) {
        if (pane === "folders") {
            return "folders";
        }
        const compact =
            el && el.classList.contains("o_compact") && browser.matchMedia(COMPACT_MEDIA).matches;
        return compact ? "listCompact" : "list";
    }

    paneElements() {
        const body = this.rootRef.el && this.rootRef.el.querySelector(".o_mail_client_body");
        if (!body) {
            return {};
        }
        return {
            body,
            folders: body.querySelector(":scope > .o_mail_client_folders"),
            list: body.querySelector(":scope > .o_mail_client_list"),
            handles: body.querySelectorAll(":scope > .o_mail_client_resizer"),
        };
    }

    /**
     * Сколько занимают соседние колонки и границы — для предела ширины.
     * Доводка: в раскладке «на весь экран» список (или письмо на его месте)
     * сам занимает весь остаток — его ширину не вычитаем, иначе предел
     * папок выходил отрицательным и колонка схлопывалась до 160 px при любом
     * движении границы (и это запоминалось). Остатку и там — не меньше
     * READER_MIN.
     */
    paneOthers(pane, els) {
        let others = 0;
        for (const handle of els.handles || []) {
            others += handle.getBoundingClientRect().width;
        }
        let other = pane === "folders" ? els.list : els.folders;
        if (pane === "folders" && this.fullLayout) {
            other = null;
        }
        if (other) {
            others += other.getBoundingClientRect().width;
        }
        return others;
    }

    paneWidth(pane) {
        const els = this.paneElements();
        const el = els[pane];
        if (!el) {
            return null;
        }
        return {
            els,
            el,
            key: this.widthKeyFor(pane, el),
            width: el.getBoundingClientRect().width,
            available: els.body.getBoundingClientRect().width,
            others: this.paneOthers(pane, els),
        };
    }

    setPaneWidth(key, width) {
        this.state.widths = { ...this.state.widths, [key]: width };
        writePref(widthsKey(user.userId), JSON.stringify(this.state.widths));
    }

    /**
     * Перетаскивание границы колонки. Пока тянут, ширина ставится прямо в
     * стиль корня (без перерисовки списка на каждое движение мыши), в конце —
     * в состояние и в память браузера. Рамки писем на это время не ловят
     * мышь (o_mc_resizing, mail_client.scss): иначе курсор над письмом
     * «терял» границу.
     */
    startResize(ev, pane) {
        if (ev.button !== 0 || this.isPhone) {
            return;
        }
        const info = this.paneWidth(pane);
        if (!info) {
            return;
        }
        const handle = ev.currentTarget;
        const root = this.rootRef.el;
        const x0 = ev.clientX;
        let width = Math.round(info.width);
        ev.preventDefault();
        try {
            handle.setPointerCapture(ev.pointerId);
        } catch {
            // Без захвата тоже тянется, пока мышь над границей.
        }
        this.state.resizing = info.key;
        const onMove = (move) => {
            width = clampPane(info.key, info.width + move.clientX - x0, info);
            root.style.setProperty(WIDTH_VARS[info.key], `${width}px`);
        };
        const onUp = () => {
            handle.removeEventListener("pointermove", onMove);
            handle.removeEventListener("pointerup", onUp);
            handle.removeEventListener("pointercancel", onUp);
            this.state.resizing = null;
            this.setPaneWidth(info.key, width);
        };
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
    }

    /** Граница колонки с клавиатуры: ← → по 16 px, Home — по умолчанию. */
    onResizerKeydown(ev, pane) {
        if (ev.key === "Home") {
            ev.preventDefault();
            this.resetPaneWidth(pane);
            return;
        }
        const step = ev.key === "ArrowLeft" ? -KEY_STEP : ev.key === "ArrowRight" ? KEY_STEP : 0;
        if (!step) {
            return;
        }
        ev.preventDefault();
        const info = this.paneWidth(pane);
        if (info) {
            this.setPaneWidth(info.key, clampPane(info.key, info.width + step, info));
        }
    }

    /** Двойной щелчок по границе — ширина по умолчанию (из стилей). */
    resetPaneWidth(pane) {
        const info = this.paneWidth(pane);
        const key = info ? info.key : pane;
        const widths = { ...this.state.widths };
        delete widths[key];
        this.state.widths = widths;
        if (this.rootRef.el) {
            this.rootRef.el.style.removeProperty(WIDTH_VARS[key]);
        }
        writePref(widthsKey(user.userId), JSON.stringify(widths));
    }

    resizerValue(pane) {
        const key = pane === "folders" ? "folders" : "list";
        return this.state.widths[key] || PANE_DEFAULTS[key];
    }

    resizerLimits(pane) {
        return PANE_LIMITS[pane === "folders" ? "folders" : "list"];
    }

    get activeFolder() {
        for (const account of this.state.accounts) {
            const folder = account.folders.find((f) => f.id === this.state.activeFolderId);
            if (folder) {
                return folder;
            }
        }
        return null;
    }

    get activeAccount() {
        return this.state.accounts.find((a) =>
            a.folders.some((f) => f.id === this.state.activeFolderId)
        );
    }

    /**
     * Whether move and delete may be offered for what is on screen.
     *
     * Both are refused server-side on a read-only mailbox, because carrying
     * them out locally would drop mail from Odoo that is still on the server.
     * The unified inbox spans several mailboxes, so it takes the strictest
     * answer among them rather than acting on a mix.
     */
    get canAct() {
        if (this.state.unified) {
            return (
                this.state.accounts.length > 0 &&
                this.state.accounts.every((account) => account.can_act)
            );
        }
        const account = this.activeAccount;
        return Boolean(account && account.can_act);
    }

    // ПРАВКА ПМК (шаг 41): выбор папки сбрасывает поиск (как в Mail.ru),
    // закрывает шторку папок на телефоне и возвращает список на экран.
    async selectFolder(folderId) {
        this.state.activeFolderId = folderId;
        this.state.unified = false;
        this.clearSelection();
        this.resetSearchState();
        this.leaveReader();
        await this.loadMessages({ reset: true });
        await this.loadDrafts();
    }

    async selectUnified() {
        this.state.unified = true;
        this.state.activeFolderId = null;
        this.clearSelection();
        this.resetSearchState();
        this.leaveReader();
        await this.loadMessages({ reset: true });
    }

    /** ПРАВКА ПМК (шаг 41): поиск — пусто, отложенный запуск — отменён. */
    resetSearchState() {
        this.debouncedSearch.cancel();
        this.state.search = "";
        this.state.searchInput = "";
        this.state.searchScope = false;
    }

    /** ПРАВКА ПМК (шаг 41): на экран — список (шторка папок закрыта). */
    leaveReader() {
        this.state.folderDrawer = false;
        this.state.readerOpen = false;
        this.listRowId = null;
    }

    clearSelection() {
        this.state.selectedMessageId = null;
        this.state.detail = null;
        this.state.selectedIds = [];
        this.state.thread = [];
        this.state.contact = null;
    }

    /**
     * ПРАВКА ПМК (шаг 41): фильтры модуля почты и надстройки (крючок
     * extraFilters — pmk_mail_ui: «С лидом»). Без env (hoot-тест
     * filters.test.js собирает компонент без него) крючок отдаёт пусто.
     */
    get filters() {
        return [...MESSAGE_FILTERS, ...this.extraFilters()];
    }

    extraFilters() {
        return [];
    }

    get activeFilter() {
        return this.filters.find((f) => f.id === this.state.filter) || MESSAGE_FILTERS[0];
    }

    /**
     * ПРАВКА ПМК (шаг 41, А7): кнопки-фильтры над списком — «Непрочитанные»,
     * «С вложениями», «Ждут ответа» и кнопки надстройки (extraQuickFilters).
     * Подписи — строкой (prop списка — строка, а _t при загрузке модуля
     * отдаёт ленивый перевод).
     */
    get quickFilters() {
        const byId = new Map(this.filters.map((f) => [f.id, f]));
        return [...QUICK_FILTER_IDS.map((id) => byId.get(id)), ...this.extraQuickFilters()]
            .filter(Boolean)
            .map((f) => ({ id: f.id, label: String(f.label), icon: f.icon || "" }));
    }

    extraQuickFilters() {
        return [];
    }

    /** Повторный щелчок по нажатой кнопке-фильтру снимает фильтр. */
    async setQuickFilter(filterId) {
        await this.setFilter(toggleQuickFilter(this.state.filter, filterId));
    }

    /** ПРАВКА ПМК (шаг 41): имена папок для метки у строки найденного. */
    get folderNames() {
        const names = {};
        for (const account of this.state.accounts) {
            for (const folder of account.folders) {
                names[folder.id] = { name: folder.name, account: account.email };
            }
        }
        return names;
    }

    /**
     * Empty while unfiltered, so the list can tell "no mail" from "no match".
     *
     * Resolved with String(): the labels are built at module load, when _t()
     * still returns a lazy translation rather than text, and the receiving
     * prop is declared as a String.
     */
    get filterLabel() {
        return this.state.filter === "all" ? "" : String(this.activeFilter.label);
    }

    async setFilter(filterId) {
        if (filterId === this.state.filter) {
            return;
        }
        this.state.filter = filterId;
        // The rows about to arrive are a different set, so anything ticked or
        // open refers to a message that may no longer be listed.
        this.clearSelection();
        await this.loadMessages({ reset: true });
    }

    async toggleThreaded() {
        this.state.threaded = !this.state.threaded;
        writePref(THREADED_KEY, this.state.threaded);
        this.clearSelection();
        await this.loadMessages({ reset: true });
    }

    /**
     * Ask the mail server to search.
     *
     * Odoo can only match what it stores, and this client stores headers by
     * design - so anything older than the sync window, or a word that appears
     * only in a body, is invisible locally but not to the server.
     */
    async searchOnServer() {
        if (!this.state.activeFolderId || !this.state.search) {
            return;
        }
        this.state.searchingServer = true;
        this.showListForResults(); // ПРАВКА ПМК (шаг 41, доводка)
        try {
            const result = await this.orm.call("mail.client.folder", "search_server", [], {
                folder_id: this.state.activeFolderId,
                term: this.state.search,
            });
            this.notification.add(
                result.fetched
                    ? _t("%s more message(s) found on the server.", result.fetched)
                    : _t("Nothing further found on the server."),
                { type: result.fetched ? "success" : "info" }
            );
            await this.loadMessages({ reset: true });
        } finally {
            this.state.searchingServer = false;
        }
    }

    async loadDrafts() {
        const account = this.activeAccount;
        this.state.drafts = account
            ? await this.orm.call("mail.client.compose", "list_drafts", [], {
                  account_id: account.id,
              })
            : [];
    }

    // ------------------------------------------------------------------
    // multi-selection
    // ------------------------------------------------------------------
    toggleSelected(messageId) {
        const selected = this.state.selectedIds;
        const index = selected.indexOf(messageId);
        if (index === -1) {
            selected.push(messageId);
        } else {
            selected.splice(index, 1);
        }
        this.refreshBulkTargets();
    }

    toggleAll() {
        this.state.selectedIds =
            this.state.selectedIds.length === this.state.messages.length
                ? []
                : this.state.messages.map((message) => message.id);
        this.refreshBulkTargets();
    }

    async refreshBulkTargets() {
        if (!this.state.selectedIds.length) {
            this.state.bulkMoveTargets = [];
            return;
        }
        this.state.bulkMoveTargets = await this.orm.call(
            "mail.client.message",
            "get_bulk_move_targets",
            [],
            { message_ids: this.state.selectedIds }
        );
    }

    async runBulk(method, params, { removesRows = false } = {}) {
        const ids = this.state.selectedIds.slice();
        if (!ids.length) {
            return;
        }
        this.state.bulkBusy = true;
        try {
            // ПРАВКА ПМК (шаг 22): запись строк списка — обновление списка
            // её дождётся (trackListWrite).
            await this.trackListWrite(
                this.orm.call("mail.client.message", method, [], {
                    message_ids: ids,
                    ...params,
                })
            );
            if (removesRows) {
                this.state.messages = this.state.messages.filter((m) => !ids.includes(m.id));
                if (ids.includes(this.state.selectedMessageId)) {
                    this.state.selectedMessageId = null;
                    this.state.detail = null;
                }
            }
            this.state.selectedIds = [];
            this.state.bulkMoveTargets = [];
            await this.loadAccounts();
        } finally {
            this.state.bulkBusy = false;
        }
    }

    async bulkSeen(value) {
        const ids = this.state.selectedIds;
        for (const message of this.state.messages) {
            if (ids.includes(message.id)) {
                message.flag_seen = value;
            }
        }
        this.noteListEdit(); // ПРАВКА ПМК (шаг 22)
        await this.runBulk("set_seen_bulk", { value });
    }

    async bulkFlagged(value) {
        const ids = this.state.selectedIds;
        for (const message of this.state.messages) {
            if (ids.includes(message.id)) {
                message.flag_flagged = value;
            }
        }
        this.noteListEdit(); // ПРАВКА ПМК (шаг 22)
        await this.runBulk("set_flagged_bulk", { value });
    }

    async bulkMove(folderId) {
        await this.runBulk("move_bulk", { folder_id: folderId }, { removesRows: true });
    }

    async bulkDelete() {
        await this.runBulk("delete_bulk", {}, { removesRows: true });
    }

    /**
     * ПРАВКА ПМК (шаг 41): параметры списка — ОДНИМ местом для загрузки
     * (loadMessages) и для обновления после синхронизации (refreshListOnce).
     * Иначе обновление перечитало бы список с другим поиском или фильтром, и
     * вернулся бы «прыжок» списка (Б2). Поиск — по всем папкам, кроме Спама
     * и Корзины (А7): в них самих сервер ищет только в открытой.
     */
    listQuery(extra = {}) {
        return {
            folder_id: this.state.activeFolderId,
            search: this.state.search || null,
            search_everywhere: Boolean(this.state.search),
            threaded: this.state.threaded,
            unified: this.state.unified,
            message_filter: this.state.filter,
            ...extra,
        };
    }

    async loadMessages({ reset = false } = {}) {
        if (!this.state.activeFolderId && !this.state.unified) {
            return;
        }
        // ПРАВКА ПМК (шаг 41): загрузок разом бывает несколько (поиск по мере
        // ввода) — «грузится», пока идёт хоть одна.
        this.listLoads++;
        this.state.loadingList = true;
        if (reset) {
            // ПРАВКА ПМК (шаг 22): на экране будет другой список — отложенное
            // обновление прежнего и его плашка «N новых писем» больше ни к
            // чему, а начатое обновление (refreshList) своё не запишет.
            this.listGeneration++;
            this.resetLoads++;
            this.state.pendingNew = 0;
            this.listStale = false;
        }
        // ПРАВКА ПМК (шаг 41): ответ для списка, которого уже нет на экране
        // (набрали ещё букву, сменили папку или фильтр), выбрасывается — иначе
        // медленный ответ на «сч» затёр бы быстрый на «счёт».
        const generation = this.listGeneration;
        try {
            // Keyset paging: ask for what is older than the last row we hold,
            // rather than an OFFSET that Postgres has to walk past.
            // ПРАВКА ПМК (шаг 41, Б1): ключ составной — дата и id строки (у
            // переписки — thread_max_id): равные даты на границе страницы не
            // теряются (pageAfter, list_refresh.js).
            const page = reset ? { before: null, before_id: null } : pageAfter(this.state.messages);
            const result = await this.orm.call(
                "mail.client.folder",
                "get_messages",
                [],
                this.listQuery({ limit: PAGE_SIZE, ...page })
            );
            if (generation !== this.listGeneration) {
                return;
            }
            if (reset) {
                this.state.messages = result.messages;
                this.state.digests = result.digests || [];
                this.state.searchScope = result.scope || false;
            } else {
                // ПРАВКА ПМК (шаг 22): страница могла разминуться с
                // обновлением списка (refreshList) — строк, которые уже на
                // экране, второй раз не добавляем.
                const threaded = this.state.threaded;
                const shown = new Set(this.state.messages.map((m) => rowKey(m, threaded)));
                this.state.messages = this.state.messages.concat(
                    result.messages.filter((m) => !shown.has(rowKey(m, threaded)))
                );
            }
            this.state.hasMore = result.has_more;
        } finally {
            this.listLoads--;
            this.state.loadingList = this.listLoads > 0;
            if (reset) {
                this.resetLoads--;
            }
        }
    }

    async loadMore() {
        await this.loadMessages({ reset: false });
    }

    // ------------------------------------------------------------------
    // ПРАВКА ПМК (шаг 41, А7): поиск по мере ввода
    // ------------------------------------------------------------------
    /** Набрали в поле поиска — искать после паузы (SEARCH_DELAY_MS). */
    onSearchInput(value) {
        this.state.searchInput = value;
        this.debouncedSearch();
    }

    /** Enter — искать сразу; Esc — очистить поиск (и не дальше: иначе Esc
     *  ещё и вернул бы из письма к списку). */
    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.debouncedSearch.cancel();
            this.applySearch({ enter: true });
        } else if (ev.key === "Escape" && (this.state.searchInput || this.state.search)) {
            ev.preventDefault();
            ev.stopPropagation();
            this.debouncedSearch.cancel();
            this.state.searchInput = "";
            this.applySearch();
        }
    }

    /**
     * Применить набранное: от двух знаков (Enter — и с одного), пусто —
     * обычный список, тот же текст — ничего (searchDecision,
     * quick_filters.js).
     */
    async applySearch({ enter = false } = {}) {
        const decision = searchDecision(this.state.searchInput, {
            enter,
            applied: this.state.search,
        });
        if (decision === "same" || decision === "wait") {
            return;
        }
        this.state.search = decision === "reset" ? "" : this.state.searchInput.trim();
        if (!this.state.search) {
            this.state.searchScope = false;
        }
        this.showListForResults();
        await this.loadMessages({ reset: true });
    }

    /**
     * ПРАВКА ПМК (шаг 41, доводка): найденное — на экран. В раскладке «на
     * весь экран» открытое письмо закрывает список, и результат поиска
     * (и «Искать на сервере») оставался под ним невидимым до «← К списку».
     * Письмо не закрываем — строка его остаётся выделенной, как после
     * «← К списку».
     */
    showListForResults() {
        if (this.fullLayout && this.state.readerOpen) {
            this.state.readerOpen = false;
            this.pointerInReader = false;
        }
    }

    /** Прежний вход (поиск по Enter) — для надстроек. */
    async onSearch(value) {
        this.state.searchInput = value || "";
        await this.applySearch({ enter: true });
    }

    /** ПРАВКА ПМК (шаг 41): где искали — для шапки списка. */
    get searchScope() {
        return this.state.search ? this.state.searchScope || "folder" : "";
    }

    // ------------------------------------------------------------------
    // reading
    // ------------------------------------------------------------------
    /**
     * ПРАВКА ПМК: письмо открывается без мигания и без гонки («Почта как в
     * Mail.ru», шаг 2, А11; шаг 17 плана, 29.09.2026).
     *
     * Четыре запроса идут разом, а не по очереди: было четыре круга до
     * сервера подряд, стало время самого долгого. Ответ пишется в state
     * одним куском, когда пришли все четыре, — до этого на экране остаётся
     * прежнее письмо (окно чтения показывает его бледным, пока loadingDetail).
     *
     * Гонка автора: при быстрых щелчках ответ прошлого открытия приходил
     * позже и записывался поверх — на экране письмо X при выделенной строке
     * S2, а setSeen(true) после него помечал S2 (setSeen берёт выделенную
     * строку) и сбивал счётчик папки. Теперь у каждого открытия свой знак:
     * после await ответ пишется, только если это всё ещё последнее открытие
     * и строка всё ещё выделена (выделение сбрасывают смена папки, фильтра,
     * перенос, удаление). Опоздавший ответ молча выбрасывается, его ошибка —
     * тоже: письмо, которого уже нет на экране, не должно открывать окно
     * ошибки.
     *
     * pmk_mail_ui/static/src/js/thread_seen.js держится на том, что
     * setSeen(true) зовётся синхронно после записи ответа — так и осталось.
     *
     * Возвращает, чем кончилось открытие (крючок для thread_seen.js):
     * "shown" — письмо на экране; "superseded" — ответ пришёл, но уже
     * открыли другое, ответ выброшен; "failed" — не открылось, а на экране
     * уже другое письмо, ошибка выброшена молча. Отказ ТЕКУЩЕГО открытия —
     * исключение, как у автора.
     */
    async selectMessage(messageId) {
        const token = {};
        this.openToken = token;
        const isCurrent = () =>
            this.openToken === token && this.state.selectedMessageId === messageId;
        this.state.selectedMessageId = messageId;
        this.state.loadingDetail = true;
        // ПРАВКА ПМК (шаг 41, А10): в раскладке «на весь экран» и на
        // телефоне открытое письмо встаёт на место списка.
        this.state.readerOpen = true;
        try {
            // The body is fetched from IMAP on this call when it is not stored
            // yet, so the round trip can be slower than a normal read.
            const [detail, moveTargets, contact, thread] = await Promise.all([
                this.orm.call("mail.client.message", "get_message_detail", [messageId]),
                this.orm.call("mail.client.message", "get_move_targets", [messageId]),
                this.orm.call("mail.client.message", "get_contact_context", [messageId]),
                this.state.threaded
                    ? this.orm.call("mail.client.message", "get_thread", [messageId])
                    : [],
            ]);
            if (!isCurrent()) {
                return "superseded";
            }
            Object.assign(this.state, { detail, moveTargets, contact, thread });
            // Opening a message marks it read, the way every mail client does.
            if (!this.state.detail.flag_seen) {
                this.setSeen(true);
            }
            return "shown";
        } catch (error) {
            if (!isCurrent()) {
                return "failed";
            }
            this.state.detail = null;
            throw error;
        } finally {
            if (this.openToken === token) {
                this.state.loadingDetail = false;
            }
        }
    }

    /**
     * ПРАВКА ПМК (разбор шага 20, 30.09.2026): письмо ленты переписки
     * показано — развёрнуто, и его тело пришло с сервера
     * (panes/conversation.js, props.onShown). Крючок для pmk_mail_ui:
     * thread_seen.js гасит переписку до этого письма. Модуль почты сам
     * ничего не помечает: разворот письма — только просмотр.
     */
    conversationShown() {
        // Отметки «прочитано» у модуля почты — только открытие строки.
    }

    // ------------------------------------------------------------------
    // ПРАВКА ПМК (шаг 41, А6): соседнее письмо и горячие клавиши
    // ------------------------------------------------------------------
    /**
     * Щелчок по строке списка. Запоминаем строку: если дальше открыть письмо
     * из переписки под письмом, ↑/↓ продолжают от неё. Само открытие —
     * selectMessage (его перехватывает pmk_mail_ui, thread_seen.js).
     */
    selectRow(messageId) {
        this.listRowId = messageId;
        return this.selectMessage(messageId);
    }

    /** Строка списка, на которой человек сейчас: открытая или последняя. */
    rowOnScreen() {
        const rows = this.state.messages;
        const open = this.state.selectedMessageId;
        if (open && rows.some((row) => row.id === open)) {
            return open;
        }
        const key = this.selectedThreadKey;
        const byKey = key && rows.find((row) => row.thread_key === key);
        if (byKey) {
            return byKey.id;
        }
        return rows.some((row) => row.id === this.listRowId) ? this.listRowId : null;
    }

    neighbour(dir) {
        return neighbourId(
            this.state.messages,
            { selectedId: this.rowOnScreen(), hasMore: this.state.hasMore },
            dir
        );
    }

    /** Для кнопок ↑ ↓ в строке над письмом (на весь экран). */
    get neighbours() {
        const next = this.neighbour(1);
        return { prev: Boolean(this.neighbour(-1).id), next: Boolean(next.id || next.needMore) };
    }

    /**
     * ↑ / ↓ и кнопки ↑ ↓: открыть соседнее письмо списка. Внизу
     * загруженного — сначала «Загрузить ещё». Строка подтягивается в виду.
     */
    async moveSelection(dir) {
        let target = this.neighbour(dir);
        if (target.needMore) {
            await this.loadMore();
            target = this.neighbour(dir);
        }
        if (!target.id) {
            return;
        }
        if (this.listApi) {
            this.listApi.revealRow(target.id);
        }
        await this.selectRow(target.id);
    }

    /**
     * Кнопка строки над письмом для клавиши (data-mc-key: r, a, f; l — у
     * кнопки «Лид» pmk_mail_ui). Только видимая и доступная: нет кнопки —
     * клавиша ничего не делает (pickKeyButton, hotkeys.js).
     */
    keyButton(key) {
        const root = this.rootRef.el;
        if (!root) {
            return null;
        }
        return pickKeyButton(
            root.querySelectorAll(`.o_mail_client_reading [data-mc-key="${key}"]`),
            key,
            {
                isVisible: (el) =>
                    el.getClientRects().length > 0 &&
                    window.getComputedStyle(el).visibility !== "hidden",
                isInert: (el) => Boolean(el.closest("[inert]")),
            }
        );
    }

    clickKeyButton(key) {
        const button = this.keyButton(key);
        if (button) {
            button.click();
        }
    }

    /**
     * «/» — курсор в поиск. Не в поле ввода и не в редакторе, не поверх
     * диалога (у сервиса ui ядра активный элемент тогда — окно диалога).
     */
    onWindowKeydown(ev) {
        if (ev.defaultPrevented || !isSearchKey(ev)) {
            return;
        }
        if (isTypingTarget(ev.target) || isTypingTarget(document.activeElement)) {
            return;
        }
        if (this.ownActiveElement && this.ui.activeElement !== this.ownActiveElement) {
            return;
        }
        const input = this.searchRef.el;
        if (!input || !input.getClientRects().length) {
            return;
        }
        ev.preventDefault();
        input.focus();
        input.select();
    }

    // ------------------------------------------------------------------
    // ПРАВКА ПМК (шаг 41, А5): значки строки при наведении
    // ------------------------------------------------------------------
    /**
     * «Прочитано / не прочитано» у строки списка — без открытия письма.
     * Строка и счётчик папки (папка строки — folder_id) меняются сразу,
     * запись — через trackListWrite (обновление списка её дождётся), потом
     * точные счётчики с сервера. В режиме переписок pmk_mail_ui ведёт это
     * так же, как кнопка «Прочитано» окна: вся переписка
     * (step41_mail.js).
     */
    async rowSeen(message, value) {
        if (Boolean(message.flag_seen) === Boolean(value)) {
            return;
        }
        const values = { flag_seen: value };
        if (message.unread_count !== undefined) {
            values.unread_count = value ? 0 : Math.max(message.unread_count || 0, 1);
        }
        this.updateRow(message.id, values);
        this.adjustUnread(message.folder_id || this.state.activeFolderId, value ? -1 : 1);
        await this.trackListWrite(
            this.orm.call("mail.client.message", "set_seen", [], {
                message_id: message.id,
                value,
            })
        );
        await this.loadAccounts();
    }

    /** Звезда у строки списка («Отметить» / «Снять отметку»). */
    async rowFlagged(message, value) {
        this.updateRow(message.id, { flag_flagged: value });
        await this.trackListWrite(
            this.orm.call("mail.client.message", "set_flagged", [], {
                message_id: message.id,
                value,
            })
        );
    }

    // ------------------------------------------------------------------
    // message actions - optimistic, then queued to the server
    // ------------------------------------------------------------------
    updateRow(messageId, values) {
        const row = this.state.messages.find((m) => m.id === messageId);
        if (row) {
            Object.assign(row, values);
            this.noteListEdit(); // ПРАВКА ПМК (шаг 22)
        }
        // ПРАВКА ПМК (шаг 18): то же письмо в окне переписки и в истории
        // контакта — его могли открыть оттуда, и значок там должен совпадать.
        for (const item of this.state.thread || []) {
            if (item.id === messageId) {
                Object.assign(item, values);
            }
        }
        for (const item of this.state.contact?.history || []) {
            if (item.id === messageId) {
                Object.assign(item, values);
            }
        }
        if (this.state.detail && this.state.detail.id === messageId) {
            Object.assign(this.state.detail, values);
        }
    }

    adjustUnread(folderId, delta) {
        for (const account of this.state.accounts) {
            const folder = account.folders.find((f) => f.id === folderId);
            if (folder) {
                folder.unread = Math.max(0, (folder.unread || 0) + delta);
            }
        }
        this.inboxUnreadChanged(); // ПРАВКА ПМК (шаг 41)
    }

    /**
     * ПРАВКА ПМК (шаг 18): счётчик — у папки письма, а не у открытой папки.
     * Письмо из «Отправленных», открытое из окна переписки во «Входящих»,
     * прибавляло «Входящим», а в «Все входящие» (activeFolderId пуст)
     * счётчики не менялись вовсе. Папку знает detail (get_message_detail
     * отдаёт folder_id); selectMessage зовёт setSeen(true) сразу после записи
     * detail, так что detail — это выделенное письмо.
     */
    async setSeen(value) {
        const messageId = this.state.selectedMessageId;
        if (!messageId) {
            return;
        }
        const detail = this.state.detail;
        const folderId =
            detail && detail.id === messageId && detail.folder_id
                ? detail.folder_id
                : this.state.activeFolderId;
        this.updateRow(messageId, { flag_seen: value });
        this.adjustUnread(folderId, value ? -1 : 1);
        await this.trackListWrite(
            this.orm.call("mail.client.message", "set_seen", [], {
                message_id: messageId,
                value,
            })
        );
    }

    async toggleSeen() {
        await this.setSeen(!this.state.detail.flag_seen);
    }

    async toggleFlagged() {
        const messageId = this.state.selectedMessageId;
        const value = !this.state.detail.flag_flagged;
        this.updateRow(messageId, { flag_flagged: value });
        await this.trackListWrite(
            this.orm.call("mail.client.message", "set_flagged", [], {
                message_id: messageId,
                value,
            })
        );
    }

    dropSelected() {
        const messageId = this.state.selectedMessageId;
        this.state.messages = this.state.messages.filter((m) => m.id !== messageId);
        this.state.selectedMessageId = null;
        this.state.detail = null;
        this.noteListEdit(); // ПРАВКА ПМК (шаг 22)
    }

    async moveMessage(folderId) {
        const messageId = this.state.selectedMessageId;
        this.dropSelected();
        await this.trackListWrite(
            this.orm.call("mail.client.message", "move_to_folder", [], {
                message_id: messageId,
                folder_id: folderId,
            })
        );
        await this.loadAccounts();
    }

    async deleteMessage() {
        const messageId = this.state.selectedMessageId;
        this.dropSelected();
        await this.trackListWrite(
            this.orm.call("mail.client.message", "delete_message", [], {
                message_id: messageId,
            })
        );
        await this.loadAccounts();
    }

    /**
     * ПРАВКА ПМК (шаг 22): строки списка правятся на экране раньше, чем
     * запись дойдёт до базы (отметки, перенос, удаление), а ответ
     * обновления списка (refreshList) снят с базы в момент запроса. Ответ,
     * запрошенный до правки или пока её запись шла, вернул бы строке
     * прежнее: открытое письмо снова жирное — до следующего прохода с
     * изменениями. Поэтому:
     * - noteListEdit — строки на экране поправлены (здесь, в updateRow,
     *   dropSelected, bulkSeen/bulkFlagged; pmk_mail_ui thread_seen.js — в
     *   pmkApplyThreadResult). Ответ обновления, пришедший после правки, не
     *   применяется: список перечитывается ещё раз;
     * - trackListWrite — запись этих строк идёт на сервер. Обновление
     *   списка не спрашивает сервер, пока она не дошла, а её конец — тоже
     *   правка: ответ, снятый до записи, не применится.
     */
    noteListEdit() {
        this.listEdits++;
    }

    async trackListWrite(promise) {
        this.noteListEdit();
        this.listWrites.add(promise);
        try {
            return await promise;
        } finally {
            this.listWrites.delete(promise);
            this.noteListEdit();
        }
    }

    downloadEml() {
        if (this.state.selectedMessageId) {
            browser.location.href = `/mail_client/message/${this.state.selectedMessageId}/eml`;
        }
    }

    async downloadAttachment(attachmentId) {
        return this.orm.call("mail.client.attachment", "download", [], {
            attachment_id: attachmentId,
        });
    }

    // ------------------------------------------------------------------
    // composing
    // ------------------------------------------------------------------
    /**
     * ПРАВКА ПМК (шаг 20): ответить или переслать можно конкретное письмо
     * переписки (кнопки у развёрнутого письма в ленте), а не только
     * открытое: messageId. Без него — открытое, как было (закреплённая
     * строка над письмом). Prop onReply окна чтения — этот метод.
     */
    async compose(mode = "new", messageId = null) {
        const account = this.activeAccount;
        if (!account) {
            return;
        }
        this.state.draft = await this.orm.call("mail.client.compose", "start", [], {
            account_id: account.id,
            mode,
            message_id: mode === "new" ? null : messageId ?? this.state.selectedMessageId,
        });
    }

    async resumeDraft(composeId) {
        this.state.draft = await this.orm.call("mail.client.compose", "open_draft", [], {
            compose_id: composeId,
        });
    }

    async closeComposer() {
        this.state.draft = null;
        await this.loadDrafts();
    }

    async onSent() {
        this.state.draft = null;
        await this.loadDrafts();
        // The sent copy is APPENDed to the server's Sent folder, so Odoo only
        // learns about it by syncing. Reloading the list alone would leave the
        // message you just sent invisible until the next cron run.
        await this.syncNow();
    }

    async allowImages() {
        const messageId = this.state.selectedMessageId;
        if (!messageId) {
            return;
        }
        const detail = await this.orm.call("mail.client.message", "allow_images", [messageId]);
        // ПРАВКА ПМК: та же гонка, что в selectMessage, — пока сервер отвечал,
        // могли открыть другое письмо; ответ по прежнему на него не пишем.
        if (this.state.selectedMessageId === messageId && this.state.detail?.id === messageId) {
            this.state.detail = detail;
        }
    }

    // ------------------------------------------------------------------
    // sync
    // ------------------------------------------------------------------
    /**
     * ПРАВКА ПМК (шаг 22 плана, 30.09.2026): кнопка «Синхронизировать».
     *
     * Ящик занят — его синхронизирует крон (или кнопка в другой вкладке)
     * либо дочитывает структуры крон «Describe Older Messages»: сервер
     * прохода не начинает и отвечает busy — мягкое «Ящик сейчас занят —
     * новые письма придут сами», не ошибка. Придут: идущий проход пришлёт
     * сигнал шины, а после дочитки (она сигнала не шлёт) письма принесёт
     * следующий проход крона. После прохода — обновление без сброса
     * (refreshAfterSync): список не прыгает к началу, если пользователь не
     * в начале, и не перечитывается вовсе, если в показанных папках ничего
     * не изменилось (changed, folder_ids).
     *
     * Сигнал шины этого ящика, пришедший, пока идёт запрос, откладывается
     * (onSyncNotification, syncSignal): это свой же проход — его покроет
     * ответ кнопки, иначе список и ящики перечитывались бы дважды, — или
     * проход крона, закончившийся перед нашим. Его изменения
     * присоединяются к ответу (ящик занят — обрабатываются одни). Свой
     * сигнал, пришедший уже после ответа, обработается ещё раз — лишнее
     * обновление безвредно.
     */
    async syncNow() {
        const account = this.activeAccount;
        if (!account || this.state.syncing) {
            return;
        }
        this.state.syncing = true;
        this.syncingAccountId = account.id;
        this.syncSignal = null;
        try {
            let result = null;
            let signal = null;
            try {
                result = await this.orm.call("mail.client.account", "sync_account", [], {
                    account_id: account.id,
                });
            } finally {
                this.syncingAccountId = null;
                signal = this.syncSignal;
                this.syncSignal = null;
                if (!result && signal) {
                    // Запрос упал (ошибку покажет Odoo) — отложенный сигнал
                    // чужого прохода обрабатываем как обычно, не теряем.
                    this.refreshAfterSync(account.id, signal);
                }
            }
            if (result.busy) {
                this.notification.add(
                    _t("The mailbox is busy right now; new mail will arrive by itself."),
                    { type: "info", title: _t("Mail sync") }
                );
                if (signal) {
                    await this.refreshAfterSync(account.id, signal);
                }
                return;
            }
            if (result.state === "error") {
                this.notification.add(result.error_message || _t("Synchronisation failed."), {
                    type: "danger",
                    title: _t("Mail sync"),
                });
            }
            const shown = this.state.accounts.find((a) => a.id === account.id);
            const stateChanged =
                !shown || shown.state !== result.state || result.state === "error";
            if (shown) {
                shown.state = result.state;
            }
            await this.refreshAfterSync(
                account.id,
                this.mergeSyncSignals(signal, {
                    changed: result.changed !== false,
                    folderIds: Array.isArray(result.folder_ids) ? result.folder_ids : null,
                    stateChanged,
                })
            );
        } finally {
            this.state.syncing = false;
        }
    }

    /** ПРАВКА ПМК (шаг 22): ящики и список — без сброса списка к началу. */
    async refresh() {
        await this.loadAccounts();
        await this.refreshList();
    }

    /**
     * ПРАВКА ПМК (шаг 22): сигнал синхронизации ящика. Раньше каждый
     * сигнал перегружал список с первой страницы (loadMessages reset):
     * догруженные страницы терялись, прокрутка прыгала, а сигнал теперь
     * раз в 2 минуты. Сервер говорит, изменилось ли что-то в письмах за
     * проход и в каких папках (changed, folder_ids; сигнал старого сервера
     * без них — «изменилось везде»):
     * - нет — только состояние ящика и время прохода, из самого сигнала;
     *   ящики перечитываются, только если сменилось состояние (текст
     *   ошибки берётся оттуда);
     * - да — счётчики папок, а список — если изменилась показанная в нём
     *   папка (listShowsChange), без сброса (refreshList). Новый спам не
     *   перечитывает открытые «Входящие».
     * Фоновая синхронизация другого ящика список не трогает.
     */
    onSyncNotification(payload) {
        const account = this.state.accounts.find((a) => a.id === payload.account_id);
        if (!account) {
            return;
        }
        // Ящик в ошибке — текст ошибки (подсказка в дереве) мог смениться,
        // его несёт только get_inbox_state.
        const stateChanged = account.state !== payload.state || payload.state === "error";
        account.state = payload.state;
        account.last_sync_date = payload.last_sync_date;
        const signal = {
            changed: payload.changed !== false,
            folderIds: Array.isArray(payload.folder_ids) ? payload.folder_ids : null,
            stateChanged,
        };
        if (this.syncingAccountId === payload.account_id) {
            // Ждём ответа кнопки этого ящика — он покроет (syncNow).
            this.syncSignal = this.mergeSyncSignals(this.syncSignal, signal);
            return;
        }
        return this.refreshAfterSync(payload.account_id, signal);
    }

    /** ПРАВКА ПМК (шаг 22): два сигнала одного ящика — как один. */
    mergeSyncSignals(a, b) {
        if (!a || !b) {
            return a || b;
        }
        return {
            changed: a.changed || b.changed,
            // null — «везде»: сервер не сказал, в каких папках.
            folderIds:
                a.folderIds && b.folderIds ? [...new Set([...a.folderIds, ...b.folderIds])] : null,
            stateChanged: a.stateChanged || b.stateChanged,
        };
    }

    async refreshAfterSync(accountId, { changed = true, folderIds = null, stateChanged = true } = {}) {
        if (!changed && !stateChanged) {
            // Проход ничего не изменил: состояние ящика уже на месте, а
            // счётчики папок без изменений писем прежние.
            return;
        }
        await this.loadAccounts();
        if (changed && this.listShowsChange(accountId, folderIds)) {
            await this.refreshList();
        }
    }

    /**
     * ПРАВКА ПМК (шаг 22): изменения прохода (папки folderIds) касаются
     * списка на экране. Касаются, если изменилась:
     * - открытая папка («Все входящие» — «Входящие» ящика);
     * - папка строки рассылок (state.digests);
     * - в режиме переписок — любая рабочая папка ящика: строка переписки
     *   считает её письма по всему ящику (ответ в «Отправленных», в архиве,
     *   в своей папке). Тихие — Спам, Корзина, сортировщики mail.ru
     *   (folder.quiet) — нет: их письма переписку не решают.
     * folderIds не пришли (старый сервер) или папки нет в дереве — касаются.
     * ПРАВКА ПМК (шаг 41): правило — чистая функция showsChange
     * (panes/list_refresh.js); при поиске «по всем папкам» касается любая
     * папка ящика, кроме Спама и Корзины.
     */
    listShowsChange(accountId, folderIds) {
        if (!this.showsAccount(accountId)) {
            return false;
        }
        const account = this.state.accounts.find((a) => a.id === accountId);
        return showsChange(
            {
                unified: this.state.unified,
                threaded: this.state.threaded,
                activeFolderId: this.state.activeFolderId,
                digestIds: (this.state.digests || []).map((d) => d.folder_id),
                everywhere: Boolean(this.state.search) && this.state.searchScope === "everywhere",
            },
            account ? account.folders : [],
            folderIds
        );
    }

    /** ПРАВКА ПМК (шаг 22): письма этого ящика сейчас в списке. */
    showsAccount(accountId) {
        if (this.state.unified) {
            return this.state.accounts.some((a) => a.id === accountId);
        }
        return Boolean(this.activeAccount && this.activeAccount.id === accountId);
    }

    /**
     * ПРАВКА ПМК (шаг 22): перечитать список, не сбрасывая его.
     *
     * Перечитывается НАЧАЛО списка — столько строк, сколько на экране, и
     * ещё страница про запас (не больше 200), с тем же поиском, фильтром,
     * режимом переписок; сводит его с экраном mergeListHead
     * (panes/list_refresh.js; там же — зачем запас).
     * - Пользователь в начале списка (или apply) — свежий список ставится
     *   целиком: новые строки сверху, уже загруженные страницы остаются
     *   (кроме случая, когда пришло больше строк, чем запас, или загружено
     *   больше 200: тогда остальное догрузит «Загрузить ещё»), прокрутка —
     *   в начале. Выделение, галочки и открытое письмо остаются; у
     *   переписки, где сменилось письмо строки, подсветка держится по
     *   переписке (selectedThreadKey).
     * - Пользователь прокрутил вниз — список не двигается: на месте
     *   обновляются только отметки и счётчики строк, а новые строки (и
     *   строка рассылок) ждут наверху — плашка «N новых писем»
     *   (pendingNew); щелчок по ней или возврат наверх ставят список
     *   целиком (showNewMessages, onListTop).
     * - Строки на экране поправили, пока шёл ответ, или их запись ещё идёт
     *   (noteListEdit, trackListWrite) — ответ не применяется, список
     *   перечитывается ещё раз, когда записи дошли.
     * Вызовы, пришедшие во время обновления, сливаются в одно следующее.
     */
    refreshList({ apply = false } = {}) {
        if (this.listRefreshing) {
            this.listRefreshQueued = { apply: apply || Boolean(this.listRefreshQueued?.apply) };
            return this.listRefreshing;
        }
        this.listRefreshing = (async () => {
            try {
                let next = { apply };
                while (next) {
                    this.listRefreshQueued = null;
                    await this.refreshListOnce(next);
                    next = this.listRefreshQueued;
                }
            } finally {
                this.listRefreshing = null;
                this.listRefreshQueued = null;
            }
        })();
        return this.listRefreshing;
    }

    async refreshListOnce({ apply = false } = {}) {
        // Запись поправленных строк ещё идёт на сервер: ответ, снятый до
        // неё, вернул бы им прежнее (trackListWrite) — сначала дождаться.
        while (this.listWrites.size) {
            await Promise.allSettled([...this.listWrites]);
        }
        if ((!this.state.activeFolderId && !this.state.unified) || this.resetLoads) {
            // Список грузится с начала (другая папка, фильтр, поиск) — он и
            // так будет свежим.
            return;
        }
        const generation = this.listGeneration;
        const edits = this.listEdits;
        // ПРАВКА ПМК (шаг 41): те же параметры, что у загрузки (listQuery).
        const result = await this.orm.call(
            "mail.client.folder",
            "get_messages",
            [],
            this.listQuery({
                // Запас в страницу: начало дойдёт до последней строки экрана,
                // даже если сверху пришли новые, а у загруженного целиком
                // списка ответ выйдет короче запроса (panes/list_refresh.js).
                limit: Math.min(this.state.messages.length + PAGE_SIZE, REFRESH_MAX_ROWS),
                before: null,
            })
        );
        if (generation !== this.listGeneration || this.resetLoads) {
            return; // пока шёл ответ, на экране стал другой список
        }
        if (edits !== this.listEdits) {
            // Пока шёл ответ, строки на экране поправили (открыли письмо,
            // отметили, перенесли): ответ снят с базы раньше и вернул бы им
            // прежнее — открытое письмо снова жирное. Ещё раз, когда записи
            // дойдут.
            this.listRefreshQueued = { apply: apply || Boolean(this.listRefreshQueued?.apply) };
            return;
        }
        const threaded = this.state.threaded;
        const open = this.state.messages.find((m) => m.id === this.state.selectedMessageId);
        const openKey = threaded ? (open && open.thread_key) || this.selectedThreadKey : null;
        const merge = mergeListHead(this.state.messages, result, {
            threaded,
            hasMore: this.state.hasMore,
            selectedIds: this.state.selectedIds,
        });
        const atTop =
            apply || !this.state.messages.length || !this.listApi || this.listApi.isAtTop();
        const digests = result.digests || [];
        const digestsChanged = JSON.stringify(digests) !== JSON.stringify(this.state.digests);
        if (!atTop || (!merge.structural && !this.listStale)) {
            // Состав и порядок строк прежние (или пользователь прокрутил
            // вниз): только отметки и счётчики строк — на месте. Список не
            // перерисовывается целиком: отметка на mail.ru меняет одну строку.
            for (const [row, values] of merge.updates) {
                Object.assign(row, values);
            }
            if (!atTop) {
                this.state.pendingNew = merge.fresh;
                // Строка рассылок стоит среди строк по дате — её смена тоже
                // ждёт возврата наверх (onListTop).
                this.listStale = this.listStale || merge.structural || digestsChanged;
                return;
            }
            this.state.pendingNew = 0;
            this.state.hasMore = merge.hasMore;
            if (digestsChanged) {
                this.state.digests = digests;
            }
            return;
        }
        this.state.messages = merge.messages;
        this.state.hasMore = merge.hasMore;
        this.state.digests = digests;
        this.state.pendingNew = 0;
        this.listStale = false;
        const ticked = this.state.selectedIds;
        if (
            merge.selectedIds.length !== ticked.length ||
            merge.selectedIds.some((id, index) => id !== ticked[index])
        ) {
            this.state.selectedIds = merge.selectedIds;
            this.refreshBulkTargets();
        }
        if (openKey) {
            const row = merge.messages.find((m) => m.thread_key === openKey);
            this.state.selectedRow =
                row && row.id !== this.state.selectedMessageId
                    ? { id: this.state.selectedMessageId, key: openKey }
                    : null;
        }
        if (this.listApi) {
            this.listApi.keepTop();
        }
    }

    /**
     * ПРАВКА ПМК (шаг 22): переписка открытой строки, если её строку теперь
     * представляет другое письмо (пришёл ответ) — по ней список держит
     * подсветку. Открыли другое письмо — подсветка снова по id.
     */
    get selectedThreadKey() {
        const row = this.state.selectedRow;
        return this.state.threaded && row && row.id === this.state.selectedMessageId
            ? row.key
            : null;
    }

    /** ПРАВКА ПМК (шаг 22): щелчок по плашке «N новых писем». */
    showNewMessages() {
        return this.refreshList({ apply: true });
    }

    /**
     * ПРАВКА ПМК (шаг 22): пользователь сам вернулся в начало списка.
     * Без apply: пока идёт ответ, он может снова уйти вниз (инерция
     * трекпада) — тогда список не ставится и прокрутку не дёргает; «в
     * начале ли» проверится по ответу. apply — только у плашки: там
     * пользователь сам попросил наверх.
     */
    onListTop() {
        if (this.listStale || this.state.pendingNew) {
            return this.refreshList();
        }
    }

    /**
     * ПРАВКА ПМК (шаг 22): прокрутку списка отдаёт MessageList. Список
     * смонтирован заново (закрыли редактор письма) — он в начале, а
     * отложенное обновление (плашка, listStale) ещё ждёт возврата наверх,
     * которого не будет: ставим сейчас.
     */
    setListApi(api) {
        this.listApi = api;
        if (api && (this.listStale || this.state.pendingNew)) {
            this.refreshList();
        }
    }
}

registry.category("actions").add("mail_client.inbox", MailClientInbox);
