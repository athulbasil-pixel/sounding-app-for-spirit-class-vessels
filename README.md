# MarineSense Engine Room Watch Log — Spirit class

This app replaces the Excel engine-room watch and sounding workbook with an offline browser app (Flask + SQLite).

**Status: Phase 0, design and data map.** There is no backend yet.

- [docs/WATCHLOG_BUILD_PROMPT.md](docs/WATCHLOG_BUILD_PROMPT.md): the build brief and phase plan
- [docs/field_registry.yaml](docs/field_registry.yaml): every workbook field, its unit, kind and source cell
- [docs/data_model.md](docs/data_model.md): the SQLite schema, calculation rules and workbook findings
- `mockups/`: static, clickable mockups with synthetic data, in Night and Day themes

## Viewing the mockups

From the repository folder:

```
python -m http.server 5090 --bind 127.0.0.1
```

Then open http://127.0.0.1:5090/mockups/index.html.

## Data privacy

This repository is public. Real workbooks, watch records, crew names, generated PDFs and databases are excluded by `.gitignore` and must never be committed. All demo and test data is synthetic.
