/**
 * Кнопка «Создать лида» в панели действий над письмом.
 *
 * Показывается только когда почта открыта из Продаж. Признак приезжает в
 * params отдельной записи действия и кладётся в env — не через props: у
 * ReadingPane строгая схема props, лишний ключ завалит проверку Owl, а
 * протаскивать его через шаблон корня значило бы зависеть от расстановки
 * компонентов внутри чужого модуля.
 */
import { useState, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// Импорт по имени класса — заодно и страховка: если автор переименует файл,
// загрузчик упадёт с понятной ошибкой, а не оставит немую кнопку.
import { MailClientInbox } from "@mail_client/mail_client_action";
import { ReadingPane } from "@mail_client/panes/reading_pane";

patch(MailClientInbox.prototype, {
    setup() {
        super.setup();
        useSubEnv({ pmkCrm: Boolean(this.props.action?.params?.pmk_crm) });
    },
});

patch(ReadingPane.prototype, {
    setup() {
        // super первым: он создаёт this.state и this.notification, без них
        // отвалятся меню «переместить», карточка контакта и индикатор загрузки.
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this.pmkLead = useState({ busy: false });
    },

    async pmkCreateLead() {
        // detail может обнулиться между отрисовкой и кликом — список писем
        // сбрасывает выделение при смене папки.
        if (!this.props.detail || this.pmkLead.busy) {
            return;
        }
        this.pmkLead.busy = true;
        try {
            const result = await this.orm.call(
                "mail.client.message",
                "action_pmk_create_lead",
                [[this.props.detail.id]]
            );
            this.notification.add(
                result.created ? _t("Лид создан") : _t("Из этого письма лид уже есть"),
                { type: result.created ? "success" : "info" }
            );
            await this.action.doAction(result.action);
        } finally {
            this.pmkLead.busy = false;
        }
    },
});
