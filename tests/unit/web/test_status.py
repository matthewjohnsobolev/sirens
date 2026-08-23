"""Тести сторінки стану.

Фікстури тут навмисно повторюють РЕАЛЬНУ форму відповідей healthchecks.io:
read-only ключ віддає unique_key і не віддає uuid/ping_url, поля flips_url не
існує взагалі, а /flips/ повертає голий масив від нових до старих. Попередня
версія цих тестів вигадувала зручніший API - і саме тому сторінка місяць
показувала «Усі системи працюють» незалежно від того, що коїлось насправді.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from web import status as web_status
from web.status import (
    COMPONENTS_SPEC,
    KYIV_TZ,
    WINDOW_DAYS,
    _build_component,
    _collect_status,
    _find_matching_check,
    _plural_days,
    _resolve_history_start,
    format_day_title,
    get_status_data,
    refresh_status_cache,
    summarize_days,
)


# --- допоміжне -------------------------------------------------------------

def _check(slug, name, status="up", n_pings=100):
    """Чек у тій формі, в якій його віддає read-only ключ."""
    return {
        "name": name,
        "slug": slug,
        "tags": "prod",
        "status": status,
        "n_pings": n_pings,
        "started": False,
        "last_ping": datetime.now(KYIV_TZ).isoformat(),
        "unique_key": f"key-{slug}",
    }


def _flip(moment, up):
    return {"timestamp": moment.isoformat(), "up": up}


def _spec(key):
    return next(spec for spec in COMPONENTS_SPEC if spec["key"] == key)


def _probe(flips=(), *, present=True, live="ok", flips_ok=True, history_start=None):
    """Зонд у тій формі, до якої обидва провайдери зводять свої відповіді."""
    return {
        "present": present,
        "live": live,
        "flips": list(flips),
        "flips_ok": flips_ok,
        "history_start": history_start,
    }


def _responder(checks, flips_by_key, flips_status=200):
    """Підмінник requests.get, що розрізняє список чеків і флипи."""
    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        if '/flips/' in url:
            resp.status_code = flips_status
            if flips_status != 200:
                resp.raise_for_status.side_effect = RuntimeError('boom')
                return resp
            key = url.rstrip('/').split('/')[-2]
            # Реальний API віддає голий масив від нових до старих.
            resp.json.return_value = list(reversed(flips_by_key.get(key, [])))
        else:
            resp.status_code = 200
            resp.json.return_value = {"checks": checks}
        return resp
    return fake_get


@pytest.fixture(autouse=True)
def _quiet_redis(monkeypatch):
    """Жоден тест тут не має торкатись живого Redis."""
    fake = MagicMock()
    fake.get.return_value = None
    fake.hgetall.return_value = {}
    monkeypatch.setattr('web.status.redis_client', fake)
    return fake


@pytest.fixture(autouse=True)
def _no_start_date(monkeypatch):
    monkeypatch.setattr('web.status.STATUS_START_DATE', '')
    monkeypatch.setattr('web.status.HEALTHCHECKS_SLUG_ALERTS_SOURCE', '')
    monkeypatch.setattr('web.status.HEALTHCHECKS_SLUG_ALERTS_BROADCAST', '')


def _days_ago(component, ago):
    """Стан доби, що була `ago` днів тому; days відсортовані від старих до нових."""
    return component['days'][WINDOW_DAYS - 1 - ago]['state']


# --- маршрути --------------------------------------------------------------

def test_status_route(client):
    response = client.get('/status')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Стан сервісу' in html

    assets = re.findall(r'(?:href|src)="(/static/(?:css|js)/status\.[^"]+)"', html)
    assert assets, "Не знайдено status.css або status.js у розмітці"
    for asset in assets:
        assert '?v=' in asset, f"Статичний ассет {asset} без версійного хешу"


def test_status_route_renders_bars_without_javascript(client):
    """Смуги приходять з сервера: сторінка стану потрібна саме тоді, коли JS не працює."""
    html = client.get('/status').get_data(as_text=True)
    assert html.count('class="bar"') == WINDOW_DAYS * len(COMPONENTS_SPEC)


def test_status_route_says_it_does_not_know(client):
    """Без даних сторінка мовчить про доступність, а не рапортує 100 %."""
    html = client.get('/status').get_data(as_text=True)
    assert 'Немає даних про стан' in html
    assert 'Усі системи працюють' not in html
    assert '100,00' not in html


def test_api_status_route(client):
    response = client.get('/api/status')
    assert response.status_code == 200
    data = response.json
    assert 'components' in data
    assert 'headline' in data
    assert 'overall_uptime' in data
    assert len(data['components']) == 4
    keys = [c['key'] for c in data['components']]
    assert keys == ['map', 'api', 'alerts', 'tg']


def test_api_status_carries_no_markup():
    """state_sub із &nbsp; колись їхав просто в JSON; розмітка лишається в шаблоні."""
    from web.server import create_app

    client = create_app(init_db=False, start_healthcheck=False).test_client()
    payload = json.dumps(client.get('/api/status').json, ensure_ascii=False)
    assert '&nbsp;' not in payload
    assert '&' not in payload


# --- зіставлення чеків -----------------------------------------------------

def test_matching_check():
    checks = [
        _check("alerts", "Sirens Alerts Worker"),
        _check("tg", "Sirens Broadcasts"),
    ]
    assert _find_matching_check(_spec('alerts'), checks) == checks[0]
    assert _find_matching_check(_spec('tg'), checks) == checks[1]


def test_matching_check_claims_each_check_once():
    """Один чек не може стояти за двома компонентами одночасно."""
    checks = [_check("alerts", "Sirens Alerts Worker")]
    claimed = set()

    first = _find_matching_check(_spec('alerts'), checks, claimed)
    second = _find_matching_check(_spec('tg'), checks, claimed)

    assert first == checks[0]
    assert second is None


def test_slug_override_is_not_second_guessed(monkeypatch, caplog):
    """Явно заданий slug, який нікуди не веде, лишає компонент порожнім."""
    monkeypatch.setattr('web.status.HEALTHCHECKS_SLUG_ALERTS_SOURCE', 'no-such-slug')
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with caplog.at_level('WARNING'):
        assert _find_matching_check(_spec('alerts'), checks) is None
    assert 'no-such-slug' in caplog.text


def test_slug_override_wins_over_the_exact_match(monkeypatch):
    monkeypatch.setattr('web.status.HEALTHCHECKS_SLUG_ALERTS_SOURCE', 'ingest-v2')
    checks = [
        _check("alerts", "Sirens Alerts Worker"),
        _check("ingest-v2", "Sirens Ingest"),
    ]
    assert _find_matching_check(_spec('alerts'), checks) == checks[1]


def test_a_lookalike_check_is_never_adopted(caplog):
    """Ключових слів більше немає: чек зі словом "alerts" у назві - не наш чек.

    Саме через підрядковий пошук будь-який сторонній чек, у назві якого
    трапилось потрібне слово, мовчки ставав компонентом і показував під ним
    свою історію.
    """
    checks = [
        _check("backup-alerts", "Backup alerts mailer"),
        _check("third-party-api", "Some other API"),
    ]

    with caplog.at_level('WARNING'):
        assert _find_matching_check(_spec('alerts'), checks) is None
        assert _find_matching_check(_spec('tg'), checks) is None

    assert 'is configured' in caplog.text


# --- відновлення історії ---------------------------------------------------

def test_multi_day_outage_paints_every_affected_day():
    """Аварія на три доби мала фарбувати лише день падіння - тепер усі три."""
    now = datetime.now(KYIV_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    flips = [
        (now - timedelta(days=5), 0),
        (now - timedelta(days=2), 1),
    ]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )

    assert _days_ago(component, 5) == 'down'
    assert _days_ago(component, 4) == 'down'
    assert _days_ago(component, 3) == 'down'
    assert _days_ago(component, 2) == 'down'
    assert _days_ago(component, 1) == 'ok'


def test_outage_started_before_the_window_is_visible():
    """Падіння, що почалось до вікна, лишало його початок зеленим."""
    now = datetime.now(KYIV_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    flips = [
        (now - timedelta(days=WINDOW_DAYS + 10), 0),
        (now - timedelta(days=WINDOW_DAYS - 3), 1),
    ]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )

    assert _days_ago(component, WINDOW_DAYS - 1) == 'down'
    assert _days_ago(component, WINDOW_DAYS - 2) == 'down'


def test_outage_across_midnight_is_split_between_days():
    """Аварія через північ рахується в обидві доби, а не тільки в першу."""
    now = datetime.now(KYIV_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    midnight = now.replace(hour=0, minute=0)
    flips = [
        (midnight - timedelta(minutes=10), 0),  # учора о 23:50
        (midnight + timedelta(minutes=10), 1),  # сьогодні о 00:10
    ]

    component, _tracked, down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )

    # Двадцять хвилин простою, порівну по обидва боки півночі.
    assert down == pytest.approx(20 * 60, abs=1)
    assert _days_ago(component, 1) == 'deg'
    assert _days_ago(component, 0) == 'deg'


def test_short_blip_is_degraded_not_down():
    now = datetime.now(KYIV_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    flips = [
        (now - timedelta(days=2, minutes=10), 0),
        (now - timedelta(days=2), 1),
    ]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )
    assert _days_ago(component, 2) == 'deg'


def test_uptime_counts_seconds_not_whole_days():
    """Шестигодинна аварія - це шість годин, а не викреслена доба."""
    now = datetime.now(KYIV_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=10)
    flips = [
        (start, 1),
        (now - timedelta(days=3, hours=6), 0),
        (now - timedelta(days=3), 1),
    ]

    component, tracked, down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )

    assert down == pytest.approx(6 * 3600, abs=1)
    # Старий розрахунок штрафував цілу добу і давав би приблизно 90 %.
    assert component['uptime'] > 97.0


def test_live_down_status_reaches_today_and_headline():
    """Регрес на days.get(0) по словнику з рядковими ключами."""
    now = datetime.now(KYIV_TZ)
    checks = [_check("alerts", "Sirens Alerts Worker", status="down")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    assert data['headline'] == 'Частина систем недоступна'
    comp = next(c for c in data['components'] if c['key'] == 'alerts')
    assert comp['days'][-1]['state'] == 'down'


def test_grace_status_shows_as_degraded():
    checks = [_check("alerts", "Sirens Alerts Worker", status="grace")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    assert data['headline'] == 'Спостерігаються збої в роботі'


def test_paused_check_reads_as_maintenance():
    checks = [_check("alerts", "Sirens Alerts Worker", status="paused")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    assert data['headline'] == 'Планові технічні роботи'


# --- чесність замість вигаданих ста відсотків ------------------------------

def test_failed_flip_fetch_is_nodata_not_ok():
    """Таймаут при завантаженні флипів не має виглядати як «сбоїв не було»."""
    now = datetime.now(KYIV_TZ)

    component, tracked, _down = _build_component(
        _spec('alerts'), _probe([], flips_ok=False), now, {}
    )

    assert tracked == 0
    assert component['uptime'] is None
    assert {day['state'] for day in component['days']} <= {'nodata', 'ok'}
    assert _days_ago(component, 5) == 'nodata'


def test_flips_http_failure_leaves_component_without_uptime():
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {}, flips_status=500)):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    map_comp = next(c for c in data['components'] if c['key'] == 'map')
    assert map_comp['uptime'] is None
    assert map_comp['tracked_days'] == 0


def test_unmatched_component_is_marked_unmonitored():
    """tg та api не мають свого чека - і не вдають, ніби мають 100 %."""
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    tg_comp = next(c for c in data['components'] if c['key'] == 'tg')
    assert tg_comp['monitored'] is False
    assert tg_comp['uptime'] is None
    assert all(day['state'] == 'nodata' for day in tg_comp['days'])


def test_unmatched_component_stays_nodata_even_with_start_date(monkeypatch):
    """Задана дата старту не має вигадувати історію для компонента без чека."""
    today = datetime.now(KYIV_TZ).date()
    monkeypatch.setattr(
        'web.status.STATUS_START_DATE', (today - timedelta(days=30)).isoformat()
    )
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    api_comp = next(c for c in data['components'] if c['key'] == 'api')
    assert api_comp['uptime'] is None
    assert all(day['state'] == 'nodata' for day in api_comp['days'])


def test_unreachable_api_falls_back_to_last_good(_quiet_redis):
    """Впав healthchecks.io - показуємо старий знімок із поміткою, а не «все добре»."""
    snapshot = {'headline': 'Усі системи працюють', 'updated_at': '22 серпня, 10:00'}
    _quiet_redis.get.side_effect = lambda key: (
        json.dumps(snapshot) if key == web_status.LAST_GOOD_KEY else None
    )

    data = get_status_data()
    assert data['stale'] is True
    assert data['headline'] == 'Усі системи працюють'


def test_empty_cache_reports_unknown(_quiet_redis):
    _quiet_redis.get.return_value = None

    data = get_status_data()
    assert data['headline'] == 'Немає даних про стан'
    assert data['overall_uptime'] is None
    assert data['unknown'] is True
    assert all(c['uptime'] is None for c in data['components'])


def test_unreachable_redis_reports_unknown(_quiet_redis):
    _quiet_redis.get.side_effect = ConnectionError('redis down')

    data = get_status_data()
    assert data['headline'] == 'Немає даних про стан'


def test_unknown_components_do_not_share_one_days_list():
    """Кожен компонент має власний список діб, а не спільний об'єкт."""
    data = web_status._unknown_status_data()
    first, second = data['components'][0], data['components'][1]
    assert first['days'] is not second['days']


