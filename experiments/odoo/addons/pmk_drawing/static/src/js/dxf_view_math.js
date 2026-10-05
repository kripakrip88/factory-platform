/* ПМК: чистые правила окна чертежа DXF (разбор удобства, шаг 46).
 *
 * Ни одного импорта Odoo: масштаб к курсору, «Вписать», пределы масштаба,
 * читаемость цветов на белом листе и проверка ответа сервера гоняются
 * обычным node (static/tests/dxf_view_math.test.mjs), без браузера.
 *
 * ДОГОВОР С СЕРВЕРОМ — шапка tools/dxf_render.py (ok, viewbox, layers,
 * palette, items, size_mm, units, notes, skipped). normalizeDrawing ниже —
 * второй его конец; менять только вместе.
 *
 * ВИД (view) — прямоугольник {x, y, w, h} в координатах путей (viewBox SVG).
 * Его пропорции всегда равны пропорциям листа на экране (canvas, в точках
 * экрана), поэтому «точка экрана -> координата чертежа» — одно умножение.
 */

export const SVG_NS = "http://www.w3.org/2000/svg";

// Поля вокруг чертежа при «Вписать» — доля стороны листа.
export const FIT_MARGIN = 0.04;
// Масштаб относительно «вписан» (1 = 100 %). Сверху — пока единица
// координат (миллионная доля чертежа) не крупнее 4 точек экрана: глубже
// целые координаты ezdxf дают ступеньки. Снизу — 10 %: дальше чертёж — точка.
export const MAX_ZOOM = 5000;
export const MIN_ZOOM = 0.1;
// Контраст линии с белым листом — порог WCAG для графики (3:1). Жёлтый (1,1),
// голубой (1,3), светло-зелёный (1,4) и светло-серый AutoCAD рисует на
// чёрном фоне — на белом их не прочесть, они темнеют. Красный (4,0),
// пурпурный (3,1), синий и серый ACI 8 (3,9) читаются — остаются как в файле.
export const MIN_CONTRAST = 3;

const D_RE = /^[MLHVCSQTAZmlhvcsqtaz0-9eE.,\s+-]*$/;
const COLOR_RE = /^#[0-9a-f]{6}$/i;
const DXF_MIMETYPES = new Set([
    "image/vnd.dxf",
    "image/x-dxf",
    "image/dxf",
    "application/dxf",
    "application/x-dxf",
]);

function text(value) {
    if (value === null || value === undefined || value === false) {
        return "";
    }
    return String(value);
}

/** Вложение — чертёж DXF? По имени (.dxf) или по заявленному типу. */
export function isDxfFile(name, mimetype) {
    const lower = text(name).trim().toLowerCase();
    if (lower.endsWith(".dxf")) {
        return true;
    }
    return DXF_MIMETYPES.has(text(mimetype).trim().toLowerCase());
}

/**
 * Вид «весь чертёж в окне»: content {x, y, w, h} — рамка того, что надо
 * вписать, в координатах путей (x, y по умолчанию 0 — весь viewbox),
 * canvas {w, h} — лист на экране в точках.
 */
