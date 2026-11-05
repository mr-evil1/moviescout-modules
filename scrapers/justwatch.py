# -*- coding: utf-8 -*-
# JustWatch TV
# IT('s) Possible
# 2026.11.03
import json
import random
import re
import string
import uuid
import urllib.parse
from resources.lib import multiquest, log

_LANG_MAP      = {'DE': 'de', 'AT': 'de', 'CH': 'de', 'FR': 'fr', 'IT': 'it', 'ES': 'es', 'NL': 'nl', 'PL': 'pl'}
_country_cache = None

_COUNTRY_QUERY = """
query GetCountry {
  userInfo { country }
}
"""

def _detect_country():
    global _country_cache
    if _country_cache:
        return _country_cache
    try:
        payload = json.dumps({"operationName": "GetCountry", "query": _COUNTRY_QUERY, "variables": {}},
                             separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json", "Content-Type": "application/json",
            "Origin": "https://www.justwatch.com", "Referer": "https://www.justwatch.com/",
            "User-Agent": _UA,
        }
        r = multiquest.post(_API_ENDPOINT, data=payload, headers=headers, timeout=10)
        body = json.loads(r.text)
        code = ((body.get("data") or {}).get("userInfo") or {}).get("country", "")
        code = (code or "").strip().upper()
        if len(code) == 2 and code.isalpha():
            _country_cache = code
            log.log("[JustWatch] Land erkannt: %s" % code, log.LOGINFO)
            return code
        log.log("[JustWatch] Land nicht erkannt, Fallback AT", log.LOGWARNING)
    except Exception as e:
        log.log("[JustWatch] Landerkennung fehlgeschlagen (%s), Fallback AT" % e, log.LOGWARNING)
    _country_cache = "AT"
    return "AT"

SITE_ID       = 'justwatch'
SITE_NAME     = 'JustWatch TV'
SITE_DOMAIN   = 'www.justwatch.com'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True

_API_ENDPOINT = 'https://apis.justwatch.com/graphql'
_IMG_BASE     = 'https://images.justwatch.com'
_UA           = 'MovieScout JustWatch addon/1.0'
_BROWSER_UA   = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
_APP_VERSION  = '4.1.0-web-web'
_DEVICE_ID    = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(22))
_PAGE_VIEW    = str(uuid.uuid4())
_device_registered = False

_AUDIO        = 'de'
_PAGE_SIZE    = 30

POPULAR_QUERY = """
query GetPopularTitles($country: Country!, $first: Int!, $language: Language!, $offset: Int!, $popularTitlesFilter: TitleFilter!, $watchNowFilter: WatchNowOfferFilter!) {
  popularTitles(country: $country, filter: $popularTitlesFilter, first: $first, sortBy: POPULAR, offset: $offset) {
    edges { node {
      __typename id objectType
      content(country: $country, language: $language) {
        title fullPath originalReleaseYear posterUrl(profile: S718) ageCertification shortDescription __CONTENT__
      }
      watchNowOffer(country: $country, platform: WEB, filter: $watchNowFilter) {
        id standardWebURL streamUrlExternalPlayer streamUrl monetizationType __OFFER__
        package { clearName shortName technicalName }
      }
    } }
    pageInfo { hasNextPage }
    totalCount
  }
}
"""

SHOW_SEASONS_QUERY = """
query GetShowSeasons($fullPath: String!, $country: Country!, $language: Language!, $provider: String!) {
  urlV2(fullPath: $fullPath, site: "www") {
    node {
      __typename id
      ... on Show {
        content(country: $country, language: $language) { title shortDescription posterUrl(profile: S718) }
        seasons(sortDirection: DESC) {
          id
          content(country: $country, language: $language) {
            title seasonNumber fullPath posterUrl(profile: S718)
          }
          offers(country: $country, platform: WEB, filter: {packages: [$provider]__AUDIO__}) {
            id monetizationType package { technicalName clearName }
          }
        }
      }
    }
  }
}
"""

