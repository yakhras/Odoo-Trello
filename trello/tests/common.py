# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import copy
from unittest.mock import patch

from odoo.tests import TransactionCase, new_test_user

BOARD = 'b1'
UPLOAD_URL = 'https://trello.com/1/cards/c1/attachments/a1/download/mock.png'
BIG_URL = 'https://trello.com/1/cards/c1/attachments/a3/download/meeting.mp3'


def trello_data():
    """A small board as the Trello REST API returns it."""
    return {
        'boards': [{'id': BOARD, 'name': 'Website Redesign', 'url': 'https://trello.com/b/b1', 'closed': False}],
        'board': {
            'id': BOARD, 'name': 'Website Redesign', 'url': 'https://trello.com/b/b1', 'closed': False,
            'lists': [
                {'id': 'l1', 'name': 'To Do', 'pos': 1, 'closed': False},
                {'id': 'l2', 'name': 'Doing', 'pos': 2, 'closed': False},
                {'id': 'l3', 'name': 'Done', 'pos': 3, 'closed': False},
            ],
            'labels': [
                {'id': 'lab1', 'name': 'Urgent', 'color': 'red'},
                {'id': 'lab2', 'name': '', 'color': 'green'},
            ],
            'members': [{'id': 'm1', 'fullName': 'Ann Smith', 'username': 'ann'}],
            'checklists': [{
                'id': 'cl1', 'idCard': 'c1', 'name': 'Steps', 'pos': 1,
                'checkItems': [
                    {'name': 'Draft', 'state': 'complete', 'pos': 1},
                    {'name': 'Review', 'state': 'incomplete', 'pos': 2},
                ],
            }],
            'cards': [
                {'id': 'c1', 'name': 'Home page', 'desc': 'Hero banner', 'due': '2026-11-01T10:00:00.000Z',
                 'dueComplete': False, 'closed': False, 'idList': 'l2', 'idLabels': ['lab1'],
                 'idMembers': ['m1'], 'url': 'https://trello.com/c/c1'},
                {'id': 'c2', 'name': 'Logo', 'desc': '', 'due': None, 'dueComplete': True, 'closed': False,
                 'idList': 'l1', 'idLabels': ['lab2'], 'idMembers': [], 'url': 'https://trello.com/c/c2'},
                {'id': 'c3', 'name': 'Old idea', 'desc': '', 'due': None, 'dueComplete': False, 'closed': True,
                 'idList': 'l1', 'idLabels': [], 'idMembers': [], 'url': 'https://trello.com/c/c3'},
            ],
        },
        'attachments': [
            {'id': 'c1', 'attachments': [
                {'id': 'a1', 'name': 'mock.png', 'url': UPLOAD_URL, 'mimeType': 'image/png',
                 'bytes': 7, 'isUpload': True},
                {'id': 'a2', 'name': 'Spec', 'url': 'https://docs.example.com/spec', 'mimeType': '',
                 'bytes': None, 'isUpload': False},
                {'id': 'a3', 'name': 'meeting.mp3', 'url': BIG_URL, 'mimeType': 'audio/mpeg',
                 'bytes': 100 * 1024 * 1024, 'isUpload': True},
            ]},
            {'id': 'c2', 'attachments': []},
            {'id': 'c3', 'attachments': []},
        ],
        # newest first, like Trello
        'actions': [
            {'id': 'act2', 'date': '2026-10-02T09:00:00.000Z', 'memberCreator': {'fullName': 'Ann Smith'},
             'data': {'text': 'Second comment', 'card': {'id': 'c1'}}},
            {'id': 'act1', 'date': '2026-10-01T09:00:00.000Z', 'memberCreator': {'fullName': 'Ann Smith'},
             'data': {'text': 'First comment', 'card': {'id': 'c1'}}},
        ],
    }


class TrelloCase(TransactionCase):
    """Trello API fully mocked: no HTTP call ever leaves the test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('trello.api_key', 'test-key')
        ICP.set_param('trello.api_token', 'test-token')
        cls.Board = cls.env['trello.board']
        cls.Project = cls.env['project.project']
        cls.Task = cls.env['project.task'].with_context(active_test=False)
        cls.Stage = cls.env['project.task.type']
        cls.ann = new_test_user(cls.env, login='ann_trello', name='Ann Smith',
                                groups='project.group_project_user')

    def setUp(self):
        super().setUp()
        self.trello = trello_data()
        self.downloads = {UPLOAD_URL: b'PNGDATA'}
        self.download_calls = []
        api_class = self.registry['trello.api']
        for patcher in (
            patch.object(api_class, '_request', autospec=True, side_effect=self._fake_request),
            patch.object(api_class, '_download', autospec=True, side_effect=self._fake_download),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fake_request(self, api, path, params=None, method='GET'):
        params = params or {}
        data = self.trello
        if path == '/members/me/boards':
            return copy.deepcopy(data['boards'])
        if path == f'/boards/{BOARD}/lists':
            return copy.deepcopy(data['board']['lists'])
        if path == f'/boards/{BOARD}':
            return copy.deepcopy(data['board'])
        if path == f'/boards/{BOARD}/cards':
            return copy.deepcopy(data['attachments'])
        if path == f'/boards/{BOARD}/actions':
            actions = data['actions']
            if params.get('before'):
                ids = [a['id'] for a in actions]
                actions = actions[ids.index(params['before']) + 1:]
            return copy.deepcopy(actions[:params.get('limit', 1000)])
        raise AssertionError(f"Unexpected Trello call {path}")

    def _fake_download(self, api, url):
        self.download_calls.append(url)
        return self.downloads.get(url)

    def card(self, card_id):
        return next(c for c in self.trello['board']['cards'] if c['id'] == card_id)

    def fetch_board(self):
        self.Board.action_fetch_boards()
        return self.Board.search([('trello_id', '=', BOARD)])

    def activate_board(self, project=None, review=False):
        board = self.fetch_board()
        board.write({'link_mode': 'existing' if project else 'new', 'project_id': project.id if project else False,
                     'review_changes': review})
        board.action_confirm()
        board.action_activate()
        return board

    def task(self, card_id):
        return self.Task.search([('trello_card_id', '=', card_id)])