export function fitView(content, canvas, margin = FIT_MARGIN) {
    const cw = Math.max(1, canvas.w);
    const ch = Math.max(1, canvas.h);
    const bw = Math.max(content.w, 1);
    const bh = Math.max(content.h, 1);
    const cx = (Number(content.x) || 0) + content.w / 2;
    const cy = (Number(content.y) || 0) + content.h / 2;
    const room = Math.max(0.1, 1 - 2 * margin);
    // Единиц чертежа на точку экрана — по тесной стороне.
    const scale = Math.max(bw / (cw * room), bh / (ch * room));
    const w = cw * scale;
    const h = ch * scale;
    return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/**
 * Что вписывать: рамка слоёв с галочкой ({x, y, w, h}) или null — у слоёв
 * с галочкой рамок нет (всё снято), тогда окно вписывает весь viewbox.
 * layers — слои normalizeDrawing (box: {x0, y0, x1, y1} или null), layerOn
 * — галочки по id. Выключенный в файле слой далеко в стороне не мешает
 * вписать чертёж, а включённый галочкой — вписывается вместе с ним.
 */
export function layersBox(layers, layerOn) {
    let box = null;
    for (const layer of layers || []) {
        if (!layer.box || !(layerOn && layerOn[layer.id])) {
            continue;
        }
        const { x0, y0, x1, y1 } = layer.box;
        box = box
            ? {
                  x0: Math.min(box.x0, x0),
                  y0: Math.min(box.y0, y0),
                  x1: Math.max(box.x1, x1),
                  y1: Math.max(box.y1, y1),
              }
            : { x0, y0, x1, y1 };
    }
    return box ? { x: box.x0, y: box.y0, w: box.x1 - box.x0, h: box.y1 - box.y0 } : null;
}

/**
 * Масштаб с неподвижной точкой под курсором: px, py — точка в листе (в
 * точках экрана от левого верхнего угла). factor > 1 — крупнее. fit — вид
 * «вписан»: от него считаются пределы MIN_ZOOM…MAX_ZOOM.
 */
export function zoomAt(view, factor, px, py, canvas, fit = null) {
    let f = Number.isFinite(factor) && factor > 0 ? factor : 1;
    if (fit) {
        const zoom = fit.w / view.w;
        const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * f));
        f = next / zoom;
    }
    const cw = Math.max(1, canvas.w);
    const ch = Math.max(1, canvas.h);
    const rx = px / cw;
    const ry = py / ch;
    const ux = view.x + rx * view.w;
    const uy = view.y + ry * view.h;
    const w = view.w / f;
    const h = view.h / f;
    return { x: ux - rx * w, y: uy - ry * h, w, h };
}

/** Сдвиг на dx, dy точек экрана (чертёж едет за рукой). */
export function panBy(view, dx, dy, canvas) {
    const kx = view.w / Math.max(1, canvas.w);
    const ky = view.h / Math.max(1, canvas.h);
    return { x: view.x - dx * kx, y: view.y - dy * ky, w: view.w, h: view.h };
}

/** Два пальца на листе: середина между ними (в точках листа) и расстояние. */
export function pinchPoint(a, b) {
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) };
}

/**
 * Щипок: before/after — pinchPoint до и после движения пальцев. Чертёж
 * едет за серединой между пальцами и растёт во столько раз, во сколько
 * разошлись пальцы; точка чертежа под серединой остаётся под ней. Пределы
 * масштаба — те же, что у колеса (fit).
 */
export function pinchView(view, before, after, canvas, fit = null) {
    let next = panBy(view, after.x - before.x, after.y - before.y, canvas);
    if (before.d > 0 && after.d > 0) {
        next = zoomAt(next, after.d / before.d, after.x, after.y, canvas, fit);
    }
    return next;
}

/**
 * Не дать увести чертёж с глаз: центр вида — внутри рамки «вписан». Чертёж
 * может уйти к краю, но не исчезнуть целиком.
 */
export function clampView(view, fit) {
    if (!fit) {
        return view;
    }
    const cx = Math.min(fit.x + fit.w, Math.max(fit.x, view.x + view.w / 2));
    const cy = Math.min(fit.y + fit.h, Math.max(fit.y, view.y + view.h / 2));
    return { x: cx - view.w / 2, y: cy - view.h / 2, w: view.w, h: view.h };
}

