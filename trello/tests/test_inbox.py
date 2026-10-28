# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import re

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TrelloCase


@tagged('post_install', '-at_install')
class TestInbox(TrelloCase):

    def setUp(self):
        super().setUp()
        self.board = self.activate_board(review=True)
        self.Change = self.env['trello.card.change']

    def sync(self):
        return self.board._sync_board()

    def pending(self, card_id=None):
        domain = [('board_id', '=', self.board.id), ('state', '=', 'pending')]
        if card_id:
            domain.append(('trello_card_id', '=', card_id))
        return self.Change.search(domain)

    def import_all(self):
        self.sync()
        self.pending().action_apply()

    def test_review_is_on_by_default(self):
        self.assertTrue(self.Board.new({'name': 'x', 'trello_id': 'x'}).review_changes)

    def test_new_cards_wait_in_inbox(self):
        stats = self.sync()
        self.assertFalse(self.task('c1') | self.task('c2') | self.task('c3'), "nothing reaches the tasks")
        self.assertEqual(stats['pending'], 3)
        self.assertEqual(set(self.pending().mapped('kind')), {'new'})
        self.assertTrue(self.pending('c3').card_closed)
        self.assertIn('Home page', self.pending('c1').changes_html)
        self.assertFalse(self.board.comments_since, "comments of pending cards are read again later")
        self.assertEqual(self.board.pending_change_count, 3)

    def test_apply_new_card_creates_task(self):
        self.sync()
        change = self.pending('c1')
        change.action_apply()
        home = self.task('c1')
        self.assertEqual(change.state, 'applied')
        self.assertEqual(change.task_id, home)
        self.assertEqual((home.project_id, home.stage_id.name), (self.board.project_id, 'Doing'))
        self.pending().action_ignore()
        self.sync()
        self.assertEqual(len(home.message_ids.filtered(lambda m: m.trello_action_id)), 2,
                         "comments of an applied card are imported by the next sync")

    def test_second_sync_does_not_duplicate(self):
        self.sync()
        fetched = self.pending()
        self.sync()
        self.assertEqual(self.pending(), fetched)

    def test_ignored_new_card_is_not_proposed_again(self):
        self.sync()
        change = self.pending('c2')
        change.action_ignore()
        self.sync()
        self.assertFalse(self.pending('c2'))
        change.action_reset()
        self.assertEqual(self.pending('c2'), change)

    def test_link_new_card_to_existing_task(self):
        task = self.Task.create({'name': 'Logo work', 'project_id': self.board.project_id.id})
        self.sync()
        change = self.pending('c2')
        change.task_id = task
        change.action_apply()
        self.assertEqual((task.trello_card_id, task.name), ('c2', 'Logo work'), "the task is linked as it is")
        self.assertFalse(self.Task.search_count([('name', '=', 'Logo')]))
        self.card('c2')['name'] = 'Logo v2'
        self.sync()
        self.assertEqual(self.pending('c2').changed_keys, ['name'])

    def test_card_change_waits_for_review(self):
        self.import_all()
        self.card('c1')['name'] = 'Landing page'
        self.sync()
        change = self.pending('c1')
        self.assertEqual((change.kind, change.changed_keys), ('update', ['name']))
        self.assertEqual(self.task('c1').name, 'Home page', "task untouched until applied")
        self.assertIn('Landing page', change.changes_html)
        change.action_apply()
        self.assertEqual(self.task('c1').name, 'Landing page')
        self.sync()
        self.assertFalse(self.pending())

    def test_changed_deadline_is_shown_in_user_timezone(self):
        self.import_all()
        self.env.user.tz = 'Europe/Istanbul'  # UTC+3 all year
        self.card('c1')['due'] = '2026-11-08T10:00:00.000Z'
        self.sync()
        html = self.pending('c1').changes_html
        # Both columns: 10:00 UTC is 1:00 PM in Istanbul, the date format follows the language.
        self.assertEqual(len(re.findall(r'\b0?1:00 PM', html)), 2, html)  # 18.0: 1:00, 19+: 01:00
        self.assertNotIn('10:00', html, "no UTC time")

    def test_ignored_change_is_not_proposed_again(self):
        self.import_all()
        self.card('c1')['name'] = 'Landing page'
        self.sync()
        self.pending('c1').action_ignore()
        self.sync()
        self.assertFalse(self.pending())
        self.assertEqual(self.task('c1').name, 'Home page')
        self.card('c1')['desc'] = 'New hero'
        self.sync()
        self.assertEqual(self.pending('c1').changed_keys, ['description'], "a later change comes back")

    def test_reverted_card_drops_pending_line(self):
        self.import_all()
        self.card('c1')['name'] = 'Landing page'
        self.sync()
        self.card('c1')['name'] = 'Home page'
        self.sync()
        self.assertFalse(self.pending())

    def test_archived_and_deleted_cards(self):
        self.import_all()
        self.card('c1')['closed'] = True
        self.trello['board']['cards'] = [c for c in self.trello['board']['cards'] if c['id'] != 'c2']
        self.sync()
        self.assertEqual(self.pending('c1').kind, 'archive')
        self.assertEqual(self.pending('c2').kind, 'archive')
        self.assertTrue(self.task('c1').active and self.task('c2').active)
        self.pending('c1').action_apply()
        self.pending('c2').action_ignore()
        self.assertFalse(self.task('c1').active)
        self.assertTrue(self.task('c2').active)
        self.sync()
        self.assertFalse(self.pending(), "an ignored deletion is not proposed again")

    def test_already_linked_card_cannot_be_applied_twice(self):
        self.sync()
        change = self.pending('c1')
        self.board._create_task_from_card('c1', change.incoming, change.list_map_id)
        with self.assertRaises(UserError):
            change.action_apply()

    def test_switching_review_off_applies_directly(self):
        self.sync()
        self.board.review_changes = False
        stats = self.sync()
        self.assertEqual(stats['created'], 3)
        self.assertFalse(self.pending(), "pending lines are dropped once the sync applies cards itself")

    def test_unlink_board_removes_inbox(self):
        self.sync()
        self.board.action_unlink_project()
        self.assertFalse(self.Change.search([('board_id', '=', self.board.id)]))
