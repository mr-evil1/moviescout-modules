# -*- coding: utf-8 -*-
import re
import json
import datetime
from urllib.parse import quote_plus, unquote_plus
import xbmcgui
from resources.lib import multiquest, log

SITE_ID       = 'internetarchive'
SITE_NAME     = 'Internet Archive'
SITE_DOMAIN   = 'archive.org'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True
STREAMLG      = 'LG0'

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_COLLECTIONS = {
    'Cinemocracy':        'cinemocracy',
    'Feature Films':      'feature_films',
    'Film Noir':          'Film_Noir',
    'Movie Trailers':     'movie_trailers',
    'SciFi / Horror':     'SciFi_Horror',
    'Short Format Films': 'short_films',
}

_GENRES = [
    ('Horror',             'subject:"Horror"'),
    ('Sci-Fi & Fantasy',   'subject:("Sci-Fi" OR "Science Fiction" OR "Fantasy")'),
    ('Film Noir & Krimi',  'subject:("Film Noir" OR "Crime" OR "Mystery")'),
    ('Komödie',            'subject:("Comedy" OR "Slapstick")'),
    ('Drama',              'subject:"Drama"'),
    ('Western',            'subject:"Western"'),
    ('Action & Abenteuer', 'subject:("Action" OR "Adventure")'),
    ('Stummfilme',         'subject:("Silent Film" OR "Silent")'),
    ('Action',             'Action'),
    ('Adventure',          'Adventure'),
    ('Animation',          'Animation'),
    ('Crime',              'Crime'),
    ('Documentary',        'Documentary'),
    ('Family',             'Family'),
    ('Musical',            'Musical'),
    ('Romance',            'Romance'),
    ('Short',              'Short'),
    ('Thriller',           'Thriller'),
    ('War',                'War'),
]

_EPOCHS = [
    ('Vor 1930 (Stummfilm-Ära)',           'year:[1000 TO 1929]'),
    ('1930 – 1949 (Goldenes Zeitalter)',    'year:[1930 TO 1949]'),
    ('1950 – 1969 (Klassiker & B-Movies)', 'year:[1950 TO 1969]'),
    ('1970 – 1989',                         'year:[1970 TO 1989]'),
    ('1990 – Heute',                        'year:[1990 TO 2030]'),
]

_LANG_MAP = {
    'ger': 'de', 'german': 'de',
    'eng': 'en', 'english': 'en',
}

_S_COLLECTIONS   = '__ia_collections__'
_S_COLL          = '__ia_coll__:'
_S_GENRES        = '__ia_genres__'
_S_GENRE         = '__ia_genre__:'
_S_GENRE_ADV     = '__ia_genre_adv__:'
_S_JAHRE         = '__ia_jahre__'
_S_JAHR          = '__ia_jahr__:'
_S_EPOCHEN       = '__ia_epochen__'
_S_EPOCHE        = '__ia_epoche__:'
_S_NEU           = '__ia_neu__:'
_S_DE            = '__ia_de__:'
_S_POPULAR       = '__ia_popular__:'

_PAGE = 50


def _base():
    return 'https://' + SITE_DOMAIN


def _get_json(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA, 'Accept': 'application/json'}, timeout=20)
        r.raise_for_status()
        return json.loads(r.text)
    except Exception:
        log.error()
        return {}


def _thumb(identifier):
    return 'https://archive.org/services/img/' + identifier


def _adv_url(q, sort='downloads+desc', rows=_PAGE, page=1, raw=False):
    if raw:
        q_part = quote_plus(q)
    else:
        q_part = q + '+AND+mediatype%3Amovies'
    url = (
        _base() + '/advancedsearch.php?q=' + q_part +
        '&fl[]=identifier&fl[]=language&fl[]=title&fl[]=year'
        '&rows=' + str(rows) + '&page=' + str(page) + '&output=json'
    )
    if sort:
        url += '&sort[]=' + sort
    return url