/** Новый размер листа на экране: тот же центр и тот же масштаб. */
export function resizeView(view, oldCanvas, newCanvas) {
    const perPoint = view.w / Math.max(1, oldCanvas.w);
    const cx = view.x + view.w / 2;
    const cy = view.y + view.h / 2;
    const w = Math.max(1, newCanvas.w) * perPoint;
    const h = Math.max(1, newCanvas.h) * perPoint;
    return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/** Масштаб в процентах от «вписан»: 100 — весь чертёж в окне. */
export function zoomPercent(view, fit) {
    if (!view || !fit || !view.w) {
        return 100;
    }
    return Math.round((fit.w / view.w) * 100);
}

/** «1 250 %» — с пробелами между разрядами. */
export function zoomLabel(percent) {
    return `${groupDigits(Math.round(percent))} %`;
}

export function viewBoxString(view) {
    const r = (value) => Math.round(value * 100) / 100;
    return `${r(view.x)} ${r(view.y)} ${r(view.w)} ${r(view.h)}`;
}

/**
 * Шаг масштаба на одно движение колеса. Мышь даёт deltaY ±100 точек
 * (иногда строками или страницами — deltaMode 1 и 2), сенсорная панель —
 * много мелких. Один щелчок колеса — примерно ×1,16; рывок не больше ×2.
 */
export function wheelFactor(deltaY, deltaMode = 0) {
    let pixels = Number(deltaY) || 0;
    if (deltaMode === 1) {
        pixels *= 40;
    } else if (deltaMode === 2) {
        pixels *= 800;
    }
    const factor = Math.exp(-pixels * 0.0015);
    return Math.min(2, Math.max(0.5, factor));
}

// ---------------------------------------------------------------------------
// Цвета
// ---------------------------------------------------------------------------

function parseHex(hex) {
    const value = text(hex).trim();
    if (!COLOR_RE.test(value)) {
        return null;
    }
    return [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));
}

