# -*- coding: utf-8 -*-
#Thx zusatzmetall
import json
import re
import html as htmllib
import math
import urllib.parse
import urllib.request
import urllib.error
import os
import time
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import xbmcvfs
import xbmc
import xbmcgui
import xbmcaddon

SITE_ID       = 'wedotv'
SITE_NAME     = 'WedoTV'
SITE_DOMAIN   = 'wedotv.com'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True
STREAMLG      = 'LG0'
SCRAPER_TIMEOUT = 18

try:
    _ICON = xbmcaddon.Addon().getAddonInfo('icon')
except Exception:
    _ICON = ''

_UA = (
    'Mozilla/5.0 (Linux; Android 15; Mobile) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/140.0.0.0 Mobile Safari/537.36'
)

_LANG    = 'de'
_COUNTRY = 'at'
_LOC     = f'{_LANG}-{_COUNTRY}'

HEADERS = {
    'User-Agent': _UA,
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'de-AT,de-DE;q=0.9,de;q=0.8,en-US;q=0.7,en;q=0.6',
    'Referer': f'https://www.wedotv.com/{_LOC}/movies',
    'Cookie': f'language={_LANG}; country={_COUNTRY}'
}

_BASE         = 'https://www.wedotv.com'
_API_PLAYER   = _BASE + '/api/player.get_video.php'
_API_PLAYLIST = _BASE + '/api/getPlaylist.php'
_PAGE_LIMIT   = 24
_DETAIL_BUDGET = 20
_DETAIL_WORKERS = 8

def _profile_dir():
    try:
        return xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    except Exception:
        return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.moviescout/')

_CACHE_DIR = os.path.join(_profile_dir(), 'wedotv')

_SECTIONS = {
    'movies': '/movies',
    'series': '/series',
    'sport': '/sport'
}

_FALLBACK_GENRES = [
    ('Alle', 'all'),
    ('Abenteuer', 'adventure'),
    ('Action', 'action'),
    ('Animation', 'animation'),
    ('Dokumentarfilm', 'documentary'),
    ('Drama', 'drama'),
    ('Familie', 'family'),
    ('Fantasy', 'fantasy'),
    ('Geschichte', 'history'),
    ('Horror', 'horror'),
    ('Komödie', 'comedy'),
    ('Krimi', 'crime'),
    ('Musik', 'music'),
    ('Romantik', 'romance'),
    ('Sci-Fi', 'sci-fi'),
    ('Sport', 'sports'),
    ('Thriller', 'thriller'),
    ('Weihnachten', 'christmas')
]

_API_LISTS = {
    'movies': _BASE + '/api/getMovies.php',
    'series': _BASE + '/api/getSeries.php'
}
_LIST_LIMIT = 25

_SKIP_ROWS = {'456'}
_cache_lock = threading.Lock()

try:
    from resources.lib import log as _mslog
except Exception:
    _mslog = None

def log_error(msg=""):
    import traceback
    if _mslog is not None:
        try:
            _mslog.log(f"[Wedotv] ERROR: {msg}\n{traceback.format_exc()}", _mslog.LOGERROR)
            return
        except Exception:
            pass
    xbmc.log(f"[Wedotv] ERROR: {msg}\n{traceback.format_exc()}", xbmc.LOGERROR)

def log_warn(msg):
    if _mslog is not None:
        try:
            _mslog.log(f"[Wedotv] {msg}", _mslog.LOGWARNING)
            return
        except Exception:
            pass
    xbmc.log(f"[Wedotv] {msg}", xbmc.LOGWARNING)

def _ensure_cache_dir():
    try:
        if not os.path.exists(_CACHE_DIR):
            os.makedirs(_CACHE_DIR)
    except Exception:
        pass

def _cache_read(name, ttl=None):
    path = os.path.join(_CACHE_DIR, name)
    try:
        if ttl is not None and time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _cache_write(name, data):
    _ensure_cache_dir()
    try:
        with open(os.path.join(_CACHE_DIR, name), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

def _get_text(url, params=None, timeout=10):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers=dict(HEADERS))
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        log_error(f"URL: {url} | Error: {str(e)}")
        return None

