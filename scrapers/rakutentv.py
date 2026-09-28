# -*- coding: utf-8 -*-
#THX zusatzmetall für Hilfe
import datetime
import json
import os
import time
import uuid
import urllib.error
from calendar import timegm as TGM
from urllib.parse import urlencode, quote

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import log, multiquest

SITE_ID       = 'rakutentv'
SITE_NAME     = 'Rakuten TV'
SITE_DOMAIN   = 'rakuten.tv'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True
STREAMLG      = 'L0'

try:
    _ICON = xbmcaddon.Addon().getAddonInfo('icon')
except Exception:
    _ICON = ''

_GIZMO    = 'https://gizmo.rakuten.tv/v3'
_BASE_URL = 'https://www.rakuten.tv/'
_PER_PAGE = 24
_UA       = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')
_ATV_AGENT = ('Mozilla/5.0 (Linux; Android 11; SHIELD Android TV '
              'Build/RQ1A.210105.003; wv) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Version/4.0 Chrome/99.0.4844.88 '
              'Mobile Safari/537.36')

_REGION_URL      = 'https://ipwho.is/?output=json'
_COUNTRY_MARKETS = {
    'DE': ('de', 'de',    '307'),
    'AT': ('at', 'de-AT', '300'),
    'CH': ('ch', 'de-CH', '319'),
}
_MARKET_CACHE   = [None]
_SERIAL_CACHE   = [None]
_WEB_IDS_CACHE  = [None]
_CHANNEL_CACHE  = [None]
_GUIDE_CACHE    = [None]
_PLATFORM_CACHE = [None]


def _detect_platform():
    if _PLATFORM_CACHE[0]:
        return _PLATFORM_CACHE[0]
    try:
        is_android = bool(xbmc.getCondVisibility('System.Platform.Android'))
    except Exception:
        is_android = False
    platform = 'atvui40' if is_android else 'web'
    _PLATFORM_CACHE[0] = platform
    log.log('[RakutenTV] _detect_platform -> %s' % platform)
    return platform


def _detect_market():
    if _MARKET_CACHE[0]:
        return _MARKET_CACHE[0]
    market, locale_, class_id = ('de', 'de', '307')
    try:
        r = multiquest.get(_REGION_URL, timeout=8)
        if r.status_code < 400:
            data = json.loads(r.text)
            cc = (data.get('country_code') or '').upper()
            if cc in _COUNTRY_MARKETS:
                market, locale_, class_id = _COUNTRY_MARKETS[cc]
            log.log('[RakutenTV] IP-Land: %s -> market=%s locale=%s class=%s'
                    % (cc or '?', market, locale_, class_id))
        else:
            log.log('[RakutenTV] IP-Check HTTP %d, Fallback DE' % r.status_code, log.LOGWARNING)
    except Exception as e:
        log.log('[RakutenTV] IP-Check fehlgeschlagen: %s, Fallback DE' % e, log.LOGWARNING)
    _MARKET_CACHE[0] = (market, locale_, class_id)
    return _MARKET_CACHE[0]


def _base_params():
    market, locale_, class_id = _detect_market()
    return {
        'classification_id':           class_id,
        'device_identifier':           'web',
        'device_stream_audio_quality': '2.0',
        'device_stream_hdr_type':      'NONE',
        'device_stream_video_quality': 'FHD',
        'locale':                      locale_,
        'market_code':                 market,
    }


def _params_user():
    p = _base_params()
    p['live_channel_support'] = 'false'
    p['user_status']          = 'visitor'
    return p


def _params_pack():
    p = _base_params()
    p['disable_dash_legacy_packages'] = 'false'
    return p


def _get_device_serial():
    if _SERIAL_CACHE[0]:
        return _SERIAL_CACHE[0]
    try:
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        path = os.path.join(profile, 'rakutentv_device.json')
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        serial = data.get('device_serial') or ''
        if serial:
            _SERIAL_CACHE[0] = serial
            return serial
        serial = str(uuid.uuid4())
        try:
            os.makedirs(profile, exist_ok=True)
        except Exception:
            pass
        data['device_serial'] = serial
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
        _SERIAL_CACHE[0] = serial
        return serial
    except Exception:
        serial = str(uuid.uuid4())
        _SERIAL_CACHE[0] = serial
        return serial