function toHex(rgb) {
    return `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
}

function channel(c) {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** Относительная яркость по WCAG: 0 — чёрный, 1 — белый. */
export function luminance(hex) {
    const rgb = parseHex(hex);
    if (!rgb) {
        return 0;
    }
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

/** Контраст цвета с белым листом: 1 — не видно, 21 — чёрный. */
export function contrastOnWhite(hex) {
    return 1.05 / (luminance(hex) + 0.05);
}

/**
 * Цвет линии на белом листе: как в файле, если читается; почти белый —
 * чёрный (белый в AutoCAD значит «цвет переднего плана»); светлый
 * (жёлтый, голубой, светло-зелёный, светло-серый) — темнее того же оттенка,
 * до контраста MIN_CONTRAST. Оттенок сохраняется: слой «жёлтый» остаётся
 * узнаваемым — оливковым, а не чёрным.
 */
export function sheetColor(hex) {
    const rgb = parseHex(hex);
    if (!rgb) {
        return "#000000";
    }
    const value = toHex(rgb);
    if (contrastOnWhite(value) >= MIN_CONTRAST) {
        return value;
    }
    if (Math.min(...rgb) >= 230) {
        return "#000000";
    }
    // Затемняем умножением каналов (оттенок тот же), ищем наибольший
    // множитель, при котором контраст уже достаточен.
    let low = 0;
    let high = 1;
    for (let step = 0; step < 24; step++) {
        const mid = (low + high) / 2;
        const candidate = toHex(rgb.map((c) => c * mid));
        if (contrastOnWhite(candidate) >= MIN_CONTRAST) {
            low = mid;
        } else {
            high = mid;
        }
    }
    return toHex(rgb.map((c) => c * low));
}

// ---------------------------------------------------------------------------
// Подписи
// ---------------------------------------------------------------------------

/**
 * «150 000» — неразрывный пробел между разрядами; четырёхзначные — слитно
 * («3455»), как принято в русском наборе и на чертежах.
 */
export function groupDigits(value) {
    const number = Math.round(Number(value) || 0);
    const sign = number < 0 ? "−" : "";
    const digits = String(Math.abs(number));
    if (digits.length <= 4) {
        return sign + digits;
    }
    return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

/** Миллиметры по-русски: 3455, 12,5, 0,25 — без хвоста «,0». */
export function formatMm(value) {
    const number = Math.abs(Number(value) || 0);
    if (number >= 100) {
        return groupDigits(number);
    }
    const digits = number >= 10 ? 1 : 2;
    return number
        .toFixed(digits)
        .replace(/0+$/, "")
        .replace(/\.$/, "")
        .replace(".", ",");
}

/** Габарит: «3455 × 1581 мм». */
export function sizeLabel(width, height) {
    if (!(Number(width) >= 0) || !(Number(height) >= 0)) {
        return "";
    }
    return `${formatMm(width)} × ${formatMm(height)} мм`;
}

/** Единицы: «единицы: мм» или «единицы не заданы — считаем мм». */
export function unitsLabel(units) {
    const source = units && typeof units === "object" ? units : {};
    if (source.assumed) {
        return "единицы не заданы — считаем мм";
    }
    const label = text(source.label);
    return label ? `единицы: ${label}` : "";
}

/** Слои по имени, как в АвтоКАДе: «0», «2», «10», «Контур», «Размеры». */
export function compareLayerNames(left, right) {
    return text(left).localeCompare(text(right), "ru", { numeric: true, sensitivity: "base" });
}

// ---------------------------------------------------------------------------
// Ответ сервера
// ---------------------------------------------------------------------------

/** Рамка слоя из ответа: четыре конечных числа по порядку, иначе null. */
function layerBox(raw) {
    if (!Array.isArray(raw) || raw.length !== 4) {
        return null;
    }
    const [x0, y0, x1, y1] = raw.map(Number);
    if (![x0, y0, x1, y1].every(Number.isFinite) || x1 < x0 || y1 < y0) {
        return null;
    }
    return { x0, y0, x1, y1 };
}

/**
 * Проверка ответа сервера (tools/dxf_render.py) перед тем, как класть его в
 * разметку. Строки путей — только команды и числа (никакой разметки), цвета —
 * только #rrggbb, номера слоёв и цветов — в своих списках. Негодный путь
 * выбрасывается и считается (dropped), окно показывает остальное.
 */
export function normalizeDrawing(raw) {
    const source = raw && typeof raw === "object" ? raw : {};
    if (!source.ok) {
        return {
            ok: false,
            reason: text(source.reason) || "Чертёж не удалось показать. Файл можно скачать.",
        };
    }
    const box = Array.isArray(source.viewbox) ? source.viewbox : [];
    const width = Number(box[0]);
    const height = Number(box[1]);
    if (!(width > 0) || !(height > 0) || !Number.isFinite(width) || !Number.isFinite(height)) {
        return { ok: false, reason: "Чертёж пришёл без размеров — показать нечего." };
    }
    const palette = (Array.isArray(source.palette) ? source.palette : []).map((color) =>
        sheetColor(color)
    );
    const rawLayers = Array.isArray(source.layers) ? source.layers : [];
    const layers = rawLayers.map((layer, index) => {
        const item = layer && typeof layer === "object" ? layer : {};
        const fileColor = COLOR_RE.test(text(item.color)) ? text(item.color).toLowerCase() : "#000000";
        return {
            id: index,
            name: text(item.name) || "0",
            color: sheetColor(fileColor),
            fileColor,
            on: item.on !== false,
            box: layerBox(item.box),
        };
    });
    const items = [];
    let dropped = 0;
    for (const item of Array.isArray(source.items) ? source.items : []) {
        if (!Array.isArray(item) || item.length < 4) {
            dropped++;
            continue;
        }
        const [layer, kind, color, d] = item;
        if (
            !Number.isInteger(layer) ||
            layer < 0 ||
            layer >= layers.length ||
            !(kind === 0 || kind === 1 || kind === 2) ||
            !Number.isInteger(color) ||
            color < 0 ||
            color >= palette.length ||
            typeof d !== "string" ||
            !d ||
            !D_RE.test(d)
        ) {
            dropped++;
            continue;
        }
        items.push({ layer, kind, color: palette[color], d });
    }
    if (!items.length) {
        return { ok: false, reason: "В чертеже нет ни одной линии — показывать нечего." };
    }
    const used = new Set(items.map((item) => item.layer));
    const shownLayers = layers
        .filter((layer) => used.has(layer.id))
        .sort((left, right) => compareLayerNames(left.name, right.name));
    const size = Array.isArray(source.size_mm) ? source.size_mm : [];
    const notes = (Array.isArray(source.notes) ? source.notes : []).map(text).filter(Boolean);
    if (dropped) {
        notes.push(`Не показано путей с ошибками: ${groupDigits(dropped)}.`);
    }
    return {
        ok: true,
        width,
        height,
        layers: shownLayers,
        items,
        notes,
        sizeLabel: size.length === 2 ? sizeLabel(size[0], size[1]) : "",
        unitsLabel: unitsLabel(source.units),
        layout: text(source.layout),
        dropped,
    };
}
