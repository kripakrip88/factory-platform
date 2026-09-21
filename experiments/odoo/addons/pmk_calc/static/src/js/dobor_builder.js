/**
 * Построитель профиля доборного элемента.
 *
 * Перенос редактора с ERPNext. Геометрия перенесена ДОСЛОВНО: по этим
 * развёрткам режут металл, и расхождение в формуле означало бы брак в цеху.
 * Менялась только оболочка — вместо страницы Frappe компонент Odoo, вместо
 * frappe.call запись прямо в поле записи.
 *
 * Модель профиля: start — точка начала, segs — полки [{len, dir}], где len в
 * миллиметрах, dir — направление в градусах. Из них считаются вершины, а из
 * вершин — всё остальное: углы гибов, развёртка, контур.
 *
 * Почему координаты рисуются в «мире», а не сразу в пикселях: полки задаются
 * в миллиметрах и могут быть и 20 мм, и 2000 мм. Чертёж вписывается в холст
 * отдельным шагом (computeFit), поэтому масштаб не протекает в геометрию.
 */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useRef, useState, onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const SVGNS = "http://www.w3.org/2000/svg";
const GRAB = 14;        // радиус захвата вершины, px
const FOLD_GAP = 8;     // зазор подгиба 180°, имитирует толщину металла
// Порог свободного вращения: пока курсор ближе ROT_FREE_R к центру ручки,
// это ещё клик, а не «кручу». Радиус, а не пройденный путь, потому что он
// закрывает сразу две беды:
//   1) дрожание руки при клике — это 1-3 px, до 24 px ему далеко (а на
//      планшете палец гуляет заметно сильнее мыши);
//   2) угол вокруг центра ручки у самого центра считается неустойчиво: на
//      8 px от центра сдвиг на один пиксель — это уже ~7°, планку швыряет.
//      На 24 px тот же пиксель даёт ~2.4° — так ей можно управлять.
// Сама ручка 42 px в поперечнике (scss .pmk-dobor__rot), её радиус 21, то есть
// порог — это «палец ушёл с ручки». Внутри порога вращение не применяется.
const ROT_FREE_R = 24;
const VIEW_W = 760;
const VIEW_H = 440;
// Шаг ручки вращения, в градусах dir. Минус здесь не опечатка: в verts()
// y = cur.y - len*sin(dir), то есть с ростом dir точка уходит ВВЕРХ по экрану
// (ось Y в SVG направлена вниз). Значит рост dir — это поворот ПРОТИВ часовой
// стрелки, а глиф ⟳ на ручке обещает ПО часовой — отсюда отрицательный шаг.
// В построителе ERPNext та же ручка делала ровно это же (s.dir -= 5).
const ROT_STEP = -5;
// Полоса внизу холста под знак замка. Отдавать её знаку обязательно: без
// резерва контур вписывается во всю высоту, и нижняя полка вместе с подписью
// размера ложится прямо на плашку. Серверный генератор эскиза резервирует
// такую же полосу (dobor_report.LOCK_BAND) — само ПРАВИЛО обязано совпадать,
// иначе на экране и в печати профиль вписан по-разному. Числа при этом разные
// и совпадать не могут: холсты разного размера (здесь 760x440, там 470x300).
// 100 = 68 (от низа холста до центра знака) + 22 (полвысоты плашки) + 10 воздуха.
const LOCK_BAND = 100;
// Цвет слоя краски, когда покрытие у позиции не выбрано. Служебный, а не
// «какой-нибудь металлический»: по нему сразу видно, что цвет НЕ выбран, и
// никто не примет его за покрытие. В серверном эскизе для того же случая свой
// цвет (dobor_report.NO_COATING_STROKE) — совпадать они не обязаны, совпадать
// должны настоящие цвета покрытий.
const PAINT_NO_COATING = "#f08fb0";
// Ниже этой яркости (0-255) цвет на тёмном холсте не читается — см.
// liftForDarkCanvas.
const PAINT_MIN_LUMA = 110;

/**
 * Разбор цвета покрытия. Зеркало серверного normalize_hex.
 *
 * ЕДИНСТВЕННОЕ правило разбора описано и реализовано в models/dobor.py,
 * функция normalize_hex — там же написано, почему оно обязано быть одно.
 * Здесь не второе правило, а его повторение: холст читает справочник
 * покрытий напрямую (иначе не перекрасится до сохранения), а серверный эскиз
 * получает уже нормализованный hex из снимка профиля. Пока правил было два,
 * значение без решётки («b9c2cc») красило печать и НЕ красило холст — тот
 * рисовал служебный «покрытие не выбрано». Правите здесь — правьте и там.
 *
 * Правило: срезать пробелы, дописать решётку если её нет, принять только
 * шесть hex-цифр, всё остальное — null, то есть «цвета нет».
 */
function normalizeHex(value) {
    let text = (value || "").trim();
    if (!text) {
        return null;
    }
    if (!text.startsWith("#")) {
        text = "#" + text;
    }
    return /^#[0-9a-f]{6}$/i.test(text) ? text : null;
}

