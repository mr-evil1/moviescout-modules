# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote, urlparse
from resources.lib import multiquest, log

SITE_ID       = 'movie2k'
SITE_NAME     = 'Movie2k'
SITE_DOMAIN   = 'movie2k.ch'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_S_MOVIES  = '__m2k_movies__'
_S_SERIES  = '__m2k_series__'
_S_GENRES  = '__m2k_genres__'
_S_BROWSE  = '__m2k_browse__:'
_S_SEASONS = '__m2k_seasons__:'
_S_EPS     = '__m2k_eps__:'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA, 'Referer': referer or _base() + '/'}
    try:
        r = multiquest.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _get_json(url, referer=None):
    headers = {
        'User-Agent': _UA,
        'Referer': referer or _base() + '/',
        'Accept': 'application/json, text/plain, */*',
        'Origin': _base(),
    }
    try:
        r = multiquest.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return None


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(text):
    t = (text or '').upper()
    if '2160' in t or '4K' in t: return '4K'
    if '1080' in t: return '1080p'
    if '720' in t: return '720p'
    if '480' in t: return '480p'
    return 'HD'


def _poster(path):
    if not path: return ''
    if path.startswith('http'): return path
    return 'https://image.tmdb.org/t/p/w300' + path


def _is_series(title):
    return bool(re.search(r'\b(Staffel|Season)\s*\d+', title or '', re.I))