def _get_web_ids():
    if _WEB_IDS_CACHE[0]:
        return _WEB_IDS_CACHE[0]
    try:
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        path = os.path.join(profile, 'rakutentv_device.json')
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        uid = data.get('device_uid') or ''
        ppid = data.get('publisher_provided_id') or ''
        if uid and ppid:
            _WEB_IDS_CACHE[0] = (uid, ppid)
            return uid, ppid
        uid  = uid  or str(uuid.uuid4())
        ppid = ppid or str(uuid.uuid4())
        try:
            os.makedirs(profile, exist_ok=True)
        except Exception:
            pass
        data['device_uid'] = uid
        data['publisher_provided_id'] = ppid
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
        _WEB_IDS_CACHE[0] = (uid, ppid)
        return uid, ppid
    except Exception:
        ids = (str(uuid.uuid4()), str(uuid.uuid4()))
        _WEB_IDS_CACHE[0] = ids
        return ids


def _headers(content_type=None, ua=None):
    h = {
        'User-Agent':      ua or _UA,
        'Accept':          'application/json, text/plain, */*',
        'Accept-Language': 'de-DE,de;q=0.9',
        'Origin':          'https://www.rakuten.tv',
        'Referer':         'https://www.rakuten.tv/',
    }
    if content_type:
        h['Content-Type'] = content_type
    return h


def _get(path, extra=None, timeout=15, base=None):
    p = base() if base else _base_params()
    if extra:
        p.update(extra)
    try:
        r = multiquest.get(_GIZMO + path, params=p, headers=_headers(), timeout=timeout)
        log.log('[RakutenTV] GET %d %s' % (r.status_code, path))
        if r.status_code >= 400:
            log.log('[RakutenTV] GET Fehler body=%s' % r.text[:200], log.LOGWARNING)
            return None
        return json.loads(r.text)
    except Exception as e:
        log.log('[RakutenTV] GET Fehler %s | path=%s' % (e, path), log.LOGWARNING)
        return None


def _post(path, body, extra=None, timeout=15, ua=None, replace_params=False):
    p = {} if replace_params else _base_params()
    if extra:
        p.update(extra)
    url = _GIZMO + path + '?' + urlencode(p)
    try:
        r = multiquest.post(
            url,
            data=json.dumps(body),
            headers=_headers('application/json; charset=utf-8', ua=ua),
            timeout=timeout,
        )
        log.log('[RakutenTV] POST %d %s' % (r.status_code, path))
        if r.status_code >= 400:
            log.log('[RakutenTV] POST Fehler body=%s' % r.text[:200], log.LOGWARNING)
            return None
        return json.loads(r.text)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode('utf-8', 'replace')[:500]
        except Exception:
            detail = ''
        log.log('[RakutenTV] POST HTTPError %s %s body=%s' % (e.code, path, detail), log.LOGWARNING)
        return None
    except Exception as e:
        log.log('[RakutenTV] POST Fehler %s | path=%s' % (e, path), log.LOGWARNING)
        return None


def _thumb(images):
    if not images:
        return _ICON
    return (images.get('artwork') or
            images.get('artwork_webp') or
            images.get('snapshot') or
            _ICON)


