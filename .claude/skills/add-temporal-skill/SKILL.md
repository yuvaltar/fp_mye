---
name: add-temporal-skill
description: Add a new skill (prediction agent) to the Temporal Skills Market engine in /algo — implement the shared interface, register it with the supervisor, test it, and add its row to the backtest report. Use whenever the user asks for a new skill, agent, signal or time horizon in the market.
---

# Add a temporal skill

A skill is one agent that predicts annualized 5-trading-day realized volatility from one time horizon or signal type. Adding one is always the same four steps. Do all four; a skill that is not registered, tested and reported does not count as added.

Before starting, ask the user for anything missing: the skill's name (snake_case), its horizon (`short`, `medium` or `long`, as in the contract) and the signal it uses in one sentence. If it needs a dependency outside the allowed list in `CLAUDE.md`, stop and ask.

## 1. Implement the shared interface

Create `algo/tsm/skills/<name>.py` with one class that subclasses `Skill` from `algo/tsm/skills/base.py`.

The shared interface is:

```python
class Skill(ABC):
    name: str       # snake_case, unique, matches the contract's skills[].name
    horizon: str    # "short" | "medium" | "long"

    @abstractmethod
    def fit(self, history: pd.DataFrame) -> None:
        """Train on daily data up to and including the last row."""

    @abstractmethod
    def predict(self, history: pd.DataFrame) -> float:
        """Annualized realized vol (decimal) for the 5 trading days after the last row."""
```

`history` is one ticker's daily data indexed by date, oldest first. If `base.py` does not exist yet, create it with exactly this interface first, and tell the user you did.

Rules for the implementation:

- Use only rows of `history`; never fetch data inside a skill, and never read anything dated after the last row (no look-ahead).
- Return a positive float in contract units (`0.24` = 24%), never a percentage or a daily value.
- Fix random seeds so the same input gives the same output.
- Do not change the interface to suit one skill. If the interface really is insufficient, stop and explain why to the user.

## 2. Register it with the supervisor

Add the class to the skill registry in `algo/tsm/supervisor.py` (the single list the supervisor iterates over). Nothing else should need to change: the supervisor weights whatever is registered, and the API reports whatever the supervisor returns. If adding a skill forces edits elsewhere, flag that as a design problem instead of patching around it.

The contract in `/contracts` must not change: a new skill is just one more entry in `skills[]`.

## 3. Test it

Add `algo/tests/skills/test_<name>.py` covering at least:

- `predict` returns a finite positive float on a realistic synthetic price series;
- no look-ahead: the prediction for a date is identical whether or not later rows exist in the frame it was cut from;
- determinism: two runs give the same number;
- it appears in the supervisor's registry, and the weights still sum to 1.

Run `cd algo && pytest` and make sure the whole suite passes, including `tests/test_contract.py`.

## 4. Add its row to the backtest report

Run the `backtest-report` skill so `docs/backtest.md` is regenerated with the new skill's row (its own error metrics and its average weight). Never add the row by hand: the report is generated.

## Finish

Tell the user, in plain language: what signal the skill uses, how it did against the HAR-RV baseline, the average weight the supervisor gave it, and whether adding it improved the combined prediction. Report a skill that makes things worse as such rather than tuning until it looks good.
