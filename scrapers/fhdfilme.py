# -*- coding: utf-8 -*-
import re
import json as _json
from urllib.parse import quote as _quote
from resources.lib import multiquest, log

SITE_ID       = 'fhdfilme'
SITE_NAME     = 'FHD Filme'
SITE_DOMAIN   = 'hdfilme.win'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None, cache_ttl=0):
    headers = {'User-Agent': _UA}
    if referer:
        headers['Referer'] = referer
    if cache_ttl:
        headers['_cache_ttl'] = cache_ttl
    try:
        r = multiquest.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _cleantitle(s):
    s = (s or '').lower()
    return re.sub(r'[^a-z0-9]', '', s)


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
    return re.sub(r'\s+', ' ', text)


def _resolve_meinecloud(url, referer=''):
    try:
        html = _get(url, referer)
        if not html:
            return []
        links = re.findall(r'data-link=\"([^\"]+)\"', html)
        result = []
        for u in links:
            if not u:
                continue
            if 'meinecloud' in u:
                continue
            if u.startswith('//'):
                u = 'https:' + u
            result.append(u)
        return result
    except Exception:
        log.error()
        return []


def _hosters_from_html(html, referer=''):
    raw = re.findall(r'data-link=\"([^\"]+)\"', html)
    seen = set()
    result = []
    for link in raw:
        if not link:
            continue
        if 'meinecloud' in link:
            if link.startswith('//'):
                link = 'https:' + link
            for resolved in _resolve_meinecloud(link, referer):
                if resolved not in seen:
                    seen.add(resolved)
                    name = resolved.split('/')[2].split('.')[0]
                    result.append((name, resolved, False, 'HD'))
        else:
            if link.startswith('//'):
                link = 'https:' + link
            if 'youtube' in link:
                continue
            if link not in seen:
                seen.add(link)
                name = link.split('/')[2].split('.')[0]
                result.append((name, link, False, 'HD'))
    return result


def _get_cloud_url(page_url):
    html = _get(page_url, _base(), cache_ttl=600)
    m = re.search(r'(tt\d{7,8})', html)
    if not m:
        m = re.search(r'imdb[^\"\']{0,20}[\"\'](tt\d{7,8})', html, re.I)
    if m:
        imdb_id = m.group(1)
        check_url = 'https://meinecloud.click/serials.php?task=check&id_imdb=' + imdb_id
        try:
            r = multiquest.get(check_url, headers={'User-Agent': _UA, 'Referer': _base() + '/'}, timeout=10)
            r.raise_for_status()
            data = _json.loads(r.text)
            if data.get('exists') and data.get('player_url'):
                return data['player_url']
        except Exception:
            log.error()
    html_uncommented = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    for iframe_src in re.findall(r'<iframe[^>]*src=\"([^\"]+)\"', html_uncommented, re.I):
        if 'meinecloud.click' in iframe_src:
            if iframe_src.startswith('//'):
                iframe_src = 'https:' + iframe_src
            return iframe_src
    return ''


def _extract_hosters_from_page(page_url, season=0, episode=0):
    html = _get(page_url, _base(), cache_ttl=600)
    html_uncommented = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    iframes = re.findall(r'<iframe[^>]*src=\"([^\"]+)\"', html_uncommented, re.I)
    result = []
    for iframe_url in iframes:
        if 'youtube' in iframe_url:
            continue
        if not iframe_url.startswith('http'):
            iframe_url = _base() + '/' + iframe_url.lstrip('/')
        if season > 0 and episode > 0 and 'meinecloud.click' in iframe_url:
            iframe_html = _get(iframe_url, page_url, cache_ttl=600)
            season_id = _cloud_season_id(iframe_html, season)
            if season_id:
                hosters = _cloud_episode_hosters(iframe_html, season_id, episode, iframe_url)
                result.extend(hosters)
            continue
        iframe_html = _get(iframe_url, page_url, cache_ttl=600)
        hosters = _hosters_from_html(iframe_html, page_url)
        if hosters:
            result.extend(hosters)
        else:
            result.append((iframe_url.split('/')[2], iframe_url, False, 'HD'))
    return result


