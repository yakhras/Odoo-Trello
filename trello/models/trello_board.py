# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from collections import defaultdict
from datetime import datetime

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tools import plaintext2html

from .trello_list_map import guess_task_state

try:
    import markdown
except ImportError:
    markdown = None

_logger = logging.getLogger(__name__)

PAGE_LIMIT = 1000  # Trello returns at most 1000 items per request (API Introduction.pdf, "Paging")


def _parse_dt(value):
    """Trello ISO 8601 UTC string -> naive UTC datetime (Odoo convention)."""
    if not value:
        return False
    return datetime.strptime(value[:19], '%Y-%m-%dT%H:%M:%S')


def _md_to_html(text):
    if not text:
        return ''
    if markdown:
        return markdown.markdown(text, extensions=['nl2br'])
    return plaintext2html(text)


class TrelloBoard(models.Model):
    _name = 'trello.board'
    _description = 'Trello Board'
    _order = 'name'

    name = fields.Char(required=True, readonly=True)
    trello_id = fields.Char(string='Trello Board ID', required=True, readonly=True, index=True)
    url = fields.Char(readonly=True)
    closed = fields.Boolean(string='Closed in Trello', readonly=True)
    state = fields.Selection([
        ('draft', 'To Map'),
        ('lists', 'Lists to Map'),
        ('active', 'Active'),
        ('paused', 'Paused'),
    ], default='draft', required=True, readonly=True, index=True)
    link_mode = fields.Selection([
        ('existing', 'Link to existing project'),
        ('new', 'Create new project'),
    ], required=True, default='new')
    project_id = fields.Many2one('project.project', ondelete='restrict', index=True)
    list_map_ids = fields.One2many('trello.list.map', 'board_id', string='List Mappings')
    unmapped_count = fields.Integer(compute='_compute_unmapped_count')
    last_sync = fields.Datetime(readonly=True)
    comments_since = fields.Datetime(readonly=True, help="Comments older than this are already imported.")
    last_error = fields.Text(readonly=True)

    _trello_id_uniq = models.Constraint('UNIQUE(trello_id)', 'This Trello board is already registered.')
    _project_uniq = models.Constraint('UNIQUE(project_id)', 'This project is already linked to another Trello board.')

    @api.depends('list_map_ids.state')
    def _compute_unmapped_count(self):
        for board in self:
            board.unmapped_count = len(board.list_map_ids.filtered(lambda l: l.state == 'unmapped'))

    @api.onchange('link_mode')
    def _onchange_link_mode(self):
        if self.link_mode == 'new':
            self.project_id = False

    # ------------------------------------------------------------------
    # Board -> Project control stage
    # ------------------------------------------------------------------
    @api.model
    def action_fetch_boards(self):
        boards = self.env['trello.api']._request('/members/me/boards', {'fields': 'name,url,closed', 'filter': 'all'})
        known = set(self.search([]).mapped('trello_id'))
        taken_projects = set(self.search([('project_id', '!=', False)]).project_id.ids)
        Project = self.env['project.project']
        for data in boards:
            if data['id'] in known:
                continue
            project = Project.search([('name', '=ilike', data['name']),
                                      ('id', 'not in', list(taken_projects)),
                                      ('trello_board_id', '=', False)], limit=1)
            if project:
                taken_projects.add(project.id)
            self.create({
                'name': data['name'],
                'trello_id': data['id'],
                'url': data.get('url'),
                'closed': data.get('closed', False),
                'link_mode': 'existing' if project else 'new',
                'project_id': project.id,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Trello Boards"),
            'res_model': 'trello.board',
            'view_mode': 'list,form',
            'context': {'search_default_group_state': 1},
        }

    def action_confirm(self):
        Project = self.env['project.project']
        for board in self:
            if board.state != 'draft':
                continue
            if board.link_mode == 'existing':
                if not board.project_id:
                    raise ValidationError(self.env._("Board '%s': choose the project to link to.", board.name))
                if self.search_count([('project_id', '=', board.project_id.id), ('id', '!=', board.id)]):
                    raise ValidationError(self.env._("Project '%s' is already linked to another Trello board.",
                                                     board.project_id.display_name))
                if board.project_id.trello_board_id and board.project_id.trello_board_id != board.trello_id:
                    raise ValidationError(self.env._("Project '%s' is already linked to another Trello board.",
                                                     board.project_id.display_name))
            else:
                if Project.with_context(active_test=False).search_count([('name', '=ilike', board.name)]):
                    raise ValidationError(self.env._(
                        "A project named '%s' already exists. Use 'Link to existing project' or rename the "
                        "board in Trello to avoid a duplicate.", board.name))
                board.project_id = False
            board._load_lists()
            board.state = 'lists'

    def action_activate(self):
        for board in self.filtered(lambda b: b.state == 'lists'):
            if not board.list_map_ids:
                raise UserError(self.env._("Board '%s' has no lists to map.", board.name))
            if board.link_mode == 'new' and not board.project_id:
                if self.env['project.project'].with_context(active_test=False).search_count(
                        [('name', '=ilike', board.name)]):
                    raise ValidationError(self.env._("A project named '%s' already exists.", board.name))
                board.project_id = self.env['project.project'].create({
                    'name': board.name,
                    'trello_board_id': board.trello_id,
                })
            else:
                board.project_id.trello_board_id = board.trello_id
            board._apply_list_mapping(board.list_map_ids)
            board.state = 'active'

    def action_apply_list_mapping(self):
        for board in self:
            board._apply_list_mapping(board.list_map_ids.filtered(lambda l: l.state == 'unmapped'))

    def action_reload_lists(self):
        for board in self:
            board._load_lists()

    def action_pause(self):
        self.filtered(lambda b: b.state == 'active').state = 'paused'

    def action_resume(self):
        self.filtered(lambda b: b.state == 'paused').state = 'active'

    def action_unlink_project(self):
        Task = self.env['project.task'].with_context(active_test=False)
        for board in self.filtered(lambda b: b.state != 'draft'):
            Task.search([('trello_board_ref_id', '=', board.id)]).write({
                'trello_card_id': False,
                'trello_url': False,
                'trello_card_name': False,
                'trello_board_ref_id': False,
                'trello_synced_values': False,
            })
            if board.project_id:
                if board.project_id.trello_board_id == board.trello_id:
                    board.project_id.trello_board_id = False
            board.list_map_ids.unlink()
            board.write({
                'state': 'draft',
                'link_mode': 'existing' if board.project_id else 'new',
                'last_sync': False,
                'comments_since': False,
                'last_error': False,
            })

    # ------------------------------------------------------------------
    # List -> Stage control stage
    # ------------------------------------------------------------------
    def _load_lists(self, lists=None):
        """Create a mapping line (state 'unmapped') for every Trello list not yet known."""
        self.ensure_one()
        if lists is None:
            lists = self.env['trello.api']._request(f'/boards/{self.trello_id}/lists',
                                                    {'filter': 'all', 'fields': 'name,pos,closed'})
        Stage = self.env['project.task.type']
        known = {m.trello_list_id: m for m in self.list_map_ids}
        for data in lists:
            vals = {'name': data['name'], 'pos': data.get('pos') or 0.0, 'closed': data.get('closed', False)}
            line = known.get(data['id'])
            if line:
                line.write(vals)  # a Trello rename never renames the Odoo stage
                continue
            stage = Stage
            if self.project_id:
                stage = Stage.search([('project_ids', 'in', self.project_id.id),
                                      ('name', '=ilike', data['name'])], limit=1)
            vals.update({
                'board_id': self.id,
                'trello_list_id': data['id'],
                'mode': 'merge' if stage else 'new',
                'stage_id': stage.id,
                'task_state': guess_task_state(data['name']),
                'state': 'unmapped',
            })
            self.env['trello.list.map'].create(vals)

    def _apply_list_mapping(self, lines):
        self.ensure_one()
        incomplete = lines.filtered(lambda l: l.mode == 'merge' and not l.stage_id)
        if incomplete:
            raise UserError(self.env._("Choose a stage for these lists: %s", ', '.join(incomplete.mapped('name'))))
        if not self.project_id:
            raise UserError(self.env._("Board '%s' is not linked to a project.", self.name))
        Stage = self.env['project.task.type']
        ordered = self.list_map_ids.sorted('pos')
        for line in lines:
            if line.mode == 'new' and not line.stage_id:
                line.stage_id = Stage.create({
                    'name': line.name,
                    'sequence': ordered.ids.index(line.id) * 10,
                    'fold': line.closed,
                    'project_ids': [Command.link(self.project_id.id)],
                })
            elif self.project_id not in line.stage_id.project_ids:
                line.stage_id.project_ids = [Command.link(self.project_id.id)]
        lines.write({'state': 'mapped'})

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------
    def action_sync(self):
        stats = defaultdict(int)
        for board in self.filtered(lambda b: b.state == 'active'):
            for key, value in board._sync_board().items():
                stats[key] += value
        message = self.env._(
            "%(created)s created, %(updated)s updated, %(archived)s archived, %(skipped)s skipped "
            "(unmapped lists), %(comments)s comments, %(attachments)s attachments.",
            created=stats['created'], updated=stats['updated'], archived=stats['archived'],
            skipped=stats['skipped'], comments=stats['comments'], attachments=stats['attachments'])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._("Trello sync done"),
                'message': message,
                'type': 'warning' if stats['skipped'] else 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    @api.model
    def _cron_sync(self):
        for board in self.search([('state', '=', 'active')]):
            try:
                board._sync_board()
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception("Trello sync failed for board %s", board.name)
                board.last_error = str(e)
                self.env.cr.commit()

    def _sync_board(self):
        self.ensure_one()
        started = fields.Datetime.now()
        data = self.env['trello.api']._request(f'/boards/{self.trello_id}', {
            'fields': 'name,url,closed',
            'lists': 'all',
            'list_fields': 'name,pos,closed',
            'cards': 'all',
            'card_fields': 'name,desc,due,dueComplete,closed,idList,idLabels,idMembers,url',
            'labels': 'all',
            'label_fields': 'name,color',
            'labels_limit': PAGE_LIMIT,
            'members': 'all',
            'member_fields': 'fullName,username',
            'checklists': 'all',
        })
        self.write({'name': data['name'], 'url': data.get('url'), 'closed': data.get('closed', False)})
        self._load_lists(data.get('lists', []))
        tags = self._sync_labels(data.get('labels', []))
        members = self._sync_members(data.get('members', []))
        checklists = defaultdict(list)
        for checklist in data.get('checklists', []):
            checklists[checklist['idCard']].append(checklist)

        stats = self._sync_cards(data.get('cards', []), tags, members, checklists)
        stats['attachments'] = self._sync_attachments()
        stats['comments'] = self._sync_comments()

        vals = {'last_sync': started, 'last_error': False}
        if not stats['skipped']:
            # Keep re-reading comments of skipped cards until their list is mapped.
            vals['comments_since'] = started
        self.write(vals)
        return stats

    def _sync_labels(self, labels):
        """Return {trello_label_id: project.tags}. Tags are global in Odoo, so labels match by name."""
        Tag = self.env['project.tags']
        param = self.env['ir.config_parameter'].sudo().get_param('trello.priority_labels', 'urgent,high priority')
        priority_names = {n.strip().lower() for n in (param or '').split(',') if n.strip()}
        result = {}
        for label in labels:
            name = (label.get('name') or '').strip() or (label.get('color') or 'label').capitalize()
            tag = Tag.with_context(active_test=False).search([('name', '=ilike', name)], limit=1)
            if not tag:
                tag = Tag.create({'name': name, 'trello_imported': True,
                                  'trello_priority': name.lower() in priority_names})
            elif not tag.trello_imported:
                # First time this tag is seen from Trello; afterwards the flag is left to the user.
                tag.write({'trello_imported': True,
                           'trello_priority': tag.trello_priority or name.lower() in priority_names})
            result[label['id']] = tag
        return result

    def _sync_members(self, members):
        """Return {trello_member_id: trello.member}."""
        Member = self.env['trello.member']
        Users = self.env['res.users']
        result = {}
        for data in members:
            member = Member.search([('trello_id', '=', data['id'])], limit=1)
            vals = {'full_name': data.get('fullName'), 'username': data.get('username')}
            if member:
                member.write(vals)
            else:
                vals['trello_id'] = data['id']
                if data.get('fullName'):
                    vals['user_id'] = Users.search([('name', '=ilike', data['fullName']),
                                                    ('share', '=', False)], limit=1).id
                member = Member.create(vals)
            result[data['id']] = member
        return result

    def _card_description(self, card, checklists):
        html = Markup(_md_to_html(card.get('desc')))
        for checklist in sorted(checklists, key=lambda c: c.get('pos') or 0):
            items = sorted(checklist.get('checkItems', []), key=lambda i: i.get('pos') or 0)
            html += Markup('<h4>%s</h4><ul>') % checklist.get('name', '')
            for item in items:
                box = '☑' if item.get('state') == 'complete' else '☐'
                html += Markup('<li>%s %s</li>') % (box, item.get('name', ''))
            html += Markup('</ul>')
        return html

    def _task_by_card(self, card_ids=None):
        """Return {trello_card_id: task} for the tasks linked to this board.

        The link is the card id, which Trello keeps globally unique, so a task stays
        linked to its card even after being renamed or moved to another project.
        Tasks carrying one of ``card_ids`` but no board yet (imported before 19.0.1.1.0)
        are included so the caller can adopt them.
        """
        domain = [('trello_card_id', '!=', False), ('trello_board_ref_id', '=', self.id)]
        if card_ids:
            domain = ['&', ('trello_card_id', '!=', False),
                      '|', ('trello_board_ref_id', '=', self.id),
                      '&', ('trello_board_ref_id', '=', False), ('trello_card_id', 'in', list(card_ids))]
        tasks = self.env['project.task'].with_context(active_test=False).search(domain)
        return {task.trello_card_id: task for task in tasks}

    def _task_vals(self, incoming, line, keys):
        """Convert the compared values of a card into project.task values, limited to ``keys``."""
        converters = {
            'name': lambda: {'name': incoming['name']},
            'description': lambda: {'description': Markup(incoming['description'])},
            'date_deadline': lambda: {'date_deadline': _parse_dt(incoming['date_deadline'])},
            'list': lambda: {'stage_id': line.stage_id.id},
            'tag_ids': lambda: {'tag_ids': [Command.set(incoming['tag_ids'])]},
            'user_ids': lambda: {'user_ids': [Command.set(incoming['user_ids'])]},
            'priority': lambda: {'priority': incoming['priority']},
            'state': lambda: {'state': incoming['state']},
            'active': lambda: {'active': incoming['active']},
            'trello_url': lambda: {'trello_url': incoming['trello_url']},
        }
        vals = {}
        for key in keys:
            vals.update(converters[key]())
        return vals

    def _sync_cards(self, cards, tags, members, checklists):
        stats = defaultdict(int)
        Task = self.env['project.task'].with_context(
            active_test=False, trello_sync=True, mail_create_nolog=True,
            mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True)
        line_by_list = {line.trello_list_id: line for line in self.list_map_ids}
        existing = self._task_by_card({card['id'] for card in cards})
        Task.browse([t.id for t in existing.values() if not t.trello_board_ref_id]).write(
            {'trello_board_ref_id': self.id})
        seen = set()
        for card in cards:
            seen.add(card['id'])
            line = line_by_list.get(card['idList'])
            if not line or line.state != 'mapped' or not line.stage_id:
                stats['skipped'] += 1
                continue
            card_tags = self.env['project.tags'].browse([tags[l].id for l in card.get('idLabels', []) if l in tags])
            users = self.env['res.users'].browse(
                [members[m].user_id.id for m in card.get('idMembers', []) if m in members and members[m].user_id])
            # JSON-comparable snapshot of what Trello says now.
            incoming = {
                'name': card.get('name') or self.env._("(no title)"),
                'description': str(self._card_description(card, checklists.get(card['id'], []))),
                'date_deadline': card.get('due') or False,
                'list': card['idList'],
                'tag_ids': sorted(card_tags.ids),
                'user_ids': sorted(users.ids),
                'priority': '1' if any(card_tags.mapped('trello_priority')) else '0',
                'state': '1_done' if card.get('dueComplete') else line.task_state,
                'active': not card.get('closed'),
                'trello_url': card.get('url'),
            }
            task = existing.get(card['id'])
            if not task:
                vals = self._task_vals(incoming, line, incoming.keys())
                vals.update({
                    'project_id': self.project_id.id,
                    'trello_card_id': card['id'],
                    'trello_board_ref_id': self.id,
                    'trello_card_name': incoming['name'],
                    'trello_synced_values': incoming,
                })
                Task.create(vals)
                stats['created'] += 1
                continue
            if task.trello_card_name != incoming['name']:
                task.trello_card_name = incoming['name']  # always current, whatever the task title is
            last = task.trello_synced_values
            if not last:
                # Imported before 19.0.1.1.0: take today's card as the baseline, keep the Odoo edits.
                task.trello_synced_values = incoming
                continue
            # Only fields changed in Trello since the last sync are written, so Odoo-side
            # edits (renamed task, other stage, other assignee...) are kept until the card changes them.
            changed = [key for key, value in incoming.items() if last.get(key) != value]
            if 'list' in changed and task.project_id != self.project_id:
                changed.remove('list')  # the list's stage belongs to the board's project, not the task's new one
            if changed:
                vals = self._task_vals(incoming, line, changed)
                vals['trello_synced_values'] = incoming
                task.with_context(trello_sync=True, mail_auto_subscribe_no_notify=True).write(vals)
                stats['updated'] += 1
            elif last != incoming:
                task.trello_synced_values = incoming
        gone = Task.browse([t.id for card_id, t in existing.items() if card_id not in seen and t.active])
        gone.write({'active': False})
        stats['archived'] = len(gone)
        return stats

    def _sync_attachments(self):
        api_client = self.env['trello.api']
        max_mb = int(self.env['ir.config_parameter'].sudo().get_param('trello.max_attachment_mb', 25) or 25)
        cards = api_client._request(f'/boards/{self.trello_id}/cards', {
            'filter': 'all',
            'fields': 'id',
            'attachments': 'true',
            'attachment_fields': 'id,name,url,mimeType,bytes,isUpload',
        })
        tasks = self._task_by_card()
        Attachment = self.env['ir.attachment']
        all_ids = [a['id'] for c in cards for a in c.get('attachments', [])]
        done = set(Attachment.sudo().search([('trello_attachment_id', 'in', all_ids)]).mapped('trello_attachment_id'))
        count = 0
        for card in cards:
            task = tasks.get(card['id'])
            if not task:
                continue
            for att in card.get('attachments', []):
                if att['id'] in done:
                    continue
                vals = {
                    'name': att.get('name') or 'attachment',
                    'res_model': 'project.task',
                    'res_id': task.id,
                    'trello_attachment_id': att['id'],
                }
                raw = None
                if att.get('isUpload') and (att.get('bytes') or 0) <= max_mb * 1024 * 1024:
                    raw = api_client._download(att['url'])
                if raw is not None:
                    vals.update({'type': 'binary', 'raw': raw})
                    if att.get('mimeType'):
                        vals['mimetype'] = att['mimeType']
                else:
                    vals.update({'type': 'url', 'url': att['url']})
                Attachment.create(vals)
                count += 1
        return count

    def _sync_comments(self):
        api_client = self.env['trello.api']
        params = {'filter': 'commentCard', 'limit': PAGE_LIMIT}
        if self.comments_since:
            params['since'] = self.comments_since.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        actions = []
        while True:
            batch = api_client._request(f'/boards/{self.trello_id}/actions', params)
            actions += batch
            if len(batch) < PAGE_LIMIT:
                break
            params['before'] = batch[-1]['id']
        if not actions:
            return 0
        done = set(self.env['mail.message'].sudo().search(
            [('trello_action_id', 'in', [a['id'] for a in actions])]).mapped('trello_action_id'))
        tasks = self._task_by_card()
        count = 0
        for action in reversed(actions):  # Trello returns newest first
            if action['id'] in done:
                continue
            task = tasks.get(action.get('data', {}).get('card', {}).get('id'))
            if not task:
                continue
            author = (action.get('memberCreator') or {}).get('fullName') or 'Trello'
            text = action.get('data', {}).get('text') or ''
            body = Markup('<p><strong>%s</strong> (Trello):</p><p>%s</p>') % (
                author, Markup('<br/>').join(escape(line) for line in text.splitlines()))
            message = task.with_context(mail_auto_subscribe_no_notify=True).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_note')
            message.sudo().write({'trello_action_id': action['id'], 'date': _parse_dt(action.get('date'))})
            count += 1
        return count
