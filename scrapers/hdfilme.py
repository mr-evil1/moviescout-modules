# -*- coding: utf-8 -*-
import re
import time
import concurrent.futures
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from resources.lib import multiquest, log
from resources.lib.control import keyboard

SITE_ID       = 'hdfilme'
SITE_NAME     = 'HD Filme'
SITE_DOMAIN   = 'hd-filme.bond'
TYPE          = 'both'
GLOBAL_SEARCH = True

_S_SEARCH   = '__hdfilme_search__'
_last_search = ''

_FF = 158
_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:%d.0) Gecko/20100101 Firefox/%d.0' % (_FF, _FF)

_SKIP_LINK = re.compile(
    r'/vod/vpn|youtube\.com|embed-\.html|/e/\s*$|/e/\s*\"|'
    r'mixdrop\.[a-z]+/e/\s*$|supervideo\.cc/embed-s\.html$',
    re.I
)


def _base():
    return 'https://' + SITE_DOMAIN


def _headers(url, referer=None):
    h = {
        'User-Agent': _UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }
    if referer:
        h['Referer'] = referer
    h['Upgrade-Insecure-Requests'] = '1'
    h['Sec-Fetch-Dest'] = 'document'
    h['Sec-Fetch-Mode'] = 'navigate'
    same = bool(referer) and urlparse(referer).hostname == urlparse(url).hostname
    h['Sec-Fetch-Site'] = 'same-origin' if same else ('cross-site' if referer else 'none')
    h['Sec-Fetch-User'] = '?1'
    h['Priority'] = 'u=0, i'
    return h


def _get(url, referer=None, cookies=True):
    try:
        r = multiquest.get(url, headers=_headers(url, referer), timeout=10, cookies=cookies)
        r.raise_for_status()
        return r.text
    except Exception:
        log.log('[hdfilme] _get fehlgeschlagen: %s' % url)
        log.error()
        return ''


def _post_headers(referer):
    h = _headers(_base() + '/index.php', referer)
    h['Content-Type'] = 'application/x-www-form-urlencoded'
    h['Origin'] = _base()
    h['Sec-Fetch-Site'] = 'same-origin'
    return h


def _post(data, referer=None, cookies=True, path='/'):
    try:
        r = multiquest.post(_base() + path, data=data, headers=_post_headers(referer or _base() + '/'), timeout=10, cookies=cookies)
        r.raise_for_status()
        return r.text
    except Exception:
        log.log('[hdfilme] _post fehlgeschlagen: %s' % data.get('story', ''))
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


def _clean_plot(raw):
    text = re.sub(r'<[^>]+>', '', raw).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def _normalise_link(link):
    link = link.strip()
    if link.startswith('//'):
        link = 'https:' + link
    elif link.startswith('/') or not link.startswith('http'):
        link = _base() + '/' + link.lstrip('/')
    return link


def _hosters_from_section(section):
    result = []
    seen = set()
    for full_li in re.findall(r'<li[^>]*(?:data-link=\"[^\"]*\")?[^>]*>.*?</li>', section, re.S | re.I):
        link_m = re.search(r'data-link=\"([^\"]+)\"', full_li)
        if not link_m:
            continue
        raw_link = link_m.group(1)
        if _SKIP_LINK.search(raw_link):
            continue
        if raw_link in seen:
            continue
        seen.add(raw_link)
        link  = _normalise_link(raw_link)
        body  = re.sub(r'<[^>]+>', '', full_li)
        label = re.sub(r'\s+', ' ', body).strip() or 'Hoster'
        qual  = _quality_from_text(label)
        result.append((label, link, qual))
    return result


def _extract_plot_from_html(html):
    m = re.search(r'<div[^>]*class=\"[^\"]*col-md-12[^\"]*nopadding[^\"]*\"[^>]*>\s*<p>(.*?)</p>', html, re.S | re.I)
    if m:
        return _clean_plot(m.group(1))
    m = re.search(r'<meta[^>]*name=\"description\"[^>]*content=\"([^\"]{30,})\"', html, re.I)
    if m:
        return m.group(1).strip()
    return ''


def _extract_hosters_from_page(page_url):
    html   = _get(page_url, _base())
    result = _hosters_from_section(html)
    plot   = _extract_plot_from_html(html)
    return result, plot


