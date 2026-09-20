/**
 * Сворачиваемые секции формы.
 *
 * Штатного механизма в Odoo 19 нет: `<group>` компилируется в компонент со
 * строго ограниченным набором свойств, ни «collapsible», ни состояния там не
 * предусмотрено. Зато класс из представления до разметки доезжает — на этом и
 * строимся.
 *
 * Самое важное здесь — последний блок. Обязательное поле внутри свёрнутой
 * секции ВСЁ РАВНО проверяется при сохранении: Odoo смотрит на данные записи,
 * а не на то, что нарисовано. Форма не сохранится, а какое поле виновато —
 * не покажет, потому что оно скрыто. Поэтому секцию с ошибкой разворачиваем
 * принудительно, иначе человек попадает в тупик без объяснений.
 */
import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

const STORE_KEY = "pmk_form_sections";
const DONE = "pmkSection";

function readState() {
    try {
        return JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}");
    } catch {
        // Приватное окно, запрет на хранилище — секции просто откроются
        // по умолчанию из разметки. Ломаться из-за этого нечему.
        return {};
    }
}

function writeState(state) {
    try {
        window.localStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch {
        /* см. выше */
    }
}

function sectionKey(el) {
    return el.getAttribute("name") || (el.querySelector(".o_horizontal_separator")?.textContent || "").trim();
}

function enhance(el) {
    if (el.dataset[DONE]) {
        return;
    }
    // Заголовок лежит по-разному: у группы с подгруппами — прямым потомком,
    // у группы с одним полем Odoo заворачивает его в колонку сетки.
    const title = el.querySelector(":scope > .o_horizontal_separator")
        || el.querySelector(":scope > * > .o_horizontal_separator");
    if (!title) {
        return;                       // секция без заголовка — сворачивать не за что
    }
    el.dataset[DONE] = "1";
    // Помечаем ветку с заголовком, чтобы стили прятали всё, кроме неё:
    // иначе при сворачивании исчезает и сам заголовок.
    const head = title.parentElement === el ? title : title.parentElement;
    head.classList.add("pmk-section__head");

    const key = sectionKey(el);
    const state = readState();
    // Разметка задаёт состояние по умолчанию, сохранённое его перебивает.
    const closed = key in state ? state[key] : el.classList.contains("pmk-section--closed");
    el.classList.toggle("pmk-section--closed", !!closed);

    title.setAttribute("role", "button");
    title.setAttribute("tabindex", "0");
    title.setAttribute("aria-expanded", String(!closed));

    const toggle = () => {
        const nowClosed = !el.classList.contains("pmk-section--closed");
        el.classList.toggle("pmk-section--closed", nowClosed);
        title.setAttribute("aria-expanded", String(!nowClosed));
        const saved = readState();
        saved[key] = nowClosed;
        writeState(saved);
    };

    title.addEventListener("click", toggle);
    title.addEventListener("keydown", (ev) => {
        // Заголовок работает как кнопка, значит обязан слушать клавиатуру.
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            toggle();
        }
    });
}

function revealInvalid(root) {
    for (const field of root.querySelectorAll(".o_field_invalid")) {
        const section = field.closest(".pmk-section--closed");
        if (!section) {
            continue;
        }
        section.classList.remove("pmk-section--closed");
        section.querySelector(".pmk-section__head")?.setAttribute("aria-expanded", "true");
        const saved = readState();
        saved[sectionKey(section)] = false;
        writeState(saved);
    }
}

patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        useEffect(() => {
            const root = document.querySelector(".o_form_view.pmk-form");
            if (!root) {
                return;
            }
            root.querySelectorAll(".pmk-section").forEach(enhance);
            revealInvalid(root);
        });
    },
});