def _get_json(url, params=None):
    text = _get_text(url, params)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception as e:
        log_error(f"JSON: {url} | Error: {str(e)}")
        return None

def _absolute_url(url):
    if not url:
        return ''
    url = str(url).strip()
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return _BASE + url
    return url

def _page_url(handler):
    handler = str(handler or '').strip()
    if not handler:
        return ''
    if handler.startswith('http'):
        return handler
    if not handler.startswith('/'):
        handler = '/' + handler
    if not re.match(r'^/[a-z]{2}-[a-z]{2}(/|$)', handler):
        handler = '/' + _LOC + handler
    return _BASE + handler

def _extract_img(item):
    if not isinstance(item, dict):
        return _ICON
    for k in ['portrait', 'image_placeholder', 'image', 'cover', 'poster']:
        val = item.get(k)
        if val:
            return _absolute_url(val)
    return _ICON

def _clean_html(text):
    if not text:
        return ''
    return htmllib.unescape(re.sub(r'<[^>]+>', '', str(text))).strip()

def _iso_duration(value):
    m = re.match(r'^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$', str(value or ''))
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s

def _parse_detail(html):
    info = {'plot': '', 'year': '', 'duration': 0, 'genre': [], 'cast': '', 'director': ''}
    for block in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        nodes = data.get('@graph') if isinstance(data, dict) and '@graph' in data else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get('@type') not in ('Movie', 'TVSeries', 'VideoObject', 'TVEpisode'):
                continue
            if not info['plot'] and node.get('description'):
                info['plot'] = _clean_html(node.get('description'))
            if not info['year']:
                cand = str(node.get('copyrightYear') or str(node.get('datePublished') or '')[:4] or '')
                if re.fullmatch(r'(19|20)\d{2}', cand):
                    info['year'] = cand
            if not info['duration']:
                info['duration'] = _iso_duration(node.get('duration'))
            if not info['genre'] and node.get('genre'):
                g = node.get('genre')
                info['genre'] = g if isinstance(g, list) else [g]
            if not info['cast'] and isinstance(node.get('actor'), list):
                info['cast'] = ', '.join(a.get('name', '') for a in node['actor'] if isinstance(a, dict) and a.get('name'))
            if not info['director'] and isinstance(node.get('director'), list):
                info['director'] = ', '.join(a.get('name', '') for a in node['director'] if isinstance(a, dict) and a.get('name'))
    if not info['plot']:
        m = re.search(r'class="hero-description">(.*?)</p>', html, re.S)
        if m:
            info['plot'] = _clean_html(m.group(1))
    extra = []
    if info['cast']:
        extra.append('Darsteller: ' + info['cast'])
    if info['director']:
        extra.append('Regie: ' + info['director'])
    if extra:
        info['plot'] = (info['plot'] + '\n\n' + '\n'.join(extra)).strip()
    return info

def _fetch_detail(handler):
    url = _page_url(handler)
    if not url:
        return None
    html = _get_text(url, timeout=8)
    if not html:
        return None
    info = _parse_detail(html)
    if not info['plot'] and not info['year']:
        return None
    det = {k: info[k] for k in ('plot', 'year', 'duration', 'genre')}
    if not re.fullmatch(r'(19|20)\d{2}', str(det.get('year') or '')):
        det['year'] = ''
    return det

def _enrich(items):
    cache = _cache_read('details.json') or {}
    missing = []
    for node in items:
        key = node.get('_key')
        if not key:
            continue
        det = cache.get(key)
        if det:
            if not re.fullmatch(r'(19|20)\d{2}', str(det.get('year') or '')):
                det = dict(det, year='')
            node.update(det)
        else:
            missing.append(node)

    if missing:
        deadline = time.time() + _DETAIL_BUDGET

        def work(node):
            if time.time() > deadline:
                return node, None
            return node, _fetch_detail(node['_handler'])

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            for node, det in pool.map(work, missing):
                if det:
                    cache[node['_key']] = det
                    node.update(det)
        _cache_write('details.json', cache)

    for node in items:
        node.pop('_key', None)
        node.pop('_handler', None)
    return items

