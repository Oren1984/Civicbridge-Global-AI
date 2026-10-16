# Jurisdiction packs and source provenance

Packs are versioned JSON files in `backend/packs/`, loaded by `app.cli bootstrap` (`app/seed.py`).

| File | Code | Version | Title |
|---|---|---|---|
| `il-1.0.0.json` | IL | 1.0.0 | Israel — synthetic illustrative pack |
| `de-1.0.0.json` | DE | 1.0.0 | Germany / EU context — synthetic illustrative pack |
| `us-1.0.0.json` | US | 1.0.0 | United States — synthetic illustrative pack |
| `templates.json` | — | — | 6 life-event templates (relocation IL→DE, employment DE, study US, family IL, retirement DE→IL, business US-SF) |
| `glossary.json` | — | — | 10-entry demo glossary used by mock translation |
| `fixtures.json`, `fixtures/` | — | — | Demo files and the hash-matched audio transcript fixture |

A pack contains jurisdictions (country, region, municipality) with time zones and synthetic holiday calendars, authorities ("Demo …"), services with SLA working days, procedures, rule sets with rule versions (conditions, outcomes, review dates, verification status), and source records with passages.

## Rules that keep content honest

- **Everything is synthetic** and labelled. Authority names carry a "Demo" prefix; rule versions and sources have `verification_status = synthetic_illustrative`.
- **No invented URLs.** Where a real official source would exist, the source has `url = null` and `is_placeholder = true`; the UI shows "No official link (synthetic source)".
- **Review dates** are carried through: rules or sources past their review date are flagged in screening results, answers and Governance › Data quality.
- **Checksum guard.** The loader stores each pack's checksum. If a file changes without a version bump, bootstrap refuses to load it, so content changes are always visible as new versions. Rule versions referenced by decisions are stored on the decision (`rule_version_ids`).

## Adding or changing a pack

1. Copy a pack, change its `code`/`version` (a new file name such as `de-1.1.0.json`).
2. Keep `synthetic`/`is_placeholder` flags truthful. Add a real URL only for a real, checked source and set `verification_status` accordingly.
3. Restart the backend (`docker compose restart backend`); bootstrap loads the new version and Governance › Data quality lists it.
