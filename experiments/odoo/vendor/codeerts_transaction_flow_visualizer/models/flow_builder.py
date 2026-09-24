from collections import deque

from odoo import api, models
from odoo.exceptions import AccessError

_STATE_COLOR = {
    'draft': 'grey', 'sent': 'grey', 'cancel': 'red',
    'sale': 'blue', 'done': 'green', 'purchase': 'blue',
    'to approve': 'blue', 'confirmed': 'blue', 'progress': 'blue',
    'assigned': 'blue', 'waiting': 'grey', 'posted': 'green',
    'paid': 'green', 'in_payment': 'green', 'not_paid': 'blue',
}

# Models that carry a Flow Map button and have a _neighbors branch.
_SUPPORTED_MODELS = (
    'sale.order', 'purchase.order', 'mrp.production',
    'account.move', 'stock.picking',
    'project.project', 'project.task',
)


class TransactionFlowBuilder(models.AbstractModel):
    _name = 'transaction.flow.builder'
    _description = 'Transaction Flow Graph Builder'

    @api.model
    def _node_id(self, record) -> str:
        return '%s,%s' % (record._name, record.id)

    @api.model
    def _state_field(self, record) -> str:
        # A posted invoice is more informative shown by its payment status
        # (paid / in_payment / not_paid) than by the generic 'posted' state.
        if record._name == 'account.move' and record.state == 'posted' \
                and 'payment_state' in record._fields and record.payment_state:
            return 'payment_state'
        for fname in ('state', 'payment_state'):
            if fname in record._fields:
                return fname
        return ''

    @api.model
    def _state_label(self, record, fname, raw) -> str:
        """Human-readable, translated label for a selection value."""
        if not fname or not raw:
            return ''
        selection = dict(record.fields_get([fname])[fname].get('selection') or [])
        return selection.get(raw, raw)

    @api.model
    def _node_for(self, record) -> dict:
        fname = self._state_field(record)
        raw = record[fname] if fname else ''
        return {
            'id': self._node_id(record),
            'model': record._name,
            'res_id': record.id,
            'label': record.display_name,
            'state': self._state_label(record, fname, raw),
            'color': _STATE_COLOR.get(raw, 'grey'),
            'kind': record._description or record._name,
        }

    @api.model
    def _optional_rel(self, record, fname):
        """Read an OPTIONAL relation, tolerating a field this user is not allowed to read.

        `fname in record._fields` proves the field EXISTS, not that the current user may READ it. A field
        declared with `groups=` raises AccessError on access for anyone outside those groups, so the
        presence test is not a sufficient guard. The Flow Map is a read-only overview: a relation the user
        cannot see is simply left out of the graph, which is what they would see anyway. Returns an EMPTY
        recordset (never None) so every caller can append unconditionally.
        """
        field = record._fields.get(fname)
        if field is None:
            return record.browse()
        try:
            return record[fname]
        except AccessError:
            comodel = getattr(field, 'comodel_name', None)
            return self.env[comodel].browse() if comodel else record.browse()

    @api.model
    def _neighbors(self, record) -> list:
        model = record._name
        env = self.env
        linked = []
        if model == 'sale.order':
            if 'invoice_ids' in record._fields:
                linked.append(record.invoice_ids)
            if 'picking_ids' in record._fields:
                linked.append(record.picking_ids)
            if hasattr(record, '_get_purchase_orders'):
                linked.append(record._get_purchase_orders())
            # Optional: lights up only when sale_project is installed.
            # Read these via _optional_rel, NEVER directly. Core declares them with `groups=`, so a direct
            # read raises AccessError for anyone outside Project: `project_ids` on every supported version,
            # and `tasks_ids` from 19.0 onward (17.0/18.0 sale_project declare it without `groups=`).
            linked.append(self._optional_rel(record, 'project_ids'))
            linked.append(self._optional_rel(record, 'tasks_ids'))
        elif model == 'project.project':
            if 'sale_order_id' in record._fields and record.sale_order_id:
                linked.append(record.sale_order_id)
            if 'task_ids' in record._fields:
                linked.append(record.task_ids)
        elif model == 'project.task':
            if 'sale_order_id' in record._fields and record.sale_order_id:
                linked.append(record.sale_order_id)
            if 'project_id' in record._fields and record.project_id:
                linked.append(record.project_id)
        elif model == 'purchase.order':
            if 'invoice_ids' in record._fields:
                linked.append(record.invoice_ids)
            if 'picking_ids' in record._fields:
                linked.append(record.picking_ids)
            if hasattr(record, '_get_sale_orders'):
                linked.append(record._get_sale_orders())
        elif model == 'mrp.production':
            if 'sale_line_id' in record._fields:
                linked.append(record.sale_line_id.order_id)
            if 'move_finished_ids' in record._fields:
                linked.append(record.move_finished_ids.move_dest_ids.picking_id)
            if 'move_raw_ids' in record._fields:
                linked.append(record.move_raw_ids.move_orig_ids.picking_id)
        elif model == 'stock.picking':
            if 'sale_id' in record._fields and record.sale_id:
                linked.append(record.sale_id)
            if 'purchase_id' in record._fields and record.purchase_id:
                linked.append(record.purchase_id)
        elif model == 'account.move':
            # The id MUST be wrapped in a list. `invoice_ids` is a computed field with a custom search
            # method; 19.0 survives a bare int only because odoo/orm/domains.py:1314-1317 quietly wraps a
            # non-collection value and logs "should have a list value". On 17.0/18.0 there is no such
            # normalisation and sale/models/sale_order.py feeds it straight to list(value), so a bare int
            # raised TypeError: 'int' object is not iterable and the Flow Map died on any invoice.
            linked.append(env['sale.order'].search([('invoice_ids', 'in', [record.id])]))
            linked.append(env['purchase.order'].search([('invoice_ids', 'in', [record.id])]))

        seen, out = set(), []
        for rs in linked:
            for rec in rs:
                key = (rec._name, rec.id)
                if not rec.id or key in seen or (rec._name == model and rec.id == record.id):
                    continue
                seen.add(key)
                out.append(rec)
        return out

    @api.model
    def get_flow_graph(self, res_model, res_id, max_depth: int = 3,
                       max_nodes: int = 60) -> dict:
        if res_model not in _SUPPORTED_MODELS:
            return {'nodes': [], 'edges': [], 'truncated': False}
        anchor = self.env[res_model].browse(res_id).exists()
        if not anchor:
            return {'nodes': [], 'edges': [], 'truncated': False}
        nodes, edges, edge_seen, truncated = {}, [], set(), False
        nodes[self._node_id(anchor)] = self._node_for(anchor)
        frontier = deque([(anchor, 0)])
        while frontier:
            record, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for neigh in self._neighbors(record):
                nid = self._node_id(neigh)
                ekey = tuple(sorted((self._node_id(record), nid)))
                if ekey not in edge_seen:
                    edge_seen.add(ekey)
                    edges.append({'from': self._node_id(record), 'to': nid})
                if nid not in nodes:
                    if len(nodes) >= max_nodes:
                        truncated = True
                        continue
                    nodes[nid] = self._node_for(neigh)
                    frontier.append((neigh, depth + 1))
        valid = set(nodes)
        edges = [e for e in edges if e['from'] in valid and e['to'] in valid]
        return {'nodes': list(nodes.values()), 'edges': edges, 'truncated': truncated}
