# -*- coding: utf-8 -*-
# Scraper by mr-evil1
# mod by Zusatzmetall
# IT('s) Possible Team
# 2026.09.19
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import os
import time
import xbmcvfs
import xbmc
import xbmcgui
import xbmcaddon
from concurrent.futures import ThreadPoolExecutor, as_completed

SITE_ID       = 'netzkino'
SITE_NAME     = 'Netzkino'
SITE_DOMAIN   = 'netzkino.de'
TYPE          = 'both'
GLOBAL_SEARCH = True

try:
    _ICON = xbmcaddon.Addon().getAddonInfo('icon')
except Exception:
    _ICON = ''

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

_BASE       = 'https://www.netzkino.de/'
_GQL        = 'https://data.netzkino.de/netzkino/graphql'
_URL_STREAM = 'https://pmd.netzkino-seite.netzkino.de/'

_URL_GENRE  = _BASE + 'genre'
_URL_CAT    = _BASE + 'kategorie/%s'
_URL_DETAIL = _BASE + 'details/%s'

_HASH_CAT     = '5e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8'
_HASH_ALL     = '51eb32b81108d564d20969692d53311885bc80b2d1a7041ce5cba1398923caa6'
_HASH_DETAILS = '692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97'
_HASH_VIDEO   = 'ce2a04069f5ed18f6399df7070a2d27e209a7c530c77e4fb583ec898da02b1f1'
_HASH_SEARCH  = 'e7f141530416887b1faa663dbdd468534c6639e47886e8156686afd9a0f81d76'

_CACHE_DIR = os.path.join(
    xbmcvfs.translatePath('special://profile/addon_data/'),
    'plugin.video.moviescout',
    'netzkino'
)
_CATEGORY_CACHE_TTL   = 7 * 24 * 3600
_DETAILS_CACHE_TTL    = 7 * 24 * 3600
_ALL_MOVIES_CACHE_TTL = 7 * 24 * 3600
_MAX_WORKERS  = 9
_PAGE_SIZE    = 200
_MEM_CATEGORY = {}
_MEM_DETAILS  = {}


def _cache_file(kind, key):
    import hashlib
    digest = hashlib.sha1(str(key).encode('utf-8')).hexdigest()
    return os.path.join(_CACHE_DIR, '%s_%s.json' % (kind, digest))


def _cache_load(kind, key, ttl):
    if not key:
        return None

    memory = _MEM_CATEGORY if kind == 'cat' else _MEM_DETAILS
    mem_key = str(key)
    now = time.time()

    entry = memory.get(mem_key)
    if entry:
        timestamp, value = entry
        if now - timestamp < ttl:
            return value
        memory.pop(mem_key, None)

    path = _cache_file(kind, key)
    try:
        if not os.path.isfile(path):
            return None
        if now - os.path.getmtime(path) >= ttl:
            return None
        with open(path, 'r', encoding='utf-8') as fh:
            value = json.load(fh)
        memory[mem_key] = (now, value)
        return value
    except Exception as e:
        log_error('Cache read error: %s' % e)
        return None


def _cache_save(kind, key, value):
    if not key:
        return

    memory = _MEM_CATEGORY if kind == 'cat' else _MEM_DETAILS
    mem_key = str(key)
    now = time.time()
    memory[mem_key] = (now, value)

    try:
        if not os.path.isdir(_CACHE_DIR):
            xbmcvfs.mkdirs(_CACHE_DIR)
        path = _cache_file(kind, key)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(value, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, path)
    except Exception as e:
        log_error('Cache write error: %s' % e)


_MAIN_CATS = [
    ('Serien',           'serien'),
    ('Alle Filme (A-Z)', 'alle-filme'),
]

def log_error(msg=""):
    import traceback
    xbmc.log(f"[Netzkino] ERROR: {msg}\n{traceback.format_exc()}", xbmc.LOGERROR)

def _clean_html(raw_text):
    if not raw_text:
        return ''
    text = re.sub(r'<[^>]+>', '', str(raw_text))
    return text.strip()

def _sort_year(items):
    def year_key(x):
        try:
            return int(x.get('year') or 0)
        except (ValueError, TypeError):
            return 0
    return sorted(items, key=year_key, reverse=True)

class DummyResponse:
    def __init__(self, text, status):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP Error {self.status_code}")
    def json(self):
        return json.loads(self.text)

