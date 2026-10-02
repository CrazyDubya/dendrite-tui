# Dendrite

A Textual TUI for growing ideas through time — trees, branches, context, now and then.

Extracted from an orphan branch on [CrazyDubya/warroom](https://github.com/CrazyDubya/warroom) (`claude/tui-future-apps-…`). That repo’s `main` is a different product (collaborative investigation warroom); Dendrite is a separate idea-tree app.

## Install / run

```bash
pip install -e .
dendrite
# or
python run.py
```

Python ≥ 3.10. Core deps: Textual, Rich. Optional LLM extras: `pip install -e ".[llm]"`.

## Layout

- `dendrite/app.py` — Textual application entry
- `dendrite/models.py`, `storage.py`, `widgets.py`
- `dendrite/llm/` — optional provider registry
- `run.py` — quick runner
- `pyproject.toml` — package `dendrite` v0.1.0

## Status

Prototype / early extract. Source tip preserved at warroom branch `claude/tui-future-apps-016mtHpue4cq1DQ2CGKYtfFS` (`19e04b25`) until reviewed.