def test_refresh_writes_both_cache_keys(_quiet_redis):
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            assert refresh_status_cache() is not None

    written = {call.args[0] for call in _quiet_redis.set.call_args_list}
    assert written == {web_status.CACHE_KEY, web_status.LAST_GOOD_KEY}


def test_failed_refresh_keeps_the_old_snapshot(_quiet_redis):
    with patch('requests.get', side_effect=RuntimeError('healthchecks down')):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            assert refresh_status_cache() is None

    _quiet_redis.set.assert_not_called()


def test_get_status_data_never_calls_the_network(_quiet_redis):
    """Сторонній API не має стояти на шляху запиту читача."""
    _quiet_redis.get.return_value = None

    with patch('requests.get', side_effect=AssertionError('network in request path')):
        assert get_status_data()['headline'] == 'Немає даних про стан'


# --- два провайдери в одному знімку ----------------------------------------

def _ur_responder(monitor):
    def fake_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.json.return_value = {"stat": "ok", "monitors": [monitor]}
        return resp
    return fake_post


def _ur_monitor(status=2, days_old=40):
    created = datetime.now(KYIV_TZ) - timedelta(days=days_old)
    return {
        "id": 777001,
        "friendly_name": "sirens-web",
        "status": status,
        "create_datetime": int(created.timestamp()),
        "logs": [],
    }


