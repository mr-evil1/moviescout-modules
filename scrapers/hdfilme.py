# -*- coding: utf-8 -*-
import re
from urllib.request import Request, urlopen
from resources.lib import multiquest, log

SITE_ID       = 'hdfilme'
SITE_NAME     = 'HD Filme'
SITE_DOMAIN   = 'hdfilme1.co'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_SKIP_LINK = re.compile(
    r'/vod/vpn|youtube\.com|embed-\.html|/e/\s*$|/e/\s*\"|'
    r'mixdrop\.[a-z]+/e/\s*$|supervideo\.cc/embed-s\.html$',
    re.I
)


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


def _search_ajax(query):
    from urllib.parse import urlencode as _urlencode
    user_hash = _get_user_hash()
    if not user_hash:
        return []
    url = _base() + '/engine/ajax/controller.php?mod=search'
    payload = _urlencode({'query': query, 'user_hash': user_hash}).encode('utf-8')
    try:
        req = Request(url, data=payload, headers={
            'User-Agent': _UA,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': _base(),
            'X-Requested-With': 'XMLHttpRequest',
        })
        import urllib.request as _urllib_request
        with _urllib_request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception:
        log.error()
        return []
    items = []
    for href, title, plot in re.findall(
        r'<a\s+href=\"([^\"]+)\"[^>]*>\s*<span[^>]*class=\"searchheading\"[^>]*>([^<]+)</span>\s*<span>([^<]*)</span>',
        html, re.I
    ):
        s_name = re.sub(r'\s+stream\s*$', '', title.strip(), flags=re.I).strip()
        staffel_m  = re.search(r'^(.*?)\s*[-–]\s*Staffel\s*(\d+)', s_name, re.I)
        season_num = int(staffel_m.group(2)) if staffel_m else 0
        is_tv      = staffel_m is not None
        if staffel_m and season_num:
            next_func = 'get_episodes'
        elif is_tv:
            next_func = 'get_seasons'
        else:
            next_func = 'get_hosters'
        items.append({
            'title':       s_name,
            'url':         href if href.startswith('http') else _base() + '/' + href.lstrip('/'),
            'season':      season_num,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   next_func,
            'is_playable': False,
        })
    return items


def _find_page_url(title, year, season=0):
    results = _search_ajax(title)
    for item in results:
        if _cleantitle(item['title']) not in _cleantitle(title) and _cleantitle(title) not in _cleantitle(item['title']):
            continue
        return item['url']
    return ''


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
                result.append((sub_name, sub_url, False, sub_qual, ''))
        else:
            result.append((name, hurl, False, quality, ''))
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


def _browse_entries(url):
    b = _base()

    if url == 'genres':
        return _load_genres(b)
    if url == 'jahre':
        return _load_jahre(b)
    if url == 'laender':
        return _load_laender(b)

    html  = _get(url)
    if not html:
        log.log('hdfilme _browse_entries: leere Antwort für %s' % url, log.LOGWARNING)
        return []
    items = []

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

        year_m = re.search(r'text-capitalize[^>]+>\s*[^<]*?(\d{4})\s*<', article, re.I)
        year   = year_m.group(1).strip() if year_m else ''

        staffel_m  = re.search(r'^(.*?)\s*[-–]\s*Staffel\s*(\d+)', s_name, re.I)
        season_num = int(staffel_m.group(2)) if staffel_m else 0
        is_tv      = staffel_m is not None or bool(re.search(r'season|serie', s_name, re.I))

        if staffel_m and season_num:
            next_func = 'get_episodes'
        elif is_tv:
            next_func = 'get_seasons'
        else:
            next_func = 'get_hosters'

        item = {
            'title':       s_name,
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'season':      season_num,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   next_func,
            'is_playable': False,
        }
        items.append(item)

    next_m = re.search(r'href=\"([^\"]+)\">(?:›|&rsaquo;|Next|Weiter)</a>', html, re.I)
    if not next_m:
        next_m = re.search(r'class=\"[^\"]*next[^\"]*\"[^>]*href=\"([^\"]+)\"', html, re.I)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({'title': '[B]>>> Weiter[/B]', 'url': next_url, 'next_func': 'load', 'is_playable': False})

    return items


def search(query='', params=None):
    return _search_ajax(query)
