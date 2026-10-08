"""The interface every skill of the market implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from tsm.data import Panel

# Smallest volatility a skill may return (0.5%); keeps predictions strictly positive.
MIN_VOL = 0.005


class TemporalSkill(ABC):
    """One agent predicting annualized 5-trading-day realized volatility.

    ``fit`` and ``predict`` both receive the panel as it was known on the
    as-of date: its last row is the as-of date and nothing later exists in it.
    A skill must use nothing but that panel.
    """

    name: str  # snake_case, matches skills[].name in the contract
    horizon: str  # "short" | "medium" | "long", as in the contract
    refit_every_days: int = 5  # trading days between two calls to fit in the backtest

    @abstractmethod
    def fit(self, panel: Panel) -> None:
        """Train on the panel. Only rows whose 5-day future is already inside the panel have a target."""

    @abstractmethod
    def predict(self, panel: Panel) -> dict[str, float]:
        """Volatility (decimal) of each ticker over the 5 trading days after the panel's last row."""
