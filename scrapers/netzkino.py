# -*- coding: utf-8 -*-
#mod by Zusatzmetall
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from resources.lib import multiquest, log

SITE_ID       = 'netzkino'
SITE_NAME     = 'Netzkino'
SITE_DOMAIN   = 'netzkino.de'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA         = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_GQL        = 'https://data.netzkino.de/netzkino/graphql'
_URL_STREAM = 'https://pmd.netzkino-seite.netzkino.de/'

_HASH_CAT     = '5e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8'
_HASH_ALL     = '51eb32b81108d564d20969692d53311885bc80b2d1a7041ce5cba1398923caa6'
_HASH_DETAILS = '692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97'
_HASH_VIDEO   = 'ce2a04069f5ed18f6399df7070a2d27e209a7c530c77e4fb583ec898da02b1f1'
_HASH_SEARCH  = 'e7f141530416887b1faa663dbdd468534c6639e47886e8156686afd9a0f81d76'

_URL_DETAILS  = 'https://www.netzkino.de/details/%s'

_MAIN_CATS = [
    ('Neu',                     'neu-frontpage'),
    ('Highlights',              'highlights-frontpage'),
    ('Top bewertet',            'themenkino-top-rated-imdb'),
    ('Serien',                  'serien'),
    ('Actionfilme',             'actionfilme'),
    ('Abenteuerfilme',          'abenteuer'),
    ('Animationsfilme',         'animationsfilme-zeichentrick'),
    ('Blockbuster & Kultfilme', 'blockbuster-kultfilme-frontpage'),    
    ('Dokumentationen',         'top-dokumentationen'),
    ('Fantasyfilme',            'fantasyfilme-actionkino'),    
    ('Historiefilme',           'historiendrama'),
    ('Kriegsfilme',             'kriegsfilme'),
    ('Krimifilme',              'krimi'),    
    ('Liebesfilme',             'liebesdrama'),      
    ('Mockbusterfilme',         'themenkino-die-besten-mockbuster'),     
    ('Psychofilme',             'psychothriller'),         
    ('Starkinofilme',           'starkino'),       
    ('Tatsachenfilme',          'themenkino-filme-nach-wahren-begebenheiten'),
    ('Weihnachtsfilme',         'weihnachtsfilme'),    
    ('Westernfilme',            'western'),    
    ('Zombiefilme',             'zombie'),    
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
        if not isinstance(body, dict):
            return {}
        errors = body.get('errors') or []
        if fallback_hash and any(isinstance(e, dict) and e.get('message') == 'PersistedQueryNotFound' for e in errors):
            return _gql(op, fallback_hash, variables)
        data = body.get('data')
        return data if isinstance(data, dict) else {}
    except Exception:
        log.error()
        return {}


def _img(node, *keys):
    if not isinstance(node, dict):
        return ''
    for k in keys:
        img = node.get(k)
        if isinstance(img, dict) and img.get('masterUrl'):
            return img['masterUrl']
    return ''


def _node_to_item(node):
    if not isinstance(node, dict):
        return None

    movie = node.get('contentMovie') or node.get('movie')
    series = node.get('contentSeries') or node.get('series')

    if not movie and not series:
        if node.get('numberOfSeasons') is not None or node.get('seasons') is not None:
            series = node
        elif node.get('id') or node.get('title') or node.get('slug'):
            if node.get('type') == 'series' or node.get('isSeries'):
                series = node
            else:
                movie = node

    if movie and movie.get('title'):
        slug = str(movie.get('slug') or movie.get('id') or '')
        year = movie.get('productionYear')
        return {
            'title':       str(movie.get('title') or ''),
            'url':         slug,
            'poster':      _img(movie, 'coverImage', 'widescreenImage'),
            'fanart':      _img(movie, 'widescreenImage', 'headerImage24By9'),
            'year':        str(year) if year else '',
            'plot':        str(movie.get('longSynopsis') or movie.get('shortSynopsis') or ''),
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        }

    if series and series.get('title'):
        slug = str(series.get('slug') or series.get('id') or '')
        year = series.get('productionYear')
        return {
            'title':       str(series.get('title') or ''),
            'url':         slug,
            'poster':      _img(series, 'coverImage', 'widescreenImage'),
            'fanart':      _img(series, 'widescreenImage', 'headerImage24By9'),
            'year':        str(year) if year else '',
            'plot':        str(series.get('longSynopsis') or series.get('shortSynopsis') or ''),
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'showSeasons',
        }
    return None


def _fetch_next_data(slug_or_url):
    import re as _re
    if slug_or_url.startswith('http'):
        target_urls = [slug_or_url]
    else:
        target_urls = [
            'https://www.netzkino.de/kategorie/%s' % slug_or_url,
            'https://www.netzkino.de/%s' % slug_or_url
        ]

    for target_url in target_urls:
        try:
            r = multiquest.get(target_url, headers={'User-Agent': _UA}, timeout=10)
            r.raise_for_status()
            m = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, _re.DOTALL)
            if m:
                return json.loads(m.group(1))
        except Exception:
            continue
    return None


