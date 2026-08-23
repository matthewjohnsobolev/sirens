"""
Status page data aggregator for Sirens.

Збирає 90-денну історію по добах із двох провайдерів і складає її в Redis.
healthchecks.io дивиться зсередини (чи сервіс сам про себе доповів), UptimeRobot
- ззовні (чи сайт відкривається у відвідувача); кожен сліпий там, де бачить
другий. Обидва зводяться до спільної форми «зонда», тож арифметика простоїв тут
одна на всіх. Сторінка стану сама нікуди не ходить: кеш наповнює фоновий потік
у web/server.py, тож сторонній API ніколи не стоїть на шляху запиту читача.

Головне правило цього модуля: незнання не можна показувати як «все добре».
Якщо моніторинг не знайшовся, історія не завантажилась або API недоступний -
доба стає "nodata", а доступність - None, і сторінка друкує прочерк замість
відсотка.

Форма зонда, яку віддає кожен провайдер:
  * present      - чи знайшовся моніторинг під цей компонент
  * live         - поточний стан: ok | deg | down | mnt | nodata
  * flips        - перемикання (час, up) за зростанням часу
  * flips_ok     - чи вдався запит; порожньо від таймауту ≠ порожньо від спокою
  * history_start- найраніша мить, про яку провайдер може щось сказати

Контракт UptimeRobot описаний у web/uptime.py.

Контракт API (healthchecks.io/docs/api), від якого тут усе залежить:
  * GET /api/v3/checks/ віддає {"checks": [...]}; поля 'flips_url' там немає.
  * Read-only ключ прибирає з відповіді uuid, ping_url, update_url, pause_url,
    resume_url, channels і додає натомість unique_key. Саме unique_key підходить
    у шлях /api/v3/checks/<id>/flips/.
  * Поля 'created' у чека немає, а 'started' - булеве. Дату початку історії
    доводиться брати з флипів або запам'ятовувати самим.
  * /flips/ віддає ГОЛИЙ масив [{"timestamp": ..., "up": 0|1}, ...] від нових
    до старих.
"""

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=3))

import requests

from config import (
    HEALTHCHECKS_API,
    HEALTHCHECKS_SLUG_ALERTS_SOURCE,
    HEALTHCHECKS_SLUG_ALERTS_BROADCAST,
    STATUS_START_DATE,
)
from web import uptime
from web.db import redis_client

log = logging.getLogger(__name__)

CACHE_KEY = "service:healthchecks_status:90d"
# Останній вдалий знімок переживає і промах кешу, і падіння healthchecks.io:
# краще показати дані півгодинної давнини з поміткою, ніж вигадані сто відсотків.
LAST_GOOD_KEY = "service:healthchecks_status:last_good"
# Коли чек уперше потрапив нам на очі. Флипи в healthchecks.io не вічні, а іншого
# джерела дати старту в API немає, тож ведемо її самі.
FIRST_SEEN_KEY = "service:healthchecks_status:first_seen"

# Трохи більше за STATUS_REFRESH_INTERVAL у web/server.py: рівна хвилина означала
# б, що ключ протухає рівно тоді, коли оновлювач має його переписати, і сторінка
# регулярно провалювалась би на LAST_GOOD з поміткою «дані станом на» - для
# цілком свіжих даних.
CACHE_TTL = 90  # seconds
LAST_GOOD_TTL = 86400  # seconds
REQUEST_TIMEOUT = 5  # seconds

WINDOW_DAYS = 90
# Коротка яма - це "збої", а не "недоступно": хвилинний промах пінга не варто
# малювати тим самим кольором, що й півдня тиші.
DEGRADED_THRESHOLD = 1200  # seconds

HC_API_BASE = "https://healthchecks.io/api/v3"

UK_MONTHS = [
    "",
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
]

DAY_WORDS = {
    "ok": "без збоїв",
    "mnt": "планові роботи",
    "deg": "збої",
    "down": "недоступно",
    "nodata": "немає даних",
}

# Наскільки погана доба. Потрібно там, де за неї сперечаються два джерела:
# порахована з флипів історія і поточний статус чека.
SEVERITY = {"ok": 0, "deg": 1, "down": 2}

HEALTHCHECKS = "healthchecks"
UPTIMEROBOT = "uptimerobot"

