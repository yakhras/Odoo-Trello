# Generated demo data for screenshots (no Trello account, no API call).
# The Trello API client is replaced, for this shell session only, by a fake that answers
# with the boards below; the module's own workflow (fetch, confirm, map, activate, sync)
# then creates the projects, stages, tasks, comments and attachments. A last sync with
# Review Before Applying on fills the Inbox with one new, one changed and one archived card.
# Run on a throwaway DB: odoo shell -d trello_demo < tools/demo_data.py
# (scripts/module_lab.ps1 -Do up does this). The file is the same on every series branch.
import base64
import copy
import io

from PIL import Image, ImageDraw


def png(text, color):
    img = Image.new('RGB', (640, 360), color)
    ImageDraw.Draw(img).text((40, 160), text, fill='white')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def lst(i, name, pos):
    return {'id': i, 'name': name, 'pos': pos, 'closed': False}


def card(i, name, list_id, labels=(), members=(), due=None, done=False, closed=False, desc=''):
    return {'id': i, 'name': name, 'desc': desc, 'due': due, 'dueComplete': done, 'closed': closed,
            'idList': list_id, 'idLabels': list(labels), 'idMembers': list(members),
            'url': f'https://trello.com/c/{i}'}


HERO_URL = 'https://trello.com/1/cards/w1/attachments/at1/download/hero-mockup.png'
BOARDS = {
    'wb': {
        'id': 'wb', 'name': 'Website Redesign', 'url': 'https://trello.com/b/wb', 'closed': False,
        'lists': [lst('wl1', 'To Do', 1), lst('wl2', 'In Progress', 2), lst('wl3', 'Review', 3),
                  lst('wl4', 'Done', 4)],
        'labels': [{'id': 'lu', 'name': 'Urgent', 'color': 'red'},
                   {'id': 'lf', 'name': 'Frontend', 'color': 'blue'},
                   {'id': 'lb', 'name': 'Backend', 'color': 'purple'}],
        'members': [{'id': 'm1', 'fullName': 'Ann Smith', 'username': 'annsmith'},
                    {'id': 'm2', 'fullName': 'Omar Haddad', 'username': 'omarh'}],
        'checklists': [{'id': 'k1', 'idCard': 'w1', 'name': 'Steps', 'pos': 1, 'checkItems': [
            {'name': 'Wireframe', 'state': 'complete', 'pos': 1},
            {'name': 'High-fidelity mockup', 'state': 'complete', 'pos': 2},
            {'name': 'Responsive check', 'state': 'incomplete', 'pos': 3}]}],
        'cards': [
            card('w1', 'Home page hero section', 'wl2', ['lu', 'lf'], ['m1'], '2026-11-05T16:00:00.000Z',
                 desc='New hero with the product photo and one clear call to action.\n'
                      'Design: https://example.com/figma/hero'),
            card('w2', 'Contact form validation', 'wl1', ['lb'], ['m2'], '2026-11-12T16:00:00.000Z',
                 desc='Validate email and phone on the server, show errors inline.'),
            card('w3', 'Logo refresh', 'wl4', ['lf'], ['m1'], '2026-10-10T16:00:00.000Z', done=True),
            card('w4', 'Blog layout', 'wl3', ['lf'], ['m1', 'm2'], '2026-11-20T16:00:00.000Z',
                 desc='Two columns on desktop, one on phones.'),
            card('w5', 'Cookie banner', 'wl1', ['lu', 'lb'], ['m2'], '2026-11-03T16:00:00.000Z'),
            card('w6', 'Sitemap and SEO tags', 'wl2', ['lb'], [], None),
            card('w7', 'Old landing page', 'wl4', [], [], None, closed=True),
        ],
        'attachments': [
            {'id': 'w1', 'attachments': [
                {'id': 'at1', 'name': 'hero-mockup.png', 'url': HERO_URL, 'mimeType': 'image/png',
                 'bytes': 20000, 'isUpload': True},
                {'id': 'at2', 'name': 'Brand guidelines', 'url': 'https://example.com/brand-guidelines',
                 'mimeType': '', 'bytes': None, 'isUpload': False}]},
        ],
        'actions': [
            {'id': 'ac2', 'date': '2026-10-16T10:30:00.000Z', 'memberCreator': {'fullName': 'Omar Haddad'},
             'data': {'text': 'Looks great. Can we try a darker overlay on the photo?', 'card': {'id': 'w1'}}},
            {'id': 'ac1', 'date': '2026-10-15T09:00:00.000Z', 'memberCreator': {'fullName': 'Ann Smith'},
             'data': {'text': 'First mockup is attached.', 'card': {'id': 'w1'}}},
        ],
    },
    'mb': {
        'id': 'mb', 'name': 'Marketing Plan', 'url': 'https://trello.com/b/mb', 'closed': False,
        'lists': [lst('ml1', 'Backlog', 1), lst('ml2', 'In Progress', 2), lst('ml3', 'Campaign Ideas', 3),
                  lst('ml4', 'Published', 4), lst('ml5', 'Cancelled', 5)],
        'labels': [], 'members': [], 'checklists': [], 'cards': [], 'attachments': [], 'actions': [],
    },
    'hb': {
        'id': 'hb', 'name': 'Home Renovation', 'url': 'https://trello.com/b/hb', 'closed': False,
        'lists': [], 'labels': [], 'members': [], 'checklists': [], 'cards': [], 'attachments': [],
        'actions': [],
    },
}


