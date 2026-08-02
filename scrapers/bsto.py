# -*- coding: utf-8 -*-
import re
import unicodedata
from html import unescape
from urllib.parse import urljoin, unquote
from resources.lib import multiquest, log
from resources.lib.captcha.captcha_helper import solve_recaptcha, extract_recaptcha_sitekey

SITE_ID       = 'bsto'
SITE_NAME     = 'BS.to'
SITE_DOMAIN   = 'burningseries.ac'
TYPE          = 'series'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None, caching=True):
    headers = {
        'User-Agent':      _UA,
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    }
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        log.log('[bsto] _get OK url=%s size=%d' % (url, len(r.text)))
        return r.text
    except Exception as e:
        log.log('[bsto] _get FAILED url=%s error=%s' % (url, e), log.LOGERROR)
        return ''


def _post(url, data, referer=None):
    headers = {
        'User-Agent':       _UA,
        'Accept':           'application/json, text/javascript, */*; q=0.01',
        'Accept-Language':  'de-DE,de;q=0.9',
        'Content-Type':     'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin':           _base(),
    }
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.post(url, data=data, headers=headers, timeout=15)
        r.raise_for_status()
        log.log('[bsto] _post OK url=%s size=%d' % (url, len(r.text)))
        return r.text
    except Exception as e:
        log.log('[bsto] _post FAILED url=%s error=%s' % (url, e), log.LOGERROR)
        return ''


def _clean_text(value):
    value = unescape(value or '')
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _cleantitle(s):
    try:
        s = unicodedata.normalize('NFKD', s or '')
        s = s.encode('ascii', 'ignore').decode('ascii')
    except Exception:
        pass
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _titles_match(variants, scraped_title):
    scraped_clean = _cleantitle(scraped_title)
    scraped_parts = [_cleantitle(p) for p in re.split(r'\s*\|\s*', scraped_title) if p.strip()]
    for query in variants:
        for scraped in [scraped_clean] + scraped_parts:
            if not query or not scraped: continue
            if query == scraped: return True
            if len(query) > 4 and query in scraped: return True
            if len(scraped) > 4 and scraped in query: return True
    return False


def _attr(attrs, name):
    m = re.search(r'%s\s*=\s*(["\'])(.*?)\1' % re.escape(name), attrs, re.I | re.S)
    return _clean_text(m.group(2)) if m else ''


def _find_series(title):
    variants = list(set([_cleantitle(title)]))
    html = _get(urljoin(_base(), 'andere-serien'), _base())
    results = []
    seen = set()
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.I | re.S):
        href = _attr(m.group(1), 'href')
        if not href or not href.startswith('serie/'): continue
        if len(href.strip('/').split('/')) != 2: continue
        if href in seen: continue
        seen.add(href)
        series_title = _clean_text(m.group(2)) or href.rsplit('/', 1)[-1].replace('-', ' ')
        if _titles_match(variants, series_title):
            results.append((href.strip('/'), series_title))
    return results


def _parse_hoster_links(html, page_url):
    from urllib.parse import urlparse
    page_path = urlparse(page_url).path.strip("/")
    last_seg = page_path.rsplit("/", 1)[-1]
    lang = last_seg if last_seg in ("de", "en", "des") else ""
    log.log('[bsto] _parse_hoster_links url=%s lang=%s' % (page_url, lang))
    tabs_m = re.search(r'<ul[^>]*class="[^"]*hoster-tabs[^"]*"[^>]*>(.*?)</ul>', html, re.S | re.I)
    if not tabs_m:
        log.log('[bsto] _parse_hoster_links: kein hoster-tabs ul gefunden url=%s' % page_url, log.LOGWARNING)
        log.log('[bsto] HTML-Ausschnitt: %s' % html[:2000])
        return []
    inner = tabs_m.group(1)
    log.log('[bsto] hoster-tabs inner len=%d' % len(inner))
    hosters = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', inner, re.S | re.I):
        href = m.group(1).strip()
        hoster = _clean_text(re.sub(r'<i[^>]*>.*?</i>', '', m.group(2), flags=re.S | re.I))
        if not hoster:
            hoster = _clean_text(m.group(2))
        if not href or not hoster:
            log.log('[bsto] _parse_hoster_links: leerer eintrag href=%s hoster=%s' % (href, hoster))
            continue
        hoster_url = href if href.startswith("http") else urljoin(_base(), href)
        log.log('[bsto] hoster gefunden: %s -> %s lang=%s' % (hoster, hoster_url, lang))
        hosters.append((hoster, hoster_url, lang))
    log.log('[bsto] _parse_hoster_links: %d hoster url=%s' % (len(hosters), page_url))
    return hosters