/**
 * Поднять тёмный цвет покрытия до различимого на тёмном холсте.
 *
 * Холст построителя тёмный, и тёмные покрытия на нём пропадают: у RAL 8017
 * «Шоколад» это #3a2419, яркость 40 из 255 — тонкий пунктир сливается с фоном.
 * Тон сохраняем, подмешивая белый ровно до порога; светлые покрытия (Цинк
 * #b9c2cc, RAL 9003 #f1f0ea) не трогаем вовсе.
 *
 * В печати задача обратная — там лист белый, и цвет наоборот притушается
 * (dobor_report._darken, множитель из ERPNext). Один и тот же цвет, разные
 * фоны: подгонять их под одно число нельзя, иначе одна из сторон ослепнет.
 */
function liftForDarkCanvas(hex) {
    const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    if (luma >= PAINT_MIN_LUMA) {
        return hex;
    }
    const t = (PAINT_MIN_LUMA - luma) / (255 - luma);
    return "#" + rgb
        .map((c) => Math.round(c + (255 - c) * t).toString(16).padStart(2, "0"))
        .join("");
}

export class DoborBuilder extends Component {
    static template = "pmk_calc.DoborBuilder";
    static props = { ...standardFieldProps };

    setup() {
        this.svgRef = useRef("svg");
        this.wrapRef = useRef("wrap");
        this.editRef = useRef("edit");
        this.rotRef = useRef("rot");

        this.state = useState({
            hemLeft: false, hemRight: false, hemLen: 15,
            lock: false, growEnd: true, paintOn: false,
            developed: 0, bends: 0, flanges: 0,
        });

        // Состояние профиля живёт вне реактивности: оно меняется по десять раз
        // за секунду при перетаскивании, и на каждое движение мыши
        // перерисовывать весь компонент незачем — SVG обновляется напрямую.
        this.geom = {
            start: { x: 180, y: 300 },
            segs: [],
            hemLeftDir: 1, hemRightDir: -1,
            paintSide: 1,
        };
        this.view = { k: 1, cx: VIEW_W / 2, cy: VIEW_H / 2, areaH: VIEW_H };
        this.dragIdx = -1;
        this.editKind = null;
        this.editIdx = -1;
        // Ключи снимка, которых построитель не знает (их пишет сервер).
        // Заполняется в loadFromField, переносится в saveToField.
        this.snapExtra = {};
        // Состояние свободного вращения: {cx, cy, prev, free} или null.
        // Тоже вне реактивности — меняется на каждое движение указателя.
        this.rot = null;

        onMounted(() => {
            this.loadFromField();
            this.redraw();
        });
        onPatched(() => {
            // Покрытие выбирают НЕ в построителе, а в карточке позиции справа.
            // OWL перерисует шаблон, но SVG мы строим руками, и сам он не
            // обновится — перерисовываем, когда цвет приехал новый. Сравнение
            // с уже нарисованным отсекает все прочие перерисовки формы: их
            // много, а холст тяжёлый.
            if (this.paintDrawn !== this.paintStroke()) {
                this.redraw();
            }
        });
        onWillUnmount(() => this.flushEdit());
    }

    // ── обмен с полем записи ───────────────────────────────────────────────

    loadFromField() {
        let snap = null;
        try {
            snap = JSON.parse(this.props.record.data[this.props.name] || "null");
        } catch {
            snap = null;
        }
        // Снимок несёт ключи, которых построитель не знает: paintHex туда
        // пишет сервер (DoborOrderLine._sync_snapshot_coating), а печатный
        // лист читает из снимка ещё и comment — его клал построитель ERPNext.
        // Держим исходный объект,
        // чтобы saveToField() не стирал чужое — см. там же. Старый формат
        // (голый массив полок) не берём: складывать в него ключи некуда.
        this.snapExtra = snap && !Array.isArray(snap) && typeof snap === "object" ? snap : {};
        if (!snap || !Array.isArray(snap.segs)) {
            return;
        }
        this.geom.start = snap.start || { x: 180, y: 300 };
        this.geom.segs = snap.segs.map((s) => ({ ...s }));
        this.geom.hemLeftDir = snap.hemLeftDir ?? 1;
        this.geom.hemRightDir = snap.hemRightDir ?? -1;
        this.geom.paintSide = snap.paintSide ?? 1;
        this.state.hemLeft = !!snap.hemLeft;
        this.state.hemRight = !!snap.hemRight;
        this.state.hemLen = snap.hemLen ?? 15;
        this.state.lock = !!snap.lock;
        this.state.paintOn = !!snap.paintOn;
    }

    saveToField() {
        const snap = {
            // Чужие ключи снимка — первыми, чтобы свои их перекрывали.
            // Собирать снимок с нуля нельзя: он терял paintHex, сервер в том же
            // write() вписывал цвет обратно — лишняя запись в базу и мигание
            // цвета на холсте, пока запись перечитывается.
            ...this.snapExtra,
            start: { ...this.geom.start },
            segs: this.geom.segs.map((s) => ({ ...s })),
            hemLeft: this.state.hemLeft,
            hemRight: this.state.hemRight,
            hemLeftDir: this.geom.hemLeftDir,
            hemRightDir: this.geom.hemRightDir,
            hemLen: this.state.hemLen,
            lock: this.state.lock,
            paintOn: this.state.paintOn,
            paintSide: this.geom.paintSide,
        };
        this.snapExtra = snap;  // следующее сохранение опять унесёт чужие ключи
        this.props.record.update({ [this.props.name]: JSON.stringify(snap) });
    }

    // ── геометрия (перенесена без изменений) ───────────────────────────────

