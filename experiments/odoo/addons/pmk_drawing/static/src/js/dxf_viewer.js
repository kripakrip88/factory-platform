/* ПМК: окно чертежа DXF — лист с путями, масштаб, сдвиг, слои (шаг 46).
 *
 * Чертёж нарисовал сервер (ezdxf, tools/dxf_render.py): сюда приходят
 * готовые пути SVG по слоям. Браузер только показывает:
 *   • колесо — масштаб к курсору, перетаскивание — сдвиг, на планшете —
 *     щипок двумя пальцами (масштаб вокруг середины между ними) и сдвиг
 *     одним, «Вписать», клавиши + − 0 и стрелки на листе;
 *   • слои — галочками, без перерисовки: пути лежат кусками по слоям в
 *     порядке наложения файла, галочка прячет куски своего слоя;
 *   • «Вписать» — по слоям с галочкой (рамки слоёв прислал сервер):
 *     выключенный в файле слой с мусором далеко в стороне не делает
 *     чертёж точкой, а включённый галочкой — вписывается вместе со всем;
 *   • лист белый в обеих темах (как страница PDF), цвета линий проходят
 *     проверку читаемости на белом (dxf_view_math.sheetColor).
 *
 * SVG собирается createElementNS, а не вставкой разметки: строки путей —
 * только команды и числа (проверены normalizeDrawing), чужой разметки в окне
 * нет вовсе. Масштаб и сдвиг — сменой viewBox, раз в кадр.
 *
 * Компонент общий: его открывают окно ленты и лазера (dxf_dialog.js) и окно
 * «Посмотреть» почты (vendor/mail_client берёт его из реестра
 * pmk_file_viewers под ключом "dxf" — без импорта нашего модуля).
 */
