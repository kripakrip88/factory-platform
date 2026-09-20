/**
 * Редактор страниц PDF внутри документа.
 *
 * Устройство простое и намеренно одно: ВСЕ страницы всех PDF-вложений записи
 * складываются в ОДИН список. Дальше с ним делают что угодно — переставляют,
 * поворачивают, удаляют, ставят разрезы. Из этого выражается всё:
 *   склеить   — страницы разных файлов лежат в одном списке;
 *   разрезать — разрез делит список на несколько файлов;
 *   удалить   — страницы нет в списке;
 *   повернуть — у страницы свой угол.
 * Один список вместо пяти отдельных режимов: и пользователю нечего изучать,
 * и в коде нечему разойтись.
 *
 * Страницы рисует pdf.js, который уже входит в Odoo. Отрисовка ЛЕНИВАЯ: на
 * альбоме в сотню листов отрисовать всё сразу — это секунды ожидания и
 * мегабайты картинок в памяти, поэтому рисуем то, что видно на экране.
 *
 * Собирает новый файл сервер (PyPDF2). Браузер лишь говорит, ЧТО собрать:
 * из какого вложения, какую страницу и с каким поворотом.
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadPDFJSAssets } from "@web/core/utils/pdfjs";
import { _t } from "@web/core/l10n/translation";
import {
    Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState,
} from "@odoo/owl";

const THUMB_WIDTH = 150;

export class PmkPdfEditor extends Component {
    static template = "pmk_pdf.Editor";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.gridRef = useRef("grid");

        const context = (this.props.action && this.props.action.context) || {};
        this.resModel = context.pmk_res_model || context.active_model;
        this.resId = context.pmk_res_id || context.active_id;

        this.state = useState({
            loading: true,
            busy: false,
            error: null,
            sources: [],
            pages: [],
            name: "",
        });

        // Отрисованные страницы держим вне реактивного состояния: это сотни
        // строк по десятку килобайт, и в реактивной обёртке они дают лишние
        // перерисовки на каждое касание.
        this.thumbs = {};
        this.documents = {};   // id вложения → загруженный pdf.js-документ
        this.rendering = new Set();

        onWillStart(() => this.load());
        onMounted(() => this.watchVisible());
        // После перестановки и удаления состав узлов меняется — наблюдатель
        // должен узнать о новых, иначе они останутся без отрисовки.
        onPatched(() => this.reobserve());
        onWillUnmount(() => this.cleanup());
    }

    // ------------------------------------------------------------------
    // Загрузка
    // ------------------------------------------------------------------

    async load() {
        if (!this.resModel || !this.resId) {
            this.state.error = _t("Не понятно, с каким документом работать.");
            this.state.loading = false;
            return;
        }
        let sources;
        try {
            sources = await this.orm.call("pmk.pdf.job", "pmk_sources", [
                this.resModel,
                Number(this.resId),
            ]);
        } catch (error) {
            this.state.error = error.data ? error.data.message : String(error);
            this.state.loading = false;
            return;
        }

        this.state.sources = sources;
        const usable = sources.filter((s) => s.pages > 0);
        if (!usable.length) {
            this.state.error = sources.length
                ? _t("Ни один из вложенных PDF не удалось прочитать.")
                : _t("К документу не приложено ни одного PDF.");
            this.state.loading = false;
            return;
        }

        // Имя по умолчанию — от первого файла: чаще всего правят именно его,
        // и предлагать «Документ.pdf» значит заставлять переименовывать.
        this.state.name = usable[0].name.replace(/\.pdf$/i, "");

        const pages = [];
        for (const source of usable) {
            for (let i = 0; i < source.pages; i++) {
                pages.push({
                    key: `${source.id}-${i}`,
                    src: source.id,
                    page: i,
                    rotate: 0,
                    breakBefore: false,
                    label: source.name,
                });
            }
        }
        this.state.pages = pages;
        this.state.loading = false;

        try {
            await loadPDFJSAssets();
            globalThis.pdfjsLib.GlobalWorkerOptions.workerSrc =
                "/web/static/lib/pdfjs/build/pdf.worker.js";
            this.pdfjsReady = true;
        } catch {
            // Без отрисовки редактор остаётся рабочим: страницы показываются
            // номерами. Это хуже, но не мешает переставить и удалить.
            this.pdfjsReady = false;
        }
    }

    // ------------------------------------------------------------------
    // Отрисовка страниц
    // ------------------------------------------------------------------

    /** Рисуем только то, что попало в поле зрения. */
    watchVisible() {
        if (!this.gridRef.el) {
            return;
        }
        this.observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        const key = entry.target.dataset.pageKey;
                        if (key) {
                            this.renderThumb(key);
                        }
                    }
                }
            },
            { root: this.gridRef.el, rootMargin: "300px" }
        );
        this.reobserve();
    }

    reobserve() {
        if (!this.observer || !this.gridRef.el) {
            return;
        }
        this.observer.disconnect();
        for (const el of this.gridRef.el.querySelectorAll("[data-page-key]")) {
            this.observer.observe(el);
        }
    }

    async renderThumb(key) {
        if (this.thumbs[key] || this.rendering.has(key) || !this.pdfjsReady) {
            return;
        }
        const page = this.state.pages.find((p) => p.key === key);
        if (!page) {
            return;
        }
        this.rendering.add(key);
        try {
            const doc = await this.pdfDocument(page.src);
            const pdfPage = await doc.getPage(page.page + 1);
            const base = pdfPage.getViewport({ scale: 1 });
            const viewport = pdfPage.getViewport({ scale: THUMB_WIDTH / base.width });
            const canvas = document.createElement("canvas");
            canvas.width = Math.ceil(viewport.width);
            canvas.height = Math.ceil(viewport.height);
            await pdfPage.render({
                canvasContext: canvas.getContext("2d"),
                viewport,
            }).promise;
            this.thumbs[key] = canvas.toDataURL("image/jpeg", 0.7);
            this.render();
        } catch {
            // Одна нечитаемая страница не должна ронять весь экран.
            this.thumbs[key] = false;
        } finally {
            this.rendering.delete(key);
        }
    }

    async pdfDocument(attachmentId) {
        if (!this.documents[attachmentId]) {
            this.documents[attachmentId] = globalThis.pdfjsLib.getDocument(
                `/web/content/${attachmentId}`
            ).promise;
        }
        return this.documents[attachmentId];
    }

    thumbOf(key) {
        return this.thumbs[key];
    }

    cleanup() {
        if (this.observer) {
            this.observer.disconnect();
        }
        this.thumbs = {};
    }

    // ------------------------------------------------------------------
    // Правка
    // ------------------------------------------------------------------

    rotate(page) {
        page.rotate = (page.rotate + 90) % 360;
    }

    remove(page) {
        const index = this.state.pages.indexOf(page);
        if (index >= 0) {
            this.state.pages.splice(index, 1);
            delete this.thumbs[page.key];
        }
    }

    toggleBreak(page) {
        // У первой страницы разрез бессмысленен: он не отделяет ничего.
        if (this.state.pages.indexOf(page) === 0) {
            return;
        }
        page.breakBefore = !page.breakBefore;
    }

    onDragStart(ev, page) {
        this.dragged = page;
        ev.dataTransfer.effectAllowed = "move";
        // Без этого Firefox не начинает перетаскивание.
        ev.dataTransfer.setData("text/plain", page.key);
    }

    onDragOver(ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
    }

    onDrop(ev, target) {
        ev.preventDefault();
        if (!this.dragged || this.dragged === target) {
            return;
        }
        const pages = this.state.pages;
        const from = pages.indexOf(this.dragged);
        const to = pages.indexOf(target);
        if (from < 0 || to < 0) {
            return;
        }
        pages.splice(from, 1);
        pages.splice(to, 0, this.dragged);
        this.dragged = null;
        // Первая страница не может начинаться с разреза.
        if (pages.length) {
            pages[0].breakBefore = false;
        }
    }

    // ------------------------------------------------------------------
    // Сборка
    // ------------------------------------------------------------------

    /** Список страниц → список документов: разрезы делят его на части. */
    get plannedDocuments() {
        const documents = [];
        let current = null;
        for (const page of this.state.pages) {
            if (!current || page.breakBefore) {
                current = { pages: [] };
                documents.push(current);
            }
            current.pages.push(page);
        }
        return documents;
    }

    get partsCount() {
        return this.plannedDocuments.length;
    }

    async save() {
        if (this.state.busy) {
            return;
        }
        const documents = this.plannedDocuments;
        if (!documents.length) {
            this.notification.add(_t("Не осталось ни одной страницы."), { type: "warning" });
            return;
        }
        const many = documents.length > 1;
        const payload = documents.map((doc, index) => ({
            name: many
                ? `${this.state.name || _t("Документ")}-${index + 1}`
                : this.state.name || _t("Документ"),
            pages: doc.pages.map((p) => ({ src: p.src, page: p.page, rotate: p.rotate })),
        }));

        this.state.busy = true;
        try {
            const created = await this.orm.call("pmk.pdf.job", "pmk_build", [
                payload,
                this.resModel,
                Number(this.resId),
            ]);
            this.notification.add(
                created.length > 1
                    ? _t("Готово: приложено файлов — %s", created.length)
                    : _t("Готово: приложен файл «%s»", created[0].name),
                { type: "success" }
            );
            this.close();
        } catch (error) {
            this.notification.add(
                error.data ? error.data.message : String(error),
                { type: "danger", sticky: true }
            );
        } finally {
            this.state.busy = false;
        }
    }

    close() {
        // Возврат к документу, а не на рабочий стол: редактор открыли ИЗ
        // записи, туда и логично вернуться.
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: this.resModel,
            res_id: Number(this.resId),
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("pmk_pdf_editor", PmkPdfEditor);