    verts() {
        const v = [{ ...this.geom.start }];
        let cur = { ...this.geom.start };
        for (const s of this.geom.segs) {
            const r = (s.dir * Math.PI) / 180;
            cur = { x: cur.x + s.len * Math.cos(r), y: cur.y - s.len * Math.sin(r) };
            v.push({ x: cur.x, y: cur.y });
        }
        return v;
    }

    /** Знаковое отклонение направления на гибе i. */
    bendAngle(i) {
        let d = this.geom.segs[i].dir - this.geom.segs[i - 1].dir;
        while (d > 180) d -= 360;
        while (d < -180) d += 360;
        return d;
    }

    /** Угол МЕЖДУ полками, 0..180 — то, что понимает человек. */
    flangeAngle(i) {
        return 180 - Math.abs(this.bendAngle(i));
    }

    /** Задать угол между полками: поворачиваем весь хвост профиля. */
    applyFlangeAngle(i, want) {
        want = Math.max(0, Math.min(180, want));
        const cur = this.bendAngle(i);
        const sign = cur < 0 ? -1 : 1;
        const delta = sign * (180 - want) - cur;
        for (let k = i; k < this.geom.segs.length; k++) {
            this.geom.segs[k].dir += delta;
        }
    }

    /** Подгиб 180°: полки почти сложены. Наша доработка, порог тот же. */
    isFold(s) {
        return s >= 1 && s < this.geom.segs.length && Math.abs(this.bendAngle(s)) > 170;
    }

    computeFit() {
        const v = this.verts();
        if (!v.length) {
            this.view = { k: 1, cx: VIEW_W / 2, cy: VIEW_H / 2, areaH: VIEW_H };
            return;
        }
        let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
        for (const p of v) {
            minx = Math.min(minx, p.x); maxx = Math.max(maxx, p.x);
            miny = Math.min(miny, p.y); maxy = Math.max(maxy, p.y);
        }
        // При включённом замке низ холста занят знаком, и вписывать контур
        // нужно в высоту НАД ним. Условие ровно то же, что на сервере
        // (dobor_report: band = LOCK_BAND if lock else 0) — иначе экран и
        // печать расходятся по вписыванию, как расходились до этой правки.
        const areaH = VIEW_H - (this.state.lock ? LOCK_BAND : 0);
        const bw = Math.max(1, maxx - minx), bh = Math.max(1, maxy - miny), pad = 100;
        let k = Math.min((VIEW_W - pad) / bw, (areaH - pad) / bh);
        // Масштаб ограничен ТОЛЬКО снизу. Раньше здесь стоял ещё и потолок
        // Math.min(1.8, k) — он приехал из построителя ERPNext (metal_calculator,
        // page/dobor_builder/dobor_builder.js, computeFit) без пояснений. Там
        // холст был высотой 440 px во всю страницу, единица viewBox равнялась
        // пикселю, и 1.8 px на миллиметр хватало: профиль 85×61 занимал
        // 153×110 px. Здесь холст живёт в диалоге и вписывается в остаток
        // высоты: на форме владельца (замер 21.09.2026) это 269 px, масштаб
        // экрана 269/440 = 0.61, и тот же профиль сжимался до 93×67 px —
        // подписи размеров не читались. Потолок отменял вписывание для любого
        // профиля мельче ~370×190 мм, то есть почти для всех доборок. Без него
        // 85×61 занимает 334×240 единиц viewBox — весь холст, как и большой
        // профиль. Серверный эскиз (dobor_report.sketch_svg) потолка не имел
        // никогда: экран и печать теперь вписывают контур по одному правилу.
        //
        // Подписи при этом друг на друга не налезают: кегль у них фиксирован,
        // а расстояния между ними растут вместе с k — чем крупнее чертёж, тем
        // просторнее подписям. Тесно им наоборот при МАЛОМ k (длинная планка с
        // коротким загибом: 2000 и 15 мм дают k ≈ 0.33, загиб — 5 px), и это
        // потолок никогда не лечил. За поле pad (50 с каждой стороны в
        // единицах viewBox) подписи не выходят: наибольший вынос у подписи
        // длины по вертикальной полке — 16 + полширины «2500» ≈ 32 — и у
        // подписи угла — 20 + полширины «135°» ≈ 33; оба меньше 50.
        //
        // Нижний зажим остаётся: k делит в W() (холст → мир) при
        // перетаскивании, и 0.05 не даёт ему уйти в ноль на ошибочно
        // огромной длине (k < 0.05 — это контур шире 13 м).
        k = Math.max(0.05, k);
        this.view = { k, cx: (minx + maxx) / 2, cy: (miny + maxy) / 2, areaH };
    }

    /** Мир → холст. */
    D(p) {
        return {
            x: VIEW_W / 2 + (p.x - this.view.cx) * this.view.k,
            // По вертикали центр — середина ОСТАВШЕЙСЯ площади, а не всего
            // холста: иначе резерв под замок съедался бы поровну сверху и
            // снизу и знак снова оказался бы под контуром. Так же в
            // dobor_report (там центрируют по area_h / 2).
            y: this.view.areaH / 2 + (p.y - this.view.cy) * this.view.k,
        };
    }

