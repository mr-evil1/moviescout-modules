# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote_plus
from resources.lib import multiquest, log

SITE_ID       = 'animetoast'
SITE_NAME     = 'AnimeToast'
SITE_DOMAIN   = 'animetoast.cc'
TYPE          = 'anime'
GLOBAL_SEARCH = True

_UA  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_SEP = '\x00'

try:
    from html import unescape as _unescape
except ImportError:
    def _unescape(x): return x

_BASE_RE = re.escape(SITE_DOMAIN.replace('www.', ''))

_RE_ENTRY     = re.compile(r'<a\s+href="(https?://[^/"]*%s/[a-z0-9][a-z0-9-]+/)"\s+title="([^"]+)">\s*<img[^>]+src="([^"]+)"' % _BASE_RE)
_RE_AZ        = re.compile(r'<li>\s*<a\s+href="(https?://[^/"]*%s/[a-z0-9][a-z0-9-]+/)">\s*([^<]+?)\s*</a>' % _BASE_RE)
_RE_NEXT      = re.compile(r'<a[^>]+class="[^"]*nextpostslink[^"]*"[^>]*href="([^"]+)"')
_RE_TAB       = re.compile(r'<a\s+data-toggle="tab"\s+href="#multi_link_tab(\d+)">\s*([^<]+?)\s*</a>')
_RE_BTN       = re.compile(r'<a\s+class="multilink-btn[^"]*"\s*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_RE_LINKNUM   = re.compile(r'[?&]link=(\d+)')
_RE_EMBED     = re.compile(r'id="player-embed"[^>]*>\s*(?:<a\s+href|<iframe[^>]*?\ssrc)="([^"]+)"')
_RE_TABSPLIT  = re.compile(r'id="multi_link_tab(\d+)"')
_RE_AJAX_P    = re.compile(r'class="simple-iframe-player"\s+data-title="([^"]+)"')
_RE_NONCE     = re.compile(r'iframe_loader\s*=\s*\{[^}]*?"nonce":"([^"]+)"')
_RE_SERVER_SEL= re.compile(r'<select[^>]*class="server-select"[^>]*>(.*?)</select>', re.DOTALL)
_RE_OPTION    = re.compile(r'<option\s+value="(\d+)"[^>]*>\s*([^<]*?)\s*</option>')
_RE_SEASON    = re.compile(r'%s/season-(winter|fruehling|sommer|herbst)-(\d{4})/' % _BASE_RE)
_RE_OG_IMG    = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_RE_OG_IMG2   = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)

_AZ_SKIP      = ('a-z-index', 'wochenplan', 'season-', 'latest-upload', 'privacy',
                 'agb', 'index-', 'category', 'genre', 'datenschutz', 'impressum')
_SEASON_SLUGS = (('winter', 'Winter'), ('fruehling', 'Frühling'),
                 ('sommer', 'Sommer'), ('herbst', 'Herbst'))


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA, 'Accept-Language': 'de-DE,de;q=0.9'}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _post_json(url, data, referer=None):
    headers = {'User-Agent': _UA, 'Content-Type': 'application/x-www-form-urlencoded'}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.post(url, data=data, headers=headers, timeout=15)
        r.raise_for_status()
        return json.loads(r.text)
    except Exception:
        log.error()
        return {}


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = _unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def _normhoster(s):
    s = (s or '').lower().strip()
    s = re.sub(r'\.(sx|com|net|to|sb|io|cc|me|stream|club|pro|live|fun|si|ws)$', '', s)
    return re.sub(r'[^a-z0-9]', '', s)


def _slug(url):
    m = re.search(r'https?://[^/]+/([^/?#]+)', url or '')
    return m.group(1) if m else ''


def _split_tabs(html):
    parts = _RE_TABSPLIT.split(html)
    panes = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            panes[int(parts[i])] = parts[i + 1]
        except ValueError:
            continue
    return panes


def _buttons(chunk):
    out = []
    for href, inner in _RE_BTN.findall(chunk):
        m = _RE_LINKNUM.search(href)
        if not m:
            continue
        out.append((href, int(m.group(1)), _clean(inner)))
    return out


def _cover(html):
    m = _RE_OG_IMG.search(html or '') or _RE_OG_IMG2.search(html or '')
    return m.group(1) if m else ''


def _embed_url(html):
    m = _RE_EMBED.search(html)
    return m.group(1) if m else ''


def _ep_num(label):
    m = re.search(r'(\d+)', label or '')
    return int(m.group(1)) if m else None


def _season_range(label):
    m = re.search(r'S\d+:\D*(\d+)\D+(\d+)', label or '')
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _hoster_name(url):
    host = re.sub(r'^https?://', '', url).split('/', 1)[0]
    return (host.split('.')[0] or 'Hoster').title()