def _item_to_node(item, media_type='auto'):
    if not isinstance(item, dict):
        return None
    wedotv_id = str(item.get('id') or item.get('media_catalog_id') or '')
    title = str(item.get('title') or '').strip()
    if not title or not wedotv_id:
        return None

    poster = _extract_img(item)
    url_handler = str(item.get('url_handler') or item.get('link') or '')
    category = str(item.get('category') or item.get('type') or item.get('media_type') or '').lower()

    if media_type == 'movie':
        is_series = False
    elif media_type == 'series':
        is_series = True
    else:
        is_series = category not in ('movie', 'film', '')

    return {
        'title': title,
        'url': f"{wedotv_id}|{url_handler}",
        'poster': poster,
        'icon': poster,
        'fanart': poster,
        'mediatype': 'tvshow' if is_series else 'movie',
        'is_playable': not is_series,
        'next_func': 'showSeasons' if is_series else 'get_hosters',
        'plot': '',
        '_key': wedotv_id,
        '_handler': url_handler
    }

def _batch_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ('items', 'movies', 'series', 'shows', 'data', 'episodes'):
            val = data.get(k)
            if isinstance(val, list) and val:
                return val
    return []

def _collect(batches, media_type):
    items = []
    seen = set()
    for batch in batches:
        for entry in batch or []:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get('id') or entry.get('media_catalog_id') or '')
            if not eid or eid in seen:
                continue
            seen.add(eid)
            node = _item_to_node(entry, media_type)
            if node:
                items.append(node)
    return items

def _fetch_paged(api, base_params, limit, media_type, max_items=3000, enrich=True):
    params = dict(base_params)
    params.update({'page': 1, 'limit': limit})
    data = _get_json(api, params=params)
    first = _batch_of(data)
    if not first:
        try:
            snippet = json.dumps(data, ensure_ascii=False)[:300]
        except Exception:
            snippet = str(data)[:300]
        log_warn(f"empty list {api} {params} -> {snippet}")
        return []
    batches = [first]
    total = 0
    if isinstance(data, dict):
        try:
            total = int(data.get('total') or 0)
        except (ValueError, TypeError):
            total = 0
    more = bool(data.get('hasMore')) if isinstance(data, dict) else len(first) >= limit

    if total and total > len(first):
        pages = int(math.ceil(min(total, max_items) / float(limit)))
        def get_page(p):
            q = dict(base_params)
            q.update({'page': p, 'limit': limit})
            return _batch_of(_get_json(api, params=q))
        if pages > 1:
            with ThreadPoolExecutor(max_workers=8) as pool:
                batches.extend(pool.map(get_page, range(2, pages + 1)))
    elif more:
        page = 2
        while page <= 60:
            q = dict(base_params)
            q.update({'page': page, 'limit': limit})
            d = _get_json(api, params=q)
            batch = _batch_of(d)
            if not batch:
                break
            batches.append(batch)
            if isinstance(d, dict) and not d.get('hasMore'):
                break
            if isinstance(d, list) and len(batch) < limit:
                break
            page += 1

    items = _collect(batches, media_type)
    if enrich:
        return _enrich(items)
    for node in items:
        node.pop('_key', None)
        node.pop('_handler', None)
    return items

def _fetch_genre(section, slug, media_type, enrich=True):
    extras = [{}]
    if section == 'series':
        extras.append({'country': _COUNTRY.upper(), 'locale': f'{_LANG}_{_COUNTRY.upper()}'})
    for extra in extras:
        params = {'poster_format': 'portrait'}
        params.update(extra)
        if slug and slug != 'all':
            params['genre'] = slug
        items = _fetch_paged(_API_LISTS[section], params, _LIST_LIMIT, media_type, enrich=enrich)
        if items:
            return items
    if section == 'series' and (not slug or slug == 'all'):
        return _rows_merged('series', media_type, enrich)
    return []

def _rows_merged(section, media_type, enrich=True):
    rows = _section_rows(section)
    if not rows:
        return []
    def get(row):
        return _fetch_paged(_API_PLAYLIST, {'row': row[1], 'poster_format': 'portrait'}, _PAGE_LIMIT, media_type, enrich=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(get, rows))
    items = []
    seen = set()
    for group in groups:
        for node in group:
            if node['url'] not in seen:
                seen.add(node['url'])
                items.append(node)
    if enrich:
        for node in items:
            node['_key'] = node['url'].split('|')[0]
            node['_handler'] = node['url'].split('|', 1)[1] if '|' in node['url'] else ''
        return _enrich(items)
    return items

