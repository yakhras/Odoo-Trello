# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import time
from urllib.parse import urlparse

import requests

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TRELLO_API_URL = 'https://api.trello.com/1'
TIMEOUT = 30
MAX_RETRIES = 3


class TrelloApi(models.AbstractModel):
    _name = 'trello.api'
    _description = 'Trello REST API client'

    def _credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('trello.api_key')
        token = ICP.get_param('trello.api_token')
        if not key or not token:
            raise UserError(self.env._("Trello API key and token are not set (Project > Configuration > Settings > Trello)."))
        return key, token

    def _request(self, path, params=None, method='GET'):
        """Call the Trello REST API and return the decoded JSON.

        Key and token are sent as query parameters (Authorization.pdf). A 429 is
        retried after the rate-limit interval announced in the response headers
        (Rate Limits.pdf); a 401 means the token was revoked or is invalid.
        """
        key, token = self._credentials()
        query = dict(params or {}, key=key, token=token)
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.request(method, TRELLO_API_URL + path, params=query, timeout=TIMEOUT)
            except requests.RequestException as e:
                raise UserError(self.env._("Cannot reach Trello: %s", e)) from e
            if resp.status_code != 429 or attempt == MAX_RETRIES:
                break
            interval_ms = resp.headers.get('x-rate-limit-api-token-interval-ms') or 10000
            _logger.info("Trello rate limit hit on %s (%s), retrying", path, resp.text[:100])
            time.sleep(min(int(interval_ms) / 1000.0, 10))

        if resp.status_code == 401:
            raise UserError(self.env._(
                "Trello rejected the API key/token (%s). Generate a new token and save it in the settings.",
                resp.text[:200]))
        if resp.status_code >= 400:
            raise UserError(self.env._("Trello API error %(code)s on %(path)s: %(msg)s",
                                       code=resp.status_code, path=path, msg=resp.text[:300]))
        return resp.json()

    def _download(self, url):
        """Download an uploaded card attachment; return bytes or None on failure.

        Uploaded attachments require the OAuth Authorization header (format from
        Authorization.pdf). Credentials are only ever sent to Trello hosts.
        """
        host = urlparse(url).hostname or ''
        if not (host == 'trello.com' or host.endswith('.trello.com')):
            return None
        key, token = self._credentials()
        headers = {'Authorization': f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'}
        try:
            resp = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as e:
            _logger.warning("Trello attachment download failed for %s: %s", url, e)
            return None
        if resp.status_code != 200:
            _logger.warning("Trello attachment download failed for %s: HTTP %s", url, resp.status_code)
            return None
        return resp.content
