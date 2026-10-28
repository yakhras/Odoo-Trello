# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    trello_api_key = fields.Char(string='Trello API Key', config_parameter='trello.api_key')
    trello_api_token = fields.Char(string='Trello Token', config_parameter='trello.api_token')
    trello_priority_labels = fields.Char(string='Priority Label Names', config_parameter='trello.priority_labels',
                                         default='urgent,high priority',
                                         help="Comma-separated, case-insensitive. New Trello labels with these "
                                              "names are flagged as high priority.")
    trello_max_attachment_mb = fields.Integer(string='Max Attachment Size (MB)',
                                              config_parameter='trello.max_attachment_mb', default=25,
                                              help="Larger uploads are stored as a link to Trello instead of a file.")

    def _trello_save_credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_str('trello.api_key', (self.trello_api_key or '').strip())
        ICP.set_str('trello.api_token', (self.trello_api_token or '').strip())

    def action_trello_test_connection(self):
        self.ensure_one()
        self._trello_save_credentials()
        me = self.env['trello.api']._request('/members/me', {'fields': 'username,fullName'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._("Trello"),
                'message': self.env._("Connected as %(name)s (@%(user)s)",
                                      name=me.get('fullName'), user=me.get('username')),
                'type': 'success',
            },
        }

    def action_trello_fetch_boards(self):
        self.ensure_one()
        self._trello_save_credentials()
        return self.env['trello.board'].action_fetch_boards()