import { Component, markRaw, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

import {
    SVG_NS,
    clampView,
    fitView,
    layersBox,
    normalizeDrawing,
    panBy,
    pinchPoint,
    pinchView,
    resizeView,
    viewBoxString,
    wheelFactor,
    zoomAt,
    zoomLabel,
    zoomPercent,
} from "./dxf_view_math";

// Шаг кнопок «+» и «−» и клавиш.
const BUTTON_STEP = 1.5;
// Сдвиг стрелкой — доля листа.
const ARROW_STEP = 0.1;
// Список слоёв открыт сразу, если окно шире этого и слоёв больше одного.
const WIDE_SCREEN = 992;

export class DxfViewer extends Component {
    static template = "pmk_drawing.DxfViewer";
    static props = {
        // Ответ сервера как есть (договор — шапка tools/dxf_render.py).
        data: { type: Object },
    };

    setup() {
        // Чертёж — в обычном поле, а не в состоянии: в нём до 150 000
        // путей, и следить за каждым незачем.
        this.drawing = markRaw(normalizeDrawing(this.props.data));
        const layers = this.drawing.ok ? this.drawing.layers : [];
        const layerOn = {};
        for (const layer of layers) {
            layerOn[layer.id] = layer.on;
        }
        this.state = useState({
            zoom: 100,
            showLayers: layers.length > 1 && window.innerWidth >= WIDE_SCREEN,
            layerOn,
        });
        this.sheetRef = useRef("sheet");
        this.view = null;
        this.fit = null;
        this.canvas = { w: 0, h: 0 };
        this.runs = new Map();
        this.svg = null;
        this.frame = 0;
        // Указатели на листе (мышь, пальцы): id -> точка в листе. Один —
        // сдвиг, два — щипок (pinch — середина и расстояние до движения).
        this.pointers = new Map();
        this.pinch = null;
        this.listeners = [];
        onMounted(() => this.mountSheet());
        onWillUnmount(() => this.unmountSheet());
    }

    // ------------------------------------------------------------------
    // Лист
    // ------------------------------------------------------------------

    mountSheet() {
        const sheet = this.sheetRef.el;
        if (!sheet || !this.drawing.ok) {
            return;
        }
        const svg = document.createElementNS(SVG_NS, "svg");
        svg.setAttribute("class", "o_pmk_dxf_svg");
        svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
        svg.setAttribute("focusable", "false");
        svg.setAttribute("aria-hidden", "true");
        const root = document.createElementNS(SVG_NS, "g");
        root.setAttribute("stroke-linecap", "round");
        root.setAttribute("stroke-linejoin", "round");
        root.setAttribute("fill-rule", "evenodd");
        // Куски подряд идущих путей одного слоя — свой <g>: порядок
        // наложения как в файле, а галочка слоя прячет только его куски.
        let run = null;
        for (const item of this.drawing.items) {
            if (!run || run.layer !== item.layer) {
                const group = document.createElementNS(SVG_NS, "g");
                root.appendChild(group);
                run = { layer: item.layer, group };
                if (!this.runs.has(item.layer)) {
                    this.runs.set(item.layer, []);
                }
                this.runs.get(item.layer).push(group);
            }
            const path = document.createElementNS(SVG_NS, "path");
            path.setAttribute("d", item.d);
            if (item.kind === 1) {
                path.setAttribute("fill", item.color);
                path.setAttribute("stroke", "none");
            } else {
                path.setAttribute("fill", "none");
                path.setAttribute("stroke", item.color);
                // Толщина — в точках экрана при любом масштабе.
                path.setAttribute("stroke-width", item.kind === 2 ? "2" : "1");
                path.setAttribute("vector-effect", "non-scaling-stroke");
            }
            run.group.appendChild(path);
        }
        svg.appendChild(root);
        sheet.appendChild(svg);
        this.svg = svg;
        for (const layer of this.drawing.layers) {
            this.applyLayer(layer.id);
        }

        this.listen(sheet, "wheel", (ev) => this.onWheel(ev), { passive: false });
        this.listen(sheet, "pointerdown", (ev) => this.onPointerDown(ev));
        this.listen(sheet, "pointermove", (ev) => this.onPointerMove(ev));
        this.listen(sheet, "pointerup", (ev) => this.onPointerUp(ev));
        this.listen(sheet, "pointercancel", (ev) => this.onPointerUp(ev));
        this.listen(sheet, "keydown", (ev) => this.onKeyDown(ev));
        this.listen(sheet, "dblclick", (ev) => this.onDoubleClick(ev));
        // Размер листа известен только после вёрстки окна (диалог ещё
        // открывается) — «Вписать» по первому замеру.
        this.resizeObserver = new ResizeObserver(() => this.onResize());
        this.resizeObserver.observe(sheet);
        this.onResize();
    }

    unmountSheet() {
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        for (const [target, type, handler, options] of this.listeners) {
            target.removeEventListener(type, handler, options);
        }
        this.listeners = [];
        if (this.frame) {
            cancelAnimationFrame(this.frame);
            this.frame = 0;
        }
    }

    listen(target, type, handler, options = undefined) {
        target.addEventListener(type, handler, options);
        this.listeners.push([target, type, handler, options]);
    }

    /** Что вписывать: слои с галочкой, а если у них рамок нет — весь лист. */
    get content() {
        return (
            layersBox(this.layers, this.state.layerOn) || {
                x: 0,
                y: 0,
                w: this.drawing.width,
                h: this.drawing.height,
            }
        );
    }

    /**
     * Галочки слоёв поменялись — «вписан» теперь другой. Вид не двигаем
     * (человек смотрит, куда смотрел), меняются только «Вписать», проценты
     * масштаба и его пределы.
     */
    refit() {
        if (this.canvas.w < 2 || this.canvas.h < 2) {
            return;
        }
        this.fit = fitView(this.content, this.canvas);
        this.schedule();
    }

    onResize() {
        const sheet = this.sheetRef.el;
        if (!sheet) {
            return;
        }
        const rect = sheet.getBoundingClientRect();
        const canvas = { w: Math.round(rect.width), h: Math.round(rect.height) };
        if (canvas.w < 2 || canvas.h < 2) {
            return;
        }
        const old = this.canvas;
        this.canvas = canvas;
        this.fit = fitView(this.content, canvas);
        if (!this.view || old.w < 2) {
            this.view = this.fit;
        } else {
            this.view = clampView(resizeView(this.view, old, canvas), this.fit);
        }
        this.schedule();
    }

    setView(view) {
        if (!this.fit) {
            return;
        }
        this.view = clampView(view, this.fit);
        this.schedule();
    }

    /** viewBox — раз в кадр: колесо и сдвиг шлют десятки событий в секунду. */
    schedule() {
        if (this.frame) {
            return;
        }
        this.frame = requestAnimationFrame(() => {
            this.frame = 0;
            if (this.svg && this.view) {
                this.svg.setAttribute("viewBox", viewBoxString(this.view));
                this.state.zoom = zoomPercent(this.view, this.fit);
            }
        });
    }

    // ------------------------------------------------------------------
    // Масштаб и сдвиг
    // ------------------------------------------------------------------

    onWheel(ev) {
        if (!this.view) {
            return;
        }
        // Колесо над чертежом — масштаб, а не прокрутка окна.
        ev.preventDefault();
        const rect = this.sheetRef.el.getBoundingClientRect();
        this.setView(
            zoomAt(
                this.view,
                wheelFactor(ev.deltaY, ev.deltaMode),
                ev.clientX - rect.left,
                ev.clientY - rect.top,
                this.canvas,
                this.fit
            )
        );
    }

    /** Точка указателя в листе (в точках экрана от левого верхнего угла). */
    sheetPoint(ev) {
        const rect = this.sheetRef.el.getBoundingClientRect();
        return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
    }

    /** Щипок по первым двум указателям. */
    pinchNow() {
        const [a, b] = this.pointers.values();
        return pinchPoint(a, b);
    }

    onPointerDown(ev) {
        if (ev.button !== 0 || !this.view) {
            return;
        }
        const sheet = this.sheetRef.el;
        this.pointers.set(ev.pointerId, this.sheetPoint(ev));
        try {
            sheet.setPointerCapture(ev.pointerId);
        } catch {
            // Указатель уже отпущен — сдвиг просто не начнётся.
        }
        // Второй палец лёг — дальше щипок, отсчёт от этого положения.
        this.pinch = this.pointers.size >= 2 ? this.pinchNow() : null;
        sheet.classList.add("o_pmk_dxf_dragging");
    }

    onPointerMove(ev) {
        const last = this.pointers.get(ev.pointerId);
        if (!last || !this.view) {
            return;
        }
        const point = this.sheetPoint(ev);
        this.pointers.set(ev.pointerId, point);
        if (this.pointers.size >= 2) {
            const next = this.pinchNow();
            if (this.pinch) {
                this.setView(pinchView(this.view, this.pinch, next, this.canvas, this.fit));
            }
            this.pinch = next;
            return;
        }
        const dx = point.x - last.x;
        const dy = point.y - last.y;
        if (dx || dy) {
            this.setView(panBy(this.view, dx, dy, this.canvas));
        }
    }

    onPointerUp(ev) {
        if (!this.pointers.has(ev.pointerId)) {
            return;
        }
        this.pointers.delete(ev.pointerId);
        // Один палец из двух поднят — оставшийся дальше сдвигает с того
        // места, где стоит (его точка обновлялась и во время щипка).
        this.pinch = this.pointers.size >= 2 ? this.pinchNow() : null;
        const sheet = this.sheetRef.el;
        if (sheet) {
            try {
                sheet.releasePointerCapture(ev.pointerId);
            } catch {
                // Уже отпущен.
            }
            if (!this.pointers.size) {
                sheet.classList.remove("o_pmk_dxf_dragging");
            }
        }
    }

    /** Двойной щелчок — крупнее вдвое в этом месте. */
    onDoubleClick(ev) {
        if (!this.view) {
            return;
        }
        const rect = this.sheetRef.el.getBoundingClientRect();
        this.setView(
            zoomAt(this.view, 2, ev.clientX - rect.left, ev.clientY - rect.top, this.canvas, this.fit)
        );
    }

    onKeyDown(ev) {
        if (!this.view || ev.ctrlKey || ev.metaKey || ev.altKey) {
            return;
        }
        const step = { w: this.canvas.w * ARROW_STEP, h: this.canvas.h * ARROW_STEP };
        let handled = true;
        switch (ev.key) {
            case "+":
            case "=":
                this.zoomIn();
                break;
            case "-":
            case "_":
                this.zoomOut();
                break;
            case "0":
                this.fitDrawing();
                break;
            case "ArrowLeft":
                this.setView(panBy(this.view, step.w, 0, this.canvas));
                break;
            case "ArrowRight":
                this.setView(panBy(this.view, -step.w, 0, this.canvas));
                break;
            case "ArrowUp":
                this.setView(panBy(this.view, 0, step.h, this.canvas));
                break;
            case "ArrowDown":
                this.setView(panBy(this.view, 0, -step.h, this.canvas));
                break;
            default:
                handled = false;
        }
        if (handled) {
            ev.preventDefault();
            ev.stopPropagation();
        }
    }

    zoomBy(factor) {
        if (!this.view) {
            return;
        }
        this.setView(
            zoomAt(this.view, factor, this.canvas.w / 2, this.canvas.h / 2, this.canvas, this.fit)
        );
    }

    zoomIn() {
        this.zoomBy(BUTTON_STEP);
    }

    zoomOut() {
        this.zoomBy(1 / BUTTON_STEP);
    }

    fitDrawing() {
        if (this.fit) {
            this.setView(this.fit);
        }
    }

    get zoomText() {
        return zoomLabel(this.state.zoom);
    }

    // ------------------------------------------------------------------
    // Слои
    // ------------------------------------------------------------------

    get layers() {
        return this.drawing.ok ? this.drawing.layers : [];
    }

    get layersLabel() {
        const total = this.layers.length;
        const shown = this.layers.filter((layer) => this.state.layerOn[layer.id]).length;
        return shown === total ? `Слои: ${total}` : `Слои: ${shown} из ${total}`;
    }

    toggleLayers() {
        this.state.showLayers = !this.state.showLayers;
    }

    toggleLayer(layer) {
        this.state.layerOn[layer.id] = !this.state.layerOn[layer.id];
        this.applyLayer(layer.id);
        this.refit();
    }

    setAllLayers(on) {
        for (const layer of this.layers) {
            this.state.layerOn[layer.id] = on;
            this.applyLayer(layer.id);
        }
        this.refit();
    }

    applyLayer(id) {
        const on = Boolean(this.state.layerOn[id]);
        for (const group of this.runs.get(id) || []) {
            group.style.display = on ? "" : "none";
        }
    }

    swatchStyle(layer) {
        // Цвет проверен normalizeDrawing: только #rrggbb.
        return `background-color: ${layer.color};`;
    }

    layerTitle(layer) {
        const parts = [layer.name];
        if (!layer.on) {
            parts.push("в файле слой выключен");
        }
        if (layer.fileColor !== layer.color) {
            parts.push(`цвет в файле ${layer.fileColor} — на белом листе темнее`);
        }
        return parts.join(" · ");
    }
}