def test_a_provider_without_components_is_not_queried():
    """Порожній список - привід не ходити в мережу взагалі."""
    with patch('requests.get', side_effect=AssertionError('network without components')):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            assert web_status._healthchecks_probes([]) == {}


def test_both_providers_land_in_one_snapshot(monkeypatch):
    """Кожен компонент бере історію у свого провайдера й не заглядає до чужого."""
    monkeypatch.setattr('web.uptime.UPTIMEROBOT_SIRENS_WEB_API', 'ur-web-key')
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('requests.post', side_effect=_ur_responder(_ur_monitor())):
            with patch('web.status.HEALTHCHECKS_API', 'test-key'):
                data = _collect_status()

    by_key = {c['key']: c for c in data['components']}
    assert by_key['map']['monitored'] is True       # UptimeRobot
    assert by_key['alerts']['monitored'] is True    # healthchecks.io
    # А ці двоє не налаштовані в жодного - і чесно про це кажуть.
    assert by_key['api']['monitored'] is False
    assert by_key['tg']['monitored'] is False


def test_one_provider_alone_still_fills_its_own_components(monkeypatch):
    """Ненастроєний healthchecks не заважає UptimeRobot показати своє."""
    monkeypatch.setattr('web.uptime.UPTIMEROBOT_SIRENS_WEB_API', 'ur-web-key')

    with patch('requests.post', side_effect=_ur_responder(_ur_monitor())):
        with patch('web.status.HEALTHCHECKS_API', ''):
            data = _collect_status()

    by_key = {c['key']: c for c in data['components']}
    assert by_key['map']['monitored'] is True
    assert by_key['alerts']['monitored'] is False
    assert all(day['state'] == 'nodata' for day in by_key['alerts']['days'])


