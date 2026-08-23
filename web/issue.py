"""Що саме питає форма /issue - і чим сервер перевіряє відповідь.

Один опис на три боки. Сторінка малює з нього вкладки, перелік варіантів і
підказку міст; той самий перелік сервер бере за словник, коли приймає POST;
з нього ж береться англійський підпис, під яким звернення лягає в Sentry.
Доки джерело спільне, "що саме сталося" на сторінці й у Sentry - це буквально
один рядок; розійтись вони можуть тільки разом.

Порядок розділів тут - порядок вкладок на сторінці, порядок варіантів -
порядок кнопок усередині розділу.
"""

from config import BROADCAST_CITIES, DISTRICT_CONFIG

# Розділ - це не тема листа, а місце, де шукати збій: сповіщення живуть у
# ботові, мапа - у вебі, решта не має спільного місця взагалі.
#
# 'tab'  - напис на вкладці; короткий, бо їх три в рядок на 320px.
# 'name' - те, з чим звернення живе далі: ним сервер перевіряє відповідь, його
#          бачить людина. "Мапа тривог" замість "Мапа": у списку звернень
#          мусить читатись без сторінки поруч.
# 'en'   - те саме англійською, для Sentry: звіти читають у консолі, де решта
#          подій англійською, і кирилиця там читалась би найгірше з усього.
# 'key'  - незмінний ярлик варіанта. Тег у Sentry тримається саме за нього, а
#          не за формулювання: перепишеш український рядок - група подій
#          лишиться тією самою.
CATEGORIES = (
    {
        'id': 'alerts',
        'tab': 'Сповіщення',
        'name': 'Сповіщення',
        'en': 'Alerts',
        # Кожен варіант - окремий збій із власною причиною, а не відтінок
        # сусіднього: спізнилось / не прийшло / прийшло дарма / не той стан.
        # Формулювання від людини: те, що вона бачила, а не те, як це зветься
        # всередині.
        'options': (
            {
                'key': 'late',
                'name': 'Сповіщення прийшло із запізненням',
                'en': 'Notification arrived late',
            },
            {
                'key': 'never_arrived',
                'name': 'Сповіщення не прийшло взагалі',
                'en': 'Notification never arrived',
            },
            {
                'key': 'false_alarm',
                'name': 'Сповіщення прийшло, хоча тривоги не було',
                'en': 'Notification sent with no alert',
            },
            {
                'key': 'early_all_clear',
                'name': 'Прийшов відбій, хоча тривога тривала',
                'en': 'All-clear sent while the alert was still on',
            },
        ),
    },
    {
        'id': 'map',
        'tab': 'Мапа',
        'name': 'Мапа тривог',
        'en': 'Alert map',
        'options': (
            {
                'key': 'oblast_not_highlighted',
                'name': 'Область не підсвічена, хоча тривога є',
                'en': 'Oblast not highlighted during an alert',
            },
            {
                'key': 'oblast_highlighted',
                'name': 'Область підсвічена, хоча тривоги немає',
                'en': 'Oblast highlighted with no alert',
            },
            {
                'key': 'map_not_opening',
                'name': 'Мапа не відкривається зовсім',
                'en': 'Map does not open at all',
            },
        ),
    },
    {
        'id': 'other',
        'tab': 'Інше',
        'name': 'Інше',
        'en': 'Other',
        'options': (),
    },
)

OPTIONS_BY_CATEGORY = {c['name']: tuple(o['name'] for o in c['options']) for c in CATEGORIES}

# Вкладка підписана коротко, а далі звернення живе під повною назвою. Без
# JavaScript у полі category опиняється саме напис вкладки, тож короткі форми
# лишаються чинними на вході й нормалізуються до 'name'.
CATEGORY_ALIASES = {c['tab']: c['name'] for c in CATEGORIES}

# Порядок кирилиці в Unicode - не український алфавіт: і, ї, є, ґ винесені в
# додатковий блок і за замовчуванням падають у кінець списку, за "я". Тому
# ключ сортування - позиція літери в абетці, а не її код.
UKRAINIAN_ALPHABET = 'абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'
_LETTER_ORDER = {letter: i for i, letter in enumerate(UKRAINIAN_ALPHABET)}


def ukrainian_sort_key(name: str) -> list[int]:
    """Назва як послідовність позицій в абетці; апостроф і дефіс не рахуються."""
    return [_LETTER_ORDER[ch] for ch in name.lower() if ch in _LETTER_ORDER]


# Підказка міста - це рівно ті міста, куди я мовлю: людина скаржиться на
# сповіщення, якого чекала, а чекати його можна тільки там, де є канал.
# Поле при цьому лишається вільним - список підказує, але не обмежує.
CITIES = tuple(sorted(BROADCAST_CITIES.values(), key=ukrainian_sort_key))

# Підказка району - повний список районів з конфігурації.
DISTRICTS = tuple(sorted({conf['name'] for conf in DISTRICT_CONFIG.values()}, key=ukrainian_sort_key))

# Коли саме сталася проблема (обов'язково для сповіщення та мапи, необов'язково для іншого).
TIME_OPTIONS = (
    {'key': 'just_now', 'name': 'Щойно', 'en': 'Just now'},
    {'key': 'under_1hour', 'name': 'Менше години тому', 'en': 'Less than 1 hour ago'},
    {'key': 'custom', 'name': 'Вибрати дату і час', 'en': 'Specific time'},
)

TIME_NAMES = tuple(t['name'] for t in TIME_OPTIONS)

# Українське формулювання -> те, чим воно є для Sentry. Пошук іде за 'name',
# бо саме він приходить із форми: сторінка не знає ні про ключі, ні про
# англійські підписи, і знати не мусить.
CATEGORY_INFO = {c['name']: {'key': c['id'], 'en': c['en']} for c in CATEGORIES}
OPTION_INFO = {
    o['name']: {'key': o['key'], 'en': o['en']} for c in CATEGORIES for o in c['options']
}
TIME_INFO = {t['name']: {'key': t['key'], 'en': t['en']} for t in TIME_OPTIONS}


def page_config() -> dict:
    """Той самий довідник у формі, зручній сторінці.

    Їде в розмітку одним JSON, бо інакше перелік довелося б тримати ще й у
    JavaScript - і саме він першим розійшовся б із перевіркою на сервері.

    Ключі й англійські підписи сюди не потрапляють: вони існують для Sentry,
    а сторінці нема чого з ними робити.
    """
    return {
        'sets': {c['id']: [o['name'] for o in c['options']] for c in CATEGORIES},
        'categories': {c['id']: c['name'] for c in CATEGORIES},
        'cities': list(CITIES),
        'districts': list(DISTRICTS),
        'time_options': list(TIME_NAMES),
    }
