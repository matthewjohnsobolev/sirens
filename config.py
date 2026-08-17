import os
from dotenv import load_dotenv

load_dotenv()

api_id = os.getenv('TELEGRAM_API_ID')
api_hash = os.getenv('TELEGRAM_API_HASH')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:pass@localhost:5432/sirens')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')
HEALTHCHECKS_PING_URL_ALERTS = os.getenv('HEALTHCHECKS_PING_URL_ALERTS', '')
HEALTHCHECKS_PING_URL_WEB = os.getenv('HEALTHCHECKS_PING_URL_WEB', '')
# R2 credentials for BI stats upload:
R2_ACCESS_KEY_ID = os.getenv('CLOUDFLARE_R2_ACCESS_KEY_ID') or os.getenv('R2_ACCESS_KEY_ID', '')
R2_SECRET_ACCESS_KEY = os.getenv('CLOUDFLARE_R2_SECRET_ACCESS_KEY') or os.getenv('R2_SECRET_ACCESS_KEY', '')
CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
R2_DATA_BUCKET = (
    os.getenv('CLOUDFLARE_R2_BI_DATA_BUCKET')
    or os.getenv('CLOUDFLARE_R2_DATA_BUCKET')
    or os.getenv('CLOUDFLARE_R2_BUCKET')
    or os.getenv('CLUDFLARE_R2_BUCKET')
    or os.getenv('R2_DATA_BUCKET')
    or os.getenv('R2_BUCKET', 'sirens-bi-data')
)
R2_BUCKET = R2_DATA_BUCKET
R2_WEB_BUCKET = (
    os.getenv('CLOUDFLARE_R2_BI_WEB_BUCKET')
    or os.getenv('CLOUDFLARE_R2_WEB_BUCKET')
    or os.getenv('R2_WEB_BUCKET', 'sirens-bi-web')
)
R2_ENDPOINT = os.getenv('CLOUDFLARE_R2_ENDPOINT') or os.getenv('R2_ENDPOINT', '')
if not R2_ENDPOINT and CLOUDFLARE_ACCOUNT_ID:
    R2_ENDPOINT = f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"



# Optional GitHub PAT to trigger workflow_dispatch for dashboard build
GITHUB_PAT = os.getenv('GITHUB_PAT', '')
_raw_repo = os.getenv('GITHUB_REPO', 'matthewjohnsobolev/sirens')
GITHUB_REPO = _raw_repo.replace('https://github.com/', '').replace('http://github.com/', '').replace('git@github.com:', '').strip('/')


# One Sentry project for both services: they share config.py and fail together
# (a Redis outage hits both), so a single issue stream keeps an incident whole.
# Events are told apart by the "service" tag each service sets after init.
SENTRY_DSN = os.getenv('SENTRY_DSN', '')

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
IMAGES_PATH = os.path.join(PROJECT_ROOT, "assets", "img")
SESSION_PATH =  os.path.join(PROJECT_ROOT, "data", "sessions")
LOGS_PATH = os.path.join(PROJECT_ROOT, "logs")
VERSION = '1.1.0'

test_channels = {
    'source': -1001843473515,
    'kremenchuk': -1001754447620,
    'cherkasy': -1001754447620,
    'kropyvnytskyi': -1001754447620,
    'dnipro': -1001754447620,
    'kryvyirih': -1001754447620,
    'nikopol': -1001754447620,
    'kamianske': -1001754447620,
    'zaporizhzhia': -1001754447620,
    'kyiv': -1001754447620,
    'zhytomyr': -1001754447620,
    'bilatserkva': -1001754447620,
    'bucha': -1001754447620,
    'vinnytsia': -1001754447620,
    'kharkiv': -1001754447620,
    'odesa': -1001754447620,
    'mykolaiv': -1001754447620,
    'pervomaisk': -1001754447620,
    'lviv': -1001754447620,
    'ivanofrankivsk': -1001754447620,
    'chernivtsi': -1001754447620,
    'ternopil': -1001754447620,
    'chernihiv': -1001754447620,
    'sumy': -1001754447620,
    'khmelnytskyi': -1001754447620,
    'poltava': -1002491507567,
    'lutsk': -1001754447620,
    'kovel': -1001754447620,
    'uzhhorod': -1001754447620,
    'kherson': -1001754447620,
    'fastiv': -1001754447620,
    'rivne': -1001754447620,
    'uman': -1001754447620,
    'zvenyhorodka': -1001754447620,
    'zolotonosha': -1001754447620,
    'izmail': -1001754447620,
}