def test_a_broken_provider_never_overwrites_the_history(_quiet_redis, monkeypatch):
    """Збій провайдера лишає старий знімок: інакше година недоступності API
    затерла б справжню 90-денну історію суцільним «немає даних»."""
    monkeypatch.setattr('web.uptime.UPTIMEROBOT_SIRENS_WEB_API', 'ur-web-key')
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('requests.post', side_effect=RuntimeError('uptimerobot down')):
            with patch('web.status.HEALTHCHECKS_API', 'test-key'):
                assert refresh_status_cache() is None

    _quiet_redis.set.assert_not_called()


# --- дата початку історії --------------------------------------------------

def test_start_date_prefers_explicit_config(monkeypatch):
    monkeypatch.setattr('web.status.STATUS_START_DATE', '2026-08-01')
    now = datetime.now(KYIV_TZ)

    start = _resolve_history_start('alerts', _probe(), {}, now)
    assert start.date().isoformat() == '2026-08-01'


def test_start_date_comes_from_earliest_flip():
    """Історія починається миттю флипа, а не північчю того дня."""
    now = datetime.now(KYIV_TZ)
    flips = [(now - timedelta(days=20), 1), (now - timedelta(days=5), 0)]

    start = _resolve_history_start('alerts', _probe(flips), {}, now)
    assert start == now - timedelta(days=20)


