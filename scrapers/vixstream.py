# -*- coding: utf-8 -*-
import re
import base64
from urllib.parse import quote, urlparse
from resources.lib import multiquest, log
from resources.lib.control import getSetting

SITE_ID       = 'vixstream'
SITE_NAME     = 'Vixstream'
SITE_DOMAIN   = 'vixsrc.to'
TYPE          = 'both'
GLOBAL_SEARCH = True

_TMDB_IMG  = 'https://image.tmdb.org/t/p/w500'
_TMDB_BASE = 'https://api.themoviedb.org/3'
_TMDB_KEY  = getSetting('api.tmdb') or base64.b64decode('ZWRkZTZiNWU0MTI0NmFiNzlhMjY5N2NkMTI1ZTE3ODE=').decode()

_S_MOVIES  = '__vix_movies__'
_S_SERIES  = '__vix_series__'
_S_GENRES  = '__vix_genres__'
_S_BROWSE  = '__vix_browse__:'
_S_SEASONS = '__vix_seasons__:'
_S_EPS     = '__vix_eps__:'


def _base():
    return 'https://' + SITE_DOMAIN


def _tmdb(path, params=None):
    p = {'api_key': _TMDB_KEY, 'language': 'de-DE'}
    if params:
        p.update(params)
    try:
        r = multiquest.get(_TMDB_BASE + path, params=p, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return None


def _vix_session():
    return multiquest.Session(use_cf=True)


def _vix_get(session, path, referer=None):
    url = path if path.startswith('http') else _base() + path
    try:
        r = session.get(url, headers={
            'Referer': referer or _base() + '/',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        }, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _vix_api(session, path, referer):
    url = path if path.startswith('http') else _base() + path
    try:
        r = session.get(url, headers={
            'Referer': referer,
            'Accept': 'application/json, */*',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': _base(),
        }, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return None


def _poster(path):
    if not path: return ''
    if path.startswith('http'): return path
    return _TMDB_IMG + path


def _quality(text):
    t = (text or '').upper()
    if '2160' in t or '4K' in t: return '4K'
    if '1080' in t: return '1080p'
    if '720' in t:  return '720p'
    if '480' in t:  return '480p'
    return 'HD'


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _item_from_tmdb(m, is_series=False):
    _id    = str(m.get('id', ''))
    title  = m.get('title') or m.get('name', '')
    poster = _poster(m.get('poster_path', ''))
    year   = (m.get('release_date') or m.get('first_air_date', ''))[:4]
    plot   = m.get('overview', '')
    try:    rating = float(m.get('vote_average', 0))
    except: rating = 0.0
    if is_series:
        return {
            'title': title, 'url': _S_SEASONS + _id, 'poster': poster,
            'year': year, 'plot': plot, 'rating': rating,
            'mediatype': 'tvshow', 'is_playable': False, 'next_func': 'load',
        }
    return {
        'title': title, 'url': _id, 'poster': poster,
        'year': year, 'plot': plot, 'rating': rating,
        'mediatype': 'movie', 'is_playable': True, 'next_func': 'get_hosters',
    }


def _tmdb_browse(params_str):
    page = 1
    if '|page=' in params_str:
        params_str, pg = params_str.rsplit('|page=', 1)
        page = int(pg)
    is_series = 'tv' in params_str
    media     = 'tv' if is_series else 'movie'

    extra = {}
    for part in params_str.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            extra[k] = v

    data = _tmdb('/discover/%s' % media, {**extra, 'page': page})
    if not data:
        return []
    items = [_item_from_tmdb(m, is_series) for m in data.get('results', [])]
    if page < int(data.get('total_pages', page)):
        items.append({
            'title': '[B]>>> Weiter[/B]',
            'url':   _S_BROWSE + params_str + '|page=%d' % (page + 1),
            'next_func': 'load', 'is_playable': False,
        })
    return items


def _get_seasons(tmdb_id):
    data = _tmdb('/tv/%s' % tmdb_id)
    if not data:
        return []
    poster = _poster(data.get('poster_path', ''))
    plot   = data.get('overview', '')
    items  = []
    for s in data.get('seasons', []):
        s_num = s.get('season_number', 0)
        if s_num == 0: continue
        s_poster = _poster(s.get('poster_path') or '') or poster
        item = {
            'title': 'Staffel %d' % s_num,
            'url':   _S_EPS + '%s|%d' % (tmdb_id, s_num),
            'poster': s_poster, 'mediatype': 'season',
            'is_playable': False, 'next_func': 'load',
        }
        if plot: item['plot'] = plot
        items.append(item)
    return items


def _get_episodes(encoded):
    tmdb_id, season = encoded.rsplit('|', 1)
    data = _tmdb('/tv/%s/season/%s' % (tmdb_id, season))
    if not data:
        return []
    poster = _poster(data.get('poster_path', ''))
    items  = []
    for ep in data.get('episodes', []):
        ep_num   = ep.get('episode_number', 0)
        ep_title = ep.get('name', '') or ('Episode %d' % ep_num)
        ep_still = _poster(ep.get('still_path', '')) or poster
        items.append({
            'title':   'S%02dE%02d – %s' % (int(season), ep_num, ep_title),
            'url':     '%s|s%s|e%d' % (tmdb_id, season, ep_num),
            'poster':  ep_still, 'plot': ep.get('overview', ''),
            'mediatype': 'episode', 'is_playable': True, 'next_func': 'get_hosters',
            'season': int(season), 'episode': ep_num,
        })
    return items


def _resolve(tmdb_id, season=0, episode=0):
    is_series = season > 0
    if is_series:
        page_url = '/tv/%s' % tmdb_id
        api_path = '/api/tv/%s/%d/%d' % (tmdb_id, season, episode)
    else:
        page_url = '/movie/%s' % tmdb_id
        api_path = '/api/movie/%s' % tmdb_id

    with _vix_session() as sess:
        _vix_get(sess, page_url)

        data = _vix_api(sess, api_path, _base() + page_url)
        if not data:
            log.log('[vixstream] _resolve: keine API-Antwort fuer %s' % api_path)
            return []
        src = data.get('src', '')
        if not src:
            log.log('[vixstream] _resolve: kein src in API-Antwort: %s' % str(data)[:200])
            return []

        log.log('[vixstream] _resolve: src=%s' % src)

        result = []
        for lang in ('de', 'en'):
            if '?' in src:
                embed_path = src + '&lang=' + lang
            else:
                embed_path = src + '?lang=' + lang

            embed_html = _vix_get(sess, embed_path, _base() + page_url)
            if not embed_html:
                log.log('[vixstream] _resolve: kein embed_html fuer lang=%s path=%s' % (lang, embed_path))
                continue

            full_embed = embed_path if embed_path.startswith('http') else _base() + embed_path
            video_id_m = re.search(r'/embed/([^/?&#]+)', full_embed)
            if not video_id_m:
                log.log('[vixstream] _resolve: video_id nicht gefunden in %s' % full_embed)
                continue
            video_id = video_id_m.group(1)

            token = ''
            for pat in (
                r'["\']token["\']\s*:\s*["\']([a-f0-9A-F\-]{16,})["\']',
                r'token["\']?\s*:\s*["\']([a-f0-9A-F\-]{16,})["\']',
                r'const\s+token\s*=\s*["\']([a-f0-9A-F\-]{16,})["\']',
            ):
                m = re.search(pat, embed_html)
                if m:
                    token = m.group(1)
                    break

            expires = ''
            for pat in (
                r'["\']expires["\']\s*:\s*["\']?(\d{10})["\']?',
                r'expires["\']?\s*:\s*["\']?(\d{10})',
            ):
                m = re.search(pat, embed_html)
                if m:
                    expires = m.group(1)
                    break

            if not token or not expires:
                log.log('[vixstream] _resolve: token=%r expires=%r – uebersprungen (lang=%s)' % (token, expires, lang))
                continue

            playlist_url = '%s/playlist/%s?token=%s&expires=%s&h=1&lang=%s' % (
                _base(), video_id, token, expires, lang
            )
            from urllib.parse import urlencode
            final = '%s|%s' % (playlist_url, urlencode({
                'User-Agent':  multiquest._DEFAULT_UA,
                'Referer':     '%s/embed/%s' % (_base(), video_id),
                'Origin':      _base(),
            }))
            label = 'Deutsch' if lang == 'de' else 'Englisch'
            result.append(('VixCloud (%s)' % label, final, True, '1080p', lang))

    return result


def _movies_menu():
    return [
        {'title': 'Beliebt',        'url': _S_BROWSE + 'sort_by=popularity.desc',                          'next_func': 'load', 'is_playable': False},
        {'title': 'Top bewertet',   'url': _S_BROWSE + 'sort_by=vote_average.desc&vote_count.gte=200',     'next_func': 'load', 'is_playable': False},
        {'title': 'Meistgesehen',   'url': _S_BROWSE + 'sort_by=vote_count.desc',                          'next_func': 'load', 'is_playable': False},
        {'title': 'Jetzt im Kino',  'url': _S_BROWSE + 'sort_by=primary_release_date.desc&with_release_type=3', 'next_func': 'load', 'is_playable': False},
    ]


def _series_menu():
    return [
        {'title': 'Beliebt',        'url': _S_BROWSE + 'type=tv&sort_by=popularity.desc',                      'next_func': 'load', 'is_playable': False},
        {'title': 'Top bewertet',   'url': _S_BROWSE + 'type=tv&sort_by=vote_average.desc&vote_count.gte=200', 'next_func': 'load', 'is_playable': False},
        {'title': 'Meistgesehen',   'url': _S_BROWSE + 'type=tv&sort_by=vote_count.desc',                      'next_func': 'load', 'is_playable': False},
    ]


_GENRES = [
    (28,'Action'),(12,'Abenteuer'),(16,'Animation'),(35,'Komödie'),
    (80,'Krimi'),(99,'Dokumentation'),(18,'Drama'),(10751,'Familie'),
    (14,'Fantasy'),(36,'Geschichte'),(27,'Horror'),(10402,'Musik'),
    (9648,'Mystery'),(10749,'Romantik'),(878,'Sci-Fi'),(53,'Thriller'),
    (10752,'Krieg'),(37,'Western'),
]


def _genres_menu():
    return [
        {'title': name, 'url': _S_BROWSE + 'with_genres=%d&sort_by=popularity.desc' % gid,
         'next_func': 'load', 'is_playable': False}
        for gid, name in _GENRES
    ]


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Filme',  'url': _S_MOVIES, 'next_func': 'load', 'is_playable': False},
            {'title': 'Serien', 'url': _S_SERIES, 'next_func': 'load', 'is_playable': False},
            {'title': 'Genre',  'url': _S_GENRES, 'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_MOVIES:           return _movies_menu()
    if url == _S_SERIES:           return _series_menu()
    if url == _S_GENRES:           return _genres_menu()
    if url.startswith(_S_BROWSE):  return _tmdb_browse(url[len(_S_BROWSE):])
    if url.startswith(_S_SEASONS): return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):     return _get_episodes(url[len(_S_EPS):])
    return []


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    _p        = params or {}
    season_i  = int(season  or _p.get('season',  0) or 0)
    episode_i = int(episode or _p.get('episode', 0) or 0)

    if url and '|s' in url and '|e' in url:
        tmdb_id, s_part, e_part = url.split('|')
        return _resolve(tmdb_id, season=int(s_part[1:]), episode=int(e_part[1:]))

    if url and not url.startswith('__'):
        return _resolve(url, season=season_i, episode=episode_i)

    if imdb:
        data = _tmdb('/find/%s' % imdb, {'external_source': 'imdb_id'})
        if data:
            results = data.get('movie_results') or data.get('tv_results') or []
            if results:
                tmdb_id = str(results[0].get('id', ''))
                return _resolve(tmdb_id, season=season_i, episode=episode_i)

    if title:
        media = 'tv' if season_i else 'movie'
        data  = _tmdb('/search/%s' % media, {'query': title})
        clean = _cleantitle(title)
        for r in (data.get('results', []) if data else []):
            rt = r.get('title') or r.get('name', '')
            if _cleantitle(rt) != clean: continue
            if year and not season_i:
                ry = (r.get('release_date') or r.get('first_air_date', ''))[:4]
                if ry and abs(int(ry) - int(year)) > 1: continue
            return _resolve(str(r.get('id', '')), season=season_i, episode=episode_i)

    return []


def search(query='', params=None):
    movies = []
    series = []
    data = _tmdb('/search/movie', {'query': query})
    if data:
        movies = [_item_from_tmdb(m, False) for m in data.get('results', [])]
    data = _tmdb('/search/tv', {'query': query})
    if data:
        series = [_item_from_tmdb(m, True) for m in data.get('results', [])]
    return movies + series