def _get_user_hash():
    html = _get(_base())
    m = re.search(r"dle_login_hash\s*=\s*'([a-f0-9]+)'", html, re.I)
    return m.group(1) if m else ''


def _search_url(query):
    from urllib.parse import quote
    return _base() + '/index.php?do=search&subaction=search&story=' + quote(query, safe='')


def _warmup():
    try:
        if multiquest.get_cookie(_base(), 'PHPSESSID'):
            return
    except Exception:
        pass
    _get(_base() + '/')


def _search_form(query, page=1, per_page=0):
    d = {
        'story': query,
        'do': 'search',
        'subaction': 'search',
    }
    if page > 1:
        d['search_start'] = str(page)
        d['full_search'] = '0'
        d['result_from'] = str((page - 1) * per_page + 1)
    return d


def _search_ajax(query, is_global=False):
    _warmup()
    html = _post(_search_form(query))
    if html:
        items = _parse_articles(html)
        if items:
            items += _fetch_more_search_pages(query, per_page=len(items), is_global=is_global, use_post=True)
            return items
    url  = _search_url(query)
    html = _get(url, referer=_base())
    if not html:
        return []
    items = _parse_articles(html)
    items += _fetch_more_search_pages(url, is_global=is_global)
    return items


_RETRY_PAUSE = 0.6


def _fetch_search_page(base, page, fresh=False, per_page=0, use_post=False):
    if use_post:
        html = _post(_search_form(base, page, per_page), cookies=fresh, path='/index.php')
    else:
        sep = '&' if '?' in base else '?'
        url = '%s%ssearch_start=%d' % (base, sep, page)
        html = _get(url, referer=_base(), cookies=fresh)
    if not html:
        return [], False
    return _parse_articles(html), True


def _fetch_more_search_pages(base_url, is_global=False, batch=4, per_page=0, use_post=False):
    max_pages = 5 if is_global else 10
    d_pages   = {}
    retry     = []
    end       = None
    page      = 2
    while page <= max_pages:
        pages_batch = list(range(page, min(page + batch, max_pages + 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pages_batch)) as pool:
            results = list(pool.map(lambda p: _fetch_search_page(base_url, p, False, per_page, use_post), pages_batch))
        for num, (rows, reached) in zip(pages_batch, results):
            if not reached:
                retry.append(num)
            elif rows:
                d_pages[num] = rows
            else:
                time.sleep(_RETRY_PAUSE)
                rows2, reached2 = _fetch_search_page(base_url, num, True, per_page, use_post)
                if reached2 and not rows2:
                    end = num
                    break
                if rows2:
                    log.log('[hdfilme] search retry: page %d recovered, %d hits' % (num, len(rows2)))
                    d_pages[num] = rows2
                else:
                    log.log('[hdfilme] search retry: page %d unconfirmed, skipped' % num)
        if end is not None:
            break
        page += batch
    if end is not None:
        retry = [p for p in retry if p < end]
    for num in retry:
        time.sleep(_RETRY_PAUSE)
        rows, reached = _fetch_search_page(base_url, num, True, per_page, use_post)
        if rows:
            log.log('[hdfilme] search retry: page %d recovered, %d hits' % (num, len(rows)))
            d_pages[num] = rows
        else:
            log.log('[hdfilme] search retry: page %d still unreachable' % num)
    all_items = []
    for num in sorted(d_pages):
        all_items.extend(d_pages[num])
    return all_items


def _find_page_url(title, year, season=0):
    year_str = str(year or '')
    results  = _search_ajax(title)
    best     = ''
    for item in results:
        if _cleantitle(item['title']) not in _cleantitle(title) and _cleantitle(title) not in _cleantitle(item['title']):
            continue
        if year_str and season == 0 and item.get('year', '') and item['year'] != year_str:
            if not best:
                best = item['url']
            continue
        return item['url']
    return best


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base())
    result = {}
    plot = _extract_plot_from_html(html)
    if plot:
        result['plot'] = plot
    y = re.search(r'<meta[^>]*itemprop=\"datePublished\"[^>]*content=\"(\d{4})', html, re.I)
    if not y:
        ym = re.search(r'<p[^>]*class=\"[^\"]*text-capitalize[^\"]*\"[^>]*>([^<]+)', html, re.I)
        if ym:
            y = re.search(r'(\d{4})', ym.group(1))
    if y:
        result['year'] = y.group(1)
    pm = re.search(r'<img[^>]*class=\"[^\"]*img[^\"]*\"[^>]*data-src=\"([^\"]+)\"', html, re.I)
    if not pm:
        pm = re.search(r'<img[^>]*class=\"[^\"]*poster[^\"]*\"[^>]*src=\"([^\"]+)\"', html, re.I)
    if pm:
        result['poster'] = pm.group(1) if pm.group(1).startswith('http') else _base() + pm.group(1)
    return result


