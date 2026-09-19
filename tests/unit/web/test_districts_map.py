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
    # 118 base districts + 3 carved-out raion polygons (nikopol_raion, kharkiv_raion, zaporizhzhia_raion)
    assert len(data["features"]) == len(DISTRICT_CONFIG) + 3

    carved_raions = {"nikopol_raion", "kharkiv_raion", "zaporizhzhia_raion"}
    expected_ids = set(DISTRICT_CONFIG.keys()) | carved_raions
    feature_ids = {feat["properties"]["id"] for feat in data["features"]}
    assert feature_ids == expected_ids

    for feat in data["features"]:
        props = feat["properties"]
        base_id = (
            props["id"].replace("_raion", "") if props["id"].endswith("_raion") else props["id"]
        )
        assert base_id in DISTRICT_CONFIG
        assert props["oblast"] == DISTRICT_CONFIG[base_id]["oblast"]
        assert feat["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert len(feat["geometry"]["coordinates"]) > 0


def test_oblasts_outline_geojson_validity():
    for name in ("oblasts.geojson", "oblasts_outline.geojson"):
        geojson_path = os.path.join("web", "static", "geo", name)
        assert os.path.isfile(geojson_path)

        with open(geojson_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["type"] == "FeatureCollection"
        # 24 oblasts + Kyiv + unified Crimea = 26 regions
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

    # Перевірка через Node.js верстки попапів:
    # 1. Район із каналом (bilatserkva)
    # 2. Район без каналу (obukhiv)
    # 3. Місто-регіон (kyiv) без дублювання заголовка
    # 4. Крим як єдине ціле (crimea) без дублювання заголовка
    # 5. Кальміуський район (kalmiuske) Донецької області
    # 6. Район Луганщини (siverskodonetsk)
    # 7. Відсутність скролбарів та фіксований контейнер district-popup
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

    # Перевірка 1: Район з локальним каналом
    assert '<div class="district-popup-name">Білоцерківський район</div>' in html_with_ch
    assert '<div class="district-popup">' in html_with_ch
    assert 'class="channel-popup-button"' in html_with_ch
    assert "Підписатися на сповіщення" in html_with_ch
    assert "tg://resolve?domain=bilatserkva_alert" in html_with_ch

    # Перевірка 2: Район без локального каналу (отримує загальний канал для єдиного розміру)
    assert '<div class="district-popup-name">Обухівський район</div>' in html_no_ch
    assert '<div class="district-popup">' in html_no_ch
    assert "channel-popup-button" in html_no_ch
    assert "Підписатися на сповіщення" in html_no_ch
    assert "tg://resolve?domain=sirens_live" in html_no_ch

    # Перевірка 3: Місто Київ
    assert '<div class="district-popup-name">Київ</div>' in html_kyiv
    assert "Підписатися на сповіщення" in html_kyiv

    # Перевірка 4: Крим як єдине ціле — тільки "Крим"
    assert '<div class="district-popup-name">Крим</div>' in html_crimea

    # Перевірка 5: Кальміуський район Донеччини
    assert '<div class="district-popup-name">Кальміуський район</div>' in html_kalmiuske

    # Перевірка 6: Район Луганщини
    assert '<div class="district-popup-name">Сіверськодонецький район</div>' in html_siversk

    # Перевірка 7: Жодної підписи областей у попапах
    for h in (html_with_ch, html_no_ch, html_kyiv, html_crimea, html_kalmiuske, html_siversk):
        assert "district-popup-oblast" not in h
        assert "scroller" not in h
        assert "scrollable-content" not in h
        assert "scroller-bar" not in h


def test_css_design_system_typography():
    css_path = Path("web") / "static" / "css" / "districts-map.css"
    content = css_path.read_text(encoding="utf-8")

    # Перевірка: Головний заголовок району оформлено в Inter
    assert ".district-popup-name" in content
    assert "var(--font)" in content

    # Перевірка: Фіксований єдиний розмір поп-апа (310x116px контент, 340x146px обгортка)
    assert "width: 310px" in content
    assert "height: 116px" in content
    assert "340px" in content
    assert "146px" in content
    assert ".district-popup" in content

    # Перевірка: Підвищена контрастність підписів міст завдяки чіткому ореолу
    assert ".map-pin__name" in content
    assert "var(--map-label-halo)" in content
    assert "var(--weight-control)" in content

    # Перевірка: відсутність забороненого filter: brightness
    assert "filter: brightness" not in content
