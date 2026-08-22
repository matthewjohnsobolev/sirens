"""Довідник форми /report-error: те, з чого малюється сторінка й чим сервер
перевіряє відповідь."""

from config import BROADCAST_CITIES, BROADCAST_DISTRICTS
from web import report_form


def test_cities_are_exactly_the_ones_with_a_channel():
    """Скаржаться на сповіщення, якого чекали, а чекати його можна тільки там,
    де є канал."""
    assert set(report_form.CITIES) == set(BROADCAST_CITIES.values())
    assert len(report_form.CITIES) == len(BROADCAST_DISTRICTS)


def test_cities_follow_the_ukrainian_alphabet():
    """І, Ї, Є в Unicode стоять за «я», тож без власного ключа «Ізмаїл» опинився
    б у кінці списку, а не між «Івано-Франківськом» і «Кам'янським»."""
    assert list(report_form.CITIES) == sorted(
        report_form.CITIES, key=report_form.ukrainian_sort_key
    )
    assert report_form.CITIES.index('Івано-Франківськ') < report_form.CITIES.index('Ізмаїл')
    assert report_form.CITIES.index('Ізмаїл') < report_form.CITIES.index('Київ')
    assert report_form.CITIES.index('Житомир') < report_form.CITIES.index('Івано-Франківськ')


def test_apostrophe_and_hyphen_do_not_move_a_city_in_the_list():
    """«Кам'янське» стоїть там само, де стояло б «Камянське»: розділові знаки
    в ключі не рахуються, інакше вони кидали б місто на початок абетки."""
    assert report_form.ukrainian_sort_key("Кам'янське") == report_form.ukrainian_sort_key(
        'Камянське'
    )
    assert report_form.ukrainian_sort_key('Івано-Франківськ') == report_form.ukrainian_sort_key(
        'ІваноФранківськ'
    )
    assert report_form.CITIES.index("Кам'янське") < report_form.CITIES.index('Київ')


def test_category_names_and_tab_labels_are_distinct_fields():
    """Вкладка підписана коротко, у базу їде повна назва."""
    by_id = {c['id']: c for c in report_form.CATEGORIES}

    assert by_id['map']['tab'] == 'Мапа'
    assert by_id['map']['name'] == 'Мапа тривог'
    assert report_form.CATEGORY_ALIASES['Мапа'] == 'Мапа тривог'


def test_only_the_catch_all_category_has_no_options():
    """Розділ без переліку існує саме для непередбаченого - там суть у коментарі."""
    empty = [c['id'] for c in report_form.CATEGORIES if not c['options']]

    assert empty == ['other']
    assert all(report_form.OPTIONS_BY_CATEGORY[c['name']] == c['options']
               for c in report_form.CATEGORIES)


def test_no_option_belongs_to_two_categories():
    """Однакове формулювання в двох розділах зробило б перевірку неоднозначною."""
    seen = [option for c in report_form.CATEGORIES for option in c['options']]

    assert len(seen) == len(set(seen))


def test_page_config_carries_everything_the_page_draws_itself_from():
    config = report_form.page_config()

    assert config['cities'] == list(report_form.CITIES)
    assert config['sets']['other'] == []
    assert config['categories']['alerts'] == 'Сповіщення'