def _enc(base, **kw):
    return base + _SEP + json.dumps(kw, ensure_ascii=False) if kw else base


def _dec(url):
    if _SEP not in url:
        return url, {}
    idx = url.index(_SEP)
    try:
        return url[:idx], json.loads(url[idx + 1:])
    except Exception:
        return url[:idx], {}


def _ep_items(btns, cover):
    return [
        {'title': label or ('Folge %d' % (pos + 1)), 'url': href,
         'poster': cover, 'mediatype': 'episode', 'next_func': 'get_hosters', 'is_playable': True}
        for pos, (href, _, label) in enumerate(btns)
    ]


def _ajax_data(nonce, title, server, entry_url, episode=None):
    data = {'action': 'get_episode_data', 'title': title, 'server': server, 'nonce': nonce}
    if episode is not None:
        data['episode'] = str(episode)
    return _post_json(_base() + '/wp-admin/admin-ajax.php', data, referer=entry_url)


def _season_map():
    html = _get(_base())
    out = {}
    for slug, year in _RE_SEASON.findall(html):
        out.setdefault(int(year), set()).add(slug)
    return out


def _browse_series(url, html=None):
    if html is None:
        html = _get(url)
    panes    = _split_tabs(html)
    cover    = _cover(html)
    tab_names = {int(i): _clean(n) for i, n in _RE_TAB.findall(html)}

    season_btns = []
    for idx in sorted(panes):
        block = [b for b in _buttons(panes[idx]) if re.match(r'S\d', b[2])]
        if len(block) >= 2:
            season_btns = block
            break

    if season_btns:
        return [
            {'title': label,
             'url': _enc(url, mode='season', pos=pos, label=label, cover=cover),
             'poster': cover, 'mediatype': 'season', 'next_func': 'load', 'is_playable': False}
            for pos, (_, _, label) in enumerate(season_btns)
        ]

    m_ajax = _RE_AJAX_P.search(html)
    if m_ajax:
        title = m_ajax.group(1)
        sel   = _RE_SERVER_SEL.search(html)
        opts  = _RE_OPTION.findall(sel.group(1)) if sel else []
        return [
            {'title': 'Server %s' % (lbl or val),
             'url': _enc(url, mode='ajax_srv', ajax_title=title, server=val, cover=cover),
             'poster': cover, 'mediatype': 'season', 'next_func': 'load', 'is_playable': False}
            for val, lbl in opts
        ]

    return [
        {'title': tab_names.get(idx, 'Hoster %d' % idx),
         'url': _enc(url, mode='lain', tab=idx,
                     hoster=tab_names.get(idx, 'Hoster %d' % idx), ep_range='', cover=cover),
         'poster': cover, 'mediatype': 'season', 'next_func': 'load', 'is_playable': False}
        for idx in sorted(panes) if _buttons(panes[idx])
    ]


def _browse_season_hosters(series_url, pos, label, cover):
    html      = _get(series_url)
    if not cover:
        cover = _cover(html)
    panes     = _split_tabs(html)
    tab_names = {int(i): _clean(n) for i, n in _RE_TAB.findall(html)}
    lo, hi    = _season_range(label)
    items     = []

    for idx in sorted(panes):
        btns = _buttons(panes[idx])
        if not btns:
            continue
        name       = tab_names.get(idx, 'Hoster %d' % idx)
        block_btns = [b for b in btns if re.match(r'S\d', b[2])]
        if block_btns:
            try:
                href = block_btns[int(pos)][0]
            except (IndexError, ValueError):
                continue
            items.append({
                'title': '%s - %s' % (label, name) if label else name,
                'url': _enc(href, mode='block', hoster=name, cover=cover),
                'poster': cover, 'mediatype': 'season', 'next_func': 'load', 'is_playable': False,
            })
        else:
            ep_nums  = [n for n in (_ep_num(b[2]) for b in btns) if n is not None]
            ep_range = ''
            if lo is not None and ep_nums:
                in_r = [n for n in ep_nums if lo <= n <= hi]
                if not in_r:
                    continue
                ep_range = '%d-%d' % (lo, hi)
                lbl = '%s (Ep. %d-%d)' % (name, min(in_r), max(in_r))
            else:
                lbl = '%s (Ep. %d-%d)' % (name, min(ep_nums), max(ep_nums)) if ep_nums else name
            items.append({
                'title': lbl,
                'url': _enc(series_url, mode='lain', tab=idx, hoster=name,
                            ep_range=ep_range, cover=cover),
                'poster': cover, 'mediatype': 'season', 'next_func': 'load', 'is_playable': False,
            })
    return items


