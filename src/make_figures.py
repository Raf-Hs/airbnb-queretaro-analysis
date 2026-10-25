"""Generate the figures used in the README, findings report and dashboard spec.

All figures use the 99-listing city sample (the rural farm stay is excluded and
called out in the footnote). Run after clean_data.py.
"""

from __future__ import annotations

import textwrap

import matplotlib
matplotlib.use("Agg")

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse

from config import (
    CENTRO_LAT,
    CENTRO_LON,
    DISTANCE_BANDS,
    FIGURES_DIR,
    LISTINGS_CLEAN,
    MONTH_LABELS_EN,
    PALETTE,
    POSTAL_GEOJSON,
    RATES_CLEAN,
)

ROOM_COLORS = {"entire_home": PALETTE["teal"], "private_room": PALETTE["orange"]}
ROOM_LABELS = {"entire_home": "Entire home", "private_room": "Private room"}
BAND_ORDER = [b[2] for b in DISTANCE_BANDS]

SOURCE = (
    "Source: AirROI public data portal, Querétaro 2026-07 release (100-listing sample) · "
    "city sample n=99, MXN · analysis window Aug 2025-Apr 2026 for realised demand"
)


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlecolor": PALETTE["dark"],
            "axes.labelsize": 9,
            "axes.labelcolor": "#444444",
            "axes.edgecolor": "#cccccc",
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#e8e8e8",
            "grid.linewidth": 0.7,
            "axes.axisbelow": True,
            "xtick.color": "#555555",
            "ytick.color": "#555555",
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.frameon": False,
            "legend.fontsize": 8.5,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def finish(fig, filename: str, subtitle: str = "", note: str = SOURCE) -> None:
    if subtitle:
        fig.text(0.5, 0.965, subtitle, ha="center", va="top", fontsize=9, color="#666666")
    fig.text(0.01, 0.012, note, ha="left", va="bottom", fontsize=6.8, color="#8a8a8a")
    fig.savefig(FIGURES_DIR / filename, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print(f"  wrote {filename}")


def load():
    listings = pd.read_csv(LISTINGS_CLEAN, dtype={"listing_id": str, "postal_code": str})
    rates = pd.read_csv(RATES_CLEAN, dtype={"listing_id": str}, parse_dates=["month_start"])
    city = listings[listings["is_city_core"]].copy()
    monthly = rates[rates["listing_id"].isin(city["listing_id"])].copy()
    return listings, city, monthly


# ---------------------------------------------------------------------------
# 1. price distribution
# ---------------------------------------------------------------------------
def fig_price_distribution(city: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axes[0]

    prices = city["price_mxn"]
    bins = np.logspace(np.log10(prices.min() * 0.95), np.log10(prices.max() * 1.05), 28)
    ax.hist(prices, bins=bins, color=PALETTE["navy"], alpha=0.82, edgecolor="white", linewidth=0.6)
    ax.set_xscale("log")
    median = prices.median()
    q1, q3 = prices.quantile([0.25, 0.75])
    ax.axvline(median, color=PALETTE["orange"], linewidth=2)
    ax.annotate(
        f"median\nMX$1,{median:,.0f}".replace(",", ","),
        xy=(median, ax.get_ylim()[1] * 0.82),
        xytext=(8, 0),
        textcoords="offset points",
        fontsize=8.5,
        color=PALETTE["orange"],
        fontweight="bold",
    )
    ax.axvspan(q1, q3, color=PALETTE["sand"], alpha=0.18, zorder=0)
    ax.set_xlabel("Asking ADR (MXN per night, log scale)")
    ax.set_ylabel("Listings")
    ax.set_title("Nightly prices are right-skewed", loc="left")
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.text(
        0.02, 0.95,
        f"n = {len(prices)}   ·   p25 MX${q1:,.0f}   ·   p75 MX${q3:,.0f}",
        transform=ax.transAxes, va="top", fontsize=8, color="#666666",
    )

    ax = axes[1]
    groups = ["entire_home", "private_room"]
    data = [city.loc[city["room_type"] == g, "price_mxn"] for g in groups]
    bp = ax.boxplot(
        data, orientation="horizontal", widths=0.5, patch_artist=True, showfliers=False,
        medianprops={"color": "white", "linewidth": 1.6},
        whiskerprops={"color": "#888888"}, capprops={"color": "#888888"},
    )
    for patch, g in zip(bp["boxes"], groups):
        patch.set_facecolor(ROOM_COLORS[g])
        patch.set_edgecolor("white")
        patch.set_alpha(0.85)
    rng = np.random.default_rng(7)
    for i, (g, values) in enumerate(zip(groups, data), start=1):
        y = i + rng.normal(0, 0.07, len(values))
        ax.scatter(values, y, s=14, color=PALETTE["dark"], alpha=0.45, linewidths=0, zorder=3)
        ax.text(
            values.max() * 1.06, i,
            f"n={len(values)}\nmed MX${values.median():,.0f}",
            va="center", fontsize=8, color="#555555",
        )
    ax.set_yticks([1, 2], ["Entire home", "Private room"])
    ax.set_xscale("log")
    ax.set_xlim(right=city["price_mxn"].max() * 1.6)
    ax.set_xlabel("Asking ADR (MXN per night, log scale)")
    ax.set_title("Entire homes ask ~1.8× private rooms", loc="left")
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    fig.subplots_adjust(top=0.80, wspace=0.32)
    finish(fig, "01_price_distribution.png", "Asking nightly rate (ADR), trailing twelve months")


# ---------------------------------------------------------------------------
# 2. capacity
# ---------------------------------------------------------------------------
def fig_capacity(city: pd.DataFrame) -> None:
    order = ["Studio / 1 BR", "2 BR", "3 BR", "4+ BR", "Unknown"]
    labels = ["Studio / 1 BR", "2 BR", "3 BR", "4+ BR", "Not stated"]
    fig, ax = plt.subplots(figsize=(8.6, 4.6))

    rng = np.random.default_rng(11)
    for i, band in enumerate(order):
        subset = city[city["bedroom_band"] == band]
        if subset.empty:
            continue
        for j, room in enumerate(["entire_home", "private_room"]):
            vals = subset.loc[subset["room_type"] == room, "price_mxn"]
            if vals.empty:
                continue
            x = i + (j - 0.5) * 0.28 + rng.normal(0, 0.035, len(vals))
            ax.scatter(
                x, vals, s=28, color=ROOM_COLORS[room], alpha=0.72,
                edgecolor="white", linewidth=0.5, zorder=3,
            )
            ax.plot(
                [i + (j - 0.5) * 0.28 - 0.11, i + (j - 0.5) * 0.28 + 0.11],
                [vals.median(), vals.median()],
                color=PALETTE["dark"], linewidth=1.8, zorder=4,
            )
        ax.text(i, 12_500, f"n={len(subset)}", ha="center", fontsize=8, color="#777777")

    ax.set_xticks(range(len(order)), labels)
    ax.set_yscale("log")
    ax.set_ylim(300, 15_000)
    ax.set_ylabel("Asking ADR (MXN per night, log scale)")
    ax.set_xlabel("Bedroom band (from listing metadata)")
    ax.set_title("Capacity is the clearest price driver — but 19 listings do not state bedrooms", loc="left", pad=18)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=ROOM_COLORS[g],
               markeredgecolor="white", markersize=7, label=ROOM_LABELS[g])
        for g in ["entire_home", "private_room"]
    ]
    ax.legend(handles=handles, loc="upper left", ncol=2, bbox_to_anchor=(0, 1.0))
    ax.text(
        0.0, -0.16,
        "Bedroom metadata is missing for 17 of 24 private rooms, so 'Not stated' is mostly a room-type effect, not a size effect.",
        transform=ax.transAxes, fontsize=7.5, color="#777777",
    )
    finish(fig, "02_capacity_and_price.png", "Price by bedroom band and room type")


