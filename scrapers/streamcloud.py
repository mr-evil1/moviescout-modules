# -*- coding: utf-8 -*-
import re
from html import unescape
from urllib.parse import urljoin, quote
from resources.lib import multiquest, log

SITE_ID       = 'streamcloud'
SITE_NAME     = 'Streamcloud'
SITE_DOMAIN   = 'streamcloud.forum'
TYPE          = 'both'
GLOBAL_SEARCH = True


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=15, use_cf=True)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _get_json(url, referer=None):
    try:
        r = multiquest.get(url, headers={
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Referer': referer or _base(),
        }, timeout=15, use_cf=True)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return {}


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _clean_html(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()


def _quality(text):
    text = (text or '').lower()
    if '2160' in text or '4k' in text: return '4K'
    if '1440' in text: return '1440p'
    if '1080' in text: return '1080p'
    if '720' in text: return '720p'
    if '480' in text or 'dvd' in text: return 'SD'
    return 'HD'


def _host(url):
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or '').replace('www.', '')
    except Exception:
        return ''



_PLOT_PATTERNS = [
    r'<div[^>]*class="[^"]*full-text[^"]*"[^>]*>(.*?)</div>\s*</div>',
    r'<div[^>]*class="[^"]*full-text[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*news-text[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*short-story[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</div>',
    r'<div[^>]*itemprop="description"[^>]*>(.*?)</div>',
    r'<p[^>]*itemprop="description"[^>]*>(.*?)</p>',
]

_SEO_PHRASES = (
    'stream kostenlos', 'jetzt online', 'kostenlos online',
    'ohne anmeldung', 'in hd stream', 'legal streamen',
)


def _is_seo(text):
    t = text.lower()
    return any(p in t for p in _SEO_PHRASES)


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base())
    result = {}

    # Plot: try known DLE div patterns first
    for pat in _PLOT_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            plot = _clean_html(m.group(1))
            if len(plot) > 40 and not _is_seo(plot):
                result['plot'] = plot
                break

    # Plot fallback: og:description meta
    if 'plot' not in result:
        m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:description"', html, re.I)
        if m:
            plot = unescape(m.group(1)).strip()
            if len(plot) > 40 and not _is_seo(plot):
                result['plot'] = plot

    # Poster: dedicated poster img, then og:image
    pm = re.search(r'<img[^>]*class="[^"]*poster[^"]*"[^>]*src="([^"]+)"', html, re.I)
    if not pm:
        pm = re.search(r'<div[^>]*class="[^"]*poster[^"]*"[^>]*>[\s\S]*?<img[^>]*src="([^"]+)"', html, re.I)
    if not pm:
        pm = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        if not pm:
            pm = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html, re.I)
    if pm:
        poster = unescape(pm.group(1))
        result['poster'] = poster if poster.startswith('http') else _base() + poster

    # Year
    ym = re.search(r'<div[^>]*class="f_year"[^>]*>[\s\S]*?(\d{4})', html, re.I)
    if ym:
        result['year'] = ym.group(1)

    return result


_GENRES_HARDCODED = [
    ('Action',        'action'),       ('Abenteuer',    'abenteuer'),
    ('Animation',     'animation'),    ('Biographie',   'biographie'),
    ('Dokumentation', 'dokumentation'),('Drama',        'drama'),
    ('Familie',       'familie'),      ('Fantasy',      'fantasy'),
    ('Historie',      'historie'),     ('Horror',       'horror'),
    ('Komödie',       'komodie'),      ('Krieg',        'krieg'),
    ('Krimi',         'krimi'),        ('Liebesfilm',   'liebesfilm'),
    ('Musik',         'musik'),        ('Mystery',      'mystery'),
    ('Reality-TV',    'reality-tv'),   ('Romantik',     'romantik'),
    ('Sci-Fi',        'sci-fi'),       ('Sport',        'sport'),
    ('Thriller',      'thriller'),     ('Western',      'western'),
    ('Demnächst',     'demnachst'),
]


