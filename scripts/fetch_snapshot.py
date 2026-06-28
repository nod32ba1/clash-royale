#!/usr/bin/env python3
"""
Fetch a Clash Royale player's card collection from the official Supercell API
and append a dated snapshot to data/<TAG>.json.

Env vars:
  CR_API_TOKEN   - Supercell API bearer token (required)
  CR_PLAYER_TAGS - comma-separated player tags, e.g. "809U0Y0LG,ABC123" (required)
  CR_API_BASE    - API base URL (default: official proxy that has a fixed IP)

The proxy https://proxy.royaleapi.dev/v1 routes from a fixed IP (45.79.218.79),
so you whitelist THAT ip on your token instead of GitHub Actions' rotating IPs.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = os.environ.get("CR_API_BASE", "https://proxy.royaleapi.dev/v1")
TOKEN = os.environ.get("CR_API_TOKEN")
TAGS = os.environ.get("CR_PLAYER_TAGS", "")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Max card count needed to reach a given rarity's top level (display level 15),
# i.e. cumulative cards from level 1 -> max. Used to compute "outstanding".
# These are the standard CR upgrade totals per rarity.
RARITY_MAX_LEVEL = {"Common": 15, "Rare": 15, "Epic": 15, "Legendary": 15, "Champion": 15}


def fetch_player(tag: str) -> dict:
    clean = tag.lstrip("#").upper()
    url = f"{API_BASE}/players/{urllib.parse.quote('#' + clean)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            # RoyaleAPI proxy sits behind Cloudflare, which blocks the default
            # urllib User-Agent with a 1010 "browser signature" error.
            "User-Agent": "cr-card-tracker",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_cards(player: dict) -> list[dict]:
    """Flatten the API cards array to a clean, display-aligned schema.

    The unified "King Level" display scale is anchored by the card(s) with the
    highest maxLevel in the response (Commons). A card's display level is
    level + (top_max - maxLevel). This auto-adapts when Supercell raises the
    cap (e.g. the Level 16 update) without any hardcoded rarity offsets.
    """
    cards = player.get("cards", [])
    if not cards:
        return []
    top_max = max(c.get("maxLevel", 14) for c in cards)

    rows = []
    for c in cards:
        max_lvl = c.get("maxLevel", top_max)
        offset = top_max - max_lvl
        display_level = c.get("level", 0) + offset
        display_max = top_max
        max_evo = c.get("maxEvolutionLevel")
        evo_level = c.get("evolutionLevel", 0)
        rows.append({
            "name": c.get("name"),
            "id": c.get("id"),
            "rarity": (c.get("rarity") or "").capitalize(),
            "elixir": c.get("elixirCost"),
            "level": display_level,           # display scale (e.g. 1..16)
            "max_level": display_max,
            "count": c.get("count", 0),       # cards held toward NEXT upgrade
            "star_level": c.get("starLevel", 0),
            "evo_level": evo_level,
            "max_evo_level": max_evo,
            "is_maxed": display_level >= display_max,
        })
    return rows


def snapshot(tag: str) -> dict:
    player = fetch_player(tag)
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "tag": player.get("tag"),
        "name": player.get("name"),
        "exp_level": player.get("expLevel"),
        "trophies": player.get("trophies"),
        "cards": normalize_cards(player),
    }


def append_snapshot(tag: str, snap: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = tag.lstrip("#").upper()
    path = DATA_DIR / f"{clean}.json"
    if path.exists():
        history = json.loads(path.read_text(encoding="utf-8"))
    else:
        history = {"tag": snap["tag"], "name": snap["name"], "snapshots": []}

    # Replace today's snapshot if it already exists (idempotent re-runs).
    history["name"] = snap["name"]
    history["snapshots"] = [s for s in history["snapshots"] if s["date"] != snap["date"]]
    history["snapshots"].append(snap)
    history["snapshots"].sort(key=lambda s: s["date"])

    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_index():
    """Maintain data/index.json listing all tracked players for the dashboard."""
    players = []
    for p in sorted(DATA_DIR.glob("*.json")):
        if p.name == "index.json":
            continue
        h = json.loads(p.read_text(encoding="utf-8"))
        players.append({
            "tag": h.get("tag"),
            "name": h.get("name"),
            "file": p.name,
            "snapshots": len(h.get("snapshots", [])),
        })
    (DATA_DIR / "index.json").write_text(
        json.dumps({"players": players}, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main():
    if not TOKEN:
        sys.exit("ERROR: CR_API_TOKEN not set")
    tags = [t.strip() for t in TAGS.split(",") if t.strip()]
    if not tags:
        sys.exit("ERROR: CR_PLAYER_TAGS not set")

    for tag in tags:
        try:
            snap = snapshot(tag)
            path = append_snapshot(tag, snap)
            print(f"OK {tag}: {snap['name']} - {len(snap['cards'])} cards -> {path.name}")
        except Exception as e:
            print(f"FAIL {tag}: {e}", file=sys.stderr)

    write_index()


if __name__ == "__main__":
    main()