def _parse_docs(docs):
    items = []
    for doc in docs:
        identifier = doc.get('identifier', '')
        title      = doc.get('title', '')
        if not identifier or not title:
            continue
        item = {
            'title':       title,
            'url':         identifier,
            'poster':      _thumb(identifier),
            'mediatype':   'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        year = str(doc.get('year') or '')
        if len(year) == 4:
            item['year'] = year
        lang = doc.get('language') or ''
        if isinstance(lang, list):
            lang = lang[0] if lang else ''
        lang_out = _LANG_MAP.get(str(lang).lower().strip(), '')
        if lang_out:
            item['lang'] = lang_out
        items.append(item)
    return items


def _docs_from(data):
    return (data.get('response') or {}).get('docs') or []


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _paged(url_prefix, q, sort='downloads+desc', page=1, raw=False):
    data  = _get_json(_adv_url(q, sort=sort, rows=_PAGE, page=page, raw=raw))
    docs  = _docs_from(data)
    items = _parse_docs(docs)
    if len(docs) == _PAGE:
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         url_prefix + str(page + 1),
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Kollektionen',   'url': _S_COLLECTIONS,   'next_func': 'load',   'is_playable': False},
            {'title': 'Genre',          'url': _S_GENRES,         'next_func': 'load',   'is_playable': False},
            {'title': 'Epoche / Jahr',  'url': _S_EPOCHEN,        'next_func': 'load',   'is_playable': False},
            {'title': 'Jahre',          'url': _S_JAHRE,          'next_func': 'load',   'is_playable': False},
            {'title': 'Deutsche Filme', 'url': _S_DE + '1',       'next_func': 'load',   'is_playable': False},
            {'title': 'Beliebte Filme', 'url': _S_POPULAR + '1',  'next_func': 'load',   'is_playable': False},
            {'title': 'Neu',            'url': _S_NEU + '1',      'next_func': 'load',   'is_playable': False},
            {'title': 'Suche',          'url': '',                'next_func': 'search', 'is_playable': False},
        ]

    if url == _S_COLLECTIONS:
        return [
            {'title': name, 'url': _S_COLL + coll_id, 'next_func': 'load', 'is_playable': False}
            for name, coll_id in _COLLECTIONS.items()
        ]

    if url.startswith(_S_COLL):
        coll_id = url[len(_S_COLL):]
        return _paged(_S_COLL + coll_id + ':', 'collection:' + coll_id + ' AND mediatype:movies', raw=True)

    if url == _S_GENRES:
        items = []
        for label, filter_str in _GENRES:
            prefix = _S_GENRE_ADV if ('"' in filter_str or '(' in filter_str) else _S_GENRE
            items.append({'title': label, 'url': prefix + label, 'next_func': 'load', 'is_playable': False})
        return items

    if url.startswith(_S_GENRE_ADV):
        label      = url[len(_S_GENRE_ADV):]
        filter_str = next((f for l, f in _GENRES if l == label), None)
        if not filter_str:
            return []
        page_key = _S_GENRE_ADV + label + ':'
        try:
            page = int(url.split(':')[-1])
        except (ValueError, IndexError):
            page = 1
        q = 'mediatype:movies AND ' + filter_str
        return _paged(page_key, q, page=page, raw=True)

    if url.startswith(_S_GENRE):
        parts = url[len(_S_GENRE):].rsplit(':', 1)
        genre = parts[0]
        try:
            page = int(parts[1])
        except (ValueError, IndexError):
            page = 1
        return _paged(_S_GENRE + genre + ':', genre + ' AND mediatype:movies', page=page, raw=True)

    if url == _S_EPOCHEN:
        return [
            {'title': label, 'url': _S_EPOCHE + quote_plus(filter_str), 'next_func': 'load', 'is_playable': False}
            for label, filter_str in _EPOCHS
        ]

    if url.startswith(_S_EPOCHE):
        raw_part   = url[len(_S_EPOCHE):]
        parts      = raw_part.rsplit(':', 1)
        filter_str = unquote_plus(parts[0])
        try:
            page = int(parts[1])
        except (ValueError, IndexError):
            page = 1
        page_key = _S_EPOCHE + parts[0] + ':'
        q = 'mediatype:movies AND ' + filter_str
        return _paged(page_key, q, page=page, raw=True)

    if url == _S_JAHRE:
        year = datetime.datetime.now().year
        return [
            {'title': str(y), 'url': _S_JAHR + str(y), 'next_func': 'load', 'is_playable': False}
            for y in range(year, 1919, -1)
        ]

    if url.startswith(_S_JAHR):
        parts = url[len(_S_JAHR):].rsplit(':', 1)
        year  = parts[0]
        try:
            page = int(parts[1])
        except (ValueError, IndexError):
            page = 1
        q = 'mediatype:movies AND year:' + year
        return _paged(_S_JAHR + year + ':', q, page=page, raw=True)

    if url.startswith(_S_NEU):
        try:
            page = int(url[len(_S_NEU):] or 1)
        except ValueError:
            page = 1
        return _paged(_S_NEU, 'mediatype:movies', sort='addeddate+desc', page=page, raw=True)

    if url.startswith(_S_DE):
        try:
            page = int(url[len(_S_DE):] or 1)
        except ValueError:
            page = 1
        q = 'mediatype:movies AND language:("German" OR "Deutsch" OR "ger" OR "de")'
        return _paged(_S_DE, q, page=page, raw=True)

    if url.startswith(_S_POPULAR):
        try:
            page = int(url[len(_S_POPULAR):] or 1)
        except ValueError:
            page = 1
        return _paged(_S_POPULAR, 'mediatype:movies', page=page, raw=True)

    return []


def get_hosters(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    if url:
        identifier = url.rstrip('/').split('/')[-1]
        embed = 'https://archive.org/embed/' + identifier
        return [('Archive.org', embed, False, '', '')]

    if not title:
        return []

    clean = _cleantitle(title)
    years = [str(year), str(int(year or 0) + 1)] if year else ['']

    def _search(yr):
        q = quote_plus(title)
        if yr:
            q += '+AND+year%3A' + yr
        data = _get_json(_adv_url(q, sort='', rows=20))
        return _docs_from(data)

    for yr in years:
        for doc in _search(yr):
            identifier = doc.get('identifier', '')
            doc_title  = doc.get('title', '')
            if not identifier or not doc_title:
                continue
            if clean in _cleantitle(doc_title) or _cleantitle(doc_title) in clean:
                embed = 'https://archive.org/embed/' + identifier
                return [('Archive.org', embed, False, '', '')]

    return []


def search(query='', params=None, url=''):
    if not query and isinstance(params, dict):
        query = params.get('query') or params.get('keyword') or ''
    if not query and isinstance(url, str) and url:
        query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('Internet Archive – Suche')
            if r:
                query = r.strip()
        except Exception:
            log.error()
    if not query:
        return []
    data = _get_json(_adv_url(quote_plus(query), sort=''))
    return _parse_docs(_docs_from(data))
