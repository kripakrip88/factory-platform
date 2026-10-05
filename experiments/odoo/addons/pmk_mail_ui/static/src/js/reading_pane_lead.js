/**
 * Кнопка «Создать лида» в панели действий над письмом.
 *
 * Показывается только когда почта открыта из Продаж. Признак приезжает в
 * params отдельной записи действия и кладётся в env — не через props: у
 * ReadingPane строгая схема props, лишний ключ завалит проверку Owl, а
 * протаскивать его через шаблон корня значило бы зависеть от расстановки
 * компонентов внутри чужого модуля.
 *
 * И только тому, кто может завести лид (разбор UX, шаг 38, доводка
 * 05.10.2026). С шага 38 почта одна — «Продажи → Почта»: её читает и
 * снабженец без прав на продажи, и кнопка «Лид» у него кончалась бы отказом
 * в доступе. Право спрашиваем у сервера тем же вызовом, что ядро
 * (user.checkAccessRight → has_access, ответ кэшируется на сессию), до
 * первой отрисовки почты (onWillStart). env заморожен, поэтому признак в нём —
 * свойство-геттер: шаблон кнопки по-прежнему читает env.pmkCrm. Ошибка
 * запроса — кнопки нет: лучше не показать, чем показать отказ. Сервер
 * проверяет то же самое (action_pmk_create_lead).
 */
import { onWillStart, useState, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// Импорт по имени класса — заодно и страховка: если автор переименует файл,
// загрузчик упадёт с понятной ошибкой, а не оставит немую кнопку.
import { MailClientInbox } from "@mail_client/mail_client_action";
import { ReadingPane } from "@mail_client/panes/reading_pane";

patch(MailClientInbox.prototype, {
    setup() {
        super.setup();
        const fromSales = Boolean(this.props.action?.params?.pmk_crm);
        const lead = { allowed: false };
        useSubEnv({
            get pmkCrm() {
                return lead.allowed;
            },
        });
        if (fromSales) {
            onWillStart(async () => {
                try {
                    lead.allowed = Boolean(await user.checkAccessRight("crm.lead", "create"));
                } catch {
                    lead.allowed = false;
                }
            });
        }
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
                result.created
                    ? _t("Лид создан")
                    : result.from_thread
                      ? _t("У этой переписки лид уже есть — открыт он")
                      : _t("Из этого письма лид уже есть"),
                { type: result.created ? "success" : "info" }
            );
            await this.action.doAction(result.action);
        } finally {
            this.pmkLead.busy = false;
        }
    },
});
