# -*- coding: utf-8 -*-
import re
import time
import requests

SITE_ID       = 'megakino'
SITE_NAME     = 'Megakino'
SITE_DOMAIN   = 'megakino.live'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'

_BASE_URL = None


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
        if html and 'yg=token' in html:
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
        m     = re.search(r'<select[^>]*id="ep%s"[^>]*>(.*?)</select>' % episode, html, re.S)
        links = re.findall(r'value="([^"]+)"', m.group(1)) if m else []
    else:
        links = re.findall(r'<iframe[^>]*src="([^"]+)"', html)
    for link in links:
        if 'youtube' in link:
            continue
        if link.startswith('//'):
            link = 'https:' + link
        result.append((quality, link, False))
    return result


def _find_page_url(title, year, season=0):
    clean = _cleantitle(title)
    html  = _get(_base() + '/index.php?do=search&subaction=search&story=%s' % requests.utils.quote(title))
    for s_url, s_name in re.findall(
        r'<a class="poster grid-item[^>]*href="([^"]+)"[^>]*>.*?alt="([^"]+)"', html, re.S
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


def _browse_entries(url):
    html  = _get(url)
    items = []
    for s_url, s_name in re.findall(
        r'<a class="poster grid-item[^>]*href="([^"]+)"[^>]*>.*?alt="([^"]+)"', html, re.S
    ):
        if not s_url.startswith('http'):
            s_url = _base() + s_url
        is_tv = bool(re.search(r'staffel|season|serie', s_name, re.I))
        items.append({
            'title':       s_name.strip(),
            'url':         s_url,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        })
    next_m = re.search(r'class="next"[^>]*href="([^"]+)"', html)
    if next_m:
        next_url = next_m.group(1)
        if not next_url.startswith('http'):
            next_url = _base() + next_url
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    return [
        {'title': 'Neu',    'url': _base() + '/neue-filme/',    'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',   'url': _base() + '/kinofilme/',     'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': _base() + '/serien-stream/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Anime',  'url': _base() + '/anime/',         'next_func': 'load', 'is_playable': False},
    ]


def search(query='', params=None):
    url = _base() + '/index.php?do=search&subaction=search&story=%s' % requests.utils.quote(query)
    return _browse_entries(url)
