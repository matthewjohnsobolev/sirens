"""
Prepare and optimize GeoJSON files for the district-level sirens map experiment.

Takes UN OCHA Ukraine admin boundaries (admin1 and admin2), maps them to
domain.geo.DISTRICT_CONFIG and domain.geo.OBLAST_NAMES, applies Douglas-Peucker
simplification (epsilon ~0.0007 deg ≈ 50m), rounds coordinates to 5 decimal places,
strips unneeded metadata, and writes:
- web/static/geo/districts.geojson
- web/static/geo/oblasts_outline.geojson
"""

import json
import math
import os
import re
import sys

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from domain.geo import DISTRICT_CONFIG, OBLAST_NAMES

POSSIBLE_ADMIN_DIRS = [
    os.path.join(PROJECT_ROOT, "web", "static"),
    r"D:\Projects\Code\Sirens\sirens\web\static",
]


def find_file(filename: str) -> str:
    for d in POSSIBLE_ADMIN_DIRS:
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    raise FileNotFoundError(f"Cannot find {filename} in {POSSIBLE_ADMIN_DIRS}")


def point_line_distance(p, start, end):
    if start == end:
        return math.hypot(p[0] - start[0], p[1] - start[1])
    n = abs(
        (end[1] - start[1]) * p[0]
        - (end[0] - start[0]) * p[1]
        + end[0] * start[1]
        - end[1] * start[0]
    )
    d = math.hypot(end[1] - start[1], end[0] - start[0])
    return n / d


def rdp(points, epsilon):
    if len(points) < 4:
        return points
    is_closed = points[0] == points[-1]
    dmax = 0.0
    index = 0
    end = len(points) - 1
    for i in range(1, end):
        d = point_line_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d
    if dmax > epsilon:
        rec1 = rdp(points[: index + 1], epsilon)
        rec2 = rdp(points[index:], epsilon)
        res = rec1[:-1] + rec2
    else:
        res = [points[0], points[end]]
    if is_closed and len(res) < 4:
        return points
    return res


def round_coords(coords, decimals=5):
    if isinstance(coords, (int, float)):
        return round(coords, decimals)
    if isinstance(coords, list):
        return [round_coords(c, decimals) for c in coords]
    return coords


def simplify_geometry(geom, epsilon=0.00025):
    gtype = geom["type"]
    coords = geom["coordinates"]
    if gtype == "Polygon":
        new_coords = []
        for r in coords:
            sr = rdp(r, epsilon)
            new_coords.append(round_coords(sr if len(sr) >= 4 else r))
        return {"type": "Polygon", "coordinates": new_coords}
    elif gtype == "MultiPolygon":
        new_coords = []
        for poly in coords:
            s_poly = []
            for r in poly:
                sr = rdp(r, epsilon)
                s_poly.append(round_coords(sr if len(sr) >= 4 else r))
            if s_poly:
                new_coords.append(s_poly)
        return {"type": "MultiPolygon", "coordinates": new_coords}
    return geom


def map_admin1_to_oblast_id(adm1_pcode: str, adm1_name: str) -> str | None:
    pcode_map = {
        "UA01": "crimea",
        "UA05": "vinnytsia_oblast",
        "UA07": "volyn_oblast",
        "UA12": "dnipropetrovsk_oblast",
        "UA14": "donetsk_oblast",
        "UA18": "zhytomyr_oblast",
        "UA21": "zakarpattia_oblast",
        "UA23": "zaporizhzhia_oblast",
        "UA26": "ivanofrankivsk_oblast",
        "UA32": "kyiv_oblast",
        "UA35": "kirovohrad_oblast",
        "UA44": "luhansk_oblast",
        "UA46": "lviv_oblast",
        "UA48": "mykolaiv_oblast",
        "UA51": "odesa_oblast",
        "UA53": "poltava_oblast",
        "UA56": "rivne_oblast",
        "UA59": "sumy_oblast",
        "UA61": "ternopil_oblast",
        "UA63": "kharkiv_oblast",
        "UA65": "kherson_oblast",
        "UA68": "khmelnytskyi_oblast",
        "UA71": "cherkasy_oblast",
        "UA73": "chernivtsi_oblast",
        "UA74": "chernihiv_oblast",
        "UA80": "kyiv",
        "UA85": "sevastopol",
    }
    return pcode_map.get(adm1_pcode)


