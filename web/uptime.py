"""
UptimeRobot provider for the Sirens status page.

Друга модель моніторингу поруч із healthchecks.io. Той знає рівно те, що сервіс
сам про себе розповів: процес живий, значить зелено. Досяжність ззовні - DNS,
TLS, Cloudflare, nginx, рендер сторінки - у нього сліпа зона за побудовою.
UptimeRobot дивиться з протилежного боку, тому «Мапа» і «API» живляться саме
звідси.

Модуль віддає ту саму нормалізовану форму «зонда», що й healthchecks-гілка в
web/status.py, тож уся арифметика простоїв там спільна для обох провайдерів.

Контракт API (uptimerobot.com/api), від якого тут усе залежить:
  * POST /v2/getMonitors, ключ іде полем форми api_key, не заголовком.
  * Ключі тут помоніторні: такий ключ віддає рівно один свій монітор, тож
    зіставляти компонент із монітором не доводиться - помилитись нема в чому.
  * Відповідь завжди 200; невдачу видно лише по {"stat": "fail", "error": {...}}.
  * logs=1 додає масив logs; log_types=1-2 лишає в ньому падіння й підйоми.
  * logs[].datetime - unix-секунди, logs[].type: 1 = down, 2 = up.
  * status: 0 paused, 1 not checked yet, 2 up, 8 seems down, 9 down.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import (
    UPTIMEROBOT_SIRENS_API_API,
    UPTIMEROBOT_SIRENS_WEB_API,
)

log = logging.getLogger(__name__)

UR_API_BASE = "https://api.uptimerobot.com/v2"
REQUEST_TIMEOUT = 10  # seconds; UptimeRobot відповідає помітно повільніше за hc

LIVE_BY_STATUS = {
    0: "mnt",
    1: "nodata",
    2: "ok",
    8: "minor",
    9: "down",
}

LOG_TYPE_DOWN = 1
LOG_TYPE_UP = 2


def _api_key(key: str) -> str:
    """Помоніторний ключ під компонент. Читається щоразу - заради тестів."""
    return {
        "map": UPTIMEROBOT_SIRENS_WEB_API,
        "api": UPTIMEROBOT_SIRENS_API_API,
    }.get(key, "").strip()


def is_configured() -> bool:
    """Чи є сенс узагалі йти в UptimeRobot."""
    return bool(UPTIMEROBOT_SIRENS_WEB_API or UPTIMEROBOT_SIRENS_API_API)


def _blank_probe() -> Dict[str, Any]:
    """Зонд, який нічого не стверджує: доба стане nodata, доступність - прочерк."""
    return {
        "present": False,
        "live": None,
        "flips": [],
        "flips_ok": False,
        "history_start": None,
    }


def _parse_unix(value: Any, tz) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(value), tz)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _flips_from_logs(logs: Any, tz) -> List[Tuple[datetime, int]]:
    """Події монітора як перемикання стану, за зростанням часу.

    Форма збігається з флипами healthchecks.io навмисно: далі їх розбирає той
    самий код, що рахує відрізки простою.
    """
    flips: List[Tuple[datetime, int]] = []
    for entry in logs if isinstance(logs, list) else []:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        if entry_type not in (LOG_TYPE_UP, LOG_TYPE_DOWN):
            continue
        moment = _parse_unix(entry.get("datetime"), tz)
        if moment is None:
            continue
        flips.append((moment, 1 if entry_type == LOG_TYPE_UP else 0))

    flips.sort(key=lambda flip: flip[0])
    return flips


def _fetch_monitor(api_key: str) -> Optional[Dict[str, Any]]:
    """Єдиний монітор, який віддає цей ключ, разом із його логами.

    Часові межі логів не ставимо навмисно - рівно з тієї ж причини, з якої їх
    немає в healthchecks-гілці: без події, що сталася ДО початку вікна,
    неможливо дізнатись, у якому стані сервіс це вікно зустрів.
    """
    resp = requests.post(
        f"{UR_API_BASE}/getMonitors",
        data={
            "api_key": api_key,
            "format": "json",
            "logs": 1,
            "log_types": f"{LOG_TYPE_DOWN}-{LOG_TYPE_UP}",
            "response_times": 0,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    if not isinstance(payload, dict) or payload.get("stat") != "ok":
        # UptimeRobot відповідає 200 і на помилку, тож raise_for_status її не
        # ловить: невдачу видно лише по цьому полю.
        error = payload.get("error") if isinstance(payload, dict) else payload
        log.warning("UptimeRobot refused the request: %r", error)
        return None

    monitors = payload.get("monitors")
    if not isinstance(monitors, list) or not monitors:
        log.warning("UptimeRobot returned no monitor for the configured key")
        return None

    return monitors[0] if isinstance(monitors[0], dict) else None


def fetch_probes(keys: List[str], tz) -> Dict[str, Dict[str, Any]]:
    """Зонди для компонентів, що живляться з UptimeRobot.

    Ненастроєний ключ - це порожній зонд: компонент чесно каже, що моніторингу
    немає. А от ключ, який заданий і не спрацював, кидає далі: обхід має
    зірватись цілком, щоб refresh_status_cache нічого не переписав. Інакше
    хвилинний збій API затер би справжню історію суцільним "немає даних", і
    сторінка забула б усе, що знала.
    """
    probes: Dict[str, Dict[str, Any]] = {}

    for key in keys:
        api_key = _api_key(key)
        if not api_key:
            log.warning("No UptimeRobot key configured for the %r component", key)
            probes[key] = _blank_probe()
            continue

        monitor = _fetch_monitor(api_key)
        if monitor is None:
            probes[key] = _blank_probe()
            continue

        probes[key] = {
            "present": True,
            "live": LIVE_BY_STATUS.get(monitor.get("status"), "nodata"),
            "flips": _flips_from_logs(monitor.get("logs"), tz),
            "flips_ok": True,
            # Монітор не міг падати до того, як його створили - це і є найраніша
            # мить, про яку тут узагалі є що сказати.
            "history_start": _parse_unix(monitor.get("create_datetime"), tz),
        }

    return probes
