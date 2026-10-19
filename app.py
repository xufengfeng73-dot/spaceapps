"""Streamlit skeleton: MODIS / VIIRS hotspot harmonization starter.

Run:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

st.set_page_config(page_title="火点调和 #9 · 起跑版", layout="wide")
st.title("🛰️ MODIS / VIIRS 火点调和 · 起跑版")
st.caption("NASA Space Apps Challenge 2026 · Challenge #9 — burning activity calendar starter")


@st.cache_data
def load_data() -> tuple[pd.DataFrame, str]:
    downloaded = sorted(DATA_DIR.glob("firms_*.csv"))
    if downloaded:
        # merge all downloaded products, tag sensor from filename
        frames = []
        for f in downloaded:
            df = pd.read_csv(f)
            df["sensor"] = "VIIRS" if "VIIRS" in f.name.upper() else "MODIS"
            frames.append(df)
        return pd.concat(frames, ignore_index=True), "live FIRMS download"
    df = pd.read_csv(DATA_DIR / "sample_fires.csv")
    df["sensor"] = df["instrument"].str.upper()
    return df, "bundled demo data (synthetic)"


df, source = load_data()
st.info(f"数据源：{source}（{len(df)} 条火点）")

# ---- sidebar filters ----
st.sidebar.header("筛选")
sensors = st.sidebar.multiselect("传感器", ["MODIS", "VIIRS"], default=["MODIS", "VIIRS"])
conf = st.sidebar.multiselect("置信度", ["l", "n", "h"], default=["l", "n", "h"])
dates = sorted(df["acq_date"].unique())
day_range = st.sidebar.select_slider("日期", options=dates, value=(dates[0], dates[-1]))

f = df[df["sensor"].isin(sensors) & df["confidence"].isin(conf)]
f = f[(f["acq_date"] >= day_range[0]) & (f["acq_date"] <= day_range[1])]

# ---- metrics ----
c1, c2, c3 = st.columns(3)
c1.metric("火点总数", len(f))
c2.metric("MODIS", (f["sensor"] == "MODIS").sum())
c3.metric("VIIRS", (f["sensor"] == "VIIRS").sum())

# ---- main map ----
COLOR = {"MODIS": [255, 80, 40, 180], "VIIRS": [40, 140, 255, 180]}
f = f.copy()
f["color"] = f["sensor"].map(COLOR)
layer = pdk.Layer(
    "ScatterplotLayer", data=f,
    get_position=["longitude", "latitude"],
    get_fill_color="color", get_radius="frp",
    radius_scale=400, radius_min_pixels=3, pickable=True,
)
view = pdk.ViewState(
    latitude=float(f["latitude"].mean()) if len(f) else 20,
    longitude=float(f["longitude"].mean()) if len(f) else 0,
    zoom=4,
)
st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view,
                         tooltip={"text": "{sensor} FRP:{frp}MW {acq_date}"}))
st.caption("🔴 MODIS C6.1　🔵 VIIRS 375m　圆圈大小 ∝ FRP（火点辐射功率）")

# ---- side-by-side comparison ----
st.subheader("传感器并排对比")
left, right = st.columns(2)
for col, sensor in ((left, "MODIS"), (right, "VIIRS")):
    with col:
        st.markdown(f"**{sensor}**")
        sf = f[f["sensor"] == sensor]
        if len(sf):
            v = pdk.ViewState(latitude=float(sf["latitude"].mean()),
                              longitude=float(sf["longitude"].mean()), zoom=5)
            col.pydeck_chart(pdk.Deck(
                layers=[pdk.Layer("ScatterplotLayer", data=sf,
                                  get_position=["longitude", "latitude"],
                                  get_fill_color=COLOR[sensor], get_radius="frp",
                                  radius_scale=400, radius_min_pixels=3)],
                initial_view_state=v))
        else:
            st.write("（无数据）")
        st.caption(f"平均 FRP：{sf['frp'].mean():.1f} MW" if len(sf) else "")

# ---- placeholders for the 48h work ----
with st.expander("⏳ 48 小时内要接的东西（TODO）", expanded=True):
    st.markdown(
        "- **校准后的统一火点序列**：跑 `python calibrate.py`，把匹配对和 FRP 对比接到这里，"
        "替换上面两张并排图为一张调和后的图。\n"
        "- **燃烧活动日历**：按选定区域聚合每日调和 FRP，画出历史火情日历（热力图），"
        "标出关键高峰期。\n"
        "- **区域选择器**：让用户框选感兴趣区域，`fetch_firms.py --region` 按该区域重拉数据。"
    )