    /** Холст → мир: обратное преобразование, нужно при перетаскивании. */
    W(p) {
        return {
            x: this.view.cx + (p.x - VIEW_W / 2) / this.view.k,
            y: this.view.cy + (p.y - this.view.areaH / 2) / this.view.k,
        };
    }

    svgPoint(ev) {
        const svg = this.svgRef.el;
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX;
        pt.y = ev.clientY;
        const ctm = svg.getScreenCTM();
        if (!ctm) {
            return { x: 0, y: 0 };
        }
        const inv = pt.matrixTransform(ctm.inverse());
        return { x: inv.x, y: inv.y };
    }

    // ── расчёт для панели результатов ──────────────────────────────────────

    recompute() {
        const segs = this.geom.segs;
        const flangeSum = segs.reduce((a, s) => a + (s.len || 0), 0);
        const hemCount = (this.state.hemLeft ? 1 : 0) + (this.state.hemRight ? 1 : 0);
        this.state.developed = Math.round((flangeSum + hemCount * this.state.hemLen) * 100) / 100;
        // Завальцовка — это подгиб 180°, то есть тоже гиб: на П-образном
        // профиле из трёх полок выходит 4 гиба, два угла и две завальцовки.
        this.state.bends = Math.max(0, segs.length - 1) + hemCount + (this.state.lock ? 2 : 0);
        this.state.flanges = segs.length;
    }

    // ── рисование ──────────────────────────────────────────────────────────

    /**
     * Цвет слоя краски — цвет выбранного покрытия.
     *
     * Hex берём из записи (coating_hex → coating_id.hex_color), а не из снимка
     * профиля: покрытие меняют в колонке справа, и холст должен перекраситься
     * сразу, не дожидаясь сохранения. В снимок тот же цвет вписывает сервер
     * (DoborOrderLine._sync_snapshot_coating) — так у ключа один писатель, а
     * печатный лист и список рисуют ровно то, что было выбрано.
     *
     * Формат разбираем общей функцией normalizeHex — справочник покрытий
     * открыт на правку, и в поле цвета может оказаться что угодно, но принять
     * или отвергнуть значение холст и печать обязаны ОДИНАКОВО.
     */
    paintStroke() {
        const hex = normalizeHex(this.props.record.data.coating_hex);
        if (!hex) {
            return PAINT_NO_COATING;
        }
        return liftForDarkCanvas(hex);
    }

    mk(tag, attrs) {
        const el = document.createElementNS(SVGNS, tag);
        for (const k in attrs) {
            el.setAttribute(k, attrs[k]);
        }
        return el;
    }