def _fetch_playlist(row, media_type='auto', max_items=600):
    params = {'row': row, 'poster_format': 'portrait'}
    return _fetch_paged(_API_PLAYLIST, params, _PAGE_LIMIT, media_type, max_items=max_items)

def _section_genres(section):
    name = f'genres_{section}.json'
    cached = _cache_read(name, ttl=24 * 3600)
    if cached:
        return [tuple(x) for x in cached]
    html = _get_text(_BASE + '/' + _LOC + _SECTIONS[section], timeout=12)
    genres = []
    if html:
        seen = set()
        pattern = r'href="/[a-z]{2}-[a-z]{2}/' + section + r'/([^"/?#]+)"\s+class="custom-select-option[^"]*">\s*([^<]*?)\s*<'
        for slug, label in re.findall(pattern, html):
            if slug in seen:
                continue
            seen.add(slug)
            genres.append((htmllib.unescape(label).strip(), slug))
    if genres:
        _cache_write(name, genres)
        return genres
    return list(_FALLBACK_GENRES)

def _section_rows(section):
    cached = _cache_read(f'rows_{section}.json', ttl=6 * 3600)
    if cached:
        return [tuple(x) for x in cached]
    html = _get_text(_BASE + '/' + _LOC + _SECTIONS[section], timeout=12)
    rows = []
    if html:
        seen = set()
        for m in re.finditer(r'<section class="carousel-section">.*?data-playlist_id="(\d+)"', html, re.S):
            rid = m.group(1)
            titles = re.findall(r'carousel-title">([^<]*)<', m.group(0))
            if rid in seen or rid in _SKIP_ROWS or not titles:
                continue
            seen.add(rid)
            rows.append((htmllib.unescape(titles[-1]).strip(), rid))
    if rows:
        _cache_write(f'rows_{section}.json', rows)
    return rows

def _menu(section, genre_func, rows_func):
    nodes = [{'title': t, 'url': slug, 'is_playable': False, 'next_func': genre_func, 'poster': _ICON, 'icon': _ICON} for t, slug in _section_genres(section)]
    nodes.append({'title': 'Kollektionen', 'url': section, 'plot': 'Kuratierte Listen der Startseite.', 'is_playable': False, 'next_func': rows_func, 'poster': _ICON, 'icon': _ICON})
    return nodes

def _row_menu(section, next_func):
    return [{'title': t, 'url': rid, 'is_playable': False, 'next_func': next_func, 'poster': _ICON, 'icon': _ICON} for t, rid in _section_rows(section)]

def load(url='', params=None):
    return [
        {
            'title': 'Suche',
            'url': '',
            'plot': 'Durchsucht Wedotv nach Filmen und Serien.',
            'is_playable': False,
            'next_func': 'search',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Filme',
            'url': 'movies_cat',
            'plot': 'Verfügbare Filme nach Genres.',
            'is_playable': False,
            'next_func': 'showMovieGenres',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Serien',
            'url': 'series_cat',
            'plot': 'Verfügbare Serien auf Wedotv.',
            'is_playable': False,
            'next_func': 'showSeries',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Sport',
            'url': 'sport_cat',
            'plot': 'Sport-Inhalte auf Wedotv.',
            'is_playable': False,
            'next_func': 'showSport',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Cache leeren',
            'url': '',
            'plot': 'Löscht den lokalen Cache.',
            'is_playable': False,
            'next_func': 'clear_cache',
            'poster': _ICON,
            'icon': _ICON
        }
    ]

def showMovieGenres(url='', params=None):
    try:
        return _menu('movies', 'showGenreMovies', 'showMovieRows')
    except Exception as e:
        log_error(f"showMovieGenres error: {e}")
        return []

def showGenreMovies(url='', params=None):
    try:
        return _fetch_genre('movies', url, 'movie')
    except Exception as e:
        log_error(f"showGenreMovies error: {e}")
        return []