def _browse_entries(url, no_details=False):
    html      = _get(url, _base())
    is_series = '/serien/' in url
    items     = []

    pattern = (
        r'<div class="item\b[^>]*>[\s\S]*?'
        r'<div class="thumb"[^>]*>[\s\S]*?'
        r'<a href="([^"]+)"><img src="([^"]+)"[\s\S]*?'
        r'<div class="f_title">[\s\S]*?<a[^>]*>([^<]+)</a>'
        r'[\s\S]*?<div class="f_year">[\s\S]*?(?:<span[^>]*>)?([^<\n]*)'
    )
    for href, thumb, title, year_raw in re.findall(pattern, html, re.I):
        year_m    = re.search(r'\d{4}', year_raw)
        year      = year_m.group() if year_m else ''
        title     = unescape(title.strip())
        item_url  = unescape(href) if unescape(href).startswith('http') else _base() + unescape(href)
        thumb_url = thumb if thumb.startswith('http') else _base() + thumb
        item = {
            'title':       title,
            'url':         item_url,
            'poster':      thumb_url,
            'year':        year,
            'mediatype':   'tvshow' if is_series else 'movie',
            'next_func':   'get_seasons' if is_series else 'get_hosters',
            'is_playable': not is_series,
        }
        if no_details:
            item['plot'] = ' '
        items.append(item)

    next_m = re.search(r'<a href="([^"]+)"[^>]*>\s*Next\s*>', html, re.I)
    if next_m:
        next_url = next_m.group(1)
        if not next_url.startswith('http'):
            next_url = _base() + next_url
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load_fast' if no_details else 'load',
            'is_playable': False,
        })

    return items


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    b = _base()
    return [
        {'title': '[B]── Schnell (ohne Beschreibung) ──[/B]', 'url': '', 'next_func': 'load_fast', 'is_playable': False},
        {'title': 'Beliebt',    'url': b + '/beliebte-filme/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Kinofilme',  'url': b + '/kinofilme/',      'next_func': 'load', 'is_playable': False},
        {'title': 'Serien',     'url': b + '/serien/',         'next_func': 'load', 'is_playable': False},
        {'title': 'Alle Filme', 'url': b + '/filme-stream/',   'next_func': 'load', 'is_playable': False},
        {'title': 'Genre',      'url': '',                     'next_func': 'load_genre', 'is_playable': False},
    ]


def load_fast(url='', params=None):
    if url:
        return _browse_entries(url, no_details=True)
    b = _base()
    return [
        {'title': 'Beliebt',    'url': b + '/beliebte-filme/', 'next_func': 'load_fast', 'is_playable': False},
        {'title': 'Kinofilme',  'url': b + '/kinofilme/',      'next_func': 'load_fast', 'is_playable': False},
        {'title': 'Serien',     'url': b + '/serien/',         'next_func': 'load_fast', 'is_playable': False},
        {'title': 'Alle Filme', 'url': b + '/filme-stream/',   'next_func': 'load_fast', 'is_playable': False},
        {'title': 'Genre',      'url': '',                     'next_func': 'load_genre', 'is_playable': False},
    ]


def load_genre(url='', params=None):
    b = _base()
    return [
        {
            'title':       name,
            'url':         b + '/' + slug + '/',
            'next_func':   'load',
            'is_playable': False,
        }
        for name, slug in _GENRES_HARDCODED
    ]

def _serial_player_from_imdb(imdb):
    try:
        data = _get_json(
            'https://meinecloud.click/serials.php?task=check&id_imdb=%s' % quote(imdb), _base()
        )
        if isinstance(data, dict) and data.get('exists') and data.get('player_url'):
            return data.get('player_url', '').replace('\\/', '/')
    except Exception:
        log.error()
    return ''


def _get_serial_player(detail_url):
    """Fetch detail page → extract imdb_id → return meinecloud serial player URL."""
    html = _get(detail_url, _base())
    for imdb_id in re.findall(r'meinecloud\.click/(?:ddl|serial)/((?:tt)?\d+)', html, re.I):
        if not imdb_id.startswith('tt'):
            imdb_id = 'tt' + imdb_id
        player = _serial_player_from_imdb(imdb_id)
        if player:
            return player
    return ''


def get_seasons(url='', params=None):
    player_url = _get_serial_player(url)
    if not player_url:
        return []
    html    = _get(player_url, _base())
    seasons = []
    for data_season, label in re.findall(
        r'<div[^>]*class="[^"]*_stab[^"]*"[^>]*data-season="(\d+)"[^>]*>(.*?)</div>',
        html, re.S | re.I
    ):
        num_m = re.search(r'\d+', label)
        if num_m:
            seasons.append(int(num_m.group()))
    seasons = sorted(set(seasons))
    return [
        {
            'title':       'Staffel %d' % s,
            'url':         url,
            'season':      s,
            'next_func':   'get_episodes',
            'is_playable': False,
        }
        for s in seasons
    ]


