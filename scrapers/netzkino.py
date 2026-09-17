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
    ('Historiefilme',            'historiendrama'),
    ('Kriegsfilme',              'kriegsfilme'),
    ('Krimifilme',               'krimi'),
    ('Liebesfilme',              'liebesdrama'),
    ('Mockbusterfilme',          'themenkino-die-besten-mockbuster'),
    ('Psychofilme',              'psychothriller'),
    ('Starkinofilme',            'starkino'),
    ('Tatsachenfilme',           'themenkino-filme-nach-wahren-begebenheiten'),
    ('Weihnachtsfilme',          'weihnachtsfilme'),
    ('Westernfilme',             'western'),
    ('Zombiefilme',              'zombie'),
]


def _get(url, timeout=15):
    try:
        r = multiquest.get(
            url,
            headers={'User-Agent': _UA},
            timeout=timeout
        )
        r.raise_for_status()
        return r
    except Exception:
        log.error()
        return None


def _get_html(url):
    r = _get(url, timeout=15)
    if not r:
        return ''
    return r.text or ''


def _gql(op, hash_, variables, fallback_hash=None):
    ext = json.dumps({
        'persistedQuery': {
            'version': 1,
            'sha256Hash': hash_
        }
    })

    var = json.dumps(variables)

    url = (
        '%s?extensions=%s&variables=%s&operationName=%s'
        % (
            _GQL,
            urllib.parse.quote(ext),
            urllib.parse.quote(var),
            urllib.parse.quote(op)
        )
    )

    try:
        r = multiquest.get(
            url,
            headers={'User-Agent': _UA},
            timeout=15
        )

        r.raise_for_status()

        body = r.json()

        if not isinstance(body, dict):
            return {}

        errors = body.get('errors') or []

        if fallback_hash:
            for error in errors:
                if (
                    isinstance(error, dict)
                    and error.get('message') == 'PersistedQueryNotFound'
                ):
                    return _gql(
                        op,
                        fallback_hash,
                        variables
                    )

        data = body.get('data')

        if isinstance(data, dict):
            return data

    except Exception:
        log.error()

    return {}


def _next_data(url):
    html = _get_html(url)

    if not html:
        return None

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL
    )

    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except Exception:
        return None


def _fetch_next_data(slug_or_url):
    if not slug_or_url:
        return None

    if str(slug_or_url).startswith('http'):
        urls = [str(slug_or_url)]
    else:
        urls = [
            _URL_CAT % slug_or_url,
            _BASE + str(slug_or_url)
        ]

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
        queries = (
            next_data
            .get('props', {})
            .get('__dehydratedState', {})
            .get('queries', [])
        )

        for query in queries:
            if not isinstance(query, dict):
                continue

            key = query.get('queryKey') or []

            if not key:
                continue

            if key[0] not in names:
                continue

            state = query.get('state') or {}
            data = state.get('data') or {}

            if not isinstance(data, dict):
                continue

            return data.get('data') or data

    except Exception:
        log.error()

    return None


def _find_category_in_next_data(next_data):
    data = _find_query(
        next_data,
        [
            'CategoryDataBySlug',
            'AllContent',
            'CategoryData'
        ]
    )

    if not isinstance(data, dict):
        return {}

    category = (
        data.get('category')
        or data.get('parentCategory')
    )

    return category if isinstance(category, dict) else {}


def _img(node, *keys):
    if not isinstance(node, dict):
        return ''

    for key in keys:
        image = node.get(key)

        if (
            isinstance(image, dict)
            and image.get('masterUrl')
        ):
            return str(image['masterUrl'])

    return ''