def showMovieRows(url='', params=None):
    return _row_menu('movies', 'showMovieRow')

def showMovieRow(url='', params=None):
    try:
        return _fetch_playlist(url, 'movie')
    except Exception as e:
        log_error(f"showMovieRow error: {e}")
        return []

def showSeries(url='', params=None):
    try:
        return _menu('series', 'showSeriesGenre', 'showSeriesRows')
    except Exception as e:
        log_error(f"showSeries error: {e}")
        return []

def showSeriesGenre(url='', params=None):
    try:
        return _fetch_genre('series', url, 'series')
    except Exception as e:
        log_error(f"showSeriesGenre error: {e}")
        return []

def showSeriesRows(url='', params=None):
    return _row_menu('series', 'showSeriesRow')

def showSeriesRow(url='', params=None):
    try:
        return _fetch_playlist(url, 'series')
    except Exception as e:
        log_error(f"showSeriesRow error: {e}")
        return []

def showSport(url='', params=None):
    try:
        return _row_menu('sport', 'showSportRow')
    except Exception as e:
        log_error(f"showSport error: {e}")
        return []

def showSportRow(url='', params=None):
    try:
        return _fetch_playlist(url, 'auto')
    except Exception as e:
        log_error(f"showSportRow error: {e}")
        return []

def _parse_episodes(html):
    episodes = []
    for m in re.finditer(r'<a\s[^>]*class="episode-card"[^>]*>(.*?)</a>', html, re.S):
        tag = html[m.start():m.start() + 400]
        body = m.group(1)
        s = re.search(r'data-season="(\d+)"', tag)
        e = re.search(r'data-episode="(\d+)"', tag)
        vid = re.search(r'data-video-id="(\d+)"', body)
        if not vid:
            continue
        title = re.search(r'<h4[^>]*>(.*?)</h4>', body, re.S)
        plot = re.search(r'<p[^>]*>(.*?)</p>', body, re.S)
        small = re.search(r'<small[^>]*>(.*?)</small>', body, re.S)
        thumb = re.search(r"background-image:\s*url\('([^']+)'\)", body)
        minutes = 0
        if small:
            mm = re.search(r'(\d+)\s*min', small.group(1))
            if mm:
                minutes = int(mm.group(1)) * 60
        raw_title = _clean_html(title.group(1)) if title else ''
        episodes.append({
            'season': int(s.group(1)) if s else 1,
            'episode': int(e.group(1)) if e else 0,
            'video_id': vid.group(1),
            'title': re.sub(r'^S\d+\s*E\d+:\s*', '', raw_title) or raw_title,
            'plot': _clean_html(plot.group(1)) if plot else '',
            'duration': minutes,
            'thumb': thumb.group(1) if thumb else ''
        })
    return episodes

def _duration_seconds(value):
    text = str(value or '')
    m = re.search(r'(\d+)', text)
    if not m:
        return 0
    n = int(m.group(1))
    if 'min' in text.lower():
        return n * 60
    return n if n > 600 else n * 60

def _api_episodes(series_id, season):
    result = []
    page = 1
    while page <= 30:
        data = _get_json(_API_LISTS['series'], params={'series_id': series_id, 'season': season, 'page': page, 'limit': 24, 'poster_format': 'landscape'})
        batch = _batch_of(data)
        if not batch:
            break
        for ep in batch:
            if not isinstance(ep, dict) or not ep.get('id'):
                continue
            try:
                ep_num = int(ep.get('episode_number') or ep.get('episode') or 0)
            except (ValueError, TypeError):
                ep_num = 0
            try:
                s_num = int(ep.get('season') or season)
            except (ValueError, TypeError):
                s_num = int(season)
            result.append({
                'season': s_num,
                'episode': ep_num,
                'video_id': str(ep['id']),
                'title': str(ep.get('title') or '').strip(),
                'plot': _clean_html(ep.get('description') or ''),
                'duration': _duration_seconds(ep.get('duration')),
                'thumb': _absolute_url(ep.get('thumbnail_placeholder') or ep.get('image_placeholder') or '')
            })
        if isinstance(data, dict) and not data.get('hasMore'):
            break
        if isinstance(data, list):
            break
        page += 1
    return result

