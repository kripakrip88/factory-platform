/**
 * Окно позиции доборки — во весь экран.
 *
 * ЗАЧЕМ. Построитель профиля живёт в форме строки one2many, то есть в диалоге.
 * В обычном окне холсту доставалось ~270 px высоты, и профиль 85 × 61 мм
 * рисовался размером с почтовую марку — подписи размеров не читались
 * (жалоба владельца 21.09.2026).
 *
 * ПОЧЕМУ ПАТЧ, А НЕ АТРИБУТ ВЬЮХИ. Строку one2many открывает X2ManyFieldDialog
 * (web, views/fields/relational_utils.js: useOpenX2ManyRecord →
 * addDialog(X2ManyFieldDialog, …)). Размер окна он не принимает и в Dialog
 * не передаёт — его геттер dialogProps отдаёт только title, withBodyPadding,
 * modalRef, contentClass и onExpand, поэтому Dialog берёт свой размер по
 * умолчанию "lg". Ни атрибута формы/поля, ни ключа контекста для этого в web
 * нет: context.dialog_size читает только action_service для act_window с
 * target="new", до диалога строки он не доходит.
 *
 * ЧТО ДЕЛАЕМ. Dialog принимает size="fullscreen" (core/dialog/dialog.js,
 * validate) и вешает его классом modal-fullscreen (core/dialog/dialog.xml:
 * modal-{{props.size}}). Это штатный класс Bootstrap 5: 100vw × 100%, без
 * полей, .modal-content на всю высоту. Так же открывает себя история правок
 * html_editor (history_dialog.js: this.size = "fullscreen"). Крестик в шапке
 * и кнопки в подвале при этом остаются: Dialog прячет их только при своём
 * fullscreen=true (мобильный режим), а не по size.
 *
 * ГРАНИЦЫ. Включается ТОЛЬКО для форм, у которых корневой <form> помечен
 * классом pmk-dialog-fullscreen (у нас — форма позиции доборки в
 * views/dobor_views.xml). Остальные диалоги системы патч не меняет.
 */

import { patch } from "@web/core/utils/patch";
import { X2ManyFieldDialog } from "@web/views/fields/relational_utils";

const MARKER = "pmk-dialog-fullscreen";

patch(X2ManyFieldDialog.prototype, {
    get dialogProps() {
        const props = super.dialogProps;
        // archInfo.xmlDoc — корневой <form> разметки (form_arch_parser.js).
        // Класс читаем так же, как computeViewClassName в views/utils.js:
        // по атрибуту, а не через classList — это XML-узел, не HTML.
        const classes = this.archInfo?.xmlDoc?.getAttribute?.("class")?.split(" ") || [];
        if (classes.includes(MARKER)) {
            props.size = "fullscreen";
        }
        return props;
    },
});