SEASON_EPISODES_QUERY = """
query GetSeasonEpisodes($seasonId: ID!, $country: Country!, $language: Language!, $provider: String!, $limit: Int!) {
  node(id: $seasonId) {
    __typename id
    ... on Season {
      content(country: $country, language: $language) { title seasonNumber posterUrl(profile: S718) }
      episodes(limit: $limit) {
        id
        content(country: $country, language: $language) {
          title seasonNumber episodeNumber shortDescription runtime
        }
        offers(country: $country, platform: WEB, filter: {packages: [$provider]__AUDIO__}) {
          id streamUrlExternalPlayer streamUrl monetizationType
          package { clearName shortName technicalName }
        }
      }
    }
  }
}
"""

TITLE_OFFERS_QUERY = """
query GetTitleOffers($fullPath: String!, $country: Country!, $provider: String!) {
  urlV2(fullPath: $fullPath, site: "www") {
    node {
      __typename id
      ... on Movie {
        offers(country: $country, platform: WEB, filter: {packages: [$provider]}) {
          id monetizationType streamUrlExternalPlayer streamUrl
          package { clearName shortName technicalName }
        }
      }
    }
  }
}
"""

PLAY_INFORMATION_QUERY = """
mutation GetPlayInformation($input: GetPlayInformationInput!) {
  getPlayInformation(input: $input) {
    errorCode
    playbackId
    streams {
      url encodingType drmType
      manifestUrlDash manifestUrlSignedVariants manifestContent
      secureStreamPaths { Path SignedCookie }
      drmConfigs { certificateURL drmType laURL }
    }
    offer { id streamUrlExternalPlayer streamUrl }
  }
}
"""


PLAY_INFORMATION_QUERY_BASE = """
mutation GetPlayInformation($input: GetPlayInformationInput!) {
  getPlayInformation(input: $input) {
    errorCode
    playbackId
    streams {
      url encodingType drmType manifestUrlDash
      drmConfigs { certificateURL drmType laURL }
    }
    offer { id streamUrlExternalPlayer streamUrl }
  }
}
"""


def _first_error(body):
    try:
        return str(body['errors'][0].get('message', ''))[:200]
    except Exception:
        return ''


def _api_raw(operation, query, variables, extra_headers=None):
    payload = json.dumps({"operationName": operation, "query": query, "variables": variables},
                         separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json", "Content-Type": "application/json",
        "Origin": "https://www.justwatch.com", "Referer": "https://www.justwatch.com/",
        "User-Agent": _UA,
    }
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = multiquest.post(_API_ENDPOINT, data=payload, headers=headers, timeout=20)
        try:
            body = json.loads(r.text)
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if r.status_code >= 400 or body.get("errors"):
            log.log('[JustWatch] %s: HTTP %s %s %s' % (operation, r.status_code, _first_error(body), (r.text or '')[:200]),
                    log.LOGWARNING)
        return body
    except Exception as exc:
        body_text = ''
        try:
            body_text = exc.read().decode('utf-8', errors='replace')[:500]
        except Exception:
            pass
        log.log('[JustWatch] API-Aufruf %s fehlgeschlagen: %s %s' % (operation, exc, body_text), log.LOGWARNING)
        return {}


def _api_call(operation, query, variables, extra_headers=None):
    return _api_raw(operation, query, variables, extra_headers).get("data") or {}


def _api_fallback(operation, build_query, build_vars, levels):
    for level in levels:
        raw = _api_raw(operation, build_query(level), build_vars(level))
        if raw.get("data") is not None and not raw.get("errors"):
            return raw["data"], level
        if not raw: 
            break
        log.log('[JustWatch] %s: Stufe %s fehlgeschlagen, versuche Fallback' % (operation, level),
                log.LOGWARNING)
    return {}, None


def _register_device():
    global _device_registered
    if _device_registered:
        return
    _device_registered = True
    query = 'mutation RegisterDeviceId { registerDeviceId(input: "%s") { deviceId } }' % _DEVICE_ID
    _api_raw("RegisterDeviceId", query, {}, {"User-Agent": _BROWSER_UA})


def _play_headers(country, language, fullpath):
    sg = "c=%s&l=%s&pv=%s&d=%s&p=%s&pa=%s&e=" % (
        country, language, _PAGE_VIEW, _DEVICE_ID, _APP_VERSION,
        urllib.parse.quote(fullpath or '/', safe=''))
    return {
        'app-version': _APP_VERSION,
        'device-id': _DEVICE_ID,
        'sg': sg,
        'Cookie': 'jw_id=%s' % _DEVICE_ID,
        'User-Agent': _BROWSER_UA,
    }