def get_episodes(url='', params=None):
    season = int((params or {}).get('season', 0))
    if not season:
        return []
    player_url = _get_serial_player(url)
    if not player_url:
        return []
    html    = _get(player_url, _base())
    s_pat   = r'\bS0*%d\s*E(\d+)\b' % season
    ep_nums = sorted(set(
        int(m.group(1))
        for label in re.findall(r'data-label="([^"]+)"', html, re.I)
        for m in [re.search(s_pat, label, re.I)]
        if m
    ))
    return [
        {
            'title':       'Episode %d' % e,
            'url':         url,
            'season':      season,
            'episode':     e,
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        for e in ep_nums
    ]


def _parse_search_results(html):
    pattern = (
        r'<div class="item\b[^>]*>[\s\S]*?'
        r'<div class="thumb" title="([^"]*)"[\s\S]*?'
        r'<a href="([^"]+)"[\s\S]*?'
        r'<div class="f_title">[\s\S]*?<a[^>]*>([\s\S]*?)</a>'
        r'[\s\S]*?<div class="f_year">[\s\S]*?(?:<span[^>]*>)?([^<\n]*)'
    )
    results = []
    for thumb_title, url, title, year_raw in re.findall(pattern, html or '', re.I):
        year_m = re.search(r'\d{4}', year_raw)
        results.append({
            'title': _clean_html(title or thumb_title),
            'url':   urljoin(_base(), unescape(url)),
            'year':  year_m.group() if year_m else '',
        })
    return results


def search(query='', params=None):
    html  = _get(_base() + '/index.php?do=search&subaction=search&story=%s' % quote(query), _base())
    items = []
    for item in _parse_search_results(html):
        items.append({
            'title':       item['title'],
            'url':         item['url'],
            'year':        item['year'],
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    return items



def _title_matches(title, clean_titles):
    current = _cleantitle(title)
    if current in clean_titles: return True
    return any(current and c and (current.startswith(c) or c.startswith(current)) for c in clean_titles)


def _find_detail_urls(title, year, expect_series, imdb_id=''):
    seen = set()
    results = []
    if imdb_id:
        query = imdb_id if imdb_id.startswith('tt') else 'tt' + imdb_id
        html = _get(_base() + '/index.php?do=search&subaction=search&story=%s' % quote(query), _base())
        for item in _parse_search_results(html):
            if item['url'] not in seen:
                seen.add(item['url'])
                results.append(item['url'])
        if results:
            return results
    clean_titles = set([_cleantitle(title)])
    html = _get(_base() + '/index.php?do=search&subaction=search&story=%s' % quote(title), _base())
    for item in _parse_search_results(html):
        if not _title_matches(item['title'], clean_titles): continue
        if year and item['year'] and str(year) != str(item['year']): continue
        if item['url'] not in seen:
            seen.add(item['url'])
            results.append(item['url'])
    return results


def _add_data_links(html, referer, seen):
    result = []
    for url in re.findall(r'data-link="([^"]+)"', html or '', re.I):
        url = unescape(url.strip())
        if not url or url in seen: continue
        if url.startswith('//'): url = 'https:' + url
        host = _host(url)
        if host in ['meinecloud.click', 'dl.tmdb.club'] and not re.search(r'\.(mp4|m3u8)(\?|$)', url, re.I):
            continue
        seen.add(url)
        result.append((host or SITE_NAME, url, re.search(r'\.(mp4|m3u8)(\?|$)', url, re.I) is not None, _quality(url), 'de'))
    return result


def _evil():
    try:
        from resources.lib import cloud
        return cloud
    except Exception:
        return None


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if params:
        season  = int(params.get('season',  season  or 0))
        episode = int(params.get('episode', episode or 0))
    result = []
    seen   = set()

    evil = _evil()

    if int(season or 0) == 0:
        if imdb and evil:
            try:
                for item in evil.get_movie(imdb):
                    name, hurl, direct = item[0], item[1], item[2]
                    if hurl not in seen:
                        seen.add(hurl)
                        result.append((name, hurl, direct, _quality(hurl), 'de'))
            except Exception:
                log.error()
        if not result:
            for detail_url in _find_detail_urls(title, year, False, imdb_id=imdb)[:3]:
                html = _get(detail_url, _base())
                for mc_url in re.findall(r'<iframe[^>]+src="([^"]*meinecloud\.click/movie/[^"]+)"', html, re.I):
                    player_html = _get(unescape(mc_url), _base())
                    result += _add_data_links(player_html, mc_url, seen)
    else:
        if imdb and evil:
            try:
                for item in evil.get_episode(imdb, int(season), int(episode)):
                    name, hurl, direct = item[0], item[1], item[2]
                    if hurl not in seen:
                        seen.add(hurl)
                        result.append((name, hurl, direct, _quality(hurl), 'de'))
            except Exception:
                log.error()
        if not result:
            player_urls = []
            detail_urls = [url] if url else _find_detail_urls(title, '', True, imdb_id=imdb)[:3]
            for detail_url in detail_urls:
                html = _get(detail_url, _base())
                for imdb_id in re.findall(r'meinecloud\.click/(?:ddl|serial)/((?:tt)?\d+)', html, re.I):
                    if not imdb_id.startswith('tt'): imdb_id = 'tt' + imdb_id
                    p = _serial_player_from_imdb(imdb_id)
                    if p and p not in player_urls: player_urls.append(p)
            if imdb:
                p = _serial_player_from_imdb(imdb)
                if p and p not in player_urls: player_urls.append(p)
            for player_url in player_urls:
                html = _get(player_url, _base())
                for tag in re.findall(r'<div class="_ep[^"]*"[^>]*>', html, re.I):
                    attrs = dict(re.findall(r'data-([a-z_-]+)="([^"]*)"', tag, re.I))
                    label = unescape(attrs.get('label', ''))
                    link  = attrs.get('link', '')
                    m = re.search(r'\bS0*(\d+)\s*E0*(\d+)\b', label, re.I)
                    if not m: continue
                    if int(m.group(1)) == int(season) and int(m.group(2)) == int(episode):
                        link = unescape(link.strip())
                        if link and link not in seen:
                            seen.add(link)
                            result.append((_host(link) or SITE_NAME, link, False, _quality(label), 'de'))
    return result