    redraw() {
        const svg = this.svgRef.el;
        if (!svg) {
            return;
        }
        if (this.dragIdx < 0) {
            this.computeFit();
        }
        while (svg.firstChild) {
            svg.removeChild(svg.firstChild);
        }

        const segs = this.geom.segs;
        const v = this.verts().map((p) => this.D(p));
        const INK = "#f0f4f8";
        // Считаем цвет краски всегда, даже когда слой выключен: по нему
        // onPatched понимает, что покрытие сменили и холст пора перерисовать.
        const paint = this.paintStroke();
        this.paintDrawn = paint;

        if (v.length >= 2) {
            const unitv = (a, b) => {
                const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1;
                return { x: dx / l, y: dy / l };
            };

            // Слой краски: пунктир, отведённый по нормали в сторону покрытия.
            // Рисуем ДО контура, чтобы линия профиля осталась главной.
            if (this.state.paintOn) {
                const off = v.map((p, i) => {
                    let nx = 0, ny = 0;
                    if (i < v.length - 1) {
                        const d = unitv(p, v[i + 1]); nx += -d.y; ny += d.x;
                    }
                    if (i > 0) {
                        const d = unitv(v[i - 1], p); nx += -d.y; ny += d.x;
                    }
                    const l = Math.hypot(nx, ny) || 1;
                    return `${p.x + (nx / l) * 6 * this.geom.paintSide},${p.y + (ny / l) * 6 * this.geom.paintSide}`;
                }).join(" ");
                svg.appendChild(this.mk("polyline", {
                    points: off, fill: "none", stroke: paint,
                    "stroke-width": "1.8", "stroke-dasharray": "4 3", "stroke-linejoin": "round",
                }));
            }

            // Контур. У подгиба 180° рисуется параллельная линия с разворотом,
            // а смещение НАКОПИТЕЛЬНОЕ — иначе при нескольких подгибах подряд
            // полки накладываются друг на друга и пропадают.
            let shift = { x: 0, y: 0 };
            let d = `M ${v[0].x} ${v[0].y}`;
            for (let s = 0; s < segs.length; s++) {
                if (this.isFold(s)) {
                    const a = { x: v[s].x + shift.x, y: v[s].y + shift.y };
                    const dir = unitv(v[s], v[s + 1]);
                    const n = { x: -dir.y, y: dir.x };
                    const side = (this.bendAngle(s) > 0 ? -1 : 1) * (segs[s].foldFlip ? -1 : 1);
                    shift = { x: shift.x + n.x * side * FOLD_GAP, y: shift.y + n.y * side * FOLD_GAP };
                    const aOff = { x: v[s].x + shift.x, y: v[s].y + shift.y };
                    const uin = unitv(v[s - 1], v[s]);
                    const cross = (aOff.x - a.x) * uin.y - (aOff.y - a.y) * uin.x;
                    const sweep = cross > 0 ? 0 : 1;
                    const b = { x: v[s + 1].x + shift.x, y: v[s + 1].y + shift.y };
                    d += ` A ${FOLD_GAP / 2} ${FOLD_GAP / 2} 0 0 ${sweep} ${aOff.x} ${aOff.y} L ${b.x} ${b.y}`;
                } else {
                    const b = { x: v[s + 1].x + shift.x, y: v[s + 1].y + shift.y };
                    d += ` L ${b.x} ${b.y}`;
                }
            }
            svg.appendChild(this.mk("path", {
                d, fill: "none", stroke: INK, "stroke-width": "3.2",
                "stroke-linejoin": "round", "stroke-linecap": "round",
            }));

            // Завальцовка — полукруг на краю полки.
            const drawHem = (edge, u, flip) => {
                const nx = -u.y * flip, ny = u.x * flip, r = 4.5, L = 16;
                const sx = edge.x, sy = edge.y;
                const bx = sx + nx * 2 * r, by = sy + ny * 2 * r;
                const ex = bx + u.x * L, ey = by + u.y * L, k = (r * 4) / 3;
                svg.appendChild(this.mk("path", {
                    d: `M ${sx} ${sy} C ${sx - u.x * k} ${sy - u.y * k} ${bx - u.x * k} ${by - u.y * k} ${bx} ${by} L ${ex} ${ey}`,
                    fill: "none", stroke: INK, "stroke-width": "3.2",
                    "stroke-linecap": "round", "stroke-linejoin": "round",
                }));
                const t = this.mk("text", {
                    x: (bx + ex) / 2 + nx * 12, y: (by + ey) / 2 + ny * 12 + 3,
                    "text-anchor": "middle", "font-size": "9.5", "font-weight": "700",
                    fill: "#9fb0c4",
                });
                t.textContent = "завальц. " + this.state.hemLen;
                svg.appendChild(t);
            };
            if (this.state.hemLeft && segs.length >= 1) {
                drawHem(v[0], unitv(v[0], v[1]), this.geom.hemLeftDir);
            }
            if (this.state.hemRight && segs.length >= 1) {
                drawHem(v[v.length - 1], unitv(v[v.length - 1], v[v.length - 2]), this.geom.hemRightDir);
            }

            // Замок — знак в фиксированной зоне снизу по центру, как в ERPNext:
            // на самом контуре его не нарисовать, это способ соединения планок,
            // а не элемент сечения.
            if (this.state.lock && segs.length >= 1) {
                const cx = VIEW_W / 2, cy = VIEW_H - 68;
                svg.appendChild(this.mk("rect", {
                    x: cx - 26, y: cy - 22, width: 52, height: 44, rx: 9,
                    fill: "#ffffff", stroke: "#1a1f29", "stroke-width": "1.4",
                }));
                const g = this.mk("g", {
                    transform: `translate(${cx},${cy}) scale(0.95)`,
                    stroke: "#111", "stroke-width": "2.4",
                    "stroke-linecap": "round", "stroke-linejoin": "round", fill: "none",
                });
                for (const d of ["M -20 7 L -8 -3", "M 20 7 L 8 -3",
                                 "M -3 0 l 3 5", "M 1 -1 l 3 5", "M 5 -2 l 2 5"]) {
                    g.appendChild(this.mk("path", { d }));
                }
                g.appendChild(this.mk("path", { d: "M -8 -3 Q -1 2 3 -1 Q 7 -4 9 -2", "stroke-width": "2.8" }));
                svg.appendChild(g);
                const lt = this.mk("text", {
                    x: cx, y: cy + 34, "text-anchor": "middle",
                    "font-size": "9", "font-weight": "700", fill: "#e6ebf2",
                });
                lt.textContent = "ЗАМОК";
                svg.appendChild(lt);
            }
        }

        // Подписи длин — по ним же и правят размер.
        for (let i = 0; i < segs.length; i++) {
            const a = v[i], b = v[i + 1];
            const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
            let nx = -(b.y - a.y), ny = b.x - a.x;
            const nl = Math.hypot(nx, ny) || 1;
            nx = (nx / nl) * 16; ny = (ny / nl) * 16;
            const t = this.mk("text", {
                x: mx + nx, y: my + ny + 4, "text-anchor": "middle",
                "font-size": "13", "font-weight": "700", fill: "#8ab4f8",
                class: "pmk-dobor-len", "data-idx": i,
            });
            t.textContent = String(Math.round(segs[i].len));
            svg.appendChild(t);
        }

        // Углы между полками. Подпись выносится НАРУЖУ ПО БИССЕКТРИСЕ, иначе
        // она ложится прямо на линию профиля и мешает читать чертёж — в
        // ERPNext это решено так же.
        for (let i = 1; i < segs.length; i++) {
            const ba = Math.abs(this.bendAngle(i));
            // На подгибе 180° угла нет — там метка подгиба, а не градусы.
            if (ba < 1 || ba > 170) {
                continue;
            }
            const p = v[i], a = v[i - 1], b = v[i + 1];

            // Единичные векторы от вершины к соседям.
            let t1x = a.x - p.x, t1y = a.y - p.y;
            const l1 = Math.hypot(t1x, t1y) || 1;
            t1x /= l1; t1y /= l1;
            let t2x = b.x - p.x, t2y = b.y - p.y;
            const l2 = Math.hypot(t2x, t2y) || 1;
            t2x /= l2; t2y /= l2;

            // Внутренняя биссектриса, взятая с минусом — то есть наружу.
            let bx = t1x + t2x, by = t1y + t2y;
            const bl = Math.hypot(bx, by);
            let ox, oy;
            if (bl < 0.15) {
                // Почти развёрнутый угол: биссектриса вырождается, уходим по нормали.
                ox = -t2y; oy = t2x;
            } else {
                ox = -bx / bl; oy = -by / bl;
            }

            svg.appendChild(this.mk("circle", {
                cx: p.x, cy: p.y, r: 11, fill: "#f0a04b", opacity: 0.14,
            }));
            const t = this.mk("text", {
                x: p.x + ox * 20, y: p.y + oy * 20 + 3.5, "text-anchor": "middle",
                "font-size": "11", "font-weight": "700", fill: "#f0a04b",
                class: "pmk-dobor-bend", "data-idx": i,
            });
            t.textContent = Math.round(this.flangeAngle(i)) + "°";
            svg.appendChild(t);
        }

        // Вершины: за них тянут.
        v.forEach((p, i) => {
            svg.appendChild(this.mk("circle", {
                cx: p.x, cy: p.y, r: 5, fill: "#8ab4f8",
                class: "pmk-dobor-vert", "data-idx": i,
            }));
        });

        this.recompute();
    }