def _license_key(url, headers):
    return '%s|Content-Type=application%%2Foctet-stream&%s|R{SSM}|' % (url, headers)


def _hls_is_widevine(url):
    try:
        token = url.rsplit('/', 1)[-1].split('.')[0]
        token += '=' * (-len(token) % 4)
        data = json.loads(__import__('base64').urlsafe_b64decode(token.encode('ascii')).decode('utf-8'))
        return str(data.get('d') or '').lower() == 'widevine'
    except Exception:
        return False


def _api_context():
    country = _detect_country()
    return country, _LANG_MAP.get(country, 'en'), 'jwt'


def _image_url(path, profile, filename):
    if not path:
        return ''
    path = (path.replace('{profile}', profile)
                .replace('{format}', 'jpg')
                .replace('{filename}', filename))
    if path.startswith('//'):
        return 'https:' + path
    if path.startswith('/'):
        return _IMG_BASE + path
    return path


def _poster(path):
    return _image_url(path, 's718', 'poster.jpg')


def _fsk(age):
    age = str(age or '').strip()
    if not age:
        return ''
    return age if age.upper().startswith('FSK') else 'FSK %s' % age


def _audio_ok(offer):
    langs = [str(x).lower() for x in ((offer or {}).get("audioLanguages") or [])]
    return not langs or _AUDIO in langs


_CATALOG_LEVELS = ((True, True), (True, False), (False, True), (False, False))
_AUDIO_LEVELS   = (True, False)


def _catalog_query(level):
    audio, backdrop = level
    return (POPULAR_QUERY
            .replace('__CONTENT__', 'backdrops(profile: S1920) { backdropUrl }' if backdrop else '')
            .replace('__OFFER__', 'audioLanguages' if audio else ''))


def _catalog_variables(search_text, offset, object_type, level, scout=False):
    country, language, provider = _api_context()
    providers = [provider]
    monetization = ["FREE"]
    filter_value = {
        "ageCertifications": [],
        "excludeGenres": [],
        "excludeProductionCountries": [],
        "objectTypes": [object_type] if object_type else [],
        "productionCountries": [],
        "subgenres": [],
        "genres": [],
        "excludeIrrelevantTitles": False,
        "presentationTypes": [],
        "searchQuery": search_text,
    }
    if not scout:
        filter_value["packages"] = providers
        filter_value["monetizationTypes"] = monetization
    watch_filter = {"packages": providers, "monetizationTypes": monetization}
    return {
        "country": country, "language": language, "first": _PAGE_SIZE, "offset": offset,
        "popularTitlesFilter": filter_value, "watchNowFilter": watch_filter,
    }


def _audio_query(query, audio):
    return query.replace('__AUDIO__', ', audioLanguages: ["%s"]' % _AUDIO if audio else '')


def load(url='', params=None):
    if url:
        return showEntries(url, params)
    return [
        {'title': 'Beliebte kostenlose Titel', 'url': 'list', 'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'Filme', 'url': 'movies', 'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'Serien', 'url': 'series', 'is_playable': False, 'next_func': 'showEntries'},
        {'title': 'Suche', 'url': 'search', 'is_playable': False, 'next_func': 'search'},
    ]


def showEntries(url='', params=None):
    if not url or url == 'list':
        return _list_catalog(object_type='')
    if url == 'movies':
        return _list_catalog(object_type='MOVIE')
    if url == 'series':
        return _list_catalog(object_type='SHOW')
    if url.startswith('more:'):
        offset, object_type, search_text = (url[5:].split('||', 2) + ['', ''])[:3]
        return _list_catalog(search_text=search_text, offset=int(offset or 0), object_type=object_type)
    if url.startswith('seasons:'):
        fullpath, title = url[8:].split('||', 1)
        return _show_seasons(fullpath, title)
    if url.startswith('episodes:'):
        season_id, show_title = url[9:].split('||', 1)
        return _season_episodes(season_id, show_title)
    return []


def _fetch_catalog(search_text="", offset=0, object_type="", scout=False):
    data, level = _api_fallback(
        "GetPopularTitles", _catalog_query,
        lambda lv: _catalog_variables(search_text, offset, object_type, lv, scout=scout),
        _CATALOG_LEVELS)
    if level is None:
        return None, False
    audio_active = level[0]
    if not audio_active:
        log.log('[JustWatch] Audio-Filter "%s" nicht verfuegbar - Liste kann andere Tonspuren enthalten' % _AUDIO,
                log.LOGWARNING)
    return (data.get("popularTitles") or {}), audio_active