def _get(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode('utf-8', errors='ignore')
            return DummyResponse(content, response.status)
    except urllib.error.HTTPError as e:
        return DummyResponse('', e.code)
    except Exception as e:
        log_error(str(e))
        return None

def _get_html(url):
    r = _get(url, timeout=15)
    return r.text if r else ''

def _gql(op, hash_, variables, fallback_hash=None):
    ext = json.dumps({'persistedQuery': {'version': 1, 'sha256Hash': hash_}})
    var = json.dumps(variables)
    url = f"{_GQL}?extensions={urllib.parse.quote(ext)}&variables={urllib.parse.quote(var)}&operationName={urllib.parse.quote(op)}"

    try:
        r = _get(url, timeout=15)
        if not r:
            return {}
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            return {}

        errors = body.get('errors') or []
        if fallback_hash:
            for error in errors:
                if isinstance(error, dict) and error.get('message') == 'PersistedQueryNotFound':
                    return _gql(op, fallback_hash, variables)

        data = body.get('data')
        if isinstance(data, dict):
            return data
    except Exception as e:
        log_error(str(e))
    return {}

def _next_data(url):
    html = _get_html(url)
    if not html:
        return None
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None

def _fetch_next_data(slug_or_url):
    if not slug_or_url:
        return None
    urls = [str(slug_or_url)] if str(slug_or_url).startswith('http') else [_URL_CAT % slug_or_url, _BASE + str(slug_or_url)]
    for url in urls:
        nd = _next_data(url)
        if nd:
            return nd
    return None

def _find_query(next_data, names):
    if not isinstance(next_data, dict):
        return None
    if isinstance(names, str):
        names = [names]
    try:
        queries = next_data.get('props', {}).get('__dehydratedState', {}).get('queries', [])
        for query in queries:
            if not isinstance(query, dict):
                continue
            key = query.get('queryKey') or []
            if not key or key[0] not in names:
                continue
            state = query.get('state') or {}
            data = state.get('data') or {}
            if not isinstance(data, dict):
                continue
            return data.get('data') or data
    except Exception as e:
        log_error(str(e))
    return None

def _find_category_in_next_data(next_data):
    data = _find_query(next_data, ['CategoryDataBySlug', 'AllContent', 'CategoryData'])
    if not isinstance(data, dict):
        return {}
    category = data.get('category') or data.get('parentCategory')
    return category if isinstance(category, dict) else {}

def _img(node, *keys):
    if not isinstance(node, dict):
        return ''
    for key in keys:
        image = node.get(key)
        if isinstance(image, dict) and image.get('masterUrl'):
            return str(image['masterUrl'])
    return _ICON

def _extract_details(obj):
    if not isinstance(obj, dict):
        return {}

    plot_raw = (
        obj.get('longSynopsis')
        or obj.get('shortSynopsis')
        or obj.get('synopsis')
        or obj.get('description')
        or obj.get('teaser')
        or ''
    )

    year = obj.get('productionYear') or obj.get('year') or ''

    genres = []
    genres_obj = obj.get('genres') or obj.get('categories') or []
    if isinstance(genres_obj, dict):
        genres_obj = genres_obj.get('nodes') or []
    if isinstance(genres_obj, list):
        for g in genres_obj:
            if isinstance(g, dict) and g.get('title'):
                genres.append(g['title'])
            elif isinstance(g, str):
                genres.append(g)

    duration = obj.get('duration') or obj.get('runtime') or 0
    try:
        duration = int(duration)
        if 0 < duration < 300:
            duration = duration * 60
    except (ValueError, TypeError):
        duration = 0

    rating = obj.get('imDbRating') or obj.get('imdbRating') or obj.get('rating') or 0.0
    try:
        rating = float(rating)
    except (ValueError, TypeError):
        rating = 0.0

    directors = []
    dirs_obj = obj.get('directors') or obj.get('director') or []
    if isinstance(dirs_obj, dict):
        dirs_obj = dirs_obj.get('nodes') or []
    if isinstance(dirs_obj, list):
        for d in dirs_obj:
            if isinstance(d, dict) and d.get('name'):
                directors.append(d['name'])
            elif isinstance(d, str):
                directors.append(d)

    return {
        'plot': _clean_html(plot_raw),
        'year': str(year) if year else '',
        'genre': genres,
        'duration': duration,
        'rating': rating,
        'director': directors,
    }

def _node_to_item(node):
    if not isinstance(node, dict):
        return None
    movie = node.get('contentMovie') or node.get('movie')
    series = node.get('contentSeries') or node.get('series')

    if not movie and not series:
        if node.get('numberOfSeasons') is not None or node.get('seasons') is not None:
            series = node
        elif node.get('type') == 'series' or node.get('isSeries'):
            series = node
        elif node.get('id') or node.get('title') or node.get('slug'):
            movie = node

    if isinstance(movie, dict) and movie.get('title'):
        slug = str(movie.get('slug') or movie.get('id') or '')
        details = _extract_details(movie)
        poster = _img(movie, 'coverImage', 'widescreenImage') or _ICON
        return {
            'title': str(movie.get('title') or ''),
            'url': slug,
            'poster': poster,
            'icon': poster,
            'fanart': _img(movie, 'widescreenImage', 'headerImage24By9'),
            'mediatype': 'movie',
            'is_playable': True,
            'next_func': 'get_hosters',
            **details
        }

    if isinstance(series, dict) and series.get('title'):
        slug = str(series.get('slug') or series.get('id') or '')
        details = _extract_details(series)
        poster = _img(series, 'coverImage', 'widescreenImage') or _ICON
        return {
            'title': str(series.get('title') or ''),
            'url': slug,
            'poster': poster,
            'icon': poster,
            'fanart': _img(series, 'widescreenImage', 'headerImage24By9'),
            'mediatype': 'tvshow',
            'is_playable': False,
            'next_func': 'showSeasons',
            **details
        }
    return None

def _fetch_single_details(item):
    if not isinstance(item, dict):
        return item

    url = str(item.get('url') or '')
    if not url:
        return item

    cached = _cache_load('details', url, _DETAILS_CACHE_TTL)
    if isinstance(cached, dict):
        item.update(cached)
        return item

    data = _gql(
        'MovieDetails',
        _HASH_DETAILS,
        {
            'movieId': url,
            'externalId': url,
            'slug': url,
            'potentialMovieId': url
        }
    )

    details = {}
    if isinstance(data, dict):
        movie = (
            data.get('movie')
            or data.get('series')
            or data.get('contentMovie')
            or data.get('contentSeries')
            or {}
        )
        if isinstance(movie, dict) and movie:
            details = _extract_details(movie)
            poster = _img(movie, 'coverImage', 'widescreenImage')
            fanart = _img(movie, 'widescreenImage', 'headerImage24By9')
            if poster:
                details['poster'] = poster
                details['icon'] = poster
            if fanart:
                details['fanart'] = fanart

    if details:
        _cache_save('details', url, details)
        item.update(details)

    if not item.get('poster'):
        item['poster'] = _ICON
    if not item.get('icon'):
        item['icon'] = _ICON
    return item

def _enrich_items(items):
    if not items:
        return []

    items_to_enrich = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get('poster'):
            item['poster'] = _ICON
        if not item.get('icon'):
            item['icon'] = _ICON

        if not (item.get('is_playable') or item.get('mediatype') in ('movie', 'tvshow')):
            continue

        if not item.get('plot'):
            items_to_enrich.append(item)

    if not items_to_enrich:
        return items

    uncached = []
    for item in items_to_enrich:
        if _cache_load('details', str(item.get('url') or ''), _DETAILS_CACHE_TTL) is None:
            uncached.append(item)

    if not uncached:
        for item in items_to_enrich:
            _fetch_single_details(item)
        return items

    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create('Netzkino', 'Lade zusätzliche Film-Details...')
    total = len(uncached)
    completed = 0

    try:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, total)) as executor:
            futures = [executor.submit(_fetch_single_details, item) for item in uncached]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log_error(str(e))
                completed += 1
                p_dialog.update(
                    int(completed * 100 / total),
                    f'Details: {completed}/{total}'
                )
    finally:
        p_dialog.close()

    for item in items_to_enrich:
        if item not in uncached:
            _fetch_single_details(item)

    return items