def _series_page(handler):
    html = _get_text(_page_url(handler), timeout=12)
    if not html:
        return '', [], ''
    info = _parse_detail(html)
    og = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    episodes = _parse_episodes(html)

    containers = re.findall(r'<h3[^>]*>\s*(?:Season|Staffel)\s+(\d+)\s*</h3>\s*<div class="carousel-items js-carousel-episodes"[^>]*data-series_id="(\d+)"', html)
    if containers:
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(lambda c: _api_episodes(c[1], c[0]), containers))
        by_id = {ep['video_id']: ep for ep in episodes}
        for group in fetched:
            for ep in group:
                old = by_id.get(ep['video_id'])
                if old:
                    for k in ('title', 'plot', 'thumb'):
                        if not old.get(k) and ep.get(k):
                            old[k] = ep[k]
                else:
                    by_id[ep['video_id']] = ep
        episodes = list(by_id.values())
    return info['plot'], episodes, og.group(1) if og else ''

def _episode_nodes(episodes, poster, series_plot=''):
    items = []
    for ep in sorted(episodes, key=lambda x: (x['season'], x['episode'])):
        img = ep['thumb'] or poster or _ICON
        label = f"{ep['episode']}. {ep['title']}" if ep['episode'] else ep['title']
        items.append({
            'title': label,
            'url': f"{ep['video_id']}|",
            'poster': img,
            'icon': img,
            'fanart': poster or img,
            'mediatype': 'episode',
            'is_playable': True,
            'next_func': 'get_hosters',
            'plot': ep['plot'] or series_plot,
            'duration': ep['duration'],
            'season': ep['season'],
            'episode': ep['episode']
        })
    return items

def showSeasons(url='', params=None):
    if not url or '|' not in url:
        return []
    parts = url.split('|')
    handler = parts[1] if len(parts) > 1 else ''

    try:
        plot, episodes, poster = _series_page(handler)
        if not episodes:
            return [{
                'title': 'Abspielen',
                'url': url,
                'poster': poster or _ICON,
                'icon': poster or _ICON,
                'mediatype': 'episode',
                'is_playable': True,
                'next_func': 'get_hosters',
                'plot': plot
            }]

        seasons = sorted({ep['season'] for ep in episodes})
        if len(seasons) == 1:
            return _episode_nodes(episodes, poster, plot)

        return [{
            'title': f"Staffel {n}",
            'url': f"{parts[0]}|{handler}|{n}",
            'poster': poster or _ICON,
            'icon': poster or _ICON,
            'fanart': poster or _ICON,
            'plot': plot,
            'is_playable': False,
            'next_func': 'showEpisodes'
        } for n in seasons]
    except Exception as e:
        log_error(f"showSeasons error: {e}")
        return []

def showEpisodes(url='', params=None):
    parts = (url or '').split('|')
    if len(parts) < 3:
        return []
    handler = parts[1]
    try:
        target = int(parts[2])
    except ValueError:
        return []

    try:
        plot, episodes, poster = _series_page(handler)
        return _episode_nodes([e for e in episodes if e['season'] == target], poster, plot)
    except Exception as e:
        log_error(f"showEpisodes error: {e}")
        return []

def _play_url(url):
    return f"{url}|User-Agent={urllib.parse.quote(_UA)}&Referer={urllib.parse.quote(_BASE + '/')}"

