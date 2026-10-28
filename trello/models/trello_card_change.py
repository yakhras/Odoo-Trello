# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext
from odoo.tools.misc import format_datetime

from .trello_board import _parse_dt

FIELD_LABELS = {
    'name': 'Title',
    'description': 'Description',
    'date_deadline': 'Deadline',
    'list': 'Stage',
    'tag_ids': 'Tags',
    'user_ids': 'Assignees',
    'priority': 'Priority',
    'state': 'State',
    'active': 'Active',
    'trello_url': 'Trello Card',
}


class TrelloCardChange(models.Model):
    """A card fetched from Trello waiting for a decision (Trello Inbox).

    Only boards with "Review before applying" fill it; the sync then never writes tasks itself.
    """
    _name = 'trello.card.change'
    _description = 'Trello Inbox'
    _order = 'fetch_date desc, id desc'

    board_id = fields.Many2one('trello.board', required=True, readonly=True, ondelete='cascade', index=True)
    project_id = fields.Many2one(related='board_id.project_id')
    list_map_id = fields.Many2one('trello.list.map', string='Trello List', readonly=True, ondelete='set null')
    stage_id = fields.Many2one(related='list_map_id.stage_id', string='Stage')
    trello_card_id = fields.Char(string='Trello Card ID', required=True, readonly=True, index=True)
    name = fields.Char(string='Card', readonly=True)
    trello_url = fields.Char(string='Trello Card URL', readonly=True)
    card_closed = fields.Boolean(string='Archived in Trello', readonly=True)
    kind = fields.Selection([
        ('new', 'New card'),
        ('update', 'Card changed'),
        ('archive', 'Card archived/deleted'),
    ], required=True, readonly=True)
    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade',
                              help="New card: leave empty to create a task, or pick an existing task to link it to.")
    incoming = fields.Json(readonly=True)
    changed_keys = fields.Json(readonly=True)
    changes_html = fields.Html(string='Changes', compute='_compute_changes_html', sanitize=False)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('applied', 'Applied'),
        ('ignored', 'Ignored'),
    ], default='pending', required=True, readonly=True, index=True)
    fetch_date = fields.Datetime(string='Fetched On', readonly=True)

    def init(self):
        # One pending line per card. Odoo 18 has no models.UniqueIndex, and a partial index
        # (WHERE ...) can't be an _sql_constraints entry, so it is created here.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS trello_card_change__pending_card_uniq
            ON trello_card_change (trello_card_id) WHERE (state = 'pending')
        """)

    @api.depends('incoming', 'changed_keys', 'task_id', 'list_map_id')
    def _compute_changes_html(self):
        Task = self.env['project.task']
        states = dict(Task._fields['state']._description_selection(self.env))
        Tag, Users = self.env['project.tags'], self.env['res.users']

        def text(value, limit=300):
            value = html2plaintext(value or '').strip()
            return value if len(value) <= limit else value[:limit] + '…'

        def when(value):
            # In the user's timezone, as the task form shows it (both values are UTC).
            return value and format_datetime(self.env, value, dt_format='short')

        for change in self:
            incoming = change.incoming or {}
            task = change.task_id if change.kind != 'new' else Task
            show = {
                'name': lambda: (task.name, incoming['name']),
                'description': lambda: (text(task.description), text(incoming['description'])),
                'date_deadline': lambda: (when(task.date_deadline), when(_parse_dt(incoming['date_deadline']))),
                'list': lambda: (task.stage_id.name, change.list_map_id.stage_id.name or change.list_map_id.name),
                'tag_ids': lambda: (', '.join(task.tag_ids.mapped('name')),
                                    ', '.join(Tag.browse(incoming['tag_ids']).exists().mapped('name'))),
                'user_ids': lambda: (', '.join(task.user_ids.mapped('name')),
                                     ', '.join(Users.browse(incoming['user_ids']).exists().mapped('name'))),
                'priority': lambda: (task and ('High' if task.priority == '1' else 'Normal'),
                                     'High' if incoming['priority'] == '1' else 'Normal'),
                'state': lambda: (states.get(task.state), states.get(incoming['state'])),
                'active': lambda: (task and ('Yes' if task.active else 'No'), 'Yes' if incoming['active'] else 'No'),
                'trello_url': lambda: (task.trello_url, incoming['trello_url']),
            }
            rows = Markup()
            for key in change.changed_keys or []:
                if key not in show:
                    continue
                old, new = show[key]()
                rows += Markup('<tr><th>%s</th><td>%s</td><td>%s</td></tr>') % (
                    self.env._(FIELD_LABELS[key]), old or '—', new or '—')
            change.changes_html = rows and (Markup(
                '<table class="table table-sm table-bordered"><thead><tr><th>%s</th><th>%s</th><th>%s</th></tr>'
                '</thead><tbody>%s</tbody></table>') % (
                self.env._("Field"), self.env._("Odoo now"), self.env._("Trello"), rows))

    def action_apply(self):
        for change in self.filtered(lambda c: c.state == 'pending'):
            change.board_id._apply_card_change(change)
        self.filtered(lambda c: c.state == 'pending').write({'state': 'applied'})

    def action_ignore(self):
        for change in self.filtered(lambda c: c.state == 'pending' and c.kind != 'new'):
            # The task now counts as in line with this card, so the same change isn't proposed again.
            change.task_id.trello_synced_values = change.incoming
        self.filtered(lambda c: c.state == 'pending').write({'state': 'ignored'})

    def action_reset(self):
        """Bring an ignored new card back to the Inbox."""
        lines = self.filtered(lambda c: c.state == 'ignored' and c.kind == 'new')
        for change in lines:
            if self.search_count([('trello_card_id', '=', change.trello_card_id), ('state', '=', 'pending')]):
                raise UserError(self.env._("Card '%s' is already waiting in the Trello Inbox.", change.name))
        lines.write({'state': 'pending'})
        # Comments of an ignored card were never imported: read them again on the next sync.
        lines.board_id.write({'comments_since': False})