def _list_catalog(search_text="", offset=0, object_type=""):
    listing, audio_active = _fetch_catalog(search_text, offset, object_type)
    if listing is None:
        return []
    items = []
    for edge in listing.get("edges") or []:
        node = (edge or {}).get("node") or {}
        content = node.get("content") or {}
        offer = node.get("watchNowOffer") or {}

        show = node.get("__typename") == "Show" or node.get("objectType") == "SHOW"

        if audio_active and not show and not offer.get("id"):
            continue
        if not _audio_ok(offer):
            continue
        if not show and not offer.get("id"):
            continue

        title = content.get("title") or "Unbenannter Titel"
        year = content.get("originalReleaseYear")
        label = title
        poster = _poster(content.get("posterUrl"))
        backdrops = content.get("backdrops") or []
        fanart = _image_url((backdrops[0] or {}).get("backdropUrl") if backdrops else '',
                            's1920', 'backdrop.jpg') or poster
        fullpath = content.get("fullPath", "")

        item = {
            'title': label,
            'poster': poster,
            'fanart': fanart,
            'year': str(year) if year else '',
            'mpaa': _fsk(content.get("ageCertification")),
            'plot': content.get("shortDescription") or '',
            'mediatype': 'tvshow' if show else 'movie',
        }
        if show:
            item.update({
                'url': 'seasons:%s||%s' % (fullpath, title),
                'is_playable': False,
                'next_func': 'showEntries',
            })
        else:
            item.update({
                'url': 'offer:%s||%s||%s' % (offer.get("id", ""), fullpath, title),
                'is_playable': True,
                'next_func': 'get_hosters',
            })
        items.append(item)

    if (listing.get("pageInfo") or {}).get("hasNextPage"):
        items.append({
            'title': 'Weitere Ergebnisse …',
            'url': 'more:%d||%s||%s' % (offset + _PAGE_SIZE, object_type, search_text),
            'is_playable': False,
            'next_func': 'showEntries',
        })
    return items


def _fetch_seasons(fullpath):
    country, language, provider = _api_context()
    data, level = _api_fallback(
        "GetShowSeasons",
        lambda audio: _audio_query(SHOW_SEASONS_QUERY, audio),
        lambda audio: {"fullPath": fullpath, "country": country, "language": language, "provider": provider},
        _AUDIO_LEVELS)
    return ((data.get("urlV2") or {}).get("node") or {}), level


def _fetch_episodes(season_id):
    country, language, provider = _api_context()
    data, level = _api_fallback(
        "GetSeasonEpisodes",
        lambda audio: _audio_query(SEASON_EPISODES_QUERY, audio),
        lambda audio: {"seasonId": season_id, "country": country, "language": language,
                       "provider": provider, "limit": 100},
        _AUDIO_LEVELS)
    return (data.get("node") or {}), level


def _show_seasons(fullpath, show_title):
    node, level = _fetch_seasons(fullpath)
    show_content = node.get("content") or {}
    show_poster = _poster(show_content.get("posterUrl"))
    show_plot = show_content.get("shortDescription") or ''
    seasons = node.get("seasons") or []

    if level and any(s.get("offers") for s in seasons):
        seasons = [s for s in seasons if s.get("offers")]

    items = []
    for season in seasons:
        content = season.get("content") or {}
        number = content.get("seasonNumber")
        label = content.get("title") or ("Staffel %s" % number if number else "Staffel")
        poster = _poster(content.get("posterUrl")) or show_poster
        items.append({
            'title': label,
            'url': 'episodes:%s||%s' % (season.get("id", ""), show_title),
            'poster': poster,
            'fanart': show_poster or poster,
            'plot': show_plot,
            'season': number or 0,
            'mediatype': 'season',
            'is_playable': False,
            'next_func': 'showEntries',
        })
    return items


