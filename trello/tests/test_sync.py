# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import datetime
from unittest.mock import patch

from odoo.tests import tagged

from .common import BIG_URL, UPLOAD_URL, TrelloCase


@tagged('post_install', '-at_install')
class TestSync(TrelloCase):

    def setUp(self):
        super().setUp()
        self.board = self.activate_board()

    def sync(self):
        return self.board._sync_board()

    def test_first_sync_creates_tasks(self):
        stats = self.sync()
        self.assertEqual((stats['created'], stats['skipped']), (3, 0))
        home, logo, old = self.task('c1'), self.task('c2'), self.task('c3')
        self.assertEqual(home.project_id, self.board.project_id)
        self.assertEqual(home.stage_id.name, 'Doing')
        self.assertEqual(home.tag_ids.mapped('name'), ['Urgent'])
        self.assertEqual(home.priority, '1', "the Urgent label gives high priority")
        self.assertEqual(home.user_ids, self.ann)
        self.assertEqual(home.date_deadline, datetime(2026, 11, 1, 10, 0))
        self.assertEqual(home.state, '01_in_progress')
        self.assertIn('Hero banner', home.description)
        self.assertIn('☑ Draft', home.description)
        self.assertIn('☐ Review', home.description)
        self.assertEqual((home.trello_card_name, home.trello_board_ref_id), ('Home page', self.board))
        self.assertEqual(logo.tag_ids.mapped('name'), ['Green'], "a label without name is named after its color")
        self.assertEqual((logo.priority, logo.state), ('0', '1_done'), "a completed due date means Done")
        self.assertFalse(old.active, "an archived card gives an archived task")
        self.assertEqual(self.ann, self.env['trello.member'].search([('trello_id', '=', 'm1')]).user_id)

    def test_done_list_sets_done(self):
        self.card('c1')['idList'] = 'l3'
        self.sync()
        self.assertEqual(self.task('c1').state, '1_done')

    def test_unmapped_list_is_skipped_until_mapped(self):
        self.trello['board']['lists'].append({'id': 'l4', 'name': 'Ideas', 'pos': 4, 'closed': False})
        self.card('c2')['idList'] = 'l4'
        stats = self.sync()
        self.assertEqual(stats['skipped'], 1)
        self.assertFalse(self.task('c2'))
        self.assertEqual(self.board.unmapped_count, 1)
        self.assertFalse(self.board.comments_since, "comments are re-read while cards are skipped")
        self.board.action_apply_list_mapping()
        self.sync()
        self.assertEqual(self.task('c2').stage_id.name, 'Ideas')
        self.assertTrue(self.board.comments_since)

    def test_card_gone_from_trello_archives_task(self):
        self.sync()
        self.trello['board']['cards'] = [c for c in self.trello['board']['cards'] if c['id'] != 'c1']
        stats = self.sync()
        self.assertEqual(stats['archived'], 1)
        self.assertFalse(self.task('c1').active)
        self.assertTrue(self.task('c1').exists(), "nothing is deleted")

    def test_task_moved_to_other_project_is_not_duplicated(self):
        self.sync()
        other = self.Project.create({'name': 'Other project'})
        other_stage = self.Stage.create({'name': 'Backlog', 'project_ids': [(4, other.id)]})
        home = self.task('c1')
        home.write({'project_id': other.id, 'stage_id': other_stage.id, 'name': 'My own title'})
        stats = self.sync()
        self.assertEqual(stats['created'], 0)
        self.assertEqual(len(self.task('c1')), 1)
        self.assertEqual((home.project_id, home.name), (other, 'My own title'))
        # The card changes in Trello: the same task follows, stage stays in its new project.
        self.card('c1').update({'name': 'Home page v2', 'idList': 'l3'})
        self.sync()
        self.assertEqual(len(self.task('c1')), 1)
        self.assertEqual((home.name, home.project_id, home.stage_id), ('Home page v2', other, other_stage))
        self.assertEqual(home.state, '1_done')

    def test_odoo_rename_kept_until_card_renamed(self):
        self.sync()
        home = self.task('c1')
        home.name = 'Landing page'
        self.sync()
        self.assertEqual((home.name, home.trello_card_name), ('Landing page', 'Home page'))
        self.card('c1')['name'] = 'Home page (new)'
        self.sync()
        self.assertEqual((home.name, home.trello_card_name), ('Home page (new)', 'Home page (new)'))

    def test_odoo_edits_of_other_fields_are_kept(self):
        self.sync()
        home = self.task('c1')
        home.write({'user_ids': [(6, 0, [])], 'priority': '0'})
        self.sync()
        self.assertFalse(home.user_ids)
        self.assertEqual(home.priority, '0')

    def test_task_imported_before_snapshots_is_not_overwritten(self):
        self.sync()
        home = self.task('c1')
        home.write({'name': 'Edited before upgrade', 'trello_synced_values': False})
        self.sync()
        self.assertEqual(home.name, 'Edited before upgrade')
        self.assertEqual(home.trello_synced_values['name'], 'Home page')

    def test_comments_are_imported_once_across_pages(self):
        with patch('odoo.addons.trello.models.trello_board.PAGE_LIMIT', 1):
            self.sync()
            self.sync()
        messages = self.env['mail.message'].search(
            [('model', '=', 'project.task'), ('res_id', '=', self.task('c1').id),
             ('trello_action_id', '!=', False)], order='date, id')
        self.assertEqual(messages.mapped('trello_action_id'), ['act1', 'act2'])
        self.assertIn('First comment', messages[0].body)
        self.assertEqual(messages[0].date, datetime(2026, 10, 1, 9, 0))

    def test_attachments(self):
        self.sync()
        self.sync()
        attachments = self.env['ir.attachment'].search(
            [('res_model', '=', 'project.task'), ('res_id', '=', self.task('c1').id)])
        by_id = {a.trello_attachment_id: a for a in attachments}
        self.assertEqual(set(by_id), {'a1', 'a2', 'a3'}, "no attachment is imported twice")
        self.assertEqual((by_id['a1'].type, by_id['a1'].raw.content), ('binary', b'PNGDATA'))
        self.assertEqual((by_id['a2'].type, by_id['a2'].url), ('url', 'https://docs.example.com/spec'))
        self.assertEqual((by_id['a3'].type, by_id['a3'].url), ('url', BIG_URL), "too large: kept as a link")
        self.assertEqual(self.download_calls, [UPLOAD_URL])

    def test_failed_download_falls_back_to_link(self):
        self.downloads.clear()
        self.sync()
        upload = self.env['ir.attachment'].search([('trello_attachment_id', '=', 'a1')])
        self.assertEqual((upload.type, upload.url), ('url', UPLOAD_URL))

    def test_priority_flag_set_by_hand(self):
        self.sync()
        green = self.task('c2').tag_ids
        green.trello_priority = True
        self.card('c2')['name'] = 'Logo v2'  # any change re-evaluates the card
        self.sync()
        self.assertEqual(self.task('c2').priority, '1')

    def test_cron_syncs_active_boards(self):
        with patch.object(self.env.cr, 'commit'):
            self.Board._cron_sync()
        self.assertEqual(len(self.Task.search([('trello_board_ref_id', '=', self.board.id)])), 3)