def _category_slugs(slug):
    slug = str(slug or '').strip().strip('/')
    if not slug:
        return []
    result = [slug]
    if slug.endswith('-frontpage'):
        base_slug = slug[:-10].rstrip('-')
        if base_slug:
            result.append(base_slug)
    elif slug.endswith('_frontpage'):
        base_slug = slug[:-11].rstrip('_')
        if base_slug:
            result.append(base_slug)
    return result

def _gql_category_all(slug, use_cache=True):
    cache_key = str(slug or '').strip().strip('/')
    if use_cache:
        cached = _cache_load('cat', cache_key, _CATEGORY_CACHE_TTL)
        if cached is not None:
            return cached

    best = []
    for current_slug in _category_slugs(slug):
        items = []
        after = None
        page = 1
        while True:
            variables = {'slug': current_slug}
            if after:
                variables['after'] = after
            data = _gql('CategoryDataBySlug', _HASH_CAT, variables)
            if not isinstance(data, dict):
                break
            category = data.get('category')
            if not isinstance(category, dict):
                break
            content = category.get('content') or {}
            if not isinstance(content, dict):
                break

            for node in content.get('nodes') or []:
                item = _node_to_item(node)
                if item:
                    items.append(item)

            page_info = content.get('pageInfo') or {}
            if page_info.get('hasNextPage') and page_info.get('endCursor'):
                new_after = page_info.get('endCursor')
                if new_after == after:
                    break
                after = new_after
                page += 1
                if page > 100:
                    break
            else:
                break

        if len(items) > len(best):
            best = items

        if best:
            break

    _cache_save('cat', cache_key, best)
    return best

