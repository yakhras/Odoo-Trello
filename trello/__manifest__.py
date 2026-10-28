# Copyright 2026 Yaser Akhras
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Trello',
    'version': '18.0.1.3.0',
    'summary': 'Import Trello boards, lists, cards, comments and attachments into Odoo Projects',
    'description': """
Trello -> Odoo one-way synchronisation
======================================
* Board -> Project control stage (link to existing project or create a new one, no duplicates)
* List -> Stage control stage (merge into existing stage or create a new one)
* Cards -> Tasks (description, checklists, deadline, labels, members, priority, state)
* Comments -> chatter notes, attachments -> task attachments
* Trello Inbox: review new and changed cards before they reach tasks (per board)
* Polling via scheduled action (no webhooks required)
""",
    'category': 'Services/Project',
    'author': 'Yaser Akhras',
    'maintainers': ['yakhras'],
    'website': 'https://yaserakhras.com',
    'license': 'AGPL-3',
    'depends': ['project', 'mail'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/trello_board_views.xml',
        'views/trello_member_views.xml',
        'views/trello_card_change_views.xml',
        'views/project_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
