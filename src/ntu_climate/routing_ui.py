"""Dashboard panel for OSM OD routing, independent of weather scenarios."""
import json

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from .io import ROOT
from .routing import CATEGORIES, count_routes


def render_routing():
    output = ROOT / "data/processed/routing"
    if not (output / "routing_summary.json").exists():
        st.info("Build the cached OSM route analysis first: python scripts/build_routes.py")
        return
    summary = json.loads((output / "routing_summary.json").read_text(encoding="utf-8"))
    st.subheader("Dormitory → LT / library / canteen")
    st.caption("One distance-shortest OSM walking route per origin–destination pair. Each route counts once per crossed cell. Equal OD weights; not measured pedestrian traffic.")
    st.warning("OSM candidate locations use nodes or polygon representative points, not verified entrances. Nearest-node access, missing indoor links and incomplete POIs require review. Access offsets are excluded from route length and grid counts.")
    st.write(f"{summary['origins']} origins · {summary['destinations']} destinations · "
             f"{summary['reachable_pairs']} / {summary['od_pairs']} reachable OD pairs")
    st.write("Destination coverage:", summary["destination_categories"])
    missing = [c for c in CATEGORIES if not summary["destination_categories"].get(c)]
    if missing:
        st.warning("No mapped destinations for: " + ", ".join(missing))
    grid = gpd.read_file(output / "grid_routes.geojson")
    routes = gpd.read_file(output / "routes.geojson")
    pois = gpd.read_file(output / "route_pois.geojson")
    if pois.empty:
        st.warning("No POI candidates. Supply a reviewed POI CSV and rebuild routes.")
        return
    od = pd.read_csv(output / "od_routes.csv")
    origins = pois.loc[pois.category == "dormitory", ["poi_id", "name"]].set_index("poi_id")["name"].to_dict()
    selected_origins = st.multiselect("Dormitories", list(origins), default=list(origins), format_func=origins.get)
    selected_categories = st.multiselect("Destination categories", list(CATEGORIES), default=list(CATEGORIES))
    if routes.empty:
        st.warning("No reachable routes. Review the POI and OD diagnostics below.")
        selected = routes
    else:
        selected = routes[routes.origin_id.isin(selected_origins) & routes.category.isin(selected_categories)]
    counts = count_routes(grid, selected)
    metric = st.selectbox("Grid colour", ["route_count", "route_share"])
    show_routes = st.checkbox("Overlay selected shortest routes", value=False)
    m = folium.Map(location=[1.348, 103.682], zoom_start=15, tiles=None, control_scale=True)
    if st.checkbox("Online OpenStreetMap basemap", value=False, key="routing_tiles"):
        folium.TileLayer("OpenStreetMap").add_to(m)
    maximum = max(float(counts[metric].max()), 1e-12)
    from branca.colormap import linear
    colours = linear.YlOrRd_09.scale(0, maximum)
    colours.caption = "Distinct OD routes" if metric == "route_count" else "Share of reachable selected OD pairs"
    folium.GeoJson(json.loads(counts.to_crs("EPSG:4326").to_json()), name="Route counts",
                   style_function=lambda f: {"fillColor": colours(f["properties"][metric]), "fillOpacity": 0.65,
                                             "color": "#64748b", "weight": 0.4},
                   tooltip=folium.GeoJsonTooltip(fields=["grid_id", "route_count", "route_count_lt", "route_count_library", "route_count_canteen", "route_share"])).add_to(m)
    colours.add_to(m)
    if show_routes and not selected.empty:
        folium.GeoJson(json.loads(selected.to_crs("EPSG:4326").to_json()), name="Shortest routes",
                       style_function=lambda _: {"color": "#2563eb", "weight": 2, "opacity": 0.5},
                       tooltip=folium.GeoJsonTooltip(fields=["origin_name", "destination_name", "distance_m"])).add_to(m)
    for poi in pois.to_crs("EPSG:4326").itertuples():
        folium.CircleMarker([poi.geometry.y, poi.geometry.x], radius=4,
                            color="#2563eb" if poi.category == "dormitory" else "#15803d",
                            tooltip=f"{poi.name} ({poi.category}); snap {poi.snap_distance_m:.0f} m").add_to(m)
    folium.LayerControl().add_to(m)
    st.caption("OSM © OpenStreetMap contributors · unofficial campus boundary")
    st_folium(m, height=580, returned_objects=[], use_container_width=True, key="routing_map")
    st.dataframe(counts.drop(columns="geometry").sort_values("route_count", ascending=False), use_container_width=True)
    st.download_button("Download selected grid counts", counts.drop(columns="geometry").to_csv(index=False), "grid_route_counts.csv", "text/csv")
    with st.expander("POI candidates and access diagnostics"):
        st.dataframe(pd.read_csv(output / "route_pois.csv"), use_container_width=True)
        st.download_button("Download POI list for review", (output / "route_pois.csv").read_bytes(), "route_pois.csv", "text/csv")
    with st.expander("All OD pairs, including unreachable routes"):
        st.dataframe(od, use_container_width=True)
        st.download_button("Download OD diagnostics", od.to_csv(index=False), "od_routes.csv", "text/csv")
    with st.expander("Reproducibility and assumptions"):
        st.json(summary)