def showGenres(url='', params=None):
    data = _gql('AllContent', _HASH_ALL, {'parentSlug': 'netzkino-genre', 'featuredSlug': 'keinefeatured'})
    if not isinstance(data, dict):
        return []
    parent = data.get('parentCategory') or {}
    subcategories = parent.get('subcategories') or {} if isinstance(parent, dict) else {}
    nodes = subcategories.get('nodes') or [] if isinstance(subcategories, dict) else {}
    items = []
    for node in nodes:
        if isinstance(node, dict) and node.get('slug') and node.get('title'):
            items.append({'title': str(node['title']), 'url': str(node['slug']), 'is_playable': False, 'next_func': 'showEntries', 'poster': _ICON, 'icon': _ICON})
    return items

def _discover_slugs_parallel(initial_slugs, p_dialog, max_rounds=4):
    discovered = set(initial_slugs)
    frontier = list(initial_slugs)
    for _ in range(max_rounds):
        if not frontier or p_dialog.iscanceled():
            break
        new_slugs = []
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, max(1, len(frontier)))) as executor:
            futures = {executor.submit(_next_data_category_items, slug): slug for slug in frontier}
            for future in as_completed(futures):
                if p_dialog.iscanceled():
                    return list(discovered)
                try:
                    for sub in future.result() or []:
                        if not sub.get('is_playable') and sub.get('next_func') == 'showEntries':
                            sub_slug = sub.get('url')
                            if sub_slug and sub_slug not in discovered:
                                discovered.add(sub_slug)
                                new_slugs.append(sub_slug)
                except Exception as e:
                    log_error(f'Slug discovery error: {e}')
        frontier = new_slugs
    return list(discovered)


def _get_all_movies_cached():
    cache_path = os.path.join(
        _CACHE_DIR, 'temp', 'netzkino_all_movies_cache.json'
    )
    temp_dir = os.path.dirname(cache_path)

    try:
        if not os.path.isdir(temp_dir):
            xbmcvfs.mkdirs(temp_dir)
        if os.path.isfile(cache_path) and (
            time.time() - os.path.getmtime(cache_path) < _ALL_MOVIES_CACHE_TTL
        ):
            with open(cache_path, 'r', encoding='utf-8') as fh:
                cached = json.load(fh)
            if isinstance(cached, list):
                xbmc.log('[Netzkino] Alle Filme aus Cache geladen.', xbmc.LOGINFO)
                return cached
    except Exception as e:
        log_error(f'Cache read error: {e}')

    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create('Netzkino', 'Starte A-Z Indexierung...')

    all_items = []
    try:
        seed_slugs = set()
        for c in _MAIN_CATS:
            slug = c if isinstance(c, (list, tuple)) and len(c) > 1 else c
            if isinstance(slug, str) and slug != 'serien':
                seed_slugs.add(slug)

        p_dialog.update(5, 'Lade Genre-Liste...')
        for g in showGenres():
            if isinstance(g, dict) and g.get('url'):
                seed_slugs.add(g['url'])

        p_dialog.update(10, f'{len(seed_slugs)} Start-Slugs - entdecke Unterkategorien...')
        slug_list = _discover_slugs_parallel(seed_slugs, p_dialog)

        if p_dialog.iscanceled():
            return []

        total_slugs = len(slug_list)
        p_dialog.update(25, f'{total_slugs} Kategorien gefunden. Lade Filme...')

        seen_ids = set()
        completed_slugs = 0

        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, max(1, total_slugs))) as executor:
            futures = {executor.submit(_gql_category_all, slug): slug for slug in slug_list}
            for future in as_completed(futures):
                if p_dialog.iscanceled():
                    break
                try:
                    for item in future.result() or []:
                        uid = str(item.get('url') or '')
                        if uid and uid not in seen_ids:
                            seen_ids.add(uid)
                            all_items.append(item)
                except Exception as e:
                    log_error(f'AllMovies category error: {e}')
                completed_slugs += 1
                pct = 25 + int((completed_slugs / max(1, total_slugs)) * 70)
                p_dialog.update(pct, f'Lade Kategorien: {completed_slugs}/{total_slugs} ({len(all_items)} Filme)')

        if p_dialog.iscanceled():
            return []

        p_dialog.update(96, f'Sortiere {len(all_items)} Filme...')
        all_items.sort(key=lambda x: str(x.get('title', '')).casefold())

    finally:
        p_dialog.close()

    try:
        if not os.path.isdir(temp_dir):
            xbmcvfs.mkdirs(temp_dir)
        tmp = cache_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(all_items, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, cache_path)
    except Exception as e:
        log_error(f'Cache write error: {e}')

    return all_items


