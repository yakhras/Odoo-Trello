# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import importlib.util
from pathlib import Path

from odoo.tests import TransactionCase, tagged

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def load_migration(version, name):
    spec = importlib.util.spec_from_file_location(f'trello_{name}', MIGRATIONS / version / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged('post_install', '-at_install')
class TestMigrations(TransactionCase):

    def test_1_1_0_archives_duplicates_and_keeps_the_original(self):
        cr = self.env.cr
        # Rebuild the state of 19.0.1.0.0, when one card could have a task in several projects.
        cr.execute("SELECT conname FROM pg_constraint WHERE conname LIKE 'project_task%trello_card_uniq'")
        for (name,) in cr.fetchall():
            cr.execute(f'ALTER TABLE project_task DROP CONSTRAINT "{name}"')
        Project = self.env['project.project']
        original = self.env['project.task'].create({'name': 'Mine', 'project_id': Project.create({'name': 'P1'}).id,
                                                    'trello_card_id': 'X'})
        copy = self.env['project.task'].create({'name': 'Copy', 'project_id': Project.create({'name': 'P2'}).id,
                                                'trello_card_id': 'X'})
        message = copy.message_post(body='from Trello')
        message.trello_action_id = 'act'
        attachment = self.env['ir.attachment'].create({
            'name': 'f', 'res_model': 'project.task', 'res_id': copy.id, 'trello_attachment_id': 'att'})
        self.env.flush_all()

        load_migration('19.0.1.1.0', 'pre-migrate').migrate(cr, '19.0.1.0.0')
        self.env.invalidate_all()

        self.assertEqual((original.active, original.trello_card_id), (True, 'X'))
        self.assertEqual((copy.active, copy.trello_card_id), (False, False))
        self.assertEqual(message.res_id, original.id)
        self.assertEqual(attachment.res_id, original.id)

    def test_1_2_0_fills_card_name(self):
        task = self.env['project.task'].create({
            'name': 'Renamed in Odoo', 'project_id': self.env['project.project'].create({'name': 'P'}).id,
            'trello_card_id': 'Y', 'trello_synced_values': {'name': 'Card name'}})
        self.env.flush_all()
        load_migration('19.0.1.2.0', 'post-migrate').migrate(self.env.cr, '19.0.1.1.0')
        self.env.invalidate_all()
        self.assertEqual(task.trello_card_name, 'Card name')