def fake_request(api, path, params=None, method='GET'):
    parts = path.strip('/').split('/')
    if path == '/members/me/boards':
        return [{k: b[k] for k in ('id', 'name', 'url', 'closed')} for b in BOARDS.values()]
    board = BOARDS[parts[1]]
    if len(parts) == 2:
        return copy.deepcopy(board)
    if parts[2] == 'lists':
        return copy.deepcopy(board['lists'])
    if parts[2] == 'cards':
        return copy.deepcopy(board['attachments'])
    if parts[2] == 'actions':
        return [] if (params or {}).get('before') else copy.deepcopy(board['actions'])
    raise ValueError(path)


api_class = env.registry['trello.api']
api_class._request = fake_request
api_class._download = lambda api, url: png('Hero mockup', (37, 99, 235)) if url == HERO_URL else None

ICP = env['ir.config_parameter'].sudo()
set_param = getattr(ICP, 'set_str', None) or ICP.set_param  # Odoo 20 renamed set_param
set_param('trello.api_key', 'demo0key0not0real0000000000000000')
set_param('trello.api_token', 'demo-token-not-real')
groups = 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'  # 18.0: groups_id
for name, login in (('Ann Smith', 'ann'), ('Omar Haddad', 'omar')):
    env['res.users'].create({'name': name, 'login': login,
                             groups: [(6, 0, [env.ref('project.group_project_user').id])]})

# An existing project the Marketing board will be linked to, with its own stages.
marketing = env['project.project'].create({'name': 'Marketing Plan', 'type_ids': []})  # its own stages only
for seq, stage in enumerate(['Backlog', 'In Progress', 'Published']):
    env['project.task.type'].create({'name': stage, 'sequence': seq, 'project_ids': [(4, marketing.id)]})

Board = env['trello.board']
Board.action_fetch_boards()
web = Board.search([('trello_id', '=', 'wb')])
web.action_confirm()
web.action_activate()
web.review_changes = False  # first import straight into tasks; the Inbox is shown further down
web._sync_board()

# A list added in Trello after activation: its cards wait until it is mapped.
BOARDS['wb']['lists'].append(lst('wl5', 'Ideas', 5))
BOARDS['wb']['cards'].append(card('w8', 'Dark mode', 'wl5', ['lf'], [], None))
web._sync_board()

# Renamed in Odoo: the Trello tab shows the card's own name.
blog = env['project.task'].search([('trello_card_id', '=', 'w4')])
blog.name = 'Blog layout (client feedback)'

# Review Before Applying on (the default), then three things change in Trello: a new card,
# a renamed card with a new due date, and an archived card. The sync lists them in the Inbox.
web.review_changes = True
cards = {c['id']: c for c in BOARDS['wb']['cards']}
BOARDS['wb']['cards'].append(card('w9', 'Newsletter signup', 'wl1', ['lf'], ['m1'], '2026-11-25T16:00:00.000Z',
                                  desc='Signup box in the footer, double opt-in.'))
cards['w2'].update(name='Contact form validation and spam protection', due='2026-11-18T16:00:00.000Z')
cards['w5']['closed'] = True
web._sync_board()

mkt = Board.search([('trello_id', '=', 'mb')])
mkt.action_confirm()  # suggested: link to the existing "Marketing Plan" project

# The demo server must not call the real Trello with the fake key.
env.ref('trello.ir_cron_trello_sync').active = False
env.cr.commit()
print('demo data ready:', Board.search([]).mapped(lambda b: (b.name, b.state)),
      'inbox:', env['trello.card.change'].search([]).mapped('kind'))