def _find_category_in_next_data(nd):
    if not isinstance(nd, dict):
        return {}
    try:
        queries = nd.get('props', {}).get('__dehydratedState', {}).get('queries', [])
        for q in queries:
            if not isinstance(q, dict):
                continue
            key = q.get('queryKey') or []
            if key and key[0] in ('CategoryDataBySlug', 'AllContent', 'CategoryData'):
                state_data = q.get('state', {}).get('data', {})
                if isinstance(state_data, dict):
                    inner_data = state_data.get('data') or state_data
                    if isinstance(inner_data, dict):
                        cat = inner_data.get('category') or inner_data.get('parentCategory')
                        if cat:
                            return cat
    except Exception:
        log.error()
    return {}


def load(url='', params=None):
    items = [{'title': 'Suche', 'url': '', 'is_playable': False, 'next_func': 'search'}]
    items.extend([
        {'title': title, 'url': slug, 'is_playable': False, 'next_func': 'showEntries'}
        for title, slug in _MAIN_CATS
    ])
    items.append({'title': 'Weitere Genres', 'url': '', 'is_playable': False, 'next_func': 'showGenres'})
    return items


def showGenres(url='', params=None):
    data  = _gql('AllContent', _HASH_ALL, {'parentSlug': 'netzkino-genre', 'featuredSlug': 'keinefeatured'})
    nodes = (data.get('parentCategory') or {}).get('subcategories', {}).get('nodes', []) if isinstance(data, dict) else []
    return [
        {'title': str(n.get('title') or ''), 'url': str(n.get('slug') or ''),
         'is_playable': False, 'next_func': 'showEntries'}
        for n in nodes if isinstance(n, dict) and n.get('slug') and n.get('title')
    ]


