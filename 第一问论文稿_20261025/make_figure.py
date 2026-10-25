"""Generate the figure used by main.tex from the verified Q1 result table."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "第一问重做_20261025/deps"))
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "第一问重做_20261025/结果/10_五项描述性关联特征.csv"
DEST = HERE / "images/q1_signed_effect.png"
DEST.parent.mkdir(exist_ok=True)

data = pd.read_csv(SOURCE).sort_values("rank")
labels = ["浅层含水率24h变化", "72h累计降水", "水汽压亏缺", "下行长波辐射", "气压"]
values = data["signed_delta"].to_numpy()
font = FontProperties(fname="C:/Windows/Fonts/msyh.ttc", size=10)

fig, ax = plt.subplots(figsize=(7.2, 2.55), dpi=220)
colors = ["#227C95" if value < 0 else "#CF7040" for value in values]
ax.barh(range(5), values, color=colors, height=.58)
ax.axvline(0, color="#454545", linewidth=.85)
ax.set_yticks(range(5), labels, fontproperties=font)
ax.invert_yaxis()
ax.set_xlim(-1.04, .55)
ax.set_xticks([-1, -.5, 0, .5])
ax.tick_params(axis="x", labelsize=9, length=0)
ax.tick_params(axis="y", length=0)
ax.spines[["top", "right", "left"]].set_visible(False)
ax.spines["bottom"].set_color("#BBBBBB")
ax.grid(axis="x", color="#E9E9E9", linewidth=.65)
ax.set_axisbelow(True)
ax.set_xlabel("有向秩差（左：事件偏低；右：事件偏高）", fontproperties=font, labelpad=5)
for idx, value in enumerate(values):
    ax.text(value + .025, idx, f"{value:+.3f}",
            ha="left", va="center", fontsize=9,
            color="white" if value < 0 else "#333333")
fig.subplots_adjust(left=.285, right=.965, top=.985, bottom=.25)
fig.savefig(DEST, dpi=220, facecolor="white")
print(DEST)