def _extract_recaptcha_sitekey(html):
    return extract_recaptcha_sitekey(html)


def _has_recaptcha_sitekey(html):
    m = re.search(r'series\.init\s*\([^,]+,\s*[^,]+,\s*["\']([^"\']*)["\']', html, re.I)
    has_key = bool(m and m.group(1).strip())
    log.log('[bsto] _has_recaptcha_sitekey: %s' % has_key)
    return has_key


def _language_from_code(code):
    code = (code or '').lower()
    if code == 'de':  return 'de', 'Deutsch'
    if code == 'des': return 'en', 'Deutsch Sub'
    if code == 'en':  return 'en', 'Englisch'
    return '', ''


def _resolve_hoster_url(hoster_path, page_url):
    import json as _json
    full_url = urljoin(_base(), hoster_path)
    log.log('[bsto] _resolve_hoster_url: lade %s' % full_url)

    sess = multiquest.Session(headers={
        'User-Agent':      _UA,
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
        'Referer':         page_url,
    })

    try:
        r = sess.get(full_url, timeout=10)
        html = r.text
        final_url = r.url or full_url
    except Exception as e:
        log.log('[bsto] _resolve_hoster_url: GET fehlgeschlagen url=%s error=%s' % (full_url, e), log.LOGERROR)
        sess.close()
        return ''

    if not html:
        log.log('[bsto] _resolve_hoster_url: leere Antwort url=%s' % full_url, log.LOGERROR)
        sess.close()
        return ''

    log.log('[bsto] _resolve_hoster_url: finale URL=%s' % final_url)

    hp_m = re.search(r'<[^>]+class=["\'][^"\']*hoster-player[^"\']*["\'][^>]*>', html, re.I)
    if hp_m:
        lid_m = re.search(r'data-lid=["\']([^"\']+)["\']', hp_m.group(0))
    else:
        lid_m = re.search(r'data-lid=["\']([^"\']+)["\']', html)

    token_m = re.search(r'security_token["\']?\s+content=["\']([^"\']+)["\']', html, re.I)

    if not lid_m:
        log.log('[bsto] _resolve_hoster_url: data-lid fehlt url=%s' % final_url, log.LOGERROR)
        sess.close()
        return ''
    if not token_m:
        log.log('[bsto] _resolve_hoster_url: security_token fehlt url=%s' % final_url, log.LOGERROR)
        sess.close()
        return ''

    embed_url = urljoin(_base(), '/ajax/embed.php')
    embed_headers = {
        'Accept':           'application/json, text/javascript, */*; q=0.01',
        'Content-Type':     'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin':           _base(),
        'Referer':          final_url,
    }

    def _post_embed(ticket):
        data = {
            'token':  token_m.group(1),
            'LID':    lid_m.group(1),
            'ticket': ticket,
        }
        log.log('[bsto] _resolve_hoster_url: POST embed.php LID=%s ticket=%s' % (lid_m.group(1), bool(ticket)))
        resp = sess.post(embed_url, data=data, headers=embed_headers)
        parsed = _json.loads(resp.text)
        return parsed.get('link', '') or ''

    try:
        link = _post_embed('')
        if link:
            log.log('[bsto] _resolve_hoster_url: link (kein captcha)=%s' % link)
            sess.close()
            return link
    except Exception as e:
        log.log('[bsto] _resolve_hoster_url: POST ohne captcha fehlgeschlagen: %s' % e, log.LOGERROR)

    sitekey = _extract_recaptcha_sitekey(html)
    if sitekey:
        log.log('[bsto] _resolve_hoster_url: sitekey=%s versuche captcha' % sitekey)
        try:
            captcha_token = solve_recaptcha(sitekey, final_url)
            link = _post_embed(captcha_token or '')
            if link:
                log.log('[bsto] _resolve_hoster_url: link (captcha)=%s' % link)
                sess.close()
                return link
        except Exception as e:
            log.log('[bsto] _resolve_hoster_url: captcha Pfad fehlgeschlagen: %s' % e, log.LOGERROR)
    else:
        log.log('[bsto] _resolve_hoster_url: kein sitekey, kein captcha fallback', log.LOGWARNING)

    sess.close()
    return ''


