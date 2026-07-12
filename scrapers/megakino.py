# -*- coding: utf-8 -*-
import re
import time
import requests
from urllib.parse import quote_plus, urlparse

SITE_ID       = 'megakino'
SITE_NAME     = 'Megakino'
SITE_DOMAIN   = 'megakino.live'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'

_BASE_URL = None

_NAV_GENRE      = '__genre__'
_NAV_COLLECTION = '__collection__'


def _base():
    global _BASE_URL
    if not _BASE_URL:
        try:
            domain = requests.get(
                'https://raw.githubusercontent.com/mr-evil1/megakino/main/megakino-url.json',
                timeout=5
            ).json().get('url', SITE_DOMAIN)
            _BASE_URL = 'https://' + domain
        except Exception:
            _BASE_URL = 'https://' + SITE_DOMAIN
    return _BASE_URL


def _get(url, referer=None):
    headers = {
        'User-Agent':      _UA,
        'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
        'Referer':         referer or _base() + '/',
    }
    try:
        sess = requests.Session()
        r    = sess.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        html = r.text
        if html and ('yg=token' in html or '?y=token' in html):
            tok_h = dict(headers)
            tok_h['X-Requested-With'] = 'XMLHttpRequest'
            tok_h['Referer'] = url
            sess.get(_base() + '/index.php?yg=token', headers=tok_h, timeout=10)
            time.sleep(0.5)
            html = sess.get(url, headers=headers, timeout=10).text
        return html if html and len(html) > 500 else ''
    except Exception:
        return ''


def _cleantitle(s):
    s = (s or '').lower()
    return re.sub(r'[^a-z0-9]', '', s)


def _extract_hosters_from_page(page_url, season=0, episode=0):
    html    = _get(page_url, _base())
    quality = '1080p' if '1080' in html else '720p' if '720' in html else 'HD'
    result  = []
    if season and episode:
        m     = re.search(r'id="ep%s"[^>]*>(.*?)</select>' % episode, html, re.S)
        links = re.findall(r'value="([^"]+)"', m.group(1)) if m else []
    else:
        links = re.findall(r'<iframe[^>]*src="([^"]+)"', html)
    for link in links:
        if 'youtube' in link:
            continue
        if link.startswith('//'):
            link = 'https:' + link
        try:
            host = re.sub(r'^www\.', '', urlparse(link).netloc).split('.')[0].capitalize()
        except Exception:
            host = 'Stream'
        result.append(('%s | %s' % (host, quality), link, False))
    return result


def _find_page_url(title, year, season=0):
    clean = _cleantitle(title)
    html  = _get(_base() + '/index.php?do=search&subaction=search&story=%s' % quote_plus(title))
    for s_url, s_name in re.findall(
        r'<a[^>]*class="poster grid-item[^>]*href="([^"]+)"[^>]*>.*?alt="([^"]+)"', html, re.S
    ):
        if clean in _cleantitle(s_name) or _cleantitle(s_name) in clean:
            return s_url if s_url.startswith('http') else _base() + s_url
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        return _extract_hosters_from_page(url, season, episode)
    page_url = _find_page_url(title, year, season)
    if not page_url:
        return []
    return _extract_hosters_from_page(page_url, season, episode)


def _abs_url(u):
    if not u:
        return ''
    if u.startswith('//'):
        return 'https:' + u
    if u.startswith('/'):
        return _base() + u
    return u


def _parse_entries(html):
    items   = []
    pattern = r'<a[^>]*class="poster grid-item[^>]*href="([^"]+)"[^>]*>.*?<img[^>]*data-src="([^"]+)"[^>]*alt="([^"]+)"'
    for s_url, s_thumb, s_name in re.findall(pattern, html, re.S):
        s_url   = _abs_url(s_url)
        s_thumb = _abs_url(s_thumb)
        is_tv   = (
            any(x in s_url for x in ('/serials/', '/multfilm/')) or
            bool(re.search(r'staffel|season', s_name, re.I))
        )
        items.append({
            'title':       s_name.strip(),
            'url':         s_url,
            'poster':      s_thumb,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        })
    return items


def _browse_entries(url):
    html  = _get(url)
    items = _parse_entries(html)
    m = re.search(
        r'<div[^>]*class="[^"]*pagination__btn-loader[^"]*"[^>]*>.*?<a href="([^"]+)"',
        html, re.S
    )
    if m:
        next_url = _abs_url(m.group(1))
        items.append({
            'title':       '[B]>>> Nächste Seite[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_genre(base_url):
    html  = _get(base_url)
    items = []
    m = re.search(
        r'<div[^>]*class="side-block__title"[^>]*>Genres</div>(.*?)</ul>\s*</div>',
        html, re.S
    )
    if m:
        for g_url, g_name in re.findall(r'href="([^"]+)">([^<]+)</a>', m.group(1)):
            items.append({
                'title':       g_name.strip(),
                'url':         _abs_url(g_url),
                'next_func':   'load',
                'is_playable': False,
            })
    return items


def _browse_collection(base_url):
    html  = _get(base_url)
    items = []
    m = re.search(
        r'<div[^>]*class="side-block__title"[^>]*>Sammlung</div>.*?'
        r'<div[^>]*class="[^"]*collection-scroll[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.S
    )
    if m:
        for c_url, c_name in re.findall(
            r'href="([^"]+)"[^>]*>.*?<div[^>]*class="custom-collection-title"[^>]*>([^<]+)</div>',
            m.group(1), re.S
        ):
            items.append({
                'title':       c_name.strip(),
                'url':         _abs_url(c_url),
                'next_func':   'load',
                'is_playable': False,
            })
    return items


def load(url='', params=None):
    if url == _NAV_GENRE:
        return _browse_genre(_base() + '/')
    if url == _NAV_COLLECTION:
        return _browse_collection(_base() + '/')
    if url:
        return _browse_entries(url)
    b = _base()
    return [
        {'title': 'Neu',             'url': b + '/',             'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',            'url': b + '/kinofilme/',   'next_func': 'load', 'is_playable': False},
        {'title': 'Filme',           'url': b + '/films/',       'next_func': 'load', 'is_playable': False},
        {'title': 'Serien',          'url': b + '/serials/',     'next_func': 'load', 'is_playable': False},
        {'title': 'Anime',           'url': b + '/multfilm/',    'next_func': 'load', 'is_playable': False},
        {'title': 'Dokumentationen', 'url': b + '/documentary/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Genre',           'url': _NAV_GENRE,          'next_func': 'load', 'is_playable': False},
        {'title': 'Sammlung',        'url': _NAV_COLLECTION,     'next_func': 'load', 'is_playable': False},
    ]


def search(query='', params=None):
    url = _base() + '/index.php?do=search&subaction=search&story=%s' % quote_plus(query)
    return _browse_entries(url)
