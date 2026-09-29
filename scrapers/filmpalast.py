# -*- coding: utf-8 -*-
import re
from html import unescape
from urllib.parse import quote_plus

from resources.lib import multiquest, log

SITE_ID       = 'filmpalast'
SITE_NAME     = 'FilmPalast'
SITE_DOMAIN   = 'filmpalast.to'
TYPE          = 'movie'
GLOBAL_SEARCH = True
ACTIVE        = True

_URL_MAIN   = 'https://' + SITE_DOMAIN
_URL_SEARCH = _URL_MAIN + '/search/title/%s/page/1'
_URL_STREAM = _URL_MAIN + '/stream/%s'

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
_HEADERS = {'User-Agent': _UA, 'Accept-Language': 'de-DE,de;q=0.9'}

_RE_SEARCH_ITEM   = re.compile(
    r'<a[^>]+href="https://filmpalast\.to/stream/([a-z0-9\-]+)"[^>]*>'
    r'.*?<img[^>]+alt="([^"]+)"',
    re.S
)
_RE_THUMB         = re.compile(r'<img[^>]+src="(/files/movies/\d+/[^"]+)"[^>]+alt="([^"]+)"')
_RE_YEAR          = re.compile(r'\b((?:19[5-9]|20[0-3])\d)\b')
_RE_RELEASE_TEXT  = re.compile(r'id="release_text"[^>]*>([^<&]+)')
_RE_HOST_BLOCK    = re.compile(r'<ul class="currentStreamLinks">(.*?)</ul>', re.S)
_RE_HOST_NAME     = re.compile(r'class="hostName">([^<]+)<')
_RE_PLAYER_URL    = re.compile(r'data-player-url="(https?://[^"]+)"')
_RE_HREF_URL      = re.compile(r'href="(https?://(?!filmpalast)[^"]+)"')
_RE_OG_TITLE      = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']')
_RE_OG_IMAGE      = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']')
_RE_OG_DESC       = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']')
_RE_CANONICAL     = re.compile(r'<link rel="canonical" href="[^"]+/stream/([a-z0-9\-]+)"')


def _get(url):
    try:
        r = multiquest.get(url, headers=_HEADERS, timeout=15)
        return r.text
    except Exception:
        log.error()
        return ''


def _lang_from_signals(sTitle='', sSlug='', sRelease=''):
    title_up   = sTitle.upper()
    slug_up    = sSlug.upper()
    release_up = sRelease.upper().replace('-', '.')

    if 'ENGLISH' in title_up or title_up.endswith('*ENGLISH*') or '*ENGLISH*' in title_up:
        return 'en'
    if slug_up.endswith('-ENGLISH') or '-ENGLISH-' in slug_up:
        return 'en'

    if sRelease:
        parts = set(release_up.split('.'))
        if 'GERMAN' in release_up or 'DEUTSCH' in release_up:
            return 'de'
        if 'DL' in parts:
            return 'de'
        if 'OV' in parts or 'ENGLISH' in release_up or 'ENG' in parts:
            return 'en'
        if 'MULTi' in sRelease or 'MULTI' in release_up:
            if 'GERMAN' not in release_up and 'DL' not in parts:
                return 'en'
        return 'unbekannt'

    return 'unbekannt'


def _extract_hosters_from_page(sHtml, sSlug=''):
    sRelease = ''
    mRel = _RE_RELEASE_TEXT.search(sHtml)
    if mRel:
        sRelease = unescape(mRel.group(1)).strip()

    mOgTitle = _RE_OG_TITLE.search(sHtml)
    sTitle = unescape(mOgTitle.group(1)).strip() if mOgTitle else ''

    sLang = _lang_from_signals(sTitle, sSlug, sRelease)

    quality = 'HD'
    rel_up = sRelease.upper()
    if 'CAM' in rel_up or 'TELESYNC' in rel_up or '.TS.' in rel_up:
        quality = 'CAM'
    elif '1080' in rel_up:
        quality = '1080'
    elif '720' in rel_up:
        quality = '720'

    hosters = []
    seen_urls = set()
    for block in _RE_HOST_BLOCK.findall(sHtml):
        mName = _RE_HOST_NAME.search(block)
        sName = unescape(mName.group(1)).strip() if mName else 'Hoster'
        mUrl = _RE_PLAYER_URL.search(block)
        if not mUrl:
            mUrl = _RE_HREF_URL.search(block)
        if not mUrl:
            continue
        sUrl = mUrl.group(1)
        if sUrl in seen_urls or 'youtube' in sUrl:
            continue
        seen_urls.add(sUrl)
        hosters.append([sName, sUrl, False, quality, sLang])
    return hosters


def _slug_from_title(title, year=''):
    slug = title.lower().strip()
    slug = re.sub(r'[^a-z0-9\s]', '', slug)
    slug = re.sub(r'\s+', '-', slug).strip('-')
    return slug


def _parse_search_results(sHtml):
    items = []
    seen = set()
    for m in _RE_SEARCH_ITEM.finditer(sHtml):
        sSlug  = m.group(1)
        sTitle = unescape(m.group(2)).strip()
        if sSlug in seen or not sTitle:
            continue
        seen.add(sSlug)
        items.append({
            'title':     sTitle,
            'url':       _URL_STREAM % sSlug,
            'slug':      sSlug,
        })
    return items


def search(query='', params=None):
    sHtml = _get(_URL_SEARCH % quote_plus(query))
    return _parse_search_results(sHtml)


def get_details(url='', params=None):
    sHtml = _get(url)
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
    mYear = _RE_YEAR.search(sHtml[sHtml.find('<body>'):sHtml.find('<body>')+2000] if '<body>' in sHtml else sHtml[:2000])
    if mYear:
        d['year'] = mYear.group(1)
    return d


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if int(season or 0) > 0:
        return []

    if url and url.startswith('http'):
        mSlug = _RE_CANONICAL.search(_get(url))
        sSlug = mSlug.group(1) if mSlug else url.rstrip('/').split('/')[-1]
        sHtml = _get(url)
        if not sHtml:
            return []
        return _extract_hosters_from_page(sHtml, sSlug)

    if not title:
        return []

    sHtml = _get(_URL_SEARCH % quote_plus(title))
    if not sHtml:
        return []

    items = _parse_search_results(sHtml)
    if not items:
        log.log('[FilmPalast] Keine Treffer für "%s"' % title)
        return []

    title_clean = title.lower().strip()
    year_str    = str(year) if year else ''

    best_url  = ''
    best_slug = ''
    for item in items:
        t = item['title'].lower()
        t_base = re.sub(r'\s*\*[^*]+\*\s*', '', t).strip()
        if title_clean not in t and t_base not in title_clean and title_clean not in t_base:
            continue
        if year_str and year_str not in item.get('url', '') and year_str not in item['title']:
            pass
        best_url  = item['url']
        best_slug = item['slug']
        break

    if not best_url:
        best_url  = items[0]['url']
        best_slug = items[0]['slug']

    log.log('[FilmPalast] Detail: %s' % best_url)
    sHtml = _get(best_url)
    if not sHtml:
        return []
    return _extract_hosters_from_page(sHtml, best_slug)
