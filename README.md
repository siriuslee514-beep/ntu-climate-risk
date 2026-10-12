# NTU campus climate screening prototype

这是一个在本地运行的二维 GIS 与天气观测筛查原型。输入是 OpenStreetMap 的 NTU `amenity=university` 多边形、建筑与可步行线，以及 NEA/data.gov.sg 的 S44 Nanyang Avenue 逐分钟气温、相对湿度、风速和 5 分钟累计降雨。天气站是所有网格共享的天气背景；地图没有逐栋建筑实测温度。

## 安装与运行

仓库包含 2026-08-26 至 2026-09-24 的真实原始响应、清洗数据、来源清单和分析产物。克隆后可直接用这份**历史缓存快照**启动页面，不会自动更新天气。推荐 Python 3.12，不要修改系统 Python：

```bash
git clone https://github.com/TTtianTT/ntu-climate-risk.git
cd ntu-climate-risk
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

浏览器打开 `http://localhost:8501`。如果没有 `python3.12` 命令，可使用已安装的 Python 3.12 解释器绝对路径创建 `.venv`。当前机器实测使用 `/opt/anaconda3/bin/python -m venv .venv --system-site-packages` 创建项目环境，所用版本见 `requirements.txt`。

要刷新采样期或从零重建缓存，按顺序执行：

```bash
.venv/bin/python scripts/fetch_data.py --days 7
.venv/bin/python scripts/build_dataset.py
.venv/bin/python scripts/run_analysis.py --config configs/default.yaml
.venv/bin/python scripts/export_figures.py
.venv/bin/python scripts/build_3d.py
.venv/bin/python scripts/update_manifest.py
.venv/bin/python scripts/validate_real_data.py
```

要复现仓库内固定的 30 日快照，可先执行 `.venv/bin/python scripts/fetch_data.py --start 2026-08-26 --end 2026-09-24 --offline`，再运行上面的构建命令（从 `build_dataset.py` 开始）。`--offline` 只读取已提交的真实原始响应。

采集脚本默认使用执行时区 `Asia/Singapore` 的最近完整日；`--days 30` 扩展至 30 天，也可用 `--start YYYY-MM-DD --end YYYY-MM-DD` 固定范围。`build_dataset.py` 默认使用最近一次采集命令的日期选择，也可显式传入相同的 `--start` 与 `--end`，避免把缓存中的其他日期混进样本。`--offline` 只读取已缓存的真实原始响应，不会生成模拟数据；若缺少缓存会报错。可选的 `DATA_GOV_SG_API_KEY` 环境变量只加在请求头，不会写进项目。脚本对请求设置超时、重试、限速和 `Retry-After` 处理。

```bash
.venv/bin/python scripts/fetch_data.py --days 30
.venv/bin/python scripts/fetch_data.py --days 30 --offline
.venv/bin/python -m pytest -q
```

## 页面与产物

- 新增 **Walking routes / 路线经过次数**：基于缓存 OSM 步行路网计算宿舍到 LT／图书馆／食堂的距离最短路径，统计每个网格被不同 OD 路线经过的次数。先运行 `python scripts/build_routes.py`；点位核对、算法定义和完整使用方法见 [ROUTING.md](ROUTING.md)。

- `Overview / Campus map`：本地缓存的 OSM 建筑、步道、校区边界、S44 和 100 m 网格。地图底图默认关闭，矢量与静态回退图来自本地；可选 OSM 在线底图保留归属标注。
- `Weather & Quality`：实际样本时间、各变量小时图与每日覆盖率。最新值显示缓存时间，并非实时。
- `Scenario Explorer`：基于相同观测样本比较 +1/+2°C、降雨 ×1.1/×1.2 和指定网格遮棚改善敏感性情景；展示汇总指标、网格散点比较、两张同色标的 100 m 网格地图和降雨阈值分析，并可下载 JSON/CSV/GeoPackage。蓝框标识假设遮棚改善的网格。
- `Sources & Methods`：逐文件来源、种类、哈希、假设和限制。
- `3D buildings (experimental)`：真实 OSM 轮廓的浏览拉伸。只有极少数实际 `height` 标签，其他高度明确标记为假设；不用于分析。
- `data/raw/`：原始 OSM XML、官方 v1 每日 JSON、v2 最新/分页结构探针；`data/metadata/source_manifest.json` 是可机读来源清单。
- `data/processed/campus.gpkg`：QGIS 图层 `campus`, `buildings`, `walks`, `pois`, `grid`, `stations`；同名 GeoJSON 用于 Web。`observations.parquet`, `hourly_quality.csv`, `daily_quality.csv` 是观测与质量资料。
- `outputs/maps/`：校园图和基线筛查 GeoPackage/GeoJSON；`outputs/figures/`：天气、覆盖率和情景对比 PNG；`outputs/tables/`：对应 CSV、分析摘要与实际情景配置。
- `outputs/maps/dashboard_overview.png`：浏览器中实际打开的 30 天页面截图。

OSM 检索框内的建筑不等于 NTU 资产。图层字段 `inside_campus_osm` 区分校区多边形内外；多边形来自社区绘制，需人工核对。步道 `covered` 缺失单独计量，不当成未覆盖。长度及面积在新加坡 SVY21 米制投影中计算，Web GeoJSON 转回 WGS84。

更多定义、来源和验证状态分别见 [METHODS.md](METHODS.md)、[DATA_SOURCES.md](DATA_SOURCES.md)、[VALIDATION.md](VALIDATION.md)。本项目由 AI 辅助开发；课程使用权限及学术陈述需人工审核。没有写正式课程报告、幻灯片或演讲稿。