    // ── взаимодействие ─────────────────────────────────────────────────────

    nearestVertex(pv) {
        const dv = this.verts().map((p) => this.D(p));
        let best = -1, bd = GRAB;
        dv.forEach((q, i) => {
            const dist = Math.hypot(q.x - pv.x, q.y - pv.y);
            if (dist < bd) { bd = dist; best = i; }
        });
        return best;
    }

    onCanvasPointerDown(ev) {
        this.flushEdit();
        const p = this.svgPoint(ev);

        const lenLabel = ev.target.closest?.(".pmk-dobor-len");
        if (lenLabel) {
            this.openEdit("len", +lenLabel.dataset.idx, ev);
            return;
        }
        const bendLabel = ev.target.closest?.(".pmk-dobor-bend");
        if (bendLabel) {
            this.openEdit("bend", +bendLabel.dataset.idx, ev);
            return;
        }

        const idx = this.nearestVertex(p);
        if (idx >= 0) {
            this.dragIdx = idx;
            // Захват ставим на САМ ХОЛСТ, а не на кружок вершины (ev.target).
            // Кружок живёт до первого же движения: redraw() стирает всё
            // содержимое svg и рисует заново, элемент с захватом исчезает, и
            // браузер захват снимает. Дальше палец или мышь уходят за край
            // холста — «отпустил» не приходит никуда, dragIdx остаётся
            // взведённым, полка продолжает тянуться за курсором БЕЗ нажатия,
            // а вписывание при взведённом dragIdx намеренно пропускается
            // (см. redraw). Снаружи это выглядит как «полка уехала за окно и
            // с ней ничего не сделаешь». Холст не пересоздаётся никогда,
            // поэтому захват на нём переживает любую перерисовку.
            this.svgRef.el?.setPointerCapture?.(ev.pointerId);
            return;
        }
        this.addPoint(this.W(p));
    }

    onCanvasPointerMove(ev) {
        if (this.dragIdx < 0) {
            return;
        }
        // Страховка от залипшего перетаскивания. Если кнопка уже не нажата
        // (buttons === 0), а мы всё ещё «тащим» — значит «отпустил» до нас не
        // доехало: отпустили за пределами холста, окно потеряло фокус, жест
        // отменила система. Без этой проверки полка молча ходит за курсором и
        // не вписывается обратно, потому что вписывание при взведённом dragIdx
        // пропускается. Захват на холсте (см. onCanvasPointerDown) закрывает
        // главный случай, но не все — этот выход закрывает остальные.
        if (ev.buttons === 0) {
            this.onCanvasPointerUp();
            return;
        }
        const w = this.W(this.svgPoint(ev));
        const segs = this.geom.segs;
        const i = this.dragIdx;

        if (i === 0) {
            // Тянем начало: двигаем точку старта, первая полка пересчитывается.
            this.geom.start = { x: w.x, y: w.y };
            if (segs.length) {
                const v = this.verts();
                const dx = v[1].x - w.x, dy = -(v[1].y - w.y);
                segs[0].len = Math.max(1, Math.round(Math.hypot(dx, dy)));
                segs[0].dir = Math.round((Math.atan2(dy, dx) * 180) / Math.PI);
            }
        } else {
            const v = this.verts();
            const prev = v[i - 1];
            const dx = w.x - prev.x, dy = -(w.y - prev.y);
            segs[i - 1].len = Math.max(1, Math.round(Math.hypot(dx, dy)));
            segs[i - 1].dir = Math.round((Math.atan2(dy, dx) * 180) / Math.PI);
        }
        this.redraw();
    }