def test_start_date_falls_back_to_remembered_first_seen():
    """last_ping завжди «щойно», тож історію треба пам'ятати самим."""
    now = datetime.now(KYIV_TZ)
    remembered = (now.date() - timedelta(days=40)).isoformat()

    start = _resolve_history_start('alerts', _probe(), {'alerts': remembered}, now)
    assert start.date().isoformat() == remembered


def test_start_date_does_not_rewind_to_midnight_when_flips_exist_today():
    """Флип усередині сьогоднішнього дня не має відкочуватись на північ через first_seen."""
    now = datetime.now(KYIV_TZ).replace(hour=14, minute=0, second=0, microsecond=0)
    flip_time = now.replace(hour=12, minute=7)
    flips = [(flip_time, 1)]

    start = _resolve_history_start('alerts', _probe(flips), {'alerts': now.date().isoformat()}, now)
    assert start == flip_time


def test_start_date_is_none_without_a_check():
    now = datetime.now(KYIV_TZ)
    assert _resolve_history_start('tg', _probe(present=False), {}, now) is None


def test_start_date_takes_the_provider_hint():
    """UptimeRobot знає, коли монітор створили; раніше за це знати нічого."""
    now = datetime.now(KYIV_TZ)
    created = now - timedelta(days=30)

    start = _resolve_history_start('map', _probe(history_start=created), {}, now)
    assert start == created


def test_last_ping_does_not_collapse_history():
    """Регрес: історія колись схлопувалась в одну добу через last_ping."""
    now = datetime.now(KYIV_TZ)
    flips = [(now - timedelta(days=45), 1)]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips), now, {}
    )
    assert component['tracked_days'] == 46


# --- підписи ---------------------------------------------------------------

@pytest.mark.parametrize("count,word", [
    (1, 'день'), (2, 'дні'), (3, 'дні'), (4, 'дні'),
    (5, 'днів'), (11, 'днів'), (14, 'днів'), (21, 'день'),
    (22, 'дні'), (90, 'днів'), (0, 'днів'),
])
def test_plural_days(count, word):
    assert _plural_days(count) == word


