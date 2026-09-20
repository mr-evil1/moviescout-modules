# -*- coding: utf-8 -*-
import re
from urllib.parse import quote, urlparse

from resources.lib import multiquest, log

SITE_ID       = 'kinox_to'
SITE_NAME     = 'KinoX.to'
SITE_DOMAIN   = 'kinox.you'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_GENRES_FILME = [
    ('Action',          '/action/'),
    ('Abenteuer',       '/abenteuer/'),
    ('Animation',       '/animation/'),
    ('Biographie',      '/biographie/'),
    ('Dokumentation',   '/dokumentation/'),
    ('Drama',           '/drama/'),
    ('Erotikfilme',     '/erotikfilme/'),
    ('Familie',         '/familie/'),
    ('Fantasy',         '/fantasy/'),
    ('Historienfilme',  '/historien/'),
    ('Horror',          '/horror/'),
    ('Komödie',         '/komodie/'),
    ('Krimi',           '/krimi/'),
    ('Krieg',           '/krieg/'),
    ('Musikfilme',      '/musikfilme/'),
    ('Mystery',         '/mystery/'),
    ('Romantik',        '/romantik/'),
    ('Science-Fiction', '/sci-fi/'),
    ('Sport',           '/sport/'),
    ('Thriller',        '/thriller/'),
    ('Western',         '/western/'),
]

_GENRES_SERIEN = _GENRES_FILME

_YEARS = [str(y) for y in range(2026, 2009, -1)]

_S_FILME        = '__ky_filme__'
_S_SERIEN       = '__ky_serien__'
_S_GENRE_FILME  = '__ky_gf__'
_S_GENRE_SERIEN = '__ky_gs__'
_S_YEAR_FILME   = '__ky_yf__'
_S_YEAR_SERIEN  = '__ky_ys__'
_S_BROWSE       = '__ky_browse__:'

_FILME_MENU = [
    ('Alle Filme',         '/kinofilme-online/'),
    ('Aktuelle Kinofilme', '/aktuelle-kinofilme-im-kino/'),
    ('Demnächst im Kino',  '/demnachst/'),
]
_SERIEN_MENU = [
    ('Alle Serien', '/serienstream-deutsch/'),
]


def _base():
    return 'https://' + SITE_DOMAIN


def _headers(referer=None):
    return {
        'User-Agent': _UA,
        'Referer':    referer or _base() + '/',
    }


