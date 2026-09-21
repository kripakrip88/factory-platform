from odoo import http
from odoo.http import request


class TeamInboxBasicController(http.Controller):

    @http.route('/teaminboxbasic/messages', type='jsonrpc', auth='user', methods=['POST'])
    def get_messages(self, direction='in', limit=25, offset=0, search='', sort='desc',
                      date_from='', date_to='', **kwargs):
        base_url = request.httprequest.host_url.rstrip('/')
        return request.env['teaminboxbasic.message'].get_data(
            direction=direction, limit=limit, offset=offset,
            search=search, sort=sort, date_from=date_from, date_to=date_to,
            base_url=base_url,
        )

    @http.route('/teaminboxbasic/stats', type='jsonrpc', auth='user', methods=['POST'])
    def get_stats(self, **kwargs):
        return request.env['teaminboxbasic.message'].get_stats()

    @http.route('/teaminboxbasic/body', type='jsonrpc', auth='user', methods=['POST'])
    def get_body(self, message_id, **kwargs):
        return request.env['teaminboxbasic.message'].get_message_body(message_id)
