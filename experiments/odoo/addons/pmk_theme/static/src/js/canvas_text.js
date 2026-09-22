/** @odoo-module **/

/**
 * Светлые подписи на графиках.
 *
 * ЗАЧЕМ. График рисуется на canvas, и CSS до подписей осей и легенды не
 * достаёт — их цвет задаёт JS. Odoo выбирает цвет по схеме оформления,
 * причём ОДИН РАЗ при загрузке модуля
 * (web/static/src/views/graph/graph_renderer.js:29-32):
 *
 *     const colorScheme = cookie.get("color_scheme");
 *     const GRAPH_LEGEND_COLOR = getCustomColor(colorScheme, "#111827", "#ffffff");
 *     const GRAPH_LABEL_COLOR  = getCustomColor(colorScheme, "#111827", "#E4E4E4");
 *
 * Наша тема делает интерфейс тёмным СТИЛЯМИ, а штатный переключатель схемы
 * при этом остаётся в светлом положении. Значит Odoo берёт левую ветку —
 * #111827, почти чёрный, — и подписи пропадают на тёмной карточке графика.
 *
 * Перенесено из чужой темы, которую снимаем:
 * vendor/theme_liquid_glass/static/src/js/canvas_text.js (47 строк).
 * Модуль-импорт и точка патча оставлены В ТОЧНОСТИ теми же — проверено по
 * исходникам Odoo 19 в контейнере odoo-app, см. ниже.
 *
 * ┌ ПОДТВЕРЖДЕНИЕ ТОЧКИ ПАТЧА (odoo 19, /usr/lib/python3/dist-packages/odoo) ┐
 * │ web/static/src/views/graph/graph_renderer.js:117                         │
 * │     export class GraphRenderer extends Component { … }                   │
 * │ — класс существует и экспортируется под этим именем; так его импортируют │
 * │   и сами модули Odoo, например                                           │
 * │   stock/static/src/stock_forecasted/forecasted_graph.js:2                 │
 * │       import { GraphRenderer } from "@web/views/graph/graph_renderer";    │
 * │                                                                           │
 * │ graph_renderer.js:403  getLegendOptions() { … }                          │
 * │ graph_renderer.js:551  getScaleOptions()  { … }                          │
 * │ — оба метода на месте и вызываются при сборке настроек графика:          │
 * │   graph_renderer.js:770  scales:  this.getScaleOptions(),                 │
 * │   graph_renderer.js:772  legend:  this.getLegendOptions(),                │
 * └───────────────────────────────────────────────────────────────────────────┘
 *
 * ⚠️ БАНДЛ. Этот файл обязан подключаться в "web.assets_backend_lazy", а НЕ в
 * "web.assets_backend". Вид «График» лежит в отложенном бандле: в
 * web/__manifest__.py:109 строка 'web/static/src/views/graph/**' сначала
 * ИСКЛЮЧЕНА из assets_backend (директива remove) и затем включена в
 * assets_backend_lazy (web/__manifest__.py:141). Если положить патч в обычный
 * бандл, импорт "@web/views/graph/graph_renderer" там не разрешится, и патч
 * молча не применится — а заметят это только на графике, который никто не
 * открывает сразу. Чужая тема подключала его именно так
 * (vendor/theme_liquid_glass/__manifest__.py, раздел web.assets_backend_lazy),
 * и это единственное, что нужно повторить при регистрации.
 */

import { patch } from "@web/core/utils/patch";
import { GraphRenderer } from "@web/views/graph/graph_renderer";

/**
 * Цвет подписей берём из нашего словаря токенов (tokens.scss, :root),
 * а не зашиваем числом: сменится тема — сменятся и подписи, руками ничего
 * править не придётся.
 *
 * Запасное значение обязательно. Стили и этот файл живут в РАЗНЫХ бандлах
 * (стили — в web.assets_backend, патч — в web.assets_backend_lazy), и если
 * токены по какой-то причине не доехали, getPropertyValue вернёт пустую
 * строку. Пустую строку Chart.js принял бы за «цвет не задан» и нарисовал бы
 * подписи цветом по умолчанию — снова тёмным. Поэтому падаем на белый:
 * именно его ставила чужая тема, так что вид не дёрнется.
 */
const FALLBACK_COLOR = "#ffffff";

function fontColor() {
    try {
        const value = getComputedStyle(document.documentElement)
            .getPropertyValue("--pmk-text-strong")
            .trim();
        return value || FALLBACK_COLOR;
    } catch {
        // Ни при каких обстоятельствах не роняем отрисовку графика из-за цвета.
        return FALLBACK_COLOR;
    }
}

patch(GraphRenderer.prototype, {

    /**
     * Подписи и заголовки осей.
     *
     * Проверки на существование ветки — не перестраховка, а необходимость:
     * в режиме «круговая» ядро возвращает из этого метода пустой объект
     * (graph_renderer.js:554-556: `if (mode === "pie") { return {} }`),
     * и обращение к options.x.ticks без проверки уронило бы весь график.
     */
    getScaleOptions() {
        const options = super.getScaleOptions();
        const color = fontColor();

        if (options.x?.ticks) {
            options.x.ticks.color = color;
        }
        // У горизонтальной оси ядро сейчас заголовка НЕ создаёт
        // (graph_renderer.js:557-570 — у xAxe есть ticks, grid, border, но нет
        // title), так что ветка вхолостую. Оставляем: если Odoo заголовок
        // добавит, он окажется покрашен, а не станет чёрным сюрпризом.
        if (options.x?.title) {
            options.x.title.color = color;
        }

        if (options.y?.ticks) {
            options.y.ticks.color = color;
        }
        // А вот здесь ветка рабочая: заголовок вертикальной оси ядро создаёт
        // всегда (graph_renderer.js:574-581), и в светлой схеме кладёт туда
        // color: null — то есть цвет Chart.js по умолчанию, тёмно-серый.
        if (options.y?.title) {
            options.y.title.color = color;
        }

        return options;
    },

    /**
     * Легенда.
     *
     * Ядро собирает подписи функцией generateLabels и в каждую кладёт свой
     * fontColor (graph_renderer.js:429 для круговой и :454 для остальных).
     * Заменить сам цвет нельзя — он вычислен при загрузке модуля; поэтому
     * оборачиваем функцию и правим цвет уже в готовых подписях.
     *
     * Имя поля оставляем fontColor — ровно то, которым пользуется ядро, чтобы
     * подписи легенды и подписи осей красились одинаково.
     */
    getLegendOptions() {
        const options = super.getLegendOptions();

        if (options.labels?.generateLabels) {
            const originalGenerateLabels = options.labels.generateLabels;

            options.labels.generateLabels = (chart) => {
                // Цвет считаем внутри, на каждую отрисовку: легенда
                // перестраивается при переключении рядов, и к этому моменту
                // стили точно применены.
                const color = fontColor();
                return originalGenerateLabels(chart).map((label) => ({
                    ...label,
                    fontColor: color,
                }));
            };
        }

        return options;
    },

});
