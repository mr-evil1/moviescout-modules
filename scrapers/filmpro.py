# -*- coding: utf-8 -*-
import re
import html as _html
from urllib.parse import quote
from resources.lib import multiquest, log

SITE_ID       = 'filmpro'
SITE_NAME     = 'FilmPro'
SITE_DOMAIN   = 'filmpalast.one'
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
    s = (s or '').lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


def _clean_plot(raw):
    text = re.sub(r'<[^>]+>', '', raw).strip()
    text = _html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^(?:Beschreibung|Description|Inhalt|Plot)\s*:\s*', '', text, flags=re.I)
    text = re.sub(r'\{[^}]+\}', '', text).strip()
    return text


def _extract_plot(html):
    patterns = [
        r'<div[^>]*class=\"[^\"]*Description[^\"]*\"[^>]*>(.*?)</div>',
        r'<(?:span|p|div)[^>]*itemprop=\"description\"[^>]*>(.*?)</(?:span|p|div)>',
        r'<meta[^>]*itemprop=\"description\"[^>]*content=\"([^\"]+)\"',
        r'<p[^>]*class=\"[^\"]*sescri[^\"]*\"[^>]*>(.*?)</p>',
        r'<div[^>]*class=\"[^\"]*sescri[^\"]*\"[^>]*>(.*?)</div>',
        r'<div[^>]*class=\"[^\"]*full-text[^\"]*\"[^>]*>(.*?)</div>',
        r'<div[^>]*class=\"[^\"]*plot[^\"]*\"[^>]*>(.*?)</div>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.S | re.I)
        if m:
            plot = _clean_plot(m.group(1))
            if len(plot) > 20:
                return plot
    return ''


def _extract_poster(html):
    for pat in (
        r'<img[^>]*class=\"[^\"]*poster[^\"]*\"[^>]*src=\"([^\"]+)\"',
        r'<img[^>]*src=\"([^\"]+)\"[^>]*class=\"[^\"]*poster[^\"]*\"',
        r'<img[^>]*(?:data-src|src)=\"(/uploads/[^\"]+)\"',
    ):
        m = re.search(pat, html, re.I)
        if m:
            src = m.group(1)
            if src.startswith('/'):
                src = _base() + src
            return src
    return ''


def get_details(url='', params=None):
    if not url:
        return {}
    html = _get(url, _base())
    result = {}
    plot = _extract_plot(html)
    if plot:
        result['plot'] = plot
    y = (re.search(r'class=\"Year\"[^>]*>(\d{4})', html, re.I) or
         re.search(r'itemprop=\"dateCreated\"[^>]*>(\d{4})', html, re.I))
    if y:
        result['year'] = y.group(1)
    poster = _extract_poster(html)
    if poster:
        result['poster'] = poster
    r = re.search(r'itemprop=\"ratingValue\"[^>]*>([^<]+)', html, re.I)
    if r:
        try:
            result['rating'] = float(r.group(1).strip().replace(',', '.'))
        except Exception:
            pass
    return result


def _imdb_from_page(url):
    html = _get(url, _base())
    for pat in (
        r"meinecloud\.click/(?:ddl|movie|serial)/(tt\d+)",
        r"imdb\.com/title/(tt\d+)",
        r"id_imdb=(tt\d+)",
        r"var\s+imdb\s*=\s*['\"]+(tt\d+)['\"]",
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return ''


def _cloud_to_hosters(cloud_list):
    result = []
    for entry in cloud_list:
        name = entry[0] if len(entry) > 0 else SITE_NAME
        link = entry[1] if len(entry) > 1 else ''
        if not link:
            continue
        result.append((name, link, False, 'HD', 'de'))
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    from resources.lib import cloud
    if params:
        season  = params.get('season',  season)
        episode = params.get('episode', episode)
    season  = int(season  or 0)
    episode = int(episode or 0)

    if season > 0 and url and ('dr0pstream.com' in url or 'dropcdn' in url):
        return [(SITE_NAME, url, False, 'HD', 'de')]

    clean_url = url
    for prefix in (_S_SEASONS, _S_EPISODES):
        if clean_url.startswith(prefix):
            clean_url = clean_url[len(prefix):]
            break

    if not imdb and clean_url:
        imdb = _imdb_from_page(clean_url)

    if not imdb:
        return []

    if season == 0:
        return _cloud_to_hosters(cloud.get_movie(imdb))

    return _cloud_to_hosters(cloud.get_episode(imdb, season, episode))


_S_FILME    = '__fp_filme__'
_S_SERIEN   = '__fp_serien__'
_S_GENRES   = '__fp_genres__'
_S_JAHRE    = '__fp_jahre__'
_S_LAENDER  = '__fp_laender__'
_S_AZ       = '__fp_az__'
_S_SEASONS  = '__fp_seasons__:'
_S_EPISODES = '__fp_episodes__:'


def _filme_menu():
    b = _base()
    return [
        {'title': 'Neueste',    'url': b + '/filme/',      'next_func': 'load', 'is_playable': False},
        {'title': 'Kinofilme',  'url': b + '/kinofilme/',  'next_func': 'load', 'is_playable': False},
        {'title': 'Familie',    'url': b + '/familie/',    'next_func': 'load', 'is_playable': False},
        {'title': 'Genres',     'url': _S_GENRES,          'next_func': 'load', 'is_playable': False},
        {'title': 'Jahr',       'url': _S_JAHRE,           'next_func': 'load', 'is_playable': False},
        {'title': 'Land',       'url': _S_LAENDER,         'next_func': 'load', 'is_playable': False},
    ]


def _serien_menu():
    b = _base()
    return [
        {'title': 'Neueste', 'url': b + '/serien/', 'next_func': 'load', 'is_playable': False},
        {'title': 'Genres',  'url': _S_GENRES,      'next_func': 'load', 'is_playable': False},
        {'title': 'Jahr',    'url': _S_JAHRE,        'next_func': 'load', 'is_playable': False},
    ]


def _genres_menu():
    b = _base()
    genres = [
        ('Action',        'action'),
        ('Abenteuer',     'abenteuer'),
        ('Animation',     'animation'),
        ('Comedy',        'komodie'),
        ('Drama',         'drama'),
        ('Familie',       'familie'),
        ('Fantasy',       'fantasy'),
        ('Horror',        'horror'),
        ('Krimi',         'krimi'),
        ('Romantik',      'romantik'),
        ('Sci-Fi',        'sci-fi'),
        ('Thriller',      'thriller'),
        ('Western',       'western'),
        ('Dokumentation', 'dokumentation'),
    ]
    return [
        {'title': name, 'url': b + '/%s/' % slug,
         'next_func': 'load', 'is_playable': False}
        for name, slug in genres
    ]


def _jahre_menu():
    import datetime
    b    = _base()
    year = datetime.datetime.now().year
    return [
        {'title': str(y), 'url': b + '/xfsearch/%d' % y,
         'next_func': 'load', 'is_playable': False}
        for y in range(year, year - 15, -1)
    ]


def _laender_menu():
    b = _base()
    countries = [
        ('Deutschland',   '/xfsearch/deutschland'),
        ('USA',           '/xfsearch/USA'),
        ('Großbritannien','/xfsearch/country/United Kingdom/'),
        ('Frankreich',    '/xfsearch/country/frankreich/'),
        ('Japan',         '/xfsearch/country/Japan/'),
        ('Südkorea',      '/xfsearch/country/South Korea/'),
        ('Österreich',    '/xfsearch/country/Austria/'),
        ('Italien',       '/xfsearch/country/italien/'),
        ('Spanien',       '/xfsearch/country/spanien/'),
        ('Kanada',        '/xfsearch/country/Canada/'),
        ('Australien',    '/xfsearch/country/Australia/'),
        ('Indien',        '/xfsearch/country/India/'),
    ]
    return [
        {'title': name, 'url': b + path,
         'next_func': 'load', 'is_playable': False}
        for name, path in countries
    ]


def _az_menu():
    b = _base()
    items = [{'title': '#', 'url': b + '/catalog/other/', 'next_func': 'load', 'is_playable': False}]
    for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        items.append({'title': ch, 'url': b + '/catalog/%s/' % ch.lower(), 'next_func': 'load', 'is_playable': False})
    return items


def _parse_articles(html, force_series=False):
    items = []
    for article in re.findall(r'<article[^>]*>(.*?)</article>', html, re.S | re.I):
        a_m = re.search(r'<a[^>]+href=\"(https?://[^\"]+)\"', article, re.I)
        if not a_m:
            continue
        item_url = a_m.group(1)

        title_m = re.search(r'class=\"Title\"[^>]*>([^<]+)', article, re.I)
        if not title_m:
            continue
        item_title = _html.unescape(title_m.group(1).strip())
        item_title = re.sub(r'\s*[-\u2013]\s*Der Film\s*$', '', item_title, flags=re.I).strip()

        year_m = re.search(r'class=\"Year\"[^>]*>(\d{4})', article, re.I)
        year   = year_m.group(1) if year_m else ''

        qual_m = re.search(r'class=\"Qlty\"[^>]*>([^<]+)', article, re.I)
        _qt = (qual_m.group(1) if qual_m else '').upper()
        qual = '4K' if ('4K' in _qt or '2160' in _qt) else '1080p' if '1080' in _qt else '720p' if '720' in _qt else 'SD' if '480' in _qt else 'HD'

        thumb_m = (
            re.search(r'data-src=\"(/uploads/[^\"]+)\"', article, re.I) or
            re.search(r'src=\"(/uploads/[^\"]+)\"', article, re.I)
        )
        thumb = (_base() + thumb_m.group(1)) if thumb_m else ''

        plot_m = re.search(r'class=\"[^\"]*sescri[^\"]*\"[^>]*>(.*?)</(?:p|div)>', article, re.S | re.I)
        plot   = _clean_plot(plot_m.group(1)) if plot_m else ''

        if force_series:
            mediatype   = 'tvshow'
            next_func   = 'load'
            is_playable = False
            entry_url   = _S_SEASONS + item_url
            if not plot:
                plot = ' '
        else:
            mediatype   = 'movie'
            next_func   = 'get_hosters'
            is_playable = True
            entry_url   = item_url

        item = {
            'title':       item_title,
            'url':         entry_url,
            'poster':      thumb,
            'year':        year,
            'mediatype':   mediatype,
            'next_func':   next_func,
            'is_playable': is_playable,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items
def _next_page(html, current_url):
    m = (
        re.search(r'<a[^>]*class="[^"]*\bnext\b[^"]*"[^>]*href="([^"]+)"', html, re.I) or
        re.search(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*\bnext\b[^"]*"', html, re.I) or
        re.search(r'<a[^>]*class="[^"]*nextlink[^"]*"[^>]*href="([^"]+)"', html, re.I) or
        re.search(r'<a[^>]*href="([^"]+)"[^>]*>(?:\s*(?:>>|&raquo;|»|›)\s*)</a>', html, re.I) or
        re.search(r'<a[^>]*href="([^"]+)"[^>]*>[^<]*(?:Next|Weiter)\s*[»›]', html, re.I)
    )
    if m:
        nxt = m.group(1)
        return (_base() + nxt) if nxt.startswith('/') else nxt
    if re.search(r'class="[^"]*(?:pager|navigation|navi|pages)[^"]*"', html, re.I):
        page_m    = re.search(r'/page/(\d+)/', current_url)
        page      = int(page_m.group(1)) + 1 if page_m else 2
        base_path = re.sub(r'/page/\d+/', '/', current_url)
        return base_path.rstrip('/') + '/page/%d/' % page
    return ''


def _parse_catalog_rows(html):
    items = []
    tbody = re.search(r'<tbody[^>]*id="dle-content"[^>]*>(.*?)</tbody>', html, re.S | re.I)
    if not tbody:
        return items
    for row in re.findall(r'<tr>(.*?)</tr>', tbody.group(1), re.S | re.I):
        url_m = re.search(r'class="MvTbImg"[^>]*href="([^"]+)"', row, re.I)
        if not url_m:
            url_m = re.search(r'href="(https?://[^"]+/stream/[^"]+)"', row, re.I)
        if not url_m:
            continue
        item_url = url_m.group(1)
        title_m = re.search(r'<strong>([^<]+)</strong>', row, re.I)
        if not title_m:
            continue
        item_title = _html.unescape(title_m.group(1).strip())
        thumb_m = re.search(r'data-src="(/uploads/[^"]+)"', row, re.I)
        thumb   = (_base() + thumb_m.group(1)) if thumb_m else ''
        tds     = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)
        year    = re.sub(r'<[^>]+>', '', tds[3]).strip() if len(tds) > 3 else ''
        qlty_m  = re.search(r'class="Qlty">([^<]+)', tds[4], re.I) if len(tds) > 4 else None
        _qt     = (qlty_m.group(1) if qlty_m else '').upper()
        qual    = '4K' if ('4K' in _qt or '2160' in _qt) else '1080p' if '1080' in _qt else '720p' if '720' in _qt else 'HD'
        genres  = tds[6] if len(tds) > 6 else ''
        is_serie = bool(re.search(r'/serien/', genres, re.I))
        if is_serie:
            items.append({
                'title':       item_title,
                'url':         _S_SEASONS + item_url,
                'poster':      thumb,
                'year':        year,
                'mediatype':   'tvshow',
                'next_func':   'load',
                'is_playable': False,
            })
        else:
            items.append({
                'title':       item_title,
                'url':         item_url,
                'poster':      thumb,
                'year':        year,
                'mediatype':   'movie',
                'next_func':   'get_hosters',
                'is_playable': True,
            })
    return items


def _browse_entries(url):
    html         = _get(url, _base())
    is_catalog   = '/catalog/' in url
    force_series = '/serien/' in url
    items        = _parse_catalog_rows(html) if is_catalog else _parse_articles(html, force_series=force_series)
    nxt          = _next_page(html, url)
    if nxt:
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         nxt,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _get_poster_from_html(html):
    m = (re.search(r'data-src=\"(/uploads/[^\"]+)\"', html, re.I) or
         re.search(r'src=\"(/uploads/[^\"]+)\"', html, re.I))
    return (_base() + m.group(1)) if m else ''


def _meinecloud_serial_html(imdb):
    from resources.lib import evil as cloud
    imdb_num = re.sub(r'[^0-9]', '', str(imdb))
    html = cloud._get('https://meinecloud.click/serial/%s' % imdb_num)
    if not html:
        html = cloud._get('https://meinecloud.click/serial/%s' % imdb)
    return html or ''


def _parse_serial_html(html):
    sid_to_snum = {}
    for sid, label in re.findall(r'data-season="(\d+)"[^>]*>\s*(S\d+)\s*<', html):
        m = re.match(r'S(\d+)', label.strip())
        if m:
            sid_to_snum[sid] = int(m.group(1))
    episodes = {}
    blocks = re.split(r'(?=<div[^>]*class="[^"]*_season-eps[^"]*"[^>]*data-season=")', html)
    for block in blocks:
        sid_m = re.match(r'<div[^>]*data-season="(\d+)">', block)
        if not sid_m:
            continue
        sid = sid_m.group(1)
        snum = sid_to_snum.get(sid)
        if snum is None:
            continue
        links  = re.findall(r'data-link="([^"]+)"', block)
        labels = re.findall(r'data-label="([^"]+)"', block)
        ep_nums = re.findall(r'<div[^>]*class="[^"]*_ep-n[^"]*">(\d+)</div>', block)
        for i, (link_raw, label) in enumerate(zip(links, labels)):
            ep_num = int(ep_nums[i]) if i < len(ep_nums) else i + 1
            link = link_raw.strip()
            if link.startswith('//'):
                link = 'https:' + link
            episodes.setdefault(snum, []).append((ep_num, label.strip(), link))
    return sid_to_snum, episodes


def _get_seasons(show_url):
    imdb_m = re.search(r'/(tt\d+)', show_url)
    imdb = imdb_m.group(1) if imdb_m else _imdb_from_page(show_url)
    if not imdb:
        return []
    html = _meinecloud_serial_html(imdb)
    if not html:
        return []
    poster = _get_poster_from_html(_get(show_url, _base()))
    plot = _extract_plot(_get(show_url, _base()))
    sid_to_snum, episodes = _parse_serial_html(html)
    seasons = sorted(episodes.keys())
    if not seasons:
        return []
    items = []
    for s in seasons:
        item = {
            'title':       'Staffel %d' % s,
            'url':         _S_EPISODES + show_url + '|' + imdb + '|%d' % s,
            'poster':      poster,
            'mediatype':   'season',
            'next_func':   'load',
            'is_playable': False,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _get_episodes(encoded):
    show_url, imdb, season_s = encoded.rsplit('|', 2)
    season = int(season_s)
    html = _meinecloud_serial_html(imdb)
    if not html:
        return []
    show_html = _get(show_url, _base())
    poster = _get_poster_from_html(show_html)
    plot = _extract_plot(show_html)
    _, episodes = _parse_serial_html(html)
    items = []
    for ep_num, ep_title, link in sorted(episodes.get(season, []), key=lambda x: x[0]):
        item = {
            'title':       ep_title,
            'url':         link,
            'poster':      poster,
            'mediatype':   'episode',
            'next_func':   'get_hosters',
            'is_playable': True,
            'season':      season,
            'episode':     ep_num,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items
def load(url='', params=None):
    if url == _S_FILME:
        return _filme_menu()
    if url == _S_SERIEN:
        return _serien_menu()
    if url == _S_GENRES:
        return _genres_menu()
    if url == _S_JAHRE:
        return _jahre_menu()
    if url == _S_LAENDER:
        return _laender_menu()
    if url == _S_AZ:
        return _az_menu()
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPISODES):
        return _get_episodes(url[len(_S_EPISODES):])
    if url:
        return _browse_entries(url)
    return [
        {'title': 'Filme',  'url': _S_FILME,  'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': _S_SERIEN, 'next_func': 'load', 'is_playable': False},
    ]


def search(query='', params=None):
    url   = _base() + '/?story=%s&do=search&subaction=search&titleonly=3' % quote(query)
    html  = _get(url, _base())
    items = _parse_articles(html)
    clean_q = _cleantitle(query)
    return [
        i for i in items
        if clean_q in _cleantitle(i.get('title', '')) or
           _cleantitle(i.get('title', '')) in clean_q
    ]
