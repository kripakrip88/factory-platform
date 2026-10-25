/**
 * Меню «В работу ▾» в строке над письмом (25.10.2026, почта проще; было —
 * кнопка «Лид»): «Лид из письма» / «Открыть лид», «Привязать к сделке»,
 * «Создать / Открыть контрагента». Сведения о письме — из карточки справа
 * (cardStore, letter_actions.js), второго запроса к серверу нет.
 *
 * Лид и сделка — только тому, кто может завести лид (признак env.pmkCrm,
 * ниже); контрагент — всем (снабженцу из «Закупок» тоже нужен поставщик).
 *
 * Прежнее описание кнопки «Лид»:
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
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// Импорт по имени класса — заодно и страховка: если автор переименует файл,
// загрузчик упадёт с понятной ошибкой, а не оставит немую кнопку.
import { MailClientInbox } from "@mail_client/mail_client_action";
import { ReadingPane } from "@mail_client/panes/reading_pane";
import { openLeadDialog } from "./lead_dialog";
import { CARD_RELOAD, cardFor, cardStore, createPartnerDialog, linkDealDialog } from "./letter_actions";
import { openFromMail } from "./mail_return";

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
        this.pmkCards = useState(cardStore);
    },

    /** Карточка открытого письма (или null — карточки нет / ещё грузится). */
    get pmkCard() {
        // pmkCards — подписка на cardStore: меню перерисуется, когда карточка
        // догрузится.
        return this.props.detail && this.pmkCards ? cardFor(this.props.detail.id) : null;
    },

    /** Меню «В работу» не пустое: лид/сделка (есть права) или контрагент. */
    get pmkWorkMenu() {
        return Boolean(this.env.pmkCrm || this.pmkCanPartner || this.pmkCard?.partner);
    },

    get pmkCanPartner() {
        const card = this.pmkCard;
        return card ? Boolean(!card.partner && card.email) : true;
    },

    pmkOpenLead() {
        const card = this.pmkCard;
        if (card?.lead && this.props.detail) {
            openFromMail(this.env, "crm.lead", card.lead.id, this.props.detail.id);
        }
    },

    pmkOpenPartner() {
        const card = this.pmkCard;
        if (card?.partner && this.props.detail) {
            openFromMail(this.env, "res.partner", card.partner.id, this.props.detail.id);
        }
    },

    pmkLinkDeal() {
        if (this.props.detail) {
            linkDealDialog(this.env, this.props.detail.id, this.pmkCard?.partner);
        }
    },

    async pmkCreatePartner() {
        if (!this.props.detail || this.pmkLead.busy) {
            return;
        }
        this.pmkLead.busy = true;
        try {
            await createPartnerDialog(this.env, this.props.detail.id);
        } finally {
            this.pmkLead.busy = false;
        }
    },

    async pmkCreateLead() {
        // detail может обнулиться между отрисовкой и кликом — список писем
        // сбрасывает выделение при смене папки.
        if (!this.props.detail || this.pmkLead.busy) {
            return;
        }
        const messageId = this.props.detail.id;
        this.pmkLead.busy = true;
        try {
            // 14.10.2026: окно «Новый лид из письма» (lead_dialog.js) вместо
            // мгновенного лида и его формы в окошке.
            await openLeadDialog(this.env, messageId, {
                onDone: () => {
                    // Карточка справа (partner_card.js) и значок у строки.
                    this.env.bus.trigger(CARD_RELOAD);
                    this.env.pmkMail?.refreshLead(messageId);
                },
            });
        } finally {
            this.pmkLead.busy = false;
        }
    },
});
