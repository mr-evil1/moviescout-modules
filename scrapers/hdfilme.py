# -*- coding: utf-8 -*-
#2
import re
from resources.lib import multiquest, log

SITE_ID       = 'hdfilme'
SITE_NAME     = 'HD Filme'
SITE_DOMAIN   = 'hdfilme1.co'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _cleantitle(s):
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def _quality_from_text(text):
    t = text.upper()
    if '2160' in t or '4K' in t:
        return '4K'
    if '1080' in t:
        return '1080p'
    if '720' in t:
        return '720p'
    return 'HD'


def _try_resolve(url):
    return url, False


def _clean_plot(raw):
    text = re.sub(r'<[^>]+>', '', raw).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def _hoster_name(url):
    try:
        from urllib.parse import urlparse
        host = urlparse(url if url.startswith('http') else 'https:' + url).netloc
        return re.sub(r'^www\.', '', host).split('.')[0].capitalize() or 'Hoster'
    except Exception:
        return 'Hoster'


def _extract_hosters_from_page(page_url):
    html   = _get(page_url, _base())
    result = []
    for link in re.findall(r'data-link="([^"]+)', html):
        if not link.startswith('http'):
            link = 'https:' + link
        result.append((_hoster_name(link), link, 'HD'))
    plot = ''
    p = re.search(r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I)
    if p:
        plot = _clean_plot(p.group(1))
    return result, plot


def _find_page_url(title, year, season=0):
    from urllib.parse import quote as _quote
    search_url = _base() + '/index.php?do=search&subaction=search&story=%s' % _quote(title)
    html = _get(search_url)
    for s_url, s_title, s_year in re.findall(
        r'class="thumb".*?href="([^"]+)".*?title="([^"]+)".*?_year">([^<]+)', html, re.S
    ):
        if _cleantitle(s_title) not in _cleantitle(title) and _cleantitle(title) not in _cleantitle(s_title):
            continue
        if season == 0 and year and s_year.strip() != str(year):
            continue
        return s_url
    return ''


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base())
    result = {}
    p = re.search(r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I)
    if p:
        result['plot'] = _clean_plot(p.group(1))
    y = re.search(r'_year">(\d{4})', html, re.I)
    if y:
        result['year'] = y.group(1)
    pm = re.search(r'<img[^>]*class="[^"]*poster[^"]*"[^>]*src="([^"]+)"', html, re.I)
    if pm:
        result['poster'] = pm.group(1) if pm.group(1).startswith('http') else _base() + pm.group(1)
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        raw, _ = _extract_hosters_from_page(url)
    elif season == 0 and imdb:
        html = _get('https://meinecloud.click/movie/%s' % imdb)
        raw  = []
        for link in re.findall(r'data-link="([^"]+)', html):
            if not link.startswith('http'):
                link = 'https:' + link
            raw.append((_hoster_name(link), link, 'HD'))
    else:
        page_url = _find_page_url(title, year, season)
        if not page_url:
            return []
        html   = _get(page_url)
        ep_key = '%sx%s' % (season, episode)
        m      = re.search(r'data-num="%s"(.*?)(?:data-num="|$)' % re.escape(ep_key), html, re.S)
        raw    = []
        if m:
            for link in re.findall(r'data-link="([^"]+)', m.group(0)):
                if not link.startswith('http'):
                    link = 'https:' + link
                raw.append((_hoster_name(link), link, 'HD'))
    result = []
    for name, hurl, quality in raw:
        resolved_url, is_resolved = _try_resolve(hurl)
        result.append((name, resolved_url, is_resolved))
    return result


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    b = _base()
    return [
        {'title': 'Neu',    'url': b + '/kinofilme-online/',           'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',   'url': b + '/aktuelle-kinofilme-im-kino/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': b + '/serienstream-deutsch/',       'next_func': 'load', 'is_playable': False},
        {'title': 'Suche',  'url': '',                                  'next_func': 'search', 'is_playable': False},
    ]


def _browse_entries(url):
    html  = _get(url)
    if not html:
        log.log('hdfilme _browse_entries: leere Antwort für %s' % url, log.LOGWARNING)
        return []
    items = []

    articles = re.findall(r'<div class="box-product(.*?)</li>', html, re.S)
    if not articles:
        articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.S)
    if not articles:
        articles = re.findall(r'<li[^>]*class="[^"]*item[^"]*"[^>]*>(.*?)</li>', html, re.S)

    log.log('hdfilme _browse_entries: %d Artikel gefunden für %s' % (len(articles), url))

    for article in articles:
        url_m = re.search(r'href="([^"]+)"[^>]*title="([^"]+)"', article, re.I)
        if url_m:
            s_url  = url_m.group(1)
            s_name = url_m.group(2)
        else:
            url_m = re.search(r'href="([^"]+)"', article, re.I)
            if not url_m:
                continue
            s_url  = url_m.group(1)
            h3_m   = re.search(r'<h3[^>]*>(.*?)</h3>', article, re.S | re.I)
            s_name = re.sub(r'<[^>]+>', '', h3_m.group(1)).strip() if h3_m else ''

        if not s_name or not s_url:
            continue
        s_name = re.sub(r'\s+stream\s*$', '', s_name, flags=re.I).strip()
        if not s_name:
            continue
        if s_url.startswith('//'):
            s_url = 'https:' + s_url
        elif not s_url.startswith('http'):
            s_url = _base() + '/' + s_url.lstrip('/')

        thumb_m = (re.search(r'data-src="(/files/[^"]+)"', article, re.I) or
                   re.search(r'data-src="([^"]+)"', article, re.I) or
                   re.search(r'src="(/files/[^"]+)"', article, re.I))
        thumb = thumb_m.group(1) if thumb_m else ''
        if thumb.startswith('/'):
            thumb = _base() + thumb

        year_m = re.search(r'_year">([^<]+)', article)
        year   = year_m.group(1).strip() if year_m else ''

        plot = ''
        plot_m = re.search(r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>', article, re.S | re.I)
        if not plot_m:
            plot_m = re.search(r'<p[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</p>', article, re.S | re.I)
        if not plot_m:
            plot_m = re.search(r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>', article, re.S | re.I)
        if plot_m:
            plot = _clean_plot(plot_m.group(1))

        is_tv  = bool(re.search(r'staffel|season|serie', s_name, re.I))

        item = {
            'title':       s_name,
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        if plot:
            item['plot'] = plot
        items.append(item)

    next_m = re.search(r'href="([^"]+)">(?:›|&rsaquo;|Next|Weiter)</a>', html, re.I)
    if not next_m:
        next_m = re.search(r'class="[^"]*next[^"]*"[^>]*href="([^"]+)"', html, re.I)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({'title': '[B]>>> Weiter[/B]', 'url': next_url, 'next_func': 'load', 'is_playable': False})

    log.log('hdfilme _browse_entries: %d Items zurückgegeben' % len(items))
    return items


def search(query='', params=None):
    from urllib.parse import quote as _quote
    url = _base() + '/index.php?do=search&subaction=search&story=%s' % _quote(query)
    return _browse_entries(url)
