# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    trello_board_id = fields.Char(string='Trello Board ID', copy=False, index='btree_not_null', readonly=True)

    _sql_constraints = [('trello_board_uniq', 'UNIQUE(trello_board_id)',
                         'This Trello board is already linked to another project.')]


class ProjectTask(models.Model):
    _inherit = 'project.task'

    trello_card_id = fields.Char(string='Trello Card ID', copy=False, index='btree_not_null', readonly=True)
    trello_url = fields.Char(string='Trello Card', copy=False, readonly=True)
    trello_card_name = fields.Char(string='Trello Card Name', copy=False, readonly=True,
                                   help="Current name of the card in Trello, shown when it differs from the task title.")
    trello_board_ref_id = fields.Many2one('trello.board', string='Trello Board', copy=False, index='btree_not_null',
                                          readonly=True, ondelete='set null')
    trello_synced_values = fields.Json(copy=False, readonly=True,
                                       help="Card values at the last sync; only fields changed in Trello since "
                                            "then overwrite the task.")

    # One task per card, whatever project the task was moved to.
    _sql_constraints = [('trello_card_uniq', 'UNIQUE(trello_card_id)', 'This Trello card is already linked to a task.')]


class ProjectTags(models.Model):
    _inherit = 'project.tags'

    trello_imported = fields.Boolean(string='From Trello', copy=False)
    trello_priority = fields.Boolean(string='High Priority',
                                     help="Tasks carrying this Trello label get high priority (starred).")