def _browse_series_list(url):
    html = _get(url, _base())
    items = []
    seen = set()
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.I | re.S):
        href = _attr(m.group(1), 'href')
        if not href or not href.startswith('serie/'): continue
        if len(href.strip('/').split('/')) != 2: continue
        if href in seen: continue
        seen.add(href)
        series_title = _clean_text(m.group(2)) or href.rsplit('/', 1)[-1].replace('-', ' ')
        if not series_title: continue
        items.append({
            'title':       series_title,
            'url':         urljoin(_base(), href),
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'get_seasons',
        })
    return items


def _browse_new(url, section_id):
    html = _get(url, _base())
    m = re.search(r'<section[^>]*id=["\']%s["\'][^>]*>.*?<ul[^>]*>(.*?)</ul>.*?</section>' % re.escape(section_id), html, re.S | re.I)
    if not m:
        return []
    items = []
    for lm in re.finditer(r'<li[^>]*>\s*<a\b([^>]*)>(.*?)</a>', m.group(1), re.I | re.S):
        href = _attr(lm.group(1), 'href')
        title = _clean_text(lm.group(2))
        if not href or not title: continue
        if not href.startswith('http'):
            href = urljoin(_base(), href)
        items.append({
            'title':       title,
            'url':         href,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'get_seasons',
        })
    return items