def _node_to_item(node):
    if not isinstance(node, dict):
        return None

    movie = (
        node.get('contentMovie')
        or node.get('movie')
    )

    series = (
        node.get('contentSeries')
        or node.get('series')
    )

    if not movie and not series:

        if (
            node.get('numberOfSeasons') is not None
            or node.get('seasons') is not None
        ):
            series = node

        elif (
            node.get('type') == 'series'
            or node.get('isSeries')
        ):
            series = node

        elif (
            node.get('id')
            or node.get('title')
            or node.get('slug')
        ):
            movie = node

    if (
        isinstance(movie, dict)
        and movie.get('title')
    ):
        slug = str(
            movie.get('slug')
            or movie.get('id')
            or ''
        )

        year = movie.get('productionYear')

        return {
            'title': str(movie.get('title') or ''),
            'url': slug,

            'poster': _img(
                movie,
                'coverImage',
                'widescreenImage'
            ),

            'fanart': _img(
                movie,
                'widescreenImage',
                'headerImage24By9'
            ),

            'year': (
                str(year)
                if year
                else ''
            ),

            'plot': str(
                movie.get('longSynopsis')
                or movie.get('shortSynopsis')
                or ''
            ),

            'mediatype': 'movie',
            'is_playable': True,
            'next_func': 'get_hosters',
        }

    if (
        isinstance(series, dict)
        and series.get('title')
    ):
        slug = str(
            series.get('slug')
            or series.get('id')
            or ''
        )

        year = series.get('productionYear')

        return {
            'title': str(series.get('title') or ''),
            'url': slug,

            'poster': _img(
                series,
                'coverImage',
                'widescreenImage'
            ),

            'fanart': _img(
                series,
                'widescreenImage',
                'headerImage24By9'
            ),

            'year': (
                str(year)
                if year
                else ''
            ),

            'plot': str(
                series.get('longSynopsis')
                or series.get('shortSynopsis')
                or ''
            ),

            'mediatype': 'tvshow',
            'is_playable': False,
            'next_func': 'showSeasons',
        }

    return None


def _category_slugs(slug):
    slug = str(slug or '').strip()

    if not slug:
        return []

    result = []

    def add(value):
        if value and value not in result:
            result.append(value)

    add(slug)

    base = (
        slug
        .replace('-frontpage', '')
        .replace('_frontpage', '')
    )

    add(base)
    add(base + '-frontpage')
    add(base + '_frontpage')

    return result


def _gql_category_all(slug):
    best = []

    for current_slug in _category_slugs(slug):

        items = []
        after = None

        while True:

            variables = {
                'slug': current_slug
            }

            if after:
                variables['after'] = after

            data = _gql(
                'CategoryDataBySlug',
                _HASH_CAT,
                variables
            )

            if not isinstance(data, dict):
                break

            category = data.get('category')

            if not isinstance(category, dict):
                break

            content = category.get('content') or {}

            if not isinstance(content, dict):
                break

            nodes = content.get('nodes') or []

            for node in nodes:
                item = _node_to_item(node)

                if item:
                    items.append(item)

            page_info = content.get('pageInfo') or {}

            if (
                page_info.get('hasNextPage')
                and page_info.get('endCursor')
            ):
                new_after = page_info.get('endCursor')

                if new_after == after:
                    break

                after = new_after

            else:
                break

        if len(items) > len(best):
            best = items

    return best


def _next_data_category_items(url):
    next_data = _fetch_next_data(url)

    if not next_data:
        return []

    category = _find_category_in_next_data(next_data)

    if not category:
        return []

    items = []

    subcategories = category.get('subcategories') or {}

    if isinstance(subcategories, dict):

        for sub in subcategories.get('nodes') or []:

            if not isinstance(sub, dict):
                continue

            slug = sub.get('slug')
            title = sub.get('title')

            if not slug or not title:
                continue

            items.append({
                'title': str(title),
                'url': str(slug),
                'is_playable': False,
                'next_func': 'showEntries',
            })

    content = category.get('content') or {}

    if isinstance(content, dict):

        for node in content.get('nodes') or []:

            item = _node_to_item(node)

            if item:
                items.append(item)

    return items


