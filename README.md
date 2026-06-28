# Clash Royale Card Tracker

Daily snapshots of any player's card collection from the **official Clash Royale API**, committed to this repo by a scheduled GitHub Action, and rendered as a static progress-over-time dashboard on GitHub Pages.

Give it a player tag → it tracks levels, cards held, and day-over-day gains automatically.

## How it works

```
GitHub Action (daily cron)
   └─ scripts/fetch_snapshot.py
        └─ GET official API (via fixed-IP proxy)
             └─ append dated snapshot to docs/data/<TAG>.json
                  └─ commit + push
                       └─ docs/index.html reads docs/data/*.json → dashboard
```

The official API returns each card's `level`, `maxLevel`, and `count` (cards held toward the next upgrade). The script normalizes the internal per-rarity level onto the unified "King Level" display scale (the numbers you see on RoyaleAPI / in-game) — and it auto-calibrates from the data, so it keeps working when Supercell raises the level cap.

## One-time setup

### 1. Get an API token
- Go to the official developer portal, log in, and create a key.
- **Whitelist IP `45.79.218.79`** on the key. That's the [RoyaleAPI proxy](https://docs.royaleapi.com/proxy.html) IP, which the script uses by default so you don't have to chase GitHub Actions' rotating IPs.

### 2. Add repo secrets & variables
In your repo: **Settings → Secrets and variables → Actions**
- Secret `CR_API_TOKEN` → your token
- Variable `CR_PLAYER_TAGS` → comma-separated tags, e.g. `809U0Y0LG,9PLJLPQ8G` (no `#`)

### 3. Enable Pages
**Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**.
Your dashboard will be at `https://<you>.github.io/<repo>/`.

### 4. Kick it off
**Actions → Daily Card Snapshot → Run workflow.** After the first run, `data/` is populated and the dashboard goes live. The cron then runs every day at 00:30 UTC.

## Run locally

```bash
export CR_API_TOKEN="your-token"
export CR_PLAYER_TAGS="809U0Y0LG"
python3 scripts/fetch_snapshot.py
# then serve the folder and open docs/index.html
python3 -m http.server 8000
```

## Adding / removing players
Edit the `CR_PLAYER_TAGS` repo variable. New tags start accumulating history on the next run; the dashboard's player dropdown updates from `data/index.json` automatically.

## Notes
- Snapshots are idempotent per day — re-running the same day overwrites that day's entry rather than duplicating it.
- The dashboard's progress bar shows progress toward max **level** (the API doesn't expose the per-level card requirement). The "Held" column shows raw cards-toward-next-upgrade from the API.
- This project is not affiliated with or endorsed by Supercell.