    onCanvasPointerUp(ev) {
        if (this.dragIdx >= 0) {
            this.dragIdx = -1;
            // Отпускаем захват явно. Браузер снял бы его и сам, но тогда
            // прилетит lostpointercapture и зайдёт сюда второй раз — лишняя
            // перерисовка и лишняя запись в поле. Здесь dragIdx уже сброшен,
            // поэтому повторный заход просто ничего не сделает.
            const svg = this.svgRef.el;
            if (svg && ev?.pointerId !== undefined && svg.hasPointerCapture?.(ev.pointerId)) {
                // Проверка обязательна: releasePointerCapture на незахваченном
                // указателе бросает NotFoundError, а сюда приходят и события
                // без захвата (pointerleave, наша страховка по buttons === 0).
                svg.releasePointerCapture(ev.pointerId);
            }
            // Вписывание считается именно здесь: пока тащат, оно намеренно
            // пропускается, чтобы чертёж не дёргался под рукой.
            this.redraw();
            this.saveToField();
        }
    }

    addPoint(p) {
        const v = this.verts();
        const segs = this.geom.segs;
        if (this.state.growEnd) {
            const last = v[v.length - 1];
            const dx = p.x - last.x, dy = -(p.y - last.y);
            const len = Math.round(Math.hypot(dx, dy));
            if (len < 5) { return; }
            segs.push({ len, dir: Math.round((Math.atan2(dy, dx) * 180) / Math.PI) });
        } else {
            const first = v[0];
            const dx = first.x - p.x, dy = -(first.y - p.y);
            const len = Math.round(Math.hypot(dx, dy));
            if (len < 5) { return; }
            this.geom.start = { x: p.x, y: p.y };
            segs.unshift({ len, dir: Math.round((Math.atan2(dy, dx) * 180) / Math.PI) });
        }
        this.redraw();
        this.saveToField();
    }

    openEdit(kind, idx, ev) {
        const input = this.editRef.el;
        const wrap = this.wrapRef.el;
        if (!input || !wrap) { return; }
        const r = wrap.getBoundingClientRect();
        this.editKind = kind;
        this.editIdx = idx;
        input.value = kind === "len"
            ? String(Math.round(this.geom.segs[idx].len))
            : String(Math.round(this.flangeAngle(idx)));
        input.style.left = (ev.clientX - r.left - 31) + "px";
        input.style.top = (ev.clientY - r.top - 12) + "px";
        input.style.display = "block";
        setTimeout(() => { input.focus(); input.select(); }, 0);
    }

    flushEdit() {
        const input = this.editRef.el;
        if (this.editKind == null || !input) { return; }
        const value = parseFloat(input.value);
        if (!Number.isNaN(value)) {
            if (this.editKind === "len") {
                this.geom.segs[this.editIdx].len = Math.max(1, value);
            } else {
                this.applyFlangeAngle(this.editIdx, value);
            }
        }
        input.style.display = "none";
        this.editKind = null;
        this.redraw();
        this.saveToField();
    }

    onEditKeydown(ev) {
        if (ev.key === "Enter") { this.flushEdit(); }
        if (ev.key === "Escape") {
            this.editRef.el.style.display = "none";
            this.editKind = null;
        }
    }

    // ── команды панели ─────────────────────────────────────────────────────

    undo() {
        if (!this.geom.segs.length) { return; }
        if (this.state.growEnd) { this.geom.segs.pop(); } else { this.geom.segs.shift(); }
        this.redraw();
        this.saveToField();
    }

    clearAll() {
        this.geom.segs = [];
        this.geom.start = { x: 180, y: 300 };
        this.redraw();
        this.saveToField();
    }

    /** Зеркало: вместе с профилем разворачиваются завальцовка и сторона окраски. */
    mirror() {
        for (const s of this.geom.segs) { s.dir = -s.dir; }
        this.geom.hemLeftDir *= -1;
        this.geom.hemRightDir *= -1;
        this.geom.paintSide *= -1;
        this.redraw();
        this.saveToField();
    }

    rotate(deg) {
        for (const s of this.geom.segs) { s.dir += deg; }
        this.redraw();
        this.saveToField();
    }

    // ── вращение ──────────────────────────────────────────────────────────
    //
    // Ручка одна и работает как верньер приёмника: зажал и повёл вокруг неё —
    // планка идёт за курсором на произвольный угол, отпустил не сдвинувшись —
    // шаг ROT_STEP. Так было в построителе ERPNext, и владелец крутит эскиз
    // именно так, когда ему нужен угол «на глаз», а не кратный пяти.
    //
    // Отдельных кнопок «влево/вправо» нет намеренно: при переносе их завели, и
    // обе показывали стрелку в сторону, ПРОТИВОПОЛОЖНУЮ реальному повороту (см.
    // ROT_STEP), а клик по ручке повторял одну из них. Кнопка, которая крутит
    // не туда, куда нарисована, хуже отсутствующей кнопки.
    //
    // Указатель захватывается (setPointerCapture), поэтому вести можно куда
    // угодно — хоть за пределы окна: события всё равно придут ручке.

    /** Угол курсора относительно центра ручки, в градусах экрана. */
    rotAngle(ev) {
        return (Math.atan2(ev.clientY - this.rot.cy, ev.clientX - this.rot.cx) * 180) / Math.PI;
    }

    startRotate(ev) {
        if (!this.geom.segs.length) { return; }
        // Без preventDefault браузер начинает своё: выделение текста мышью и
        // подтаскивание страницы пальцем (прокрутку глушит ещё touch-action
        // на самой ручке, но одного CSS мало — ниже есть и pointercancel).
        ev.preventDefault();
        const el = this.rotRef.el;
        const r = el.getBoundingClientRect();
        this.rot = {
            cx: r.left + r.width / 2,
            cy: r.top + r.height / 2,
            prev: null,   // базовый угол; ставится в момент выхода за порог
            free: false,  // было ли настоящее вращение (тогда клик не считаем)
        };
        el.setPointerCapture?.(ev.pointerId);
    }