def match_district_key(props: dict, matched_keys: set) -> str | None:
    name_uk = props.get("adm2_name1", "").strip()
    name_en = props.get("adm2_name", "").strip()

    if "Шептицький" in name_uk or "Sheptytskyi" in name_en:
        if "chervonohrad" not in matched_keys and "chervonohrad" in DISTRICT_CONFIG:
            return "chervonohrad"

    clean_uk = re.sub(r"\s*(район|міськрада|місто)\s*", "", name_uk, flags=re.I).strip()

    for k, v in DISTRICT_CONFIG.items():
        if k in matched_keys:
            continue
        v_name = v["name"]
        if clean_uk in v_name or v_name.startswith(clean_uk):
            return k
        if any(clean_uk in alias or alias in clean_uk for alias in v.get("aliases", [])):
            return k
        slug = re.sub(r"[^a-z]", "", name_en.lower())
        if slug == k.lower():
            return k

    return None


def prepare_districts(admin1_path: str, admin2_path: str, admin3_path: str) -> dict:
    with open(admin1_path, encoding="utf-8") as f:
        admin1_data = json.load(f)
    with open(admin2_path, encoding="utf-8") as f:
        admin2_data = json.load(f)
    with open(admin3_path, encoding="utf-8") as f:
        admin3_data = json.load(f)

    a1_by_pcode = {f["properties"]["adm1_pcode"]: f for f in admin1_data.get("features", [])}
    a2_by_pcode = {f["properties"]["adm2_pcode"]: f for f in admin2_data.get("features", [])}
    a3_by_pcode = {f["properties"]["adm3_pcode"]: f for f in admin3_data.get("features", [])}

    if "UA3200" in a2_by_pcode and "UA3210" in a2_by_pcode:
        vyshhorod_geom = shape(a2_by_pcode["UA3210"]["geometry"])
        chernobyl_geom = shape(a2_by_pcode["UA3200"]["geometry"])
        merged_vyshhorod = unary_union([vyshhorod_geom, chernobyl_geom])
        a2_by_pcode["UA3210"]["geometry"] = mapping(merged_vyshhorod)
        del a2_by_pcode["UA3200"]
        print(
            "Successfully merged Chernobyl Exclusion Zone (UA3200) into Vyshhorodskyi district (UA3210)"
        )

    carve_cities = [
        {
            "city_id": "nikopol",
            "city_name": "Нікополь",
            "city_display": "Nikopol",
            "raion_id": "nikopol_raion",
            "raion_name": "Нікопольський район",
            "raion_display": "Nikopol Raion",
            "oblast": "dnipropetrovsk_oblast",
            "adm2_pcode": "UA1208",
            "adm3_pcode": "UA1208005",
        },
        {
            "city_id": "kharkiv",
            "city_name": "Харків",
            "city_display": "Kharkiv",
            "raion_id": "kharkiv_raion",
            "raion_name": "Харківський район",
            "raion_display": "Kharkiv Raion",
            "oblast": "kharkiv_oblast",
            "adm2_pcode": "UA6312",
            "adm3_pcode": "UA6312027",
        },
        {
            "city_id": "zaporizhzhia",
            "city_name": "Запоріжжя",
            "city_display": "Zaporizhzhia",
            "raion_id": "zaporizhzhia_raion",
            "raion_name": "Запорізький район",
            "raion_display": "Zaporizhzhia Raion",
            "oblast": "zaporizhzhia_oblast",
            "adm2_pcode": "UA2306",
            "adm3_pcode": "UA2306007",
        },
    ]

    matched_keys = set()
    out_features = []

    for item in carve_cities:
        a2_feat = a2_by_pcode.get(item["adm2_pcode"])
        a3_feat = a3_by_pcode.get(item["adm3_pcode"])
        if a2_feat and a3_feat:
            district_geom = shape(a2_feat["geometry"])
            city_geom = shape(a3_feat["geometry"])
            raion_geom = district_geom.difference(city_geom)

            out_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": item["city_id"],
                        "name": item["city_name"],
                        "display_name": item["city_display"],
                        "oblast": item["oblast"],
                        "is_city": True,
                        "adm3_pcode": item["adm3_pcode"],
                    },
                    "geometry": mapping(city_geom),
                }
            )

            out_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": item["raion_id"],
                        "name": item["raion_name"],
                        "display_name": item["raion_display"],
                        "oblast": item["oblast"],
                        "is_city": False,
                        "adm2_pcode": item["adm2_pcode"],
                    },
                    "geometry": mapping(raion_geom),
                }
            )

            matched_keys.add(item["city_id"])
            del a2_by_pcode[item["adm2_pcode"]]
            print(f"Successfully carved out city {item['city_id']} from {item['raion_id']}")

    if "UA01" in a1_by_pcode and "UA85" in a1_by_pcode:
        c_geom = shape(a1_by_pcode["UA01"]["geometry"])
        s_geom = shape(a1_by_pcode["UA85"]["geometry"])
        merged_crimea = unary_union([c_geom, s_geom])
        conf = DISTRICT_CONFIG["crimea"]
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": "crimea",
                    "name": conf["name"],
                    "display_name": conf.get("display_name", "Crimea"),
                    "oblast": conf["oblast"],
                    "adm1_pcode": "UA01",
                },
                "geometry": mapping(merged_crimea),
            }
        )
        matched_keys.add("crimea")
        print("Successfully merged Crimea and Sevastopol into unified Crimea feature")

    for feat in a2_by_pcode.values():
        props = feat.get("properties", {})
        district_key = match_district_key(props, matched_keys)
        if not district_key:
            continue

        matched_keys.add(district_key)
        conf = DISTRICT_CONFIG[district_key]

        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": district_key,
                    "name": conf["name"].replace("м. ", ""),
                    "display_name": conf.get("display_name", district_key),
                    "oblast": conf["oblast"],
                    "adm2_pcode": props.get("adm2_pcode"),
                },
                "geometry": feat["geometry"],
            }
        )

    missing = set(DISTRICT_CONFIG.keys()) - matched_keys
    if missing:
        print(f"Warning: {len(missing)} districts not matched: {missing}", file=sys.stderr)
    else:
        print(f"Successfully matched all {len(matched_keys)} districts!")

    return {
        "type": "FeatureCollection",
        "features": out_features,
    }


