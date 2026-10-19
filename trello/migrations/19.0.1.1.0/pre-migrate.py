# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Remove duplicate tasks created for cards whose task was moved to another project.

    Before 19.0.1.1.0 the sync only looked for tasks in the board's project, so moving a
    task elsewhere made the next sync create a second task for the same card. Keep the
    oldest task (the one the user worked on), move the Trello comments/attachments of the
    copies onto it, then archive the copies and detach them from the card, so the new
    UNIQUE(trello_card_id) constraint can be created. Nothing is deleted.
    """
    cr.execute("""
        CREATE TEMP TABLE trello_dup ON COMMIT DROP AS
        SELECT id, keep_id FROM (
            SELECT id, min(id) OVER (PARTITION BY trello_card_id) AS keep_id
              FROM project_task
             WHERE trello_card_id IS NOT NULL
        ) t
        WHERE id <> keep_id
    """)
    cr.execute("""
        UPDATE mail_message m SET res_id = d.keep_id
          FROM trello_dup d
         WHERE m.model = 'project.task' AND m.res_id = d.id AND m.trello_action_id IS NOT NULL
    """)
    cr.execute("""
        UPDATE ir_attachment a SET res_id = d.keep_id
          FROM trello_dup d
         WHERE a.res_model = 'project.task' AND a.res_id = d.id AND a.trello_attachment_id IS NOT NULL
    """)
    cr.execute("""
        UPDATE project_task t SET active = false, trello_card_id = NULL, trello_url = NULL
          FROM trello_dup d
         WHERE t.id = d.id
     RETURNING t.id, d.keep_id
    """)
    for dup_id, keep_id in cr.fetchall():
        _logger.info("Trello: archived duplicate task %s, kept task %s", dup_id, keep_id)