# Кожен компонент стверджує щось своє, і жоден не дублює сусіда.
#
# Мапа й API дивляться ззовні (UptimeRobot): чи відкривається сайт у відвідувача
# й чи віддає ендпойнт справжній JSON. Внутрішній пінг цього не знає - процес
# може бути живий, поки хост недосяжний.
#
# Потік тривог і Сповіщення - два кінці ланцюга зсередини (healthchecks.io): чи
# пости з джерела доходять до нас і чи наші бродкасти виходять у канали мережі.
# Ламаються вони незалежно, тож і чеки різні.
#
# Порядок важливий: компоненти розбирають чеки згори вниз, і забраний чек більше
# нікому не дістанеться.
COMPONENTS_SPEC = [
    {"key": "map", "name": "Мапа", "source": UPTIMEROBOT},
    {"key": "api", "name": "API", "source": UPTIMEROBOT},
    {"key": "alerts", "name": "Потік тривог", "source": HEALTHCHECKS},
    {"key": "tg", "name": "Сповіщення в Telegram", "source": HEALTHCHECKS},
]


# --- дрібні форматувальники ------------------------------------------------

def _plural_days(count: int) -> str:
    """день / дні / днів - інакше в підписі виходить «за 1 днів»."""
    if 11 <= count % 100 <= 14:
        return "днів"
    last = count % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дні"
    return "днів"


def _format_kyiv_date(dt: datetime) -> str:
    """Format datetime as '22 серпня, 14:32'."""
    return f"{dt.day} {UK_MONTHS[dt.month]}, {dt.strftime('%H:%M')}"


def format_day_title(iso_date: str, state: str) -> str:
    """Підпис однієї смуги: «25 травня — без збоїв»."""
    word = DAY_WORDS.get(state, state)
    try:
        day = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return word
    return f"{day.day} {UK_MONTHS[day.month]} — {word}"


def summarize_days(days: List[Dict[str, str]]) -> str:
    """Зведення смуги для aria-label.

    Дев'яносто окремих підписів екранна читалка перетворює на дев'яносто рядків
    шуму, тож смуга віддається одним описом, а самі смуги ховаються.
    """
    counts = Counter(day.get("state", "nodata") for day in days)
    order = (
        ("ok", "без збоїв"),
        ("deg", "зі збоями"),
        ("down", "недоступно"),
        ("mnt", "планові роботи"),
        ("nodata", "без даних"),
    )
    parts = [
        f"{counts[state]} {_plural_days(counts[state])} {word}"
        for state, word in order
        if counts.get(state)
    ]
    return ", ".join(parts) or "немає даних"


# --- розбір відповідей API -------------------------------------------------