def _season_episodes(season_id, show_title):
    node, level = _fetch_episodes(season_id)
    season_poster = _poster((node.get("content") or {}).get("posterUrl"))
    episodes = node.get("episodes") or []
    items = []
    for episode in episodes:
        content = episode.get("content") or {}
        offers = episode.get("offers") or []
        offer = next((o for o in offers if o and o.get("id")), {})
        if not offer:
            continue
        number = content.get("episodeNumber")
        label = ("E%02d — " % number if isinstance(number, int) else "") + (content.get("title") or "Folge")
        items.append({
            'title': label,
            'url': 'offer:%s||||%s' % (offer.get("id", ""), label),
            'poster': season_poster,
            'fanart': season_poster,
            'season': content.get("seasonNumber") or 0,
            'episode': number or 0,
            'mediatype': 'episode',
            'plot': content.get("shortDescription") or "",
            'duration': content.get("runtime") or 0,
            'is_playable': True,
            'next_func': 'get_hosters',
        })
    return items


def search(query='', params=None, url=''):
    if not query:
        try:
            import xbmcgui
            query = xbmcgui.Dialog().input('JustWatch Suche', type=xbmcgui.INPUT_ALPHANUM)
        except Exception:
            pass
    if not query:
        return []
    return _list_catalog(search_text=query)


def _norm(text):
    return re.sub(r'[\W_]+', '', (text or '').lower())


def _to_int(value):
    try:
        return int(value)
    except Exception:
        return 0


def _first_offer_id(offers):
    return next((o.get("id") for o in (offers or []) if o and o.get("id")), '')


def _resolve_episode(fullpath, season, episode, show_title):
    node, _level = _fetch_seasons(fullpath)
    season_id = next((s.get("id") for s in (node.get("seasons") or [])
                      if _to_int((s.get("content") or {}).get("seasonNumber")) == season), '')
    if not season_id:
        return ''
    season_node, _level = _fetch_episodes(season_id)
    for ep in season_node.get("episodes") or []:
        if _to_int((ep.get("content") or {}).get("episodeNumber")) != episode:
            continue
        offer_id = _first_offer_id(ep.get("offers"))
        if offer_id:
            return 'offer:%s||||%s' % (offer_id, show_title)
    return ''