def _browse_block(block_url, hoster, cover):
    html       = _get(block_url)
    if not cover:
        cover  = _cover(html)
    embed      = _embed_url(html)
    base_d     = SITE_DOMAIN.replace('www.', '')

    if embed and base_d in embed and _slug(embed) != _slug(block_url):
        arc_html  = _get(embed)
        arc_panes = _split_tabs(arc_html)
        arc_tabs  = {int(i): _clean(n) for i, n in _RE_TAB.findall(arc_html)}
        tab_idx   = next((i for i, n in arc_tabs.items() if _normhoster(n) == _normhoster(hoster)), None)
        ep_btns   = _buttons(arc_panes[tab_idx]) if tab_idx in (arc_panes or {}) else _buttons(arc_html)
        return _ep_items(ep_btns, cover)

    if embed and base_d not in embed:
        return [{'title': 'Stream', 'url': block_url, 'poster': cover,
                 'mediatype': 'episode', 'next_func': 'get_hosters', 'is_playable': True}]

    cur_slug = _slug(block_url)
    ep_btns  = [b for b in _buttons(html)
                if (_slug(b[0]) and _slug(b[0]) != cur_slug) or re.match(r'(?i)ep\.?\s*\d', b[2])]
    return _ep_items(ep_btns, cover)


def _browse_lain(series_url, tab_idx, hoster, ep_range, cover):
    html = _get(series_url)
    if not cover:
        cover = _cover(html)
    panes  = _split_tabs(html)
    base_d = SITE_DOMAIN.replace('www.', '')
    try:
        btns = _buttons(panes[int(tab_idx)])
    except (KeyError, ValueError):
        btns = []

    if len(btns) == 1 and re.search(r'\d+\s*-\s*\d+', btns[0][2]):
        arc_url = _embed_url(_get(btns[0][0]))
        if arc_url and base_d in arc_url and _slug(arc_url) != _slug(series_url):
            arc_html  = _get(arc_url)
            arc_panes = _split_tabs(arc_html)
            arc_tabs  = {int(i): _clean(n) for i, n in _RE_TAB.findall(arc_html)}
            t_idx     = next((i for i, n in arc_tabs.items() if _normhoster(n) == _normhoster(hoster)), None)
            arc_btns  = _buttons(arc_panes[t_idx]) if t_idx in (arc_panes or {}) else []
            if arc_btns:
                btns = arc_btns

    if ep_range:
        try:
            rlo, rhi = (int(x) for x in ep_range.split('-'))
            btns = [b for b in btns if _ep_num(b[2]) is not None and rlo <= _ep_num(b[2]) <= rhi]
        except (ValueError, TypeError):
            pass

    return _ep_items(btns, cover)


def _browse_ajax_episodes(entry_url, ajax_title, server, cover):
    html = _get(entry_url)
    if not cover:
        cover = _cover(html)
    m = _RE_NONCE.search(html)
    if not m:
        return []
    data     = _ajax_data(m.group(1), ajax_title, server, entry_url)
    episodes = data.get('data', {}).get('episodes', []) if data.get('success') else []
    return [
        {'title': ep.get('title') or ('Folge %s' % ep.get('number', '')),
         'url': _enc(entry_url, mode='ajax_ep', ajax_title=ajax_title,
                     server=server, episode=str(ep.get('number', ''))),
         'poster': cover, 'mediatype': 'episode', 'next_func': 'get_hosters', 'is_playable': True}
        for ep in episodes
    ]


def _browse_grid(url):
    html  = _get(url)
    items = []
    seen  = set()
    for s_url, title, thumb in _RE_ENTRY.findall(html):
        if s_url in seen:
            continue
        seen.add(s_url)
        items.append({'title': _clean(title), 'url': s_url, 'poster': thumb,
                      'mediatype': 'tvshow', 'next_func': 'load', 'is_playable': False})
    m = _RE_NEXT.search(html)
    if m:
        items.append({'title': '[B]>>> Weiter[/B]', 'url': m.group(1),
                      'next_func': 'load', 'is_playable': False})
    return items


