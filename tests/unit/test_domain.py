import domain


def test_domain_districts_by_oblast_covers_every_district():
    assert set(domain.DISTRICTS_BY_OBLAST["cherkasy_oblast"]) == {
        "cherkasy",
        "zvenyhorodka",
        "zolotonosha",
        "uman",
    }
    assert set(domain.DISTRICTS_BY_OBLAST["kyiv_oblast"]) == {
        "bilatserkva",
        "boryspil",
        "brovary",
        "bucha",
        "vyshhorod",
        "obukhiv",
        "fastiv",
    }
    assert set(domain.DISTRICTS_BY_OBLAST["lviv_oblast"]) == {
        "lviv",
        "drohobych",
        "zolochiv",
        "sambir",
        "stryi",
        "chervonohrad",
        "yavoriv",
    }
    assert domain.DISTRICTS_BY_OBLAST["kyiv"] == ["kyiv"]
    assert sum(len(d) for d in domain.DISTRICTS_BY_OBLAST.values()) == len(domain.DISTRICT_CONFIG)


def test_domain_occupied_regions_have_no_districts():
    """Крим, Севастополь, Донеччина й Луганщина лишаються поза довідником."""
    for region in ("crimea", "sevastopol", "donetsk_oblast", "luhansk_oblast"):
        assert region not in domain.DISTRICTS_BY_OBLAST


def test_domain_region_config_is_the_broadcast_subset():
    """REGION_CONFIG - рівно ті райони, у яких є канал."""
    assert set(domain.REGION_CONFIG) == domain.BROADCAST_DISTRICTS
    assert domain.BROADCAST_DISTRICTS <= set(domain.DISTRICT_CONFIG)
    assert set(domain.real_channels) == set(domain.test_channels)
    assert all("display_name" in conf for conf in domain.REGION_CONFIG.values())


def test_domain_broadcast_triggers_keep_the_oblast_name():
    """Формат REGION_CONFIG незмінний: назва району плюс назва області."""
    assert domain.REGION_CONFIG["bucha"]["triggers"] == ["Бучанський район", "Київська область"]
    assert domain.DISTRICT_CONFIG["bucha"]["triggers"] == ["Бучанський район"]


def test_domain_triggers_cover_both_apostrophes():
    assert domain.DISTRICT_CONFIG["kamianske"]["triggers"] == [
        "Кам'янський район",
        "Кам\u2019янський район",
    ]
    assert domain.DISTRICT_CONFIG["kupiansk"]["triggers"] == [
        "Куп'янський район",
        "Куп\u2019янський район",
    ]


def test_domain_renamed_districts_keep_their_former_name():
    for key, former in [
        ("zviahel", "Новоград-Волинський район"),
        ("volodymyr", "Володимир-Волинський район"),
        ("samar", "Новомосковський район"),
        ("berestyn", "Красноградський район"),
    ]:
        assert former in domain.DISTRICT_CONFIG[key]["triggers"]


def test_domain_no_trigger_belongs_to_two_districts():
    """Однакова назва в двох областях зробила б зіставлення неоднозначним."""
    owners = {}
    for key, conf in domain.DISTRICT_CONFIG.items():
        for trigger in conf["triggers"]:
            owners.setdefault(trigger, []).append(key)

    assert {t: keys for t, keys in owners.items() if len(keys) > 1} == {}


def test_domain_every_broadcast_district_has_a_city_name():
    """Новий канал без назви міста потрапив би в розсилку, але не в підказку
    на сторінці помилки."""
    assert set(domain.BROADCAST_CITIES) == domain.BROADCAST_DISTRICTS
    assert all(name.strip() for name in domain.BROADCAST_CITIES.values())
    assert len(set(domain.BROADCAST_CITIES.values())) == len(domain.BROADCAST_CITIES)


def test_domain_messages_completeness():
    assert "air_raid_alert" in domain.MESSAGES
    assert "air_raid_alert_cancelled" in domain.MESSAGES
    assert "threat_of_shelling" in domain.MESSAGES
    assert "threat_of_shelling_cancelled" in domain.MESSAGES
