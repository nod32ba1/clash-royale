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
DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"

# Upgrade economy tables (NOT exposed by the API). Source: Clash Royale wiki
# (post-2026 Level-16 economy). Keyed by rarity -> {unified display level: cost to
# upgrade TO that level from the previous one}. The entry at a rarity's FLOOR level
# (e.g. Common 1, Rare 3) is the card's unlock cost, not an upgrade step.
# Validated: column/row totals match the wiki, and the Common column reproduces the
# RoyaleAPI figures for Electro Spirit (95550 gold, lvl4->13) and Ice Spirit.
CARDS_REQ = {
    "Common":    {1:1, 2:2, 3:4, 4:10, 5:20, 6:50, 7:100, 8:200, 9:400, 10:800, 11:1000, 12:1500, 13:2500, 14:3500, 15:5500, 16:7500},
    "Rare":      {3:1, 4:2, 5:4, 6:10, 7:20, 8:50, 9:100, 10:200, 11:300, 12:400, 13:550, 14:750, 15:1000, 16:1400},
    "Epic":      {6:1, 7:2, 8:4, 9:10, 10:20, 11:30, 12:50, 13:70, 14:100, 15:130, 16:180},
    "Legendary": {9:1, 10:2, 11:4, 12:6, 13:9, 14:12, 15:14, 16:20},
    "Champion":  {11:1, 12:2, 13:5, 14:8, 15:11, 16:15},
}
GOLD_REQ = {
    "Common":    {2:5, 3:20, 4:50, 5:150, 6:400, 7:1000, 8:2000, 9:4000, 10:8000, 11:15000, 12:25000, 13:40000, 14:60000, 15:90000, 16:120000},
    "Rare":      {4:50, 5:150, 6:400, 7:1000, 8:2000, 9:4000, 10:8000, 11:15000, 12:25000, 13:40000, 14:60000, 15:90000, 16:120000},
    "Epic":      {7:400, 8:2000, 9:4000, 10:8000, 11:15000, 12:25000, 13:40000, 14:60000, 15:90000, 16:120000},
    "Legendary": {10:5000, 11:15000, 12:25000, 13:40000, 14:60000, 15:90000, 16:120000},
    "Champion":  {12:25000, 13:40000, 14:60000, 15:90000, 16:120000},
}


def upgrade_economy(rarity: str, level: int, count: int) -> dict:
    """Derive the upgrade-economy columns for one card.

    Inputs are the unified display `level`, the rarity, and `count` = loose spare
    cards held (the API's `count`). Returns holding/max/outstanding/new level/gold.
    All upgrade costs come from the per-rarity CARDS_REQ / GOLD_REQ tables.
    """
    cards = CARDS_REQ.get(rarity, {})
    gold = GOLD_REQ.get(rarity, {})
    if not cards:
        return {}
    floor = min(cards)                       # level a fresh card of this rarity starts at
    top = max(cards)                         # max level in the tables (16)
    # Cards already sunk into reaching the current level (excludes the floor unlock).
    invested = sum(c for lvl, c in cards.items() if floor < lvl <= level)
    holding = invested + count
    max_card = sum(c for lvl, c in cards.items() if lvl > floor)   # floor -> max
    outstanding = max(0, max_card - holding)

    # Greedily spend the loose `count` to see how many levels it buys (card-limited).
    spare = count
    new_level = level
    new_gold = 0
    for lvl in range(level + 1, top + 1):
        need = cards.get(lvl)
        if need is None or spare < need:
            break
        spare -= need
        new_level = lvl
        new_gold += gold.get(lvl, 0)
    return {
        "holding": holding,
        "max_card": max_card,
        "outstanding": outstanding,
        "new_level": new_level,
        "new_level_gold": new_gold,
    }


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
        rarity = (c.get("rarity") or "").capitalize()
        count = c.get("count", 0)
        econ = upgrade_economy(rarity, display_level, count)
        rows.append({
            "name": c.get("name"),
            "id": c.get("id"),
            "rarity": rarity,
            "elixir": c.get("elixirCost"),
            "level": display_level,           # display scale (e.g. 1..16)
            "max_level": display_max,
            "count": count,                   # loose spare cards held
            "star_level": c.get("starLevel", 0),
            "evo_level": evo_level,
            "max_evo_level": max_evo,
            "is_maxed": display_level >= display_max,
            # Upgrade economy (computed from embedded CR tables, not the API):
            "holding": econ.get("holding"),
            "max_card": econ.get("max_card"),
            "outstanding": econ.get("outstanding"),
            "new_level": econ.get("new_level"),
            "new_level_gold": econ.get("new_level_gold"),
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
    # Player names can be non-ASCII (e.g. CJK). On Windows the console defaults
    # to cp1252, so printing such a name raises UnicodeEncodeError and the card
    # data — already written — gets misreported as a FAIL. Force UTF-8 output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

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
