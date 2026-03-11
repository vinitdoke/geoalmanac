---
description: Unified workflow for adding Hiking and Skiing trips
---

# Adding Trips to GeoAlmanac

This workflow handles both Hiking and Skiing trips using a common processing script.

## 1. Upload Data

### For Hiking 🥾
- Upload your **GPX file** to the `trails/` folder.
- (Optional) Upload photos to `trails/photos/`.

### For Skiing ⛷️
- Export from **Slopes**:
    1. **KMZ** (Google Earth) -> For track segments (Runs/Lifts).
    2. **GPX** (Raw GPS) -> For elevation data.
- Upload **BOTH files** to the `ski_tracks/` folder.
- **Naming**: The script supports:
    - Same name (e.g., `MyTrip.kmz` & `MyTrip.gpx`)
    - Suffix style (e.g., `MyTrip.kmz` & `MyTrip - raw gps.gpx`)
- **Multi-day**: Upload separate files for each day. They will be treated as distinct entries sorted by date.

## 2. Process Data
Run the update script from the project root:

```bash
./update_data.sh
```

This will:
1. Scan `trails/` and `ski_tracks/`.
2. Process all new files.
3. Automatically extract names and dates from filenames (e.g., `January 24, 2026 - Location`).
4. Update `src/web/data/hikes.json`.

## 3. Verify
- If the local web server isn't already running, start it:
  ```bash
  lsof -i :8000 >/dev/null || python3 -m http.server 8000 -d src/web
  ```
- Open [http://localhost:8000](http://localhost:8000) in your browser.
- Your new trips should appear in the list.
