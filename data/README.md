# Data Directory

## `ferry_terminals.json`

Static list of Washington State Ferry terminals with geocoded locations.

**Schema:**
- `name`: Simple name used for API lookups (e.g. `"Bremerton"`, `"Bainbridge Island"`)
- `display_name`: Human-readable name with neighborhood (e.g. `"Bremerton (Downtown)"`)
- `address`: Full street address
- `lat`, `lng`: Coordinates used for distance calculations
- `place_id`: Google Maps place ID
- `city`, `neighborhood`, `county`

**Source:** Manual compilation from WSDOT terminal data and Google Maps geocoding.

**Updates:** Rarely — only when new terminals open or addresses change.

---

## `sample_events.json`

Synthetic tech events for demo and testing. Covers March–June 2026.

**Schema:**
- `title`, `description`, `location`, `topic`
- `start_time`, `end_time`: ISO 8601 with timezone
- `url`: Event page (optional)
- `presenting`: boolean
- `talk_title`: your talk title if presenting (optional)

**Load with:**
```bash
python setup/elasticsearch_setup.py --load-sample-data
```

---

## Note on ferry schedules

Ferry schedules are **not stored as a static file** — `wsdot_server.py` calls the live
WSDOT Ferries API on every request so schedules are always current.
