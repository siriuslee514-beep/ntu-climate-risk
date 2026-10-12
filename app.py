"""NTU campus climate screening dashboard. Launch with streamlit run app.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_cache = Path(__file__).resolve().parent / "data/metadata/render_cache"
_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache))

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
import yaml
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.colors import to_hex
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from ntu_climate.analysis import percent_change, rainfall_events, scenario_grid
from ntu_climate.io import ROOT
from ntu_climate.weather import heat_degree_hours

st.set_page_config(page_title="NTU Climate Risk Screening", layout="wide")
st.title("NTU Campus Climate Risk Screening")
st.caption("Real OSM geometry + NEA station observations · Exploratory screening proxy · Hypothetical sensitivity scenarios")


@st.cache_data(show_spinner=False)
def load_data(signature):
    obs = pd.read_parquet(ROOT / "data/processed/observations.parquet")
    hourly = pd.read_csv(ROOT / "data/processed/hourly_quality.csv")
    daily = pd.read_csv(ROOT / "data/processed/daily_quality.csv")
    summary = json.loads((ROOT / "data/processed/summary.json").read_text())
    manifest = json.loads((ROOT / "data/metadata/source_manifest.json").read_text())
    cfg = yaml.safe_load((ROOT / "configs/default.yaml").read_text())
    return obs, hourly, daily, summary, manifest, cfg


@st.cache_data(show_spinner=False)
def load_geojson(name):
    return json.loads((ROOT / f"data/processed/{name}.geojson").read_text())


@st.cache_data(show_spinner=False)
def load_grid():
    return gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="grid")


def shade(value, vmax):
    if value is None or not np.isfinite(value):
        return "#9ca3af"
    if not vmax or vmax <= 0:
        return "#dbeafe"
    r = min(1.0, max(0.0, value / vmax))
    return to_hex(plt.get_cmap("YlOrRd")(0.15 + 0.78 * r))


def campus_map(grid_result, vmax, show_tiles=False, show_walks=True, show_buildings=True,
               height=590, key=None):
    m = folium.Map(location=[1.348, 103.682], zoom_start=15, tiles=None, control_scale=True)
    if show_tiles:
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap © contributors", control=True).add_to(m)
    campus = load_geojson("campus")
    folium.GeoJson(campus, name="OSM university boundary", style_function=lambda _: {"color": "#1d4ed8", "weight": 3, "fillOpacity": 0.02}).add_to(m)
    if show_buildings:
        buildings = load_geojson("buildings")
        buildings["features"] = [f for f in buildings["features"] if f["properties"].get("inside_campus_osm")]
        folium.GeoJson(buildings, name="OSM buildings (inside boundary)",
                       style_function=lambda _: {"color": "#475569", "weight": 0.5, "fillColor": "#64748b", "fillOpacity": 0.28},
                       tooltip=folium.GeoJsonTooltip(fields=["name", "osm_id"], aliases=["Name", "OSM ID"])).add_to(m)
    if show_walks:
        walks = load_geojson("walks")
        walks["features"] = [f for f in walks["features"] if f["properties"].get("inside_campus_osm")]
        colors = {"yes": "#15803d", "no": "#ea580c", "unknown": "#64748b"}
        folium.GeoJson(walks, name="Walkable OSM ways", style_function=lambda f: {
            "color": colors.get(f["properties"]["covered_class"], "#64748b"), "weight": 2.2, "opacity": 0.7},
            tooltip=folium.GeoJsonTooltip(fields=["highway", "covered", "osm_id"], aliases=["Highway", "Covered tag", "OSM ID"])).add_to(m)
    by_id = grid_result.set_index("grid_id")
    geo = load_geojson("grid")
    for f in geo["features"]:
        p = f["properties"]
        row = by_id.loc[p["grid_id"]]
        p["proxy_degC_h_m"] = None if pd.isna(row["proxy_degC_h_m"]) else round(float(row["proxy_degC_h_m"]), 2)
        p["effective_uncovered_m"] = round(float(row["effective_uncovered_m"]), 2)
        p["covered_unknown_pct"] = round(float(p["unknown_fraction"]) * 100, 1)
        p["selected_for_shelter"] = bool(row["selected_for_shelter"])
    folium.GeoJson(geo, name="100 m screening grid", style_function=lambda f: {
        "fillColor": shade(f["properties"]["proxy_degC_h_m"], vmax), "fillOpacity": 0.45,
        "color": "#1d4ed8" if f["properties"]["selected_for_shelter"] else "#334155",
        "weight": 2 if f["properties"]["selected_for_shelter"] else 0.4},
        tooltip=folium.GeoJsonTooltip(fields=["grid_id", "walk_m", "covered_unknown_pct", "effective_uncovered_m", "proxy_degC_h_m"],
                                      aliases=["Grid ID", "Walkway length (m)", "Unknown covered (%)", "Assumed unprotected (m)", "Proxy (°C·h·m)"],
                                      localize=True)).add_to(m)
    stations = load_geojson("stations")
    for f in stations["features"]:
        lon, lat = f["geometry"]["coordinates"]
        folium.CircleMarker([lat, lon], radius=7, color="#1e3a8a", fill=True, fill_color="#60a5fa",
                            tooltip=f"{f['properties']['station_id']} · {f['properties']['name']}").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    m.fit_bounds([[1.3394, 103.6758], [1.3572, 103.6903]])
    st_folium(m, height=height, returned_objects=[], key=key, use_container_width=True)


def static_map(grid, result, vmax, title="Walking heat exposure proxy"):
    fig, ax = plt.subplots(figsize=(6.5, 6.1))
    display = grid.merge(result[["grid_id", "proxy_degC_h_m", "selected_for_shelter"]], on="grid_id")
    if display["proxy_degC_h_m"].notna().any():
        display.plot(column="proxy_degC_h_m", ax=ax, cmap="YlOrRd", vmin=0,
                     vmax=vmax if vmax and vmax > 0 else 1,
                     missing_kwds={"color": "#9ca3af", "label": "Unavailable"},
                     edgecolor="#64748b", linewidth=0.25)
        fig.colorbar(ScalarMappable(norm=Normalize(0, vmax if vmax and vmax > 0 else 1), cmap="YlOrRd"),
                     ax=ax, shrink=0.7, label="°C·h·m")
    else:
        display.plot(ax=ax, color="#9ca3af", edgecolor="#64748b", linewidth=0.25)
        ax.text(0.5, 0.5, "Proxy unavailable: insufficient observations", transform=ax.transAxes,
                ha="center", va="center", bbox={"facecolor": "white", "alpha": 0.9})
    selected = display[display["selected_for_shelter"]]
    if not selected.empty:
        selected.boundary.plot(ax=ax, color="#1d4ed8", linewidth=1.5)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title)
    fig.text(0.02, 0.01, "OSM © contributors · NEA/data.gov.sg · unofficial boundary", fontsize=8)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


try:
    watched = [ROOT / "data/processed/observations.parquet", ROOT / "data/processed/hourly_quality.csv",
               ROOT / "data/processed/daily_quality.csv", ROOT / "data/processed/summary.json",
               ROOT / "data/metadata/source_manifest.json", ROOT / "configs/default.yaml"]
    signature = tuple(p.stat().st_mtime_ns for p in watched)
    obs, hourly, daily, meta, manifest, cfg = load_data(signature)
    grid = load_grid()
except (FileNotFoundError, KeyError, ValueError) as exc:
    st.error(f"Real data unavailable: {exc}. Run fetch_data.py and build_dataset.py. No synthetic fallback is used.")
    st.stop()

date_min, date_max = min(meta["days"]), max(meta["days"])
coverage = len(obs[(obs["variable"] == "temperature") & (~obs["suspect"])]) / (len(meta["days"]) * 1440)
station = meta["station_metadata"].get("temperature", {})
boundary_note = "OSM amenity=university polygon; unofficial boundary, needs field verification"
unknown_share = grid["covered_unknown_m"].sum() / grid["walk_m"].sum()
st.info(f"Observed mode · S44 {station.get('name', 'unknown')} ({date_min} to {date_max}, Asia/Singapore). "
        "Weather is one shared station background, not measured building temperatures. " + boundary_note)

overview, weather_tab, scenarios, sources, buildings_3d, routing_tab = st.tabs(["Overview / Campus map", "Weather & Quality", "Scenario Explorer", "Sources & Methods", "3D buildings (experimental)", "Walking routes / 路线经过次数"])

with routing_tab:
    from ntu_climate.routing_ui import render_routing
    render_routing()

with overview:
    h = heat_degree_hours(obs, cfg["temperature_threshold_c"], expected_days=meta["days"])
    valid_h = h["heat_degree_hours"] if h["coverage"] >= cfg["minimum_coverage"] else None
    base = scenario_grid(grid, valid_h, cfg["q_unknown"])
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Observed sample", f"{len(meta['days'])} complete local dates")
    k2.metric("S44 temperature coverage", f"{coverage:.1%}")
    k3.metric("Walkable OSM ways", f"{meta['spatial_counts']['walks']:,}")
    k4.metric("Grid cells with walkway", f"{len(grid):,}")
    st.caption("Potential unprotected walking heat-exposure proxy = H × (covered=no length + q × covered=unknown length). "
               "q=0.5 is an assumption. Units: °C·h·m. This is not health risk probability or observed pedestrian exposure.")
    st.warning(f"Covered tag is unknown for {unknown_share:.1%} of mapped walking length. Proxy patterns mostly reflect walking length and the q assumption; field verification is needed.")
    map_tiles = st.checkbox("Show online OpenStreetMap basemap", value=False, key="overview_tiles")
    show_walks = st.checkbox("Show walking ways", value=True)
    show_buildings = st.checkbox("Show buildings", value=True)
    try:
        campus_map(base, float(base["proxy_degC_h_m"].max()) if valid_h is not None else None,
                   map_tiles, show_walks, show_buildings, key="overview_map")
    except Exception as exc:
        st.warning(f"Interactive map unavailable: {exc}. Local vector fallback follows.")
    with st.expander("Local vector fallback map"):
        static_map(grid, base, float(base["proxy_degC_h_m"].max()) if valid_h is not None else None)
    selected_id = st.selectbox("Inspect grid cell", grid["grid_id"].tolist())
    st.dataframe(base.loc[base["grid_id"] == selected_id,
                          ["grid_id", "area_m2", "walk_m", "covered_yes_m", "covered_no_m", "covered_unknown_m", "unknown_fraction", "effective_uncovered_m", "proxy_degC_h_m"]],
                 hide_index=True)
    st.caption("OSM © contributors. Gray walking lines mean missing or unrecognized covered tag; missing does not mean uncovered. "
               "Crossing lines on different bridge/tunnel/layer levels are not treated as network connections.")

with weather_tab:
    st.selectbox("Station", ["S44 · Nanyang Avenue"], disabled=True, help="Only S44 is included in this observed-sample build")
    variables = {"temperature": "Air temperature (°C)", "humidity": "Relative humidity (%)", "rainfall": "Rainfall (mm per hour, observed intervals)", "wind_speed": "Wind speed (m/s)"}
    variable = st.selectbox("Observed variable", list(variables), format_func=lambda x: variables[x])
    date_options = sorted(meta["days"])
    d0, d1 = st.select_slider("Local date range", options=date_options, value=(date_options[0], date_options[-1]))
    chart = hourly[(hourly["variable"] == variable) & hourly["local_day"].between(d0, d1)].copy()
    chart["local_time"] = pd.to_datetime(chart["local_day"] + " " + chart["hour"].astype(str).str.zfill(2) + ":00")
    fig = px.line(chart, x="local_time", y="value", title=f"S44 · {variables[variable]} · Asia/Singapore", markers=False,
                  hover_data=["coverage", "status", "valid_count", "expected_count"])
    fig.update_layout(xaxis_title="Local time", yaxis_title=variables[variable])
    st.plotly_chart(fig, use_container_width=True)
    variable_obs = obs[obs["variable"] == variable]
    if not variable_obs.empty:
        latest = variable_obs.sort_values("timestamp").iloc[-1]
        st.caption(f"Latest cached {variable} reading: {latest['timestamp_raw']} · {latest['value']:.2f} {latest['unit']}. Not live.")
    st.subheader("Completeness by local day")
    st.dataframe(daily[daily["variable"] == variable][["station_id", "local_day", "valid_count", "expected_count", "coverage", "status", "value", "unit"]], hide_index=True)
    st.caption("Qualified means ≥80% of expected intervals; this is an engineering threshold. "
               "Partial rainfall sums are marked partial. Missing rainfall is never converted to zero.")
    st.download_button("Download hourly quality CSV", hourly.to_csv(index=False), "hourly_quality.csv", "text/csv")
    st.download_button("Download daily quality CSV", daily.to_csv(index=False), "daily_quality.csv", "text/csv")

with scenarios:
    st.caption("These are self-selected sensitivity scenarios, not official V3 future projections or measured shelter effects.")
    st.warning(f"Covered status is unknown for {unknown_share:.1%} of walking length. q controls a dominant assumption; the selected ten cells are illustrative, not an intervention recommendation.")
    c1, c2, c3, c4 = st.columns(4)
    warming = c1.selectbox("Warming (°C)", [0.0, 1.0, 2.0], index=2)
    rain_mult = c2.selectbox("Rainfall multiplier", [1.0, 1.1, 1.2], index=1)
    q = c3.slider("Unknown covered: assumed uncovered share", 0.0, 1.0, 0.5, 0.05)
    reduction = c4.selectbox("Selected cells: unprotected length reduction", [0.0, 0.25, 0.5], index=1)
    defaults = cfg.get("shelter_grid_ids") or []
    chosen = st.multiselect("Shelter intervention grid IDs", grid["grid_id"].tolist(), default=[x for x in defaults if x in set(grid["grid_id"])])
    heat_base = heat_degree_hours(obs, cfg["temperature_threshold_c"], expected_days=meta["days"])
    heat_scenario = heat_degree_hours(obs, cfg["temperature_threshold_c"], warming, meta["days"])
    valid = heat_base["coverage"] >= cfg["minimum_coverage"]
    baseline = scenario_grid(grid, heat_base["heat_degree_hours"] if valid else None, q)
    changed = scenario_grid(grid, heat_scenario["heat_degree_hours"] if valid else None, q, set(chosen), reduction)
    baseline_q0 = scenario_grid(grid, heat_base["heat_degree_hours"] if valid else None, 0.0)
    baseline_q1 = scenario_grid(grid, heat_base["heat_degree_hours"] if valid else None, 1.0)
    changed_q0 = scenario_grid(grid, heat_scenario["heat_degree_hours"] if valid else None, 0.0, set(chosen), reduction)
    changed_q1 = scenario_grid(grid, heat_scenario["heat_degree_hours"] if valid else None, 1.0, set(chosen), reduction)
    upper = scenario_grid(grid, heat_degree_hours(obs, cfg["temperature_threshold_c"], 2.0, meta["days"])["heat_degree_hours"] if valid else None, q)
    common_max = max(float(upper["proxy_degC_h_m"].max()) if valid else 0,
                     float(changed["proxy_degC_h_m"].max()) if valid else 0)
    total_base = float(baseline["proxy_degC_h_m"].sum()) if valid else None
    total_new = float(changed["proxy_degC_h_m"].sum()) if valid else None
    s1, s2, s3 = st.columns(3)
    s1.metric("Baseline H (°C·h)", f"{heat_base['heat_degree_hours']:.2f}" if valid else "Unavailable")
    s2.metric("Scenario H (°C·h)", f"{heat_scenario['heat_degree_hours']:.2f}" if valid else "Unavailable")
    change = percent_change(total_new, total_base) if valid else None
    s3.metric("Proxy change", f"{change:+.1f}%" if change is not None else "Unavailable / zero baseline")
    if valid:
        st.caption(f"Absolute total proxy: baseline {total_base:,.0f}, scenario {total_new:,.0f} °C·h·m. "
                   f"q=0–1 parameter range: baseline {baseline_q0.proxy_degC_h_m.sum():,.0f}–{baseline_q1.proxy_degC_h_m.sum():,.0f}; "
                   f"scenario {changed_q0.proxy_degC_h_m.sum():,.0f}–{changed_q1.proxy_degC_h_m.sum():,.0f} °C·h·m. "
                   f"Temperature valid coverage {heat_base['coverage']:.1%}; this range is not a confidence interval.")
    else:
        st.warning(f"Proxy unavailable: temperature coverage {heat_base['coverage']:.1%} is below {cfg['minimum_coverage']:.0%}.")
    compare = pd.DataFrame({"grid_id": grid["grid_id"], "baseline_proxy": baseline["proxy_degC_h_m"],
                            "scenario_proxy": changed["proxy_degC_h_m"], "unknown_fraction": grid["unknown_fraction"],
                            "baseline_q0": baseline_q0["proxy_degC_h_m"], "baseline_q1": baseline_q1["proxy_degC_h_m"],
                            "scenario_q0": changed_q0["proxy_degC_h_m"], "scenario_q1": changed_q1["proxy_degC_h_m"]})
    st.plotly_chart(px.scatter(compare, x="baseline_proxy", y="scenario_proxy", hover_name="grid_id",
                               title="Baseline vs sensitivity scenario · same cells and observation mask",
                               labels={"baseline_proxy": "Baseline (°C·h·m)", "scenario_proxy": "Scenario (°C·h·m)"}), use_container_width=True)
    st.caption(f"Common map color scale: 0 to {common_max:,.1f} °C·h·m. q=0 and q=1 define a parameter sensitivity range, not a confidence interval.")
    left, right = st.columns(2)
    with left:
        st.subheader("Baseline")
        static_map(grid, baseline, common_max, "Baseline · local 100 m grid")
    with right:
        st.subheader("Sensitivity scenario")
        static_map(grid, changed, common_max, "Sensitivity scenario · local 100 m grid")
    rain_threshold = st.slider("Observed-hour rainfall threshold (mm/h)", 5.0, 50.0,
                               float(cfg.get("rainfall_event_threshold_mm_h", 20.0)), 1.0)
    rainfall = rainfall_events(obs, [1.0, rain_mult], cfg["minimum_coverage"], rain_threshold)
    if rainfall["status"] == "available":
        st.info(f"Strongest qualified observed hour: {rainfall['strongest_qualified_hour_start']} · "
                f"{rainfall['strongest_qualified_hour_mm']:.1f} mm; ×{rain_mult:g} sensitivity: "
                f"{rainfall['scenarios'][-1]['scaled_mm']:.1f} mm. Observed hour timing and missing intervals unchanged.")
        st.bar_chart(pd.DataFrame({"condition": ["Observed sample", f"Same hours ×{rain_mult:g}"],
                                   "qualified_hours_at_or_above_threshold": [s["qualified_sample_hours_at_or_above_threshold"] for s in rainfall["scenarios"]]}).set_index("condition"))
        st.caption(f"Hours at or above {rain_threshold:g} mm/h in this 30-day sample; scaling can change threshold crossings, "
                   "but this is not a future event frequency or flood probability.")
    else:
        st.warning("Rainfall event analysis unavailable or partial; no flood depth or probability is inferred.")
    config_out = {**cfg, "warming_c_selected": warming, "rainfall_multiplier_selected": rain_mult,
                  "rainfall_event_threshold_mm_h": rain_threshold,
                  "q_unknown": q, "shelter_reduction_selected": reduction, "shelter_grid_ids": chosen,
                  "data_kind": "assumed sensitivity scenario", "observation_period": [date_min, date_max]}
    st.download_button("Download scenario configuration JSON", json.dumps(config_out, indent=2), "scenario_config.json", "application/json")
    st.download_button("Download comparison CSV", compare.to_csv(index=False), "scenario_comparison.csv", "text/csv")
    gpkg = ROOT / "outputs/maps/baseline_proxy.gpkg"
    if gpkg.exists():
        st.download_button("Download baseline QGIS GeoPackage", gpkg.read_bytes(), gpkg.name, "application/geopackage+sqlite3")

with sources:
    st.subheader("Sources and provenance")
    st.dataframe(pd.DataFrame(manifest)[["provider", "data_kind", "variable", "station_id", "unit", "time_range", "row_count", "source_url", "local_path", "sha256", "quality_notes"]], hide_index=True)
    st.markdown("**Observed:** NEA/data.gov.sg weather at S44; OSM community mapped geometry. **Derived:** 100 m spatial grid, quality aggregates, heat degree-hours and proxy. **Assumed:** threshold, unknown shelter share, warming, rain multiplier and shelter intervention. No synthetic data enter the dashboard.")
    st.markdown("**Formula:** H = Σ max(T − T₀, 0) × 1/60 h for valid one-minute S44 observations; T₀ = 30°C by default. Pᵢ = H × [L(covered=no) + q × L(covered=unknown)]. The 30°C cutoff is exploratory, not a medical or official alert threshold.")
    st.markdown("The fixed covered tag is incomplete shade evidence. Sheltered paths may still be hot. The proxy has no pedestrian counts, solar radiation, validated health outcome or loss model. Rainfall is only event scaling; no drainage or fine topography supports flood depth/probability. Uniform warming can preserve the spatial ranking.")
    st.markdown("**V3:** [CCRS climate projections](https://ccrs.weather.gov.sg/climate-projections/) links the [V3 visualiser](https://www.mss-int.sg/v3-climate-projections/explore/climate-visualiser/atmospheric-variables/future-changes/time-series), which shows a 1995–2014 baseline, 2080–2099 end-century summary and SSP1-2.6/2-4.5/5-8.5. The [V3 FAQ](https://www.mss-int.sg/v3-climate-projections/faq) describes 8 km and 2 km domains. This prototype imports no V3 numerical value. +1/+2°C and ×1.1/×1.2 rain are self-selected sensitivity scenarios only.")
    st.markdown("OSM © OpenStreetMap contributors ([licence](https://www.openstreetmap.org/copyright)); NEA/data.gov.sg ([Open Data Licence](https://data.gov.sg/open-data-licence)). Validate the mapped boundary, covered tags, station representativeness and course AI policy before formal use.")

with buildings_3d:
    st.caption("Real OSM footprints extruded for browsing only. Heights from OSM height tags where present; otherwise levels × assumed 3.2 m or an assumed 10 m display height. Not official BIM, shadow, wind or flood modelling.")
    path_3d = ROOT / "data/processed/buildings_3d.json"
    if not path_3d.exists():
        st.warning("Optional 3D data unavailable. Run scripts/build_3d.py after the 2D pipeline.")
    else:
        records = json.loads(path_3d.read_text())
        st.caption(f"{len(records)} polygon parts · {sum(x['height_is_assumed'] for x in records)} use an assumed height. Blue: OSM height tag; orange: assumed height.")
        try:
            layer = pdk.Layer("PolygonLayer", data=records, get_polygon="polygon", extruded=True,
                              get_elevation="display_height_m", elevation_scale=1,
                              get_fill_color="[height_is_assumed ? 230 : 59, height_is_assumed ? 140 : 130, height_is_assumed ? 75 : 246, 190]",
                              get_line_color=[51, 65, 85], pickable=True, auto_highlight=True)
            deck = pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(latitude=1.348, longitude=103.682,
                                                                             zoom=15.5, pitch=50, bearing=25),
                            map_style=None,
                            tooltip={"html": "<b>{name}</b><br/>OSM {osm_id}<br/>{display_height_m} m · {height_source}"})
            st.pydeck_chart(deck, use_container_width=True)
        except Exception as exc:
            st.warning(f"3D preview unavailable: {exc}. The 2D map and exports remain available.")