def _get(path, referer=None):
    url = path if path.startswith('http') else _base() + path
    try:
        r = multiquest.get(url, headers=_headers(referer), timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _parse_entries(html):
    items = []
    for chunk in re.split(r'(?=<div class="short-entry")', html):
        if 'short-entry-title' not in chunk:
            continue

        url_m = re.search(r'<a href="(https://kinox\.you/[^"]+)"', chunk)
        if not url_m:
            continue
        full_url = url_m.group(1)

        title_m = re.search(
            r'class="short-entry-title"[^>]*>.*?<a[^>]*>([^<]+)</a>',
            chunk, re.DOTALL
        )
        title = title_m.group(1).strip() if title_m else ''

        poster_m = re.search(r'<img[^>]+src="(/uploads/[^"]+)"', chunk)
        poster = (_base() + poster_m.group(1)) if poster_m else ''

        is_series = bool(re.search(r'<div class="serie-num">', chunk)) or 'Staffel' in title

        year_m = re.search(r'\((\d{4})\)\s*$', title.strip())
        year = year_m.group(1) if year_m else ''
        clean_title = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip()

        plot_m = re.search(r'class="[^"]*short-entry-desc[^"]*"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        if not plot_m:
            plot_m = re.search(r'class="[^"]*entry-desc[^"]*"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        plot = re.sub(r'<[^>]+>', '', plot_m.group(1)).strip() if plot_m else ''

        item = {
            'title':       clean_title or title,
            'url':         full_url,
            'poster':      poster,
            'mediatype':   'tvshow' if is_series else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        if year:
            item['year'] = year
        if plot:
            item['plot'] = plot
        items.append(item)

    return items


def _extract_content(html):
    m = re.search(
        r"id=[\"']dle-content[\"'](.*?)<div[^>]+id=[\"']bottom_pagination[\"']",
        html, re.DOTALL
    )
    if m:
        return m.group(1)
    m = re.search(r'class="short-row"(.*?)<div[^>]+id=["\']bottom_pagination["\']', html, re.DOTALL)
    if m:
        return m.group(1)
    return html


def _parse_page(path, page=1):
    if path.startswith('http'):
        req_url = path
        if page > 1:
            base_path = re.sub(r'/page/\d+/?$', '', path).rstrip('/')
            req_url = base_path + '/page/' + str(page) + '/'
    else:
        clean = path.rstrip('/')
        if page > 1:
            req_url = clean + '/page/' + str(page) + '/'
        else:
            req_url = clean + '/'

    html = _get(req_url)
    if not html:
        return []

    block = _extract_content(html)
    items = _parse_entries(block)

    pages_m = re.search(
        r'id=["\']bottom_pagination["\'].*?<div class=["\']pages["\']>(.*?)</div>',
        html, re.DOTALL
    )
    if pages_m:
        max_page = 0
        for pg in re.findall(r'/page/(\d+)/', pages_m.group(1)):
            max_page = max(max_page, int(pg))
        if page < max_page:
            next_enc = _S_BROWSE + path + '|page=' + str(page + 1)
            items.append({
                'title':       '[B]>>> Weiter[/B]',
                'url':         next_enc,
                'next_func':   'load',
                'is_playable': False,
            })

    return items


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Suche',  'url': '',         'next_func': 'search', 'is_playable': False, 'is_search': True},
            {'title': 'Filme',  'url': _S_FILME,   'next_func': 'load',   'is_playable': False},
            {'title': 'Serien', 'url': _S_SERIEN,  'next_func': 'load',   'is_playable': False},
        ]

    if url == _S_FILME:
        items = [
            {'title': lbl, 'url': _S_BROWSE + path + '|page=1', 'next_func': 'load', 'is_playable': False}
            for lbl, path in _FILME_MENU
        ]
        items.append({'title': 'Genre', 'url': _S_GENRE_FILME, 'next_func': 'load', 'is_playable': False})
        items.append({'title': 'Jahr',  'url': _S_YEAR_FILME,  'next_func': 'load', 'is_playable': False})
        return items

    if url == _S_SERIEN:
        items = [
            {'title': lbl, 'url': _S_BROWSE + path + '|page=1', 'next_func': 'load', 'is_playable': False}
            for lbl, path in _SERIEN_MENU
        ]
        items.append({'title': 'Genre', 'url': _S_GENRE_SERIEN, 'next_func': 'load', 'is_playable': False})
        items.append({'title': 'Jahr',  'url': _S_YEAR_SERIEN,  'next_func': 'load', 'is_playable': False})
        return items

    if url == _S_GENRE_FILME:
        return [
            {'title': name, 'url': _S_BROWSE + path + '|page=1', 'next_func': 'load', 'is_playable': False}
            for name, path in _GENRES_FILME
        ]

    if url == _S_GENRE_SERIEN:
        return [
            {'title': name, 'url': _S_BROWSE + path + '|page=1', 'next_func': 'load', 'is_playable': False}
            for name, path in _GENRES_SERIEN
        ]

    if url == _S_YEAR_FILME:
        return [
            {'title': yr, 'url': _S_BROWSE + '/xfsearch/' + yr + '/|page=1', 'next_func': 'load', 'is_playable': False}
            for yr in _YEARS
        ]

    if url == _S_YEAR_SERIEN:
        return [
            {'title': yr, 'url': _S_BROWSE + '/xfsearch/' + yr + '/|page=1', 'next_func': 'load', 'is_playable': False}
            for yr in _YEARS
        ]

    if url.startswith(_S_BROWSE):
        encoded = url[len(_S_BROWSE):]
        page = 1
        path = encoded
        if '|page=' in encoded:
            path, pg = encoded.rsplit('|page=', 1)
            page = int(pg)
        return _parse_page(path, page)

    return []


def get_details(url='', params=None):
    if not url or url.startswith('__ky_'):
        return {}
    html = _get(url)
    if not html:
        return {}

    result = {}

    title_m = re.search(r'<title>([^<]+)</title>', html)
    if title_m:
        raw = title_m.group(1).split(' Stream')[0].strip()
        year_m = re.search(r'\((\d{4})\)', raw)
        if year_m:
            result['year'] = year_m.group(1)
        result['title'] = re.sub(r'\s*\(\d{4}\)\s*$', '', raw).strip()

    poster_m = re.search(r'background-image:\s*url\((/uploads/[^)]+)\)', html)
    if not poster_m:
        poster_m = re.search(r'<img[^>]+src="(/uploads/thumb/[^"]+)"', html)
    if poster_m:
        result['poster'] = _base() + poster_m.group(1)

    for plot_pat in [
        r'class="Descriptore"[^>]*>(.*?)</div>',
        r'class="info-text"[^>]*>(.*?)</div>',
        r'class="[^"]*full-story[^"]*"[^>]*>(.*?)</div>',
        r'class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]+itemprop="description"[^>]*>(.*?)</div>',
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
    ]:
        plot_m = re.search(plot_pat, html, re.DOTALL)
        if plot_m:
            raw_plot = re.sub(r'<[^>]+>', '', plot_m.group(1)).strip()
            if len(raw_plot) > 20:
                result['plot'] = raw_plot
                break

    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if not url:
        html = _get(
            '/index.php?do=search&subaction=search&story=' + quote(title),
            referer=_base() + '/'
        )
        if not html:
            return []
        url_m = re.search(r'href="(https://kinox\.you/\d+-[^"]+\.html)"', html)
        if not url_m:
            return []
        url = url_m.group(1)

    if season and episode:
        sep = '&' if '?' in url else '?'
        url = url + sep + 'season=%d&episode=%d' % (season, episode)

    html = _get(url, referer=_base() + '/')
    if not html:
        return []

    hl_m = re.search(r'id="HosterList"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if not hl_m:
        return []

    result = {}
    for li in re.finditer(
        r'<li[^>]+data-link="([^"]+)"[^>]*>.*?<div class="Named">([^<]+)</div>',
        hl_m.group(1), re.DOTALL
    ):
        link = li.group(1).strip()
        name = li.group(2).strip()

        if not link or link.startswith('/vod/') or link == '2':
            continue

        host = urlparse(link).hostname or ''
        if not host:
            continue

        if 'youtube' in host or 'youtu.be' in host:
            continue

        domain = '.'.join(host.split('.')[-2:])
        if domain not in result:
            result[domain] = (link, name)

    return [(dom, v[0], False, 'HD', 'de') for dom, v in result.items()]


def search(query='', url='', params=None):
    if not query:
        try:
            import xbmcgui
            kb = xbmcgui.Dialog()
            query = kb.input('[KinoX] Suche', type=xbmcgui.INPUT_ALPHANUM)
        except Exception:
            pass
    if not query:
        return []

    html = _get(
        '/index.php?do=search&subaction=search&story=' + quote(query),
        referer=_base() + '/'
    )
    if not html:
        return []

    block = _extract_content(html)
    return _parse_entries(block)