def showAllMovies(url='', params=None):
    return _get_all_movies_cached()


def showYears(url='', params=None):
    all_items = _get_all_movies_cached()
    years_map = {}
    
    for item in all_items:
        if not isinstance(item, dict):
            continue
        y = str(item.get('year') or '').strip()
        if y and y.isdigit():
            val = int(y)
            years_map[val] = years_map.get(val, 0) + 1

    sorted_years = sorted(years_map.keys(), reverse=True)
    
    items = []
    for y in sorted_years:
        count = years_map[y]
        items.append({
            'title': f'{y}  ({count} {"Film" if count == 1 else "Filme"})',
            'url': f'year_filter|{y}',
            'plot': f'Alle Filme aus dem Jahr {y}',
            'is_playable': False,
            'next_func': 'showMoviesForYear',
            'poster': _ICON,
            'icon': _ICON
        })
    return items


def showMoviesForYear(url='', params=None):
    if not url or '|' not in url:
        return []
    
    parts = str(url).split('|', 1)
    target_year = parts[1].strip() if len(parts) > 1 else ''
    all_items = _get_all_movies_cached()
    
    filtered = []
    seen = set()
    for item in all_items:
        if str(item.get('year')) == target_year:
            uid = str(item.get('url') or '')
            if uid not in seen:
                seen.add(uid)
                filtered.append(item)
                
    filtered.sort(key=lambda x: str(x.get('title', '')).casefold())
    return _enrich_items(filtered)
    

def _next_data_category_items(url):
    next_data = _fetch_next_data(url)
    if not next_data:
        return []
    category = _find_category_in_next_data(next_data)
    if not category:
        return []

    subcategories = category.get('subcategories') or {}
    sub_nodes = subcategories.get('nodes') if isinstance(subcategories, dict) else []
    if sub_nodes:
        items = []
        for sub in sub_nodes:
            if not isinstance(sub, dict):
                continue
            slug, title = sub.get('slug'), sub.get('title')
            if slug and title:
                items.append({
                    'title': str(title),
                    'url': str(slug),
                    'is_playable': False,
                    'next_func': 'showEntries',
                    'poster': _ICON,
                    'icon': _ICON
                })
        if items:
            return items

    items = []
    content = category.get('content') or {}
    if isinstance(content, dict):
        for node in content.get('nodes') or []:
            item = _node_to_item(node)
            if item:
                items.append(item)
    return items

def clear_cache(url='', params=None):
    _MEM_CATEGORY.clear()
    _MEM_DETAILS.clear()

    removed = 0
    try:
        if os.path.exists(_CACHE_DIR):
            for root, dirs, files in os.walk(_CACHE_DIR, topdown=False):
                for name in files:
                    try:
                        os.remove(os.path.join(root, name))
                        removed += 1
                    except Exception:
                        pass
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(root, name))
                    except Exception:
                        pass
    except Exception as e:
        log_error(f'Cache clear error: {e}')
    
    xbmc.log(f'[Netzkino] Cache geleert ({removed} Elemente).', xbmc.LOGINFO)
    
    xbmcgui.Dialog().notification('Netzkino', f'Cache geleert ({removed} Elemente)', xbmcgui.NOTIFICATION_INFO, 3000, False)
    return True