def _cloud_season_id(html, season):
    for data_season, label in re.findall(r'<div[^>]*class=\"[^\"]*_stab[^\"]*\"[^>]*data-season=\"(\d+)\"[^>]*>(.*?)</div>', html, re.S | re.I):
        num_m = re.search(r'\d+', label)
        if num_m and int(num_m.group()) == season:
            return data_season
    return ''


def _cloud_episode_hosters(html, season_id, episode, referer):
    seen = set()
    result = []
    s_pat = r'S(\d+)\s*E0*%d\b' % episode
    for div in re.findall(r'<div[^>]*class=\"[^\"]*_ep\b[^\"]*\"[^>]*>', html, re.I):
        link_m = re.search(r'data-link=\"([^\"]+)\"', div, re.I)
        label_m = re.search(r'data-label=\"([^\"]+)\"', div, re.I)
        if not link_m or not label_m:
            continue
        link = link_m.group(1)
        label = label_m.group(1)
        lm = re.search(s_pat, label, re.I)
        if not lm:
            continue
        if not link:
            continue
        if link.startswith('//'):
            link = 'https:' + link
        if 'meinecloud' in link:
            for resolved in _resolve_meinecloud(link, referer):
                if resolved not in seen:
                    seen.add(resolved)
                    name = resolved.split('/')[2].split('.')[0]
                    result.append((name, resolved, False, 'HD'))
        else:
            if link not in seen:
                seen.add(link)
                name = link.split('/')[2].split('.')[0]
                result.append((name, link, False, 'HD'))
    return result


def _find_page_url(title, year, season=0):
    search_url = _base() + '/?story=%s&do=search&subaction=search' % _quote(title)
    html = _get(search_url)
    for s_url, s_title, s_year in re.findall(
        r'class=\"thumb\".*?href=\"([^\"]+)\".*?title=\"([^\"]+)\".*?_year\">([^<]+)', html, re.S
    ):
        if _cleantitle(s_title) not in _cleantitle(title) and _cleantitle(title) not in _cleantitle(s_title):
            continue
        if season == 0 and year and s_year.strip() != str(year):
            continue
        return s_url
    return ''


_PLOT_PATTERNS = [
    r'<div[^>]*class=\"[^\"]*prose[^\"]*\"[^>]*>(.*?)</div>\s*\n?\s*</div>',
    r'<div[^>]*class=\"[^\"]*prose[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*class=\"[^\"]*full-text[^\"]*\"[^>]*>(.*?)</div>\s*(?:</div>|<div[^>]*class=\"[^\"]*share)',
    r'<div[^>]*class=\"[^\"]*full-text[^\"]*\"[^>]*>(.*?)</div>',
    r'<p[^>]*class=\"[^\"]*sescri[^\"]*\"[^>]*>(.*?)</p>',
    r'<div[^>]*class=\"[^\"]*sescri[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*class=\"[^\"]*news-text[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*class=\"[^\"]*movie-description[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*class=\"[^\"]*film-description[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*class=\"[^\"]*storyline[^\"]*\"[^>]*>(.*?)</div>',
    r'<div[^>]*itemprop=\"description\"[^>]*>(.*?)</div>',
    r'<p[^>]*itemprop=\"description\"[^>]*>(.*?)</p>',
    r'<span[^>]*itemprop=\"description\"[^>]*>(.*?)</span>',
]


_SEO_PHRASES = ('stream kostenlos', 'wie in einem echten kino', 'legal streamen',
                'jetzt online', 'kostenlos online', 'ohne anmeldung', 'in hd stream')


