# -*- coding: utf-8 -*-
from . import res_partner
# Разбор UX, шаг 28: тип контрагента словами завода, кнопка «Сделки».
from . import partner_card
# Разбор UX, шаг 29: «Клиенты» — список и форма, без канбана.
from . import ir_actions_act_window
# Клиент из письма: не плодить дубли (шаг З-14): поиск клиента по ИНН и
# домену, «Возможные дубли», мастер «В сделку», целевая карточка мастера
# объединения. Шаг З-17: окно объединения по-русски, разные ИНН, перенос
# телефонов, почт и примечаний (partner_merge).
from . import partner_match
from . import partner_duplicate
from . import partner_merge
from . import crm_lead