def _browse_genre(url):
    html = _get(url, _base())
    items = []
    for m in re.finditer(r'<div[^>]*class=["\'][^"\']*genre[^"\']*["\'][^>]*>.*?<strong>([^<]+)</strong>(.*?)</div>', html, re.I | re.S):
        genre_name = _clean_text(m.group(1))
        if not genre_name: continue
        items.append({
            'title':       genre_name,
            'url':         '__genre__:' + genre_name,
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _browse_genre_entries(genre_name):
    html = _get(urljoin(_base(), 'serie-genre'), _base())
    pat = r'<div[^>]*class=["\'][^"\']*genre[^"\']*["\'][^>]*>\s*<span>\s*<strong>%s</strong>\s*</span>\s*<ul>(.*?)</ul>' % re.escape(genre_name)
    m = re.search(pat, html, re.S | re.I)
    if not m:
        return []
    items = []
    for lm in re.finditer(r'<a\b([^>]*)>(.*?)</a>', m.group(1), re.I | re.S):
        href = _attr(lm.group(1), 'href')
        title = _clean_text(lm.group(2))
        if not href or not title: continue
        if not href.startswith('http'):
            href = urljoin(_base(), href)
        items.append({
            'title':       title,
            'url':         href,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'get_seasons',
        })
    return items


def get_seasons(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    html = _get(url, _base())
    seasons = []
    for m in re.finditer(r'<li[^>]*class=["\']s(\d+)(?:\s+active)?["\'][^>]*>\s*<a\b([^>]*)>([^<]+)</a>', html, re.I):
        s_num = int(m.group(1))
        href = _attr(m.group(2), 'href') or m.group(2).strip()
        s_name = _clean_text(m.group(3))
        if s_num == 0:
            continue
        s_url = href if href.startswith('http') else urljoin(_base(), href)
        seasons.append({
            'title':       'Staffel %s' % s_num if not s_name else s_name,
            'url':         s_url,
            'season':      s_num,
            'is_playable': False,
            'next_func':   'get_episodes',
        })
    seasons.sort(key=lambda x: x['season'])
    return seasons


def get_episodes(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    if params:
        season = int(params.get('season', season))
    html = _get(url, _base())
    episodes = []
    pattern = r'<tr[^>]*>\s*<td>\s*<a\b([^>]*)>(\d+)</a>\s*</td>\s*<td>.*?<a\b([^>]*)title=["\']([^"\']+)["\'][^>]*>'
    for m in re.finditer(pattern, html, re.I | re.S):
        ep_num = int(m.group(2))
        ep_title = _clean_text(m.group(4))
        ep_href = _attr(m.group(1), 'href')
        ep_url = ep_href if ep_href.startswith('http') else urljoin(_base(), ep_href)
        episodes.append({
            'title':       '%s - %s' % (ep_num, ep_title) if ep_title else str(ep_num),
            'url':         ep_url,
            'season':      season,
            'episode':     ep_num,
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    episodes.sort(key=lambda x: x['episode'])
    return episodes


def load(url='', params=None):
    if url:
        if url.startswith('__genre__:'):
            return _browse_genre_entries(url[len('__genre__:'):])
        if url == '__new_series__':
            return _browse_new(_base(), 'newest_series')
        if url == '__new_episodes__':
            return _browse_new(_base(), 'newest_episodes')
        if url == '__genre_list__':
            return _browse_genre(urljoin(_base(), 'serie-genre'))
        return _browse_series_list(url)
    b = _base()
    return [
        {'title': 'Neue Serien',  'url': '__new_series__',                     'is_playable': False, 'next_func': 'load'},
        {'title': 'Neue Folgen',  'url': '__new_episodes__',                    'is_playable': False, 'next_func': 'load'},
        {'title': 'Alle Serien',  'url': urljoin(b, 'andere-serien'),           'is_playable': False, 'next_func': 'load'},
        {'title': 'Genre',        'url': '__genre_list__',                      'is_playable': False, 'next_func': 'load'},
        {'title': 'Von A-Z',      'url': urljoin(b, 'serie-alphabet'),          'is_playable': False, 'next_func': 'load'},
        {'title': 'Suche',        'url': urljoin(b, 'andere-serien'),           'is_playable': False, 'next_func': 'search'},
    ]


def _resolve_episode_url(title, season, episode):
    season  = int(season  or 0)
    episode = int(episode or 0)
    if not title or season == 0 or episode == 0:
        log.log('[bsto] _resolve_episode_url: ungueltige Parameter title=%s s=%d e=%d' % (title, season, episode), log.LOGWARNING)
        return ''

    series_list = _find_series(title)
    if not series_list:
        log.log('[bsto] _resolve_episode_url: Serie nicht gefunden fuer "%s"' % title, log.LOGWARNING)
        return ''

    series_path = series_list[0][0]
    series_url  = urljoin(_base(), series_path)
    log.log('[bsto] _resolve_episode_url: Serie gefunden %s' % series_url)

    seasons = get_seasons(url=series_url)
    season_url = ''
    for s in seasons:
        if s.get('season') == season:
            season_url = s.get('url', '')
            break

    if not season_url:
        log.log('[bsto] _resolve_episode_url: Staffel %d nicht gefunden auf %s' % (season, series_url), log.LOGWARNING)
        return ''

    log.log('[bsto] _resolve_episode_url: Staffel-URL=%s' % season_url)

    episodes = get_episodes(url=season_url, season=season)
    for ep in episodes:
        if ep.get('episode') == episode:
            ep_url = ep.get('url', '')
            log.log('[bsto] _resolve_episode_url: Episode %d gefunden %s' % (episode, ep_url))
            return ep_url

    log.log('[bsto] _resolve_episode_url: Episode %d nicht gefunden auf %s' % (episode, season_url), log.LOGWARNING)
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if not url:
        log.log('[bsto] get_hosters: keine URL, starte Titelsuche fuer "%s" S%02dE%02d' % (title, int(season or 0), int(episode or 0)))
        url = _resolve_episode_url(title, season, episode)
        if not url:
            return []

    stripped = url.rstrip('/')
    last_seg = stripped.rsplit('/', 1)[-1]

    if last_seg in ('de', 'en', 'des'):
        base_ep_url = stripped.rsplit('/', 1)[0]
        lang_codes = [last_seg]
    else:
        base_ep_url = stripped
        lang_codes = ['de', 'en', 'des']

    log.log('[bsto] get_hosters: base_ep_url=%s langs=%s' % (base_ep_url, lang_codes))
    result = []
    seen = set()

    for lang_code in lang_codes:
        page_url = base_ep_url + '/' + lang_code
        log.log('[bsto] get_hosters: lade %s' % page_url)
        html = _get(page_url, _base())
        if not html:
            log.log('[bsto] get_hosters: leere Antwort fuer %s' % page_url, log.LOGWARNING)
            continue
        hosters = _parse_hoster_links(html, page_url)
        log.log('[bsto] get_hosters: %d hoster auf %s' % (len(hosters), page_url))
        for hoster, hoster_url, lang in hosters:
            if hoster_url in seen:
                continue
            seen.add(hoster_url)
            source_language, _ = _language_from_code(lang)
            stream_url = _resolve_hoster_url(hoster_url, page_url)
            if not stream_url:
                log.log('[bsto] get_hosters: kein stream fuer %s' % hoster_url, log.LOGWARNING)
                continue
            log.log('[bsto] get_hosters: hoster=%s stream=%s lang=%s' % (hoster, stream_url[:80], source_language))
            result.append((hoster, stream_url, True, 'SD', source_language))

    log.log('[bsto] get_hosters: gesamt %d hoster' % len(result))
    return result

def get_hoster_url(url='', params=None):
    referer = params.get('referer', _base()) if params else _base()
    log.log('[bsto] get_hoster_url: url=%s' % url)
    stream_url = _resolve_hoster_url(url, referer)
    if stream_url:
        log.log('[bsto] get_hoster_url: stream=%s' % stream_url)
        return [{'streamUrl': stream_url, 'resolved': False}]
    log.log('[bsto] get_hoster_url: kein stream fuer %s' % url, log.LOGERROR)
    return [{'streamUrl': '', 'resolved': False}]


def search(query='', params=None):
    variants = [_cleantitle(query)]
    html = _get(urljoin(_base(), 'andere-serien'), _base())
    items = []
    seen = set()
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.I | re.S):
        href = _attr(m.group(1), 'href')
        if not href or not href.startswith('serie/'): continue
        if len(href.strip('/').split('/')) != 2: continue
        if href in seen: continue
        seen.add(href)
        series_title = _clean_text(m.group(2)) or href.rsplit('/', 1)[-1].replace('-', ' ')
        if not _titles_match(variants, series_title): continue
        items.append({
            'title':       series_title,
            'url':         urljoin(_base(), href),
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'get_seasons',
        })
    return items


def get_details(url='', params=None):
    if not url:
        return {}
    html = _get(url, _base())
    result = {}
    m = re.search(r'<div[^>]*id=["\']sp_left["\'][^>]*>.*?<p>(.*?)</p>', html, re.S | re.I)
    if m:
        result['plot'] = _clean_text(m.group(1))
    y = re.search(r'Produktionsjahre.*?<em>(\d{4})', html, re.S | re.I)
    if y:
        result['year'] = y.group(1)
    pm = re.search(r'<div[^>]*id=["\']sp_right["\'][^>]*>.*?<img[^>]*src=["\']([^"\']+)["\']', html, re.S | re.I)
    if pm:
        src = pm.group(1)
        result['poster'] = src if src.startswith('http') else urljoin(_base(), src)
    return result
