# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    trello_attachment_id = fields.Char(copy=False, index='btree_not_null')