def test_format_day_title():
    assert format_day_title('2026-05-25', 'ok') == '25 травня — без збоїв'
    assert format_day_title('2026-05-25', 'down') == '25 травня — недоступно'
    assert format_day_title('not-a-date', 'nodata') == 'немає даних'


def test_summarize_days_counts_states():
    days = [{'date': '2026-05-25', 'state': 'ok'}] * 88 + [{'date': '2026-05-26', 'state': 'down'}] * 2
    summary = summarize_days(days)
    assert '88 днів без збоїв' in summary
    assert '2 дні недоступно' in summary


def test_summarize_empty_days():
    assert summarize_days([]) == 'немає даних'


# --- розбір відповідей API -------------------------------------------------

def test_parse_ts_rejects_junk():
    assert web_status._parse_ts(None) is None
    assert web_status._parse_ts(12345) is None
    assert web_status._parse_ts('not-a-timestamp') is None


def test_parse_ts_treats_a_naive_stamp_as_utc():
    """Мітка без зсуву не має тлумачитись як час машини, де крутиться воркер."""
    assert web_status._parse_ts('2026-08-20T09:00:00') == datetime(
        2026, 8, 20, 9, 0, tzinfo=timezone.utc
    )
    assert web_status._parse_ts('2026-08-20T09:00:00Z') == datetime(
        2026, 8, 20, 9, 0, tzinfo=timezone.utc
    )


def test_fetch_flips_without_an_identifier_is_a_failure():
    """Без unique_key і uuid шлях до флипів не побудувати - і це не «сбоїв не було»."""
    assert web_status._fetch_flips({"name": "Sirens Web App"}, {}) == ([], False)


def test_fetch_flips_sorts_oldest_first():
    """API віддає від нових до старих, а весь розрахунок іде вперед у часі."""
    now = datetime.now(KYIV_TZ)
    resp = MagicMock()
    resp.json.return_value = [_flip(now, 1), _flip(now - timedelta(hours=2), 0)]

    with patch('requests.get', return_value=resp):
        flips, ok = web_status._fetch_flips(_check("alerts", "W"), {})

    assert ok is True
    assert [up for _ts, up in flips] == [0, 1]


def test_fetch_flips_accepts_a_wrapped_payload():
    """Документація показує голий масив; обгортку теж переживаємо."""
    resp = MagicMock()
    resp.json.return_value = {"flips": [_flip(datetime.now(KYIV_TZ), 1)]}

    with patch('requests.get', return_value=resp):
        flips, ok = web_status._fetch_flips(_check("alerts", "W"), {})

    assert ok is True
    assert [up for _ts, up in flips] == [1]


def test_fetch_flips_skips_unusable_entries():
    now = datetime.now(KYIV_TZ)
    resp = MagicMock()
    resp.json.return_value = ['nonsense', {"up": 1}, {"timestamp": 'junk', "up": 0}, _flip(now, 0)]

    with patch('requests.get', return_value=resp):
        flips, ok = web_status._fetch_flips(_check("alerts", "W"), {})

    assert ok is True
    assert [up for _ts, up in flips] == [0]


def test_fetch_flips_of_an_unknown_shape_is_empty():
    resp = MagicMock()
    resp.json.return_value = 42

    with patch('requests.get', return_value=resp):
        assert web_status._fetch_flips(_check("alerts", "W"), {}) == ([], True)


# --- відновлення стану -----------------------------------------------------

def test_never_pinged_check_reads_as_nodata():
    assert web_status._live_state(_check("alerts", "W", n_pings=0)) == 'nodata'
    assert web_status._live_state(_check("alerts", "W", status='new')) == 'nodata'
    assert web_status._live_state(None) is None


def test_state_before_the_earliest_flip_is_the_opposite_of_it():
    now = datetime.now(KYIV_TZ)
    yesterday = now - timedelta(days=1)

    # Найперший флип - «піднявся», отже до нього сервіс лежав.
    assert web_status._state_at([(now, 1)], yesterday, True) is False
    # Найперший флип - «впав», отже до нього все працювало.
    assert web_status._state_at([(now, 0)], yesterday, False) is True
    # Флипів немає взагалі - лишається те, що передали.
    assert web_status._state_at([], now, True) is True