def _browse_az(url):
    html  = _get(url)
    items = []
    seen  = set()
    for s_url, title in _RE_AZ.findall(html):
        if _slug(s_url) and any(b in _slug(s_url) for b in _AZ_SKIP):
            continue
        if s_url in seen:
            continue
        seen.add(s_url)
        items.append({'title': _clean(title), 'url': s_url,
                      'mediatype': 'tvshow', 'next_func': 'load', 'is_playable': False})
    return items


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Neues',         'url': '__news__',    'next_func': 'load', 'is_playable': False},
            {'title': 'Seasons',       'url': '__seasons__', 'next_func': 'load', 'is_playable': False},
            {'title': 'Index Ger Dub', 'url': _base() + '/a-z-index-dub/', 'next_func': 'load', 'is_playable': False},
            {'title': 'Index Ger Sub', 'url': _base() + '/a-z-index-sub/', 'next_func': 'load', 'is_playable': False},
        ]

    if url == '__news__':
        return [
            {'title': 'Kürzlich hinzugefügt', 'url': _base() + '/latest-uploads/', 'next_func': 'load', 'is_playable': False},
            {'title': 'Update/Upgrade',        'url': _base() + '/',                'next_func': 'load', 'is_playable': False},
        ]

    if url == '__seasons__':
        s_map = _season_map()
        return [
            {'title': str(y), 'url': '__year_%d__' % y, 'next_func': 'load', 'is_playable': False}
            for y in sorted(s_map, reverse=True)
        ]

    if url.startswith('__year_') and url.endswith('__'):
        try:
            year = int(url[7:-2])
        except ValueError:
            return []
        have = _season_map().get(year, set())
        return [
            {'title': '%s %d' % (lbl, year),
             'url': '%s/season-%s-%d/' % (_base(), slug, year),
             'mediatype': 'season', 'next_func': 'load', 'is_playable': False}
            for slug, lbl in _SEASON_SLUGS if slug in have
        ]

    base_url, enc = _dec(url)
    mode = enc.get('mode', '')

    if mode == 'season':
        return _browse_season_hosters(base_url, enc.get('pos', 0),
                                      enc.get('label', ''), enc.get('cover', ''))
    if mode == 'block':
        return _browse_block(base_url, enc.get('hoster', ''), enc.get('cover', ''))
    if mode == 'lain':
        return _browse_lain(base_url, enc.get('tab', 0), enc.get('hoster', ''),
                            enc.get('ep_range', ''), enc.get('cover', ''))
    if mode == 'ajax_srv':
        return _browse_ajax_episodes(base_url, enc.get('ajax_title', ''),
                                     enc.get('server', ''), enc.get('cover', ''))

    if 'a-z-index' in base_url:
        return _browse_az(base_url)

    if SITE_DOMAIN.replace('www.', '') in base_url:
        if any(x in base_url for x in ('latest-upload', 'season-', '/?', '/page/')):
            return _browse_grid(base_url)
        if base_url.rstrip('/').count('/') <= 3:
            html = _get(base_url)
            if _RE_AJAX_P.search(html) or _RE_TAB.search(html):
                return _browse_series(base_url, html)
            items = []
            seen  = set()
            for s_url, title, thumb in _RE_ENTRY.findall(html):
                if s_url in seen:
                    continue
                seen.add(s_url)
                items.append({'title': _clean(title), 'url': s_url, 'poster': thumb,
                              'mediatype': 'tvshow', 'next_func': 'load', 'is_playable': False})
            m = _RE_NEXT.search(html)
            if m:
                items.append({'title': '[B]>>> Weiter[/B]', 'url': m.group(1),
                              'next_func': 'load', 'is_playable': False})
            return items

    return _browse_grid(base_url)


def get_hosters(url='', params=None):
    base_url, enc = _dec(url)
    mode = enc.get('mode', '')

    if mode == 'ajax_ep':
        html = _get(base_url)
        m    = _RE_NONCE.search(html)
        if not m:
            return []
        data      = _ajax_data(m.group(1), enc.get('ajax_title', ''),
                               enc.get('server', ''), base_url,
                               episode=enc.get('episode'))
        hoster_url = data.get('data', {}).get('url', '') if data.get('success') else ''
        if hoster_url:
            name = _hoster_name(hoster_url)
            return [(name, hoster_url, False, 'HD', '')]
        return []

    base_d     = SITE_DOMAIN.replace('www.', '')
    html       = _get(url)
    hoster_url = _embed_url(html)
    if hoster_url and base_d in hoster_url:
        hoster_url = _embed_url(_get(hoster_url))
    if hoster_url and base_d not in hoster_url:
        name = _hoster_name(hoster_url)
        return [(name, hoster_url, False, 'HD', '')]
    return []


def search(query='', params=None):
    html  = _get(_base() + '/?s=' + quote_plus(query))
    items = []
    seen  = set()
    for s_url, title, thumb in _RE_ENTRY.findall(html):
        if s_url in seen:
            continue
        seen.add(s_url)
        items.append({'title': _clean(title), 'url': s_url, 'poster': thumb,
                      'mediatype': 'tvshow', 'next_func': 'load', 'is_playable': False})
    return items


def get_details(url='', params=None):
    if not url or url.startswith('__') or _SEP in url or 'link=' in url:
        return {}
    try:
        html = _get(url)
        if not html:
            return {}
        result = {}
        m = _RE_OG_IMG.search(html) or _RE_OG_IMG2.search(html)
        if m:
            result['poster'] = m.group(1)
        m_desc = re.search(r'class="entry-content"[^>]*>(.*?)</div>', html, re.S)
        if m_desc:
            result['plot'] = _clean(m_desc.group(1))[:600]
        return result
    except Exception:
        log.error()
        return {}
