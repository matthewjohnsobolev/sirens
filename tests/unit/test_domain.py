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
    """Crimea, Sevastopol, Donetsk, and Luhansk regions remain outside the directory."""
    for region in ("crimea", "sevastopol", "donetsk_oblast", "luhansk_oblast"):
        assert region not in domain.DISTRICTS_BY_OBLAST


def test_domain_region_config_is_the_broadcast_subset():
    """REGION_CONFIG contains exactly the districts that have a broadcast channel."""
    assert set(domain.REGION_CONFIG) == domain.BROADCAST_DISTRICTS
    assert domain.BROADCAST_DISTRICTS <= set(domain.DISTRICT_CONFIG)
    assert set(domain.real_channels) == set(domain.test_channels)
    assert all("display_name" in conf for conf in domain.REGION_CONFIG.values())


def test_domain_broadcast_triggers_keep_the_oblast_name():
    """REGION_CONFIG format is stable: district name plus oblast name."""
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
    """Identical trigger names across two oblasts would make matching ambiguous."""
    owners = {}
    for key, conf in domain.DISTRICT_CONFIG.items():
        for trigger in conf["triggers"]:
            owners.setdefault(trigger, []).append(key)

    assert {t: keys for t, keys in owners.items() if len(keys) > 1} == {}


def test_domain_every_broadcast_district_has_a_city_name():
    """A broadcast district without a city name would send alerts but miss autocomplete suggestions."""
    assert set(domain.BROADCAST_CITIES) == domain.BROADCAST_DISTRICTS
    assert all(name.strip() for name in domain.BROADCAST_CITIES.values())
    assert len(set(domain.BROADCAST_CITIES.values())) == len(domain.BROADCAST_CITIES)


def test_domain_messages_completeness():
    assert "air_raid_alert" in domain.MESSAGES
    assert "air_raid_alert_cancelled" in domain.MESSAGES
    assert "threat_of_shelling" in domain.MESSAGES
    assert "threat_of_shelling_cancelled" in domain.MESSAGES


def test_domain_every_district_has_an_english_name():
    """The two name tables are keyed alike, so /api can never half-label one."""
    assert set(domain.DISTRICT_NAMES_EN) == set(domain.DISTRICT_CONFIG)
    assert len(set(domain.DISTRICT_NAMES_EN.values())) == len(domain.DISTRICT_NAMES_EN)
    assert all(name.isascii() and name.strip() for name in domain.DISTRICT_NAMES_EN.values())
    # Kyiv is the city itself; every other entry is a district.
    assert domain.DISTRICT_NAMES_EN["kyiv"] == "Kyiv"
    assert all(
        name.endswith(" District")
        for key, name in domain.DISTRICT_NAMES_EN.items()
        if key != "kyiv"
    )


def test_domain_regions_cover_every_oblast_a_district_points_at():
    """A district may not name a region /api has no label for."""
    assert set(domain.DISTRICTS_BY_OBLAST) <= set(domain.REGIONS)
    assert all(uk and en for uk, en in domain.REGIONS.values())
    assert len(set(domain.REGIONS.values())) == len(domain.REGIONS)
