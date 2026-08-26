import os
import sys
from dotenv import load_dotenv

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

load_dotenv()

api_id = os.getenv('TELEGRAM_API_ID')
api_hash = os.getenv('TELEGRAM_API_HASH')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:pass@localhost:5432/sirens')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')
# Два кінці ланцюга тривог міряються окремо: SOURCE - чи пости з джерела доходять
# до нас, BROADCAST - чи наші розсилки в канали мережі проходять. Ламаються вони
# незалежно, тож і чеки різні.
HEALTHCHECKS_PING_URL_ALERTS_SOURCE = os.getenv('HEALTHCHECKS_PING_URL_ALERTS_SOURCE', '')
HEALTHCHECKS_PING_URL_ALERTS_BROADCAST = os.getenv('HEALTHCHECKS_PING_URL_ALERTS_BROADCAST', '')
HEALTHCHECKS_PING_URL_WEB = os.getenv('HEALTHCHECKS_PING_URL_WEB', '')
HEALTHCHECKS_API = (
    os.getenv('HEALTHCHECKS_API')
    or os.getenv('HEALTHCHECKS_READ_ONLY_API')
    or os.getenv('HEALTHCHECKS_API_KEY')
    or ''
)
# З якої дати історія на сторінці стану вважається достовірною. Спільна для обох
# провайдерів; HEALTHCHECKS_START_DATE лишається запасним ім'ям заради тих .env,
# де воно вже прописане.
STATUS_START_DATE = (
    os.getenv('STATUS_START_DATE')
    or os.getenv('HEALTHCHECKS_START_DATE')
    or ''
)
# Явні slug чеків для сторінки стану. Read-only ключ не віддає ping_url, тож
# зіставити компонент із чеком інакше можна лише за назвою - здогадкою, яку
# ламає будь-яке перейменування в healthchecks.io.
HEALTHCHECKS_SLUG_ALERTS_SOURCE = os.getenv('HEALTHCHECKS_SLUG_ALERTS_SOURCE', '')
HEALTHCHECKS_SLUG_ALERTS_BROADCAST = os.getenv('HEALTHCHECKS_SLUG_ALERTS_BROADCAST', '')

# UptimeRobot - друга модель моніторингу: чорна скриня ззовні там, де
# healthchecks.io знає лише те, що сервіс сам про себе розповів. Ключі тут
# помоніторні, а не акаунтні: такий ключ віддає рівно свій монітор, тож
# зіставляти компонент із монітором не доводиться взагалі.
UPTIMEROBOT_SIRENS_WEB_API = os.getenv('UPTIMEROBOT_SIRENS_WEB_API', '')
UPTIMEROBOT_SIRENS_API_API = os.getenv('UPTIMEROBOT_SIRENS_API_API', '')

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

# Cloudflare KV for Status Page telemetry:
CLOUDFLARE_API_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN') or os.getenv('CLOUDFLARE_KV_API_TOKEN', '')
CLOUDFLARE_KV_STATUS_NAMESPACE_ID = (
    os.getenv('CLOUDFLARE_KV_STATUS_NAMESPACE_ID')
    or os.getenv('CLOUDFLARE_KV_NAMESPACE_ID', '')
)


# Optional GitHub PAT to trigger workflow_dispatch for dashboard build
GITHUB_PAT = os.getenv('GITHUB_PAT', '')
_raw_repo = os.getenv('GITHUB_REPO', 'matthewjohnsobolev/sirens')
GITHUB_REPO = _raw_repo.replace('https://github.com/', '').replace('http://github.com/', '').replace('git@github.com:', '').strip('/')

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