real_channels = {
    'source': -1001766138888,
    'kremenchuk': -1001738859985,
    'cherkasy': -1001777493202,
    'kropyvnytskyi': -1001684581523,
    'dnipro': -1001537044610,
    'kryvyirih': -1001622554026,
    'nikopol': -1001734785202,
    'kamianske': -1001621154372,
    'zaporizhzhia': -1001738193623,
    'kyiv': -1001712561448,
    'zhytomyr': -1001711254606,
    'bilatserkva': -1001520338247,
    'bucha': -1001658454731,
    'vinnytsia': -1001680710815,
    'kharkiv': -1001746157347,
    'odesa': -1001337824256,
    'mykolaiv': -1001750632389,
    'pervomaisk': -1001165198770,
    'lviv': -1001703250824,
    'ivanofrankivsk': -1001665671654,
    'chernivtsi': -1001769342201,
    'ternopil': -1001691074647,
    'chernihiv': -1001772058915,
    'sumy': -1001700121128,
    'khmelnytskyi': -1001522478361,
    'lutsk': -1001568217990,
    'kovel': -1001689520278,
    'uzhhorod': -1001665201280,
    'kherson': -1001733476555,
    'fastiv': -1001835709020,
    'rivne': -1001820037841,
    'uman': -1002086572069,
    'poltava': -1002491507567,
    'zvenyhorodka': -1002404240334,
    'zolotonosha': -1002150602101,
    'izmail': -1002062806630,
}

MESSAGES = {
    'air_raid_alert':               '🟠 Повітряна тривога!',
    'air_raid_alert_cancelled':     '🟢 Відбій повітряної тривоги!',
    'threat_of_shelling':           '🟡 Загроза артилерійського обстрілу!',
    'threat_of_shelling_cancelled': '🟢 Відбій загрози артобстрілу!',
}

