# -*- coding: utf-8 -*-
import re
from html import unescape
from urllib.parse import quote, quote_plus

from resources.lib import multiquest, log

SITE_ID       = 'kellerkino'
SITE_NAME     = 'Kellerkino'
SITE_DOMAIN   = 'kellerkino.com'
TYPE          = 'both'
GLOBAL_SEARCH = False

_URL_MAIN       = 'https://' + SITE_DOMAIN
_URL_ARCHIVE    = _URL_MAIN + '/archiv/'
_URL_IMDB       = _URL_MAIN + '/imdb-rating/'
_URL_CATEGORIES = _URL_MAIN + '/kategorien/'
_URL_LETTERS    = _URL_MAIN + '/filme-a-z/'
_URL_SEARCH     = _URL_MAIN + '/?s=%s'

_RE_CARD          = re.compile(r'<article class="movie-card[^"]*">(.*?)</article>', re.S)
_RE_CARD_LINK     = re.compile(r'<h2><a href="([^"]+)">(.*?)</a></h2>', re.S)
_RE_CARD_IMG      = re.compile(r'<img[^>]+(?:src|data-dmt-theme-src)="([^"]+)"')
_RE_CARD_YEAR     = re.compile(r'<span>\s*(\d{4})\s*</span>')
_RE_CARD_DURATION = re.compile(r'<span>\s*(\d+)\s*Min\s*</span>')
_RE_CARD_RATING   = re.compile(r'<span>\s*IMDb\s*(\d+(?:\.\d+)?)\s*</span>')
_RE_PAGINATION    = re.compile(r'class="pagination[^"]*"[^>]*>(.*?)</(?:div|nav)>', re.S)
_RE_PAGE_CURRENT  = re.compile(r'class="page-numbers current">\s*(\d+)\s*<')
_RE_PAGE_NUMBER   = re.compile(r'class="page-numbers"[^>]*>\s*(\d+)\s*<')
_RE_PAGE_NEXT     = re.compile(r'class="next page-numbers"\s+href="([^"]+)"')
_RE_CAT_CARD      = re.compile(r'<div class="category-card">(.*?)<span class="category-card-count">', re.S)
_RE_CAT_LINK      = re.compile(r'<a class="category-card-name" href="([^"]+)"><strong>([^<]+)</strong></a>')
_RE_CAT_IMG       = re.compile(r'<img src="([^"]+)"')
_RE_LETTER        = re.compile(r'<a class="dmt-az-letter-link[^"]*"\s+href="[^"]*dmt_letter=([^"&]*)\"[^>]*>\s*<span class="dmt-az-letter-main">\s*([^<]+?)\s*</span>', re.S)
_RE_HOME_TOPCOVER = re.compile(r'<a class="top-cover" href="([^"]+)"[^>]*>\s*<img src="([^"]+)"[^>]*>\s*<span>([^<]*)</span>', re.S)
_RE_HOME_CIN_LBL  = re.compile(r'class="dmt-home-cinema-title-default">\s*([^<]+?)\s*<')
_RE_HOME_CIN_CARD = re.compile(r'<a class="dmt-home-cinema-(?:focus|secondary)" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RE_HOME_NEW_LBL  = re.compile(r'<div class="dmt-home-cinema-more-head">\s*<h2>\s*([^<]+?)\s*</h2>', re.S)
_RE_HOME_NEW_CARD = re.compile(r'<a class="dmt-home-cinema-more-card" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RE_HOME_SEC_LBL  = re.compile(r'<h2>\s*([^<]+?)\s*</h2>')
_RE_HOME_THEME_TB = re.compile(r'<button[^>]*data-dmt-home-theme-tab="([^"]+)"[^>]*data-dmt-home-theme-label="([^"]+)"', re.S)
_RE_HOME_THEME_PN = re.compile(r'id="dmt-home-theme-panel-([^"]+)"')
_RE_HOSTER_LABEL  = re.compile(r'data-nfo-player-label="([^"]*)"')
_RE_HOSTER_FRAME  = re.compile(r'<iframe[^>]+src="(https?://[^"]+)"')
_RE_DETAIL_PLOT   = re.compile(r'<div[^>]+class="[^"]*(?:entry-content|sinopsis|plot|description)[^"]*"[^>]*>(.*?)</div>', re.S)

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/126.0.0.0 Safari/537.36')
_HEADERS = {
    'User-Agent':      _UA,
    'Accept-Language': 'de-DE,de;q=0.9',
    'Accept':          'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
}


def _get(url):
    try:
        r = multiquest.get(quote(url, safe=':/?&=%'), headers=_HEADERS, timeout=15)
        return r.text
    except Exception:
        log.error()
        return ''


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s)


def _card_meta(sChunk):
    mY = _RE_CARD_YEAR.search(sChunk)
    mD = _RE_CARD_DURATION.search(sChunk)
    mR = _RE_CARD_RATING.search(sChunk)
    return (mY.group(1) if mY else '',
            mD.group(1) if mD else '',
            mR.group(1) if mR else '')


def _parse_cards(sHtml):
    cards = []
    for sCard in _RE_CARD.findall(sHtml):
        m = _RE_CARD_LINK.search(sCard)
        if not m:
            continue
        sName = unescape(_strip_tags(m.group(2))).strip()
        if not sName:
            continue
        mImg = _RE_CARD_IMG.search(sCard)
        sYear, sDur, sRating = _card_meta(sCard)
        cards.append({
            'title':     sName,
            'url':       m.group(1),
            'poster':    mImg.group(1) if mImg else '',
            'year':      sYear,
            'plot':      '',
            'rating':    sRating,
            'mediatype': 'movie',
            'is_playable': False,
            'next_func': 'get_hosters',
        })
    return cards


def _next_page_item(sHtml):
    m = _RE_PAGINATION.search(sHtml)
    if not m:
        return None
    sNav = m.group(1)
    mNext = _RE_PAGE_NEXT.search(sNav)
    if not mNext:
        return None
    mCur = _RE_PAGE_CURRENT.search(sNav)
    aNum = [int(x) for x in _RE_PAGE_NUMBER.findall(sNav)]
    sInfo = ''
    if mCur and aNum:
        sInfo = ' [Seite %s / %s]' % (mCur.group(1), max(aNum + [int(mCur.group(1))]))
    return {
        'title':     '[B]Nächste Seite »[/B]' + sInfo,
        'url':       unescape(mNext.group(1)),
        'poster':    '',
        'is_playable': False,
        'next_func': 'showEntries',
    }


def _home_blocks(sHtml):
    blocks = []
    starts = list(re.finditer(r'<section\s+class="([^"]*)"[^>]*>', sHtml))
    for i, m in enumerate(starts):
        iEnd = starts[i + 1].start() if i + 1 < len(starts) else len(sHtml)
        blocks.append((m.group(1), sHtml[m.end():iEnd]))
    return blocks


def _home_rows(sHtml):
    rows = []
    for sCls, sBlock in _home_blocks(sHtml):
        if 'top-strip' in sCls:
            dCover = {}
            for sUrl, sThumb, sName in _RE_HOME_TOPCOVER.findall(sBlock):
                dCover[sUrl] = (unescape(sName).strip(), sThumb)
            for sKey, oLbl, oCard in (('cinema', _RE_HOME_CIN_LBL, _RE_HOME_CIN_CARD),
                                       ('new',    _RE_HOME_NEW_LBL, _RE_HOME_NEW_CARD)):
                mLbl = oLbl.search(sBlock)
                seen = set()
                entries = []
                for sUrl, sInner in oCard.findall(sBlock):
                    if sUrl in seen:
                        continue
                    seen.add(sUrl)
                    sName, sThumb = dCover.get(sUrl, ('', ''))
                    if not sName:
                        mn = re.search(r'<strong>([^<]*)</strong>', sInner)
                        sName = unescape(mn.group(1)).strip() if mn else ''
                    if not sThumb:
                        mt = re.search(r'srcset="([^"]+)"', sInner)
                        sThumb = mt.group(1) if mt else ''
                    if sName:
                        entries.append((sUrl, sName, sThumb))
                if mLbl and entries:
                    rows.append((sKey, unescape(mLbl.group(1)).strip(), entries))
        elif 'movie-list-section' in sCls:
            if 'theme' in sCls:
                aParts = _RE_HOME_THEME_PN.split(sBlock)
                dPanels = dict(zip(aParts[1::2], aParts[2::2]))
                for sKey, sLbl in _RE_HOME_THEME_TB.findall(sBlock):
                    cards = _parse_cards(dPanels.get(sKey, ''))
                    if cards:
                        rows.append(('theme-' + sKey, unescape(sLbl).strip(), [(c['url'], c['title'], c['poster']) for c in cards]))
                continue
            mLbl = _RE_HOME_SEC_LBL.search(sBlock)
            cards = _parse_cards(sBlock)
            if mLbl and cards:
                sKey = 'section-' + sCls.split()[-1]
                rows.append((sKey, unescape(mLbl.group(1)).strip(), [(c['url'], c['title'], c['poster']) for c in cards]))
    return rows


def load(url='', params=None):
    return [
        {'title': 'Startseite',        'url': _URL_MAIN,       'is_playable': False, 'next_func': 'showRows'},
        {'title': 'Alle Filme',         'url': _URL_ARCHIVE,    'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'IMDb-Bewertung',     'url': _URL_IMDB,       'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'Kategorien',         'url': _URL_CATEGORIES, 'is_playable': False, 'next_func': 'showCategories'},
        {'title': 'A-Z',                'url': _URL_LETTERS,    'is_playable': False, 'next_func': 'showLetters'},
        {'title': 'Suche',              'url': '',              'is_playable': False, 'next_func': 'search'},
    ]


def showRows(url='', params=None):
    sHtml = _get(url or _URL_MAIN)
    rows = _home_rows(sHtml)
    if not rows:
        return []
    items = []
    for sKey, sLabel, entries in rows:
        items.append({
            'title':     sLabel,
            'url':       '%s|row=%s' % (_URL_MAIN, sKey),
            'poster':    entries[0][2] if entries else '',
            'is_playable': False,
            'next_func': 'showEntries',
        })
    return items


def showEntries(url='', params=None):
    if not url:
        return []
    row_key = None
    if '|row=' in url:
        url, row_key = url.split('|row=', 1)
    sHtml = _get(url)
    if not sHtml:
        return []
    if row_key:
        for sKey, _, entries in _home_rows(sHtml):
            if sKey == row_key:
                return [{'title': n, 'url': u, 'poster': t,
                         'mediatype': 'movie', 'is_playable': False, 'next_func': 'get_hosters'}
                        for u, n, t in entries]
        return []
    items = _parse_cards(sHtml)
    nxt = _next_page_item(sHtml)
    if nxt:
        items.append(nxt)
    return items


def showCategories(url='', params=None):
    sHtml = _get(_URL_CATEGORIES)
    items = []
    for sCard in _RE_CAT_CARD.findall(sHtml):
        m = _RE_CAT_LINK.search(sCard)
        if not m:
            continue
        mImg = _RE_CAT_IMG.search(sCard)
        items.append({
            'title':     unescape(m.group(2)).strip(),
            'url':       m.group(1),
            'poster':    mImg.group(1) if mImg else '',
            'is_playable': False,
            'next_func': 'showEntries',
        })
    return items


def showLetters(url='', params=None):
    sHtml = _get(_URL_LETTERS)
    items = []
    for sKey, sLabel in _RE_LETTER.findall(sHtml):
        items.append({
            'title':     unescape(sLabel).strip(),
            'url':       '%s?dmt_letter=%s' % (_URL_LETTERS, sKey),
            'is_playable': False,
            'next_func': 'showEntries',
        })
    return items


def search(query='', url='', params=None):
    if not query:
        try:
            import xbmcgui
            query = xbmcgui.Dialog().input('Kellerkino Suche').strip()
        except Exception:
            pass
    if not query:
        return []
    sHtml = _get(_URL_SEARCH % quote_plus(query))
    return _parse_cards(sHtml)


def _extract_hosters_from_url(sDetailUrl):
    sHtml = _get(sDetailUrl)
    if not sHtml:
        return []
    hosters = []
    for sPanel in sHtml.split('data-nfo-player-panel="')[1:]:
        mFrame = _RE_HOSTER_FRAME.search(sPanel)
        if not mFrame:
            continue
        sHosterUrl = mFrame.group(1)
        if 'youtube' in sHosterUrl:
            continue
        mLabel = _RE_HOSTER_LABEL.search(sPanel)
        sLabel = unescape(mLabel.group(1)).strip() if mLabel else 'Hoster'
        hosters.append([sLabel, sHosterUrl, False, '720', ''])
    return hosters


def _og(sHtml, prop):
    m = re.search(r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\']([^"\']*)["\']' % prop, sHtml)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:%s["\']' % prop, sHtml)
    return unescape(m.group(1)).strip() if m else ''


def get_details(url='', params=None):
    sHtml = _get(url)
    if not sHtml:
        return {}
    d = {}
    sDesc = _og(sHtml, 'description')
    if not sDesc:
        mPlot = _RE_DETAIL_PLOT.search(sHtml)
        if mPlot:
            sDesc = unescape(_strip_tags(mPlot.group(1))).strip()
    if sDesc:
        d['plot'] = sDesc
    sImg = _og(sHtml, 'image')
    if sImg:
        d['poster'] = sImg
    return d


def _best_match(cards, title, year):
    title_low = title.lower().strip()
    year_str  = str(year) if year else ''
    for c in cards:
        if c['title'].lower().strip() == title_low:
            if not year_str or not c['year'] or c['year'] == year_str:
                return c['url']
    for c in cards:
        if title_low in c['title'].lower():
            if not year_str or not c['year'] or c['year'] == year_str:
                return c['url']
    for c in cards:
        if title_low in c['title'].lower():
            return c['url']
    return cards[0]['url'] if cards else ''


def get_hosters(title='', year='', season=0, episode=0,
                imdb='', tmdb='', url='', params=None):
    if url and url.startswith('http'):
        log.log('[Kellerkino] get_hosters browse-mode url=%s' % url)
        return _extract_hosters_from_url(url)

    if int(season) > 0:
        return []

    log.log('[Kellerkino] get_hosters scout-mode title="%s" year=%s' % (title, year))
    sHtml = _get(_URL_SEARCH % quote_plus(title))
    if not sHtml:
        return []
    cards = _parse_cards(sHtml)
    if not cards:
        log.log('[Kellerkino] Keine Treffer für "%s"' % title)
        return []
    sDetailUrl = _best_match(cards, title, year)
    if not sDetailUrl:
        return []
    log.log('[Kellerkino] Detail: %s' % sDetailUrl)
    return _extract_hosters_from_url(sDetailUrl)