# ---------------------------------------------------------------------------
# 3. map
# ---------------------------------------------------------------------------
def fig_map(city: pd.DataFrame) -> None:
    post = gpd.read_file(POSTAL_GEOJSON)
    post = post.cx[-100.50:-100.24, 20.52:20.74]

    fig, ax = plt.subplots(figsize=(8.4, 6.4))
    post.plot(ax=ax, facecolor="#f7f5f1", edgecolor="#d8d4cc", linewidth=0.45, zorder=1)

    norm = LogNorm(vmin=350, vmax=city["price_mxn"].max())
    sizes = 18 + 210 * np.sqrt(city["revenue_mxn"] / city["revenue_mxn"].max())
    sc = ax.scatter(
        city["longitude"], city["latitude"],
        c=city["price_mxn"], s=sizes, cmap="viridis", norm=norm,
        alpha=0.9, edgecolor="white", linewidth=0.7, zorder=3,
    )

    lat = np.radians(CENTRO_LAT)
    circle = Ellipse(
        (CENTRO_LON, CENTRO_LAT), width=2 / (111.32 * np.cos(lat)), height=2 / 111.32,
        fill=False, edgecolor=PALETTE["red"], linestyle=(0, (4, 3)), linewidth=1.1, zorder=4,
    )
    ax.add_patch(circle)
    ax.scatter([CENTRO_LON], [CENTRO_LAT], marker="*", s=220, color=PALETTE["red"],
               edgecolor="white", linewidth=0.8, zorder=5)
    ax.annotate(
        "Plaza de Armas\n(distance reference)", (CENTRO_LON, CENTRO_LAT),
        xytext=(10, -22), textcoords="offset points", fontsize=8, color=PALETTE["red"],
        fontweight="bold",
    )
    ax.annotate(
        "1 km", (CENTRO_LON, CENTRO_LAT + 1 / 111.32),
        xytext=(4, 4), textcoords="offset points", fontsize=7.5, color=PALETTE["red"],
    )

    # 2 km scale bar
    km2 = 2 / (111.32 * np.cos(lat))
    x0, y0 = -100.475, 20.535
    ax.plot([x0, x0 + km2], [y0, y0], color=PALETTE["dark"], linewidth=2.4, solid_capstyle="butt", zorder=5)
    ax.text(x0 + km2 / 2, y0 + 0.003, "2 km", ha="center", fontsize=7.5, color=PALETTE["dark"])

    ax.set_xlim(-100.50, -100.24)
    ax.set_ylim(20.52, 20.73)
    ax.set_aspect(1 / np.cos(lat))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, color="#eeeeee", linewidth=0.5)
    ax.set_title("Listings cluster around the centro; the priciest homes sit just outside it", loc="left", pad=14)

    cbar = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Asking ADR (MXN/night, log scale)", fontsize=8)
    cbar.ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#777777",
               markeredgecolor="white", markersize=4.5, label="small = low TTM revenue"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#777777",
               markeredgecolor="white", markersize=10, label="large = high TTM revenue"),
    ]
    ax.legend(handles=handles, loc="lower right", handletextpad=0.6, labelspacing=0.7)

    note = (
        "Source: AirROI public data portal, Querétaro 2026-07 release · 99 city listings "
        "(1 rural farm stay 47 km east is off-map) · postal boundaries: SEPOMEX / open-mexico (MIT)"
    )
    finish(fig, "03_listing_map.png", "Spatial distribution of the sample", note)