def _episode_hosters_from_html(html, season, episode, anchor=None):
    if anchor:
        m = re.search(re.escape(anchor) + r'.*?(<ul[^>]*>.*?</ul>)', html, re.S)
        if m:
            return _hosters_from_section(m.group(1))
    pat = r'id=\"serie-%d_%d\"(.*?)(?=<li\s+id=\"serie-\d|$)' % (season, episode)
    m   = re.search(pat, html, re.S)
    if not m:
        pat2 = r'id=\"serie-1_%d\"(.*?)(?=<li\s+id=\"serie-1_\d|$)' % episode
        m    = re.search(pat2, html, re.S)
    if not m:
        return []
    return _hosters_from_section(m.group(1))


def get_seasons(url='', params=None):
    html = _get(url, _base())
    if not html:
        return []
    staffel_m = re.search(r'Staffel\s*(\d+)', html, re.I)
    if staffel_m:
        s = int(staffel_m.group(1))
        return [{'title': 'Staffel %d' % s, 'url': url, 'season': s, 'episode': 0, 'next_func': 'get_episodes', 'is_playable': False}]
    season_nums = sorted(set(int(m) for m in re.findall(r'id=\"serie-(\d+)_\d+\"', html)))
    if not season_nums:
        return []
    return [
        {
            'title':       'Staffel %d' % s,
            'url':         url,
            'season':      s,
            'episode':     0,
            'next_func':   'get_episodes',
            'is_playable': False,
        }
        for s in season_nums
    ]


def get_episodes(url='', params=None):
    season = int((params or {}).get('season', 1))
    html   = _get(url, _base())
    if not html:
        return []
    log.log('[hdfilme] get_episodes: html len=%d' % len(html))
    anchors1 = re.findall(r'\"><a href=\"#\">([^<]+)', html)
    anchors2 = re.findall(r'<a[^>]+href=\"#\"[^>]*>([^<]+)', html)
    anchors  = anchors1 or anchors2
    if anchors:
        return [
            {
                'title':          name.strip(),
                'url':            url,
                'season':         season,
                'episode':        i + 1,
                'episode_anchor': name.strip(),
                'next_func':      'get_hosters',
                'is_playable':    False,
            }
            for i, name in enumerate(anchors)
        ]
    ep_nums = sorted(set(int(m) for m in re.findall(r'id=\"serie-%d_(\d+)\"' % season, html)))
    if not ep_nums:
        return []
    return [
        {
            'title':       'Episode %d' % e,
            'url':         url,
            'season':      season,
            'episode':     e,
            'next_func':   'get_hosters',
            'is_playable': False,
        }
        for e in ep_nums
    ]


