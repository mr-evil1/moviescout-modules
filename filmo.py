# -*- coding: utf-8 -*-
import json
import re
from html import unescape
from urllib.parse import quote, quote_plus

from resources.lib import multiquest, log

SITE_ID       = 'filmo'
SITE_NAME     = 'Filmo'
SITE_DOMAIN   = 'filmo.to'
TYPE          = 'movie'
GLOBAL_SEARCH = True
ACTIVE        = True

_URL_MAIN        = 'https://' + SITE_DOMAIN
_URL_MOVIES      = _URL_MAIN + '/movies'
_URL_POPULAR     = _URL_MAIN + '/popular'
_URL_GENRES      = _URL_MAIN + '/genres'
_URL_COLLECTIONS = _URL_MAIN + '/collections'
_URL_LETTERS     = _URL_MAIN + '/letters'
_URL_SEARCH      = _URL_MAIN + '/search?q=%s'
_URL_MINT        = _URL_MAIN + '/n'

_HERO_TITLE = 'Neu diese Woche'

_LANG_FLAGS = {
    'de': 'DE',
    'gb': 'EN',
    'us': 'EN',
    'jp': 'JPN',
}

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
_HEADERS = {'User-Agent': _UA, 'Accept-Language': 'de-DE,de;q=0.9'}

_RE_CARD_SPLIT    = re.compile(r'<a[^>]+href="https://filmo\.to/movies/([a-z0-9\-]+)"')
_RE_TITLE_SOURCES = (
    re.compile(r'spotlight-card__title[^>]*>\s*([^<]+?)\s*<'),
    re.compile(r'grid-card__title[^>]*>\s*([^<]+?)\s*<'),
    re.compile(r'<img[^>]+alt="([^"]+)"'),
)
_RE_THUMB             = re.compile(r'<img[^>]+src="([^"]+)"')
_RE_ROW_HEAD          = re.compile(r'<h3[^>]*>\s*([^<]{2,60}?)\s*<a[^>]+href="https://filmo\.to/((?:collections|genres)/[a-z0-9\-]+)"')
_RE_ROW_SPLIT         = re.compile(r'<h3[^>]*class="mb-0"[^>]*>\s*([^<]{2,60}?)\s*<')
_RE_GENRE             = re.compile(r'<a[^>]+href="https://filmo\.to/genres/([a-z0-9\-]+)"[^>]*>\s*<span[^>]*>\s*([^<]{2,40}?)\s*</span>')
_RE_COLLECTION_SPLIT  = re.compile(r'<a[^>]+class="collection-index-card[^"]*"[^>]+href="https://filmo\.to/collections/([a-z0-9\-]+)"')
_RE_COLLECTION_TITLE  = re.compile(r'collection-index-card__title[^>]*>\s*([^<]+?)\s*<')
_RE_PAGE              = re.compile(r'[?&]page=(\d+)')
_RE_CSRF              = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
_RE_LANGROW_SPLIT     = re.compile(r'<div\s+class="provider-row"')
_RE_FLAG              = re.compile(r'class="fi fi-(\w+)"')
_RE_LANG              = re.compile(r'provider-row__lang"[^>]*>\s*([^<]+?)\s*<')
_RE_CHIP              = re.compile(
    r'data-p="([^"]+)"[^>]*>.*?provider-chip__name"[^>]*>\s*([^<]+?)\s*<'
    r'(.*?)(?=data-p="|</div></div>|$)', re.S)
_RE_CHIP_TAG          = re.compile(r'provider-chip__metadata-tag"[^>]*>\s*([^<]{1,12}?)\s*<')
_RE_RES               = re.compile(r'^(\d{3,4})p?$', re.I)
_RE_EXTERN            = re.compile(r'href="(https?://(?!(?:www\.)?filmo\.to)[^"]+)"')
_YEAR_PAT             = r'((?:19[5-9]|20[0-3])\d)'
_RE_YEAR_META_LABEL   = re.compile(r'ft-meta-label[^>]*>\s*' + _YEAR_PAT + r'\s*<')
_RE_YEAR_ERSCHEIN     = re.compile(r'Erscheinungsdatum[^<]{0,10}' + _YEAR_PAT)
_RE_YEAR_JSONLD       = re.compile(r'"(?:datePublished|dateCreated|startDate)"\s*:\s*"' + _YEAR_PAT)
_RE_YEAR_FALLBACK     = re.compile(r'(?<!w3\.org/)(?<!org/)(?<!/)\b' + _YEAR_PAT + r'\b(?!/svg)')