def _item_from_movie(entry):
    cid   = entry.get('id') or ''
    title = entry.get('title') or entry.get('display_name') or ''
    if not cid or not title:
        return None
    images = entry.get('images') or {}
    thumb  = _thumb(images)
    return {
        'title':       title,
        'url':         'movie:%s' % cid,
        'poster':      thumb,
        'icon':        thumb,
        'fanart':      thumb,
        'plot':        entry.get('short_plot') or '',
        'year':        str(entry.get('year') or ''),
        'mediatype':   'movie',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _item_from_show(entry):
    cid   = entry.get('id') or ''
    title = entry.get('title') or ''
    if not cid or not title:
        return None
    seasons   = entry.get('seasons') or []
    season_id = (seasons[0].get('id') or '') if seasons else ''
    if not season_id:
        season_id = cid
    images = entry.get('images') or {}
    thumb  = _thumb(images)
    return {
        'title':       title,
        'url':         'show:%s' % season_id,
        'poster':      thumb,
        'icon':        thumb,
        'fanart':      thumb,
        'plot':        entry.get('short_plot') or '',
        'mediatype':   'tvshow',
        'is_playable': False,
        'next_func':   'showSeasons',
    }


def _item_from_live(entry):
    cid   = entry.get('id') or ''
    title = entry.get('title') or ''
    if not cid or not title:
        return None
    images  = entry.get('images') or {}
    logo    = (images.get('artwork_negative') or
               images.get('artwork') or
               _ICON)
    fanart  = images.get('snapshot') or images.get('artwork') or logo
    ch_no   = entry.get('channel_number') or ''
    label   = '[%s] %s' % (ch_no, title) if ch_no else title
    epg_now = (entry.get('current_epg') or {}).get('title') or ''
    plot    = ('[B]%s[/B]\n' % epg_now) + (entry.get('short_plot') or '') if epg_now else (entry.get('short_plot') or '')
    return {
        'title':       '[COLOR gold][B]%s[/B][/COLOR]' % label,
        'url':         'live:%s' % cid,
        'poster':      logo,
        'icon':        logo,
        'fanart':      fanart,
        'plot':        plot,
        'mediatype':   'video',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _item_from_entry(entry):
    t = (entry.get('type') or '').lower()
    if t == 'movies':
        return _item_from_movie(entry)
    if t == 'tv_shows':
        return _item_from_show(entry)
    if t == 'live_channels':
        return _item_from_live(entry)
    log.log('[RakutenTV] _item_from_entry unbekannter type=%s' % t)
    return None


def _garden_lists(garden_id):
    data = _get('/skeleton/gardens/%s' % garden_id, base=_params_user)
    if not data:
        return []
    return (data.get('data') or {}).get('lists') or []


def _list_data(list_id):
    data = _get('/lists/%s' % list_id, extra={'contents[per_page]': str(_PER_PAGE)})
    if not data:
        return {}, []
    d        = data.get('data') or {}
    contents = (d.get('contents') or {}).get('data') or []
    return d, contents


def _list_page_contents(list_id, page):
    data = _get('/lists/%s/contents' % list_id, extra={
        'page':     str(page),
        'per_page': str(_PER_PAGE),
    })
    if not data:
        return [], 0, 0
    raw   = data.get('data') or []
    meta  = data.get('meta') or {}
    total = int(meta.get('total_count') or meta.get('total') or 0)
    pages = int(meta.get('total_pages') or (total // _PER_PAGE + 1) or 0)
    return raw, total, pages


def _fmt_epg_ts(ts):
    dt = datetime.datetime.utcfromtimestamp(ts)
    return dt.strftime('%Y-%m-%dT%H:00:00.000Z')


def _parse_guides(program):
    guides_infos = ''
    counter = 0
    for scraps in program:
        start_date = datetime.datetime(*(time.strptime(scraps['starts_at'][:19], '%Y-%m-%dT%H:%M:%S')[0:6]))
        ends_date  = datetime.datetime(*(time.strptime(scraps['ends_at'][:19],   '%Y-%m-%dT%H:%M:%S')[0:6]))
        title   = scraps.get('title') or ''
        episode = scraps.get('subtitle') if scraps.get('subtitle') and len(scraps.get('subtitle', '')) > 5 else None
        desc    = '[CR]'
        if scraps.get('description') and len(scraps['description']) > 10 and \
                'info not available' not in scraps['description'].lower() and \
                title.lower() != scraps['description'].lower():
            raw = scraps['description'][:300].replace(chr(10), '').strip()
            desc = '%s...[CR][CR]' % raw if len(scraps['description']) > 300 else '%s[CR][CR]' % raw
        if counter < 6 and ends_date > datetime.datetime.now():
            counter += 1
            ts = '%s - %s' % (start_date.strftime('%H:%M'), ends_date.strftime('%H:%M'))
            if episode is None:
                guides_infos += '[B]%s[/B]  %s[CR]%s' % (ts, title, desc)
            else:
                guides_infos += '[B]%s[/B]  %s  [I](%s)[/I][CR]%s' % (ts, title, episode, desc)
    return guides_infos


def _fetch_all_channels():
    if _GUIDE_CACHE[0]:
        return _GUIDE_CACHE[0]
    from concurrent.futures import ThreadPoolExecutor, wait, as_completed, ALL_COMPLETED
    now_utc     = datetime.datetime.utcnow()
    utc_start   = (now_utc - datetime.timedelta(hours=4)).strftime('%Y-%m-%dT%H:00:00.000Z')
    utc_ends    = (now_utc + datetime.timedelta(hours=26)).strftime('%Y-%m-%dT%H:00:00.000Z')
    epoch_start = TGM(time.strptime(utc_start[:19], '%Y-%m-%dT%H:%M:%S')) * 1000
    epoch_ends  = TGM(time.strptime(utc_ends[:19],  '%Y-%m-%dT%H:%M:%S')) * 1000
    base = _base_params()
    base.update({
        'epg_duration_minutes':    '360',
        'epg_starts_at':           utc_start,
        'epg_starts_at_timestamp': str(epoch_start),
        'epg_ends_at':             utc_ends,
        'epg_ends_at_timestamp':   str(epoch_ends),
        'per_page':                '25',
    })
    urls = []
    for page in range(1, 9):
        p = dict(base)
        p['page'] = str(page)
        urls.append({'page': page, 'url': _GIZMO + '/live_channels?' + urlencode(p)})

    hdrs = _headers()
    results_by_page = {}

    def _fetch_page(entry):
        try:
            r = multiquest.get(entry['url'], headers=hdrs, timeout=20)
            if r.status_code < 400:
                return entry['page'], json.loads(r.text)
        except Exception as e:
            log.log('[RakutenTV] _fetch_all_channels Seite %d Fehler: %s' % (entry['page'], e), log.LOGWARNING)
        return entry['page'], None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_page, u) for u in urls]
        wait(futures, timeout=30, return_when=ALL_COMPLETED)
        for future in as_completed(futures):
            try:
                page, data = future.result()
                if data:
                    results_by_page[page] = data
            except Exception as e:
                log.log('[RakutenTV] _fetch_all_channels future Fehler: %s' % e, log.LOGWARNING)

    all_channels = []
    for page in sorted(results_by_page):
        batch = results_by_page[page].get('data') or []
        all_channels.extend(batch)

    all_channels.sort(key=lambda x: (x.get('title') or '').lower())
    result = {'data': all_channels}
    _GUIDE_CACHE[0] = result
    log.log('[RakutenTV] _fetch_all_channels total=%d' % len(all_channels))
    return result


def _fetch_channel_categories():
    if _CHANNEL_CACHE[0]:
        return _CHANNEL_CACHE[0]
    top15_data = _get('/lists/live-tv-top-15', base=_base_params)
    cats_data  = _get('/live_channel_categories', base=_base_params)
    simplex    = 'LIVE TV | Top 15'
    categories = {simplex: []}
    if top15_data:
        for item in (top15_data.get('data') or {}).get('contents', {}).get('data') or []:
            cid = item.get('id') or ''
            if cid:
                categories[simplex].append(cid)
    if cats_data:
        for cat in sorted(cats_data.get('data') or [], key=lambda x: (x.get('name') or '').lower()):
            name     = cat.get('name') or ''
            channels = cat.get('live_channels') or []
            if name:
                categories[name] = channels
    _CHANNEL_CACHE[0] = categories
    log.log('[RakutenTV] _fetch_channel_categories cats=%d' % len(categories))
    return categories


def load(url='', params=None):
    return [
        {
            'title':       'Filme',
            'url':         'free-movies',
            'plot':        'Alle kostenlosen Filme auf Rakuten TV (AVOD) nach Genre.',
            'is_playable': False,
            'next_func':   'showGenres',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Serien',
            'url':         'free-shows',
            'plot':        'Alle kostenlosen Serien auf Rakuten TV.',
            'is_playable': False,
            'next_func':   'showGenres',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Live TV (nach Kategorie)',
            'url':         '',
            'plot':        'FAST Live-Kanäle nach Kategorie mit EPG-Programminformationen.',
            'is_playable': False,
            'next_func':   'showLiveCategories',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Live TV (alle Kanäle)',
            'url':         'all',
            'plot':        'Alle FAST Live-Kanäle auf Rakuten TV mit EPG.',
            'is_playable': False,
            'next_func':   'showAllLiveChannels',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Suche',
            'url':         '',
            'plot':        'Rakuten TV durchsuchen.',
            'is_playable': False,
            'next_func':   'search',
            'poster':      _ICON,
            'icon':        _ICON,
        },
    ]


def showGenres(url='', params=None):
    is_movies   = (url == 'free-movies')
    target_type = 'Movie' if is_movies else 'TvShow'
    all_lists   = _garden_lists('avod-fast')
    items       = []
    seen        = set()
    for lst in all_lists:
        if lst.get('type') != 'lists':
            continue
        if lst.get('content_type') != target_type:
            continue
        list_id = lst.get('id') or ''
        if not list_id or list_id in seen:
            continue
        seen.add(list_id)
        meta, first_page = _list_data(list_id)
        name = (meta.get('name') or meta.get('short_name') or
                list_id.replace('-', ' ').replace('free ', '').replace('free-', '').title())
        if ' | ' in name:
            name = name.split(' | ', 1)[1]
        if not name:
            continue
        items.append({
            'title':       name,
            'url':         'list:%s:1' % list_id,
            'plot':        name,
            'is_playable': False,
            'next_func':   'showList',
            'poster':      _ICON,
            'icon':        _ICON,
        })
    log.log('[RakutenTV] showGenres %s count=%d' % (url, len(items)))
    return items


def showList(url='', params=None):
    if not url.startswith('list:'):
        return []
    parts   = url[5:].rsplit(':', 1)
    list_id = parts[0]
    page    = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    if page == 1:
        meta, raw = _list_data(list_id)
        total_pages = 0
        if meta:
            contents_meta = (meta.get('contents') or {})
            total = int(contents_meta.get('total_count') or 0)
            total_pages = (total + _PER_PAGE - 1) // _PER_PAGE if total else 0
    else:
        raw, total, total_pages = _list_page_contents(list_id, page)
    items = []
    for e in raw:
        item = _item_from_entry(e)
        if item:
            items.append(item)
    log.log('[RakutenTV] showList list=%s page=%d items=%d' % (list_id, page, len(items)))
    if total_pages and page < total_pages:
        items.append({
            'title':       '>> Weiter (Seite %d/%d)' % (page + 1, total_pages),
            'url':         'list:%s:%d' % (list_id, page + 1),
            'plot':        'Nächste Seite laden',
            'is_playable': False,
            'next_func':   'showList',
        })
    return items


def showLiveCategories(url='', params=None):
    categories = _fetch_channel_categories()
    items      = []
    for cat_name in categories:
        items.append({
            'title':       cat_name,
            'url':         'cat:%s' % cat_name,
            'plot':        cat_name,
            'is_playable': False,
            'next_func':   'showLiveCategoryChannels',
            'poster':      _ICON,
            'icon':        _ICON,
        })
    items.append({
        'title':       'Alle Kanäle',
        'url':         'all',
        'plot':        'Alle Live-Kanäle ohne Kategoriefilter.',
        'is_playable': False,
        'next_func':   'showAllLiveChannels',
        'poster':      _ICON,
        'icon':        _ICON,
    })
    log.log('[RakutenTV] showLiveCategories count=%d' % len(items))
    return items


def showLiveCategoryChannels(url='', params=None):
    if not url.startswith('cat:'):
        return []
    cat_name   = url[4:]
    categories = _fetch_channel_categories()
    channel_ids = categories.get(cat_name) or []
    if not channel_ids:
        log.log('[RakutenTV] showLiveCategoryChannels keine IDs für %s' % cat_name, log.LOGWARNING)
        return []
    guides = _fetch_all_channels()
    all_ch = guides.get('data') or []
    id_set = set(str(x) for x in channel_ids)
    items  = []
    for ch in sorted(all_ch, key=lambda x: (x.get('title') or '').lower()):
        if ch.get('id') not in id_set:
            continue
        item = _build_live_item_with_epg(ch)
        if item:
            items.append(item)
    log.log('[RakutenTV] showLiveCategoryChannels cat=%s count=%d' % (cat_name, len(items)))
    return items


def showAllLiveChannels(url='', params=None):
    guides = _fetch_all_channels()
    all_ch = guides.get('data') or []
    items  = []
    for ch in all_ch:
        item = _build_live_item_with_epg(ch)
        if item:
            items.append(item)
    log.log('[RakutenTV] showAllLiveChannels count=%d' % len(items))
    return items


def _build_live_item_with_epg(ch):
    cid   = ch.get('id') or ''
    title = ch.get('title') or ''
    if not cid or not title:
        return None
    images = ch.get('images') or {}
    logo   = (images.get('artwork_negative') or
               images.get('artwork') or
               images.get('artwork_webp') or
               _ICON)
    fanart = images.get('snapshot') or images.get('artwork') or logo
    lang   = ''
    try:
        lang = ch['labels']['languages'][0]['id']
    except Exception:
        pass
    programs = ch.get('live_programs') or []
    epg_plot = _parse_guides(programs) if programs else (ch.get('short_plot') or '')
    return {
        'title':       '[COLOR gold][B]%s[/B][/COLOR]' % title,
        'url':         'live:%s:%s' % (cid, lang),
        'poster':      logo,
        'icon':        logo,
        'fanart':      fanart,
        'plot':        epg_plot,
        'mediatype':   'video',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def showSeasons(url='', params=None):
    if not url.startswith('show:'):
        return []
    season_id = url[5:]
    data      = _get('/seasons/%s' % season_id, base=_params_pack)
    if not data:
        return []
    d            = data.get('data') or {}
    other        = d.get('other_seasons') or []
    all_seasons  = [d] + other if other else [d]
    if len(all_seasons) == 1:
        return showEpisodes('season:%s' % season_id)
    images = d.get('images') or {}
    thumb  = _thumb(images)
    items  = []
    for s in all_seasons:
        sid   = s.get('id') or ''
        snum  = s.get('season_number') or s.get('number') or 0
        label = 'Staffel %s' % snum
        if not sid:
            continue
        items.append({
            'title':       label,
            'url':         'season:%s' % sid,
            'plot':        label,
            'mediatype':   'season',
            'season':      int(snum) if str(snum).isdigit() else 1,
            'is_playable': False,
            'next_func':   'showEpisodes',
            'poster':      thumb,
            'icon':        thumb,
        })
    log.log('[RakutenTV] showSeasons season_id=%s seasons=%d' % (season_id, len(items)))
    return items


def showEpisodes(url='', params=None):
    if not url.startswith('season:'):
        return []
    season_id = url[7:]
    data      = _get('/seasons/%s' % season_id, base=_params_pack)
    if not data:
        return []
    d        = data.get('data') or {}
    episodes = d.get('episodes') or []
    snum     = d.get('season_number') or d.get('number') or 1
    items    = []
    for ep in episodes:
        eid    = ep.get('id') or ''
        title  = ep.get('title') or ''
        ep_num = ep.get('number') or ep.get('episode_number') or 0
        images = ep.get('images') or {}
        thumb  = _thumb(images)
        if not eid:
            continue
        if str(ep_num).isdigit() and str(snum).isdigit():
            label = 'S%sE%s - %s' % (str(snum).zfill(2), str(ep_num).zfill(2), title) if title else 'S%sE%s' % (str(snum).zfill(2), str(ep_num).zfill(2))
        else:
            label = title or ('Episode %s' % ep_num)
        items.append({
            'title':       label,
            'url':         'episode:%s:%s' % (eid, season_id),
            'poster':      thumb,
            'icon':        thumb,
            'fanart':      thumb,
            'plot':        ep.get('short_plot') or ep.get('plot') or '',
            'mediatype':   'episode',
            'season':      int(snum) if str(snum).isdigit() else 1,
            'episode':     int(ep_num) if str(ep_num).isdigit() else 0,
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    log.log('[RakutenTV] showEpisodes season_id=%s snum=%s count=%d' % (season_id, snum, len(items)))
    return items


def _search_api(query, content_type, page=1):
    endpoint_map = {'Movie': 'movies', 'TvShow': 'tv_shows'}
    endpoint     = endpoint_map.get(content_type, content_type.lower())
    data = _get('/%s' % endpoint, extra={
        'query':         query,
        'search_engine': 'external',
        'page':          str(page),
        'per_page':      str(_PER_PAGE),
    })
    if not data:
        return []
    return data.get('data') or []


def search(query='', params=None, url=''):
    if isinstance(params, dict):
        query = query or params.get('query') or params.get('keyword') or ''
    if not query and isinstance(url, str) and url and url.lower() not in ('search', 'suche'):
        query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('Rakuten TV Suche')
            if r:
                query = r.strip()
        except Exception:
            pass
    if not query:
        return []
    log.log('[RakutenTV] Suche: "%s"' % query)
    movies = _search_api(query, 'Movie')
    shows  = _search_api(query, 'TvShow')
    items  = []
    for e in movies:
        item = _item_from_movie(e)
        if item:
            items.append(item)
    for e in shows:
        item = _item_from_show(e)
        if item:
            items.append(item)
    log.log('[RakutenTV] Suche "%s" → %d Treffer' % (query, len(items)))
    return items


def _scout_resolve(title, year, season, episode):
    if not title:
        return ''
    for ctype in ('Movie', 'TvShow'):
        results = _search_api(title, ctype)
        if not results:
            continue
        hits = [e for e in results
                if title.lower() in (e.get('title') or '').lower()]
        if not hits:
            hits = results
        if year:
            by_year = [e for e in hits if str(e.get('year') or '') == str(year)]
            if by_year:
                hits = by_year
        if ctype == 'Movie':
            mid = hits[0].get('id') or ''
            if mid:
                return 'movie:%s' % mid
            continue
        if ctype == 'TvShow':
            show_id = hits[0].get('id') or ''
            if not show_id:
                continue
            seasons  = hits[0].get('seasons') or []
            seas_id  = (seasons[0].get('id') or '') if seasons else ''
            if not seas_id:
                return 'show:%s' % show_id
            seas_data = _get('/seasons/%s' % seas_id, base=_params_pack)
            if not seas_data:
                return 'show:%s' % seas_id
            d   = seas_data.get('data') or {}
            eps = d.get('episodes') or []
            if season and season > 1:
                for other in (d.get('other_seasons') or []):
                    if str(other.get('season_number') or other.get('number') or '') == str(season):
                        other_id   = other.get('id') or ''
                        other_data = _get('/seasons/%s' % other_id, base=_params_pack) if other_id else None
                        if other_data:
                            d      = other_data.get('data') or {}
                            eps    = d.get('episodes') or []
                            seas_id = other_id
                        break
            for ep in eps:
                if str(ep.get('number') or '') == str(episode):
                    eid = ep.get('id') or ''
                    if eid:
                        return 'episode:%s:%s' % (eid, seas_id)
            if eps:
                return 'episode:%s:%s' % ((eps[0].get('id') or ''), seas_id)
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    u = str(url or '')

    if u.startswith('live:') and u.count(':') >= 2:
        parts    = u.split(':', 2)
        live_id  = parts[1]
        org_lang = parts[2] if len(parts) > 2 else 'DEU'
        return _play_live(live_id, org_lang)

    if not u.startswith(('movie:', 'live:', 'episode:', 'show:')):
        resolved = _scout_resolve(title, year, season, episode)
        if not resolved:
            log.log('[RakutenTV] Scout: kein Treffer für title=%s year=%s' % (title, year), log.LOGWARNING)
            return []
        u = resolved
    log.log('[RakutenTV] get_hosters url=%s' % u)

    if u.startswith('movie:'):
        content_id   = u[6:]
        content_type = 'movies'
    elif u.startswith('live:'):
        content_id   = u[5:].split(':')[0]
        content_type = 'live_channels'
        return _play_live(content_id, 'DEU')
    elif u.startswith('episode:'):
        parts      = u[8:].split(':', 1)
        ep_id      = parts[0]
        seas_id    = parts[1] if len(parts) > 1 else ''
        return _play_episode(ep_id, seas_id)
    elif u.startswith('show:'):
        resolved = _scout_resolve(title, year, season, episode)
        if resolved and not resolved.startswith('show:'):
            return get_hosters(url=resolved)
        log.log('[RakutenTV] get_hosters: show ohne Episode', log.LOGWARNING)
        return []
    else:
        log.log('[RakutenTV] get_hosters unbekanntes Schema: %s' % u, log.LOGWARNING)
        return []

    return _request_stream(content_id, content_type, is_live=False)


def _play_episode(ep_id, seas_id):
    platform = _detect_platform()
    if seas_id:
        def _params_vod():
            p = _params_pack()
            p['device_identifier'] = platform
            return p
        data = _get('/seasons/%s' % seas_id, base=_params_vod)
        if data:
            episodes = (data.get('data') or {}).get('episodes') or []
            matched  = [ep for ep in episodes if ep.get('id') == ep_id]
            if matched:
                log.log('[RakutenTV] _play_episode ep_id=%s season=%s' % (ep_id, seas_id))
                return _request_stream(ep_id, 'episodes', is_live=False)
    log.log('[RakutenTV] _play_episode fallback ep_id=%s' % ep_id)
    return _request_stream(ep_id, 'episodes', is_live=False)


def _play_live(content_id, org_lang):
    return _request_stream(content_id, 'live_channels', is_live=True, lang=org_lang)


def _request_stream(content_id, content_type, is_live=False, lang='DEU'):
    market, locale_, class_id = _detect_market()
    platform   = _detect_platform()
    is_android = platform == 'atvui40'
    vod_ua     = _ATV_AGENT if is_android else _UA
    body = {
        'audio_language':              lang or 'DEU',
        'audio_quality':               '2.0',
        'classification_id':           class_id,
        'content_id':                  content_id,
        'content_type':                content_type,
        'device_stream_video_quality': 'FHD',
        'hdr_type':                    'NONE',
        'video_type':                  'stream',
        'subtitle_formats':            ['vtt'],
        'subtitle_language':           'MIS',
        'support_closed_captions':     True,
    }
    if is_live:
        device_uid, publisher_provided_id = _get_web_ids()
        body.update({
            'device_serial':           'not implemented',
            'device_uid':              device_uid,
            'publisher_provided_id':   publisher_provided_id,
            'player':                  'web:HLS-NONE:NONE',
            'device_make':             'chrome',
            'device_model':            'GENERIC',
            'device_year':             1970,
            'strict_video_quality':    False,
            'support_thumbnails':      True,
        })
        extra_params = _params_pack()
    else:
        if is_android:
            body.update({
                'device_serial': _get_device_serial(),
                'player':        'atvui40:DASH-CENC:WVM',
            })
        else:
            device_uid, publisher_provided_id = _get_web_ids()
            body.update({
                'device_serial':         'not implemented',
                'device_uid':            device_uid,
                'publisher_provided_id': publisher_provided_id,
                'player':                'web:DASH-CENC:WVM',
            })
        extra_params = {
            'classification_id': class_id,
            'device_identifier': platform,
            'market_code':       market,
        }
    log.log('[RakutenTV] Stream request content_id=%s type=%s live=%s platform=%s'
            % (content_id, content_type, is_live, platform))
    post_ua     = None if is_live else vod_ua
    vod_replace = not is_live
    data = _post('/avod/streamings', body, extra=extra_params, ua=post_ua, replace_params=vod_replace)
    if not data:
        return []
    d            = data.get('data') or {}
    stream_infos = d.get('stream_infos') or []
    if not stream_infos:
        stream_url = d.get('stream_url') or d.get('hls_url') or d.get('url') or ''
        if stream_url:
            stream_infos = [{'url': stream_url, 'type': 'hls'}]
    if not stream_infos:
        log.log('[RakutenTV] _request_stream keine Stream-Infos | keys=%s' % list(d.keys()), log.LOGWARNING)
        return []
    drm_ua       = vod_ua if not is_live else _UA
    drm_ct       = 'application%%2Foctet-stream' if is_android else 'text%%2Fhtml'
    results = []
    for si in stream_infos:
        surl  = si.get('url') or ''
        stype = (si.get('type') or 'hls').lower()
        if not surl:
            continue
        if stype not in ('dash', 'mpd') and '.mpd' in surl.lower():
            stype = 'mpd'
        drm     = si.get('drm') or {}
        drm_key = (
            drm.get('widevine_license_url') or
            drm.get('license_acquisition_url') or
            drm.get('license_url') or
            si.get('license_url') or
            d.get('license_url') or
            ''
        ).strip()
        log.log('[RakutenTV] license_url=%s' % (drm_key[:80] if drm_key else 'none'))
        drm_info = {}
        if drm_key:
            _hdrs = (
                'User-Agent=%s&'
                'Referer=%s&'
                'Content-Type=%s'
                % (
                    quote(drm_ua, safe=''),
                    quote(_BASE_URL, safe=''),
                    drm_ct,
                )
            )
            drm_info['license_key'] = '%s|%s|R{SSM}|' % (drm_key, _hdrs)
            drm_info['server_certificate'] = 'CAQ='
        label  = 'RakutenTV'
        label += ' [%s]' % stype.upper() if stype else ''
        results.append([label, surl, drm_info, '', '', 'rakutentv'])
        log.log('[RakutenTV] stream stype=%s url=%s' % (stype, surl[:80]))
    return results