def _resolve(url):
    if not url:
        return []

    if '|' in url:
        parts = url.split('|')
        wedotv_id, url_handler = parts[0], parts[1]
    else:
        wedotv_id = url
        url_handler = ''

    real_video_id = wedotv_id

    if url_handler:
        web_url = _page_url(url_handler)
        html = _get_text(web_url, timeout=8)
        if html:
            vid_match = re.search(r'data-video-id\s*=\s*["\'](\d+)["\']', html)
            if vid_match:
                real_video_id = vid_match.group(1)
            else:
                m3u8_match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
                if m3u8_match:
                    return [('Wedotv (HD)', _play_url(m3u8_match.group(1)), True, 'HD', 'de')]

    pdata = _get_json(_API_PLAYER, params={'video_id': real_video_id, '_cb': int(time.time() * 1000)})

    def find_m3u8(obj):
        if isinstance(obj, dict):
            src = obj.get('video_source')
            if isinstance(src, str) and '.m3u8' in src.lower():
                return _absolute_url(src)
            for v in obj.values():
                res = find_m3u8(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = find_m3u8(item)
                if res:
                    return res
        elif isinstance(obj, str) and '.m3u8' in obj.lower() and obj.startswith(('http', '//', '/')):
            return _absolute_url(obj)
        return ''

    stream_url = find_m3u8(pdata)
    if stream_url:
        return [('Wedotv (HD)', _play_url(stream_url), True, 'HD', 'de')]

    return []

def _norm(text):
    text = str(text or '').lower().replace('ß', 'ss').replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', text)

def _catalog(section):
    name = f'catalog_{section}.json'
    cached = _cache_read(name, ttl=12 * 3600)
    if cached:
        return cached
    media_type = 'movie' if section == 'movies' else 'series'
    nodes = _fetch_genre(section, 'all', media_type, enrich=False)
    entries = [[n['title'], n['url']] for n in nodes]
    if entries:
        _cache_write(name, entries)
    return entries

def _find_entries(section, title):
    target = _norm(title)
    if not target:
        return []
    entries = _catalog(section)
    exact = [e for e in entries if _norm(e[0]) == target]
    if exact:
        return exact
    loose = [e for e in entries if _norm(e[0]).startswith(target) or target.startswith(_norm(e[0])) and len(_norm(e[0])) >= 6]
    return loose[:3]

def _pick_by_year(entries, year):
    if len(entries) <= 1 or not str(year or '').isdigit():
        return entries[0] if entries else None
    for e in entries:
        det = _fetch_detail(e[1].split('|', 1)[1]) if '|' in e[1] else None
        if det and det.get('year') == str(year):
            return e
    return entries[0]

def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        return _resolve(url)

    try:
        season = int(season or 0)
        episode = int(episode or 0)
    except (ValueError, TypeError):
        season, episode = 0, 0

    try:
        if season > 0 and episode > 0:
            entry = _pick_by_year(_find_entries('series', title), year)
            if not entry or '|' not in entry[1]:
                return []
            handler = entry[1].split('|', 1)[1]
            _, episodes, _ = _series_page(handler)
            for ep in episodes:
                if ep['season'] == season and ep['episode'] == episode:
                    return _resolve(f"{ep['video_id']}|")
            return []

        entry = _pick_by_year(_find_entries('movies', title), year)
        if not entry:
            return []
        return _resolve(entry[1])
    except Exception as e:
        log_error(f"get_hosters scout error: {e}")
        return []

def search(query='', params=None, url=''):
    if not query:
        try:
            query = xbmcgui.Dialog().input('Wedotv Suche')
            if not query:
                return []
        except Exception:
            return []

    try:
        q = query.lower()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_movies = pool.submit(_fetch_genre, 'movies', 'all', 'movie', False)
            f_series = pool.submit(_fetch_genre, 'series', 'all', 'series', False)
            pool_results = f_movies.result() + f_series.result()
        seen = set()
        matched = []
        for node in pool_results:
            if node['url'] in seen or q not in node.get('title', '').lower():
                continue
            seen.add(node['url'])
            matched.append(node)
        if not matched:
            xbmcgui.Dialog().notification('Wedotv', 'Keine Treffer gefunden.', xbmcgui.NOTIFICATION_INFO, 3000, False)
        return matched[:60]
    except Exception as e:
        log_error(f"search error: {e}")
        return []

def clear_cache(url='', params=None):
    try:
        if os.path.exists(_CACHE_DIR):
            for root, dirs, files in os.walk(_CACHE_DIR, topdown=False):
                for name in files:
                    try:
                        os.remove(os.path.join(root, name))
                    except Exception:
                        pass
    except Exception as e:
        log_error(f"clear_cache error: {e}")
    xbmcgui.Dialog().notification('Wedotv', 'Cache geleert', xbmcgui.NOTIFICATION_INFO, 3000, False)
    return []