# ---------------------------------------------------------------------------
# 4. distance
# ---------------------------------------------------------------------------
def fig_distance(city: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.3), gridspec_kw={"width_ratios": [1.5, 1]})
    ax = axes[0]
    for room in ["entire_home", "private_room"]:
        sub = city[city["room_type"] == room]
        ax.scatter(
            sub["distance_centro_km"], sub["price_mxn"], s=34,
            color=ROOM_COLORS[room], alpha=0.7, edgecolor="white", linewidth=0.5,
            label=ROOM_LABELS[room], zorder=3,
        )

    # binned median, only where at least 5 listings fall in the bin
    bins = np.arange(0, 13, 1.5)
    city["_bin"] = pd.cut(city["distance_centro_km"], bins)
    summary = city.groupby("_bin", observed=True).agg(
        dist=("distance_centro_km", "median"), med=("price_mxn", "median"), n=("price_mxn", "size")
    )
    summary = summary[summary["n"] >= 5]
    ax.plot(summary["dist"], summary["med"], color=PALETTE["dark"], linewidth=1.6,
            marker="o", markersize=4, label="Binned median (n≥5)", zorder=4)

    rho = city["distance_centro_km"].corr(city["price_mxn"], method="spearman")
    ax.set_yscale("log")
    ax.set_xlabel("Straight-line distance to Plaza de Armas (km)")
    ax.set_ylabel("Asking ADR (MXN/night, log scale)")
    ax.set_title(f"Distance explains almost none of the price variation (Spearman ρ = {rho:+.2f})", loc="left")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(loc="upper right")
    ax.set_xlim(0, 13)

    ax = axes[1]
    band_stats = (
        city.groupby("distance_band", observed=True)
        .agg(n=("listing_id", "size"), adr=("price_mxn", "median"), occ=("occupancy", "mean"))
        .reindex(BAND_ORDER)
        .dropna(subset=["adr"])
    )
    y = np.arange(len(band_stats))
    ax.barh(y, band_stats["adr"], color=PALETTE["navy"], alpha=0.85, height=0.6)
    for yi, (adr, n) in enumerate(zip(band_stats["adr"], band_stats["n"])):
        ax.text(adr + 25, yi, f"MX${adr:,.0f}  (n={int(n)})", va="center", fontsize=7.8, color="#555555")
    ax.set_yticks(y, [textwrap.fill(b, 18) for b in band_stats.index])
    ax.invert_yaxis()
    ax.set_xlim(0, band_stats["adr"].max() * 1.45)
    ax.set_xlabel("Median asking ADR (MXN/night)")
    ax.set_title("Median ADR by distance band", loc="left")
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    fig.subplots_adjust(top=0.80, wspace=0.42)
    note = (
        "Source: AirROI 2026-07 release · 99 city listings · distance is straight-line, "
        "not travel time; 51% of the sample sits within 1 km of the centro"
    )
    finish(fig, "04_distance_and_price.png", "Centrality is not a price premium in this sample", note)


