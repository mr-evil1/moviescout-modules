# -*- coding: utf-8 -*-
import json
import urllib.parse
from resources.lib import multiquest, log

SITE_ID       = 'netzkino'
SITE_NAME     = 'Netzkino'
SITE_DOMAIN   = 'netzkino.de'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA         = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_GQL        = 'https://data.netzkino.de/netzkino/graphql'
_URL_SEARCH = 'https://api.netzkino.de.simplecache.net/capi-2.0a/search?q=%s&d=www&l=de-DE'
_URL_STREAM = 'https://pmd.netzkino-seite.netzkino.de/'

_HASH_CAT     = '225e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8'
_HASH_ALL     = '2251eb32b81108d564d20969692d53311885bc80b2d1a7041ce5cba1398923caa6'
_HASH_DETAILS = '22692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97'
_HASH_VIDEO   = '22ce2a04069f5ed18f6399df7070a2d27e209a7c530c77e4fb583ec898da02b1f1'
_HASH_SEARCH     = '22e7f141530416887b1faa663dbdd468534c6639e47886e8156686afd9a0f81d76'
_HASH_SEARCH_OLD = 'e7f141530416887b1faa663dbdd468534c6639e47886e8156686afd9a0f81d76'

_URL_DETAILS  = 'https://www.netzkino.de/details/%s'

_MAIN_CATS = [
    ('Neu',                     'neu-frontpage'),
    ('Highlights',              'highlights-frontpage'),
    ('Action',                  'actionfilme_frontpage'),
    ('Top bewertet',            'top-rated_frontpage'),
    ('Blockbuster & Kultfilme', 'blockbuster-kultfilme-frontpage'),
    ('Starkino',                'starkino'),
    ('Kriegsfilme',             'kriegsfilme-frontpage'),
    ('Dokumentationen',         'top-dokumentationen'),
    ('Zombiefilme',             'Zombiefilme-frontpage'),
    ('Western',                 'western-frontpage'),
    ('Historisches',            'historisches'),
    ('Serien',                  'serien'),
]


def _gql(op, hash_, variables, fallback_hash=None):
    ext = json.dumps({'persistedQuery': {'version': 1, 'sha256Hash': hash_}})
    var = json.dumps(variables)
    url = '%s?extensions=%s&variables=%s&operationName=%s' % (
        _GQL,
        urllib.parse.quote(ext),
        urllib.parse.quote(var),
        op,
    )
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA}, timeout=10)
        r.raise_for_status()
        body = r.json()
        errors = body.get('errors') or []
        if fallback_hash and any(e.get('message') == 'PersistedQueryNotFound' for e in errors):
            return _gql(op, fallback_hash, variables)
        return body.get('data') or {}
    except Exception:
        log.error()
        return {}


