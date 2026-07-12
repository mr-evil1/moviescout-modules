# -*- coding: utf-8 -*-
import re
import requests

SITE_ID       = 'fhdfilme'
SITE_NAME     = 'FHD Filme'
SITE_DOMAIN   = 'hdfilme.win'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA}
    if referer:
        headers['Referer'] = referer
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        return ''


def _cleantitle(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def _quality_from_text(text):
    t = text.upper()
    if '2160' in t or '4K' in t:
        return '4K'
    if '1080' in t:
        return '1080p'
    if '720' in t:
        return '720p'
    return 'HD'


def _try_resolve(url):
    return url, False


def _clean_plot(raw):
    text = re.sub(r'<[^>]+>', '', raw).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def _extract_hosters_from_page(page_url):
    html   = _get(page_url, _base())
    result = []
    for link in re.findall(r'data-link="([^"]+)', html):
        if not link.startswith('http'):
            link = 'https:' + link
        result.append(('Hoster', link, 'HD'))
    plot = ''
    p = re.search(r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I)
    if p:
        plot = _clean_plot(p.group(1))
    return result, plot


def _find_page_url(title, year, season=0):
    search_url = _base() + '/?story=%s&do=search&subaction=search' % requests.utils.quote(title)
    html = _get(search_url)
    for s_url, s_title, s_year in re.findall(
        r'class="thumb".*?href="([^"]+)".*?title="([^"]+)".*?_year">([^<]+)', html, re.S
    ):
        if _cleantitle(s_title) not in _cleantitle(title) and _cleantitle(title) not in _cleantitle(s_title):
            continue
        if season == 0 and year and s_year.strip() != str(year):
            continue
        return s_url
    return ''


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base())
    result = {}
    p = re.search(r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I)
    if p:
        result['plot'] = _clean_plot(p.group(1))
    y = re.search(r'_year">(\d{4})', html)
    if y:
        result['year'] = y.group(1)
    pm = re.search(r'<img[^>]*class="[^"]*poster[^"]*"[^>]*src="([^"]+)"', html, re.I)
    if pm:
        result['poster'] = pm.group(1) if pm.group(1).startswith('http') else _base() + pm.group(1)
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        raw, _ = _extract_hosters_from_page(url)
    elif season == 0 and imdb:
        html = _get('https://meinecloud.click/movie/%s' % imdb)
        raw  = []
        for link in re.findall(r'data-link="([^"]+)', html):
            if not link.startswith('http'):
                link = 'https:' + link
            raw.append(('Hoster', link, 'HD'))
    else:
        page_url = _find_page_url(title, year, season)
        if not page_url:
            return []
        html   = _get(page_url)
        ep_key = '%sx%s' % (season, episode)
        m      = re.search(r'data-num="%s"(.*?)(?:data-num="|$)' % re.escape(ep_key), html, re.S)
        raw    = []
        if m:
            for link in re.findall(r'data-link="([^"]+)', m.group(0)):
                if not link.startswith('http'):
                    link = 'https:' + link
                raw.append(('Hoster', link, 'HD'))
    result = []
    for name, hurl, quality in raw:
        resolved_url, is_resolved = _try_resolve(hurl)
        result.append((name, resolved_url, is_resolved))
    return result


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    return [
        {'title': 'Neu',    'url': _base() + '/filme1/',    'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',   'url': _base() + '/kinofilme/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': _base() + '/serien/',    'next_func': 'load', 'is_playable': False},
    ]


def _browse_entries(url):
    html  = _get(url)
    items = []
    for s_url, s_name, thumb, dummy in re.findall(
        r'class="thumb"[^>]*>.*?href="([^"]+)"[^>]*title="([^"]+)".*?src="([^"]+)"(.*?)</li>',
        html, re.S
    ):
        if not s_url.startswith('http'):
            s_url = _base() + '/' + s_url.lstrip('/')
        if thumb.startswith('/'):
            thumb = _base() + thumb
        year_m = re.search(r'_year">([^<]+)', dummy)
        year   = year_m.group(1).strip() if year_m else ''
        is_tv  = bool(re.search(r'staffel|season|serie', s_name, re.I))
        items.append({
            'title':       s_name.strip(),
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        })
    next_m = re.search(r'href="([^"]+)">›</a>', html)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({'title': '[B]>>> Weiter[/B]', 'url': next_url, 'next_func': 'load', 'is_playable': False})
    return items


def search(query='', params=None):
    url = _base() + '/?story=%s&do=search&subaction=search' % requests.utils.quote(query)
    return _browse_entries(url)