# ---------------------------------------------------------------------------
# 5. seasonality
# ---------------------------------------------------------------------------
def fig_seasonality(monthly: pd.DataFrame) -> None:
    g = (
        monthly.groupby("month_start")
        .agg(
            adr_q=("adr_quoted_mxn", "median"),
            adr_b=("adr_booked_mxn", "median"),
            occ=("reserved_days", "sum"),
            avail=("nights_available", "sum"),
            rev=("revenue_mxn", "sum"),
            bookings=("has_bookings", "sum"),
        )
        .reset_index()
    )
    g["occ"] = g["occ"] / g["avail"]

    fig, axes = plt.subplots(3, 1, figsize=(10, 8.2), sharex=True,
                             gridspec_kw={"height_ratios": [1.25, 1, 1]})
    x = g["month_start"]
    labels = [f"{MONTH_LABELS_EN[m]}\n{y}" if m in (1, 8) else MONTH_LABELS_EN[m]
              for m, y in zip(g["month_start"].dt.month, g["month_start"].dt.year)]

    # shade the censored window across all panels
    cutoff = pd.Timestamp("2026-05-01")
    for ax in axes:
        ax.axvspan(cutoff, g["month_start"].max() + pd.Timedelta(days=20),
                   color="#eeeeee", zorder=0)
        ax.axvline(cutoff, color="#b0b0b0", linestyle=(0, (3, 3)), linewidth=1)

    ax = axes[0]
    ax.plot(x, g["adr_q"], color=PALETTE["navy"], linewidth=2.2, marker="o", markersize=4,
            label="Median asking ADR")
    booked = g["adr_b"].copy()
    ax.plot(x, booked, color=PALETTE["orange"], linewidth=2.0, marker="s", markersize=3.6,
            label="Median booked ADR")
    ax.set_ylabel("MXN / night")
    ax.set_title("Asking prices rise through the year while realised occupancy collapses", loc="left")
    ax.legend(loc="upper left", ncol=2)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylim(500, 1400)
    ax.annotate(
        "May-Jul 2026: bookings incomplete\n(snapshot right-censoring, not seasonality)",
        xy=(pd.Timestamp("2026-05-20"), 620), fontsize=7.6, color="#777777", ha="left",
    )

    ax = axes[1]
    colors = [PALETTE["navy"] if d <= pd.Timestamp("2026-04-01") else "#c9c9c9" for d in x]
    ax.bar(x, g["occ"], width=22, color=colors, edgecolor="white", linewidth=0.6)
    for xi, v in zip(x, g["occ"]):
        ax.text(xi, v + 0.008, f"{v:.0%}", ha="center", fontsize=7, color="#666666")
    ax.set_ylabel("Occupancy")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.set_ylim(0, 0.42)
    ax.set_title("Calendar occupancy: December and March peaks, January dip", loc="left")

    ax = axes[2]
    ax.bar(x, g["rev"] / 1e6, width=22,
           color=[PALETTE["teal"] if d <= pd.Timestamp("2026-04-01") else "#c9c9c9" for d in x],
           edgecolor="white", linewidth=0.6)
    for xi, v in zip(x, g["rev"] / 1e6):
        ax.text(xi, v + 0.015, f"{v:.2f}", ha="center", fontsize=7, color="#666666")
    ax.set_ylabel("MXN million")
    ax.set_xlabel("Month")
    ax.set_ylim(0, 1.55)
    ax.set_title("Monthly revenue across the 99-listing sample", loc="left")

    ax.set_xticks(x, labels)
    fig.subplots_adjust(top=0.91, hspace=0.36)
    note = (
        "Source: AirROI 2026-07 release · 99 city listings · booked ADR is missing when a listing "
        "had no reservations that month · occupancy = reserved nights / calendar nights"
    )
    finish(fig, "05_seasonality.png", "One year of calendar data (Aug 2025 - Jul 2026)", note)