    onRotateMove(ev) {
        if (!this.rot) { return; }
        const dx = ev.clientX - this.rot.cx, dy = ev.clientY - this.rot.cy;
        if (Math.hypot(dx, dy) < ROT_FREE_R) {
            // Вернулись к центру — сбрасываем базу, чтобы при следующем выходе
            // за порог планка не прыгнула на угол, «накопленный» в мёртвой зоне.
            this.rot.prev = null;
            return;
        }
        const a = this.rotAngle(ev);
        if (this.rot.prev === null) {
            this.rot.prev = a;
            this.rot.free = true;
            return;
        }
        let d = a - this.rot.prev;
        // Через ±180° разность скачет на 360°: без нормализации один пиксель
        // движения обернулся бы полным оборотом в dir. Геометрию это не
        // испортило бы (синус с косинусом периодичны), но в снимке профиля
        // копились бы числа вида 3700°, а их потом читать людям.
        while (d > 180) { d -= 360; }
        while (d < -180) { d += 360; }
        this.rot.prev = a;
        // Экранный угол растёт по часовой стрелке (ось Y вниз), а dir — против
        // (в verts() y = cur.y - len*sin). Поэтому вычитаем: планка идёт ЗА
        // курсором, а не против него.
        for (const s of this.geom.segs) { s.dir -= d; }
        this.redraw();
    }

    endRotate() {
        const rot = this.rot;
        if (!rot) { return; }
        this.rot = null;
        if (rot.free) {
            this.saveToField();   // рисовали уже по ходу, осталось сохранить
            return;
        }
        // Зажали и отпустили на месте — обычный шаг. Направление задано
        // знаком ROT_STEP, там же разобрано, почему он отрицательный.
        this.rotate(ROT_STEP);
    }

    /** Жест перехватила система (звонок, свайп ОС) — просто закрываем сессию. */
    cancelRotate() {
        const rot = this.rot;
        this.rot = null;
        if (rot?.free) { this.saveToField(); }
    }

    /**
     * Клавиатура: Enter/Space на ручке дают click с detail === 0. У клика
     * мышью detail >= 1, и его мы игнорируем — поворот уже сделал endRotate,
     * иначе вышло бы два шага за одно нажатие. Ручка осталась <button> (а не
     * <div>, как в ERPNext) именно ради этого: с клавиатуры её тоже крутят.
     */
    onRotateClick(ev) {
        if (ev.detail === 0) { this.rotate(ROT_STEP); }
    }

    /**
     * Выравнивание: самую длинную полку — горизонтально. Перенесено из
     * построителя ERPNext (alignMinBox) вместе с особым случаем симметрии.
     */
    alignFlat() {
        const segs = this.geom.segs;
        if (!segs.length) { return; }
        let maxLen = -1;
        for (const s of segs) { maxLen = Math.max(maxLen, s.len); }
        // Допуск 0.5 мм: длины приходят и из перетаскивания (там целые), и из
        // ручного ввода (там дробные), строгое равенство ловило бы не всё.
        const long = [];
        segs.forEach((s, i) => { if (Math.abs(s.len - maxLen) < 0.5) { long.push(i); } });

        if (long.length === 2 && long[1] === long[0] + 1) {
            // Две одинаковые длинные полки подряд — это симметричный «домик»
            // (конёк). Класть его длинной полкой горизонтально бессмысленно:
            // ставим по оси симметрии — биссектриса между полками смотрит
            // вниз (-90° в dir), конёк оказывается сверху.
            const i = long[0];
            const a1 = ((segs[i].dir + 180) * Math.PI) / 180;   // первая полка — от вершины
            const a2 = (segs[i + 1].dir * Math.PI) / 180;
            const bx = Math.cos(a1) + Math.cos(a2), by = Math.sin(a1) + Math.sin(a2);
            const delta = -90 - (Math.atan2(by, bx) * 180) / Math.PI;
            for (const s of segs) { s.dir += delta; }
        } else {
            const degr = segs[long[0]].dir;
            for (const s of segs) { s.dir -= degr; }
        }
        this.redraw();
        this.saveToField();
    }

    toggle(key) {
        this.state[key] = !this.state[key];
        this.redraw();
        this.saveToField();
    }

    /** Развернуть завальцовку на другую сторону полки. */
    flipHem(side) {
        if (side === "left") {
            this.geom.hemLeftDir *= -1;
        } else {
            this.geom.hemRightDir *= -1;
        }
        this.redraw();
        this.saveToField();
    }

    /** Сторона покрытия: на какую сторону профиля лёг лак. */
    flipPaint() {
        this.geom.paintSide *= -1;
        this.redraw();
        this.saveToField();
    }

    onHemLenChange(ev) {
        this.state.hemLen = Math.max(0, parseFloat(ev.target.value) || 0);
        this.redraw();
        this.saveToField();
    }
}

registry.category("fields").add("pmk_dobor_builder", {
    component: DoborBuilder,
    supportedTypes: ["text"],
});
