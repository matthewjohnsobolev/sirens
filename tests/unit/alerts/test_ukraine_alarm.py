"""
Unit tests for domain.ukraine_alarm (geo resolver, models, and diff engine).
"""

from domain.ukraine_alarm import (
    TargetAlert,
    UkraineAlarmGeoResolver,
    compute_alerts_diff,
    extract_active_threats_by_district,
    normalize_geo_name,
    parse_alert_kind_and_level,
)


def test_normalize_geo_name():
    assert normalize_geo_name("м. Київ") == "київ"
    assert normalize_geo_name("Київська область") == "київська"
    assert normalize_geo_name("Бучанський район") == "бучанський"
    assert normalize_geo_name("Бучанська територіальна громада") == "бучанська"
    assert normalize_geo_name("смт Бородянка") == "бородянка"
    assert normalize_geo_name("") == ""
    assert normalize_geo_name("Кам’янський район") == "кам'янський"


def test_geo_resolver_static_mappings():
    resolver = UkraineAlarmGeoResolver()
    assert resolver.state_id_to_oblast.get("31") == "kyiv"
    assert resolver.state_id_to_oblast.get("14") == "kyiv_oblast"
    assert resolver.state_id_to_oblast.get("9") == "dnipropetrovsk_oblast"
    assert resolver.state_id_to_oblast.get("4") == "vinnytsia_oblast"
    assert resolver.state_id_to_oblast.get("22") == "kharkiv_oblast"
    assert resolver.state_id_to_oblast.get("12") == "zaporizhzhia_oblast"

    districts = resolver.resolve_districts_for_region("id_bucha", "District", "Бучанський район")
    assert districts == ["bucha"]

    districts_khmilnyk = resolver.resolve_districts_for_region(
        "34", "District", "Хмільницький район"
    )
    assert districts_khmilnyk == ["khmilnyk"]

    # Cities: city matches, but district does not trigger city
    assert resolver.resolve_districts_for_region("id_nikopol_city", "Community", "м. Нікополь") == [
        "nikopol"
    ]
    assert (
        resolver.resolve_districts_for_region("id_nikopol_dist", "District", "Нікопольський район")
        == []
    )

    assert resolver.resolve_districts_for_region("id_kharkiv_city", "State", "м. Харків") == [
        "kharkiv"
    ]
    assert (
        resolver.resolve_districts_for_region("id_kharkiv_dist", "District", "Харківський район")
        == []
    )

    assert resolver.resolve_districts_for_region("id_zp_city", "State", "м. Запоріжжя") == [
        "zaporizhzhia"
    ]
    assert (
        resolver.resolve_districts_for_region("id_zp_dist", "District", "Запорізький район") == []
    )


def test_geo_resolver_load_regions_tree():
    resolver = UkraineAlarmGeoResolver()
    payload = {
        "states": [
            {
                "regionId": "14",
                "regionName": "Київська область",
                "regionType": "State",
                "regionChildIds": [
                    {
                        "regionId": "101",
                        "regionName": "Бучанський район",
                        "regionType": "District",
                        "regionChildIds": [
                            {
                                "regionId": "1001",
                                "regionName": "Бучанська територіальна громада",
                                "regionType": "Community",
                            },
                            {
                                "regionId": "1002",
                                "regionName": "Ірпінська територіальна громада",
                                "regionType": "Community",
                            },
                        ],
                    }
                ],
            },
            {
                "regionId": "31",
                "regionName": "м. Київ",
                "regionType": "State",
                "regionChildIds": [],
            },
        ]
    }

    resolver.load_regions_tree(payload)

    assert resolver.resolve_districts_for_region("14", "State") == [
        "bilatserkva",
        "boryspil",
        "brovary",
        "bucha",
        "vyshhorod",
        "obukhiv",
        "fastiv",
    ]
    assert resolver.resolve_districts_for_region("31", "State") == ["kyiv"]

    assert resolver.resolve_districts_for_region("101", "District") == ["bucha"]

    assert resolver.resolve_districts_for_region("1001", "Community") == ["bucha"]
    assert resolver.resolve_districts_for_region("1002", "Community") == ["bucha"]

    assert resolver.resolve_districts_for_region("88888", "Unknown") == []