def _scout_resolve(title, year, season, episode):
    title_n = _norm(title)
    if not title_n:
        return ''
    season, episode, year_i = _to_int(season), _to_int(episode), _to_int(year)
    is_show = season > 0
    if is_show and episode <= 0:
        return ''

    listing, audio_active = _fetch_catalog(search_text=title, object_type='SHOW' if is_show else 'MOVIE', scout=True)
    if not listing:
        return ''

    candidates = []
    for edge in listing.get("edges") or []:
        node = (edge or {}).get("node") or {}
        content = node.get("content") or {}
        offer = node.get("watchNowOffer") or {}
        if not is_show:
            if audio_active and not offer.get("id"):
                continue
            if not _audio_ok(offer):
                continue
        name_n = _norm(content.get("title"))
        if not name_n:
            continue
        if name_n == title_n:
            score = 100
        elif title_n in name_n or name_n in title_n:
            score = 50
        else:
            continue
        found_year = _to_int(content.get("originalReleaseYear"))
        if year_i and found_year:
            diff = abs(found_year - year_i)
            if diff == 0:
                score += 20
            elif diff == 1:
                score += 10
            elif not is_show:
                continue 
        candidates.append((score, node, content, offer))

    candidates.sort(key=lambda c: c[0], reverse=True)
    for _score, node, content, offer in candidates[:3]:
        fullpath = content.get("fullPath", "")
        name = content.get("title") or title
        if is_show:
            resolved = _resolve_episode(fullpath, season, episode, name)
            if resolved:
                return resolved
        else:
            return 'offer:%s||%s||%s' % (offer.get("id", ""), fullpath, name)
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if not (url or '').startswith('offer:'):
        url = _scout_resolve(title, year, season, episode)
        if not url:
            log.log('[JustWatch] Scout: kein Treffer fuer title=%s year=%s S%s E%s'
                    % (title, year, season, episode), log.LOGWARNING)
            return []
    offer_id, fullpath = "", ""
    if url.startswith('offer:'):
        parts = url[6:].split('||', 2)
        offer_id = parts[0]
        if len(parts) > 1:
            fullpath = parts[1]

    last_error_code = ""

    if offer_id:
        country, language, _provider = _api_context()
        hdr_str = "Origin=%s&Referer=%s&User-Agent=%s" % (
            urllib.parse.quote("https://www.justwatch.com"),
            urllib.parse.quote("https://www.justwatch.com/"),
            urllib.parse.quote(_BROWSER_UA))
        _register_device()
        play_headers = _play_headers(country, language, fullpath)
        hls_fallback = None
        for variant in ({"drmType": "widevine", "deviceOs": "windows"},
                        {"drmType": "widevine", "deviceOs": "android"},
                        {"drmType": "playready", "deviceOs": "windows"},
                        {"deviceOs": "windows"}):
            play_input = {"offerId": offer_id}
            play_input.update(variant)
            res = {}
            for play_query in (PLAY_INFORMATION_QUERY, PLAY_INFORMATION_QUERY_BASE):
                raw = _api_raw("GetPlayInformation", play_query, {"input": play_input}, play_headers)
                if raw.get("data") and not raw.get("errors"):
                    res = raw["data"]
                    break
            info = (res.get("getPlayInformation") or {})

            err = info.get("errorCode")
            if err:
                last_error_code = str(err)
                log.log('[JustWatch] PlayInformation errorCode: %s' % err, log.LOGWARNING)
                err_up = str(err).upper()
                if 'AGE' in err_up or '18' in err_up or '16' in err_up or 'NIGHT' in err_up:
                    return []
                continue

            for s in info.get("streams") or []:
                drm = str(s.get("drmType") or "").lower()

                hls = s.get("manifestUrlSignedVariants") or ""
                configs = s.get("drmConfigs") or []
                wv = next((c.get("laURL") for c in configs
                           if str(c.get("drmType")).lower() == "widevine" and c.get("laURL")), "")
                hls_widevine = _hls_is_widevine(hls)
                log.log('[JustWatch] Stream %s/%s: drmType=%s enc=%s hls=%s dash=%s laURL=%s hlsWidevine=%s' % (
                    variant.get("deviceOs"), variant.get("drmType") or '-', drm or '-',
                    s.get("encodingType") or '-', bool(hls), bool(s.get("manifestUrlDash")), bool(wv),
                    hls_widevine), log.LOGWARNING)

                manifest = s.get("manifestUrlDash") or ""
                if manifest and wv:
                    drm_info = {
                        'drm_type': 'widevine',
                        'drm_license': wv,
                        'license_key': _license_key(wv, hdr_str),
                    }
                    return [('JustWatch DRM', manifest, drm_info)]

                if hls and (drm == "widevine" or hls_widevine):
                    if wv and hls_fallback is None:
                        hls_fallback = [('JustWatch DRM', hls, {
                            'drm_type': 'widevine',
                            'drm_license': wv,
                            'license_key': _license_key(wv, hdr_str),
                        })]
                    elif not wv:
                        log.log('[JustWatch] Widevine-HLS ohne Lizenz-URL', log.LOGWARNING)
                    continue

                if hls and drm in ("", "none", "null"):
                    return [('JustWatch', hls, True, 'HD', 'de')]

                su = s.get("url") or ""
                if su and drm in ("", "none", "null"):
                    return [('JustWatch', su, True, 'HD', 'de')]

                inline = s.get("manifestContent") or ""
                paths = [p.get("Path") for p in (s.get("secureStreamPaths") or []) if p.get("Path")]
                if inline and paths:
                    return [('JustWatch', paths[0], True, 'HD', 'de')]

        if hls_fallback:
            log.log('[JustWatch] Kein DASH-Stream verfuegbar, Widevine-HLS wird versucht', log.LOGWARNING)
            return hls_fallback

    if fullpath:
        country, language, provider = _api_context()
        data = _api_call("GetTitleOffers", TITLE_OFFERS_QUERY,
                         {"fullPath": fullpath, "country": country, "provider": provider})
        node = ((data.get("urlV2") or {}).get("node") or {})
        offers = [o for o in (node.get("offers") or []) if o and o.get("id")]
        for o in offers:
            direct = o.get("streamUrlExternalPlayer") or o.get("streamUrl") or ""
            if direct and direct.startswith("https://"):
                return [('JustWatch', direct, True, 'HD', 'de')]
            if o["id"] != offer_id:
                res = get_hosters(url='offer:%s||||' % o['id'])
                if res:
                    return res

    if last_error_code:
        raise Exception('Wiedergabe nicht möglich: %s' % last_error_code)

    return []
