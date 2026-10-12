"""OSM node-topology shortest paths and distinct OD route counts per grid."""
from __future__ import annotations

import heapq
import math
import re
import xml.etree.ElementTree as ET

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon

from .spatial import METRIC_CRS, WGS84, walkable

CATEGORIES = ("lt", "library", "canteen")


def tags_of(element):
    return {t.get("k"): t.get("v") for t in element.findall("tag")}


def poi_category(tags):
    """Conservative candidates; transport stops and ancillary hall rooms are excluded."""
    name = tags.get("name", "").lower()
    if ("bus_stop" in tags.get("highway", "") or tags.get("public_transport")
            or tags.get("access") in {"no", "private"}):
        return None
    if "faculty housing" in name:
        return None
    if tags.get("residential") == "dormitory" or tags.get("building") == "dormitory":
        return "dormitory"
    if tags.get("amenity") == "library":
        return "library"
    if (tags.get("room") == "lecture_hall" or "lecture theatre" in name
            or "lecture theater" in name or re.fullmatch(r"lt\s*\d+[a-z]?", name)):
        return "lt"
    if tags.get("amenity") in {"food_court", "canteen"} or (
            tags.get("amenity") == "restaurant" and "canteen" in name):
        return "canteen"
    return None


def read_network_and_pois(path, campus):
    """Keep OSM node IDs: geometric crossings alone never create junctions."""
    root = ET.parse(path).getroot()
    project = Transformer.from_crs(WGS84, METRIC_CRS, always_xy=True).transform
    nodes = {e.get("id"): project(float(e.get("lon")), float(e.get("lat")))
             for e in root.findall("node")}
    blocked = {e.get("id") for e in root.findall("node")
               if tags_of(e).get("foot") in {"no", "private"}
               or (tags_of(e).get("access") in {"no", "private"}
                   and tags_of(e).get("foot") not in {"yes", "designated", "permissive"})}
    graph = {}
    for way in root.findall("way"):
        tags = tags_of(way)
        if not walkable(tags) or tags.get("area") == "yes":
            continue
        refs = [n.get("ref") for n in way.findall("nd")]
        direction = tags.get("oneway:foot", "no").lower()
        for u, v in zip(refs, refs[1:]):
            if u not in nodes or v not in nodes or u in blocked or v in blocked:
                continue
            length = math.dist(nodes[u], nodes[v])
            if length <= 0:
                continue
            graph.setdefault(u, {})
            graph.setdefault(v, {})
            if direction != "-1":
                graph[u][v] = min(length, graph[u].get(v, math.inf))
            if direction not in {"yes", "1", "true"}:
                graph[v][u] = min(length, graph[v].get(u, math.inf))
    boundary = campus.to_crs(METRIC_CRS).geometry.union_all()
    candidates, dormitory_areas = [], []
    for e in root:
        tags = tags_of(e)
        category = poi_category(tags)
        if category is None or not tags.get("name") or e.tag not in {"node", "way"}:
            continue
        if e.tag == "node":
            geom = Point(nodes[e.get("id")])
        else:
            refs = [n.get("ref") for n in e.findall("nd")]
            if len(refs) < 4 or refs[0] != refs[-1] or any(n not in nodes for n in refs):
                continue
            polygon = Polygon([nodes[n] for n in refs]).buffer(0)
            geom = polygon.representative_point()
            if category == "dormitory" and tags.get("residential") == "dormitory":
                dormitory_areas.append(polygon)
        if geom.is_empty or not boundary.covers(geom):
            continue
        candidates.append(dict(poi_id=f"{e.tag}/{e.get('id')}", name=tags["name"],
                               category=category, geometry=geom,
                               location_source="OSM node" if e.tag == "node" else "OSM polygon representative point",
                               priority=0 if tags.get("residential") == "dormitory" else 1))
    pois = gpd.GeoDataFrame(candidates, columns=["poi_id", "name", "category", "geometry", "location_source", "priority"],
                           geometry="geometry", crs=METRIC_CRS)
    if not pois.empty:
        # A hall's mapped blocks must not each add another equal-weight origin.
        nested_blocks = pois.apply(lambda row: row.category == "dormitory" and row.priority == 1
                                  and any(area.covers(row.geometry) for area in dormitory_areas), axis=1)
        pois = pois.loc[~nested_blocks].copy()
        pois["name_key"] = pois["name"].str.lower().str.strip()
        pois = pois.sort_values(["priority", "poi_id"]).drop_duplicates(["category", "name_key"])
        pois = pois.drop(columns=["priority", "name_key"]).reset_index(drop=True)
    return graph, {n: nodes[n] for n in graph}, pois


def load_poi_csv(path):
    """Optional complete, reviewed replacement POI list in WGS84."""
    frame = pd.read_csv(path, dtype={"poi_id": str})
    required = {"poi_id", "name", "category", "longitude", "latitude"}
    if not required.issubset(frame.columns):
        raise ValueError(f"POI CSV requires {sorted(required)}")
    if frame[list(required)].isna().any().any() or frame.poi_id.duplicated().any():
        raise ValueError("POIs need non-null values and unique poi_id")
    if not frame.category.isin(("dormitory", *CATEGORIES)).all():
        raise ValueError("category must be dormitory, lt, library or canteen")
    if not (frame.longitude.between(-180, 180) & frame.latitude.between(-90, 90)).all():
        raise ValueError("Invalid WGS84 longitude/latitude")
    frame["location_source"] = "reviewed CSV (user supplied)"
    return gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame.longitude, frame.latitude), crs=WGS84).to_crs(METRIC_CRS)


