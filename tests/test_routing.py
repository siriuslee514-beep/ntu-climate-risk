import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from ntu_climate.routing import count_routes, dijkstra, poi_category, read_network_and_pois, route_analysis
from ntu_climate.spatial import METRIC_CRS


def test_dijkstra_uses_distance_not_fewest_edges():
    graph = {"a": {"b": 10, "c": 2}, "b": {}, "c": {"b": 3}}
    distances, parents = dijkstra(graph, "a")
    assert distances["b"] == 5
    assert parents["b"] == "c"


def test_distinct_routes_count_once_and_corner_touch_excluded():
    grid = gpd.GeoDataFrame({"grid_id": ["a", "b", "c"]},
                            geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(10, 10, 20, 20)], crs=METRIC_CRS)
    routes = gpd.GeoDataFrame({"category": ["lt", "library"]}, geometry=[
        LineString([(1, 1), (12, 1), (1, 2), (10, 10)]), LineString([(2, 2), (3, 3)])], crs=METRIC_CRS)
    result = count_routes(grid, routes)
    assert result.route_count.tolist() == [2, 1, 0]
    assert result.route_count_lt.tolist() == [1, 1, 0]
    assert result.route_share.tolist() == [1, 0.5, 0]


def test_unreachable_far_snap_and_same_node_are_auditable():
    nodes = {"a": (0, 0), "b": (10, 0), "c": (50, 0)}
    graph = {"a": {"b": 10}, "b": {"a": 10}, "c": {}}
    pois = gpd.GeoDataFrame({"poi_id": ["o", "d1", "d2", "d3", "d4"],
                            "name": ["hall", "lt", "lib", "far", "same"],
                            "category": ["dormitory", "lt", "library", "canteen", "lt"]},
                           geometry=[Point(0, 0), Point(10, 0), Point(50, 0), Point(100, 0), Point(0, 0)], crs=METRIC_CRS)
    grid = gpd.GeoDataFrame({"grid_id": ["a"]}, geometry=[box(-1, -1, 20, 20)], crs=METRIC_CRS)
    result, routes, od, _, summary = route_analysis(graph, nodes, pois, grid, max_snap_m=5)
    assert od.status.tolist() == ["routed", "unreachable", "snap_too_far", "same_node"]
    assert len(routes) == 2
    assert result.route_count.tolist() == [1]
    assert result.route_share.tolist() == [0.5]
    assert summary["od_pairs"] == 4
    with pytest.raises(ValueError):
        route_analysis(graph, nodes, pois, grid, max_snap_m=-1)


def test_osm_topology_does_not_connect_grade_crossings_and_honours_foot_direction(tmp_path):
    osm = tmp_path / "test.osm"
    osm.write_text('''<osm>
      <node id="1" lon="103.68" lat="1.345"/><node id="2" lon="103.682" lat="1.347"/>
      <node id="3" lon="103.68" lat="1.347"/><node id="4" lon="103.682" lat="1.345"/>
      <node id="5" lon="103.683" lat="1.347"/>
      <way id="11"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/><tag k="oneway:foot" v="yes"/></way>
      <way id="12"><nd ref="3"/><nd ref="4"/><tag k="highway" v="footway"/></way>
      <way id="13"><nd ref="2"/><nd ref="5"/><tag k="highway" v="footway"/><tag k="foot" v="no"/></way>
    </osm>''')
    campus = gpd.GeoDataFrame(geometry=[box(103.67, 1.33, 103.70, 1.36)], crs="EPSG:4326")
    graph, _, _ = read_network_and_pois(osm, campus)
    distances, _ = dijkstra(graph, "1")
    assert set(distances) == {"1", "2"}
    assert not graph["2"]
    assert "5" not in graph


def test_poi_classification_excludes_bus_stops_and_sports_halls():
    assert poi_category({"name": "Hall 1", "highway": "bus_stop"}) is None
    assert poi_category({"name": "Library", "amenity": "library", "public_transport": "platform"}) is None
    assert poi_category({"name": "Sport Hall", "building": "sports_hall"}) is None
    assert poi_category({"name": "Hall 1", "residential": "dormitory"}) == "dormitory"
    assert poi_category({"name": "LT 12"}) == "lt"
    assert poi_category({"name": "Canteen 4", "amenity": "restaurant"}) == "canteen"


def test_zero_routes_produces_zero_counts():
    grid = gpd.GeoDataFrame({"grid_id": ["a"]}, geometry=[box(0, 0, 10, 10)], crs=METRIC_CRS)
    routes = gpd.GeoDataFrame({"category": []}, geometry=[], crs=METRIC_CRS)
    result = count_routes(grid, routes)
    assert result.route_count.tolist() == [0]
    assert result.route_share.tolist() == [0]


def test_dormitory_blocks_do_not_duplicate_parent_origin(tmp_path):
    osm = tmp_path / "halls.osm"
    osm.write_text('''<osm>
      <node id="1" lon="103.68" lat="1.34"/><node id="2" lon="103.69" lat="1.34"/>
      <node id="3" lon="103.69" lat="1.35"/><node id="4" lon="103.68" lat="1.35"/>
      <node id="5" lon="103.685" lat="1.345"><tag k="building" v="dormitory"/><tag k="name" v="Block 1"/></node>
      <way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
      <tag k="residential" v="dormitory"/><tag k="name" v="Hall 1"/></way>
    </osm>''')
    campus = gpd.GeoDataFrame(geometry=[box(103.67, 1.33, 103.70, 1.36)], crs="EPSG:4326")
    _, _, pois = read_network_and_pois(osm, campus)
    assert pois.name.tolist() == ["Hall 1"]