def load(url='', params=None):
    return [
        {
            'title': 'Suche',
            'url': '',
            'plot': 'Durchsucht Netzkino nach Filmen und Serien.',
            'is_playable': False,
            'next_func': 'search',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Alle Filme A - Z',
            'url': 'alle-filme',
            'plot': 'Alphabetische Gesamtübersicht aller verfügbaren Filme. Beim ersten Start werden alle verfügbaren Filme gelistet und im Cache für 7 Tage gespeichert. Dieser Vorgang kann etwas länger dauern.',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Nach Produktionsjahr',
            'url': 'years_overview',
            'plot': 'Filme chronologisch nach Produktionsjahr durchsuchen (neueste zuerst).',
            'is_playable': False,
            'next_func': 'showYears',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Serien',
            'url': 'serien',
            'plot': 'Übersicht aller verfügbaren Serien auf Netzkino.',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Genres',
            'url': '',
            'plot': 'Filme nach verschiedenen Genres und Kategorien filtern.',
            'is_playable': False,
            'next_func': 'showGenres',
            'poster': _ICON,
            'icon': _ICON
        },
        {
            'title': 'Cache leeren',
            'url': '',
            'plot': 'Löscht den lokalen Cache für Kategorien und Filmdetails.',
            'is_playable': False,
            'next_func': 'clear_cache',
            'poster': _ICON,
            'icon': _ICON
        },
    ]


def _parse_url_offset(url):
    url = str(url or '')
    if '|' in url:
        parts = url.rsplit('|', 1)
        try:
            return parts[0], int(parts[1])
        except (ValueError, IndexError):
            return url, 0
    return url, 0
    

def showEntries(url='', params=None):
    if not url:
        return []

    base_url, offset = _parse_url_offset(url)
    slug = str(base_url).rstrip('/').rsplit('/', 1)[-1]

    if slug == 'alle-filme':
        all_items = _get_all_movies_cached()
    else:
        sub_items = _next_data_category_items(base_url)
        if sub_items and any(not x.get('is_playable') and x.get('next_func') == 'showEntries' for x in sub_items):
            return sub_items

        all_items = _gql_category_all(slug)
        if not all_items:
            all_items = _next_data_category_items(base_url)

    total = len(all_items)
    page = all_items[offset:offset + _PAGE_SIZE]
    enriched_page = _enrich_items(page)

    if offset + _PAGE_SIZE < total:
        remaining = total - offset - _PAGE_SIZE
        enriched_page.append({
            'title': f'Weiter  ({remaining} weitere)',
            'url': f'{base_url}|{offset + _PAGE_SIZE}',
            'plot': f'Seite {offset // _PAGE_SIZE + 2} laden ({remaining} weitere Einträge).',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON,
        })

    return enriched_page
    

def showEntriesByYear(url='neu-frontpage', params=None):
    if not url:
        url = 'neu-frontpage'
    slug = str(url).rstrip('/').rsplit('/', 1)[-1]
    items = _gql_category_all(slug)
    if not items:
        items = _next_data_category_items(url)
    enriched = _enrich_items(items)
    return _sort_year(enriched)