def dijkstra(graph, source):
    distances, parents, queue = {source: 0.0}, {}, [(0.0, source)]
    while queue:
        distance, u = heapq.heappop(queue)
        if distance != distances[u]:
            continue
        for v, length in sorted(graph[u].items()):
            candidate = distance + length
            if candidate < distances.get(v, math.inf):
                distances[v], parents[v] = candidate, u
                heapq.heappush(queue, (candidate, v))
    return distances, parents


def count_routes(grid, routes):
    """One count per OD per cell, positive length only (not a corner touch)."""
    result = grid.to_crs(METRIC_CRS).copy()
    for category in ("all", *CATEGORIES):
        result["route_count" if category == "all" else f"route_count_{category}"] = 0
    for route in routes.to_crs(METRIC_CRS).itertuples():
        if route.geometry is None or route.geometry.is_empty:
            continue
        for position in result.sindex.query(route.geometry, predicate="intersects"):
            cell = result.geometry.iloc[position]
            if route.geometry.intersection(cell).length > 1e-6:
                idx = result.index[position]
                result.at[idx, "route_count"] += 1
                result.at[idx, f"route_count_{route.category}"] += 1
    result["route_share"] = result.route_count / len(routes) if len(routes) else 0.0
    return result


def route_analysis(graph, nodes, pois, grid, max_snap_m=150.0):
    if not math.isfinite(max_snap_m) or max_snap_m <= 0:
        raise ValueError("max_snap_m must be finite and positive")
    if not nodes:
        raise ValueError("OSM walking network is empty")
    pois = pois.to_crs(METRIC_CRS).copy()
    if pois.poi_id.duplicated().any():
        raise ValueError("Duplicate POI IDs")
    node_ids = sorted(nodes)
    node_points = gpd.GeoSeries([Point(nodes[n]) for n in node_ids], crs=METRIC_CRS)
    snaps, offsets, statuses = [], [], []
    for point in pois.geometry:
        distances = node_points.distance(point)
        position = distances.idxmin()
        offset = float(distances.loc[position])
        snaps.append(node_ids[position])
        offsets.append(offset)
        statuses.append("snapped" if offset <= max_snap_m else "too_far")
    pois["network_node"], pois["snap_distance_m"], pois["snap_status"] = snaps, offsets, statuses
    origins = pois[pois.category == "dormitory"]
    destinations = pois[pois.category.isin(CATEGORIES)]
    records, route_rows = [], []
    for origin in origins.itertuples():
        distances, parents = dijkstra(graph, origin.network_node) if origin.snap_status == "snapped" else ({}, {})
        for destination in destinations.itertuples():
            record = dict(route_id=f"{origin.poi_id}->{destination.poi_id}", origin_id=origin.poi_id,
                          origin_name=origin.name, destination_id=destination.poi_id,
                          destination_name=destination.name, category=destination.category,
                          origin_snap_m=origin.snap_distance_m, destination_snap_m=destination.snap_distance_m,
                          distance_m=None)
            if origin.snap_status != "snapped" or destination.snap_status != "snapped":
                record["status"] = "snap_too_far"
            elif destination.network_node not in distances:
                record["status"] = "unreachable"
            else:
                record["distance_m"] = distances[destination.network_node]
                path = [destination.network_node]
                while path[-1] != origin.network_node:
                    path.append(parents[path[-1]])
                path.reverse()
                record["status"] = "same_node" if len(path) == 1 else "routed"
                geom = Point(nodes[path[0]]) if len(path) == 1 else LineString([nodes[n] for n in path])
                route_rows.append(dict(record, geometry=geom))
            records.append(record)
    columns = ["route_id", "origin_id", "origin_name", "destination_id", "destination_name", "category",
               "origin_snap_m", "destination_snap_m", "distance_m", "status"]
    routes = gpd.GeoDataFrame(route_rows, columns=[*columns, "geometry"], geometry="geometry", crs=METRIC_CRS)
    od = pd.DataFrame(records, columns=columns)
    result = count_routes(grid, routes)
    summary = dict(origins=len(origins), destinations=len(destinations), od_pairs=len(od),
                   destination_categories={c: int((destinations.category == c).sum()) for c in CATEGORIES},
                   status_counts=od.status.value_counts().to_dict(), reachable_pairs=len(routes),
                   visited_cells=int((result.route_count > 0).sum()), max_snap_m=max_snap_m,
                   graph_nodes=len(nodes), directed_edges=sum(map(len, graph.values())),
                   pairing="all dormitories x all destinations; equal OD weights; one shortest path per pair",
                   metric="network distance in EPSG:3414 metres; access connectors excluded",
                   caveat="OSM candidates and nearest-node access require review; counts are not observed footfall")
    return result, routes, od, pois, summary
