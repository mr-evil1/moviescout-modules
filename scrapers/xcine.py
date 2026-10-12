# -*- coding: utf-8 -*-
import re
from html import unescape
from urllib.parse import quote_plus

import xbmcgui
from resources.lib import multiquest, log

SITE_ID       = 'xcine'
SITE_NAME     = 'xCine'
SITE_DOMAIN   = 'xcine.hair'
TYPE          = 'movie'
GLOBAL_SEARCH = True
ACTIVE        = True

_URL_MAIN      = 'https://' + SITE_DOMAIN + '/'
_URL_NEW       = _URL_MAIN + 'kinofilme-online/'
_URL_KINO      = _URL_MAIN + 'aktuelle-kinofilme-im-kino/'
_URL_ANIMATION = _URL_MAIN + 'animation/'
_URL_SERIES    = _URL_MAIN + 'serienstream-deutsch/'
_URL_SEARCH    = _URL_MAIN + 'index.php?do=search&subaction=search&story=%s&titleonly=3'

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
_HEADERS = {'User-Agent': _UA, 'Accept-Language': 'de-DE,de;q=0.9'}

_RE_ENTRY = re.compile(
    r'item__link.*?href="([^"]+).*?<img src="([^"]+).*?alt="([^"]+)(.*?)</span>\s+<span>',
    re.S
)
_RE_QUALITY   = re.compile(r'movie-item__label">([^<]+)')
_RE_EP_COUNT  = re.compile(r'ep-num">e\.([\d]+)')
_RE_YEAR      = re.compile(r'meta ws-nowrap">\s+<span>([\d]+)')
_RE_IS_SERIES = re.compile(r'\s+-\s+Staffel\s+\d+')

_RE_NEXT_1    = re.compile(r'class="pagination.*?<span>[^>]</span>\s<a\shref="([^"]+)', re.S)
_RE_NEXT_2    = re.compile(r'class="pagination.*?<span>[^>][^>]</span>\s<a\shref="([^"]+)', re.S)
_RE_NEXT_3    = re.compile(r'class="pagination.*?<span>[^>][^>][^>]</span>\s<a\shref="([^"]+)', re.S)

_RE_GENRE_BLOCK = re.compile(r'Genre.*?</ul>', re.S)
_RE_YEAR_BLOCK  = re.compile(r'Release.*?</ul>', re.S)
_RE_LINK        = re.compile(r'href="([^"]+).*?>([^<]+)')

_RE_SEASONS  = re.compile(r'"><a href="#">([^<]+)')
_RE_DESC     = re.compile(r'"description"[^>]content="([^"]+)')
_RE_HOSTERS  = re.compile(r'link="([^"]+)')

_RE_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']')
_RE_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']')
_RE_OG_DESC  = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']')


def _get(url, cache_ttl=0):
    try:
        h = dict(_HEADERS)
        if cache_ttl:
            h['_cache_ttl'] = cache_ttl
        r = multiquest.get(url, headers=h, timeout=15)
        return r.text
    except Exception:
        log.error()
        return ''


def _parse_entries(sHtml):
    items = []
    for m in _RE_ENTRY.finditer(sHtml):
        sUrl       = m.group(1).strip()
        sThumbnail = m.group(2).strip()
        sName      = unescape(m.group(3)).strip()
        sDummy     = m.group(4)

        if not sUrl.startswith('http'):
            sUrl = _URL_MAIN + sUrl.lstrip('/')
        if sThumbnail.startswith('/'):
            sThumbnail = _URL_MAIN + sThumbnail[1:]

        mQ = _RE_QUALITY.search(sDummy)
        mE = _RE_EP_COUNT.search(sDummy)
        mY = _RE_YEAR.search(sDummy)

        is_tvshow = bool(_RE_IS_SERIES.search(sName))

        item = {
            'title':       sName,
            'url':         sUrl,
            'poster':      sThumbnail,
            'mediatype':   'tvshow' if is_tvshow else 'movie',
            'is_playable': False,
            'next_func':   'show_episodes' if is_tvshow else 'get_hosters',
            'is_tvshow':   is_tvshow,
        }
        if mQ:
            item['quality'] = mQ.group(1).strip()
        if mE:
            item['info'] = mE.group(1) + ' Episoden'


        items.append(item)
    return items