def _parse_ts(value: Any) -> Optional[datetime]:
    """ISO-мітка часу з API у київському поясі."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KYIV_TZ)


def _slug_override(key: str) -> str:
    """Явно заданий slug чека. Читається щоразу, щоб його можна було підмінити."""
    return {
        "alerts": HEALTHCHECKS_SLUG_ALERTS_SOURCE,
        "tg": HEALTHCHECKS_SLUG_ALERTS_BROADCAST,
    }.get(key, "").strip()


def _check_api_id(check: Dict[str, Any]) -> str:
    """Ідентифікатор чека для /flips/.

    Read-only ключ не віддає uuid - замість нього приходить unique_key, і саме
    він підставляється в шлях.
    """
    return str(check.get("unique_key") or check.get("uuid") or "").strip()


def _find_matching_check(
    spec: Dict[str, Any],
    checks: List[Dict[str, Any]],
    claimed: Optional[Set[int]] = None,
) -> Optional[Dict[str, Any]]:
    """Знайти чек під компонент - тільки за точним збігом.

    Зіставлення за ping_url тут було б марним: read-only ключ це поле не віддає.
    Лишається slug і назва, і ніяких здогадок за підрядком: колись їх тут було
    три рівні, і найширший з них означав, що будь-який майбутній чек зі словом
    "api" чи "tg" у назві мовчки ставав чужим компонентом і показував під ним
    свою історію. Порожній рядок чесніший за підмінений.

    Чек, який уже забрав інший компонент, з розгляду прибирається: без цього два
    компоненти з однаковим slug у конфізі показували б один і той самий графік.
    """
    if claimed is None:
        claimed = set()
    candidates = [(i, c) for i, c in enumerate(checks) if i not in claimed]

    def _take(index: int, check: Dict[str, Any]) -> Dict[str, Any]:
        claimed.add(index)
        return check

    override = _slug_override(spec["key"]).lower()
    if override:
        for index, check in candidates:
            if str(check.get("slug", "")).strip().lower() == override:
                return _take(index, check)
        log.warning(
            "No healthchecks.io check has slug %r configured for the %r component",
            override, spec["key"],
        )
        return None

    key = spec["key"].lower()
    name = spec["name"].lower()
    for index, check in candidates:
        if (str(check.get("slug", "")).strip().lower() == key
                or str(check.get("name", "")).strip().lower() == name):
            return _take(index, check)

    log.warning("No healthchecks.io check is configured for the %r component", spec["key"])
    return None


def _fetch_flips(
    check: Dict[str, Any], headers: Dict[str, str]
) -> Tuple[List[Tuple[datetime, int]], bool]:
    """Перемикання стану чека за зростанням часу.

    Другим значенням повертається те, чи вдався запит: порожній список від
    таймауту й порожній список від «сбоїв не було» - різні речі, і плутати їх
    означає малювати зелену смугу там, де ми просто нічого не дізнались.

    Часові фільтри не ставимо навмисно: без флипа, що стався ДО початку вікна,
    неможливо дізнатись, у якому стані сервіс зустрів це вікно.
    """
    api_id = _check_api_id(check)
    if not api_id:
        log.warning(
            "Check %r has neither unique_key nor uuid; its flips are unreachable",
            check.get("name", "?"),
        )
        return [], False

    try:
        resp = requests.get(
            f"{HC_API_BASE}/checks/{api_id}/flips/", headers=headers, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        log.warning("Failed to fetch flips for check %r", check.get("name", "?"), exc_info=True)
        return [], False

    # Документація показує голий масив; обгортку приймаємо на випадок змін.
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("flips", [])
    else:
        raw = []

    flips = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        moment = _parse_ts(item.get("timestamp"))
        if moment is None:
            continue
        flips.append((moment, 1 if item.get("up") else 0))

    # Відповідь іде від нових до старих, а весь розрахунок нижче йде вперед у часі.
    flips.sort(key=lambda flip: flip[0])
    return flips, True


# --- відновлення історії ---------------------------------------------------

def _live_state(check: Optional[Dict[str, Any]]) -> Optional[str]:
    """Поточний стан чека - найпряміше джерело того, що коїться просто зараз."""
    if check is None:
        return None
    if check.get("n_pings") == 0:
        return "nodata"
    return {
        "up": "ok",
        "grace": "deg",
        "down": "down",
        "paused": "mnt",
        "new": "nodata",
    }.get(str(check.get("status", "")).lower(), "nodata")


def _state_at(flips: List[Tuple[datetime, int]], moment: datetime, fallback_up: bool) -> bool:
    """Чи був сервіс живий у вказану мить."""
    last: Optional[int] = None
    for timestamp, up in flips:
        if timestamp > moment:
            break
        last = up
    if last is not None:
        return last == 1

    # Раніше за `moment` флипів немає: стан до найпершого флипа - протилежний
    # до нього самого (флип униз означає, що до нього було вгорі).
    for _timestamp, up in flips:
        return up == 0

    return fallback_up


def _down_intervals(
    flips: List[Tuple[datetime, int]],
    window_start: datetime,
    now: datetime,
    initial_up: bool,
) -> List[Tuple[datetime, datetime]]:
    """Відрізки простою в межах [window_start, now].

    Саме відрізки, а не позначки на добах: аварія, що почалась до вікна або
    перетнула північ, інакше лишається невидимою.
    """
    intervals: List[Tuple[datetime, datetime]] = []
    down_since: Optional[datetime] = None if initial_up else window_start

    for timestamp, up in flips:
        if timestamp <= window_start:
            continue  # враховано в initial_up
        if timestamp > now:
            break
        if up == 0:
            if down_since is None:
                down_since = timestamp
        elif down_since is not None:
            intervals.append((down_since, timestamp))
            down_since = None

    if down_since is not None:
        intervals.append((down_since, now))
    return intervals


def _overlap_seconds(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return max(0.0, (end - start).total_seconds())


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=KYIV_TZ)


def _load_first_seen() -> Dict[str, str]:
    try:
        return redis_client.hgetall(FIRST_SEEN_KEY) or {}
    except Exception:
        log.warning("Redis unreachable when reading the first-seen map", exc_info=True)
        return {}


def _remember_first_seen(key: str, day: date) -> None:
    """Записати дату першої зустрічі з чеком - але тільки якщо її ще немає."""
    try:
        redis_client.hsetnx(FIRST_SEEN_KEY, key, day.isoformat())
    except Exception:
        log.warning("Redis unreachable when recording first-seen for %s", key, exc_info=True)


def _resolve_history_start(
    key: str,
    probe: Dict[str, Any],
    first_seen: Dict[str, str],
    now: datetime,
) -> Optional[datetime]:
    """З якої миті по цьому компоненту є що казати.

    Саме миті, а не доби. Якщо найраніше, що ми знаємо, - це «сервіс піднявся
    позавчора о 12:00», то про ранок позавчора не відомо нічого, і він має
    лишитись невідомим. Інакше обрізаний ретеншном край історії заднім числом
    оголошується падінням: край - це межа нашого знання, а не подія.

    last_ping тут свідомо не використовується: він завжди «щойно», і історія від
    нього щоразу схлопується в один сьогоднішній день.
    """
    if not probe["present"]:
        return None

    configured = (STATUS_START_DATE or "").strip()
    if configured:
        try:
            return _midnight(date.fromisoformat(configured))
        except ValueError:
            log.warning("Invalid STATUS_START_DATE format: %s", configured)

    _remember_first_seen(key, now.date())

    candidates = []
    if probe["flips"]:
        candidates.append(probe["flips"][0][0])
    if probe["history_start"] is not None:
        # UptimeRobot знає, коли монітор створили; healthchecks.io такого поля
        # не має й лишає цю підказку порожньою.
        candidates.append(probe["history_start"])

    remembered = first_seen.get(key)
    if remembered:
        try:
            remembered_dt = _midnight(date.fromisoformat(remembered))
            if not candidates or remembered_dt.date() < min(candidates).date():
                candidates.append(remembered_dt)
        except ValueError:
            log.warning("Stored first-seen date for %s is malformed: %r", key, remembered)

    return min(candidates) if candidates else now


def _build_component(
    spec: Dict[str, Any],
    probe: Dict[str, Any],
    now: datetime,
    first_seen: Dict[str, str],
) -> Tuple[Dict[str, Any], float, float]:
    """Один компонент: 90 діб, доступність і зведення.

    Провайдер уже звів свою відповідь до спільної форми зонда, тож уся
    арифметика нижче однакова і для healthchecks.io, і для UptimeRobot.

    Повертає також відстежені секунди й секунди простою - загальний відсоток
    рахується по них, а не середнім із середніх.
    """
    today = now.date()
    first_day = today - timedelta(days=WINDOW_DAYS - 1)
    live = probe["live"]
    flips = probe["flips"]
    history_start = _resolve_history_start(spec["key"], probe, first_seen, now)

    history_known = probe["present"] and probe["flips_ok"] and history_start is not None
    intervals: List[Tuple[datetime, datetime]] = []
    window_start = now
    if history_known:
        window_start = max(history_start, _midnight(first_day))
        initial_up = _state_at(flips, window_start, fallback_up=(live != "down"))
        intervals = _down_intervals(flips, window_start, now, initial_up)

    days: List[Dict[str, str]] = []
    tracked_seconds = 0.0
    down_seconds = 0.0
    tracked_days = 0

    for offset in range(WINDOW_DAYS):
        day = first_day + timedelta(days=offset)
        # Доба рахується лише тією частиною, що вкладається у вікно спостереження:
        # перша зазвичай неповна, остання триває тільки до «зараз».
        day_start = max(_midnight(day), window_start)
        day_end = min(_midnight(day) + timedelta(days=1), now)
        if not history_known or day_end <= day_start:
            days.append({"date": day.isoformat(), "state": "nodata"})
            continue

        down = sum(_overlap_seconds(day_start, day_end, start, end) for start, end in intervals)
        tracked_days += 1
        tracked_seconds += (day_end - day_start).total_seconds()
        down_seconds += down

        if down <= 0:
            state = "ok"
        elif down < DEGRADED_THRESHOLD:
            state = "deg"
        else:
            state = "down"
        days.append({"date": day.isoformat(), "state": state})

    # Останню добу уточнює живий статус чека. По-перше, флип у healthchecks.io
    # з'являється лише після закінчення grace, тож поточне падіння в ньому ще не
    # записане. По-друге, статус чека відомий навіть тоді, коли історії немає
    # зовсім - і тоді це єдине, що ми можемо чесно сказати про сьогодні.
    if live is not None and days:
        computed = days[-1]["state"]
        if live in ("mnt", "nodata") or computed in ("nodata", "mnt"):
            days[-1]["state"] = live
        elif SEVERITY[live] > SEVERITY[computed]:
            # За добу могло статись гірше, ніж коїться просто зараз; беремо гірше.
            days[-1]["state"] = live

    if tracked_seconds > 0:
        # uptime_pct, а не uptime: модуль провайдера імпортовано під іменем
        # uptime, і локальна змінна з тією ж назвою зробила б його недосяжним.
        uptime_pct: Optional[float] = round(
            max(0.0, min(100.0, (tracked_seconds - down_seconds) / tracked_seconds * 100)), 2
        )
    else:
        uptime_pct = None

    component = {
        "key": spec["key"],
        "name": spec["name"],
        "uptime": uptime_pct,
        "days": days,
        "tracked_days": tracked_days,
        "monitored": probe["present"],
        "state": days[-1]["state"] if days else "nodata",
    }
    return component, tracked_seconds, down_seconds


def _headline(components: List[Dict[str, Any]]) -> str:
    states = [c["state"] for c in components if c["monitored"]]
    if not states or all(state == "nodata" for state in states):
        return "Немає даних про стан"
    if "down" in states:
        return "Частина систем недоступна"
    if "deg" in states:
        return "Спостерігаються збої в роботі"
    if "mnt" in states:
        return "Планові технічні роботи"
    return "Усі системи працюють"


def _blank_probe() -> Dict[str, Any]:
    """Зонд, який нічого не стверджує: доба стане nodata, доступність - прочерк."""
    return {
        "present": False,
        "live": None,
        "flips": [],
        "flips_ok": False,
        "history_start": None,
    }


def _healthchecks_probes(specs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Зонди для компонентів, що живляться з healthchecks.io.

    Ненастроєний провайдер - це порожні зонди: компоненти чесно кажуть, що
    моніторингу немає. А от провайдер, який налаштований і не відповів, кидає
    далі: обхід має зірватись цілком, щоб refresh_status_cache нічого не
    переписав. Інакше годинний збій healthchecks.io затер би справжню
    90-денну історію суцільним "немає даних".
    """
    if not specs:
        return {}

    if not HEALTHCHECKS_API:
        log.info(
            "HEALTHCHECKS_API not configured; %s stay without monitoring",
            ", ".join(spec["key"] for spec in specs),
        )
        return {spec["key"]: _blank_probe() for spec in specs}

    headers = {"X-Api-Key": HEALTHCHECKS_API.strip()}
    resp = requests.get(f"{HC_API_BASE}/checks/", headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    checks_list = resp.json().get("checks", [])

    claimed: Set[int] = set()
    # За кількома компонентами може стояти один чек, а в API є ліміт запитів:
    # флипи тягнемо рівно раз на чек.
    flips_cache: Dict[str, Tuple[List[Tuple[datetime, int]], bool]] = {}

    probes: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        check = _find_matching_check(spec, checks_list, claimed)
        if check is None:
            probes[spec["key"]] = _blank_probe()
            continue

        api_id = _check_api_id(check)
        if api_id not in flips_cache:
            flips_cache[api_id] = _fetch_flips(check, headers)
        flips, flips_ok = flips_cache[api_id]

        probes[spec["key"]] = {
            "present": True,
            "live": _live_state(check),
            "flips": flips,
            "flips_ok": flips_ok,
            # У чека немає поля 'created', а 'started' - булеве; дату початку
            # історії доводиться брати з флипів або запам'ятовувати самим.
            "history_start": None,
        }

    return probes


def _collect_status() -> Optional[Dict[str, Any]]:
    """Опитати обидва провайдери й скласти денний розклад за 90 діб."""
    if not (HEALTHCHECKS_API or uptime.is_configured()):
        log.info("No monitoring provider is configured; the status page has nothing to report")
        return None

    now = datetime.now(KYIV_TZ)
    first_seen = _load_first_seen()

    # Провайдери опитуються незалежно, і падіння одного не забирає з собою
    # компоненти другого: половина правди краща за жодної.
    probes = _healthchecks_probes(
        [spec for spec in COMPONENTS_SPEC if spec["source"] == HEALTHCHECKS]
    )
    probes.update(
        uptime.fetch_probes(
            [spec["key"] for spec in COMPONENTS_SPEC if spec["source"] == UPTIMEROBOT],
            KYIV_TZ,
        )
    )

    components = []
    total_tracked = 0.0
    total_down = 0.0
    max_tracked_days = 0

    for spec in COMPONENTS_SPEC:
        probe = probes.get(spec["key"]) or _blank_probe()
        component, tracked, down = _build_component(spec, probe, now, first_seen)
        components.append(component)
        total_tracked += tracked
        total_down += down
        max_tracked_days = max(max_tracked_days, component["tracked_days"])

    if total_tracked > 0:
        overall: Optional[float] = round(
            max(0.0, min(100.0, (total_tracked - total_down) / total_tracked * 100)), 2
        )
    else:
        overall = None

    period_days = max_tracked_days if 0 < max_tracked_days < WINDOW_DAYS else WINDOW_DAYS

    return {
        "updated_at": _format_kyiv_date(now),
        "fetched_at": now.isoformat(),
        "headline": _headline(components),
        "overall_uptime": overall,
        "period_days": period_days,
        "period_days_word": _plural_days(period_days),
        "components": components,
        "today_iso": now.date().isoformat(),
        "stale": False,
    }


def _unknown_status_data() -> Dict[str, Any]:
    """Чесне «ми не знаємо»: жодного відсотка й жодної зеленої смуги."""
    now = datetime.now(KYIV_TZ)
    today = now.date()
    first_day = today - timedelta(days=WINDOW_DAYS - 1)

    return {
        "updated_at": _format_kyiv_date(now),
        "fetched_at": None,
        "headline": "Немає даних про стан",
        "overall_uptime": None,
        "period_days": WINDOW_DAYS,
        "period_days_word": _plural_days(WINDOW_DAYS),
        "components": [
            {
                "key": spec["key"],
                "name": spec["name"],
                "uptime": None,
                "days": [
                    {"date": (first_day + timedelta(days=offset)).isoformat(), "state": "nodata"}
                    for offset in range(WINDOW_DAYS)
                ],
                "tracked_days": 0,
                "monitored": False,
                "state": "nodata",
            }
            for spec in COMPONENTS_SPEC
        ],
        "today_iso": today.isoformat(),
        "stale": False,
        "unknown": True,
    }


def refresh_status_cache() -> Optional[Dict[str, Any]]:
    """Сходити в healthchecks.io і перекласти відповідь у кеш.

    Викликається з фонового потоку web/server.py, а не із запиту читача.
    Невдалий обхід нічого не переписує: старий знімок лишається кращим за нічого.
    """
    try:
        data = _collect_status()
    except Exception:
        log.exception("Error while collecting status data from the monitoring providers")
        return None

    if not data:
        return None

    payload = json.dumps(data, ensure_ascii=False)
    try:
        redis_client.set(CACHE_KEY, payload, ex=CACHE_TTL)
        redis_client.set(LAST_GOOD_KEY, payload, ex=LAST_GOOD_TTL)
    except Exception:
        log.warning("Redis unreachable when writing the status cache", exc_info=True)

    return data


def get_status_data() -> Dict[str, Any]:
    """Дані для сторінки стану. Тільки читання кеша - жодних походів у мережу."""
    for key, is_stale in ((CACHE_KEY, False), (LAST_GOOD_KEY, True)):
        try:
            cached = redis_client.get(key)
        except Exception:
            log.warning("Redis unreachable when reading the status cache", exc_info=True)
            break
        if not cached:
            continue
        try:
            data = json.loads(cached)
        except ValueError:
            log.warning("Cached status payload at %s is not valid JSON", key)
            continue
        if is_stale:
            data["stale"] = True
        return data

    return _unknown_status_data()
