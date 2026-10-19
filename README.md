# NASA Space Apps 2026 · #9 火点调和 · 起跑包

## 这是什么

第 9 题「Harmonization of MODIS and VIIRS Hot Spots」（难度 Advanced/Intermediate，
方向 Earth Science + Software）的起跑骨架。

题目大意：卫星已经追踪了 20 多年的活动火点，但数据分散在
**MODIS** 和 **VIIRS** 两种传感器上，无法直接比较。挑战要求做一个网页应用，
把两套记录调和成一份**燃烧活动日历**，让应急响应、科学家和土地管理者
查看选定区域的历史火情模式和关键时期。

这个包只搭骨架：**数据抓取 → 校准脚手架 → 展示页面**。48 小时内的
核心模型（真正的交叉校准、燃烧日历）和最终展示由你自己完成。

> 数据来源说明：火点数据来自 NASA FIRMS（免费公开）。
> 包内 `data/sample_fires.csv` 是**合成演示数据**，仅用于离线测试管线，
> 正式作品请用真实 FIRMS 数据。

## 文件

| 文件 | 作用 |
|---|---|
| `fetch_firms.py` | 拉取 NASA FIRMS 的 MODIS C6.1 和 VIIRS 375m 火点 CSV |
| `calibrate.py` | MODIS↔VIIRS 时空匹配＋FRP 对比脚手架（含 48h TODO） |
| `app.py` | Streamlit 展示页骨架：地图＋双传感器并排对比＋TODO 占位 |
| `data/sample_fires.csv` | 50 行合成演示数据（两种传感器） |
| `requirements.txt` | pandas / streamlit / requests / pydeck |

## 运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 拉数据（无 key 会自动用演示数据，不报错）
python fetch_firms.py
# 有免费 FIRMS key 后：
FIRMS_MAP_KEY=你的key python fetch_firms.py --region -125,32,-114,42 --days 3

# 3. 跑校准脚手架
python calibrate.py

# 4. 启动展示页
streamlit run app.py
```

免费 FIRMS MAP_KEY 申请：https://firms.modaps.eosdis.nasa.gov/api/area/
（填邮箱即可，一般即时发放）。

## 48 小时内要做的事

1. **真正的交叉校准**（`calibrate.py` 里标了 `TODO(48h)`）：
   检出效率加权（VIIRS 375m 能看到比 MODIS 1km 更小的火）、
   昼夜过境时间校正、对数回归拟合 FRP 换算关系。
2. **燃烧活动日历**：按选定区域把调和后的 FRP 聚合成日序列，
   画热力日历并标出历史高峰期——这是题目要的核心交付。
3. **区域选择器**：`app.py` 里加框选区域 → 调 `fetch_firms.py --region` 重拉。
4. **展示打磨**：侧栏筛选、图例、英文版界面（评委看英文）。

## 注意事项

- 10 月 28 日官方完整题面公布后，若与此处的题目摘要有出入，以官方题面为准。
- 推送到 GitHub 时只推你新建的仓库，不要动其他仓库。
- 注册、建库、最终提交需要你本人操作。