def _get(url):
    try:
        r = multiquest.get(quote(url, safe=':/?&=+%'), headers=_HEADERS, timeout=15)
        return r.text
    except Exception:
        log.error()
        return ''


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s)


def _clean_thumb(url):
    return url.split('?')[0] if url else ''


def _parse_cards(sHtml):
    cards = []
    seen  = set()
    parts = _RE_CARD_SPLIT.split(sHtml)
    for i in range(1, len(parts) - 1, 2):
        sSlug, sChunk = parts[i], parts[i + 1]
        if sSlug in seen:
            continue
        seen.add(sSlug)
        sName = ''
        for pat in _RE_TITLE_SOURCES:
            m = pat.search(sChunk)
            if m and m.group(1).strip():
                sName = m.group(1).strip()
                break
        if not sName:
            sName = sSlug.replace('-', ' ').title()
        mThumb = _RE_THUMB.search(sChunk)
        cards.append({
            'title':       unescape(sName),
            'url':         '%s/%s' % (_URL_MOVIES, sSlug),
            'poster':      _clean_thumb(mThumb.group(1)) if mThumb else '',
            'plot':        '',
            'mediatype':   'movie',
            'is_playable': False,
            'next_func':   'get_hosters',
        })
    return cards


def _next_page_item(base_url, sHtml, next_func='showEntries'):
    pages = [int(p) for p in _RE_PAGE.findall(sHtml)]
    if not pages:
        return None
    m = _RE_PAGE.search(base_url)
    current = int(m.group(1)) if m else 1
    if current >= max(pages):
        return None
    url_base = re.sub(r'[?&]page=\d+', '', base_url)
    sep = '&' if '?' in url_base else '?'
    return {
        'title':       '[B]Nächste Seite »[/B] [Seite %d / %d]' % (current + 1, max(pages)),
        'url':         '%s%spage=%d' % (url_base, sep, current + 1),
        'is_playable': False,
        'next_func':   next_func,
    }


