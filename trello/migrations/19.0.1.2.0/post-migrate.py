# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    """Fill the new Trello card name from the card values stored at the last sync."""
    cr.execute("""
        UPDATE project_task
           SET trello_card_name = trello_synced_values->>'name'
         WHERE trello_card_id IS NOT NULL
           AND trello_card_name IS NULL
           AND trello_synced_values ? 'name'
    """)