def _resolve_sirius(hurl):
    html = _get(hurl)
    if not html:
        return []
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    return _hosters_from_section(html)


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season  = int(season  or (params or {}).get('season',  0))
    episode = int(episode or (params or {}).get('episode', 0))
    if url:
        if season > 0:
            anchor = (params or {}).get('episode_anchor', '')
            html   = _get(url, _base())
            raw    = _episode_hosters_from_html(html, season, episode, anchor)
            if not raw:
                raw, _ = _extract_hosters_from_page(url)
        else:
            raw, _ = _extract_hosters_from_page(url)
    elif season == 0 and imdb:
        html = _get('https://meinecloud.click/movie/%s' % imdb)
        raw  = _hosters_from_section(html)
    elif season > 0 and imdb:
        anchor   = (params or {}).get('episode_anchor', '')
        imdb_num = re.sub(r'[^0-9]', '', imdb)
        html     = _get('https://meinecloud.click/serial/%s' % imdb_num)
        raw      = _episode_hosters_from_html(html, season, episode, anchor)
        if not raw:
            html = _get('https://meinecloud.click/serial/%s' % imdb)
            raw  = _episode_hosters_from_html(html, season, episode, anchor)
    else:
        page_url = _find_page_url(title, year, season)
        if not page_url:
            return []
        html = _get(page_url, _base())
        if season > 0:
            anchor = (params or {}).get('episode_anchor', '')
            raw = _episode_hosters_from_html(html, season, episode, anchor)
        else:
            raw = _hosters_from_section(html)

    result = []
    for name, hurl, quality in raw:
        if re.search(r'meinecloud\.click/', hurl, re.I):
            for sub_name, sub_url, sub_qual in _resolve_sirius(hurl):
                result.append((sub_name, sub_url, False, sub_qual, 'de'))
        else:
            result.append((name, hurl, False, quality, 'de'))
    return result


def load(url='', params=None):
    if url:
        return _browse_entries(url)
    b = _base()
    return [
        {'title': 'Neu',               'url': b + '/kinofilme-online/',           'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',              'url': b + '/aktuelle-kinofilme-im-kino/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Demnächst im Kino', 'url': b + '/demnachst/',                  'next_func': 'load', 'is_playable': False},
        {'title': 'Serien',            'url': b + '/serienstream-deutsch/',        'next_func': 'load', 'is_playable': False},
        {'title': 'Genres',            'url': 'genres',                           'next_func': 'load', 'is_playable': False},
        {'title': 'Nach Jahr',         'url': 'jahre',                            'next_func': 'load', 'is_playable': False},
        {'title': 'Nach Land',         'url': 'laender',                          'next_func': 'load', 'is_playable': False},
        {'title': '[B]Suche[/B]',      'url': _S_SEARCH,                          'next_func': 'load', 'is_playable': False},
    ]


def _load_genres(b):
    return [
        {'title': 'Action',        'url': b + '/action/',                  'next_func': 'load', 'is_playable': False},
        {'title': 'Komödie',       'url': b + '/komodie/',                 'next_func': 'load', 'is_playable': False},
        {'title': 'Thriller',      'url': b + '/thriller/',                'next_func': 'load', 'is_playable': False},
        {'title': 'Horror',        'url': b + '/horror/',                  'next_func': 'load', 'is_playable': False},
        {'title': 'Romantik',      'url': b + '/romantik/',                'next_func': 'load', 'is_playable': False},
        {'title': 'Anime',         'url': b + '/xfsearch/Anime',           'next_func': 'load', 'is_playable': False},
        {'title': 'Dokumentarfilm','url': b + '/xfsearch/Dokumentarfilm',  'next_func': 'load', 'is_playable': False},
        {'title': 'Animation',     'url': b + '/xfsearch/Animation',       'next_func': 'load', 'is_playable': False},
        {'title': 'Fantasy',       'url': b + '/xfsearch/Fantasy',         'next_func': 'load', 'is_playable': False},
        {'title': 'Science-Fiction','url': b + '/xfsearch/Science-Fiction','next_func': 'load', 'is_playable': False},
        {'title': 'Abenteuer',     'url': b + '/xfsearch/Abenteuer',       'next_func': 'load', 'is_playable': False},
        {'title': 'Krimi',         'url': b + '/xfsearch/Krimi',           'next_func': 'load', 'is_playable': False},
        {'title': 'Drama',         'url': b + '/xfsearch/Drama',           'next_func': 'load', 'is_playable': False},
        {'title': 'Familie',       'url': b + '/xfsearch/Familie',         'next_func': 'load', 'is_playable': False},
        {'title': 'Biografie',     'url': b + '/xfsearch/Biografie',       'next_func': 'load', 'is_playable': False},
    ]


def _load_jahre(b):
    return [
        {'title': str(y), 'url': b + '/xfsearch/%d' % y, 'next_func': 'load', 'is_playable': False}
        for y in range(2026, 2013, -1)
    ]