def _is_seo(text):
    t = text.lower()
    return any(p in t for p in _SEO_PHRASES)


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base(), cache_ttl=600)
    result = {}
    for pat in _PLOT_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            plot = _clean_plot(m.group(1))
            if len(plot) > 30 and not _is_seo(plot):
                result['plot'] = plot
                break
    if 'plot' not in result:
        candidates = [_clean_plot(p) for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S)]
        candidates = [c for c in candidates if len(c) > 80 and not _is_seo(c)]
        if candidates:
            result['plot'] = max(candidates, key=len)
    y = re.search(r'_year\">(\d{4})', html)
    if y:
        result['year'] = y.group(1)
    pm = re.search(r'<img[^>]*class=\"[^\"]*poster[^\"]*\"[^>]*src=\"([^\"]+)\"', html, re.I)
    if not pm:
        pm = re.search(r'<img[^>]*data-src=\"([^\"]+)\"', html, re.I)
    if pm:
        result['poster'] = pm.group(1) if pm.group(1).startswith('http') else _base() + pm.group(1)
    return result


def _episode_hosters_from_site_html(html, season, episode):
    raw = []
    m = re.search(r'#se-ac-%d(.*?)</div></div>' % season, html, re.S | re.I)
    if not m:
        return raw
    ep_m = re.search(r'x%d\s*Episode(.*?)<br' % episode, m.group(1), re.S | re.I)
    if not ep_m:
        return raw
    seen = set()
    for link in re.findall(r'href=\"([^\"]+)\"', ep_m.group(1)):
        if not link or 'youtube' in link:
            continue
        if not link.startswith('http'):
            link = _base() + '/' + link.lstrip('/')
        if link not in seen:
            seen.add(link)
            name = link.split('/')[2].split('.')[0] if '//' in link else ''
            raw.append((name, link, False, 'HD'))
    return raw


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if params:
        season  = int(params.get('season',  season))
        episode = int(params.get('episode', episode))
    if url and season > 0 and episode > 0:
        html = _get(url, _base(), cache_ttl=600)
        raw = _episode_hosters_from_site_html(html, season, episode)
        if not raw:
            raw = _extract_hosters_from_page(url, season, episode)
        if not raw:
            cloud_url = _get_cloud_url(url)
            if cloud_url:
                cloud_html = _get(cloud_url, url, cache_ttl=600)
                season_id = _cloud_season_id(cloud_html, season)
                if season_id:
                    raw = _cloud_episode_hosters(cloud_html, season_id, episode, cloud_url)
    elif url:
        raw = _extract_hosters_from_page(url, season, episode)
    elif season == 0 and imdb:
        html = _get('https://meinecloud.click/movie/%s' % imdb)
        raw  = _hosters_from_html(html)
    else:
        page_url = _find_page_url(title, year, season)
        if not page_url:
            return []
        raw = _extract_hosters_from_page(page_url, season, episode)

    result = []
    for entry in raw:
        name    = entry[0]
        hurl    = entry[1]
        quality = entry[3] if len(entry) > 3 else 'HD'
        result.append((name, hurl, False, quality, ''))
    return result


def _browse_entries(url):
    html  = _get(url, cache_ttl=300)
    html  = html.replace('\n', '').replace('\r', '').replace('\t', '')
    items = []
    blocks = re.findall(r'class=\"item relative mt-3\">(.*?)</div>\s*</div>', html, re.S)
    for block in blocks:
        url_m   = re.search(r'href=\"([^\"]+)', block)
        name_m  = re.search(r'title=\"([^\"]+)', block)
        thumb_m = re.search(r'data-src=\"([^\"]+)', block)
        if not (url_m and name_m and thumb_m):
            continue
        s_url  = url_m.group(1)
        s_name = name_m.group(1)
        thumb  = thumb_m.group(1)
        year_m   = re.search(r'mt-1\">[^<]*<span>([\d]+)</span>', block)
        dur_m    = re.search(r'<span>([\d]+)\smin</span>', block)
        year     = year_m.group(1).strip() if year_m else ''
        duration = int(dur_m.group(1)) if dur_m else 999
        is_tv    = duration <= 70
        if not s_url.startswith('http'):
            s_url = _base() + '/' + s_url.lstrip('/')
        if not thumb.startswith('http'):
            thumb = _base() + thumb
        items.append({
            'title':       s_name.strip(),
            'url':         s_url,
            'poster':      thumb,
            'year':        year,
            'mediatype':   'tvshow' if is_tv else 'movie',
            'next_func':   'get_seasons' if is_tv else 'get_hosters',
            'is_playable': not is_tv,
        })
    next_m = re.search(r'page_next.*?href=\"([^\"]+)\"', html)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({'title': '[B]>>> Weiter[/B]', 'url': next_url, 'next_func': 'load', 'is_playable': False})
    return items