def load(url='', params=None):

    items = [
        {
            'title': 'Suche',
            'url': '',
            'is_playable': False,
            'next_func': 'search'
        }
    ]

    for title, slug in _MAIN_CATS:

        items.append({
            'title': title,
            'url': slug,
            'is_playable': False,
            'next_func': 'showEntries'
        })

    items.append({
        'title': 'Weitere Genres',
        'url': '',
        'is_playable': False,
        'next_func': 'showGenres'
    })

    return items


def showEntries(url='', params=None):

    if not url:
        return []

    slug = str(url).rstrip('/').rsplit('/', 1)[-1]

    items = _gql_category_all(slug)

    if items:
        return items

    return _next_data_category_items(url)


def showGenres(url='', params=None):

    data = _gql(
        'AllContent',
        _HASH_ALL,
        {
            'parentSlug': 'netzkino-genre',
            'featuredSlug': 'keinefeatured'
        }
    )

    if not isinstance(data, dict):
        return []

    parent = data.get('parentCategory') or {}

    if not isinstance(parent, dict):
        return []

    subcategories = parent.get('subcategories') or {}

    if not isinstance(subcategories, dict):
        return []

    nodes = subcategories.get('nodes') or []

    items = []

    for node in nodes:

        if not isinstance(node, dict):
            continue

        slug = node.get('slug')
        title = node.get('title')

        if not slug or not title:
            continue

        items.append({
            'title': str(title),
            'url': str(slug),
            'is_playable': False,
            'next_func': 'showEntries',
        })

    return items


def showHighlights(url='', params=None):

    return [
        {
            'title': title,
            'url': _URL_CAT % slug,
            'is_playable': False,
            'next_func': 'showEntries'
        }
        for title, slug in _MAIN_CATS
    ]