# ---------------------------------------------------------------------------
# 6. price vs occupancy
# ---------------------------------------------------------------------------
def fig_price_occupancy(city: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    sizes = pd.Series(22 + 150 * np.sqrt(city["revenue_mxn"] / city["revenue_mxn"].max()), index=city.index)
    for room in ["entire_home", "private_room"]:
        sub = city[city["room_type"] == room]
        ax.scatter(
            sub["occupancy"], sub["price_mxn"], s=sizes[sub.index], color=ROOM_COLORS[room],
            alpha=0.7, edgecolor="white", linewidth=0.6, label=ROOM_LABELS[room], zorder=3,
        )
    ax.axvline(city["occupancy"].median(), color="#b0b0b0", linestyle=":", linewidth=1)
    ax.axhline(city["price_mxn"].median(), color="#b0b0b0", linestyle=":", linewidth=1)
    ax.text(city["occupancy"].median() + 0.006, 380, "median occupancy", fontsize=7.2, color="#888888", rotation=90)
    ax.text(0.012, city["price_mxn"].median() * 1.04, "median ADR", fontsize=7.2, color="#888888")

    rho = city["occupancy"].corr(city["price_mxn"], method="spearman")
    ax.set_yscale("log")
    ax.set_xlabel("Calendar occupancy (share of all nights booked)")
    ax.set_ylabel("Asking ADR (MXN/night, log scale)")
    ax.set_title(f"Higher asking prices do not visibly depress occupancy (ρ = {rho:+.2f})", loc="left")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(loc="upper right", title="Bubble size = TTM revenue", title_fontsize=7.5)
    ax.set_xlim(0, 0.72)

    note = (
        "Source: AirROI 2026-07 release · 99 city listings · correlation is descriptive; "
        "price and occupancy are jointly driven by capacity, location and host strategy"
    )
    finish(fig, "06_price_vs_occupancy.png", "No simple price-volume trade-off in the cross-section", note)


# ---------------------------------------------------------------------------
# 7. segments
# ---------------------------------------------------------------------------
def fig_segments(city: pd.DataFrame) -> None:
    segments = {
        "Entire home": city[city["room_type"] == "entire_home"],
        "Private room": city[city["room_type"] == "private_room"],
        "Superhost": city[city["superhost"] == 1],
        "Not superhost": city[city["superhost"] == 0],
        "Pro managed": city[city["professional_management"] == 1],
        "Independent": city[city["professional_management"] == 0],
    }
    stats = pd.DataFrame(
        {
            k: {
                "n": len(v),
                "adr": v["price_mxn"].median(),
                "occ": v["occupancy"].mean(),
                "rev": v["revenue_mxn"].median(),
            }
            for k, v in segments.items()
        }
    ).T

    colors = [PALETTE["teal"], PALETTE["orange"], PALETTE["navy"], PALETTE["grey"],
              PALETTE["navy"], PALETTE["grey"]]

    fig, axes = plt.subplots(1, 3, figsize=(11.6, 4.1))
    metrics = [
        ("adr", "Median asking ADR (MXN/night)", "{:,.0f}", 1.30),
        ("occ", "Mean calendar occupancy", "{:.1%}", 1.35),
        ("rev", "Median TTM revenue (MXN)", "{:,.0f}", 1.45),
    ]
    for ax, (metric, title, fmt, xmax_factor) in zip(axes, metrics):
        y = np.arange(len(stats))
        ax.barh(y, stats[metric], color=colors, alpha=0.88, height=0.62)
        for yi, (v, n) in enumerate(zip(stats[metric], stats["n"])):
            label = f"{v / 1e6:.2f}M" if metric == "rev" else fmt.format(v)
            ax.text(v * 1.03, yi, label, va="center", fontsize=7.8, color="#444444")
        ax.set_yticks(y, [f"{k}  (n={int(n)})" for k, n in zip(stats.index, stats["n"])])
        ax.invert_yaxis()
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_xlim(0, stats[metric].max() * xmax_factor)
        ax.grid(axis="y", visible=False)
        if metric == "occ":
            ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
        else:
            ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    fig.subplots_adjust(top=0.80, wspace=0.55)
    note = (
        "Source: AirROI 2026-07 release · 99 city listings · 'Pro managed' = 17 listings held by "
        "only 2 hosts, so that comparison is a two-host case study, not a market effect"
    )
    finish(fig, "07_segment_scorecard.png", "Segment scorecard: price, occupancy and revenue", note)


# ---------------------------------------------------------------------------
# 8. revenue concentration (Lorenz)
# ---------------------------------------------------------------------------
def fig_lorenz(city: pd.DataFrame) -> None:
    rev = np.sort(city["revenue_mxn"].values)
    cum = np.cumsum(rev) / rev.sum()
    share = np.arange(1, len(rev) + 1) / len(rev)
    share = np.insert(share, 0, 0)
    cum = np.insert(cum, 0, 0)

    n = len(rev)
    gini = (n + 1 - 2 * np.sum(cum[1:])) / n

    fig, ax = plt.subplots(figsize=(6.9, 5.2))
    ax.plot([0, 1], [0, 1], color="#bbbbbb", linestyle="--", linewidth=1, label="Perfect equality")
    ax.plot(share, cum, color=PALETTE["navy"], linewidth=2.6, label=f"Sample Lorenz curve (Gini {gini:.2f})")
    ax.fill_between(share, cum, share, color=PALETTE["sand"], alpha=0.25)

    top10 = rev[::-1][: int(np.ceil(n * 0.10))].sum() / rev.sum()
    top20 = rev[::-1][: int(np.ceil(n * 0.20))].sum() / rev.sum()
    ax.scatter([0.90], [1 - top10], color=PALETTE["red"], zorder=5, s=38)
    ax.annotate(f"Top 10% of listings\n= {top10:.0%} of revenue", xy=(0.90, 1 - top10),
                xytext=(-128, 26), textcoords="offset points", fontsize=8.2,
                color=PALETTE["red"], fontweight="bold",
                arrowprops={"arrowstyle": "-", "color": PALETTE["red"], "linewidth": 0.8})
    ax.text(0.04, 0.90, f"Top 20% = {top20:.0%}\nof sample revenue", fontsize=8.2, color="#555555")

    ax.set_xlabel("Cumulative share of listings (lowest to highest revenue)")
    ax.set_ylabel("Cumulative share of TTM revenue")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.set_title("Revenue is concentrated: a fifth of listings earns half the money", loc="left")
    ax.legend(loc="upper left")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    finish(fig, "08_revenue_concentration.png", "Lorenz curve of trailing-twelve-month revenue")


# ---------------------------------------------------------------------------
# 9. correlation heatmap
# ---------------------------------------------------------------------------
def fig_correlation(city: pd.DataFrame) -> None:
    cols = {
        "price_mxn": "Asking ADR",
        "occupancy": "Occupancy",
        "revenue_mxn": "TTM revenue",
        "guests": "Guests",
        "bedrooms": "Bedrooms",
        "baths": "Bathrooms",
        "rating_overall": "Rating",
        "num_reviews": "Reviews",
        "distance_centro_km": "Distance to centro",
        "ttm_avg_length_of_stay": "Avg stay length",
        "photos_count": "Photos",
    }
    corr = city[list(cols)].corr(method="spearman").rename(index=cols, columns=cols)
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)

    fig, ax = plt.subplots(figsize=(8.1, 6.6))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("white")
    im = ax.imshow(np.ma.array(corr.values, mask=mask), cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=42, ha="right")
    ax.set_yticks(range(len(corr)), corr.index)
    ax.grid(False)

    for i in range(len(corr)):
        for j in range(len(corr)):
            if mask[i, j]:
                continue
            val = corr.values[i, j]
            color = "white" if abs(val) > 0.55 else "#333333"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=7.8, color=color)

    ax.set_title("Capacity and price move together; ratings barely move anything", loc="left", pad=14)
    cbar = fig.colorbar(im, ax=ax, fraction=0.036, pad=0.02)
    cbar.set_label("Spearman correlation", fontsize=8)
    ax.text(
        0.0, -0.28,
        "Pairwise complete observations (bedrooms n=80). Correlation is not causation; capacity, "
        "room type and host strategy are correlated with each other.",
        transform=ax.transAxes, fontsize=7.2, color="#777777",
    )
    finish(fig, "09_correlation_matrix.png", "Spearman rank correlations, city sample")