def _og(sHtml, prop):
    m = re.search(r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\']([^"\']*)["\']' % prop, sHtml)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:%s["\']' % prop, sHtml)
    return unescape(m.group(1)).strip() if m else ''


def load(url='', params=None):
    return [
        {'title': 'Filme',        'url': _URL_MOVIES,      'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'Beliebt',      'url': _URL_POPULAR,     'is_playable': False, 'next_func': 'showRows'},
        {'title': 'Genres',       'url': _URL_GENRES,      'is_playable': False, 'next_func': 'showGenres'},
        {'title': 'Kollektionen', 'url': _URL_COLLECTIONS, 'is_playable': False, 'next_func': 'showCollections'},
        {'title': 'Highlights',   'url': _URL_MAIN,        'is_playable': False, 'next_func': 'showRows'},
        {'title': 'A-Z',          'url': _URL_LETTERS,     'is_playable': False, 'next_func': 'showLetters'},
        {'title': 'Suche',        'url': '',               'is_playable': False, 'next_func': 'search'},
    ]


def showRows(url='', params=None):
    sUrl  = url or _URL_MAIN
    sHtml = _get(sUrl)
    if not sHtml:
        return []
    items      = []
    seen       = set()
    seenTitles = set()

    mFirst = _RE_ROW_SPLIT.search(sHtml)
    if mFirst and _RE_CARD_SPLIT.search(sHtml[:mFirst.start()]):
        items.append({'title': _HERO_TITLE, 'url': sUrl + '|row=__hero__',
                      'is_playable': False, 'next_func': 'showEntries'})
        seen.add('__hero__')
        seenTitles.add(_HERO_TITLE)

    for sTitle, sPath in _RE_ROW_HEAD.findall(sHtml):
        if sPath in seen:
            continue
        seen.add(sPath)
        sTitle = unescape(sTitle.strip())
        seenTitles.add(sTitle)
        items.append({'title': sTitle, 'url': '%s/%s' % (_URL_MAIN, sPath),
                      'is_playable': False, 'next_func': 'showEntries'})

    aParts = _RE_ROW_SPLIT.split(sHtml)
    for i in range(1, len(aParts) - 1, 2):
        sTitle = unescape(aParts[i].strip())
        sBlock = aParts[i + 1]
        if sTitle in seenTitles or not _RE_CARD_SPLIT.search(sBlock):
            continue
        seenTitles.add(sTitle)
        items.append({'title': sTitle, 'url': sUrl + '|row=' + sTitle,
                      'is_playable': False, 'next_func': 'showEntries'})

    return items


def showEntries(url='', params=None):
    if not url:
        return []
    row_key  = None
    base_url = url
    if '|row=' in url:
        base_url, row_key = url.split('|row=', 1)

    sHtml = _get(base_url)
    if not sHtml:
        return []

    is_row = row_key is not None
    if row_key == '__hero__':
        mFirst = _RE_ROW_SPLIT.search(sHtml)
        if mFirst:
            sHtml = sHtml[:mFirst.start()]
    elif row_key:
        aParts = _RE_ROW_SPLIT.split(sHtml)
        for i in range(1, len(aParts) - 1, 2):
            if unescape(aParts[i].strip()) == row_key:
                sHtml = aParts[i + 1]
                break

    items = _parse_cards(sHtml)
    if not is_row:
        nxt = _next_page_item(base_url, sHtml)
        if nxt:
            items.append(nxt)
    return items


def showGenres(url='', params=None):
    sHtml = _get(_URL_GENRES)
    items = []
    seen  = set()
    for sSlug, sName in _RE_GENRE.findall(sHtml):
        if sSlug in seen:
            continue
        seen.add(sSlug)
        items.append({
            'title':       unescape(sName.strip()) or sSlug.replace('-', ' ').title(),
            'url':         '%s/%s' % (_URL_GENRES, sSlug),
            'is_playable': False,
            'next_func':   'showEntries',
        })
    return items


def showCollections(url='', params=None):
    sUrl  = url or _URL_COLLECTIONS
    sHtml = _get(sUrl)
    items = []
    seen  = set()
    aParts = _RE_COLLECTION_SPLIT.split(sHtml)
    for i in range(1, len(aParts) - 1, 2):
        sSlug, sChunk = aParts[i], aParts[i + 1]
        if sSlug in seen:
            continue
        seen.add(sSlug)
        mName = _RE_COLLECTION_TITLE.search(sChunk)
        sName = unescape(mName.group(1).strip()) if mName else sSlug.replace('-', ' ').title()
        items.append({'title': sName, 'url': '%s/%s' % (_URL_COLLECTIONS, sSlug),
                      'is_playable': False, 'next_func': 'showEntries'})
    nxt = _next_page_item(sUrl, sHtml, next_func='showCollections')
    if nxt:
        items.append(nxt)
    return items


def showLetters(url='', params=None):
    return [
        {'title': s.upper(), 'url': '%s/%s' % (_URL_LETTERS, s),
         'is_playable': False, 'next_func': 'showEntries'}
        for s in (['0-9'] + [chr(c) for c in range(ord('a'), ord('z') + 1)])
    ]


def search(query='', url='', params=None):
    if not query:
        try:
            import xbmcgui
            query = xbmcgui.Dialog().input('Filmo Suche').strip()
        except Exception:
            pass
    if not query:
        return []
    return _parse_cards(_get(_URL_SEARCH % quote_plus(query)))


def get_details(url='', params=None):
    sHtml = _get(url)
    if not sHtml:
        return {}
    d     = {}
    sDesc = _og(sHtml, 'description')
    if sDesc:
        d['plot'] = sDesc
    sImg = _og(sHtml, 'image')
    if sImg:
        d['poster'] = sImg.split('?')[0]
    mYear = (_RE_YEAR_META_LABEL.search(sHtml)
             or _RE_YEAR_ERSCHEIN.search(sHtml)
             or _RE_YEAR_JSONLD.search(sHtml)
             or _RE_YEAR_FALLBACK.search(sHtml))
    if mYear:
        d['year'] = mYear.group(1)
    return d


def _parse_chips(sHtml):
    chips = []
    for sRow in _RE_LANGROW_SPLIT.split(sHtml)[1:]:
        mFlag = _RE_FLAG.search(sRow)
        mLang = _RE_LANG.search(sRow)
        sFlag     = mFlag.group(1).lower() if mFlag else ''
        sLangLabel = _LANG_FLAGS.get(sFlag, '')
        if not sLangLabel and mLang:
            sLangLabel = mLang.group(1).strip()
        for sPayload, sHosterName, sRest in _RE_CHIP.findall(sRow):
            sQuality = ''
            for sTag in _RE_CHIP_TAG.findall(sRest):
                m = _RE_RES.match(sTag.strip())
                if m and not sQuality:
                    sQuality = m.group(1)
            chips.append((sPayload, sHosterName.strip(), sQuality or '720', sLangLabel))
    return chips


def _resolve_payload(sPayload, sCsrf, sess, sDetailUrl):
    try:
        r = sess.post(
            _URL_MINT,
            data={'p': sPayload},
            headers={
                'X-CSRF-TOKEN':     sCsrf,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer':          sDetailUrl,
                'Accept':           'application/json, text/plain, */*',
            },
            timeout=10,
        )
        r.raise_for_status()
        sToken = json.loads(r.text).get('x', '')
        if not sToken:
            return ''
        r2   = sess.get('%s/%s' % (_URL_MINT, sToken),
                        headers={'Referer': sDetailUrl}, timeout=10)
        sUrl = r2.url or ''
        if SITE_DOMAIN in sUrl:
            mExt = _RE_EXTERN.search(r2.text or '')
            sUrl = mExt.group(1) if mExt else ''
        return sUrl
    except Exception:
        log.error()
        return ''


def _hosters_from_detail(sDetailUrl):
    try:
        with multiquest.Session(headers=_HEADERS) as sess:
            r     = sess.get(sDetailUrl, timeout=15)
            sHtml = r.text
            mCsrf = _RE_CSRF.search(sHtml)
            if not mCsrf:
                log.log('[Filmo] Kein CSRF-Token auf %s' % sDetailUrl)
                return []
            sCsrf   = mCsrf.group(1)
            hosters = []
            seen    = set()
            for sPayload, sName, sQuality, sLang in _parse_chips(sHtml):
                sKey = sPayload[:24]
                if sKey in seen:
                    continue
                seen.add(sKey)
                sUrl = _resolve_payload(sPayload, sCsrf, sess, sDetailUrl)
                if sUrl:
                    hosters.append([sName, sUrl, False, sQuality, sLang])
            return hosters
    except Exception:
        log.error()
        return []


def _best_match(cards, title, year):
    title_low = title.lower().strip()
    year_str  = str(year) if year else ''
    for c in cards:
        if c['title'].lower().strip() == title_low:
            if not year_str or c.get('year', '') == year_str:
                return c['url']
    for c in cards:
        if title_low in c['title'].lower():
            if not year_str or c.get('year', '') == year_str:
                return c['url']
    for c in cards:
        if title_low in c['title'].lower():
            return c['url']
    return cards[0]['url'] if cards else ''


def get_hosters(title='', year='', season=0, episode=0,
                imdb='', tmdb='', url='', params=None):
    if url and url.startswith('http'):
        log.log('[Filmo] get_hosters browse url=%s' % url)
        return _hosters_from_detail(url)

    if int(season) > 0:
        return []

    log.log('[Filmo] get_hosters scout title="%s" year=%s' % (title, year))
    sHtml = _get(_URL_SEARCH % quote_plus(title))
    if not sHtml:
        return []
    cards = _parse_cards(sHtml)
    if not cards:
        log.log('[Filmo] Keine Treffer für "%s"' % title)
        return []
    sDetailUrl = _best_match(cards, title, year)
    if not sDetailUrl:
        return []
    log.log('[Filmo] Detail: %s' % sDetailUrl)
    return _hosters_from_detail(sDetailUrl)
