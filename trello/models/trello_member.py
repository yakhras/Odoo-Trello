# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class TrelloMember(models.Model):
    _name = 'trello.member'
    _description = 'Trello Member'
    _order = 'full_name'
    _rec_name = 'full_name'

    trello_id = fields.Char(required=True, readonly=True, index=True)
    full_name = fields.Char()
    username = fields.Char()
    user_id = fields.Many2one('res.users', string='Odoo User', domain=[('share', '=', False)],
                              help="Tasks assigned to this Trello member are assigned to this user.")

    _sql_constraints = [('trello_id_uniq', 'UNIQUE(trello_id)', 'This Trello member already exists.')]