# ---------------------------------------------------------------------------
# 10. within-listing repricing
# ---------------------------------------------------------------------------
def fig_within_listing(monthly: pd.DataFrame) -> None:
    price = monthly.pivot_table(index="listing_id", columns="month_start", values="adr_quoted_mxn")
    occ = monthly.pivot_table(index="listing_id", columns="month_start", values="occupancy")
    base_price = price[price.columns.min()]
    price_index = price.div(base_price, axis=0).mul(100)
    occ_change = occ.sub(occ[occ.columns.min()], axis=0).mul(100)

    x = pd.to_datetime(price_index.columns)
    labels = [f"{MONTH_LABELS_EN[m]}\n{y}" if m in (1, 8) else MONTH_LABELS_EN[m]
              for m, y in zip(x.month, x.year)]
    cutoff = pd.Timestamp("2026-05-01")

    fig, axes = plt.subplots(2, 1, figsize=(9.6, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.35, 1]})

    for ax in axes:
        ax.axvspan(cutoff, x.max() + pd.Timedelta(days=18), color="#eeeeee", zorder=0)
        ax.axvline(cutoff, color="#b0b0b0", linestyle=(0, (3, 3)), linewidth=1)

    ax = axes[0]
    med = price_index.median()
    q1 = price_index.quantile(0.25)
    q3 = price_index.quantile(0.75)
    ax.fill_between(x, q1, q3, color=PALETTE["teal"], alpha=0.18, linewidth=0, label="Interquartile range")
    ax.plot(x, med, color=PALETTE["teal"], linewidth=2.4, marker="o", markersize=4, label="Median listing")
    ax.axhline(100, color="#999999", linewidth=0.9, linestyle=":")
    ax.set_ylabel("ADR index (Aug 2025 = 100)")
    ax.set_title("The same listings charge ~25% more in April than in August", loc="left")
    ax.legend(loc="upper left", ncol=2)
    ax.set_ylim(60, 175)
    ax.annotate(
        f"+{med.iloc[-4] - 100:.0f}% by Apr 2026",
        xy=(x[-4], med.iloc[-4]), xytext=(-8, 12), textcoords="offset points",
        fontsize=8.5, color=PALETTE["teal"], fontweight="bold", ha="right",
    )

    ax = axes[1]
    med_o = occ_change.median()
    ax.fill_between(x, occ_change.quantile(0.25), occ_change.quantile(0.75),
                    color=PALETTE["orange"], alpha=0.18, linewidth=0)
    ax.plot(x, med_o, color=PALETTE["orange"], linewidth=2.2, marker="s", markersize=3.6,
            label="Median listing")
    ax.axhline(0, color="#999999", linewidth=0.9, linestyle=":")
    ax.set_ylabel("Occupancy change (percentage points)")
    ax.set_xlabel("Month")
    ax.set_title("Occupancy did not rise with price", loc="left")
    ax.set_ylim(-22, 12)
    ax.legend(loc="lower left")

    ax.set_xticks(x, labels)
    fig.subplots_adjust(top=0.90, hspace=0.34)
    note = (
        "Source: AirROI 2026-07 release · 98 city listings with an Aug-2025 observation · "
        "each listing is compared with its own base month, so composition cannot drive the move"
    )
    finish(fig, "10_within_listing_repricing.png", "Within-listing price and occupancy change", note)


def main() -> None:
    style()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    _, city, monthly = load()
    print(f"city listings: {len(city)}; monthly rows: {len(monthly)}")

    fig_price_distribution(city)
    fig_capacity(city)
    fig_map(city)
    fig_distance(city)
    fig_seasonality(monthly)
    fig_price_occupancy(city)
    fig_segments(city)
    fig_lorenz(city)
    fig_correlation(city)
    fig_within_listing(monthly)


if __name__ == "__main__":
    main()
