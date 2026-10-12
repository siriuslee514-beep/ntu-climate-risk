#!/usr/bin/env python3
"""Build reproducible OD routes from the cached OSM XML; no API request."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT
from ntu_climate.routing import load_poi_csv, read_network_and_pois, route_analysis
from ntu_climate.spatial import WGS84


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pois", type=Path, help="Reviewed POI CSV replaces automatic OSM candidates")
    parser.add_argument("--max-snap-m", type=float, default=150.0)
    args = parser.parse_args()
    osm = ROOT / "data/raw/osm/ntu_bbox.osm"
    campus_path = ROOT / "data/processed/campus.geojson"
    grid_path = ROOT / "data/processed/grid.geojson"
    graph, nodes, pois = read_network_and_pois(osm, gpd.read_file(campus_path))
    if args.pois:
        pois = load_poi_csv(args.pois)
    grid, routes, od, pois, summary = route_analysis(
        graph, nodes, pois, gpd.read_file(grid_path), args.max_snap_m)
    summary["input_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [osm, campus_path, grid_path] + ([args.pois] if args.pois else [])}
    summary["poi_selection"] = str(args.pois) if args.pois else "automatic OSM node/way candidates; not entrance-verified"
    output = ROOT / "data/processed/routing"
    output.mkdir(parents=True, exist_ok=True)
    for name, frame in [("grid_routes", grid), ("routes", routes), ("route_pois", pois)]:
        (output / f"{name}.geojson").write_text(frame.to_crs(WGS84).to_json(drop_id=True), encoding="utf-8")
    od.to_csv(output / "od_routes.csv", index=False)
    grid.drop(columns="geometry").to_csv(output / "grid_route_counts.csv", index=False)
    poi_table = pois.to_crs(WGS84).copy()
    poi_table["longitude"] = poi_table.geometry.x
    poi_table["latitude"] = poi_table.geometry.y
    poi_table.drop(columns="geometry").to_csv(output / "route_pois.csv", index=False)
    (output / "routing_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