def _item_from_api(movie, is_series=False):
    _id    = str(movie.get('_id', ''))
    title  = movie.get('title', '')
    year   = str(movie.get('year', ''))
    poster = _poster(movie.get('poster_path_season') or movie.get('poster_path') or movie.get('backdrop_path', ''))
    plot   = movie.get('storyline') or movie.get('overview', '')
    try:
        rating = float(movie.get('rating', 0))
    except Exception:
        rating = 0.0
    if is_series:
        return {
            'title':       title,
            'url':         _S_EPS + _id,
            'poster':      poster,
            'year':        year,
            'plot':        plot,
            'rating':      rating,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        }
    return {
        'title':       title,
        'url':         _id,
        'poster':      poster,
        'year':        year,
        'plot':        plot,
        'rating':      rating,
        'mediatype':   'movie',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _browse_api(params, page=1):
    if '|page=' in params:
        params, pg_str = params.rsplit('|page=', 1)
        page = int(pg_str)
    is_series = 'tvseries' in params or 'type=tv' in params
    url  = _base() + '/data/browse/?' + params + '&page=%d&limit=20' % page
    data = _get_json(url)
    if not data:
        return []
    items = []
    for m in data.get('movies', []):
        # Serien erkennen: entweder browse-Typ oder Title enthält 'Staffel/Season'
        serie = is_series or _is_series(m.get('title', ''))
        items.append(_item_from_api(m, serie))
    pager = data.get('pager', {})
    if page < int(pager.get('totalPages', page)):
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         _S_BROWSE + params + '|page=%d' % (page + 1),
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _get_episodes(_id):
    # Lädt Episoden direkt aus /data/watch/ – keine separate Seasons-API
    data = _get_json(_base() + '/data/watch/?_id=' + _id)
    if not data:
        return []
    poster = _poster(data.get('poster_path_season') or data.get('poster_path', ''))
    plot   = data.get('storyline') or data.get('overview', '')
    s_num  = data.get('s', 1)
    # Nur Streams MIT 'e'-Feld (Episoden), gelöschte ausschließen
    streams = [s for s in data.get('streams', []) if not s.get('deleted') and 'e' in s]
    ep_nums = sorted(set(int(s['e']) for s in streams))
    items = []
    for ep in ep_nums:
        ep_title = next(
            (s.get('e_title', '') for s in streams if int(s.get('e', -1)) == ep and s.get('e_title')),
            ''
        )
        label = 'S%02dE%02d' % (s_num, ep)
        if ep_title: label += ' - ' + ep_title
        item = {
            'title':       label,
            'url':         _id,
            'poster':      poster,
            'mediatype':   'episode',
            'is_playable': True,
            'next_func':   'get_hosters',
            'season':      s_num,
            'episode':     ep,
        }
        if plot: item['plot'] = plot
        items.append(item)
    return items


def _movies_menu():
    orders = [
        ('Featured',         'featured'),
        ('Neuerscheinungen', 'releases'),
        ('Trending',         'trending'),
        ('Updates',          'updates'),
        ('Requested',        'requested'),
        ('Top bewertet',     'rating'),
        ('Meiste Votes',     'votes'),
        ('Meiste Views',     'views'),
    ]
    return [{'title': l, 'url': _S_BROWSE + 'lang=2&type=movies&order_by=' + o,
             'next_func': 'load', 'is_playable': False} for l, o in orders]


def _series_menu():
    orders = [
        ('Neuerscheinungen', 'releases'),
        ('Trending',         'trending'),
        ('Updates',          'updates'),
        ('Requested',        'requested'),
        ('Top bewertet',     'rating'),
        ('Meiste Votes',     'votes'),
        ('Meiste Views',     'views'),
    ]
    return [{'title': l, 'url': _S_BROWSE + 'lang=2&type=tvseries&order_by=' + o,
             'next_func': 'load', 'is_playable': False} for l, o in orders]


def _genres_menu():
    genres = [
        'Action', 'Abenteuer', 'Animation', 'Biographie', 'Dokumentation',
        'Drama', 'Familie', 'Fantasy', 'Horror', 'Komödie',
        'Krimi', 'Mystery', 'Romantik', 'Sci-Fi', 'Thriller',
    ]
    return [{'title': g, 'url': _S_BROWSE + 'lang=2&type=movies&genres=%s&order_by=new' % quote(g),
             'next_func': 'load', 'is_playable': False} for g in genres]


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Filme',  'url': _S_MOVIES, 'next_func': 'load', 'is_playable': False},
            {'title': 'Serien', 'url': _S_SERIES, 'next_func': 'load', 'is_playable': False},
            {'title': 'Genre',  'url': _S_GENRES, 'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_MOVIES:  return _movies_menu()
    if url == _S_SERIES:  return _series_menu()
    if url == _S_GENRES:  return _genres_menu()
    if url.startswith(_S_BROWSE):  return _browse_api(url[len(_S_BROWSE):])
    if url.startswith(_S_SEASONS): return _get_episodes(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):     return _get_episodes(url[len(_S_EPS):])
    return []


def _find_id(title, year, season):
    clean    = _cleantitle(title)
    stype    = 'tvseries' if season else 'movies'
    data = _get_json(
        _base() + '/data/browse/?lang=2&type=%s&order_by=new&page=1&keyword=%s'
        % (stype, quote(title))
    )
    if not data:
        return ''
    for m in data.get('movies', []):
        raw_title = m.get('title', '')
        # Staffel-/Season-Suffix entfernen für Titelvergleich
        mt = re.sub(r'\s*[-–]\s*(Staffel|Season)\s*\d+.*$', '', raw_title, flags=re.I).strip()
        if _cleantitle(mt) != clean:
            continue
        if season:
            # Staffel-Nummer aus API-Titel oder 's'-Feld lesen
            sn = m.get('s', 0)
            if not sn:
                sm = re.search(r'(?:Staffel|Season)\s*(\d+)', raw_title, re.I)
                sn = int(sm.group(1)) if sm else 0
            if int(sn) != int(season):
                continue
        else:
            try:
                if year and int(m.get('year', 0)) and abs(int(m['year']) - int(year)) > 1:
                    continue
            except Exception:
                pass
        return str(m['_id'])
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season_i  = int(season  or 0)
    episode_i = int(episode or 0)

    _id = url if (url and not url.startswith('__')) else ''
    if not _id and title:
        _id = _find_id(title, year, season_i)
    if not _id:
        return []

    data = _get_json(_base() + '/data/watch/?_id=' + _id)
    if not data:
        return []

    streams = [s for s in data.get('streams', []) if not s.get('deleted')]

    if season_i and episode_i:
        # Episoden-Streams: nur passende Episode
        streams = [s for s in streams if 'e' in s and int(s.get('e', -1)) == episode_i]
    else:
        # Film-Streams: nur Streams OHNE Episode-Feld
        streams = [s for s in streams if 'e' not in s]

    result = []
    seen   = set()
    for s in streams:
        raw_url = s.get('stream', '')
        if not raw_url or 'youtube' in raw_url.lower():
            continue
        if raw_url.startswith('//'): raw_url = 'https:' + raw_url
        hostname = urlparse(raw_url).hostname or ''
        if hostname in seen: continue
        seen.add(hostname)
        hoster  = '.'.join(hostname.split('.')[-2:]) if hostname else SITE_NAME
        quality = _quality(s.get('release', ''))
        result.append((hoster, raw_url, False, quality, 'de'))
    return result


def search(query='', params=None):
    data = _get_json(_base() + '/data/browse/?lang=2&order_by=new&page=1&keyword=' + quote(query))
    if not data:
        return []
    items = []
    for m in data.get('movies', []):
        serie = _is_series(m.get('title', ''))
        items.append(_item_from_api(m, serie))
    return items


def get_details(url='', params=None):
    if not url or url.startswith('__'):
        return {}
    _id = url
    for prefix in (_S_SEASONS, _S_EPS):
        if url.startswith(prefix):
            _id = url[len(prefix):]
            break
    data = _get_json(_base() + '/data/watch/?_id=' + _id)
    if not data:
        return {}
    result = {}
    plot = data.get('storyline') or data.get('overview', '')
    if plot:   result['plot']   = plot
    if data.get('year'):   result['year']   = str(data['year'])
    if data.get('rating'): result['rating'] = float(data['rating'])
    poster = _poster(data.get('poster_path') or data.get('poster_path_season', ''))
    if poster: result['poster'] = poster
    return result