def test_flips_in_the_future_are_ignored():
    now = datetime.now(KYIV_TZ)
    flips = [(now - timedelta(hours=2), 0), (now + timedelta(hours=1), 1)]

    intervals = web_status._down_intervals(flips, now - timedelta(days=1), now, True)
    assert intervals == [(now - timedelta(hours=2), now)]


def test_today_keeps_the_worse_of_history_and_live_status():
    """Вранці лежало, зараз працює - доба лишається червоною."""
    now = datetime.now(KYIV_TZ).replace(hour=23, minute=0, second=0, microsecond=0)
    flips = [
        (now - timedelta(days=3), 1),
        (now.replace(hour=2), 0),
        (now.replace(hour=6), 1),
    ]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips, live='ok'), now, {}
    )
    assert _days_ago(component, 0) == 'down'


def test_live_outage_outranks_a_calm_history():
    """Флип пишеться лише після grace, тож поточне падіння видно тільки в статусі."""
    now = datetime.now(KYIV_TZ).replace(hour=23, minute=0, second=0, microsecond=0)
    flips = [(now - timedelta(days=3), 1)]

    component, _tracked, _down = _build_component(
        _spec('alerts'), _probe(flips, live='down'), now, {}
    )
    assert _days_ago(component, 0) == 'down'


def test_headline_is_unknown_when_every_check_is_silent():
    checks = [_check("alerts", "Sirens Alerts Worker", n_pings=0)]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            data = _collect_status()

    assert data['headline'] == 'Немає даних про стан'


# --- збої довкола -----------------------------------------------------------

def test_redis_failures_do_not_break_first_seen(_quiet_redis, caplog):
    _quiet_redis.hgetall.side_effect = ConnectionError('redis down')
    _quiet_redis.hsetnx.side_effect = ConnectionError('redis down')

    with caplog.at_level('WARNING'):
        assert web_status._load_first_seen() == {}
        web_status._remember_first_seen('map', datetime.now(KYIV_TZ).date())

    assert 'Redis unreachable' in caplog.text


def test_malformed_start_date_config_is_ignored(monkeypatch, caplog):
    monkeypatch.setattr('web.status.STATUS_START_DATE', '20 серпня')
    now = datetime.now(KYIV_TZ)

    with caplog.at_level('WARNING'):
        start = _resolve_history_start('alerts', _probe(), {}, now)

    assert 'Invalid STATUS_START_DATE' in caplog.text
    assert start == now


def test_malformed_remembered_date_is_ignored(caplog):
    now = datetime.now(KYIV_TZ)

    with caplog.at_level('WARNING'):
        start = _resolve_history_start('alerts', _probe(), {'alerts': 'вчора'}, now)

    assert 'malformed' in caplog.text
    assert start == now


def test_fetch_without_an_api_key_returns_nothing(caplog):
    with patch('web.status.HEALTHCHECKS_API', ''):
        with caplog.at_level('INFO'):
            assert _collect_status() is None

    assert 'No monitoring provider is configured' in caplog.text


def test_refresh_without_an_api_key_writes_nothing(_quiet_redis):
    with patch('web.status.HEALTHCHECKS_API', ''):
        assert refresh_status_cache() is None

    _quiet_redis.set.assert_not_called()


def test_refresh_survives_unreachable_redis(_quiet_redis, caplog):
    _quiet_redis.set.side_effect = ConnectionError('redis down')
    checks = [_check("alerts", "Sirens Alerts Worker")]

    with patch('requests.get', side_effect=_responder(checks, {})):
        with patch('web.status.HEALTHCHECKS_API', 'test-key'):
            with caplog.at_level('WARNING'):
                assert refresh_status_cache() is not None

    assert 'Redis unreachable' in caplog.text


def test_corrupt_cache_entry_is_skipped(_quiet_redis, caplog):
    _quiet_redis.get.side_effect = lambda key: (
        '{not json' if key == web_status.CACHE_KEY else None
    )

    with caplog.at_level('WARNING'):
        data = get_status_data()

    assert data['headline'] == 'Немає даних про стан'
    assert 'not valid JSON' in caplog.text