def load(url='', params=None):
    return [
        {'title': 'Neue Filme',        'url': _URL_NEW,       'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'movie'},
        {'title': 'Aktuelle Kinofilme', 'url': _URL_KINO,      'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'movie'},
        {'title': 'Animation',          'url': _URL_ANIMATION, 'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'movie'},
        {'title': 'Serien',             'url': _URL_SERIES,    'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'tvshow'},
        {'title': 'Nach Jahr',          'url': _URL_MAIN,      'next_func': 'browse_years',   'is_playable': False, 'mediatype': 'movie'},
        {'title': 'Suche',              'url': '',             'next_func': 'search',         'is_playable': False, 'mediatype': 'movie'},
    ]


def browse_years(url='', params=None):
    sHtml = _get(url or _URL_MAIN, cache_ttl=60 * 60 * 48)
    items = []
    mBlock = _RE_YEAR_BLOCK.search(sHtml)
    if not mBlock:
        return items
    for m in _RE_LINK.finditer(mBlock.group(0)):
        sUrl  = m.group(1).strip()
        sName = unescape(m.group(2)).strip()
        if not sUrl.startswith('http'):
            sUrl = _URL_MAIN + sUrl.lstrip('/')
        items.append({'title': sName, 'url': sUrl, 'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'movie'})
    return items


def browse_genres(url='', params=None):
    sHtml = _get(url or _URL_MAIN, cache_ttl=60 * 60 * 48)
    items = []
    mBlock = _RE_GENRE_BLOCK.search(sHtml)
    if not mBlock:
        return items
    for m in _RE_LINK.finditer(mBlock.group(0)):
        sUrl  = m.group(1).strip()
        sName = unescape(m.group(2)).strip()
        if not sUrl.startswith('http'):
            sUrl = _URL_MAIN + sUrl.lstrip('/')
        items.append({'title': sName, 'url': sUrl, 'next_func': 'browse_entries', 'is_playable': False, 'mediatype': 'movie'})
    return items


def browse_entries(url='', params=None):
    sHtml = _get(url, cache_ttl=60 * 60 * 6)
    if not sHtml:
        return []

    items = _parse_entries(sHtml)

    mNext = _RE_NEXT_1.search(sHtml) or _RE_NEXT_2.search(sHtml) or _RE_NEXT_3.search(sHtml)
    if mNext:
        sNextUrl = mNext.group(1).strip()
        if not sNextUrl.startswith('http'):
            sNextUrl = _URL_MAIN + sNextUrl.lstrip('/')
        items.append({
            'title':     '>> Nächste Seite',
            'url':       sNextUrl,
            'next_func': 'browse_entries',
            'is_playable': False,
            'mediatype': 'movie',
        })

    return items


def show_episodes(url='', params=None):
    sHtml = _get(url, cache_ttl=60 * 60 * 4)
    if not sHtml:
        return []

    items = []
    mDesc = _RE_DESC.search(sHtml)
    sDesc = unescape(mDesc.group(1)).strip() if mDesc else ''

    mPoster = _RE_OG_IMAGE.search(sHtml)
    sPoster = mPoster.group(1) if mPoster else ''

    for i, m in enumerate(_RE_SEASONS.finditer(sHtml)):
        sName = unescape(m.group(1)).strip()
        item = {
            'title':         sName,
            'url':           url,
            'poster':        sPoster,
            'next_func':     'get_hosters',
            'is_playable':   False,
            'mediatype':     'episode',
            'episode_name':  sName,
            'episode_index': i,
        }
        if sDesc:
            item['plot'] = sDesc
        items.append(item)

    return items


def search(query='', params=None, url=''):
    if isinstance(params, dict):
        query = query or params.get('query') or params.get('keyword') or ''
    if not query:
        if isinstance(url, str) and url and url.lower() not in ('search', 'suche', 'search_form'):
            query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('xCine Suche')
            if r:
                query = r.strip()
        except Exception:
            log.error()
    if not query:
        return []
    sHtml = _get(_URL_SEARCH % quote_plus(query))
    if not sHtml:
        return []
    return _parse_entries(sHtml)


def get_details(url='', params=None):
    sHtml = _get(url, cache_ttl=60 * 60 * 6)
    if not sHtml:
        return {}
    d = {}
    mTitle = _RE_OG_TITLE.search(sHtml)
    if mTitle:
        d['title'] = unescape(mTitle.group(1)).strip()
    mImage = _RE_OG_IMAGE.search(sHtml)
    if mImage:
        d['poster'] = mImage.group(1)
    mDesc = _RE_OG_DESC.search(sHtml)
    if mDesc:
        d['plot'] = unescape(mDesc.group(1)).strip()
    return d


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    episode_name  = (params or {}).get('episode_name', '')
    episode_index = (params or {}).get('episode_index', None)

    if url and url.startswith('http'):
        sHtml = _get(url)
    elif title:
        sHtml = _get(_URL_SEARCH % quote_plus(title))
        items = _parse_entries(sHtml)
        if not items:
            log.log('[xCine] Keine Treffer für "%s"' % title)
            return []
        title_clean = title.lower().strip()
        year_str    = str(year) if year else ''
        best_url = ''
        for item in items:
            t = item['title'].lower()
            if title_clean not in t and t not in title_clean:
                continue
            if year_str and year_str not in item['title']:
                pass
            best_url = item['url']
            break
        if not best_url:
            best_url = items[0]['url']
        sHtml = _get(best_url)
    else:
        return []

    if not sHtml:
        return []

    filtered = False
    if episode_name:
        m = re.search(r'>{0}<.*?</ul></li>'.format(re.escape(episode_name)), sHtml, re.S)
        if m:
            sHtml    = m.group(0)
            filtered = True

    all_links = []
    seen_all  = set()
    for m in _RE_HOSTERS.finditer(sHtml):
        sLink = m.group(1).strip()
        if not sLink or sLink in seen_all:
            continue
        if 'youtube' in sLink or 'vod' in sLink:
            continue
        if sLink.startswith('//'):
            sLink = 'https:' + sLink
        seen_all.add(sLink)
        all_links.append(sLink)

    if not filtered:
        if episode_index is not None and len(all_links) > 1:
            try:
                all_links = [all_links[episode_index]]
            except IndexError:
                pass
        elif len(all_links) > 1:
            all_links = [all_links[0]]

    hosters = []
    for sLink in all_links:
        try:
            from urllib.parse import urlparse as _up
            sName = _up(sLink).netloc.split('.')[0].strip() or sLink
        except Exception:
            sName = sLink
        hosters.append([sName, sLink, False, '720', 'de'])

    return hosters
