# -*- coding: utf-8 -*-
"""«Связи» строками по этапам жизни заказа (разбор схемы 12.10.2026).

Антон: «каждый этап жизненного цикла заказа идёт на новых строчках и не
растягивается вправо бесконечно». Граф тот же (get_flow_graph), раскладка другая:

1. Заявка      — клиент, письмо, лид, сделка, расчёт КП, счёт (колонками);
2. Расчёт      — общий (технический) расчёт → категории → их раскрои (деревом);
3. Закупки     — заявки на металл и заказы поставщику;
4. Производство — строка «Заказов в работе», задания лазеру, производство;
5. Участки     — позже (распределение по участкам);
6. Отгрузка    — отгрузки и документы; паспорта — позже.

Внутри этапа документы переносятся на новую строку, а не уходят вправо. Линий между
этапами нет: при наведении подсвечиваются связанные документы (рёбра графа).

Лид и сделка — в Odoo одна запись (лид превращается в сделку). На схеме — два блока:
«Лид» (когда пришёл, от кого) и «Сделка» (стадия), щелчок по обоим открывает запись.
Раскрой листа доборки, раскрой зонтов, металлоизделия и раскладка листа — вкладки
документов, а не отдельные документы («не будем плодить кучу документов»): блок
открывает документ сразу на нужной вкладке (open_tab).
"""
from odoo import api, models

from .flow_builder import _CALC_MODELS, _field

_LANES = (
    ('order', 'Заявка', 'от письма до счёта'),
    ('calc', 'Расчёт', 'общий → категории → раскрои'),
    ('buy', 'Закупки', 'металл под заказ'),
    ('make', 'Производство', ''),
    ('shops', 'Участки', 'позже: распределение по участкам'),
    ('ship', 'Отгрузка', 'паспорта на изделия — позже'),
)
_ORDER_COLS = ('Клиент', 'Письмо', 'Лид', 'Сделка', 'Расчёт КП', 'Счёт')
_LANE_OF = {
    'purchase.order': 'buy',
    'project.task': 'make',
    'project.project': 'make',
    'pmk.laser.job': 'make',
    'pmk.laser.task': 'make',
    'pmk.laser.nest': 'make',
    'mrp.production': 'make',
    'stock.picking': 'ship',
    'account.move': 'ship',
}
_CUT_TAB = {
    # модель калькулятора → (вкладка раскроя, подпись блока, станок)
    'pmk.dobor.order': ('pmk_dobor_cut', 'Раскрой листа', 'гильотина'),
    'pmk.vent.hood.order': ('pmk_nest', 'Раскрой зонтов', 'лазер'),
}
_CAT_FLAG = {'pmk.dobor.order': 'cat_dobor', 'pmk.vent.hood.order': 'cat_vent'}


def _date(value):
    return value.strftime('%d.%m.%Y') if value else ''


