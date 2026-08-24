"""Довідник форми /issue: те, з чого малюється сторінка й чим сервер
перевіряє відповідь."""

from config import BROADCAST_CITIES, BROADCAST_DISTRICTS, DISTRICT_CONFIG
from web import issue


def test_cities_are_exactly_the_ones_with_a_channel():
    """Скаржаться на сповіщення, якого чекали, а чекати його можна тільки там,
    де є канал."""
    assert set(issue.CITIES) == set(BROADCAST_CITIES.values())
    assert len(issue.CITIES) == len(BROADCAST_DISTRICTS)


def test_cities_follow_the_ukrainian_alphabet():
    """І, Ї, Є в Unicode стоять за «я», тож без власного ключа «Ізмаїл» опинився
    б у кінці списку, а не між «Івано-Франківськом» і «Кам'янським»."""
    assert list(issue.CITIES) == sorted(
        issue.CITIES, key=issue.ukrainian_sort_key
    )
    assert issue.CITIES.index('Івано-Франківськ') < issue.CITIES.index('Ізмаїл')
    assert issue.CITIES.index('Ізмаїл') < issue.CITIES.index('Київ')
    assert issue.CITIES.index('Житомир') < issue.CITIES.index('Івано-Франківськ')


def test_districts_contain_every_district_and_follow_alphabet():
    """Довідник районів охоплює всі райони з DISTRICT_CONFIG."""
    assert set(issue.DISTRICTS) == {conf['name'] for conf in DISTRICT_CONFIG.values()}
    assert list(issue.DISTRICTS) == sorted(
        issue.DISTRICTS, key=issue.ukrainian_sort_key
    )
    assert 'Бучанський район' in issue.DISTRICTS
    assert 'м. Київ' in issue.DISTRICTS


def test_apostrophe_and_hyphen_do_not_move_a_city_in_the_list():
    """«Кам'янське» стоїть там само, де стояло б «Камянське»: розділові знаки
    в ключі не рахуються, інакше вони кидали б місто на початок абетки."""
    assert issue.ukrainian_sort_key("Кам'янське") == issue.ukrainian_sort_key(
        'Камянське'
    )
    assert issue.ukrainian_sort_key('Івано-Франківськ') == issue.ukrainian_sort_key(
        'ІваноФранківськ'
    )
    assert issue.CITIES.index("Кам'янське") < issue.CITIES.index('Київ')


def test_category_names_and_tab_labels_are_distinct_fields():
    """Вкладка підписана коротко, далі звернення живе під повною назвою."""
    by_id = {c['id']: c for c in issue.CATEGORIES}

    assert by_id['map']['tab'] == 'Мапа'
    assert by_id['map']['name'] == 'Мапа тривог'
    assert issue.CATEGORY_ALIASES['Мапа'] == 'Мапа тривог'


def test_map_options_match_updated_specification():
    """У мапі залишились дві опції тривоги і додано опцію, що мапа не відкривається."""
    map_options = issue.OPTIONS_BY_CATEGORY['Мапа тривог']
    assert map_options == (
        'Область не підсвічена, хоча тривога є',
        'Область підсвічена, хоча тривоги немає',
        'Мапа не відкривається зовсім',
    )


def test_only_the_catch_all_category_has_no_options():
    """Розділ без переліку існує саме для непередбаченого - там суть у коментарі."""
    empty = [c['id'] for c in issue.CATEGORIES if not c['options']]

    assert empty == ['other']
    assert all(
        issue.OPTIONS_BY_CATEGORY[c['name']] == tuple(o['name'] for o in c['options'])
        for c in issue.CATEGORIES
    )


def test_no_option_belongs_to_two_categories():
    """Однакове формулювання в двох розділах зробило б перевірку неоднозначною."""
    seen = [o['name'] for c in issue.CATEGORIES for o in c['options']]

    assert len(seen) == len(set(seen))


def test_every_choice_carries_an_english_label_for_sentry():
    """Звернення читають у Sentry поруч із рештою подій проєкту - там усе
    англійською, і кирилиця читалась би найгірше з усього."""
    records = (
        list(issue.CATEGORIES)
        + [o for c in issue.CATEGORIES for o in c['options']]
        + list(issue.TIME_OPTIONS)
    )

    assert records, "довідник не має бути порожнім"
    for record in records:
        assert record['en'].strip(), record
        assert record['en'].isascii(), record


def test_sentry_keys_are_stable_ascii_and_unique():
    """Тег тримається за ключ, а не за формулювання: перепишеш український
    рядок - історія групи в Sentry лишиться тією самою. Кирилиця в теґу
    зробила б його непридатним для фільтра."""
    option_keys = [o['key'] for c in issue.CATEGORIES for o in c['options']]
    time_keys = [t['key'] for t in issue.TIME_OPTIONS]
    category_keys = [c['id'] for c in issue.CATEGORIES]

    for keys in (option_keys, time_keys, category_keys):
        assert len(keys) == len(set(keys))
        for key in keys:
            assert key.isascii() and key == key.strip() and ' ' not in key, key

    # 'unspecified' - те, чим сервер підписує відсутній вибір; ключ довідника
    # з таким написом зробив би дві різні події нерозрізнимими.
    assert 'unspecified' not in option_keys + time_keys + category_keys


def test_lookups_cover_every_wording_the_form_can_send():
    """Пошук іде за українським рядком, бо саме він приходить із форми."""
    assert set(issue.CATEGORY_INFO) == {c['name'] for c in issue.CATEGORIES}
    assert set(issue.OPTION_INFO) == {
        o['name'] for c in issue.CATEGORIES for o in c['options']
    }
    assert set(issue.TIME_INFO) == set(issue.TIME_NAMES)
    assert issue.OPTION_INFO['Сповіщення прийшло із запізненням'] == {
        'key': 'late', 'en': 'Notification arrived late',
    }
    assert issue.OPTION_INFO['Сповіщення прийшло двічі поспіль'] == {
        'key': 'duplicate', 'en': 'Notification arrived twice in a row',
    }
    assert issue.OPTION_INFO['Мапа не відкривається зовсім'] == {
        'key': 'map_not_opening', 'en': 'Map does not open at all',
    }
    assert issue.CATEGORY_INFO['Мапа тривог'] == {'key': 'map', 'en': 'Alert map'}


def test_page_config_carries_everything_the_page_draws_itself_from():
    """Сторінці їдуть тільки українські написи: ключі й англійські підписи
    існують для Sentry, і робити їй із ними нема чого."""
    config = issue.page_config()

    assert config['cities'] == list(issue.CITIES)
    assert config['districts'] == list(issue.DISTRICTS)
    assert config['sets']['other'] == []
    assert config['categories']['alerts'] == 'Сповіщення'
    assert config['sets']['alerts'] == list(issue.OPTIONS_BY_CATEGORY['Сповіщення'])
    assert config['time_options'] == ['Щойно', 'Менше години тому', 'Вибрати дату і час']
