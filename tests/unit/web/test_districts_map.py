import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from domain.geo import DISTRICT_CONFIG


def test_main_page_districts_map(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "districts-map.css" in html
    assert "districts-map.js" in html
    assert "https://geo.sirens.live/districts.geojson" in html
    assert "https://geo.sirens.live/oblasts.geojson" in html


def test_districts_geojson_validity():
    geojson_path = os.path.join("web", "static", "geo", "districts.geojson")
    assert os.path.isfile(geojson_path)

    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["type"] == "FeatureCollection"

    assert len(data["features"]) == len(DISTRICT_CONFIG)

    expected_ids = set(DISTRICT_CONFIG.keys())
    feature_ids = {feat["properties"]["id"] for feat in data["features"]}
    assert feature_ids == expected_ids

    for feat in data["features"]:
        props = feat["properties"]
        d_id = props["id"]
        assert d_id in DISTRICT_CONFIG
        assert props["oblast"] == DISTRICT_CONFIG[d_id]["oblast"]
        assert feat["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert len(feat["geometry"]["coordinates"]) > 0


def test_oblasts_outline_geojson_validity():
    for name in ("oblasts.geojson", "oblasts_outline.geojson"):
        geojson_path = os.path.join("web", "static", "geo", name)
        assert os.path.isfile(geojson_path)

        with open(geojson_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["type"] == "FeatureCollection"

        assert len(data["features"]) == 26

    for feat in data["features"]:
        props = feat["properties"]
        assert "id" in props
        assert "name" in props
        assert feat["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert len(feat["geometry"]["coordinates"]) > 0


def test_district_popup_content_rendering_and_styling():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { getDistrictPopupContent } = require('./web/static/js/districts-map.js');
    const { DISTRICT_MARKERS } = require('./web/static/js/districts.js');

    const apiData = {
        kyiv_oblast: {
            title: 'Київська область',
            districts: {
                bilatserkva: {
                    title: 'Білоцерківський район',
                    alert: { status: true, level: 'red', updated_at: 1740000000, source: 'https://t.me/sirens_live/1' }
                },
                obukhiv: {
                    title: 'Обухівський район',
                    alert: { status: false, updated_at: 1740000000 }
                }
            }
        },
        kyiv: {
            title: 'м. Київ',
            districts: {
                kyiv: {
                    title: 'м. Київ',
                    alert: { status: true, level: 'yellow', updated_at: 1740000000 }
                }
            }
        },
        crimea: {
            title: 'Автономна Республіка Крим',
            districts: {
                crimea: {
                    title: 'Автономна Республіка Крим',
                    alert: { status: false }
                }
            }
        },
        donetsk_oblast: {
            title: 'Донецька область',
            districts: {
                kalmiuske: {
                    title: 'Кальміуський район',
                    alert: { status: true, level: 'red', updated_at: 1740000000 }
                }
            }
        },
        luhansk_oblast: {
            title: 'Луганська область',
            districts: {
                siverskodonetsk: {
                    title: 'Сіверськодонецький район',
                    alert: { status: false }
                }
            }
        }
    };

    // 1. Район з Telegram-каналом
    const featWithChannel = {
        properties: { id: 'bilatserkva', name: 'Білоцерківський район', oblast: 'kyiv_oblast' }
    };
    const htmlWithChannel = getDistrictPopupContent(featWithChannel, apiData);

    // 2. Район без Telegram-каналу
    const featWithoutChannel = {
        properties: { id: 'obukhiv', name: 'Обухівський район', oblast: 'kyiv_oblast' }
    };
    const htmlWithoutChannel = getDistrictPopupContent(featWithoutChannel, apiData);

    // 3. Місто-регіон Київ
    const featKyiv = {
        properties: { id: 'kyiv', name: 'Київ', oblast: 'kyiv' }
    };
    const htmlKyiv = getDistrictPopupContent(featKyiv, apiData);

    // 4. Крим як єдине ціле
    const featCrimea = {
        properties: { id: 'crimea', name: 'Крим', oblast: 'crimea' }
    };
    const htmlCrimea = getDistrictPopupContent(featCrimea, apiData);

    // 5. Кальміуський район Донеччини
    const featKalmiuske = {
        properties: { id: 'kalmiuske', name: 'Кальміуський район', oblast: 'donetsk_oblast' }
    };
    const htmlKalmiuske = getDistrictPopupContent(featKalmiuske, apiData);

    // 6. Сіверськодонецький район Луганщини
    const featSiversk = {
        properties: { id: 'siverskodonetsk', name: 'Сіверськодонецький район', oblast: 'luhansk_oblast' }
    };
    const htmlSiversk = getDistrictPopupContent(featSiversk, apiData);

    console.log(JSON.stringify({
        htmlWithChannel,
        htmlWithoutChannel,
        htmlKyiv,
        htmlCrimea,
        htmlKalmiuske,
        htmlSiversk
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())

    html_with_ch = results["htmlWithChannel"]
    html_no_ch = results["htmlWithoutChannel"]
    html_kyiv = results["htmlKyiv"]
    html_crimea = results["htmlCrimea"]
    html_kalmiuske = results["htmlKalmiuske"]
    html_siversk = results["htmlSiversk"]

    assert '<div class="district-popup-name">Білоцерківський район</div>' in html_with_ch
    assert '<div class="district-popup">' in html_with_ch
    assert 'class="channel-popup-button"' in html_with_ch
    assert "Підписатися на сповіщення" in html_with_ch
    assert "tg://resolve?domain=bilatserkva_alert" in html_with_ch

    assert '<div class="district-popup-name">Обухівський район</div>' in html_no_ch
    assert '<div class="district-popup">' in html_no_ch
    assert "channel-popup-button" not in html_no_ch
    assert "Підписатися на сповіщення" not in html_no_ch
    assert "tg://resolve?domain=" not in html_no_ch

    assert '<div class="district-popup-name">Київ</div>' in html_kyiv
    assert "Підписатися на сповіщення" in html_kyiv

    assert '<div class="district-popup-name">Крим</div>' in html_crimea
    assert "channel-popup-button" not in html_crimea
    assert "Підписатися на сповіщення" not in html_crimea

    assert '<div class="district-popup-name">Кальміуський район</div>' in html_kalmiuske
    assert "channel-popup-button" not in html_kalmiuske
    assert "Підписатися на сповіщення" not in html_kalmiuske

    assert '<div class="district-popup-name">Сіверськодонецький район</div>' in html_siversk
    assert "channel-popup-button" not in html_siversk
    assert "Підписатися на сповіщення" not in html_siversk

    for h in (html_with_ch, html_no_ch, html_kyiv, html_crimea, html_kalmiuske, html_siversk):
        assert "district-popup-oblast" not in h
        assert "scroller" not in h
        assert "scrollable-content" not in h
        assert "scroller-bar" not in h


def test_css_design_system_typography():
    css_path = Path("web") / "static" / "css" / "districts-map.css"
    content = css_path.read_text(encoding="utf-8")

    assert ".district-popup-name" in content
    assert "var(--font)" in content

    assert "width: 310px" in content
    assert "height: 116px" in content
    assert "height: 68px" in content
    assert "340px" in content
    assert ".district-popup" in content

    assert ".map-pin__name" in content
    assert "var(--map-label-halo)" in content
    assert "var(--weight-control)" in content

    assert "filter: brightness" not in content

    assert "@media (hover: none)" in content


def test_district_touch_target_scoping():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { findNearbyMarker } = require('./web/static/js/districts-map.js');

    const mockMap = {
        latLngToContainerPoint: (coords) => {
            const lat = Array.isArray(coords) ? coords[0] : coords.lat;
            const lng = Array.isArray(coords) ? coords[1] : coords.lng;
            return { x: lng * 100, y: lat * 100 };
        }
    };

    // Точка поруч із маркером Білої Церкви (49.7968, 30.1311)
    const nearBilatserkva = { lat: 49.7968, lng: 30.1311 };
    const farCoords = { lat: 46.4825, lng: 30.7233 }; // Одеса

    // 1. Клік на районі 'bilatserkva' поруч із маркером знаходить маркер Білої Церкви
    const mSelf = findNearbyMarker(nearBilatserkva, mockMap, 'bilatserkva');

    // 2. Клік на сусідньому районі 'obukhiv' поруч із межею/маркером НЕ чіпляє маркер Білої Церкви
    const mNeighbor = findNearbyMarker(nearBilatserkva, mockMap, 'obukhiv');

    // 3. Клік далеко від маркера повертає null
    const mFar = findNearbyMarker(farCoords, mockMap, 'bilatserkva');

    console.log(JSON.stringify({
        selfDistrict: mSelf ? mSelf.district : null,
        neighborDistrict: mNeighbor ? mNeighbor.district : null,
        farDistrict: mFar ? mFar.district : null
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())
    assert results["selfDistrict"] == "bilatserkva"
    assert results["neighborDistrict"] is None
    assert results["farDistrict"] is None


def test_format_duration_days_threshold():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { formatDuration } = require('./web/static/js/districts.js');
    const now = Math.floor(Date.now() / 1000);

    const res13d = formatDuration(now - (13 * 86400 + 5 * 3600));
    const res14d0h = formatDuration(now - (14 * 86400));
    const res14d5h = formatDuration(now - (14 * 86400 + 5 * 3600));
    const res15d = formatDuration(now - (15 * 86400 + 3 * 3600));
    const res30d = formatDuration(now - (30 * 86400 + 12 * 3600));

    console.log(JSON.stringify({ res13d, res14d0h, res14d5h, res15d, res30d }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())
    assert results["res13d"] == "13 дн 5 год"
    assert results["res14d0h"] == "14 дн"
    assert results["res14d5h"] == "14 дн"
    assert results["res15d"] == "15 дн"
    assert results["res30d"] == "30 дн"


def test_threat_priority_and_stroke_order():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { getDistrictState, pinState, STROKE_ORDER, PIN_STATES } = require('./web/static/js/districts-map.js');

    const redAndShelling = {
        alert: { status: true, level: 'red' },
        shelling: { status: true }
    };
    const s1 = getDistrictState({ d1: { districts: { sub1: redAndShelling } } }, 'd1', 'sub1');
    const p1 = pinState(redAndShelling);

    const yellowAndShelling = {
        alert: { status: true, level: 'yellow' },
        shelling: { status: true }
    };
    const s2 = getDistrictState({ d1: { districts: { sub1: yellowAndShelling } } }, 'd1', 'sub1');
    const p2 = pinState(yellowAndShelling);

    const yellowOnly = {
        alert: { status: true, level: 'yellow' },
        shelling: { status: false }
    };
    const s3 = getDistrictState({ d1: { districts: { sub1: yellowOnly } } }, 'd1', 'sub1');
    const p3 = pinState(yellowOnly);

    const shellingOnly = {
        alert: { status: false },
        shelling: { status: true }
    };
    const s4 = getDistrictState({ d1: { districts: { sub1: shellingOnly } } }, 'd1', 'sub1');
    const p4 = pinState(shellingOnly);

    const idleThreat = {
        alert: { status: false },
        shelling: { status: false }
    };
    const s5 = getDistrictState({ d1: { districts: { sub1: idleThreat } } }, 'd1', 'sub1');
    const p5 = pinState(idleThreat);

    console.log(JSON.stringify({
        s1, p1, s2, p2, s3, p3, s4, p4, s5, p5,
        strokeOrder: STROKE_ORDER,
        pinLifts: {
            idle: PIN_STATES.idle.lift,
            yellow: PIN_STATES.yellow.lift,
            shelling: PIN_STATES.shelling.lift,
            red: PIN_STATES.red.lift
        }
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())
    assert results["s1"] == "red"
    assert results["p1"] == "red"
    assert results["s2"] == "shelling"
    assert results["p2"] == "shelling"
    assert results["s3"] == "yellow"
    assert results["p3"] == "yellow"
    assert results["s4"] == "shelling"
    assert results["p4"] == "shelling"
    assert results["s5"] == "idle"
    assert results["p5"] == "idle"

    so = results["strokeOrder"]
    assert so["idle"] < so["yellow"] < so["shelling"] < so["red"]

    pl = results["pinLifts"]
    assert pl["idle"] < pl["yellow"] < pl["shelling"] < pl["red"]


def test_nikopol_popup_rendering_priority_and_scroller():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { getDistrictPopupContent } = require('./web/static/js/districts-map.js');

    const featNikopol = {
        properties: { id: 'nikopol', name: 'Нікополь', oblast: 'dnipropetrovsk_oblast' }
    };

    const apiDataShellingOnly = {
        dnipropetrovsk_oblast: {
            districts: {
                nikopol: {
                    title: 'Нікополь',
                    alert: { status: false, updated_at: 1740000000 },
                    shelling: { status: true, updated_at: 1740001000 }
                }
            }
        }
    };
    const htmlShelling = getDistrictPopupContent(featNikopol, apiDataShellingOnly);

    const apiDataRedAndShelling = {
        dnipropetrovsk_oblast: {
            districts: {
                nikopol: {
                    title: 'Нікополь',
                    alert: { status: true, level: 'red', updated_at: 1740002000 },
                    shelling: { status: true, updated_at: 1740001000 }
                }
            }
        }
    };
    const htmlRedAndShelling = getDistrictPopupContent(featNikopol, apiDataRedAndShelling);

    const apiDataYellowAndShelling = {
        dnipropetrovsk_oblast: {
            districts: {
                nikopol: {
                    title: 'Нікополь',
                    alert: { status: true, level: 'yellow', updated_at: 1740002000 },
                    shelling: { status: true, updated_at: 1740001000 }
                }
            }
        }
    };
    const htmlYellowAndShelling = getDistrictPopupContent(featNikopol, apiDataYellowAndShelling);

    const apiDataRedOnly = {
        dnipropetrovsk_oblast: {
            districts: {
                nikopol: {
                    title: 'Нікополь',
                    alert: { status: true, level: 'red', updated_at: 1740002000 },
                    shelling: { status: false }
                }
            }
        }
    };
    const htmlRedOnly = getDistrictPopupContent(featNikopol, apiDataRedOnly);

    console.log(JSON.stringify({
        htmlShelling,
        htmlRedAndShelling,
        htmlYellowAndShelling,
        htmlRedOnly
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())

    h1 = results["htmlShelling"]
    assert "container scroller" in h1
    assert "scrollable-content scroller-view" in h1
    assert 'data-state="shelling"' in h1
    assert 'data-state="idle"' in h1
    assert h1.index('data-state="shelling"') < h1.index('data-state="idle"')
    assert h1.index("channel-popup-button") > h1.index('data-state="idle"')

    h2 = results["htmlRedAndShelling"]
    assert "container scroller" in h2
    assert 'data-state="red"' in h2
    assert 'data-state="shelling"' in h2
    assert h2.index('data-state="red"') < h2.index('data-state="shelling"')
    assert h2.index("channel-popup-button") > h2.index('data-state="shelling"')

    h3 = results["htmlYellowAndShelling"]
    assert "container scroller" in h3
    assert 'data-state="shelling"' in h3
    assert 'data-state="yellow"' in h3
    assert h3.index('data-state="shelling"') < h3.index('data-state="yellow"')
    assert h3.index("channel-popup-button") > h3.index('data-state="yellow"')

    h4 = results["htmlRedOnly"]
    assert "container scroller" not in h4
    assert 'data-state="red"' in h4
    assert "channel-popup-button" in h4


def test_marker_popup_opens_raion_except_cities():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { getFeatureForMarker, getMarkerPopupContent, CITY_POPUPS } = require('./web/static/js/districts-map.js');
    const { DISTRICT_MARKERS } = require('./web/static/js/districts.js');

    const mBilatserkva = DISTRICT_MARKERS.find(m => m.district === 'bilatserkva');
    const mLviv = DISTRICT_MARKERS.find(m => m.district === 'lviv');
    const mKharkiv = DISTRICT_MARKERS.find(m => m.district === 'kharkiv');
    const mZaporizhzhia = DISTRICT_MARKERS.find(m => m.district === 'zaporizhzhia');
    const mNikopol = DISTRICT_MARKERS.find(m => m.district === 'nikopol');
    const mKyiv = DISTRICT_MARKERS.find(m => m.district === 'kyiv');

    const featBila = getFeatureForMarker(mBilatserkva);
    const featLviv = getFeatureForMarker(mLviv);
    const featKharkiv = getFeatureForMarker(mKharkiv);
    const featZaporizhzhia = getFeatureForMarker(mZaporizhzhia);
    const featNikopol = getFeatureForMarker(mNikopol);
    const featKyiv = getFeatureForMarker(mKyiv);

    const popupBila = getMarkerPopupContent(mBilatserkva);
    const popupLviv = getMarkerPopupContent(mLviv);
    const popupKharkiv = getMarkerPopupContent(mKharkiv);
    const popupZaporizhzhia = getMarkerPopupContent(mZaporizhzhia);
    const popupNikopol = getMarkerPopupContent(mNikopol);
    const popupKyiv = getMarkerPopupContent(mKyiv);

    console.log(JSON.stringify({
        featBila,
        featLviv,
        featKharkiv,
        featZaporizhzhia,
        featNikopol,
        featKyiv,
        popupBila,
        popupLviv,
        popupKharkiv,
        popupZaporizhzhia,
        popupNikopol,
        popupKyiv
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())

    assert results["featBila"]["properties"]["name"] == "Білоцерківський район"
    assert '<div class="district-popup-name">Білоцерківський район</div>' in results["popupBila"]
    assert "Біла Церква</div>" not in results["popupBila"]

    assert results["featLviv"]["properties"]["name"] == "Львівський район"
    assert '<div class="district-popup-name">Львівський район</div>' in results["popupLviv"]

    assert results["featKharkiv"]["properties"]["name"] == "Харків"
    assert '<div class="district-popup-name">Харків</div>' in results["popupKharkiv"]

    assert results["featZaporizhzhia"]["properties"]["name"] == "Запоріжжя"
    assert '<div class="district-popup-name">Запоріжжя</div>' in results["popupZaporizhzhia"]

    assert results["featNikopol"]["properties"]["name"] == "Нікополь"
    assert '<div class="district-popup-name">Нікополь</div>' in results["popupNikopol"]

    assert results["featKyiv"]["properties"]["name"] == "Київ"
    assert '<div class="district-popup-name">Київ</div>' in results["popupKyiv"]


def test_district_id_aliases_handling():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    test_script = """
    const { getDistrictData, getMarkerThreats, districtPillState } = require('./web/static/js/districts.js');
    const { getDistrictState, getDistrictPopupContent, getFeatureForMarker, findNearbyMarker } = require('./web/static/js/districts-map.js');

    const apiData = {
        dnipropetrovsk_oblast: {
            districts: {
                nikopol: {
                    title: 'Нікополь',
                    alert: { status: true, level: 'red', updated_at: 1740000000 },
                    shelling: { status: true, updated_at: 1740000500 }
                },
                nikopol_district: {
                    title: 'Нікопольський район',
                    alert: { status: true, level: 'yellow', updated_at: 1740001000 }
                }
            }
        },
        zaporizhzhia_oblast: {
            districts: {
                zaporizhzhia: {
                    title: 'Запоріжжя',
                    alert: { status: true, level: 'red', updated_at: 1740000000 }
                },
                zaporizhzhia_district: {
                    title: 'Запорізький район',
                    alert: { status: true, level: 'red', updated_at: 1740002000 }
                }
            }
        },
        lviv_oblast: {
            districts: {
                sheptytskyi: {
                    title: 'Шептицький район',
                    alert: { status: true, level: 'red', updated_at: 1740003000 }
                }
            }
        }
    };

    const d1 = getDistrictData(apiData.dnipropetrovsk_oblast.districts, 'nikopol_raion');
    const d2 = getDistrictData(apiData.dnipropetrovsk_oblast.districts, 'nikopol_district');
    const d3 = getDistrictData(apiData.lviv_oblast.districts, 'chervonohrad');
    const d4 = getDistrictData(apiData.lviv_oblast.districts, 'sheptytskyi');

    const sNikopolRaion = getDistrictState(apiData, 'dnipropetrovsk_oblast', 'nikopol_raion');
    const sZaporizhzhiaRaion = getDistrictState(apiData, 'zaporizhzhia_oblast', 'zaporizhzhia_raion');
    const sSheptytskyiChervonohrad = getDistrictState(apiData, 'lviv_oblast', 'chervonohrad');

    const featNikopolRaion = {
        properties: { id: 'nikopol_raion', name: 'Нікопольський район', oblast: 'dnipropetrovsk_oblast' }
    };
    const htmlNikopolRaion = getDistrictPopupContent(featNikopolRaion, apiData);

    const featZaporizhzhiaRaion = {
        properties: { id: 'zaporizhzhia_raion', name: 'Запорізький район', oblast: 'zaporizhzhia_oblast' }
    };
    const htmlZaporizhzhiaRaion = getDistrictPopupContent(featZaporizhzhiaRaion, apiData);

    const mockMap = {
        latLngToContainerPoint: (coords) => {
            const lat = Array.isArray(coords) ? coords[0] : coords.lat;
            const lng = Array.isArray(coords) ? coords[1] : coords.lng;
            return { x: lng * 100, y: lat * 100 };
        }
    };
    const nearNikopol = { lat: 47.5675, lng: 34.3948 };
    const markerNikopol = findNearbyMarker(nearNikopol, mockMap, 'nikopol_raion');

    console.log(JSON.stringify({
        d1Title: d1 ? d1.title : null,
        d2Title: d2 ? d2.title : null,
        d3Title: d3 ? d3.title : null,
        d4Title: d4 ? d4.title : null,
        sNikopolRaion,
        sZaporizhzhiaRaion,
        sSheptytskyiChervonohrad,
        htmlNikopolRaion,
        htmlZaporizhzhiaRaion,
        markerNikopol: markerNikopol ? markerNikopol.district : null
    }));
    """

    res = subprocess.run(
        [node, "-e", test_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    results = json.loads(res.stdout.strip())

    assert results["d1Title"] == "Нікопольський район"
    assert results["d2Title"] == "Нікопольський район"
    assert results["d3Title"] == "Шептицький район"
    assert results["d4Title"] == "Шептицький район"

    assert results["sNikopolRaion"] == "yellow"
    assert results["sZaporizhzhiaRaion"] == "red"
    assert results["sSheptytskyiChervonohrad"] == "red"

    assert "pill--yellow" in results["htmlNikopolRaion"]
    assert "Жовтий рівень тривоги" in results["htmlNikopolRaion"]
    assert "oblast-description-time" in results["htmlNikopolRaion"]

    assert "pill--red" in results["htmlZaporizhzhiaRaion"]
    assert "Червоний рівень тривоги" in results["htmlZaporizhzhiaRaion"]
    assert "oblast-description-time" in results["htmlZaporizhzhiaRaion"]

    assert results["markerNikopol"] == "nikopol"

