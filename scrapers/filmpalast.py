# -*- coding: utf-8 -*-
import re
from resources.lib import multiquest, log

SITE_ID      = 'filmpalast'
SITE_NAME    = 'FilmPalast'
SITE_DOMAIN  = 'filmpalast.to'
TYPE         = 'both'
GLOBAL_SEARCH = True


_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'


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
    text = re.sub(r'^(?:Beschreibung|Description|Inhalt|Plot)\s*:\s*', '', text, flags=re.I)
    return text


def _extract_plot_from_detail(html):
    patterns = [
        r'<(?:span|p|div)[^>]*itemprop="description"[^>]*>(.*?)</(?:span|p|div)>',
        r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>',
        r'<div[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</div>',
        r'<p[^>]*class="[^"]*plot[^"]*"[^>]*>(.*?)</p>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.S | re.I)
        if m:
            plot = _clean_plot(m.group(1))
            if len(plot) > 20:
                return plot
    return ''


def _extract_hosters_from_page(page_url):
    html = _get(page_url, _base())
    quality = 'HD'
    q = re.search(r'<span id="release_text"[^>]*>([^<&]+)', html, re.I)
    if q:
        quality = _quality_from_text(q.group(1))
    streams = re.findall(
        r'<p class="hostName">([^<]+)</p>.*?<li[^>]*class="streamPlayBtn[^"]*".*?<a[^>]*(?:href|data-player-url)="([^"]+)"',
        html, re.S | re.I
    )
    plot = _extract_plot_from_detail(html)
    result = []
    for hoster, s_url in streams:
        if not s_url or s_url.startswith('javascript'):
            continue
        result.append((hoster.strip(), s_url, quality))
    return result, plot


def _find_page_url(title, year, season=0):
    from urllib.parse import quote as _quote
    search_url = _base() + '/search/title/' + _quote(title)
    html = _get(search_url, _base())
    content_m = re.search(r'id="content"[^>]*>(.+?)<div id="paging"', html, re.S | re.I)
    if not content_m:
        return ''
    content = content_m.group(1)
    matches = re.findall(r'href="//filmpalast\.to(/stream/[^"]+)"[^>]*title="([^"]+)"', content, re.S | re.I)
    clean_t = _cleantitle(title)
    for m_url, m_title in matches:
        if _cleantitle(m_title) not in clean_t and clean_t not in _cleantitle(m_title):
            continue
        page_url = _base() + m_url
        page_html = _get(page_url, _base())
        if season == 0 and year:
            y = re.search(r'>Ver&ouml;ffentlicht:\s*([^<]+)', page_html, re.I)
            if y and str(year) not in y.group(1):
                continue
        if season > 0:
            if 'staffel' not in m_title.lower() and 's0' not in m_title.lower():
                continue
            s_m = re.search(r'staffel\s*(\d+)', m_title, re.I)
            if s_m and int(s_m.group(1)) != season:
                continue
        return page_url
    return ''


def get_details(url='', params=None):
    if not url:
        return {}
    html = _get(url, _base())
    plot = _extract_plot_from_detail(html)
    year = ''
    y = re.search(r'>Ver&ouml;ffentlicht:\s*(\d{4})', html, re.I)
    if y:
        year = y.group(1)
    rating = ''
    r = re.search(r'itemprop="ratingValue"[^>]*>([^<]+)', html, re.I)
    if r:
        rating = r.group(1).strip()
    poster = ''
    for size in ('450', '315', '240', '100'):
        pm = re.search(r'<img[^>]*src="(/files/movies/' + size + r'/[^"]+)"', html, re.I)
        if pm:
            poster = _base() + pm.group(1)
            break
    if not poster:
        pm = re.search(r'<img[^>]*(?:class="cover[^"]*"|id="img__\d+")[^>]*src="(/files/movies/[^"]+)"', html, re.I)
        if not pm:
            pm = re.search(r'<img[^>]*src="(/files/movies/[^"]+)"[^>]*(?:class="cover[^"]*"|id="img__\d+")', html, re.I)
        if pm:
            poster = _base() + pm.group(1)
    result = {}
    if plot:
        result['plot'] = plot
    if year:
        result['year'] = year
    if poster:
        result['poster'] = poster
    if rating:
        try:
            result['rating'] = float(rating)
        except Exception:
            pass
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        raw, _ = _extract_hosters_from_page(url)
    else:
        page_url = _find_page_url(title, year, season)
        if not page_url:
            return []
        raw, _ = _extract_hosters_from_page(page_url)

    return [(name, hurl, False, quality, '') for name, hurl, quality in raw]


_S_FILME    = '__fp_filme__'
_S_SERIEN   = '__fp_serien__'
_S_SEC      = '__fp_section__:'
_S_SEASONS  = '__fp_seasons__:'
_S_EPISODES = '__fp_episodes__:'


def _filme_menu():
    b = _base()
    return [
        {'title': 'Neuesten',       'url': b + '/movies/new',                          'next_func': 'load', 'is_playable': False},
        {'title': 'Hits',           'url': b + '/movies/top',                          'next_func': 'load', 'is_playable': False},
        {'title': 'Votes',          'url': b + '/movies/votes',                        'next_func': 'load', 'is_playable': False},
        {'title': 'IMDB-Bewertung', 'url': b + '/movies/imdb',                        'next_func': 'load', 'is_playable': False},
        {'title': 'Englisch',       'url': b + '/search/genre/Englisch',               'next_func': 'load', 'is_playable': False},
        {'title': 'Genre',          'url': _S_SEC + b + '/movies/new|genre',           'next_func': 'load', 'is_playable': False},
        {'title': 'A-Z',            'url': _S_SEC + b + '/movies/new|movietitle',      'next_func': 'load', 'is_playable': False},
    ]


def _serien_menu():
    b = _base()
    return [
        {'title': 'Neuesten', 'url': b + '/serien/view',                              'next_func': 'load', 'is_playable': False},
        {'title': 'A-Z',      'url': _S_SEC + b + '/serien/view|movietitle',          'next_func': 'load', 'is_playable': False},
    ]


def _browse_section(encoded):
    base_url, section_id = encoded.rsplit('|', 1)
    html = _get(base_url)
    pat = r'<section[^>]+id="%s"[^>]*>(.*?)</section>' % re.escape(section_id)
    m = re.search(pat, html, re.S | re.I)
    if not m:
        return []
    items = []
    for entry_url, name in re.findall(r'href="([^"]+)">([^<]+)', m.group(1)):
        if entry_url.startswith('/'):
            entry_url = _base() + entry_url
        items.append({
            'title':       name.strip(),
            'url':         entry_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _get_poster_from_html(html):
    for size in ('450', '315', '240', '100'):
        pm = re.search(r'<img[^>]*src="(/files/movies/' + size + r'/[^"]+)"', html, re.I)
        if pm:
            return _base() + pm.group(1)
    pm = re.search(r'<img[^>]*src="(/files/movies/[^"]+)"', html, re.I)
    return _base() + pm.group(1) if pm else ''


def _get_seasons(show_url):
    html = _get(show_url, _base())
    seasons = re.findall(r'<a[^>]*class="staffTab"[^>]*data-sid="(\d+)"', html, re.I)
    if not seasons:
        seasons = re.findall(r'data-sid="(\d+)"', html, re.I)
    poster = _get_poster_from_html(html)
    plot = _extract_plot_from_detail(html)
    items = []
    for s in seasons:
        item = {
            'title':       'Staffel ' + s,
            'url':         _S_EPISODES + show_url + '|' + s,
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
    show_url, season = encoded.rsplit('|', 1)
    html = _get(show_url, _base())
    m_start = re.search(r'<div[^>]*data-sid="%s"[^>]*>' % re.escape(season), html, re.I)
    if not m_start:
        return []
    section_start = m_start.end()
    m_next = re.search(r'<div[^>]*class="staffelWrapperLoop', html[section_start:], re.I)
    section = html[section_start: section_start + m_next.start()] if m_next else html[section_start:]
    poster = _get_poster_from_html(html)
    plot = _extract_plot_from_detail(html)
    items = []
    for anchor in re.finditer(r'(<a[^>]*class="getStaffelStream[^"]*"[^>]*>)(.*?)</a>', section, re.S | re.I):
        href_m = re.search(r'href="([^"]+)"', anchor.group(1))
        if not href_m:
            continue
        ep_url = href_m.group(1).strip()
        if ep_url.startswith('//'):
            ep_url = 'https:' + ep_url
        elif ep_url.startswith('/'):
            ep_url = _base() + ep_url
        content = re.sub(r'<small[^>]*>.*?</small>', '', anchor.group(2), flags=re.S | re.I)
        raw = re.sub(r'<[^>]+>', '', content).replace('&nbsp;', ' ')
        ep_title = ' '.join(raw.split())
        if not ep_title:
            ep_m = re.search(r's\d+e(\d+)', ep_url, re.I)
            ep_title = 'Folge ' + ep_m.group(1) if ep_m else ep_url.split('/')[-1]
        item = {
            'title':       ep_title,
            'url':         ep_url,
            'poster':      poster,
            'mediatype':   'episode',
            'next_func':   'get_hosters',
            'is_playable': True,
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
    if url.startswith(_S_SEC):
        return _browse_section(url[len(_S_SEC):])
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPISODES):
        return _get_episodes(url[len(_S_EPISODES):])
    if url:
        return _browse_entries(url)
    return [
        {'title': 'Filme',  'url': _S_FILME,  'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': _S_SERIEN, 'next_func': 'load', 'is_playable': False},
        {'title': 'Suche',  'url': '',         'next_func': 'load', 'is_playable': False},
    ]


def _extract_plot_from_article(article_html):
    patterns = [
        r'<p[^>]*class="[^"]*sescri[^"]*"[^>]*>(.*?)</p>',
        r'<p[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</p>',
        r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>',
        r'<p[^>]*class="[^"]*plot[^"]*"[^>]*>(.*?)</p>',
    ]
    for pat in patterns:
        m = re.search(pat, article_html, re.S | re.I)
        if m:
            plot = _clean_plot(m.group(1))
            if len(plot) > 20:
                return plot
    return ''


def _browse_entries(url):
    html = _get(url)
    pattern = r'<article[^>]*>(.*?)</article>'
    articles = re.findall(pattern, html, re.S | re.I)
    items = []
    seen_shows = set()
    for article in articles:
        url_m = re.search(r'<a[^>]+href="([^"]+)"[^>]+title="([^"]+)"', article, re.I)
        if not url_m:
            continue
        s_url  = url_m.group(1)
        s_name = url_m.group(2)
        thumb_m = (
            re.search(r'<img[^>]*src=["\'](files/movies[^"\']+)["\']', article, re.I) or
            re.search(r'<img[^>]*src=["\'](/files/movies[^"\']+)["\']', article, re.I) or
            re.search(r'<img[^>]*class="cover[^"]*"[^>]*src=["\']([ ^"\']+)["\']', article, re.I) or
            re.search(r'<img[^>]+src=["\']([ ^"\']+)["\']', article, re.I)
        )
        thumb = thumb_m.group(1) if thumb_m else ''
        if s_url.startswith('//'):
            s_url = 'https:' + s_url
        if thumb.startswith('/'):
            thumb = _base() + thumb
        year_m = re.search(r'Jahr:\s*(\d+)', article)
        year = year_m.group(1) if year_m else ''
        plot = _extract_plot_from_article(article)
        se_m = re.search(r'\s+S\d\dE\d\d', s_name, re.I)
        if se_m:
            show_name = s_name[:se_m.start()].strip()
            if show_name in seen_shows:
                continue
            seen_shows.add(show_name)
            item = {
                'title':       show_name,
                'url':         _S_SEASONS + s_url,
                'poster':      thumb,
                'year':        year,
                'mediatype':   'tvshow',
                'next_func':   'load',
                'is_playable': False,
            }
        else:
            item = {
                'title':       s_name,
                'url':         s_url,
                'poster':      thumb,
                'year':        year,
                'mediatype':   'movie',
                'next_func':   'get_hosters',
                'is_playable': True,
            }
        if plot:
            item['plot'] = plot
        items.append(item)
    next_m = re.search(r'<a class="pageing[^"]*"[^>]*href="([^"]+)"[^>]*>[^<]*vor', html, re.I)
    if next_m:
        next_url = _base() + next_m.group(1) if next_m.group(1).startswith('/') else next_m.group(1)
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def search(query='', params=None):
    from urllib.parse import quote as _quote
    url = _base() + '/search/title/' + _quote(query)
    return _browse_entries(url)
