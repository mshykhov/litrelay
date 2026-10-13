# Demo inputs

These short chapters were written for this repository. They demonstrate aligned English source and a partial Russian translation.

```bash
uv run litrelay init demo --source examples/demo/source --translation examples/demo/translation --source-lang en --target-lang ru --title "A light in the harbor"
uv run litrelay run demo
```

The second command calls the selected real model. Automated tests inject fake responses to test the workflow without API usage.