def showSeasons(url='', params=None):

    if not url:
        return []

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

    if not isinstance(data, dict):
        return []

    series = (
        data.get('series')
        or data.get('contentSeries')
        or {}
    )

    if not isinstance(series, dict):
        return []

    seasons_obj = series.get('seasons') or {}

    if not isinstance(seasons_obj, dict):
        return []

    seasons = seasons_obj.get('nodes') or []

    if not seasons:
        return []

    poster = _img(
        series,
        'coverImage',
        'widescreenImage'
    )

    fanart = _img(
        series,
        'widescreenImage',
        'headerImage24By9'
    )

    items = []

    for season in seasons:

        if not isinstance(season, dict):
            continue

        season_num = (
            season.get('seasonInSeries')
            or 1
        )

        first_episode = season.get('firstEpisode') or {}

        if not isinstance(first_episode, dict):
            continue

        first_nodes = first_episode.get('nodes') or []

        if not first_nodes:
            continue

        first = first_nodes[0]

        if not isinstance(first, dict):
            continue

        first_ep_id = first.get('id')

        if not first_ep_id:
            continue

        season_id = season.get('id') or ''

        year = (
            season.get('productionYear')
            or series.get('productionYear')
        )

        season_poster = _img(
            season,
            'coverImage',
            'widescreenImage'
        ) or poster

        season_fanart = _img(
            season,
            'widescreenImage'
        ) or fanart

        items.append({
            'title': 'Staffel %d' % season_num,

            'url': '%s|%s|%d' % (
                season_id,
                first_ep_id,
                season_num
            ),

            'poster': season_poster,
            'fanart': season_fanart,

            'year': (
                str(year)
                if year
                else ''
            ),

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

    season_id = parts[0]
    ep_id = parts[1]

    try:
        season_num = int(parts[2]) if len(parts) > 2 else 1
    except Exception:
        season_num = 1

    items = []
    seen = set()
    ep_num = 1

    while ep_id and ep_id not in seen:

        seen.add(ep_id)

        data = _gql(
            'VideoData',
            _HASH_VIDEO,
            {
                'contentId': ep_id,
                'externalId': ep_id,
                'checkSpecialCategory': False,
                'specialCategorySlug': ''
            }
        )

        if not isinstance(data, dict):
            break

        ep = (
            data.get('episodeData')
            or data.get('episode')
        )

        if not isinstance(ep, dict):
            break

        season_obj = ep.get('season') or {}

        if (
            isinstance(season_obj, dict)
            and season_obj.get('id')
            and season_obj.get('id') != season_id
        ):
            break

        year = (
            ep.get('productionYear')
            or (
                season_obj.get('productionYear')
                if isinstance(season_obj, dict)
                else None
            )
        )

        episode_id = ep.get('id') or ep_id

        items.append({
            'title': str(
                ep.get('title')
                or ('Episode %d' % ep_num)
            ),

            'url': str(episode_id),

            'poster': _img(
                ep,
                'coverImage'
            ),

            'year': (
                str(year)
                if year
                else ''
            ),

            'mediatype': 'episode',
            'season': season_num,

            'episode': (
                ep.get('episodeInSeason')
                or ep_num
            ),

            'is_playable': True,
            'next_func': 'get_hosters',
        })

        ep_num += 1

        next_episode = ep.get('nextEpisodeId') or ''

        if next_episode == ep_id:
            break

        ep_id = next_episode

    return items


def _pmd_and_year_from_page(content_id):

    if not content_id:
        return None, None

    try:

        url = _URL_DETAIL % str(content_id)

        r = multiquest.get(
            url,
            headers={'User-Agent': _UA},
            timeout=15
        )

        r.raise_for_status()

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text,
            re.DOTALL
        )

        if not match:
            return None, None

        data = json.loads(match.group(1))

        queries = (
            data
            .get('props', {})
            .get('__dehydratedState', {})
            .get('queries', [])
        )

        state = {}

        for query in queries:

            if not isinstance(query, dict):
                continue

            key = query.get('queryKey') or []

            if (
                key
                and key[0] == 'MovieDetails'
            ):
                state = query.get('state') or {}
                break

        state_data = state.get('data') or {}

        inner_data = (
            state_data.get('data')
            if isinstance(state_data, dict)
            else {}
        )

        if not isinstance(inner_data, dict):
            return None, None

        content = (
            inner_data.get('movie')
            or inner_data.get('series')
            or {}
        )

        if not isinstance(content, dict):
            return None, None

        video_source = content.get('videoSource') or {}

        if not isinstance(video_source, dict):
            video_source = {}

        pmd = video_source.get('pmdUrl')

        year = content.get('productionYear')

        return (
            pmd,
            str(year) if year else None
        )

    except Exception:
        log.error()
        return None, None


def _pmd_from_page(content_id):

    pmd, _ = _pmd_and_year_from_page(content_id)

    return pmd


def get_hosters(
    title='',
    year='',
    season=0,
    episode=0,
    imdb='',
    tmdb='',
    url='',
    params=None
):

    if url:

        pmd = ''

        try:
            season_num = int(season or 0)
        except Exception:
            season_num = 0

        if season_num > 0:

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

                ep = data.get('episodeData') or {}

                if isinstance(ep, dict):

                    video_source = (
                        ep.get('videoSource')
                        or {}
                    )

                    if isinstance(video_source, dict):
                        pmd = (
                            video_source.get('pmdUrl')
                            or ''
                        )

        else:

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

                movie = (
                    data.get('movie')
                    or data.get('contentMovie')
                    or {}
                )

                if isinstance(movie, dict):

                    video_source = (
                        movie.get('videoSource')
                        or {}
                    )

                    if isinstance(video_source, dict):
                        pmd = (
                            video_source.get('pmdUrl')
                            or ''
                        )

            if not pmd:
                pmd = _pmd_from_page(url) or ''

        if pmd:

            stream_url = (
                _URL_STREAM
                + urllib.parse.quote(
                    str(pmd),
                    safe='/'
                )
            )

            return [
                (
                    'Netzkino',
                    stream_url,
                    True,
                    'HD',
                    'de'
                )
            ]

        return []

    query = re.sub(
        r'\s*[\(\[\{].*',
        '',
        str(title or '')
    ).strip()

    words = query.split()

    query = (
        words[0].lower()
        if words
        else query.lower()
    )

    if not query:
        return []

    year_s = str(year or '')

    data = _gql(
        'Search',
        _HASH_SEARCH,
        {'text': query}
    )

    if not isinstance(data, dict):
        return []

    search = data.get('search') or {}

    if not isinstance(search, dict):
        return []

    nodes = search.get('nodes') or []

    for node in nodes:

        if not isinstance(node, dict):
            continue

        content_id = (
            node.get('id')
            or node.get('slug')
        )

        if not content_id:
            continue

        pmd, page_year = _pmd_and_year_from_page(
            content_id
        )

        if not pmd:
            continue

        if (
            year_s
            and page_year
            and page_year != year_s
        ):
            continue

        stream_url = (
            _URL_STREAM
            + urllib.parse.quote(
                str(pmd),
                safe='/'
            )
        )

        return [
            (
                'Netzkino',
                stream_url,
                True,
                'HD',
                'de'
            )
        ]

    return []


def get_details(url='', params=None):

    if not url:
        return {}

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

    if not isinstance(data, dict):
        return {}

    movie = (
        data.get('movie')
        or data.get('series')
        or data.get('contentMovie')
        or data.get('contentSeries')
        or {}
    )

    if not isinstance(movie, dict):
        return {}

    return {
        'plot': str(
            movie.get('longSynopsis')
            or movie.get('shortSynopsis')
            or ''
        ),

        'poster': _img(
            movie,
            'coverImage',
            'widescreenImage'
        ),
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

        query = (
            p_dict.get('query')
            or p_dict.get('keyword')
            or p_dict.get('search')
            or ''
        )

    if not query:

        try:
            import xbmcgui

            dialog = xbmcgui.Dialog()

            result = dialog.input(
                'Netzkino Suche',
                type=xbmcgui.INPUT_ALPHANUM
            )

            if result:
                query = result.strip()

        except Exception:
            log.error()

    if not query:
        return []

    data = _gql(
        'Search',
        _HASH_SEARCH,
        {'text': query}
    )

    if not isinstance(data, dict):
        return []

    search_data = data.get('search') or {}

    if not isinstance(search_data, dict):
        return []

    nodes = search_data.get('nodes') or []

    if not nodes:
        return []

    ids = []

    for node in nodes:

        if not isinstance(node, dict):
            continue

        content_id = (
            node.get('id')
            or node.get('slug')
        )

        if content_id and content_id not in ids:
            ids.append(content_id)

    if not ids:
        return []

    def _fetch_item(content_id):

        try:

            data = _gql(
                'MovieDetails',
                _HASH_DETAILS,
                {
                    'movieId': content_id,
                    'externalId': content_id,
                    'slug': content_id,
                    'potentialMovieId': content_id
                }
            )

            if isinstance(data, dict):

                item = _node_to_item(data)

                if item:
                    return item

                movie = data.get('movie')
                series = data.get('series')

                if movie:
                    item = _node_to_item({
                        'contentMovie': movie
                    })

                    if item:
                        return item

                if series:
                    item = _node_to_item({
                        'contentSeries': series
                    })

                    if item:
                        return item

            pmd, page_year = _pmd_and_year_from_page(
                content_id
            )

            if pmd:

                return {
                    'title': str(content_id),
                    'url': str(content_id),
                    'poster': '',
                    'fanart': '',
                    'year': (
                        str(page_year)
                        if page_year
                        else ''
                    ),
                    'mediatype': 'movie',
                    'is_playable': True,
                    'next_func': 'get_hosters',
                }

        except Exception:
            log.error()

        return None

    items = []

    with ThreadPoolExecutor(max_workers=8) as executor:

        futures = {
            executor.submit(
                _fetch_item,
                content_id
            ): content_id
            for content_id in ids
        }

        for future in as_completed(futures):

            try:

                item = future.result(timeout=15)

                if item:
                    items.append(item)

            except Exception:
                log.error()

    return items
