"""``python -m tsm.market_map``: look at the market map on real prices before any model uses it.

Reads the frozen price cache (never downloads) and:

- prints the 5 neighbours of NVDA, JPM and XOM on 2024-06-28, with and without
  the market adjustment;
- prints, for both settings, the mean share of a stock's neighbours that sit in
  its own sector, over the month-ends of 2016 to 2019, next to the share random
  neighbours would give;
- saves a heatmap of the 2024-06-28 market-adjusted map, stocks ordered by
  sector, to ``docs/graph_assets/adjacency_2024-06-28.png``.

A neighbour here is a non-zero off-diagonal entry of the matrix the model will
see, after the support was made symmetric. The market's own row is left out of
the shares: it has no sector peers by definition.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from tsm.config import DOCS_DIR, MARKET_TICKER, SECTORS
from tsm.data import load_panel, truncate_panel
from tsm.models.graph import correlation_adjacency, correlation_adjacency_series

AS_OF = "2024-06-28"
SHOWN = ["NVDA", "JPM", "XOM"]
SHARE_YEARS = ("2016", "2019")
ASSETS_DIR = DOCS_DIR / "graph_assets"
SETTINGS = {"market-adjusted": True, "raw returns": False}

# One blue, light to dark; zero blends into the white surface.
BLUES = LinearSegmentedColormap.from_list(
    "blues", ["#ffffff", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
)


def neighbours(matrix: np.ndarray, tickers: list[str], ticker: str, top: int = 5) -> list[tuple[str, float]]:
    """A stock's strongest links, with their correlation.

    Weights in a row are the correlations divided by the row sum, and the
    self-loop's correlation is 1, so weight / self-weight gives the correlation
    back. The strongest ``k`` of a row are the ones the stock picked itself.
    """
    i = tickers.index(ticker)
    row = matrix[i].copy()
    row[i] = 0.0
    order = [j for j in np.argsort(-row) if row[j] > 0][:top]
    return [(tickers[j], matrix[i, j] / matrix[i, i]) for j in order]


def same_sector_share(series: np.ndarray, tickers: list[str], rows: list[int]) -> float:
    """Mean over dates of the mean over stocks of: neighbours in its sector / neighbours."""
    sectors = np.array([SECTORS[t] for t in tickers])
    same = sectors[:, None] == sectors[None, :]
    others = ~np.eye(len(tickers), dtype=bool)
    stocks = [i for i, t in enumerate(tickers) if t != MARKET_TICKER]
    per_date = []
    for r in rows:
        linked = (series[r] > 0) & others
        counts = linked.sum(axis=1)
        shares = [(linked[i] & same[i]).sum() / counts[i] for i in stocks if counts[i] > 0]
        per_date.append(np.mean(shares))
    return float(np.mean(per_date))


def random_share(tickers: list[str], market_can_be_a_neighbour: bool) -> float:
    """What the share would be if neighbours were drawn at random."""
    pool = [t for t in tickers if market_can_be_a_neighbour or t != MARKET_TICKER]
    shares = []
    for t in tickers:
        if t == MARKET_TICKER:
            continue
        peers = sum(1 for o in pool if o != t and SECTORS[o] == SECTORS[t])
        shares.append(peers / (len(pool) - 1))
    return float(np.mean(shares))


def month_end_rows(dates: pd.DatetimeIndex, first_year: str, last_year: str) -> list[int]:
    positions = pd.Series(np.arange(len(dates)), index=dates)[first_year:last_year]
    return positions.groupby(positions.index.to_period("M")).last().tolist()


def heatmap(matrix: np.ndarray, tickers: list[str], path) -> None:
    """The matrix with stocks grouped by sector, sector blocks outlined."""
    sector_order = list(dict.fromkeys(SECTORS[t] for t in SECTORS))
    order = sorted(range(len(tickers)), key=lambda i: (sector_order.index(SECTORS[tickers[i]]), i))
    shown = matrix[np.ix_(order, order)]
    labels = [tickers[i] for i in order]
    groups = [SECTORS[t] for t in labels]
    edges = [i for i in range(1, len(groups)) if groups[i] != groups[i - 1]]

    # The market's self-loop is 1 by construction; letting it set the scale would wash out every other cell.
    scale = shown.copy()
    if MARKET_TICKER in labels:
        m = labels.index(MARKET_TICKER)
        scale[m, m] = 0.0
    fig, ax = plt.subplots(figsize=(11, 11.5))
    image = ax.imshow(shown, cmap=BLUES, vmin=0, vmax=scale.max(), interpolation="nearest")
    for edge in edges:
        ax.axhline(edge - 0.5, color="#9a9a96", linewidth=0.6)
        ax.axvline(edge - 0.5, color="#9a9a96", linewidth=0.6)
    ax.set_xticks(range(len(labels)), labels, rotation=90, fontsize=7, color="#3d3d3a")
    ax.set_yticks(range(len(labels)), labels, fontsize=7, color="#3d3d3a")
    starts = [0, *edges]
    ends = [*edges, len(labels)]
    for start, end in zip(starts, ends):
        ax.text(len(labels) + 0.6, (start + end - 1) / 2, groups[start], va="center", fontsize=8, color="#3d3d3a")
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0)
    bar = fig.colorbar(image, ax=ax, orientation="horizontal", fraction=0.025, pad=0.08, extend="max")
    bar.set_label(
        f"weight: each row sums to 1, the diagonal is the self-loop ({MARKET_TICKER}'s is 1.0, off the scale)",
        fontsize=8,
        color="#3d3d3a",
    )
    bar.ax.tick_params(labelsize=7, colors="#3d3d3a")
    bar.outline.set_visible(False)
    ax.set_title(
        f"Market map on {AS_OF}: market-adjusted correlations, 120-day window, k = 5",
        fontsize=11,
        color="#1f1f1d",
        loc="left",
    )
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    panel = load_panel(cache_only=True)
    tickers = list(panel)
    dates = next(iter(panel.values())).index
    position = int(dates.get_loc(pd.Timestamp(AS_OF)))
    on_date = truncate_panel(panel, position)
    print(f"{len(tickers)} tickers, prices {dates[0].date()} to {dates[-1].date()} (frozen cache)\n")

    maps = {label: correlation_adjacency(on_date, market_adjusted=flag) for label, flag in SETTINGS.items()}
    for label, matrix in maps.items():
        print(f"Neighbours on {AS_OF}, {label} (correlation of the residuals or returns):")
        for ticker in SHOWN:
            listed = ", ".join(f"{n} {c:.2f} ({SECTORS[n]})" for n, c in neighbours(matrix, tickers, ticker))
            total = int(np.count_nonzero(matrix[tickers.index(ticker)])) - 1
            print(f"  {ticker} [{SECTORS[ticker]}]: {listed}; {total} links after symmetrising")
        print()

    rows = month_end_rows(dates, *SHARE_YEARS)
    print(f"Share of neighbours in the same sector, month-ends {SHARE_YEARS[0]}-{SHARE_YEARS[1]} ({len(rows)} dates):")
    for label, flag in SETTINGS.items():
        share = same_sector_share(correlation_adjacency_series(panel, market_adjusted=flag), tickers, rows)
        chance = random_share(tickers, market_can_be_a_neighbour=not flag)
        print(f"  {label}: {share:.1%} (random neighbours: {chance:.1%})")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSETS_DIR / f"adjacency_{AS_OF}.png"
    heatmap(maps["market-adjusted"], tickers, path)
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
