# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import TrelloCase


@tagged('post_install', '-at_install')
class TestBoardWorkflow(TrelloCase):

    def test_fetch_twice_creates_no_duplicate(self):
        self.Board.action_fetch_boards()
        self.Board.action_fetch_boards()
        board = self.Board.search([('trello_id', '=', 'b1')])
        self.assertEqual(len(board), 1)
        self.assertEqual((board.state, board.link_mode), ('draft', 'new'))

    def test_fetch_suggests_project_with_same_name(self):
        project = self.Project.create({'name': 'website redesign'})
        board = self.fetch_board()
        self.assertEqual((board.link_mode, board.project_id), ('existing', project))
        self.assertEqual(board.state, 'draft', "a suggestion is never applied without Confirm")

    def test_confirm_existing_needs_project(self):
        board = self.fetch_board()
        board.link_mode = 'existing'
        with self.assertRaises(ValidationError):
            board.action_confirm()

    def test_confirm_refuses_project_of_another_board(self):
        project = self.Project.create({'name': 'Other', 'trello_board_id': 'another-board'})
        board = self.fetch_board()
        board.write({'link_mode': 'existing', 'project_id': project.id})
        with self.assertRaises(ValidationError):
            board.action_confirm()

    def test_one_project_per_board_in_database(self):
        project = self.Project.create({'name': 'Shared'})
        self.Board.create({'name': 'A', 'trello_id': 'x1', 'project_id': project.id})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Board.create({'name': 'B', 'trello_id': 'x2', 'project_id': project.id})
            self.env.flush_all()

    def test_confirm_new_refuses_existing_project_name(self):
        self.Project.create({'name': 'Website Redesign'})
        board = self.fetch_board()
        board.write({'link_mode': 'new', 'project_id': False})
        with self.assertRaisesRegex(ValidationError, 'already exists'):
            board.action_confirm()

    def test_confirm_loads_lists_with_suggestions(self):
        project = self.Project.create({'name': 'Site'})
        doing = self.Stage.create({'name': 'doing', 'project_ids': [(4, project.id)]})
        board = self.fetch_board()
        board.write({'link_mode': 'existing', 'project_id': project.id})
        board.action_confirm()
        self.assertEqual(board.state, 'lists')
        lines = {line.trello_list_id: line for line in board.list_map_ids}
        self.assertEqual(set(lines), {'l1', 'l2', 'l3'})
        self.assertEqual((lines['l2'].mode, lines['l2'].stage_id), ('merge', doing))
        self.assertEqual(lines['l1'].mode, 'new')
        self.assertEqual(lines['l3'].task_state, '1_done')
        self.assertEqual(set(board.list_map_ids.mapped('state')), {'unmapped'})

    def test_activate_needs_a_stage_for_merge_lines(self):
        board = self.fetch_board()
        board.action_confirm()
        board.list_map_ids[0].write({'mode': 'merge', 'stage_id': False})
        with self.assertRaises(UserError):
            board.action_activate()
        self.assertEqual(board.state, 'lists')

    def test_activate_creates_project_and_stages(self):
        board = self.activate_board()
        self.assertEqual(board.state, 'active')
        self.assertEqual((board.project_id.name, board.project_id.trello_board_id), ('Website Redesign', 'b1'))
        stages = board.list_map_ids.stage_id
        self.assertEqual(stages.mapped('name'), ['To Do', 'Doing', 'Done'])
        self.assertTrue(all(board.project_id in stage.project_ids for stage in stages))
        self.assertEqual(set(board.list_map_ids.mapped('state')), {'mapped'})

    def test_activate_existing_merges_into_its_stage(self):
        project = self.Project.create({'name': 'Site'})
        doing = self.Stage.create({'name': 'Doing', 'project_ids': [(4, project.id)]})
        board = self.activate_board(project)
        self.assertEqual(board.list_map_ids.filtered(lambda l: l.trello_list_id == 'l2').stage_id, doing)
        self.assertEqual(self.Stage.search_count([('name', '=', 'Doing'), ('project_ids', 'in', project.id)]), 1)

    def test_unlink_deletes_nothing(self):
        board = self.activate_board()
        board.action_sync()
        project = board.project_id
        tasks = self.Task.search([('project_id', '=', project.id)])
        board.action_unlink_project()
        self.assertEqual(board.state, 'draft')
        self.assertFalse(board.list_map_ids)
        self.assertTrue(project.exists())
        self.assertFalse(project.trello_board_id)
        self.assertEqual(len(tasks.exists()), 3)
        self.assertFalse(any(tasks.mapped('trello_card_id')))

    def test_pause_and_resume(self):
        board = self.activate_board()
        board.action_pause()
        self.assertEqual(board.state, 'paused')
        self.Board._cron_sync()
        self.assertFalse(self.task('c1'), "a paused board is not synced")
        board.action_resume()
        self.assertEqual(board.state, 'active')
