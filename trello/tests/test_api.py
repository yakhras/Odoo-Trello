# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

API = 'odoo.addons.trello.models.trello_api'


class FakeResponse:
    def __init__(self, payload=None, status=200, headers=None, content=b''):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._payload


@tagged('post_install', '-at_install')
class TestTrelloApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.ICP.set_str('trello.api_key', 'test-key')
        cls.ICP.set_str('trello.api_token', 'test-token')
        cls.api = cls.env['trello.api']

    def setUp(self):
        super().setUp()
        patcher = patch(f'{API}.time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_key_and_token_sent_as_query_params(self):
        with patch(f'{API}.requests.request', return_value=FakeResponse({'id': 'me'})) as request:
            self.assertEqual(self.api._request('/members/me'), {'id': 'me'})
        params = request.call_args.kwargs['params']
        self.assertEqual((params['key'], params['token']), ('test-key', 'test-token'))

    def test_missing_credentials(self):
        self.ICP.set_str('trello.api_token', '')
        with self.assertRaises(UserError):
            self.api._request('/members/me')

    def test_revoked_token(self):
        with patch(f'{API}.requests.request', return_value=FakeResponse('invalid token', status=401)):
            with self.assertRaisesRegex(UserError, 'rejected'):
                self.api._request('/members/me')

    def test_rate_limit_is_retried(self):
        limited = FakeResponse({'error': 'API_TOKEN_LIMIT_EXCEEDED'}, status=429,
                               headers={'x-rate-limit-api-token-interval-ms': '10000'})
        with patch(f'{API}.requests.request', side_effect=[limited, FakeResponse([])]) as request:
            self.assertEqual(self.api._request('/boards/b1/lists'), [])
        self.assertEqual(request.call_count, 2)

    def test_other_errors(self):
        with patch(f'{API}.requests.request', return_value=FakeResponse('board not found', status=404)):
            with self.assertRaisesRegex(UserError, '404'):
                self.api._request('/boards/nope')

    def test_download_sends_oauth_header_to_trello_only(self):
        with patch(f'{API}.requests.get', return_value=FakeResponse(content=b'file')) as get:
            self.assertEqual(self.api._download('https://trello.com/1/cards/c/attachments/a/download/f.png'),
                             b'file')
            self.assertIn('oauth_token="test-token"', get.call_args.kwargs['headers']['Authorization'])
            get.reset_mock()
            self.assertIsNone(self.api._download('https://evil.example.com/f.png'))
            get.assert_not_called()

    def test_failed_download_returns_none(self):
        with patch(f'{API}.requests.get', return_value=FakeResponse(status=403)):
            self.assertIsNone(self.api._download('https://trello.com/1/cards/c/attachments/a/download/f.png'))