def _get_json(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return {}


def _img(node, *keys):
    for k in keys:
        img = node.get(k)
        if isinstance(img, dict) and img.get('masterUrl'):
            return img['masterUrl']
    return ''


def _node_to_item(node):
    movie = node.get('contentMovie')
    if movie:
        year = movie.get('productionYear')
        return {
            'title':       str(movie.get('title') or ''),
            'url':         str(movie.get('id') or ''),
            'poster':      _img(movie, 'coverImage', 'widescreenImage'),
            'fanart':      _img(movie, 'widescreenImage', 'headerImage24By9'),
            'year':        str(year) if year else '',
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        }
    series = node.get('contentSeries')
    if series:
        year = series.get('productionYear')
        return {
            'title':       str(series.get('title') or ''),
            'url':         str(series.get('slug') or series.get('id') or ''),
            'poster':      _img(series, 'coverImage', 'widescreenImage'),
            'fanart':      _img(series, 'widescreenImage', 'headerImage24By9'),
            'year':        str(year) if year else '',
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'showSeasons',
        }
    return None


def load(url='', params=None):
    items = [{'title': title, 'url': slug, 'is_playable': False, 'next_func': 'showEntries'}
             for title, slug in _MAIN_CATS]
    items.append({'title': 'Genres', 'url': '', 'is_playable': False, 'next_func': 'showGenres'})
    return items


def showGenres(url='', params=None):
    data  = _gql('AllContent', _HASH_ALL, {'parentSlug': 'netzkino-genre', 'featuredSlug': 'keinefeatured'})
    nodes = data.get('parentCategory', {}).get('subcategories', {}).get('nodes', [])
    return [
        {'title': str(n.get('title') or ''), 'url': str(n.get('slug') or ''),
         'is_playable': False, 'next_func': 'showEntries'}
        for n in nodes if n.get('slug') and n.get('title')
    ]


def showEntries(url='', params=None):
    if not url:
        return []
    data  = _gql('CategoryDataBySlug', _HASH_CAT, {'slug': url})
    nodes = data.get('category', {}).get('content', {}).get('nodes', [])
    items = []
    for node in nodes:
        item = _node_to_item(node)
        if item:
            items.append(item)
    return items


def showSeasons(url='', params=None):
    if not url:
        return []
    data    = _gql('MovieDetails', _HASH_DETAILS,
                   {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
    series  = data.get('series') or {}
    seasons = (series.get('seasons') or {}).get('nodes', [])
    if not seasons:
        return []
    poster = _img(series, 'coverImage', 'widescreenImage')
    fanart = _img(series, 'widescreenImage', 'headerImage24By9')
    items  = []
    for s in seasons:
        season_num  = s.get('seasonInSeries') or 1
        first_eps   = (s.get('firstEpisode') or {}).get('nodes', [])
        first_ep_id = first_eps[0]['id'] if first_eps else ''
        if not first_ep_id:
            continue
        season_id = s.get('id') or ''
        year      = s.get('productionYear') or series.get('productionYear')
        items.append({
            'title':       'Staffel %d' % season_num,
            'url':         '%s|%s|%d' % (season_id, first_ep_id, season_num),
            'poster':      _img(s, 'coverImage', 'widescreenImage') or poster,
            'fanart':      _img(s, 'widescreenImage') or fanart,
            'year':        str(year) if year else '',
            'mediatype':   'season',
            'season':      season_num,
            'is_playable': False,
            'next_func':   'showEpisodes',
        })
    return items


def showEpisodes(url='', params=None):
    if not url or '|' not in url:
        return []
    parts      = url.split('|')
    season_id  = parts[0]
    ep_id      = parts[1]
    season_num = int(parts[2]) if len(parts) > 2 else 1
    items = []
    seen  = set()
    ep_num = 1
    while ep_id and ep_id not in seen:
        seen.add(ep_id)
        data = _gql('VideoData', _HASH_VIDEO,
                    {'contentId': ep_id, 'externalId': ep_id,
                     'checkSpecialCategory': False, 'specialCategorySlug': ''})
        ep = data.get('episodeData')
        if not ep:
            break
        if (ep.get('season') or {}).get('id') != season_id:
            break
        year = ep.get('productionYear') or (ep.get('season') or {}).get('productionYear')
        items.append({
            'title':       str(ep.get('title') or ('Episode %d' % ep_num)),
            'url':         str(ep.get('id') or ep_id),
            'poster':      _img(ep, 'coverImage'),
            'year':        str(year) if year else '',
            'mediatype':   'episode',
            'season':      season_num,
            'episode':     ep.get('episodeInSeason') or ep_num,
            'is_playable': True,
            'next_func':   'get_hosters',
        })
        ep_num  += 1
        ep_id    = ep.get('nextEpisodeId') or ''
    return items


def _pmd_and_year_from_page(content_id):
    import re as _re
    try:
        r = multiquest.get(_URL_DETAILS % content_id, headers={'User-Agent': _UA}, timeout=10)
        r.raise_for_status()
        m = _re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, _re.DOTALL)
        if not m:
            return None, None
        data = json.loads(m.group(1))
        queries = data.get('props', {}).get('__dehydratedState', {}).get('queries', [])
        state = next((q.get('state', {}) for q in queries if q.get('queryKey', [''])[0] == 'MovieDetails'), {})
        movie = state.get('data', {}).get('data', {}).get('movie') or {}
        pmd  = (movie.get('videoSource') or {}).get('pmdUrl') or None
        year = str(movie.get('productionYear') or '') or None
        return pmd, year
    except Exception:
        log.error()
        return None, None


def _pmd_from_page(content_id):
    pmd, _ = _pmd_and_year_from_page(content_id)
    return pmd


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        if season and int(season) > 0:
            data = _gql('VideoData', _HASH_VIDEO,
                        {'contentId': url, 'externalId': url,
                         'checkSpecialCategory': False, 'specialCategorySlug': ''})
            ep  = data.get('episodeData') or {}
            pmd = (ep.get('videoSource') or {}).get('pmdUrl') or ''
        else:
            pmd = _pmd_from_page(url) or ''
            if not pmd:
                data  = _gql('MovieDetails', _HASH_DETAILS,
                             {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
                movie = data.get('movie') or {}
                pmd   = (movie.get('videoSource') or {}).get('pmdUrl') or ''
        if pmd:
            return [('Netzkino', _URL_STREAM + urllib.parse.quote(pmd, safe='/'), True, 'HD', 'de')]
        return []

    import re as _re
    query = _re.sub(r'\s*[\(\[\{].*', '', title).strip()
    words = query.split()
    query = words[0].lower() if words else query.lower()
    year_s = str(year or '')
    data  = _gql('Search', _HASH_SEARCH, {'text': query}, fallback_hash=_HASH_SEARCH_OLD)
    nodes = (data.get('search') or {}).get('nodes') or []
    for node in nodes:
        content_id = node.get('id')
        if not content_id:
            continue
        pmd, page_year = _pmd_and_year_from_page(content_id)
        if not pmd:
            continue
        if year_s and page_year and page_year != year_s:
            continue
        return [('Netzkino', _URL_STREAM + urllib.parse.quote(pmd, safe='/'), True, 'HD', 'de')]
    return []


def get_details(url='', params=None):
    if not url:
        return {}
    data  = _gql('MovieDetails', _HASH_DETAILS,
                 {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
    movie = data.get('movie') or data.get('series') or {}
    return {
        'plot':   str(movie.get('longSynopsis') or movie.get('shortSynopsis') or ''),
        'poster': _img(movie, 'coverImage', 'widescreenImage'),
    }


def search(query='', params=None):
    if not query:
        return []
    data  = _get_json(_URL_SEARCH % urllib.parse.quote_plus(query))
    posts = data.get('posts') or []
    items = []
    for post in posts:
        cf        = post.get('custom_fields') or {}
        streaming = (cf.get('Streaming') or [''])[0]
        youtube   = (cf.get('Youtube_Delivery_Id') or [''])[0]
        if not streaming and not youtube:
            continue
        year = str((cf.get('Jahr') or [''])[0])
        url_ = ''
        if streaming:
            url_ = _URL_STREAM + urllib.parse.quote(streaming, safe='/') + '.mp4'
        elif youtube:
            url_ = 'plugin://plugin.video.youtube/play/?video_id=%s' % youtube
        items.append({
            'title':       str(post.get('title') or ''),
            'url':         url_,
            'poster':      str(post.get('thumbnail') or ''),
            'fanart':      str((cf.get('featured_img_all') or [''])[0]),
            'year':        year,
            'plot':        str(post.get('content') or ''),
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    return items