REGION_CONFIG = {
    'nikopol': {
        'triggers': ["Нікопольський район", "м. Нікополь"],
        'alert_triggers': {
            'threat_of_shelling':           ["артилерійський обстріл"],
            'threat_of_shelling_cancelled': ["Відбій загрози артобстрілу"],
            'air_raid_alert':               ["Повітряна тривога"],
            'air_raid_alert_cancelled':     ["Відбій тривоги"],
        },
        'oblast': 'dnipropetrovsk_oblast',
        'display_name': 'Nikopol'
    },

    # --- Kyiv ---
    'kyiv':          {'triggers': ["м. Київ"], 'oblast': 'kyiv', 'display_name': 'Kyiv'},

    # --- Central ---
    'cherkasy':      {'triggers': ["Черкаська область", "Черкаський район"], 'oblast': 'cherkasy_oblast', 'display_name': 'Cherkasy'},
    'uman':          {'triggers': ["Черкаська область", "Уманський район"], 'oblast': 'cherkasy_oblast', 'display_name': 'Uman'},
    'zvenyhorodka':  {'triggers': ["Черкаська область", "Звенигородський район"], 'oblast': 'cherkasy_oblast', 'display_name': 'Zvenyhorodka'},
    'zolotonosha':   {'triggers': ["Черкаська область", "Золотоніський район"], 'oblast': 'cherkasy_oblast', 'display_name': 'Zolotonosha'},
    'chernihiv':     {'triggers': ["Чернігівська область", "Чернігівський район"], 'oblast': 'chernihiv_oblast', 'display_name': 'Chernihiv'},
    'kropyvnytskyi': {'triggers': ["Кіровоградська область", "Кропивницький район"], 'oblast': 'kirovohrad_oblast', 'display_name': 'Kropyvnytskyi'},
    'poltava':       {'triggers': ["Полтавська область", "Полтавський район"], 'oblast': 'poltava_oblast', 'display_name': 'Poltava'},
    'kremenchuk':    {'triggers': ["Полтавська область", "Кременчуцький район"], 'oblast': 'poltava_oblast', 'display_name': 'Kremenchuk'},
    'vinnytsia':     {'triggers': ["Вінницька область", "Вінницький район"], 'oblast': 'vinnytsia_oblast', 'display_name': 'Vinnytsia'},
    'zhytomyr':      {'triggers': ["Житомирська область", "Житомирський район"], 'oblast': 'zhytomyr_oblast', 'display_name': 'Zhytomyr'},

    # --- Kyiv region ---
    'bilatserkva':   {'triggers': ["Київська область", "Білоцерківський район"], 'oblast': 'kyiv_oblast', 'display_name': 'Bila Tserkva'},
    'bucha':         {'triggers': ["Київська область", "Бучанський район"], 'oblast': 'kyiv_oblast', 'display_name': 'Bucha'},
    'fastiv':        {'triggers': ["Київська область", "Фастівський район"], 'oblast': 'kyiv_oblast', 'display_name': 'Fastiv'},

    # --- Northeast ---
    'kharkiv':       {'triggers': ["Харківська область", "м. Харків"], 'oblast': 'kharkiv_oblast', 'display_name': 'Kharkiv'},
    'sumy':          {'triggers': ["Сумська область", "Сумський район"], 'oblast': 'sumy_oblast', 'display_name': 'Sumy'},

    # --- East ---
    'zaporizhzhia':  {'triggers': ["Запорізька область", "м. Запоріжжя"], 'oblast': 'zaporizhzhia_oblast', 'display_name': 'Zaporizhzhia'},
    'dnipro':        {'triggers': ["Дніпропетровська область", "Дніпровський район"], 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Dnipro'},
    'kryvyirih':     {'triggers': ["Дніпропетровська область", "Криворізький район"], 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Kryvyi Rih'},
    'kamianske':     {'triggers': ["Дніпропетровська область", "Кам’янський район", "Кам'янський район"], 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Kamianske'},

    # --- South ---
    'kherson':       {'triggers': ["Херсонська область", "Херсонський район"], 'oblast': 'kherson_oblast', 'display_name': 'Kherson'},
    'mykolaiv':      {'triggers': ["Миколаївська область", "Миколаївський район"], 'oblast': 'mykolaiv_oblast', 'display_name': 'Mykolaiv'},
    'pervomaisk':    {'triggers': ["Миколаївська область", "Первомайський район"], 'oblast': 'mykolaiv_oblast', 'display_name': 'Pervomaisk'},
    'odesa':         {'triggers': ["Одеська область", "Одеський район"], 'oblast': 'odesa_oblast', 'display_name': 'Odesa'},
    'izmail':        {'triggers': ["Одеська область", "Ізмаїльський район"], 'oblast': 'odesa_oblast', 'display_name': 'Izmail'},

    # --- West ---
    'lviv':          {'triggers': ["Львівська область", "Львівський район"], 'oblast': 'lviv_oblast', 'display_name': 'Lviv'},
    'lutsk':         {'triggers': ["Волинська область", "Луцький район"], 'oblast': 'volyn_oblast', 'display_name': 'Lutsk'},
    'kovel':         {'triggers': ["Волинська область", "Ковельський район"], 'oblast': 'volyn_oblast', 'display_name': 'Kovel'},
    'rivne':         {'triggers': ["Рівненська область", "Рівненський район"], 'oblast': 'rivne_oblast', 'display_name': 'Rivne'},
    'ternopil':      {'triggers': ["Тернопільська область", "Тернопільський район"], 'oblast': 'ternopil_oblast', 'display_name': 'Ternopil'},
    'khmelnytskyi':  {'triggers': ["Хмельницька область", "Хмельницький район"], 'oblast': 'khmelnytskyi_oblast', 'display_name': 'Khmelnytskyi'},
    'ivanofrankivsk': {'triggers': ["Івано-Франківська область", "Івано-Франківський район"], 'oblast': 'ivanofrankivsk_oblast', 'display_name': 'Ivano-Frankivsk'},
    'uzhhorod':      {'triggers': ["Закарпатська область", "Ужгородський район"], 'oblast': 'zakarpattia_oblast', 'display_name': 'Uzhhorod'},
    'chernivtsi':    {'triggers': ["Чернівецька область", "Чернівецький район"], 'oblast': 'chernivtsi_oblast', 'display_name': 'Chernivtsi'},
}

CITIES_LIST = [(key, data['display_name']) for key, data in REGION_CONFIG.items()]