def main():
    admin1_file = find_file("ukr_admin1.geojson")
    admin2_file = find_file("ukr_admin2.geojson")
    admin3_file = find_file("ukr_admin3.geojson")
    print(f"Reading admin1 from: {admin1_file}")
    print(f"Reading admin2 from: {admin2_file}")
    print(f"Reading admin3 from: {admin3_file}")

    geo_out_dir = os.path.join(PROJECT_ROOT, "web", "static", "geo")
    os.makedirs(geo_out_dir, exist_ok=True)

    districts_fc = prepare_districts(admin1_file, admin2_file, admin3_file)
    raw_temp_path = os.path.join(geo_out_dir, "_raw_temp_districts.geojson")
    districts_path = os.path.join(geo_out_dir, "districts.geojson")

    with open(raw_temp_path, "w", encoding="utf-8") as f:
        json.dump(districts_fc, f, ensure_ascii=False)

    import subprocess

    cmd = [
        "npx",
        "--yes",
        "mapshaper",
        raw_temp_path,
        "-snap",
        "0.0001",
        "-clean",
        "-simplify",
        "12%",
        "keep-shapes",
        "-o",
        districts_path,
        "format=geojson",
        "precision=0.00001",
    ]
    print("Running topology-preserving simplification via mapshaper...")
    subprocess.run(cmd, check=True, shell=True)
    if os.path.exists(raw_temp_path):
        os.remove(raw_temp_path)

    print(
        f"Wrote districts GeoJSON to {districts_path} ({os.path.getsize(districts_path) / 1024 / 1024:.2f} MB)"
    )

    oblasts_path = os.path.join(geo_out_dir, "oblasts_outline.geojson")
    raw_dissolve_cmd = [
        "npx",
        "--yes",
        "mapshaper",
        districts_path,
        "-dissolve",
        "oblast",
        "-o",
        oblasts_path,
        "format=geojson",
        "precision=0.00001",
    ]
    print("Dissolving districts to generate seamless oblast boundaries...")
    subprocess.run(raw_dissolve_cmd, check=True, shell=True)

    with open(oblasts_path, encoding="utf-8") as f:
        dissolved_data = json.load(f)

    existing_obl_ids = set()
    for feat in dissolved_data.get("features", []):
        obl_id = feat["properties"].get("oblast") or feat["properties"].get("id")
        feat["properties"]["id"] = obl_id
        feat["properties"]["name"] = OBLAST_NAMES.get(obl_id, obl_id)
        existing_obl_ids.add(obl_id)

    with open(admin1_file, encoding="utf-8") as f:
        admin1_data = json.load(f)

    for a1_feat in admin1_data.get("features", []):
        p = a1_feat.get("properties", {})
        oid = map_admin1_to_oblast_id(p.get("adm1_pcode"), p.get("adm1_name"))
        if oid and oid in OBLAST_NAMES and oid not in existing_obl_ids:
            if oid == "sevastopol" and "crimea" in existing_obl_ids:
                continue
            dissolved_data["features"].append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": oid,
                        "name": OBLAST_NAMES.get(oid, p.get("adm1_name1", oid)),
                    },
                    "geometry": simplify_geometry(a1_feat["geometry"], epsilon=0.00025),
                }
            )
            existing_obl_ids.add(oid)

    with open(oblasts_path, "w", encoding="utf-8") as f:
        json.dump(dissolved_data, f, ensure_ascii=False, separators=(",", ":"))

    print(
        f"Wrote dissolved oblasts outline GeoJSON to {oblasts_path} ({os.path.getsize(oblasts_path) / 1024 / 1024:.2f} MB)"
    )


if __name__ == "__main__":
    main()
