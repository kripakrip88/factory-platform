/**
 * Окна строк во весь экран и со своим заголовком: позиция доборки, изделие
 * расчёта.
 *
 * ЗАЧЕМ. Построитель профиля живёт в форме строки one2many, то есть в диалоге.
 * В обычном окне холсту доставалось ~270 px высоты, и профиль 85 × 61 мм
 * рисовался размером с почтовую марку — подписи размеров не читались
 * (жалоба владельца 21.09.2026). Окно изделия расчёта — то же (разбор UX,
 * шаг 34, 02.10.2026): в обычном окне было видно 6 деталей из 22, а
 * заголовок говорил «Открыть: Изделия» — ядро собирает его из подписи поля
 * (множественное число), а не из формы.
 *
 * ПОЧЕМУ ПАТЧ, А НЕ АТРИБУТ ВЬЮХИ. Строку one2many открывает X2ManyFieldDialog
 * (web, views/fields/relational_utils.js: useOpenX2ManyRecord →
 * addDialog(X2ManyFieldDialog, …)). Размер окна он не принимает и в Dialog
 * не передаёт — его геттер dialogProps отдаёт только title, withBodyPadding,
 * modalRef, contentClass и onExpand, поэтому Dialog берёт свой размер по
 * умолчанию "lg". Ни атрибута формы/поля, ни ключа контекста для этого в web
 * нет: context.dialog_size читает только action_service для act_window с
 * target="new", до диалога строки он не доходит. Заголовок — так же:
 * openRecord ставит «Открыть: %s» / «Создать %s» по string ПОЛЯ
 * (activeField.string), строку формы не читает никто.
 *
 * ЧТО ДЕЛАЕМ. Dialog принимает size="fullscreen" (core/dialog/dialog.js,
 * validate) и вешает его классом modal-fullscreen (core/dialog/dialog.xml:
 * modal-{{props.size}}). Это штатный класс Bootstrap 5: 100vw × 100%, без
 * полей, .modal-content на всю высоту. Так же открывает себя история правок
 * html_editor (history_dialog.js: this.size = "fullscreen"). Крестик в шапке
 * и кнопки в подвале при этом остаются: Dialog прячет их только при своём
 * fullscreen=true (мобильный режим), а не по size. Заголовок — атрибут
 * string корневого <form>: «Изделие» и у нового изделия, и у открытого.
 *
 * КНОПКИ «РАЗВЕРНУТЬ» В ОКНЕ ВО ВЕСЬ ЭКРАН НЕТ (доводка шага 34). У
 * сохранённой строки ядро ставит onExpand (тот же геттер dialogProps), и в
 * шапке окна появляется значок «развернуть» (core/dialog/dialog.xml,
 * o_expand_button). Он сохраняет строку, закрывает документ и открывает
 * строку отдельной страницей — views [[false, "form"]]. Своей формы у
 * моделей строк нет (pmk.metal.spec.product, pmk.dobor.order.line: формы
 * живут внутри поля one2many документа), и ядро собирает автоформу: все
 * поля подряд, таблицы деталей сырыми списками, служебные поля наружу.
 * Окно и так во весь экран — кнопка ничего не даёт и уводит из документа.
 * Снимаем её там же, где ставим размер; обычные окна системы её сохраняют.
 *
 * ГРАНИЦЫ. Включается ТОЛЬКО по меткам на корневом <form> окна:
 *   • pmk-dialog-fullscreen — во весь экран и без «развернуть» (форма
 *     позиции доборки, views/dobor_views.xml; форма изделия,
 *     views/metal_spec_views.xml);
 *   • pmk-dialog-own-title — заголовок из string формы (форма изделия).
 * Остальные диалоги системы патч не меняет: у доборки заголовок прежний.
 */

import { patch } from "@web/core/utils/patch";
import { X2ManyFieldDialog } from "@web/views/fields/relational_utils";

const FULLSCREEN = "pmk-dialog-fullscreen";
const OWN_TITLE = "pmk-dialog-own-title";

patch(X2ManyFieldDialog.prototype, {
    get dialogProps() {
        const props = super.dialogProps;
        // archInfo.xmlDoc — корневой <form> разметки (form_arch_parser.js).
        // Класс читаем так же, как computeViewClassName в views/utils.js:
        // по атрибуту, а не через classList — это XML-узел, не HTML.
        const form = this.archInfo?.xmlDoc;
        const classes = form?.getAttribute?.("class")?.split(/\s+/) || [];
        if (classes.includes(FULLSCREEN)) {
            props.size = "fullscreen";
            // Без «развернуть»: окно уже во весь экран, а своей формы у
            // строки нет — ядро открыло бы автоформу (см. начало файла).
            delete props.onExpand;
        }
        const title = form?.getAttribute?.("string");
        if (classes.includes(OWN_TITLE) && title) {
            props.title = title;
        }
        return props;
    },
});