def get_seasons(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    cloud_url = _get_cloud_url(url)
    if not cloud_url:
        return []
    html = _get(cloud_url, url, cache_ttl=600)
    seasons = []
    for data_season, label in re.findall(
        r'<div[^>]*class=\"[^\"]*_stab[^\"]*\"[^>]*data-season=\"(\d+)\"[^>]*>(.*?)</div>', html, re.S | re.I
    ):
        num_m = re.search(r'\d+', label)
        if not num_m:
            continue
        s_num = int(num_m.group())
        seasons.append((s_num, data_season, label.strip()))
    seasons.sort(key=lambda x: x[0])
    return [
        {
            'title':       'Staffel %s' % s_num,
            'url':         url,
            'season':      s_num,
            'next_func':   'get_episodes',
            'is_playable': False,
        }
        for s_num, _sid, _lbl in seasons
    ]


def get_episodes(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    if params:
        season = int(params.get('season', season))
    html = _get(url, _base(), cache_ttl=600)
    ep_nums = []
    m = re.search(r'#se-ac-%d(.*?)</div></div>' % season, html, re.S | re.I)
    if m:
        ep_nums = sorted(set(int(n) for n in re.findall(r'Episode\s(\d+)', m.group(1))))
    if not ep_nums:
        cloud_url = _get_cloud_url(url)
        if cloud_url:
            cloud_html = _get(cloud_url, url, cache_ttl=600)
            s_pat = r'S0*%d\s*E(\d+)\b' % season
            ep_nums = sorted(set(
                int(m2.group(1))
                for label in re.findall(r'data-label=\"([^\"]+)\"', cloud_html)
                for m2 in [re.search(s_pat, label, re.I)]
                if m2
            ))
    return [
        {
            'title':       'Episode %s' % e,
            'url':         url,
            'season':      season,
            'episode':     e,
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        for e in ep_nums
    ]


def _browse_value(value):
    html = _get(_base(), cache_ttl=300)
    html = html.replace('\n', '').replace('\r', '').replace('\t', '')
    m = re.search(r'>{0}</(.*?)</a[^<]*</div>'.format(value), html, re.S)
    if not m:
        m = re.search(r'>{0}</a>(.*?)</ul>'.format(value), html, re.S)
    if not m:
        return []
    items = []
    for href, name in re.findall(r'href=\"([^\"]+)[^>]*>([^<]+)', m.group(1)):
        if href.startswith('/'):
            href = _base() + href
        items.append({'title': name.strip(), 'url': href, 'next_func': 'load', 'is_playable': False})
    return items


def load(url='', params=None):
    if url:
        if url.startswith('__value__:'):
            return _browse_value(url[len('__value__:'):])
        return _browse_entries(url)
    b = _base()
    return [
        {'title': 'Neu',    'url': b + '/filme1/',     'next_func': 'load', 'is_playable': False},
        {'title': 'Kino',   'url': b + '/kinofilme/',  'next_func': 'load', 'is_playable': False},
        {'title': 'Serien', 'url': b + '/serien/',     'next_func': 'load', 'is_playable': False},
        {'title': 'Filme',  'url': b,                  'next_func': 'load', 'is_playable': False},
        {'title': 'Genre',  'url': '__value__:Genre',  'next_func': 'load', 'is_playable': False},
        {'title': 'Jahr',   'url': '__value__:Jahres', 'next_func': 'load', 'is_playable': False},
        {'title': 'Land',   'url': '__value__:Land',   'next_func': 'load', 'is_playable': False},
    ]


def search(query='', params=None):
    url = _base() + '/?story=%s&do=search&subaction=search' % _quote(query)
    return _browse_entries(url)