def showSeasons(url='', params=None):
    if not url:
        return []
    data = _gql('MovieDetails', _HASH_DETAILS, {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
    if not isinstance(data, dict):
        return []
    series = data.get('series') or data.get('contentSeries') or {}
    seasons_obj = series.get('seasons') or {} if isinstance(series, dict) else {}
    seasons = seasons_obj.get('nodes') or [] if isinstance(seasons_obj, dict) else []
    if not seasons:
        return []

    poster = _img(series, 'coverImage', 'widescreenImage') or _ICON
    fanart = _img(series, 'widescreenImage', 'headerImage24By9')
    items = []

    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_num = season.get('seasonInSeries') or 1
        first_episode = season.get('firstEpisode') or {}
        first_nodes = first_episode.get('nodes') or [] if isinstance(first_episode, dict) else []
        if not first_nodes or not isinstance(first_nodes[0], dict):
            continue
        first_ep_id = first_nodes[0].get('id')
        if not first_ep_id:
            continue

        season_id = season.get('id') or ''
        year = season.get('productionYear') or series.get('productionYear')
        s_poster = _img(season, 'coverImage', 'widescreenImage') or poster
        items.append({
            'title': f'Staffel {season_num}',
            'url': f'{season_id}|{first_ep_id}|{season_num}',
            'poster': s_poster,
            'icon': s_poster,
            'fanart': _img(season, 'widescreenImage') or fanart,
            'year': str(year) if year else '',
            'mediatype': 'season',
            'season': season_num,
            'is_playable': False,
            'next_func': 'showEpisodes',
        })
    return items

def showEpisodes(url='', params=None):
    if not url or '|' not in url:
        return []
    parts = str(url).split('|')
    season_id = parts[0] if len(parts) > 0 else ''
    ep_id = parts[1] if len(parts) > 1 else ''
    try:
        season_num = int(parts[2]) if len(parts) > 2 else 1
    except Exception:
        season_num = 1

    items, seen, ep_num = [], set(), 1
    while ep_id and ep_id not in seen:
        seen.add(ep_id)
        data = _gql('VideoData', _HASH_VIDEO, {'contentId': ep_id, 'externalId': ep_id, 'checkSpecialCategory': False, 'specialCategorySlug': ''})
        if not isinstance(data, dict):
            break
        ep = data.get('episodeData') or data.get('episode')
        if not isinstance(ep, dict):
            break
        season_obj = ep.get('season') or {}
        if isinstance(season_obj, dict) and season_obj.get('id') and season_obj.get('id') != season_id:
            break

        year = ep.get('productionYear') or (season_obj.get('productionYear') if isinstance(season_obj, dict) else None)
        poster = _img(ep, 'coverImage') or _ICON
        items.append({
            'title': str(ep.get('title') or f'Episode {ep_num}'),
            'url': str(ep.get('id') or ep_id),
            'poster': poster,
            'icon': poster,
            'year': str(year) if year else '',
            'mediatype': 'episode',
            'season': season_num,
            'episode': ep.get('episodeInSeason') or ep_num,
            'is_playable': True,
            'next_func': 'get_hosters',
        })
        ep_num += 1
        next_episode = ep.get('nextEpisodeId') or ''
        if next_episode == ep_id:
            break
        ep_id = next_episode
    return _enrich_items(items)

def _pmd_and_year_from_page(content_id):
    if not content_id:
        return None, None
    try:
        r = _get(_URL_DETAIL % str(content_id), timeout=15)
        if not r:
            return None, None
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if not match:
            return None, None
        data = json.loads(match.group(1))
        queries = data.get('props', {}).get('__dehydratedState', {}).get('queries', [])
        state = {}
        for query in queries:
            if isinstance(query, dict) and query.get('queryKey') and query['queryKey'][0] == 'MovieDetails':
                state = query.get('state') or {}
                break
        state_data = state.get('data') or {}
        inner_data = state_data.get('data') if isinstance(state_data, dict) else {}
        content = inner_data.get('movie') or inner_data.get('series') or {} if isinstance(inner_data, dict) else {}
        video_source = content.get('videoSource') or {} if isinstance(content, dict) else {}
        return video_source.get('pmdUrl'), str(content.get('productionYear')) if content.get('productionYear') else None
    except Exception as e:
        log_error(str(e))
        return None, None

def _pmd_from_page(content_id):
    pmd, _ = _pmd_and_year_from_page(content_id)
    return pmd

def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        pmd = ''
        
        data = _gql(
            'VideoData', 
            _HASH_VIDEO, 
            {
                'contentId': url, 
                'externalId': url, 
                'checkSpecialCategory': False, 
                'specialCategorySlug': ''
            }
        )
        
        if isinstance(data, dict):
            ep = (
                data.get('episodeData') 
                or data.get('episode') 
                or (data.get('videoData') or {}).get('episodeData')
                or {}
            )
            if isinstance(ep, dict):
                video_source = ep.get('videoSource') or {}
                if isinstance(video_source, dict):
                    pmd = video_source.get('pmdUrl') or ''
                    
        if not pmd:
            data = _gql(
                'MovieDetails', 
                _HASH_DETAILS, 
                {
                    'movieId': url, 
                    'externalId': url, 
                    'slug': url, 
                    'potentialMovieId': url
                }
            )
            
            if isinstance(data, dict):
                movie = data.get('movie') or data.get('contentMovie') or {}
                if isinstance(movie, dict):
                    video_source = movie.get('videoSource') or {}
                    if isinstance(video_source, dict):
                        pmd = video_source.get('pmdUrl') or ''
                        
        if not pmd:
            pmd = _pmd_from_page(url) or ''

        if pmd:
            pmd_str = str(pmd)
            stream_url = pmd_str if pmd_str.startswith('http') else (_URL_STREAM + urllib.parse.quote(pmd_str, safe='/'))
            return [('Netzkino', stream_url, True, 'HD', 'de')]

        return []

    query = re.sub(r'\s*[\(\[\{].*', '', str(title or '')).strip()
    words = query.split()
    query = words[0].lower() if words else query.lower()
    
    if not query:
        return []

    year_s = str(year or '')
    data = _gql('Search', _HASH_SEARCH, {'text': query})
    
    if not isinstance(data, dict):
        return []
        
    search_data = data.get('search') or {}
    if not isinstance(search_data, dict):
        return []
        
    nodes = search_data.get('nodes') or []

    for node in nodes:
        if not isinstance(node, dict):
            continue
            
        content_id = node.get('id') or node.get('slug')
        if not content_id:
            continue
            
        pmd, page_year = _pmd_and_year_from_page(content_id)
        if not pmd:
            continue
            
        if year_s and page_year and page_year != year_s:
            continue
            
        pmd_str = str(pmd)
        stream_url = pmd_str if pmd_str.startswith('http') else (_URL_STREAM + urllib.parse.quote(pmd_str, safe='/'))
        return [('Netzkino', stream_url, True, 'HD', 'de')]

    return []

def search(query='', params=None, url=''):
    if isinstance(params, str):
        try:
            p_dict = json.loads(params)
        except Exception:
            p_dict = {}
    elif isinstance(params, dict):
        p_dict = params
    else:
        p_dict = {}

    if not query:
        if isinstance(url, str) and url and url.lower() not in ['search', 'suche', 'search_form']:
            query = url
        else:
            query = p_dict.get('query') or p_dict.get('keyword') or p_dict.get('search') or ''

    if not query:
        try:
            dialog = xbmcgui.Dialog()
            result = dialog.input('Netzkino Suche')
            if result:
                query = result.strip()
        except Exception as e:
            log_error(f"Tastatur Fehler: {e}")

    if not query:
        return []

    data = _gql('Search', _HASH_SEARCH, {'text': query})
    if not isinstance(data, dict):
        return []
    search_data = data.get('search') or {}
    nodes = search_data.get('nodes') or [] if isinstance(search_data, dict) else []
    if not nodes:
        xbmcgui.Dialog().notification('Netzkino', 'Keine Treffer zur Suche gefunden.', xbmcgui.NOTIFICATION_INFO, 3000, False)
        return []

    ids = []
    for node in nodes:
        if isinstance(node, dict):
            content_id = node.get('id') or node.get('slug')
            if content_id and content_id not in ids:
                ids.append(content_id)

    def _fetch_item(content_id):
        try:
            data = _gql('MovieDetails', _HASH_DETAILS, {'movieId': content_id, 'externalId': content_id, 'slug': content_id, 'potentialMovieId': content_id})
            if isinstance(data, dict):
                item = _node_to_item(data)
                if item:
                    return item
                movie, series = data.get('movie'), data.get('series')
                if movie:
                    item = _node_to_item({'contentMovie': movie})
                    if item:
                        return item
                if series:
                    item = _node_to_item({'contentSeries': series})
                    if item:
                        return item

            pmd, page_year = _pmd_and_year_from_page(content_id)
            if pmd:
                return {
                    'title': str(content_id),
                    'url': str(content_id),
                    'poster': _ICON,
                    'icon': _ICON,
                    'fanart': '',
                    'year': str(page_year) if page_year else '',
                    'mediatype': 'movie',
                    'is_playable': True,
                    'next_func': 'get_hosters',
                }
        except Exception as e:
            log_error(str(e))
        return None

    items = []
    p_dialog = xbmcgui.DialogProgressBG()
    p_dialog.create('Netzkino', f'Suche nach "{query}"...')
    total = len(ids)
    completed = 0

    try:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_item, content_id): content_id for content_id in ids}
            for future in as_completed(futures):
                try:
                    item = future.result(timeout=15)
                    if item:
                        items.append(item)
                except Exception as e:
                    log_error(str(e))
                completed += 1
                percent = int((completed / total) * 100) if total else 0
                p_dialog.update(percent, f'Suche: {completed}/{total} verarbeitet...')
    finally:
        p_dialog.close()

    if not items:
        xbmcgui.Dialog().notification('Netzkino', 'Keine passenden Streams gefunden.', xbmcgui.NOTIFICATION_INFO, 3000, False)

    items.sort(key=lambda x: str(x.get('title', '')).casefold())
    return items
