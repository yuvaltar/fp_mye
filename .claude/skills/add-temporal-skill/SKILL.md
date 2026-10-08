---
name: add-temporal-skill
description: Add a new skill (prediction agent) to the Temporal Skills Market engine in /algo — implement the shared interface, register it with the supervisor, test it, and add its row to the backtest report. Use whenever the user asks for a new skill, agent, signal or time horizon in the market.
---

# Add a temporal skill

A skill is one agent that predicts annualized 5-trading-day realized volatility from one time horizon or signal type. Adding one is always the same four steps. Do all four; a skill that is not registered, tested and reported does not count as added.

Before starting, ask the user for anything missing: the skill's name (snake_case), its horizon (`short`, `medium` or `long`, as in the contract) and the signal it uses in one sentence. If it needs a dependency outside the allowed list in `CLAUDE.md`, stop and ask.

## 1. Implement the shared interface

Create `algo/tsm/skills/<name>.py` with one class that subclasses `TemporalSkill` from `algo/tsm/skills/base.py`. Read an existing skill first (`short_term.py` is the simplest) and follow its shape.

The shared interface is:

```python
class TemporalSkill(ABC):
    name: str               # snake_case, unique, matches the contract's skills[].name
    horizon: str            # "short" | "medium" | "long"
    refit_every_days: int   # trading days between two fits in the backtest

    @abstractmethod
    def fit(self, panel: Panel) -> None: ...

    @abstractmethod
    def predict(self, panel: Panel) -> dict[str, float]: ...
```

`panel` is a dict of ticker to daily price frame (open, high, low, close, volume), all on the same dates, oldest first. It is always the panel as known on the as-of date: its last row is the as-of date. `predict` returns, for every ticker, the annualized volatility of the 5 trading days after that last row.

Rules for the implementation:

- Use only the panel you are given; never fetch data inside a skill. The backtest hands a skill nothing from the future, so the only way to leak is to build training targets wrongly: take targets from `tsm.target.forward_realized_vol` on the panel and drop the rows where it is NaN.
- `predict` is called on dates when `fit` was not; it must use the newest rows of the panel, not a state frozen at fit time.
- Return a positive float in contract units (`0.24` = 24%), floored at `MIN_VOL`.
- Fix random seeds so the same input gives the same output.
- Do not change the interface to suit one skill. If the interface really is insufficient, stop and explain why to the user.

## 2. Register it with the supervisor

Add the class to `build_skills()` in `algo/tsm/supervisor.py` (the single list the backtest and the supervisor iterate over). Nothing else should need to change: the supervisor weights whatever is registered, and the API reports whatever the supervisor returns. If adding a skill forces edits elsewhere, flag that as a design problem instead of patching around it.

The contract in `/contracts` must not change: a new skill is just one more entry in `skills[]`.

## 3. Test it

Add the skill to the `SKILLS` dict in `algo/tests/skills/test_skills.py`. That runs the checks every skill must pass: a finite positive prediction per ticker, determinism, no future leakage (prices after the as-of date are corrupted and the prediction must not move), and reaction to new data between two fits. `test_registry_matches_the_tested_skills` fails until the skill is in both the registry and that dict. Add a separate test file only for behaviour specific to the skill.

Run `cd algo && pytest` and make sure the whole suite passes, including `tests/test_backtest.py` (pipeline-wide leakage) and `tests/test_contract.py`.

## 4. Add its row to the backtest report

Run the `backtest-report` skill so `docs/backtest.md` is regenerated with the new skill's row (its own error metrics and its average weight). Never add the row by hand: the report is generated.

## Finish

Tell the user, in plain language: what signal the skill uses, how it did against the HAR-RV baseline, the average weight the supervisor gave it, and whether adding it improved the combined prediction. Report a skill that makes things worse as such rather than tuning until it looks good.
