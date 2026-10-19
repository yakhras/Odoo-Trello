# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models

TASK_STATES = [
    ('01_in_progress', 'In Progress'),
    ('02_changes_requested', 'Changes Requested'),
    ('03_approved', 'Approved'),
    ('04_waiting_normal', 'Waiting'),
    ('1_done', 'Done'),
    ('1_canceled', 'Cancelled'),
]


def guess_task_state(list_name):
    name = (list_name or '').lower()
    if any(word in name for word in ('done', 'complete', 'finished')):
        return '1_done'
    if 'cancel' in name:
        return '1_canceled'
    if any(word in name for word in ('waiting', 'blocked')):
        return '04_waiting_normal'
    return '01_in_progress'


class TrelloListMap(models.Model):
    _name = 'trello.list.map'
    _description = 'Trello List to Stage Mapping'
    _order = 'board_id, pos, id'

    board_id = fields.Many2one('trello.board', required=True, ondelete='cascade', index=True)
    trello_list_id = fields.Char(string='Trello List ID', required=True, readonly=True)
    name = fields.Char(string='Trello List', readonly=True)
    pos = fields.Float(readonly=True)
    closed = fields.Boolean(string='Archived in Trello', readonly=True)
    mode = fields.Selection([
        ('merge', 'Merge into existing stage'),
        ('new', 'Create new stage'),
    ], required=True, default='new')
    stage_id = fields.Many2one('project.task.type', string='Stage', ondelete='restrict')
    task_state = fields.Selection(TASK_STATES, required=True, default='01_in_progress',
                                  help="State given to tasks whose card is in this list "
                                       "(a card with a completed due date is always Done).")
    state = fields.Selection([('unmapped', 'Unmapped'), ('mapped', 'Mapped')],
                             default='unmapped', required=True, readonly=True,
                             help="Cards in unmapped lists are skipped by the sync.")

    _board_list_uniq = models.Constraint('UNIQUE(board_id, trello_list_id)',
                                         'This Trello list is already mapped for this board.')

    @api.onchange('mode', 'stage_id')
    def _onchange_mapping(self):
        # Any change must be applied again (Activate / Apply list mappings).
        self.state = 'unmapped'
        if self.mode == 'new':
            self.stage_id = False