def _load_laender(b):
    return [
        {'title': 'USA',                    'url': b + '/xfsearch/Vereinigte Staaten/',    'next_func': 'load', 'is_playable': False},
        {'title': 'Deutschland',            'url': b + '/xfsearch/Deutschland',            'next_func': 'load', 'is_playable': False},
        {'title': 'Vereinigtes Königreich', 'url': b + '/xfsearch/Vereinigtes Königreich','next_func': 'load', 'is_playable': False},
        {'title': 'Japan',                  'url': b + '/xfsearch/Japan/',                 'next_func': 'load', 'is_playable': False},
        {'title': 'Austria',                'url': b + '/xfsearch/Austria',                'next_func': 'load', 'is_playable': False},
    ]


def _parse_articles(html):
    items    = []
    articles = re.findall(r'<div class=\"box-product(.*?)</li>', html, re.S)
    if not articles:
        articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.S)
    if not articles:
        articles = re.findall(r'<li[^>]*class=\"[^\"]*item[^\"]*\"[^>]*>(.*?)</li>', html, re.S)
    for article in articles:
        url_m = re.search(r'href=\"([^\"]+)\"[^>]*title=\"([^\"]+)\"', article, re.I)
        if url_m:
            s_url  = url_m.group(1)
            s_name = url_m.group(2)
        else:
            url_m = re.search(r'href=\"([^\"]+)\"', article, re.I)
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
        thumb_m = (re.search(r'data-src=\"(/files/[^\"]+)\"', article, re.I) or
                   re.search(r'data-src=\"(/uploads/[^\"]+)\"', article, re.I) or
                   re.search(r'data-src=\"([^\"]+)\"', article, re.I) or
                   re.search(r'src=\"(/files/[^\"]+)\"', article, re.I))
        thumb = thumb_m.group(1) if thumb_m else ''
        if thumb.startswith('/'):
            thumb = _base() + thumb
        year_m     = re.search(r'text-capitalize[^>]+>\s*[^<]*?(\d{4})\s*<', article, re.I)
        year       = year_m.group(1).strip() if year_m else ''
        staffel_m  = re.search(r'^(.*?)\s*[-–]\s*Staffel\s*(\d+)', s_name, re.I)
        season_num = int(staffel_m.group(2)) if staffel_m else 0
        is_tv      = staffel_m is not None or bool(re.search(r'season|serie', s_name, re.I))
        if staffel_m and season_num:
            next_func = 'get_episodes'
        elif is_tv:
            next_func = 'get_seasons'
        else:
            next_func = 'get_hosters'
        items.append({
            'title':       s_name,
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'season':      season_num,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   next_func,
            'is_playable': False,
        })
    return items


def _browse_entries(url):
    b = _base()

    if url == 'genres':
        return _load_genres(b)
    if url == 'jahre':
        return _load_jahre(b)
    if url == 'laender':
        return _load_laender(b)
    if url == _S_SEARCH:
        global _last_search
        kb = keyboard(_last_search, 'HD Filme Suche')
        kb.doModal()
        if not kb.isConfirmed():
            return []
        query = kb.getText().strip()
        if not query:
            return []
        _last_search = query
        return search(query=query)

    html  = _get(url)
    if not html:
        log.log('hdfilme _browse_entries: leere Antwort für %s' % url, log.LOGWARNING)
        return []
    items = _parse_articles(html)

    next_m = re.search(r'href=\"([^\"]+)\">(?:›|&rsaquo;|Next|Weiter)</a>', html, re.I)
    if not next_m:
        next_m = re.search(r'class=\"[^\"]*next[^\"]*\"[^>]*href=\"([^\"]+)\"', html, re.I)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        page_info = ''
        pag_m = re.search(r'class=\"[^\"]*pagination[^\"]*\"(.*?)</div>', html, re.S | re.I)
        if pag_m:
            cur_m  = re.search(r'<span[^>]*>(\d+)</span>', pag_m.group(1))
            pages  = [int(x) for x in re.findall(r'>(\d{1,6})<', pag_m.group(1))]
            if cur_m and pages:
                page_info = ' [Seite %s / %d]' % (cur_m.group(1), max(pages))
        items.append({'title': '[B]>>> Weiter[/B]' + page_info, 'url': next_url, 'next_func': 'load', 'is_playable': False})

    return items


def search(query='', params=None, is_global=False):
    return _search_ajax(query, is_global=is_global)
