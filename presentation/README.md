# Results deck

`sciplay_results.pptx` – short results deck, updated as each part of the assignment is finished.

Rebuild after the data or findings change:

```bash
uv run python presentation/export_deck_data.py   # numbers and chart series -> deck_data.json
node presentation/build_deck.js                  # needs Node.js and `npm install pptxgenjs`
```

All numbers come from `sciplay.audit`, so the deck matches the notebook.
Charts are native PowerPoint charts and can be edited in PowerPoint.
