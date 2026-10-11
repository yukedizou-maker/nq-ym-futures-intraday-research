"""Recreate seven Chinese charts from the published YM result tables.

This visualizes archived outputs; it does not rerun the trading strategy.
"""

import csv
from datetime import datetime
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


BASE = Path(__file__).resolve().parents[1] / "reports" / "ym_sa"
OUT = BASE / "charts" / "zh"
OUT.mkdir(parents=True, exist_ok=True)


def choose_chinese_font():
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in candidates:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            return
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC"):
        if any(f.name == name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            return
    raise RuntimeError("找不到中文字体；请安装微软雅黑、黑体或 Noto Sans CJK 后重试。")


def rows(filename):
    with (BASE / filename).open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def finish(filename):
    plt.tight_layout()
    plt.savefig(OUT / filename, dpi=170, bbox_inches="tight")
    plt.close()


choose_chinese_font()
plt.rcParams.update({"axes.unicode_minus": False, "figure.facecolor": "white", "axes.grid": True, "grid.alpha": 0.2})

daily = rows("daily_equity_drawdown.csv")
dates = [datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in daily]
equity = np.array([float(r["equity"]) for r in daily])
drawdown = np.array([float(r["drawdown_pct"]) * 100 for r in daily])
yearly = rows("portfolio_yearly.csv")
years = [int(r["year"]) for r in yearly]
year_pnl = [float(r["net_pnl"]) for r in yearly]

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(dates, equity, color="#1469a0", linewidth=1.8)
ax.axhline(50000, color="#8293a3", linestyle="--", linewidth=1, label="初始资金 5 万美元")
ax.set(title="YM 日内策略组合：模拟权益曲线", xlabel="日期", ylabel="模拟账户权益（美元）")
ax.legend(frameon=False)
finish("equity_curve.png")

fig, ax = plt.subplots(figsize=(12, 5))
ax.bar(years, year_pnl, color=["#177e89" if x >= 0 else "#c45252" for x in year_pnl])
ax.axhline(0, color="#495766", linewidth=0.8)
ax.set(title="YM 日内策略组合：逐年模拟净利润", xlabel="年份（2011、2026 为部分年度）", ylabel="模拟净利润（美元）")
ax.set_xticks(years)
ax.tick_params(axis="x", rotation=45)
finish("yearly_pnl.png")

fig, ax = plt.subplots(figsize=(12, 5))
ax.fill_between(dates, drawdown, 0, color="#cf665d", alpha=0.72)
ax.set(title="YM 日内策略组合：每日收盘权益回撤", xlabel="日期", ylabel="相对历史高点的回撤（%）")
finish("drawdown_curve.png")

monthly = rows("portfolio_monthly.csv")
heat = np.full((len(years), 12), np.nan)
year_index = {year: i for i, year in enumerate(years)}
for row in monthly:
    year, month = map(int, row["month"].split("-"))
    if year in year_index:
        heat[year_index[year], month - 1] = float(row["net_pnl"])
fig, ax = plt.subplots(figsize=(13, 7))
scale = max(abs(np.nanmin(heat)), abs(np.nanmax(heat)))
im = ax.imshow(heat, cmap="RdBu", vmin=-scale, vmax=scale, aspect="auto")
ax.set(title="YM 日内策略组合：逐月模拟净利润", xlabel="月份", ylabel="年份")
ax.set_xticks(range(12), [f"{m}月" for m in range(1, 13)])
ax.set_yticks(range(len(years)), years)
fig.colorbar(im, ax=ax, label="模拟净利润（美元）")
finish("monthly_pnl_heatmap.png")

strategy = rows("strategy_summary.csv")
names = [r["name"] for r in strategy]
pf = [float(r["profit_factor"]) for r in strategy]
fig, ax = plt.subplots(figsize=(8, 4.5))
bars = ax.bar(names, pf, color="#3f85a6")
ax.bar_label(bars, fmt="%.2f", padding=4)
ax.set(title="五条规则独立单手测试：盈利因子", xlabel="规则", ylabel="盈利因子")
ax.set_ylim(0, max(pf) * 1.2)
finish("strategy_pf.png")

strategy_yearly = rows("strategy_yearly.csv")
fig, ax = plt.subplots(figsize=(12, 5.5))
for name in names:
    by_year = {int(r["year"]): float(r["net_pnl"]) for r in strategy_yearly if r["strategy"] == name}
    ax.plot(years, [by_year.get(y, 0) for y in years], marker="o", markersize=3, label=name)
ax.axhline(0, color="#495766", linewidth=0.8)
ax.set(title="五条规则独立单手测试：逐年模拟净利润", xlabel="年份", ylabel="模拟净利润（美元）")
ax.set_xticks(years)
ax.tick_params(axis="x", rotation=45)
ax.legend(ncol=5, frameon=False)
finish("strategy_yearly_pnl.png")

year_pf = [float(r["profit_factor"]) for r in yearly]
finite_max = max(value for value in year_pf if math.isfinite(value))
plot_pf = [value if math.isfinite(value) else finite_max * 1.08 for value in year_pf]
fig, ax = plt.subplots(figsize=(12, 5))
ax.bar(years, plot_pf, color=["#177e89" if x >= 1 else "#c45252" for x in year_pf])
for year, original, shown in zip(years, year_pf, plot_pf):
    if not math.isfinite(original):
        ax.text(year, shown + finite_max * 0.03, "∞（无亏损交易）", ha="center", fontsize=9)
ax.axhline(1, color="#495766", linestyle="--", linewidth=1, label="盈亏平衡：1")
ax.set(title="YM 日内策略组合：逐年盈利因子", xlabel="年份", ylabel="盈利因子")
ax.set_ylim(0, finite_max * 1.22)
ax.set_xticks(years)
ax.tick_params(axis="x", rotation=45)
ax.legend(frameon=False)
finish("yearly_pf.png")

print(f"已生成 7 张中文图表：{OUT}")
