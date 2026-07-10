# -*- coding: utf-8 -*-
import re
import requests

SITE_ID      = 'filmpalast'
SITE_NAME    = 'FilmPalast'
SITE_DOMAIN  = 'filmpalast.to'
TYPE         = 'both'
GLOBAL_SEARCH = True


_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'


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


def _extract_hosters_from_page(page_url):
    html = _get(page_url, _base())
    quality = 'HD'
    q = re.search(r'<span id="release_text"[^>]*>([^<&]+)', html, re.I)
    if q:
        quality = _quality_from_text(q.group(1))
    streams = re.findall(
        r'<p class="hostName">([^<]+)</p>.*?<li[^>]*class="streamPlayBtn[^"]*".*?<a[^>]*(?:href|data-player-url)="([^"]+)"',
        html, re.S | re.I
    )
    result = []
    for hoster, s_url in streams:
        if not s_url or s_url.startswith('javascript'):
            continue
        result.append((hoster.strip(), s_url, quality))
    return result


def _find_page_url(title, year, season=0):
    search_url = _base() + '/search/title/' + requests.utils.quote(title)
    html = _get(search_url, _base())
    content_m = re.search(r'id="content"[^>]*>(.+?)<div id="paging"', html, re.S | re.I)
    if not content_m:
        return ''
    content = content_m.group(1)
    matches = re.findall(r'href="//filmpalast\.to(/stream/[^"]+)"[^>]*title="([^"]+)"', content, re.S | re.I)
    clean_t = _cleantitle(title)
    for m_url, m_title in matches:
        if _cleantitle(m_title) not in clean_t and clean_t not in _cleantitle(m_title):
            continue
        page_url = _base() + m_url
        page_html = _get(page_url, _base())
        if season == 0 and year:
            y = re.search(r'>Ver&ouml;ffentlicht:\s*([^<]+)', page_html, re.I)
            if y and str(year) not in y.group(1):
                continue
        if season > 0:
            if 'staffel' not in m_title.lower() and 's0' not in m_title.lower():
                continue
            s_m = re.search(r'staffel\s*(\d+)', m_title, re.I)
            if s_m and int(s_m.group(1)) != season:
                continue
        return page_url
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        raw = _extract_hosters_from_page(url)
        return [(name, hurl, False) for name, hurl, _ in raw]

    page_url = _find_page_url(title, year, season)
    if not page_url:
        return []
    raw = _extract_hosters_from_page(page_url)
    return [(name, hurl, False) for name, hurl, _ in raw]


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    return [
        {'title': 'Neu',        'url': _base() + '/movies/new',   'next_func': 'load', 'is_playable': False},
        {'title': 'Top',        'url': _base() + '/movies/top',   'next_func': 'load', 'is_playable': False},
        {'title': 'Serien',     'url': _base() + '/serien/view',  'next_func': 'load', 'is_playable': False},
        {'title': 'Suche',      'url': '',                         'next_func': 'load', 'is_playable': False},
    ]


def _browse_entries(url):
    html = _get(url)
    pattern = r'<article[^>]*>\s*<a href="([^"]+)" title="([^"]+)">\s*<img src=["\']([^"\']+)["\'][^>]*>(.*?)</article>'
    matches = re.findall(pattern, html, re.S | re.I)
    if not matches:
        pattern = r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>[^<]*<img[^>]*src=["\']([^"\']*)["\'][^>]*>\s*</a>(\s*)</article>'
        matches = re.findall(pattern, html, re.S | re.I)
    items = []
    for s_url, s_name, thumb, dummy in matches:
        if s_url.startswith('//'):
            s_url = 'https:' + s_url
        if thumb.startswith('/'):
            thumb = _base() + thumb
        year_m = re.search(r'Jahr:\s*(\d+)', dummy)
        year = year_m.group(1) if year_m else ''
        is_tv = bool(re.search(r'S\d\dE\d\d', s_name, re.I))
        items.append({
            'title':       s_name,
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        })
    next_m = re.search(r'<a class="pageing[^"]*"[^>]*href="([^"]+)"[^>]*>[^<]*vor', html, re.I)
    if next_m:
        next_url = _base() + next_m.group(1) if next_m.group(1).startswith('/') else next_m.group(1)
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def search(query='', params=None):
    url = _base() + '/search/title/' + requests.utils.quote(query)
    return _browse_entries(url)
