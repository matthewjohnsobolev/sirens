"""
Issue form configuration and dictionary for the web interface and Sentry.
"""

from domain import BROADCAST_CITIES, DISTRICT_CONFIG

CATEGORIES = (
    {
        "id": "alerts",
        "tab": "Сповіщення",
        "name": "Сповіщення",
        "en": "Alerts",
        "options": (
            {
                "key": "late",
                "name": "Сповіщення прийшло із запізненням",
                "en": "Notification arrived late",
            },
            {
                "key": "never_arrived",
                "name": "Сповіщення не прийшло взагалі",
                "en": "Notification never arrived",
            },
            {
                "key": "false_alarm",
                "name": "Сповіщення прийшло, хоча тривоги не було",
                "en": "Notification sent with no alert",
            },
            {
                "key": "early_all_clear",
                "name": "Прийшов відбій, хоча тривога тривала",
                "en": "All-clear sent while the alert was still on",
            },
            {
                "key": "duplicate",
                "name": "Сповіщення прийшло двічі поспіль",
                "en": "Notification arrived twice in a row",
            },
        ),
    },
    {
        "id": "map",
        "tab": "Мапа",
        "name": "Мапа тривог",
        "en": "Alert map",
        "options": (
            {
                "key": "oblast_not_highlighted",
                "name": "Область не підсвічена, хоча тривога є",
                "en": "Oblast not highlighted during an alert",
            },
            {
                "key": "oblast_highlighted",
                "name": "Область підсвічена, хоча тривоги немає",
                "en": "Oblast highlighted with no alert",
            },
            {
                "key": "map_not_opening",
                "name": "Мапа не відкривається зовсім",
                "en": "Map does not open at all",
            },
        ),
    },
    {
        "id": "other",
        "tab": "Інше",
        "name": "Інше",
        "en": "Other",
        "options": (),
    },
)

OPTIONS_BY_CATEGORY = {c["name"]: tuple(o["name"] for o in c["options"]) for c in CATEGORIES}
CATEGORY_ALIASES = {c["tab"]: c["name"] for c in CATEGORIES}

UKRAINIAN_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_LETTER_ORDER = {letter: i for i, letter in enumerate(UKRAINIAN_ALPHABET)}


def ukrainian_sort_key(name: str) -> list[int]:
    return [_LETTER_ORDER[ch] for ch in name.lower() if ch in _LETTER_ORDER]


CITIES = tuple(sorted(BROADCAST_CITIES.values(), key=ukrainian_sort_key))
DISTRICTS = tuple(
    sorted({conf["name"] for conf in DISTRICT_CONFIG.values()}, key=ukrainian_sort_key)
)

TIME_OPTIONS = (
    {"key": "just_now", "name": "Щойно", "en": "Just now"},
    {"key": "under_1hour", "name": "Менше години тому", "en": "Less than 1 hour ago"},
    {"key": "custom", "name": "Вибрати дату і час", "en": "Specific time"},
)

TIME_NAMES = tuple(t["name"] for t in TIME_OPTIONS)

CATEGORY_INFO = {c["name"]: {"key": c["id"], "en": c["en"]} for c in CATEGORIES}
OPTION_INFO = {
    o["name"]: {"key": o["key"], "en": o["en"]} for c in CATEGORIES for o in c["options"]
}
TIME_INFO = {t["name"]: {"key": t["key"], "en": t["en"]} for t in TIME_OPTIONS}


def page_config() -> dict:
    return {
        "sets": {c["id"]: [o["name"] for o in c["options"]] for c in CATEGORIES},
        "categories": {c["id"]: c["name"] for c in CATEGORIES},
        "cities": list(CITIES),
        "districts": list(DISTRICTS),
        "time_options": list(TIME_NAMES),
    }
