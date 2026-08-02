# -*- coding: utf-8 -*-
import json
from urllib.parse import urlparse, quote
from resources.lib import multiquest, log

SITE_ID       = 'einschalten'
SITE_NAME     = 'Einschalten'
SITE_DOMAIN   = 'einschalten.in'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def _base():
    return 'https://' + SITE_DOMAIN


def _api(path):
    return _base() + '/api' + path


def _get(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return {}


def _post(url, payload):
    try:
        r = multiquest.post(url, json=payload, headers={'User-Agent': _UA}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return {}


def _parse_quality(release_name):
    rn = release_name or ''
    if '2160' in rn or '4K' in rn:    return '4K'
    elif '1440' in rn or '2K' in rn:  return '1440p'
    elif '1080' in rn:                 return '1080p'
    elif '720' in rn:                  return '720p'
    elif '480' in rn:                  return '480p'
    elif '360' in rn:                  return '360p'
    return 'SD'


def _movie_to_item(m):
    year = (m.get('releaseDate') or '')[:4]
    return {
        'title':       m.get('title', ''),
        'url':         str(m.get('id', '')),
        'poster':      _base() + '/api/image/poster' + m.get('posterPath', ''),
        'year':        year,
        'rating':      m.get('voteAverage', 0),
        'mediatype':   'movie',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _collection_to_item(c):
    return {
        'title':       c.get('name', ''),
        'url':         str(c.get('id', '')),
        'poster':      _base() + '/api/image/poster' + c.get('posterPath', ''),
        'plot':        c.get('overview', ''),
        'mediatype':   'movie',
        'is_playable': False,
        'next_func':   'showCollectionEntries',
    }


def _add_next(items, next_func, url, page):
    items.append({
        'title':       '[B]>>> Weiter (Seite %d)[/B]' % (page + 1),
        'url':         url,
        'next_func':   next_func,
        'is_playable': False,
    })


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Aktuelle Releases', 'url': 'order=new',   'is_playable': False, 'next_func': 'showEntries'},
            {'title': 'Neu hinzugefügt',   'url': 'order=added', 'is_playable': False, 'next_func': 'showEntries'},
            {'title': 'Genres',            'url': '',             'is_playable': False, 'next_func': 'showGenres'},
            {'title': 'Collections',       'url': '',             'is_playable': False, 'next_func': 'showCollections'},
        ]
    return showEntries(url=url, params=params)


def showEntries(url='', params=None):
    params     = params or {}
    page       = int(params.get('page', 0))
    api_params = dict(p.split('=', 1) for p in url.split('&') if '=' in p)
    api_params['pageNumber'] = page
    data       = _get(_api('/movies') + '?' + '&'.join('%s=%s' % (k, v) for k, v in api_params.items()))
    items      = [_movie_to_item(m) for m in data.get('data', [])]
    if not items:
        return []
    if data.get('pagination', {}).get('hasMore', False):
        _add_next(items, 'showEntries', url, page)
    return items


def showGenres(url='', params=None):
    genres = _get(_api('/genres'))
    if not isinstance(genres, list):
        return []
    return [
        {'title': g['name'], 'url': 'genre=%d' % g['id'], 'is_playable': False, 'next_func': 'showEntries'}
        for g in genres
    ]


def showCollections(url='', params=None):
    params = params or {}
    page   = int(params.get('page', 0))
    data   = _get(_api('/collections') + '?pageNumber=%d' % page)
    items  = [_collection_to_item(c) for c in data.get('data', [])]
    if not items:
        return []
    if data.get('pagination', {}).get('hasMore', False):
        _add_next(items, 'showCollections', url, page)
    return items


def showCollectionEntries(url='', params=None):
    data   = _get(_api('/collections/%s' % url))
    movies = data.get('movies', [])
    if not movies:
        data2 = _get(_api('/movies') + '?collectionId=%s' % url)
        return [_movie_to_item(m) for m in data2.get('data', [])]
    return [_movie_to_item(m) for m in movies]


def _find_movie_id(title, year):
    data = _post(_api('/search'), {'query': title, 'pageNumber': 0})
    results = data.get('data', [])
    if not results:
        return ''
    year = str(year or '')
    for m in results:
        if year and str((m.get('releaseDate') or '')[:4]) != year:
            continue
        return str(m.get('id', ''))
    return str(results[0].get('id', ''))


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if not url:
        url = _find_movie_id(title, year)
    if not url:
        log.log('[einschalten] get_hosters: kein Film gefunden fuer "%s" (%s)' % (title, year))
        return []
    data   = _get(_api('/movies/%s/watch' % url))
    stream = data.get('streamUrl', '')
    if not stream:
        log.log('[einschalten] get_hosters: kein streamUrl für id=%s' % url)
        return []
    quality = _parse_quality(data.get('releaseName', ''))
    try:
        hoster = urlparse(stream).netloc.replace('www.', '')
    except Exception:
        log.error()
        hoster = SITE_NAME
    return [(hoster, stream, False, quality, 'de')]


def get_details(url='', params=None):
    if not url:
        return {}
    data = _get(_api('/movies/%s' % url))
    if not data:
        return {}
    return {
        'plot':   data.get('overview', ''),
        'rating': data.get('voteAverage', 0),
    }


def search(query='', params=None):
    data = _post(_api('/search'), {'query': query, 'pageNumber': 0})
    return [_movie_to_item(m) for m in data.get('data', [])]