def showEntries(url='', params=None):
    if not url:
        return []

    slug = url.rstrip('/').rsplit('/', 1)[-1]
    items = []

    for s in [slug, slug + '-frontpage', slug + '_frontpage']:
        data = _gql('CategoryDataBySlug', _HASH_CAT, {'slug': s})
        cat = data.get('category') if isinstance(data, dict) else None
        if not isinstance(cat, dict):
            continue

        subcats = (cat.get('subcategories') or {}).get('nodes', []) if isinstance(cat.get('subcategories'), dict) else []
        for sc in subcats:
            if isinstance(sc, dict) and sc.get('slug') and sc.get('title'):
                items.append({
                    'title': str(sc['title']),
                    'url': str(sc['slug']),
                    'is_playable': False,
                    'next_func': 'showEntries',
                })

        nodes = (cat.get('content') or {}).get('nodes', []) if isinstance(cat.get('content'), dict) else []
        for node in nodes:
            item = _node_to_item(node)
            if item:
                items.append(item)

        if items:
            return items

    nd = _fetch_next_data(url)
    cat = _find_category_in_next_data(nd)
    if isinstance(cat, dict):
        subcats = (cat.get('subcategories') or {}).get('nodes', []) if isinstance(cat.get('subcategories'), dict) else []
        for sc in subcats:
            if isinstance(sc, dict) and sc.get('slug') and sc.get('title'):
                items.append({
                    'title': str(sc['title']),
                    'url': str(sc['slug']),
                    'is_playable': False,
                    'next_func': 'showEntries',
                })

        nodes = (cat.get('content') or {}).get('nodes', []) if isinstance(cat.get('content'), dict) else []
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
    series  = data.get('series') or data.get('contentSeries') or {} if isinstance(data, dict) else {}
    seasons = (series.get('seasons') or {}).get('nodes', []) if isinstance(series.get('seasons'), dict) else []
    if not seasons:
        return []
    poster = _img(series, 'coverImage', 'widescreenImage')
    fanart = _img(series, 'widescreenImage', 'headerImage24By9')
    items  = []
    for s in seasons:
        if not isinstance(s, dict):
            continue
        season_num  = s.get('seasonInSeries') or 1
        first_eps   = (s.get('firstEpisode') or {}).get('nodes', []) if isinstance(s.get('firstEpisode'), dict) else []
        first_ep_id = first_eps[0]['id'] if first_eps and isinstance(first_eps[0], dict) and 'id' in first_eps[0] else ''
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
        ep = (data.get('episodeData') or data.get('episode')) if isinstance(data, dict) else None
        if not isinstance(ep, dict):
            break
        season_obj = ep.get('season') or {}
        if isinstance(season_obj, dict) and season_obj.get('id') != season_id:
            break
        year = ep.get('productionYear') or (season_obj.get('productionYear') if isinstance(season_obj, dict) else None)
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
        state = next((q.get('state', {}) for q in queries if isinstance(q, dict) and (q.get('queryKey') or [''])[0] == 'MovieDetails'), {})
        data_obj = state.get('data', {}) if isinstance(state, dict) else {}
        inner_data = data_obj.get('data', {}) if isinstance(data_obj, dict) else {}
        movie = (inner_data.get('movie') or inner_data.get('series')) if isinstance(inner_data, dict) else {}
        if not isinstance(movie, dict):
            return None, None
        pmd  = (movie.get('videoSource') or {}).get('pmdUrl') if isinstance(movie.get('videoSource'), dict) else None
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
            ep  = data.get('episodeData') or {} if isinstance(data, dict) else {}
            pmd = (ep.get('videoSource') or {}).get('pmdUrl') or '' if isinstance(ep, dict) and isinstance(ep.get('videoSource'), dict) else ''
        else:
            data  = _gql('MovieDetails', _HASH_DETAILS,
                         {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
            movie = (data.get('movie') or data.get('series') or {}) if isinstance(data, dict) else {}
            pmd   = (movie.get('videoSource') or {}).get('pmdUrl') or '' if isinstance(movie.get('videoSource'), dict) else ''
            if not pmd:
                pmd = _pmd_from_page(url) or ''
        if pmd:
            return [('Netzkino', _URL_STREAM + urllib.parse.quote(pmd, safe='/'), True, 'HD', 'de')]
        return []

    import re as _re
    query = _re.sub(r'\s*[\(\[\{].*', '', title).strip()
    words = query.split()
    query = words[0].lower() if words else query.lower()
    year_s = str(year or '')
    data  = _gql('Search', _HASH_SEARCH, {'text': query})
    nodes = (data.get('search') or {}).get('nodes') or [] if isinstance(data, dict) else []
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
        return [('Netzkino', _URL_STREAM + urllib.parse.quote(pmd, safe='/'), True, 'HD', 'de')]
    return []


def get_details(url='', params=None):
    if not url:
        return {}
    data  = _gql('MovieDetails', _HASH_DETAILS,
                 {'movieId': url, 'externalId': url, 'slug': url, 'potentialMovieId': url})
    movie = (data.get('movie') or data.get('series') or {}) if isinstance(data, dict) else {}
    return {
        'plot':   str(movie.get('longSynopsis') or movie.get('shortSynopsis') or ''),
        'poster': _img(movie, 'coverImage', 'widescreenImage'),
    }


def search(url='', params=None, query=''):
    p_dict = {}
    if isinstance(params, str):
        try:
            p_dict = json.loads(params)
        except Exception:
            p_dict = {}
    elif isinstance(params, dict):
        p_dict = params

    if not query:
        query = p_dict.get('query') or p_dict.get('keyword') or p_dict.get('search') or ''

    if not query:
        import xbmcgui
        dialog = xbmcgui.Dialog()
        res = dialog.input('Netzkino Suche', type=xbmcgui.INPUT_ALPHANUM)
        if res:
            query = res.strip()

    if not query:
        return []

    data = _gql('Search', _HASH_SEARCH, {'text': query})
    if not isinstance(data, dict):
        return []

    nodes = (data.get('search') or {}).get('nodes') or []
    if not nodes:
        return []

    def _fetch_item(content_id):
        try:
            details = _gql('MovieDetails', _HASH_DETAILS, {
                'movieId': content_id, 'externalId': content_id,
                'slug': content_id, 'potentialMovieId': content_id
            })
            item = _node_to_item(details)
            if item:
                return item

            pmd, year = _pmd_and_year_from_page(content_id)
            if pmd:
                return {
                    'title': str(content_id),
                    'url': str(content_id),
                    'poster': '',
                    'fanart': '',
                    'year': str(year) if year else '',
                    'mediatype': 'movie',
                    'is_playable': True,
                    'next_func': 'get_hosters',
                }
        except Exception:
            log.error()
        return None

    ids = [n.get('id') or n.get('slug') for n in nodes if isinstance(n, dict) and (n.get('id') or n.get('slug'))]
    items = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_item, cid): cid for cid in ids}
        for f in as_completed(futures):
            try:
                item = f.result(timeout=10)
                if item:
                    items.append(item)
            except Exception:
                log.error()

    return items