def test_parse_alert_kind_and_level():

    res1 = parse_alert_kind_and_level({"type": "AIR"})
    assert res1 == TargetAlert("air_raid_alert", None)

    res2 = parse_alert_kind_and_level(
        {
            "type": "AIR",
            "activeAlertLevels": [{"alertLevel": "Red", "reason": "danger"}],
        }
    )
    assert res2 == TargetAlert("air_raid_alert", "red")

    res3 = parse_alert_kind_and_level(
        {
            "type": "AIR",
            "activeAlertLevels": [{"alertLevel": "Yellow"}],
        }
    )
    assert res3 == TargetAlert("air_raid_alert", "yellow")

    res4 = parse_alert_kind_and_level({"type": "ARTILLERY"})
    assert res4 == TargetAlert("threat_of_shelling", None)

    res5 = parse_alert_kind_and_level({"type": "UNKNOWN"})
    assert res5 == TargetAlert("air_raid_alert", None)

    res6 = parse_alert_kind_and_level({"type": "URBAN_FIGHTS"})
    assert res6 == TargetAlert("air_raid_alert", None)

    res7 = parse_alert_kind_and_level({"type": "SOMETHING_ELSE"})
    assert res7 is None


def test_extract_active_threats_by_district():
    resolver = UkraineAlarmGeoResolver()
    resolver.state_id_to_oblast["31"] = "kyiv"
    resolver.district_id_to_district["101"] = "bucha"
    resolver.district_id_to_district["201"] = "nikopol"

    payload = [
        {
            "regionId": "31",
            "regionType": "State",
            "activeAlerts": [{"type": "AIR", "activeAlertLevels": [{"alertLevel": "Red"}]}],
        },
        {
            "regionId": "101",
            "regionType": "District",
            "activeAlerts": [{"type": "AIR", "activeAlertLevels": [{"alertLevel": "Yellow"}]}],
        },
        {
            "regionId": "201",
            "regionType": "District",
            "activeAlerts": [{"type": "ARTILLERY"}],
        },
        {
            "regionId": "999",
            "regionType": "State",
            "activeAlerts": [],
        },
    ]

    threats = extract_active_threats_by_district(payload, resolver)
    assert threats["kyiv"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")
    assert threats["bucha"]["air_raid_alert"] == TargetAlert("air_raid_alert", "yellow")
    assert threats["nikopol"]["threat_of_shelling"] == TargetAlert("threat_of_shelling", None)


def test_compute_alerts_diff():

    prev_state = {
        "bucha": {"air_raid_alert": TargetAlert("air_raid_alert", "yellow")},
        "nikopol": {"threat_of_shelling": TargetAlert("threat_of_shelling", None)},
    }

    curr_state = {
        "bucha": {"air_raid_alert": TargetAlert("air_raid_alert", "red")},
        "kyiv": {"air_raid_alert": TargetAlert("air_raid_alert", "red")},
    }

    to_trigger, to_cancel = compute_alerts_diff(prev_state, curr_state)

    trigger_dict = {d: alert for d, alert in to_trigger}
    assert trigger_dict["kyiv"] == TargetAlert("air_raid_alert", "red")
    assert trigger_dict["bucha"] == TargetAlert("air_raid_alert", "red")

    cancel_dict = {d: (event, prev_lvl) for d, event, prev_lvl in to_cancel}
    assert cancel_dict["nikopol"] == ("threat_of_shelling_cancelled", None)


def test_compute_alerts_diff_all_clear():
    prev_state = {
        "kyiv": {"air_raid_alert": TargetAlert("air_raid_alert", "red")},
    }
    curr_state = {}

    to_trigger, to_cancel = compute_alerts_diff(prev_state, curr_state)
    assert len(to_trigger) == 0
    assert len(to_cancel) == 1
    assert to_cancel[0] == ("kyiv", "air_raid_alert_cancelled", "red")


def test_geo_resolver_recursive_city_or_village():
    resolver = UkraineAlarmGeoResolver()
    payload = {
        "states": [
            {
                "regionId": "10",
                "regionName": "Київська область",
                "regionType": "State",
                "regionChildIds": [
                    {
                        "regionId": "101",
                        "regionName": "Бучанський район",
                        "regionType": "District",
                        "regionChildIds": [
                            {
                                "regionId": "1001",
                                "regionName": "Бучанська територіальна громада",
                                "regionType": "Community",
                                "regionChildIds": [
                                    {
                                        "regionId": "10001",
                                        "regionName": "м. Буча",
                                        "regionType": "CityOrVillage",
                                        "regionChildIds": [
                                            {
                                                "regionId": "100001",
                                                "regionName": "Лісовий район",
                                                "regionType": "CityDistrict",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    resolver.load_regions_tree(payload)
    assert resolver.resolve_districts_for_region("10001", "CityOrVillage") == ["bucha"]
    assert resolver.resolve_districts_for_region("100001", "CityDistrict") == ["bucha"]


def test_extract_active_threats_alert_level_region_id():
    resolver = UkraineAlarmGeoResolver()
    resolver.state_id_to_oblast["10"] = "kyiv_oblast"
    resolver.district_id_to_district["101"] = "bucha"

    payload = [
        {
            "regionId": "10",
            "regionType": "State",
            "regionName": "Київська область",
            "activeAlerts": [
                {
                    "regionId": "101",
                    "regionType": "District",
                    "type": "CUSTOM",
                    "activeAlertLevels": [{"alertLevel": "Red"}],
                }
            ],
        }
    ]
    threats = extract_active_threats_by_district(payload, resolver)
    assert list(threats.keys()) == ["bucha"]
    assert threats["bucha"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")

    payload_info = [
        {
            "regionId": "101",
            "regionType": "District",
            "activeAlerts": [{"type": "INFO"}],
        }
    ]
    threats_info = extract_active_threats_by_district(payload_info, resolver)
    assert len(threats_info) == 0


def test_extract_active_threats_real_world_payload():
    resolver = UkraineAlarmGeoResolver()
    resolver.load_regions_tree(
        {
            "states": [
                {
                    "regionId": "9999",
                    "regionName": "Автономна Республіка Крим",
                    "regionType": "State",
                    "regionChildIds": [],
                },
                {
                    "regionId": "26",
                    "regionName": "Харківська область",
                    "regionType": "State",
                    "regionChildIds": [
                        {
                            "regionId": "250",
                            "regionName": "Лозівський район",
                            "regionType": "District",
                            "regionChildIds": [],
                        },
                        {
                            "regionId": "249",
                            "regionName": "Чугуївський район",
                            "regionType": "District",
                            "regionChildIds": [
                                {
                                    "regionId": "1313",
                                    "regionName": "Вовчанська міська територіальна громада",
                                    "regionType": "Community",
                                }
                            ],
                        },
                    ],
                },
                {
                    "regionId": "9",
                    "regionName": "Дніпропетровська область",
                    "regionType": "State",
                    "regionChildIds": [
                        {
                            "regionId": "47",
                            "regionName": "Нікопольський район",
                            "regionType": "District",
                            "regionChildIds": [
                                {
                                    "regionId": "349",
                                    "regionName": "Марганецька міська територіальна громада",
                                    "regionType": "Community",
                                },
                                {
                                    "regionId": "351",
                                    "regionName": "м. Нікополь та Нікопольська територіальна громада",
                                    "regionType": "Community",
                                },
                            ],
                        }
                    ],
                },
                {
                    "regionId": "4",
                    "regionName": "Вінницька область",
                    "regionType": "State",
                    "regionChildIds": [
                        {
                            "regionId": "34",
                            "regionName": "Хмільницький район",
                            "regionType": "District",
                            "regionChildIds": [
                                {
                                    "regionId": "216",
                                    "regionName": "м. Хмільник та Хмільницька територіальна громада",
                                    "regionType": "Community",
                                }
                            ],
                        }
                    ],
                },
                {
                    "regionId": "1293",
                    "regionName": "м. Харків та Харківська територіальна громада",
                    "regionType": "State",
                    "regionChildIds": [],
                },
                {
                    "regionId": "564",
                    "regionName": "м. Запоріжжя та Запорізька територіальна громада",
                    "regionType": "State",
                    "regionChildIds": [],
                },
            ]
        }
    )

    payload = [
        {
            "regionId": "16",
            "regionType": "State",
            "regionName": "Луганська область",
            "activeAlerts": [
                {
                    "regionId": "16",
                    "regionType": "State",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Red", "reason": ""}],
                }
            ],
        },
        {
            "regionId": "9999",
            "regionType": "State",
            "regionName": "Автономна Республіка Крим",
            "activeAlerts": [
                {
                    "regionId": "9999",
                    "regionType": "State",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Red", "reason": ""}],
                }
            ],
        },
        {
            "regionId": "248",
            "regionType": "District",
            "regionName": "Кременчуцький район",
            "activeAlerts": [
                {
                    "regionId": "248",
                    "regionType": "District",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Yellow", "reason": "БпЛА"}],
                }
            ],
        },
        {
            "regionId": "250",
            "regionType": "District",
            "regionName": "Лозівський район",
            "activeAlerts": [
                {
                    "regionId": "250",
                    "regionType": "District",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Red", "reason": "Ракета"}],
                }
            ],
        },
        {
            "regionId": "349",
            "regionType": "Community",
            "regionName": "Марганецька міська територіальна громада",
            "activeAlerts": [
                {
                    "regionId": "349",
                    "regionType": "Community",
                    "type": "ARTILLERY",
                    "activeAlertLevels": [{"alertLevel": "Red"}],
                }
            ],
        },
        {
            "regionId": "351",
            "regionType": "Community",
            "regionName": "м. Нікополь та Нікопольська територіальна громада",
            "activeAlerts": [
                {
                    "regionId": "351",
                    "regionType": "Community",
                    "type": "ARTILLERY",
                    "activeAlertLevels": [{"alertLevel": "Red"}],
                }
            ],
        },
        {
            "regionId": "1293",
            "regionType": "State",
            "regionName": "м. Харків та Харківська територіальна громада",
            "activeAlerts": [
                {
                    "regionId": "1293",
                    "regionType": "State",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Red"}],
                }
            ],
        },
        {
            "regionId": "34",
            "regionType": "District",
            "regionName": "Хмільницький район",
            "activeAlerts": [
                {
                    "regionId": "34",
                    "regionType": "District",
                    "type": "AIR",
                    "activeAlertLevels": [{"alertLevel": "Yellow"}],
                }
            ],
        },
    ]

    threats = extract_active_threats_by_district(payload, resolver)

    assert "crimea" in threats
    assert threats["crimea"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")

    assert "luhansk" in threats
    assert threats["luhansk"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")

    assert "kremenchuk" in threats
    assert threats["kremenchuk"]["air_raid_alert"] == TargetAlert("air_raid_alert", "yellow")

    assert "lozova" in threats
    assert threats["lozova"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")

    assert "nikopol" in threats
    assert threats["nikopol"]["threat_of_shelling"] == TargetAlert("threat_of_shelling", None)

    assert "kharkiv" in threats
    assert threats["kharkiv"]["air_raid_alert"] == TargetAlert("air_raid_alert", "red")

    assert "khmilnyk" in threats
    assert threats["khmilnyk"]["air_raid_alert"] == TargetAlert("air_raid_alert", "yellow")