# --- Райони України ---------------------------------------------------------
#
# Довідник районів підконтрольних областей живить дві різні речі: перехоплення
# тривог і карту. Бродкаст - третя, окрема роль: район отримує його лише тоді,
# коли його ключ є серед real_channels. Тому записи діляться на два типи -
# "карта + тривога" (є свій канал, є display_name) і "просто карта" (стан
# пишеться в Redis/PG, а таблетка на карті веде на пост першоджерела).
#
# 'name'    - українська назва; вона ж підзаголовок у попапі області.
# 'aliases' - інші форми, якими джерело може назвати той самий район: назва до
#             перейменування або місто замість району.
#
# Ключі районів із каналом збігаються з ключами real_channels і не змінюються:
# на них стоїть історія в alert_history і ключі стану в Redis.
#
# Крим, Севастополь, Донецька й Луганська область районів тут не мають -
# їхні попапи лишаються з єдиною плашкою "Немає даних по районах".

APOSTROPHES = ("'", "’")


def apostrophe_variants(name):
    """Обидві форми апострофа: джерело пише то ', то ’."""
    if not any(mark in name for mark in APOSTROPHES):
        return [name]
    straight = name.replace("’", "'")
    return [straight, straight.replace("'", "’")]


DISTRICT_CONFIG = {
    # --- Київ ---
    'kyiv':               {'name': 'м. Київ', 'oblast': 'kyiv', 'display_name': 'Kyiv'},

    # --- Київська ---
    'bilatserkva':        {'name': 'Білоцерківський район', 'oblast': 'kyiv_oblast', 'display_name': 'Bila Tserkva'},
    'boryspil':           {'name': 'Бориспільський район', 'oblast': 'kyiv_oblast'},
    'brovary':            {'name': 'Броварський район', 'oblast': 'kyiv_oblast'},
    'bucha':              {'name': 'Бучанський район', 'oblast': 'kyiv_oblast', 'display_name': 'Bucha'},
    'vyshhorod':          {'name': 'Вишгородський район', 'oblast': 'kyiv_oblast'},
    'obukhiv':            {'name': 'Обухівський район', 'oblast': 'kyiv_oblast'},
    'fastiv':             {'name': 'Фастівський район', 'oblast': 'kyiv_oblast', 'display_name': 'Fastiv'},

    # --- Вінницька ---
    'vinnytsia':          {'name': 'Вінницький район', 'oblast': 'vinnytsia_oblast', 'display_name': 'Vinnytsia'},
    'haisyn':             {'name': 'Гайсинський район', 'oblast': 'vinnytsia_oblast'},
    'zhmerynka':          {'name': 'Жмеринський район', 'oblast': 'vinnytsia_oblast'},
    'mohylivpodilskyi':   {'name': 'Могилів-Подільський район', 'oblast': 'vinnytsia_oblast'},
    'tulchyn':            {'name': 'Тульчинський район', 'oblast': 'vinnytsia_oblast'},
    'khmilnyk':           {'name': 'Хмільницький район', 'oblast': 'vinnytsia_oblast'},

    # --- Волинська ---
    'lutsk':              {'name': 'Луцький район', 'oblast': 'volyn_oblast', 'display_name': 'Lutsk'},
    'volodymyr':          {'name': 'Володимирський район', 'oblast': 'volyn_oblast',
                           'aliases': ['Володимир-Волинський район']},
    'kaminkashyrskyi':    {'name': 'Камінь-Каширський район', 'oblast': 'volyn_oblast'},
    'kovel':              {'name': 'Ковельський район', 'oblast': 'volyn_oblast', 'display_name': 'Kovel'},

    # --- Дніпропетровська ---
    'dnipro':             {'name': 'Дніпровський район', 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Dnipro'},
    'kamianske':          {'name': "Кам'янський район", 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Kamianske'},
    'kryvyirih':          {'name': 'Криворізький район', 'oblast': 'dnipropetrovsk_oblast', 'display_name': 'Kryvyi Rih'},
    'nikopol': {
        'name': 'Нікопольський район',
        'aliases': ['м. Нікополь'],
        'oblast': 'dnipropetrovsk_oblast',
        'display_name': 'Nikopol',
        'alert_triggers': {
            'threat_of_shelling':           ["артилерійський обстріл"],
            'threat_of_shelling_cancelled': ["Відбій загрози артобстрілу"],
            'air_raid_alert':               ["Повітряна тривога"],
            'air_raid_alert_cancelled':     ["Відбій тривоги"],
        },
    },
    'pavlohrad':          {'name': 'Павлоградський район', 'oblast': 'dnipropetrovsk_oblast'},
    'samar':              {'name': 'Самарівський район', 'oblast': 'dnipropetrovsk_oblast',
                           'aliases': ['Новомосковський район']},
    'synelnykove':        {'name': 'Синельниківський район', 'oblast': 'dnipropetrovsk_oblast'},

    # --- Житомирська ---
    'zhytomyr':           {'name': 'Житомирський район', 'oblast': 'zhytomyr_oblast', 'display_name': 'Zhytomyr'},
    'berdychiv':          {'name': 'Бердичівський район', 'oblast': 'zhytomyr_oblast'},
    'zviahel':            {'name': 'Звягельський район', 'oblast': 'zhytomyr_oblast',
                           'aliases': ['Новоград-Волинський район']},
    'korosten':           {'name': 'Коростенський район', 'oblast': 'zhytomyr_oblast'},

    # --- Закарпатська ---
    'uzhhorod':           {'name': 'Ужгородський район', 'oblast': 'zakarpattia_oblast', 'display_name': 'Uzhhorod'},
    'berehove':           {'name': 'Берегівський район', 'oblast': 'zakarpattia_oblast'},
    'mukachevo':          {'name': 'Мукачівський район', 'oblast': 'zakarpattia_oblast'},
    'rakhiv':             {'name': 'Рахівський район', 'oblast': 'zakarpattia_oblast'},
    'tiachiv':            {'name': 'Тячівський район', 'oblast': 'zakarpattia_oblast'},
    'khust':              {'name': 'Хустський район', 'oblast': 'zakarpattia_oblast'},

    # --- Запорізька ---
    'zaporizhzhia':       {'name': 'Запорізький район', 'oblast': 'zaporizhzhia_oblast',
                           'aliases': ['м. Запоріжжя'], 'display_name': 'Zaporizhzhia'},
    'berdiansk':          {'name': 'Бердянський район', 'oblast': 'zaporizhzhia_oblast'},
    'vasylivka':          {'name': 'Василівський район', 'oblast': 'zaporizhzhia_oblast'},
    'melitopol':          {'name': 'Мелітопольський район', 'oblast': 'zaporizhzhia_oblast'},
    'polohy':             {'name': 'Пологівський район', 'oblast': 'zaporizhzhia_oblast'},

    # --- Івано-Франківська ---
    'ivanofrankivsk':     {'name': 'Івано-Франківський район', 'oblast': 'ivanofrankivsk_oblast', 'display_name': 'Ivano-Frankivsk'},
    'verkhovyna':         {'name': 'Верховинський район', 'oblast': 'ivanofrankivsk_oblast'},
    'kalush':             {'name': 'Калуський район', 'oblast': 'ivanofrankivsk_oblast'},
    'kolomyia':           {'name': 'Коломийський район', 'oblast': 'ivanofrankivsk_oblast'},
    'kosiv':              {'name': 'Косівський район', 'oblast': 'ivanofrankivsk_oblast'},
    'nadvirna':           {'name': 'Надвірнянський район', 'oblast': 'ivanofrankivsk_oblast'},

    # --- Кіровоградська ---
    'kropyvnytskyi':      {'name': 'Кропивницький район', 'oblast': 'kirovohrad_oblast', 'display_name': 'Kropyvnytskyi'},
    'holovanivsk':        {'name': 'Голованівський район', 'oblast': 'kirovohrad_oblast'},
    'novoukrainka':       {'name': 'Новоукраїнський район', 'oblast': 'kirovohrad_oblast'},
    'oleksandriia':       {'name': 'Олександрійський район', 'oblast': 'kirovohrad_oblast'},

    # --- Львівська ---
    'lviv':               {'name': 'Львівський район', 'oblast': 'lviv_oblast', 'display_name': 'Lviv'},
    'drohobych':          {'name': 'Дрогобицький район', 'oblast': 'lviv_oblast'},
    'zolochiv':           {'name': 'Золочівський район', 'oblast': 'lviv_oblast'},
    'sambir':             {'name': 'Самбірський район', 'oblast': 'lviv_oblast'},
    'stryi':              {'name': 'Стрийський район', 'oblast': 'lviv_oblast'},
    'chervonohrad':       {'name': 'Червоноградський район', 'oblast': 'lviv_oblast'},
    'yavoriv':            {'name': 'Яворівський район', 'oblast': 'lviv_oblast'},

    # --- Миколаївська ---
    'mykolaiv':           {'name': 'Миколаївський район', 'oblast': 'mykolaiv_oblast', 'display_name': 'Mykolaiv'},
    'bashtanka':          {'name': 'Баштанський район', 'oblast': 'mykolaiv_oblast'},
    'voznesensk':         {'name': 'Вознесенський район', 'oblast': 'mykolaiv_oblast'},
    'pervomaisk':         {'name': 'Первомайський район', 'oblast': 'mykolaiv_oblast', 'display_name': 'Pervomaisk'},

    # --- Одеська ---
    'odesa':              {'name': 'Одеський район', 'oblast': 'odesa_oblast', 'display_name': 'Odesa'},
    'berezivka':          {'name': 'Березівський район', 'oblast': 'odesa_oblast'},
    'bilhoroddnistrovskyi': {'name': 'Білгород-Дністровський район', 'oblast': 'odesa_oblast'},
    'bolhrad':            {'name': 'Болградський район', 'oblast': 'odesa_oblast'},
    'izmail':             {'name': 'Ізмаїльський район', 'oblast': 'odesa_oblast', 'display_name': 'Izmail'},
    'podilsk':            {'name': 'Подільський район', 'oblast': 'odesa_oblast'},
    'rozdilna':           {'name': 'Роздільнянський район', 'oblast': 'odesa_oblast'},

    # --- Полтавська ---
    'poltava':            {'name': 'Полтавський район', 'oblast': 'poltava_oblast', 'display_name': 'Poltava'},
    'kremenchuk':         {'name': 'Кременчуцький район', 'oblast': 'poltava_oblast', 'display_name': 'Kremenchuk'},
    'lubny':              {'name': 'Лубенський район', 'oblast': 'poltava_oblast'},
    'myrhorod':           {'name': 'Миргородський район', 'oblast': 'poltava_oblast'},

    # --- Рівненська ---
    'rivne':              {'name': 'Рівненський район', 'oblast': 'rivne_oblast', 'display_name': 'Rivne'},
    'varash':             {'name': 'Вараський район', 'oblast': 'rivne_oblast'},
    'dubno':              {'name': 'Дубенський район', 'oblast': 'rivne_oblast'},
    'sarny':              {'name': 'Сарненський район', 'oblast': 'rivne_oblast'},

    # --- Сумська ---
    'sumy':               {'name': 'Сумський район', 'oblast': 'sumy_oblast', 'display_name': 'Sumy'},
    'konotop':            {'name': 'Конотопський район', 'oblast': 'sumy_oblast'},
    'okhtyrka':           {'name': 'Охтирський район', 'oblast': 'sumy_oblast'},
    'romny':              {'name': 'Роменський район', 'oblast': 'sumy_oblast'},
    'shostka':            {'name': 'Шосткинський район', 'oblast': 'sumy_oblast'},

    # --- Тернопільська ---
    'ternopil':           {'name': 'Тернопільський район', 'oblast': 'ternopil_oblast', 'display_name': 'Ternopil'},
    'kremenets':          {'name': 'Кременецький район', 'oblast': 'ternopil_oblast'},
    'chortkiv':           {'name': 'Чортківський район', 'oblast': 'ternopil_oblast'},

    # --- Харківська ---
    'kharkiv':            {'name': 'Харківський район', 'oblast': 'kharkiv_oblast',
                           'aliases': ['м. Харків'], 'display_name': 'Kharkiv'},
    'berestyn':           {'name': 'Берестинський район', 'oblast': 'kharkiv_oblast',
                           'aliases': ['Красноградський район']},
    'bohodukhiv':         {'name': 'Богодухівський район', 'oblast': 'kharkiv_oblast'},
    'izium':              {'name': 'Ізюмський район', 'oblast': 'kharkiv_oblast'},
    'kupiansk':           {'name': "Куп'янський район", 'oblast': 'kharkiv_oblast'},
    'lozova':             {'name': 'Лозівський район', 'oblast': 'kharkiv_oblast'},
    'chuhuiv':            {'name': 'Чугуївський район', 'oblast': 'kharkiv_oblast'},

    # --- Херсонська ---
    'kherson':            {'name': 'Херсонський район', 'oblast': 'kherson_oblast', 'display_name': 'Kherson'},
    'beryslav':           {'name': 'Бериславський район', 'oblast': 'kherson_oblast'},
    'henichesk':          {'name': 'Генічеський район', 'oblast': 'kherson_oblast'},
    'kakhovka':           {'name': 'Каховський район', 'oblast': 'kherson_oblast'},
    'skadovsk':           {'name': 'Скадовський район', 'oblast': 'kherson_oblast'},

    # --- Хмельницька ---
    'khmelnytskyi':       {'name': 'Хмельницький район', 'oblast': 'khmelnytskyi_oblast', 'display_name': 'Khmelnytskyi'},
    'kamianetspodilskyi': {'name': "Кам'янець-Подільський район", 'oblast': 'khmelnytskyi_oblast'},
    'shepetivka':         {'name': 'Шепетівський район', 'oblast': 'khmelnytskyi_oblast'},

    # --- Черкаська ---
    'cherkasy':           {'name': 'Черкаський район', 'oblast': 'cherkasy_oblast', 'display_name': 'Cherkasy'},
    'zvenyhorodka':       {'name': 'Звенигородський район', 'oblast': 'cherkasy_oblast', 'display_name': 'Zvenyhorodka'},
    'zolotonosha':        {'name': 'Золотоніський район', 'oblast': 'cherkasy_oblast', 'display_name': 'Zolotonosha'},
    'uman':               {'name': 'Уманський район', 'oblast': 'cherkasy_oblast', 'display_name': 'Uman'},

    # --- Чернівецька ---
    'chernivtsi':         {'name': 'Чернівецький район', 'oblast': 'chernivtsi_oblast', 'display_name': 'Chernivtsi'},
    'vyzhnytsia':         {'name': 'Вижницький район', 'oblast': 'chernivtsi_oblast'},
    'dnistrovskyi':       {'name': 'Дністровський район', 'oblast': 'chernivtsi_oblast'},

    # --- Чернігівська ---
    'chernihiv':          {'name': 'Чернігівський район', 'oblast': 'chernihiv_oblast', 'display_name': 'Chernihiv'},
    'koriukivka':         {'name': 'Корюківський район', 'oblast': 'chernihiv_oblast'},
    'nizhyn':             {'name': 'Ніжинський район', 'oblast': 'chernihiv_oblast'},
    'novhorodsiverskyi':  {'name': 'Новгород-Сіверський район', 'oblast': 'chernihiv_oblast'},
    'pryluky':            {'name': 'Прилуцький район', 'oblast': 'chernihiv_oblast'},
}

for _key, _conf in DISTRICT_CONFIG.items():
    _forms = [_conf['name'], *_conf.get('aliases', ())]
    _conf['triggers'] = [form for raw in _forms for form in apostrophe_variants(raw)]

# Згадка області піднімає тривогу в усіх її районах - джерело часто оголошує
# тривогу саме по області, а не перелічує райони.
OBLAST_TRIGGERS = {
    'cherkasy_oblast':       ["Черкаська область"],
    'chernihiv_oblast':      ["Чернігівська область"],
    'chernivtsi_oblast':     ["Чернівецька область"],
    'dnipropetrovsk_oblast': ["Дніпропетровська область"],
    'ivanofrankivsk_oblast': ["Івано-Франківська область"],
    'kharkiv_oblast':        ["Харківська область"],
    'kherson_oblast':        ["Херсонська область"],
    'khmelnytskyi_oblast':   ["Хмельницька область"],
    'kirovohrad_oblast':     ["Кіровоградська область"],
    'kyiv_oblast':           ["Київська область"],
    'lviv_oblast':           ["Львівська область"],
    'mykolaiv_oblast':       ["Миколаївська область"],
    'odesa_oblast':          ["Одеська область"],
    'poltava_oblast':        ["Полтавська область"],
    'rivne_oblast':          ["Рівненська область"],
    'sumy_oblast':           ["Сумська область"],
    'ternopil_oblast':       ["Тернопільська область"],
    'vinnytsia_oblast':      ["Вінницька область"],
    'volyn_oblast':          ["Волинська область"],
    'zakarpattia_oblast':    ["Закарпатська область"],
    'zaporizhzhia_oblast':   ["Запорізька область"],
    'zhytomyr_oblast':       ["Житомирська область"],
}

# Райони, у яких є свій канал: саме вони - і тільки вони - отримують бродкаст.
BROADCAST_DISTRICTS = frozenset(real_channels) - {'source'}

# REGION_CONFIG лишається тим, чим був: районами з каналом. Формат теж старий -
# 'triggers' містять і назву району, і назву області.
REGION_CONFIG = {
    key: {**conf, 'triggers': conf['triggers'] + OBLAST_TRIGGERS.get(conf['oblast'], [])}
    for key, conf in DISTRICT_CONFIG.items()
    if key in BROADCAST_DISTRICTS
}

# Карта показує всі райони, а не лише ті, куди я мовлю.
DISTRICTS_BY_OBLAST = {}
for district_key, conf in DISTRICT_CONFIG.items():
    DISTRICTS_BY_OBLAST.setdefault(conf['oblast'], []).append(district_key)

CITIES_LIST = [(key, data['display_name']) for key, data in REGION_CONFIG.items()]

# Українська назва міста, що дало ім'я району з каналом. У довіднику вище її
# немає: там 'name' - це район ("Харківський район"), а 'display_name' -
# латиниця для службових написів. Форма помилки питає саме місто: людина живе
# в Харкові, а не в Харківському районі, і шукає в підказці "Харків".
#
# Ключі збігаються з BROADCAST_DISTRICTS - тобто це рівно ті міста, куди йде
# сповіщення. За відповідністю стежить тест: новий канал без назви міста
# з'явився б у розсилці, але не в підказці.
BROADCAST_CITIES = {
    'bilatserkva':    'Біла Церква',
    'bucha':          'Буча',
    'cherkasy':       'Черкаси',
    'chernihiv':      'Чернігів',
    'chernivtsi':     'Чернівці',
    'dnipro':         'Дніпро',
    'fastiv':         'Фастів',
    'ivanofrankivsk': 'Івано-Франківськ',
    'izmail':         'Ізмаїл',
    'kamianske':      "Кам'янське",
    'kharkiv':        'Харків',
    'kherson':        'Херсон',
    'khmelnytskyi':   'Хмельницький',
    'kovel':          'Ковель',
    'kremenchuk':     'Кременчук',
    'kropyvnytskyi':  'Кропивницький',
    'kryvyirih':      'Кривий Ріг',
    'kyiv':           'Київ',
    'lutsk':          'Луцьк',
    'lviv':           'Львів',
    'mykolaiv':       'Миколаїв',
    'nikopol':        'Нікополь',
    'odesa':          'Одеса',
    'pervomaisk':     'Первомайськ',
    'poltava':        'Полтава',
    'rivne':          'Рівне',
    'sumy':           'Суми',
    'ternopil':       'Тернопіль',
    'uman':           'Умань',
    'uzhhorod':       'Ужгород',
    'vinnytsia':      'Вінниця',
    'zaporizhzhia':   'Запоріжжя',
    'zhytomyr':       'Житомир',
    'zolotonosha':    'Золотоноша',
    'zvenyhorodka':   'Звенигородка',
}
