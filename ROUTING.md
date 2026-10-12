# 宿舍到 LT／图书馆／食堂的最短路径网格指标

## 运行

安装原有 requirements.txt 后，在项目根目录执行（不需要访问 Overpass，也不需要重新下载天气）：

```bash
python scripts/build_routes.py
python -m streamlit run app.py
```

打开新增的 `Walking routes / 路线经过次数` 标签页，可选择宿舍、目的地类别，查看网格经过次数／比例、叠加最短路线，并下载 CSV。Windows 虚拟环境对应 `.venv\Scripts\python.exe`。

每次更新 OSM、校园边界或网格后，重新运行 `build_routes.py`。新输出存放在独立的 `data/processed/routing/` 下，天气指标与遮棚情景计算保持原有定义。

## 指标定义

起点集合 O 为 OSM 识别到的具名宿舍；终点集合 D 为具名 LT、图书馆、食堂。默认计算全部 O×D 组合，每个 OD 权重为 1。不是只去最近的食堂，也不是所有网络节点之间的介数中心性。

以路段在 EPSG:3414 中的长度作为权重，Dijkstra 为每对可达 OD 选取一条最短路线 P。若存在等长最短路线，按排序后的 OSM 节点顺序确定一条，不拆分权重。

网格 g 的指标为 `C_g = Σ_(o,d) 1[length(P_od ∩ g) > 0]`。

- `route_count`：穿过网格的不同 OD 路线数。同一路线重复进入同一网格只计一次。
- `route_count_lt/library/canteen`：按目的地类别拆分，三类之和等于总次数。
- `route_share`：次数除以当前选择中的可达 OD 对数；没有可达路线时为 0。各网格比例不需要加总为 1。
- 仅接触网格角点不计数。沿两个网格共享边界行走时，两格均计数。判断长度容差为 10⁻⁶ 米。
- 起终点落到同一网络节点的 OD 标记 `same_node`，距离为 0，计入可达分母，但不贡献经过次数。

它衡量的是**假设所有宿舍—目的地组合等权时的路线集中程度**。可与已有热暴露指标并列筛选“热暴露较高且路线集中”的调查区域。没有宿舍人数、课表或实测出行频率，因此不将次数解释为人数，也不直接改写原热暴露指标的单位。

## OSM 路网和点位

直接读取仓库的 `data/raw/osm/ntu_bbox.osm`。沿原始 way 的连续节点建立边；只有共享 OSM 节点才连通，不按线条平面交叉自动连通。复用项目 `walkable` 的道路类型和访问过滤规则，额外排除 `area=yes` 面，遵守 `oneway:foot`，并移除明确禁止步行的节点。普通汽车单行线不自动限制步行方向。保留整个下载框内路网，允许最短路绕行校园边界外，网格次数仅统计现有校园网格。

自动候选点包括：

- 宿舍：具名 `residential=dormitory` 或 `building=dormitory`。
- LT：`room=lecture_hall`、名称含 Lecture Theatre/Theater，或 `LT 数字`。
- 图书馆：`amenity=library`。
- 食堂：`amenity=food_court/canteen`，或带 Canteen 名称的 restaurant。

候选仅取校园多边形内的 node 或闭合 way。排除公交站、公共交通平台、Faculty Housing、明确私有或禁止访问点位。宿舍区域内的单栋宿舍楼不重复作为起点；相同类别同名点位仅留一个，宿舍优先选 residential 区域。其他不同名称的重复映射仍需人工审核。复合宿舍区域按一个起点处理。未展开 multipolygon relation 的 POI，因此候选数量不代表完整设施名录；OSM 未标注的 LT 不会被虚构补齐。

面对象使用米制投影下的内部代表点，点对象使用原坐标。候选点匹配最近路网节点，默认最大距离 150 米（可用 `--max-snap-m` 修改）。这是假设阈值；点位到网络节点的距离写入 `snap_distance_m`。这段接入距离不算作经过验证的步行路线，不加入长度和网格计数。节点匹配可能选到隔墙或不同楼层的路段；OSM 的障碍物、开放时间、条件限制及室内通行资料不完整，结果需要现场或校园地图核验。

## 人工核对与替换点位

导出 `data/processed/routing/route_pois.csv`，逐项核对宿舍、LT、图书馆、食堂，建议改为真实入口坐标。保留或新增列：`poi_id,name,category,longitude,latitude`，其中 category 为 `dormitory/lt/library/canteen`。使用：

```bash
python scripts/build_routes.py --pois reviewed_pois.csv --max-snap-m 100
```

该 CSV **完整替换**自动候选清单，旧的 snap 诊断列会重新计算。自定义清单的研究范围由使用者确认。无法匹配或断开的 OD 不补直线，分别记录为 `snap_too_far` 和 `unreachable`。

## 输出和核验

| 文件 | 内容 |
|---|---|
| grid_routes.geojson / grid_route_counts.csv | 原网格属性及新经过次数、比例 |
| routes.geojson | 可达 OD 路线、距离、类别；同节点 OD 为点 |
| od_routes.csv | 所有尝试的 OD，包括失败状态与两端匹配距离 |
| route_pois.geojson / route_pois.csv | 实际使用的候选点及匹配诊断 |
| routing_summary.json | OD 数量、各类别覆盖、状态计数、输入 SHA-256 和假设 |

运行 `python -m pytest -q` 验证距离权重、重复穿格去重、角点排除、断路、匹配阈值、同节点、零路线、OSM 拓扑和步行单行限制。数据源归属：© OpenStreetMap contributors，ODbL；候选名称、坐标和路网均来自仓库 OSM 缓存或显式提供的复核 CSV。