class PmkFlowLanes(models.AbstractModel):
    _inherit = 'pmk.flow.builder'

    @api.model
    def _lane_virtual(self, parent, suffix, label, state, tab, color='grey'):
        """Блок-вкладка: не документ, а вкладка документа parent (узел графа)."""
        return dict(parent, id='%s:%s' % (parent['id'], suffix), label=label, state=state,
                    color=color, kind=label, open_tab=tab,
                    hint='%s — вкладка «%s»' % (parent['label'], label),
                    open_model=parent['model'], open_res_id=parent['res_id'], open_action=False)

    @api.model
    def _lane_cut_state(self, record):
        """Вторая строка блока раскроя: станок и, у доборки, сколько листов."""
        tab, _label, machine = _CUT_TAB[record._name]
        if record._name != 'pmk.dobor.order':
            return machine
        try:
            from odoo.addons.pmk_calc.tools import dobor_cut as C
            sheets = 0
            for g in record._cut_groups().values():
                v = C.plan(g['strips'], g['mass'])[record.cut_source]
                sheets += v['sheets'] + (v.get('ready') or 0)
        except Exception:  # раскрой не сложился — блок всё равно нужен
            return machine
        return '%s · %d л.' % (machine, sheets) if sheets else '%s · нет позиций' % machine

    @api.model
    def get_flow_lanes(self, res_model, res_id):
        graph = self.get_flow_graph(res_model, res_id)
        nodes = {n['id']: n for n in graph['nodes']}
        edges = list(graph['edges'])
        anchor = '%s,%s' % (res_model, res_id)

        def rec(node):
            return self.env[node['model']].browse(node['res_id'])

        order_cols = {title: [] for title in _ORDER_COLS}
        flat = {key: [] for key, _t, _h in _LANES}
        specs, calcs, cuts = [], [], []
        for nid, node in list(nodes.items()):
            model = node['model']
            record = rec(node)
            if model == 'res.partner':
                order_cols['Клиент'].append(nid)
            elif model == 'mail.client.message':
                order_cols['Письмо'].append(nid)
            elif model == 'crm.lead':
                if record.type == 'opportunity':
                    lead = dict(node, id=nid + ':lead', label='Лид от %s' % _date(record.create_date),
                                state=record.contact_name or record.email_from or record.partner_name or '',
                                color='grey', kind='Лид')
                    nodes[lead['id']] = lead
                    edges.append({'from': lead['id'], 'to': nid})
                    # Письмо пришло лидом: ребро письма — к лиду.
                    edges[:] = [{'from': lead['id'], 'to': e['to']} if e['from'] == nid
                                and e['to'].startswith('mail.client.message,') else e for e in edges]
                    edges[:] = [{'from': e['from'], 'to': lead['id']} if e['to'] == nid
                                and e['from'].startswith('mail.client.message,') else e for e in edges]
                    order_cols['Лид'].append(lead['id'])
                    order_cols['Сделка'].append(nid)
                else:
                    order_cols['Лид'].append(nid)
            elif model == 'pmk.metal.spec':
                specs.append((nid, record))
                if _field(record, 'pmk_kind') != 'tech':
                    order_cols['Расчёт КП'].append(nid)
            elif model == 'sale.order':
                order_cols['Счёт'].append(nid)
            elif model in _CALC_MODELS:
                calcs.append((nid, record))
            elif model == 'pmk.cut.plan':
                cuts.append((nid, record))
            else:
                flat[_LANE_OF.get(model, 'make')].append(nid)

        # ─── «Расчёт»: дерево на расчёт ───────────────────────────────────
        trees = []
        used = set()
        for sid, spec in specs:
            tech = _field(spec, 'pmk_kind') == 'tech'
            my_calcs = [(nid, r) for nid, r in calcs if _field(r, 'spec_id') == spec]
            my_cuts = [nid for nid, r in cuts if _field(r, 'spec_id') == spec]
            if not (tech or my_calcs or my_cuts):
                continue
            rows = []
            if _field(spec, 'cat_metal', True):
                metal = self._lane_virtual(nodes[sid], 'metal', 'Металлоизделия',
                                           'изделий: %d' % len(spec.product_ids), 'composition')
                sheets = sum(spec.layout_group_ids.mapped('sheets')) or \
                    sum(spec.sheet_line_ids.mapped('layout_sheets'))
                sheet = self._lane_virtual(nodes[sid], 'sheet', 'Раскладка листа',
                                           'листов: %d' % sheets if sheets else 'не раскладывали', 'layout')
                # Металлоизделия — это и прокат, и лист (Антон 13.10.2026): блок проката есть
                # всегда; раскроя (РК-…) ещё нет — «не раскладывали», щелчок — вкладка
                # «Металл» расчёта с кнопкой «Разложить прокат».
                linear = [] if my_cuts else [self._lane_virtual(
                    nodes[sid], 'linear', 'Раскрой проката', 'не раскладывали', 'layout')]
                for v in [metal, sheet] + linear:
                    nodes[v['id']] = v
                    edges.append({'from': sid, 'to': v['id']})
                rows.append({'head': [metal['id']],
                             'tail': (my_cuts or [v['id'] for v in linear]) + [sheet['id']]})
                for cid in my_cuts:
                    edges.append({'from': metal['id'], 'to': cid})
                used.update(my_cuts)
            for nid, calc in my_calcs:
                tab, label, _machine = _CUT_TAB[calc._name]
                flag = _CAT_FLAG.get(calc._name)
                if flag and not spec[flag]:
                    nodes[nid] = dict(nodes[nid], state='черновик · не в расчёте', color='grey', draft=True)
                cut = self._lane_virtual(nodes[nid], 'cut', label, self._lane_cut_state(calc), tab)
                nodes[cut['id']] = cut
                edges.append({'from': nid, 'to': cut['id']})
                rows.append({'head': [nid], 'tail': [cut['id']]})
                used.add(nid)
            trees.append({'root': sid, 'ref': not tech, 'rows': rows})
        # Доборка без расчёта и раскрой без расчёта — строками без корня.
        loose = [{'head': [nid], 'tail': []} for nid, _r in calcs + cuts if nid not in used]
        if loose:
            trees.append({'root': False, 'ref': False, 'rows': loose})

        lanes = []
        for key, title, hint in _LANES:
            lane = {'key': key, 'title': title, 'hint': hint}
            if key == 'order':
                lane['cols'] = [{'title': t, 'items': order_cols[t]} for t in _ORDER_COLS if order_cols[t]]
                lane['empty'] = not lane['cols']
            elif key == 'calc':
                lane['trees'] = trees
                lane['empty'] = not trees
            else:
                lane['items'] = flat[key]
                lane['empty'] = not flat[key]
            lanes.append(lane)
        for node in nodes.values():
            node['anchor'] = node['id'] == anchor
        return {
            'lanes': lanes,
            'nodes': nodes,
            'edges': edges,
            'count': len(graph['nodes']),
            'truncated': graph['truncated'],
            'restricted': graph['restricted'],
        }
