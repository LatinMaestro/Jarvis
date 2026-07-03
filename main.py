# ============================================================================================================
# ============================================================================================================
# BOT HEADER
# ============================================================================================================
# ==================================s==========================================================================

# =========================
# Imports
# =========================
import os
import re
import io
import json
import random
import sqlite3
import asyncio
import threading
import aiohttp
import math
import traceback
import urllib.parse
import discord
import pandas
import time
import asyncio
import heapq

from discord.ext import commands, tasks
from discord.ui import View, Button, Select
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from uuid import uuid4
from itertools import combinations
from typing import Any, Optional
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from jarvis.database.connection import (
    env_flag as _env_flag,
    open_sqlite_connection,
    prepare_sqlite_db_file as _prepare_sqlite_db_file,
)
from jarvis.database.roster import list_enabled_roster_uids, list_roster
from jarvis.formatting import format_duration as _fmt_time
from jarvis.naming import (
    PREFERRED_PLAYERS,
    canonical_player_name,
    norm_key,
    norm_simple as _norm_simple,
)
from jarvis.rendering.fonts import BODY_PT, DEFAULT_FONT_PATH, TITLE_PT, get_fonts
from jarvis.stats.hero_bans import get_top_hero_bans as _get_top_hero_bans
from jarvis.stats.hero_time import get_hero_time_by_player as _get_hero_time_by_player
from jarvis.stats.hero_roles import load_hero_cache_rows, load_season_hero_usage
from jarvis.stats.games import get_recent_games as _get_recent_games
from jarvis.stats.head_to_head import get_opponent_match_uids, load_accuracy_components, load_player_totals
from jarvis.stats.low_team import (
    calculate_low_team_results as _calculate_low_team_results,
    render_low_team_image as _render_low_team_image,
)
from jarvis.stats.player_bans import load_ban_events, load_human_player_matches
from jarvis.stats.profiles import latest_player_name, list_human_players
from jarvis.stats.role_winrates import load_role_segment_rows
from jarvis.stats.seasons import (
    season_date_range as _read_season_date_range,
    season_game_count as _read_season_game_count,
)
from jarvis.stats.sessions import (
    aggregate_wl_for_labels as _read_session_wl,
    load_all_ordered_game_labels,
    load_games_grouped_by_local_date,
)
from jarvis.stats.team_size_records import (
    aggregate_records as _team_size_aggregate_records,
    eligible_exact_2v2_labels as _team_size_eligible_exact_2v2_labels,
    eligible_min_4v4_labels as _team_size_eligible_min_4v4_labels,
    render_records_image as _team_size_render_records_image,
)
from jarvis.stats.top3 import load_human_match_rows as _load_top3_human_match_rows
from rivalsmeta_adapter import (
    RIVALSMETA_API_BASE,
    fetch_rivalsmeta_player_history,
    is_rivalsmeta_match_url,
    match_id_from_rivalsmeta_url,
    normalise_rivalsmeta_match_payload,
    read_limited_response_body,
)

# =========================
# Team Fairness Session State (keep for !session_* / !next_teams)
# =========================
SESSION_STATES = {}  # key = (guild_id, channel_id) -> SessionState
FAIRNESS_CONTEXTS = {}  # key = (guild_id, channel_id) -> FairnessContext
_PERSISTENT_NEXTTEAMS_VIEWS_REGISTERED = False

# =========================
# Discord bot setup
# =========================
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# Database setup
# =========================
# Railway/DigitalOcean-ready: keep the database path configurable so SQLite can
# live on persistent storage (e.g. Railway volume mounted at /data).
DB_PATH = (os.getenv("MR_DB_PATH", "marvel_rivals_stats.db") or "marvel_rivals_stats.db").strip()
DB_SEED_PATH = (os.getenv("MR_DB_SEED_PATH", "marvel_rivals_stats.db") or "marvel_rivals_stats.db").strip()


def _allow_command_hero_cache_refresh() -> bool:
    """Keep normal display/stat commands from making surprise hero-cache API calls."""
    return _env_flag("ENABLE_COMMAND_HERO_CACHE_REFRESH", False)


_prepare_sqlite_db_file(DB_PATH, DB_SEED_PATH)

conn, c = open_sqlite_connection(DB_PATH)


# =========================
# Season + migrations
# =========================
def run_db_migrations(default_season: int = 5):
    """
    Season support:
    - Ensures bot_settings and seasons tables exist
    - Makes game_stats + streaks season-aware (PK includes season_id)
    - Creates season-filtered views game_stats_v and streaks_v (current season only)
    """

    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    c.execute("SELECT value FROM bot_settings WHERE key='current_season'")
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO bot_settings(key, value) VALUES('current_season', ?)",
            (str(default_season), ))
        conn.commit()

    # Detect whether game_stats already has season_id
    c.execute("PRAGMA table_info(game_stats)")
    cols = [r[1] for r in c.fetchall()]
    game_stats_has_season = ("season_id" in cols)

    # Detect whether streaks already has season_id
    c.execute("PRAGMA table_info(streaks)")
    cols2 = [r[1] for r in c.fetchall()]
    streaks_has_season = ("season_id" in cols2)

    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='game_stats'"
    )
    game_stats_exists = c.fetchone() is not None

    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='streaks'")
    streaks_exists = c.fetchone() is not None

    # --- game_stats ---
    if not game_stats_exists:
        c.execute("""
            CREATE TABLE IF NOT EXISTS game_stats (
                season_id INTEGER NOT NULL,
                game_label TEXT NOT NULL,
                player TEXT NOT NULL,

                kills INTEGER,
                deaths INTEGER,
                assists INTEGER,
                damage INTEGER,
                damage_taken INTEGER,
                healing INTEGER,
                win INTEGER,
                loss INTEGER,
                mvp INTEGER,
                svp INTEGER,

                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season_id, game_label, player)
            )
        """)
        conn.commit()

    elif game_stats_exists and not game_stats_has_season:
        c.execute("ALTER TABLE game_stats RENAME TO game_stats_old")

        c.execute("""
            CREATE TABLE game_stats (
                season_id INTEGER NOT NULL,
                game_label TEXT NOT NULL,
                player TEXT NOT NULL,

                kills INTEGER,
                deaths INTEGER,
                assists INTEGER,
                damage INTEGER,
                damage_taken INTEGER,
                healing INTEGER,
                win INTEGER,
                loss INTEGER,
                mvp INTEGER,
                svp INTEGER,

                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season_id, game_label, player)
            )
        """)

        c.execute(f"""
            INSERT INTO game_stats (
                season_id, game_label, player,
                kills, deaths, assists, damage, damage_taken, healing,
                win, loss, mvp, svp, timestamp
            )
            SELECT
                {default_season}, game_label, player,
                kills, deaths, assists, damage, damage_taken, healing,
                win, loss, mvp, svp, timestamp
            FROM game_stats_old
        """)

        c.execute("DROP TABLE game_stats_old")
        conn.commit()

    # --- streaks ---
    if not streaks_exists:
        c.execute("""
            CREATE TABLE IF NOT EXISTS streaks (
                season_id INTEGER NOT NULL,
                player TEXT NOT NULL,
                current_streak INTEGER,
                longest_win_streak INTEGER,
                PRIMARY KEY (season_id, player)
            )
        """)
        conn.commit()

    elif streaks_exists and not streaks_has_season:
        c.execute("ALTER TABLE streaks RENAME TO streaks_old")

        c.execute("""
            CREATE TABLE streaks (
                season_id INTEGER NOT NULL,
                player TEXT NOT NULL,
                current_streak INTEGER,
                longest_win_streak INTEGER,
                PRIMARY KEY (season_id, player)
            )
        """)

        c.execute(f"""
            INSERT INTO streaks (season_id, player, current_streak, longest_win_streak)
            SELECT {default_season}, player, current_streak, longest_win_streak
            FROM streaks_old
        """)

        c.execute("DROP TABLE streaks_old")
        conn.commit()


def ensure_season_table():
    c.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            season_id INTEGER PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def get_current_season_id() -> int:
    c.execute(
        "SELECT CAST(value AS INTEGER) FROM bot_settings WHERE key='current_season'"
    )
    row = c.fetchone()
    return int(row[0]) if row and row[0] is not None else 5


def set_current_season_id(season_id: int):
    c.execute(
        """
        INSERT INTO bot_settings(key, value) VALUES('current_season', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (str(season_id), ))
    conn.commit()


def ensure_season_exists(season_id: int):
    ensure_season_table()
    c.execute("INSERT OR IGNORE INTO seasons(season_id) VALUES(?)",
              (season_id, ))
    conn.commit()


def refresh_season_views():
    season_id = get_current_season_id()

    c.execute("DROP VIEW IF EXISTS game_stats_v")
    c.execute("DROP VIEW IF EXISTS streaks_v")

    c.execute(f"""
        CREATE VIEW game_stats_v AS
        SELECT *
        FROM game_stats
        WHERE season_id = {season_id}
    """)

    c.execute(f"""
        CREATE VIEW streaks_v AS
        SELECT *
        FROM streaks
        WHERE season_id = {season_id}
    """)

    conn.commit()


def update_streak(player: str, won: bool, season_id: Optional[int] = None):
    """
    Keep streaks working with API imports.
    Call this from submit_match AFTER inserting/refreshing human game_stats rows.
    """
    if season_id is None:
        season_id = get_current_season_id()

    c.execute(
        "SELECT current_streak, longest_win_streak FROM streaks_v WHERE player = ?",
        (player, ))
    row = c.fetchone()

    if not row:
        current_streak = 1 if won else -1
        longest_win_streak = 1 if won else 0
    else:
        current_streak, longest_win_streak = row
        if won:
            current_streak = current_streak + 1 if current_streak >= 0 else 1
            longest_win_streak = max(longest_win_streak, current_streak)
        else:
            current_streak = current_streak - 1 if current_streak <= 0 else -1

    c.execute(
        """
        REPLACE INTO streaks (season_id, player, current_streak, longest_win_streak)
        VALUES (?, ?, ?, ?)
    """, (season_id, player, current_streak, longest_win_streak))

    conn.commit()

# =========================
# Session persistence table (for next_teams/session)
# =========================
def ensure_session_state_table():
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_state (
            guild_id   INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, channel_id)
        )
    """)
    conn.commit()


def _session_key_to_ids(key):
    return int(key[0]), int(key[1])


def _serialize_session(session) -> dict:
    return {
        "active_players": sorted(list(getattr(session, "active_players", set()) or [])),
        "display_name_map": dict(getattr(session, "display_name_map", {}) or {}),
        "session_games": [
            {
                "team_a": sorted(list(g["team_a"])),
                "team_b": sorted(list(g["team_b"])),
                "low_team": sorted(list(g["low_team"])) if g.get("low_team") else None,
                "restricted_roles": dict(g.get("restricted_roles") or {}) if g.get("restricted_roles") else None,
            }
            for g in (getattr(session, "session_games", None) or [])
        ],
        "session_low_team_counts": dict(getattr(session, "session_low_team_counts", {}) or {}),
        "last_split": ({
            "team_a": sorted(list(session.last_split.get("team_a", []))),
            "team_b": sorted(list(session.last_split.get("team_b", []))),
            "low_team": sorted(list(session.last_split.get("low_team", []))) if session.last_split.get("low_team") else None,
            "score": session.last_split.get("score"),
        } if getattr(session, "last_split", None) else None),
        "last_debug": (session.last_debug if isinstance(getattr(session, "last_debug", None), dict) else None),
        "pending_roll_token": getattr(session, "pending_roll_token", None),
        "pending_roll_message_id": getattr(session, "pending_roll_message_id", None),
        "pending_roll_data": ({
            "team_a": sorted(list(session.pending_roll_data.get("team_a", []))),
            "team_b": sorted(list(session.pending_roll_data.get("team_b", []))),
            "low_team": sorted(list(session.pending_roll_data.get("low_team", []))) if session.pending_roll_data.get("low_team") else None,
            "restricted_roles": dict(session.pending_roll_data.get("restricted_roles") or {}) if session.pending_roll_data.get("restricted_roles") else None,
        } if getattr(session, "pending_roll_data", None) else None),
        "pair_lock_47_disabled": bool(getattr(session, "pair_lock_47_disabled", False)),
        "pair_lock_47_disabled_lobby": (
            sorted(list(getattr(session, "pair_lock_47_disabled_lobby", []) or []))
            if getattr(session, "pair_lock_47_disabled_lobby", None)
            else None
        ),
    }

def _apply_session_state(session, data: dict):
    # Lobby
    session.active_players = set(data.get("active_players") or [])

    dnm = data.get("display_name_map")
    if isinstance(dnm, dict) and dnm:
        session.display_name_map = dnm

    # Committed session history
    session.session_games = []
    for g in (data.get("session_games") or []):
        team_a = frozenset(g.get("team_a") or [])
        team_b = frozenset(g.get("team_b") or [])
        low_team_list = g.get("low_team")
        low_team = frozenset(low_team_list) if low_team_list else None

        rr = g.get("restricted_roles")
        restricted_roles = dict(rr) if isinstance(rr, dict) and rr else None

        session.session_games.append({
            "team_a": team_a,
            "team_b": team_b,
            "low_team": low_team,
            "restricted_roles": restricted_roles,
        })

    # Low-team counts
    session.session_low_team_counts = defaultdict(int)
    for k, v in (data.get("session_low_team_counts") or {}).items():
        try:
            session.session_low_team_counts[str(k)] = int(v)
        except Exception:
            session.session_low_team_counts[str(k)] = 0

    # Optional last split/debug
    ls = data.get("last_split")
    if isinstance(ls, dict):
        session.last_split = {
            "team_a": frozenset(ls.get("team_a") or []),
            "team_b": frozenset(ls.get("team_b") or []),
            "low_team": frozenset(ls.get("low_team") or []) if ls.get("low_team") else None,
            "score": ls.get("score"),
        }
    else:
        session.last_split = None

    session.last_debug = data.get("last_debug") if isinstance(data.get("last_debug"), dict) else None

    # Pending roll
    session.pending_roll_token = data.get("pending_roll_token")
    session.pending_roll_message_id = data.get("pending_roll_message_id")

    prd = data.get("pending_roll_data")
    if isinstance(prd, dict) and prd:
        rr = prd.get("restricted_roles")
        restricted_roles = dict(rr) if isinstance(rr, dict) and rr else None

        session.pending_roll_data = {
            "team_a": frozenset(prd.get("team_a") or []),
            "team_b": frozenset(prd.get("team_b") or []),
            "low_team": frozenset(prd.get("low_team") or []) if prd.get("low_team") else None,
            "restricted_roles": restricted_roles,
        }
    else:
        session.pending_roll_data = None

    # 47% pair-lock session state
    session.pair_lock_47_disabled = bool(data.get("pair_lock_47_disabled", False))
    session.pair_lock_47_disabled_lobby = (
        tuple(sorted(data.get("pair_lock_47_disabled_lobby") or []))
        if data.get("pair_lock_47_disabled_lobby")
        else None
    )


def _save_session_state(key, session):
    guild_id, channel_id = _session_key_to_ids(key)
    payload_json = json.dumps(_serialize_session(session), ensure_ascii=False)

    c.execute("""
        INSERT INTO session_state (guild_id, channel_id, state_json, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(guild_id, channel_id)
        DO UPDATE SET state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP
    """, (guild_id, channel_id, payload_json))
    conn.commit()


def _load_session_state(key) -> Optional[dict]:
    guild_id, channel_id = _session_key_to_ids(key)
    c.execute("SELECT state_json FROM session_state WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
    row = c.fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _delete_session_state(key):
    guild_id, channel_id = _session_key_to_ids(key)
    c.execute("DELETE FROM session_state WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
    conn.commit()

# ============================================================
# MR API: Tables + Helpers (store ALL match data; bots retained)
# ============================================================


def _is_bot_player(obj: dict) -> bool:
    """
    Best-effort bot detection:
    - obj.is_bot True OR nick_name contains 'bot'
    Handles payloads where nick_name == 'Bot'.
    """
    if not isinstance(obj, dict):
        return False
    if obj.get("is_bot") is True:
        return True
    nick = (obj.get("nick_name") or obj.get("nickname") or "").strip().lower()
    return ("bot" in nick)


def ensure_mr_api_tables():
    """
    Call once on startup AFTER conn/c exist.
    Safe to call multiple times.
    """

    # Map season+match_uid to game_label to prevent double-import
    c.execute("""
        CREATE TABLE IF NOT EXISTS match_imports (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (season_id, match_uid)
        )
    """)

    # Match meta (one row per imported match)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_match_meta (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,

            game_mode_id INTEGER,
            game_mode_name TEXT,
            replay_id TEXT,

            mvp_uid INTEGER,
            mvp_hero_id INTEGER,
            svp_uid INTEGER,
            svp_hero_id INTEGER,

            -- TRUE match-play timestamp (UTC ISO8601) used for season routing (details OR history fallback)
            match_time_utc TEXT,

            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (season_id, match_uid),
            UNIQUE (season_id, game_label)
        )
    """)

    # Migration for existing DBs (safe if column already exists)
    try:
        c.execute("ALTER TABLE mr_match_meta ADD COLUMN match_time_utc TEXT")
    except sqlite3.OperationalError:
        pass

    # Helpful index for time-window queries (0.5 split, season windows, etc.)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_mr_meta_time ON mr_match_meta(season_id, match_time_utc)"
    )

    def _col_exists(table: str, col: str) -> bool:
        c.execute(f"PRAGMA table_info({table})")
        return any(str(r[1]).lower() == col.lower() for r in c.fetchall())

    # Add match_time_utc if missing (safe migration)
    if not _col_exists("mr_match_meta", "match_time_utc"):
        c.execute("ALTER TABLE mr_match_meta ADD COLUMN match_time_utc TEXT")
        # Helps range queries for halves
        c.execute("CREATE INDEX IF NOT EXISTS idx_mr_match_meta_time ON mr_match_meta(season_id, match_time_utc)")
        conn.commit()


    # Store raw match JSON (includes bots)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_match_json_raw (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            json_text TEXT NOT NULL,
            stored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (season_id, match_uid),
            UNIQUE (season_id, game_label)
        )
    """)

    # Store sanitised match JSON (bots removed) for convenience/debug
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_match_json_humans (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            json_text TEXT NOT NULL,
            stored_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (season_id, match_uid),
            UNIQUE (season_id, game_label)
        )
    """)

    # Player totals per match (humans + bots; flagged)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_player_match (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,

            player_uid INTEGER NOT NULL,
            player TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,

            player_icon INTEGER,
            camp INTEGER,

            cur_hero_id INTEGER,
            cur_hero_icon TEXT,

            is_win INTEGER,

            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,

            total_hero_damage REAL,
            total_hero_heal REAL,
            total_damage_taken REAL,

            system TEXT,
            dynamic_name TEXT,
            dynamic_json TEXT,

            PRIMARY KEY (season_id, match_uid, player_uid)
        )
    """)

    # Per-hero segments per player per match (humans + bots; flagged)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_hero_segments (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,

            player_uid INTEGER NOT NULL,
            player TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,

            hero_id INTEGER NOT NULL,
            hero_icon TEXT,

            seconds REAL,
            kills INTEGER,
            deaths INTEGER,
            assists INTEGER,
            session_hit_rate REAL,

            PRIMARY KEY (season_id, match_uid, player_uid, hero_id)
        )
    """)

    # Badges per player per match (humans + bots; flagged)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_player_badges (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,

            player_uid INTEGER NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,

            badge_id INTEGER,
            badge_name TEXT NOT NULL,
            badge_count INTEGER,

            PRIMARY KEY (season_id, match_uid, game_label, player_uid, badge_name)
        )
    """)

    # Ban picks (from match_dynamic_fields.ban_pick_info)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_ban_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,

            round_idx INTEGER,
            battle_side INTEGER,
            conf_id INTEGER,
            is_pick INTEGER,
            vote_type INTEGER,

            hero_id INTEGER,
            raw_json TEXT
        )
    """)

    # HUMAN-ONLY hero time (keeps !hero_time clean)
    c.execute("""
        CREATE TABLE IF NOT EXISTS hero_time_stats (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            player TEXT NOT NULL,
            hero_id TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            PRIMARY KEY (season_id, match_uid, player, hero_id)
        )
    """)

    # ALL hero time (humans + bots) for later bot-only commands
    c.execute("""
        CREATE TABLE IF NOT EXISTS hero_time_stats_all (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            player TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,
            hero_id TEXT NOT NULL,
            seconds INTEGER NOT NULL,
            PRIMARY KEY (season_id, match_uid, player, hero_id, is_bot)
        )
    """)

    # Existing bans convenience table (match-level bans)
    c.execute("""
        CREATE TABLE IF NOT EXISTS hero_bans (
            season_id INTEGER NOT NULL,
            match_uid TEXT NOT NULL,
            game_label TEXT NOT NULL,
            hero_id TEXT NOT NULL
        )
    """)

    # -----------------------------
    # HERO CACHE TABLE (names + roles)
    # -----------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS hero_cache (
            hero_id TEXT PRIMARY KEY,
            hero_name TEXT,
            hero_role TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()

    # migrate older dbs (add missing columns)
    try:
        c.execute("PRAGMA table_info(hero_cache)")
        cols = {str(r[1]).lower() for r in (c.fetchall() or [])}
        if "updated_at" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN updated_at TEXT")
        if "hero_role" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN hero_role TEXT")
        conn.commit()
    except Exception:
        pass

    # Optional: stable identity table (humans + bots)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_players (
            player_uid INTEGER PRIMARY KEY,
            last_seen_name TEXT,
            is_bot INTEGER NOT NULL DEFAULT 0,
            last_seen_system TEXT,
            last_seen_icon INTEGER,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Helpful indexes
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_mr_player_match_game ON mr_player_match(season_id, game_label, is_bot)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_mr_segments_game ON mr_hero_segments(season_id, game_label, is_bot)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_mr_bans_game ON mr_ban_picks(season_id, game_label)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_mr_meta_game ON mr_match_meta(season_id, game_label)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_hero_time_all_game ON hero_time_stats_all(season_id, game_label, is_bot)"
    )

    conn.commit()


def extract_bans_from_md(md: dict) -> list[int]:
    """
    match_details.match_dynamic_fields.ban_pick_info[]
    Returns hero_id ints, de-duped preserving order.
    """
    if not isinstance(md, dict):
        return []

    mdf = md.get("match_dynamic_fields") or {}
    info = mdf.get("ban_pick_info") or []

    out: list[int] = []
    seen = set()

    for entry in info:
        if not isinstance(entry, dict):
            continue
        hid = entry.get("hero_id")
        if hid is None:
            continue
        try:
            hid_i = int(hid)
        except Exception:
            continue

        if hid_i not in seen:
            seen.add(hid_i)
            out.append(hid_i)

    return out


def sanitise_match_payload_humans_only(payload: dict) -> dict:
    """
    Deep-copies payload and removes bot players from match_players.
    Stored into mr_match_json_humans for convenience.
    """
    if not isinstance(payload, dict):
        return {}

    out = json.loads(json.dumps(payload))  # deep copy
    md = (out.get("match_details") or {})
    players = md.get("match_players") or []

    if isinstance(players, list):
        md["match_players"] = [
            p for p in players if isinstance(p, dict) and not _is_bot_player(p)
        ]

    out["match_details"] = md
    return out


def delete_game_everywhere(season_id: int, game_label: str):
    """
    Deletes a game across ALL tables (prevents orphaned hero/bot/human rows).
    Safe to call even if some tables have no rows.
    """
    c.execute(
        "SELECT match_uid FROM match_imports WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    match_uids = [r[0] for r in c.fetchall()]

    # core season stats (HUMANS)
    c.execute("DELETE FROM game_stats WHERE season_id=? AND game_label=?",
              (season_id, game_label))
    c.execute(
        "DELETE FROM streaks WHERE season_id=? AND player IN (SELECT DISTINCT player FROM game_stats WHERE season_id=? AND game_label=?)",
        (season_id, season_id, game_label
         ))  # optional; remove if you prefer streaks to remain historical

    # convenience tables
    c.execute("DELETE FROM hero_time_stats WHERE season_id=? AND game_label=?",
              (season_id, game_label))
    c.execute(
        "DELETE FROM hero_time_stats_all WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    c.execute("DELETE FROM hero_bans WHERE season_id=? AND game_label=?",
              (season_id, game_label))

    # MR tables
    c.execute("DELETE FROM mr_player_match WHERE season_id=? AND game_label=?",
              (season_id, game_label))
    c.execute(
        "DELETE FROM mr_hero_segments WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    c.execute(
        "DELETE FROM mr_player_badges WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    c.execute("DELETE FROM mr_ban_picks WHERE season_id=? AND game_label=?",
              (season_id, game_label))
    c.execute("DELETE FROM mr_match_meta WHERE season_id=? AND game_label=?",
              (season_id, game_label))
    c.execute(
        "DELETE FROM mr_match_json_raw WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    c.execute(
        "DELETE FROM mr_match_json_humans WHERE season_id=? AND game_label=?",
        (season_id, game_label))

    # import markers
    c.execute("DELETE FROM match_imports WHERE season_id=? AND game_label=?",
              (season_id, game_label))

    # belt-and-braces by match_uid
    for mu in match_uids:
        c.execute(
            "DELETE FROM mr_player_match WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM mr_hero_segments WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM mr_player_badges WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute("DELETE FROM mr_ban_picks WHERE season_id=? AND match_uid=?",
                  (season_id, mu))
        c.execute(
            "DELETE FROM mr_match_meta WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM mr_match_json_raw WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM mr_match_json_humans WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM hero_time_stats WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute(
            "DELETE FROM hero_time_stats_all WHERE season_id=? AND match_uid=?",
            (season_id, mu))
        c.execute("DELETE FROM hero_bans WHERE season_id=? AND match_uid=?",
                  (season_id, mu))
        c.execute(
            "DELETE FROM match_imports WHERE season_id=? AND match_uid=?",
            (season_id, mu))

    conn.commit()
    try:
        refresh_season_views()
    except Exception:
        pass

def upsert_match_into_mr_tables(*, season_id: int, game_label: str, payload: dict):
    """
    Stores ALL match data into mr_* tables (humans + bots; flagged),
    while keeping season tables human-only for submit_match.

    Stores:
      - Stores player-level final_hits + solo_kill into mr_player_match (adds cols if missing)
      - Allocates final_hits + solo_kill across multiple heroes per match (kill-share, then time-share fallback)
      - Writes allocated values into mr_hero_segments.final_hits + mr_hero_segments.solo_kills (per hero segment)
    """
    md = (payload or {}).get("match_details") or {}
    match_uid = md.get("match_uid")
    if not match_uid:
        raise RuntimeError("Payload missing match_details.match_uid")

    ensure_mr_api_tables()
    ensure_mr_hero_segments_dht_cols()
    ensure_mr_hero_segments_fhsk_cols()

    # --- ensure mr_player_match has final_hits + solo_kill columns (safe migration) ---
    def _col_exists(table: str, col: str) -> bool:
        try:
            c.execute(f"PRAGMA table_info({table})")
            return any(str(r[1]).lower() == col.lower() for r in (c.fetchall() or []))
        except Exception:
            return False

    try:
        if not _col_exists("mr_player_match", "final_hits"):
            c.execute("ALTER TABLE mr_player_match ADD COLUMN final_hits INTEGER")
        if not _col_exists("mr_player_match", "solo_kill"):
            c.execute("ALTER TABLE mr_player_match ADD COLUMN solo_kill INTEGER")
        conn.commit()
    except Exception:
        # ignore if already exists / locked in older environments
        pass

    # Re-import safety: remove any existing data under this label/season
    delete_game_everywhere(season_id, game_label)

    # --- Match meta ---
    gm = md.get("game_mode") or {}

    # Best-effort match time from match-details payload
    match_time_utc = None
    try:
        dt = _extract_match_datetime_utc(payload)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            match_time_utc = dt.astimezone(timezone.utc).isoformat()
    except Exception:
        match_time_utc = None

    c.execute(
        """
        INSERT INTO mr_match_meta (
            season_id, match_uid, game_label,
            game_mode_id, game_mode_name, replay_id,
            mvp_uid, mvp_hero_id, svp_uid, svp_hero_id,
            match_time_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            season_id, str(match_uid), game_label,
            gm.get("game_mode_id"),
            gm.get("game_mode_name"),
            str(md.get("replay_id")) if md.get("replay_id") is not None else None,
            md.get("mvp_uid"), md.get("mvp_hero_id"),
            md.get("svp_uid"), md.get("svp_hero_id"),
            match_time_utc
        )
    )

    # --- JSON copies ---
    c.execute(
        """
        INSERT INTO mr_match_json_raw (season_id, match_uid, game_label, json_text)
        VALUES (?,?,?,?)
        """,
        (season_id, str(match_uid), game_label, json.dumps(payload))
    )

    humans_only = sanitise_match_payload_humans_only(payload)
    c.execute(
        """
        INSERT INTO mr_match_json_humans (season_id, match_uid, game_label, json_text)
        VALUES (?,?,?,?)
        """,
        (season_id, str(match_uid), game_label, json.dumps(humans_only))
    )

    # --- Import record (dedupe marker) ---
    c.execute(
        """
        INSERT INTO match_imports (season_id, match_uid, game_label)
        VALUES (?,?,?)
        """,
        (season_id, str(match_uid), game_label)
    )

    # --- Ban picks + hero_bans convenience ---
    bans = extract_bans_from_md(md)
    mdf = md.get("match_dynamic_fields") or {}
    ban_info = mdf.get("ban_pick_info") or []

    if isinstance(ban_info, list):
        for entry in ban_info:
            if not isinstance(entry, dict):
                continue
            hid_i = None
            try:
                if entry.get("hero_id") is not None:
                    hid_i = int(entry.get("hero_id"))
            except Exception:
                hid_i = None

            c.execute(
                """
                INSERT INTO mr_ban_picks (
                    season_id, match_uid, game_label,
                    round_idx, battle_side, conf_id, is_pick, vote_type,
                    hero_id, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    season_id, str(match_uid), game_label,
                    entry.get("round_idx"), entry.get("battle_side"),
                    entry.get("conf_id"), entry.get("is_pick"),
                    entry.get("vote_type"), hid_i,
                    json.dumps(entry)
                )
            )

    for hid in bans:
        c.execute(
            """
            INSERT INTO hero_bans (season_id, match_uid, game_label, hero_id)
            VALUES (?,?,?,?)
            """,
            (season_id, str(match_uid), game_label, str(hid))
        )

    # --- Players (humans + bots) ---
    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    # Name strategy:
    # - Humans: canonical names, de-dupe within match
    # - Bots: always suffix with uid (many are named "Bot")
    human_counts: dict[str, int] = {}
    base_name_by_uid: dict[int, str] = {}
    is_bot_by_uid: dict[int, int] = {}

    for p in players:
        if not isinstance(p, dict):
            continue
        uid = p.get("player_uid")
        if uid is None:
            continue
        try:
            uid_i = int(uid)
        except Exception:
            continue

        bot_flag = 1 if _is_bot_player(p) else 0
        is_bot_by_uid[uid_i] = bot_flag

        nick_raw = (p.get("nick_name") or p.get("nickname") or p.get("player_name") or "").strip()
        if not nick_raw:
            nick_raw = "Bot" if bot_flag else f"UID_{uid_i}"

        base = "Bot" if bot_flag else canonical_player_name(nick_raw)
        base_name_by_uid[uid_i] = base

        if bot_flag == 0:
            human_counts[base] = human_counts.get(base, 0) + 1

    def display_name(uid_i: int) -> str:
        base = base_name_by_uid.get(uid_i, f"UID_{uid_i}")
        bot_flag = is_bot_by_uid.get(uid_i, 0)

        if bot_flag == 1:
            return f"{base} ({uid_i})"
        if human_counts.get(base, 0) <= 1:
            return base
        return f"{base} ({uid_i})"

    def _safe_int(x, default=0) -> int:
        try:
            return int(float(x))
        except Exception:
            return int(default)

    def _safe_float(x, default=0.0) -> float:
        try:
            return float(x)
        except Exception:
            return float(default)

    def _player_fh_sk(pdict: dict) -> tuple[int, int]:
        # Player-level totals from API (per match, NOT per hero)
        fh = pdict.get("final_hits")
        sk = pdict.get("solo_kill")  # API uses solo_kill (singular)
        if sk is None:
            sk = pdict.get("solo_kills")
        return _safe_int(fh, 0), _safe_int(sk, 0)

    for p in players:
        if not isinstance(p, dict):
            continue
        uid = p.get("player_uid")
        if uid is None:
            continue
        try:
            uid_i = int(uid)
        except Exception:
            continue

        bot_flag = 1 if _is_bot_player(p) else 0
        player_name = display_name(uid_i)

        dyn = p.get("dynamic_fields") or {}
        system = dyn.get("system") if isinstance(dyn, dict) else None
        dynamic_name = dyn.get("name") if isinstance(dyn, dict) else None
        is_win_flag = _parse_is_win_flag(p.get("is_win"))

        # stable identity
        c.execute(
            """
            INSERT OR REPLACE INTO mr_players
              (player_uid, last_seen_name, is_bot, last_seen_system, last_seen_icon, updated_at)
            VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (uid_i, player_name, bot_flag, system, p.get("player_icon"))
        )

        # player-level FH/SK totals
        fh_total, sk_total = _player_fh_sk(p)

        # mr_player_match includes final_hits and solo_kill.
        c.execute(
            """
            INSERT INTO mr_player_match (
                season_id, match_uid, game_label,
                player_uid, player, is_bot,
                player_icon, camp,
                cur_hero_id, cur_hero_icon,
                is_win,
                kills, deaths, assists,
                total_hero_damage, total_hero_heal, total_damage_taken,
                final_hits, solo_kill,
                system, dynamic_name, dynamic_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                season_id, str(match_uid), game_label,
                uid_i, player_name, bot_flag,
                p.get("player_icon"), p.get("camp"),
                p.get("cur_hero_id"), p.get("cur_hero_icon"), is_win_flag,
                _safe_int(p.get("kills"), 0),
                _safe_int(p.get("deaths"), 0),
                _safe_int(p.get("assists"), 0),
                _safe_float(p.get("total_hero_damage"), 0.0),
                _safe_float(p.get("total_hero_heal"), 0.0),
                _safe_float(p.get("total_damage_taken"), 0.0),
                int(fh_total), int(sk_total),
                system, dynamic_name,
                json.dumps(dyn) if isinstance(dyn, dict) else None
            )
        )

        # badges
        badges = p.get("badges") or []
        if isinstance(badges, list):
            for b in badges:
                if not isinstance(b, dict):
                    continue
                bname = (b.get("name") or "").strip()
                if not bname:
                    continue
                c.execute(
                    """
                    INSERT INTO mr_player_badges (
                        season_id, match_uid, game_label,
                        player_uid, is_bot,
                        badge_id, badge_name, badge_count
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        season_id, str(match_uid), game_label, uid_i, bot_flag,
                        b.get("id"), bname, _safe_int(b.get("count"), 0)
                    )
                )

        # hero segments (+ hero_time convenience)
        heroes = p.get("player_heroes") or []
        if not isinstance(heroes, list):
            heroes = []

        # --- parse hero segments once (we must allocate FH/SK across multiple heroes) ---
        parsed = []
        per_hero_fhsk_present = False

        for h in heroes:
            if not isinstance(h, dict):
                continue
            hid = h.get("hero_id")
            if hid is None:
                continue
            try:
                hid_i = int(hid)
            except Exception:
                continue

            seconds = _safe_float(h.get("play_time"), 0.0)
            hk = _safe_int(h.get("kills"), 0)
            hd = _safe_int(h.get("deaths"), 0)
            ha = _safe_int(h.get("assists"), 0)

            acc = h.get("session_hit_rate")
            try:
                acc_f = float(acc) if acc is not None else None
            except Exception:
                acc_f = None

            # per-hero D/H/T if present in payload
            seg_dmg, seg_heal, seg_taken = _extract_per_hero_dht(h)

            # detect if API ever provides per-hero FH/SK (it usually does NOT; player-level only)
            hf = h.get("final_hits")
            hs = h.get("solo_kill")
            if hs is None:
                hs = h.get("solo_kills")

            if hf is not None or hs is not None:
                per_hero_fhsk_present = True

            parsed.append({
                "h": h,
                "hero_id": hid_i,
                "hero_icon": h.get("hero_icon"),
                "seconds": seconds,
                "kills": hk,
                "deaths": hd,
                "assists": ha,
                "acc_f": acc_f,
                "seg_dmg": seg_dmg,
                "seg_heal": seg_heal,
                "seg_taken": seg_taken,
                "hero_fh_raw": hf,
                "hero_sk_raw": hs,
            })

        # --- allocate FH/SK for this player across hero segments ---
        if parsed:
            if per_hero_fhsk_present:
                # Use per-hero values if provided (rare)
                for e in parsed:
                    e["final_hits"] = float(_safe_int(e.get("hero_fh_raw"), 0))
                    e["solo_kills"] = float(_safe_int(e.get("hero_sk_raw"), 0))
            else:
                total_kills = sum(int(e["kills"]) for e in parsed)
                total_sec = sum(float(e["seconds"]) for e in parsed)

                for e in parsed:
                    if total_kills > 0:
                        share = float(e["kills"]) / float(total_kills)
                    elif total_sec > 0:
                        share = float(e["seconds"]) / float(total_sec)
                    else:
                        share = 0.0

                    e["final_hits"] = float(fh_total) * share
                    e["solo_kills"] = float(sk_total) * share

        # --- write hero segments + hero time tables ---
        for e in parsed:
            hid_i = e["hero_id"]
            seconds = float(e["seconds"])
            hk = int(e["kills"])
            hd = int(e["deaths"])
            ha = int(e["assists"])
            acc_f = e["acc_f"]

            seg_dmg = e["seg_dmg"]
            seg_heal = e["seg_heal"]
            seg_taken = e["seg_taken"]

            alloc_fh = float(e.get("final_hits", 0.0) or 0.0)
            alloc_sk = float(e.get("solo_kills", 0.0) or 0.0)

            c.execute(
                """
                INSERT OR REPLACE INTO mr_hero_segments (
                    season_id, match_uid, game_label,
                    player_uid, player, is_bot,
                    hero_id, hero_icon,
                    seconds, kills, deaths, assists, session_hit_rate,
                    hero_damage, hero_heal, hero_damage_taken,
                    final_hits, solo_kills
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    season_id, str(match_uid), game_label,
                    uid_i, player_name, bot_flag,
                    hid_i, e.get("hero_icon"),
                    seconds, hk, hd, ha, acc_f,
                    seg_dmg, seg_heal, seg_taken,
                    alloc_fh, alloc_sk,
                )
            )

            # ALL hero time
            c.execute(
                """
                INSERT OR REPLACE INTO hero_time_stats_all (
                    season_id, match_uid, game_label,
                    player, is_bot, hero_id, seconds
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    season_id, str(match_uid), game_label,
                    player_name, bot_flag, str(hid_i), int(seconds)
                )
            )

            # HUMAN-ONLY hero time
            if bot_flag == 0:
                c.execute(
                    """
                    INSERT OR REPLACE INTO hero_time_stats (
                        season_id, match_uid, game_label,
                        player, hero_id, seconds
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (season_id, str(match_uid), game_label, player_name, str(hid_i), int(seconds))
                )

    conn.commit()


# --- Compatibility wrapper: allow positional calls for legacy code paths ---
_upsert_match_into_mr_tables_kwonly = upsert_match_into_mr_tables


def upsert_match_into_mr_tables(*args, **kwargs):
    """
    Backwards-compatible wrapper.

    Original function is keyword-only:
      upsert_match_into_mr_tables(season_id=..., game_label=..., payload=...)

    This wrapper allows legacy positional usage:
      upsert_match_into_mr_tables(season_id, game_label, payload)
    """
    if args:
        if len(args) < 3:
            raise TypeError(
                "upsert_match_into_mr_tables requires 3 positional args: season_id, game_label, payload"
            )
        season_id, game_label, payload = args[0], args[1], args[2]
        return _upsert_match_into_mr_tables_kwonly(
            season_id=season_id,
            game_label=game_label,
            payload=payload,
            **kwargs
        )
    return _upsert_match_into_mr_tables_kwonly(**kwargs)


# =========================
# Startup initialisation
# =========================
run_db_migrations(default_season=5)
ensure_session_state_table()

ensure_season_exists(get_current_season_id())
refresh_season_views()

ensure_mr_api_tables()

# ============================================================================================================
# ============================================================================================================
# API helpers
# ============================================================================================================
# ============================================================================================================


def extract_match_id(url_or_id: str) -> str | None:
    """
    Accepts:
      - raw match_uid (contains underscores)
      - rivalsmeta URL like https://rivalsmeta.com/matches/<match_uid>?...
    Returns match_uid.
    """
    if not url_or_id:
        return None
    s = url_or_id.strip()

    rivalsmeta_match_id = match_id_from_rivalsmeta_url(s)
    if rivalsmeta_match_id:
        return rivalsmeta_match_id

    # If it's a URL, last path segment before ?
    if "://" in s:
        try:
            s = s.split("/")[-1].split("?")[0]
        except Exception:
            return None

    # A match_uid typically contains underscores; accept as-is
    return s if s else None


async def mr_api_get_json(path: str) -> dict:
    """
    Calls MarvelRivalsAPI using MR_API_KEY in environment.
    Base: https://marvelrivalsapi.com
    """
    api_key = os.getenv("MR_API_KEY") or os.getenv("MY_API_KEY")
    if not api_key:
        raise RuntimeError("MR_API_KEY is not set in environment secrets.")

    url = f"https://marvelrivalsapi.com{path}"
    headers = {"x-api-key": api_key}

    async with aiohttp.ClientSession() as session:
        async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=25)) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {txt[:300]}")
            return await resp.json()


async def rivalsmeta_get_match_json(match_uid: str, session=None) -> dict:
    """Fetch one public RivalsMeta match and translate it to Jarvis's payload shape."""
    match_uid = str(match_uid or "").strip()
    if not match_uid or len(match_uid) > 160 or not all(
            ch.isdigit() or ch == "_" for ch in match_uid):
        raise RuntimeError("Invalid RivalsMeta match id.")

    url = f"{RIVALSMETA_API_BASE}/matches/{match_uid}"
    headers = {"User-Agent": "Jarvis-Marvel-Rivals-Bot/1.0"}
    async def _fetch(active_session):
        async with active_session.get(url, headers=headers, allow_redirects=False) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"RivalsMeta HTTP {resp.status}: {text[:200]}")
            body = await read_limited_response_body(resp.content)
            try:
                raw = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                content_type = resp.headers.get("Content-Type", "unknown")
                raise RuntimeError(
                    f"RivalsMeta returned invalid JSON ({content_type}, {len(body)} bytes)."
                ) from exc
            return raw

    if session is None:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as owned_session:
            raw = await _fetch(owned_session)
    else:
        raw = await _fetch(session)

    payload = normalise_rivalsmeta_match_payload(raw)
    returned_uid = str(payload["match_details"].get("match_uid") or "")
    if returned_uid != match_uid:
        raise RuntimeError("RivalsMeta returned a different match id.")
    return payload


async def fetch_submit_match_payload(match_or_url: str,
                                     match_uid: str) -> tuple[dict, str]:
    """Use RivalsMeta for its URLs; otherwise fall back to it if the official API fails."""
    if is_rivalsmeta_match_url(match_or_url):
        return await rivalsmeta_get_match_json(match_uid), "RivalsMeta"

    try:
        return await mr_api_get_json(f"/api/v1/match/{match_uid}"), "MarvelRivalsAPI"
    except Exception as official_error:
        try:
            return await rivalsmeta_get_match_json(match_uid), "RivalsMeta fallback"
        except Exception as rivalsmeta_error:
            raise RuntimeError(
                f"Official API failed ({official_error}); RivalsMeta fallback failed ({rivalsmeta_error})."
            ) from rivalsmeta_error


# ------------------------------------------------------------------------------------------------------------
# Hero name resolution + caching
# ------------------------------------------------------------------------------------------------------------

_HERO_NAME_MEMO: dict[str, str] = {}
_HERO_NAME_FETCH_LOCK = asyncio.Lock()
# Avoid surprise API calls from normal display commands. Run !refresh_heroes to populate/update cache.
HERO_NAME_API_FALLBACK_ENABLED = os.getenv("HERO_NAME_API_FALLBACK_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _ensure_hero_cache_schema():
    """
    Ensure hero_cache has required columns.
    (Supports older DBs that pre-date role caching.)
    """
    ensure_mr_api_tables()
    global c, conn

    try:
        c.execute("PRAGMA table_info(hero_cache)")
        cols = {str(r[1]).lower() for r in (c.fetchall() or [])}

        if "updated_at" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN updated_at TEXT")
        if "hero_role" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN hero_role TEXT")

        conn.commit()
    except Exception:
        pass

async def get_hero_name(hero_id: str) -> str:
    """Resolve a hero name for display.

    Supports both raw hero IDs (e.g. 'hero_001') and legacy numeric-only IDs ('001').
    Resolution order:
      1) In-memory memo
      2) hero_cache table (DB)
      3) Fallback API call: /api/v1/heroes/hero/{hero_id} (persist result)

    Returns a prettified name when available, otherwise returns the original hero_id string.
    """
    global c, conn

    raw = _safe_str(hero_id)
    if not raw:
        return raw

    # Build lookup variants (raw first; also digits-only if different)
    variants = [raw]
    digits = _digits_only(raw)
    if digits and digits != raw:
        variants.append(digits)

    # 1) memo
    for key in variants:
        cached = _HERO_NAME_MEMO.get(key)
        if cached:
            return cached

    _ensure_hero_cache_schema()

    # 2) DB
    for key in variants:
        try:
            c.execute("SELECT hero_name FROM hero_cache WHERE hero_id=?", (key,))
            row = c.fetchone()
            if row and row[0]:
                nm = _hero_pretty(str(row[0]))
                if nm:
                    # store in memo for all variants
                    for k2 in variants:
                        _HERO_NAME_MEMO[k2] = nm
                    return nm
        except Exception:
            continue

    # 3) API fallback (single-flight)
    # Disabled by default to keep normal command usage from making surprise API calls.
    # Run !refresh_heroes manually, or set HERO_NAME_API_FALLBACK_ENABLED=true if needed.
    if not HERO_NAME_API_FALLBACK_ENABLED:
        return raw

    async with _HERO_NAME_FETCH_LOCK:
        # re-check memo/db after waiting
        for key in variants:
            cached = _HERO_NAME_MEMO.get(key)
            if cached:
                return cached

        for key in variants:
            try:
                c.execute("SELECT hero_name FROM hero_cache WHERE hero_id=?", (key,))
                row = c.fetchone()
                if row and row[0]:
                    nm = _hero_pretty(str(row[0]))
                    if nm:
                        for k2 in variants:
                            _HERO_NAME_MEMO[k2] = nm
                        return nm
            except Exception:
                pass

        # Try the raw ID first for API (matches API docs), then digits-only if needed
        name = None
        for key in variants:
            try:
                resp = await mr_api_get_json(f"/api/v1/heroes/hero/{key}")
                if isinstance(resp, dict):
                    name = _safe_str(resp.get("name"))
                if name:
                    break
            except Exception:
                continue

        if name:
            now = datetime.now(timezone.utc).isoformat()
            try:
                # persist under ALL variants so both old/new stored IDs resolve
                for key in variants:
                    c.execute(
                        """
                        INSERT INTO hero_cache (hero_id, hero_name, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(hero_id) DO UPDATE SET
                            hero_name = excluded.hero_name,
                            updated_at = excluded.updated_at
                        """,
                        (key, name, now),
                    )
                conn.commit()
            except Exception:
                pass

            nm = _hero_pretty(name)
            if nm:
                for k2 in variants:
                    _HERO_NAME_MEMO[k2] = nm
                return nm

    return raw



# =========================
# Hero Cache Refresh (API -> DB)
# =========================
def _safe_str(x) -> str:
    try:
        if x is None:
            return ""
        s = str(x)
        return s.strip()
    except Exception:
        return ""


from datetime import datetime, timezone, timedelta

async def refresh_hero_cache(force: bool = False) -> int:
    """Pull /api/v1/heroes and upsert into hero_cache (name + role).

    Stores hero IDs in a backward-compatible way:
      - raw ID (e.g. 'hero_001')
      - digits-only alias if applicable (e.g. '001')

    API may return:
      { "heroes": [ ... ] }  or  [ ... ]
    """
    global c, conn

    _ensure_hero_cache_schema()  # must ensure hero_role + updated_at exist

    # Skip refresh if cache is "recent" unless forced
    if not force:
        try:
            c.execute("SELECT MAX(updated_at) FROM hero_cache")
            last = (c.fetchone() or [None])[0]
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) - last_dt < timedelta(days=7):
                        return 0
                except Exception:
                    pass
        except Exception:
            pass

    resp = await mr_api_get_json("/api/v1/heroes")

    heroes_list = None
    if isinstance(resp, dict):
        heroes_list = resp.get("heroes")
    elif isinstance(resp, list):
        heroes_list = resp

    if not isinstance(heroes_list, list):
        return 0

    now = datetime.now(timezone.utc).isoformat()

    updated = 0
    for h in heroes_list:
        if not isinstance(h, dict):
            continue

        hid_raw = _safe_str(h.get("id"))
        name = _safe_str(h.get("name"))
        role = _safe_str(h.get("role"))  # Vanguard, Duelist or Strategist

        if not hid_raw or not name:
            continue

        # Store raw + digits-only alias (if different)
        ids_to_store = [hid_raw]
        hid_digits = _digits_only(hid_raw)
        if hid_digits and hid_digits != hid_raw:
            ids_to_store.append(hid_digits)

        # Pretty name once (store pretty for memo; DB can store raw or pretty—keeping DB as raw string is fine)
        pretty_name = _hero_pretty(name) or name

        for hid in ids_to_store:
            try:
                # check whether this row meaningfully changes (to keep "updated" meaningful)
                c.execute("SELECT hero_name, hero_role FROM hero_cache WHERE hero_id=?", (hid,))
                existing = c.fetchone()
                existing_name = existing[0] if existing else None
                existing_role = existing[1] if existing and len(existing) > 1 else None

                c.execute(
                    """
                    INSERT INTO hero_cache (hero_id, hero_name, hero_role, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(hero_id) DO UPDATE SET
                        hero_name = excluded.hero_name,
                        hero_role = excluded.hero_role,
                        updated_at = excluded.updated_at
                    """,
                    (hid, pretty_name, role, now),
                )

                # count only if changed (name or role) or brand new
                if (existing is None) or (existing_name != pretty_name) or ((role or "") != (existing_role or "")):
                    updated += 1

            except Exception:
                continue

    try:
        conn.commit()
    except Exception:
        pass

    # Keep memo consistent (names + roles)
    if updated:
        for h in heroes_list:
            if not isinstance(h, dict):
                continue
            hid_raw = _safe_str(h.get("id"))
            name = _safe_str(h.get("name"))
            role = _safe_str(h.get("role"))

            if not hid_raw or not name:
                continue

            nm = _hero_pretty(name) or name
            if not nm:
                continue

            _HERO_NAME_MEMO[hid_raw] = nm
            hid_digits = _digits_only(hid_raw)
            if hid_digits and hid_digits != hid_raw:
                _HERO_NAME_MEMO[hid_digits] = nm

            # Optional: if you keep a role memo as well, populate it.
            # Safe even if you have not defined it yet; it will no-op.
            try:
                _HERO_ROLE_MEMO[hid_raw] = role
                if hid_digits and hid_digits != hid_raw:
                    _HERO_ROLE_MEMO[hid_digits] = role
            except Exception:
                pass

    return updated


def _hero_pretty(name: str) -> str:
    s = _safe_str(name).replace("_", " ").strip()
    if not s:
        return s
    # keep '&' and '-' readable; simple Title Case
    return " ".join(w[:1].upper() + w[1:] if w else "" for w in s.split(" "))


def _load_hero_name_map() -> dict[str, str]:
    """Loads hero_id -> prettified hero_name from hero_cache."""
    global c
    m: dict[str, str] = {}
    try:
        c.execute("SELECT hero_id, hero_name FROM hero_cache")
        for hid, nm in c.fetchall():
            hid_s = _safe_str(hid)
            nm_s = _hero_pretty(nm)
            if hid_s and nm_s:
                m[hid_s] = nm_s
    except Exception:
        pass
    return m

# ==========================================================================================
# HERO SEGMENT DAMAGE / HEALING / DAMAGE-TAKEN SUPPORT
# - Ensures per-hero damage/heal/taken columns exist in mr_hero_segments
# - Supports backfilling from mr_match_json_raw when the API provides per-hero fields
# ==========================================================================================

def _mr_has_column(table: str, column: str) -> bool:
    try:
        c.execute(f"PRAGMA table_info({table})")
        return any((row[1] == column) for row in c.fetchall())
    except Exception:
        return False


def ensure_mr_hero_segments_dht_cols() -> None:
    """
    Ensures mr_hero_segments has per-hero damage/heal/taken columns.
    Safe to call repeatedly.
    """
    try:
        ensure_mr_api_tables()
    except Exception:
        # If tables aren't ready yet, let caller handle ordering.
        pass

    cols = [
        ("hero_damage", "REAL"),
        ("hero_heal", "REAL"),
        ("hero_damage_taken", "REAL"),
    ]
    changed = False
    for col, col_type in cols:
        if not _mr_has_column("mr_hero_segments", col):
            try:
                c.execute(f"ALTER TABLE mr_hero_segments ADD COLUMN {col} {col_type}")
                changed = True
            except Exception:
                # Column may already exist or SQLite may reject for other reasons
                pass

    if changed:
        try:
            conn.commit()
        except Exception:
            pass


def _to_float_or_none(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None

def ensure_mr_hero_segments_fhsk_cols() -> None:
    """
    Ensures mr_hero_segments has per-hero Final Hits + Solo Kills columns.
    Safe to call repeatedly.
    """
    try:
        ensure_mr_api_tables()
    except Exception:
        pass

    cols = [
        ("final_hits", "INTEGER"),
        ("solo_kills", "INTEGER"),
    ]
    changed = False
    for col, col_type in cols:
        if not _mr_has_column("mr_hero_segments", col):
            try:
                c.execute(f"ALTER TABLE mr_hero_segments ADD COLUMN {col} {col_type}")
                changed = True
            except Exception:
                pass

    if changed:
        try:
            conn.commit()
        except Exception:
            pass


def _extract_per_hero_final_hits_solo_kills(hero_dict: dict) -> tuple[int, int]:
    """
    Best-effort extraction of per-hero 'Final Hits' and 'Solo Kills' from match_details.player_heroes items.
    Returns (final_hits, solo_kills) as ints (defaults to 0,0).
    """
    if not isinstance(hero_dict, dict):
        return 0, 0

    def _pick_int(keys: list[str]) -> int:
        for k in keys:
            if k in hero_dict and hero_dict.get(k) is not None:
                try:
                    return int(float(hero_dict.get(k)))
                except Exception:
                    pass
        return 0

    final_hits = _pick_int([
        "final_hits", "finalHits",
        "final_blows", "finalBlows",
        "final_hit", "finalHit",
    ])
    solo_kills = _pick_int([
        "solo_kills", "soloKills",
        "solo_kill", "soloKill",
        "solo_elims", "soloElims",
    ])

    return final_hits, solo_kills


def _extract_per_hero_dht(hero_dict: dict) -> tuple[float | None, float | None, float | None]:
    """
    Attempts to read per-hero damage / heal / taken from a hero segment dict.
    Key names vary by API revisions, so we try several.
    """
    if not isinstance(hero_dict, dict):
        return (None, None, None)

    dmg = (
        hero_dict.get("hero_damage")
        or hero_dict.get("damage")
        or hero_dict.get("total_hero_damage")
        or hero_dict.get("total_damage")
    )
    heal = (
        hero_dict.get("hero_heal")
        or hero_dict.get("healing")
        or hero_dict.get("heal")
        or hero_dict.get("total_hero_heal")
        or hero_dict.get("total_heal")
    )
    taken = (
        hero_dict.get("hero_damage_taken")
        or hero_dict.get("damage_taken")
        or hero_dict.get("total_damage_taken")
        or hero_dict.get("taken")
    )

    return (_to_float_or_none(dmg), _to_float_or_none(heal), _to_float_or_none(taken))


@bot.command(name="backfill_hero_dht", aliases=["mr_backfill_hero_dht"])
async def backfill_hero_dht_cmd(ctx, season: int | None = None):
    """
    One-off utility to populate mr_hero_segments.hero_damage/hero_heal/hero_damage_taken
    from stored mr_match_json_raw, if the API payload includes per-hero D/H/T.
    """

    ensure_mr_hero_segments_dht_cols()

    # Default to current season_id if not provided
    try:
        sid = int(season) if season is not None else int(get_current_season_id())
    except Exception:
        await ctx.send("❌ Invalid season.")
        return

    try:
        c.execute(
            "SELECT match_uid, game_label, json_text FROM mr_match_json_raw WHERE season_id = ?",
            (sid,)
        )
        rows = c.fetchall()
    except Exception as e:
        await ctx.send(f"❌ Failed to read mr_match_json_raw: `{type(e).__name__}: {e}`")
        return

    updated = 0
    scanned = 0

    for match_uid, game_label, json_text in rows:
        scanned += 1
        if not json_text:
            continue

        try:
            payload = json.loads(json_text)
        except Exception:
            continue

        md = (payload or {}).get("match_details") or {}
        players = md.get("match_players") or []
        if not isinstance(players, list):
            continue

        for p in players:
            if not isinstance(p, dict):
                continue

            uid = p.get("player_uid")
            if uid is None:
                continue
            try:
                uid_i = int(uid)
            except Exception:
                continue

            # Match table stores bots too; we keep bot-flag consistent
            bot_flag = 1 if _is_bot_player(p) else 0

            heroes = p.get("player_heroes") or []
            if not isinstance(heroes, list):
                continue

            for h in heroes:
                if not isinstance(h, dict):
                    continue

                hid = h.get("hero_id")
                if hid is None:
                    continue
                try:
                    hid_i = int(hid)
                except Exception:
                    continue

                dmg, heal, taken = _extract_per_hero_dht(h)
                if dmg is None and heal is None and taken is None:
                    continue  # nothing to write

                try:
                    c.execute(
                        """
                        UPDATE mr_hero_segments
                        SET hero_damage = COALESCE(?, hero_damage),
                            hero_heal = COALESCE(?, hero_heal),
                            hero_damage_taken = COALESCE(?, hero_damage_taken)
                        WHERE season_id = ?
                          AND match_uid = ?
                          AND player_uid = ?
                          AND hero_id = ?
                          AND is_bot = ?
                        """,
                        (dmg, heal, taken, sid, str(match_uid), uid_i, hid_i, bot_flag)
                    )
                    if c.rowcount and c.rowcount > 0:
                        updated += 1
                except Exception:
                    # Ignore per-row failures; continue backfill
                    continue

    try:
        conn.commit()
    except Exception:
        pass

    await ctx.send(
        f"✅ Backfill complete for Season {sid}. Scanned **{scanned}** matches • Updated **{updated}** hero-segment rows."
    )


# ============================================================================================================
# ============================================================================================================
# Auto Importer (API polling → filter → season-window routing → import)
# ============================================================================================================
# ============================================================================================================
BRIS_TZ = ZoneInfo("Australia/Brisbane")

API_BASE = "https://marvelrivalsapi.com"

# -------------------------
# CONFIG (tune these)
# -------------------------
# Background auto-import is intentionally disabled. The bot imports only when
# !auto_import_run is manually triggered after a session.
AUTO_IMPORT_ENABLED_DEFAULT = False
AUTO_IMPORT_INTERVAL_SECONDS = int(
    os.getenv("AUTO_IMPORT_INTERVAL_SECONDS", "120"))  # kept for compatibility; loop is not started

# Import all game types (ranked/quickplay/custom/etc.)
AUTO_IMPORT_REQUIRE_CUSTOM = False
CUSTOM_MODE_KEYWORDS = ["custom"
                        ]  # additional custom-mode keywords may be added here
ALLOWED_GAME_MODE_IDS = set()  # optional numeric IDs if you learn them later

# Discovery breadth
# These defaults are deliberately conservative to prevent rate-limit pressure.
# Manual import looks back only a few days and stops as soon as it reaches history
# that was already scanned in a previous run.
MATCH_HISTORY_PER_PLAYER_LIMIT = int(os.getenv("MATCH_HISTORY_PER_PLAYER_LIMIT", "20"))
MAX_MATCHES_TO_IMPORT_PER_TICK = int(os.getenv("MAX_MATCHES_TO_IMPORT_PER_TICK", "20"))
AUTO_IMPORT_MAX_LOOKBACK_DAYS = int(os.getenv("AUTO_IMPORT_MAX_LOOKBACK_DAYS", "4"))
AUTO_IMPORT_FIRST_RUN_LOOKBACK_DAYS = int(os.getenv("AUTO_IMPORT_FIRST_RUN_LOOKBACK_DAYS", "7"))
AUTO_IMPORT_HISTORY_PAGE_SIZE = int(os.getenv("AUTO_IMPORT_HISTORY_PAGE_SIZE", "20"))
AUTO_IMPORT_MAX_HISTORY_PAGES = int(os.getenv("AUTO_IMPORT_MAX_HISTORY_PAGES", "2"))
AUTO_IMPORT_HISTORY_REQUEST_DELAY = float(os.getenv("AUTO_IMPORT_HISTORY_REQUEST_DELAY", "0.35"))
AUTO_IMPORT_DETAIL_REQUEST_DELAY = float(os.getenv("AUTO_IMPORT_DETAIL_REQUEST_DELAY", "0.25"))
AUTO_IMPORT_REFRESH_ROSTER_DEFAULT = os.getenv("AUTO_IMPORT_REFRESH_ROSTER_DEFAULT", "false").strip().lower() in ("1", "true", "yes", "on")
AUTO_IMPORT_API_SEASONS_ENV = os.getenv("AUTO_IMPORT_API_SEASONS", "").strip()

# Minimum humans per team (humans = roster players)
MIN_ROSTER_HUMANS_PER_TEAM = 2
MIN_ROSTER_HUMANS_TOTAL = 4

# If roster table is empty, you can optionally fall back to names
ROSTER_NAMES_FALLBACK = set([
    # "NevSONIC", "LatinMaestro", "Texonidas"
])


# -------------------------
# Time / settings helpers
# -------------------------
def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace(
            "Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _norm_name_simple(s: str) -> str:
    return "".join(str(s or "").split()).lower()


def ensure_auto_import_tables():
    """
    Tables used for auto-import housekeeping + roster + season windows + settings.
    Safe to call repeatedly.
    """
    ensure_mr_api_tables()

    # roster: supports UIDs (preferred) + display names (optional)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_roster (
            player_uid INTEGER PRIMARY KEY,
            player_name TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # settings store (enable/disable, cutoff, etc.)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_bot_settings (
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)

    # season windows: Brisbane dates stored as UTC boundaries
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_season_windows (
            season_id INTEGER PRIMARY KEY,
            start_utc TEXT NOT NULL,
            end_utc   TEXT,              -- NULL = open-ended
            note      TEXT
        )
    """)

    # optional season split windows: overrides midpoint split for !leaderboard_image 0.5
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_season_split_windows (
            season_id INTEGER NOT NULL,
            split_label TEXT NOT NULL,
            start_utc TEXT NOT NULL,
            end_utc TEXT NOT NULL,
            note TEXT,
            PRIMARY KEY (season_id, split_label)
        )
    """)

    # skipped matches (auto-import + manual): primarily used to track skipped draws
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_skipped_matches (
            match_uid      TEXT PRIMARY KEY,
            match_time_utc TEXT,
            season_id      INTEGER,
            reason         TEXT,
            source         TEXT,
            details_json   TEXT,
            first_seen_at  TEXT DEFAULT (datetime('now')),
            last_seen_at   TEXT DEFAULT (datetime('now')),
            seen_count     INTEGER DEFAULT 1
        )
    """)

    # Cursor/high-watermark table for API discovery. This prevents manual
    # !auto_import_run from repeatedly re-scanning old history pages.
    c.execute("""
        CREATE TABLE IF NOT EXISTS mr_auto_import_scan_state (
            discovery_key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            api_season TEXT NOT NULL,
            newest_match_time_utc TEXT,
            newest_match_uid TEXT,
            last_scanned_at TEXT,
            last_completed_at TEXT,
            last_error TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_match_imports_match_uid ON match_imports(match_uid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_skipped_matches_reason_uid ON mr_skipped_matches(reason, match_uid)")

    conn.commit()


def _record_skipped_match(
    match_uid: str,
    *,
    match_dt_utc: datetime | None,
    season_id: int | None,
    reason: str,
    source: str,
    details: dict | None = None,
):
    """Persist skipped matches so they can be reported later (e.g., skipped draws)."""
    ensure_auto_import_tables()
    mu = str(match_uid or "").strip()
    if not mu:
        return

    iso = match_dt_utc.astimezone(timezone.utc).isoformat() if isinstance(
        match_dt_utc, datetime) else None
    sid = int(season_id) if season_id is not None else None
    rsn = (reason or "").strip().upper() or "UNKNOWN"
    src = (source or "").strip() or "unknown"

    try:
        details_json = json.dumps(details) if isinstance(details,
                                                         dict) else None
    except Exception:
        details_json = None

    c.execute(
        """
        INSERT INTO mr_skipped_matches(match_uid, match_time_utc, season_id, reason, source, details_json)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(match_uid) DO UPDATE SET
            match_time_utc=COALESCE(excluded.match_time_utc, mr_skipped_matches.match_time_utc),
            season_id=COALESCE(excluded.season_id, mr_skipped_matches.season_id),
            reason=excluded.reason,
            source=excluded.source,
            details_json=COALESCE(excluded.details_json, mr_skipped_matches.details_json),
            last_seen_at=datetime('now'),
            seen_count=mr_skipped_matches.seen_count + 1
        """,
        (mu, iso, sid, rsn, src, details_json),
    )
    conn.commit()


def _get_setting(key: str, default: str | None = None) -> str | None:
    ensure_auto_import_tables()
    c.execute("SELECT v FROM mr_bot_settings WHERE k=?", (key, ))
    r = c.fetchone()
    return str(r[0]) if r and r[0] is not None else default


def _set_setting(key: str, value: str):
    ensure_auto_import_tables()
    c.execute(
        """
        INSERT INTO mr_bot_settings(k, v) VALUES(?, ?)
        ON CONFLICT(k) DO UPDATE SET v=excluded.v
    """, (key, str(value)))
    conn.commit()


def _is_auto_import_enabled() -> bool:
    v = _get_setting("auto_import_enabled", None)
    if v is None:
        return bool(AUTO_IMPORT_ENABLED_DEFAULT)
    return str(v).strip().lower() in ("1", "true", "yes", "on", "enabled")


def _bris_to_utc_iso(date_str: str, *, end_of_day: bool) -> str:
    """
    date_str: 'YYYY-MM-DD' in Brisbane time.
    end_of_day=False => 00:00:00
    end_of_day=True  => 23:59:59
    Returns UTC ISO string.
    """
    dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    else:
        dt = dt.replace(hour=0, minute=0, second=0)
    dt_bris = dt.replace(tzinfo=BRIS_TZ)
    dt_utc = dt_bris.astimezone(timezone.utc)
    return dt_utc.isoformat()


def set_season_window(season_id: int,
                      start_bris: str,
                      end_bris: str | None,
                      note: str = ""):
    ensure_auto_import_tables()
    start_utc = _bris_to_utc_iso(start_bris, end_of_day=False)
    end_utc = _bris_to_utc_iso(end_bris, end_of_day=True) if end_bris else None
    c.execute(
        """
        INSERT INTO mr_season_windows(season_id, start_utc, end_utc, note)
        VALUES(?,?,?,?)
        ON CONFLICT(season_id) DO UPDATE SET
            start_utc=excluded.start_utc,
            end_utc=excluded.end_utc,
            note=excluded.note
    """, (int(season_id), start_utc, end_utc, (note or "").strip()))
    conn.commit()


def list_season_windows() -> list[dict]:
    ensure_auto_import_tables()
    c.execute(
        "SELECT season_id, start_utc, end_utc, note FROM mr_season_windows ORDER BY season_id ASC"
    )
    out = []
    for sid, su, eu, note in c.fetchall():
        su_dt = _parse_iso_utc(su).astimezone(BRIS_TZ) if su else None
        eu_dt = _parse_iso_utc(eu).astimezone(BRIS_TZ) if eu else None
        out.append({
            "season_id": int(sid),
            "start_bris": su_dt.strftime("%Y-%m-%d") if su_dt else "—",
            "end_bris": eu_dt.strftime("%Y-%m-%d") if eu_dt else "OPEN",
            "note": note or ""
        })
    return out


def _normalise_season_split_label(split_label: str) -> str:
    raw = str(split_label or "").strip().lower().replace("_", "-")
    if raw in ("0", "0.0", "first", "first-half", "firsthalf", "season0"):
        return "0"
    if raw in ("0.5", ".5", "5", "half", "second", "second-half", "secondhalf", "season5"):
        return "0.5"
    raise ValueError("Split must be `0` or `0.5`.")


def set_season_split_window(season_id: int,
                            split_label: str,
                            start_bris: str,
                            end_bris: str,
                            note: str = ""):
    ensure_auto_import_tables()
    label = _normalise_season_split_label(split_label)
    if not end_bris or str(end_bris).strip().upper() == "OPEN":
        raise ValueError("Split windows need a concrete end date.")

    start_utc = _bris_to_utc_iso(start_bris, end_of_day=False)
    end_utc = _bris_to_utc_iso(end_bris, end_of_day=True)

    split_start = _parse_iso_utc(start_utc)
    split_end = _parse_iso_utc(end_utc)
    if split_start and split_end and split_start > split_end:
        raise ValueError("Split start must be on or before the split end.")

    c.execute(
        """
        SELECT start_utc, end_utc
        FROM mr_season_windows
        WHERE season_id=?
        """,
        (int(season_id),),
    )
    season_row = c.fetchone()
    if season_row and season_row[0] and season_row[1]:
        season_start = _parse_iso_utc(season_row[0])
        season_end = _parse_iso_utc(season_row[1])
        if split_start and season_start and split_start < season_start:
            raise ValueError("Split start must be inside the main season window.")
        if split_end and season_end and split_end > season_end:
            raise ValueError("Split end must be inside the main season window.")

    c.execute(
        """
        INSERT INTO mr_season_split_windows(season_id, split_label, start_utc, end_utc, note)
        VALUES(?,?,?,?,?)
        ON CONFLICT(season_id, split_label) DO UPDATE SET
            start_utc=excluded.start_utc,
            end_utc=excluded.end_utc,
            note=excluded.note
        """,
        (int(season_id), label, start_utc, end_utc, (note or "").strip()),
    )
    conn.commit()


def list_season_split_windows(season_id: int | None = None) -> list[dict]:
    ensure_auto_import_tables()
    if season_id is None:
        c.execute(
            """
            SELECT season_id, split_label, start_utc, end_utc, note
            FROM mr_season_split_windows
            ORDER BY season_id ASC, split_label ASC
            """
        )
    else:
        c.execute(
            """
            SELECT season_id, split_label, start_utc, end_utc, note
            FROM mr_season_split_windows
            WHERE season_id=?
            ORDER BY split_label ASC
            """,
            (int(season_id),),
        )

    out = []
    for sid, label, su, eu, note in c.fetchall():
        su_dt = _parse_iso_utc(su).astimezone(BRIS_TZ) if su else None
        eu_dt = _parse_iso_utc(eu).astimezone(BRIS_TZ) if eu else None
        out.append({
            "season_id": int(sid),
            "split_label": str(label),
            "start_bris": su_dt.strftime("%Y-%m-%d") if su_dt else "-",
            "end_bris": eu_dt.strftime("%Y-%m-%d") if eu_dt else "-",
            "note": note or "",
        })
    return out


def resolve_season_for_match_time(match_dt_utc: datetime) -> int | None:
    """
    Returns season_id whose window contains match_dt_utc.
    If no windows exist, returns None.
    """
    ensure_auto_import_tables()
    c.execute("SELECT COUNT(*) FROM mr_season_windows")
    n = int((c.fetchone() or [0])[0])
    if n <= 0:
        return None

    iso = match_dt_utc.astimezone(timezone.utc).isoformat()
    c.execute(
        """
        SELECT season_id
        FROM mr_season_windows
        WHERE start_utc <= ?
          AND (end_utc IS NULL OR end_utc >= ?)
        ORDER BY season_id DESC
        LIMIT 1
    """, (iso, iso))
    r = c.fetchone()
    return int(r[0]) if r else None


def get_auto_import_cutoff_utc() -> datetime:
    """
    Returns the configured import cutoff.

    Older builds defaulted this to "now", which could cause the first manual
    import after a session to miss games from earlier that night. For the manual
    importer, default to a short first-run lookback instead. The active scan still
    applies AUTO_IMPORT_MAX_LOOKBACK_DAYS, so this does not create large backfills.
    """
    v = _get_setting("auto_import_cutoff_utc", None)
    if not v:
        dt = datetime.now(timezone.utc) - timedelta(days=max(1, int(AUTO_IMPORT_FIRST_RUN_LOOKBACK_DAYS)))
        _set_setting("auto_import_cutoff_utc", dt.isoformat())
        return dt
    dt = _parse_iso_utc(v)
    if dt is None:
        dt = datetime.now(timezone.utc) - timedelta(days=max(1, int(AUTO_IMPORT_FIRST_RUN_LOOKBACK_DAYS)))
        _set_setting("auto_import_cutoff_utc", dt.isoformat())
    return dt


def _effective_auto_import_cutoff_utc(lookback_days: int | None = None) -> datetime:
    """Return the stricter of the stored cutoff and the rolling lookback window."""
    try:
        days = int(lookback_days) if lookback_days is not None else int(AUTO_IMPORT_MAX_LOOKBACK_DAYS)
    except Exception:
        days = int(AUTO_IMPORT_MAX_LOOKBACK_DAYS)
    days = max(1, min(days, 14))

    configured_cutoff = get_auto_import_cutoff_utc()
    rolling_cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return max(configured_cutoff, rolling_cutoff)


def set_auto_import_cutoff_bris(date_str: str):
    """
    date_str: YYYY-MM-DD in Brisbane time. Cutoff uses 00:00 that day.
    """
    iso = _bris_to_utc_iso(date_str, end_of_day=False)
    _set_setting("auto_import_cutoff_utc", iso)


def _extract_match_datetime_utc(payload: dict) -> datetime | None:
    """
    Robust extractor: tries common fields in match_details.
    """
    md = (payload or {}).get("match_details") or {}

    # ISO string candidates
    for k in [
            "match_start_time", "start_time", "started_at", "match_time",
            "created_at"
    ]:
        v = md.get(k)
        if isinstance(v, str) and v.strip():
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

    # epoch ms candidates
    for k in ["match_start_time_ms", "start_time_ms", "timestamp_ms"]:
        v = md.get(k)
        try:
            if v is not None:
                ms = int(v)
                if ms > 10_000_000_000:
                    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except Exception:
            pass

    # epoch seconds candidates
    for k in [
            "match_start_time_s", "start_time_s", "timestamp_s", "timestamp"
    ]:
        v = md.get(k)
        try:
            if v is not None:
                s = int(v)
                if 1_000_000_000 < s < 50_000_000_000:
                    return datetime.fromtimestamp(s, tz=timezone.utc)
        except Exception:
            pass

    return None


# -------------------------
# Roster helpers (UIDs preferred)
# -------------------------
def _roster_uids_and_names() -> tuple[set[int], set[str]]:
    ensure_auto_import_tables()
    c.execute("SELECT player_uid, player_name FROM mr_roster WHERE enabled=1")
    uids = set()
    names = set()
    for uid, nm in c.fetchall():
        if uid is not None:
            try:
                uids.add(int(uid))
            except Exception:
                pass
        if nm:
            names.add(_norm_name_simple(nm))

    if not uids and not names and ROSTER_NAMES_FALLBACK:
        names |= {_norm_name_simple(x) for x in ROSTER_NAMES_FALLBACK}

    return uids, names


def _is_roster_human(player_uid, player_name, roster_uids: set[int],
                     roster_names_norm: set[str]) -> bool:
    if player_uid is not None:
        try:
            if int(player_uid) in roster_uids:
                return True
        except Exception:
            pass
    if player_name:
        if _norm_name_simple(player_name) in roster_names_norm:
            return True
    return False


# -------------------------
# API
# -------------------------
async def _api_get_json(path: str, session: "aiohttp.ClientSession"):
    api_key = os.getenv("MR_API_KEY") or os.getenv("MY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MR_API_KEY (or MY_API_KEY) not set in environment.")

    url = API_BASE + path
    headers = {"x-api-key": api_key}

    async with session.get(url, headers=headers) as resp:
        if resp.status == 429:
            raise RuntimeError("RATE_LIMIT_429")
        if resp.status >= 400:
            text = await resp.text()
            raise RuntimeError(f"API_ERROR_{resp.status}: {text[:200]}")
        return await resp.json()


async def _fetch_match_history_for_player(query: str,
                                          session: "aiohttp.ClientSession",
                                          skip: int = 0,
                                          season: str = None,
                                          game_mode: int = None):
    q = urllib.parse.quote(str(query))
    params = [f"skip={int(skip)}"]
    if season is not None and str(season).strip() != "":
        params.append(f"season={urllib.parse.quote(str(season).strip())}")
    if game_mode is not None:
        params.append(f"game_mode={int(game_mode)}")
    path = f"/api/v1/player/{q}/match-history?" + "&".join(params)
    return await _api_get_json(path, session)


async def _fetch_match_details(match_uid: str,
                               session: "aiohttp.ClientSession"):
    m = urllib.parse.quote(str(match_uid))
    path = f"/api/v1/match/{m}"
    return await _api_get_json(path, session)

# -------------------------
# API: player refresh (update endpoint)
# -------------------------
async def _api_get_any(path: str, session: "aiohttp.ClientSession") -> dict:
    """
    GET helper that tolerates either JSON or plain-text responses.
    Returns a dict with keys:
      - ok: bool
      - status: int
      - data: parsed JSON (if any)
      - text: raw text (if any)
    """
    api_key = os.getenv("MR_API_KEY") or os.getenv("MY_API_KEY")
    if not api_key:
        raise RuntimeError("MR_API_KEY (or MY_API_KEY) not set in environment.")

    url = API_BASE + path
    headers = {"x-api-key": api_key}

    async with session.get(url, headers=headers) as resp:
        status = resp.status

        if status == 429:
            raise RuntimeError("RATE_LIMIT_429")
        if status >= 400:
            # include a small snippet for diagnostics
            txt = await resp.text()
            raise RuntimeError(f"API_ERROR_{status}: {txt[:200]}")

        # Try JSON first; fall back to text
        try:
            data = await resp.json()
            return {"ok": True, "status": status, "data": data, "text": None}
        except Exception:
            txt = await resp.text()
            return {"ok": True, "status": status, "data": None, "text": txt}


async def _trigger_player_update(query: str, session: "aiohttp.ClientSession") -> dict:
    """
    Triggers MarvelRivalsAPI player refresh queue for a specific player query (uid or name).
    Endpoint: /api/v1/player/{query}/update
    """
    q = urllib.parse.quote(str(query))
    path = f"/api/v1/player/{q}/update"
    return await _api_get_any(path, session)


async def _update_roster_players_trigger(
    *,
    roster_uids: list[int],
    ctx: "commands.Context" = None,
    concurrency: int = 3,
    per_call_delay_s: float = 0.25,
) -> dict:
    """
    Triggers player update for each roster uid.
    - Concurrency capped to reduce 429s
    - Retries with backoff on 429
    Returns summary dict.
    """
    if aiohttp is None:
        raise RuntimeError("aiohttp missing; cannot call API.")

    # Safety: empty roster
    if not roster_uids:
        return {"total": 0, "queued": 0, "failed": 0, "failures": []}

    timeout = aiohttp.ClientTimeout(total=25)
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    results = {"total": len(roster_uids), "queued": 0, "failed": 0, "failures": []}

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def _one(uid: int):
            async with sem:
                # Retry on 429 with exponential backoff
                backoff = 1.2
                for attempt in range(1, 5):  # 4 attempts max
                    try:
                        await _trigger_player_update(str(uid), session)
                        results["queued"] += 1
                        # small pacing delay to be gentle to the API
                        await asyncio.sleep(per_call_delay_s)
                        return
                    except Exception as e:
                        msg = str(e)
                        if "RATE_LIMIT_429" in msg and attempt < 4:
                            await asyncio.sleep(backoff)
                            backoff *= 1.8
                            continue
                        results["failed"] += 1
                        results["failures"].append({"uid": uid, "error": msg[:200]})
                        return

        # Fire tasks
        tasks_ = [asyncio.create_task(_one(uid)) for uid in roster_uids]
        await asyncio.gather(*tasks_)

    # Optional: short feedback to Discord
    if ctx is not None:
        await ctx.send(
            f"Roster refresh queued: **{results['queued']}** / **{results['total']}** "
            f"(failed **{results['failed']}**)."
        )
        if results["failed"] > 0:
            # Show up to 8 failures
            sample = results["failures"][:8]
            lines = [f"- {x['uid']}: {x['error']}" for x in sample]
            await ctx.send("Some refresh failures:\n" + "\n".join(lines))

    return results


# -------------------------
# Filters
# -------------------------
def _is_custom_match(payload: dict) -> bool:
    if not AUTO_IMPORT_REQUIRE_CUSTOM:
        return True

    md = (payload or {}).get("match_details") or {}

    # Some payloads use nested game_mode
    nested = md.get("game_mode") or {}
    mode_name = str(
        md.get("game_mode_name") or nested.get("game_mode_name")
        or nested.get("game_mode") or "").lower()

    mode_id = md.get("game_mode_id")
    if mode_id is None:
        mode_id = nested.get("game_mode_id")

    if mode_id is not None:
        try:
            if int(mode_id) in ALLOWED_GAME_MODE_IDS:
                return True
        except Exception:
            pass

    return any(k in mode_name for k in CUSTOM_MODE_KEYWORDS)


def _parse_is_win_flag(raw) -> int | None:
    """Normalises the API's is_win field.

    Expected outcomes:
      - 1 = win
      - 0 = loss
      - 2 = draw
      - None = unknown
    """
    w = raw
    if isinstance(w, dict):
        w = w.get("is_win")

    if w is None:
        return None

    if isinstance(w, bool):
        return 1 if w else 0

    if isinstance(w, (int, float)):
        try:
            i = int(w)
        except Exception:
            return None
        return i if i in (0, 1, 2) else None

    if isinstance(w, str):
        ws = w.strip().lower()
        if ws in ("1", "true", "yes", "win", "w"):
            return 1
        if ws in ("0", "false", "no", "loss", "lose", "l"):
            return 0
        if ws in ("2", "draw", "tie"):
            return 2

    return None


def _is_draw_match(payload: dict) -> bool:
    """Returns True when the payload clearly represents a draw/tie.

    The Marvel Rivals API commonly encodes draws as is_win=2 for each player.
    """
    md = (payload or {}).get("match_details") or {}

    # Explicit draw markers (if present)
    winner_side_raw = md.get("match_winner_side")
    if isinstance(winner_side_raw, str):
        if winner_side_raw.strip().lower() in ("draw", "tie", "none"):
            return True

    # Score-based draw check (if available)
    score_info = md.get("score_info")
    if isinstance(score_info, dict) and len(score_info) >= 2:
        try:
            scores = [int(v) for v in score_info.values() if v is not None]
            if len(scores) >= 2 and len(set(scores)) == 1:
                return True
        except Exception:
            pass

    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    # is_win=2 is the primary draw signal
    for p in players:
        if not isinstance(p, dict):
            continue
        if _is_bot_player(p):
            continue
        if _parse_is_win_flag(p.get("is_win")) == 2:
            return True

    return False


def _is_draw_or_invalid_result(payload: dict) -> bool:
    md = (payload or {}).get("match_details") or {}

    # If explicit draw markers exist
    winner_side_raw = md.get("match_winner_side")
    winner_side_str = str(winner_side_raw).strip().lower()
    if winner_side_str in ("draw", "tie", "none", ""):
        return True

    # Score-based draw check (if available)
    score_info = md.get("score_info")
    if isinstance(score_info, dict) and len(score_info) >= 2:
        try:
            scores = [int(v) for v in score_info.values() if v is not None]
            if len(scores) >= 2 and len(set(scores)) == 1:
                # e.g. 0-0 or 1-1 treated as draw/invalid
                return True
        except Exception:
            pass

    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    wins = 0
    losses = 0

    for p in players:
        if not isinstance(p, dict):
            continue
        if _is_bot_player(p):
            continue

        w = p.get("is_win")

        # API may return:
        # - bool True/False
        # - int 1/0
        # - string "1"/"0"/"true"/"false"
        # - dict like {"score": 1, "is_win": true}
        if isinstance(w, dict):
            w = w.get("is_win")

        if isinstance(w, bool):
            if w:
                wins += 1
            else:
                losses += 1
        elif isinstance(w, (int, float)):
            if int(w) == 1:
                wins += 1
            elif int(w) == 0:
                losses += 1
        elif isinstance(w, str):
            ws = w.strip().lower()
            if ws in ("1", "true", "yes", "win"):
                wins += 1
            elif ws in ("0", "false", "no", "loss", "lose"):
                losses += 1

    # If we cannot determine both sides exist, treat as invalid
    return (wins == 0 or losses == 0)


def _passes_min_humans_each_team(payload: dict) -> bool:
    """
    Import guard:
    - Only import games with roster participation:
        * at least MIN_ROSTER_HUMANS_TOTAL rostered players overall
        * at least MIN_ROSTER_HUMANS_PER_TEAM rostered players on each of the 2 teams
    """
    roster_uids, roster_names_norm = _roster_uids_and_names()
    if not roster_uids and not roster_names_norm:
        # Without roster, cannot enforce reliably.
        return False

    md = (payload or {}).get("match_details") or {}
    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    roster_humans_by_team = defaultdict(int)
    roster_humans_total = 0

    for p in players:
        if not isinstance(p, dict):
            continue
        if _is_bot_player(p):
            continue

        uid = p.get("player_uid")
        name = (p.get("nick_name") or p.get("nickname") or p.get("player_name")
                or p.get("player") or "")
        name = str(name).strip() if name else None

        if not _is_roster_human(uid, name, roster_uids, roster_names_norm):
            continue

        camp = p.get("camp")
        if camp is None:
            continue
        try:
            camp_i = int(camp)
        except Exception:
            continue

        roster_humans_by_team[camp_i] += 1
        roster_humans_total += 1

    # Need exactly two teams represented by rostered players
    teams = [t for t, ct in roster_humans_by_team.items() if ct > 0]
    if len(teams) != 2:
        return False

    # Total rostered players requirement
    if roster_humans_total < int(MIN_ROSTER_HUMANS_TOTAL):
        return False

    # Minimum rostered players per team requirement
    return all(roster_humans_by_team[t] >= int(MIN_ROSTER_HUMANS_PER_TEAM)
               for t in teams)


# -------------------------
# Game label + importing
# -------------------------
def _next_game_label_for_season(season_id: int) -> str:
    try:
        c.execute(
            "SELECT COUNT(DISTINCT game_label) FROM game_stats WHERE season_id=?",
            (season_id, ))
        n = int((c.fetchone() or [0])[0]) + 1
        return f"Game_{n}"
    except Exception:
        pass

    c.execute(
        "SELECT COUNT(DISTINCT game_label) FROM game_stats_v WHERE season_id=?",
        (season_id, ))
    n = int((c.fetchone() or [0])[0]) + 1
    return f"Game_{n}"


def _already_imported_in_any_season(match_uid: str) -> bool:
    ensure_mr_api_tables()
    c.execute("SELECT 1 FROM match_imports WHERE match_uid=? LIMIT 1",
              (str(match_uid), ))
    return c.fetchone() is not None

def _set_imported_match_time_utc(match_uid: str, match_dt_utc: datetime) -> None:
    """
    Persist the authoritative match-play timestamp (UTC) for an imported match.
    This must use the SAME timestamp used for season routing in auto-import.
    """
    if not match_uid or not isinstance(match_dt_utc, datetime):
        return

    ensure_mr_api_tables()

    dt = match_dt_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso = dt.astimezone(timezone.utc).isoformat()

    # Update across any season rows for safety (match_uid should be globally unique, but this is robust)
    c.execute(
        "UPDATE mr_match_meta SET match_time_utc=? WHERE match_uid=?",
        (iso, str(match_uid)),
    )
    conn.commit()


def _already_skipped_match(match_uid: str,
                           *,
                           reason: str | None = None) -> bool:
    """Returns True if the match_uid has been recorded as skipped."""
    ensure_auto_import_tables()
    if reason:
        c.execute(
            "SELECT 1 FROM mr_skipped_matches WHERE match_uid=? AND reason=? LIMIT 1",
            (str(match_uid), str(reason)),
        )
    else:
        c.execute("SELECT 1 FROM mr_skipped_matches WHERE match_uid=? LIMIT 1",
                  (str(match_uid), ))
    return c.fetchone() is not None


async def _import_match_into_season(
    match_uid: str,
    payload: dict,
    season_id: int,
    match_dt_utc: datetime | None = None,
):
    """
    Imports one match into a specific season_id:
      - writes mr_* tables
      - writes game_stats rows (human-only)
      - records match_imports
      - persists match_time_utc (TRUE match timestamp used for season routing)
    """
    ensure_mr_api_tables()
    ensure_auto_import_tables()

    season_id = int(season_id)
    game_label = _next_game_label_for_season(season_id)

    # Store API-native match payload (includes bots)
    upsert_match_into_mr_tables(season_id=season_id, game_label=game_label, payload=payload)

    # Store human-only season stats used by leaderboards.
    if "write_season_rows_from_match_payload" not in globals():
        raise RuntimeError("Missing helper: write_season_rows_from_match_payload(...)")

    write_season_rows_from_match_payload(
        season_id,
        game_label,
        payload,
        overwrite_label=True,
        update_streaks_flag=True
    )

    # Record import (prevents duplicates)
    c.execute(
        """
        INSERT INTO match_imports(season_id, match_uid, game_label, imported_at)
        VALUES(?,?,?,?)
        ON CONFLICT(season_id, match_uid) DO NOTHING
        """,
        (season_id, str(match_uid), str(game_label), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()

    # Persist authoritative match timestamp (use the same value used for season routing)
    try:
        dt = match_dt_utc or _extract_match_datetime_utc(payload)
        if isinstance(dt, datetime):
            _set_imported_match_time_utc(match_uid, dt)
    except Exception:
        pass

# -------------------------
# Auto-import scan state / cursor helpers
# -------------------------
def _auto_import_scan_key(query: str, api_season: str) -> str:
    return f"{str(query).strip()}::{str(api_season).strip()}"


def _history_match_uid(item: dict) -> str:
    return str((item or {}).get("match_uid") or "").strip()


def _history_item_datetime_utc(item: dict) -> datetime | None:
    ts = (item or {}).get("match_time_stamp") or (item or {}).get("match_timestamp") or (item or {}).get("match_time")
    if ts is None:
        return None
    try:
        raw = int(ts)
        # tolerate either seconds or milliseconds
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    except Exception:
        return None


def _get_auto_import_scan_state(query: str, api_season: str) -> dict:
    ensure_auto_import_tables()
    key = _auto_import_scan_key(query, api_season)
    c.execute(
        """
        SELECT newest_match_time_utc, newest_match_uid, last_scanned_at, last_completed_at, last_error
        FROM mr_auto_import_scan_state
        WHERE discovery_key=?
        """,
        (key,),
    )
    row = c.fetchone()
    if not row:
        return {}
    return {
        "newest_match_time_utc": row[0],
        "newest_match_uid": row[1],
        "last_scanned_at": row[2],
        "last_completed_at": row[3],
        "last_error": row[4],
    }


def _set_auto_import_scan_state(query: str, api_season: str, *, newest_dt: datetime | None, newest_match_uid: str | None, completed: bool, error: str | None = None) -> None:
    ensure_auto_import_tables()
    key = _auto_import_scan_key(query, api_season)
    now_iso = datetime.now(timezone.utc).isoformat()
    newest_iso = newest_dt.astimezone(timezone.utc).isoformat() if isinstance(newest_dt, datetime) else None
    c.execute(
        """
        INSERT INTO mr_auto_import_scan_state (
            discovery_key, query, api_season, newest_match_time_utc, newest_match_uid,
            last_scanned_at, last_completed_at, last_error
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(discovery_key) DO UPDATE SET
            query=excluded.query,
            api_season=excluded.api_season,
            newest_match_time_utc=COALESCE(excluded.newest_match_time_utc, mr_auto_import_scan_state.newest_match_time_utc),
            newest_match_uid=COALESCE(excluded.newest_match_uid, mr_auto_import_scan_state.newest_match_uid),
            last_scanned_at=excluded.last_scanned_at,
            last_completed_at=CASE WHEN ? THEN excluded.last_completed_at ELSE mr_auto_import_scan_state.last_completed_at END,
            last_error=excluded.last_error
        """,
        (key, str(query), str(api_season), newest_iso, newest_match_uid, now_iso, now_iso if completed else None, error, 1 if completed else 0),
    )
    conn.commit()


def _clear_auto_import_scan_state() -> None:
    ensure_auto_import_tables()
    c.execute("DELETE FROM mr_auto_import_scan_state")
    conn.commit()


def _get_auto_import_api_seasons() -> list[str]:
    """Return the API season(s) to scan. Defaults to current season + half-season only."""
    raw = _get_setting("auto_import_api_seasons", None) or AUTO_IMPORT_API_SEASONS_ENV
    if raw:
        seasons = [x.strip() for x in str(raw).replace(";", ",").split(",") if x.strip()]
        if seasons:
            return seasons

    try:
        sid = int(get_current_season_id())
    except Exception:
        sid = 7

    # Marvel Rivals API separates x and x.5; Jarvis stores both under one season id.
    return [f"{sid}.5", str(sid)]


def _parse_auto_import_run_args(args) -> dict:
    """Parse optional !auto_import_run arguments without breaking the existing command."""
    opts = {
        "lookback_days": int(AUTO_IMPORT_MAX_LOOKBACK_DAYS),
        "refresh_roster": bool(AUTO_IMPORT_REFRESH_ROSTER_DEFAULT),
        "reset_cursor": False,
        "provider": "auto",
    }
    for raw in args or []:
        a = str(raw).strip().lower()
        if not a:
            continue
        if a in ("refresh", "--refresh", "update", "--update"):
            opts["refresh_roster"] = True
        elif a in ("no_refresh", "no-refresh", "--no-refresh", "norefresh"):
            opts["refresh_roster"] = False
        elif a in ("reset_cursor", "reset-cursor", "--reset-cursor", "reset"):
            opts["reset_cursor"] = True
        elif a in ("rivalsmeta", "--rivalsmeta", "fallback", "--fallback"):
            opts["provider"] = "rivalsmeta"
        elif a.startswith("days=") or a.startswith("--days="):
            try:
                opts["lookback_days"] = int(a.split("=", 1)[1])
            except Exception:
                pass
        elif a.isdigit():
            opts["lookback_days"] = int(a)

    opts["lookback_days"] = max(1, min(int(opts["lookback_days"]), 14))
    return opts

# -------------------------
# Core tick (loop + manual command share this)
# -------------------------

AUTO_IMPORT_RUN_LOCK = asyncio.Lock()

# API seasons ordered newest to oldest.
API_SEASON_ORDER = [
    "8.5", "8", "7.5", "7", "6.5", "6", "5.5", "5", "4.5", "4", "3.5", "3", "2.5", "2", "1.5", "1", "0.5", "0"
]

async def _auto_import_tick(
    bot: commands.Bot,
    *,
    force: bool = False,
    status_cb=None,
    lookback_days: int | None = None,
    provider: str = "auto",
):
    """
    Manual importer, optimised for low API usage.

    Key behaviours:
      - No background polling.
      - Scans only current API season + half-season by default.
      - Uses a rolling lookback window (default 4 days).
      - Persists a per-player/per-API-season cursor so old history is not re-scanned.
      - Fetches match details only for genuinely new, unimported, unskipped candidate matches.
      - Falls back to RivalsMeta roster histories and match details when the official API fails.
    """
    def _status(phase: str = None, detail: str = None):
        if status_cb:
            try:
                status_cb(phase=phase, detail=detail)
            except Exception:
                pass

    async with AUTO_IMPORT_RUN_LOCK:
        _status("Initial checks…", "validating aiohttp / roster / scan settings")

        # Manual runs can bypass the legacy enabled flag. Non-manual/background runs remain disabled by default.
        if (not force) and (not _is_auto_import_enabled()):
            _status("Auto-import disabled", "background import is disabled (manual !auto_import_run only)")
            return
        if aiohttp is None:
            _status("aiohttp missing", "cannot call API (skipping)")
            return

        ensure_auto_import_tables()

        roster_uids, roster_names_norm = _roster_uids_and_names()
        if not roster_uids and not roster_names_norm:
            _status("No roster configured", "no roster_uids or roster_names (skipping)")
            return

        cutoff_utc = _effective_auto_import_cutoff_utc(lookback_days)
        cutoff_txt = cutoff_utc.astimezone(BRIS_TZ).strftime("%Y-%m-%d %H:%M")

        if roster_uids:
            queries = [str(uid) for uid in sorted(roster_uids)]
            query_mode = "uids"
        else:
            queries = [nm for nm in sorted(ROSTER_NAMES_FALLBACK)]
            query_mode = "names(fallback)"

        api_seasons = _get_auto_import_api_seasons()
        imported_count = 0
        seen_match_uids: set[str] = set()
        provider_mode = str(provider or "auto").strip().lower()
        prefer_rivalsmeta_history = provider_mode == "rivalsmeta"
        prefer_rivalsmeta_details = provider_mode == "rivalsmeta"

        counters = {
            "players_done": 0,
            "api_seasons_done": 0,
            "pages_done": 0,
            "seen": 0,
            "imported": 0,
            "skip_cursor": 0,
            "skip_cutoff": 0,
            "skip_already_imported": 0,
            "skip_deleted": 0,
            "skip_draw_pre": 0,
            "skip_draw_post": 0,
            "skip_min_humans": 0,
            "skip_no_time": 0,
            "api_429": 0,
            "api_err": 0,
            "details_429": 0,
            "details_err": 0,
            "cursor_updates": 0,
            "rivalsmeta_history_pages": 0,
            "rivalsmeta_detail_matches": 0,
            "history_fallbacks": 0,
            "detail_fallbacks": 0,
        }

        _status(
            "Preparing queries…",
            f"mode={query_mode}, provider={provider_mode}, players={len(queries)}, api_seasons={','.join(api_seasons)}, cutoff={cutoff_txt} Brisbane, max_import={MAX_MATCHES_TO_IMPORT_PER_TICK}",
        )

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for qi, q in enumerate(queries, start=1):
                if imported_count >= MAX_MATCHES_TO_IMPORT_PER_TICK:
                    break

                for si, api_season in enumerate(api_seasons, start=1):
                    if imported_count >= MAX_MATCHES_TO_IMPORT_PER_TICK:
                        break

                    state = _get_auto_import_scan_state(q, api_season)
                    cursor_dt = _parse_iso_utc(state.get("newest_match_time_utc")) if state else None
                    newest_dt_seen: datetime | None = None
                    newest_uid_seen: str | None = None
                    fetched_any_page = False
                    had_error = False
                    reached_old_history = False

                    _status(
                        f"Player {qi}/{len(queries)} – API season {si}/{len(api_seasons)}",
                        f"q={q} season={api_season} | imported={counters['imported']} seen={counters['seen']} pages={counters['pages_done']}",
                    )

                    for page in range(int(AUTO_IMPORT_MAX_HISTORY_PAGES)):
                        if imported_count >= MAX_MATCHES_TO_IMPORT_PER_TICK or reached_old_history:
                            break

                        skip = page * int(AUTO_IMPORT_HISTORY_PAGE_SIZE)
                        _status(
                            "Fetching recent history…",
                            f"q={q} season={api_season} page={page+1}/{AUTO_IMPORT_MAX_HISTORY_PAGES} skip={skip} | imported={counters['imported']} seen={counters['seen']}",
                        )

                        try:
                            hist, history_source = await _fetch_history_with_provider_fallback(
                                q,
                                session,
                                skip=skip,
                                season=api_season,
                                prefer_rivalsmeta=prefer_rivalsmeta_history,
                            )
                            if history_source == "rivalsmeta":
                                if not prefer_rivalsmeta_history:
                                    counters["history_fallbacks"] += 1
                                    _status(
                                        "RivalsMeta history fallback active",
                                        "official history unavailable; using public roster histories for this run",
                                    )
                                prefer_rivalsmeta_history = True
                                counters["rivalsmeta_history_pages"] += 1
                            await asyncio.sleep(float(AUTO_IMPORT_HISTORY_REQUEST_DELAY))
                        except RuntimeError as e:
                            had_error = True
                            if "RATE_LIMIT_429" in str(e):
                                counters["api_429"] += 1
                                _status("Rate limited (history)", f"429 on match-history; stopping this player/season | q={q} season={api_season}")
                            else:
                                counters["api_err"] += 1
                            break
                        except Exception as e:
                            had_error = True
                            counters["api_err"] += 1
                            _set_auto_import_scan_state(q, api_season, newest_dt=None, newest_match_uid=None, completed=False, error=f"history: {type(e).__name__}: {e}")
                            break

                        items = (hist or {}).get("match_history") or []
                        if not isinstance(items, list) or not items:
                            break

                        fetched_any_page = True
                        counters["pages_done"] += 1

                        for it in items:
                            mu_tmp = _history_match_uid(it)
                            dt_tmp = _history_item_datetime_utc(it)
                            if dt_tmp and (newest_dt_seen is None or dt_tmp > newest_dt_seen):
                                newest_dt_seen = dt_tmp
                                newest_uid_seen = mu_tmp or newest_uid_seen

                        for it in items[: int(MATCH_HISTORY_PER_PLAYER_LIMIT)]:
                            if imported_count >= MAX_MATCHES_TO_IMPORT_PER_TICK:
                                break

                            match_uid = _history_match_uid(it)
                            if not match_uid:
                                continue

                            match_dt_hist = _history_item_datetime_utc(it)

                            if cursor_dt and match_dt_hist and match_dt_hist < cursor_dt:
                                counters["skip_cursor"] += 1
                                reached_old_history = True
                                break

                            if match_dt_hist and match_dt_hist < cutoff_utc:
                                counters["skip_cutoff"] += 1
                                reached_old_history = True
                                break

                            if match_uid in seen_match_uids:
                                continue
                            seen_match_uids.add(match_uid)
                            counters["seen"] += 1

                            try:
                                if _already_imported_in_any_season(match_uid):
                                    if match_dt_hist is not None:
                                        try:
                                            _set_imported_match_time_utc(match_uid, match_dt_hist)
                                        except Exception:
                                            pass
                                    counters["skip_already_imported"] += 1
                                    continue
                            except Exception:
                                continue

                            try:
                                if _already_skipped_match(match_uid, reason="DELETED"):
                                    counters["skip_deleted"] += 1
                                    continue
                            except Exception:
                                pass

                            try:
                                if _already_skipped_match(match_uid, reason="DRAW"):
                                    counters["skip_draw_pre"] += 1
                                    continue
                            except Exception:
                                pass

                            _status(
                                "Fetching new match details…",
                                f"match_uid={match_uid} | imported={counters['imported']} seen={counters['seen']} cursor_skip={counters['skip_cursor']} cutoff_skip={counters['skip_cutoff']}",
                            )

                            try:
                                payload, detail_source = await _fetch_match_details_with_provider_fallback(
                                    match_uid,
                                    session,
                                    prefer_rivalsmeta=prefer_rivalsmeta_details,
                                )
                                if detail_source == "rivalsmeta":
                                    if not prefer_rivalsmeta_details:
                                        counters["detail_fallbacks"] += 1
                                        _status(
                                            "RivalsMeta detail fallback active",
                                            "official match details unavailable; using public match pages for this run",
                                        )
                                    prefer_rivalsmeta_details = True
                                    counters["rivalsmeta_detail_matches"] += 1
                                await asyncio.sleep(float(AUTO_IMPORT_DETAIL_REQUEST_DELAY))
                            except RuntimeError as e:
                                had_error = True
                                if "RATE_LIMIT_429" in str(e):
                                    counters["details_429"] += 1
                                    _status("Rate limited (details)", f"429 on match-details; stopping this player/season | match_uid={match_uid}")
                                    reached_old_history = True
                                else:
                                    counters["details_err"] += 1
                                break
                            except Exception as e:
                                had_error = True
                                counters["details_err"] += 1
                                _set_setting("auto_import_last_error", f"{match_uid}: details {type(e).__name__}: {e}")
                                break

                            match_dt = _extract_match_datetime_utc(payload) or match_dt_hist
                            if match_dt is None:
                                counters["skip_no_time"] += 1
                                continue
                            if match_dt < cutoff_utc:
                                counters["skip_cutoff"] += 1
                                continue

                            season_id = resolve_season_for_match_time(match_dt)
                            if season_id is None:
                                season_id = int(get_current_season_id())

                            try:
                                if not _passes_min_humans_each_team(payload):
                                    counters["skip_min_humans"] += 1
                                    continue
                            except Exception:
                                continue

                            try:
                                if _is_draw_match(payload):
                                    md = (payload or {}).get("match_details") or {}
                                    gm = md.get("game_mode") or {}
                                    _record_skipped_match(
                                        match_uid,
                                        match_dt_utc=match_dt,
                                        season_id=season_id,
                                        reason="DRAW",
                                        source=f"auto_import_run:{detail_source}",
                                        details={
                                            "replay_id": md.get("replay_id"),
                                            "game_mode_id": gm.get("game_mode_id"),
                                            "game_mode_name": gm.get("game_mode_name"),
                                        },
                                    )
                                    counters["skip_draw_post"] += 1
                                    continue
                            except Exception:
                                pass

                            try:
                                await _import_match_into_season(match_uid, payload, season_id, match_dt_utc=match_dt)
                                imported_count += 1
                                counters["imported"] += 1
                                _status(
                                    "Imported match",
                                    f"match_uid={match_uid} → season_id={season_id} | imported={counters['imported']} seen={counters['seen']}",
                                )
                            except Exception as e:
                                had_error = True
                                _set_setting("auto_import_last_error", f"{match_uid}: import {type(e).__name__}: {e}")
                                break

                        if reached_old_history:
                            break

                    if fetched_any_page and not had_error and imported_count < MAX_MATCHES_TO_IMPORT_PER_TICK:
                        _set_auto_import_scan_state(
                            q,
                            api_season,
                            newest_dt=newest_dt_seen,
                            newest_match_uid=newest_uid_seen,
                            completed=True,
                            error=None,
                        )
                        counters["cursor_updates"] += 1
                    elif had_error:
                        _set_auto_import_scan_state(
                            q,
                            api_season,
                            newest_dt=None,
                            newest_match_uid=None,
                            completed=False,
                            error="scan stopped due to API/detail/import error",
                        )

                    counters["api_seasons_done"] += 1

                counters["players_done"] += 1

        summary = (
            f"imported={counters['imported']} seen_candidates={counters['seen']} history_pages={counters['pages_done']} "
            f"cursor_skips={counters['skip_cursor']} cutoff_skips={counters['skip_cutoff']} already={counters['skip_already_imported']} "
            f"deleted={counters['skip_deleted']} draws={counters['skip_draw_pre'] + counters['skip_draw_post']} min_humans={counters['skip_min_humans']} "
            f"429(history)={counters['api_429']} 429(details)={counters['details_429']} "
            f"errors(history)={counters['api_err']} errors(details)={counters['details_err']} cursor_updates={counters['cursor_updates']} "
            f"rivalsmeta(history_pages)={counters['rivalsmeta_history_pages']} rivalsmeta(details)={counters['rivalsmeta_detail_matches']} "
            f"fallbacks(history/details)={counters['history_fallbacks']}/{counters['detail_fallbacks']}"
        )

        _set_setting("auto_import_last_run", _now_iso_utc())
        _set_setting("auto_import_last_imported_count", str(imported_count))
        _set_setting("auto_import_last_summary", summary)

        _status("Finished import run", summary)

async def _fetch_history_with_backoff(query: str,
                                      session,
                                      *,
                                      skip: int,
                                      season: str | None = None,
                                      game_mode: int | None = None):
    # Exponential backoff on 429
    backoff = 2
    max_backoff = 30
    attempts = 6

    for attempt in range(attempts):
        try:
            return await _fetch_match_history_for_player(query,
                                                         session,
                                                         skip=skip,
                                                         season=season,
                                                         game_mode=game_mode)
        except RuntimeError as e:
            if "RATE_LIMIT_429" in str(e):
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)
                continue
            raise  # other RuntimeErrors should bubble up
    raise RuntimeError("RATE_LIMIT_429 (exceeded retry attempts)")


async def _fetch_history_with_provider_fallback(query: str,
                                                session,
                                                *,
                                                skip: int,
                                                season: str,
                                                prefer_rivalsmeta: bool = False):
    """Fetch history from the official API, falling back to RivalsMeta for UID rosters."""
    official_error = None
    if not prefer_rivalsmeta:
        try:
            history = await _fetch_history_with_backoff(
                query,
                session,
                skip=skip,
                season=season,
            )
            items = (history or {}).get("match_history") or []
            if skip > 0 or (isinstance(items, list) and items):
                return history, "official"
            official_error = RuntimeError("official history returned an empty first page")
        except Exception as exc:
            official_error = exc

    try:
        history = await fetch_rivalsmeta_player_history(
            query,
            session,
            skip=skip,
            season=season,
            game_mode=3,
        )
        return history, "rivalsmeta"
    except Exception as rivalsmeta_error:
        if official_error is None:
            raise
        raise RuntimeError(
            f"Official history failed ({official_error}); RivalsMeta fallback failed ({rivalsmeta_error})."
        ) from rivalsmeta_error


async def _fetch_match_details_with_provider_fallback(
        match_uid: str,
        session,
        *,
        prefer_rivalsmeta: bool = False):
    """Fetch full match details with a per-run RivalsMeta circuit breaker."""
    official_error = None
    if not prefer_rivalsmeta:
        try:
            return await _fetch_match_details(match_uid, session), "official"
        except Exception as exc:
            official_error = exc

    try:
        return await rivalsmeta_get_match_json(match_uid, session=session), "rivalsmeta"
    except Exception as rivalsmeta_error:
        if official_error is None:
            raise
        raise RuntimeError(
            f"Official match details failed ({official_error}); RivalsMeta fallback failed ({rivalsmeta_error})."
        ) from rivalsmeta_error

async def _start_status_ticker(
    ctx,
    *,
    phase_ref: dict,
    interval_s: int = 15,
    title: str = "Auto-import status",
):
    """
    Starts a 15s ticker that edits ONE Discord message with current phase + elapsed time.
    phase_ref: mutable dict {"phase": "...", "detail": "..."} updated by the caller.
    Returns: (stop_event, ticker_task, status_message)
    """
    start_ts = time.time()
    stop_event = asyncio.Event()

    def _render() -> str:
        elapsed = int(time.time() - start_ts)
        phase = phase_ref.get("phase", "Working...")
        detail = phase_ref.get("detail", "")
        detail_line = f"\n{detail}" if detail else ""
        return (
            f"**{title}**\n"
            f"• Elapsed: **{elapsed}s**\n"
            f"• Phase: **{phase}**"
            f"{detail_line}"
        )

    status_msg = await ctx.send(_render())

    async def _loop():
        last_text = None
        while not stop_event.is_set():
            await asyncio.sleep(interval_s)
            try:
                text = _render()
                if text != last_text:
                    await status_msg.edit(content=text)
                    last_text = text
            except Exception:
                # If edit fails (permissions/Discord hiccup), ignore.
                pass

    task = asyncio.create_task(_loop())
    return stop_event, task, status_msg


async def _stop_status_ticker(stop_event, task, status_msg, final_text: str = None):
    """Stops the ticker and optionally edits the status message with a final result."""
    try:
        stop_event.set()
    except Exception:
        pass
    try:
        task.cancel()
    except Exception:
        pass

    if final_text and status_msg:
        try:
            await status_msg.edit(content=final_text)
        except Exception:
            try:
                await status_msg.channel.send(final_text)
            except Exception:
                pass

# -------------------------
# Manual-only auto-import
# -----------------------
# Auto-import no longer runs every 120 seconds. Use !auto_import_run after a
# session. This avoids unnecessary history scans and API rate-limit pressure.


# ============================================================================================================
# ============================================================================================================
# Shared helper: payload -> (human-only) game_stats rows
# Used by submit_match AND auto-import.
# ============================================================================================================
# ============================================================================================================


def _is_bot_player(p: dict) -> bool:
    """
    Bot detection (safe, non-recursive).
    Uses explicit flags if present; otherwise checks common bot naming.
    """
    if not isinstance(p, dict):
        return False

    # Explicit flags (if API ever provides them)
    if p.get("is_bot") is True:
        return True

    # Name-based fallback for payloads where nick_name == "Bot".
    for k in ("nick_name", "nickname", "player_name", "player", "name"):
        v = p.get(k)
        if isinstance(v, str) and v.strip().lower() == "bot":
            return True

    return False


def write_season_rows_from_match_payload(season_id: int,
                                         game_label: str,
                                         payload: dict,
                                         *,
                                         overwrite_label: bool = True,
                                         update_streaks_flag: bool = True):
    """
    Writes HUMAN-ONLY rows into game_stats for leaderboard + existing season commands.
    Mirrors the fields used by submit_match.
    """
    ensure_mr_api_tables()

    md = (payload or {}).get("match_details") or {}
    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    # optional: match timestamp for record-keeping
    match_dt = _extract_match_datetime_utc(payload)
    match_ts = match_dt.astimezone(BRIS_TZ).strftime(
        "%Y-%m-%d %H:%M:%S") if match_dt else None

    # overwrite this label (safe when replacing)
    if overwrite_label:
        try:
            c.execute(
                "DELETE FROM game_stats WHERE season_id=? AND game_label=?",
                (int(season_id), str(game_label)))
        except Exception:
            pass

    mvp_uid = md.get("mvp_uid")
    svp_uid = md.get("svp_uid")

    human_rows = []
    bot_count = 0

    for p in players:
        if not isinstance(p, dict):
            continue
        if _is_bot_player(p):
            bot_count += 1
            continue

        nick = (p.get("nick_name") or p.get("nickname") or p.get("player_name")
                or "").strip()
        if not nick:
            continue

        nick = canonical_player_name(nick)
        uid = p.get("player_uid")
        result = _parse_is_win_flag(p.get("is_win"))
        is_win = (result == 1)
        is_loss = (result == 0)

        row = {
            "season_id": int(season_id),
            "game_label": str(game_label),
            "player": nick,
            "kills": int(p.get("kills") or 0),
            "deaths": int(p.get("deaths") or 0),
            "assists": int(p.get("assists") or 0),
            "damage": int(float(p.get("total_hero_damage") or 0)),
            "damage_taken": int(float(p.get("total_damage_taken") or 0)),
            "healing": int(float(p.get("total_hero_heal") or 0)),
            # Draws/unknowns are stored as win=0, loss=0 so they don't distort stats.
            "win": 1 if is_win else 0,
            "loss": 1 if is_loss else 0,
            "mvp": 1 if (mvp_uid is not None and uid == mvp_uid) else 0,
            "svp": 1 if (svp_uid is not None and uid == svp_uid) else 0,
            "player_uid": uid,
        }
        human_rows.append((row, p))

    if not human_rows:
        raise RuntimeError("No human players found in payload.")

    # Dedupe display names inside this match.
    name_counts = {}
    for r, raw in human_rows:
        name_counts[r["player"]] = name_counts.get(r["player"], 0) + 1
    if any(ct > 1 for ct in name_counts.values()):
        for r, raw in human_rows:
            if name_counts.get(r["player"],
                               0) > 1 and r.get("player_uid") is not None:
                r["player"] = f"{r['player']} ({int(r['player_uid'])})"

    def _pick_best(rows_with_raw, want_win: bool) -> int:
        best_i = 0
        best_score = None
        for i, (r, _raw) in enumerate(rows_with_raw):
            if bool(r["win"]) != want_win:
                continue
            score = (r["kills"] * 3) + (r["assists"] * 1) + (r["damage"] /
                                                             1000.0)
            if best_score is None or score > best_score:
                best_score = score
                best_i = i
        return best_i

    # Enforce exactly one MVP + one SVP among humans (fallback if API picked a bot)
    if sum(r["mvp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["mvp"] = 0
        human_rows[_pick_best(human_rows, True)][0]["mvp"] = 1

    if sum(r["svp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["svp"] = 0
        human_rows[_pick_best(human_rows, False)][0]["svp"] = 1

    # Insert season rows.
    for (r, _raw) in human_rows:
        c.execute(
            """
            INSERT INTO game_stats (
                season_id, game_label, player,
                kills, deaths, assists,
                damage, damage_taken, healing,
                win, loss, mvp, svp,
                timestamp
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, COALESCE(?, CURRENT_TIMESTAMP))
            ON CONFLICT(season_id, game_label, player) DO UPDATE SET
                kills=excluded.kills,
                deaths=excluded.deaths,
                assists=excluded.assists,
                damage=excluded.damage,
                damage_taken=excluded.damage_taken,
                healing=excluded.healing,
                win=excluded.win,
                loss=excluded.loss,
                mvp=excluded.mvp,
                svp=excluded.svp,
                timestamp=excluded.timestamp
        """, (r["season_id"], r["game_label"], r["player"], r["kills"],
              r["deaths"], r["assists"], r["damage"], r["damage_taken"],
              r["healing"], r["win"], r["loss"], r["mvp"], r["svp"], match_ts))

    conn.commit()

    # update streaks (skip draws/unknowns)
    if update_streaks_flag:
        for (r, _raw) in human_rows:
            if int(r.get("win") or 0) == 1:
                update_streak(r["player"], won=True, season_id=int(season_id))
            elif int(r.get("loss") or 0) == 1:
                update_streak(r["player"], won=False, season_id=int(season_id))

        try:
            refresh_season_views()
        except Exception:
            pass


# ============================================================================================================
# ============================================================================================================
# SEASON COMMANDS (API-era)
# - Uses match_imports / mr_match_meta for season game counts + ranges
# - Still refreshes game_stats_v view for compatibility with commands
# ============================================================================================================
# ============================================================================================================


def ensure_seasons_table():
    c.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            season_id INTEGER PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _season_game_count(season_id: int) -> int:
    """
    Prefer match_imports because API import is now the source of truth.
    Fallback to game_stats if needed.
    """
    return _read_season_game_count(c, season_id)


def _season_date_range(season_id: int):
    """
    Prefer mr_match_meta/imported_at (available for every API imported match).
    Fallback to game_stats timestamps if required.
    Returns (min_date_str, max_date_str) or (None, None)
    """
    return _read_season_date_range(c, season_id)


def _ensure_season_exists_api(season_id: int):
    """
    Keeps the seasons metadata table in sync with API-era usage.
    """
    ensure_seasons_table()
    c.execute("INSERT OR IGNORE INTO seasons(season_id) VALUES(?)",
              (int(season_id), ))
    conn.commit()

# ---------------------------
# !season
# ---------------------------
@bot.command(name='season')
async def season(ctx):
    sid = get_current_season_id()
    await ctx.send(f"🏷️ Current season: **Season {sid}**")


# ======================================================================
# Clear session and fairness caches when switching seasons so next_teams starts fresh.
# ======================================================================

try:
    bot.remove_command("set_season")
except Exception:
    pass

@bot.command(name='set_season')
async def set_season(ctx, season_id: int):
    ensure_mr_api_tables()
    ensure_seasons_table()

    season_id = int(season_id)
    _ensure_season_exists_api(season_id)
    set_current_season_id(season_id)

    try:
        refresh_season_views()
    except Exception:
        pass

    # Reset all in-memory fairness/session caches
    try:
        SESSION_STATES.clear()
        FAIRNESS_CONTEXTS.clear()
    except Exception:
        pass

    # Reset persisted session state (restart-safe)
    try:
        ensure_session_state_table()
        c.execute("DELETE FROM session_state")
        conn.commit()
    except Exception:
        pass

    await ctx.send(f"✅ Switched to **Season {season_id}** (fairness session reset).")

# ---------------------------
# !list_seasons  (note: user asked list_season but code was list_seasons)
# ---------------------------
@bot.command(name='list_seasons')
async def list_seasons(ctx):
    ensure_mr_api_tables()
    ensure_seasons_table()

    c.execute("SELECT season_id FROM seasons ORDER BY season_id ASC")
    seasons = [r[0] for r in c.fetchall()]
    if not seasons:
        await ctx.send("No seasons found.")
        return

    current = get_current_season_id()
    lines = ["📚 **Seasons**"]

    for sid in seasons:
        games = _season_game_count(int(sid))
        mn, mx = _season_date_range(int(sid))

        tag = " (current)" if int(sid) == int(current) else ""
        date_range = f" — {mn} to {mx}" if (mn and mx) else ""

        lines.append(f"Season {sid}: {games} game(s){date_range}{tag}")

    await ctx.send("\n".join(lines))


# ---------------------------
# !reset_season (admin)
# Starts a new season number (default: current + 1)
# Does NOT delete old data.
# ---------------------------
@bot.command(name='reset_season')
async def reset_season(ctx, season_id: int = None):
    ensure_mr_api_tables()
    ensure_seasons_table()

    if season_id is None:
        current = get_current_season_id()
        season_id = int(current) + 1
    else:
        season_id = int(season_id)

    _ensure_season_exists_api(season_id)
    set_current_season_id(season_id)

    try:
        refresh_season_views()
    except Exception:
        pass

    await ctx.send(
        f"📅 New season started: **Season {season_id}**. (Old seasons are preserved.)"
    )


# ---------------------------
# !browse_games (API-era)
# Prefer mr_match_meta for ordering + match timestamps
# ---------------------------
@bot.command(name='browse_games')
async def browse_games(ctx, limit: int = 40):
    """List recorded games for the current season.

    Includes:
      - game_label
      - match_uid (game ID)
      - played timestamp (from match_time_utc when available)
      - imported timestamp

    Default shows the most recent 40 rows to avoid Discord 2000-char limits.
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # ---- clamp limit ----
    try:
        n = int(limit)
    except Exception:
        n = 40
    n = max(1, min(n, 120))

    def _parse_sqlite_utc_dt(s: str):
        """SQLite CURRENT_TIMESTAMP is UTC; treat naive values as UTC."""
        try:
            dt = datetime.fromisoformat(str(s).strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    rows = _get_recent_games(c, season_id, n)

    if not rows:
        await ctx.send(f"No games recorded yet for Season {season_id}.")
        return

    header = f"**Recorded Games — Season {season_id} (latest {len(rows)}):**"
    lines = ["game_label | match_id | played (Brisbane) | imported (Brisbane)"]

    for game_label, match_uid, match_time_utc, imported_at in rows:
        # played
        played_bris = "—"
        dt_play = _parse_iso_utc(match_time_utc) if match_time_utc else None
        if dt_play is not None:
            try:
                played_bris = dt_play.astimezone(BRIS_TZ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        # imported
        imported_bris = "—"
        dt_imp = _parse_sqlite_utc_dt(imported_at) if imported_at else None
        if dt_imp is not None:
            try:
                imported_bris = dt_imp.astimezone(BRIS_TZ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        mid = str(match_uid) if match_uid else "—"
        gl = str(game_label)
        lines.append(f"{gl} | {mid} | {played_bris} | {imported_bris}")

    # Chunk to avoid Discord 2000-char errors
    async def _send_chunks(prefix: str, body_lines: list[str], max_len: int = 1900):
        cur = prefix + "\n```\n"
        for ln in body_lines:
            ln = str(ln)
            if len(cur) + len(ln) + 1 > max_len:
                cur += "```"
                await ctx.send(cur)
                cur = "```\n" + ln + "\n"
            else:
                cur += ln + "\n"
        cur += "```"
        await ctx.send(cur)

    await _send_chunks(header, lines)

# ============================================================================================================
# Command - Refresh Heroes (force refresh hero_cache from API)
# Usage:
#   !refresh_heroes
#   !refresh_heros     (alias)
# ============================================================================================================

try:
    bot.remove_command("refresh_heroes")
except Exception:
    pass

@bot.command(name="refresh_heroes", aliases=["refresh_heros", "refresh_hero_cache", "refreshheroes"])
async def refresh_heroes_cmd(ctx):
    # Restrict cache refresh to the bot owner or server administrators.

    # Ensure tables exist
    try:
        ensure_mr_api_tables()
    except Exception:
        pass

    msg = await ctx.send("Refreshing hero cache from API…")

    try:
        # Clear memo so new names appear immediately everywhere
        try:
            _HERO_NAME_MEMO.clear()
        except Exception:
            pass

        updated = await refresh_hero_cache(force=True)

        total = None
        try:
            c.execute("SELECT COUNT(*) FROM hero_cache")
            total = int((c.fetchone() or [0])[0])
        except Exception:
            total = None

        out = f"✅ Hero cache refresh complete. Updated/Upserted: **{int(updated)}**"
        if total is not None:
            out += f" • Total heroes in cache: **{total}**"

        try:
            await msg.edit(content=out)
        except Exception:
            await ctx.send(out)

    except Exception as e:
        err = f"❌ Hero cache refresh failed: `{type(e).__name__}: {e}`"
        try:
            await msg.edit(content=err)
        except Exception:
            await ctx.send(err)

# ============================================================================================================
# Command - hero role check
# ============================================================================================================

def _hr_fmt_time(sec: float) -> str:
    try:
        s = int(round(float(sec or 0.0)))
    except Exception:
        s = 0
    m, ss = divmod(s, 60)
    h, mm = divmod(m, 60)
    if h > 0:
        return f"{h}h{mm:02d}m"
    return f"{mm}m{ss:02d}s"


async def _hr_send_long(ctx, text: str):
    # Discord hard limit ~2000 chars
    chunks = []
    cur = ""
    for line in text.splitlines():
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)

    for ch in chunks:
        await ctx.send(f"```{ch.strip()}```")


try:
    bot.remove_command("hero_roles_check")
except Exception:
    pass


@bot.command(name="hero_roles_check")
async def hero_roles_check(ctx, *args):
    """
    Usage:
      !hero_roles_check
      !hero_roles_check refresh
      !hero_roles_check 6
      !hero_roles_check 6 refresh
    """
    ensure_mr_api_tables()
    global c

    season_id = get_current_season_id()
    force_refresh = False

    for a in args:
        s = str(a).lower().strip()
        if s.isdigit():
            season_id = int(s)
        if s in ("refresh", "force", "--refresh", "--force"):
            force_refresh = True

    if force_refresh:
        fn = globals().get("refresh_hero_cache")
        if callable(fn):
            try:
                updated = await fn(force=True)
                await ctx.send(f"Hero cache refreshed. Updated rows: {updated}")
            except Exception as e:
                await ctx.send(f"Hero cache refresh failed: {e}")

    # Build role map from cache (digits-only normalisation)
    cache = {}  # hid_int -> (name, role)
    bad_cache_ids = []
    try:
        for hid, name, role in load_hero_cache_rows(c):
            hid_s = str(hid or "").strip()
            hid_digits = _digits_only(hid_s) or hid_s
            if not hid_digits:
                bad_cache_ids.append(hid_s)
                continue
            try:
                hid_i = int(hid_digits)
            except Exception:
                bad_cache_ids.append(hid_s)
                continue
            cache[hid_i] = (str(name or "").strip(), str(role or "").strip())
    except Exception:
        pass

    # Pull heroes used in this season (by seconds)
    usage = []  # (hid_raw, hid_i, sec)
    bad_segment_ids = []
    try:
        for hid, sec in load_season_hero_usage(c, season_id):
            hid_s = str(hid or "").strip()
            hid_digits = _digits_only(hid_s) or hid_s
            if not hid_digits:
                bad_segment_ids.append(hid_s)
                continue
            try:
                hid_i = int(hid_digits)
            except Exception:
                bad_segment_ids.append(hid_s)
                continue
            usage.append((hid_s, hid_i, float(sec or 0.0)))
    except Exception:
        await ctx.send("No mr_hero_segments data found for this season.")
        return

    allowed = {"Vanguard", "Duelist", "Strategist"}

    total_seen = len({hid_i for _raw, hid_i, _sec in usage})
    known_role = 0
    missing_in_cache = []
    invalid_role = []
    ok = []

    for raw, hid_i, sec in usage:
        if hid_i not in cache:
            missing_in_cache.append((raw, hid_i, sec))
            continue
        name, role = cache[hid_i]
        if role not in allowed:
            invalid_role.append((raw, hid_i, name, role, sec))
            continue
        ok.append((raw, hid_i, name, role, sec))
        known_role += 1

    # Build report
    lines = []
    lines.append(f"Hero Role Audit — Season {season_id}")
    lines.append(f"Heroes seen in match data: {total_seen}")
    lines.append(f"Valid role mappings: {known_role}")
    lines.append(f"Missing from hero_cache: {len({hid_i for _raw, hid_i, _sec in missing_in_cache})}")
    lines.append(f"Invalid/missing role values: {len({hid_i for _raw, hid_i, _n, _r, _sec in invalid_role})}")
    if bad_segment_ids:
        lines.append(f"Non-numeric hero_id values in mr_hero_segments (first 10): {bad_segment_ids[:10]}")
    if bad_cache_ids:
        lines.append(f"Non-numeric hero_id values in hero_cache (first 10): {bad_cache_ids[:10]}")
    lines.append("")

    if missing_in_cache:
        lines.append("Top heroes missing from cache (by seconds):")
        for raw, hid_i, sec in missing_in_cache[:15]:
            lines.append(f"- {raw} -> {hid_i}  |  {_hr_fmt_time(sec)}")
        lines.append("")

    if invalid_role:
        lines.append("Top heroes with invalid/missing role (by seconds):")
        for raw, hid_i, name, role, sec in invalid_role[:15]:
            nm = name or "(no name)"
            rl = role or "(blank)"
            lines.append(f"- {hid_i}  {nm}  |  role={rl}  |  {_hr_fmt_time(sec)}")
        lines.append("")

    lines.append("If the Season Story ternary plot looks wrong, the usual causes are:")
    lines.append("1) hero_ids in mr_hero_segments are not purely numeric (e.g. 'hero_1011')")
    lines.append("2) hero_cache has blank/invalid hero_role for heroes used this season")

    await _hr_send_long(ctx, "\n".join(lines))

# ============================================================================================================
# ============================================================================================================
# Commands - !hero_role_set - set names and roles
# !hero_role_set 10573 <Role> <OptionalName>
# ============================================================================================================
# ============================================================================================================
from datetime import datetime, timezone

_ALLOWED_ROLES = {"vanguard": "Vanguard", "duelist": "Duelist", "strategist": "Strategist"}

def _ss_is_admin(ctx) -> bool:
    return True

def _ensure_hero_cache_schema_strict():
    """
    Ensure hero_cache exists with hero_name, hero_role, updated_at.
    Safe to call anytime.
    """
    ensure_mr_api_tables()
    global c, conn

    c.execute("""
        CREATE TABLE IF NOT EXISTS hero_cache (
            hero_id TEXT PRIMARY KEY,
            hero_name TEXT,
            hero_role TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()

    try:
        c.execute("PRAGMA table_info(hero_cache)")
        cols = {str(r[1]).lower() for r in (c.fetchall() or [])}
        if "hero_name" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN hero_name TEXT")
        if "hero_role" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN hero_role TEXT")
        if "updated_at" not in cols:
            c.execute("ALTER TABLE hero_cache ADD COLUMN updated_at TEXT")
        conn.commit()
    except Exception:
        pass

try:
    bot.remove_command("hero_role_set")
except Exception:
    pass

@bot.command(name="hero_role_set")
async def hero_role_set(ctx, hero_id: str = None, role: str = None, *, hero_name: str = None):
    """
    Usage:
      !hero_role_set <hero_id> <Vanguard|Duelist|Strategist> [optional hero name...]
    Examples:
      !hero_role_set 1058 Duelist Gambit
      !hero_role_set 10571 Vanguard
    """
    global c, conn


    if not hero_id or not role:
        await ctx.send("Usage: `!hero_role_set <hero_id> <Vanguard|Duelist|Strategist> [optional hero name]`")
        return

    role_key = str(role).strip().lower()
    if role_key not in _ALLOWED_ROLES:
        await ctx.send("Role must be one of: Vanguard, Duelist, Strategist.")
        return

    role_norm = _ALLOWED_ROLES[role_key]
    hid_raw = str(hero_id).strip()
    if not hid_raw:
        await ctx.send("Invalid hero_id.")
        return

    # Store the raw hero id and a digits-only alias when applicable.
    ids_to_store = [hid_raw]
    hid_digits = _digits_only(hid_raw)
    if hid_digits and hid_digits != hid_raw:
        ids_to_store.append(hid_digits)

    _ensure_hero_cache_schema_strict()

    now = datetime.now(timezone.utc).isoformat()
    name_clean = _safe_str(hero_name) if hero_name else None
    if name_clean:
        name_clean = _hero_pretty(name_clean) or name_clean

    changed = 0
    for hid in ids_to_store:
        try:
            # Fetch existing
            c.execute("SELECT hero_name, hero_role FROM hero_cache WHERE hero_id=?", (hid,))
            ex = c.fetchone()
            ex_name = (ex[0] if ex else None)
            ex_role = (ex[1] if ex and len(ex) > 1 else None)

            # If no name provided, preserve existing name
            final_name = name_clean if name_clean else ex_name

            c.execute("""
                INSERT INTO hero_cache (hero_id, hero_name, hero_role, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(hero_id) DO UPDATE SET
                    hero_name = excluded.hero_name,
                    hero_role = excluded.hero_role,
                    updated_at = excluded.updated_at
            """, (hid, final_name, role_norm, now))

            if (ex is None) or ((ex_role or "") != role_norm) or (name_clean and (ex_name or "") != (final_name or "")):
                changed += 1

            # Optional: keep any in-memory memo consistent if you use it elsewhere
            try:
                if final_name:
                    _HERO_NAME_MEMO[hid] = final_name
                _HERO_ROLE_MEMO[hid] = role_norm
            except Exception:
                pass

        except Exception:
            continue

    try:
        conn.commit()
    except Exception:
        pass

    nm_msg = f" name='{name_clean}'" if name_clean else ""
    await ctx.send(f"Upserted role='{role_norm}'{nm_msg} for hero_id(s): {', '.join(ids_to_store)}. Changes: {changed}")



# ============================================================================================================
# ============================================================================================================
# Commands - API Auto Imports
# ============================================================================================================
# ============================================================================================================
def _is_admin(ctx) -> bool:
    return True


@bot.command(name="auto_import_status")
async def auto_import_status(ctx):
    enabled = _is_auto_import_enabled()
    last = _get_setting("auto_import_last_run", "—")
    last_n = _get_setting("auto_import_last_imported_count", "0")
    summary = _get_setting("auto_import_last_summary", "—")
    cutoff = get_auto_import_cutoff_utc().astimezone(BRIS_TZ).strftime("%Y-%m-%d %H:%M")
    api_seasons = ", ".join(_get_auto_import_api_seasons())

    await ctx.send(
        "Auto import background loop: **OFF** (manual only)\n"
        f"Legacy enabled flag: **{'ON' if enabled else 'OFF'}** • Last run: {last} • Last imported: {last_n}\n"
        f"Cutoff floor: **{cutoff} Brisbane** • Default lookback: **{AUTO_IMPORT_MAX_LOOKBACK_DAYS} day(s)** • API seasons: **{api_seasons}**\n"
        f"Last summary: `{summary}`"
    )

@bot.command(name="skipped_draws",
             aliases=[
                 "skipped_draw_games", "draw_skips", "skipped_games_draws",
                 "skippinggames_draws"
             ])
async def skipped_draws_cmd(ctx, limit: int = 20):
    """List matches that were skipped because they were detected as draws."""
    ensure_auto_import_tables()
    try:
        n = int(limit)
    except Exception:
        n = 20
    n = max(1, min(n, 50))

    c.execute(
        """
        SELECT match_uid, match_time_utc, season_id, source, last_seen_at, seen_count
        FROM mr_skipped_matches
        WHERE reason = 'DRAW'
        ORDER BY datetime(last_seen_at) DESC
        LIMIT ?
        """,
        (n, ),
    )
    rows = c.fetchall() or []
    if not rows:
        await ctx.send("No skipped draw matches recorded.")
        return

    lines = [f"**Skipped draw matches (showing up to {n}):**"]
    for match_uid, match_time_utc, season_id, source, last_seen_at, seen_count in rows:
        dt_txt = "—"
        try:
            dt = _parse_iso_utc(match_time_utc) if match_time_utc else None
            if dt:
                dt_txt = dt.astimezone(BRIS_TZ).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        sid_txt = str(season_id) if season_id is not None else "—"
        src_txt = str(source) if source else "—"
        cnt_txt = str(seen_count or 1)
        lines.append(
            f"- `{match_uid}` • {dt_txt} Brisbane • Season {sid_txt} • {src_txt} • seen {cnt_txt}x"
        )

    await ctx.send("\n".join(lines))


@bot.command(name="auto_import_on")
async def auto_import_on(ctx):
    _set_setting("auto_import_enabled", "true")
    await ctx.send("Legacy auto-import enabled flag is now **ON**. Background polling is still disabled; use `!auto_import_run` manually after sessions.")


@bot.command(name="auto_import_off")
async def auto_import_off(ctx):
    _set_setting("auto_import_enabled", "false")
    await ctx.send("Legacy auto-import enabled flag is now **OFF**. Background polling is disabled; manual `!auto_import_run` still works.")


@bot.command(name="auto_import_cutoff")
async def auto_import_cutoff_cmd(ctx, date_bris: str = None):
    """
    Show or set the cutoff (Brisbane date).
    Usage:
      !auto_import_cutoff           (shows current)
      !auto_import_cutoff 2026-01-05  (sets to 00:00 that day Brisbane)
    """
    if date_bris:
        try:
            set_auto_import_cutoff_bris(date_bris)
            await ctx.send(
                f"Auto-import cutoff set to **{date_bris} 00:00 Brisbane**.")
        except Exception as e:
            await ctx.send(f"Failed to set cutoff: {e}")
    else:
        dt = get_auto_import_cutoff_utc().astimezone(BRIS_TZ)
        await ctx.send(
            f"Auto-import cutoff is **{dt.strftime('%Y-%m-%d %H:%M')} Brisbane**."
        )


@bot.command(name="season_window_set")
async def season_window_set_cmd(ctx,
                                season_id: int,
                                start_bris: str,
                                end_bris: str = None,
                                *,
                                note: str = ""):
    """
    Define season windows (Brisbane time).
    Usage:
      !season_window_set 1 2025-12-01 2025-12-31
      !season_window_set 2 2026-01-01 OPEN
    """
    if end_bris and str(end_bris).strip().upper() == "OPEN":
        end_bris = None
    try:
        set_season_window(int(season_id), start_bris, end_bris, note=note)
        await ctx.send(
            f"Season {season_id} window set: {start_bris} → {end_bris or 'OPEN'} (Brisbane time)."
        )
    except Exception as e:
        await ctx.send(f"Failed to set season window: {e}")


@bot.command(name="season_split_window_set",
             aliases=["season_half_window_set"])
async def season_split_window_set_cmd(ctx,
                                      season_id: int = None,
                                      split_label: str = None,
                                      start_bris: str = None,
                                      end_bris: str = None,
                                      *,
                                      note: str = ""):
    """
    Define exact 0 / 0.5 split windows inside a season (Brisbane time).
    Usage:
      !season_split_window_set 8 0 2026-01-01 2026-01-21
      !season_split_window_set 8 0.5 2026-01-22 2026-02-14
    """
    if season_id is None or not split_label or not start_bris or not end_bris:
        await ctx.send(
            "Usage: `!season_split_window_set <season_id> <0|0.5> <YYYY-MM-DD> <YYYY-MM-DD> [note]`"
        )
        return
    try:
        label = _normalise_season_split_label(split_label)
        set_season_split_window(int(season_id), label, start_bris, end_bris, note=note)
        season_label = f"{season_id}.0" if label == "0" else f"{season_id}.5"
        await ctx.send(
            f"Season {season_label} window set: {start_bris} -> {end_bris} (Brisbane time)."
        )
    except Exception as e:
        await ctx.send(f"Failed to set season split window: {e}")


@bot.command(name="season_windows")
async def season_windows_cmd(ctx):
    rows = list_season_windows()
    if not rows:
        await ctx.send(
            "No season windows set. Use `!season_window_set <season_id> <YYYY-MM-DD> [YYYY-MM-DD|OPEN]`."
        )
        return
    lines = ["**Season Windows (Brisbane time):**"]
    for r in rows:
        note = f" — {r['note']}" if r["note"] else ""
        lines.append(
            f"- Season {r['season_id']}: {r['start_bris']} → {r['end_bris']}{note}"
        )
    await ctx.send("\n".join(lines))


@bot.command(name="roster_add")
async def roster_add(ctx, player_uid: int, *, player_name: str = ""):
    ensure_auto_import_tables()
    c.execute(
        """
        INSERT INTO mr_roster(player_uid, player_name, enabled)
        VALUES(?,?,1)
        ON CONFLICT(player_uid) DO UPDATE SET player_name=excluded.player_name, enabled=1
    """, (int(player_uid), (player_name or "").strip()))
    conn.commit()
    await ctx.send(f"Roster updated: **{player_uid}** added/enabled.")


@bot.command(name="roster_remove")
async def roster_remove(ctx, player_uid: int):
    ensure_auto_import_tables()
    c.execute("UPDATE mr_roster SET enabled=0 WHERE player_uid=?",
              (int(player_uid), ))
    conn.commit()
    await ctx.send(f"Roster updated: **{player_uid}** disabled.")


@bot.command(name="roster_list")
async def roster_list(ctx):
    ensure_auto_import_tables()
    rows = list_roster(c)
    if not rows:
        await ctx.send(
            "Roster is empty. Use `!roster_add <player_uid> [name]`.")
        return
    lines = []
    for uid, nm, en in rows:
        lines.append(
            f"- {uid} — {nm or '—'} {'(ON)' if int(en or 0)==1 else '(OFF)'}")
    await ctx.send("**Roster:**\n" + "\n".join(lines))

@bot.command(name="roster_update_all")
async def roster_update_all(ctx):
    """
    Triggers MarvelRivalsAPI refresh queue for every enabled roster UID.
    Usage:
      !roster_update_all
    """
    ensure_auto_import_tables()
    roster_uids = list_enabled_roster_uids(c)

    if not roster_uids:
        await ctx.send("Roster is empty (no enabled player_uid rows).")
        return

    await ctx.send(f"Queuing API refresh for **{len(roster_uids)}** roster player(s)…")
    try:
        await _update_roster_players_trigger(roster_uids=roster_uids, ctx=ctx)
    except Exception as e:
        await ctx.send(f"Roster refresh failed: {e}")



@bot.command(name="auto_import_run")
async def auto_import_run(ctx, *args):

    opts = _parse_auto_import_run_args(args)
    if opts.get("reset_cursor"):
        _clear_auto_import_scan_state()

    phase_ref = {"phase": "Starting…", "detail": ""}
    stop_event = ticker_task = status_msg = None

    def _status_update(*, phase=None, detail=None):
        if phase is not None:
            phase_ref["phase"] = phase
        if detail is not None:
            phase_ref["detail"] = detail

    try:
        stop_event, ticker_task, status_msg = await _start_status_ticker(
            ctx,
            phase_ref=phase_ref,
            interval_s=15,
            title="Auto-import status",
        )

        _status_update(phase="Loading config / roster…", detail="Reading settings / roster from DB")
        enabled = _is_auto_import_enabled()
        roster_uids, roster_names_norm = _roster_uids_and_names()
        api_seasons = _get_auto_import_api_seasons()
        _status_update(
            detail=(
                f"manual_only=True, legacy_enabled={enabled}, roster_uids={len(roster_uids)}, roster_names={len(roster_names_norm)}, "
                f"lookback_days={opts['lookback_days']}, provider={opts['provider']}, api_seasons={','.join(api_seasons)}, reset_cursor={opts['reset_cursor']}"
            )
        )

        # Roster refresh is no longer automatic because it is one API call per roster player.
        # Run `!auto_import_run refresh` only when you specifically need to queue API-side player refreshes first.
        if opts.get("refresh_roster") and roster_uids:
            roster_uid_list = sorted(list(roster_uids))
            _status_update(
                phase="Queuing roster refresh (requested)…",
                detail=f"queuing {len(roster_uid_list)} player(s) before import"
            )
            try:
                await _update_roster_players_trigger(roster_uids=roster_uid_list, ctx=None)
                _status_update(detail=f"queued {len(roster_uid_list)} player(s); starting import…")
            except Exception as e:
                _status_update(detail=f"refresh queue failed: {str(e)[:160]} (continuing without refresh)")

        _status_update(phase="Importing recent matches…", detail="Fetching recent pages only / applying cursor / writing new matches")
        await _auto_import_tick(
            bot,
            force=True,
            status_cb=_status_update,
            lookback_days=opts["lookback_days"],
            provider=opts["provider"],
        )

        final = (
            "**Auto-import status**\n"
            "✅ Completed.\n"
            f"Last run: `{_get_setting('auto_import_last_run')}`\n"
            f"Imported this run: `{_get_setting('auto_import_last_imported_count')}`\n"
            f"Summary: `{_get_setting('auto_import_last_summary', '—')}`\n"
            "Note: background auto-import is disabled. Use `!auto_import_run` after each session, or `!auto_import_run rivalsmeta` to force the backup provider."
        )
        await _stop_status_ticker(stop_event, ticker_task, status_msg, final_text=final)

        # Automatically refresh all stats channels after a successful manual import.
        # This is intentionally run only after the import completes successfully, so a failed
        # import does not trigger a stats refresh against partially updated data.
        try:
            await ctx.send("📊 Auto-import complete. Running `!run_all_stats` now…")
            cmd = bot.get_command("run_all_stats")
            if cmd and getattr(cmd, "callback", None):
                await cmd.callback(ctx)
            else:
                await ctx.send("⚠️ `run_all_stats` command was not found, so the stats refresh was skipped.")
        except Exception as e:
            await ctx.send(f"⚠️ Auto-import completed, but `!run_all_stats` failed: `{type(e).__name__}: {e}`")
            try:
                traceback.print_exc()
            except Exception:
                pass

    except Exception as e:
        err_text = f"**Auto-import status**\n❌ Failed: `{str(e)[:180]}`"
        if stop_event and ticker_task:
            await _stop_status_ticker(stop_event, ticker_task, status_msg, final_text=err_text)
        else:
            await ctx.send(err_text)
        raise

    finally:
        if stop_event and ticker_task:
            try:
                await _stop_status_ticker(stop_event, ticker_task, status_msg)
            except Exception:
                pass


@bot.command(name="auto_import_debug")
async def auto_import_debug(ctx, player_uid: str = None):
    if aiohttp is None:
        await ctx.send("aiohttp missing; cannot call API.")
        return
    if not player_uid:
        await ctx.send("Usage: !auto_import_debug <player_uid>")
        return

    async def send_chunks(text: str):
        # Discord message limit safety (~2000 chars)
        chunk = ""
        for line in text.splitlines(True):
            if len(chunk) + len(line) > 1900:
                await ctx.send(f"```{chunk}```")
                chunk = ""
            chunk += line
        if chunk.strip():
            await ctx.send(f"```{chunk}```")

    cutoff_utc = get_auto_import_cutoff_utc()
    roster_uids, roster_names_norm = _roster_uids_and_names()

    header = []
    header.append(f"Auto Import Debug for player_uid={player_uid}")
    header.append(f"auto_import_enabled={_is_auto_import_enabled()}")
    header.append(
        f"cutoff_utc={cutoff_utc.isoformat() if cutoff_utc else 'None'}")
    header.append(
        f"roster_uids={len(roster_uids)} roster_names={len(roster_names_norm)}"
    )
    header.append("Fetching match-history…")
    await send_chunks("\n".join(header))

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            hist = await _fetch_match_history_for_player(str(player_uid),
                                                         session,
                                                         skip=0)
        except Exception as e:
            await send_chunks(
                f"FAILED to fetch match-history: {type(e).__name__}: {e}")
            return

        items = (hist or {}).get("match_history") or []
        if not isinstance(items, list) or not items:
            await send_chunks("No match_history items returned.")
            return

        # Show a quick list of match_uids returned
        uid_list = []
        for it in items[:10]:
            uid_list.append(str((it or {}).get("match_uid") or ""))
        await send_chunks("Top match_uids from history:\n" +
                          "\n".join(uid_list))

        results = []
        max_checks = min(10, len(items))

        for idx in range(max_checks):
            it = items[idx] or {}
            match_uid = str(it.get("match_uid") or "").strip()
            match_ts = it.get("match_time_stamp")

            if not match_uid:
                results.append(f"[{idx}] SKIP: no match_uid in history item")
                continue

            # Convert history timestamp if available
            match_dt_hist = None
            if match_ts is not None:
                try:
                    match_dt_hist = datetime.fromtimestamp(int(match_ts),
                                                           tz=timezone.utc)
                except Exception:
                    match_dt_hist = None

            # Gate 1: cutoff (history-based)
            if match_dt_hist and cutoff_utc and match_dt_hist < cutoff_utc:
                results.append(
                    f"[{idx}] {match_uid} REJECT: before cutoff (hist={match_dt_hist.isoformat()})"
                )
                continue

            # Gate 2: already imported
            try:
                if _already_imported_in_any_season(match_uid):
                    results.append(
                        f"[{idx}] {match_uid} REJECT: already imported")
                    continue
            except Exception as e:
                results.append(
                    f"[{idx}] {match_uid} ERROR: import-check failed {type(e).__name__}: {e}"
                )
                continue

            # Fetch match details
            try:
                payload = await _fetch_match_details(match_uid, session)
            except Exception as e:
                results.append(
                    f"[{idx}] {match_uid} ERROR: fetch match-details failed {type(e).__name__}: {e}"
                )
                continue

            # Determine match datetime
            match_dt = _extract_match_datetime_utc(payload) or match_dt_hist
            if match_dt is None:
                results.append(
                    f"[{idx}] {match_uid} REJECT: cannot determine match datetime"
                )
                continue
            if cutoff_utc and match_dt < cutoff_utc:
                results.append(
                    f"[{idx}] {match_uid} REJECT: before cutoff (details={match_dt.isoformat()})"
                )
                continue

            # Season routing check
            try:
                season_id = resolve_season_for_match_time(match_dt)
                if season_id is None:
                    season_id = int(get_current_season_id())
            except Exception as e:
                results.append(
                    f"[{idx}] {match_uid} ERROR: season resolve failed {type(e).__name__}: {e}"
                )
                continue

            # Apply the custom-match gate when enabled in configuration.
            try:
                if not _is_custom_match(payload):
                    results.append(
                        f"[{idx}] {match_uid} REJECT: not custom (AUTO_IMPORT_REQUIRE_CUSTOM=True)"
                    )
                    continue
            except Exception as e:
                results.append(
                    f"[{idx}] {match_uid} ERROR: custom-check failed {type(e).__name__}: {e}"
                )
                continue

            # Gate: roster participation
            try:
                if not _passes_min_humans_each_team(payload):
                    results.append(
                        f"[{idx}] {match_uid} REJECT: roster rule not met (>=2 roster per team, >=4 total)"
                    )
                    continue
            except Exception as e:
                results.append(
                    f"[{idx}] {match_uid} ERROR: roster-check failed {type(e).__name__}: {e}"
                )
                continue

            # If you still had a draw gate, it would show here — but we are removing it.
            results.append(
                f"[{idx}] {match_uid} PASS: would import into season {season_id} (dt={match_dt.isoformat()})"
            )

        await send_chunks("Results:\n" + "\n".join(results))


@bot.command(name="match_history_probe")
async def match_history_probe(ctx,
                              player_uid: str = None,
                              pages: int = 6,
                              step: int = 20,
                              season: str = None,
                              game_mode: str = None):
    """
    Usage:
      !match_history_probe <player_uid> [pages] [step] [season] [game_mode]

    Examples:
      !match_history_probe 96894221
      !match_history_probe 96894221 6 20
      !match_history_probe 96894221 6 20 5.5
      !match_history_probe 96894221 6 20 5
      !match_history_probe 96894221 6 20 5.5 3

    Notes:
      - Uses RATE_LIMIT_429 backoff and retry handling.
      - Uses a small pacing delay between successful page fetches.
      - Supports optional season and game_mode query params (v1 endpoint).
    """
    if aiohttp is None:
        await ctx.send("aiohttp missing; cannot call API.")
        return
    if not player_uid:
        await ctx.send(
            "Usage: !match_history_probe <player_uid> [pages] [step] [season] [game_mode]"
        )
        return

    try:
        pages = max(1, min(int(pages),
                           30))  # allow up to 30 pages (still reasonable)
        step = max(1, min(int(step), 100))  # typical pagination step
    except Exception:
        await ctx.send("pages/step must be numbers.")
        return

    # Parse optional game_mode
    gm_val = None
    if game_mode not in (None, "", "None", "none", "—", "-"):
        try:
            gm_val = int(game_mode)
        except Exception:
            await ctx.send("game_mode must be a number (e.g., 3).")
            return

    # Normalise season (keep as string; API expects like '5', '5.5', etc.)
    season_val = None
    if season not in (None, "", "None", "none", "—", "-"):
        season_val = str(season).strip()

    async def send_chunks(text: str):
        chunk = ""
        for line in text.splitlines(True):
            if len(chunk) + len(line) > 1900:
                await ctx.send(f"```{chunk}```")
                chunk = ""
            chunk += line
        if chunk.strip():
            await ctx.send(f"```{chunk}```")

    async def _fetch_with_backoff(q: str, session: "aiohttp.ClientSession", *,
                                  skip: int):
        # Exponential backoff on 429, with a few retries.
        backoff = 2
        max_backoff = 30
        attempts = 7

        for _attempt in range(attempts):
            try:
                # Pass season and game mode through to the history endpoint.
                return await _fetch_match_history_for_player(q,
                                                             session,
                                                             skip=skip,
                                                             season=season_val,
                                                             game_mode=gm_val)
            except RuntimeError as e:
                if "RATE_LIMIT_429" in str(e):
                    await asyncio.sleep(backoff)
                    backoff = min(max_backoff, backoff * 2)
                    continue
                raise
        raise RuntimeError("RATE_LIMIT_429 (exceeded retry attempts)")

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        lines = []
        lines.append(f"Match History Probe for player_uid={player_uid}")
        lines.append(f"pages={pages} step={step}")
        lines.append(
            f"season={season_val if season_val is not None else '(default)'} game_mode={gm_val if gm_val is not None else '(default)'}"
        )
        lines.append("")

        seen = set()
        oldest_dt = None
        total_items = 0

        for i in range(pages):
            skip = i * step

            try:
                hist = await _fetch_with_backoff(str(player_uid),
                                                 session,
                                                 skip=skip)
            except Exception as e:
                lines.append(f"skip={skip}: ERROR {type(e).__name__}: {e}")
                break

            items = (hist or {}).get("match_history") or []
            if not isinstance(items, list):
                lines.append(f"skip={skip}: match_history not a list")
                break

            total_items += len(items)

            page_oldest = None
            page_new_uids = 0

            for it in items:
                mu = str((it or {}).get("match_uid") or "").strip()
                if mu and mu not in seen:
                    seen.add(mu)
                    page_new_uids += 1

                ts = (it or {}).get("match_time_stamp") or (it or {}).get(
                    "match_timestamp") or (it or {}).get("match_time")
                if ts is None:
                    continue
                try:
                    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                except Exception:
                    continue

                if page_oldest is None or dt < page_oldest:
                    page_oldest = dt
                if oldest_dt is None or dt < oldest_dt:
                    oldest_dt = dt

            lines.append(
                f"skip={skip}: returned={len(items)} new_uids={page_new_uids}"
                + (f" page_oldest={page_oldest.isoformat()}"
                   if page_oldest else " page_oldest=—"))

            # If empty page, end reached
            if len(items) == 0:
                break

            # Pacing delay to reduce 429s
            await asyncio.sleep(0.6)

        lines.append("")
        lines.append(
            f"Unique match_uids seen: {len(seen)} (raw items fetched: {total_items})"
        )
        lines.append(
            f"Oldest timestamp reached: {oldest_dt.isoformat() if oldest_dt else '—'}"
        )

        await send_chunks("\n".join(lines))


# ============================================================================================================
# ============================================================================================================
# COMMANDS: API Import match -> DB (ALL match data into mr_* including bots,
# HUMAN-ONLY into game_stats + streaks)
# ============================================================================================================
# ============================================================================================================


@bot.command(name="submit_match")
async def submit_match(ctx, match_or_url: str = None, game_label: str = None):
    """
    Usage:
      !submit_match <match_id_or_url>
      !submit_match <match_id_or_url> Game_141

    Behaviour:
      1) Fetches match payload from MarvelRivalsAPI or a supplied RivalsMeta URL
      2) Stores ALL match data (humans + bots) into mr_* tables (bots flagged)
      3) Inserts HUMAN-ONLY season stats into game_stats (for existing season commands)
      4) Updates streaks for humans
      5) Prints a detailed human-only match summary + bans
    """

    async def _send_long(text: str):
        max_len = 1900
        if len(text) <= max_len:
            await ctx.send(text)
            return
        buf = ""
        for line in text.split("\n"):
            if len(buf) + len(line) + 1 > max_len:
                await ctx.send(buf)
                buf = line
            else:
                buf = (buf + "\n" + line) if buf else line
        if buf:
            await ctx.send(buf)

    def _team_totals(team_rows):
        return {
            "k": sum(r["kills"] for r, _ in team_rows),
            "d": sum(r["deaths"] for r, _ in team_rows),
            "a": sum(r["assists"] for r, _ in team_rows),
            "dmg": sum(r["damage"] for r, _ in team_rows),
            "taken": sum(r["damage_taken"] for r, _ in team_rows),
            "heal": sum(r["healing"] for r, _ in team_rows),
        }

    def _sort_key(item):
        r, _raw = item
        return (r["kills"], r["damage"], r["assists"])

    def _dedupe_human_display_names(rows_with_raw):
        counts = {}
        for r, raw in rows_with_raw:
            nm = r["player"]
            counts[nm] = counts.get(nm, 0) + 1
        for r, raw in rows_with_raw:
            nm = r["player"]
            if counts.get(nm, 0) > 1:
                uid = raw.get("player_uid")
                if uid is not None:
                    r["player"] = f"{nm} ({int(uid)})"
        return rows_with_raw

    def _pick_best(rows_with_raw, want_win: bool) -> int:
        best_i = 0
        best_score = None
        for i, (r, _raw) in enumerate(rows_with_raw):
            if bool(r["win"]) != want_win:
                continue
            score = (r["kills"] * 3) + (r["assists"] * 1) + (r["damage"] /
                                                             1000.0)
            if best_score is None or score > best_score:
                best_score = score
                best_i = i
        return best_i

    # ---------- validate ----------
    if not match_or_url:
        await ctx.send(
            "Usage: `!submit_match <match_id_or_url> [optional_game_label]`")
        return

    ensure_mr_api_tables()

    match_uid = extract_match_id(match_or_url)
    if not match_uid:
        await ctx.send(
            "Could not parse match id. Provide a match id or a rivalsmeta match URL."
        )
        return

    season_id = get_current_season_id()

    # Prevent duplicate imports of same match in same season
    c.execute(
        "SELECT game_label FROM match_imports WHERE season_id=? AND match_uid=?",
        (season_id, match_uid))
    already = c.fetchone()
    if already:
        await ctx.send(
            f"That match is already imported for Season {season_id} as **{already[0]}**."
        )
        return

    # Game label default (prefer MR meta count; fallback to game_stats_v)
    if game_label is None:
        try:
            c.execute("SELECT COUNT(*) FROM mr_match_meta WHERE season_id=?",
                      (season_id, ))
            count = (c.fetchone() or [0])[0] + 1
        except Exception:
            c.execute("SELECT COUNT(DISTINCT game_label) FROM game_stats_v")
            count = (c.fetchone() or [0])[0] + 1
        game_label = f"Game_{count}"

    # If label exists already, we will overwrite (consistent with API-only workflow)
    c.execute(
        "SELECT match_uid FROM match_imports WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    existing = c.fetchone()
    if existing:
        await ctx.send(
            f"⚠️ `{game_label}` already exists in Season {season_id}; it will be replaced."
        )

    await ctx.send(f"Fetching match `{match_uid}` …")

    # ---------- fetch payload ----------
    try:
        payload, import_source = await fetch_submit_match_payload(
            match_or_url, match_uid)
    except Exception as e:
        await ctx.send(f"Failed to fetch match: {e}")
        return

    # Skip draw matches (API typically encodes draws as is_win=2)
    try:
        if _is_draw_match(payload):
            md = (payload or {}).get("match_details") or {}
            match_dt = _extract_match_datetime_utc(payload)
            gm = md.get("game_mode") or {}
            _record_skipped_match(
                match_uid,
                match_dt_utc=match_dt,
                season_id=season_id,
                reason="DRAW",
                source="submit_match",
                details={
                    "replay_id": md.get("replay_id"),
                    "game_mode_id": gm.get("game_mode_id"),
                    "game_mode_name": gm.get("game_mode_name"),
                },
            )
            await ctx.send(
                "⏭️ This match appears to be a **draw** (is_win=2). It has been skipped."
            )
            return
    except Exception:
        # If draw state can't be determined, proceed with normal import.
        pass

    md = (payload or {}).get("match_details") or {}
    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    # ---------- store ALL match data (humans + bots) into mr_* tables ----------
    try:
        upsert_match_into_mr_tables(season_id=season_id,
                                    game_label=game_label,
                                    payload=payload)
    except Exception as e:
        await ctx.send(f"DB write failed while storing match payload: {e}")
        return

    # ---------- build HUMAN rows for game_stats ----------
    mvp_uid = md.get("mvp_uid")
    svp_uid = md.get("svp_uid")

    human_rows = []
    bot_count = 0

    for p in players:
        if not isinstance(p, dict):
            continue

        if _is_bot_player(p):
            bot_count += 1
            continue

        nick = (p.get("nick_name") or p.get("nickname") or p.get("player_name")
                or "").strip()
        if not nick:
            continue

        nick = canonical_player_name(nick)
        uid = p.get("player_uid")
        result = _parse_is_win_flag(p.get("is_win"))
        is_win = (result == 1)
        is_loss = (result == 0)

        row = {
            "season_id": season_id,
            "game_label": game_label,
            "player": nick,
            "kills": int(p.get("kills") or 0),
            "deaths": int(p.get("deaths") or 0),
            "assists": int(p.get("assists") or 0),
            "damage": int(float(p.get("total_hero_damage") or 0)),
            "damage_taken": int(float(p.get("total_damage_taken") or 0)),
            "healing": int(float(p.get("total_hero_heal") or 0)),

            # Draws/unknowns are stored as win=0, loss=0 so they don't distort stats.
            "win": 1 if is_win else 0,
            "loss": 1 if is_loss else 0,
            "mvp": 1 if (mvp_uid is not None and uid == mvp_uid) else 0,
            "svp": 1 if (svp_uid is not None and uid == svp_uid) else 0,
        }

        human_rows.append((row, p))

    if not human_rows:
        await ctx.send(
            "No human players found in this match payload (only bots).")
        return

    # Avoid name collisions inside this match
    human_rows = _dedupe_human_display_names(human_rows)

    # Enforce exactly one MVP + one SVP among humans (fallback if API picked a bot)
    if sum(r["mvp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["mvp"] = 0
        human_rows[_pick_best(human_rows, True)][0]["mvp"] = 1

    if sum(r["svp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["svp"] = 0
        human_rows[_pick_best(human_rows, False)][0]["svp"] = 1

    # ---------- write HUMAN season stats into game_stats + update streaks ----------
    try:
        write_season_rows_from_match_payload(season_id,
                                             game_label,
                                             payload,
                                             overwrite_label=True,
                                             update_streaks_flag=True)
    except Exception as e:
        await ctx.send(f"DB insert failed while writing Season stats: {e}")
        return

    # ---------- bans ----------
    bans = extract_bans_from_md(md)
    ban_names = []
    for hid in (bans or [])[:12]:
        ban_names.append(await get_hero_name(str(hid)))

    # ---------- detailed output (humans only) ----------
    mode_name = ((md.get("game_mode")
                  or {}).get("game_mode_name")) or "Unknown mode"
    replay_id = md.get("replay_id")

    team0, team1, unknown = [], [], []
    for (r, raw) in human_rows:
        camp = raw.get("camp")
        if camp == 0:
            team0.append((r, raw))
        elif camp == 1:
            team1.append((r, raw))
        else:
            unknown.append((r, raw))

    if unknown:
        for (r, raw) in unknown:
            if r.get("win") == 1:
                team0.append((r, raw))
            elif r.get("loss") == 1:
                team1.append((r, raw))
            else:
                # Unknown/draw result with unknown camp: default to Team 0 to avoid biasing losses.
                team0.append((r, raw))

    team0.sort(key=_sort_key, reverse=True)
    team1.sort(key=_sort_key, reverse=True)

    tot0 = _team_totals(team0)
    tot1 = _team_totals(team1)

    w0 = sum(r["win"] for r, _ in team0)
    w1 = sum(r["win"] for r, _ in team1)

    label0 = "Team 0"
    label1 = "Team 1"
    if w0 and not w1:
        label0 += " (WIN)"
        label1 += " (LOSS)"
    elif w1 and not w0:
        label1 += " (WIN)"
        label0 += " (LOSS)"

    mvp_name = next((r["player"] for r, _ in human_rows if r.get("mvp") == 1),
                    None)
    svp_name = next((r["player"] for r, _ in human_rows if r.get("svp") == 1),
                    None)

    async def _hero_snippet(raw_player: dict) -> str:
        heroes = raw_player.get("player_heroes") or []
        if not isinstance(heroes, list) or not heroes:
            return ""

        def _pt(x):
            try:
                return float(x.get("play_time") or 0.0)
            except Exception:
                return 0.0

        heroes_sorted = sorted([h for h in heroes if isinstance(h, dict)],
                               key=_pt,
                               reverse=True)[:2]

        parts = []
        for h in heroes_sorted:
            hid = h.get("hero_id")
            if hid is None:
                continue
            hero_nm = await get_hero_name(str(int(hid)))
            sec = int(float(h.get("play_time") or 0.0))
            acc = h.get("session_hit_rate")
            acc_txt = ""
            try:
                if acc is not None:
                    acc_txt = f", Acc {float(acc)*100:.1f}%"
            except Exception:
                acc_txt = ""
            parts.append(f"{hero_nm} {_fmt_time(sec)}{acc_txt}")
        return " • Heroes: " + " | ".join(parts) if parts else ""

    out = []
    out.append(
        f"✅ Imported match `{match_uid}` → **Season {season_id}** / **{game_label}**"
    )
    out.append(f"Source: **{import_source}**")
    out.append(f"Mode: **{mode_name}**" +
               (f" • Replay: `{replay_id}`" if replay_id else ""))

    if bot_count:
        out.append(
            f"Hidden bot players stored: **{bot_count}** (available for future bot-only commands)"
        )

    out.append(f"MVP: **{mvp_name or '—'}** • SVP: **{svp_name or '—'}**")
    out.append("Bans: " + (", ".join(
        f"**{bn}**" for bn in ban_names) if bans else "**None detected**"))

    out.append("")
    out.append(
        f"**{label0}** — Totals: {tot0['k']}/{tot0['d']}/{tot0['a']} • DMG {tot0['dmg']} • Taken {tot0['taken']} • Heal {tot0['heal']}"
    )
    for r, raw in team0:
        tags = []
        if r.get("mvp") == 1: tags.append("MVP")
        if r.get("svp") == 1: tags.append("SVP")
        tag_s = (" " + " ".join(tags)) if tags else ""
        hero_s = await _hero_snippet(raw)
        out.append(
            f"- {r['player']}: {r['kills']}/{r['deaths']}/{r['assists']} • DMG {r['damage']} • Taken {r['damage_taken']} • Heal {r['healing']}{tag_s}{hero_s}"
        )

    out.append("")
    out.append(
        f"**{label1}** — Totals: {tot1['k']}/{tot1['d']}/{tot1['a']} • DMG {tot1['dmg']} • Taken {tot1['taken']} • Heal {tot1['heal']}"
    )
    for r, raw in team1:
        tags = []
        if r.get("mvp") == 1: tags.append("MVP")
        if r.get("svp") == 1: tags.append("SVP")
        tag_s = (" " + " ".join(tags)) if tags else ""
        hero_s = await _hero_snippet(raw)
        out.append(
            f"- {r['player']}: {r['kills']}/{r['deaths']}/{r['assists']} • DMG {r['damage']} • Taken {r['damage_taken']} • Heal {r['healing']}{tag_s}{hero_s}"
        )

    await _send_long("\n".join(out))


# ============================================================
# COMMAND: hero_time (humans only)
# ============================================================


@bot.command(name="hero_time")
async def hero_time(ctx, *, player_name: str = None):
    """
    Usage:
      !hero_time
      !hero_time LatinMaestro
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    canonical_name = canonical_player_name(player_name.strip()) if player_name else None
    by_player = _get_hero_time_by_player(c, season_id, canonical_name)
    if not by_player:
        await ctx.send(
            "No hero time data yet. Import matches first with `!submit_match`."
        )
        return

    lines = []
    if player_name:
        p = list(by_player.keys())[0]
        lines.append(f"**Hero time — {p} (Season {season_id})**")
        for hid, sec in by_player[p][:12]:
            hero_nm = await get_hero_name(hid)
            lines.append(f"- {hero_nm}: {_fmt_time(sec)}")
    else:
        lines.append(f"**Hero time (top 5 per player) — Season {season_id}**")
        for p in sorted(by_player.keys()):
            top = by_player[p][:5]
            pretty = []
            for hid, sec in top:
                hero_nm = await get_hero_name(hid)
                pretty.append(f"{hero_nm} {_fmt_time(sec)}")
            lines.append(f"- **{p}:** " + " • ".join(pretty))

    await ctx.send("\n".join(lines))


# ============================================================================================================
# Command - player_heros (dropdown -> image table, plus "All" to show top 20 Hero+Player dominance)
# ============================================================================================================

# --- Hero eligibility rules for win-rate/match counting (exclude swap heroes) ---
HERO_WIN_MIN_SECONDS = 120  # hero must be played >= 2:00 in that match to count toward Win%/eligible matches
HERO_WIN_MIN_RATIO = 0.20  # AND hero must be >= 20% of the player's match time to count toward Win%/eligible matches

# --- Season dominance thresholds (avoid 1-game 100% entries) ---
DOM_MIN_ELIG_MATCHES = 10  # minimum eligible matches for a hero+player to appear in "All"
DOM_MIN_ELIG_SECONDS = 3600  # minimum eligible time (1 hr) for a hero+player to appear in "All"
DOM_TOP_N = 30


def _get_player_hero_rows_api(
        season_id: int,
        player_uid: int,
        min_sec: int = HERO_WIN_MIN_SECONDS,
        min_ratio: float = HERO_WIN_MIN_RATIO) -> list[dict]:
    """
    Returns per-hero stats for a player for the given season:
      - total seconds (all time on hero)
      - avg K/D/A per match (across ALL matches where hero appeared)
      - win% based only on ELIGIBLE hero appearances:
            hero_seconds >= min_sec AND hero_seconds / player_total_match_seconds >= min_ratio
      - matches shown as eligible only
    """
    ensure_mr_api_tables()

    c.execute(
        """
        WITH hs AS (
            SELECT
                season_id, match_uid, game_label, player_uid, is_bot,
                hero_id,
                COALESCE(seconds,0) AS seconds,
                COALESCE(kills,0)   AS kills,
                COALESCE(deaths,0)  AS deaths,
                COALESCE(assists,0) AS assists
            FROM mr_hero_segments
            WHERE season_id = ?
              AND player_uid = ?
              AND is_bot = 0
        ),
        match_tot AS (
            SELECT
                season_id, match_uid, game_label, player_uid, is_bot,
                SUM(seconds) AS total_sec
            FROM hs
            GROUP BY season_id, match_uid, game_label, player_uid, is_bot
        ),
        joined AS (
            SELECT
                hs.hero_id,
                hs.match_uid,
                hs.seconds,
                hs.kills, hs.deaths, hs.assists,
                mt.total_sec,
                COALESCE(pm.is_win,0) AS is_win
            FROM hs
            JOIN match_tot mt
              ON mt.season_id  = hs.season_id
             AND mt.match_uid  = hs.match_uid
             AND mt.game_label = hs.game_label
             AND mt.player_uid = hs.player_uid
             AND mt.is_bot     = hs.is_bot
            JOIN mr_player_match pm
              ON pm.season_id  = hs.season_id
             AND pm.match_uid  = hs.match_uid
             AND pm.game_label = hs.game_label
             AND pm.player_uid = hs.player_uid
             AND pm.is_bot     = hs.is_bot
        )
        SELECT
            hero_id,
            SUM(seconds) AS total_seconds,
            SUM(kills)   AS k,
            SUM(deaths)  AS d,
            SUM(assists) AS a,

            COUNT(DISTINCT match_uid) AS matches_any,

            COUNT(DISTINCT CASE
                WHEN seconds >= ?
                 AND total_sec > 0
                 AND (1.0 * seconds / total_sec) >= ?
                THEN match_uid END
            ) AS matches_elig,

            SUM(CASE
                WHEN seconds >= ?
                 AND total_sec > 0
                 AND (1.0 * seconds / total_sec) >= ?
                 AND is_win = 1
                THEN 1 ELSE 0 END
            ) AS wins_elig
        FROM joined
        GROUP BY hero_id
        HAVING total_seconds > 0
        ORDER BY total_seconds DESC
    """, (int(season_id), int(player_uid), int(min_sec), float(min_ratio),
          int(min_sec), float(min_ratio)))

    rows = []
    for hero_id, total_seconds, k, d, a, matches_any, matches_elig, wins_elig in c.fetchall(
    ):
        matches_any = int(matches_any or 0)
        denom_any = max(1, matches_any)

        rows.append({
            "hero_id": int(hero_id),
            "seconds": int(total_seconds or 0),

            # Avg K/D/A across ALL matches hero appeared in
            "avg_k": (int(k or 0) / denom_any),
            "avg_d": (int(d or 0) / denom_any),
            "avg_a": (int(a or 0) / denom_any),
            "matches_elig": int(matches_elig or 0),
            "wins_elig": int(wins_elig or 0),
        })

    return rows


def _get_top_dominant_hero_player_rows_api(
        season_id: int,
        min_sec: int = HERO_WIN_MIN_SECONDS,
        min_ratio: float = HERO_WIN_MIN_RATIO,
        min_matches: int = DOM_MIN_ELIG_MATCHES,
        min_seconds: int = DOM_MIN_ELIG_SECONDS,
        top_n: int = DOM_TOP_N) -> list[dict]:
    """
    Returns top N (hero, player) combinations across the season:
      - eligible matches/wins/time only (filters out swaps)
      - avg K/D/A per eligible match
      - sorted by win% then K/D/A then eligible matches
    """
    ensure_mr_api_tables()

    c.execute(
        """
        WITH hs AS (
            SELECT
                season_id, match_uid, game_label, player_uid, is_bot,
                hero_id,
                COALESCE(seconds,0) AS seconds,
                COALESCE(kills,0)   AS kills,
                COALESCE(deaths,0)  AS deaths,
                COALESCE(assists,0) AS assists
            FROM mr_hero_segments
            WHERE season_id = ?
              AND is_bot = 0
        ),
        match_tot AS (
            SELECT
                season_id, match_uid, game_label, player_uid, is_bot,
                SUM(seconds) AS total_sec
            FROM hs
            GROUP BY season_id, match_uid, game_label, player_uid, is_bot
        ),
        joined AS (
            SELECT
                hs.hero_id,
                hs.player_uid,
                hs.match_uid,
                hs.seconds,
                hs.kills, hs.deaths, hs.assists,
                mt.total_sec,
                COALESCE(pm.is_win,0) AS is_win
            FROM hs
            JOIN match_tot mt
              ON mt.season_id  = hs.season_id
             AND mt.match_uid  = hs.match_uid
             AND mt.game_label = hs.game_label
             AND mt.player_uid = hs.player_uid
             AND mt.is_bot     = hs.is_bot
            JOIN mr_player_match pm
              ON pm.season_id  = hs.season_id
             AND pm.match_uid  = hs.match_uid
             AND pm.game_label = hs.game_label
             AND pm.player_uid = hs.player_uid
             AND pm.is_bot     = hs.is_bot
            WHERE hs.season_id = ?
        ),
        elig AS (
            SELECT
                hero_id,
                player_uid,
                match_uid,
                seconds,
                kills, deaths, assists,
                is_win
            FROM joined
            WHERE seconds >= ?
              AND total_sec > 0
              AND (1.0 * seconds / total_sec) >= ?
        )
        SELECT
            hero_id,
            player_uid,
            COUNT(DISTINCT match_uid) AS matches_elig,
            SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) AS wins_elig,
            SUM(seconds) AS seconds_elig,
            SUM(kills)   AS k_elig,
            SUM(deaths)  AS d_elig,
            SUM(assists) AS a_elig
        FROM elig
        GROUP BY hero_id, player_uid
        HAVING matches_elig >= ?
           AND seconds_elig >= ?
    """, (int(season_id), int(season_id), int(min_sec), float(min_ratio),
          int(min_matches), int(min_seconds)))

    rows = []
    for hero_id, player_uid, m, w, sec, k, d, a in c.fetchall():
        m = int(m or 0)
        w = int(w or 0)
        sec = int(sec or 0)
        k = int(k or 0)
        d = int(d or 0)
        a = int(a or 0)
        if m <= 0:
            continue

        win_pct = (w / m) * 100.0
        avg_k = k / m
        avg_d = d / m
        avg_a = a / m

        rows.append({
            "hero_id": int(hero_id),
            "player_uid": int(player_uid),
            "matches": m,
            "wins": w,
            "seconds": sec,
            "win_pct": win_pct,
            "avg_k": avg_k,
            "avg_d": avg_d,
            "avg_a": avg_a,
        })

    # Sort as requested: Win% desc, then K/D/A desc (using (K+A)/max(1,D) as a tie-break score), then matches desc
    def kda_score(r: dict) -> float:
        return (r["avg_k"] + r["avg_a"]) / max(1e-9, r["avg_d"])

    rows.sort(key=lambda r: (r["win_pct"], kda_score(r), r["matches"]),
              reverse=True)
    return rows[:top_n]


def _render_player_heros_card(player_name: str, season_id: int,
                              rows: list[dict]) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)
    draw.text((pad * 2, int(pad * 1.4)),
              f"{player_name} — Season {season_id} • Heroes Played",
              font=title_font,
              fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    draw.text((left_x, y), "Hero", font=body_font, fill=muted)
    draw.text((left_x + 520, y), "Time", font=body_font, fill=muted)
    draw.text((left_x + 680, y), "Avg K/D/A", font=body_font, fill=muted)
    draw.text((left_x + 980, y), "Win%", font=body_font, fill=muted)
    draw.text((left_x + 1120, y), "Matches", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    max_rows = 18
    for r in rows[:max_rows]:
        hero_nm = str(r.get("hero_name", r["hero_id"]))[:28]
        time_txt = _fmt_time(int(r["seconds"]))
        kda_txt = f"{r['avg_k']:.1f}/{r['avg_d']:.1f}/{r['avg_a']:.1f}"

        m_elig = int(r["matches_elig"])
        w_elig = int(r["wins_elig"])
        win_txt = "—" if m_elig == 0 else f"{(w_elig / m_elig) * 100.0:.1f}%"

        matches_txt = f"{m_elig}"  # eligible matches only (as requested)

        draw.text((left_x, y), hero_nm, font=body_font, fill=text)
        draw.text((left_x + 520, y), time_txt, font=body_font, fill=text)
        draw.text((left_x + 680, y), kda_txt, font=body_font, fill=text)
        draw.text((left_x + 980, y), win_txt, font=body_font, fill=text)
        draw.text((left_x + 1120, y), matches_txt, font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    draw.text(
        (left_x, y_footer),
        f"Win%/Matches count only eligible games: hero ≥ {HERO_WIN_MIN_SECONDS}s AND ≥ {int(HERO_WIN_MIN_RATIO * 100)}% of your match time.",
        font=body_font,
        fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _render_dominant_hero_player_card(season_id: int,
                                      rows: list[dict]) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)
    draw.text(
        (pad * 2, int(pad * 1.4)),
        f"Season {season_id} • Most Dominant Hero + Player (Top {DOM_TOP_N})",
        font=title_font,
        fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    draw.text((left_x, y), "Hero", font=body_font, fill=muted)
    draw.text((left_x + 360, y), "Player", font=body_font, fill=muted)
    draw.text((left_x + 770, y), "Time", font=body_font, fill=muted)
    draw.text((left_x + 930, y), "Avg K/D/A", font=body_font, fill=muted)
    draw.text((left_x + 1220, y), "Win%", font=body_font, fill=muted)
    draw.text((left_x + 1340, y), "Games", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    max_rows = 18
    for r in rows[:max_rows]:
        hero_nm = str(r.get("hero_name", r["hero_id"]))[:18]
        player_nm = str(r.get("player_name", r["player_uid"]))[:22]
        time_txt = _fmt_time(int(r["seconds"]))
        kda_txt = f"{r['avg_k']:.1f}/{r['avg_d']:.1f}/{r['avg_a']:.1f}"
        win_txt = f"{r['win_pct']:.1f}%"
        games_txt = f"{int(r['matches'])}"

        draw.text((left_x, y), hero_nm, font=body_font, fill=text)
        draw.text((left_x + 360, y), player_nm, font=body_font, fill=text)
        draw.text((left_x + 770, y), time_txt, font=body_font, fill=text)
        draw.text((left_x + 930, y), kda_txt, font=body_font, fill=text)
        draw.text((left_x + 1220, y), win_txt, font=body_font, fill=text)
        draw.text((left_x + 1340, y), games_txt, font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    draw.text(
        (left_x, y_footer),
        f"Eligibility: hero ≥ {HERO_WIN_MIN_SECONDS}s and ≥ {int(HERO_WIN_MIN_RATIO*100)}% of match time. "
        f"Minimum to rank: ≥ {DOM_MIN_ELIG_MATCHES} games and ≥ {_fmt_time(DOM_MIN_ELIG_SECONDS)} on that hero.",
        font=body_font,
        fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def _build_player_heros_image(season_id: int,
                                    player_uid: int) -> io.BytesIO | None:
    player_name = _get_player_display_name(season_id, player_uid)
    rows = _get_player_hero_rows_api(season_id, player_uid)
    if not rows:
        return None

    hero_ids = list({str(r["hero_id"]) for r in rows})
    results = await asyncio.gather(*[get_hero_name(hid) for hid in hero_ids],
                                   return_exceptions=True)
    hero_map: dict[int, str] = {}
    for hid, nm in zip(hero_ids, results):
        hero_map[int(hid)] = nm if isinstance(nm, str) else hid

    for r in rows:
        r["hero_name"] = hero_map.get(int(r["hero_id"]), str(r["hero_id"]))

    return _render_player_heros_card(player_name, season_id, rows)


async def _build_dominant_hero_player_image(
        season_id: int) -> io.BytesIO | None:
    rows = _get_top_dominant_hero_player_rows_api(season_id)
    if not rows:
        return None

    # Resolve hero names
    hero_ids = list({str(r["hero_id"]) for r in rows})
    hero_names = await asyncio.gather(
        *[get_hero_name(hid) for hid in hero_ids], return_exceptions=True)
    hero_map: dict[int, str] = {}
    for hid, nm in zip(hero_ids, hero_names):
        hero_map[int(hid)] = nm if isinstance(nm, str) else hid

    # Resolve player names (local helper, no await)
    player_uids = list({int(r["player_uid"]) for r in rows})
    player_map: dict[int, str] = {
        uid: _get_player_display_name(season_id, uid)
        for uid in player_uids
    }

    for r in rows:
        r["hero_name"] = hero_map.get(int(r["hero_id"]), str(r["hero_id"]))
        r["player_name"] = player_map.get(int(r["player_uid"]),
                                          str(r["player_uid"]))

    return _render_dominant_hero_player_card(season_id, rows)


class PlayerHerosSelectView(discord.ui.View):

    def __init__(self, season_id: int, players: list[dict]):
        super().__init__(timeout=120)
        self.season_id = int(season_id)

        options = [
            discord.SelectOption(label="All (Top 20 Dominant)", value="ALL")
        ]
        for p in players[:24]:  # keep total <= 25
            disp = str(p["player"])
            uid = int(p["player_uid"])
            options.append(
                discord.SelectOption(label=disp[:100], value=str(uid)))

        select = discord.ui.Select(placeholder="Select a player (or All)…",
                                   min_values=1,
                                   max_values=1,
                                   options=options)

        async def _on_select(interaction: discord.Interaction):
            await interaction.response.defer()

            if select.values[0] == "ALL":
                buf = await _build_dominant_hero_player_image(self.season_id)
                if buf is None:
                    await interaction.followup.send(
                        "No eligible hero data found for the season yet. Import matches first with `!submit_match`."
                    )
                    return
                await interaction.followup.send(file=discord.File(
                    fp=buf, filename=f"dominant_heros_s{self.season_id}.png"))
                return

            uid = int(select.values[0])
            buf = await _build_player_heros_image(self.season_id, uid)
            if buf is None:
                await interaction.followup.send(
                    "No hero segment data found for that player in the current season. Import matches first with `!submit_match`."
                )
                return

            await interaction.followup.send(file=discord.File(
                fp=buf, filename=f"player_heros_{uid}_s{self.season_id}.png"))

        select.callback = _on_select
        self.add_item(select)




@bot.command(name="player_heros", aliases=["player_heroes"])
async def player_heros(ctx, *, player_name: Optional[str] = None):
    """
    Usage:
      !player_heros            -> dropdown with "All"
      !player_heros <player>   -> direct player lookup
      !player_heros all        -> direct season dominance table
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # Direct "all"
    if player_name and player_name.strip().lower() == "all":
        buf = await _build_dominant_hero_player_image(season_id)
        if buf is None:
            await ctx.send(
                "No eligible hero data found for the season yet. Import matches first with `!submit_match`."
            )
            return
        await ctx.send(file=discord.File(
            fp=buf, filename=f"dominant_heros_s{season_id}.png"))
        return

    # Direct player
    if player_name:
        uid = _resolve_player_uid(season_id, player_name)
        if uid is None:
            await ctx.send(
                "Couldn't find that player in the current season. Try `!player_heros` to pick from a list."
            )
            return
        buf = await _build_player_heros_image(season_id, uid)
        if buf is None:
            await ctx.send(
                "No hero segment data found for that player. Import matches first with `!submit_match`."
            )
            return
        await ctx.send(file=discord.File(
            fp=buf, filename=f"player_heros_{uid}_s{season_id}.png"))
        return

    # Dropdown
    players = _get_api_players(season_id)
    if not players:
        await ctx.send(
            "No API-imported players found yet. Import matches first with `!submit_match ...`."
        )
        return

    await ctx.send(
        f"Select a player (or All) to view hero dominance (Season {season_id}):",
        view=PlayerHerosSelectView(season_id, players))


# ============================================================
# COMMAND: hero_bans
# ============================================================


@bot.command(name="hero_bans")
async def hero_bans(ctx):
    """
    Season ban counts (from match_dynamic_fields.ban_pick_info → hero_bans table).
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    rows = _get_top_hero_bans(c, season_id, limit=30)
    if not rows:
        await ctx.send(f"No ban data recorded for Season {season_id} yet. "
                       "Import matches first using `!submit_match`.")
        return

    lines = [f"**Season {season_id} — Hero bans (top 30)**"]
    for hero_id, ban_events in rows:
        hero_nm = await get_hero_name(str(hero_id))
        lines.append(f"- {hero_nm}: **{int(ban_events)}** bans")

    await ctx.send("\n".join(lines))

# =========================
# Player Bans (ENEMY bans vs each player) — styled like player_heros
# =========================
@bot.command(name="player_bans")
async def player_bans(ctx):
    """
    Main table: Player | Eligible Games | Enemy Ban #1 | #2 | #3
      - Counts ONLY bans made by the opposing team in matches the player appeared in.
      - "Games" counts only eligible matches (we know player's camp AND bans exist).

    Under-table: Top 5 highest enemy-ban rates overall (unique heroes; min games).
    """
    global c, conn

    # IMPORTANT: import BEFORE any use (prevents UnboundLocalError)
    from collections import defaultdict, Counter

    season_id = get_current_season_id()

    # Ensure tables exist
    try:
        ensure_mr_api_tables()
    except Exception:
        await ctx.send("Database tables are not initialised yet. Please run the startup init once.")
        return

    # Avoid command-triggered API calls by default. Run !refresh_heroes manually when cache needs updating.
    if _allow_command_hero_cache_refresh():
        try:
            await refresh_hero_cache(force=False)
        except Exception:
            pass

    hero_map = _load_hero_name_map()

    def hero_label(hid) -> str:
        hs = _safe_str(hid)
        return hero_map.get(hs, hs if hs else "-")

    def _clip(s: str, n: int) -> str:
        s = s or ""
        return s if len(s) <= n else (s[: max(0, n - 1)] + "…")

    def _norm_side(v):
        """
        Normalise side/team values into 0/1.
        Accepts:
          - 0/1 (returns as-is)
          - 1/2 (converts to 0/1)
        Returns None if unknown.
        """
        try:
            i = int(v)
        except Exception:
            return None
        if i in (0, 1):
            return i
        if i in (1, 2):
            return i - 1
        return None

    # ---------------------------------------------------------------------
    # Build: player_matches + player_side from mr_player_match (exclude bots)
    # ---------------------------------------------------------------------
    try:
        pm_rows = load_human_player_matches(c, season_id)
    except Exception as e:
        await ctx.send(f"Could not read mr_player_match: {repr(e)}")
        return

    player_matches = defaultdict(set)   # player -> set(match_uid)
    player_side = {}                   # (player, match_uid) -> 0/1

    for mid, player, camp in pm_rows:
        mid_s = _safe_str(mid)
        p_s = _safe_str(player)
        if not mid_s or not p_s:
            continue
        player_matches[p_s].add(mid_s)

        s = _norm_side(camp)
        if s is not None:
            player_side[(p_s, mid_s)] = s

    if not player_matches:
        await ctx.send("No player/match data found for the current season.")
        return

    # ---------------------------------------------------------------------
    # Build: bans_by_match_side from mr_ban_picks (is_pick = 0 => bans)
    # ---------------------------------------------------------------------
    try:
        ban_rows = load_ban_events(c, season_id)
    except Exception as e:
        await ctx.send(f"Could not read mr_ban_picks: {repr(e)}")
        return

    if not ban_rows:
        await ctx.send("No ban data found for the current season (mr_ban_picks returned 0 rows).")
        return

    bans_by_match_side = defaultdict(lambda: {0: [], 1: []})  # mid -> {0:[hid], 1:[hid]}
    for mid, bside, hid in ban_rows:
        mid_s = _safe_str(mid)
        hid_s = _safe_str(hid)
        s = _norm_side(bside)
        if not mid_s or not hid_s or s is None:
            continue
        bans_by_match_side[mid_s][s].append(hid_s)

    matches_with_bans = set(bans_by_match_side.keys())

    def _enemy_bans_for(player: str, mid: str) -> list[str]:
        """
        Returns bans made by the opposing team in match 'mid' against 'player'.
        """
        s = player_side.get((player, mid))
        if s not in (0, 1):
            return []
        enemy = 1 - s
        return bans_by_match_side.get(mid, {}).get(enemy, []) or []

    # ---------------------------------------------------------------------
    # Build per-player top 3 (enemy bans only)
    # ---------------------------------------------------------------------
    table_rows = []

    for player in sorted(player_matches.keys(), key=lambda x: x.lower()):
        mids = player_matches[player]

        eligible_mids = [
            mid for mid in mids
            if mid in matches_with_bans and player_side.get((player, mid)) in (0, 1)
        ]
        games = len(eligible_mids)
        if games <= 0:
            continue

        counter = Counter()
        for mid in eligible_mids:
            for b in _enemy_bans_for(player, mid):
                if b:
                    counter[b] += 1

        top3 = counter.most_common(3)

        def fmt(item):
            if not item:
                return "-"
            hid, cnt = item
            pct = (cnt / games) * 100.0
            # keep it compact for the table
            return f"{_clip(hero_label(hid), 18)} ({cnt}, {pct:.0f}%)"

        b1 = top3[0] if len(top3) > 0 else None
        b2 = top3[1] if len(top3) > 1 else None
        b3 = top3[2] if len(top3) > 2 else None

        table_rows.append({
            "player": player,
            "games": games,
            "b1": fmt(b1),
            "b2": fmt(b2),
            "b3": fmt(b3),
        })

    if not table_rows:
        await ctx.send("No eligible matches with bans + known teams were found for this season.")
        return

    # Sort main table by eligible games desc
    table_rows.sort(key=lambda r: r["games"], reverse=True)

    # ---------------------------------------------------------------------
    # Top 5 overall enemy-ban rates (unique hero), using each player's Top 3
    # ---------------------------------------------------------------------
    MIN_GAMES_TOP5 = 5
    CANDIDATES_PER_PLAYER = 3

    top_candidates = []  # (rate, games, cnt, player, hero)

    for r in table_rows:
        player = r["player"]
        games = int(r["games"])
        if games < MIN_GAMES_TOP5:
            continue

        counter = Counter()
        mids = player_matches.get(player, set())
        eligible_mids = [
            mid for mid in mids
            if mid in matches_with_bans and player_side.get((player, mid)) in (0, 1)
        ]
        games = len(eligible_mids)
        if games < MIN_GAMES_TOP5:
            continue

        for mid in eligible_mids:
            for b in _enemy_bans_for(player, mid):
                if b:
                    counter[b] += 1

        for hid, cnt in counter.most_common(CANDIDATES_PER_PLAYER):
            rate = cnt / games
            top_candidates.append((rate, games, cnt, player, hid))

    top_candidates.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

    seen_heroes = set()
    top5 = []
    for rate, games, cnt, player, hid in top_candidates:
        hs = _safe_str(hid)
        if not hs or hs in seen_heroes:
            continue
        seen_heroes.add(hs)
        top5.append((rate, games, cnt, player, hid))
        if len(top5) >= 5:
            break

    # ---------------------------------------------------------------------
    # Render (styled like player_heros)
    # ---------------------------------------------------------------------
    W, H = 1500, 980
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Enemy Team Bans vs Players — Season {season_id}"
    draw.text((pad * 2, int(pad * 1.4)), title, font=title_font, fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    # Column x positions (fit inside the card)
    x_player = left_x
    x_games = left_x + 300
    x_b1 = left_x + 400
    x_b2 = left_x + 730
    x_b3 = left_x + 1060

    # Headers
    draw.text((x_player, y), "Player", font=body_font, fill=muted)
    draw.text((x_games, y), "Games", font=body_font, fill=muted)
    draw.text((x_b1, y), "Enemy Ban #1", font=body_font, fill=muted)
    draw.text((x_b2, y), "Enemy Ban #2", font=body_font, fill=muted)
    draw.text((x_b3, y), "Enemy Ban #3", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    # Main rows (limit to keep a consistent card height)
    max_main_rows = 15
    for r in table_rows[:max_main_rows]:
        draw.text((x_player, y), _clip(r["player"], 18), font=body_font, fill=text)
        draw.text((x_games, y), str(r["games"]), font=body_font, fill=text)
        draw.text((x_b1, y), _clip(r["b1"], 28), font=body_font, fill=text)
        draw.text((x_b2, y), _clip(r["b2"], 28), font=body_font, fill=text)
        draw.text((x_b3, y), _clip(r["b3"], 28), font=body_font, fill=text)
        y += 32

    # Divider before summary
    y += 6
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    # Summary title
    draw.text(
        (left_x, y),
        f"Top 5 highest enemy-ban rates (unique heroes; min {MIN_GAMES_TOP5} games)",
        font=body_font,
        fill=muted,
    )
    y += 34

    # Summary headers
    x_rank = left_x
    x_sp = left_x + 90
    x_hero = left_x + 390
    x_cnt = left_x + 760
    x_rate = left_x + 900

    draw.text((x_rank, y), "Rank", font=body_font, fill=muted)
    draw.text((x_sp, y), "Player", font=body_font, fill=muted)
    draw.text((x_hero, y), "Hero", font=body_font, fill=muted)
    draw.text((x_cnt, y), "Count", font=body_font, fill=muted)
    draw.text((x_rate, y), "Rate", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for i, (rate, games, cnt, player, hid) in enumerate(top5, start=1):
        draw.text((x_rank, y), f"#{i}", font=body_font, fill=text)
        draw.text((x_sp, y), _clip(player, 18), font=body_font, fill=text)
        draw.text((x_hero, y), _clip(hero_label(hid), 22), font=body_font, fill=text)
        draw.text((x_cnt, y), str(cnt), font=body_font, fill=text)
        draw.text((x_rate, y), f"{rate*100:.0f}%", font=body_font, fill=text)
        y += 32

    # Footer note
    footer = "Games count only matches with recorded bans + known team side. Bans shown are the opposing team’s bans."
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    await ctx.send(file=discord.File(fp=buf, filename="player_bans.png"))

# =========================
# =========================
# =========================
# =========================
# =========================
# =========================
# More Selected Top-3 Exposure
# =========================
TOP3_MORE_MIN_GAMES_FOR_LIFT = 3


def _top3_more_clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _top3_more_side_map(camp_values):
    """
    Robustly map raw camp values into team 0 / team 1 on a per-match basis.
    Supports either {0,1} or {1,2}. Falls back to the first two sorted values.
    """
    vals = {int(v) for v in camp_values if v is not None}
    if vals == {0, 1} or vals <= {0, 1}:
        return {0: 0, 1: 1}
    if vals == {1, 2} or vals <= {1, 2}:
        return {1: 0, 2: 1}

    ordered = sorted(vals)
    if len(ordered) >= 2:
        return {ordered[0]: 0, ordered[1]: 1}
    return None


def _top3_more_build_base(season_id: int, top3_uids: list[int]) -> dict:
    """
    Builds base counts for the selected top 3.

    Qualifying match:
      - one team had MORE of the selected top 3 than the other team
      - examples: 1-0, 2-0, 2-1, 3-0, 3-1, 3-2

    Returns base rows with:
      - all-game totals
      - qualifying-game totals
      - advantaged-team totals
      - against-advantaged-team totals
    """
    ensure_mr_api_tables()
    season_id = int(season_id)
    top3_set = {int(x) for x in (top3_uids or []) if x is not None}

    if len(top3_set) != 3:
        raise ValueError("Exactly 3 selected players are required.")

    raw_rows = _load_top3_human_match_rows(c, season_id)

    if not raw_rows:
        return {
            "rows_base": [],
            "summary": {
                "total_matches": 0,
                "qualifying_matches": 0,
                "equal_matches": 0,
                "no_selected_matches": 0,
                "balanced_selected_matches": 0,
                "diff1_matches": 0,
                "diff2plus_matches": 0,
            },
        }

    by_match_raw = defaultdict(list)
    display_name = {}

    for match_uid, uid, player, camp, is_win in raw_rows:
        try:
            uid_i = int(uid)
        except Exception:
            continue

        match_s = str(match_uid or "").strip()
        player_s = str(player or "").strip() or f"UID_{uid_i}"

        if not match_s:
            continue

        try:
            camp_i = int(camp)
        except Exception:
            continue

        is_win_i = 1 if int(is_win or 0) == 1 else 0
        display_name[uid_i] = player_s
        by_match_raw[match_s].append((uid_i, player_s, camp_i, is_win_i))

    all_games = defaultdict(int)
    all_wins = defaultdict(int)

    qual_games = defaultdict(int)
    qual_wins = defaultdict(int)

    more_games = defaultdict(int)
    more_wins = defaultdict(int)
    more_by1 = defaultdict(int)
    more_by2plus = defaultdict(int)

    vs_more_games = defaultdict(int)
    vs_more_wins = defaultdict(int)

    total_matches = 0
    qualifying_matches = 0
    equal_matches = 0
    no_selected_matches = 0
    balanced_selected_matches = 0
    diff1_matches = 0
    diff2plus_matches = 0

    for _match_uid, members in by_match_raw.items():
        side_map = _top3_more_side_map([m[2] for m in members])
        if not side_map:
            continue

        teams = {0: [], 1: []}
        valid_rows = 0

        for uid_i, player_s, camp_i, is_win_i in members:
            if camp_i not in side_map:
                continue
            side = side_map[camp_i]
            teams[side].append((uid_i, player_s, is_win_i))
            all_games[uid_i] += 1
            all_wins[uid_i] += is_win_i
            valid_rows += 1

        if valid_rows == 0:
            continue

        total_matches += 1

        team0 = teams.get(0) or []
        team1 = teams.get(1) or []

        top0 = sum(1 for uid_i, _nm, _w in team0 if uid_i in top3_set)
        top1 = sum(1 for uid_i, _nm, _w in team1 if uid_i in top3_set)
        diff = top0 - top1

        if diff == 0:
            equal_matches += 1
            if top0 == 0:
                no_selected_matches += 1
            else:
                balanced_selected_matches += 1
            continue

        qualifying_matches += 1
        if abs(diff) == 1:
            diff1_matches += 1
        else:
            diff2plus_matches += 1

        for uid_i, _nm, is_win_i in (team0 + team1):
            qual_games[uid_i] += 1
            qual_wins[uid_i] += is_win_i

        advantaged_team = 0 if diff > 0 else 1
        disadvantaged_team = 1 if diff > 0 else 0

        for uid_i, _nm, is_win_i in teams[advantaged_team]:
            more_games[uid_i] += 1
            more_wins[uid_i] += is_win_i
            if abs(diff) == 1:
                more_by1[uid_i] += 1
            else:
                more_by2plus[uid_i] += 1

        for uid_i, _nm, is_win_i in teams[disadvantaged_team]:
            vs_more_games[uid_i] += 1
            vs_more_wins[uid_i] += is_win_i

    rows_base = []
    all_uids = sorted(display_name.keys(), key=lambda u: display_name[u].lower())

    for uid_i in all_uids:
        rows_base.append({
            "player_uid": uid_i,
            "player": display_name.get(uid_i, f"UID_{uid_i}"),
            "is_top3": uid_i in top3_set,
            "all_games": int(all_games.get(uid_i, 0)),
            "all_wins": int(all_wins.get(uid_i, 0)),
            "qual_games": int(qual_games.get(uid_i, 0)),
            "qual_wins": int(qual_wins.get(uid_i, 0)),
            "more_games": int(more_games.get(uid_i, 0)),
            "more_wins": int(more_wins.get(uid_i, 0)),
            "more_by1": int(more_by1.get(uid_i, 0)),
            "more_by2plus": int(more_by2plus.get(uid_i, 0)),
            "vs_more_games": int(vs_more_games.get(uid_i, 0)),
            "vs_more_wins": int(vs_more_wins.get(uid_i, 0)),
        })

    return {
        "rows_base": rows_base,
        "summary": {
            "total_matches": total_matches,
            "qualifying_matches": qualifying_matches,
            "equal_matches": equal_matches,
            "no_selected_matches": no_selected_matches,
            "balanced_selected_matches": balanced_selected_matches,
            "diff1_matches": diff1_matches,
            "diff2plus_matches": diff2plus_matches,
        },
    }


def _top3_more_prepare_payload(base: dict, scope_mode: str) -> dict:
    """
    scope_mode:
      - 'all'  -> denominator uses all games
      - 'qual' -> denominator uses qualifying games only
    """
    rows_base = list(base.get("rows_base") or [])
    summary = dict(base.get("summary") or {})
    scope_mode = str(scope_mode or "all").lower().strip()

    if scope_mode not in {"all", "qual"}:
        scope_mode = "all"

    scope_label = "all games"

    rows = []
    for r in rows_base:
        if scope_mode == "qual":
            games = int(r["qual_games"])
            wins = int(r["qual_wins"])
            scope_label = "qualifying imbalance games only"
        else:
            games = int(r["all_games"])
            wins = int(r["all_wins"])
            scope_label = "all games"

        more_games = int(r["more_games"])
        more_wins = int(r["more_wins"])
        vs_more_games = int(r["vs_more_games"])
        vs_more_wins = int(r["vs_more_wins"])

        overall_wr = (wins / games * 100.0) if games > 0 else 0.0
        more_wr = (more_wins / more_games * 100.0) if more_games > 0 else None
        vs_more_wr = (vs_more_wins / vs_more_games * 100.0) if vs_more_games > 0 else None

        more_pct = (more_games / games * 100.0) if games > 0 else 0.0
        vs_more_pct = (vs_more_games / games * 100.0) if games > 0 else 0.0
        wr_lift = (more_wr - overall_wr) if more_wr is not None else None

        rows.append({
            "player_uid": r["player_uid"],
            "player": r["player"],
            "is_top3": r["is_top3"],
            "games": games,
            "wins": wins,
            "overall_wr": overall_wr,
            "more_games": more_games,
            "more_wins": more_wins,
            "more_pct": more_pct,
            "more_wr": more_wr,
            "vs_more_games": vs_more_games,
            "vs_more_wins": vs_more_wins,
            "vs_more_pct": vs_more_pct,
            "vs_more_wr": vs_more_wr,
            "wr_lift": wr_lift,
            "more_by1": int(r["more_by1"]),
            "more_by2plus": int(r["more_by2plus"]),
        })

    rows.sort(
        key=lambda r: (
            1 if r["is_top3"] else 0,
            -float(r["more_pct"]),
            -int(r["more_games"]),
            r["player"].lower(),
        )
    )

    non_top3 = [r for r in rows if not r["is_top3"]]

    biggest_exposure = sorted(
        non_top3,
        key=lambda r: (float(r["more_pct"]), int(r["more_games"]), r["player"].lower()),
        reverse=True,
    )[:5]

    biggest_lift = [
        r for r in non_top3
        if r["wr_lift"] is not None and int(r["more_games"]) >= int(TOP3_MORE_MIN_GAMES_FOR_LIFT)
    ]
    biggest_lift = sorted(
        biggest_lift,
        key=lambda r: (float(r["wr_lift"]), float(r["more_wr"] or 0.0), int(r["more_games"])),
        reverse=True,
    )[:5]

    most_faced = sorted(
        non_top3,
        key=lambda r: (float(r["vs_more_pct"]), int(r["vs_more_games"]), r["player"].lower()),
        reverse=True,
    )[:5]

    summary["biggest_exposure"] = biggest_exposure
    summary["biggest_lift"] = biggest_lift
    summary["most_faced"] = most_faced
    summary["scope_mode"] = scope_mode
    summary["scope_label"] = scope_label

    return {
        "rows": rows,
        "summary": summary,
    }


def _top3_more_render_image(season_id: int, top3_names: list[str], payload: dict) -> io.BytesIO:
    rows = list(payload.get("rows") or [])
    summary = dict(payload.get("summary") or {})

    scope_label = str(summary.get("scope_label", "all games"))

    W = 2500
    pad = 26
    row_h = 32
    table_rows = max(1, len(rows))
    extra_h = 330
    H = max(1100, 255 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)
    good = (140, 220, 140)
    bad = (235, 140, 140)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"More Selected Top-3 Exposure — Season {season_id}"
    subtitle_1 = "Selected top 3: " + ", ".join(str(x) for x in top3_names)
    subtitle_2 = f"Denominator: {scope_label}"

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle_1, font=body_font, fill=muted)
    draw.text((pad * 2, int(pad * 3.65)), subtitle_2, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 5.0)

    x_player = left_x
    x_top3 = left_x + 300
    x_games = left_x + 390
    x_moreg = left_x + 500
    x_morep = left_x + 640
    x_morewr = left_x + 760
    x_vsg = left_x + 890
    x_vsp = left_x + 1030
    x_vswr = left_x + 1150
    x_owr = left_x + 1280
    x_lift = left_x + 1410
    x_by1 = left_x + 1550
    x_by2p = left_x + 1670

    headers = [
        (x_player, "Player"),
        (x_top3, "Top3"),
        (x_games, "Games"),
        (x_moreg, "More Gms"),
        (x_morep, "More %"),
        (x_morewr, "More WR"),
        (x_vsg, "Vs More Gms"),
        (x_vsp, "Vs More %"),
        (x_vswr, "Vs More WR"),
        (x_owr, "Overall WR"),
        (x_lift, "WR Lift"),
        (x_by1, "More by 1"),
        (x_by2p, "More by 2+"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        top3_txt = "Yes" if r["is_top3"] else "No"
        more_wr_txt = "—" if r["more_wr"] is None else f"{r['more_wr']:.1f}%"
        vs_wr_txt = "—" if r["vs_more_wr"] is None else f"{r['vs_more_wr']:.1f}%"
        lift_txt = "—" if r["wr_lift"] is None else f"{r['wr_lift']:+.1f}%"
        lift_fill = muted if r["wr_lift"] is None else (good if float(r["wr_lift"]) >= 0 else bad)
        name_fill = accent if r["is_top3"] else text

        draw.text((x_player, y), _top3_more_clip(r["player"], 18), font=body_font, fill=name_fill)
        draw.text((x_top3, y), top3_txt, font=body_font, fill=name_fill if r["is_top3"] else text)
        draw.text((x_games, y), str(r["games"]), font=body_font, fill=text)
        draw.text((x_moreg, y), str(r["more_games"]), font=body_font, fill=text)
        draw.text((x_morep, y), f"{r['more_pct']:.1f}%", font=body_font, fill=text)
        draw.text((x_morewr, y), more_wr_txt, font=body_font, fill=text)
        draw.text((x_vsg, y), str(r["vs_more_games"]), font=body_font, fill=text)
        draw.text((x_vsp, y), f"{r['vs_more_pct']:.1f}%", font=body_font, fill=text)
        draw.text((x_vswr, y), vs_wr_txt, font=body_font, fill=text)
        draw.text((x_owr, y), f"{r['overall_wr']:.1f}%", font=body_font, fill=text)
        draw.text((x_lift, y), lift_txt, font=body_font, fill=lift_fill)
        draw.text((x_by1, y), str(r["more_by1"]), font=body_font, fill=text)
        draw.text((x_by2p, y), str(r["more_by2plus"]), font=body_font, fill=text)
        y += row_h

    y += 8
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 18

    total_matches = int(summary.get("total_matches", 0))
    qualifying_matches = int(summary.get("qualifying_matches", 0))
    equal_matches = int(summary.get("equal_matches", 0))
    no_selected_matches = int(summary.get("no_selected_matches", 0))
    balanced_selected_matches = int(summary.get("balanced_selected_matches", 0))
    diff1_matches = int(summary.get("diff1_matches", 0))
    diff2plus_matches = int(summary.get("diff2plus_matches", 0))

    line_1 = (
        f"Match summary: total {total_matches}  •  qualifying imbalance {qualifying_matches}  •  equal split {equal_matches}"
    )
    line_2 = (
        f"Qualifying split sizes: diff 1 = {diff1_matches}  •  diff 2+ = {diff2plus_matches}  •  no selected online = {no_selected_matches}  •  balanced selected = {balanced_selected_matches}"
    )

    draw.text((left_x, y), line_1, font=body_font, fill=muted)
    y += 34
    draw.text((left_x, y), line_2, font=body_font, fill=muted)
    y += 42

    exposure_rows = list(summary.get("biggest_exposure") or [])
    lift_rows = list(summary.get("biggest_lift") or [])
    faced_rows = list(summary.get("most_faced") or [])

    col1_x = left_x
    col2_x = left_x + 820
    col3_x = left_x + 1550

    draw.text((col1_x, y), "Top non-top3 by More %", font=body_font, fill=muted)
    draw.text((col2_x, y), f"Top non-top3 by WR lift (min {TOP3_MORE_MIN_GAMES_FOR_LIFT} More Gms)", font=body_font, fill=muted)
    draw.text((col3_x, y), "Top non-top3 by facing advantage teams", font=body_font, fill=muted)
    y += 34

    max_summary_rows = max(len(exposure_rows), len(lift_rows), len(faced_rows), 1)
    for i in range(max_summary_rows):
        if i < len(exposure_rows):
            r = exposure_rows[i]
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['more_games']} gms ({r['more_pct']:.1f}%)"
            draw.text((col1_x, y), txt, font=body_font, fill=text)

        if i < len(lift_rows):
            r = lift_rows[i]
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['wr_lift']:+.1f}% lift"
            draw.text((col2_x, y), txt, font=body_font, fill=(good if float(r["wr_lift"]) >= 0 else bad))

        if i < len(faced_rows):
            r = faced_rows[i]
            faced_wr_txt = "—" if r["vs_more_wr"] is None else f"{r['vs_more_wr']:.1f}%"
            txt = f"#{i+1} {_top3_more_clip(r['player'], 16)} — {r['vs_more_games']} gms ({r['vs_more_pct']:.1f}%) WR {faced_wr_txt}"
            draw.text((col3_x, y), txt, font=body_font, fill=text)

        y += row_h

    footer = (
        "'More Gms' = games where a player's team had more of the selected top 3 than the other team. "
        "Scope changes only the denominator and Overall WR."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def _send_top3_more_reports(send_func, season_id: int, top3_uids: list[int]):
    base = _top3_more_build_base(season_id, top3_uids)
    if not base.get("rows_base"):
        await send_func("No eligible human match data found for the current season.")
        return

    top3_names = [_get_player_display_name(season_id, int(uid)) for uid in top3_uids]
    safe = "_".join(re.sub(r"[^a-zA-Z0-9_\-]+", "_", n)[:20] for n in top3_names)

    payload_all = _top3_more_prepare_payload(base, "all")
    payload_qual = _top3_more_prepare_payload(base, "qual")

    buf_all = _top3_more_render_image(season_id, top3_names, payload_all)
    buf_qual = _top3_more_render_image(season_id, top3_names, payload_qual)

    await send_func(
        content=(
            f"**More selected top-3 exposure — all games denominator — Season {season_id}**\n"
            f"Selected: **{top3_names[0]}**, **{top3_names[1]}**, **{top3_names[2]}**"
        ),
        file=discord.File(fp=buf_all, filename=f"top3_more_all_{safe}_s{season_id}.png"),
    )

    await send_func(
        content=(
            f"**More selected top-3 exposure — qualifying games only — Season {season_id}**\n"
            f"Only games where one team had more of the selected top 3 than the other team are included in the denominator."
        ),
        file=discord.File(fp=buf_qual, filename=f"top3_more_qual_{safe}_s{season_id}.png"),
    )


class Top3MoreSelectView(discord.ui.View):
    def __init__(self, season_id: int, players: list[dict]):
        super().__init__(timeout=120)
        self.season_id = int(season_id)

        options = [
            discord.SelectOption(label=str(p["player"])[:100], value=str(p["player_uid"]))
            for p in (players or [])[:25]
        ]

        select = discord.ui.Select(
            placeholder="Select exactly 3 players…",
            min_values=3,
            max_values=3,
            options=options,
        )

        async def _on_select(interaction: discord.Interaction):
            picked = [int(v) for v in select.values[:3]]
            picked_names = [_get_player_display_name(self.season_id, int(uid)) for uid in picked]

            await interaction.response.edit_message(
                content="Generating reports for: " + ", ".join(picked_names),
                view=None,
            )
            await _send_top3_more_reports(interaction.followup.send, self.season_id, picked)

        select.callback = _on_select
        self.add_item(select)


try:
    bot.remove_command("top3_stack")
except Exception:
    pass


@bot.command(name="top3_stack", aliases=["elite_stack", "two_plus_top3"])
async def top3_stack(ctx, *, player_names: Optional[str] = None):
    """
    Usage:
      !top3_stack
      !top3_stack Player 1 | Player 2 | Player 3
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()
    players = _get_api_players(season_id)

    if not players:
        await ctx.send("No API-imported players found yet. Import matches first with `!submit_match ...`.")
        return

    if player_names:
        parts = [p.strip() for p in re.split(r"\s*\|\s*", str(player_names)) if p.strip()]
        if len(parts) != 3:
            await ctx.send(
                "Provide exactly 3 player names separated by `|`, or run `!top3_stack` and choose from the dropdown."
            )
            return

        picked = []
        missing = []
        for part in parts:
            uid = _resolve_player_uid(season_id, part)
            if uid is None:
                missing.append(part)
            else:
                picked.append(int(uid))

        if missing:
            await ctx.send("Could not resolve: " + ", ".join(f"`{m}`" for m in missing))
            return

        if len(set(picked)) != 3:
            await ctx.send("Please choose 3 different players.")
            return

        await _send_top3_more_reports(ctx.send, season_id, picked)
        return

    extra = (
        f"\n(Showing first 25 of {len(players)}. "
        f"Use `!top3_stack Player 1 | Player 2 | Player 3` if your players are not in the dropdown.)"
        if len(players) > 25 else ""
    )

    await ctx.send(
        f"Select exactly 3 players to treat as the top 3 for Season {season_id}:{extra}",
        view=Top3MoreSelectView(season_id, players),
    )


# ============================================================================================================
# ============================================================================================================
# HERO TIERLIST + HERO SYNERGY — IMAGE OUTPUT
#
#   - Does NOT reference mr_hero_segments.is_bot (filters via mr_player_match.is_bot)
#   - Produces PNG cards using the same look/feel as player_heros (fonts via get_fonts()).
# ============================================================================================================
# ============================================================================================================

import io
import math
from collections import defaultdict
from itertools import combinations

# Use configured eligibility thresholds when available, otherwise safe defaults.
try:
    HERO_WIN_MIN_SECONDS
except NameError:
    HERO_WIN_MIN_SECONDS = 120  # 2:00

try:
    HERO_WIN_MIN_RATIO
except NameError:
    HERO_WIN_MIN_RATIO = 0.20   # 20%

HERO_TIER_DEFAULT_MIN_PICKS = 8
HERO_TIER_DEFAULT_TOP_N = 25

HERO_SYNERGY_DEFAULT_MIN_GAMES = 6
HERO_SYNERGY_DEFAULT_TOP_N = 25

HERO_IMG_PER_PAGE = 18
HERO_IMG_MAX_PAGES = 5


def _clip(s: str, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _mode_label(mode: str) -> str:
    m = (mode or "humans").strip().lower()
    if m in ("human", "humans", "h"):
        return "Humans"
    if m in ("bot", "bots", "b"):
        return "Bots"
    return "Both"


def _bot_filter_sql(mode: str) -> tuple[str, list]:
    """
    Filter uses mr_player_match.is_bot (works even if mr_hero_segments has no is_bot column).
    """
    m = (mode or "humans").strip().lower()
    if m in ("human", "humans", "h"):
        return "pm.is_bot = 0", []
    if m in ("bot", "bots", "b"):
        return "pm.is_bot = 1", []
    return "pm.is_bot IN (0,1)", []


def _hero_tierlist_rows_api(
    season_id: int,
    mode: str = "humans",
    min_sec: int = HERO_WIN_MIN_SECONDS,
    min_ratio: float = HERO_WIN_MIN_RATIO,
) -> list[dict]:
    """
    Per-hero stats across season, using ELIGIBLE hero appearances only for wins/picks:
      eligible if hero_seconds >= min_sec AND hero_seconds / player_total_match_seconds >= min_ratio

    Pick% denominator is total eligible picks across all heroes (within mode).
    """
    global c
    ensure_mr_api_tables()

    bot_where, bot_params = _bot_filter_sql(mode)

    sql = f"""
    WITH hs AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            hero_id,
            COALESCE(seconds,0) AS seconds,
            COALESCE(kills,0)   AS kills,
            COALESCE(deaths,0)  AS deaths,
            COALESCE(assists,0) AS assists
        FROM mr_hero_segments
        WHERE season_id = ?
    ),
    match_tot AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    joined AS (
        SELECT
            hs.hero_id,
            hs.match_uid,
            hs.game_label,
            hs.player_uid,
            hs.seconds,
            hs.kills, hs.deaths, hs.assists,
            mt.total_sec,
            COALESCE(pm.is_win, 0) AS is_win
        FROM hs
        JOIN match_tot mt
          ON mt.season_id  = hs.season_id
         AND mt.match_uid  = hs.match_uid
         AND mt.game_label = hs.game_label
         AND mt.player_uid = hs.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE {bot_where}
    ),
    elig AS (
        SELECT *
        FROM joined
        WHERE seconds >= ?
          AND total_sec > 0
          AND (1.0 * seconds / total_sec) >= ?
    )
    SELECT
        hero_id,
        COUNT(*) AS picks,
        SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) AS wins,
        SUM(seconds) AS seconds_total,
        SUM(kills)   AS k,
        SUM(deaths)  AS d,
        SUM(assists) AS a
    FROM elig
    GROUP BY hero_id
    HAVING picks > 0
    """

    params = [int(season_id)] + bot_params + [int(min_sec), float(min_ratio)]
    c.execute(sql, params)

    out = []
    for hero_id, picks, wins, sec, k, d, a in (c.fetchall() or []):
        picks = int(picks or 0)
        wins = int(wins or 0)
        sec = int(float(sec or 0))
        k = int(k or 0)
        d = int(d or 0)
        a = int(a or 0)

        win_pct = (wins / picks) * 100.0 if picks else 0.0
        out.append({
            "hero_id": int(hero_id),
            "picks": picks,
            "wins": wins,
            "win_pct": win_pct,
            "seconds": sec,
            "avg_k": (k / picks) if picks else 0.0,
            "avg_d": (d / picks) if picks else 0.0,
            "avg_a": (a / picks) if picks else 0.0,
        })

    return out


def _dominant_hero_rows_for_synergy_api(
    season_id: int,
    mode: str = "humans",
    min_sec: int = HERO_WIN_MIN_SECONDS,
    min_ratio: float = HERO_WIN_MIN_RATIO,
) -> list[tuple[str, int, int, int]]:
    """
    One dominant hero per player per match (largest seconds), filtered by eligibility,
    plus camp and is_win.

    Output rows: (match_uid, camp, hero_id, is_win)
    NOTE: avoids ROW_NUMBER() for maximum SQLite compatibility.
    """
    global c
    ensure_mr_api_tables()

    bot_where, bot_params = _bot_filter_sql(mode)

    sql = f"""
    WITH hs AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            hero_id,
            COALESCE(seconds,0) AS seconds
        FROM mr_hero_segments
        WHERE season_id = ?
    ),
    match_tot AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    maxs AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            MAX(seconds) AS max_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    dom_pick AS (
        -- if ties on seconds, pick the lowest hero_id deterministically
        SELECT
            hs.season_id,
            hs.match_uid,
            hs.game_label,
            hs.player_uid,
            MIN(hs.hero_id) AS hero_id,
            MAX(hs.seconds) AS seconds
        FROM hs
        JOIN maxs
          ON maxs.season_id  = hs.season_id
         AND maxs.match_uid  = hs.match_uid
         AND maxs.game_label = hs.game_label
         AND maxs.player_uid = hs.player_uid
         AND hs.seconds      = maxs.max_sec
        GROUP BY hs.season_id, hs.match_uid, hs.game_label, hs.player_uid
    ),
    joined AS (
        SELECT
            dp.match_uid,
            dp.game_label,
            dp.player_uid,
            dp.hero_id,
            dp.seconds,
            mt.total_sec,
            COALESCE(pm.camp, -1) AS camp,
            COALESCE(pm.is_win, 0) AS is_win
        FROM dom_pick dp
        JOIN match_tot mt
          ON mt.season_id  = dp.season_id
         AND mt.match_uid  = dp.match_uid
         AND mt.game_label = dp.game_label
         AND mt.player_uid = dp.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = dp.season_id
         AND pm.match_uid  = dp.match_uid
         AND pm.game_label = dp.game_label
         AND pm.player_uid = dp.player_uid
        WHERE {bot_where}
    )
    SELECT match_uid, camp, hero_id, is_win
    FROM joined
    WHERE seconds >= ?
      AND total_sec > 0
      AND (1.0 * seconds / total_sec) >= ?
      AND camp IN (0, 1)
    """

    params = [int(season_id)] + bot_params + [int(min_sec), float(min_ratio)]
    c.execute(sql, params)

    return [(str(mu), int(camp), int(hid), int(w or 0)) for (mu, camp, hid, w) in (c.fetchall() or [])]


# ------------------------------------------------------------------------------------------------------------
# IMAGE RENDERERS (styled like player_heros)
# ------------------------------------------------------------------------------------------------------------

def _render_hero_tierlist_card(
    season_id: int,
    mode_label: str,
    rows: list[dict],
    min_picks: int,
    page: int,
    pages: int,
    total_picks: int,
) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Hero Tier List — Season {season_id} ({mode_label})"
    if pages > 1:
        title += f"  •  Page {page}/{pages}"
    draw.text((pad * 2, int(pad * 1.4)), title, font=title_font, fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    # Column positions
    x_hero = left_x
    x_win = left_x + 560
    x_picks = left_x + 700
    x_pickp = left_x + 835
    x_kda = left_x + 980
    x_time = left_x + 1280

    # Headers
    draw.text((x_hero, y), "Hero", font=body_font, fill=muted)
    draw.text((x_win, y), "Win%", font=body_font, fill=muted)
    draw.text((x_picks, y), "Picks", font=body_font, fill=muted)
    draw.text((x_pickp, y), "Pick%", font=body_font, fill=muted)
    draw.text((x_kda, y), "Avg K/D/A", font=body_font, fill=muted)
    draw.text((x_time, y), "Time", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows[:HERO_IMG_PER_PAGE]:
        hero_nm = _clip(r.get("hero_name", r.get("hero_id", "")), 28)
        win_txt = f"{float(r.get('win_pct', 0.0)):.1f}%"
        picks = int(r.get("picks", 0))
        pick_pct = (picks / max(1, int(total_picks))) * 100.0
        pick_txt = f"{pick_pct:.1f}%"
        kda_txt = f"{float(r.get('avg_k', 0.0)):.1f}/{float(r.get('avg_d', 0.0)):.1f}/{float(r.get('avg_a', 0.0)):.1f}"
        time_txt = _fmt_time(int(r.get("seconds", 0)))

        draw.text((x_hero, y), hero_nm, font=body_font, fill=text)
        draw.text((x_win, y), win_txt, font=body_font, fill=text)
        draw.text((x_picks, y), str(picks), font=body_font, fill=text)
        draw.text((x_pickp, y), pick_txt, font=body_font, fill=text)
        draw.text((x_kda, y), kda_txt, font=body_font, fill=text)
        draw.text((x_time, y), time_txt, font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    footer = (
        f"Eligibility: hero ≥ {HERO_WIN_MIN_SECONDS}s AND ≥ {int(HERO_WIN_MIN_RATIO * 100)}% of player match time.  "
        f"Min picks to rank: {max(1, int(min_picks))}."
    )
    draw.text((left_x, y_footer), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _render_hero_synergy_card(
    season_id: int,
    mode_label: str,
    rows: list[dict],
    min_games: int,
    page: int,
    pages: int,
) -> io.BytesIO:
    W, H = 1500, 980
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Hero Synergy (Same Team) — Season {season_id} ({mode_label})"
    if pages > 1:
        title += f"  •  Page {page}/{pages}"
    draw.text((pad * 2, int(pad * 1.4)), title, font=title_font, fill=accent)

    left_x = pad * 2
    y = int(pad * 3.4)

    # Column positions
    x_pair = left_x
    x_win = left_x + 980
    x_games = left_x + 1120
    x_wins = left_x + 1280

    draw.text((x_pair, y), "Pair", font=body_font, fill=muted)
    draw.text((x_win, y), "Win%", font=body_font, fill=muted)
    draw.text((x_games, y), "Games", font=body_font, fill=muted)
    draw.text((x_wins, y), "Wins", font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows[:HERO_IMG_PER_PAGE]:
        pair_nm = _clip(r.get("pair_name", ""), 54)
        win_txt = f"{float(r.get('win_pct', 0.0)):.1f}%"
        games = int(r.get("games", 0))
        wins = int(r.get("wins", 0))

        draw.text((x_pair, y), pair_nm, font=body_font, fill=text)
        draw.text((x_win, y), win_txt, font=body_font, fill=text)
        draw.text((x_games, y), str(games), font=body_font, fill=text)
        draw.text((x_wins, y), str(wins), font=body_font, fill=text)
        y += 32

    y_footer = H - pad - 58
    footer = (
        f"Dominant eligible hero per player per match; pairs counted when on same team.  "
        f"Eligibility: hero ≥ {HERO_WIN_MIN_SECONDS}s AND ≥ {int(HERO_WIN_MIN_RATIO * 100)}%.  "
        f"Min games to rank: {max(1, int(min_games))}."
    )
    draw.text((left_x, y_footer), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ------------------------------------------------------------------------------------------------------------
# BUILDERS
# ------------------------------------------------------------------------------------------------------------

async def _build_hero_tierlist_images(
    season_id: int,
    mode: str,
    min_picks: int,
    top_n: int,
) -> list[io.BytesIO]:
    rows = _hero_tierlist_rows_api(season_id, mode=mode)
    if not rows:
        return []

    total_picks = sum(int(r.get("picks", 0)) for r in rows) or 1

    rows = [r for r in rows if int(r.get("picks", 0)) >= max(1, int(min_picks))]
    rows.sort(key=lambda r: (float(r.get("win_pct", 0.0)), int(r.get("picks", 0))), reverse=True)
    rows = rows[: max(1, int(top_n))]

    if not rows:
        return []

    # Resolve hero names
    hero_ids = sorted({str(r["hero_id"]) for r in rows})
    names = await asyncio.gather(*[get_hero_name(hid) for hid in hero_ids], return_exceptions=True)
    hero_map: dict[int, str] = {}
    for hid, nm in zip(hero_ids, names):
        hero_map[int(hid)] = nm if isinstance(nm, str) else str(hid)

    for r in rows:
        r["hero_name"] = hero_map.get(int(r["hero_id"]), str(r["hero_id"]))

    pages = max(1, math.ceil(len(rows) / HERO_IMG_PER_PAGE))
    pages = min(pages, HERO_IMG_MAX_PAGES)

    out = []
    mode_lbl = _mode_label(mode)
    for p in range(1, pages + 1):
        sl = rows[(p - 1) * HERO_IMG_PER_PAGE : p * HERO_IMG_PER_PAGE]
        out.append(_render_hero_tierlist_card(
            season_id=season_id,
            mode_label=mode_lbl,
            rows=sl,
            min_picks=min_picks,
            page=p,
            pages=pages,
            total_picks=total_picks,
        ))
    return out


async def _build_hero_synergy_images(
    season_id: int,
    mode: str,
    min_games: int,
    top_n: int,
) -> list[io.BytesIO]:
    dom_rows = _dominant_hero_rows_for_synergy_api(season_id, mode=mode)
    if not dom_rows:
        return []

    # Group heroes by (match_uid, camp) and determine team win by majority vote
    team_heroes = defaultdict(list)     # (match_uid, camp) -> [hero_id...]
    team_votes = defaultdict(list)      # (match_uid, camp) -> [is_win...]
    for match_uid, camp, hero_id, is_win in dom_rows:
        key = (match_uid, camp)
        team_heroes[key].append(int(hero_id))
        team_votes[key].append(int(is_win or 0))

    pair_games = defaultdict(int)
    pair_wins = defaultdict(int)

    for key, heroes in team_heroes.items():
        if len(heroes) < 2:
            continue
        votes = team_votes.get(key, [])
        team_won = 1 if (sum(votes) >= (len(votes) / 2.0)) else 0

        for a, b in combinations(heroes, 2):
            pair = (a, b) if a <= b else (b, a)
            pair_games[pair] += 1
            if team_won == 1:
                pair_wins[pair] += 1

    rows = []
    for (a, b), g in pair_games.items():
        if g < max(1, int(min_games)):
            continue
        w = int(pair_wins.get((a, b), 0))
        rows.append({
            "a": a,
            "b": b,
            "games": int(g),
            "wins": w,
            "win_pct": (w / g) * 100.0 if g else 0.0,
        })

    if not rows:
        return []

    rows.sort(key=lambda r: (float(r["win_pct"]), int(r["games"])), reverse=True)
    rows = rows[: max(1, int(top_n))]

    # Resolve hero names for pairs
    uniq_ids = sorted({str(r["a"]) for r in rows} | {str(r["b"]) for r in rows})
    names = await asyncio.gather(*[get_hero_name(hid) for hid in uniq_ids], return_exceptions=True)
    hero_map: dict[int, str] = {}
    for hid, nm in zip(uniq_ids, names):
        hero_map[int(hid)] = nm if isinstance(nm, str) else str(hid)

    for r in rows:
        a_nm = hero_map.get(int(r["a"]), str(r["a"]))
        b_nm = hero_map.get(int(r["b"]), str(r["b"]))
        r["pair_name"] = f"{a_nm} + {b_nm}"

    pages = max(1, math.ceil(len(rows) / HERO_IMG_PER_PAGE))
    pages = min(pages, HERO_IMG_MAX_PAGES)

    out = []
    mode_lbl = _mode_label(mode)
    for p in range(1, pages + 1):
        sl = rows[(p - 1) * HERO_IMG_PER_PAGE : p * HERO_IMG_PER_PAGE]
        out.append(_render_hero_synergy_card(
            season_id=season_id,
            mode_label=mode_lbl,
            rows=sl,
            min_games=min_games,
            page=p,
            pages=pages,
        ))
    return out


# ------------------------------------------------------------------------------------------------------------
# COMMANDS (remove older definitions safely, then register)
# ------------------------------------------------------------------------------------------------------------

try:
    bot.remove_command("hero_tierlist")
except Exception:
    pass

try:
    bot.remove_command("hero_synergy")
except Exception:
    pass


@bot.command(name="hero_tierlist")
async def hero_tierlist(ctx, mode: str = "humans",
                        min_picks: int = HERO_TIER_DEFAULT_MIN_PICKS,
                        top_n: int = HERO_TIER_DEFAULT_TOP_N):
    """
    Usage:
      !hero_tierlist
      !hero_tierlist humans
      !hero_tierlist bots
      !hero_tierlist both
      !hero_tierlist humans 10 30
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    try:
        min_picks = int(min_picks)
    except Exception:
        min_picks = HERO_TIER_DEFAULT_MIN_PICKS

    try:
        top_n = int(top_n)
    except Exception:
        top_n = HERO_TIER_DEFAULT_TOP_N

    mode_n = (mode or "humans").strip().lower()
    images = await _build_hero_tierlist_images(season_id, mode_n, min_picks, top_n)

    if not images:
        await ctx.send(
            f"No eligible hero data found for Season {season_id} ({_mode_label(mode_n)}). "
            f"Import matches first with `!submit_match` or reduce min_picks."
        )
        return

    for i, buf in enumerate(images, start=1):
        suffix = f"_p{i}" if len(images) > 1 else ""
        await ctx.send(file=discord.File(fp=buf, filename=f"hero_tierlist_s{season_id}_{mode_n}{suffix}.png"))


@bot.command(name="hero_synergy")
async def hero_synergy(ctx, mode: str = "humans",
                       min_games: int = HERO_SYNERGY_DEFAULT_MIN_GAMES,
                       top_n: int = HERO_SYNERGY_DEFAULT_TOP_N):
    """
    Usage:
      !hero_synergy
      !hero_synergy humans
      !hero_synergy bots
      !hero_synergy both
      !hero_synergy humans 8 30
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    try:
        min_games = int(min_games)
    except Exception:
        min_games = HERO_SYNERGY_DEFAULT_MIN_GAMES

    try:
        top_n = int(top_n)
    except Exception:
        top_n = HERO_SYNERGY_DEFAULT_TOP_N

    mode_n = (mode or "humans").strip().lower()
    images = await _build_hero_synergy_images(season_id, mode_n, min_games, top_n)

    if not images:
        await ctx.send(
            f"No eligible hero synergy pairs found for Season {season_id} ({_mode_label(mode_n)}). "
            f"Import matches first with `!submit_match` or reduce min_games."
        )
        return

    for i, buf in enumerate(images, start=1):
        suffix = f"_p{i}" if len(images) > 1 else ""
        await ctx.send(file=discord.File(fp=buf, filename=f"hero_synergy_s{season_id}_{mode_n}{suffix}.png"))

# ============================================================
# COMMAND: edit_game (official API or RivalsMeta)
# ============================================================


@bot.command(name="edit_game")
async def edit_game(ctx, game_label: str, new_match_or_url: str = None):
    """
    Match-source edit:
      - If new_match_or_url is provided: replaces the game label with that match
      - If omitted: re-imports the original match tied to that label (same match_uid)

    Usage:
      !edit_game Game_141 5168178_...
      !edit_game Game_141 https://rivalsmeta.com/matches/<id>...
      !edit_game Game_141
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # Find existing match_uid for this label
    c.execute(
        "SELECT match_uid FROM match_imports WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    row = c.fetchone()
    if not row:
        await ctx.send(
            f"❌ Game `{game_label}` not found in Season {season_id}.")
        return
    old_match_uid = row[0]

    # Determine target match
    target = new_match_or_url.strip() if new_match_or_url else old_match_uid
    match_uid = extract_match_id(target)
    if not match_uid:
        await ctx.send(
            "❌ Could not parse match id. Provide a match id or a rivalsmeta match URL."
        )
        return

    await ctx.send(f"Re-importing `{game_label}` using match `{match_uid}` …")

    try:
        payload, import_source = await fetch_submit_match_payload(
            target, match_uid)
    except Exception as e:
        await ctx.send(f"Failed to fetch match: {e}")
        return

    # IMPORTANT: this will wipe the label across all tables then rebuild it
    try:
        upsert_match_into_mr_tables(season_id=season_id,
                                    game_label=game_label,
                                    payload=payload)
    except Exception as e:
        await ctx.send(f"DB write failed while storing match payload: {e}")
        return

    # Now rebuild HUMAN-ONLY season stats for this label from payload (same logic as submit_match, condensed)
    md = (payload or {}).get("match_details") or {}
    players = md.get("match_players") or []
    if not isinstance(players, list):
        players = []

    mvp_uid = md.get("mvp_uid")
    svp_uid = md.get("svp_uid")

    human_rows = []
    for p in players:
        if not isinstance(p, dict) or _is_bot_player(p):
            continue
        nick = (p.get("nick_name") or p.get("nickname") or p.get("player_name")
                or "").strip()
        if not nick:
            continue
        nick = canonical_player_name(nick)
        uid = p.get("player_uid")
        result = _parse_is_win_flag(p.get("is_win"))
        is_win = (result == 1)
        is_loss = (result == 0)

        human_rows.append((
            {
                "season_id": season_id,
                "game_label": game_label,
                "player": nick,
                "kills": int(p.get("kills") or 0),
                "deaths": int(p.get("deaths") or 0),
                "assists": int(p.get("assists") or 0),
                "damage": int(float(p.get("total_hero_damage") or 0)),
                "damage_taken": int(float(p.get("total_damage_taken") or 0)),
                "healing": int(float(p.get("total_hero_heal") or 0)),
                # Draws/unknowns: win=0 and loss=0
                "win": 1 if is_win else 0,
                "loss": 1 if is_loss else 0,
                "mvp": 1 if (mvp_uid is not None and uid == mvp_uid) else 0,
                "svp": 1 if (svp_uid is not None and uid == svp_uid) else 0,
            },
            p))

    if not human_rows:
        await ctx.send(
            "No human players found in this match payload (only bots).")
        return

    # MVP/SVP fallback if API chose a bot or missing
    if sum(r["mvp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["mvp"] = 0
        # pick best winner
        best = 0
        best_score = None
        for i, (r, _) in enumerate(human_rows):
            if r["win"] != 1:
                continue
            score = (r["kills"] * 3) + r["assists"] + (r["damage"] / 1000.0)
            if best_score is None or score > best_score:
                best_score = score
                best = i
        human_rows[best][0]["mvp"] = 1

    if sum(r["svp"] for (r, _) in human_rows) != 1:
        for (r, _) in human_rows:
            r["svp"] = 0
        # pick best loser
        best = 0
        best_score = None
        for i, (r, _) in enumerate(human_rows):
            if r["win"] != 0:
                continue
            score = (r["kills"] * 3) + r["assists"] + (r["damage"] / 1000.0)
            if best_score is None or score > best_score:
                best_score = score
                best = i
        human_rows[best][0]["svp"] = 1

    try:
        for (r, _raw) in human_rows:
            c.execute(
                """
                INSERT INTO game_stats (
                    season_id, game_label, player,
                    kills, deaths, assists,
                    damage, damage_taken, healing,
                    win, loss, mvp, svp
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(season_id, game_label, player) DO UPDATE SET
                    kills=excluded.kills,
                    deaths=excluded.deaths,
                    assists=excluded.assists,
                    damage=excluded.damage,
                    damage_taken=excluded.damage_taken,
                    healing=excluded.healing,
                    win=excluded.win,
                    loss=excluded.loss,
                    mvp=excluded.mvp,
                    svp=excluded.svp,
                    timestamp=CURRENT_TIMESTAMP
            """, (r["season_id"], r["game_label"], r["player"], r["kills"],
                  r["deaths"], r["assists"], r["damage"], r["damage_taken"],
                  r["healing"], r["win"], r["loss"], r["mvp"], r["svp"]))
        conn.commit()

        for (r, _raw) in human_rows:
            update_streak(r["player"],
                          won=(r["win"] == 1),
                          season_id=season_id)

        refresh_season_views()

    except Exception as e:
        conn.rollback()
        await ctx.send(f"DB update failed while writing Season stats: {e}")
        return

    await ctx.send(
        f"✅ Updated `{game_label}` (Season {season_id}) to match `{match_uid}` via {import_source}."
    )


# ============================================================
# COMMAND: undo_last_game (API-first) — with DELETED tombstone
# ============================================================

@bot.command(name="undo_last_game")
async def undo_last_game(ctx):
    """
    Deletes the most recently IMPORTED game in the CURRENT season across ALL tables.
    ALSO records its match_uid(s) as reason=DELETED so auto-import will not re-import it later.
    """
    ensure_mr_api_tables()
    ensure_auto_import_tables()
    season_id = get_current_season_id()

    # Prefer MR meta as the single-source "last imported" signal
    c.execute(
        """
        SELECT game_label, match_uid, match_time_utc
        FROM mr_match_meta
        WHERE season_id = ?
        ORDER BY datetime(imported_at) DESC
        LIMIT 1
        """,
        (season_id,),
    )
    row = c.fetchone()

    game_label = None
    last_mu = None
    last_iso = None

    if row:
        game_label, last_mu, last_iso = row
    else:
        # Fallback: current-season view (already season-filtered)
        c.execute(
            """
            SELECT game_label
            FROM game_stats_v
            ORDER BY datetime(timestamp) DESC
            LIMIT 1
            """
        )
        row2 = c.fetchone()
        if not row2:
            await ctx.send("❌ No games to undo.")
            return
        game_label = row2[0]

    # Tombstone any match_uid(s) tied to this game_label before deleting rows everywhere
    try:
        c.execute(
            """
            SELECT mi.match_uid, mm.match_time_utc
            FROM match_imports mi
            LEFT JOIN mr_match_meta mm
              ON mm.season_id = mi.season_id AND mm.match_uid = mi.match_uid
            WHERE mi.season_id=? AND mi.game_label=?
            """,
            (season_id, game_label),
        )
        rows = c.fetchall() or []

        # If imports table has no rows (manual-only game), still tombstone MR meta UID if we have it
        if not rows and last_mu:
            rows = [(last_mu, last_iso)]

        seen = set()
        for mu, iso in rows:
            mu_s = str(mu or "").strip()
            if not mu_s or mu_s in seen:
                continue
            seen.add(mu_s)

            dt = _parse_iso_utc(iso) if iso else None

            _record_skipped_match(
                mu_s,
                match_dt_utc=dt,
                season_id=season_id,
                reason="DELETED",
                source="undo_last_game",
                details={
                    "game_label": str(game_label),
                    "deleted_by": str(ctx.author),
                    "channel_id": getattr(ctx.channel, "id", None),
                    "guild_id": getattr(ctx.guild, "id", None),
                },
            )
    except Exception:
        # Do not block the undo if tombstoning fails
        pass

    delete_game_everywhere(season_id, game_label)
    await ctx.send(
        f"↩️ Undid last imported game: `{game_label}` (Season {season_id}). "
        f"(Match UID(s) tombstoned as DELETED for auto-import.)"
    )


# ============================================================
# COMMAND: delete_game (API-first)
# ============================================================
@bot.command(name="delete_game")
async def delete_game(ctx, game_label: str):
    """
    Permanently delete a game label in the CURRENT season, including MR API side tables.
    Also tombstones its match_uid(s) so auto-import will not re-import it later.
    """
    ensure_mr_api_tables()
    ensure_auto_import_tables()
    season_id = get_current_season_id()

    # Check existence via MR import marker OR season stats
    c.execute(
        "SELECT COUNT(*) FROM match_imports WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    in_imports = (c.fetchone() or [0])[0]

    c.execute(
        "SELECT COUNT(*) FROM game_stats WHERE season_id=? AND game_label=?",
        (season_id, game_label))
    in_stats = (c.fetchone() or [0])[0]

    # Tombstone any match_uid(s) currently associated with this label (pre-delete)
    try:
        c.execute(
            """
            SELECT mi.match_uid, mm.match_time_utc
            FROM match_imports mi
            LEFT JOIN mr_match_meta mm
              ON mm.season_id = mi.season_id AND mm.match_uid = mi.match_uid
            WHERE mi.season_id=? AND mi.game_label=?
            """,
            (season_id, game_label),
        )
        rows = c.fetchall() or []
        for mu, iso in rows:
            dt = _parse_iso_utc(iso) if iso else None
            _record_skipped_match(
                str(mu),
                match_dt_utc=dt,
                season_id=season_id,
                reason="DELETED",
                source="delete_game",
                details={
                    "game_label": str(game_label),
                    "deleted_by": str(ctx.author),
                    "channel_id": getattr(ctx.channel, "id", None),
                    "guild_id": getattr(ctx.guild, "id", None),
                },
            )
    except Exception:
        # Do not block deletion if tombstone recording fails
        pass

    if in_imports == 0 and in_stats == 0:
        # Still attempt cleanup (harmless)
        delete_game_everywhere(season_id, game_label)
        await ctx.send(
            f"❌ Game `{game_label}` not found in Season {season_id}. (Any leftovers cleared.)"
        )
        return

    delete_game_everywhere(season_id, game_label)
    await ctx.send(
        f"🗑️ Game `{game_label}` has been permanently deleted (Season {season_id})."
    )




# ============================================================
# COMMAND: undelete_match — remove DELETED tombstone
# ============================================================

@bot.command(name="undelete_match")
async def undelete_match(ctx, match_uid: str = None):
    """
    Removes a DELETED tombstone for a match_uid so auto-import can import it again
    if it still appears in match history.
    Usage: !undelete_match <match_uid>
    """
    ensure_auto_import_tables()

    mu = str(match_uid or "").strip()
    if not mu:
        await ctx.send("Usage: `!undelete_match <match_uid>`")
        return

    c.execute(
        "SELECT 1 FROM mr_skipped_matches WHERE match_uid=? AND reason='DELETED' LIMIT 1",
        (mu,),
    )
    if not c.fetchone():
        await ctx.send(
            f"❌ No DELETED tombstone found for match_uid `{mu}`."
        )
        return

    c.execute(
        "DELETE FROM mr_skipped_matches WHERE match_uid=? AND reason='DELETED'",
        (mu,),
    )
    conn.commit()

    await ctx.send(
        f"✅ Removed DELETED tombstone for match_uid `{mu}`. "
        f"Auto-import may import it again if it is still discoverable."
    )


# ============================================================
# COMMAND: mr_cleanup_orphans (optional maintenance)
# ============================================================


@bot.command(name="mr_cleanup_orphans")
async def mr_cleanup_orphans(ctx):
    """
    Cleans rows from convenience tables where the game_label no longer exists in mr_match_meta.
    With API-only imports + delete_game_everywhere, you should rarely need this.
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    c.execute(
        """
        DELETE FROM hero_time_stats
        WHERE season_id=?
          AND game_label NOT IN (SELECT game_label FROM mr_match_meta WHERE season_id=?)
    """, (season_id, season_id))

    c.execute(
        """
        DELETE FROM hero_time_stats_all
        WHERE season_id=?
          AND game_label NOT IN (SELECT game_label FROM mr_match_meta WHERE season_id=?)
    """, (season_id, season_id))

    c.execute(
        """
        DELETE FROM hero_bans
        WHERE season_id=?
          AND game_label NOT IN (SELECT game_label FROM mr_match_meta WHERE season_id=?)
    """, (season_id, season_id))

    c.execute(
        """
        DELETE FROM match_imports
        WHERE season_id=?
          AND game_label NOT IN (SELECT game_label FROM mr_match_meta WHERE season_id=?)
    """, (season_id, season_id))

    conn.commit()
    await ctx.send(f"🧹 Cleaned orphan MR API rows for Season {season_id}.")


# ============================================================================================================
# ============================================================================================================
# Session Overview (API-native, 2 images)
# Dependencies:
#  - ensure_mr_api_tables()
#  - get_current_season_id()
#  - get_fonts()
#  - _fmt_time(seconds:int)->str
#  - get_hero_name(hero_id:str)->awaitable[str]
# Uses imported API-format match data.
# ============================================================================================================
# ============================================================================================================

BRISBANE_UTC_OFFSET_HOURS = 10  # SQLite CURRENT_TIMESTAMP is UTC; Brisbane is UTC+10


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).lower()


def _get_games_grouped_by_date_api(season_id: int):
    """
    Groups by Brisbane-local date using match_imports.imported_at (UTC) shifted +10h.
    Returns: ordered_dates, by_date dict[date_str] -> [game_label,...] (chronological)
    """
    ensure_mr_api_tables()

    return load_games_grouped_by_local_date(
        c, season_id, BRISBANE_UTC_OFFSET_HOURS
    )


def _session_labels_for_date_api(season_id: int, date_str: str | None):
    ordered_dates, by_date = _get_games_grouped_by_date_api(season_id)
    if not ordered_dates:
        return None, []
    target = date_str if (date_str
                          and date_str in by_date) else ordered_dates[-1]
    return target, by_date.get(target, [])


def _all_ordered_game_labels_api(season_id: int) -> list[str]:
    ensure_mr_api_tables()
    return load_all_ordered_game_labels(c, season_id, BRISBANE_UTC_OFFSET_HOURS)


def _aggregate_wl_for_labels_api(season_id: int,
                                 labels: list[str]) -> pandas.DataFrame:
    """
    Season standings-style aggregate (humans only).
    Returns DF with: player_uid, player, wins, losses, wl_str, winrate
    """
    return _read_session_wl(c, season_id, labels)


def _add_rank_deltas(after_df: pandas.DataFrame,
                     before_df: pandas.DataFrame | None) -> pandas.DataFrame:
    """
    Adds columns: rank, delta (↑n/↓n/= / NEW)
    """
    if after_df is None or after_df.empty:
        return after_df

    out = after_df.copy()
    out["rank"] = range(1, len(out) + 1)

    prev_rank = {}
    if before_df is not None and (not before_df.empty) and (
            "player_uid" in before_df.columns):
        tmp = before_df.copy().reset_index(drop=True)
        tmp["rank"] = range(1, len(tmp) + 1)
        prev_rank = {
            int(r["player_uid"]): int(r["rank"])
            for _, r in tmp.iterrows()
        }

    deltas = []
    for _, r in out.iterrows():
        uid = int(r["player_uid"])
        if uid not in prev_rank:
            deltas.append("NEW")
            continue
        diff = prev_rank[uid] - int(r["rank"])
        if diff == 0:
            deltas.append("=")
        elif diff > 0:
            deltas.append(f"↑{diff}")
        else:
            deltas.append(f"↓{abs(diff)}")

    out["delta"] = deltas
    return out


def _season_player_baselines_api(season_id: int) -> dict[int, dict]:
    """
    Baselines across the ENTIRE season (humans only), keyed by player_uid.
    Produces:
      - season_games, season_wins, season_losses, season_winrate
      - season_top_hero_id (by total seconds)
    """
    ensure_mr_api_tables()

    # W/L + totals
    c.execute(
        """
        SELECT
            player_uid,
            MAX(player) as player,
            COUNT(*) as games,
            SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END) as losses
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
        GROUP BY player_uid
    """, (season_id, ))
    rows = c.fetchall()

    out: dict[int, dict] = {}
    for uid, player, games, wins, losses in rows:
        uid = int(uid)
        games = int(games or 0)
        wins = int(wins or 0)
        losses = int(losses or 0)
        winrate = round((wins / games) * 100.0, 1) if games > 0 else 0.0
        out[uid] = {
            "player": str(player),
            "season_games": games,
            "season_wins": wins,
            "season_losses": losses,
            "season_winrate": winrate,
            "season_top_hero_id": None
        }

    # Top hero by season time (seconds)
    c.execute(
        """
        SELECT player_uid, hero_id, SUM(seconds) as sec
        FROM mr_hero_segments
        WHERE season_id=?
          AND is_bot=0
        GROUP BY player_uid, hero_id
        ORDER BY player_uid ASC, sec DESC
    """, (season_id, ))
    hero_rows = c.fetchall()

    seen_uid = set()
    for uid, hid, sec in hero_rows:
        uid = int(uid)
        if uid in seen_uid:
            continue
        seen_uid.add(uid)
        if uid not in out:
            out[uid] = {
                "player": str(uid),
                "season_games": 0,
                "season_wins": 0,
                "season_losses": 0,
                "season_winrate": 0.0,
                "season_top_hero_id": int(hid)
            }
        else:
            out[uid]["season_top_hero_id"] = int(hid)

    return out


def _aggregate_session_records_api(
        season_id: int, session_labels: list[str]) -> pandas.DataFrame:
    """
    Session table (humans only) with richer columns:
    Player | W/L | Win% | AvgKDA | AvgDmg | AvgHeal | AvgTaken | TopHeroSess | MVP | SVP | Badges
    Season comparison is applied after baselines are computed.
    """
    if not session_labels:
        return pandas.DataFrame()

    qmarks = ",".join("?" for _ in session_labels)

    # core per-player sums
    c.execute(
        f"""
        SELECT
            pm.player_uid,
            MAX(pm.player) as player,
            SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN pm.is_win=0 THEN 1 ELSE 0 END) AS losses,
            SUM(pm.kills) as k,
            SUM(pm.deaths) as d,
            SUM(pm.assists) as a,
            SUM(pm.total_hero_damage) as dmg,
            SUM(pm.total_hero_heal) as heal,
            SUM(pm.total_damage_taken) as taken
        FROM mr_player_match pm
        WHERE pm.season_id=?
          AND pm.is_bot=0
          AND pm.game_label IN ({qmarks})
        GROUP BY pm.player_uid
    """, (season_id, *session_labels))

    core = c.fetchall()
    if not core:
        return pandas.DataFrame()

    # top hero per player in session
    c.execute(
        f"""
        SELECT
            hs.player_uid,
            hs.hero_id,
            SUM(hs.seconds) as sec
        FROM mr_hero_segments hs
        WHERE hs.season_id=?
          AND hs.is_bot=0
          AND hs.game_label IN ({qmarks})
        GROUP BY hs.player_uid, hs.hero_id
        ORDER BY hs.player_uid ASC, sec DESC
    """, (season_id, *session_labels))
    hero_rows = c.fetchall()

    top_hero_by_uid = {}
    for uid, hid, sec in hero_rows:
        uid = int(uid)
        if uid not in top_hero_by_uid:
            top_hero_by_uid[uid] = int(hid)

    # MVP/SVP counts
    c.execute(
        f"""
        SELECT mm.mvp_uid, mm.svp_uid
        FROM mr_match_meta mm
        WHERE mm.season_id=?
          AND mm.game_label IN ({qmarks})
    """, (season_id, *session_labels))
    meta_rows = c.fetchall()

    mvp_ct = defaultdict(int)
    svp_ct = defaultdict(int)
    for mvp_uid, svp_uid in meta_rows:
        if mvp_uid is not None:
            try:
                mvp_ct[int(mvp_uid)] += 1
            except Exception:
                pass
        if svp_uid is not None:
            try:
                svp_ct[int(svp_uid)] += 1
            except Exception:
                pass

    # badge signature per player (top 2 badges for the session)
    c.execute(
        f"""
        SELECT
            pb.player_uid,
            pb.badge_name,
            SUM(pb.badge_count) as ct
        FROM mr_player_badges pb
        WHERE pb.season_id=?
          AND pb.is_bot=0
          AND pb.game_label IN ({qmarks})
          AND pb.badge_name IS NOT NULL AND TRIM(pb.badge_name) <> ''
        GROUP BY pb.player_uid, pb.badge_name
        ORDER BY pb.player_uid ASC, ct DESC, pb.badge_name ASC
    """, (season_id, *session_labels))
    badge_rows = c.fetchall()

    badge_top2 = defaultdict(list)
    for uid, bname, ct in badge_rows:
        uid = int(uid)
        if len(badge_top2[uid]) < 2:
            badge_top2[uid].append(f"{str(bname)}×{int(ct or 0)}")

    # assemble dataframe
    data = []
    for uid, player, wins, losses, k, d, a, dmg, heal, taken in core:
        uid = int(uid)
        wins = int(wins or 0)
        losses = int(losses or 0)
        g = wins + losses
        if g <= 0:
            continue

        k = int(k or 0)
        d = int(d or 0)
        a = int(a or 0)
        dmg = float(dmg or 0.0)
        heal = float(heal or 0.0)
        taken = float(taken or 0.0)

        avg_k = k / g
        avg_d = d / g
        avg_a = a / g
        avg_kda = (avg_k + avg_a) / max(1.0, avg_d)

        data.append({
            "player_uid":
            uid,
            "player":
            str(player),
            "wins":
            wins,
            "losses":
            losses,
            "wl_str":
            f"{wins}/{losses}",
            "winrate":
            round((wins / g) * 100.0, 1),
            "avg_kda":
            round(avg_kda, 2),
            "avg_dmg":
            int(round(dmg / g)),
            "avg_heal":
            int(round(heal / g)),
            "avg_taken":
            int(round(taken / g)),
            "top_hero_sess_id":
            top_hero_by_uid.get(uid),
            "mvp":
            int(mvp_ct.get(uid, 0)),
            "svp":
            int(svp_ct.get(uid, 0)),
            "badges":
            " • ".join(badge_top2.get(uid, [])) if badge_top2.get(uid) else "—"
        })

    df = pandas.DataFrame(data)
    if df.empty:
        return df

    return df.sort_values(by=["winrate", "wins"],
                          ascending=[False, False]).reset_index(drop=True)


def _build_session_teammate_matrix_fair_api(season_id: int,
                                            session_labels: list[str]):
    """
    Session teammate matrix (humans only) using player_uid to avoid naming collisions.
    Same-team defined via is_win equality.
    Returns: matrix_df (index=uids), display_name_map (uid->name), order_uids
    """

    if not session_labels:
        return pandas.DataFrame(), {}, []

    qmarks = ",".join("?" for _ in session_labels)
    c.execute(
        f"""
        SELECT game_label, player_uid, player, is_win
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
          AND game_label IN ({qmarks})
    """, (season_id, *session_labels))
    rows = c.fetchall()
    if not rows:
        return pandas.DataFrame(), {}, []

    by_game = defaultdict(dict)
    name_by_uid = {}

    for gl, uid, player, w in rows:
        uid = int(uid)
        name_by_uid[uid] = str(player)
        by_game[str(gl)][uid] = int(w or 0)

    overlap = defaultdict(int)
    same_team = defaultdict(int)

    for gl, result in by_game.items():
        uids = sorted(result.keys())
        if len(uids) < 2:
            continue
        for a, b in combinations(uids, 2):
            key = (a, b)
            overlap[key] += 1
            if result[a] == result[b]:
                same_team[key] += 1

    order = sorted(name_by_uid.keys(),
                   key=lambda uid: name_by_uid[uid].lower())
    matrix = pandas.DataFrame(index=order, columns=order)

    for r in order:
        for c_ in order:
            if r == c_:
                matrix.loc[r, c_] = "-"
            else:
                a, b = (r, c_) if r < c_ else (c_, r)
                o = overlap.get((a, b), 0)
                s = same_team.get((a, b), 0)
                if o == 0:
                    matrix.loc[r, c_] = "-"
                else:
                    pct = (s / o) * 100.0
                    matrix.loc[r, c_] = f"{s}/{o} ({pct:.1f}%)"

    return matrix, name_by_uid, order


def _session_underdog_summary_api(season_id: int, session_labels: list[str]):
    if not session_labels:
        return 0, 0

    qmarks = ",".join("?" for _ in session_labels)
    c.execute(
        f"""
        SELECT game_label, player_uid, is_win
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
          AND game_label IN ({qmarks})
    """, (season_id, *session_labels))
    rows = c.fetchall()

    by_game = defaultdict(list)
    for gl, uid, w in rows:
        by_game[str(gl)].append((int(uid), int(w or 0)))

    uneven = 0
    underdog_wins = 0

    for gl, entries in by_game.items():
        win_team = {uid for uid, w in entries if w == 1}
        loss_team = {uid for uid, w in entries if w == 0}
        if not win_team or not loss_team:
            continue
        if len(win_team) == len(loss_team):
            continue
        uneven += 1
        smaller = win_team if len(win_team) < len(loss_team) else loss_team
        if smaller is win_team:
            underdog_wins += 1

    return uneven, underdog_wins


def _session_low_team_table_api(season_id: int, session_labels: list[str],
                                name_by_uid: dict[int, str]):
    if not session_labels:
        return []

    qmarks = ",".join("?" for _ in session_labels)
    c.execute(
        f"""
        SELECT game_label, player_uid, is_win
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
          AND game_label IN ({qmarks})
    """, (season_id, *session_labels))
    rows = c.fetchall()

    by_game = defaultdict(list)
    for gl, uid, w in rows:
        by_game[str(gl)].append((int(uid), int(w or 0)))

    uneven_games = defaultdict(int)
    on_less = defaultdict(int)
    wins_on_less = defaultdict(int)

    for gl, entries in by_game.items():
        win_team = {uid for uid, w in entries if w == 1}
        loss_team = {uid for uid, w in entries if w == 0}
        if not win_team or not loss_team or len(win_team) == len(loss_team):
            continue

        for uid, _w in entries:
            uneven_games[uid] += 1

        smaller = win_team if len(win_team) < len(loss_team) else loss_team
        smaller_won = (smaller is win_team)

        for uid in smaller:
            on_less[uid] += 1
            if smaller_won:
                wins_on_less[uid] += 1

    out = []
    for uid in sorted(set(list(uneven_games.keys()) + list(on_less.keys()))):
        unev = int(uneven_games.get(uid, 0))
        less = int(on_less.get(uid, 0))
        wless = int(wins_on_less.get(uid, 0))
        pct_less = (less / unev * 100.0) if unev > 0 else 0.0
        winpct_less = (wless / less * 100.0) if less > 0 else 0.0
        out.append([
            name_by_uid.get(uid, str(uid)), less, unev, f"{pct_less:.1f}%",
            f"{winpct_less:.1f}%"
        ])

    def _pct(x):
        return float(x[3][:-1]) if str(x[3]).endswith("%") else 0.0

    def _wp(x):
        return float(x[4][:-1]) if str(x[4]).endswith("%") else 0.0

    out.sort(key=lambda r: (_pct(r), _wp(r), str(r[0]).lower()), reverse=True)
    return out


async def _session_top_bans_and_picks(season_id: int,
                                      session_labels: list[str]):
    """
    Returns:
      bans_list: [(hero_name, count), ...] top 8
      picks_list: [(hero_name, time_seconds), ...] top 8 (humans only)
    """
    if not session_labels:
        return [], []

    qmarks = ",".join("?" for _ in session_labels)

    c.execute(
        f"""
        SELECT hero_id, COUNT(*) as ct
        FROM hero_bans
        WHERE season_id=?
          AND game_label IN ({qmarks})
        GROUP BY hero_id
        ORDER BY ct DESC
        LIMIT 8
    """, (season_id, *session_labels))
    bans = c.fetchall()

    c.execute(
        f"""
        SELECT hero_id, SUM(seconds) as sec
        FROM mr_hero_segments
        WHERE season_id=?
          AND is_bot=0
          AND game_label IN ({qmarks})
        GROUP BY hero_id
        ORDER BY sec DESC
        LIMIT 8
    """, (season_id, *session_labels))
    picks = c.fetchall()

    hero_ids = set()
    for hid, _ct in bans:
        hero_ids.add(str(hid))
    for hid, _sec in picks:
        hero_ids.add(str(hid))

    # resolve in parallel
    tasks = [get_hero_name(hid) for hid in hero_ids]
    names = await asyncio.gather(*tasks) if tasks else []
    name_map = {hid: nm for hid, nm in zip(hero_ids, names)}

    bans_list = [(name_map.get(str(hid), str(hid)), int(ct or 0))
                 for hid, ct in bans]
    picks_list = [(name_map.get(str(hid), str(hid)), int(float(sec or 0)))
                  for hid, sec in picks]
    return bans_list, picks_list


# ============================================================================================================
# Session Overview — Role Distribution
# - Uses mr_hero_segments seconds (humans only) and hero_cache.hero_role mapping.
# - Draws a ternary triangle (Vanguard/Duelist/Strategist shares) into the same right-side panel area.
# ============================================================================================================

def _so_table_exists(table: str) -> bool:
    try:
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (str(table),))
        return bool(c.fetchone())
    except Exception:
        return False


def _so_col_exists(table: str, col: str) -> bool:
    try:
        c.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in (c.fetchall() or [])]
        return str(col) in cols
    except Exception:
        return False


def _so_digits_only(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))


def _so_load_hero_roles_from_cache() -> dict[int, str]:
    """
    Returns hero_id(int) -> role(str) for roles in {Vanguard, Duelist, Strategist}.
    """
    if not _so_table_exists("hero_cache"):
        return {}
    if not _so_col_exists("hero_cache", "hero_role"):
        return {}
    if not _so_col_exists("hero_cache", "hero_id"):
        return {}

    try:
        c.execute(
            """
            SELECT hero_id, hero_role
            FROM hero_cache
            WHERE hero_role IS NOT NULL
              AND TRIM(hero_role) <> ''
        """
        )
        rows = c.fetchall() or []
    except Exception:
        rows = []

    out = {}
    for hid, role in rows:
        role_s = str(role or "").strip()
        if role_s not in ("Vanguard", "Duelist", "Strategist"):
            continue
        hid_s = str(hid or "").strip()
        hid_digits = _so_digits_only(hid_s) or hid_s
        try:
            hid_i = int(hid_digits)
        except Exception:
            continue
        out[hid_i] = role_s
    return out


def _so_role_distribution_session_api(season_id: int,
                                     session_labels: list[str],
                                     *,
                                     player_uids: set[int] | None = None) -> list[dict]:
    """
    Returns rows:
      {player_uid, v, d, s, total_seconds}
    where v/d/s are fractions summing to 1.0 (known-role seconds only).
    """
    ensure_mr_api_tables()
    if not session_labels:
        return []
    if not _so_table_exists("mr_hero_segments"):
        return []

    role_map = _so_load_hero_roles_from_cache()
    if not role_map:
        return []

    labs = [str(gl) for gl in (session_labels or []) if gl is not None and str(gl).strip()]
    if not labs:
        return []

    uid_set = set()
    if player_uids:
        try:
            uid_set = {int(u) for u in player_uids if u is not None}
        except Exception:
            uid_set = set()

    qmarks = ",".join("?" for _ in labs)
    params = [int(season_id), *labs]

    uid_filter_sql = ""
    if uid_set:
        uid_q = ",".join("?" for _ in sorted(uid_set))
        uid_filter_sql = f" AND hs.player_uid IN ({uid_q})"
        params.extend([int(u) for u in sorted(uid_set)])

    try:
        c.execute(
            f"""
            SELECT hs.player_uid, hs.hero_id, SUM(COALESCE(hs.seconds,0)) AS sec
            FROM mr_hero_segments hs
            WHERE hs.season_id = ?
              AND COALESCE(hs.is_bot,0)=0
              AND hs.game_label IN ({qmarks})
              {uid_filter_sql}
            GROUP BY hs.player_uid, hs.hero_id
            HAVING sec > 0
        """,
            tuple(params),
        )
        rows = c.fetchall() or []
    except Exception:
        return []

    per = defaultdict(lambda: {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0, "unknown": 0.0})
    any_known = False

    for uid, hid, sec in rows:
        if uid is None or hid is None:
            continue
        try:
            uid_i = int(uid)
        except Exception:
            continue

        hid_s = str(hid or "").strip()
        hid_digits = _so_digits_only(hid_s) or hid_s
        try:
            hid_i = int(hid_digits)
        except Exception:
            continue

        seconds = float(sec or 0.0)
        if seconds <= 0:
            continue

        role = (role_map.get(hid_i) or "").strip()
        if role in ("Vanguard", "Duelist", "Strategist"):
            per[uid_i][role] += seconds
            any_known = True
        else:
            per[uid_i]["unknown"] += seconds

    if not any_known:
        return []

    out = []
    for uid_i, bucket in per.items():
        known = float(bucket["Vanguard"] + bucket["Duelist"] + bucket["Strategist"])
        if known <= 0:
            continue
        out.append({
            "player_uid": int(uid_i),
            "v": float(bucket["Vanguard"] / known),
            "d": float(bucket["Duelist"] / known),
            "s": float(bucket["Strategist"] / known),
            "total_seconds": int(round(known)),
        })

    out.sort(key=lambda r: int(r.get("total_seconds", 0)), reverse=True)
    return out


def _so_clip(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _so_draw_role_triangle_panel(draw, x0: int, y0: int, w: int, h: int,
                                 *,
                                 title: str,
                                 role_rows: list[dict],
                                 player_names: dict[int, str],
                                 body_font,
                                 fg,
                                 gold,
                                 grid):
    """
    Draw ternary plot in a bounded panel:
      - Vanguard (top), Duelist (bottom-left), Strategist (bottom-right)
    """
    import math

    pad_in = 12
    lh = max(22, int(getattr(body_font, "size", 18) + 8))

    # Title
    draw.text((x0 + pad_in, y0 + pad_in), str(title or "Role Distribution — Session"), font=body_font, fill=gold)
    y_sep = y0 + pad_in + lh
    draw.line([(x0 + pad_in, y_sep), (x0 + w - pad_in, y_sep)], fill=grid, width=2)

    # Plot bounds
    plot_top = y_sep + 10
    plot_left = x0 + pad_in
    plot_w = max(10, w - pad_in * 2)
    plot_h = max(10, h - (plot_top - y0) - pad_in)

    if not role_rows:
        draw.text((plot_left, plot_top), "No role distribution data available for this session yet.", font=body_font, fill=fg)
        return

    sqrt3 = math.sqrt(3.0)
    side = min(float(plot_w), float(plot_h) * 2.0 / sqrt3)
    tri_h = side * sqrt3 / 2.0

    x_left = float(plot_left) + (float(plot_w) - side) / 2.0
    y_top = float(plot_top) + (float(plot_h) - tri_h) / 2.0
    y_bottom = y_top + tri_h

    A = (x_left + side / 2.0, y_top)       # Vanguard
    B = (x_left, y_bottom)                 # Duelist
    C = (x_left + side, y_bottom)          # Strategist

    # Grid
    def mix(P, Q, t: float):
        return (t * P[0] + (1.0 - t) * Q[0], t * P[1] + (1.0 - t) * Q[1])

    grid_col = (70, 70, 90)
    for t in (0.2, 0.4, 0.6, 0.8):
        p1 = mix(A, B, t)
        p2 = mix(A, C, t)
        draw.line([p1, p2], fill=grid_col, width=1)

        p3 = mix(B, A, t)
        p4 = mix(B, C, t)
        draw.line([p3, p4], fill=grid_col, width=1)

        p5 = mix(C, A, t)
        p6 = mix(C, B, t)
        draw.line([p5, p6], fill=grid_col, width=1)

    # Triangle outline
    draw.line([A, B], fill=grid, width=3)
    draw.line([B, C], fill=grid, width=3)
    draw.line([C, A], fill=grid, width=3)

    # Labels
    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    lab_v = "Vanguard"
    lab_d = "Duelist"
    lab_s = "Strategist"

    draw.text((A[0] - _tw(lab_v) / 2.0, A[1] - lh - 4), lab_v, font=body_font, fill=gold)
    draw.text((B[0] - _tw(lab_d) / 2.0, B[1] + 6), lab_d, font=body_font, fill=gold)
    draw.text((C[0] - _tw(lab_s) / 2.0, C[1] + 6), lab_s, font=body_font, fill=gold)

    # Points + name labels (light offsets, clamped)
    offsets = [(10, -14), (10, 4), (-10, -14), (-10, 4), (14, -6), (-14, -6)]
    rr = 6

    for idx, r in enumerate(role_rows):
        uid = int(r.get("player_uid", 0) or 0)
        v = float(r.get("v", 0.0) or 0.0)
        d = float(r.get("d", 0.0) or 0.0)
        s = float(r.get("s", 0.0) or 0.0)

        # barycentric to Cartesian
        px = d * B[0] + s * C[0] + v * A[0]
        py = d * B[1] + s * C[1] + v * A[1]

        draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=gold, outline=(0, 0, 0), width=1)

        name = _so_clip(player_names.get(uid, f"UID_{uid}"), 14)
        dx, dy = offsets[idx % len(offsets)]
        tx = px + dx
        ty = py + dy

        tx = max(float(plot_left), min(tx, float(plot_left + plot_w) - _tw(name) - 2.0))
        ty = max(float(plot_top), min(ty, float(plot_top + plot_h) - lh))

        draw.text((tx, ty), name, font=body_font, fill=fg)


# ------------------------------------------------------------------------------------------------------------
# Session overview image renderer
# The right-side panel displays the Role Distribution triangle.
# ------------------------------------------------------------------------------------------------------------
def _render_session_overview_image_api(session_date, session_labels, session_df, standings_df_after):
    body_font, title_font = get_fonts()

    bg = (25, 25, 25)
    fg = (230, 230, 230)
    gold = (255, 215, 0)
    header_bg = (40, 40, 40)
    grid = (80, 80, 80)

    pad = 20
    title_h = 100
    section_gap = 26
    header_h = 54
    row_h = 44

    A_headers = [
        "Player", "W/L", "Win%", "AvgKDA", "AvgDmg", "AvgHeal", "AvgTaken",
        "SessHero", "MVP", "SVP", "Badges"
    ]

    A_rows = []
    for _, r in session_df.iterrows():
        A_rows.append([
            str(r["player"])[:22],
            r["wl_str"],
            f"{float(r['winrate']):.1f}%",
            f"{float(r['avg_kda']):.2f}",
            f"{int(r['avg_dmg']):,}",
            f"{int(r['avg_heal']):,}",
            f"{int(r['avg_taken']):,}",
            str(r.get("top_hero_sess", "—"))[:18],
            str(int(r.get("mvp", 0))),
            str(int(r.get("svp", 0))),
            str(r.get("badges", "—"))[:48],
        ])

    B_headers = ["Player", "W/L", "Win%", "Pos"]
    B_rows = []
    for _, r in standings_df_after.iterrows():
        dlt = r.get("delta", "=")
        if dlt == "=":
            pos = f"{int(r['rank'])} –"
        elif dlt == "NEW":
            pos = f"{int(r['rank'])} NEW"
        else:
            pos = f"{int(r['rank'])} {dlt}"
        B_rows.append([
            str(r["player"])[:22], r["wl_str"], f"{float(r['winrate']):.1f}%", pos
        ])

    tmp_img = Image.new("RGB", (10, 10), bg)
    td = ImageDraw.Draw(tmp_img)

    def _tw(s) -> float:
        return td.textlength(str(s), font=body_font)

    def _fit_cols(headers, rows, mins, maxs):
        cols = []
        if not rows:
            rows = [["—"] * len(headers)]
        for i, h in enumerate(headers):
            vals = [r[i] for r in rows]
            w = max([_tw(h)] + [_tw(v) for v in vals]) + 24
            cols.append(int(min(maxs[i], max(mins[i], w))))
        return cols

    A_min = [220, 90, 90, 95, 120, 120, 130, 140, 60, 60, 300]
    A_max = [360, 110, 110, 120, 160, 160, 180, 200, 80, 80, 520]
    B_min = [260, 120, 120, 140]
    B_max = [380, 160, 160, 220]

    A_col = _fit_cols(A_headers, A_rows, A_min, A_max)
    B_col = _fit_cols(B_headers, B_rows, B_min, B_max)

    width = max(sum(A_col), sum(B_col)) + pad * 2

    A_h = header_h + row_h * max(1, len(A_rows))
    B_h = header_h + row_h * max(1, len(B_rows))
    total_h = pad + title_h + pad + 28 + A_h + section_gap + 28 + B_h + pad

    img = Image.new("RGB", (int(width), int(total_h)), bg)
    d = ImageDraw.Draw(img)

    t1 = f"Session Overview — {session_date or 'Latest Session'}"
    t2 = f"{len(session_labels)} game(s)"
    d.text(((width - d.textlength(t1, font=title_font)) // 2, pad), t1, font=title_font, fill=gold)
    d.text(((width - d.textlength(t2, font=body_font)) // 2, pad + title_font.size + 12), t2, font=body_font, fill=fg)

    y = pad + title_h

    def draw_table(y0, heads, rows, cols):
        xs = [pad + sum(cols[:i]) for i in range(len(cols))]
        for i, h in enumerate(heads):
            x = xs[i]
            d.rectangle([x, y0, x + cols[i], y0 + header_h], fill=header_bg, outline=grid)
            d.text((x + 10, y0 + 14), h, font=body_font, fill=fg)

        y1 = y0 + header_h
        if not rows:
            rows = [["—"] * len(heads)]
        for r_ in rows:
            for i, c_ in enumerate(r_):
                x = xs[i]
                d.rectangle([x, y1, x + cols[i], y1 + row_h], outline=grid)
                d.text((x + 10, y1 + 10), str(c_), font=body_font, fill=fg)
            y1 += row_h
        return y1

    d.text((pad, y), "Session Records (API)", font=body_font, fill=gold)
    y += 28
    y = draw_table(y, A_headers, A_rows, A_col)

    y += section_gap
    d.text((pad, y), "Season Standings (change after session)", font=body_font, fill=gold)
    y += 28
    y_b_table_top = y
    y_b_table_end = draw_table(y, B_headers, B_rows, B_col)

    # --------------------------------------------------------------------------------------------------------
    # Role Distribution (triangle) panel — replaces Closest Rivalry (H2H)
    # --------------------------------------------------------------------------------------------------------
    try:
        b_w = int(sum(B_col))
        x0 = pad + b_w + 18
        panel_w = int(width - pad - x0)
        panel_h_max = int(y_b_table_end - y_b_table_top)

        if panel_w >= 360 and panel_h_max >= 240 and session_labels:
            season_id_raw = get_current_season_id()
            season_id = int(str(season_id_raw).strip().split(".", 1)[0])

            # name map from session_df
            name_map = {}
            player_uids = set()
            for _, rr in session_df.iterrows():
                try:
                    uid = int(rr.get("player_uid"))
                except Exception:
                    continue
                player_uids.add(uid)
                name_map[uid] = str(rr.get("player", uid))

            role_rows = _so_role_distribution_session_api(
                season_id,
                session_labels,
                player_uids=player_uids,
            )

            d.rectangle([x0, y_b_table_top, x0 + panel_w, y_b_table_top + panel_h_max], fill=header_bg, outline=grid)

            _so_draw_role_triangle_panel(
                d,
                x0,
                y_b_table_top,
                panel_w,
                panel_h_max,
                title="Role Distribution — Session",
                role_rows=list(role_rows or []),
                player_names=name_map,
                body_font=body_font,
                fg=fg,
                gold=gold,
                grid=grid,
            )

    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf



def _render_session_pairs_underdog_image_api(session_date, session_labels,
                                             matrix_df, name_by_uid,
                                             order_uids, uneven, underdog_wins,
                                             low_team_rows, bans_list,
                                             picks_list):
    body_font, title_font = get_fonts()
    bg = (25, 25, 25)
    fg = (230, 230, 230)
    gold = (255, 215, 0)
    grid = (80, 80, 80)
    pad = 20
    title_h = 100
    row_h = 40
    gap = 26
    header_h = 54
    header_bg = (40, 40, 40)

    bold_font = body_font

    def _len(s):
        try:
            return bold_font.getlength(str(s))
        except Exception:
            return float(len(str(s)) * 10)

    if order_uids:
        col_headers = [name_by_uid.get(uid, str(uid)) for uid in order_uids]
        col_widths = []
        for col_idx, uid in enumerate(order_uids):
            header_len = _len(col_headers[col_idx])
            cell_len = 0.0
            for row_uid in order_uids:
                cell_len = max(cell_len, _len(str(matrix_df.loc[row_uid,
                                                                uid])))
            col_widths.append(int(max(header_len, cell_len) + 30))
        row_label_width = int(
            max(_len(name_by_uid.get(uid, str(uid)))
                for uid in order_uids) + 30)
    else:
        col_headers, col_widths, row_label_width = [], [], 240

    matrix_width = row_label_width + sum(col_widths) + pad * 2
    matrix_height = (len(order_uids) + 2) * row_h if order_uids else (3 *
                                                                      row_h)

    C_headers = ["Player", "On Less", "Uneven", "% on Less", "Win% on Less"]
    C_cols = [320, 140, 140, 160, 180]
    C_h = header_h + row_h * max(1, len(low_team_rows))

    # Estimate wrapped bans/picks height BEFORE creating the image
    # (rebuild the same strings and wrap based on a conservative width)
    approx_width = max(matrix_width, sum(C_cols) + pad * 2)
    tmp_img2 = Image.new("RGB", (10, 10), bg)
    td2 = ImageDraw.Draw(tmp_img2)

    def _wrap_tokens_measure(text: str, max_w: int) -> int:
        if not text or text.strip() == "":
            return 1
        tokens = text.split(" • ")
        lines = 0
        cur = ""
        for t in tokens:
            cand = t if not cur else f"{cur} • {t}"
            if td2.textlength(cand, font=body_font) <= max_w:
                cur = cand
            else:
                lines += 1 if cur else 0
                cur = t
        lines += 1 if cur else 1
        return max(1, lines)

    line_h = int(body_font.size + 6)
    max_text_w = int(approx_width - pad * 2)

    bans_txt = " • ".join([f"{nm}×{ct}"
                           for nm, ct in bans_list]) if bans_list else "—"
    picks_txt = " • ".join(
        [f"{nm}({_fmt_time(sec)})"
         for nm, sec in picks_list]) if picks_list else "—"

    bans_lines_n = _wrap_tokens_measure(bans_txt, max_text_w)
    picks_lines_n = _wrap_tokens_measure(picks_txt, max_text_w)

    bans_h = 30 + (bans_lines_n * line_h) + 18  # label gap + lines + spacing
    picks_h = 30 + (picks_lines_n * line_h) + 18

    width = max(matrix_width, sum(C_cols) + pad * 2)
    total_h = pad + title_h + pad + matrix_height + gap + 34 + bans_h + 18 + picks_h + gap + 40 + gap + C_h + pad

    img = Image.new("RGB", (int(width), int(total_h)), bg)
    d = ImageDraw.Draw(img)

    t1 = f"Session Matrix + Meta — {session_date or 'Latest Session'}"
    t2 = f"{len(session_labels)} game(s)"
    d.text(((width - d.textlength(t1, font=title_font)) // 2, pad),
           t1,
           font=title_font,
           fill=gold)
    d.text(((width - d.textlength(t2, font=title_font)) // 2,
            pad + title_font.size + 6),
           t2,
           font=title_font,
           fill=gold)

    y = pad + title_h

    d.text((pad, y - 28),
           "Teammate Matrix (Same-Team/Overlap + %) — Session",
           font=body_font,
           fill=gold)

    if not order_uids:
        d.text((pad, y + 10), "—", font=body_font, fill=fg)
        y = y + (2 * row_h)
    else:
        x_offsets = [
            row_label_width + pad + sum(col_widths[:i])
            for i in range(len(order_uids))
        ]

        for idx, header in enumerate(col_headers):
            d.text((x_offsets[idx], y),
                   header[:18],
                   font=bold_font,
                   fill=(255, 255, 255))

        for r_idx, r_uid in enumerate(order_uids):
            y_row = y + (r_idx + 1) * row_h
            d.text((pad, y_row),
                   name_by_uid.get(r_uid, str(r_uid))[:18],
                   font=bold_font,
                   fill=(255, 255, 255))
            for c_idx, c_uid in enumerate(order_uids):
                x_cell = x_offsets[c_idx]
                val = str(matrix_df.loc[r_uid, c_uid])
                d.rectangle([
                    x_cell - 6, y_row - 4, x_cell + col_widths[c_idx] - 10,
                    y_row + row_h - 10
                ],
                            outline=grid)
                d.text((x_cell, y_row),
                       val,
                       font=bold_font,
                       fill=(255, 255, 255))

        y = y + (len(order_uids) + 1) * row_h

    # Bans / Picks (WRAPPED)
    y += gap

    max_text_w = int(width - pad * 2)
    line_h = int(body_font.size + 6)

    def _wrap_tokens(text: str, max_w: int) -> list[str]:
        """
        Wrap on the ' • ' token so we keep the same list styling.
        """
        if not text or text.strip() == "":
            return ["—"]

        tokens = text.split(" • ")
        lines = []
        cur = ""

        for t in tokens:
            cand = t if not cur else f"{cur} • {t}"
            if d.textlength(cand, font=body_font) <= max_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = t

        if cur:
            lines.append(cur)

        return lines if lines else ["—"]

    d.text((pad, y), "Top Bans (session)", font=body_font, fill=gold)
    y += 30
    bans_txt = " • ".join([f"{nm}×{ct}"
                           for nm, ct in bans_list]) if bans_list else "—"
    bans_lines = _wrap_tokens(bans_txt, max_text_w)
    for ln in bans_lines:
        d.text((pad, y), ln, font=body_font, fill=fg)
        y += line_h
    y += 18

    d.text((pad, y),
           "Top Picks (by total time, humans)",
           font=body_font,
           fill=gold)
    y += 30
    picks_txt = " • ".join(
        [f"{nm}({_fmt_time(sec)})"
         for nm, sec in picks_list]) if picks_list else "—"
    picks_lines = _wrap_tokens(picks_txt, max_text_w)
    for ln in picks_lines:
        d.text((pad, y), ln, font=body_font, fill=fg)
        y += line_h
    y += 18

    # underdog summary
    y += gap
    summary = f"Uneven games: {uneven}   •   Smaller team won: {underdog_wins}"
    d.text((pad, y), summary, font=body_font, fill=gold)
    y += 36

    d.text((pad, y), "Session Low-Team (condensed)", font=body_font, fill=gold)
    y += 28

    def draw_table(y0, heads, rows, cols):
        xs = [pad + sum(cols[:i]) for i in range(len(cols))]
        for i, h in enumerate(heads):
            x = xs[i]
            d.rectangle([x, y0, x + cols[i], y0 + header_h],
                        fill=header_bg,
                        outline=grid)
            d.text((x + 10, y0 + 14), h, font=body_font, fill=fg)
        y1 = y0 + header_h
        if not rows:
            rows = [["—"] * len(heads)]
        for r_ in rows:
            for i, c_ in enumerate(r_):
                x = xs[i]
                d.rectangle([x, y1, x + cols[i], y1 + row_h], outline=grid)
                d.text((x + 10, y1 + 10), str(c_), font=body_font, fill=fg)
            y1 += row_h
        return y1

    _ = draw_table(y, C_headers, low_team_rows, C_cols)

    buf = io.BytesIO()
    img = img.convert("RGB")
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================================================================
# Command - Session Overview
# ============================================================================================================


@bot.command(name="session_overview")
async def session_overview(ctx, date_str: str = None):
    """
    API-native session overview (enhanced).
    Session definition: all imported matches on a Brisbane-local date (from match_imports.imported_at).
    Usage:
      !session_overview
      !session_overview 2026-01-05
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    sess_date, session_labels = _session_labels_for_date_api(
        season_id, date_str)
    if not session_labels:
        await ctx.send("No API-imported games found for that session/date.")
        return

    # Session records (session-only)
    session_df = _aggregate_session_records_api(season_id, session_labels)
    if session_df.empty:
        await ctx.send("No human player rows found for that session.")
        return

    # Resolve hero names for SESSION top hero only
    hero_ids = set()
    for hid in session_df["top_hero_sess_id"].dropna().tolist():
        try:
            hero_ids.add(str(int(hid)))
        except Exception:
            pass

    tasks = [get_hero_name(hid) for hid in hero_ids]
    names = await asyncio.gather(*tasks) if tasks else []
    hero_name_map = {hid: nm for hid, nm in zip(hero_ids, names)}

    def _hero_name(hid_any) -> str:
        # Use a simple ASCII placeholder that always renders
        if hid_any is None or (pandas.isna(hid_any) if hasattr(pandas, "isna") else False):
            return "-"
        try:
            return hero_name_map.get(str(int(hid_any)), str(int(hid_any)))
        except Exception:
            return str(hid_any)

    # --- Standings delta (before vs after session) ---
    all_labels = _all_ordered_game_labels_api(season_id)
    first_lab, last_lab = session_labels[0], session_labels[-1]

    try:
        first_idx = all_labels.index(first_lab)
        last_idx = all_labels.index(last_lab)
    except ValueError:
        first_idx, last_idx = 0, len(all_labels) - 1

    before_subset = all_labels[:first_idx]
    after_subset = all_labels[:last_idx + 1]

    prev_df = _aggregate_wl_for_labels_api(
        season_id, before_subset) if before_subset else None
    after_df = _aggregate_wl_for_labels_api(season_id, after_subset)
    after_df = _add_rank_deltas(after_df, prev_df)

    # --- Image 1 ---
    img1 = _render_session_overview_image_api(sess_date, session_labels,
                                              session_df, after_df)
    await ctx.send(file=discord.File(
        fp=img1, filename=f"session_overview_{sess_date}.png"))

    # --- Image 2 (matrix + meta) ---
    matrix_df, name_by_uid, order_uids = _build_session_teammate_matrix_fair_api(
        season_id, session_labels)
    uneven, underdog_wins = _session_underdog_summary_api(
        season_id, session_labels)
    low_team_rows = _session_low_team_table_api(season_id, session_labels,
                                                name_by_uid)
    bans_list, picks_list = await _session_top_bans_and_picks(
        season_id, session_labels)

    img2 = _render_session_pairs_underdog_image_api(
        sess_date, session_labels, matrix_df, name_by_uid, order_uids, uneven,
        underdog_wins, low_team_rows, bans_list, picks_list)
    await ctx.send(file=discord.File(
        fp=img2, filename=f"session_overview_pairs_{sess_date}.png"))

# ============================================================================================================
# COMMAND: !season_overviews
#   Dumps ALL session_overview outputs for the current season into one thread (or channel fallback).
#
# Notes:
# - Uses the same Brisbane-local date grouping the bot already applies for session_overview.
# - Sends the same two images per session as !session_overview (overview + matrix/meta).
# ============================================================================================================

async def _send_session_overview_to_channel(channel, *, season_id: int, date_str: str):
    """
    Send the same outputs as !session_overview <date_str>, but to a provided channel/thread.
    This avoids needing to fake ctx and lets us bulk-dump into a thread.
    """
    ensure_mr_api_tables()

    sess_date, session_labels = _session_labels_for_date_api(season_id, date_str)
    if not session_labels:
        await channel.send(f"**{date_str}** — No API-imported games found for that session/date.")
        return

    # Session records (session-only)
    session_df = _aggregate_session_records_api(season_id, session_labels)
    if session_df.empty:
        await channel.send(f"**{date_str}** — No human player rows found for that session.")
        return

    # Resolve hero names for SESSION top hero only
    hero_ids = set()
    for hid in session_df["top_hero_sess_id"].dropna().tolist():
        try:
            hero_ids.add(str(int(hid)))
        except Exception:
            pass

    tasks = [get_hero_name(hid) for hid in hero_ids]
    names = await asyncio.gather(*tasks) if tasks else []
    hero_name_map = {hid: nm for hid, nm in zip(hero_ids, names)}

    def _hero_name(hid_any) -> str:
        if hid_any is None or (pandas.isna(hid_any) if hasattr(pandas, "isna") else False):
            return "-"
        try:
            return hero_name_map.get(str(int(hid_any)), str(int(hid_any)))
        except Exception:
            return str(hid_any)

    # --- Standings delta (before vs after session) ---
    all_labels = _all_ordered_game_labels_api(season_id)
    first_lab, last_lab = session_labels[0], session_labels[-1]

    try:
        first_idx = all_labels.index(first_lab)
        last_idx = all_labels.index(last_lab)
    except ValueError:
        first_idx, last_idx = 0, len(all_labels) - 1

    before_subset = all_labels[:first_idx]
    after_subset = all_labels[:last_idx + 1]

    prev_df = _aggregate_wl_for_labels_api(season_id, before_subset) if before_subset else None
    after_df = _aggregate_wl_for_labels_api(season_id, after_subset)
    after_df = _add_rank_deltas(after_df, prev_df)

    # --- Image 1 ---
    img1 = _render_session_overview_image_api(sess_date, session_labels, session_df, after_df)
    await channel.send(
        content=f"📅 **Session {sess_date}** — games: {len(session_labels)}",
        file=discord.File(fp=img1, filename=f"session_overview_{sess_date}.png")
    )

    # --- Image 2 (matrix + meta) ---
    matrix_df, name_by_uid, order_uids = _build_session_teammate_matrix_fair_api(season_id, session_labels)
    uneven, underdog_wins = _session_underdog_summary_api(season_id, session_labels)
    low_team_rows = _session_low_team_table_api(season_id, session_labels, name_by_uid)
    bans_list, picks_list = await _session_top_bans_and_picks(season_id, session_labels)

    img2 = _render_session_pairs_underdog_image_api(
        sess_date, session_labels, matrix_df, name_by_uid, order_uids,
        uneven, underdog_wins, low_team_rows, bans_list, picks_list
    )
    await channel.send(file=discord.File(fp=img2, filename=f"session_matrix_{sess_date}.png"))


try:
    bot.remove_command("season_overviews")
except Exception:
    pass


@bot.command(name="season_overviews")
async def season_overviews(ctx, season_id: int = None):
    """
    Usage:
      !season_overviews
      !season_overviews 6
    """
    ensure_mr_api_tables()

    sid = int(season_id) if season_id is not None else int(get_current_season_id())

    # Find all Brisbane-local session dates (same grouping used by session_overview)
    try:
        ordered_dates, by_date = _get_games_grouped_by_date_api(sid)
    except Exception:
        ordered_dates, by_date = [], {}

    if not ordered_dates:
        await ctx.send(f"No sessions found for Season {sid}.")
        return

    # Create a thread so everything is in one place
    out_chan = ctx.channel
    try:
        thread_name = f"Season {sid} — Session Overviews ({len(ordered_dates)} sessions)"
        out_chan = await ctx.message.create_thread(name=thread_name, auto_archive_duration=1440)
    except Exception:
        # Fallback: post into the channel (still works, just noisier)
        out_chan = ctx.channel

    await out_chan.send(f"📚 Dumping **{len(ordered_dates)}** session_overview(s) for **Season {sid}**…")

    # Send in chronological order
    for d in ordered_dates:
        try:
            await _send_session_overview_to_channel(out_chan, season_id=sid, date_str=d)
        except Exception as e:
            await out_chan.send(f"**{d}** — error generating session overview: `{type(e).__name__}: {e}`")

    await out_chan.send("✅ Done.")

# ============================================================================================================
# ============================================================================================================
# COMMAND: leaderboard_image (default = human leaderboard)
#   !leaderboard_image bots   -> Bot HERO leaderboard (hero-level, bots only)
#   !leaderboard_image both   -> Sends BOTH images
# ============================================================================================================
# ============================================================================================================


@bot.command(name='leaderboard_image')
async def leaderboard_image(ctx, mode: str = None):
    ensure_auto_import_tables()
    ensure_mr_api_tables()

    season_id_raw = get_current_season_id()
    season_id = int(str(season_id_raw).split(".", 1)[0])

    mode_n = (mode or "").strip().lower()

    show_main = (mode_n in ("", "main", "humans", "human"))
    show_bot_heroes = (mode_n in ("bots", "bot", "botheroes", "bot_heroes"))
    show_both = (mode_n in ("both", "all"))
    show_half = (mode_n in ("0.5", "half", "halves", "split", "splitseason", "split_season"))

    if show_both:
        show_main = True
        show_bot_heroes = True

    # 0.5 mode is humans-only (by request)
    if show_half:
        show_main = True
        show_bot_heroes = False

    if not (show_main or show_bot_heroes):
        await ctx.send(
            "Usage: `!leaderboard_image` | `!leaderboard_image bots` | `!leaderboard_image both` | `!leaderboard_image 0.5`"
        )
        return

    # --------------------------
    # MAIN (humans) leaderboard
    # --------------------------
    import json
    from datetime import datetime, timezone

    def _season_id_int_from_any(season_any) -> int:
        # Season ids are integers; treat a value such as "5.5" as season 5.
        return int(str(season_any).strip().split(".", 1)[0])

    def _get_season_window_utc_from_db(season_any) -> tuple[datetime, datetime]:
        # Uses mr_season_windows (UTC ISO strings)
        season_id_int = _season_id_int_from_any(season_any)

        # Season windows are created with the auto-import tables.
        try:
            ensure_auto_import_tables()
        except Exception:
            # Continue when the tables have already been initialized elsewhere.
            pass

        c.execute(
            "SELECT start_utc, end_utc FROM mr_season_windows WHERE season_id = ?",
            (season_id_int,)
        )
        row = c.fetchone()
        if not row or not row[0] or not row[1]:
            raise RuntimeError(
                f"No season window set for season {season_id_int}. "
                f"Use !season_window_set {season_id_int} YYYY-MM-DD YYYY-MM-DD"
            )

        s = datetime.fromisoformat(row[0])
        e = datetime.fromisoformat(row[1])
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        return s, e

    def _get_season_split_windows_utc_from_db(season_any) -> dict[str, tuple[datetime, datetime]]:
        season_id_int = _season_id_int_from_any(season_any)
        try:
            ensure_auto_import_tables()
        except Exception:
            pass

        c.execute(
            """
            SELECT split_label, start_utc, end_utc
            FROM mr_season_split_windows
            WHERE season_id = ?
            """,
            (season_id_int,)
        )

        out: dict[str, tuple[datetime, datetime]] = {}
        for split_label, start_utc, end_utc in c.fetchall():
            if not start_utc or not end_utc:
                continue
            s = datetime.fromisoformat(str(start_utc))
            e = datetime.fromisoformat(str(end_utc))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            out[_normalise_season_split_label(split_label)] = (
                s.astimezone(timezone.utc),
                e.astimezone(timezone.utc),
            )
        return out

    def _match_time_map_for_season(season_id_int: int) -> dict[str, datetime]:
        """
        match_uid -> match_datetime_utc (timezone-aware)

        Split leaderboards prefer the local import/upload time so manually
        submitted matches land in the half they were submitted during. If an
        import timestamp is missing, fall back to the match-play timestamp.
        """
        def _parse_iso_utc_local(s: str) -> datetime | None:
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                return None

        out: dict[str, datetime] = {}

        # 1) Preferred for split views: local DB import/upload time.
        try:
            c.execute(
                """
                SELECT match_uid, imported_at
                FROM match_imports
                WHERE season_id = ? AND imported_at IS NOT NULL
                """,
                (season_id_int,)
            )
            for mu, iso in c.fetchall():
                dt = _parse_iso_utc_local(iso)
                if dt:
                    out[str(mu)] = dt
        except Exception:
            pass

        # 2) Fallback: persisted match-play timestamp.
        try:
            c.execute(
                """
                SELECT match_uid, match_time_utc
                FROM mr_match_meta
                WHERE season_id = ? AND match_time_utc IS NOT NULL
                """,
                (season_id_int,)
            )
            for mu, iso in c.fetchall():
                mu = str(mu)
                if mu in out:
                    continue
                dt = _parse_iso_utc_local(iso)
                if dt:
                    out[mu] = dt
        except Exception:
            pass

        # 3) Fallback: raw JSON extraction (match-details only; may be missing for some matches)
        c.execute(
            "SELECT match_uid, json_text FROM mr_match_json_raw WHERE season_id = ?",
            (season_id_int,)
        )
        for match_uid, json_text in c.fetchall():
            mu = str(match_uid)
            if mu in out:
                continue
            if not json_text:
                continue
            try:
                payload = json.loads(json_text)
            except Exception:
                continue

            try:
                dt = _extract_match_datetime_utc(payload)
            except Exception:
                dt = None

            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out[mu] = dt.astimezone(timezone.utc)

        return out

    def _fetch_human_rows_for_matchtime_range(
        season_id_int: int,
        start_dt: datetime,
        end_dt: datetime,
        *,
        end_inclusive: bool
    ) -> list[tuple]:
        """
        Returns rows shaped like:
        (player, kills, deaths, assists, damage, damage_taken, healing, win, loss, mvp, svp)
        Filtered by match datetime within [start, end) or [start, end].

        Uses import/upload time first via _match_time_map_for_season(), then
        falls back to the stored match-play timestamp if needed.
        """
        match_times = _match_time_map_for_season(season_id_int)
        if not match_times:
            return []

        def _in_range(dt: datetime) -> bool:
            if dt < start_dt:
                return False
            if end_inclusive:
                return dt <= end_dt
            return dt < end_dt

        include_uids = {mu for mu, dt in match_times.items() if _in_range(dt)}
        if not include_uids:
            return []

        # Pull all human player rows + MVP/SVP from meta, then filter in Python
        c.execute(
            """
            SELECT
                pm.match_uid,
                pm.player_uid,
                pm.player,
                pm.kills, pm.deaths, pm.assists,
                pm.total_hero_damage, pm.total_damage_taken, pm.total_hero_heal,
                pm.is_win,
                mm.mvp_uid,
                mm.svp_uid
            FROM mr_player_match pm
            LEFT JOIN mr_match_meta mm
                   ON mm.season_id = pm.season_id
                  AND mm.match_uid = pm.match_uid
            WHERE pm.season_id = ? AND pm.is_bot = 0
            """,
            (season_id_int,)
        )

        out: list[tuple] = []
        for (match_uid, player_uid, player, k, d, a, dmg, taken, heal, is_win, mvp_uid, svp_uid) in c.fetchall():
            if str(match_uid) not in include_uids:
                continue

            win = 1 if int(is_win or 0) == 1 else 0
            loss = 0 if win == 1 else 1

            mvp = 0
            svp = 0
            try:
                pu = int(player_uid)
                if mvp_uid is not None and int(mvp_uid) == pu:
                    mvp = 1
                if svp_uid is not None and int(svp_uid) == pu:
                    svp = 1
            except Exception:
                pass

            out.append((
                player,
                int(k or 0), int(d or 0), int(a or 0),
                int(float(dmg or 0)), int(float(taken or 0)), int(float(heal or 0)),
                win, loss,
                mvp, svp
            ))
        return out

    async def _make_main_leaderboard_buffer_halves() -> io.BytesIO | None:
        season_id_int = _season_id_int_from_any(season_id)
        s_start, s_end = _get_season_window_utc_from_db(season_id_int)
        split_windows = _get_season_split_windows_utc_from_db(season_id_int)
        if "0" in split_windows and "0.5" in split_windows:
            h1_start, h1_end = split_windows["0"]
            h2_start, h2_end = split_windows["0.5"]
            mid = h1_end
            using_custom_splits = True
        else:
            mid = s_start + (s_end - s_start) / 2
            h1_start, h1_end = s_start, mid
            h2_start, h2_end = mid, s_end
            using_custom_splits = False

        # If there are literally no human rows for the season at all, keep the existing behaviour (return None)
        try:
            c.execute(
                "SELECT 1 FROM mr_player_match WHERE season_id=? AND is_bot=0 LIMIT 1",
                (season_id_int,)
            )
            if not c.fetchone():
                return None
        except Exception:
            pass

        def _fmt_bris(d: datetime) -> str:
            try:
                return d.astimezone(BRIS_TZ).strftime("%d %b %Y")
            except Exception:
                return d.strftime("%Y-%m-%d")

        split_note = "custom" if using_custom_splits else "midpoint"
        top_label = f"{season_id_int}.0 First Half ({_fmt_bris(h1_start)} -> {_fmt_bris(h1_end)}, {split_note} split)"
        bot_label = f"{season_id_int}.5 Second Half ({_fmt_bris(h2_start)} -> {_fmt_bris(h2_end)}, {split_note} split)"
        rows_h1 = _fetch_human_rows_for_matchtime_range(
            season_id_int, h1_start, h1_end, end_inclusive=using_custom_splits
        )
        rows_h2 = _fetch_human_rows_for_matchtime_range(
            season_id_int, h2_start, h2_end, end_inclusive=True
        )

        img_top = _render_human_leaderboard_image_from_rows(rows_h1, top_label)
        img_bot = _render_human_leaderboard_image_from_rows(rows_h2, bot_label)

        def _placeholder_half(title: str, note: str) -> Image.Image:
            headers = ["Player", "Avg K/D/A", "Avg Dmg", "Avg Taken", "Avg Heal", "W/L", "Win%", "MVP", "SVP"]
            col_widths = [200, 180, 160, 160, 160, 100, 100, 80, 80]
            x_positions = [sum(col_widths[:i]) + 20 for i in range(len(col_widths))]
            width = x_positions[-1] + col_widths[-1] + 20

            row_height = 45
            header_height = 60
            title_height = 55
            section_height = 48
            height = title_height + header_height + section_height + row_height + 40

            background_color = (25, 25, 25)
            text_color = (230, 230, 230)
            header_bg = (40, 40, 40)
            border_color = (80, 80, 80)
            gold = (255, 215, 0)
            section_bg = (32, 32, 32)
            section_text = (245, 245, 245)
            muted_text = (170, 170, 170)

            img = Image.new("RGB", (width, height), background_color)
            draw = ImageDraw.Draw(img)
            font, title_font = get_fonts()

            title_text = f"Leaderboard - Season {title}"
            tw = draw.textlength(title_text, font=title_font)
            draw.text(((width - tw) // 2, 10), title_text, fill=gold, font=title_font)

            y = title_height
            for i, h in enumerate(headers):
                x = x_positions[i]
                draw.rectangle(
                    [x - 10, y, x - 10 + col_widths[i], y + header_height],
                    fill=header_bg,
                    outline=border_color
                )
                draw.text((x, y + 15), h, fill=text_color, font=font)

            y += header_height
            draw.rectangle([10, y, width - 10, y + section_height], fill=section_bg, outline=border_color)
            draw.text((20, y + 12), "Main Leaderboard — None yet", fill=section_text, font=title_font)

            y += section_height
            draw.rectangle([10, y, width - 10, y + row_height], outline=border_color)
            draw.text((20, y + 10), note, fill=muted_text, font=font)

            return img

        # Always show both halves: use a placeholder if a half has no renderable data
        if img_top is None:
            img_top = _placeholder_half(top_label, "No human matches found in this half (by match timestamp).")
        if img_bot is None:
            img_bot = _placeholder_half(bot_label, "No human matches found in this half (by match timestamp).")

        gap = 22
        width = max(img_top.size[0], img_bot.size[0])
        height = img_top.size[1] + gap + img_bot.size[1]

        bg = Image.new("RGB", (width, height), (25, 25, 25))
        bg.paste(img_top, (0, 0))
        bg.paste(img_bot, (0, img_top.size[1] + gap))

        out = io.BytesIO()
        bg.save(out, format="PNG")
        out.seek(0)
        return out


    def _render_human_leaderboard_image_from_rows(rows: list[tuple], season_label: str) -> Image.Image | None:
        """
        Builds the styled human leaderboard for an explicit season.
        Returns a PIL Image (not a buffer) so we can stitch two halves easily.
        """
        MIN_GAMES_MAIN = 30

        def _norm(name: str) -> str:
            return re.sub(r'\s+', '', (name or '')).lower()

        if not rows:
            return None

        agg = defaultdict(lambda: defaultdict(int))
        display_name_map = {}

        for (player, k, d, a, dmg, taken, heal, win, loss, mvp, svp) in rows:
            n = _norm(player)
            if not n:
                continue
            display_name_map[n] = player
            agg[n]["kills"] += int(k or 0)
            agg[n]["deaths"] += int(d or 0)
            agg[n]["assists"] += int(a or 0)
            agg[n]["damage"] += int(dmg or 0)
            agg[n]["taken"] += int(taken or 0)
            agg[n]["healing"] += int(heal or 0)
            agg[n]["wins"] += int(win or 0)
            agg[n]["losses"] += int(loss or 0)
            agg[n]["mvp"] += int(mvp or 0)
            agg[n]["svp"] += int(svp or 0)

        data = []
        for n, s in agg.items():
            games = s["wins"] + s["losses"]
            if games <= 0:
                continue
            winrate = round((s["wins"] / games) * 100.0, 1)
            data.append({
                "player": display_name_map.get(n, n),
                "games": int(games),
                "kills": int(s["kills"]),
                "deaths": int(s["deaths"]),
                "assists": int(s["assists"]),
                "damage": int(s["damage"]),
                "damage_taken": int(s["taken"]),
                "healing": int(s["healing"]),
                "wins": int(s["wins"]),
                "losses": int(s["losses"]),
                "mvp": int(s["mvp"]),
                "svp": int(s["svp"]),
                "winrate": float(winrate),
            })

        if not data:
            return None

        df = pandas.DataFrame(data)
        df_main = df[df["games"] >= MIN_GAMES_MAIN].copy()
        df_prov = df[df["games"] < MIN_GAMES_MAIN].copy()

        sort_cols = ["winrate", "wins"]
        df_main = df_main.sort_values(by=sort_cols, ascending=[False, False]).reset_index(drop=True)
        df_prov = df_prov.sort_values(by=sort_cols, ascending=[False, False]).reset_index(drop=True)

        headers = ["Player", "Avg K/D/A", "Avg Dmg", "Avg Taken", "Avg Heal", "W/L", "Win%", "MVP", "SVP"]
        col_widths = [200, 180, 160, 160, 160, 100, 100, 80, 80]
        x_positions = [sum(col_widths[:i]) + 20 for i in range(len(col_widths))]
        width = x_positions[-1] + col_widths[-1] + 20

        row_height = 45
        header_height = 60
        title_height = 55
        section_height = 48
        gap_height = 18

        n_main = len(df_main)
        n_prov = len(df_prov)

        height = title_height + header_height
        if n_main > 0:
            height += section_height + row_height * n_main
        if n_prov > 0:
            if n_main > 0:
                height += gap_height
            height += section_height + row_height * n_prov
        height += 40

        background_color = (25, 25, 25)
        text_color = (230, 230, 230)
        header_bg = (40, 40, 40)
        border_color = (80, 80, 80)
        gold = (255, 215, 0)
        silver = (192, 192, 192)
        bronze = (205, 127, 50)
        podium_colors = [gold, silver, bronze]

        section_bg = (32, 32, 32)
        section_text = (245, 245, 245)
        muted_text = (170, 170, 170)

        img = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(img)

        font, title_font = get_fonts()
        bold_font = font

        title_text = f"Leaderboard - Season {season_label}"
        title_width = draw.textlength(title_text, font=title_font)
        draw.text(((width - title_width) // 2, 10), title_text, fill=gold, font=title_font)

        y_header = title_height
        for i, h in enumerate(headers):
            x = x_positions[i]
            draw.rectangle([x - 10, y_header, x - 10 + col_widths[i], y_header + header_height],
                           fill=header_bg, outline=border_color)
            draw.text((x, y_header + 15), h, fill=text_color, font=bold_font)

        def _draw_section_bar(y_top: int, label: str):
            draw.rectangle([10, y_top, width - 10, y_top + section_height],
                           fill=section_bg, outline=border_color)
            draw.text((20, y_top + 12), label, fill=section_text, font=title_font)

        def _draw_rows(df_section: pandas.DataFrame, y_start: int, podium: bool):
            y = y_start
            for row_idx, row in df_section.iterrows():
                row_color = podium_colors[row_idx] if (podium and row_idx < 3) else text_color
                g = int(row["games"])
                avg_k = row["kills"] / g
                avg_d = row["deaths"] / g
                avg_a = row["assists"] / g

                values = [
                    str(row["player"])[:16].ljust(16),
                    f"{avg_k:.1f}/{avg_d:.1f}/{avg_a:.1f}",
                    f"{round(row['damage'] / g):,}",
                    f"{round(row['damage_taken'] / g):,}",
                    f"{round(row['healing'] / g):,}",
                    f"{int(row['wins'])}/{int(row['losses'])}",
                    f"{float(row['winrate']):.1f}%",
                    str(int(row["mvp"])),
                    str(int(row["svp"]))
                ]

                for i, val in enumerate(values):
                    x = x_positions[i]
                    draw.rectangle([x - 10, y, x - 10 + col_widths[i], y + row_height], outline=border_color)
                    draw.text((x, y + 10), val, fill=row_color, font=font)

                y += row_height
            return y

        y_cursor = title_height + header_height

        if n_main > 0:
            _draw_section_bar(y_cursor, f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games)")
            y_cursor += section_height
            y_cursor = _draw_rows(df_main, y_cursor, podium=True)
        else:
            _draw_section_bar(y_cursor, f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games) — None yet")
            note = f"Play at least {MIN_GAMES_MAIN} games to appear in the main rankings."
            draw.text((20, y_cursor + 12), note, fill=muted_text, font=font)
            y_cursor += section_height

        if n_prov > 0:
            if n_main > 0:
                y_cursor += gap_height
            _draw_section_bar(y_cursor, f"Provisional ( < {MIN_GAMES_MAIN} games ) — not ranked against main")
            y_cursor += section_height
            y_cursor = _draw_rows(df_prov, y_cursor, podium=False)

        return img


    async def _make_main_leaderboard_buffer() -> io.BytesIO | None:
        MIN_GAMES_MAIN = 30

        def _norm(name: str) -> str:
            return re.sub(r'\s+', '', (name or '')).lower()

        # Primary: API-derived season stats (humans only) created by submit_match
        c.execute("""
            SELECT
                player,
                kills, deaths, assists,
                damage, damage_taken, healing,
                win, loss,
                mvp, svp
            FROM game_stats_v
        """)
        rows = c.fetchall()

        # Fallback: MR tables (humans only) if game_stats_v empty
        if not rows:
            c.execute(
                """
                SELECT
                    player,
                    kills, deaths, assists,
                    total_hero_damage, total_damage_taken, total_hero_heal,
                    is_win
                FROM mr_player_match
                WHERE season_id = ? AND is_bot = 0
            """, (season_id, ))
            mr_rows = c.fetchall()
            if not mr_rows:
                return None

            rows = []
            for (player, k, d, a, dmg, taken, heal, is_win) in mr_rows:
                win = 1 if int(is_win or 0) == 1 else 0
                loss = 0 if win == 1 else 1
                rows.append((player, int(k or 0), int(d or 0), int(a or 0),
                             int(float(dmg or 0)), int(float(taken or 0)),
                             int(float(heal or 0)), int(win), int(loss), 0, 0))

        agg = defaultdict(lambda: defaultdict(int))
        display_name_map = {}

        for (player, k, d, a, dmg, taken, heal, win, loss, mvp, svp) in rows:
            n = _norm(player)
            if not n:
                continue
            display_name_map[n] = player
            agg[n]["kills"] += int(k or 0)
            agg[n]["deaths"] += int(d or 0)
            agg[n]["assists"] += int(a or 0)
            agg[n]["damage"] += int(dmg or 0)
            agg[n]["taken"] += int(taken or 0)
            agg[n]["healing"] += int(heal or 0)
            agg[n]["wins"] += int(win or 0)
            agg[n]["losses"] += int(loss or 0)
            agg[n]["mvp"] += int(mvp or 0)
            agg[n]["svp"] += int(svp or 0)

        data = []
        for n, s in agg.items():
            games = s["wins"] + s["losses"]
            if games <= 0:
                continue
            winrate = round((s["wins"] / games) * 100.0, 1)
            data.append({
                "player": display_name_map.get(n, n),
                "games": int(games),
                "kills": int(s["kills"]),
                "deaths": int(s["deaths"]),
                "assists": int(s["assists"]),
                "damage": int(s["damage"]),
                "damage_taken": int(s["taken"]),
                "healing": int(s["healing"]),
                "wins": int(s["wins"]),
                "losses": int(s["losses"]),
                "mvp": int(s["mvp"]),
                "svp": int(s["svp"]),
                "winrate": float(winrate),
            })

        if not data:
            return None

        df = pandas.DataFrame(data)
        df_main = df[df["games"] >= MIN_GAMES_MAIN].copy()
        df_prov = df[df["games"] < MIN_GAMES_MAIN].copy()

        sort_cols = ["winrate", "wins"]
        df_main = df_main.sort_values(by=sort_cols,
                                      ascending=[False,
                                                 False]).reset_index(drop=True)
        df_prov = df_prov.sort_values(by=sort_cols,
                                      ascending=[False,
                                                 False]).reset_index(drop=True)

        headers = [
            "Player", "Avg K/D/A", "Avg Dmg", "Avg Taken", "Avg Heal", "W/L",
            "Win%", "MVP", "SVP"
        ]
        col_widths = [200, 180, 160, 160, 160, 100, 100, 80, 80]
        x_positions = [
            sum(col_widths[:i]) + 20 for i in range(len(col_widths))
        ]
        width = x_positions[-1] + col_widths[-1] + 20

        row_height = 45
        header_height = 60
        title_height = 55
        section_height = 48
        gap_height = 18

        n_main = len(df_main)
        n_prov = len(df_prov)

        height = title_height + header_height
        if n_main > 0:
            height += section_height + row_height * n_main
        if n_prov > 0:
            if n_main > 0:
                height += gap_height
            height += section_height + row_height * n_prov
        height += 40

        background_color = (25, 25, 25)
        text_color = (230, 230, 230)
        header_bg = (40, 40, 40)
        border_color = (80, 80, 80)
        gold = (255, 215, 0)
        silver = (192, 192, 192)
        bronze = (205, 127, 50)
        podium_colors = [gold, silver, bronze]

        section_bg = (32, 32, 32)
        section_text = (245, 245, 245)
        muted_text = (170, 170, 170)

        img = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(img)

        font, title_font = get_fonts()
        bold_font = font

        title_text = f"Leaderboard - Season {season_id}"
        title_width = draw.textlength(title_text, font=title_font)
        draw.text(((width - title_width) // 2, 10),
                  title_text,
                  fill=gold,
                  font=title_font)

        y_header = title_height
        for i, h in enumerate(headers):
            x = x_positions[i]
            draw.rectangle([
                x - 10, y_header, x - 10 + col_widths[i],
                y_header + header_height
            ],
                           fill=header_bg,
                           outline=border_color)
            draw.text((x, y_header + 15), h, fill=text_color, font=bold_font)

        def _draw_section_bar(y_top: int, label: str):
            draw.rectangle([10, y_top, width - 10, y_top + section_height],
                           fill=section_bg,
                           outline=border_color)
            draw.text((20, y_top + 12),
                      label,
                      fill=section_text,
                      font=title_font)

        def _draw_rows(df_section: pandas.DataFrame, y_start: int,
                       podium: bool):
            y = y_start
            for row_idx, row in df_section.iterrows():
                row_color = podium_colors[row_idx] if (
                    podium and row_idx < 3) else text_color
                g = int(row["games"])

                avg_k = row["kills"] / g
                avg_d = row["deaths"] / g
                avg_a = row["assists"] / g

                values = [
                    str(row["player"])[:16].ljust(16),
                    f"{avg_k:.1f}/{avg_d:.1f}/{avg_a:.1f}",
                    f"{round(row['damage'] / g):,}",
                    f"{round(row['damage_taken'] / g):,}",
                    f"{round(row['healing'] / g):,}",
                    f"{int(row['wins'])}/{int(row['losses'])}",
                    f"{float(row['winrate']):.1f}%",
                    str(int(row["mvp"])),
                    str(int(row["svp"]))
                ]

                for i, val in enumerate(values):
                    x = x_positions[i]
                    draw.rectangle(
                        [x - 10, y, x - 10 + col_widths[i], y + row_height],
                        outline=border_color)
                    draw.text((x, y + 10), val, fill=row_color, font=font)

                y += row_height
            return y

        y_cursor = title_height + header_height

        if n_main > 0:
            _draw_section_bar(y_cursor,
                              f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games)")
            y_cursor += section_height
            y_cursor = _draw_rows(df_main, y_cursor, podium=True)
        else:
            _draw_section_bar(
                y_cursor,
                f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games) — None yet")
            note = f"Play at least {MIN_GAMES_MAIN} games to appear in the main rankings."
            draw.text((20, y_cursor + 12), note, fill=muted_text, font=font)
            y_cursor += section_height

        if n_prov > 0:
            if n_main > 0:
                y_cursor += gap_height
            _draw_section_bar(
                y_cursor,
                f"Provisional ( < {MIN_GAMES_MAIN} games ) — not ranked against main"
            )
            y_cursor += section_height
            y_cursor = _draw_rows(df_prov, y_cursor, podium=False)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    from datetime import datetime, timezone

    def _parse_dt_utc(s: str) -> datetime | None:
        if not s:
            return None
        try:
            # Accepts "YYYY-MM-DDTHH:MM:SS+00:00" etc
            dt = datetime.fromisoformat(str(s))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _get_season_window_utc(season_id: int) -> tuple[datetime | None, datetime | None]:
        # expects mr_season_windows(season_id, start_utc, end_utc)
        c.execute("SELECT start_utc, end_utc FROM mr_season_windows WHERE season_id=? LIMIT 1", (int(season_id),))
        r = c.fetchone()
        if not r:
            return None, None
        return _parse_dt_utc(r[0]), _parse_dt_utc(r[1])

    def _fetch_humans_rows_for_timerange(season_id: int, start_utc: datetime, end_utc: datetime):
        """
        Pulls all human player rows whose match time falls in [start_utc, end_utc).
        Uses mr_match_meta.match_time_utc where present, else falls back to match_imports.imported_at.
        """
        start_s = start_utc.astimezone(timezone.utc).isoformat()
        end_s   = end_utc.astimezone(timezone.utc).isoformat()

        c.execute(
            """
            SELECT
                pm.game_label,
                pm.camp,
                pm.is_win,
                pm.player_uid,
                pm.player,
                pm.hero_id,
                pm.kills,
                pm.deaths,
                pm.assists,
                pm.damage,
                pm.damage_taken,
                pm.healing,
                mm.mvp_uid,
                mm.svp_uid
            FROM mr_player_match pm
            LEFT JOIN mr_match_meta mm
                   ON mm.season_id = pm.season_id
                  AND mm.match_uid = pm.match_uid
            LEFT JOIN match_imports mi
                   ON mi.season_id = pm.season_id
                  AND mi.match_uid = pm.match_uid
            WHERE pm.season_id = ?
              AND pm.is_bot = 0
              AND datetime(COALESCE(mm.match_time_utc, mi.imported_at)) >= datetime(?)
              AND datetime(COALESCE(mm.match_time_utc, mi.imported_at)) <  datetime(?)
            """,
            (int(season_id), start_s, end_s),
        )
        return c.fetchall()


    # -----------------------------------------
    # BOT HERO leaderboard (hero-only, bots only)
    # -----------------------------------------
    async def _make_bot_hero_leaderboard_buffer() -> io.BytesIO | None:
        # Aggregate hero segments across ALL bots in the season
        c.execute(
            """
            SELECT hero_id, seconds, kills, deaths, assists, session_hit_rate, match_uid, game_label, player_uid
            FROM mr_hero_segments
            WHERE season_id = ? AND is_bot = 1
            """, (season_id, )
        )
        rows = c.fetchall()
        if not rows:
            return None

        # Aggregate in python
        agg = {}  # hero_id -> dict

        for hero_id, seconds, k, d, a, acc, match_uid, game_label, player_uid in rows:
            try:
                hid = int(hero_id)
            except Exception:
                continue

            sec = float(seconds or 0.0)
            kk = int(k or 0)
            dd = int(d or 0)
            aa = int(a or 0)

            rec = agg.setdefault(
                hid,
                {
                    "seconds": 0.0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "acc_w_num": 0.0,
                    "acc_w_den": 0.0,
                    "picks": 0,
                    "wins": 0,
                    "losses": 0,
                }
            )

            rec["seconds"] += sec
            rec["kills"] += kk
            rec["deaths"] += dd
            rec["assists"] += aa

            # weighted accuracy by time (ignore NULL)
            if acc is not None:
                try:
                    acc_f = float(acc)
                    if sec > 0:
                        rec["acc_w_num"] += acc_f * sec
                        rec["acc_w_den"] += sec
                except Exception:
                    pass

        # Win/Loss per hero pick:
        # Count distinct (match_uid, game_label, player_uid, hero_id) as one "pick record"
        c.execute(
            """
            SELECT
                hs.hero_id,
                SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pm.is_win=0 THEN 1 ELSE 0 END) as losses,
                COUNT(*) as picks
            FROM (
                SELECT DISTINCT season_id, match_uid, game_label, player_uid, hero_id
                FROM mr_hero_segments
                WHERE season_id=? AND is_bot=1
            ) hs
            JOIN mr_player_match pm
              ON pm.season_id=hs.season_id
             AND pm.match_uid=hs.match_uid
             AND pm.game_label=hs.game_label
             AND pm.player_uid=hs.player_uid
             AND pm.is_bot=1
            WHERE pm.season_id=?
            GROUP BY hs.hero_id
            """, (season_id, season_id)
        )
        for hero_id, wins, losses, picks in c.fetchall():
            try:
                hid = int(hero_id)
            except Exception:
                continue
            if hid not in agg:
                agg[hid] = {
                    "seconds": 0.0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "acc_w_num": 0.0,
                    "acc_w_den": 0.0,
                    "picks": 0,
                    "wins": 0,
                    "losses": 0,
                }
            agg[hid]["wins"] = int(wins or 0)
            agg[hid]["losses"] = int(losses or 0)
            agg[hid]["picks"] = int(picks or 0)

        # Build list + sort by Win% desc (then picks desc, then seconds desc)
        items = []
        for hid, s in agg.items():
            picks = int(s.get("picks") or 0)
            sec = float(s.get("seconds") or 0.0)
            if picks <= 0 and sec <= 0:
                continue
            wins = int(s.get("wins") or 0)
            winpct = (wins / picks) * 100.0 if picks > 0 else 0.0
            s["winpct"] = winpct
            items.append((hid, s))

        if not items:
            return None

        items.sort(
            key=lambda t: (t[1].get("winpct", 0.0), t[1].get("picks", 0), t[1].get("seconds", 0.0)),
            reverse=True
        )
        items = items[:40]

        # Resolve hero names (async)
        hero_name = {}
        for hid, _ in items:
            try:
                hero_name[hid] = await get_hero_name(str(hid))
            except Exception:
                hero_name[hid] = str(hid)

        headers = ["Hero", "Picks", "W/L", "Win%", "Time", "K/D/A", "KDA", "Avg Acc%"]
        col_widths = [250, 110, 110, 110, 170, 170, 120, 140]
        x_positions = [sum(col_widths[:i]) + 20 for i in range(len(col_widths))]
        width = x_positions[-1] + col_widths[-1] + 20

        row_height = 45
        header_height = 60
        title_height = 55
        height = title_height + header_height + row_height * len(items) + 40

        background_color = (25, 25, 25)
        text_color = (230, 230, 230)
        header_bg = (40, 40, 40)
        border_color = (80, 80, 80)
        gold = (255, 215, 0)

        img = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(img)
        font, title_font = get_fonts()

        title_text = f"Bot Hero Performance - Season {season_id} (sorted by Win%)"
        title_width = draw.textlength(title_text, font=title_font)
        draw.text(((width - title_width) // 2, 10), title_text, fill=gold, font=title_font)

        # Header row
        y_header = title_height
        for i, h in enumerate(headers):
            x = x_positions[i]
            draw.rectangle([x - 10, y_header, x - 10 + col_widths[i], y_header + header_height],
                           fill=header_bg, outline=border_color)
            draw.text((x, y_header + 15), h, fill=text_color, font=font)

        # Rows
        y = title_height + header_height
        for hid, s in items:
            sec = int(s.get("seconds") or 0)
            k = int(s.get("kills") or 0)
            d = int(s.get("deaths") or 0)
            a = int(s.get("assists") or 0)

            picks = int(s.get("picks") or 0)
            wins = int(s.get("wins") or 0)
            losses = int(s.get("losses") or 0)
            winpct = float(s.get("winpct") or 0.0)

            kda = (k + a) / max(1, d)

            acc_txt = "—"
            den = float(s.get("acc_w_den") or 0.0)
            if den > 0:
                acc = float(s.get("acc_w_num") or 0.0) / den
                acc_txt = f"{acc*100:.1f}%"

            values = [
                str(hero_name.get(hid, str(hid)))[:22],
                str(picks),
                f"{wins}/{losses}",
                f"{winpct:.1f}%",
                _fmt_time(sec),
                f"{k}/{d}/{a}",
                f"{kda:.2f}",
                acc_txt
            ]

            for i, val in enumerate(values):
                x = x_positions[i]
                draw.rectangle([x - 10, y, x - 10 + col_widths[i], y + row_height],
                               outline=border_color)
                draw.text((x, y + 10), val, fill=text_color, font=font)

            y += row_height

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    # --------------------------
    # Produce + send requested image(s)
    # --------------------------
    if show_main:
        if show_half:
            try:
                main_buf = await _make_main_leaderboard_buffer_halves()
            except Exception as e:
                await ctx.send(f"0.5 leaderboard failed: {e}")
                main_buf = None

            if not main_buf:
                await ctx.send("No human leaderboard data to display yet (for either half of the season).")
            else:
                await ctx.send(file=discord.File(fp=main_buf, filename="leaderboard_humans_halves.png"))
        else:
            main_buf = await _make_main_leaderboard_buffer()
            if not main_buf:
                await ctx.send("No human leaderboard data to display yet.")
            else:
                await ctx.send(file=discord.File(fp=main_buf, filename="leaderboard_humans.png"))

    if show_bot_heroes:
        bot_buf = await _make_bot_hero_leaderboard_buffer()
        if not bot_buf:
            await ctx.send("No bot hero data to display yet (import matches first).")
        else:
            await ctx.send(file=discord.File(fp=bot_buf, filename="leaderboard_bot_heroes.png"))



# ============================================================================================================
# ============================================================================================================
# Command - Teammate matrix fair
# ============================================================================================================
# ============================================================================================================
@bot.command(name='teammate_matrix_fair')
async def teammate_matrix_fair(ctx):
    """
    API-based teammate fairness matrix (humans only):
    - For each pair (A,B), looks at matches where BOTH A and B were present (overlap games).
    - Counts how often they were on the SAME team (same camp) in those overlap games.
    - Cell value: "<same_team_games>/<overlap_games> (XX%)"
    """
    global c

    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # ----------------------------
    # Load human players per game + team (camp)
    # ----------------------------
    c.execute(
        """
        SELECT game_label, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
    """, (season_id, ))
    rows = c.fetchall()

    if not rows:
        await ctx.send(
            "No API match data found (humans). Import matches first with `!submit_match`."
        )
        return

    # game_teams[label][camp] = set(norm_name)
    game_teams: dict[str, dict[int, set[str]]] = {}
    display_name_map: dict[str, str] = {}  # norm -> last seen display

    for game_label, player, camp in rows:
        if not game_label or not player:
            continue

        n = _norm_simple(str(player))
        if not n:
            continue

        display_name_map[n] = str(player)

        if game_label not in game_teams:
            game_teams[game_label] = {0: set(), 1: set(), -1: set()}

        # camp should usually be 0 or 1; keep unknowns in -1 (overlap counts, but not same-team unless both known)
        if camp in (0, 1):
            game_teams[game_label][int(camp)].add(n)
        else:
            game_teams[game_label][-1].add(n)

    if not game_teams:
        await ctx.send(
            "No valid human players found to build the teammate matrix.")
        return

    # ----------------------------
    # Pair tallies
    # ----------------------------
    same_team = defaultdict(lambda: defaultdict(int))
    overlap = defaultdict(lambda: defaultdict(int))

    for _label, teams in game_teams.items():
        # all players present in the match (humans)
        all_players = set().union(*teams.values())
        if len(all_players) < 2:
            continue

        # overlap: any two players in the same match
        for a, b in combinations(sorted(all_players), 2):
            overlap[a][b] += 1
            overlap[b][a] += 1

        # same team: only count when both players have a known camp (0 or 1) and are in the same camp set
        for camp_id in (0, 1):
            team = teams.get(camp_id) or set()
            if len(team) < 2:
                continue
            for a, b in combinations(sorted(team), 2):
                same_team[a][b] += 1
                same_team[b][a] += 1

    if not overlap:
        await ctx.send(
            "No overlap games found to build the teammate fairness matrix.")
        return

    # ----------------------------
    # Build matrix (DataFrame)
    # ----------------------------
    all_players = sorted(overlap.keys())
    matrix = pandas.DataFrame(index=all_players, columns=all_players)

    for a in all_players:
        for b in all_players:
            if a == b:
                matrix.loc[a, b] = "-"
                continue
            ov = overlap[a].get(b, 0)
            st = same_team[a].get(b, 0)
            if ov == 0:
                matrix.loc[a, b] = "0/0 (0%)"
            else:
                pct = round((st / ov) * 100)
                matrix.loc[a, b] = f"{st}/{ov} ({pct}%)"

    # relabel index/columns with last-seen display names
    matrix.index = [display_name_map.get(n, n) for n in matrix.index]
    matrix.columns = [display_name_map.get(n, n) for n in matrix.columns]

    # ----------------------------
    # Render image
    # ----------------------------
    try:
        font, title_font = get_fonts()
    except Exception:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    padding = 20
    row_height = 40

    # compute column widths based on header & cell content (cap to avoid absurd widths)
    col_widths = []
    for col_idx, col in enumerate(matrix.columns):
        header_w = font.getlength(str(col))
        cell_w = max(
            font.getlength(str(matrix.iloc[row_idx, col_idx]))
            for row_idx in range(len(matrix)))
        w = int(max(header_w, cell_w)) + 30
        col_widths.append(min(w, 260))  # cap

    row_label_width = int(
        max(font.getlength(str(name)) for name in matrix.index)) + 30
    row_label_width = min(row_label_width, 280)  # cap

    width = int(row_label_width + sum(col_widths) + padding * 2)

    header_rows = 3  # title + legend + col headers
    height = int(padding + header_rows * row_height +
                 len(matrix) * row_height + padding)

    img = Image.new("RGB", (width, height), (25, 25, 25))
    draw = ImageDraw.Draw(img)

    title = f"Teammate Fairness Matrix — Season {season_id} (API, Humans Only)"
    legend = "Higher % = usually teamed • ~50% = even split • Lower % = usually opposite teams"

    draw.text((padding, padding), title, font=title_font, fill=(255, 215, 0))
    draw.text((padding, padding + row_height),
              legend,
              font=font,
              fill=(200, 200, 200))

    start_y = padding + 2 * row_height

    # column headers
    for col_idx, col in enumerate(matrix.columns):
        x = row_label_width + sum(col_widths[:col_idx]) + padding
        draw.text((x, start_y), str(col)[:22], font=font, fill=(230, 230, 230))

    # rows
    for row_idx, row_player in enumerate(matrix.index):
        y = start_y + (row_idx + 1) * row_height

        draw.text((padding, y),
                  str(row_player)[:22],
                  font=font,
                  fill=(230, 230, 230))

        for col_idx, _ in enumerate(matrix.columns):
            val = str(matrix.iloc[row_idx, col_idx])
            x = row_label_width + sum(col_widths[:col_idx]) + padding

            draw.rectangle(
                [x - 5, y - 5, x + col_widths[col_idx], y + row_height - 10],
                outline=(100, 100, 100),
            )
            draw.text((x, y), val, font=font, fill=(230, 230, 230))

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    await ctx.send(
        file=discord.File(fp=buffer, filename="teammate_fairness_matrix.png"))

# ============================================================================================================
# ============================================================================================================
# Command - Teammate matrix fair (LOW TEAM ONLY / UNEVEN GAMES ONLY)
# ============================================================================================================
# ============================================================================================================
@bot.command(name='teammate_matrix_lowteam_fair', aliases=['teammate_matrix_low_team_fair'])
async def teammate_matrix_lowteam_fair(ctx):
    """
    API-based low-team teammate fairness matrix (humans only):
    - Only uses UNEVEN games.
    - For each pair (A,B), looks at uneven games where BOTH A and B were present.
    - Counts how often they were together on the LOW team in those uneven games.
    - Cell value: "<same_low_team_games>/<uneven_overlap_games> (XX%)"
    """
    global c

    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # ----------------------------
    # Load human players per game + team (camp)
    # ----------------------------
    c.execute(
        """
        SELECT game_label, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
    """, (season_id, ))
    rows = c.fetchall()

    if not rows:
        await ctx.send(
            "No API match data found (humans). Import matches first with `!submit_match`."
        )
        return

    # game_teams[label][camp] = set(norm_name)
    game_teams: dict[str, dict[int, set[str]]] = {}
    display_name_map: dict[str, str] = {}  # norm -> last seen display

    for game_label, player, camp in rows:
        if not game_label or not player:
            continue

        n = _norm_simple(str(player))
        if not n:
            continue

        display_name_map[n] = str(player)

        if game_label not in game_teams:
            game_teams[game_label] = {0: set(), 1: set(), -1: set()}

        # For low-team logic, camp must be known (0 or 1).
        # Keep unknowns separate but they are not used in the low-team matrix.
        if camp in (0, 1):
            game_teams[game_label][int(camp)].add(n)
        else:
            game_teams[game_label][-1].add(n)

    if not game_teams:
        await ctx.send(
            "No valid human players found to build the low-team teammate matrix.")
        return

    # ----------------------------
    # Pair tallies
    # ----------------------------
    same_low_team = defaultdict(lambda: defaultdict(int))
    overlap_uneven = defaultdict(lambda: defaultdict(int))

    uneven_games_found = 0

    for _label, teams in game_teams.items():
        team0 = set(teams.get(0) or set())
        team1 = set(teams.get(1) or set())

        # Need two known teams
        if not team0 or not team1:
            continue

        # Uneven games only
        if len(team0) == len(team1):
            continue

        uneven_games_found += 1

        all_players = team0 | team1
        if len(all_players) < 2:
            continue

        # Overlap only across uneven games
        for a, b in combinations(sorted(all_players), 2):
            overlap_uneven[a][b] += 1
            overlap_uneven[b][a] += 1

        # Count pairs together on the LOW team only
        low_team = team0 if len(team0) < len(team1) else team1
        if len(low_team) >= 2:
            for a, b in combinations(sorted(low_team), 2):
                same_low_team[a][b] += 1
                same_low_team[b][a] += 1

    if uneven_games_found == 0:
        await ctx.send(
            "No uneven games found for the current season, so the low-team teammate matrix cannot be built."
        )
        return

    if not overlap_uneven:
        await ctx.send(
            "No uneven-game player overlap found to build the low-team teammate matrix."
        )
        return

    # ----------------------------
    # Build matrix (DataFrame)
    # ----------------------------
    all_players = sorted(
        overlap_uneven.keys(),
        key=lambda n: display_name_map.get(n, n).lower()
    )
    matrix = pandas.DataFrame(index=all_players, columns=all_players)

    for a in all_players:
        for b in all_players:
            if a == b:
                matrix.loc[a, b] = "-"
                continue

            ov = overlap_uneven[a].get(b, 0)
            lt = same_low_team[a].get(b, 0)

            if ov == 0:
                matrix.loc[a, b] = "0/0 (0%)"
            else:
                pct = round((lt / ov) * 100)
                matrix.loc[a, b] = f"{lt}/{ov} ({pct}%)"

    # relabel index/columns with last-seen display names
    matrix.index = [display_name_map.get(n, n) for n in matrix.index]
    matrix.columns = [display_name_map.get(n, n) for n in matrix.columns]

    # ----------------------------
    # Render image
    # ----------------------------
    try:
        font, title_font = get_fonts()
    except Exception:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    padding = 20
    row_height = 40

    # compute column widths based on header & cell content (cap to avoid absurd widths)
    col_widths = []
    for col_idx, col in enumerate(matrix.columns):
        header_w = font.getlength(str(col))
        cell_w = max(
            font.getlength(str(matrix.iloc[row_idx, col_idx]))
            for row_idx in range(len(matrix))
        )
        w = int(max(header_w, cell_w)) + 30
        col_widths.append(min(w, 260))

    row_label_width = int(max(font.getlength(str(name)) for name in matrix.index)) + 30
    row_label_width = min(row_label_width, 280)

    width = int(row_label_width + sum(col_widths) + padding * 2)

    header_rows = 3  # title + legend + col headers
    height = int(padding + header_rows * row_height + len(matrix) * row_height + padding)

    img = Image.new("RGB", (width, height), (25, 25, 25))
    draw = ImageDraw.Draw(img)

    title = f"Low-Team Teammate Matrix — Season {season_id} (API, Humans Only)"
    legend = "Uses UNEVEN games only • Value = together on low team / overlap in uneven games"

    draw.text((padding, padding), title, font=title_font, fill=(255, 215, 0))
    draw.text((padding, padding + row_height),
              legend,
              font=font,
              fill=(200, 200, 200))

    start_y = padding + 2 * row_height
    start_x = padding + row_label_width

    # column headers
    x = start_x
    for col_idx, col_name in enumerate(matrix.columns):
        draw.rectangle(
            [x, start_y, x + col_widths[col_idx], start_y + row_height],
            outline=(120, 120, 120),
            fill=(45, 45, 45),
        )
        draw.text((x + 8, start_y + 8),
                  str(col_name),
                  font=font,
                  fill=(255, 255, 255))
        x += col_widths[col_idx]

    # rows + cells
    y = start_y + row_height
    for row_idx, row_name in enumerate(matrix.index):
        # row label
        draw.rectangle(
            [padding, y, padding + row_label_width, y + row_height],
            outline=(120, 120, 120),
            fill=(45, 45, 45),
        )
        draw.text((padding + 8, y + 8),
                  str(row_name),
                  font=font,
                  fill=(255, 255, 255))

        x = start_x
        for col_idx, col_name in enumerate(matrix.columns):
            val = str(matrix.iloc[row_idx, col_idx])

            fill = (35, 35, 35)
            text_fill = (235, 235, 235)

            if row_name == col_name:
                fill = (55, 55, 55)
                text_fill = (180, 180, 180)

            draw.rectangle(
                [x, y, x + col_widths[col_idx], y + row_height],
                outline=(90, 90, 90),
                fill=fill,
            )
            draw.text((x + 8, y + 8), val, font=font, fill=text_fill)
            x += col_widths[col_idx]

        y += row_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await ctx.send(file=discord.File(fp=buf, filename="teammate_matrix_lowteam_fair.png"))    

# ============================================================================================================
# Command - Win Matrix (TRUE heatmap fill by win rate)
# ============================================================================================================
@bot.command(name='win_matrix')
async def win_matrix(ctx):
    """
    API-based teammate win matrix (humans only):
      - Pair (A,B) counts games where A and B are on SAME camp in a match.
      - Cell shows wins/games and win%.
      - Heatmap fill: red (0%) -> yellow (50%) -> green (100%).
    """
    global c

    ensure_mr_api_tables()
    season_id = get_current_season_id()

    c.execute(
        """
        SELECT game_label, player, camp, is_win
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
    """, (season_id, ))
    rows = c.fetchall()

    if not rows:
        await ctx.send(
            "No API match data found (humans). Import matches first with `!submit_match`."
        )
        return

    df = pandas.DataFrame(rows,
                          columns=['game_label', 'player', 'camp', 'is_win'])

    # Normalised keys for stable indexing, display names for labels only
    df['norm_player'] = df['player'].apply(lambda s: _norm_simple(str(s)))
    norm_to_display = (df.groupby('norm_player')['player'].agg(
        lambda x: x.iloc[-1]).to_dict())

    teammate_stats = defaultdict(
        lambda: defaultdict(lambda: [0, 0]))  # [wins, games]

    for game_label, g in df.groupby('game_label'):
        for camp_id, team_df in g.groupby('camp'):
            if camp_id not in (0, 1):
                continue

            players = team_df['norm_player'].dropna().unique().tolist()
            if len(players) < 2:
                continue

            wins = team_df['is_win'].fillna(0).astype(int).tolist()
            team_won = 1 if sum(1 for x in wins
                                if x == 1) >= (len(wins) / 2.0) else 0

            for p1, p2 in combinations(sorted(players), 2):
                teammate_stats[p1][p2][1] += 1
                teammate_stats[p2][p1][1] += 1
                if team_won == 1:
                    teammate_stats[p1][p2][0] += 1
                    teammate_stats[p2][p1][0] += 1

    if not teammate_stats:
        await ctx.send(
            "Not enough overlapping teammate data to build the win matrix yet."
        )
        return

    norm_players = sorted(teammate_stats.keys())

    # Build display strings + numeric winrates keyed by NORMALISED names
    matrix_txt = pandas.DataFrame(index=norm_players, columns=norm_players)
    win_rate = {}  # (norm_a, norm_b) -> float win%

    for a in norm_players:
        for b in norm_players:
            if a == b:
                matrix_txt.loc[a, b] = "-"
                continue

            w, t = teammate_stats[a][b]
            if t > 0:
                pct = (w / t) * 100.0
                matrix_txt.loc[a, b] = f"{w}/{t}\n{pct:.1f}%"
                win_rate[(a, b)] = pct
            else:
                matrix_txt.loc[a, b] = "0/0\n0.0%"
                win_rate[(a, b)] = 0.0

    # ----------------------------
    # Render heatmap image (layout tuned for long names + 2-line cells)
    # ----------------------------
    padding = 22
    title_h = 72

    # Separate header height from cell height (helps names across top)
    header_h = 62
    cell_h = 58

    # Use slightly smaller fonts than global defaults so 2 lines fit cleanly
    try:
        cell_font, title_font = get_fonts(body_pt=24, title_pt=38)
        header_font, _ = get_fonts(body_pt=26, title_pt=38)
    except Exception:
        cell_font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    def heat_rgb(pct: float) -> tuple[int, int, int]:
        pct = max(0.0, min(100.0, float(pct)))
        if pct < 50.0:
            r = 255
            g = int(255 * (pct / 50.0))
            b = 0
        else:
            ratio = (pct - 50.0) / 50.0
            r = int(255 * (1.0 - ratio))
            g = 255
            b = 0
        return (r, g, b)

    def text_color_for_bg(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return (0, 0, 0) if lum > 140 else (255, 255, 255)

    def _ellipsize_to_px(text: str, font: ImageFont.FreeTypeFont, max_px: float) -> str:
        """Trim text with ellipsis so it fits within max_px (pixel-aware, not char-count)."""
        s = str(text or "")
        if max_px <= 0:
            return ""
        try:
            if font.getlength(s) <= max_px:
                return s
            ell = "…"
            if font.getlength(ell) > max_px:
                return ""
            # simple trim loop (names are short; this is fast enough)
            while s and font.getlength(s + ell) > max_px:
                s = s[:-1]
            return s + ell if s else ell
        except Exception:
            # fallback if getlength is unavailable
            return (s[:12] + "...") if len(s) > 15 else s

    def _line_height(font: ImageFont.FreeTypeFont) -> int:
        try:
            box = font.getbbox("Ag")
            return int(box[3] - box[1])
        except Exception:
            return 18

    def _draw_centered_multiline(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                                 text: str, font: ImageFont.FreeTypeFont,
                                 fill: tuple[int, int, int], spacing: int = 2):
        """Draw multiline text centered within a rectangle."""
        lines = (text or "").splitlines() or [""]
        lh = _line_height(font)
        try:
            widths = [font.getlength(line) for line in lines]
        except Exception:
            widths = [len(line) * 10 for line in lines]

        text_w = int(max(widths) if widths else 0)
        text_h = int(lh * len(lines) + spacing * (len(lines) - 1))

        base_y = y + max(0, (h - text_h) // 2)
        cur_y = base_y
        for line, lw in zip(lines, widths):
            base_x = x + max(0, (w - int(lw)) // 2)
            draw.text((base_x, cur_y), line, font=font, fill=fill)
            cur_y += lh + spacing

    # Build display names list once
    display_names = [str(norm_to_display.get(nm, nm)) for nm in norm_players]

    # Compute dynamic widths (with caps)
    try:
        max_header_px = max(header_font.getlength(nm) for nm in display_names) if display_names else 0
    except Exception:
        max_header_px = max((len(nm) for nm in display_names), default=0) * 12

    # Column width tuned to longest header; capped so images don't become absurdly wide
    cell_w = int(max(130, min(240, max_header_px + 24)))

    # Row label width tuned similarly; give a little more room than cells
    row_label_w = int(max(220, min(340, max_header_px + 40)))

    # Canvas size
    width = padding * 2 + row_label_w + cell_w * len(norm_players)
    height = padding * 2 + title_h + header_h + cell_h * len(norm_players) + 92  # +legend space

    img = Image.new("RGB", (width, height), (25, 25, 25))
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding),
        f"Teammate Win Matrix — Season {season_id} (Humans Only)",
        font=title_font,
        fill=(255, 215, 0),
    )

    start_y = padding + title_h
    start_x = padding

    border = (80, 80, 80)

    # Header row (column names)
    for j, norm_b in enumerate(norm_players):
        x = start_x + row_label_w + j * cell_w
        nm = norm_to_display.get(norm_b, norm_b)
        header_txt = _ellipsize_to_px(str(nm), header_font, cell_w - 12)
        _draw_centered_multiline(
            draw, x, start_y, cell_w, header_h,
            header_txt, header_font, (255, 255, 255), spacing=0
        )
        # header cell border
        draw.rectangle([x, start_y, x + cell_w, start_y + header_h], outline=border)

    grid_top = start_y + header_h

    # Rows + cells
    for i, norm_a in enumerate(norm_players):
        y = grid_top + i * cell_h
        row_nm = norm_to_display.get(norm_a, norm_a)
        row_txt = _ellipsize_to_px(str(row_nm), header_font, row_label_w - 12)

        # Row label background (subtle) + border
        draw.rectangle([start_x, y, start_x + row_label_w, y + cell_h], fill=(30, 30, 30), outline=border)
        _draw_centered_multiline(
            draw, start_x, y, row_label_w, cell_h,
            row_txt, header_font, (255, 255, 255), spacing=0
        )

        for j, norm_b in enumerate(norm_players):
            x = start_x + row_label_w + j * cell_w

            if norm_a == norm_b:
                bg = (45, 45, 45)
                txt = "-"
                tc = (200, 200, 200)
            else:
                pct = win_rate.get((norm_a, norm_b), 0.0)
                bg = heat_rgb(pct)
                txt = str(matrix_txt.loc[norm_a, norm_b])   # "w/t\nxx.x%"
                tc = text_color_for_bg(bg)

            draw.rectangle([x, y, x + cell_w, y + cell_h], fill=bg, outline=border)
            _draw_centered_multiline(draw, x, y, cell_w, cell_h, txt, cell_font, tc, spacing=2)

    # Legend (bottom right)
    legend_y = grid_top + len(norm_players) * cell_h + 24
    legend_x = start_x + row_label_w + max(0, (len(norm_players) * cell_w) - 380)

    draw.text((legend_x, legend_y - 22), "Win% heatmap", font=header_font, fill=(220, 220, 220))

    bar_w, bar_h = 320, 18
    for k in range(bar_w):
        pct = (k / (bar_w - 1)) * 100.0
        draw.line([(legend_x + k, legend_y), (legend_x + k, legend_y + bar_h)], fill=heat_rgb(pct))
    draw.rectangle([legend_x, legend_y, legend_x + bar_w, legend_y + bar_h], outline=border)

    draw.text((legend_x, legend_y + bar_h + 6), "0%", font=header_font, fill=(220, 220, 220))
    draw.text((legend_x + bar_w // 2 - 14, legend_y + bar_h + 6), "50%", font=header_font, fill=(220, 220, 220))
    draw.text((legend_x + bar_w - 44, legend_y + bar_h + 6), "100%", font=header_font, fill=(220, 220, 220))

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    await ctx.send(file=discord.File(fp=buffer, filename="win_matrix.png"))

# ============================================================================================================
# COMMAND: 2v2_records — Everyone’s W/L when ONLY 4 HUMANS were present (2 humans per team), bots allowed
#
#   Eligible match =
#     - exactly 4 human players total
#     - split across exactly 2 camps/teams
#     - 2 humans on each camp (camp values can be anything: 0/1, 1/2, etc.)
#     - bots may also be present (ignored for eligibility)
#
# Usage:
#   !2v2_records
# ============================================================================================================

try:
    bot.remove_command("2v2_records")
except Exception:
    pass


def _eligible_2v2_humans_game_labels_api(season_id: int) -> list[str]:
    ensure_mr_api_tables()
    return _team_size_eligible_exact_2v2_labels(c, season_id)


def _aggregate_wl_for_labels_2v2_humans_api(season_id: int, labels: list[str]) -> "pandas.DataFrame":
    ensure_mr_api_tables()
    return _team_size_aggregate_records(c, season_id, labels)


def create_2v2_records_image(results, title="2v2 (Humans) Records"):
    return _team_size_render_records_image(results, title=title)


@bot.command(name="2v2_records")
async def two_v_two_records(ctx):
    ensure_mr_api_tables()

    season_id_raw = get_current_season_id()
    season_id = int(str(season_id_raw).split(".", 1)[0])

    labels = _eligible_2v2_humans_game_labels_api(season_id)
    if not labels:
        await ctx.send(
            f"No eligible matches found for Season {season_id} with **exactly 4 humans** split **2v2** (bots ignored)."
        )
        return

    df = _aggregate_wl_for_labels_2v2_humans_api(season_id, labels)
    if df is None or df.empty:
        await ctx.send(f"No eligible human rows found for Season {season_id} in **4-humans-only (2v2)** matches.")
        return

    results = []
    for _, r in df.iterrows():
        results.append((
            str(r["player"]),
            int(r["games"]),
            int(r["wins"]),
            int(r["losses"]),
            float(r["winrate"]),
        ))

    title = f"2v2 (Humans) Records — Season {season_id}  •  Matches: {len(labels)}"
    buf = create_2v2_records_image(results, title=title)
    await ctx.send(file=discord.File(fp=buf, filename="2v2_records.png"))


# ============================================================================================================
# COMMAND: 4v4_records - Everyone's W/L when at least 8 HUMANS were present
#   Same output style as !2v2_records, but eligibility requires minimum 4 humans per team.
#
#   Eligible match =
#     - at least 8 human players total
#     - split across exactly 2 camps/teams
#     - at least 4 humans on each camp
#     - bots may also be present (ignored for eligibility)
#
# Usage:
#   !4v4_records
# ============================================================================================================

try:
    bot.remove_command("4v4_records")
except Exception:
    pass


def _eligible_min_4v4_humans_game_labels_api(season_id: int) -> list[str]:
    ensure_mr_api_tables()
    return _team_size_eligible_min_4v4_labels(c, season_id)


@bot.command(name="4v4_records")
async def four_v_four_records(ctx):
    ensure_mr_api_tables()

    season_id_raw = get_current_season_id()
    season_id = int(str(season_id_raw).split(".", 1)[0])

    labels = _eligible_min_4v4_humans_game_labels_api(season_id)
    if not labels:
        await ctx.send(
            f"No eligible matches found for Season {season_id} with at least **8 humans** split minimum **4v4** (bots ignored)."
        )
        return

    df = _aggregate_wl_for_labels_2v2_humans_api(season_id, labels)
    if df is None or df.empty:
        await ctx.send(f"No eligible human rows found for Season {season_id} in minimum **4v4** matches.")
        return

    results = []
    for _, r in df.iterrows():
        results.append((
            str(r["player"]),
            int(r["games"]),
            int(r["wins"]),
            int(r["losses"]),
            float(r["winrate"]),
        ))

    title = f"Min 4v4 (Humans) Records - Season {season_id}  |  Matches: {len(labels)}"
    buf = create_2v2_records_image(results, title=title)
    await ctx.send(file=discord.File(fp=buf, filename="4v4_records.png"))

# ============================================================================================================
# !profile — Single-image Scouting Report (API-native, 1 image, NO TOGGLE)
#
# Includes:
#   - Snapshot (no percentile bars; just values + percentile text)
#   - Role mix (time share) + Signature heroes (by PERFORMANCE: win% with >=5 games)
#   - Win/Avoid lists based on teammate heroes rather than players or the selected player's heroes
#   - Chemistry (no Δpp deltas)
#   - Momentum (no deltas) + Enemy ban pressure
#
# Requires tables:
#   mr_player_match, mr_hero_segments, mr_ban_picks, match_imports
#
# Uses these shared helpers:
#   ensure_mr_api_tables, get_current_season_id, get_fonts, norm_key, canonical_player_name,
#   get_hero_name, refresh_hero_cache, _fmt_time, _digits_only
# ============================================================================================================

def _kda(k: float, d: float, a: float) -> float:
    d = max(1.0, float(d))
    return (float(k) + float(a)) / d


def _safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _profile_has_column(table: str, col: str) -> bool:
    try:
        c.execute(f"PRAGMA table_info({table})")
        return any(str(r[1]).lower() == col.lower() for r in c.fetchall())
    except Exception:
        return False


# ------------------------------------------------------------------------------------------------------------
# Player resolution helpers
# ------------------------------------------------------------------------------------------------------------
def _get_api_players(season_id: int) -> list[dict]:
    """
    Humans only. Returns [{player_uid, player}]
    """
    ensure_mr_api_tables()
    return list_human_players(c, season_id)


def _resolve_player_uid(season_id: int, player_name: str) -> Optional[int]:
    """
    Normalized + partial match if unique.
    """
    if not player_name:
        return None
    q = norm_key(canonical_player_name(player_name.strip()))
    players = _get_api_players(season_id)
    if not players:
        return None

    exact = [p for p in players if norm_key(p["player"]) == q]
    if len(exact) == 1:
        return exact[0]["player_uid"]

    cand = [
        p for p in players
        if norm_key(p["player"]).startswith(q) or (q in norm_key(p["player"]))
    ]
    if len(cand) == 1:
        return cand[0]["player_uid"]

    return None


def _get_player_display_name(season_id: int, player_uid: int) -> str:
    ensure_mr_api_tables()
    return latest_player_name(c, season_id, player_uid)


# ------------------------------------------------------------------------------------------------------------
# Core calculations
# ------------------------------------------------------------------------------------------------------------
def _profile_norm_side(v):
    """
    Normalise side/team values into 0/1.
    Accepts 0/1 or 1/2.
    """
    try:
        i = int(v)
    except Exception:
        return None
    if i in (0, 1):
        return i
    if i in (1, 2):
        return i - 1
    return None


def _profile_percentile(values: list[float],
                        my_value: float,
                        *,
                        higher_is_better: bool = True) -> Optional[float]:
    vals = [
        float(v) for v in values
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    if not vals:
        return None

    if not higher_is_better:
        vals = [-v for v in vals]
        my = -float(my_value)
    else:
        my = float(my_value)

    below = sum(1 for v in vals if v < my)
    equal = sum(1 for v in vals if v == my)
    n = len(vals)
    return 100.0 * (below + 0.5 * equal) / n


def _profile_role_bucket(role_str: str) -> Optional[str]:
    rs = (role_str or "").strip().lower()
    if not rs:
        return None
    if "vanguard" in rs:
        return "Vanguard"
    if "duelist" in rs:
        return "Duelist"
    if "strateg" in rs:
        return "Strategist"
    return None


def _profile_load_hero_roles() -> dict[int, str]:
    """
    Returns {hero_id_int: role_str} from hero_cache.hero_role.
    Safe if hero_cache missing or hero_role not populated.
    """
    ensure_mr_api_tables()
    if not _profile_has_column("hero_cache", "hero_role"):
        return {}

    out: dict[int, str] = {}
    try:
        c.execute("""
            SELECT hero_id, hero_role
            FROM hero_cache
            WHERE hero_role IS NOT NULL AND TRIM(hero_role) <> ''
        """)
        for hid, role in c.fetchall() or []:
            hid_s = str(hid or "").strip()
            hid_digits = _digits_only(hid_s) or hid_s
            try:
                hi = int(hid_digits)
            except Exception:
                continue
            rs = str(role or "").strip()
            if rs:
                out[hi] = rs
    except Exception:
        return {}

    return out


def _profile_get_accuracy_by_player(season_id: int) -> dict[int, float]:
    """
    Weighted accuracy by seconds where session_hit_rate exists.
    """
    ensure_mr_api_tables()
    out: dict[int, float] = {}
    try:
        c.execute(
            """
            SELECT player_uid,
                   SUM(CASE WHEN session_hit_rate IS NOT NULL THEN session_hit_rate * COALESCE(seconds,0) ELSE 0 END) AS hit_sum,
                   SUM(CASE WHEN session_hit_rate IS NOT NULL THEN COALESCE(seconds,0) ELSE 0 END) AS sec_sum
            FROM mr_hero_segments
            WHERE season_id=? AND COALESCE(is_bot,0)=0
            GROUP BY player_uid
        """,
            (int(season_id),),
        )
        for uid, hit_sum, sec_sum in c.fetchall() or []:
            uid_i = _safe_int(uid)
            sec = float(_safe_float(sec_sum))
            if uid_i <= 0 or sec <= 0.0:
                continue
            out[uid_i] = float(_safe_float(hit_sum)) / sec
    except Exception:
        return {}
    return out


def _profile_get_season_totals(season_id: int, player_uid: int) -> dict:
    """
    Player season totals + per-game derived metrics.
    Includes FH/SK if columns exist.
    """
    ensure_mr_api_tables()

    fh_col = _profile_has_column("mr_player_match", "final_hits")
    sk_col = _profile_has_column("mr_player_match", "solo_kill")

    extra_cols = []
    extra_cols.append("SUM(COALESCE(final_hits,0)) as final_hits" if fh_col else "0 as final_hits")
    extra_cols.append("SUM(COALESCE(solo_kill,0)) as solo_kills" if sk_col else "0 as solo_kills")
    extra_sql = ",\n            ".join(extra_cols)

    c.execute(
        f"""
        SELECT
            COUNT(*) as games,
            SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END) as losses,
            SUM(kills) as kills,
            SUM(deaths) as deaths,
            SUM(assists) as assists,
            SUM(total_hero_damage) as dmg,
            SUM(total_damage_taken) as taken,
            SUM(total_hero_heal) as heal,
            {extra_sql}
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND is_bot=0
        """,
        (int(season_id), int(player_uid)),
    )

    row = c.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    games, wins, losses, k, d, a, dmg, taken, heal, fh, sk = row

    games = _safe_int(games)
    wins = _safe_int(wins)
    losses = _safe_int(losses)
    k = _safe_int(k)
    d = _safe_int(d)
    a = _safe_int(a)
    dmg = float(_safe_float(dmg))
    taken = float(_safe_float(taken))
    heal = float(_safe_float(heal))
    fh = _safe_int(fh)
    sk = _safe_int(sk)

    win_pct = (wins / games * 100.0) if games > 0 else 0.0

    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "win_pct": win_pct,
        "kills": k,
        "deaths": d,
        "assists": a,
        "dmg": dmg,
        "taken": taken,
        "heal": heal,
        "final_hits": fh,
        "solo_kills": sk,
        "kda": _kda(k, d, a),
        "dmg_pg": (dmg / games) if games else 0.0,
        "heal_pg": (heal / games) if games else 0.0,
        "taken_pg": (taken / games) if games else 0.0,
        "deaths_pg": (d / games) if games else 0.0,
        "fh_pg": (fh / games) if games else 0.0,
        "sk_pg": (sk / games) if games else 0.0,
    }


def _profile_get_all_player_metrics(season_id: int, *, min_games: int = 5) -> dict[int, dict]:
    """
    Per-player baseline metrics for percentile calculations.
    Filters to humans with >= min_games.
    """
    ensure_mr_api_tables()

    fh_col = _profile_has_column("mr_player_match", "final_hits")
    sk_col = _profile_has_column("mr_player_match", "solo_kill")

    extra_cols = []
    extra_cols.append("SUM(COALESCE(final_hits,0)) as final_hits" if fh_col else "0 as final_hits")
    extra_cols.append("SUM(COALESCE(solo_kill,0)) as solo_kills" if sk_col else "0 as solo_kills")
    extra_sql = ",\n            ".join(extra_cols)

    c.execute(
        f"""
        SELECT
            player_uid,
            COUNT(*) as games,
            SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
            SUM(kills) as kills,
            SUM(deaths) as deaths,
            SUM(assists) as assists,
            SUM(total_hero_damage) as dmg,
            SUM(total_hero_heal) as heal,
            SUM(total_damage_taken) as taken,
            {extra_sql}
        FROM mr_player_match
        WHERE season_id=? AND COALESCE(is_bot,0)=0
        GROUP BY player_uid
        """,
        (int(season_id),),
    )

    acc_map = _profile_get_accuracy_by_player(season_id)

    out: dict[int, dict] = {}
    for row in c.fetchall() or []:
        uid, games, wins, k, d, a, dmg, heal, taken, fh, sk = row
        uid_i = _safe_int(uid)
        g = _safe_int(games)
        if uid_i <= 0 or g < min_games:
            continue

        w = _safe_int(wins)
        k = _safe_int(k)
        d = _safe_int(d)
        a = _safe_int(a)
        dmg = float(_safe_float(dmg))
        heal = float(_safe_float(heal))
        taken = float(_safe_float(taken))
        fh = _safe_int(fh)
        sk = _safe_int(sk)

        out[uid_i] = {
            "games": g,
            "win_pct": (w / g * 100.0) if g else 0.0,
            "kda": _kda(k, d, a),
            "deaths_pg": (d / g) if g else 0.0,
            "dmg_pg": (dmg / g) if g else 0.0,
            "heal_pg": (heal / g) if g else 0.0,
            "taken_pg": (taken / g) if g else 0.0,
            "fh_pg": (fh / g) if g else 0.0,
            "sk_pg": (sk / g) if g else 0.0,
            "acc": acc_map.get(uid_i),
        }

    return out


def _profile_get_win_seq_by_import_time(season_id: int, player_uid: int) -> list[int]:
    """
    Uses match_imports.imported_at as match ordering.
    """
    ensure_mr_api_tables()
    c.execute(
        """
        SELECT pm.is_win
        FROM match_imports mi
        JOIN mr_player_match pm
          ON pm.season_id=mi.season_id
         AND pm.match_uid=mi.match_uid
         AND pm.game_label=mi.game_label
        WHERE mi.season_id=?
          AND pm.player_uid=?
          AND COALESCE(pm.is_bot,0)=0
        ORDER BY datetime(mi.imported_at) ASC
    """,
        (int(season_id), int(player_uid)),
    )
    return [1 if _safe_int(r[0]) == 1 else 0 for r in c.fetchall()]


def _profile_form_str(seq: list[int], n: int) -> str:
    if len(seq) < n:
        return "N/A"
    s = seq[-n:]
    return "".join("W" if x == 1 else "L" for x in s)


def _profile_current_streak(seq: list[int]) -> int:
    if not seq:
        return 0
    streak_type = seq[-1]
    run = 0
    for w in reversed(seq):
        if w != streak_type:
            break
        run += 1
    return run if streak_type == 1 else -run


def _profile_streak_txt(streak: int) -> str:
    if streak > 0:
        return f"{streak}W"
    if streak < 0:
        return f"{abs(streak)}L"
    return "0"


def _profile_get_momentum_last_n(season_id: int, player_uid: int, n: int = 10) -> dict:
    """
    Last-N win%, deaths/g, final-hits/g from match_imports ordering.
    """
    ensure_mr_api_tables()

    fh_col = _profile_has_column("mr_player_match", "final_hits")
    sel_fh = "COALESCE(pm.final_hits,0)" if fh_col else "0"

    c.execute(
        f"""
        SELECT pm.is_win, pm.deaths, {sel_fh} as final_hits
        FROM match_imports mi
        JOIN mr_player_match pm
          ON pm.season_id=mi.season_id
         AND pm.match_uid=mi.match_uid
         AND pm.game_label=mi.game_label
        WHERE mi.season_id=?
          AND pm.player_uid=?
          AND COALESCE(pm.is_bot,0)=0
        ORDER BY datetime(mi.imported_at) DESC
        LIMIT ?
    """,
        (int(season_id), int(player_uid), int(n)),
    )

    rows = c.fetchall() or []
    g = len(rows)
    if g <= 0:
        return {"games": 0, "win_pct": 0.0, "deaths_pg": 0.0, "fh_pg": 0.0}

    wins = sum(1 for w, _d, _fh in rows if _safe_int(w) == 1)
    deaths = sum(_safe_int(_d) for _w, _d, _fh in rows)
    fhs = sum(_safe_int(_fh) for _w, _d, _fh in rows)

    return {
        "games": g,
        "win_pct": (wins / g * 100.0),
        "deaths_pg": (deaths / g),
        "fh_pg": (fhs / g),
    }


def _profile_get_hero_stats(season_id: int, player_uid: int) -> list[dict]:
    """
    Aggregated per-hero stats (time, games, win%, KDA, FH/G).
    """
    ensure_mr_api_tables()

    fh_col = _profile_has_column("mr_hero_segments", "final_hits")
    sel_fh = "SUM(COALESCE(hs.final_hits,0))" if fh_col else "0"

    c.execute(
        f"""
        SELECT
            hs.hero_id,
            SUM(COALESCE(hs.seconds,0)) AS sec,
            COUNT(DISTINCT hs.match_uid) AS games,
            SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) AS wins,
            SUM(COALESCE(hs.kills,0)) AS k,
            SUM(COALESCE(hs.deaths,0)) AS d,
            SUM(COALESCE(hs.assists,0)) AS a,
            AVG(CASE WHEN hs.session_hit_rate IS NULL THEN NULL ELSE hs.session_hit_rate END) AS acc,
            {sel_fh} AS final_hits
        FROM mr_hero_segments hs
        JOIN mr_player_match pm
          ON pm.season_id=hs.season_id
         AND pm.match_uid=hs.match_uid
         AND pm.player_uid=hs.player_uid
        WHERE hs.season_id=?
          AND hs.player_uid=?
          AND COALESCE(hs.is_bot,0)=0
        GROUP BY hs.hero_id
        ORDER BY sec DESC
    """,
        (int(season_id), int(player_uid)),
    )

    out = []
    for hid, sec, games, wins, k, d, a, acc, fh in c.fetchall() or []:
        g = _safe_int(games)
        w = _safe_int(wins)
        fh_i = _safe_int(fh)
        out.append({
            "hero_id": _safe_int(hid),
            "seconds": int(_safe_float(sec)),
            "games": g,
            "wins": w,
            "win_pct": (w / g * 100.0) if g else 0.0,
            "k": _safe_int(k),
            "d": _safe_int(d),
            "a": _safe_int(a),
            "kda": _kda(_safe_int(k), _safe_int(d), _safe_int(a)),
            "acc": (float(acc) if acc is not None else None),
            "final_hits": fh_i,
            "fh_pg": (fh_i / g) if g else 0.0,
        })
    return out


def _profile_get_role_mix_and_role_wr(
    season_id: int,
    player_uid: int,
    role_map: dict[int, str],
) -> tuple[dict[str, float], dict[str, dict]]:
    """
    Role seconds share + role winrate by PRIMARY hero per match (max seconds).
    """
    ensure_mr_api_tables()

    # Seconds share
    c.execute(
        """
        SELECT hero_id, SUM(COALESCE(seconds,0)) AS sec
        FROM mr_hero_segments
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
        GROUP BY hero_id
    """,
        (int(season_id), int(player_uid)),
    )
    secs_by_role = {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0}
    total_sec = 0.0
    for hid, sec in c.fetchall() or []:
        hi = _safe_int(hid)
        s = float(_safe_float(sec))
        total_sec += s
        rb = _profile_role_bucket(role_map.get(hi) or "")
        if rb in secs_by_role:
            secs_by_role[rb] += s

    share = {k: (v / total_sec) if total_sec > 0 else 0.0 for k, v in secs_by_role.items()}

    # Primary hero role per match -> role WR
    c.execute(
        """
        SELECT hs.match_uid, hs.hero_id, COALESCE(hs.seconds,0) AS sec, pm.is_win
        FROM mr_hero_segments hs
        JOIN mr_player_match pm
          ON pm.season_id=hs.season_id
         AND pm.match_uid=hs.match_uid
         AND pm.player_uid=hs.player_uid
        WHERE hs.season_id=? AND hs.player_uid=? AND COALESCE(hs.is_bot,0)=0
    """,
        (int(season_id), int(player_uid)),
    )

    best_by_match: dict[str, tuple[int, float, int]] = {}  # mid -> (hero_id, sec, is_win)
    for mid, hid, sec, is_win in c.fetchall() or []:
        mid_s = str(mid or "")
        hi = _safe_int(hid)
        s = float(_safe_float(sec))
        w = 1 if _safe_int(is_win) == 1 else 0
        prev = best_by_match.get(mid_s)
        if prev is None or s > prev[1]:
            best_by_match[mid_s] = (hi, s, w)

    role_wr = {
        "Vanguard": {"games": 0, "wins": 0},
        "Duelist": {"games": 0, "wins": 0},
        "Strategist": {"games": 0, "wins": 0},
    }
    for hi, _s, w in best_by_match.values():
        rb = _profile_role_bucket(role_map.get(hi) or "")
        if rb in role_wr:
            role_wr[rb]["games"] += 1
            role_wr[rb]["wins"] += int(w)

    for rb, d in role_wr.items():
        g = d["games"]
        d["win_pct"] = (d["wins"] / g * 100.0) if g else 0.0

    return share, role_wr


def _profile_pick_best_role(role_wr: dict[str, dict], *, min_games: int = 4) -> Optional[dict]:
    cand = []
    for role, d in role_wr.items():
        g = int(d.get("games", 0) or 0)
        if g < min_games:
            continue
        cand.append({
            "role": role,
            "games": g,
            "win_pct": float(d.get("win_pct", 0.0) or 0.0),
        })
    if not cand:
        return None
    cand.sort(key=lambda x: (x["win_pct"], x["games"]), reverse=True)
    return cand[0]


def _profile_signature_heroes_by_performance(
    hero_stats: list[dict],
    *,
    min_games: int = 5,
    limit: int = 5,
) -> list[dict]:
    """
    Signature heroes ranked by PERFORMANCE (win%),
    only including heroes with >= min_games.
    """
    elig = [h for h in hero_stats if int(h.get("games", 0) or 0) >= min_games]
    if not elig:
        return []
    elig.sort(
        key=lambda x: (
            float(x.get("win_pct", 0.0) or 0.0),
            int(x.get("games", 0) or 0),
            int(x.get("seconds", 0) or 0),
        ),
        reverse=True,
    )
    return elig[:limit]


def _profile_get_chemistry(season_id: int, player_uid: int, *, min_games: int = 4) -> dict:
    """
    Best allies / worst pairings / under-used synergy (NO Δpp deltas).
    Uses camp + match_uid to identify allies.
    """
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT match_uid, camp, is_win
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
          AND match_uid IS NOT NULL
    """,
        (int(season_id), int(player_uid)),
    )
    rows = c.fetchall() or []
    mids = []
    side_by_mid: dict[str, int] = {}
    win_by_mid: dict[str, int] = {}
    for mid, camp, is_win in rows:
        mid_s = str(mid or "")
        s = _profile_norm_side(camp)
        if not mid_s or s is None:
            continue
        mids.append(mid_s)
        side_by_mid[mid_s] = s
        win_by_mid[mid_s] = 1 if _safe_int(is_win) == 1 else 0

    if not mids:
        return {"best": [], "worst": [], "underused": None, "baseline": 0.0, "eligible_games": 0}

    ally_stats: dict[int, dict] = defaultdict(lambda: {"games": 0, "wins": 0, "name": ""})

    CHUNK = 900
    for i in range(0, len(mids), CHUNK):
        chunk = mids[i:i + CHUNK]
        q_marks = ",".join("?" for _ in chunk)
        c.execute(
            f"""
            SELECT match_uid, player_uid, player, camp
            FROM mr_player_match
            WHERE season_id=?
              AND COALESCE(is_bot,0)=0
              AND match_uid IN ({q_marks})
        """,
            (int(season_id), *chunk),
        )
        for mid, uid, name, camp in c.fetchall() or []:
            mid_s = str(mid or "")
            if not mid_s or mid_s not in side_by_mid:
                continue
            uid_i = _safe_int(uid)
            if uid_i <= 0 or uid_i == int(player_uid):
                continue
            s = _profile_norm_side(camp)
            if s is None:
                continue
            if s != side_by_mid[mid_s]:
                continue  # enemy

            ally_stats[uid_i]["games"] += 1
            ally_stats[uid_i]["wins"] += int(win_by_mid.get(mid_s, 0))
            ally_stats[uid_i]["name"] = str(name or f"UID_{uid_i}")

    allies = []
    for uid_i, d in ally_stats.items():
        g = int(d["games"])
        if g <= 0:
            continue
        w = int(d["wins"])
        allies.append({
            "player_uid": uid_i,
            "player": d["name"],
            "games": g,
            "wins": w,
            "win_pct": (w / g * 100.0) if g else 0.0,
        })

    g0 = len(win_by_mid)
    w0 = sum(win_by_mid.values())
    baseline = (w0 / g0 * 100.0) if g0 else 0.0

    eligible = [a for a in allies if a["games"] >= min_games]
    eligible.sort(key=lambda x: (x["win_pct"], x["games"]), reverse=True)
    best = eligible[:3]

    eligible_w = [a for a in allies if a["games"] >= min_games]
    eligible_w.sort(key=lambda x: (x["win_pct"], -x["games"]))
    worst = eligible_w[:3]

    under = None
    cand = [a for a in allies if 2 <= a["games"] <= max(min_games - 1, 3)]
    cand.sort(key=lambda x: (x["win_pct"], x["games"]), reverse=True)
    if cand and cand[0]["win_pct"] >= max(baseline + 10.0, 60.0):
        under = cand[0]

    return {
        "best": best,
        "worst": worst,
        "underused": under,
        "baseline": baseline,
        "eligible_games": g0,
    }


def _profile_get_enemy_bans(season_id: int, player_uid: int) -> dict:
    """
    Top enemy bans against player (requires camp + mr_ban_picks).
    """
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT match_uid, camp
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
          AND match_uid IS NOT NULL
    """,
        (int(season_id), int(player_uid)),
    )
    mids = []
    side_by_mid = {}
    for mid, camp in c.fetchall() or []:
        mid_s = str(mid or "")
        s = _profile_norm_side(camp)
        if not mid_s or s is None:
            continue
        mids.append(mid_s)
        side_by_mid[mid_s] = s

    if not mids:
        return {"games": 0, "top": []}

    bans_by_mid_side: dict[str, dict[int, list[int]]] = defaultdict(lambda: {0: [], 1: []})

    CHUNK = 900
    for i in range(0, len(mids), CHUNK):
        chunk = mids[i:i + CHUNK]
        q_marks = ",".join("?" for _ in chunk)
        c.execute(
            f"""
            SELECT match_uid, battle_side, hero_id
            FROM mr_ban_picks
            WHERE season_id=?
              AND is_pick=0
              AND hero_id IS NOT NULL
              AND match_uid IN ({q_marks})
        """,
            (int(season_id), *chunk),
        )
        for mid, bside, hid in c.fetchall() or []:
            mid_s = str(mid or "")
            s = _profile_norm_side(bside)
            hi = _safe_int(hid)
            if not mid_s or s is None or hi <= 0:
                continue
            bans_by_mid_side[mid_s][s].append(hi)

    eligible_mids = [mid for mid in mids if mid in bans_by_mid_side]
    games = len(eligible_mids)
    if games <= 0:
        return {"games": 0, "top": []}

    counter = Counter()
    for mid in eligible_mids:
        s = side_by_mid.get(mid)
        if s not in (0, 1):
            continue
        enemy = 1 - s
        for hid in bans_by_mid_side[mid].get(enemy, []) or []:
            counter[hid] += 1

    top = []
    for hid, cnt in counter.most_common(5):
        top.append({
            "hero_id": int(hid),
            "count": int(cnt),
            "pct": (cnt / games * 100.0),
        })

    return {"games": games, "top": top}


def _profile_get_teammate_hero_wr_lists(
    season_id: int,
    player_uid: int,
    *,
    min_games: int = 5,
    top_n: int = 3,
) -> tuple[list[dict], list[dict]]:
    """
    TEAMMATE HERO win/avoid lists (heroes, not players):
      - For each match the player was in, find each teammate's PRIMARY hero (max seconds)
      - Treat teammate primary heroes as "present" in that match
      - Compute WR for each teammate hero across matches
    Returns: (best_list, worst_list) with {hero_id, games, wins, win_pct}
    """
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT match_uid, camp, is_win
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
          AND match_uid IS NOT NULL
        """,
        (int(season_id), int(player_uid)),
    )
    rows = c.fetchall() or []
    if not rows:
        return [], []

    mids: list[str] = []
    side_by_mid: dict[str, int] = {}
    win_by_mid: dict[str, int] = {}
    for mid, camp, is_win in rows:
        mid_s = str(mid or "")
        s = _profile_norm_side(camp)
        if not mid_s or s is None:
            continue
        mids.append(mid_s)
        side_by_mid[mid_s] = s
        win_by_mid[mid_s] = 1 if _safe_int(is_win) == 1 else 0

    if not mids:
        return [], []

    # For each (match, teammate) pick primary hero by seconds
    best_by_pair: dict[tuple[str, int], tuple[int, float]] = {}

    CHUNK = 900
    for i in range(0, len(mids), CHUNK):
        chunk = mids[i:i + CHUNK]
        q_marks = ",".join("?" for _ in chunk)
        c.execute(
            f"""
            SELECT pm.match_uid, pm.player_uid, pm.camp, hs.hero_id, COALESCE(hs.seconds,0) AS sec
            FROM mr_player_match pm
            JOIN mr_hero_segments hs
              ON hs.season_id=pm.season_id
             AND hs.match_uid=pm.match_uid
             AND hs.player_uid=pm.player_uid
            WHERE pm.season_id=?
              AND pm.match_uid IN ({q_marks})
              AND COALESCE(pm.is_bot,0)=0
              AND COALESCE(hs.is_bot,0)=0
              AND hs.hero_id IS NOT NULL
            """,
            (int(season_id), *chunk),
        )

        for mid, uid, camp, hid, sec in c.fetchall() or []:
            mid_s = str(mid or "")
            if not mid_s or mid_s not in side_by_mid:
                continue
            uid_i = _safe_int(uid)
            if uid_i <= 0 or uid_i == int(player_uid):
                continue

            s = _profile_norm_side(camp)
            if s is None or s != side_by_mid[mid_s]:
                continue  # not a teammate

            hi = _safe_int(hid)
            if hi <= 0:
                continue
            se = float(_safe_float(sec))

            key = (mid_s, uid_i)
            prev = best_by_pair.get(key)
            if prev is None or se > prev[1]:
                best_by_pair[key] = (hi, se)

    # Convert to "hero present in match" (unique set per match)
    heroes_present_by_mid: dict[str, set[int]] = defaultdict(set)
    for (mid_s, _uid_i), (hi, _se) in best_by_pair.items():
        heroes_present_by_mid[mid_s].add(int(hi))

    games_by_h: dict[int, int] = defaultdict(int)
    wins_by_h: dict[int, int] = defaultdict(int)

    for mid_s, hero_set in heroes_present_by_mid.items():
        w = int(win_by_mid.get(mid_s, 0))
        for hi in hero_set:
            games_by_h[hi] += 1
            wins_by_h[hi] += w

    items = []
    for hi, g in games_by_h.items():
        if g < min_games:
            continue
        w = int(wins_by_h.get(hi, 0))
        items.append({
            "hero_id": int(hi),
            "games": int(g),
            "wins": int(w),
            "win_pct": (w / g * 100.0) if g else 0.0,
        })

    if not items:
        return [], []

    best = sorted(items, key=lambda x: (x["win_pct"], x["games"]), reverse=True)[:top_n]
    worst = sorted(items, key=lambda x: (x["win_pct"], -x["games"]))[:top_n]
    return best, worst


# ------------------------------------------------------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------------------------------------------------------
def _profile_text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    try:
        return draw.textbbox((0, 0), text, font=font)
    except Exception:
        w, h = font.getsize(text)
        return (0, 0, w, h)


def _profile_text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    b = _profile_text_bbox(draw, text, font)
    return int(b[2] - b[0])


def _profile_clip_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    s = str(text or "")
    if _profile_text_w(draw, s, font) <= max_w:
        return s

    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = s[:mid] + "…"
        if _profile_text_w(draw, cand, font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    mid = max(0, lo - 1)
    return (s[:mid] + "…") if mid > 0 else "…"


def _profile_draw_role_mix_bar(draw, x, y, w, h, share: dict[str, float]):
    col = {
        "Vanguard": (90, 160, 255),
        "Duelist": (255, 120, 120),
        "Strategist": (120, 220, 140),
    }
    bg = (60, 60, 78)
    outline = (90, 90, 110)

    draw.rounded_rectangle([x, y, x + w, y + h],
                           radius=max(1, h // 2),
                           fill=bg,
                           outline=outline,
                           width=1)

    cur = x
    for key in ["Vanguard", "Duelist", "Strategist"]:
        frac = max(0.0, float(share.get(key, 0.0) or 0.0))
        segw = int(round(w * frac))
        if segw <= 0:
            continue
        draw.rectangle([cur, y, cur + segw, y + h], fill=col.get(key, (200, 200, 200)))
        cur += segw


def _render_profile_dashboard(player_name: str, pack: dict) -> io.BytesIO:
    # Canvas
    W, H = 2000, 1300
    pad = 26
    gap = 18

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)

    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    body_font, title_font = get_fonts(body_pt=22, title_pt=40)

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    # Header
    header_y = int(pad * 1.3)
    draw.text((pad * 2, header_y),
              f"{player_name} — Season {pack['season_id']} • Scouting Report",
              font=title_font,
              fill=accent)

    t = pack["totals"]
    meta = (f"{t['games']} games • {t['wins']}-{t['losses']} ({t['win_pct']:.1f}%)"
            f" • Streak {pack['streak_txt']} • Last10 {pack['form10']}")
    draw.text((pad * 2, header_y + 46), meta, font=body_font, fill=muted)

    # Grid
    top_y = header_y + 92
    col_w = (W - pad * 4 - gap * 2) // 3
    x1 = pad * 2
    x2 = x1 + col_w + gap
    x3 = x2 + col_w + gap
    row1_h = 520
    y1 = top_y
    y2 = y1 + row1_h + gap
    wide_w = (W - pad * 4 - gap) // 2
    row2_h = (H - pad * 2) - y2

    def panel(x, y, w, h, title):
        draw.rounded_rectangle([x, y, x + w, y + h], radius=18, outline=line, width=2)
        draw.text((x + 18, y + 14), title, font=body_font, fill=accent)

    panel(x1, y1, col_w, row1_h, "Snapshot")
    panel(x2, y1, col_w, row1_h, "Role Mix + Signature Heroes")
    panel(x3, y1, col_w, row1_h, "Win Conditions + Avoid List")
    panel(x1, y2, wide_w, row2_h, "Chemistry")
    panel(x1 + wide_w + gap, y2, wide_w, row2_h, "Momentum + Ban Pressure")

    # Panel A: Snapshot (no bars)
    px = x1 + 18
    py = y1 + 54

    label_x = px
    value_x = px + 230
    pct_x = px + (col_w - 36) - 90

    for m in pack["snapshot_rows"]:
        draw.text((label_x, py), m["label"], font=body_font, fill=muted)
        draw.text((value_x, py), m["value_txt"], font=body_font, fill=text)
        pct_val = m.get("pct")
        pct_txt = "—" if pct_val is None else f"{pct_val:.0f}th"
        draw.text((pct_x, py), pct_txt, font=body_font, fill=text)
        py += 40

    # Panel B: Role mix + signature heroes (performance)
    bx = x2 + 18
    by = y1 + 54
    draw.text((bx, by), "Role mix (time share)", font=body_font, fill=muted)
    by += 30
    _profile_draw_role_mix_bar(draw, bx, by, col_w - 36, 22, pack["role_share"])
    by += 34

    rs = pack["role_share"]
    draw.text((bx, by),
              f"Vanguard {rs['Vanguard']*100:.0f}%   Duelist {rs['Duelist']*100:.0f}%   Strategist {rs['Strategist']*100:.0f}%",
              font=body_font,
              fill=text)
    by += 50

    draw.text((bx, by), "Signature heroes (top 5 by win%, ≥5 games)", font=body_font, fill=muted)
    by += 30

    # Shift columns LEFT so WR shows game count fully
    hero_col = bx
    time_col = bx + 270
    wr_col = bx + 380
    kda_col = bx + 520

    draw.text((hero_col, by), "Hero", font=body_font, fill=muted)
    draw.text((time_col, by), "Time", font=body_font, fill=muted)
    draw.text((wr_col, by), "WR", font=body_font, fill=muted)
    draw.text((kda_col, by), "KDA", font=body_font, fill=muted)
    by += 26

    sig = pack.get("signature_heroes", []) or []
    if not sig:
        draw.text((bx, by), "—", font=body_font, fill=text)
    else:
        for h in sig:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, 255)
            draw.text((hero_col, by), hn, font=body_font, fill=text)
            draw.text((time_col, by), _fmt_time(h["seconds"]), font=body_font, fill=text)
            draw.text((wr_col, by), f"{h['win_pct']:.0f}% ({h['games']}g)", font=body_font, fill=text)
            draw.text((kda_col, by), f"{h['kda']:.2f}", font=body_font, fill=text)
            by += 32

    # Panel C: Best role + TEAMMATE HERO win/avoid
    cx = x3 + 18
    cy = y1 + 54

    br = pack.get("best_role")
    if br:
        draw.text((cx, cy),
                  f"Best primary role: {br['role']} ({br['win_pct']:.0f}% over {br['games']}g)",
                  font=body_font,
                  fill=text)
    else:
        draw.text((cx, cy), "Best primary role: —", font=body_font, fill=text)
    cy += 44

    draw.text((cx, cy), "Win conditions teammates (top 3 heroes)", font=body_font, fill=muted)
    cy += 30

    tw = pack.get("teammate_hero_win", []) or []
    if tw:
        for h in tw[:3]:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, col_w - 36)
            draw.text((cx, cy),
                      f"• {hn}: {h['win_pct']:.0f}% ({h['games']}g)",
                      font=body_font,
                      fill=text)
            cy += 30
    else:
        draw.text((cx, cy), "—", font=body_font, fill=text)
        cy += 30

    cy += 14
    draw.text((cx, cy), "Avoid / risk teammates (bottom 3 heroes)", font=body_font, fill=muted)
    cy += 30

    tr = pack.get("teammate_hero_risk", []) or []
    if tr:
        for h in tr[:3]:
            hn = pack["hero_names"].get(h["hero_id"], str(h["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, col_w - 36)
            draw.text((cx, cy),
                      f"• {hn}: {h['win_pct']:.0f}% ({h['games']}g)",
                      font=body_font,
                      fill=text)
            cy += 30
    else:
        draw.text((cx, cy), "—", font=body_font, fill=text)
        cy += 30

    # Panel D: Chemistry (no deltas)
    dx = x1 + 18
    dy = y2 + 54
    chem = pack["chemistry"]
    draw.text((dx, dy),
              f"Eligible games: {chem.get('eligible_games',0)} • Baseline WR: {chem.get('baseline',0.0):.1f}%",
              font=body_font,
              fill=muted)
    dy += 40

    draw.text((dx, dy), "Best allies", font=body_font, fill=accent)
    dy += 30
    if chem["best"]:
        for a in chem["best"]:
            nm = _profile_clip_text(draw, a["player"], body_font, wide_w - 60)
            draw.text((dx, dy),
                      f"• {nm}: {a['win_pct']:.0f}% ({a['wins']}/{a['games']})",
                      font=body_font,
                      fill=text)
            dy += 30
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)
        dy += 30

    dy += 10
    draw.text((dx, dy), "Worst pairings", font=body_font, fill=accent)
    dy += 30
    if chem["worst"]:
        for a in chem["worst"]:
            nm = _profile_clip_text(draw, a["player"], body_font, wide_w - 60)
            draw.text((dx, dy),
                      f"• {nm}: {a['win_pct']:.0f}% ({a['wins']}/{a['games']})",
                      font=body_font,
                      fill=text)
            dy += 30
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)
        dy += 30

    dy += 10
    draw.text((dx, dy), "Under-used synergy", font=body_font, fill=accent)
    dy += 30
    u = chem.get("underused")
    if u:
        nm = _profile_clip_text(draw, u["player"], body_font, wide_w - 60)
        draw.text((dx, dy),
                  f"• {nm}: {u['win_pct']:.0f}% ({u['wins']}/{u['games']})",
                  font=body_font,
                  fill=text)
    else:
        draw.text((dx, dy), "—", font=body_font, fill=text)

    # Panel E: Momentum + bans (no deltas)
    ex = x1 + wide_w + gap + 18
    ey = y2 + 54
    m10 = pack["momentum"]

    draw.text((ex, ey), "Last 10 games momentum", font=body_font, fill=accent)
    ey += 34

    if m10["games"]:
        draw.text((ex, ey), f"Win%: {m10['win_pct']:.1f}%", font=body_font, fill=text)
        ey += 28
        draw.text((ex, ey), f"Deaths/G: {m10['deaths_pg']:.2f}", font=body_font, fill=text)
        ey += 28
        draw.text((ex, ey), f"Final Hits/G: {m10['fh_pg']:.2f}", font=body_font, fill=text)
    else:
        draw.text((ex, ey), "Not enough data.", font=body_font, fill=text)
    ey += 44

    bans = pack["enemy_bans"]
    draw.text((ex, ey),
              f"Enemy ban pressure (eligible games: {bans['games']})",
              font=body_font,
              fill=accent)
    ey += 34

    if bans["top"]:
        for b in bans["top"]:
            hn = pack["hero_names"].get(b["hero_id"], str(b["hero_id"]))
            hn = _profile_clip_text(draw, hn, body_font, wide_w - 240)
            draw.text((ex, ey), f"• {hn}: {b['count']} ({b['pct']:.0f}%)", font=body_font, fill=text)
            ey += 28
    else:
        draw.text((ex, ey), "—", font=body_font, fill=text)

    # Footer
    foot = "Percentiles are against humans with ≥5 games. Accuracy shown only where session_hit_rate exists."
    draw.text((pad * 2, H - pad - 28), foot, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ------------------------------------------------------------------------------------------------------------
# Snapshot rows builder (no bars)
# ------------------------------------------------------------------------------------------------------------
def _profile_build_snapshot_rows(all_metrics: dict[int, dict], my: dict, *, enable_pct: bool) -> list[dict]:
    win_list = [v["win_pct"] for v in all_metrics.values()]
    kda_list = [v["kda"] for v in all_metrics.values()]
    dpg_list = [v["deaths_pg"] for v in all_metrics.values()]
    dmg_list = [v["dmg_pg"] for v in all_metrics.values()]
    heal_list = [v["heal_pg"] for v in all_metrics.values()]
    taken_list = [v["taken_pg"] for v in all_metrics.values()]
    fh_list = [v["fh_pg"] for v in all_metrics.values()]
    sk_list = [v["sk_pg"] for v in all_metrics.values()]
    acc_list = [v["acc"] for v in all_metrics.values() if v.get("acc") is not None]

    def pct(lst, value, hib=True):
        if not enable_pct:
            return None
        return _profile_percentile(lst, value, higher_is_better=hib)

    rows = [
        {"label": "Win %", "value_txt": f"{my['win_pct']:.1f}%", "pct": pct(win_list, my["win_pct"], True)},
        {"label": "KDA", "value_txt": f"{my['kda']:.2f}", "pct": pct(kda_list, my["kda"], True)},
        {"label": "Deaths / G", "value_txt": f"{my['deaths_pg']:.2f}", "pct": pct(dpg_list, my["deaths_pg"], False)},
        {"label": "Damage / G", "value_txt": f"{my['dmg_pg']:.0f}", "pct": pct(dmg_list, my["dmg_pg"], True)},
        {"label": "Healing / G", "value_txt": f"{my['heal_pg']:.0f}", "pct": pct(heal_list, my["heal_pg"], True)},
        {"label": "Taken / G", "value_txt": f"{my['taken_pg']:.0f}", "pct": pct(taken_list, my["taken_pg"], True)},
        {"label": "Final Hits / G", "value_txt": f"{my['fh_pg']:.2f}", "pct": pct(fh_list, my["fh_pg"], True)},
        {"label": "Solo Kills / G", "value_txt": f"{my['sk_pg']:.2f}", "pct": pct(sk_list, my["sk_pg"], True)},
    ]

    if my.get("acc") is None or not acc_list:
        rows.append({"label": "Accuracy", "value_txt": "—", "pct": None})
    else:
        rows.append({
            "label": "Accuracy",
            "value_txt": f"{my['acc']*100:.1f}%",
            "pct": pct(acc_list, my["acc"], True),
        })

    return rows


def _profile_collect_hero_ids(pack: dict) -> set[int]:
    ids = set()
    for h in pack.get("signature_heroes", []):
        ids.add(int(h["hero_id"]))
    for b in pack.get("enemy_bans", {}).get("top", []):
        ids.add(int(b["hero_id"]))
    for h in pack.get("teammate_hero_win", []):
        ids.add(int(h["hero_id"]))
    for h in pack.get("teammate_hero_risk", []):
        ids.add(int(h["hero_id"]))
    return ids


def _profile_pack_sync(season_id: int, player_uid: int) -> dict:
    totals = _profile_get_season_totals(season_id, player_uid)

    # Percentiles baseline: humans with ≥5 games
    all_metrics = _profile_get_all_player_metrics(season_id, min_games=5)
    my_acc = _profile_get_accuracy_by_player(season_id).get(int(player_uid))

    my_for_snapshot = {
        "win_pct": totals["win_pct"],
        "kda": totals["kda"],
        "deaths_pg": totals["deaths_pg"],
        "dmg_pg": totals["dmg_pg"],
        "heal_pg": totals["heal_pg"],
        "taken_pg": totals["taken_pg"],
        "fh_pg": totals["fh_pg"],
        "sk_pg": totals["sk_pg"],
        "acc": my_acc,
    }

    enable_pct = totals["games"] >= 5
    snapshot_rows = _profile_build_snapshot_rows(all_metrics, my_for_snapshot, enable_pct=enable_pct)

    hero_stats = _profile_get_hero_stats(season_id, player_uid)

    role_map = _profile_load_hero_roles()
    role_share, role_wr = _profile_get_role_mix_and_role_wr(season_id, player_uid, role_map)
    best_role = _profile_pick_best_role(role_wr, min_games=4)

    signature = _profile_signature_heroes_by_performance(hero_stats, min_games=5, limit=5)

    chem = _profile_get_chemistry(season_id, player_uid, min_games=4)

    teammate_win, teammate_risk = _profile_get_teammate_hero_wr_lists(
        season_id, player_uid, min_games=5, top_n=3
    )

    bans = _profile_get_enemy_bans(season_id, player_uid)

    seq = _profile_get_win_seq_by_import_time(season_id, player_uid)
    form10 = _profile_form_str(seq, 10)
    streak = _profile_current_streak(seq)

    momentum = _profile_get_momentum_last_n(season_id, player_uid, n=10)

    return {
        "season_id": int(season_id),
        "player_uid": int(player_uid),
        "totals": totals,
        "snapshot_rows": snapshot_rows,
        "role_share": role_share,
        "role_wr": role_wr,
        "best_role": best_role,
        "signature_heroes": signature,
        "chemistry": chem,
        "teammate_hero_win": teammate_win,
        "teammate_hero_risk": teammate_risk,
        "enemy_bans": bans,
        "momentum": momentum,
        "form10": form10,
        "streak_txt": _profile_streak_txt(streak),
        "hero_names": {},
    }


async def _build_profile_dashboard_image(season_id: int, player_uid: int) -> tuple[str, io.BytesIO]:
    player_name = _get_player_display_name(season_id, player_uid)

    # Avoid command-triggered API calls by default. Run !refresh_heroes manually when cache needs updating.
    if _allow_command_hero_cache_refresh():
        try:
            await refresh_hero_cache(force=False)
        except Exception:
            pass

    pack = _profile_pack_sync(season_id, player_uid)

    # Resolve hero names needed for rendering
    hero_ids = _profile_collect_hero_ids(pack)
    hero_names: dict[int, str] = {}
    if hero_ids:
        ordered = sorted(hero_ids)
        results = await asyncio.gather(*[get_hero_name(str(int(h))) for h in ordered], return_exceptions=True)
        for hid, res in zip(ordered, results):
            hero_names[int(hid)] = str(hid) if isinstance(res, Exception) else str(res)

    pack["hero_names"] = hero_names
    buf = _render_profile_dashboard(player_name, pack)
    return player_name, buf


# ============================================================================================================
# Command - Profile (single-image dashboard)
# ============================================================================================================
@bot.command(name="profile")
async def profile(ctx, *, player_name: Optional[str] = None):
    """
    Single-image scouting report per player (API-native).
      - !profile <name>  -> direct player lookup
      - !profile         -> dropdown (first 25 API humans)
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    async def send_profile_to_channel(uid: int):
        disp, buf = await _build_profile_dashboard_image(season_id, uid)
        fn_safe = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", disp)[:60] or f"UID_{uid}"
        await ctx.send(
            content=f"**{disp} — Season {season_id} Scouting Report**",
            file=discord.File(fp=buf, filename=f"profile_{fn_safe}_s{season_id}.png"),
        )

    # Direct player
    if player_name:
        uid = _resolve_player_uid(season_id, player_name)
        if uid is None:
            await ctx.send(
                "Couldn't find that player in the current season. Try `!profile` (no name) to pick from a list."
            )
            return
        await send_profile_to_channel(uid)
        return

    # Dropdown
    players = _get_api_players(season_id)
    if not players:
        await ctx.send(
            "No API-imported players found yet. Import matches first with `!submit_match ...`."
        )
        return

    opts = [
        discord.SelectOption(label=p["player"][:100], value=str(p["player_uid"]))
        for p in players[:25]
    ]

    class PlayerSelect(Select):
        def __init__(self):
            super().__init__(
                placeholder="Select a player…",
                min_values=1,
                max_values=1,
                options=opts,
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(thinking=True, ephemeral=False)
            uid = int(self.values[0])

            # Prefer interaction followup to satisfy the component flow
            disp, buf = await _build_profile_dashboard_image(season_id, uid)
            fn_safe = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", disp)[:60] or f"UID_{uid}"
            await interaction.followup.send(
                content=f"**{disp} — Season {season_id} Scouting Report**",
                file=discord.File(fp=buf, filename=f"profile_{fn_safe}_s{season_id}.png"),
            )

    view = View(timeout=60)
    view.add_item(PlayerSelect())

    extra = f"\n(Showing first 25 of {len(players)}. Use `!profile <name>` if needed.)" if len(players) > 25 else ""
    await ctx.send(
        f"Pick a player to view their Season {season_id} scouting report:{extra}",
        view=view,
    )

# ============================================================================================================
# Command - role_winrates
#   !role_winrates
#   !role_winrates <player name> <role>
#
# Examples:
#   !role_winrates
#   !role_winrates LatinMaestro duelist
#   !role_winrates "Nev Pounder" strategist
# ============================================================================================================

_ROLE_WR_ALLOWED = {
    "v": "Vanguard",
    "vang": "Vanguard",
    "vanguard": "Vanguard",
    "d": "Duelist",
    "duel": "Duelist",
    "duelist": "Duelist",
    "s": "Strategist",
    "strat": "Strategist",
    "strategist": "Strategist",
}
_ROLE_WR_ORDER = ["Vanguard", "Duelist", "Strategist"]


def _role_wr_clip(text: str, n: int) -> str:
    s = str(text or "")
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _role_wr_norm_role(role_text: str) -> Optional[str]:
    if not role_text:
        return None
    return _ROLE_WR_ALLOWED.get(str(role_text).strip().lower())


def _role_wr_line_height(font) -> int:
    try:
        box = font.getbbox("Ag")
        return int(box[3] - box[1])
    except Exception:
        return 18


def _role_wr_draw_centered_multiline(draw, x: int, y: int, w: int, h: int,
                                     text: str, font, fill, spacing: int = 2):
    lines = (str(text or "")).splitlines() or [""]
    lh = _role_wr_line_height(font)
    try:
        widths = [font.getlength(line) for line in lines]
    except Exception:
        widths = [len(line) * 10 for line in lines]

    total_h = int(lh * len(lines) + spacing * (len(lines) - 1))
    cur_y = y + max(0, (h - total_h) // 2)

    for line, lw in zip(lines, widths):
        cur_x = x + max(0, (w - int(lw)) // 2)
        draw.text((cur_x, cur_y), line, font=font, fill=fill)
        cur_y += lh + spacing


async def _role_wr_load_role_map() -> dict[int, str]:
    ensure_mr_api_tables()

    fn = globals().get("_ss_load_hero_roles_from_cache")
    role_map = fn() if callable(fn) else {}

    if not role_map and _allow_command_hero_cache_refresh():
        refresh_fn = globals().get("refresh_hero_cache")
        if callable(refresh_fn):
            try:
                await refresh_fn(force=True)
            except Exception:
                pass
        role_map = fn() if callable(fn) else {}

    if role_map:
        return {
            int(hid): str(role).strip()
            for hid, role in role_map.items()
            if str(role).strip() in _ROLE_WR_ORDER
        }

    out: dict[int, str] = {}
    try:
        c.execute("""
            SELECT hero_id, hero_role
            FROM hero_cache
            WHERE COALESCE(hero_role, '') <> ''
        """)
        for hid, role in (c.fetchall() or []):
            hid_s = str(hid or "").strip()
            hid_digits = _digits_only(hid_s) or hid_s
            try:
                hid_i = int(hid_digits)
            except Exception:
                continue
            role_s = str(role or "").strip()
            if role_s in _ROLE_WR_ORDER:
                out[hid_i] = role_s
    except Exception:
        return {}

    return out


async def _role_wr_collect_match_rows(season_id: int) -> list[dict]:
    ensure_mr_api_tables()
    role_map = await _role_wr_load_role_map()
    if not role_map:
        return []

    base_rows = load_role_segment_rows(c, season_id)
    if not base_rows:
        return []

    out_by_key: dict[tuple[str, int], dict] = {}

    for match_uid, game_label, player_uid, player, camp, is_win, hero_id, sec in base_rows:
        try:
            uid_i = int(player_uid)
        except Exception:
            continue

        match_key = str(match_uid or game_label or "").strip()
        if not match_key:
            continue

        hid_s = str(hero_id or "").strip()
        hid_digits = _digits_only(hid_s) or hid_s
        try:
            hid_i = int(hid_digits)
        except Exception:
            hid_i = None

        seconds = float(sec or 0.0)
        if seconds <= 0:
            continue

        key = (match_key, uid_i)
        row = out_by_key.get(key)
        if row is None:
            row = {
                "match_key": match_key,
                "match_uid": str(match_uid or "").strip(),
                "game_label": str(game_label or "").strip(),
                "player_uid": uid_i,
                "player": str(player or f"UID_{uid_i}"),
                "camp": _profile_norm_side(camp),
                "is_win": _safe_int(is_win, 0),
                "total_sec": 0.0,
                "role_sec": {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0},
            }
            out_by_key[key] = row

        row["total_sec"] += seconds

        role = role_map.get(hid_i) if hid_i is not None else None
        if role in _ROLE_WR_ORDER:
            row["role_sec"][role] += seconds

    return list(out_by_key.values())


def _role_wr_role_eligible(row: dict, role_name: str) -> bool:
    total_sec = float(row.get("total_sec", 0.0) or 0.0)
    role_sec = float((row.get("role_sec") or {}).get(role_name, 0.0) or 0.0)
    if total_sec <= 0 or role_sec <= 0:
        return False
    return (
        role_sec >= int(HERO_WIN_MIN_SECONDS)
        and (role_sec / total_sec) >= float(HERO_WIN_MIN_RATIO)
    )


def _role_wr_cell_text(wins: int, games: int) -> str:
    games_i = int(games or 0)
    wins_i = int(wins or 0)
    if games_i <= 0:
        return "—"
    return f"{(wins_i / games_i) * 100.0:.1f}% ({wins_i}/{games_i})"


def _role_wr_build_overall_rows(match_rows: list[dict]) -> list[dict]:
    agg = {}

    for row in match_rows:
        uid = int(row["player_uid"])
        rec = agg.get(uid)
        if rec is None:
            rec = {
                "player_uid": uid,
                "player": str(row.get("player") or f"UID_{uid}"),
                "Vanguard_wins": 0,
                "Vanguard_games": 0,
                "Duelist_wins": 0,
                "Duelist_games": 0,
                "Strategist_wins": 0,
                "Strategist_games": 0,
            }
            agg[uid] = rec

        rec["player"] = str(row.get("player") or rec["player"])

        for role_name in _ROLE_WR_ORDER:
            if _role_wr_role_eligible(row, role_name):
                rec[f"{role_name}_games"] += 1
                if _safe_int(row.get("is_win"), 0) == 1:
                    rec[f"{role_name}_wins"] += 1

    out = list(agg.values())
    out.sort(key=lambda r: str(r.get("player") or "").lower())
    return out


def _role_wr_build_teammate_rows(match_rows: list[dict],
                                 anchor_uid: int,
                                 anchor_role: str) -> list[dict]:
    anchor_uid = int(anchor_uid)

    by_team = defaultdict(list)
    anchor_matches = []

    for row in match_rows:
        camp = row.get("camp")
        if camp in (0, 1):
            by_team[(str(row["match_key"]), int(camp))].append(row)

        if int(row["player_uid"]) == anchor_uid and camp in (0, 1):
            if _role_wr_role_eligible(row, anchor_role):
                anchor_matches.append(row)

    if not anchor_matches:
        return []

    agg = {}

    for anchor_row in anchor_matches:
        team_rows = by_team.get((str(anchor_row["match_key"]), int(anchor_row["camp"])), [])
        for row in team_rows:
            uid = int(row["player_uid"])
            if uid == anchor_uid:
                continue

            rec = agg.get(uid)
            if rec is None:
                rec = {
                    "player_uid": uid,
                    "player": str(row.get("player") or f"UID_{uid}"),
                    "wins": 0,
                    "games": 0,
                }
                agg[uid] = rec

            rec["player"] = str(row.get("player") or rec["player"])
            rec["games"] += 1
            if _safe_int(row.get("is_win"), 0) == 1:
                rec["wins"] += 1

    out = list(agg.values())
    out.sort(
        key=lambda r: (
            int(r.get("games", 0)),
            (float(r.get("wins", 0)) / float(r.get("games", 1))) if int(r.get("games", 0)) > 0 else 0.0,
            str(r.get("player") or "").lower(),
        ),
        reverse=True,
    )
    return out


def _role_wr_render_overall_image(season_id: int, rows: list[dict]) -> io.BytesIO:
    pad = 26
    row_h = 34
    table_rows = max(1, len(rows))
    extra_h = 220

    W = 1900
    H = max(520, 210 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Role Win Rates — Season {season_id}"
    subtitle = (
        f"Eligible role games only • role ≥ {HERO_WIN_MIN_SECONDS}s and "
        f"≥ {int(HERO_WIN_MIN_RATIO * 100)}% of that player's match time"
    )

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 4.2)

    x_player = left_x
    x_v = left_x + 360
    x_d = left_x + 840
    x_s = left_x + 1320

    headers = [
        (x_player, "Player"),
        (x_v, "Vanguard"),
        (x_d, "Duelist"),
        (x_s, "Strategist"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        player_txt = _role_wr_clip(str(r.get("player", "")), 22)
        v_txt = _role_wr_cell_text(
            int(r.get("Vanguard_wins", 0)),
            int(r.get("Vanguard_games", 0)),
        )
        d_txt = _role_wr_cell_text(
            int(r.get("Duelist_wins", 0)),
            int(r.get("Duelist_games", 0)),
        )
        s_txt = _role_wr_cell_text(
            int(r.get("Strategist_wins", 0)),
            int(r.get("Strategist_games", 0)),
        )

        draw.text((x_player, y), player_txt, font=body_font, fill=text)
        draw.text((x_v, y), v_txt, font=body_font, fill=text)
        draw.text((x_d, y), d_txt, font=body_font, fill=text)
        draw.text((x_s, y), s_txt, font=body_font, fill=text)

        # subtle row divider like the cleaner themed outputs
        draw.line([(x_player, y + row_h - 6), (W - pad * 2, y + row_h - 6)], fill=(58, 58, 76), width=1)

        y += row_h

    footer = (
        "Win rates shown as percentage with wins/games in brackets. "
        "Only eligible role appearances are counted."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _role_wr_render_teammate_image(
    season_id: int,
    anchor_player: str,
    anchor_role: str,
    rows: list[dict]
) -> io.BytesIO:
    pad = 26
    row_h = 34
    table_rows = max(1, len(rows))
    extra_h = 220

    W = 1450
    H = max(500, 210 + (table_rows * row_h) + extra_h)

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        body_font, title_font = get_fonts()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    title = f"Teammates with {anchor_player} on {anchor_role} — Season {season_id}"
    subtitle = (
        f"Counts only matches where {anchor_player} was eligible on {anchor_role}"
    )

    draw.text((pad * 2, int(pad * 1.35)), title, font=title_font, fill=accent)
    draw.text((pad * 2, int(pad * 2.7)), subtitle, font=body_font, fill=muted)

    left_x = pad * 2
    y = int(pad * 4.2)

    x_player = left_x
    x_wins = left_x + 520
    x_games = left_x + 700
    x_wr = left_x + 900

    headers = [
        (x_player, "Player"),
        (x_wins, "Wins"),
        (x_games, "Games"),
        (x_wr, "Win%"),
    ]
    for x, label in headers:
        draw.text((x, y), label, font=body_font, fill=muted)

    y += 28
    draw.line([(pad * 2, y), (W - pad * 2, y)], fill=line, width=2)
    y += 14

    for r in rows:
        wins = int(r.get("wins", 0))
        games = int(r.get("games", 0))
        wr = (wins / games) * 100.0 if games > 0 else 0.0

        draw.text((x_player, y), _role_wr_clip(str(r.get("player", "")), 26), font=body_font, fill=text)
        draw.text((x_wins, y), str(wins), font=body_font, fill=text)
        draw.text((x_games, y), str(games), font=body_font, fill=text)
        draw.text((x_wr, y), f"{wr:.1f}%", font=body_font, fill=text)

        draw.line([(x_player, y + row_h - 6), (W - pad * 2, y + row_h - 6)], fill=(58, 58, 76), width=1)

        y += row_h

    footer = (
        f"Eligibility: {anchor_role} must reach at least {HERO_WIN_MIN_SECONDS}s "
        f"and {int(HERO_WIN_MIN_RATIO * 100)}% of {anchor_player}'s match time."
    )
    draw.text((left_x, H - pad - 58), footer, font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@bot.command(name="role_winrates", aliases=["role_wr", "player_role_wr"])
async def role_winrates(ctx, *, arg: Optional[str] = None):
    """
    Usage:
      !role_winrates
      !role_winrates <player name> <role>

    Examples:
      !role_winrates
      !role_winrates LatinMaestro duelist
      !role_winrates Nev Pounder strategist
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    match_rows = await _role_wr_collect_match_rows(season_id)
    if not match_rows:
        await ctx.send(
            "No role win-rate data available yet.\n"
            "Ensure matches are imported and hero roles exist in hero_cache (`!refresh_heroes` / `!hero_role_set`)."
        )
        return

    # Option 1: no args -> table of every player with V/D/S win rates
    if not arg or not str(arg).strip():
        rows = _role_wr_build_overall_rows(match_rows)
        if not rows:
            await ctx.send("No eligible role data found for the current season.")
            return

        buf = _role_wr_render_overall_image(season_id, rows)
        await ctx.send(file=discord.File(fp=buf, filename=f"role_winrates_s{season_id}.png"))
        return

    # Option 2: player + role -> teammate table
    raw = str(arg).strip()
    player_part = None
    role_name = None

    # allow "player, role" as well as "player role"
    if "," in raw:
        a, b = raw.rsplit(",", 1)
        player_part = a.strip()
        role_name = _role_wr_norm_role(b.strip())
    else:
        parts = raw.rsplit(" ", 1)
        if len(parts) == 2:
            player_part = parts[0].strip()
            role_name = _role_wr_norm_role(parts[1].strip())

    if not player_part or role_name is None:
        await ctx.send(
            "Usage:\n"
            "`!role_winrates`\n"
            "`!role_winrates <player name> <vanguard|duelist|strategist>`"
        )
        return

    player_uid = _resolve_player_uid(season_id, player_part)
    if player_uid is None:
        await ctx.send(
            "Couldn't find that player in the current season. "
            "Use the exact current-season name shown in your other commands."
        )
        return

    anchor_player = _get_player_display_name(season_id, int(player_uid))
    rows = _role_wr_build_teammate_rows(match_rows, int(player_uid), role_name)
    if not rows:
        await ctx.send(
            f"No eligible teammate data found for **{anchor_player}** on **{role_name}** "
            f"in Season {season_id}."
        )
        return

    buf = _role_wr_render_teammate_image(season_id, anchor_player, role_name, rows)
    await ctx.send(
        file=discord.File(
            fp=buf,
            filename=f"role_winrates_{norm_key(anchor_player)}_{role_name.lower()}_s{season_id}.png",
        )
    )

# ============================================================================================================
# Head-to-Head Matchup Command (UI picker + sports-style matchup card)
#
# Command: !h2h  (aliases: !head2head, !head_to_head)
#
# DEFAULT (no hero selected on either side):
#   - TRUE HEAD-TO-HEAD ONLY: stats calculated ONLY from matches where both selected players are OPPONENTS.
#
# HERO COMPARISONS:
#   - Two independent hero dropdowns (one under each player):
#       * Each dropdown lists ONLY heroes that player has eligibly played
#       * Allows cross-hero comparisons (Hero A vs Hero B)
#       * If a side hero is left as "Overall", that side uses opponent-only H2H stats
#   - Hero comparison table includes:
#       * Win %, Games, Avg KDA, K/D/A per game, Time, Time per game, Accuracy
#       * Damage / game, Healing / game, Damage Taken / game
#     Note: hero damage/heal/taken are summed from mr_player_match across matches where the hero is eligible
#           (i.e., matches where the player was primarily on that hero by the eligibility thresholds).
#
# Layout:
#   - Table pushed down to avoid header overlap
#   - Footer wraps within each column (no cross-over)
#
# Dependencies expected to exist elsewhere in main.py:
#   bot, c (sqlite cursor)
#   ensure_mr_api_tables(), get_current_season_id()
#   _get_all_players(), _uid_from_pkey(), _get_player_display_name()
#   _top_heroes(), _badge_signature()
#   get_hero_name(hero_id_str), get_fonts(body_pt, title_pt)
#   HERO_WIN_MIN_SECONDS, HERO_WIN_MIN_RATIO
#   _ss_table_exists(name), _ss_col_exists(table, col)
# ============================================================================================================

import io
import re
import math
from collections import defaultdict

import discord

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None

# Avoid duplicate command registration during iterative dev
try:
    bot.remove_command("h2h")
except Exception:
    pass


# -----------------------------
# Small helpers
# -----------------------------
def _h2h_safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _h2h_safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def _h2h_canon_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _h2h_draw_text_bold(draw, xy, text, font, fill, bold=False):
    x, y = xy
    if not bold:
        draw.text((x, y), text, font=font, fill=fill)
        return
    for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        draw.text((x + dx, y + dy), text, font=font, fill=fill)


def _h2h_text_wh(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        try:
            return draw.textsize(text, font=font)
        except Exception:
            return (len(str(text)) * 10, 20)


def _h2h_wrap_text_lines(draw, text, font, max_width: int):
    if not text:
        return ["—"]

    words = str(text).split()
    lines = []
    cur = ""

    def fits(s: str) -> bool:
        w, _ = _h2h_text_wh(draw, s, font)
        return w <= max_width

    for w in words:
        trial = w if not cur else f"{cur} {w}"
        if fits(trial):
            cur = trial
            continue

        if cur:
            lines.append(cur)
            cur = ""

        if not fits(w):
            chunk = ""
            for ch in w:
                t2 = chunk + ch
                if fits(t2):
                    chunk = t2
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            if chunk:
                cur = chunk
        else:
            cur = w

    if cur:
        lines.append(cur)

    return lines if lines else ["—"]


def _h2h_fmt_pct(v) -> str:
    return "—" if v is None else f"{float(v):.1f}%"


def _h2h_fmt_num(v) -> str:
    if v is None:
        return "—"
    try:
        fv = float(v)
        if fv.is_integer():
            return str(int(fv))
        return f"{fv:.2f}"
    except Exception:
        return str(v)


# -----------------------------
# TRUE H2H opponent matches (match_uid list)
# -----------------------------
def _h2h_get_opponent_match_uids(season_id: int, uid_a: int, uid_b: int) -> list[str]:
    """Returns match_uids where BOTH players played and were OPPONENTS (is_win differs)."""
    ensure_mr_api_tables()
    return get_opponent_match_uids(c, season_id, uid_a, uid_b)


def _h2h_get_player_totals_in_matches(season_id: int, player_uid: int, match_uids: list[str]) -> dict:
    """Totals restricted to provided match_uids (opponents-only H2H)."""
    ensure_mr_api_tables()
    if not match_uids:
        return {"games": 0, "wins": 0, "losses": 0, "kills": 0, "deaths": 0, "assists": 0, "dmg": 0, "heal": 0, "taken": 0}

    r = load_player_totals(c, season_id, player_uid, match_uids)

    games, wins, losses, k, d, a, dmg, heal, taken = r
    return {
        "games": _h2h_safe_int(games, 0),
        "wins": _h2h_safe_int(wins, 0),
        "losses": _h2h_safe_int(losses, 0),
        "kills": _h2h_safe_int(k, 0),
        "deaths": _h2h_safe_int(d, 0),
        "assists": _h2h_safe_int(a, 0),
        "dmg": int(_h2h_safe_float(dmg, 0.0)),
        "heal": int(_h2h_safe_float(heal, 0.0)),
        "taken": int(_h2h_safe_float(taken, 0.0)),
    }


def _h2h_get_accuracy_in_matches(season_id: int, player_uid: int, match_uids: list[str]) -> float | None:
    """Weighted accuracy restricted to match_uids."""
    ensure_mr_api_tables()
    if not match_uids:
        return None
    try:
        r = load_accuracy_components(c, season_id, player_uid, match_uids)
        num = _h2h_safe_float(r[0], 0.0)
        den = _h2h_safe_float(r[1], 0.0)
        return (num / den) if den > 0 else None
    except Exception:
        return None

def _h2h_get_final_hits_solo_kills_in_matches(season_id: int, player_uid: int, match_uids: list[str]) -> dict:
    """Totals for Final Hits + Solo Kills restricted to match_uids (summing across hero segments)."""
    ensure_mr_api_tables()
    ensure_mr_hero_segments_fhsk_cols()

    if not match_uids:
        return {"final_hits": 0, "solo_kills": 0}

    ph = ",".join(["?"] * len(match_uids))
    sql = f"""
        SELECT
            SUM(COALESCE(final_hits,0)) AS final_hits,
            SUM(COALESCE(solo_kills,0)) AS solo_kills
        FROM mr_hero_segments
        WHERE season_id=?
          AND player_uid=?
          AND is_bot=0
          AND match_uid IN ({ph})
    """
    args = [int(season_id), int(player_uid)] + [str(m) for m in match_uids]
    try:
        c.execute(sql, tuple(args))
        r = c.fetchone() or (0, 0)
        return {"final_hits": _h2h_safe_int(r[0], 0), "solo_kills": _h2h_safe_int(r[1], 0)}
    except Exception:
        return {"final_hits": 0, "solo_kills": 0}


def _h2h_get_total_seconds_in_matches(season_id: int, player_uid: int, match_uids: list[str]) -> int:
    """Total seconds (sum of all hero segments) restricted to match_uids."""
    ensure_mr_api_tables()
    if not match_uids:
        return 0
    ph = ",".join(["?"] * len(match_uids))
    sql = f"""
        SELECT SUM(COALESCE(seconds,0))
        FROM mr_hero_segments
        WHERE season_id=?
          AND player_uid=?
          AND is_bot=0
          AND match_uid IN ({ph})
    """
    args = [int(season_id), int(player_uid)] + [str(m) for m in match_uids]
    try:
        c.execute(sql, tuple(args))
        r = c.fetchone()
        return int(_h2h_safe_float((r[0] if r else 0), 0.0))
    except Exception:
        return 0


def _h2h_get_hero_pool_in_matches(season_id: int, player_uid: int, match_uids: list[str]) -> int:
    """Distinct heroes used restricted to match_uids."""
    ensure_mr_api_tables()
    if not match_uids:
        return 0
    ph = ",".join(["?"] * len(match_uids))
    sql = f"""
        SELECT COUNT(DISTINCT hero_id)
        FROM mr_hero_segments
        WHERE season_id=?
          AND player_uid=?
          AND is_bot=0
          AND match_uid IN ({ph})
    """
    args = [int(season_id), int(player_uid)] + [str(m) for m in match_uids]
    try:
        c.execute(sql, tuple(args))
        r = c.fetchone()
        return _h2h_safe_int((r[0] if r else 0), 0)
    except Exception:
        return 0


def _h2h_get_mvp_svp(season_id: int, player_uid: int, match_uids: list[str] | None = None) -> tuple[int, int]:
    """MVP/SVP counts; if match_uids provided, restricts to those matches."""
    ensure_mr_api_tables()
    if match_uids is None:
        try:
            c.execute(
                """
                SELECT
                    SUM(CASE WHEN mm.mvp_uid=? THEN 1 ELSE 0 END) as mvp_ct,
                    SUM(CASE WHEN mm.svp_uid=? THEN 1 ELSE 0 END) as svp_ct
                FROM mr_match_meta mm
                JOIN mr_player_match pm
                  ON pm.season_id=mm.season_id AND pm.match_uid=mm.match_uid
                WHERE mm.season_id=? AND pm.player_uid=? AND pm.is_bot=0
                """,
                (int(player_uid), int(player_uid), int(season_id), int(player_uid)),
            )
            r = c.fetchone()
            return (_h2h_safe_int(r[0], 0), _h2h_safe_int(r[1], 0)) if r else (0, 0)
        except Exception:
            return (0, 0)

    if not match_uids:
        return (0, 0)

    ph = ",".join(["?"] * len(match_uids))
    sql = f"""
        SELECT
            SUM(CASE WHEN mvp_uid=? THEN 1 ELSE 0 END) as mvp_ct,
            SUM(CASE WHEN svp_uid=? THEN 1 ELSE 0 END) as svp_ct
        FROM mr_match_meta
        WHERE season_id=?
          AND match_uid IN ({ph})
    """
    args = [int(player_uid), int(player_uid), int(season_id)] + [str(m) for m in match_uids]
    try:
        c.execute(sql, tuple(args))
        r = c.fetchone()
        return (_h2h_safe_int(r[0], 0), _h2h_safe_int(r[1], 0)) if r else (0, 0)
    except Exception:
        return (0, 0)


# -----------------------------
# Pair record (opponents + teammates)
# -----------------------------
def _h2h_get_pair_records(season_id: int, uid_a: int, uid_b: int) -> dict:
    ensure_mr_api_tables()
    c.execute(
        """
        SELECT match_uid, player_uid, is_win
        FROM mr_player_match
        WHERE season_id=? AND is_bot=0 AND player_uid IN (?, ?)
        """,
        (int(season_id), int(uid_a), int(uid_b)),
    )

    per_match = defaultdict(dict)
    for mu, pu, w in c.fetchall() or []:
        if mu is None or pu is None:
            continue
        try:
            per_match[str(mu)][int(pu)] = int(w) if w is not None else 0
        except Exception:
            continue

    opp_games = 0
    a_wins = 0
    b_wins = 0
    duo_games = 0
    duo_wins = 0
    duo_losses = 0

    for _mu, d in per_match.items():
        if uid_a not in d or uid_b not in d:
            continue
        wa = int(d[uid_a])
        wb = int(d[uid_b])

        if wa == wb:
            duo_games += 1
            if wa == 1:
                duo_wins += 1
            else:
                duo_losses += 1
        else:
            opp_games += 1
            if wa == 1:
                a_wins += 1
            else:
                b_wins += 1

    return {"opp_games": opp_games, "a_wins": a_wins, "b_wins": b_wins, "duo_games": duo_games, "duo_wins": duo_wins, "duo_losses": duo_losses}


# -----------------------------
# Low-team + Versatility (season context)
# -----------------------------
def _h2h_get_low_team_metrics_for_players(season_id: int, uid_to_name: dict[int, str]) -> dict[int, dict]:
    c.execute("SELECT game_label, player, win FROM game_stats_v")
    rows = c.fetchall() or []
    if not rows:
        return {uid: {"on_less": 0, "uneven": 0, "pct_on_less": None, "winpct_on_less": None} for uid in uid_to_name}

    games = defaultdict(lambda: {"1": set(), "0": set()})
    for game_label, player, win in rows:
        if game_label is None or player is None:
            continue
        key = _h2h_canon_name(str(player))
        if not key:
            continue
        games[str(game_label)][str(int(win or 0))].add(key)

    low_team_counts = defaultdict(int)
    uneven_game_counts = defaultdict(int)
    low_team_win_counts = defaultdict(int)

    for _label, teams in games.items():
        win_team = teams["1"]
        loss_team = teams["0"]
        if not win_team or not loss_team:
            continue
        if len(win_team) == len(loss_team):
            continue

        for p in win_team.union(loss_team):
            uneven_game_counts[p] += 1

        if len(win_team) < len(loss_team):
            smaller = win_team
            smaller_won = True
        else:
            smaller = loss_team
            smaller_won = False

        for p in smaller:
            low_team_counts[p] += 1
            if smaller_won:
                low_team_win_counts[p] += 1

    out = {}
    for uid, name in uid_to_name.items():
        key = _h2h_canon_name(name)
        low = int(low_team_counts.get(key, 0))
        unev = int(uneven_game_counts.get(key, 0))
        wless = int(low_team_win_counts.get(key, 0))

        if unev <= 0:
            out[uid] = {"on_less": low, "uneven": unev, "pct_on_less": None, "winpct_on_less": None}
            continue

        pct_on_less = (low / unev * 100.0) if unev > 0 else 0.0
        winpct_on_less = (wless / low * 100.0) if low > 0 else 0.0
        out[uid] = {"on_less": low, "uneven": unev, "pct_on_less": float(pct_on_less), "winpct_on_less": float(winpct_on_less)}
    return out


def _h2h_get_versatility_for_players(season_id: int, uids: list[int]) -> dict[int, dict]:
    ensure_mr_api_tables()
    if not uids:
        return {}
    if not _ss_table_exists("mr_hero_segments"):
        return {int(uid): {"vers_pct": None, "eligible_heroes": 0} for uid in uids}
    if not (_ss_table_exists("mr_player_match") and _ss_col_exists("mr_player_match", "is_bot")):
        return {int(uid): {"vers_pct": None, "eligible_heroes": 0} for uid in uids}

    sql_counts = """
    WITH hs AS (
        SELECT season_id, match_uid, game_label, player_uid, hero_id, COALESCE(seconds,0) AS seconds
        FROM mr_hero_segments
        WHERE season_id = ?
    ),
    match_tot AS (
        SELECT season_id, match_uid, game_label, player_uid, SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    joined AS (
        SELECT hs.player_uid, hs.hero_id, hs.seconds, mt.total_sec
        FROM hs
        JOIN match_tot mt
          ON mt.season_id  = hs.season_id
         AND mt.match_uid  = hs.match_uid
         AND mt.game_label = hs.game_label
         AND mt.player_uid = hs.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE COALESCE(pm.is_bot,0) = 0
    ),
    elig AS (
        SELECT player_uid, hero_id, seconds
        FROM joined
        WHERE seconds >= ?
          AND total_sec > 0
          AND (1.0 * seconds / total_sec) >= ?
    )
    SELECT player_uid, COUNT(DISTINCT hero_id) AS k
    FROM elig
    GROUP BY player_uid
    """
    try:
        c.execute(sql_counts, (int(season_id), int(HERO_WIN_MIN_SECONDS), float(HERO_WIN_MIN_RATIO)))
        counts = c.fetchall() or []
    except Exception:
        counts = []

    k_max = 0
    for _uid, k in counts:
        try:
            k_max = max(k_max, int(k or 0))
        except Exception:
            pass

    if k_max <= 1:
        return {int(uid): {"vers_pct": None, "eligible_heroes": 0} for uid in uids}

    placeholders = ",".join(["?"] * len(uids))
    sql_secs = f"""
    WITH hs AS (
        SELECT season_id, match_uid, game_label, player_uid, hero_id, COALESCE(seconds,0) AS seconds
        FROM mr_hero_segments
        WHERE season_id = ?
    ),
    match_tot AS (
        SELECT season_id, match_uid, game_label, player_uid, SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    joined AS (
        SELECT hs.player_uid, hs.hero_id, hs.seconds, mt.total_sec
        FROM hs
        JOIN match_tot mt
          ON mt.season_id  = hs.season_id
         AND mt.match_uid  = hs.match_uid
         AND mt.game_label = hs.game_label
         AND mt.player_uid = hs.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE COALESCE(pm.is_bot,0) = 0
    ),
    elig AS (
        SELECT player_uid, hero_id, seconds
        FROM joined
        WHERE seconds >= ?
          AND total_sec > 0
          AND (1.0 * seconds / total_sec) >= ?
    )
    SELECT player_uid, hero_id, SUM(seconds) AS sec_elig
    FROM elig
    WHERE player_uid IN ({placeholders})
    GROUP BY player_uid, hero_id
    HAVING sec_elig > 0
    """
    args = [int(season_id), int(HERO_WIN_MIN_SECONDS), float(HERO_WIN_MIN_RATIO)] + [int(u) for u in uids]
    try:
        c.execute(sql_secs, tuple(args))
        rows = c.fetchall() or []
    except Exception:
        rows = []

    tmp = defaultdict(lambda: defaultdict(int))
    for uid, hid, sec in rows:
        if uid is None or hid is None:
            continue
        s = int(float(sec or 0))
        if s <= 0:
            continue
        tmp[int(uid)][int(hid)] += s

    out = {}
    for uid in uids:
        uid_i = int(uid)
        hero_map = tmp.get(uid_i, {})
        secs = [int(s) for s in hero_map.values() if int(s) > 0]
        K = len(secs)
        total = sum(secs)

        if K < 2 or total <= 0:
            out[uid_i] = {"vers_pct": None, "eligible_heroes": int(K)}
            continue

        probs = [s / total for s in secs]
        H = -sum(p * math.log(max(p, 1e-12)) for p in probs)
        Hmax = math.log(K)
        evenness = (H / Hmax) if Hmax > 0 else 0.0
        breadth = K / k_max
        score = 100.0 * evenness * breadth

        out[uid_i] = {"vers_pct": float(score), "eligible_heroes": int(K)}
    return out


# -----------------------------
# Eligible hero lists + hero totals (eligible) with dmg/heal/taken
# -----------------------------
def _h2h_get_player_eligible_heroes(season_id: int, player_uid: int, limit: int = 24) -> list[dict]:
    """
    Returns heroes the player has eligibly played, sorted by eligible seconds desc:
      [{ "hero_id": int, "sec_total": int }]
    Eligibility per match:
      seconds >= HERO_WIN_MIN_SECONDS AND seconds/total_sec >= HERO_WIN_MIN_RATIO
    """
    ensure_mr_api_tables()
    if not _ss_table_exists("mr_hero_segments"):
        return []
    if not (_ss_table_exists("mr_player_match") and _ss_col_exists("mr_player_match", "is_bot")):
        return []

    sql = """
    WITH hs AS (
        SELECT season_id, match_uid, game_label, player_uid, hero_id, COALESCE(seconds,0) AS seconds
        FROM mr_hero_segments
        WHERE season_id = ?
          AND player_uid = ?
    ),
    match_tot AS (
        SELECT season_id, match_uid, game_label, player_uid, SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    joined AS (
        SELECT hs.hero_id, hs.seconds, mt.total_sec
        FROM hs
        JOIN match_tot mt
          ON mt.season_id  = hs.season_id
         AND mt.match_uid  = hs.match_uid
         AND mt.game_label = hs.game_label
         AND mt.player_uid = hs.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE COALESCE(pm.is_bot,0) = 0
    ),
    elig AS (
        SELECT hero_id, seconds
        FROM joined
        WHERE seconds >= ?
          AND total_sec > 0
          AND (1.0 * seconds / total_sec) >= ?
    )
    SELECT hero_id, SUM(seconds) AS sec_elig
    FROM elig
    GROUP BY hero_id
    HAVING sec_elig > 0
    ORDER BY sec_elig DESC, hero_id ASC
    """
    try:
        c.execute(sql, (int(season_id), int(player_uid), int(HERO_WIN_MIN_SECONDS), float(HERO_WIN_MIN_RATIO)))
        rows = c.fetchall() or []
    except Exception:
        return []

    out = []
    for hid, sec in rows:
        if hid is None:
            continue
        out.append({"hero_id": int(hid), "sec_total": int(_h2h_safe_float(sec, 0.0))})

    return out[: max(0, int(limit))]


# ============================================================================================================
# H2H Hero Compare — Final Hits / G + Solo Kills / G (allocated per hero; supports multi-hero matches)
#
# Why allocation is required:
#   The match API returns final_hits + solo_kill at the player-match level, not per-hero segment.
#   The per-hero list (player_heroes) can contain multiple heroes, so we allocate totals across heroes
#   by KILL share (preferred) then TIME share.
#
# ============================================================================================================

import json
import sqlite3

def ensure_mr_player_match_fhsk_cols():
    """Adds final_hits + solo_kill to mr_player_match if missing (safe migration)."""
    ensure_mr_api_tables()

    def _col_exists(table: str, col: str) -> bool:
        try:
            c.execute(f"PRAGMA table_info({table})")
            return any(str(r[1]).lower() == col.lower() for r in (c.fetchall() or []))
        except Exception:
            return False

    try:
        if not _col_exists("mr_player_match", "final_hits"):
            c.execute("ALTER TABLE mr_player_match ADD COLUMN final_hits INTEGER")
        if not _col_exists("mr_player_match", "solo_kill"):
            c.execute("ALTER TABLE mr_player_match ADD COLUMN solo_kill INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        # if columns already exist in some form, ignore
        pass


def ensure_mr_hero_segments_fhsk_cols():
    """Adds final_hits + solo_kills to mr_hero_segments if missing (safe migration)."""
    ensure_mr_api_tables()

    def _col_exists(table: str, col: str) -> bool:
        try:
            c.execute(f"PRAGMA table_info({table})")
            return any(str(r[1]).lower() == col.lower() for r in (c.fetchall() or []))
        except Exception:
            return False

    try:
        if not _col_exists("mr_hero_segments", "final_hits"):
            c.execute("ALTER TABLE mr_hero_segments ADD COLUMN final_hits REAL")
        if not _col_exists("mr_hero_segments", "solo_kills"):
            c.execute("ALTER TABLE mr_hero_segments ADD COLUMN solo_kills REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def _h2h_pull_fhsk_from_raw(season_id: int, match_uid: str, player_uid: int) -> tuple[int | None, int | None]:
    """
    Fallback: extract final_hits + solo_kill from stored raw JSON.
    Returns (final_hits, solo_kill) or (None, None) if not found.
    """
    try:
        c.execute(
            "SELECT json_text FROM mr_match_json_raw WHERE season_id=? AND match_uid=? LIMIT 1",
            (int(season_id), str(match_uid)),
        )
        row = c.fetchone()
        if not row or not row[0]:
            return (None, None)

        payload = json.loads(row[0])

        # Usually: payload["match_details"]["match_players"]
        md = payload.get("match_details") or payload.get("match") or {}
        players = md.get("match_players") or payload.get("match_players") or []

        for p in players:
            try:
                if int(p.get("player_uid")) != int(player_uid):
                    continue
            except Exception:
                continue

            fh = p.get("final_hits")
            sk = p.get("solo_kill")
            fh_i = int(fh) if fh is not None else None
            sk_i = int(sk) if sk is not None else None
            return (fh_i, sk_i)

    except Exception:
        return (None, None)

    return (None, None)


def _h2h_get_hero_totals_eligible(
    season_id_int: int,
    player_uid: int,
    hero_id: int,
    *,
    min_seconds: float = 60.0,
    min_share: float = 0.25
) -> dict:
    """
    Returns hero-filtered totals for a player, only counting matches where the hero is "eligible":
      - seconds >= min_seconds
      - seconds >= min_share * total_seconds_played_across_all_heroes_that_match

    Uses per-hero D/H/T when present (mr_hero_segments columns); otherwise allocates match totals by TIME share.
    Adds:
      - final_hits (allocated per hero by KILL share, then TIME share)
      - solo_kills (allocated per hero by KILL share, then TIME share)
    """
    ensure_mr_hero_segments_dht_cols()
    ensure_mr_player_match_fhsk_cols()
    ensure_mr_hero_segments_fhsk_cols()

    # Pull eligible hero segment rows + totals (seconds + kills) for share calculations
    c.execute(
        """
        WITH hs AS (
            SELECT
                match_uid,
                game_label,
                hero_id,
                seconds,
                kills, deaths, assists,
                session_hit_rate,
                hero_damage, hero_heal, hero_damage_taken,
                final_hits, solo_kills
            FROM mr_hero_segments
            WHERE season_id = ?
              AND player_uid = ?
              AND is_bot = 0
        ),
        tot AS (
            SELECT
                match_uid,
                SUM(COALESCE(seconds,0)) AS total_sec,
                SUM(COALESCE(kills,0))   AS total_kills
            FROM hs
            GROUP BY match_uid
        )
        SELECT
            hs.match_uid,
            hs.game_label,
            COALESCE(hs.seconds,0) AS seconds,
            COALESCE(hs.kills,0) AS kills,
            COALESCE(hs.deaths,0) AS deaths,
            COALESCE(hs.assists,0) AS assists,
            hs.session_hit_rate,
            COALESCE(tot.total_sec,0) AS total_sec,
            COALESCE(tot.total_kills,0) AS total_kills,
            hs.hero_damage,
            hs.hero_heal,
            hs.hero_damage_taken,
            hs.final_hits,
            hs.solo_kills
        FROM hs
        JOIN tot ON tot.match_uid = hs.match_uid
        WHERE hs.hero_id = ?
          AND COALESCE(hs.seconds,0) >= ?
          AND COALESCE(hs.seconds,0) >= (COALESCE(tot.total_sec,0) * ?)
        """,
        (int(season_id_int), int(player_uid), int(hero_id), float(min_seconds), float(min_share))
    )
    seg_rows = c.fetchall() or []

    if not seg_rows:
        return {
            "games": 0, "wins": 0, "losses": 0,
            "seconds": 0.0,
            "kills": 0, "deaths": 0, "assists": 0,
            "acc_num": 0.0, "acc_den": 0.0,
            "dmg": 0.0, "heal": 0.0, "taken": 0.0,
            "final_hits": 0.0,
            "solo_kills": 0.0,
        }

    uniq_match_uids = sorted({str(r[0]) for r in seg_rows})

    # Fetch match-level win + totals for proportional fallback (only for eligible matches)
    ph = ",".join(["?"] * len(uniq_match_uids))
    c.execute(
        f"""
        SELECT
            match_uid,
            is_win,
            total_hero_damage,
            total_hero_heal,
            total_damage_taken,
            final_hits,
            solo_kill
        FROM mr_player_match
        WHERE season_id = ?
          AND player_uid = ?
          AND is_bot = 0
          AND match_uid IN ({ph})
        """,
        [int(season_id_int), int(player_uid), *uniq_match_uids]
    )
    pm = {}
    for (mu, is_win, dmg, heal, taken, fh, sk) in (c.fetchall() or []):
        pm[str(mu)] = (
            int(is_win or 0),
            (float(dmg) if dmg is not None else None),
            (float(heal) if heal is not None else None),
            (float(taken) if taken is not None else None),
            (int(fh) if fh is not None else None),
            (int(sk) if sk is not None else None),
        )

    wins = sum(1 for mu in uniq_match_uids if pm.get(mu, (0, None, None, None, None, None))[0] == 1)
    losses = len(uniq_match_uids) - wins

    seconds_total = 0.0
    kills_total = 0
    deaths_total = 0
    assists_total = 0
    acc_num = 0.0
    acc_den = 0.0

    dmg_total = 0.0
    heal_total = 0.0
    taken_total = 0.0

    final_hits_total = 0.0
    solo_kills_total = 0.0

    # Cache raw FH/SK lookups per match (only if needed)
    raw_fhsk_cache: dict[str, tuple[int | None, int | None]] = {}

    for (
        mu, gl, sec, k, d, a, acc,
        total_sec, total_kills,
        seg_dmg, seg_heal, seg_taken,
        seg_fh, seg_sk
    ) in seg_rows:
        mu = str(mu)
        sec = float(sec or 0.0)
        k_i = int(k or 0)
        total_sec = float(total_sec or 0.0)
        total_kills = float(total_kills or 0.0)

        seconds_total += sec
        kills_total += k_i
        deaths_total += int(d or 0)
        assists_total += int(a or 0)

        # Accuracy weighted by time
        if acc is not None:
            try:
                acc_f = float(acc)
                acc_num += acc_f * sec
                acc_den += sec
            except Exception:
                pass

        # Preferred: per-hero D/H/T
        if (seg_dmg is not None) or (seg_heal is not None) or (seg_taken is not None):
            dmg_total += float(seg_dmg or 0.0)
            heal_total += float(seg_heal or 0.0)
            taken_total += float(seg_taken or 0.0)
        else:
            # Fallback: allocate match totals proportionally by TIME share on this hero
            is_win, pm_dmg, pm_heal, pm_taken, pm_fh, pm_sk = pm.get(mu, (0, None, None, None, None, None))
            share_time = (sec / total_sec) if total_sec > 0 else 0.0
            dmg_total += (pm_dmg or 0.0) * share_time
            heal_total += (pm_heal or 0.0) * share_time
            taken_total += (pm_taken or 0.0) * share_time

        # Final hits / Solo kills:
        # Preferred: per-hero stored values (if you later backfill/populate them)
        if (seg_fh is not None) or (seg_sk is not None):
            final_hits_total += float(seg_fh or 0.0)
            solo_kills_total += float(seg_sk or 0.0)
        else:
            # Fallback: allocate match-level FH/SK by KILL share, then TIME share
            is_win, pm_dmg, pm_heal, pm_taken, pm_fh, pm_sk = pm.get(mu, (0, None, None, None, None, None))

            if pm_fh is None or pm_sk is None:
                if mu not in raw_fhsk_cache:
                    raw_fhsk_cache[mu] = _h2h_pull_fhsk_from_raw(season_id_int, mu, int(player_uid))
                rf, rs = raw_fhsk_cache.get(mu, (None, None))
                pm_fh = pm_fh if pm_fh is not None else rf
                pm_sk = pm_sk if pm_sk is not None else rs

            pm_fh = int(pm_fh or 0)
            pm_sk = int(pm_sk or 0)

            share_kill = (k_i / total_kills) if total_kills > 0 else 0.0
            share_time = (sec / total_sec) if total_sec > 0 else 0.0
            share = share_kill if total_kills > 0 else share_time

            final_hits_total += pm_fh * share
            solo_kills_total += pm_sk * share

    return {
        "games": len(uniq_match_uids),
        "wins": wins,
        "losses": losses,
        "seconds": seconds_total,
        "kills": kills_total,
        "deaths": deaths_total,
        "assists": assists_total,
        "acc_num": acc_num,
        "acc_den": acc_den,
        "dmg": dmg_total,
        "heal": heal_total,
        "taken": taken_total,
        "final_hits": final_hits_total,
        "solo_kills": solo_kills_total,
    }


# -----------------------------
# Player pack builder
# -----------------------------
async def _h2h_build_player_pack(
    season_id: int,
    player_uid: int,
    opponent_match_uids: list[str],
    low_team_map: dict[int, dict] | None = None,
    vers_map: dict[int, dict] | None = None,
    hero_id: int | None = None,  # if set -> hero selection for that side
) -> dict:
    uid = int(player_uid)
    season_id = int(season_id)

    name = _get_player_display_name(season_id, uid)

    # --- Season context (footer)
    try:
        c.execute(
            """
            SELECT
              COUNT(*) as games,
              SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins,
              SUM(CASE WHEN is_win=0 THEN 1 ELSE 0 END) as losses
            FROM mr_player_match
            WHERE season_id=? AND player_uid=? AND is_bot=0
            """,
            (int(season_id), int(uid)),
        )
        rr = c.fetchone() or (0, 0, 0)
        sg, sw, sl = (_h2h_safe_int(rr[0], 0), _h2h_safe_int(rr[1], 0), _h2h_safe_int(rr[2], 0))
    except Exception:
        sg, sw, sl = (0, 0, 0)

    season_win_pct = (sw / sg * 100.0) if sg > 0 else 0.0

    top_heroes = _top_heroes(season_id, uid, limit=1)
    top_hero_id = top_heroes[0]["hero_id"] if top_heroes else None
    top_hero_name = await get_hero_name(str(top_hero_id)) if top_hero_id is not None else "—"

    badges = _badge_signature(season_id, uid, limit=4)
    badge_txt = " • ".join(badges) if badges else "—"

    lt = (low_team_map or {}).get(uid, {}) if low_team_map else {}
    low_team_pct = lt.get("pct_on_less", None)
    low_team_on_less = _h2h_safe_int(lt.get("on_less", 0), 0)
    low_team_uneven = _h2h_safe_int(lt.get("uneven", 0), 0)

    vm = (vers_map or {}).get(uid, {}) if vers_map else {}
    vers_pct = vm.get("vers_pct", None)
    vers_heroes = _h2h_safe_int(vm.get("eligible_heroes", 0), 0)

    # --- Opponent-only H2H stats
    h2h_tot = _h2h_get_player_totals_in_matches(season_id, uid, opponent_match_uids)
    hg = _h2h_safe_int(h2h_tot.get("games", 0), 0)
    hw = _h2h_safe_int(h2h_tot.get("wins", 0), 0)
    hl = _h2h_safe_int(h2h_tot.get("losses", 0), 0)
    h_win_pct = (hw / hg * 100.0) if hg > 0 else 0.0

    hk = _h2h_safe_int(h2h_tot.get("kills", 0), 0)
    hd = _h2h_safe_int(h2h_tot.get("deaths", 0), 0)
    ha = _h2h_safe_int(h2h_tot.get("assists", 0), 0)
    h_dmg = _h2h_safe_float(h2h_tot.get("dmg", 0.0), 0.0)
    h_heal = _h2h_safe_float(h2h_tot.get("heal", 0.0), 0.0)
    h_taken = _h2h_safe_float(h2h_tot.get("taken", 0.0), 0.0)

    h_avg_k = (hk / hg) if hg > 0 else 0.0
    h_avg_d = (hd / hg) if hg > 0 else 0.0
    h_avg_a = (ha / hg) if hg > 0 else 0.0
    h_avg_kda = (h_avg_k + h_avg_a) / max(1.0, h_avg_d)

    h_avg_dmg = (h_dmg / hg) if hg > 0 else 0.0
    h_avg_heal = (h_heal / hg) if hg > 0 else 0.0
    h_avg_taken = (h_taken / hg) if hg > 0 else 0.0

    h2h_accuracy = _h2h_get_accuracy_in_matches(season_id, uid, opponent_match_uids)
    h2h_seconds = _h2h_get_total_seconds_in_matches(season_id, uid, opponent_match_uids)
    h2h_avg_seconds = (h2h_seconds / hg) if hg > 0 else 0.0

    h2h_hero_pool = _h2h_get_hero_pool_in_matches(season_id, uid, opponent_match_uids)
    h2h_mvp, h2h_svp = _h2h_get_mvp_svp(season_id, uid, match_uids=opponent_match_uids)

    # --- Optional hero stats (eligible)
    hero_games = hero_wins = hero_losses = 0
    hero_win_pct = 0.0
    hero_seconds = 0
    hero_avg_seconds = 0.0
    hero_avg_k = hero_avg_d = hero_avg_a = hero_avg_kda = 0.0
    hero_accuracy = None
    hero_avg_dmg = hero_avg_heal = hero_avg_taken = 0.0

    # Optional per-hero final-hit and solo-kill averages.
    hero_avg_final_hits = 0.0
    hero_avg_solo_kills = 0.0

    if hero_id is not None:
        ht = _h2h_get_hero_totals_eligible(season_id, uid, int(hero_id))
        hero_games = _h2h_safe_int(ht.get("games", 0), 0)
        hero_wins = _h2h_safe_int(ht.get("wins", 0), 0)
        hero_losses = _h2h_safe_int(ht.get("losses", 0), 0)
        hero_win_pct = (hero_wins / hero_games * 100.0) if hero_games > 0 else 0.0

        hero_seconds = _h2h_safe_int(ht.get("seconds", 0), 0)
        hero_avg_seconds = (hero_seconds / hero_games) if hero_games > 0 else 0.0

        k = _h2h_safe_int(ht.get("kills", 0), 0)
        d = _h2h_safe_int(ht.get("deaths", 0), 0)
        a = _h2h_safe_int(ht.get("assists", 0), 0)

        hero_avg_k = (k / hero_games) if hero_games > 0 else 0.0
        hero_avg_d = (d / hero_games) if hero_games > 0 else 0.0
        hero_avg_a = (a / hero_games) if hero_games > 0 else 0.0
        hero_avg_kda = (hero_avg_k + hero_avg_a) / max(1.0, hero_avg_d)

        dmg = _h2h_safe_float(ht.get("dmg", 0.0), 0.0)
        heal = _h2h_safe_float(ht.get("heal", 0.0), 0.0)
        taken = _h2h_safe_float(ht.get("taken", 0.0), 0.0)
        hero_avg_dmg = (dmg / hero_games) if hero_games > 0 else 0.0
        hero_avg_heal = (heal / hero_games) if hero_games > 0 else 0.0
        hero_avg_taken = (taken / hero_games) if hero_games > 0 else 0.0

        den = _h2h_safe_float(ht.get("acc_den", 0.0), 0.0)
        hero_accuracy = (_h2h_safe_float(ht.get("acc_num", 0.0), 0.0) / den) if den > 0 else None

        # Final Hits / G and Solo Kills / G.
        fh = _h2h_safe_float(ht.get("final_hits", 0.0), 0.0)
        sk = _h2h_safe_float(ht.get("solo_kills", 0.0), 0.0)
        hero_avg_final_hits = (fh / hero_games) if hero_games > 0 else 0.0
        hero_avg_solo_kills = (sk / hero_games) if hero_games > 0 else 0.0

    return {
        "uid": uid,
        "name": str(name),

        # Season context
        "season_games": int(sg),
        "season_wins": int(sw),
        "season_losses": int(sl),
        "season_win_pct": float(season_win_pct),
        "top_hero": str(top_hero_name),
        "badges": str(badge_txt),

        "low_team_pct": (float(low_team_pct) if low_team_pct is not None else None),
        "low_team_on_less": int(low_team_on_less),
        "low_team_uneven": int(low_team_uneven),

        "vers_pct": (float(vers_pct) if vers_pct is not None else None),
        "vers_heroes": int(vers_heroes),

        # H2H opponent-only
        "h2h_games": int(hg),
        "h2h_wins": int(hw),
        "h2h_losses": int(hl),
        "h2h_win_pct": float(h_win_pct),
        "h2h_avg_k": float(h_avg_k),
        "h2h_avg_d": float(h_avg_d),
        "h2h_avg_a": float(h_avg_a),
        "h2h_avg_kda": float(h_avg_kda),
        "h2h_avg_dmg": float(h_avg_dmg),
        "h2h_avg_heal": float(h_avg_heal),
        "h2h_avg_taken": float(h_avg_taken),
        "h2h_accuracy": (float(h2h_accuracy) if h2h_accuracy is not None else None),
        "h2h_seconds": int(h2h_seconds),
        "h2h_avg_seconds": float(h2h_avg_seconds),
        "h2h_hero_pool": int(h2h_hero_pool),
        "h2h_mvp": int(h2h_mvp),
        "h2h_svp": int(h2h_svp),

        # Optional hero selection for this side
        "hero_id": (int(hero_id) if hero_id is not None else None),
        "hero_games": int(hero_games),
        "hero_wins": int(hero_wins),
        "hero_losses": int(hero_losses),
        "hero_win_pct": float(hero_win_pct),
        "hero_seconds": int(hero_seconds),
        "hero_avg_seconds": float(hero_avg_seconds),
        "hero_avg_k": float(hero_avg_k),
        "hero_avg_d": float(hero_avg_d),
        "hero_avg_a": float(hero_avg_a),
        "hero_avg_kda": float(hero_avg_kda),
        "hero_avg_dmg": float(hero_avg_dmg),
        "hero_avg_heal": float(hero_avg_heal),
        "hero_avg_taken": float(hero_avg_taken),
        "hero_accuracy": (float(hero_accuracy) if hero_accuracy is not None else None),

        # Per-hero finishing averages.
        "hero_avg_final_hits": float(hero_avg_final_hits),
        "hero_avg_solo_kills": float(hero_avg_solo_kills),
    }



# -----------------------------
# Image renderer (supports default H2H + cross-hero compare)
# -----------------------------
def _h2h_render_matchup_image(
    title: str,
    a: dict,
    b: dict,
    pair: dict,
    a_hero_name: str | None = None,
    b_hero_name: str | None = None,
) -> io.BytesIO:
    if Image is None:
        buf = io.BytesIO()
        buf.seek(0)
        return buf

    try:
        body_font, title_font = get_fonts(body_pt=24, title_pt=44)
        small_font, _ = get_fonts(body_pt=20, title_pt=34)
    except Exception:
        body_font = title_font = small_font = None

    bg = (25, 25, 25)
    fg = (235, 235, 235)
    muted = (170, 170, 170)
    gold = (255, 215, 0)
    grid = (70, 70, 70)
    panel = (35, 35, 35)

    any_hero = bool(a_hero_name) or bool(b_hero_name)

    def _winner_flags(a_num, b_num, better: str):
        a_win = b_win = False
        if a_num is None or b_num is None:
            return a_win, b_win
        try:
            if better == "tuple_high":
                if a_num > b_num:
                    a_win = True
                elif b_num > a_num:
                    b_win = True
                return a_win, b_win
            av = float(a_num)
            bv = float(b_num)
            if better == "low":
                av, bv = -av, -bv
            if av > bv:
                a_win = True
            elif bv > av:
                b_win = True
        except Exception:
            pass
        return a_win, b_win

    def _sel_val(p: dict, key_h: str, key_h2h: str):
        return p[key_h] if p.get("hero_id") is not None else p[key_h2h]

    def _sel_acc(p: dict):
        return p["hero_accuracy"] if p.get("hero_id") is not None else p["h2h_accuracy"]

    def _sel_label(hero_name: str | None):
        return f"Hero: {hero_name}" if hero_name else "Opponents Only"

    # Rows
    if not any_hero:
        # Default: pure opponents-only H2H
        rows = [
            {"label": "H2H Win %", "a_disp": lambda: f"{a['h2h_win_pct']:.1f}%", "b_disp": lambda: f"{b['h2h_win_pct']:.1f}%",
             "a_num": lambda: a.get("h2h_win_pct"), "b_num": lambda: b.get("h2h_win_pct"), "better": "high"},
            {"label": "H2H W / L", "a_disp": lambda: f"{a['h2h_wins']}/{a['h2h_losses']}", "b_disp": lambda: f"{b['h2h_wins']}/{b['h2h_losses']}",
             "a_num": lambda: (a["h2h_wins"], -a["h2h_losses"]), "b_num": lambda: (b["h2h_wins"], -b["h2h_losses"]), "better": "tuple_high"},
            {"label": "H2H Avg KDA", "a_disp": lambda: f"{a['h2h_avg_kda']:.2f}", "b_disp": lambda: f"{b['h2h_avg_kda']:.2f}",
             "a_num": lambda: a.get("h2h_avg_kda"), "b_num": lambda: b.get("h2h_avg_kda"), "better": "high"},
            {"label": "H2H Kills / G", "a_disp": lambda: f"{a['h2h_avg_k']:.2f}", "b_disp": lambda: f"{b['h2h_avg_k']:.2f}",
             "a_num": lambda: a.get("h2h_avg_k"), "b_num": lambda: b.get("h2h_avg_k"), "better": "high"},
            {"label": "H2H Deaths / G", "a_disp": lambda: f"{a['h2h_avg_d']:.2f}", "b_disp": lambda: f"{b['h2h_avg_d']:.2f}",
             "a_num": lambda: a.get("h2h_avg_d"), "b_num": lambda: b.get("h2h_avg_d"), "better": "low"},
            {"label": "H2H Assists / G", "a_disp": lambda: f"{a['h2h_avg_a']:.2f}", "b_disp": lambda: f"{b['h2h_avg_a']:.2f}",
             "a_num": lambda: a.get("h2h_avg_a"), "b_num": lambda: b.get("h2h_avg_a"), "better": "high"},
            {"label": "H2H Damage / G", "a_disp": lambda: f"{int(round(a['h2h_avg_dmg']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_dmg']))}",
             "a_num": lambda: a.get("h2h_avg_dmg"), "b_num": lambda: b.get("h2h_avg_dmg"), "better": "high"},
            {"label": "H2H Heal / G", "a_disp": lambda: f"{int(round(a['h2h_avg_heal']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_heal']))}",
             "a_num": lambda: a.get("h2h_avg_heal"), "b_num": lambda: b.get("h2h_avg_heal"), "better": "high"},
            {"label": "H2H Taken / G", "a_disp": lambda: f"{int(round(a['h2h_avg_taken']))}", "b_disp": lambda: f"{int(round(b['h2h_avg_taken']))}",
             "a_num": lambda: a.get("h2h_avg_taken"), "b_num": lambda: b.get("h2h_avg_taken"), "better": "low"},
            {"label": "H2H MVP", "a_disp": lambda: str(int(a["h2h_mvp"])), "b_disp": lambda: str(int(b["h2h_mvp"])),
             "a_num": lambda: a.get("h2h_mvp"), "b_num": lambda: b.get("h2h_mvp"), "better": "high"},
            {"label": "H2H SVP", "a_disp": lambda: str(int(a["h2h_svp"])), "b_disp": lambda: str(int(b["h2h_svp"])),
             "a_num": lambda: a.get("h2h_svp"), "b_num": lambda: b.get("h2h_svp"), "better": "high"},
            {"label": "H2H Hero Pool", "a_disp": lambda: str(int(a["h2h_hero_pool"])), "b_disp": lambda: str(int(b["h2h_hero_pool"])),
             "a_num": lambda: a.get("h2h_hero_pool"), "b_num": lambda: b.get("h2h_hero_pool"), "better": "high"},
            {"label": "H2H Accuracy", "a_disp": lambda: ("—" if a.get("h2h_accuracy") is None else f"{a['h2h_accuracy']*100:.1f}%"),
             "b_disp": lambda: ("—" if b.get("h2h_accuracy") is None else f"{b['h2h_accuracy']*100:.1f}%"),
             "a_num": lambda: (a["h2h_accuracy"] * 100.0) if a.get("h2h_accuracy") is not None else None,
             "b_num": lambda: (b["h2h_accuracy"] * 100.0) if b.get("h2h_accuracy") is not None else None,
             "better": "high"},
        ]
    else:
        # Hero compare (cross-hero / mixed)
        rows = [
            {"label": "Win %", "a_disp": lambda: f"{_sel_val(a,'hero_win_pct','h2h_win_pct'):.1f}%", "b_disp": lambda: f"{_sel_val(b,'hero_win_pct','h2h_win_pct'):.1f}%",
             "a_num": lambda: _sel_val(a,'hero_win_pct','h2h_win_pct'), "b_num": lambda: _sel_val(b,'hero_win_pct','h2h_win_pct'), "better": "high"},

            {"label": "Games", "a_disp": lambda: str(int(_sel_val(a,'hero_games','h2h_games'))), "b_disp": lambda: str(int(_sel_val(b,'hero_games','h2h_games'))),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Avg KDA", "a_disp": lambda: f"{_sel_val(a,'hero_avg_kda','h2h_avg_kda'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_kda','h2h_avg_kda'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_kda','h2h_avg_kda'), "b_num": lambda: _sel_val(b,'hero_avg_kda','h2h_avg_kda'), "better": "high"},

            {"label": "Kills / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_k','h2h_avg_k'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_k','h2h_avg_k'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_k','h2h_avg_k'), "b_num": lambda: _sel_val(b,'hero_avg_k','h2h_avg_k'), "better": "high"},

            {"label": "Deaths / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_d','h2h_avg_d'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_d','h2h_avg_d'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_d','h2h_avg_d'), "b_num": lambda: _sel_val(b,'hero_avg_d','h2h_avg_d'), "better": "low"},

            {"label": "Assists / G", "a_disp": lambda: f"{_sel_val(a,'hero_avg_a','h2h_avg_a'):.2f}", "b_disp": lambda: f"{_sel_val(b,'hero_avg_a','h2h_avg_a'):.2f}",
             "a_num": lambda: _sel_val(a,'hero_avg_a','h2h_avg_a'), "b_num": lambda: _sel_val(b,'hero_avg_a','h2h_avg_a'), "better": "high"},

            {"label": "Final Hits / G",
             "a_disp": lambda: f"{_sel_val(a,'hero_avg_final_hits','h2h_avg_final_hits'):.2f}",
             "b_disp": lambda: f"{_sel_val(b,'hero_avg_final_hits','h2h_avg_final_hits'):.2f}",
             "a_num":  lambda: _sel_val(a,'hero_avg_final_hits','h2h_avg_final_hits'),
             "b_num":  lambda: _sel_val(b,'hero_avg_final_hits','h2h_avg_final_hits'),
             "better": "high"},

            {"label": "Solo Kills / G",
             "a_disp": lambda: f"{_sel_val(a,'hero_avg_solo_kills','h2h_avg_solo_kills'):.2f}",
             "b_disp": lambda: f"{_sel_val(b,'hero_avg_solo_kills','h2h_avg_solo_kills'):.2f}",
             "a_num":  lambda: _sel_val(a,'hero_avg_solo_kills','h2h_avg_solo_kills'),
             "b_num":  lambda: _sel_val(b,'hero_avg_solo_kills','h2h_avg_solo_kills'),
             "better": "high"},

            {"label": "Damage / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_dmg','h2h_avg_dmg')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_dmg','h2h_avg_dmg')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_dmg','h2h_avg_dmg'), "b_num": lambda: _sel_val(b,'hero_avg_dmg','h2h_avg_dmg'), "better": "high"},

            {"label": "Healing / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_heal','h2h_avg_heal')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_heal','h2h_avg_heal')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_heal','h2h_avg_heal'), "b_num": lambda: _sel_val(b,'hero_avg_heal','h2h_avg_heal'), "better": "high"},

            {"label": "Taken / G", "a_disp": lambda: f"{int(round(_sel_val(a,'hero_avg_taken','h2h_avg_taken')))}", "b_disp": lambda: f"{int(round(_sel_val(b,'hero_avg_taken','h2h_avg_taken')))}",
             "a_num": lambda: _sel_val(a,'hero_avg_taken','h2h_avg_taken'), "b_num": lambda: _sel_val(b,'hero_avg_taken','h2h_avg_taken'), "better": "low"},

            {"label": "Time (min)", "a_disp": lambda: _h2h_fmt_num((_sel_val(a,'hero_seconds','h2h_seconds') or 0) / 60.0),
             "b_disp": lambda: _h2h_fmt_num((_sel_val(b,'hero_seconds','h2h_seconds') or 0) / 60.0),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Time / G (min)", "a_disp": lambda: _h2h_fmt_num((_sel_val(a,'hero_avg_seconds','h2h_avg_seconds') or 0) / 60.0),
             "b_disp": lambda: _h2h_fmt_num((_sel_val(b,'hero_avg_seconds','h2h_avg_seconds') or 0) / 60.0),
             "a_num": lambda: None, "b_num": lambda: None, "better": "none"},

            {"label": "Accuracy", "a_disp": lambda: ("—" if _sel_acc(a) is None else f"{_sel_acc(a)*100:.1f}%"),
             "b_disp": lambda: ("—" if _sel_acc(b) is None else f"{_sel_acc(b)*100:.1f}%"),
             "a_num": lambda: (_sel_acc(a) * 100.0) if _sel_acc(a) is not None else None,
             "b_num": lambda: (_sel_acc(b) * 100.0) if _sel_acc(b) is not None else None,
             "better": "high"},
        ]

    # Geometry
    W = 1200
    pad = 30
    row_h = 46
    col_gap = 20
    label_w = 240
    col_w = (W - pad * 2 - label_w - col_gap * 2) // 2
    ax = pad
    lx = pad + col_w + col_gap
    bx = lx + label_w + col_gap

    # Measure header + footer using temp canvas
    tmp_img = Image.new("RGB", (10, 10), bg)
    tmp_draw = ImageDraw.Draw(tmp_img)

    _, title_h = _h2h_text_wh(tmp_draw, title, title_font)
    y_header = pad + title_h + 10

    header_lines = []
    if any_hero:
        header_lines.append(f"A: {_sel_label(a_hero_name)}   •   B: {_sel_label(b_hero_name)}")
    header_lines.append(f"Opponents: {a['name']} {pair['a_wins']}-{pair['b_wins']} {b['name']}  (games: {pair['opp_games']})")
    header_lines.append(f"Teammates: {pair['duo_wins']}-{pair['duo_losses']}  (games: {pair['duo_games']})")

    line_gap = 6
    cur_y = y_header
    for line in header_lines:
        _, lh = _h2h_text_wh(tmp_draw, line, small_font)
        cur_y += lh + line_gap
    header_text_bottom = cur_y

    # Push table down enough so header boxes never overlap header text
    y0 = int(header_text_bottom + 14 + 85)

    # Footer paragraphs (season context; wrapped)
    a_lt = "—" if a.get("low_team_pct") is None else f"{a['low_team_pct']:.1f}% ({a['low_team_on_less']}/{a['low_team_uneven']})"
    b_lt = "—" if b.get("low_team_pct") is None else f"{b['low_team_pct']:.1f}% ({b['low_team_on_less']}/{b['low_team_uneven']})"
    a_v = "—" if a.get("vers_pct") is None else f"{a['vers_pct']:.1f}% (K={a.get('vers_heroes',0)})"
    b_v = "—" if b.get("vers_pct") is None else f"{b['vers_pct']:.1f}% (K={b.get('vers_heroes',0)})"

    left_paras = [
        f"Season Win%: {a['season_win_pct']:.1f}%   Low-team: {a_lt}   Vers: {a_v}",
        f"Season Top Hero: {a['top_hero']}",
        f"Badges: {a['badges']}",
    ]
    right_paras = [
        f"Season Win%: {b['season_win_pct']:.1f}%   Low-team: {b_lt}   Vers: {b_v}",
        f"Season Top Hero: {b['top_hero']}",
        f"Badges: {b['badges']}",
    ]

    col_text_w = col_w - 32
    left_lines = []
    right_lines = []

    for p in left_paras:
        left_lines.extend(_h2h_wrap_text_lines(tmp_draw, p, small_font, col_text_w))
        left_lines.append("")
    for p in right_paras:
        right_lines.extend(_h2h_wrap_text_lines(tmp_draw, p, small_font, col_text_w))
        right_lines.append("")

    while left_lines and left_lines[-1] == "":
        left_lines.pop()
    while right_lines and right_lines[-1] == "":
        right_lines.pop()

    _, base_lh = _h2h_text_wh(tmp_draw, "Ag", small_font)
    footer_line_h = base_lh + 4
    footer_pad_top = 18
    footer_pad_bot = 18
    max_footer_lines = max(len(left_lines), len(right_lines), 1)
    footer_h = footer_pad_top + max_footer_lines * footer_line_h + footer_pad_bot

    H = int(y0 + len(rows) * row_h + footer_h + pad)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    d.text((pad, pad), title, font=title_font, fill=gold)

    cur_y = y_header
    for line in header_lines:
        d.text((pad, cur_y), line, font=small_font, fill=fg)
        _, lh = _h2h_text_wh(d, line, small_font)
        cur_y += lh + line_gap

    # Header boxes
    d.rectangle([ax, y0 - 85, ax + col_w, y0 - 10], fill=panel, outline=grid, width=2)
    d.rectangle([bx, y0 - 85, bx + col_w, y0 - 10], fill=panel, outline=grid, width=2)
    d.rectangle([lx, y0 - 85, lx + label_w, y0 - 10], fill=(30, 30, 30), outline=grid, width=2)

    d.text((ax + 16, y0 - 74), a["name"][:24], font=body_font, fill=fg)
    d.text((bx + 16, y0 - 74), b["name"][:24], font=body_font, fill=fg)

    # Under-name status line
    if any_hero:
        a_sel_games = int(_sel_val(a, "hero_games", "h2h_games"))
        a_sel_win = float(_sel_val(a, "hero_win_pct", "h2h_win_pct"))
        b_sel_games = int(_sel_val(b, "hero_games", "h2h_games"))
        b_sel_win = float(_sel_val(b, "hero_win_pct", "h2h_win_pct"))

        d.text((ax + 16, y0 - 44), f"{_sel_label(a_hero_name)}   •   Games: {a_sel_games}   Win%: {a_sel_win:.1f}%", font=small_font, fill=muted)
        d.text((bx + 16, y0 - 44), f"{_sel_label(b_hero_name)}   •   Games: {b_sel_games}   Win%: {b_sel_win:.1f}%", font=small_font, fill=muted)
        d.text((lx + 16, y0 - 62), "HERO COMPARE", font=small_font, fill=fg)
    else:
        d.text((ax + 16, y0 - 44), f"H2H Games: {a['h2h_games']}   H2H Win%: {a['h2h_win_pct']:.1f}%", font=small_font, fill=muted)
        d.text((bx + 16, y0 - 44), f"H2H Games: {b['h2h_games']}   H2H Win%: {b['h2h_win_pct']:.1f}%", font=small_font, fill=muted)
        d.text((lx + 16, y0 - 62), "HEAD TO HEAD", font=small_font, fill=fg)

    # Grid rows
    y = y0
    for row in rows:
        d.rectangle([ax, y, ax + col_w, y + row_h], outline=grid)
        d.rectangle([lx, y, lx + label_w, y + row_h], outline=grid)
        d.rectangle([bx, y, bx + col_w, y + row_h], outline=grid)

        a_txt = row["a_disp"]()
        b_txt = row["b_disp"]()
        better = row.get("better", "high")

        a_num = row["a_num"]()
        b_num = row["b_num"]()

        a_win = b_win = False
        if better not in ("none",):
            a_win, b_win = _winner_flags(a_num, b_num, better)

        d.text((lx + 16, y + 12), row["label"], font=small_font, fill=fg)
        _h2h_draw_text_bold(d, (ax + 16, y + 10), str(a_txt), body_font, fg, bold=a_win)
        _h2h_draw_text_bold(d, (bx + 16, y + 10), str(b_txt), body_font, fg, bold=b_win)

        y += row_h

    # Footer (wrapped per column)
    fy = y + footer_pad_top
    ly = fy
    ry = fy

    for line in left_lines:
        if line == "":
            ly += footer_line_h // 2
            continue
        d.text((ax + 16, ly), line, font=small_font, fill=muted)
        ly += footer_line_h

    for line in right_lines:
        if line == "":
            ry += footer_line_h // 2
            continue
        d.text((bx + 16, ry), line, font=small_font, fill=muted)
        ry += footer_line_h

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# -----------------------------
# UI View (players + per-side hero dropdowns)
# -----------------------------
class HeadToHeadPickerView(discord.ui.View):
    def __init__(self, ctx, season_id: int):
        super().__init__(timeout=220)
        self.ctx = ctx
        self.season_id = int(season_id)

        self.page = 0
        self.uid_a: int | None = None
        self.uid_b: int | None = None

        self.hero_a_id: int | None = None
        self.hero_b_id: int | None = None
        self.hero_a_name: str | None = None
        self.hero_b_name: str | None = None

        m = _get_all_players() or {}
        players = []
        for pkey, nm in m.items():
            uid = _uid_from_pkey(pkey)
            if uid is None:
                continue
            players.append((int(uid), str(nm)))
        players.sort(key=lambda t: t[1].lower())
        self.players = players
        self.pages = max(1, math.ceil(len(self.players) / 25))

        # Player selects
        self.sel_a = discord.ui.Select(placeholder="Select Player A…", min_values=1, max_values=1, options=[])
        self.sel_b = discord.ui.Select(placeholder="Select Player B…", min_values=1, max_values=1, options=[])
        self.sel_a.callback = self._on_select_a
        self.sel_b.callback = self._on_select_b

        # Hero selects (per side)
        self.sel_ha = discord.ui.Select(
            placeholder="Hero for Player A (optional)…",
            min_values=1, max_values=1,
            options=[discord.SelectOption(label="Overall (Opponents Only)", value="__all__", default=True)],
            disabled=True,
        )
        self.sel_hb = discord.ui.Select(
            placeholder="Hero for Player B (optional)…",
            min_values=1, max_values=1,
            options=[discord.SelectOption(label="Overall (Opponents Only)", value="__all__", default=True)],
            disabled=True,
        )
        self.sel_ha.callback = self._on_select_ha
        self.sel_hb.callback = self._on_select_hb

        self.add_item(self.sel_a)
        self.add_item(self.sel_ha)
        self.add_item(self.sel_b)
        self.add_item(self.sel_hb)

        self._sync_player_options()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            try:
                await interaction.response.send_message("Only the command author can use this selector.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    def _page_slice(self):
        start = self.page * 25
        return self.players[start:start + 25]

    def _build_player_options(self, selected_uid: int | None) -> list[discord.SelectOption]:
        chunk = self._page_slice()
        chunk_uids = [uid for uid, _nm in chunk]
        opts: list[discord.SelectOption] = []

        if selected_uid is not None and selected_uid not in chunk_uids:
            nm = _get_player_display_name(self.season_id, int(selected_uid))
            opts.append(discord.SelectOption(label=f"{nm} (selected)"[:100], value=str(int(selected_uid)), default=True))
            for uid, nm2 in chunk:
                if int(uid) == int(selected_uid):
                    continue
                if len(opts) >= 25:
                    break
                opts.append(discord.SelectOption(label=nm2[:100], value=str(int(uid))))
            return opts

        for uid, nm in chunk:
            is_def = (selected_uid is not None and int(uid) == int(selected_uid))
            opts.append(discord.SelectOption(label=nm[:100], value=str(int(uid)), default=is_def))
            if len(opts) >= 25:
                break

        if not opts:
            opts = [discord.SelectOption(label="—", value="0")]
        return opts

    def _sync_player_options(self):
        self.sel_a.options = self._build_player_options(self.uid_a)
        self.sel_b.options = self._build_player_options(self.uid_b)

        can_go_prev = self.page > 0
        can_go_next = self.page < (self.pages - 1)

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                cid = getattr(child, "custom_id", None)
                if cid == "h2h_prev":
                    child.disabled = not can_go_prev
                elif cid == "h2h_next":
                    child.disabled = not can_go_next
                elif cid == "h2h_swap":
                    child.disabled = not (self.uid_a and self.uid_b)
                elif cid == "h2h_show":
                    child.disabled = not (self.uid_a and self.uid_b and self.uid_a != self.uid_b)

        self.sel_ha.disabled = not bool(self.uid_a)
        self.sel_hb.disabled = not bool(self.uid_b)

    async def _refresh_hero_options_for(self, which: str):
        """
        which in {"A","B"}
        """
        if which == "A":
            uid = self.uid_a
            cur = self.hero_a_id
        else:
            uid = self.uid_b
            cur = self.hero_b_id

        base = [discord.SelectOption(label="Overall (Opponents Only)", value="__all__", default=(cur is None))]

        if not uid:
            opts = base
            if which == "A":
                self.sel_ha.options = opts
                self.sel_ha.disabled = True
            else:
                self.sel_hb.options = opts
                self.sel_hb.disabled = True
            return

        heroes = _h2h_get_player_eligible_heroes(self.season_id, int(uid), limit=24)
        opts = list(base)
        ids_in_list = set()

        for rec in heroes:
            hid = int(rec["hero_id"])
            ids_in_list.add(hid)
            nm = await get_hero_name(str(hid))
            minutes = int(rec.get("sec_total", 0) // 60)
            label = f"{nm} ({minutes}m)" if minutes > 0 else nm
            opts.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(hid),
                    default=(cur is not None and int(cur) == hid),
                )
            )
            if len(opts) >= 25:
                break

        # If current hero not in list, reset to overall
        if cur is not None and int(cur) not in ids_in_list:
            if which == "A":
                self.hero_a_id = None
                self.hero_a_name = None
            else:
                self.hero_b_id = None
                self.hero_b_name = None
            opts = [discord.SelectOption(label="Overall (Opponents Only)", value="__all__", default=True)] + opts[1:]
            for o in opts[1:]:
                o.default = False

        if which == "A":
            self.sel_ha.options = opts
            self.sel_ha.disabled = False
        else:
            self.sel_hb.options = opts
            self.sel_hb.disabled = False

    def _build_embed(self) -> discord.Embed:
        def _nm(uid):
            if uid is None:
                return "—"
            return _get_player_display_name(self.season_id, int(uid))

        a_h = "Overall (Opponents Only)" if self.hero_a_id is None else (self.hero_a_name or f"Hero {self.hero_a_id}")
        b_h = "Overall (Opponents Only)" if self.hero_b_id is None else (self.hero_b_name or f"Hero {self.hero_b_id}")

        e = discord.Embed(
            title=f"Head-to-Head Matchup Builder (Season {self.season_id})",
            description="Select two players. Optionally pick a hero for each player to compare cross-hero performance.",
        )
        e.add_field(name="Player A", value=_nm(self.uid_a), inline=True)
        e.add_field(name="Hero A", value=a_h, inline=True)
        e.add_field(name="Player B", value=_nm(self.uid_b), inline=True)
        e.add_field(name="Hero B", value=b_h, inline=True)
        e.add_field(name="Roster Page", value=f"{self.page + 1}/{self.pages}", inline=False)
        e.set_footer(text="Default compares Opponents Only. Hero stats use eligibility thresholds.")
        return e

    async def _on_select_a(self, interaction: discord.Interaction):
        try:
            self.uid_a = int(self.sel_a.values[0])
        except Exception:
            self.uid_a = None

        # reset hero A selection when changing player A
        self.hero_a_id = None
        self.hero_a_name = None

        self._sync_player_options()
        await self._refresh_hero_options_for("A")
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_select_b(self, interaction: discord.Interaction):
        try:
            self.uid_b = int(self.sel_b.values[0])
        except Exception:
            self.uid_b = None

        self.hero_b_id = None
        self.hero_b_name = None

        self._sync_player_options()
        await self._refresh_hero_options_for("B")
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_select_ha(self, interaction: discord.Interaction):
        v = (self.sel_ha.values[0] if self.sel_ha.values else "__all__")
        if v == "__all__":
            self.hero_a_id = None
            self.hero_a_name = None
        else:
            try:
                self.hero_a_id = int(v)
            except Exception:
                self.hero_a_id = None
                self.hero_a_name = None
            if self.hero_a_id is not None:
                self.hero_a_name = await get_hero_name(str(self.hero_a_id))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_select_hb(self, interaction: discord.Interaction):
        v = (self.sel_hb.values[0] if self.sel_hb.values else "__all__")
        if v == "__all__":
            self.hero_b_id = None
            self.hero_b_name = None
        else:
            try:
                self.hero_b_id = int(v)
            except Exception:
                self.hero_b_id = None
                self.hero_b_name = None
            if self.hero_b_id is not None:
                self.hero_b_name = await get_hero_name(str(self.hero_b_id))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="h2h_prev")
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_player_options()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="h2h_next")
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.pages - 1, self.page + 1)
        self._sync_player_options()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Swap", style=discord.ButtonStyle.secondary, custom_id="h2h_swap")
    async def btn_swap(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.uid_a, self.uid_b = self.uid_b, self.uid_a
        self.hero_a_id, self.hero_b_id = self.hero_b_id, self.hero_a_id
        self.hero_a_name, self.hero_b_name = self.hero_b_name, self.hero_a_name

        self._sync_player_options()
        await self._refresh_hero_options_for("A")
        await self._refresh_hero_options_for("B")
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Show Matchup", style=discord.ButtonStyle.primary, custom_id="h2h_show")
    async def btn_show(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if not self.uid_a or not self.uid_b or self.uid_a == self.uid_b:
            await interaction.followup.send("Please select two different players.", ephemeral=True)
            return

        season_id = int(self.season_id)
        uid_a = int(self.uid_a)
        uid_b = int(self.uid_b)

        opponent_match_uids = _h2h_get_opponent_match_uids(season_id, uid_a, uid_b)

        uid_to_name = {
            uid_a: _get_player_display_name(season_id, uid_a),
            uid_b: _get_player_display_name(season_id, uid_b),
        }
        low_team_map = _h2h_get_low_team_metrics_for_players(season_id, uid_to_name)
        vers_map = _h2h_get_versatility_for_players(season_id, [uid_a, uid_b])

        a_pack = await _h2h_build_player_pack(
            season_id, uid_a,
            opponent_match_uids=opponent_match_uids,
            low_team_map=low_team_map,
            vers_map=vers_map,
            hero_id=(int(self.hero_a_id) if self.hero_a_id is not None else None),
        )
        b_pack = await _h2h_build_player_pack(
            season_id, uid_b,
            opponent_match_uids=opponent_match_uids,
            low_team_map=low_team_map,
            vers_map=vers_map,
            hero_id=(int(self.hero_b_id) if self.hero_b_id is not None else None),
        )

        pair = _h2h_get_pair_records(season_id, uid_a, uid_b)

        any_hero = (self.hero_a_id is not None) or (self.hero_b_id is not None)
        if any_hero:
            a_tag = self.hero_a_name or "Overall"
            b_tag = self.hero_b_name or "Overall"
            title = f"HEAD TO HEAD — {a_tag} vs {b_tag} (Season {season_id})"
        else:
            title = f"HEAD TO HEAD — Opponents Only (Season {season_id})"

        buf = _h2h_render_matchup_image(
            title,
            a_pack,
            b_pack,
            pair,
            a_hero_name=self.hero_a_name,
            b_hero_name=self.hero_b_name,
        )

        safe_a = re.sub(r"[^a-zA-Z0-9_]+", "_", a_pack["name"])
        safe_b = re.sub(r"[^a-zA-Z0-9_]+", "_", b_pack["name"])
        safe_ha = re.sub(r"[^a-zA-Z0-9_]+", "_", (self.hero_a_name or "overall"))
        safe_hb = re.sub(r"[^a-zA-Z0-9_]+", "_", (self.hero_b_name or "overall"))
        fn = f"h2h_{safe_a}_vs_{safe_b}_{safe_ha}_vs_{safe_hb}.png"

        msg = f"**{a_pack['name']} vs {b_pack['name']}**"
        if any_hero:
            msg += f" — **{(self.hero_a_name or 'Overall')} vs {(self.hero_b_name or 'Overall')}**"
        else:
            msg += " — **Opponents Only**"

        await interaction.followup.send(content=msg, file=discord.File(fp=buf, filename=fn))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="h2h_close")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        try:
            for child in self.children:
                child.disabled = True
            if hasattr(self, "_message") and self._message:
                await self._message.edit(view=self)
        except Exception:
            pass


# -----------------------------
# Command
# -----------------------------
@bot.command(name="h2h", aliases=["head2head", "head_to_head"])
async def head_to_head_cmd(ctx):
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    m = _get_all_players() or {}
    if not m:
        await ctx.send("No players found. Ensure your roster is enabled or the season has imported matches.")
        return

    view = HeadToHeadPickerView(ctx, int(season_id))
    msg = await ctx.send(embed=view._build_embed(), view=view)
    view._message = msg

# ============================================================================================================
# LOW-TEAM % (season-wide, manual + API via game_stats_v)
# ============================================================================================================

def create_low_team_image_with_percent(results, title="Low-Team % (Uneven Games Only)"):
    return _render_low_team_image(results, title=title)


@bot.command(name="low_team")
async def low_team(ctx):
    """Render season-wide low-team percentages from the current-season view."""
    c.execute("SELECT game_label, player, win FROM game_stats_v")
    rows = c.fetchall()
    if not rows:
        await ctx.send("No games found for this season.")
        return

    results = _calculate_low_team_results(rows)
    buf = create_low_team_image_with_percent(results, title="Low-Team % (Season)")
    await ctx.send(file=discord.File(fp=buf, filename="low_team.png"))

# ============================================================================================================
# COMMAND: !season_story  (IMAGE OUTPUT)
#
# ============================================================================================================

import io
import re
import math
import asyncio
from datetime import datetime
from collections import defaultdict
from itertools import combinations
from zoneinfo import ZoneInfo

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


# -----------------------------
# Tunables
# -----------------------------
SS_TOP_ACTIVE = 5
SS_TOP_VERSATILE = 5
SS_TOP_BOT_HEROES = 5
SS_MIN_HALF_GAMES = 3
SS_TOP_IMPROVED = 5
SS_MIN_DUO_GAMES = 5
SS_TOP_DUOS = 5
SS_TOP_SYNERGY = 5
SS_SYNERGY_MIN_GAMES = 5
SS_TOP_DOMINANT = 5
SS_TOP_TIER = 5
SS_TIER_MIN_PICKS = 10
SS_TOP_BANS = 5

# Role distribution plot
SS_ROLE_PLOT_TITLE = "Role Distribution (All Players)"
SS_ROLE_LABEL_MAX = 12          # max chars for label next to dot
SS_ROLE_DOT_R = 6               # dot radius
SS_ROLE_GRID_STEPS = (0.2, 0.4, 0.6, 0.8)
SS_ROLE_PLOT_TOP_PAD = 30  # pushes the triangle down (was ~12 implicit)

# Biggest Upset uneven-team disadvantage (internal only)
UPSET_SIZE_PENALTY_PER_PLAYER = 0.08
UPSET_SIZE_PENALTY_CAP = 0.20
UPSET_USE_SMOOTHED_PREWIN = True
UPSET_SMOOTH_PRIOR_GAMES = 6

# Existing eligibility thresholds (same as tierlist/synergy/player_heros outputs)
try:
    HERO_WIN_MIN_SECONDS
except NameError:
    HERO_WIN_MIN_SECONDS = 120
try:
    HERO_WIN_MIN_RATIO
except NameError:
    HERO_WIN_MIN_RATIO = 0.20


# -----------------------------
# DB helpers
# -----------------------------
def _ss_table_exists(table: str) -> bool:
    global c
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return c.fetchone() is not None
    except Exception:
        return False


def _ss_col_exists(table: str, col: str) -> bool:
    global c
    try:
        c.execute(f"PRAGMA table_info({table})")
        return any(str(r[1]).lower() == col.lower() for r in (c.fetchall() or []))
    except Exception:
        return False


def _ss_norm_side(v):
    try:
        i = int(v)
    except Exception:
        return None
    if i in (0, 1):
        return i
    if i in (1, 2):
        return i - 1
    return None


def _ss_clip(s: str, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _ss_gl_sort_key(gl: str):
    s = str(gl or "")
    m = re.search(r"(\d+)", s)
    return (int(m.group(1)) if m else 10**9, s.lower())


def _ss_safe_iso_to_brisbane(iso_text: str) -> str:
    if not iso_text:
        return ""
    s = str(iso_text).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_b = dt.astimezone(ZoneInfo("Australia/Brisbane"))
        return dt_b.strftime("%d %b %Y")
    except Exception:
        return str(iso_text)


def _ss_player_name(season_id: int, player_uid: int) -> str:
    try:
        return _get_player_display_name(int(season_id), int(player_uid))
    except Exception:
        pass
    global c
    try:
        c.execute("""
            SELECT player
            FROM mr_player_match
            WHERE season_id=? AND player_uid=?
            ORDER BY rowid DESC
            LIMIT 1
        """, (int(season_id), int(player_uid)))
        r = c.fetchone()
        if r and r[0]:
            return str(r[0])
    except Exception:
        pass
    return f"UID_{player_uid}"


def _ss_get_ordered_game_labels(season_id: int) -> list[str]:
    ensure_mr_api_tables()
    global c

    if _ss_table_exists("mr_match_meta") and _ss_col_exists("mr_match_meta", "match_time_utc"):
        try:
            c.execute("""
                SELECT game_label
                FROM mr_match_meta
                WHERE season_id=?
                ORDER BY
                    CASE WHEN match_time_utc IS NULL OR match_time_utc='' THEN 1 ELSE 0 END,
                    match_time_utc ASC,
                    game_label ASC
            """, (int(season_id),))
            labels = [str(r[0]) for r in (c.fetchall() or []) if r and r[0]]
            if labels:
                return labels
        except Exception:
            pass

    try:
        c.execute("""
            SELECT DISTINCT game_label
            FROM mr_player_match
            WHERE season_id=?
            ORDER BY game_label ASC
        """, (int(season_id),))
        labels = [str(r[0]) for r in (c.fetchall() or []) if r and r[0]]
        labels.sort(key=_ss_gl_sort_key)
        return labels
    except Exception:
        return []


# -----------------------------
# Role cache helpers
# -----------------------------
def _ss_ensure_hero_role_column():
    """
    Ensures hero_cache has hero_role column (safe for older DBs).
    """
    ensure_mr_api_tables()
    global c, conn
    if not _ss_table_exists("hero_cache"):
        return
    if _ss_col_exists("hero_cache", "hero_role"):
        return
    try:
        c.execute("ALTER TABLE hero_cache ADD COLUMN hero_role TEXT")
        conn.commit()
    except Exception:
        pass


def _ss_load_hero_roles_from_cache() -> dict[int, str]:
    """
    Returns {hero_id_int: role_str} from hero_cache.hero_role.
    Robust to hero_id formats like '1011' or 'hero_1011' by digits-only normalisation.
    """
    ensure_mr_api_tables()
    global c
    if not _ss_table_exists("hero_cache"):
        return {}
    if not _ss_col_exists("hero_cache", "hero_role"):
        return {}

    out: dict[int, str] = {}
    try:
        c.execute("""
            SELECT hero_id, hero_role
            FROM hero_cache
            WHERE hero_role IS NOT NULL AND hero_role <> ''
        """)
        for hid, role in (c.fetchall() or []):
            hid_s = str(hid or "").strip()
            hid_digits = _digits_only(hid_s) or hid_s
            if not hid_digits:
                continue
            try:
                hi = int(hid_digits)
            except Exception:
                continue

            rs = (str(role or "")).strip()
            if rs:
                out[hi] = rs
    except Exception:
        return {}

    return out

async def _ss_role_distribution(season_id: int) -> list[dict]:
    """
    Computes per-player role share based on mr_hero_segments seconds:
      - joins mr_player_match to exclude bots
      - maps hero_id -> role via hero_cache.hero_role
      - returns list of:
          {player_uid, v, d, s, total_seconds}
        where v/d/s are fractions summing to 1.0
    """
    ensure_mr_api_tables()
    global c

    if not (_ss_table_exists("mr_hero_segments") and _ss_table_exists("mr_player_match")):
        return []

    _ss_ensure_hero_role_column()

    role_map = _ss_load_hero_roles_from_cache()
    if not role_map and _allow_command_hero_cache_refresh():
        # Optional one-time refresh if explicitly enabled. Default is cache-only.
        refresh_fn = globals().get("refresh_hero_cache")
        if callable(refresh_fn):
            try:
                await refresh_fn(force=True)
            except Exception:
                pass
        role_map = _ss_load_hero_roles_from_cache()

    if not role_map:
        return []

    is_bot_col = _ss_col_exists("mr_player_match", "is_bot")
    where_bot = "AND COALESCE(pm.is_bot,0)=0" if is_bot_col else ""

    # seconds per player per hero
    try:
        c.execute(f"""
            SELECT hs.player_uid, hs.hero_id, SUM(COALESCE(hs.seconds,0)) AS sec
            FROM mr_hero_segments hs
            JOIN mr_player_match pm
              ON pm.season_id  = hs.season_id
             AND pm.match_uid  = hs.match_uid
             AND pm.game_label = hs.game_label
             AND pm.player_uid = hs.player_uid
            WHERE hs.season_id = ?
              {where_bot}
            GROUP BY hs.player_uid, hs.hero_id
            HAVING sec > 0
        """, (int(season_id),))
        rows = c.fetchall() or []
    except Exception:
        return []

    per = defaultdict(lambda: {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0, "unknown": 0.0})

    # First pass: normalise hero IDs and accumulate rows (don’t drop hero_####)
    parsed_rows = []
    heroes_seen = set()

    for uid, hid, sec in rows:
        if uid is None or hid is None:
            continue

        try:
            uid_i = int(uid)
        except Exception:
            continue

        hid_s = str(hid or "").strip()
        hid_digits = _digits_only(hid_s) or hid_s
        if not hid_digits:
            # keep track by marking unknown via sentinel (optional)
            continue

        try:
            hid_i = int(hid_digits)
        except Exception:
            continue

        seconds = float(sec or 0.0)
        if seconds <= 0:
            continue

        parsed_rows.append((uid_i, hid_i, seconds))
        heroes_seen.add(hid_i)

    if not parsed_rows:
        return []

    # If we have heroes in match data that do NOT have a valid role in cache, force refresh once
    missing_roles = [hid_i for hid_i in heroes_seen if (role_map.get(hid_i) or "").strip() not in ("Vanguard", "Duelist", "Strategist")]
    if missing_roles and _allow_command_hero_cache_refresh():
        refresh_fn = globals().get("refresh_hero_cache")
        if callable(refresh_fn):
            try:
                await refresh_fn(force=True)
            except Exception:
                pass
        role_map = _ss_load_hero_roles_from_cache()

    # Final pass: bucket seconds by role
    for uid_i, hid_i, seconds in parsed_rows:
        role = (role_map.get(hid_i) or "").strip()
        if role in ("Vanguard", "Duelist", "Strategist"):
            per[uid_i][role] += seconds
        else:
            per[uid_i]["unknown"] += seconds

    out = []
    for uid_i, bucket in per.items():
        known = float(bucket["Vanguard"] + bucket["Duelist"] + bucket["Strategist"])
        if known <= 0:
            continue
        v = bucket["Vanguard"] / known
        d = bucket["Duelist"] / known
        s = bucket["Strategist"] / known
        out.append({
            "player_uid": uid_i,
            "v": v,
            "d": d,
            "s": s,
            "total_seconds": int(round(known))
        })

    out.sort(key=lambda r: int(r.get("total_seconds", 0)), reverse=True)
    return out



# -----------------------------
# Existing-command summaries (wrappers)
# -----------------------------
def _ss_top_tierlist(season_id: int, top_n: int = SS_TOP_TIER) -> list[dict]:
    fn = globals().get("_hero_tierlist_rows_api")
    if not callable(fn):
        return []
    try:
        rows = fn(int(season_id), mode="humans") or []
    except Exception:
        return []
    rows = [r for r in rows if int(r.get("picks", 0) or 0) >= int(SS_TIER_MIN_PICKS)]
    rows.sort(key=lambda r: (float(r.get("win_pct", 0.0) or 0.0), int(r.get("picks", 0) or 0)), reverse=True)
    return rows[:max(1, int(top_n))]


def _ss_top_synergy(season_id: int, top_n: int = SS_TOP_SYNERGY) -> list[dict]:
    fn = globals().get("_dominant_hero_rows_for_synergy_api")
    if not callable(fn):
        return []
    try:
        dom_rows = fn(int(season_id), mode="humans") or []
    except Exception:
        return []

    team_heroes = defaultdict(list)
    team_votes = defaultdict(list)

    for match_uid, camp, hero_id, is_win in dom_rows:
        key = (str(match_uid), int(camp))
        team_heroes[key].append(int(hero_id))
        team_votes[key].append(int(is_win or 0))

    pair_games = defaultdict(int)
    pair_wins = defaultdict(int)

    for key, heroes in team_heroes.items():
        if len(heroes) < 2:
            continue
        votes = team_votes.get(key, [])
        team_won = 1 if (sum(votes) >= (len(votes) / 2.0)) else 0
        for a, b in combinations(heroes, 2):
            pair = (a, b) if a <= b else (b, a)
            pair_games[pair] += 1
            if team_won == 1:
                pair_wins[pair] += 1

    rows = []
    for (a, b), g in pair_games.items():
        if g < int(SS_SYNERGY_MIN_GAMES):
            continue
        w = int(pair_wins.get((a, b), 0))
        rows.append({"a": a, "b": b, "games": g, "wins": w, "win_pct": (w / g) * 100.0 if g else 0.0})

    rows.sort(key=lambda r: (float(r["win_pct"]), int(r["games"])), reverse=True)
    return rows[:max(1, int(top_n))]


def _ss_top_dominant(season_id: int, top_n: int = SS_TOP_DOMINANT) -> list[dict]:
    fn = globals().get("_get_top_dominant_hero_player_rows_api")
    if not callable(fn):
        return []
    try:
        rows = fn(int(season_id)) or []
    except Exception:
        return []
    return rows[:max(1, int(top_n))]


def _ss_top_bans(season_id: int, top_n: int = SS_TOP_BANS) -> list[dict]:
    ensure_mr_api_tables()
    global c
    if not _ss_table_exists("hero_bans"):
        return []
    try:
        c.execute("""
            SELECT hero_id, COUNT(*) AS n
            FROM hero_bans
            WHERE season_id=?
            GROUP BY hero_id
            ORDER BY n DESC
            LIMIT ?
        """, (int(season_id), int(top_n)))
        rows = c.fetchall() or []
    except Exception:
        return []
    return [{"hero_id": int(hid), "bans": int(n or 0)} for hid, n in rows]


# -----------------------------
# BOT HERO TOP 5 (MATCHES leaderboard_image bots EXACTLY)
# -----------------------------
def _ss_top_bot_heroes_like_leaderboard_image_bots(season_id: int, top_n: int = SS_TOP_BOT_HEROES) -> list[dict]:
    ensure_mr_api_tables()
    global c

    if not _ss_table_exists("mr_hero_segments"):
        return []
    if not _ss_table_exists("mr_player_match"):
        return []
    if not _ss_col_exists("mr_hero_segments", "is_bot"):
        return []
    if not _ss_col_exists("mr_player_match", "is_bot"):
        return []

    sec_by_hero = defaultdict(float)
    try:
        c.execute("""
            SELECT hero_id, seconds
            FROM mr_hero_segments
            WHERE season_id=? AND is_bot=1
        """, (int(season_id),))
        for hid, sec in (c.fetchall() or []):
            try:
                hh = int(hid)
            except Exception:
                continue
            sec_by_hero[hh] += float(sec or 0.0)
    except Exception:
        return []

    wins_losses_picks = {}
    try:
        c.execute("""
            SELECT
                hs.hero_id,
                SUM(CASE WHEN pm.is_win=1 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pm.is_win=0 THEN 1 ELSE 0 END) AS losses,
                COUNT(*) AS picks
            FROM (
                SELECT DISTINCT season_id, match_uid, game_label, player_uid, hero_id
                FROM mr_hero_segments
                WHERE season_id=? AND is_bot=1
            ) hs
            JOIN mr_player_match pm
              ON pm.season_id=hs.season_id
             AND pm.match_uid=hs.match_uid
             AND pm.game_label=hs.game_label
             AND pm.player_uid=hs.player_uid
             AND pm.is_bot=1
            WHERE pm.season_id=?
            GROUP BY hs.hero_id
        """, (int(season_id), int(season_id)))
        for hid, wins, losses, picks in (c.fetchall() or []):
            try:
                hh = int(hid)
            except Exception:
                continue
            wins_losses_picks[hh] = (int(wins or 0), int(losses or 0), int(picks or 0))
    except Exception:
        return []

    items = []
    all_heroes = set(sec_by_hero.keys()) | set(wins_losses_picks.keys())
    for hid in all_heroes:
        sec = float(sec_by_hero.get(hid, 0.0))
        wins, losses, picks = wins_losses_picks.get(hid, (0, 0, 0))
        if picks <= 0 and sec <= 0:
            continue
        winpct = (wins / picks) * 100.0 if picks > 0 else 0.0
        items.append({
            "hero_id": int(hid),
            "seconds": sec,
            "picks": int(picks),
            "wins": int(wins),
            "losses": int(losses),
            "win_pct": float(winpct),
        })

    items.sort(key=lambda r: (float(r["win_pct"]), int(r["picks"]), float(r["seconds"])), reverse=True)
    return items[:max(1, int(top_n))]


# -----------------------------
# Most versatile players (mr_hero_segments eligibility; shows avg hero time %)
# -----------------------------
def _ss_most_versatile_from_segments(season_id: int, top_n: int = SS_TOP_VERSATILE) -> list[dict]:
    ensure_mr_api_tables()
    global c

    if not _ss_table_exists("mr_hero_segments"):
        return []
    if not (_ss_table_exists("mr_player_match") and _ss_col_exists("mr_player_match", "is_bot")):
        return []

    sql = """
    WITH hs AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            hero_id,
            COALESCE(seconds,0) AS seconds
        FROM mr_hero_segments
        WHERE season_id = ?
    ),
    match_tot AS (
        SELECT
            season_id, match_uid, game_label, player_uid,
            SUM(seconds) AS total_sec
        FROM hs
        GROUP BY season_id, match_uid, game_label, player_uid
    ),
    joined AS (
        SELECT
            hs.player_uid,
            hs.hero_id,
            hs.seconds,
            mt.total_sec
        FROM hs
        JOIN match_tot mt
          ON mt.season_id  = hs.season_id
         AND mt.match_uid  = hs.match_uid
         AND mt.game_label = hs.game_label
         AND mt.player_uid = hs.player_uid
        JOIN mr_player_match pm
          ON pm.season_id  = hs.season_id
         AND pm.match_uid  = hs.match_uid
         AND pm.game_label = hs.game_label
         AND pm.player_uid = hs.player_uid
        WHERE COALESCE(pm.is_bot,0) = 0
    ),
    elig AS (
        SELECT player_uid, hero_id, seconds
        FROM joined
        WHERE seconds >= ?
          AND total_sec > 0
          AND (1.0 * seconds / total_sec) >= ?
    )
    SELECT player_uid, hero_id, SUM(seconds) AS sec_elig
    FROM elig
    GROUP BY player_uid, hero_id
    HAVING sec_elig > 0
    """
    try:
        c.execute(sql, (int(season_id), int(HERO_WIN_MIN_SECONDS), float(HERO_WIN_MIN_RATIO)))
        rows = c.fetchall() or []
    except Exception:
        return []

    per_player = defaultdict(lambda: defaultdict(int))
    for uid, hid, sec in rows:
        if uid is None or hid is None:
            continue
        per_player[int(uid)][int(hid)] += int(float(sec or 0))

    hero_counts = [len([1 for _, s in hero_map.items() if int(s) > 0]) for hero_map in per_player.values()]
    k_max = max(hero_counts) if hero_counts else 0
    if k_max <= 1:
        return []

    out = []
    for uid, hero_map in per_player.items():
        secs = [int(s) for s in hero_map.values() if int(s) > 0]
        total = sum(secs)
        if total <= 0:
            continue
        K = len(secs)
        if K < 2:
            continue

        probs = [s / total for s in secs]
        H = -sum(p * math.log(max(p, 1e-12)) for p in probs)
        Hmax = math.log(K)
        evenness = (H / Hmax) if Hmax > 0 else 0.0
        breadth = K / k_max
        score = 100.0 * evenness * breadth

        avg_share = 100.0 / K

        out.append({
            "player_uid": int(uid),
            "unique_heroes": int(K),
            "vers_pct": float(score),
            "avg_share": float(avg_share),
            "total_seconds": int(total)
        })

    out.sort(key=lambda r: (float(r["vers_pct"]), int(r["unique_heroes"]), int(r["total_seconds"])), reverse=True)
    return out[:max(1, int(top_n))]


# -----------------------------
# Core season computations
# -----------------------------
def _ss_seed_hist_from_prior_seasons(current_season_id: int, player_uids: set[int]) -> dict[int, list[int]]:
    """
    Returns {uid: [wins, games]} aggregated from prior seasons for these players.
    Excludes bots if mr_player_match.is_bot exists.
    Optionally limits to last N seasons via UPSET_PRIOR_SEASONS_BACK.
    """
    ensure_mr_api_tables()
    global c

    if not player_uids:
        return {}

    if not _ss_table_exists("mr_player_match"):
        return {}

    is_bot_col = _ss_col_exists("mr_player_match", "is_bot")
    where_bot = "AND COALESCE(is_bot,0)=0" if is_bot_col else ""

    # determine which seasons to include
    seasons_to_use = None
    if UPSET_PRIOR_SEASONS_BACK is not None:
        try:
            c.execute("""
                SELECT DISTINCT season_id
                FROM mr_player_match
                WHERE season_id < ?
                ORDER BY season_id DESC
                LIMIT ?
            """, (int(current_season_id), int(UPSET_PRIOR_SEASONS_BACK)))
            seasons_to_use = [int(r[0]) for r in (c.fetchall() or []) if r and r[0] is not None]
        except Exception:
            seasons_to_use = None

        if not seasons_to_use:
            return {}

    # chunk to avoid SQLite param limits
    uids = sorted({int(u) for u in player_uids})
    out = defaultdict(lambda: [0, 0])

    def _chunks(lst, n=400):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    for chunk in _chunks(uids, n=400):
        in_placeholders = ",".join(["?"] * len(chunk))

        if seasons_to_use is None:
            # all prior seasons
            sql = f"""
                SELECT player_uid,
                       SUM(CASE WHEN COALESCE(is_win,0)=1 THEN 1 ELSE 0 END) AS wins,
                       COUNT(*) AS games
                FROM mr_player_match
                WHERE season_id < ?
                  {where_bot}
                  AND player_uid IN ({in_placeholders})
                GROUP BY player_uid
            """
            params = [int(current_season_id)] + chunk
        else:
            s_placeholders = ",".join(["?"] * len(seasons_to_use))
            sql = f"""
                SELECT player_uid,
                       SUM(CASE WHEN COALESCE(is_win,0)=1 THEN 1 ELSE 0 END) AS wins,
                       COUNT(*) AS games
                FROM mr_player_match
                WHERE season_id IN ({s_placeholders})
                  {where_bot}
                  AND player_uid IN ({in_placeholders})
                GROUP BY player_uid
            """
            params = seasons_to_use + chunk

        try:
            c.execute(sql, tuple(params))
            for uid, wins, games in (c.fetchall() or []):
                try:
                    uid_i = int(uid)
                except Exception:
                    continue
                out[uid_i][0] += int(wins or 0)
                out[uid_i][1] += int(games or 0)
        except Exception:
            continue

    return dict(out)

def _ss_compute_core(season_id: int) -> dict | None:
    """
    Computes core Season Story stats for a season (humans only), including Biggest Upset.

    Enhancement:
      - Seeds Biggest Upset pre-game strength (hist) with prior-season win/loss history for the
        players who appear in the current season, so early-season upsets are not distorted by
        fresh 50/50 starts.

    Controls use the UPSET_* tuning globals:
      UPSET_SEED_FROM_PRIOR_SEASONS = True/False
      UPSET_PRIOR_SEASONS_BACK = int | None   # e.g. 3 for last 3 seasons, None for all prior seasons
    """
    ensure_mr_api_tables()
    global c

    if not _ss_table_exists("mr_player_match"):
        return None

    is_bot_col = _ss_col_exists("mr_player_match", "is_bot")
    where_bot = "AND COALESCE(is_bot,0)=0" if is_bot_col else ""

    # --- Pull all human player-match rows for this season ---
    try:
        c.execute(f"""
            SELECT game_label, match_uid, player_uid, camp, COALESCE(is_win,0) AS is_win
            FROM mr_player_match
            WHERE season_id=? {where_bot}
        """, (int(season_id),))
        rows = c.fetchall() or []
    except Exception:
        return None

    if not rows:
        return None

    games = defaultdict(lambda: defaultdict(list))  # games[game_label][camp] = [(uid, is_win), ...]
    players = set()
    p_games = defaultdict(int)
    p_wins = defaultdict(int)

    for gl, mu, uid, camp, is_win in rows:
        camp_i = _ss_norm_side(camp)
        if camp_i not in (0, 1):
            continue
        if uid is None:
            continue

        uid = int(uid)
        gl = str(gl)
        w = int(is_win or 0)

        games[gl][camp_i].append((uid, w))
        players.add(uid)
        p_games[uid] += 1
        p_wins[uid] += w

    ordered = _ss_get_ordered_game_labels(season_id)
    ordered = [gl for gl in ordered if gl in games]
    if not ordered:
        ordered = sorted(games.keys(), key=_ss_gl_sort_key)

    total_games = len(ordered)
    unique_players = len(players)

    # --- Date range ---
    date_range = ""
    if _ss_table_exists("mr_match_meta") and _ss_col_exists("mr_match_meta", "match_time_utc"):
        try:
            c.execute("""
                SELECT MIN(match_time_utc), MAX(match_time_utc)
                FROM mr_match_meta
                WHERE season_id=? AND match_time_utc IS NOT NULL AND match_time_utc <> ''
            """, (int(season_id),))
            dtmin, dtmax = (c.fetchone() or (None, None))
            if dtmin and dtmax:
                date_range = f"{_ss_safe_iso_to_brisbane(dtmin)} – {_ss_safe_iso_to_brisbane(dtmax)}"
        except Exception:
            pass

    # --- Uneven games + underdog wins ---
    uneven_games = 0
    underdog_wins = 0
    for gl in ordered:
        t0 = games[gl].get(0, [])
        t1 = games[gl].get(1, [])
        if not t0 or not t1:
            continue
        n0, n1 = len(t0), len(t1)
        if n0 != n1:
            uneven_games += 1
            w0 = 1 if sum(w for _, w in t0) >= (n0 / 2.0) else 0
            w1 = 1 if sum(w for _, w in t1) >= (n1 / 2.0) else 0
            if (n0 < n1 and w0 == 1) or (n1 < n0 and w1 == 1):
                underdog_wins += 1

    # --- Most active ---
    most_active = [(uid, int(p_games[uid]), int(p_wins[uid])) for uid in players]
    most_active.sort(key=lambda t: (t[1], t[2]), reverse=True)
    most_active = most_active[:SS_TOP_ACTIVE]

    # --- Most improved (first half vs second half) ---
    half = max(1, total_games // 2)
    first_set = set(ordered[:half])
    first = defaultdict(lambda: [0, 0])   # uid -> [wins, games]
    second = defaultdict(lambda: [0, 0])  # uid -> [wins, games]

    for gl in ordered:
        for camp_i in (0, 1):
            for uid, w in games[gl].get(camp_i, []):
                if gl in first_set:
                    first[uid][1] += 1
                    first[uid][0] += int(w)
                else:
                    second[uid][1] += 1
                    second[uid][0] += int(w)

    improved = []
    for uid in players:
        w1, g1 = first[uid]
        w2, g2 = second[uid]
        if g1 < SS_MIN_HALF_GAMES or g2 < SS_MIN_HALF_GAMES:
            continue
        p1 = (w1 / g1) * 100.0
        p2 = (w2 / g2) * 100.0
        improved.append((uid, (p2 - p1), p1, p2))
    improved.sort(key=lambda t: (t[1], t[3]), reverse=True)
    improved = improved[:SS_TOP_IMPROVED]

    # --- Best duos ---
    duo = defaultdict(lambda: [0, 0])  # (a,b) -> [wins_together, games_together]
    for gl in ordered:
        for camp_i in (0, 1):
            team = games[gl].get(camp_i, [])
            if len(team) < 2:
                continue
            team_uids = sorted({uid for uid, _ in team})
            team_won = 1 if sum(w for _, w in team) >= (len(team) / 2.0) else 0
            for i in range(len(team_uids)):
                for j in range(i + 1, len(team_uids)):
                    a, b = team_uids[i], team_uids[j]
                    duo[(a, b)][1] += 1
                    if team_won == 1:
                        duo[(a, b)][0] += 1

    best_duos = []
    for (a, b), (w, g) in duo.items():
        if g < SS_MIN_DUO_GAMES:
            continue
        best_duos.append((a, b, (w / g) * 100.0, w, g))
    best_duos.sort(key=lambda t: (t[2], t[4]), reverse=True)
    best_duos = best_duos[:SS_TOP_DUOS]

    # --- Biggest Upset ---
    hist = defaultdict(lambda: [0, 0])  # uid -> [wins_so_far, games_so_far]

    # Seed from prior seasons (optional)
    seed_enabled = bool(globals().get("UPSET_SEED_FROM_PRIOR_SEASONS", True))
    seasons_back = globals().get("UPSET_PRIOR_SEASONS_BACK", 3)  # int or None

    if seed_enabled and players:
        try:
            # determine which seasons to include
            seasons_to_use = None
            if seasons_back is not None:
                c.execute("""
                    SELECT DISTINCT season_id
                    FROM mr_player_match
                    WHERE season_id < ?
                    ORDER BY season_id DESC
                    LIMIT ?
                """, (int(season_id), int(seasons_back)))
                seasons_to_use = [int(r[0]) for r in (c.fetchall() or []) if r and r[0] is not None]
                if not seasons_to_use:
                    seasons_to_use = []

            uids = sorted({int(u) for u in players})

            def _chunks(lst, n=400):
                for i in range(0, len(lst), n):
                    yield lst[i:i + n]

            for chunk in _chunks(uids, n=400):
                uid_ph = ",".join(["?"] * len(chunk))

                if seasons_back is None:
                    # all prior seasons
                    sql = f"""
                        SELECT player_uid,
                               SUM(CASE WHEN COALESCE(is_win,0)=1 THEN 1 ELSE 0 END) AS wins,
                               COUNT(*) AS games
                        FROM mr_player_match
                        WHERE season_id < ?
                          {where_bot}
                          AND player_uid IN ({uid_ph})
                        GROUP BY player_uid
                    """
                    params = [int(season_id)] + chunk
                else:
                    if not seasons_to_use:
                        continue
                    s_ph = ",".join(["?"] * len(seasons_to_use))
                    sql = f"""
                        SELECT player_uid,
                               SUM(CASE WHEN COALESCE(is_win,0)=1 THEN 1 ELSE 0 END) AS wins,
                               COUNT(*) AS games
                        FROM mr_player_match
                        WHERE season_id IN ({s_ph})
                          {where_bot}
                          AND player_uid IN ({uid_ph})
                        GROUP BY player_uid
                    """
                    params = seasons_to_use + chunk

                c.execute(sql, tuple(params))
                for uid, wins, games_ct in (c.fetchall() or []):
                    try:
                        uid_i = int(uid)
                    except Exception:
                        continue
                    hist[uid_i][0] += int(wins or 0)
                    hist[uid_i][1] += int(games_ct or 0)
        except Exception:
            pass

    biggest = None

    for gl in ordered:
        team0 = [uid for uid, _ in games[gl].get(0, [])]
        team1 = [uid for uid, _ in games[gl].get(1, [])]
        if not team0 or not team1:
            continue

        def pre_pct(uid: int) -> float:
            w, g = hist[uid]
            if UPSET_USE_SMOOTHED_PREWIN:
                return (w + 0.5 * UPSET_SMOOTH_PRIOR_GAMES) / (g + UPSET_SMOOTH_PRIOR_GAMES)
            return (w / g) if g > 0 else 0.50

        base0 = sum(pre_pct(u) for u in team0) / max(1, len(team0))
        base1 = sum(pre_pct(u) for u in team1) / max(1, len(team1))

        # Apply the standard uneven-team penalty.
        n0, n1 = len(team0), len(team1)
        penalty = min(UPSET_SIZE_PENALTY_CAP, UPSET_SIZE_PENALTY_PER_PLAYER * abs(n0 - n1))
        adj0, adj1 = base0, base1
        if n0 < n1:
            adj0 = max(0.0, base0 - penalty)
        elif n1 < n0:
            adj1 = max(0.0, base1 - penalty)

        # determine winner from actual match results
        t0 = games[gl].get(0, [])
        t1 = games[gl].get(1, [])
        w0 = 1 if sum(w for _, w in t0) >= (len(t0) / 2.0) else 0
        w1 = 1 if sum(w for _, w in t1) >= (len(t1) / 2.0) else 0
        winner = 0 if w0 == 1 else (1 if w1 == 1 else None)

        if winner is None:
            # still advance hist games if we cannot determine winner
            for camp_i in (0, 1):
                for uid, _w in games[gl].get(camp_i, []):
                    hist[uid][1] += 1
            continue

        # favourite vs underdog
        if adj0 >= adj1:
            fav_camp, dog_camp = 0, 1
            fav, dog = adj0, adj1
        else:
            fav_camp, dog_camp = 1, 0
            fav, dog = adj1, adj0

        if winner == dog_camp:
            gap = (fav - dog) * 100.0
            cand = {
                "game_label": gl,
                "fav_camp": fav_camp,
                "dog_camp": dog_camp,
                "fav_pct": fav * 100.0,
                "dog_pct": dog * 100.0,
                "gap": gap,
                "team0_uids": list(team0),
                "team1_uids": list(team1),
            }
            if biggest is None or cand["gap"] > biggest["gap"]:
                biggest = cand

        # advance hist using actual winner
        for camp_i in (0, 1):
            for uid, _w in games[gl].get(camp_i, []):
                hist[uid][1] += 1
                if camp_i == winner:
                    hist[uid][0] += 1

    return {
        "total_games": total_games,
        "unique_players": unique_players,
        "date_range": date_range,
        "uneven_games": uneven_games,
        "underdog_wins": underdog_wins,
        "most_active": most_active,
        "improved": improved,
        "best_duos": best_duos,
        "biggest_upset": biggest,
    }

# -----------------------------
# Render helpers: ternary plot
# -----------------------------
def _ss_draw_role_ternary_plot(draw: "ImageDraw.ImageDraw",
                              x: int, y: int, width: int, height: int,
                              role_rows: list[dict],
                              player_names: dict[int, str],
                              body_font: "ImageFont.ImageFont",
                              LH: int,
                              accent, text, muted, line):
    """
    Draws a role ternary plot in the provided rectangle.
    v (Vanguard) at top, d (Duelist) bottom-left, s (Strategist) bottom-right.
    """
    # title + separator
    draw.text((x, y), SS_ROLE_PLOT_TITLE, font=body_font, fill=accent)
    y_sep = y + LH
    draw.line([(x, y_sep), (x + width, y_sep)], fill=line, width=2)

    y_plot = y_sep + SS_ROLE_PLOT_TOP_PAD

    # compute plot height based on actual top offset (more robust than LH+14)
    h_plot = max(180, height - (y_plot - y) - 2)

    if not role_rows:
        draw.text((x, y_plot), "No role distribution data available yet.", font=body_font, fill=text)
        return

    # Fit an equilateral triangle inside (width x h_plot)
    sqrt3 = math.sqrt(3.0)
    side = min(float(width), float(h_plot) * 2.0 / sqrt3)
    tri_h = side * sqrt3 / 2.0

    # center triangle within the plot box
    x_left = float(x) + (float(width) - side) / 2.0
    y_top = float(y_plot) + (float(h_plot) - tri_h) / 2.0
    y_bottom = y_top + tri_h

    A = (x_left + side / 2.0, y_top)        # Vanguard
    B = (x_left, y_bottom)                  # Duelist
    C = (x_left + side, y_bottom)           # Strategist

    def mix(P, Q, t: float):
        return (t * P[0] + (1.0 - t) * Q[0], t * P[1] + (1.0 - t) * Q[1])

    # grid lines
    grid_col = (70, 70, 90)
    for t in SS_ROLE_GRID_STEPS:
        # v = t  (parallel to base BC): between AB and AC
        p1 = mix(A, B, t)
        p2 = mix(A, C, t)
        draw.line([p1, p2], fill=grid_col, width=1)

        # d = t  (parallel to AC): between AB and BC
        p3 = mix(B, A, t)
        p4 = mix(B, C, t)
        draw.line([p3, p4], fill=grid_col, width=1)

        # s = t  (parallel to AB): between AC and BC
        p5 = mix(C, A, t)
        p6 = mix(C, B, t)
        draw.line([p5, p6], fill=grid_col, width=1)

    # triangle outline
    draw.line([A, B], fill=muted, width=3)
    draw.line([B, C], fill=muted, width=3)
    draw.line([C, A], fill=muted, width=3)

    # axis labels
    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    lab_v = "Vanguard"
    lab_d = "Duelist"
    lab_s = "Strategist"

    draw.text((A[0] - _tw(lab_v) / 2.0, A[1] - LH - 4), lab_v, font=body_font, fill=accent)
    draw.text((B[0] - _tw(lab_d) / 2.0, B[1] + 6), lab_d, font=body_font, fill=accent)
    draw.text((C[0] - _tw(lab_s) / 2.0, C[1] + 6), lab_s, font=body_font, fill=accent)

    # dot plotting (with small cycling label offsets)
    offsets = [(10, -14), (10, 4), (-10, -14), (-10, 4), (14, -6), (-14, -6)]

    for idx, r in enumerate(role_rows):
        uid = int(r.get("player_uid", 0))
        v = float(r.get("v", 0.0))
        d = float(r.get("d", 0.0))
        s = float(r.get("s", 0.0))

        # barycentric -> cartesian
        px = d * B[0] + s * C[0] + v * A[0]
        py = d * B[1] + s * C[1] + v * A[1]

        rr = SS_ROLE_DOT_R
        draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=accent, outline=(0, 0, 0), width=1)

        name = _ss_clip(player_names.get(uid, f"UID_{uid}"), SS_ROLE_LABEL_MAX)
        dx, dy = offsets[idx % len(offsets)]
        tx = px + dx
        ty = py + dy

        # keep labels within plot area bounds (basic clamp)
        tx = max(float(x), min(tx, float(x + width) - _tw(name) - 2.0))
        ty = max(float(y_plot), min(ty, float(y_plot + h_plot) - LH))

        draw.text((tx, ty), name, font=body_font, fill=text)


# -----------------------------
# Render image
# -----------------------------
def _ss_render(season_id: int,
               core: dict,
               player_names: dict[int, str],
               hero_names: dict[int, str],
               versatile: list[dict],
               bot_heroes: list[dict],
               synergy: list[dict],
               dominant: list[dict],
               tier: list[dict],
               bans: list[dict],
               role_rows: list[dict]) -> io.BytesIO:

    if Image is None:
        raise RuntimeError("PIL not available")

    W, H = 1850, 1380
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    try:
        fonts = get_fonts()
        if isinstance(fonts, tuple) and len(fonts) >= 2:
            body_font = fonts[0]
            title_font = fonts[1]
        else:
            body_font = ImageFont.load_default()
            title_font = ImageFont.load_default()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)
    draw.text((pad * 2, int(pad * 1.35)), f"Season Story — Season {season_id}", font=title_font, fill=accent)

    subtitle_parts = [
        f"Games: {core.get('total_games', 0)}",
        f"Players: {core.get('unique_players', 0)}",
        f"Uneven: {core.get('uneven_games', 0)} (Underdog wins: {core.get('underdog_wins', 0)})",
    ]
    if core.get("date_range"):
        subtitle_parts.append(f"Dates: {core['date_range']}")
    draw.text((pad * 2, int(pad * 2.6)), "  •  ".join(subtitle_parts), font=body_font, fill=muted)

    left_x = pad * 2
    right_x = int(W * 0.54)
    top_y = int(pad * 3.95)
    LH = 28
    SEC_W = 820

    def _tw(s: str) -> float:
        try:
            return float(draw.textlength(s, font=body_font))
        except Exception:
            return float(len(s) * 9)

    def _fit(s: str, max_w: int) -> str:
        if _tw(s) <= max_w:
            return s
        t = s
        while t and _tw(t + "…") > max_w:
            t = t[:-1]
        return (t + "…") if t else "…"

    def section(x: int, y: int, title_s: str, lines: list[str], width: int = SEC_W) -> int:
        draw.text((x, y), title_s, font=body_font, fill=accent)
        y += LH
        draw.line([(x, y), (x + width, y)], fill=line, width=2)
        y += 8
        for ln in lines:
            draw.text((x, y), _fit(ln, width), font=body_font, fill=text)
            y += LH
        return y + 10

    def wrap_names(prefix: str, uids: list[int], max_w: int, max_lines: int = 3) -> list[str]:
        if not uids:
            return [_fit(prefix + "—", max_w)]
        prefix2 = " " * len(prefix)
        tokens = [_ss_clip(player_names.get(int(u), f"UID_{u}"), 12) for u in uids]
        lines, cur, used = [], prefix, 0
        for t in tokens:
            add = (", " + t) if used > 0 else t
            if _tw(cur + add) > max_w and used > 0:
                lines.append(_fit(cur, max_w))
                if len(lines) >= max_lines:
                    break
                cur = prefix2 + t
                used = 1
            else:
                cur += add
                used += 1
        if len(lines) < max_lines and cur.strip():
            lines.append(_fit(cur, max_w))
        remaining = max(0, len(tokens) - sum(len([p for p in ln.split(",") if p.strip()]) for ln in lines))
        if remaining > 0 and lines:
            suffix = f" +{remaining}"
            if _tw(lines[-1] + suffix) <= max_w:
                lines[-1] += suffix
        return lines[:max_lines]

    # LEFT
    yL = top_y

    lines = []
    for uid, g, w in (core.get("most_active") or []):
        nm = player_names.get(int(uid), f"UID_{uid}")
        lines.append(f"{_ss_clip(nm, 22)} — {int(g)} games ({int(w)}-{int(g)-int(w)})")
    if not lines:
        lines = ["No human matches recorded yet."]
    yL = section(left_x, yL, f"Most Active Players (Top {SS_TOP_ACTIVE})", lines)

    lines = []
    if versatile:
        for i, r in enumerate(versatile[:SS_TOP_VERSATILE], start=1):
            uid = int(r["player_uid"])
            nm = player_names.get(uid, f"UID_{uid}")
            lines.append(
                f"{i}. {_ss_clip(nm, 20)} — {int(r['unique_heroes'])} heroes — {float(r['vers_pct']):.1f}%"
                f" (avg {float(r['avg_share']):.1f}% per hero)"
            )
    else:
        lines = ["No versatility results yet (needs eligible hero segments)."]
    yL = section(left_x, yL, f"Most Versatile Players (Top {SS_TOP_VERSATILE})", lines)

    lines = []
    if bot_heroes:
        for i, r in enumerate(bot_heroes[:SS_TOP_BOT_HEROES], start=1):
            hid = int(r.get("hero_id", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            picks = int(r.get("picks", 0))
            wins = int(r.get("wins", 0))
            losses = int(r.get("losses", 0))
            wp = float(r.get("win_pct", 0.0))
            lines.append(f"{i}. {_ss_clip(hn, 24)} — {wp:.1f}% ({wins}/{losses}) • {picks} picks")
    else:
        lines = ["No bot hero data available yet."]
    yL = section(left_x, yL, f"Top Bot Heroes by Win% (Top {SS_TOP_BOT_HEROES})", lines)

    imp = core.get("improved") or []
    lines = []
    if imp:
        for rank, (uid, delta, p1, p2) in enumerate(imp, start=1):
            nm = player_names.get(int(uid), f"UID_{uid}")
            sign = "+" if float(delta) >= 0 else ""
            lines.append(f"{rank}. {_ss_clip(nm, 20)} — {sign}{float(delta):.1f}% ({float(p1):.1f}% → {float(p2):.1f}%)")
    else:
        lines = [f"Not enough games per half (min {SS_MIN_HALF_GAMES} each)."]
    yL = section(left_x, yL, f"Most Improved (Top {SS_TOP_IMPROVED})", lines)

    lines = []
    if synergy:
        for i, r in enumerate(synergy[:SS_TOP_SYNERGY], start=1):
            a = int(r["a"]); b = int(r["b"])
            an = hero_names.get(a) or "Unknown Hero"
            bn = hero_names.get(b) or "Unknown Hero"
            lines.append(f"{i}. {_ss_clip(an, 18)} + {_ss_clip(bn, 18)} — {float(r['win_pct']):.1f}% ({int(r['wins'])}/{int(r['games'])})")
    else:
        lines = ["No synergy results available yet."]
    yL = section(left_x, yL, f"Hero Synergy (Top {SS_TOP_SYNERGY})", lines)

    lines = []
    if dominant:
        for i, r in enumerate(dominant[:SS_TOP_DOMINANT], start=1):
            hid = int(r.get("hero_id", 0))
            uid = int(r.get("player_uid", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            pn = player_names.get(uid, f"UID_{uid}")
            wp = float(r.get("win_pct", 0.0))
            wins = int(r.get("wins", 0))
            matches = int(r.get("matches", 0))
            lines.append(f"{i}. {_ss_clip(hn, 18)} — {_ss_clip(pn, 16)} — {wp:.1f}% ({wins}/{matches})")
    else:
        lines = ["No dominant hero results available yet."]
    yL = section(left_x, yL, f"Most Dominant Heroes (Top {SS_TOP_DOMINANT})", lines)

    # RIGHT
    yR = top_y

    du = core.get("best_duos") or []
    lines = []
    if du:
        for rank, (a, b, wp, w, g) in enumerate(du, start=1):
            na = player_names.get(int(a), f"UID_{a}")
            nb = player_names.get(int(b), f"UID_{b}")
            lines.append(f"{rank}. {_ss_clip(na, 14)} + {_ss_clip(nb, 14)} — {float(wp):.1f}% ({int(w)}/{int(g)})")
    else:
        lines = [f"No duos meet min games together ({SS_MIN_DUO_GAMES})."]
    yR = section(right_x, yR, f"Best Duos (Top {SS_TOP_DUOS}, min {SS_MIN_DUO_GAMES})", lines)

    lines = []
    if tier:
        for i, r in enumerate(tier[:SS_TOP_TIER], start=1):
            hid = int(r.get("hero_id", 0))
            hn = hero_names.get(hid) or "Unknown Hero"
            picks = int(r.get("picks", 0) or 0)
            wins = int(r.get("wins", 0) or 0)
            wp = float(r.get("win_pct", 0.0) or 0.0)
            lines.append(f"{i}. {_ss_clip(hn, 22)} — {wp:.1f}% ({wins}/{picks})")
    else:
        lines = [f"No heroes meet min {SS_TIER_MIN_PICKS} eligible picks yet."]
    yR = section(right_x, yR, f"Hero Tier List (Top {SS_TOP_TIER}, min {SS_TIER_MIN_PICKS})", lines)

    lines = []
    if bans:
        for r in bans[:SS_TOP_BANS]:
            hid = int(r["hero_id"])
            hn = hero_names.get(hid) or "Unknown Hero"
            lines.append(f"• {_ss_clip(hn, 28)} — {int(r['bans'])} bans")
    else:
        lines = ["No ban data recorded yet."]
    yR = section(right_x, yR, f"Most Banned Heroes (Top {SS_TOP_BANS})", lines)

    upset = core.get("biggest_upset")
    if upset:
        gl = str(upset.get("game_label", "Unknown"))
        fav_c = int(upset.get("fav_camp", -1))
        dog_c = int(upset.get("dog_camp", -1))
        dog_pct = float(upset.get("dog_pct", 0.0))
        fav_pct = float(upset.get("fav_pct", 0.0))

        lines = [
            f"{gl} — Underdog win (Team {dog_c} beat Team {fav_c})",
            f"Pre-game strength: {dog_pct:.1f}% vs {fav_pct:.1f}%",
        ]
        lines.extend(wrap_names("T0: ", upset.get("team0_uids", []) or [], SEC_W, max_lines=3))
        lines.extend(wrap_names("T1: ", upset.get("team1_uids", []) or [], SEC_W, max_lines=3))
    else:
        lines = ["No upsets yet (needs enough pre-game history)."]
    yR = section(right_x, yR, "Biggest Upset (pre-game strength)", lines)

    # Role Distribution plot uses remaining right-column space
    bottom_limit = H - pad - 78
    remaining = max(0, bottom_limit - yR)
    if remaining >= 220:
        _ss_draw_role_ternary_plot(
            draw=draw,
            x=right_x,
            y=yR,
            width=SEC_W,
            height=remaining,
            role_rows=role_rows,
            player_names=player_names,
            body_font=body_font,
            LH=LH,
            accent=accent,
            text=text,
            muted=muted,
            line=line
        )

    footer = "Bot section matches !leaderboard_image bots (bot hero performance)."
    draw.text((pad * 2, H - pad - 52), _fit(footer, W - pad * 4), font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# -----------------------------
# Build image end-to-end
# -----------------------------
async def _ss_build_image(season_id: int):
    core = _ss_compute_core(season_id)
    if not core:
        return None

    versatile = _ss_most_versatile_from_segments(season_id, top_n=SS_TOP_VERSATILE)
    bot_heroes = _ss_top_bot_heroes_like_leaderboard_image_bots(season_id, top_n=SS_TOP_BOT_HEROES)
    synergy = _ss_top_synergy(season_id, top_n=SS_TOP_SYNERGY)
    dominant = _ss_top_dominant(season_id, top_n=SS_TOP_DOMINANT)
    tier = _ss_top_tierlist(season_id, top_n=SS_TOP_TIER)
    bans = _ss_top_bans(season_id, top_n=SS_TOP_BANS)

    # Role distribution data (humans only)
    role_rows = await _ss_role_distribution(season_id)

    # Resolve player names required
    uids = set()
    for uid, _g, _w in (core.get("most_active") or []):
        uids.add(int(uid))
    for uid, *_ in (core.get("improved") or []):
        uids.add(int(uid))
    for a, b, *_ in (core.get("best_duos") or []):
        uids.add(int(a)); uids.add(int(b))
    if core.get("biggest_upset"):
        for u in (core["biggest_upset"].get("team0_uids", []) or []):
            uids.add(int(u))
        for u in (core["biggest_upset"].get("team1_uids", []) or []):
            uids.add(int(u))
    for r in (versatile or []):
        uids.add(int(r["player_uid"]))
    for r in (dominant or []):
        try:
            uids.add(int(r.get("player_uid", 0)))
        except Exception:
            pass
    for r in (role_rows or []):
        try:
            uids.add(int(r.get("player_uid", 0)))
        except Exception:
            pass

    player_names = {uid: _ss_player_name(season_id, uid) for uid in uids}

    # Resolve hero names required
    hero_ids = set()

    for r in bot_heroes or []:
        hero_ids.add(int(r.get("hero_id", 0)))

    for r in tier or []:
        hero_ids.add(int(r.get("hero_id", 0)))
    for r in synergy or []:
        hero_ids.add(int(r.get("a", 0)))
        hero_ids.add(int(r.get("b", 0)))
    for r in dominant or []:
        hero_ids.add(int(r.get("hero_id", 0)))
    for r in bans or []:
        hero_ids.add(int(r.get("hero_id", 0)))

    hero_names = {}
    hero_ids = {hid for hid in hero_ids if hid}
    if hero_ids:
        ids_sorted = sorted(hero_ids)
        results = await asyncio.gather(*[get_hero_name(str(h)) for h in ids_sorted], return_exceptions=True)
        for hid, nm in zip(ids_sorted, results):
            if isinstance(nm, str) and nm.strip():
                hero_names[int(hid)] = nm
            else:
                hero_names[int(hid)] = "Unknown Hero"

    return _ss_render(
        season_id=season_id,
        core=core,
        player_names=player_names,
        hero_names=hero_names,
        versatile=versatile,
        bot_heroes=bot_heroes,
        synergy=synergy,
        dominant=dominant,
        tier=tier,
        bans=bans,
        role_rows=role_rows
    )


# -----------------------------
# Command
# -----------------------------
try:
    bot.remove_command("season_story")
except Exception:
    pass


@bot.command(name="season_story")
async def season_story(ctx):
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    buf = await _ss_build_image(season_id)
    if buf is None:
        await ctx.send("No season data found yet. Import matches first with `!submit_match`.")
        return

    await ctx.send(file=discord.File(fp=buf, filename=f"season_story_s{season_id}.png"))

# ============================================================================================================
# !role_distribution — 3 bar charts (Vanguard / Duelist / Strategist)
# Uses the same maths as Season Story role distribution (via _ss_role_distribution()).
# ============================================================================================================

import io
import math
from PIL import Image, ImageDraw, ImageFont

def _rd_role_color(role_label: str):
    # Subtle per-role colours (keeps Season Story palette feel)
    if role_label == "Vanguard":
        return (90, 170, 255)
    if role_label == "Duelist":
        return (255, 110, 110)
    if role_label == "Strategist":
        return (120, 230, 150)
    return (255, 215, 0)

def _rd_text_w(draw: "ImageDraw.ImageDraw", s: str, font: "ImageFont.ImageFont") -> float:
    try:
        return float(draw.textlength(s, font=font))
    except Exception:
        return float(len(s) * 9)

def _rd_line_h(font: "ImageFont.ImageFont") -> int:
    try:
        b = font.getbbox("Ag")
        return int((b[3] - b[1]) + 6)
    except Exception:
        return 26

def _rd_draw_rotated_text(base_img: Image.Image,
                          text: str,
                          font: "ImageFont.ImageFont",
                          fill,
                          x: int,
                          y: int,
                          angle: float = -45.0):
    if not text:
        return
    # create a tight RGBA label image, rotate, then paste using alpha mask
    try:
        tmp = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        dtmp = ImageDraw.Draw(tmp)
        bbox = dtmp.textbbox((0, 0), text, font=font)
        w = max(1, int(bbox[2] - bbox[0] + 2))
        h = max(1, int(bbox[3] - bbox[1] + 2))

        label = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(label)
        dl.text((0, 0), text, font=font, fill=fill)

        rot = label.rotate(angle, expand=True, resample=Image.BICUBIC)
        base_img.paste(rot, (int(x), int(y)), rot)
    except Exception:
        # fallback (non-rotated) if anything goes wrong
        try:
            d = ImageDraw.Draw(base_img)
            d.text((x, y), text, font=font, fill=fill)
        except Exception:
            pass

def _rd_render_role_bar_chart(*,
                             season_id: int,
                             role_label: str,
                             role_key: str,   # "v" | "d" | "s"
                             role_rows: list[dict],
                             player_names: dict[int, str]) -> io.BytesIO:
    # --- canvas / palette (match Season Story vibe) ---
    W, H = 1850, 900
    pad = 26

    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    # --- dynamic font sizing based on player count ---
    n = len(role_rows)
    if n <= 14:
        body_pt, title_pt, label_pt = 20, 34, 16
    elif n <= 22:
        body_pt, title_pt, label_pt = 18, 32, 14
    else:
        body_pt, title_pt, label_pt = 16, 30, 12

    try:
        body_font, title_font = get_fonts(body_pt=body_pt, title_pt=title_pt)
        label_font, _ = get_fonts(body_pt=label_pt, title_pt=label_pt)
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    LH = _rd_line_h(body_font)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # card background
    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=24, fill=card, outline=line, width=2)

    # title
    title = f"Role Distribution — {role_label} (Season {season_id})"
    draw.text((pad * 2, pad * 2), title, font=title_font, fill=accent)

    # subtitle
    sub = "Y-axis: % of time played (normalised across Vanguard/Duelist/Strategist per player)"
    draw.text((pad * 2, pad * 2 + _rd_line_h(title_font)), sub, font=body_font, fill=muted)

    # plot area
    top_y = pad * 2 + _rd_line_h(title_font) + LH + 28
    left_x = pad * 2 + 70
    right_x = W - pad * 2
    bottom_y = H - pad * 2 - 190  # reserve for rotated labels

    plot_w = max(10, right_x - left_x)
    plot_h = max(10, bottom_y - top_y)

    # axes
    draw.line([(left_x, top_y), (left_x, bottom_y)], fill=muted, width=3)
    draw.line([(left_x, bottom_y), (right_x, bottom_y)], fill=muted, width=3)

    # y grid + ticks
    ticks = [0, 20, 40, 60, 80, 100]
    for t in ticks:
        yy = bottom_y - (t / 100.0) * plot_h
        draw.line([(left_x, yy), (right_x, yy)], fill=line, width=1)
        lab = f"{t}%"
        tw = _rd_text_w(draw, lab, body_font)
        draw.text((left_x - tw - 12, yy - (LH / 2)), lab, font=body_font, fill=muted)

    if n <= 0:
        draw.text((left_x + 20, top_y + 20), "No role distribution data available yet.", font=body_font, fill=text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    # x layout
    space = plot_w / float(n)
    bar_w = int(max(10, min(64, space * 0.62)))
    bar_fill = _rd_role_color(role_label)

    # data in consistent order (role_rows already sorted by total_seconds desc)
    names = []
    pcts = []
    for r in role_rows:
        uid = int(r.get("player_uid", 0))
        nm = _ss_clip(player_names.get(uid, f"UID_{uid}"), 14)
        frac = float(r.get(role_key, 0.0) or 0.0)
        pct = max(0.0, min(100.0, frac * 100.0))
        names.append(nm)
        pcts.append(pct)

    # draw bars
    for i, (nm, pct) in enumerate(zip(names, pcts)):
        cx = left_x + (i + 0.5) * space
        x0 = int(cx - bar_w / 2)
        x1 = int(cx + bar_w / 2)

        h = (pct / 100.0) * plot_h
        y1 = bottom_y
        y0 = int(bottom_y - h)

        # bar
        draw.rectangle([x0, y0, x1, y1], fill=bar_fill, outline=line, width=2)

        # percent label
        p_lab = f"{pct:.1f}%" if n <= 18 else f"{pct:.0f}%"
        tw = _rd_text_w(draw, p_lab, label_font)
        draw.text((int(cx - tw / 2), max(top_y, y0 - LH)), p_lab, font=label_font, fill=text)

        # rotated name label
        # place roughly below x-axis; angle helps when many players
        _rd_draw_rotated_text(
            base_img=img,
            text=nm,
            font=label_font,
            fill=muted,
            x=int(cx - 10),
            y=int(bottom_y + 18),
            angle=-45.0
        )

    # footer note
    foot = "Note: Percentages use the same Season Story role-share logic (mr_hero_segments seconds; humans only)."
    draw.text((pad * 2, H - pad * 2 - 40), _ss_clip(foot, 120), font=body_font, fill=muted)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# -----------------------------
# Command: !role_distribution
# -----------------------------
try:
    bot.remove_command("role_distribution")
except Exception:
    pass


@bot.command(name="role_distribution")
async def role_distribution(ctx):
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    role_rows = await _ss_role_distribution(season_id)
    if not role_rows:
        await ctx.send(
            "No role distribution data available yet.\n"
            "Ensure you have mr_hero_segments imported, and hero roles are present in hero_cache (refresh_hero_cache / !hero_role_set)."
        )
        return

    uids = [int(r.get("player_uid", 0)) for r in role_rows if int(r.get("player_uid", 0)) > 0]
    player_names = {uid: _ss_player_name(season_id, uid) for uid in uids}

    buf_v = _rd_render_role_bar_chart(
        season_id=season_id,
        role_label="Vanguard",
        role_key="v",
        role_rows=role_rows,
        player_names=player_names
    )
    buf_d = _rd_render_role_bar_chart(
        season_id=season_id,
        role_label="Duelist",
        role_key="d",
        role_rows=role_rows,
        player_names=player_names
    )
    buf_s = _rd_render_role_bar_chart(
        season_id=season_id,
        role_label="Strategist",
        role_key="s",
        role_rows=role_rows,
        player_names=player_names
    )

    files = [
        discord.File(fp=buf_v, filename=f"role_distribution_vanguard_s{season_id}.png"),
        discord.File(fp=buf_d, filename=f"role_distribution_duelist_s{season_id}.png"),
        discord.File(fp=buf_s, filename=f"role_distribution_strategist_s{season_id}.png"),
    ]
    await ctx.send(files=files)


# ============================================================================================================
# !season_movie_pack — enriched movie pack with beats, rivalries, arcs, meta, chemistry and finale
#
# Usage:
#   !season_movie_pack
#   !season_movie_pack 6
#
# Output:
#   Uploads: season_movie_pack_s<season_id>.md
#
# Dependencies:
# - Uses shared helpers when available and otherwise degrades gracefully.
# - Required:
#     bot, discord, ensure_mr_api_tables(), get_current_season_id(), _ss_compute_core()
# - Optional helpers used if present:
#     get_hero_name() async, _get_games_grouped_by_date_api(), _aggregate_session_records_api(),
#     _session_underdog_summary_api(), _session_top_bans_and_picks(),
#     _so_session_opponent_match_uids_for_labels(), _so_h2h_stats_for_matches()
#     _build_session_teammate_matrix_fair_api() (for chemistry)
# ============================================================================================================

import io
import json
import asyncio
from collections import defaultdict
from itertools import combinations

try:
    import pandas
except Exception:
    pandas = None


def _smp_get_const(name: str, default: int) -> int:
    try:
        v = globals().get(name, default)
        return int(v) if v is not None else int(default)
    except Exception:
        return int(default)


def _smp_safe_call(fn_name: str, *args, default=None, **kwargs):
    fn = globals().get(fn_name)
    if callable(fn):
        return fn(*args, **kwargs)
    return default


async def _smp_safe_await_call(fn_name: str, *args, default=None, **kwargs):
    fn = globals().get(fn_name)
    if callable(fn):
        return await fn(*args, **kwargs)
    return default


def _smp_norm_float(x, ndp=1, default=0.0):
    try:
        return round(float(x), ndp)
    except Exception:
        return float(default)


def _smp_norm_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return int(default)


def _smp_isna(x) -> bool:
    try:
        if pandas is not None:
            return bool(pandas.isna(x))
    except Exception:
        pass
    return False


def _smp_player_name(season_id: int, player_uid: int) -> str:
    fn = globals().get("_ss_player_name")
    if callable(fn):
        try:
            n = fn(season_id, player_uid)
            if n:
                return str(n)
        except Exception:
            pass
    return f"uid:{player_uid}"


def _smp_pick_row_hero_id(row: dict) -> int | None:
    for key in ("top_hero_season_id", "top_hero_id", "top_hero_sess_id"):
        hid = row.get(key)
        if hid is None or _smp_isna(hid):
            continue
        try:
            return int(hid)
        except Exception:
            pass
    return None


async def _smp_resolve_hero_names(hero_ids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    ids = sorted({int(h) for h in hero_ids if h})
    if not ids:
        return out

    get_hero_name_fn = globals().get("get_hero_name")
    if callable(get_hero_name_fn):
        tasks = [get_hero_name_fn(str(h)) for h in ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for hid, res in zip(ids, results):
            if isinstance(res, str) and res.strip():
                out[hid] = res.strip()
            else:
                out[hid] = "Unknown Hero"
        return out

    for hid in ids:
        out[hid] = str(hid)
    return out


def _smp_build_cast_from_df(season_id: int, season_df) -> list[dict]:
    cast = []
    if season_df is None or getattr(season_df, "empty", True):
        return cast

    try:
        rows = season_df.to_dict(orient="records")
    except Exception:
        return cast

    seen = set()
    for r in rows:
        uid = _smp_norm_int(r.get("player_uid"), 0)
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)

        pname = str(r.get("player") or _smp_player_name(season_id, uid))
        hid = _smp_pick_row_hero_id(r)

        cast.append({
            "player_uid": uid,
            "player_name": pname,
            "main_hero_id": hid,          # name attached later
            "games": _smp_norm_int(r.get("games") or r.get("g") or 0),
            "wins": _smp_norm_int(r.get("wins") or r.get("w") or 0),
            "winrate": _smp_norm_float(r.get("winrate") or 0.0, 2, 0.0),
        })
    return cast


def _smp_rank_groups(cast: list[dict], min_games: int = 5, top_n: int = 5, bottom_n: int = 5):
    eligible = [c for c in cast if int(c.get("games") or 0) >= int(min_games)]
    eligible_sorted = sorted(eligible, key=lambda x: (float(x.get("winrate") or 0.0), int(x.get("games") or 0)))
    bottom = eligible_sorted[:bottom_n]
    top = list(reversed(eligible_sorted[-top_n:])) if eligible_sorted else []
    return top, bottom


def _smp_compute_pair_maps_from_labels(season_id: int, labels: list[str]):
    """
    Uses mr_player_match to compute:
      - overlap games per pair
      - teammate games per pair (same is_win)
      - opponent games per pair (different is_win)
    Returns: dicts keyed by (a,b) with a<b
    """
    if not labels:
        return {}, {}, {}

    if pandas is None:
        return {}, {}, {}

    qmarks = ",".join("?" for _ in labels)
    try:
        c.execute(
            f"""
            SELECT game_label, player_uid, player, is_win
            FROM mr_player_match
            WHERE season_id=?
              AND is_bot=0
              AND game_label IN ({qmarks})
            """, (season_id, *labels)
        )
        rows = c.fetchall()
    except Exception:
        return {}, {}, {}

    by_game = defaultdict(dict)
    for gl, uid, player, w in rows:
        try:
            uid = int(uid)
        except Exception:
            continue
        by_game[str(gl)][uid] = int(w or 0)

    overlap = defaultdict(int)
    teammate = defaultdict(int)
    opponent = defaultdict(int)

    for gl, result in by_game.items():
        uids = sorted(result.keys())
        if len(uids) < 2:
            continue
        for a, b in combinations(uids, 2):
            key = (a, b)
            overlap[key] += 1
            if result[a] == result[b]:
                teammate[key] += 1
            else:
                opponent[key] += 1

    return dict(overlap), dict(teammate), dict(opponent)


def _smp_build_rivalries(season_id: int, labels: list[str], cast: list[dict], hero_names: dict[int, str], top_n: int = 8):
    """
    Rivalries = players who faced each other often (opponents).
    If opponent match_uids + stats helpers exist, include rich rivalry notes.
    """
    # Fast count-based rivalries
    overlap, teammate, opponent = _smp_compute_pair_maps_from_labels(season_id, labels)
    if not opponent:
        return []

    uid_to_cast = {int(c["player_uid"]): c for c in cast}
    pairs = []
    for (a, b), og in opponent.items():
        if og <= 0:
            continue
        if a not in uid_to_cast or b not in uid_to_cast:
            continue
        pairs.append((og, a, b))

    pairs.sort(reverse=True, key=lambda t: t[0])
    pairs = pairs[:max(top_n * 3, 20)]  # shortlist for richer processing

    out = []
    opp_uids_fn = globals().get("_so_session_opponent_match_uids_for_labels")
    stats_fn = globals().get("_so_h2h_stats_for_matches")

    for og, a, b in pairs:
        a_name = uid_to_cast[a]["player_name"]
        b_name = uid_to_cast[b]["player_name"]
        rec = {
            "a_uid": int(a),
            "b_uid": int(b),
            "a_name": str(a_name),
            "b_name": str(b_name),
            "games_as_opponents": int(og),
            "rivalry_flavour": "frequent clashes",
        }

        # Enrich if helpers exist
        if callable(opp_uids_fn) and callable(stats_fn):
            try:
                match_uids = opp_uids_fn(season_id, int(a), int(b), labels)
                if match_uids:
                    sa = stats_fn(season_id, int(a), match_uids)
                    sb = stats_fn(season_id, int(b), match_uids)
                    # Keep stats in data pack (writer can use them), prompt forbids quoting numbers.
                    rec["stats_a"] = sa
                    rec["stats_b"] = sb

                    # Simple “closeness” / “one-sided” tags
                    try:
                        wa = int(sa.get("wins", 0))
                        wb = int(sb.get("wins", 0))
                        diff = abs(wa - wb)
                        if diff <= 1:
                            rec["rivalry_flavour"] = "nail-biting and evenly matched"
                        elif wa > wb:
                            rec["rivalry_flavour"] = f"{a_name} often held the upper hand"
                        else:
                            rec["rivalry_flavour"] = f"{b_name} often held the upper hand"
                    except Exception:
                        pass
            except Exception:
                pass

        out.append(rec)
        if len(out) >= top_n:
            break

    return out


def _smp_build_chemistry(season_id: int, labels: list[str], cast: list[dict], top_n: int = 10):
    """
    Chemistry = frequent allies + rare pairings (volatile / awkward pairing opportunities).
    Based on teammate counts from mr_player_match (no performance claims).
    """
    overlap, teammate, opponent = _smp_compute_pair_maps_from_labels(season_id, labels)
    if not teammate and not overlap:
        return {"frequent_allies": [], "rarely_teamed": []}

    uid_to_name = {int(c["player_uid"]): c["player_name"] for c in cast}

    ally_rows = []
    for (a, b), tg in teammate.items():
        if a in uid_to_name and b in uid_to_name and tg > 0:
            ally_rows.append((tg, overlap.get((a, b), tg), a, b))
    ally_rows.sort(reverse=True, key=lambda t: (t[0], t[1]))

    frequent_allies = []
    for tg, og, a, b in ally_rows[:top_n]:
        frequent_allies.append({
            "a_uid": int(a), "b_uid": int(b),
            "a_name": str(uid_to_name[a]), "b_name": str(uid_to_name[b]),
            "same_side_games": int(tg),
            "overlap_games": int(og),
            "flavour": "often fought side-by-side",
        })

    # Rarely teamed: high overlap but low teammate count
    rare_rows = []
    for (a, b), og in overlap.items():
        if a not in uid_to_name or b not in uid_to_name:
            continue
        tg = teammate.get((a, b), 0)
        if og >= 4 and tg <= 1:  # adjustable
            rare_rows.append((og, tg, a, b))
    rare_rows.sort(reverse=True, key=lambda t: (t[0], -t[1]))

    rarely_teamed = []
    for og, tg, a, b in rare_rows[:top_n]:
        rarely_teamed.append({
            "a_uid": int(a), "b_uid": int(b),
            "a_name": str(uid_to_name[a]), "b_name": str(uid_to_name[b]),
            "same_side_games": int(tg),
            "overlap_games": int(og),
            "flavour": "rarely aligned on the same side",
        })

    return {"frequent_allies": frequent_allies, "rarely_teamed": rarely_teamed}


def _smp_build_meta_timeline(season_id: int, ordered_dates: list[str], by_date: dict, hero_names: dict[int, str], top_n: int = 4):
    """
    Per-session picks/bans + a crude meta-shift detector.
    Uses _session_top_bans_and_picks(season_id, session_labels) if present.
    """
    fn = globals().get("_session_top_bans_and_picks")
    if not callable(fn):
        return {"sessions": [], "meta_shifts": []}

    sessions = []
    # for shift detection
    picks_count = defaultdict(int)
    bans_count = defaultdict(int)

    for d in ordered_dates:
        labels = by_date.get(d, []) or []
        if not labels:
            continue
        try:
            bans_list, picks_list = fn(season_id, labels)
        except Exception:
            continue

        def _norm_hero_list(lst):
            out = []
            for r in (lst or [])[:top_n]:
                hid = None
                if isinstance(r, dict):
                    hid = r.get("hero_id") or r.get("hero") or r.get("id")
                else:
                    # tolerate tuples like (hero_id, count)
                    try:
                        hid = r[0]
                    except Exception:
                        hid = None
                try:
                    hid_i = int(hid)
                except Exception:
                    continue
                out.append({
                    "hero_id": hid_i,
                    "hero_name": hero_names.get(hid_i, "Unknown Hero")
                })
            return out

        bans_norm = _norm_hero_list(bans_list)
        picks_norm = _norm_hero_list(picks_list)

        for x in bans_norm:
            bans_count[int(x["hero_id"])] += 1
        for x in picks_norm:
            picks_count[int(x["hero_id"])] += 1

        sessions.append({
            "date": str(d),
            "top_bans": bans_norm,
            "top_picks": picks_norm,
            "meta_note": "tactical adjustments and countermeasures escalated",
        })

    # crude “meta shift”: heroes appearing frequently late vs early
    meta_shifts = []
    if sessions:
        cut = max(1, len(sessions) // 3)
        early = sessions[:cut]
        late = sessions[-cut:]

        def _count_heroes(sess, key):
            c = defaultdict(int)
            for s in sess:
                for h in s.get(key, []) or []:
                    c[int(h["hero_id"])] += 1
            return c

        early_p = _count_heroes(early, "top_picks")
        late_p = _count_heroes(late, "top_picks")

        # heroes that “rose” in late picks
        deltas = []
        for hid in set(list(early_p.keys()) + list(late_p.keys())):
            deltas.append((late_p.get(hid, 0) - early_p.get(hid, 0), hid))
        deltas.sort(reverse=True, key=lambda t: t[0])

        for delta, hid in deltas[:3]:
            if delta <= 0:
                continue
            meta_shifts.append({
                "type": "meta_shift",
                "hero_id": int(hid),
                "hero_name": hero_names.get(int(hid), "Unknown Hero"),
                "note": "rose into prominence as teams adapted",
            })

    return {"sessions": sessions, "meta_shifts": meta_shifts}


def _smp_build_beats(season_id: int, core_norm: dict, ordered_dates: list[str], rivalries: list[dict], meta_shifts: list[dict], top_group: list[dict], bottom_group: list[dict]):
    """
    Turning points: opening, upset, rivalries, meta shifts, redemption, finale.
    """
    beats = []

    if ordered_dates:
        beats.append({
            "type": "opening",
            "date": str(ordered_dates[0]),
            "summary": "The season begins — alliances form, egos collide, and the first sparks of rivalry appear.",
        })

    bu = core_norm.get("biggest_upset")
    if isinstance(bu, dict):
        beats.append({
            "type": "upset",
            "date": str(bu.get("session_date") or bu.get("date") or bu.get("game_label") or ""),
            "summary": "A shocking upset rewrites expectations and proves nobody is untouchable.",
            "evidence_ref": "core.biggest_upset"
        })

    # Rivalries beat
    if rivalries:
        r = rivalries[0]
        beats.append({
            "type": "rivalry_spike",
            "date_range": "mid-season",
            "summary": f"The feud between {r.get('a_name')} and {r.get('b_name')} becomes a recurring flashpoint.",
            "evidence_ref": "rivalries[0]"
        })

    # Meta shifts
    for ms in (meta_shifts or [])[:2]:
        beats.append({
            "type": "meta_shift",
            "date_range": "season progression",
            "summary": f"{ms.get('hero_name')} reshapes the battlefield as tactics evolve.",
            "evidence_ref": "meta_timeline.meta_shifts"
        })

    # Underdog spotlight beat
    if bottom_group:
        names = ", ".join([b.get("player_name", "") for b in bottom_group[:3] if b.get("player_name")])
        if names:
            beats.append({
                "type": "underdog_arc",
                "date_range": "throughout season",
                "summary": f"The underdogs ({names}) refuse to be background characters — every setback fuels the next surprise.",
                "evidence_ref": "rankings.bottom_players"
            })

    if ordered_dates:
        beats.append({
            "type": "finale",
            "date": str(ordered_dates[-1]),
            "summary": "The finale arrives — grudges settle, legends cement their reputations, and new threats loom for next season.",
        })

    return beats


def _smp_build_arcs(season_id: int, ordered_dates: list[str], by_date: dict, cast: list[dict], hero_names: dict[int, str], top_n_players: int = 10):
    """
    Builds lightweight arcs for a selection of players:
      - headliners (top by winrate with min games)
      - underdogs (bottom by winrate with min games)
    Uses per-session aggregates when available.
    """
    arcs = []
    agg_fn = globals().get("_aggregate_session_records_api")
    if not callable(agg_fn) or not ordered_dates:
        return arcs

    # choose a manageable subset to avoid bloat
    top_group, bottom_group = _smp_rank_groups(cast, min_games=5, top_n=top_n_players//2, bottom_n=top_n_players//2)
    focus_uids = {int(x["player_uid"]) for x in (top_group + bottom_group) if x.get("player_uid")}

    # build time series per focus player: list of (date, winrate, kda)
    series = {uid: [] for uid in focus_uids}

    for d in ordered_dates:
        labels = by_date.get(d, []) or []
        if not labels:
            continue
        df = None
        try:
            df = agg_fn(season_id, labels)
        except Exception:
            df = None
        if df is None or getattr(df, "empty", True):
            continue

        try:
            rows = df.to_dict(orient="records")
        except Exception:
            continue

        for r in rows:
            uid = _smp_norm_int(r.get("player_uid"), 0)
            if uid not in focus_uids:
                continue
            series[uid].append({
                "date": str(d),
                "winrate": _smp_norm_float(r.get("winrate"), 2, 0.0),
                "avg_kda": _smp_norm_float(r.get("avg_kda"), 2, 0.0),
            })

    # classify arcs with simple heuristics
    uid_to_name = {int(c["player_uid"]): c["player_name"] for c in cast}
    uid_to_hero = {int(c["player_uid"]): c.get("main_hero_id") for c in cast}

    for uid, pts in series.items():
        if len(pts) < 3:
            continue
        start = pts[:max(1, len(pts)//3)]
        end = pts[-max(1, len(pts)//3):]

        s_wr = sum(p["winrate"] for p in start) / len(start)
        e_wr = sum(p["winrate"] for p in end) / len(end)

        arc_type = "steady_presence"
        if e_wr - s_wr >= 0.15:
            arc_type = "late_surge"
        elif s_wr - e_wr >= 0.15:
            arc_type = "early_fire_then_slump"
        elif e_wr < 0.35:
            arc_type = "struggle_against_the_odds"

        hid = uid_to_hero.get(uid)
        arcs.append({
            "player_uid": int(uid),
            "player_name": str(uid_to_name.get(uid, _smp_player_name(season_id, uid))),
            "main_hero_id": int(hid) if hid else None,
            "main_hero_name": hero_names.get(int(hid), "Unknown Hero") if hid else "Unknown Hero",
            "arc_type": arc_type,
            "note": "translate this arc into scenes and character growth — do not quote numbers",
            "series": pts,  # stats remain available; prompt forbids quoting them.
        })

    return arcs


async def _smp_build_movie_pack_md(season_id: int) -> io.BytesIO | None:
    ensure_mr_api_tables()

    # --- Core (required) ---
    core = _smp_safe_call("_ss_compute_core", season_id, default=None)
    if not core:
        return None

    if isinstance(core, dict):
        core_norm = dict(core)
    else:
        try:
            core_norm = dict(core)
        except Exception:
            core_norm = {"raw_core": core}

    # --- Season-wide lists (optional) ---
    top_vers = _smp_get_const("SS_TOP_VERSATILE", 6)
    top_bots = _smp_get_const("SS_TOP_BOT_HEROES", 6)
    top_syn  = _smp_get_const("SS_TOP_SYNERGY", 6)
    top_dom  = _smp_get_const("SS_TOP_DOMINANT", 6)
    top_tier = _smp_get_const("SS_TOP_TIER", 10)
    top_bans = _smp_get_const("SS_TOP_BANS", 8)

    versatile  = _smp_safe_call("_ss_most_versatile_from_segments", season_id, top_n=top_vers, default=[])
    bot_heroes  = _smp_safe_call("_ss_top_bot_heroes_like_leaderboard_image_bots", season_id, top_n=top_bots, default=[])
    synergy     = _smp_safe_call("_ss_top_synergy", season_id, top_n=top_syn, default=[])
    dominant    = _smp_safe_call("_ss_top_dominant", season_id, top_n=top_dom, default=[])
    tier        = _smp_safe_call("_ss_top_tierlist", season_id, top_n=top_tier, default=[])
    bans        = _smp_safe_call("_ss_top_bans", season_id, top_n=top_bans, default=[])
    role_rows   = await _smp_safe_await_call("_ss_role_distribution", season_id, default=[])

    # --- Labels / Sessions ---
    all_labels = _smp_safe_call("_all_ordered_game_labels_api", season_id, default=[])
    ordered_dates, by_date = _smp_safe_call("_get_games_grouped_by_date_api", season_id, default=([], {}))
    ordered_dates = ordered_dates or []
    by_date = by_date or {}

    # --- Season-wide DF -> Cast (ALL players; solves missing hero for many) ---
    season_df = None
    if all_labels:
        season_df = _smp_safe_call("_aggregate_session_records_api", season_id, all_labels, default=None)
    cast = _smp_build_cast_from_df(season_id, season_df)

    # --- Hero names (collect IDs first) ---
    hero_ids: set[int] = set()
    def _add_hid(v):
        try:
            if v is None or _smp_isna(v):
                return
            hero_ids.add(int(v))
        except Exception:
            pass

    for cst in cast:
        _add_hid(cst.get("main_hero_id"))

    for r in (bot_heroes or []):
        _add_hid((r.get("hero_id") if isinstance(r, dict) else None))
    for r in (tier or []):
        _add_hid((r.get("hero_id") if isinstance(r, dict) else None))
    for r in (dominant or []):
        _add_hid((r.get("hero_id") if isinstance(r, dict) else None))
    for r in (bans or []):
        _add_hid((r.get("hero_id") if isinstance(r, dict) else None))
    for r in (synergy or []):
        if isinstance(r, dict):
            _add_hid(r.get("a"))
            _add_hid(r.get("b"))

    hero_names = await _smp_resolve_hero_names(hero_ids)

    # Attach hero names to cast
    for cst in cast:
        hid = cst.get("main_hero_id")
        cst["main_hero_name"] = hero_names.get(int(hid), "Unknown Hero") if hid else "Unknown Hero"

    # --- Rankings: top & bottom (for ensemble focus) ---
    top_group, bottom_group = _smp_rank_groups(cast, min_games=5, top_n=5, bottom_n=5)
    rankings = {
        "top_players": [{"player_uid": int(x["player_uid"]), "player_name": x["player_name"], "main_hero_name": x.get("main_hero_name", "Unknown Hero")} for x in top_group],
        "bottom_players": [{"player_uid": int(x["player_uid"]), "player_name": x["player_name"], "main_hero_name": x.get("main_hero_name", "Unknown Hero")} for x in bottom_group],
        "note": "bottom_players must be featured with underdog moments and subplots (prompt enforces this)."
    }

    # --- Rivalries / Chemistry / Meta timeline / Arcs / Beats / Finale ---
    rivalries = _smp_build_rivalries(season_id, all_labels or [], cast, hero_names, top_n=8)
    chemistry = _smp_build_chemistry(season_id, all_labels or [], cast, top_n=10)

    meta = _smp_build_meta_timeline(season_id, ordered_dates, by_date, hero_names, top_n=4)
    meta_timeline = meta.get("sessions", [])
    meta_shifts = meta.get("meta_shifts", [])

    arcs = _smp_build_arcs(season_id, ordered_dates, by_date, cast, hero_names, top_n_players=10)

    beats = _smp_build_beats(season_id, core_norm, ordered_dates, rivalries, meta_shifts, top_group, bottom_group)

    finale = {
        "dates": [str(d) for d in ordered_dates[-min(2, len(ordered_dates)) :]] if ordered_dates else [],
        "spotlight": [int(x["player_uid"]) for x in (top_group[:3] + bottom_group[:2]) if x.get("player_uid")],
        "stakes": "a final collision of grudges, alliances, and momentum — set up the post-credit tease",
    }

    # --- Metadata ---
    try:
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc).isoformat()
    except Exception:
        now_utc = ""

    season_range = str(core_norm.get("date_range") or "").strip()
    if not season_range and ordered_dates:
        season_range = f"{ordered_dates[0]} – {ordered_dates[-1]}"

    # --- Pack ---
    pack = {
        "season_id": int(season_id),
        "generated_at_utc": now_utc,
        "season_range": season_range,

        "cast": cast,                 # ALL players + main hero name (best effort)
        "rankings": rankings,         # includes bottom_players explicitly

        "core": core_norm,
        "hero_names": hero_names,

        "season_lists": {
            "most_versatile": versatile or [],
            "top_bot_heroes": bot_heroes or [],
            "top_synergy_pairs": synergy or [],
            "top_dominant_heroes": dominant or [],
            "top_tierlist": tier or [],
            "top_bans": bans or [],
            "role_distribution": role_rows or [],
        },

        "meta_timeline": {
            "sessions": meta_timeline,
            "meta_shifts": meta_shifts,
        },

        "chemistry": chemistry,
        "rivalries": rivalries,
        "arcs": arcs,
        "beats": beats,
        "finale": finale,
    }

    pack_json = json.dumps(pack, ensure_ascii=False, indent=2)

    # --- Prompt (enforces ensemble + non-numeric storytelling) ---
    lines = []
    lines.append(f"# Season Movie Pack — Season {season_id}")
    lines.append("")
    lines.append("## Copy/paste prompt (use with ChatGPT)")
    lines.append("")
    lines.append("You are writing an entertaining Marvel-themed movie/story summarising a gaming season.")
    lines.append("Use ONLY the facts in the JSON attached. Do NOT invent players, matches, heroes, or outcomes.")
    lines.append("")
    lines.append("CRITICAL STYLE RULES:")
    lines.append("1) Do NOT quote numbers, stats, KDA, winrates, percentages, damage, or counts.")
    lines.append("2) Translate performance into cinematic language and consequences (rampage, clutch, collapse, redemption).")
    lines.append("3) Ensemble requirement: EVERY player in JSON.cast must appear at least once.")
    lines.append("4) Based on the dataset, give us a summary of the season, in the style of a marvel movie, and be robust with your critiques.")
    lines.append("")
    lines.append("Story building blocks you CAN use:")
    lines.append("- JSON.beats: treat these as the spine of the movie (set-pieces and turning points).")
    lines.append("- JSON.rivalries: recurring nemesis dynamics; escalate tension across acts.")
    lines.append("- JSON.chemistry.frequent_allies / rarely_teamed: friendships, odd couples, awkward alliances.")
    lines.append("- JSON.meta_timeline + meta_shifts: evolving tactics; an arms race, counters, new threats.")
    lines.append("- JSON.arcs: character momentum (late surge, slump, struggle).")
    lines.append("- JSON.core.biggest_upset: major plot twist (do not narrate it as a stat).")
    lines.append("")
    lines.append("Structure:")
    lines.append("1) Title + tagline")
    lines.append("2) Cast list: for each JSON.cast entry -> codename, personality, main_hero_name, relationships (ally/nemesis).")
    lines.append("3) Story: Cold open, Act I, Act II, Act III, Climax, Epilogue")
    lines.append("   - Use sessions as scenes only when helpful. Do not mechanically summarise every date.")
    lines.append("4) Season awards (flavour only): MVP-style, Heart of the Team, Comeback Kid, Chaos Agent, Buddy Duo, Nemesis Award")
    lines.append("5) Post-credit teaser setting up next season")
    lines.append("")
    lines.append("Tone:")
    lines.append("- Marvel-esque: cinematic stakes, witty banter, escalating set-pieces, teamwork and betrayals.")
    lines.append("- 1,200–2,500 words. Readable, entertaining, not a report.")
    lines.append("")
    lines.append("## Data (JSON)")
    lines.append("```json")
    lines.append(pack_json)
    lines.append("```")
    lines.append("")

    md = "\n".join(lines)

    buf = io.BytesIO(md.encode("utf-8"))
    buf.seek(0)
    return buf


# Safe re-register (hot reload support)
try:
    bot.remove_command("season_movie_pack")
except Exception:
    pass


@bot.command(name="season_movie_pack")
async def season_movie_pack(ctx, season_id: int = None):
    """
    Usage:
      !season_movie_pack
      !season_movie_pack 6
    """
    ensure_mr_api_tables()

    sid = int(season_id) if season_id is not None else int(get_current_season_id())

    buf = await _smp_build_movie_pack_md(sid)
    if buf is None:
        await ctx.send("No season data found yet. Import matches first, then try again.")
        return

    await ctx.send(file=discord.File(fp=buf, filename=f"season_movie_pack_s{sid}.md"))

# ============================================================================================================
# !run_all_stats — creates/updates dedicated Discord channels with the latest outputs for key stat commands
#
# Included behavior:
# - leaderboard_image posts exactly three images: main, 0.5 and bots
# - Includes hero_time, 2v2_records, profile and season_movie_pack
# - Runs profile for all human players rather than the dropdown default
# - For multi-option commands:
#     * player_heros: posts "all" + each player output in the season
#     * hero_tierlist: posts humans, bots, both
#     * hero_synergy: posts humans, bots, both
# ============================================================================================================

STATS_CATEGORY_NAME = "MR Stats"
STATS_CHANNELS = {
    "session_overview": "stats-session-overview",
    "leaderboard_image": "stats-leaderboard",
    "low_team": "stats-low-team",
    "player_heros": "stats-player-heros",
    "hero_time": "stats-hero-time",
    "role_distribution": "stats-role-distribution",
    "role_winrates": "stats-role-winrates",
    "season_story": "stats-season-story",
    "teammate_matrix_fair": "stats-teammate-matrix-fair",
    "teammate_matrix_lowteam_fair": "stats-teammate-matrix-lowteam-fair",
    "win_matrix": "stats-win-matrix",
    "hero_bans": "stats-hero-bans",
    "player_bans": "stats-player-bans",
    # user calls it !tierlist but command is hero_tierlist
    "hero_tierlist": "stats-tierlist",
    "hero_synergy": "stats-hero-synergy",
    "2v2_records": "stats-2v2-records",
    "4v4_records": "stats-4v4-records",
    "profile": "stats-profile",
    "season_movie_pack": "stats-season-movie-pack",
}


async def _stats_get_or_create_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    for cat in guild.categories:
        if cat.name == name:
            return cat
    return await guild.create_category(name)


async def _stats_get_or_create_text_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    name: str
) -> discord.TextChannel:
    # If exists anywhere, move it under the category (optional) and reuse
    for ch in guild.text_channels:
        if ch.name == name:
            try:
                if ch.category_id != category.id:
                    await ch.edit(category=category)
            except Exception:
                pass
            return ch
    return await guild.create_text_channel(name, category=category)


async def _stats_clear_bot_messages(channel: discord.TextChannel, *, limit: int = 250):
    """
    Deletes recent messages authored by this bot in the target channel.
    Uses per-message deletes to avoid bulk-delete limitations (14-day rule).
    """
    me = channel.guild.me
    if me is None:
        return

    deleted = 0
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            if msg.author and msg.author.id == me.id:
                try:
                    await msg.delete()
                    deleted += 1
                    if deleted % 8 == 0:
                        await asyncio.sleep(0.35)
                except Exception:
                    pass
    except Exception:
        pass


class _ProxyCtx:
    """
    Minimal Context-like shim so existing command callbacks can run,
    but output goes to a specific channel.
    """
    def __init__(self, base_ctx: commands.Context, channel: discord.TextChannel):
        self.bot = base_ctx.bot
        self.guild = base_ctx.guild
        self.author = base_ctx.author
        self.message = base_ctx.message
        self.channel = channel

    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)

    async def reply(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)

    def typing(self):
        return self.channel.typing()


async def _stats_run_command_callback(
    base_ctx: commands.Context,
    target_channel: discord.TextChannel,
    command_name: str,
    *args,
    **kwargs
):
    cmd = bot.get_command(command_name)
    if not cmd:
        await target_channel.send(f"⚠️ Command `{command_name}` not found in this bot.")
        return

    pctx = _ProxyCtx(base_ctx, target_channel)

    try:
        # Call the underlying callback (bypasses checks/cooldowns)
        await cmd.callback(pctx, *args, **kwargs)
    except Exception as e:
        await target_channel.send(f"⚠️ `{command_name}` failed: `{type(e).__name__}: {e}`")
        try:
            traceback.print_exc()
        except Exception:
            pass

@bot.command(name="run_all_stats")
async def run_all_stats(ctx: commands.Context):
    """
    Creates/updates dedicated stats channels and posts the latest outputs for key commands.
    """
    if not ctx.guild:
        await ctx.send("This command must be run inside a server (guild).")
        return

    # Ensure DB/API tables exist for commands that rely on them
    try:
        ensure_mr_api_tables()
    except Exception:
        pass

    guild = ctx.guild
    category = await _stats_get_or_create_category(guild, STATS_CATEGORY_NAME)

    # Create/resolve channels
    channels: dict[str, discord.TextChannel] = {}
    for cmd_name, ch_name in STATS_CHANNELS.items():
        ch = await _stats_get_or_create_text_channel(guild, category, ch_name)
        channels[cmd_name] = ch

    await ctx.send(f"Running stats refresh into **{category.name}** channels…")

    # Run each stat command into its channel (clear then post fresh outputs)
    for cmd_name, ch in channels.items():
        await _stats_clear_bot_messages(ch, limit=350)

        # Header line for clarity
        try:
            season_id = get_current_season_id()
            await ch.send(f"**Latest output — `{cmd_name}` (Season {season_id})**")
        except Exception:
            await ch.send(f"**Latest output — `{cmd_name}`**")

        # Multi-option routing
        if cmd_name == "player_heros":
            # 1) Season dominance
            await _stats_run_command_callback(ctx, ch, "player_heros", player_name="all")
            await asyncio.sleep(0.6)

            # 2) Every player in current season
            try:
                season_id = get_current_season_id()
                players = _get_api_players(season_id) or []
            except Exception:
                players = []

            for p in players:
                pname = str(p.get("player") or "").strip()
                if not pname:
                    continue
                await _stats_run_command_callback(ctx, ch, "player_heros", player_name=pname)
                await asyncio.sleep(0.6)

        elif cmd_name == "role_winrates":
            # 1) Overall table for all players
            await _stats_run_command_callback(ctx, ch, "role_winrates")
            await asyncio.sleep(0.8)

            # 2) Every player-role combination in current season
            try:
                season_id = get_current_season_id()
                players = _get_api_players(season_id) or []
            except Exception:
                players = []

            if not players:
                await ch.send("No API-imported human players found for this season.")
            else:
                roles = ["vanguard", "duelist", "strategist"]
                seen_names = set()

                for p in players:
                    pname = str(p.get("player") or "").strip()
                    if not pname:
                        continue

                    nk = norm_key(pname)
                    if nk in seen_names:
                        continue
                    seen_names.add(nk)

                    for role_name in roles:
                        await _stats_run_command_callback(
                            ctx,
                            ch,
                            "role_winrates",
                            arg=f"{pname} {role_name}",
                        )
                        await asyncio.sleep(0.7)

        elif cmd_name == "profile":
            # profile defaults to a dropdown if called with no args,
            # so we run one profile image per human player in the current season.
            try:
                season_id = get_current_season_id()
                players = _get_api_players(season_id) or []
            except Exception:
                players = []

            if not players:
                await ch.send("No API-imported human players found for this season.")
            else:
                for p in players:
                    pname = str(p.get("player") or "").strip()
                    if not pname:
                        continue
                    await _stats_run_command_callback(ctx, ch, "profile", player_name=pname)
                    await asyncio.sleep(0.8)

        elif cmd_name == "hero_tierlist":
            for mode in ("humans", "bots", "both"):
                await _stats_run_command_callback(ctx, ch, "hero_tierlist", mode)
                await asyncio.sleep(0.8)

        elif cmd_name == "hero_synergy":
            for mode in ("humans", "bots", "both"):
                await _stats_run_command_callback(ctx, ch, "hero_synergy", mode)
                await asyncio.sleep(0.8)

        elif cmd_name == "leaderboard_image":
            # Explicitly post main, 0.5, bots exactly once each
            for mode in ("main", "0.5", "bots"):
                await _stats_run_command_callback(ctx, ch, "leaderboard_image", mode)
                await asyncio.sleep(0.8)

        else:
            await _stats_run_command_callback(ctx, ch, cmd_name)
            await asyncio.sleep(0.6)

    await ctx.send(f"✅ Stats refresh complete for **{category.name}**.")

# ============================================================================================================
# !pregame — helpers and command
#   "SWINGY / BUZZ" MODE
#     - Much more swingy session predictions (dominators + disasters)
#     - Heavier weighting on teammate synergy + win_matrix style pairing success
#     - Explicit "meltdown / pop-off" night shocks (so someone can throw a night)
#     - More upsets (noise + lower Beta concentration + steeper logistic)
#
# Configuration:
#   - sims reduced: default sims=3 (and determinations image calls sims=3)
#   - predicted leaderboard % matches the displayed ~W-L rather than the mean across simulations
#   - targets use session-average games plus two, clamped to 3..12
#
# Outputs (selected players only):
#   1) Low-Team % table image (ROWS filtered only; full-season stats preserved; NO game filtering)
#   2) Teammate Fairness Matrix image (filtered)
#   3) Season Story versatility triangle image (filtered)
#   4) Leaderboard image (filtered)
#   5) Pregame Determinations image (stacked):
#        - Bouncers
#        - Team-less likelihood
#        - Predicted session leaderboard (swingy simulation)
#        - Predicted leaderboard changes (applies predicted W/L onto season standings)
#
# Notes:
#   - Uses the same dropdown view class as !session_players (ActivePlayersView).
#   - Does NOT persist/alter session_players; pregame-only.
#   - Does NOT modify next_teams state or settings.
# ============================================================================================================

import io
import re
import math
import random
from dataclasses import dataclass, field
from collections import defaultdict
from itertools import combinations, product

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


# ------------------------------------------------------------------------------------------------------------
# Canon / safe helpers
# ------------------------------------------------------------------------------------------------------------

def _pregame_canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _pregame_allowed_norms_from_pkeys(pkeys: set[str], display_name_map: dict[str, str]) -> set[str]:
    allowed = set()
    for pk in (pkeys or set()):
        disp = display_name_map.get(pk, pk)
        k = _pregame_canon(str(disp))
        if k:
            allowed.add(k)
    return allowed


def _pregame_safe_get_current_season_id() -> int:
    try:
        return int(get_current_season_id())
    except Exception:
        try:
            return int(get_current_season())
        except Exception:
            return 0


def _pregame_get_all_players_map_fallback() -> dict[str, str]:
    try:
        m = _get_all_players_prefer_roster()
        if isinstance(m, dict) and m:
            return m
    except Exception:
        pass

    try:
        ensure_auto_import_tables()
        c.execute("SELECT DISTINCT player FROM game_stats_v")
        names = [r[0] for r in c.fetchall() if r and r[0]]
        out = {}
        for n in names:
            out[str(n)] = str(n)
        return out
    except Exception:
        return {}


async def _pregame_interaction_defer_safe(interaction):
    try:
        if hasattr(interaction, "response") and hasattr(interaction.response, "defer"):
            await interaction.response.defer()
    except Exception:
        pass


def _pregame_make_players_view(*, all_players: dict, preselected: set, session_state, on_done_cb):
    """
    ActivePlayersView signature can vary; attempt common constructor shapes.
    """
    try:
        return ActivePlayersView(
            all_players,
            preselected,
            session_state,
            on_done=on_done_cb,
            persist=False,
            placeholder="Select expected online players…",
            confirm_label="Expected online"
        )
    except Exception:
        pass

    try:
        return ActivePlayersView(
            all_players,
            preselected,
            session_state,
            on_done=on_done_cb,
            persist=False
        )
    except Exception:
        pass

    try:
        return ActivePlayersView(all_players, session_state, on_done_cb)
    except Exception:
        pass

    raise RuntimeError("ActivePlayersView constructor mismatch. Paste its __init__ signature here.")


# ------------------------------------------------------------------------------------------------------------
# LOW TEAM — season-true; rows filtered only (NO game filtering)
# ------------------------------------------------------------------------------------------------------------

def _pregame_low_team_results_filtered(allowed: set[str], season_id: int) -> list[tuple]:
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT pm.game_label, pm.player, pm.is_win
        FROM mr_player_match pm
        WHERE pm.season_id = ?
          AND pm.is_bot = 0
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        return []

    games = defaultdict(lambda: {"1": set(), "0": set()})
    display_names = {}

    for game_label, player, is_win in rows:
        if game_label is None or player is None:
            continue
        key = _pregame_canon(str(player))
        if not key:
            continue

        w = "1" if int(is_win or 0) == 1 else "0"
        games[str(game_label)][w].add(key)
        display_names[key] = str(player)

    low_team_counts = defaultdict(int)
    uneven_game_counts = defaultdict(int)
    low_team_win_counts = defaultdict(int)
    on_more_counts = defaultdict(int)
    on_more_loss_counts = defaultdict(int)

    for _label, teams in games.items():
        win_team = teams["1"]
        loss_team = teams["0"]
        if not win_team or not loss_team:
            continue

        if len(win_team) == len(loss_team):
            continue

        present = win_team | loss_team
        for p in present:
            uneven_game_counts[p] += 1

        if len(win_team) < len(loss_team):
            smaller = win_team
            smaller_won = True
            larger = loss_team
            larger_lost = True
        else:
            smaller = loss_team
            smaller_won = False
            larger = win_team
            larger_lost = False

        for p in smaller:
            low_team_counts[p] += 1
            if smaller_won:
                low_team_win_counts[p] += 1

        for p in larger:
            on_more_counts[p] += 1
            if larger_lost:
                on_more_loss_counts[p] += 1

    results = []
    for p in uneven_game_counts:
        name = display_names.get(p, p)
        low = int(low_team_counts.get(p, 0))
        unev = int(uneven_game_counts.get(p, 0))
        wless = int(low_team_win_counts.get(p, 0))

        pct_on_less = (low / unev * 100.0) if unev > 0 else 0.0
        winpct_on_less = (wless / low * 100.0) if low > 0 else 0.0

        more_ct = int(on_more_counts.get(p, 0))
        more_losses = int(on_more_loss_counts.get(p, 0))
        loss_pct_on_more = (more_losses / more_ct * 100.0) if more_ct > 0 else None

        results.append((name, low, unev, pct_on_less, winpct_on_less, loss_pct_on_more))

    if allowed:
        results = [r for r in results if _pregame_canon(str(r[0])) in allowed]

    results.sort(key=lambda x: (x[3], x[2], str(x[0]).lower()), reverse=True)
    return results


def _pregame_low_team_image_filtered(allowed: set[str], season_id: int) -> io.BytesIO | None:
    rows = _pregame_low_team_results_filtered(allowed, season_id)
    if not rows:
        return None
    return create_low_team_image_with_percent(rows, title=f"Low-Team % (Selected Players) — Season {season_id}")


# ------------------------------------------------------------------------------------------------------------
# TEAMMATE MATRIX FAIR (filtered)
# ------------------------------------------------------------------------------------------------------------

def _pregame_teammate_matrix_fair_image_filtered(allowed: set[str], season_id: int) -> io.BytesIO | None:
    if Image is None:
        return None

    ensure_mr_api_tables()

    c.execute(
        """
        SELECT game_label, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        return None

    game_teams = {}
    display_name_map = {}

    for game_label, player, camp in rows:
        if not game_label or not player:
            continue
        n = _pregame_canon(str(player))
        if allowed and n not in allowed:
            continue

        display_name_map[n] = str(player)
        game_teams.setdefault(game_label, {0: set(), 1: set(), -1: set()})

        if camp in (0, 1):
            game_teams[game_label][int(camp)].add(n)
        else:
            game_teams[game_label][-1].add(n)

    if not game_teams:
        return None

    same_team = defaultdict(lambda: defaultdict(int))
    overlap = defaultdict(lambda: defaultdict(int))

    for _label, teams in game_teams.items():
        all_players = set().union(*teams.values())
        if len(all_players) < 2:
            continue

        all_list = sorted(all_players)
        for a, b in combinations(all_list, 2):
            overlap[a][b] += 1
            overlap[b][a] += 1

        for camp_id in (0, 1):
            team = teams.get(camp_id) or set()
            if len(team) < 2:
                continue
            team_list = sorted(team)
            for a, b in combinations(team_list, 2):
                same_team[a][b] += 1
                same_team[b][a] += 1

    all_players = sorted(overlap.keys())
    if len(all_players) < 2:
        return None

    import pandas
    df = pandas.DataFrame(index=all_players, columns=all_players)

    for a in all_players:
        for b in all_players:
            if a == b:
                df.loc[a, b] = "-"
                continue
            ov = overlap[a].get(b, 0)
            st = same_team[a].get(b, 0)
            if ov <= 0:
                df.loc[a, b] = "0/0 (0%)"
            else:
                pct = round((st / ov) * 100)
                df.loc[a, b] = f"{st}/{ov} ({pct}%)"

    df.index = [display_name_map.get(n, n) for n in df.index]
    df.columns = [display_name_map.get(n, n) for n in df.columns]

    try:
        font, title_font = get_fonts()
    except Exception:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    padding = 20
    row_height = 40
    row_label_width = min(int(max(font.getlength(str(name)) for name in df.index)) + 30, 280)

    col_widths = []
    for col_idx, col in enumerate(df.columns):
        header_w = font.getlength(str(col))
        cell_w = max(font.getlength(str(df.iloc[row_idx, col_idx])) for row_idx in range(len(df)))
        w = min(int(max(header_w, cell_w)) + 30, 260)
        col_widths.append(w)

    width = int(row_label_width + sum(col_widths) + padding * 2)
    header_rows = 3
    height = int(padding + header_rows * row_height + len(df) * row_height + padding)

    img = Image.new("RGB", (width, height), (25, 25, 25))
    draw = ImageDraw.Draw(img)

    draw.text((padding, padding),
              f"Teammate Fairness Matrix — Selected Players — Season {season_id}",
              font=title_font, fill=(255, 215, 0))
    draw.text((padding, padding + row_height),
              "Higher % = usually teamed • ~50% = even split • Lower % = usually opposite teams",
              font=font, fill=(200, 200, 200))

    start_y = padding + 2 * row_height

    for col_idx, col in enumerate(df.columns):
        x = row_label_width + sum(col_widths[:col_idx]) + padding
        draw.text((x, start_y), str(col)[:22], font=font, fill=(230, 230, 230))

    for row_idx, row_player in enumerate(df.index):
        y = start_y + (row_idx + 1) * row_height
        draw.text((padding, y), str(row_player)[:22], font=font, fill=(230, 230, 230))

        for col_idx in range(len(df.columns)):
            val = str(df.iloc[row_idx, col_idx])
            x = row_label_width + sum(col_widths[:col_idx]) + padding
            draw.rectangle([x - 5, y - 5, x + col_widths[col_idx], y + row_height - 10],
                           outline=(100, 100, 100))
            draw.text((x, y), val, font=font, fill=(230, 230, 230))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out

def _nt_fix_team_monobans(team: set[str],
                          restricted_roles: dict[str, str],
                          restrict_debug: dict[str, dict]):
    """
    If team has 3+ humans AND every human has the SAME restricted role,
    then change exactly ONE player's restriction to a different role.

    Which player changes?
      - the player with the LOWEST share for the currently-banned role

    What do they change to?
      - the role (excluding the banned role) with the HIGHEST share for that player
        (ties resolved randomly)

    Note: This does not change output formatting; it only tweaks the restriction mapping.
    """
    if not team or len(team) < 3:
        return

    bans = [restricted_roles.get(p) for p in team]
    if any(b not in NT_ROLES for b in bans):
        return

    if len(set(bans)) != 1:
        return  # already mixed

    banned = bans[0]  # the role everyone is banned from

    def _share_for(p: str, role: str) -> float:
        shares = (restrict_debug.get(p) or {}).get("shares") or {}
        v = shares.get(role)
        return float(v) if isinstance(v, (int, float)) else (1.0 / 3.0)

    # pick player with least % time on the banned role
    min_share = None
    candidates = []
    for p in team:
        sh = _share_for(p, banned)
        if (min_share is None) or (sh < min_share - 1e-12):
            min_share = sh
            candidates = [p]
        elif abs(sh - min_share) <= 1e-12:
            candidates.append(p)

    p_change = random.choice(candidates) if candidates else random.choice(list(team))

    # change them to the "next" restriction: highest share among remaining roles
    alt_roles = [r for r in NT_ROLES if r != banned]
    alt_shares = [(r, _share_for(p_change, r)) for r in alt_roles]
    max_share = max(v for _, v in alt_shares)

    best = [r for r, v in alt_shares if abs(v - max_share) <= 1e-12]
    new_ban = random.choice(best) if best else random.choice(alt_roles)

    restricted_roles[p_change] = new_ban


# ------------------------------------------------------------------------------------------------------------
# LEADERBOARD IMAGE (filtered)
# ------------------------------------------------------------------------------------------------------------

def _pregame_leaderboard_image_filtered(allowed: set[str], season_id: int) -> io.BytesIO | None:
    if Image is None:
        return None

    ensure_auto_import_tables()
    ensure_mr_api_tables()

    c.execute("""
        SELECT
            player,
            kills, deaths, assists,
            damage, damage_taken, healing,
            win, loss,
            mvp, svp
        FROM game_stats_v
    """)
    rows = c.fetchall()
    if not rows:
        return None

    rows_f = []
    for r in rows:
        key = _pregame_canon(str(r[0]))
        if allowed and key not in allowed:
            continue
        rows_f.append(r)

    if not rows_f:
        return None

    MIN_GAMES_MAIN = 30

    agg = defaultdict(lambda: defaultdict(int))
    disp = {}

    for (player, k, d, a, dmg, taken, heal, win, loss, mvp, svp) in rows_f:
        n = _pregame_canon(str(player))
        if not n:
            continue
        disp[n] = str(player)

        agg[n]["kills"] += int(k or 0)
        agg[n]["deaths"] += int(d or 0)
        agg[n]["assists"] += int(a or 0)
        agg[n]["damage"] += int(dmg or 0)
        agg[n]["taken"] += int(taken or 0)
        agg[n]["healing"] += int(heal or 0)
        agg[n]["wins"] += int(win or 0)
        agg[n]["losses"] += int(loss or 0)
        agg[n]["mvp"] += int(mvp or 0)
        agg[n]["svp"] += int(svp or 0)

    data = []
    for n, s in agg.items():
        games = s["wins"] + s["losses"]
        if games <= 0:
            continue
        winrate = round((s["wins"] / games) * 100.0, 1)
        data.append({
            "player": disp.get(n, n),
            "games": int(games),
            "kills": int(s["kills"]),
            "deaths": int(s["deaths"]),
            "assists": int(s["assists"]),
            "damage": int(s["damage"]),
            "damage_taken": int(s["taken"]),
            "healing": int(s["healing"]),
            "wins": int(s["wins"]),
            "losses": int(s["losses"]),
            "mvp": int(s["mvp"]),
            "svp": int(s["svp"]),
            "winrate": float(winrate),
        })

    if not data:
        return None

    import pandas
    df = pandas.DataFrame(data)
    df_main = df[df["games"] >= MIN_GAMES_MAIN].copy()
    df_prov = df[df["games"] < MIN_GAMES_MAIN].copy()

    df_main = df_main.sort_values(by=["winrate", "wins"], ascending=[False, False]).reset_index(drop=True)
    df_prov = df_prov.sort_values(by=["winrate", "wins"], ascending=[False, False]).reset_index(drop=True)

    try:
        font, title_font = get_fonts()
    except Exception:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    headers = ["Player", "Avg K/D/A", "Avg Dmg", "Avg Taken", "Avg Heal", "W/L", "Win%", "MVP", "SVP"]
    col_widths = [200, 180, 160, 160, 160, 100, 100, 80, 80]
    x_positions = [sum(col_widths[:i]) + 20 for i in range(len(col_widths))]
    width = x_positions[-1] + col_widths[-1] + 20

    row_h = 45
    header_h = 60
    title_h = 55
    section_h = 48
    gap_h = 18

    n_main = len(df_main)
    n_prov = len(df_prov)

    height = title_h + header_h + section_h
    if n_main:
        height += n_main * row_h
    if n_prov:
        height += (gap_h if n_main else 0) + section_h + n_prov * row_h
    height += 20

    img = Image.new("RGB", (int(width), int(height)), (25, 25, 25))
    draw = ImageDraw.Draw(img)

    gold = (255, 215, 0)
    text_c = (235, 235, 235)
    muted = (170, 170, 170)
    header_bg = (40, 40, 60)
    section_bg = (32, 32, 44)
    border = (90, 90, 120)
    podium = [(255, 215, 0), (210, 210, 210), (205, 127, 50)]

    title = f"Leaderboard — Selected Players — Season {season_id}"
    tw = int(draw.textlength(title, font=title_font)) if hasattr(draw, "textlength") else len(title) * 10
    draw.text(((width - tw) // 2, 10), title, fill=gold, font=title_font)

    y = title_h
    for i, h in enumerate(headers):
        x = x_positions[i]
        draw.rectangle([x - 10, y, x - 10 + col_widths[i], y + header_h], fill=header_bg, outline=border)
        draw.text((x, y + 15), h, fill=text_c, font=font)

    def _section(y0: int, label: str):
        draw.rectangle([10, y0, width - 10, y0 + section_h], fill=section_bg, outline=border)
        draw.text((20, y0 + 12), label, fill=gold, font=title_font)

    def _rows(df0, y0: int, podium_on: bool):
        for idx, row in df0.iterrows():
            g = int(row["games"])
            avg_k = row["kills"] / g
            avg_d = row["deaths"] / g
            avg_a = row["assists"] / g

            vals = [
                str(row["player"])[:16].ljust(16),
                f"{avg_k:.1f}/{avg_d:.1f}/{avg_a:.1f}",
                f"{round(row['damage'] / g):,}",
                f"{round(row['damage_taken'] / g):,}",
                f"{round(row['healing'] / g):,}",
                f"{int(row['wins'])}/{int(row['losses'])}",
                f"{float(row['winrate']):.1f}%",
                str(int(row["mvp"])),
                str(int(row["svp"]))
            ]

            color = podium[idx] if (podium_on and idx < 3) else text_c
            for i, v in enumerate(vals):
                x = x_positions[i]
                draw.rectangle([x - 10, y0, x - 10 + col_widths[i], y0 + row_h], outline=border)
                draw.text((x, y0 + 10), v, fill=color, font=font)

            y0 += row_h
        return y0

    y = title_h + header_h

    if n_main:
        _section(y, f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games)")
        y += section_h
        y = _rows(df_main, y, podium_on=True)
    else:
        _section(y, f"Main Leaderboard (≥ {MIN_GAMES_MAIN} games) — None yet")
        draw.text((20, y + 12),
                  f"Play at least {MIN_GAMES_MAIN} games to appear in the main rankings.",
                  fill=muted, font=font)
        y += section_h

    if n_prov:
        if n_main:
            y += gap_h
        _section(y, f"Provisional ( < {MIN_GAMES_MAIN} games ) — not ranked against main")
        y += section_h
        y = _rows(df_prov, y, podium_on=False)

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


# ------------------------------------------------------------------------------------------------------------
# SEASON STORY ROLE TRIANGLE (filtered)
# ------------------------------------------------------------------------------------------------------------

async def _pregame_role_triangle_image_filtered(allowed: set[str], season_id: int) -> io.BytesIO | None:
    if Image is None:
        return None

    rr = await _ss_role_distribution(season_id)
    if not rr:
        return None

    rr_f = []
    uids = set()

    for r in rr:
        try:
            uid = int(r.get("player_uid", 0))
        except Exception:
            continue
        name = _ss_player_name(season_id, uid)
        if allowed and _pregame_canon(name) not in allowed:
            continue
        rr_f.append(r)
        uids.add(uid)

    if len(rr_f) < 2:
        return None

    names_map = {uid: _ss_player_name(season_id, uid) for uid in uids}

    W, H = 980, 760
    pad = 26
    bg = (20, 20, 26)
    card = (32, 32, 44)
    line = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)
    muted = (180, 180, 200)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=22, fill=card)

    try:
        fonts = get_fonts()
        body_font = fonts[0] if isinstance(fonts, tuple) else ImageFont.load_default()
        title_font = fonts[1] if (isinstance(fonts, tuple) and len(fonts) > 1) else ImageFont.load_default()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.text((pad * 2, int(pad * 1.35)),
              f"Role Distribution Triangle — Selected Players — Season {season_id}",
              font=title_font, fill=accent)

    x = pad * 2
    y = pad * 2 + 34
    width = W - pad * 4
    height = H - y - pad * 2

    _ss_draw_role_ternary_plot(
        draw=draw,
        x=x,
        y=y,
        width=width,
        height=height,
        role_rows=rr_f,
        player_names=names_map,
        body_font=body_font,
        LH=26,
        accent=accent,
        text=text,
        muted=muted,
        line=line
    )

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


# ------------------------------------------------------------------------------------------------------------
# Determinations: Bouncers + Team-less likelihood
# ------------------------------------------------------------------------------------------------------------

def _pregame_compute_bouncers_and_lowteam(allowed: set[str], season_id: int) -> tuple[list[str], list[str]]:
    # Team-less likelihood (lowest % on less)
    lt_rows = _pregame_low_team_results_filtered(allowed, season_id)
    lt_rank = []
    for (name, low, unev, pct_on_less, _wless, _loss_more) in lt_rows:
        lt_rank.append((float(pct_on_less), int(unev), str(name), int(low)))
    lt_rank.sort(key=lambda x: (x[0], x[1], x[2].lower()))

    lowteam_lines = []
    for pct, unev, name, low in lt_rank[:3]:
        if unev > 0:
            lowteam_lines.append(f"• {name}: {pct:.1f}% on less ({low}/{unev} uneven)")
        else:
            lowteam_lines.append(f"• {name}: {pct:.1f}% on less (no uneven history)")
    if not lowteam_lines:
        lowteam_lines = ["• No team-less likelihood could be determined."]

    # Bouncers
    ensure_auto_import_tables()
    ensure_mr_api_tables()

    c.execute("SELECT player, win, loss FROM game_stats_v")
    wl_rows = c.fetchall()

    wl = defaultdict(lambda: [0, 0])
    disp = {}
    for player, w, l in wl_rows:
        k = _pregame_canon(str(player))
        if allowed and k not in allowed:
            continue
        wl[k][0] += int(w or 0)
        wl[k][1] += int(l or 0)
        disp[k] = str(player)

    perf = []
    for k, (w, l) in wl.items():
        g = w + l
        if g <= 0:
            continue
        perf.append((w / g, g, k))

    if len(perf) < 2:
        return (["• Not enough W/L history in this pool to compute bouncers."], lowteam_lines)

    perf_sorted = sorted(perf, key=lambda x: (x[0], x[1]), reverse=True)
    perf_sorted_low = sorted(perf, key=lambda x: (x[0], -x[1]))

    MIN_GAMES_FOR_RANK = 10
    best_keys = [k for wr, g, k in perf_sorted if g >= MIN_GAMES_FOR_RANK][:3] or [k for _wr, _g, k in perf_sorted[:2]]
    low_keys = [k for wr, g, k in perf_sorted_low if g >= MIN_GAMES_FOR_RANK][:4] or [k for _wr, _g, k in perf_sorted_low[:3]]
    low_keys = [k for k in low_keys if k not in best_keys]

    best_names = ", ".join(disp.get(k, k) for k in best_keys)
    bouncers_lines = [f"Best players in this pool: {best_names}"]

    if not low_keys:
        bouncers_lines.append("• No distinct low-win players identified.")
        return (bouncers_lines, lowteam_lines)

    c.execute(
        """
        SELECT game_label, player, camp
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        bouncers_lines.append("• No teammate history found for this season.")
        return (bouncers_lines, lowteam_lines)

    game_teams = {}
    for game_label, player, camp in rows:
        if not game_label or not player:
            continue
        n = _pregame_canon(str(player))
        if allowed and n not in allowed:
            continue
        game_teams.setdefault(game_label, {0: set(), 1: set(), -1: set()})
        if camp in (0, 1):
            game_teams[game_label][int(camp)].add(n)
        else:
            game_teams[game_label][-1].add(n)

    same_team = defaultdict(lambda: defaultdict(int))
    overlap = defaultdict(lambda: defaultdict(int))

    for _label, teams in game_teams.items():
        all_players = set().union(*teams.values())
        if len(all_players) < 2:
            continue
        all_list = sorted(all_players)
        for a, b in combinations(all_list, 2):
            overlap[a][b] += 1
            overlap[b][a] += 1

        for camp_id in (0, 1):
            team = teams.get(camp_id) or set()
            if len(team) < 2:
                continue
            for a, b in combinations(sorted(team), 2):
                same_team[a][b] += 1
                same_team[b][a] += 1

    MIN_OVERLAP = 3
    candidates = []
    for lk in low_keys:
        pairings = []
        for bk in best_keys:
            ov = overlap[lk].get(bk, 0)
            if ov < MIN_OVERLAP:
                continue
            st = same_team[lk].get(bk, 0)
            pct = (st / ov) * 100.0
            pairings.append((pct, ov, bk))

        if not pairings:
            for bk in best_keys:
                ov = overlap[lk].get(bk, 0)
                if ov <= 0:
                    continue
                st = same_team[lk].get(bk, 0)
                pct = (st / ov) * 100.0
                pairings.append((pct, ov, bk))

        if not pairings:
            continue

        pairings.sort(key=lambda x: (x[0], -x[1]))
        top2 = pairings[:2]
        score = sum(p for p, _ov, _bk in top2) / len(top2)
        candidates.append((score, lk, top2))

    if not candidates:
        bouncers_lines.append("• Not enough teammate history to compute bouncers.")
        return (bouncers_lines, lowteam_lines)

    candidates.sort(key=lambda x: x[0])
    for _score, lk, top2 in candidates[:3]:
        low_name = disp.get(lk, lk)
        parts = [f"{disp.get(bk, bk)} ({pct:.0f}%)" for (pct, _ov, bk) in top2]
        if len(parts) >= 2:
            bouncers_lines.append(f"• {low_name} bouncing on {parts[0]} and {parts[1]}")
        else:
            bouncers_lines.append(f"• {low_name} bouncing on {parts[0]}")

    return (bouncers_lines, lowteam_lines)

def _pregame_build_session_day_player_wl(season_id: int, allowed: set[str]) -> dict[str, list[tuple[int, int]]]:
    ensure_mr_api_tables()
    ensure_auto_import_tables()

    try:
        c.execute(
            """
            SELECT pm.game_label, pm.player, pm.is_win, mi.imported_at
            FROM mr_player_match pm
            JOIN match_imports mi ON mi.game_label = pm.game_label
            WHERE pm.season_id = ?
              AND pm.is_bot = 0
              AND mi.season_id = ?
              AND mi.imported_at IS NOT NULL
            """,
            (season_id, season_id)
        )
        rows = c.fetchall()
    except Exception:
        rows = []

    by_day_player = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # day -> p -> [w,l]

    for _gl, player, is_win, imported_at in rows:
        if not player or not imported_at:
            continue
        p = _pregame_canon(str(player))
        if allowed and p not in allowed:
            continue
        day = str(imported_at)[:10]
        if int(is_win or 0) == 1:
            by_day_player[day][p][0] += 1
        else:
            by_day_player[day][p][1] += 1

    days = sorted(by_day_player.keys())
    out = defaultdict(list)
    for d in days:
        for p, (w, l) in by_day_player[d].items():
            out[p].append((int(w), int(l)))
    return dict(out)


def _pregame_estimate_games_per_player_from_sessions(season_id: int, allowed: set[str]) -> dict[str, int]:
    """
    Average per-session games, +2 extra games for everyone, then clamp 3..12.
    """
    hist = _pregame_build_session_day_player_wl(season_id, allowed)
    out = {}
    for p in allowed:
        wl_list = hist.get(p, [])
        if not wl_list:
            out[p] = 10  # was 8; now +2
            continue
        games = [w + l for (w, l) in wl_list if (w + l) > 0]
        if not games:
            out[p] = 10  # was 8; now +2
            continue
        avg = sum(games) / len(games)
        tgt = int(round(avg)) + 2
        out[p] = max(3, min(12, tgt))
    return out


def _pregame_night_form_params(season_id: int,
                               allowed: set[str],
                               *,
                               recent_sessions: int = 8,
                               recency_decay: float = 0.75) -> dict[str, tuple[float, float]]:
    hist = _pregame_build_session_day_player_wl(season_id, allowed)
    params = {}

    for p in allowed:
        wl_list = hist.get(p, [])
        if wl_list:
            wl_list = wl_list[-recent_sessions:] if len(wl_list) > recent_sessions else wl_list
            n = len(wl_list)
            wsum = 0.0
            lsum = 0.0
            for i, (w, l) in enumerate(wl_list):
                age = (n - 1) - i
                wt = (recency_decay ** age)
                wsum += wt * float(w)
                lsum += wt * float(l)
        else:
            wsum = 0.0
            lsum = 0.0

        params[p] = (1.8 + wsum, 1.8 + lsum)

    return params


def _pregame_session_inconsistency(season_id: int, allowed: set[str]) -> dict[str, float]:
    """
    Returns per-player inconsistency score based on session-to-session win% variance.
    Higher => more boom/bust nights.
    """
    hist = _pregame_build_session_day_player_wl(season_id, allowed)
    out = {}
    for p in allowed:
        wl_list = hist.get(p, [])
        pcts = []
        for w, l in wl_list:
            g = w + l
            if g >= 3:
                pcts.append(w / g)
        if len(pcts) < 3:
            out[p] = 0.08  # default moderate volatility
            continue
        mu = sum(pcts) / len(pcts)
        var = sum((x - mu) ** 2 for x in pcts) / max(1, (len(pcts) - 1))
        sd = math.sqrt(var)
        out[p] = max(0.04, min(0.18, sd))
    return out


def _pregame_get_season_winrate_map(allowed: set[str]) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[int, int]]]:
    ensure_auto_import_tables()
    c.execute("SELECT player, win, loss FROM game_stats_v")
    rows = c.fetchall()

    wl = defaultdict(lambda: [0, 0])
    disp = {}
    for player, w, l in rows:
        k = _pregame_canon(str(player))
        if allowed and k not in allowed:
            continue
        wl[k][0] += int(w or 0)
        wl[k][1] += int(l or 0)
        disp[k] = str(player)

    wr = {}
    for k, (w, l) in wl.items():
        g = w + l
        wr[k] = (w / g) if g > 0 else 0.5

    wl_int = {k: (int(v[0]), int(v[1])) for k, v in wl.items()}
    return wr, disp, wl_int


def _pregame_pair_synergy_table(season_id: int, allowed: set[str]) -> dict[tuple[str, str], tuple[float, int]]:
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT game_label, player, camp, is_win
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        return {}

    by_game_camp = defaultdict(lambda: defaultdict(list))  # game -> camp -> [(p, is_win)]
    for gl, player, camp, is_win in rows:
        if not gl or player is None:
            continue
        p = _pregame_canon(str(player))
        if allowed and p not in allowed:
            continue
        if camp not in (0, 1):
            continue
        by_game_camp[str(gl)][int(camp)].append((p, int(is_win or 0)))

    pair_wins = defaultdict(int)
    pair_games = defaultdict(int)

    for _gl, camps in by_game_camp.items():
        for camp_id, plist in camps.items():
            players = sorted({p for p, _w in plist})
            if len(players) < 2:
                continue

            team_won = 1 if sum(w for _p, w in plist) >= (len(plist) / 2.0) else 0

            for a, b in combinations(players, 2):
                key = (a, b) if a < b else (b, a)
                pair_games[key] += 1
                if team_won == 1:
                    pair_wins[key] += 1

    out = {}
    for key, g in pair_games.items():
        w = pair_wins.get(key, 0)
        out[key] = (w / g if g > 0 else 0.5, int(g))
    return out


def _pregame_team_synergy_score(team: set[str], pair_tbl: dict[tuple[str, str], tuple[float, int]]) -> float:
    if len(team) < 2:
        return 0.0

    deltas = []
    K = 5.0  # less shrink => stronger synergy impact (more "buzz")
    for a, b in combinations(sorted(team), 2):
        key = (a, b) if a < b else (b, a)
        if key not in pair_tbl:
            continue
        wr, g = pair_tbl[key]
        shrink = (g / (g + K)) if g > 0 else 0.0
        deltas.append((wr - 0.5) * shrink)

    if not deltas:
        return 0.0

    return sum(deltas) / len(deltas)


def _pregame_opponent_table(season_id: int, allowed: set[str]) -> dict[tuple[str, str], tuple[float, int]]:
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT game_label, player, camp, is_win
        FROM mr_player_match
        WHERE season_id = ?
          AND is_bot = 0
          AND camp IN (0,1)
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        return {}

    by_game = defaultdict(lambda: {0: [], 1: []})  # gl -> camp -> [(p, is_win)]
    for gl, player, camp, is_win in rows:
        if not gl or player is None:
            continue
        p = _pregame_canon(str(player))
        if allowed and p not in allowed:
            continue
        by_game[str(gl)][int(camp)].append((p, int(is_win or 0)))

    wins = defaultdict(int)
    games = defaultdict(int)

    for _gl, camps in by_game.items():
        t0 = sorted({p for p, _w in camps[0]})
        t1 = sorted({p for p, _w in camps[1]})
        if not t0 or not t1:
            continue

        win0 = 1 if sum(w for _p, w in camps[0]) >= (len(camps[0]) / 2.0) else 0
        win1 = 1 if sum(w for _p, w in camps[1]) >= (len(camps[1]) / 2.0) else 0

        for a in t0:
            for b in t1:
                games[(a, b)] += 1
                games[(b, a)] += 1
                if win0 == 1:
                    wins[(a, b)] += 1
                if win1 == 1:
                    wins[(b, a)] += 1

    out = {}
    for key, g in games.items():
        w = wins.get(key, 0)
        out[key] = (w / g if g > 0 else 0.5, int(g))
    return out


def _pregame_team_matchup_score(team_a: set[str],
                                team_b: set[str],
                                opp_tbl: dict[tuple[str, str], tuple[float, int]]) -> float:
    if not team_a or not team_b:
        return 0.0

    K = 8.0
    deltas = []

    for a, b in product(sorted(team_a), sorted(team_b)):
        key = (a, b)
        if key not in opp_tbl:
            continue
        wr, g = opp_tbl[key]
        shrink = (g / (g + K)) if g > 0 else 0.0
        deltas.append((wr - 0.5) * shrink)

    if not deltas:
        return 0.0

    return sum(deltas) / len(deltas)


@dataclass
class _PregameDisplayFairCtx:
    games_played: dict[str, int] = field(default_factory=dict)
    low_team_games: dict[str, int] = field(default_factory=dict)
    uneven_games: dict[str, int] = field(default_factory=dict)
    low_team_pair_games: dict[tuple[str, str], int] = field(default_factory=dict)
    pair_games: dict[tuple[str, str], int] = field(default_factory=dict)

    low_team_pair_pct: dict[tuple[str, str], float] = field(default_factory=dict)
    avg_low_team_pair_pct_by_player: dict[str, float] = field(default_factory=dict)


def _pregame_build_display_fairness_context(season_id: int) -> _PregameDisplayFairCtx:
    ensure_mr_api_tables()

    c.execute(
        """
        SELECT pm.game_label, pm.player, pm.is_win
        FROM mr_player_match pm
        WHERE pm.season_id = ?
          AND pm.is_bot = 0
        """,
        (season_id,)
    )
    rows = c.fetchall()
    if not rows:
        return _PregameDisplayFairCtx()

    games_played = defaultdict(int)
    low_team_games = defaultdict(int)
    uneven_games = defaultdict(int)
    low_team_pair_games = defaultdict(int)
    pair_games = defaultdict(int)
    by_game = defaultdict(list)

    for game_label, player, is_win in rows:
        if game_label is None or player is None:
            continue
        p = _pregame_canon(str(player))
        games_played[p] += 1
        by_game[str(game_label)].append((p, int(is_win or 0)))

    for _gl, entries in by_game.items():
        winners = {p for p, w in entries if w == 1}
        losers = {p for p, w in entries if w == 0}

        if winners and losers and len(winners) != len(losers):
            present = winners | losers
            for p in present:
                uneven_games[p] += 1

            low = winners if len(winners) < len(losers) else losers
            for p in low:
                low_team_games[p] += 1

            for a, b in combinations(sorted(low), 2):
                key = (a, b) if a < b else (b, a)
                low_team_pair_games[key] += 1

        for team in (winners, losers):
            for a, b in combinations(sorted(team), 2):
                key = (a, b) if a < b else (b, a)
                pair_games[key] += 1

    low_team_pair_pct = {}
    avg_low_pair_by_player = defaultdict(list)
    for (a, b), gms in low_team_pair_games.items():
        min_low = max(1, min(low_team_games.get(a, 0), low_team_games.get(b, 0)))
        pct = gms / min_low
        low_team_pair_pct[(a, b)] = pct
        avg_low_pair_by_player[a].append(pct)
        avg_low_pair_by_player[b].append(pct)

    return _PregameDisplayFairCtx(
        games_played=dict(games_played),
        low_team_games=dict(low_team_games),
        uneven_games=dict(uneven_games),
        low_team_pair_games=dict(low_team_pair_games),
        pair_games=dict(pair_games),
        low_team_pair_pct=dict(low_team_pair_pct),
        avg_low_team_pair_pct_by_player={
            p: (sum(vs) / len(vs)) if vs else 0.0
            for p, vs in avg_low_pair_by_player.items()
        },
    )


def _pregame_pick_best_split(active: list[str], ctx_disp: _PregameDisplayFairCtx, session_stub: "SessionState") -> tuple[set[str], set[str], set[str] | None]:
    n = len(active)
    if n < 4:
        half = n // 2
        a = set(active[:half])
        b = set(active[half:])
        low = a if len(a) < len(b) else (b if len(b) < len(a) else None)
        return a, b, low

    tmp_ctx = FairnessContext(
        games_played=ctx_disp.games_played,
        low_team_games=ctx_disp.low_team_games,
        uneven_games=ctx_disp.uneven_games,
        low_team_pair_games=ctx_disp.low_team_pair_games,
        pair_games=ctx_disp.pair_games,
        low_team_pair_pct=ctx_disp.low_team_pair_pct,
        avg_low_team_pair_pct_by_player=ctx_disp.avg_low_team_pair_pct_by_player,
    )

    size_a = n // 2
    size_b = n - size_a
    if size_a > size_b:
        size_a, size_b = size_b, size_a

    players = sorted(active)
    best = None
    best_score = None

    if n <= 12:
        for comb in combinations(players, size_a):
            team_a = frozenset(comb)
            team_b = frozenset([p for p in players if p not in team_a])
            low_team = None
            if len(team_a) != len(team_b):
                low_team = team_a if len(team_a) < len(team_b) else team_b

            score, _dbg = _compute_fairness_score(team_a, team_b, low_team, tmp_ctx, session_stub, players, debug=False)
            if best_score is None or score < best_score:
                best_score = score
                best = (set(team_a), set(team_b), set(low_team) if low_team else None)
    else:
        K = 250
        for _ in range(K):
            team_a = set(random.sample(players, size_a))
            team_b = set([p for p in players if p not in team_a])
            low_team = None
            if len(team_a) != len(team_b):
                low_team = team_a if len(team_a) < len(team_b) else team_b

            score, _dbg = _compute_fairness_score(
                frozenset(team_a),
                frozenset(team_b),
                frozenset(low_team) if low_team else None,
                tmp_ctx,
                session_stub,
                players,
                debug=False
            )
            if best_score is None or score < best_score:
                best_score = score
                best = (set(team_a), set(team_b), set(low_team) if low_team else None)

    if best is None:
        team_a = set(random.sample(players, size_a))
        team_b = set([p for p in players if p not in team_a])
        low = team_a if len(team_a) < len(team_b) else (team_b if len(team_b) < len(team_a) else None)
        return team_a, team_b, low

    return best


def _pregame_predict_team_a_win_prob(team_a: set[str],
                                    team_b: set[str],
                                    night_form: dict[str, float],
                                    season_wr: dict[str, float],
                                    pair_tbl: dict[tuple[str, str], tuple[float, int]],
                                    opp_tbl: dict[tuple[str, str], tuple[float, int]],
                                    momentum: dict[str, float] | None = None,
                                    shock: dict[str, float] | None = None) -> float:
    """
    SWINGY MODE:
      - heavier synergy weighting
      - explicit shock (meltdown/pop-off) affects player form
      - less clamping; steeper logistic => more separation
    """
    momentum = momentum or {}
    shock = shock or {}

    def _clamp01(x: float) -> float:
        return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)

    def avg_form(team: set[str]) -> float:
        if not team:
            return 0.5
        vals = []
        for p in team:
            nf = night_form.get(p, 0.5)
            sw = season_wr.get(p, 0.5)
            m = momentum.get(p, 0.0)
            s = shock.get(p, 0.0)
            base = 0.84 * nf + 0.16 * sw
            vals.append(_clamp01(base + m + s))
        return sum(vals) / len(vals)

    sa = avg_form(team_a)
    sb = avg_form(team_b)

    syn_a = _pregame_team_synergy_score(team_a, pair_tbl)
    syn_b = _pregame_team_synergy_score(team_b, pair_tbl)
    sa += 0.48 * syn_a
    sb += 0.48 * syn_b

    matchup_a = _pregame_team_matchup_score(team_a, team_b, opp_tbl)
    matchup_b = _pregame_team_matchup_score(team_b, team_a, opp_tbl)
    sa += 0.26 * matchup_a
    sb += 0.26 * matchup_b

    if len(team_a) != len(team_b):
        if len(team_a) > len(team_b):
            sa += 0.12
        else:
            sb += 0.12

    d = sa - sb
    p = 1.0 / (1.0 + math.exp(-7.8 * d))
    return max(0.03, min(0.97, p))

# ------------------------------------------------------------------------------------------------------------
# Predicted session leaderboard — SWINGY MODE
#   Behavior:
#     - ORDER by predicted win-rate (based on displayed rounded ~W-L so the % and ordering are consistent)
#     - Predicted leaderboard changes: ranks are computed from CURRENT season W/L (same source as leaderboard_image)
#       plus the predicted (rounded) W/L, then shows position movement.
# ------------------------------------------------------------------------------------------------------------

def _pregame_compute_predicted_session_leaderboard(
    allowed: set[str],
    season_id: int,
    *,
    sims: int = 3
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    if not allowed or len(allowed) < 2:
        return (["• Not enough selected players to predict a session leaderboard."], {})

    season_wr, disp, _wl_int = _pregame_get_season_winrate_map(allowed)
    targets = _pregame_estimate_games_per_player_from_sessions(season_id, allowed)

    beta_params = _pregame_night_form_params(season_id, allowed, recent_sessions=8, recency_decay=0.75)
    incons = _pregame_session_inconsistency(season_id, allowed)

    pair_tbl = _pregame_pair_synergy_table(season_id, allowed)
    opp_tbl = _pregame_opponent_table(season_id, allowed)

    ctx_disp = _pregame_build_display_fairness_context(season_id)
    allowed_list = sorted(list(allowed))

    # --- SWINGY knobs ---
    upset_sigma = 0.10
    p_beta_k = 10.0
    momentum_step = 0.030
    momentum_cap = 0.16

    shock_prob = 0.22
    shock_sd = 0.10

    sims = max(1, int(sims))

    agg_w = defaultdict(float)
    agg_l = defaultdict(float)
    agg_g = defaultdict(float)

    for _ in range(sims):
        night_form: dict[str, float] = {}
        shock: dict[str, float] = {}

        for p in allowed_list:
            a, b = beta_params.get(p, (1.8, 1.8))
            nf = random.betavariate(a, b)
            nf = max(0.05, min(0.95, nf + random.gauss(0.0, incons.get(p, 0.08) * 0.55)))
            night_form[p] = nf

            if random.random() < shock_prob:
                if random.random() < 0.55:
                    shock[p] = -abs(random.gauss(0.0, shock_sd))
                else:
                    shock[p] = abs(random.gauss(0.0, shock_sd))
            else:
                shock[p] = 0.0

        remaining = {p: int(targets.get(p, 10)) for p in allowed_list}
        sim_w = defaultdict(int)
        sim_l = defaultdict(int)

        momentum = {p: 0.0 for p in allowed_list}
        session_stub = SessionState()
        safety = 0

        while any(v > 0 for v in remaining.values()) and safety < 420:
            safety += 1
            pool = [p for p, r in remaining.items() if r > 0]
            if len(pool) < 4:
                break

            desired = min(len(pool), random.choice([6, 7, 8, 9, 10, 8, 7]))
            desired = max(4, desired)

            weights = [max(1, remaining[p]) for p in pool]
            chosen = []
            pool2 = pool[:]
            weights2 = weights[:]
            for _i in range(min(desired, len(pool2))):
                tot = sum(weights2)
                r = random.uniform(0, tot)
                acc = 0.0
                idx = 0
                for j, w in enumerate(weights2):
                    acc += w
                    if acc >= r:
                        idx = j
                        break
                chosen.append(pool2.pop(idx))
                weights2.pop(idx)

            if len(chosen) < 4:
                continue

            team_a, team_b, low_team = _pregame_pick_best_split(chosen, ctx_disp, session_stub)

            p_a = _pregame_predict_team_a_win_prob(
                team_a, team_b,
                night_form, season_wr,
                pair_tbl, opp_tbl,
                momentum=momentum,
                shock=shock
            )

            p_a = max(0.03, min(0.97, p_a + random.gauss(0.0, upset_sigma)))

            a = max(0.35, p_a * p_beta_k)
            b = max(0.35, (1.0 - p_a) * p_beta_k)
            p_a2 = random.betavariate(a, b)

            a_wins = (random.random() < p_a2)

            winners = team_a if a_wins else team_b
            losers = team_b if a_wins else team_a

            for p in winners:
                sim_w[p] += 1
                momentum[p] = min(momentum_cap, momentum[p] + momentum_step)

            for p in losers:
                sim_l[p] += 1
                momentum[p] = max(-momentum_cap, momentum[p] - momentum_step)

            session_stub.session_games.append({
                "team_a": frozenset(team_a),
                "team_b": frozenset(team_b),
                "low_team": frozenset(low_team) if low_team else None,
            })

            for p in chosen:
                if remaining.get(p, 0) > 0:
                    remaining[p] -= 1

        for p in allowed_list:
            w = sim_w.get(p, 0)
            l = sim_l.get(p, 0)
            g = w + l
            if g <= 0:
                continue
            agg_w[p] += w
            agg_l[p] += l
            agg_g[p] += g

    predicted_wl: dict[str, tuple[float, float]] = {}
    entries = []

    for p in allowed_list:
        g = agg_g.get(p, 0.0)
        if g <= 0:
            continue

        ew = agg_w[p] / sims
        el = agg_l[p] / sims
        predicted_wl[p] = (ew, el)

        # DISPLAYED W-L (rounded) drives BOTH:
        #   - displayed % (must match W-L)
        #   - ordering by predicted win rate
        w_i = max(0, int(round(ew)))
        l_i = max(0, int(round(el)))
        g_i = w_i + l_i
        pct_pred = (w_i / g_i) if g_i > 0 else 0.0

        # Sort tie-breakers: win% then wins then games then name
        entries.append((pct_pred, w_i, g_i, disp.get(p, p), p, l_i))

    if not entries:
        return (["• Could not form a predicted session leaderboard."], {})

    # ORDERING: by predicted win rate (from displayed rounded W-L), then wins, then games, then name
    entries.sort(key=lambda t: (t[0], t[1], t[2], t[3].lower()), reverse=True)

    lines = []
    for i, (pct_pred, w_i, g_i, name, _p, l_i) in enumerate(entries[:10], start=1):
        lines.append(f"• {i}. {name}: ~{w_i}-{l_i} ({pct_pred*100.0:.0f}%)")

    return (lines, predicted_wl)


def _pregame_compute_predicted_leaderboard_changes(
    allowed: set[str],
    season_id: int,
    *,
    predicted_wl: dict[str, tuple[float, float]],
    max_lines: int = 12
) -> list[str]:
    """
    CONFIRMED BEHAVIOUR:
      - Current ranks are computed from current season W/L from game_stats_v
        (same source used by the leaderboard image).
      - "After" ranks are computed by adding predicted (rounded) W/L onto the current season W/L.
      - Output lists only players whose rank position changes.
    """
    _season_wr, disp, wl_int = _pregame_get_season_winrate_map(allowed)

    if not wl_int:
        return ["• No rank changes predicted."]

    def _rank(wl_map: dict[str, tuple[int, int]]):
        ranked = []
        for k, (w, l) in wl_map.items():
            g = w + l
            wr = (w / g) if g > 0 else 0.0
            ranked.append((wr, w, g, disp.get(k, k), k))
        # Match leaderboard-style ordering: win%, then wins, then games, then name
        ranked.sort(key=lambda t: (t[0], t[1], t[2], t[3].lower()), reverse=True)
        return ranked

    # Current season ranking (same W/L base as leaderboard_image)
    cur_ranked = _rank(wl_int)
    cur_pos = {k: i + 1 for i, (_wr, _w, _g, _nm, k) in enumerate(cur_ranked)}

    # Apply predicted W/L (rounded from predicted_wl floats)
    after = {}
    for k, (w, l) in wl_int.items():
        ew, el = predicted_wl.get(k, (0.0, 0.0))
        pw = int(round(ew))
        pl = int(round(el))
        after[k] = (int(w) + pw, int(l) + pl)

    after_ranked = _rank(after)
    after_pos = {k: i + 1 for i, (_wr, _w, _g, _nm, k) in enumerate(after_ranked)}

    movers = []
    for k in cur_pos.keys():
        c0 = cur_pos[k]
        c1 = after_pos.get(k, c0)
        if c1 == c0:
            continue
        delta = c0 - c1
        arrow = f"↑{delta}" if delta > 0 else f"↓{abs(delta)}"
        movers.append((
            abs(delta),
            delta > 0,
            disp.get(k, k).lower(),
            f"• {disp.get(k, k)}: {arrow} ({c0} → {c1})"
        ))

    if not movers:
        return ["• No rank changes predicted."]

    movers.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [m[3] for m in movers[:max_lines]]




# ------------------------------------------------------------------------------------------------------------
# Determinations image (stacked)
# ------------------------------------------------------------------------------------------------------------

def _pregame_determinations_image(allowed: set[str], season_id: int) -> io.BytesIO | None:
    if Image is None:
        return None

    try:
        bouncers_lines, lowteam_lines = _pregame_compute_bouncers_and_lowteam(allowed, season_id)
    except Exception as e:
        bouncers_lines = [f"• Error computing bouncers: {type(e).__name__}: {e}"]
        lowteam_lines = []

    try:
        predicted_lines, predicted_wl = _pregame_compute_predicted_session_leaderboard(allowed, season_id, sims=3)
    except Exception as e:
        predicted_lines = [f"• Error computing predicted leaderboard: {type(e).__name__}: {e}"]
        predicted_wl = {}

    try:
        change_lines = _pregame_compute_predicted_leaderboard_changes(allowed, season_id, predicted_wl=predicted_wl)
    except Exception as e:
        change_lines = [f"• Error computing predicted changes: {type(e).__name__}: {e}"]

    W = 1100
    pad = 26
    bg = (20, 20, 26)
    card = (32, 32, 44)
    divider = (80, 80, 100)
    accent = (255, 215, 0)
    text = (235, 235, 235)

    try:
        fonts = get_fonts()
        body_font = fonts[0] if isinstance(fonts, tuple) else ImageFont.load_default()
        title_font = fonts[1] if (isinstance(fonts, tuple) and len(fonts) > 1) else ImageFont.load_default()
    except Exception:
        body_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    max_w = W - pad * 4
    tmp = Image.new("RGB", (W, 10), bg)
    tmp_draw = ImageDraw.Draw(tmp)

    def _wrap_line(s: str) -> list[str]:
        s = str(s or "")
        if not s:
            return [""]

        lead = ""
        rest = s
        if rest.startswith("• "):
            lead = "• "
            rest = rest[2:]

        words = rest.split()
        if not words:
            return [lead.strip()]

        out = []
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            try:
                tw = int(tmp_draw.textlength(lead + trial, font=body_font))
            except Exception:
                tw = len(lead + trial) * 10

            if tw <= max_w:
                cur = trial
            else:
                if cur:
                    out.append(lead + cur)
                cur = w

        if cur:
            out.append(lead + cur)
        return out

    def _wrap_block(lines: list[str]) -> list[str]:
        out = []
        for ln in (lines or []):
            out.extend(_wrap_line(ln))
        return out

    wb = _wrap_block(bouncers_lines) if bouncers_lines else ["• No bouncers could be determined."]
    wl = _wrap_block(lowteam_lines) if lowteam_lines else ["• No team-less likelihood could be determined."]
    wp = _wrap_block(predicted_lines) if predicted_lines else ["• No predicted session leaderboard available."]
    wc = _wrap_block(change_lines) if change_lines else ["• No rank changes predicted."]

    line_h = 28
    title_h = 64
    section_h = 44
    spacer = 20
    bottom = 30

    H = (
        pad * 2 + title_h +
        section_h + len(wb) * line_h + spacer +
        section_h + len(wl) * line_h + spacer +
        section_h + len(wp) * line_h + spacer +
        section_h + len(wc) * line_h +
        bottom
    )
    H = max(H, 980)

    img = Image.new("RGB", (W, int(H)), bg)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([pad, pad, W - pad, int(H) - pad], radius=22, fill=card)

    draw.text((pad * 2, int(pad * 1.35)),
              f"Pregame Determinations — Selected Players — Season {season_id}",
              font=title_font, fill=accent)

    x = pad * 2
    y = pad * 2 + 52

    def _section(title: str, lines: list[str]):
        nonlocal y
        draw.text((x, y), title, font=title_font, fill=accent)
        y += 34
        draw.line([(x, y), (W - pad * 2, y)], fill=divider, width=2)
        y += 16
        for ln in lines:
            draw.text((x, y), ln, font=body_font, fill=text)
            y += line_h
        y += 18

    _section("Bouncers", wb)
    _section("Team-less likelihood", wl)
    _section("Predicted session leaderboard", wp)
    _section("Predicted leaderboard changes", wc)

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


# ------------------------------------------------------------------------------------------------------------
# COMMAND: !pregame
# ------------------------------------------------------------------------------------------------------------

try:
    bot.remove_command("pregame")
except Exception:
    pass


@bot.command(name="pregame")
async def pregame(ctx):
    """
    Dropdown-select expected-online players, then output pregame images + determinations.
    Does not alter !session_players.
    """
    session, _fair_ctx = _get_or_create_session(ctx)

    if not getattr(session, "display_name_map", None):
        session.display_name_map = _pregame_get_all_players_map_fallback()

    all_players = session.display_name_map or _pregame_get_all_players_map_fallback()
    if not all_players:
        await ctx.send("No players available yet.")
        return

    preselected = set(getattr(session, "active_players", set()) or set()) or set(all_players.keys())

    # Temporary state so this does not alter !session_players
    tmp = SessionState()
    tmp.display_name_map = dict(all_players)
    tmp.active_players = set(preselected)

    async def _after_select(interaction):
        await _pregame_interaction_defer_safe(interaction)

        season_id = _pregame_safe_get_current_season_id()
        allowed = _pregame_allowed_norms_from_pkeys(set(tmp.active_players), tmp.display_name_map)

        # 1) Low-team (rows-only filtered; season-true)
        try:
            buf = _pregame_low_team_image_filtered(allowed, season_id)
            if buf:
                await interaction.followup.send(file=discord.File(fp=buf, filename="pregame_low_team.png"))
            else:
                await interaction.followup.send("No low-team data available for the selected players.")
        except Exception as e:
            await interaction.followup.send(f"Low-team image failed: {type(e).__name__}: {e}")

        # 2) Teammate fairness matrix
        try:
            buf = _pregame_teammate_matrix_fair_image_filtered(allowed, season_id)
            if buf:
                await interaction.followup.send(file=discord.File(fp=buf, filename="pregame_teammate_matrix_fair.png"))
            else:
                await interaction.followup.send("No teammate matrix data available for the selected players.")
        except Exception as e:
            await interaction.followup.send(f"Teammate matrix failed: {type(e).__name__}: {e}")

        # 3) Role triangle
        try:
            buf = await _pregame_role_triangle_image_filtered(allowed, season_id)
            if buf:
                await interaction.followup.send(file=discord.File(fp=buf, filename="pregame_role_triangle.png"))
            else:
                await interaction.followup.send("No role triangle data available for the selected players.")
        except Exception as e:
            await interaction.followup.send(f"Role triangle failed: {type(e).__name__}: {e}")

        # 4) Leaderboard
        try:
            buf = _pregame_leaderboard_image_filtered(allowed, season_id)
            if buf:
                await interaction.followup.send(file=discord.File(fp=buf, filename="pregame_leaderboard.png"))
            else:
                await interaction.followup.send("No leaderboard data available for the selected players.")
        except Exception as e:
            await interaction.followup.send(f"Leaderboard failed: {type(e).__name__}: {e}")

        # 5) Determinations
        try:
            buf = _pregame_determinations_image(allowed, season_id)
            if buf:
                await interaction.followup.send(file=discord.File(fp=buf, filename="pregame_determinations.png"))
            else:
                await interaction.followup.send("Determinations image could not be generated (PIL unavailable).")
        except Exception as e:
            await interaction.followup.send(f"Determinations image failed: {type(e).__name__}: {e}")

    try:
        view = _pregame_make_players_view(
            all_players=all_players,
            preselected=preselected,
            session_state=tmp,
            on_done_cb=_after_select
        )
    except Exception as e:
        await ctx.send(f"Could not create pregame selection view: {type(e).__name__}: {e}")
        return

    await ctx.send(
        "Select who you expect online for the next session (this will not change `!session_players`):",
        view=view
    )

# ============================================================================================================
# NEXT_TEAMS — Role Restrictions (standalone; NO season_story dependency)
#   - Always enforced: exactly ONE restricted role per player per roll
#   - Weighted randomness based on season role distribution (mr_hero_segments seconds + hero_cache.hero_role)
#   - Includes committed session carry-over via VIRTUAL seconds derived from previous session restrictions
# ============================================================================================================

from collections import Counter

NT_ROLE_SESSION_VIRTUAL_GAME_SECONDS = 900.0    # virtual time per committed session game (per player)
NT_ROLE_COVERAGE_MISS_PEN = 180.0                # penalty if a team (>=4 humans) has 0 eligible Vanguard/Strategist
NT_ROLE_CONC_PEN = 14.0                          # penalty for clumping the same restricted role on a team (>=4 humans)

NT_ROLES = ("Vanguard", "Duelist", "Strategist")


def _nt_table_exists(name: str) -> bool:
    global c
    try:
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (str(name),))
        return c.fetchone() is not None
    except Exception:
        return False


def _nt_col_exists(table: str, col: str) -> bool:
    global c
    try:
        c.execute(f"PRAGMA table_info({table})")
        return any(str(r[1]).lower() == str(col).lower() for r in (c.fetchall() or []))
    except Exception:
        return False


def _nt_load_hero_roles_from_cache() -> dict[int, str]:
    """
    Load hero_id -> hero_role mapping from hero_cache.
    Normalises hero_id to digits-only int, matching the Season Story approach.
    """
    global c
    try:
        _ensure_hero_cache_schema()
    except Exception:
        pass

    out: dict[int, str] = {}
    try:
        c.execute("SELECT hero_id, hero_role FROM hero_cache WHERE COALESCE(hero_role,'')<>''")
        rows = c.fetchall() or []
    except Exception:
        return out

    for hid, role in rows:
        rs = str(role or "").strip()
        if rs not in NT_ROLES:
            continue
        hid_s = str(hid or "").strip()
        digits = _digits_only(hid_s) or hid_s
        try:
            out[int(digits)] = rs
        except Exception:
            continue

    return out


async def _nt_load_role_seconds_from_db(season_id: int, player_uids: set[int]) -> dict[int, dict]:
    """
    Season role seconds per player_uid from mr_hero_segments seconds:
      - excludes bots (via mr_player_match.is_bot when present)
      - maps hero_id -> role via hero_cache.hero_role
      - refreshes hero_cache once if missing role mappings are detected (same logic as Season Story)
    Returns:
      { uid: {"Vanguard":sec, "Duelist":sec, "Strategist":sec, "known_seconds":sec_total} }
    """
    global c
    ensure_mr_api_tables()

    if not (_nt_table_exists("mr_hero_segments") and _nt_table_exists("mr_player_match")):
        return {}

    role_map = _nt_load_hero_roles_from_cache()
    if not role_map and _allow_command_hero_cache_refresh():
        refresh_fn = globals().get("refresh_hero_cache")
        if callable(refresh_fn):
            try:
                await refresh_fn(force=True)
            except Exception:
                pass
        role_map = _nt_load_hero_roles_from_cache()

    if not role_map:
        return {}

    where_bot = ""
    if _nt_col_exists("mr_player_match", "is_bot"):
        where_bot = "AND COALESCE(pm.is_bot,0)=0"

    uid_filter = ""
    params = [int(season_id)]
    uids = sorted({int(u) for u in (player_uids or set()) if u is not None})
    if uids:
        uid_filter = f"AND hs.player_uid IN ({','.join('?' for _ in uids)})"
        params.extend(uids)

    try:
        c.execute(f"""
            SELECT hs.player_uid, hs.hero_id, SUM(COALESCE(hs.seconds,0)) AS sec
            FROM mr_hero_segments hs
            JOIN mr_player_match pm
              ON pm.season_id  = hs.season_id
             AND pm.match_uid  = hs.match_uid
             AND pm.game_label = hs.game_label
             AND pm.player_uid = hs.player_uid
            WHERE hs.season_id = ?
              {where_bot}
              {uid_filter}
            GROUP BY hs.player_uid, hs.hero_id
            HAVING sec > 0
        """, tuple(params))
        rows = c.fetchall() or []
    except Exception:
        return {}

    per = defaultdict(lambda: {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0, "unknown": 0.0})
    parsed = []
    heroes_seen = set()

    for uid, hid, sec in rows:
        try:
            uid_i = int(uid)
            hid_i = int(_digits_only(str(hid)) or str(hid))
            seconds = float(sec or 0.0)
        except Exception:
            continue
        if seconds <= 0:
            continue
        parsed.append((uid_i, hid_i, seconds))
        heroes_seen.add(hid_i)

    if not parsed:
        return {}

    missing_roles = [hid_i for hid_i in heroes_seen if (role_map.get(hid_i) or "").strip() not in NT_ROLES]
    if missing_roles and _allow_command_hero_cache_refresh():
        refresh_fn = globals().get("refresh_hero_cache")
        if callable(refresh_fn):
            try:
                await refresh_fn(force=True)
            except Exception:
                pass
        role_map = _nt_load_hero_roles_from_cache()

    for uid_i, hid_i, seconds in parsed:
        role = (role_map.get(hid_i) or "").strip()
        if role in NT_ROLES:
            per[uid_i][role] += seconds
        else:
            per[uid_i]["unknown"] += seconds

    out = {}
    for uid_i, bucket in per.items():
        known = float(bucket["Vanguard"] + bucket["Duelist"] + bucket["Strategist"])
        out[uid_i] = {
            "Vanguard": float(bucket["Vanguard"]),
            "Duelist": float(bucket["Duelist"]),
            "Strategist": float(bucket["Strategist"]),
            "known_seconds": float(known),
        }
    return out


def _nt_apply_session_virtual_overlay(*, active_set: set[str], session_games: list[dict], sec_by_pkey: dict[str, dict]):
    """
    Session carry-over:
      - For each committed session game, for each player with a stored restricted role:
          add virtual time equally split across the TWO allowed roles
      - This makes next-roll restrictions reflect the season DB and prior session restrictions.
    """
    if not session_games:
        return

    half = float(NT_ROLE_SESSION_VIRTUAL_GAME_SECONDS) / 2.0
    for g in (session_games or []):
        rr = g.get("restricted_roles")
        if not isinstance(rr, dict) or not rr:
            continue

        for pkey, banned in rr.items():
            if pkey not in active_set:
                continue

            b = str(banned or "").strip()
            if b not in NT_ROLES:
                continue

            if pkey not in sec_by_pkey:
                sec_by_pkey[pkey] = {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0, "known_seconds": 0.0}

            for role in NT_ROLES:
                if role == b:
                    continue
                sec_by_pkey[pkey][role] = float(sec_by_pkey[pkey].get(role, 0.0)) + half

            sec_by_pkey[pkey]["known_seconds"] = float(sec_by_pkey[pkey].get("known_seconds", 0.0)) + float(NT_ROLE_SESSION_VIRTUAL_GAME_SECONDS)


def _nt_pick_restricted_role_from_seconds(sec: dict) -> tuple[str, dict]:
    """
    Always pick ONE restricted role.

    Selection rule (ONLY):
      - weights are the CURRENT role distribution shares
      - i.e., P(ban Vanguard) = Vanguard_share, etc.

    If all shares are 0 (no data), use equal chance across all roles.
    """
    v = float(sec.get("Vanguard", 0.0) or 0.0)
    d = float(sec.get("Duelist", 0.0) or 0.0)
    s = float(sec.get("Strategist", 0.0) or 0.0)

    tot = v + d + s

    if tot <= 0.0:
        # Blank/new season (or no usable role data) => equal chance
        shares = {"Vanguard": 1.0 / 3.0, "Duelist": 1.0 / 3.0, "Strategist": 1.0 / 3.0}
        weights = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
        pick = random.choice(NT_ROLES)
        return pick, {"shares": shares, "weights": weights}

    shares = {
        "Vanguard": v / tot,
        "Duelist": d / tot,
        "Strategist": s / tot,
    }

    weights = [shares[r] for r in NT_ROLES]
    if sum(weights) <= 0.0:
        # Safety fallback (should not occur if tot>0)
        weights = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]

    pick = random.choices(list(NT_ROLES), weights=weights, k=1)[0]
    return pick, {"shares": shares, "weights": weights}



async def _nt_build_restricted_roles_for_roll(*, season_id: int, active_pkeys: list[str], session_games: list[dict]) -> tuple[dict[str, str], dict]:
    """
    Build restricted_roles for this roll, using:
      - season DB role seconds (mr_hero_segments + hero_cache.hero_role)
      - committed session carry-over (virtual seconds from prior restrictions)
    Returns:
      (restricted_roles, debug_map)
    """
    active_set = set(active_pkeys or [])
    uids = set()
    for p in active_set:
        uid = _uid_from_pkey(p)
        if uid is not None:
            uids.add(int(uid))

    by_uid = await _nt_load_role_seconds_from_db(int(season_id), uids)

    # seed seconds by player_key
    sec_by_pkey: dict[str, dict] = {}
    for p in active_set:
        uid = _uid_from_pkey(p)
        base = by_uid.get(int(uid)) if uid is not None else None
        if base:
            sec_by_pkey[p] = dict(base)
        else:
            sec_by_pkey[p] = {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0, "known_seconds": 0.0}

    # overlay committed session games
    _nt_apply_session_virtual_overlay(active_set=active_set, session_games=(session_games or []), sec_by_pkey=sec_by_pkey)

    restricted: dict[str, str] = {}
    dbg: dict[str, dict] = {}

    for p in sorted(active_set):
        role, d = _nt_pick_restricted_role_from_seconds(sec_by_pkey.get(p, {}))
        restricted[p] = role
        dbg[p] = d

    return restricted, dbg


def _nt_role_split_penalty(team_a: set[str], team_b: set[str], restricted_roles: dict[str, str]) -> tuple[float, dict]:
    """
    Soft penalties only (bots fill gaps).
    Apply role-coverage and concentration penalties only when a team has >=4 humans.
    """
    def _team_pen(team: set[str]) -> tuple[float, float]:
        if len(team) < 4:
            return 0.0, 0.0

        elig_v = sum(1 for p in team if (restricted_roles.get(p) != "Vanguard"))
        elig_s = sum(1 for p in team if (restricted_roles.get(p) != "Strategist"))

        cov_pen = 0.0
        if elig_v == 0:
            cov_pen += float(NT_ROLE_COVERAGE_MISS_PEN)
        if elig_s == 0:
            cov_pen += float(NT_ROLE_COVERAGE_MISS_PEN)

        counts = Counter(restricted_roles.get(p) for p in team)
        conc_pen = float(NT_ROLE_CONC_PEN) * sum((max(0, int(counts.get(r, 0)) - 1) ** 2) for r in NT_ROLES)

        return cov_pen, conc_pen

    a_cov, a_conc = _team_pen(set(team_a or []))
    b_cov, b_conc = _team_pen(set(team_b or []))

    cov = float(a_cov + b_cov)
    conc = float(a_conc + b_conc)
    total = float(cov + conc)
    return total, {"coverage": cov, "concentration": conc}

def _nt_role_emoji(role: str) -> str:
    r = (role or "").strip()
    return {
        "Vanguard": "🛡️",
        "Duelist": "⚔️",
        "Strategist": "✚",
    }.get(r, "❔")


# ============================================================================================================
# ============================================================================================================
# Team Randomiser Fairness Engine — API-INTEGRATED
# ============================================================================================================
# ============================================================================================================

async def _run_next_teams_roll(channel, key: tuple[int, int], *, commit_pending: bool):
    """
    Next-teams fairness roll.

    Goals:
      - Keep season pairing %s close to 50% for all players (presence-aware band 40–60%).
      - Keep low-team exposure (when uneven teams) close to the lobby target.
      - Season-wide anti-lumping: spread teammate exposure across ALL season games,
        and ALSO include committed games from the current session BEFORE rolling again.

    Notes:
      - No skill balancing is used for team selection.
      - A predicted win chance line may appear when the skill model is available;
        it does not affect team selection.
    """

    # =====================================================================================
    # Keep fairness context fresh: rebuild from ALL season DB games each roll
    # =====================================================================================
    try:
        FAIRNESS_CONTEXTS[key] = _build_fairness_context()
    except Exception:
        pass

    session, fair_ctx = _get_or_create_session_by_key(key)

    # Commit pending roll (played) if requested
    if commit_pending:
        try:
            if getattr(session, "pending_roll_token", None) and getattr(session, "pending_roll_data", None):
                _commit_pending_roll(session, session.pending_roll_token, key=key)
        except Exception:
            pass

    # Active lobby must be set
    if not session.active_players:
        await channel.send("No active players set. Use `!session_start` or `!session_players` first.")
        return

    active = list(session.active_players)
    n = len(active)
    if n < 2:
        await channel.send("Need at least 2 active players to form teams.")
        return

    active_set = set(active)
    # =====================================================================================
    # Role Restrictions — ALWAYS enforced (season DB + committed session overlay)
    # =====================================================================================
    try:
        season_id_now = get_current_season_id()
        restricted_roles, role_restrict_debug = await _nt_build_restricted_roles_for_roll(
            season_id=season_id_now,
            active_pkeys=active,
            session_games=(session.session_games or []),
        )
    except Exception:
        restricted_roles = {p: random.choice(("Vanguard", "Duelist", "Strategist")) for p in active}
        role_restrict_debug = {}

    # Team sizes
    if n % 2 == 0:
        big_size = small_size = n // 2
    else:
        big_size = (n + 1) // 2
        small_size = n - big_size

    uneven = (small_size < big_size)
    target_low = (small_size / n) if uneven else None

    # =====================================================================================
    # Tuning knobs
    # =====================================================================================
    EXHAUSTIVE_N_MAX = 14
    RAND_CANDIDATES_K = 1400

    # Random pick among top-K best candidates
    # For uneven games, do NOT randomise among the top candidates.
    # Pick the best correction candidate only.
    RAND_PICK_TOP_K = 1 if uneven else 5

    # ------------------------------------------------------------------
    # Low-team tuning
    # ------------------------------------------------------------------
    PROTECT_MARGIN = 0.015
    MIN_UNEVEN_BASELINE = 2

    # For uneven games, be strict.
    LOWTEAM_USE_HARD_PROTECTION = True
    LOWTEAM_STREAK_HARD_CAP = 2
    LOWTEAM_STREAK_HARD_PEN = 900.0

    # Stronger push toward deficit players, and stronger punishment for picking over-target players
    LOWTEAM_DEFICIT_REWARD = 520.0
    LOWTEAM_OVER_PENALTY = 520.0

    # Post-game spread controls.
    LOWTEAM_SPREAD_WEIGHT = 380.0
    LOWTEAM_L1_WEIGHT = 320.0
    LOWTEAM_SPREAD_POW = 3.8
    LOWTEAM_L1_POW = 3.2

    # Aggressively minimise the post-game low-team gap profile.
    LOWTEAM_POST_ABS_WEIGHT = 560.0
    LOWTEAM_POST_MAX_WEIGHT = 980.0
    LOWTEAM_POST_UNDER_WEIGHT = 880.0
    LOWTEAM_POST_OVER_WEIGHT = 520.0

    LOWTEAM_POST_ABS_POW = 1.8
    LOWTEAM_POST_MAX_POW = 1.6
    LOWTEAM_POST_UNDER_POW = 1.7
    LOWTEAM_POST_OVER_POW = 1.5

    # Priority pool for the most under-served low-team players.
    LOWTEAM_PRIORITY_BUFFER = 1
    LOWTEAM_PRIORITY_MISS_WEIGHT = 1800.0
    LOWTEAM_PRIORITY_WINDOW_MISS_WEIGHT = 900.0

    # ------------------------------------------------------------------
    # Pairing steering (existing “steep” terms)
    # ------------------------------------------------------------------
    PAIR_WORST_OVER_WEIGHT = 9.0
    PAIR_UNDERUSE_REWARD = 4.2
    PAIR_WORST_OVER_POW = 2.3
    PAIR_SAMPLE_DAMP_K = 4.0
    PAIR_LOCK_THRESHOLD = 0.47 #hard lock of pairings over %

    # ------------------------------------------------------------------
    # Season-wide band (±10% => 40–60)
    # ------------------------------------------------------------------
    BAND_LOW = 0.40
    BAND_HIGH = 0.60

    PAIR_BAND_POW = 2.1
    PAIR_BAND_SAMPLE_DAMP = 4.0

    PAIR_BAND_OVER_WEIGHT = 520.0
    PAIR_BAND_UNDER_REWARD = 420.0

    PAIR_BAND_UNDER_OPP_PENALTY = 680.0
    PAIR_BAND_OVER_OPP_REWARD = 260.0

    ZERO_PAIR_SEEN_MIN = 6
    ZERO_PAIR_OPP_PENALTY = 900.0

    # Season-wide streak brake
    STREAK_WEIGHT = 38.0
    STREAK_POW = 2.0
    STREAK_HARD_CAP = 3
    STREAK_HARD_PEN = 260.0

    # =====================================================================================
    # Helpers
    # =====================================================================================
    def _pair_key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    # Avoid exact repeats only within the current lobby composition
    current_lobby_players = frozenset(active)
    previous_teams = set()

    for g in (session.session_games or []):
        team_a_prev = frozenset(g.get("team_a") or [])
        team_b_prev = frozenset(g.get("team_b") or [])
        game_lobby_players = team_a_prev | team_b_prev

        # Reset the no-repeat pool whenever the lobby membership changes.
        # This keeps exact-team bans scoped to the current active player set,
        # while all session/season pair tracking still continues normally.
        if game_lobby_players != current_lobby_players:
            continue

        previous_teams.add(team_a_prev)
        previous_teams.add(team_b_prev)

    # =====================================================================================
    # Effective (season + committed session) stats for pairing + low-team steering
    # =====================================================================================
    eff_games = defaultdict(int, fair_ctx.games_played or {})
    eff_pair_games = defaultdict(int, fair_ctx.pair_games or {})
    eff_uneven = defaultdict(int, getattr(fair_ctx, "uneven_games", {}) or {})
    eff_low = defaultdict(int, getattr(fair_ctx, "low_team_games", {}) or {})

    for g in (session.session_games or []):
        ta = set(g.get("team_a") or [])
        tb = set(g.get("team_b") or [])
        present = ta | tb

        for p in present:
            eff_games[p] += 1

        for team in (ta, tb):
            for a, b in combinations(sorted(team), 2):
                eff_pair_games[_pair_key(a, b)] += 1

        lt = g.get("low_team")
        if lt:
            for p in present:
                eff_uneven[p] += 1
            for p in (set(lt) & present):
                eff_low[p] += 1

    # Effective low-team ratios (season + committed session)
    effective_ratios = {}
    protected_low = set()

    if uneven and target_low is not None:
        for p in active:
            ug = int(eff_uneven.get(p, 0))
            lc = int(eff_low.get(p, 0))
            if ug < MIN_UNEVEN_BASELINE:
                r = float(target_low)
            else:
                r = (lc / ug) if ug > 0 else float(target_low)
            effective_ratios[p] = float(r)

        # Protect players already above target + margin from being placed on low team again
        for p in active:
            ug = int(eff_uneven.get(p, 0))
            if ug < MIN_UNEVEN_BASELINE:
                continue
            if float(effective_ratios.get(p, float(target_low))) > (float(target_low) + PROTECT_MARGIN):
                protected_low.add(p)
    else:
        for p in active:
            effective_ratios[p] = 0.0

    eligible_low = [p for p in active if p not in protected_low]

    # =====================================================================================
    # Low-team priority ranking.
    # The most under-target players should be pulled back toward target quickly.
    # =====================================================================================
    current_low_deficit = {}
    if uneven and target_low is not None:
        for p in active:
            current_low_deficit[p] = max(
                0.0,
                float(target_low) - float(effective_ratios.get(p, float(target_low)))
            )
    else:
        for p in active:
            current_low_deficit[p] = 0.0

    priority_low_sorted = []
    strict_priority_low = set()
    priority_low_window = set()

    if uneven and target_low is not None:
        # Biggest deficit first. Tie-break by more uneven-game sample, then name.
        priority_low_sorted = sorted(
            active,
            key=lambda p: (
                float(current_low_deficit.get(p, 0.0)),
                int(eff_uneven.get(p, 0)),
                str(p),
            ),
            reverse=True,
        )

        # The strict set = the number of players required on the low team.
        strict_priority_low = set(priority_low_sorted[:small_size])

        # Add a tiny amount of flexibility so pairing rules can still work.
        priority_n = min(len(active), small_size + LOWTEAM_PRIORITY_BUFFER)
        priority_low_window = set(priority_low_sorted[:priority_n])

    def _postgame_low_profile(low_team: frozenset[str]) -> tuple[float, float, float, float, dict[str, float]]:
        """
        Returns:
          avg_abs_diff_from_target,
          max_abs_diff_from_target,
          total_under_target,
          total_over_target,
          postgame_ratio_map
        """
        if not uneven or target_low is None:
            return 0.0, 0.0, 0.0, 0.0, {}

        post_ratios = {}
        l1_total = 0.0
        max_abs = 0.0
        under_total = 0.0
        over_total = 0.0

        for p in active:
            ug = int(eff_uneven.get(p, 0)) + 1
            lc = int(eff_low.get(p, 0)) + (1 if p in low_team else 0)

            r = (lc / ug) if ug > 0 else float(target_low)
            r = float(r)
            post_ratios[p] = r

            diff = r - float(target_low)
            ad = abs(diff)

            l1_total += ad
            max_abs = max(max_abs, ad)

            if diff < 0:
                under_total += (-diff)
            else:
                over_total += diff

        avg_abs = l1_total / max(1.0, float(len(active)))
        return avg_abs, max_abs, under_total, over_total, post_ratios

    # Track consecutive low-team assignments (committed session games)
    low_streak = defaultdict(int)
    if uneven and (target_low is not None) and LOWTEAM_STREAK_HARD_CAP:
        for p in active:
            st = 0
            for g in reversed(session.session_games or []):
                lt = g.get("low_team")
                if not lt:
                    continue
                if p in lt:
                    st += 1
                else:
                    break
            low_streak[p] = st

    def _pair_pct(a: str, b: str) -> float:
        k2 = _pair_key(a, b)
        gms = float(eff_pair_games.get(k2, 0))
        min_g = max(1.0, float(min(eff_games.get(a, 0), eff_games.get(b, 0))))
        return gms / min_g

    # avg pair pct within current lobby
    avg_pair = defaultdict(list)
    for a, b in combinations(sorted(active), 2):
        pct = _pair_pct(a, b)
        avg_pair[a].append(pct)
        avg_pair[b].append(pct)

    avg_pair_pct_by_player = {p: (sum(vs) / len(vs)) if vs else 0.0 for p, vs in avg_pair.items()}

    def _pair_sample_weight(a: str, b: str) -> float:
        ga = float(eff_games.get(a, 0))
        gb = float(eff_games.get(b, 0))
        min_g = max(0.0, min(ga, gb))
        return (min_g / (min_g + PAIR_SAMPLE_DAMP_K)) if (min_g + PAIR_SAMPLE_DAMP_K) > 0 else 0.0

    def _pair_over_and_under(team: frozenset[str]) -> tuple[float, float]:
        worst_over = 0.0
        under_sum = 0.0
        players = sorted(team)
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                a, b = players[i], players[j]
                sp = _pair_pct(a, b)
                sa = float(avg_pair_pct_by_player.get(a, 0.0))
                sb = float(avg_pair_pct_by_player.get(b, 0.0))

                over = max(0.0, sp - sa) + max(0.0, sp - sb)
                deficit = max(0.0, sa - sp) + max(0.0, sb - sp)

                w = _pair_sample_weight(a, b)
                worst_over = max(worst_over, over * w)
                under_sum += deficit * w

        return worst_over, under_sum

    def _postgame_low_metrics(low_team: frozenset[str]) -> tuple[float, float]:
        if not uneven or target_low is None:
            return 0.0, 0.0

        new_ratios = []
        for p in active:
            ug = int(eff_uneven.get(p, 0)) + 1
            lc = int(eff_low.get(p, 0)) + (1 if p in low_team else 0)

            if ug < MIN_UNEVEN_BASELINE:
                r = float(target_low)
            else:
                r = (lc / ug) if ug > 0 else float(target_low)

            new_ratios.append(float(r))

        spread = (max(new_ratios) - min(new_ratios)) if new_ratios else 0.0
        l1avg = (sum(abs(x - float(target_low)) for x in new_ratios) / len(new_ratios)) if new_ratios else 0.0
        return spread, l1avg

    # =====================================================================================
    # Season-wide presence-aware teammate band (DB + committed session games)
    # =====================================================================================
    season_id_now = get_current_season_id()

    def _parse_dt_utc(iso: str):
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _game_num(gl: str) -> int:
        try:
            if gl and gl.startswith("Game_"):
                return int(gl.split("_", 1)[1])
        except Exception:
            pass
        return 0

    match_rec = {}
    try:
        c.execute(
            """
            SELECT
                pm.match_uid,
                pm.game_label,
                pm.player_uid,
                pm.is_win,
                mm.match_time_utc
            FROM mr_player_match pm
            LEFT JOIN mr_match_meta mm
                   ON mm.season_id = pm.season_id
                  AND mm.match_uid = pm.match_uid
            WHERE pm.season_id = ?
              AND pm.is_bot = 0
            """,
            (int(season_id_now),)
        )
        for mu, gl, uid, is_win, mt_utc in c.fetchall():
            if mu is None or uid is None:
                continue
            try:
                pkey = _pkey_from_uid(int(uid))
            except Exception:
                continue
            if pkey not in active_set:
                continue

            mu_s = str(mu)
            rec = match_rec.get(mu_s)
            if rec is None:
                dt = _parse_dt_utc(mt_utc) if mt_utc else None
                gl_s = str(gl) if gl else ""
                rec = {
                    "dt": dt,
                    "gn": _game_num(gl_s),
                    "winners": set(),
                    "losers": set(),
                    "is_session": False,
                    "si": -1,
                }
                match_rec[mu_s] = rec

            if int(is_win or 0) == 1:
                rec["winners"].add(pkey)
            else:
                rec["losers"].add(pkey)
    except Exception:
        match_rec = {}

    pair_seen = defaultdict(int)
    pair_together = defaultdict(int)
    pair_streak = {}

    matches = list(match_rec.values())

    # Build base DB pair_seen / pair_together
    for rec in matches:
        winners = rec["winners"]
        losers = rec["losers"]
        present = winners | losers
        if len(present) < 2:
            continue

        pres = sorted(present)
        for a, b in combinations(pres, 2):
            pair_seen[_pair_key(a, b)] += 1

        for team in (winners, losers):
            t = sorted(team)
            if len(t) >= 2:
                for a, b in combinations(t, 2):
                    pair_together[_pair_key(a, b)] += 1

    # Fold committed session games into pair_seen, pair_together and streak ordering
    # so the next roll sees the current band position.
    sess_recs = []
    for si, g in enumerate(session.session_games or []):
        ta = set(g.get("team_a") or []) & active_set
        tb = set(g.get("team_b") or []) & active_set
        present = ta | tb
        if len(present) < 2:
            continue

        pres = sorted(present)
        for a, b in combinations(pres, 2):
            pair_seen[_pair_key(a, b)] += 1

        for team in (ta, tb):
            t = sorted(team)
            if len(t) >= 2:
                for a, b in combinations(t, 2):
                    pair_together[_pair_key(a, b)] += 1

        sess_recs.append({
            "dt": None,
            "gn": 0,
            "winners": set(ta),
            "losers": set(tb),
            "is_session": True,
            "si": int(si),
        })

    matches.extend(sess_recs)

    def _order_key(rec):
        # Session records must be newest so streak reflects what just happened.
        if rec.get("is_session"):
            return (2, int(rec.get("si", 0)))
        dt = rec.get("dt")
        if isinstance(dt, datetime):
            return (1, dt.timestamp())
        return (0, rec.get("gn", 0))

    matches_sorted_newest = sorted(matches, key=_order_key, reverse=True)

    # Streak: consecutive teammate occurrences among matches where both present
    for a, b in combinations(sorted(active), 2):
        k2 = _pair_key(a, b)
        st = 0
        for rec in matches_sorted_newest:
            winners = rec["winners"]
            losers = rec["losers"]
            present = winners | losers
            if a not in present or b not in present:
                continue
            same = ((a in winners and b in winners) or (a in losers and b in losers))
            if same:
                st += 1
            else:
                break
        pair_streak[k2] = st

    def _band_weight(seen: float) -> float:
        w = (seen / (seen + PAIR_BAND_SAMPLE_DAMP)) if (seen + PAIR_BAND_SAMPLE_DAMP) > 0 else 0.0
        if seen >= 6.0:
            w = max(w, 0.75)
        return w

    def _pair_band_cost_if_teammates(a: str, b: str) -> float:
        k2 = _pair_key(a, b)
        seen = float(pair_seen.get(k2, 0))
        tog = float(pair_together.get(k2, 0))

        w = _band_weight(seen)

        # after placing them teammates next game: seen+1, together+1
        frac = (tog + 1.0) / (seen + 1.0)

        cost = 0.0
        if frac > BAND_HIGH:
            cost += PAIR_BAND_OVER_WEIGHT * ((frac - BAND_HIGH) ** PAIR_BAND_POW) * w
        elif frac < BAND_LOW:
            cost -= PAIR_BAND_UNDER_REWARD * ((BAND_LOW - frac) ** PAIR_BAND_POW) * w

        st = float(pair_streak.get(k2, 0))
        if st > 0:
            st_next = st + 1.0
            cost += STREAK_WEIGHT * (st_next ** STREAK_POW) * w
            if STREAK_HARD_CAP and st_next >= float(STREAK_HARD_CAP):
                cost += STREAK_HARD_PEN * w

        return cost

    def _pair_band_cost_if_opponents(a: str, b: str) -> float:
        k2 = _pair_key(a, b)
        seen = float(pair_seen.get(k2, 0))
        tog = float(pair_together.get(k2, 0))

        w = _band_weight(seen)

        # opponents next game: seen+1, together unchanged
        frac = (tog) / (seen + 1.0)

        cost = 0.0
        if frac < BAND_LOW:
            cost += PAIR_BAND_UNDER_OPP_PENALTY * ((BAND_LOW - frac) ** PAIR_BAND_POW) * w
            if tog <= 0.0 and seen >= float(ZERO_PAIR_SEEN_MIN):
                cost += ZERO_PAIR_OPP_PENALTY * w
        elif frac > BAND_HIGH:
            cost -= PAIR_BAND_OVER_OPP_REWARD * ((frac - BAND_HIGH) ** PAIR_BAND_POW) * w

        return cost

    def _season_composition_penalty(team: frozenset[str]) -> float:
        players = sorted(team)
        if len(players) < 2:
            return 0.0
        pen = 0.0
        for a, b in combinations(players, 2):
            pen += _pair_band_cost_if_teammates(a, b)
        return pen

    def _season_opponent_penalty(team_a: frozenset[str], team_b: frozenset[str]) -> float:
        if not team_a or not team_b:
            return 0.0
        pen = 0.0
        for a in team_a:
            for b in team_b:
                pen += _pair_band_cost_if_opponents(a, b)
        return pen

    # =====================================================================================
    # Candidate generation + hard 47% pair lock
    # =====================================================================================
    pair_lock_auto_disabled_this_roll = False
    pair_lock_reenabled_this_roll = False
    pair_lock_reenabled_added_players = []
    pair_lock_reenabled_removed_players = []

    def _current_pair_rate(a: str, b: str) -> float:
        k2 = _pair_key(a, b)
        seen = float(pair_seen.get(k2, 0))
        if seen <= 0.0:
            return 0.0
        return float(pair_together.get(k2, 0)) / seen

    disabled_lobby_snapshot = set(getattr(session, "pair_lock_47_disabled_lobby", []) or [])
    if bool(getattr(session, "pair_lock_47_disabled", False)) and disabled_lobby_snapshot:
        current_lobby_snapshot = set(active)
        if current_lobby_snapshot != disabled_lobby_snapshot:
            added_players = sorted([p for p in active if p not in disabled_lobby_snapshot])
            removed_players = sorted([p for p in disabled_lobby_snapshot if p not in current_lobby_snapshot])

            session.pair_lock_47_disabled = False
            session.pair_lock_47_disabled_lobby = None
            pair_lock_reenabled_this_roll = True
            pair_lock_reenabled_added_players = list(added_players)
            pair_lock_reenabled_removed_players = list(removed_players)
            try:
                _save_session_state(key, session)
            except Exception:
                pass

    def _locked_pairs_for_roll() -> set[tuple[str, str]]:
        if bool(getattr(session, "pair_lock_47_disabled", False)):
            return set()
        out = set()
        for a, b in combinations(sorted(active), 2):
            if _current_pair_rate(a, b) > float(PAIR_LOCK_THRESHOLD):
                out.add(_pair_key(a, b))
        return out

    hard_locked_pairs = _locked_pairs_for_roll()

    def _team_has_hard_locked_pair(team: frozenset[str]) -> bool:
        if not hard_locked_pairs or len(team) < 2:
            return False
        for a, b in combinations(sorted(team), 2):
            if _pair_key(a, b) in hard_locked_pairs:
                return True
        return False

    def _iter_candidates():
        if n <= EXHAUSTIVE_N_MAX:
            yield from _iter_splits_exhaustive(active, big_size)
        else:
            seen_sets = set()
            for _ in range(RAND_CANDIDATES_K):
                team_a = frozenset(random.sample(active, big_size))
                if team_a in seen_sets:
                    continue
                seen_sets.add(team_a)
                team_b = frozenset(p for p in active if p not in team_a)
                yield team_a, team_b

    def _build_top_heap(*, enforce_pair_lock: bool):
        best_heap = []
        heap_i = 0

        for team_a, team_b in _iter_candidates():
            if team_a in previous_teams or team_b in previous_teams:
                continue

            if enforce_pair_lock and (_team_has_hard_locked_pair(team_a) or _team_has_hard_locked_pair(team_b)):
                continue

            low_team = None
            if len(team_a) != len(team_b):
                low_team = team_a if len(team_a) < len(team_b) else team_b
                if LOWTEAM_USE_HARD_PROTECTION and len(eligible_low) >= len(low_team):
                    if any(p in protected_low for p in low_team):
                        continue

            base_score, _ = _compute_fairness_score(
                team_a, team_b, low_team, fair_ctx, session,
                active_players=active, debug=False
            )

            extra = 0.0

            worst_over_a, under_a = _pair_over_and_under(team_a)
            worst_over_b, under_b = _pair_over_and_under(team_b)
            worst_over = max(worst_over_a, worst_over_b)
            under_sum = under_a + under_b

            extra += PAIR_WORST_OVER_WEIGHT * (worst_over ** PAIR_WORST_OVER_POW)
            extra -= PAIR_UNDERUSE_REWARD * (under_sum / max(1.0, len(active)))

            spread = l1avg = 0.0
            low_bias = 0.0

            low_post_abs = 0.0
            low_post_max = 0.0
            low_post_under = 0.0
            low_post_over = 0.0

            low_priority_miss = 0.0
            deficit_reward = 0.0
            over_pick_pen = 0.0

            if low_team and uneven and target_low is not None:
                # Existing low-team spread metrics
                spread, l1avg = _postgame_low_metrics(low_team)
                extra += LOWTEAM_SPREAD_WEIGHT * (spread ** LOWTEAM_SPREAD_POW)
                extra += LOWTEAM_L1_WEIGHT * (l1avg ** LOWTEAM_L1_POW)

                # Evaluate the whole lobby after this candidate low-team assignment.
                low_post_abs, low_post_max, low_post_under, low_post_over, _post_ratios = _postgame_low_profile(low_team)

                extra += LOWTEAM_POST_ABS_WEIGHT * (low_post_abs ** LOWTEAM_POST_ABS_POW)
                extra += LOWTEAM_POST_MAX_WEIGHT * (low_post_max ** LOWTEAM_POST_MAX_POW)
                extra += LOWTEAM_POST_UNDER_WEIGHT * (low_post_under ** LOWTEAM_POST_UNDER_POW)
                extra += LOWTEAM_POST_OVER_WEIGHT * (low_post_over ** LOWTEAM_POST_OVER_POW)

                # Reward putting the most under-target players on the low team
                deficit_reward = sum(float(current_low_deficit.get(p, 0.0)) for p in low_team)

                # Penalise assigning already-over players to the low team
                over_pick_pen = sum(
                    max(0.0, float(effective_ratios.get(p, float(target_low))) - float(target_low))
                    for p in low_team
                )

                low_bias -= LOWTEAM_DEFICIT_REWARD * deficit_reward
                low_bias += LOWTEAM_OVER_PENALTY * over_pick_pen

                # Strongly penalise missing the most under-served players.
                if strict_priority_low:
                    missed_strict = sum(1 for p in strict_priority_low if p not in low_team)
                    if missed_strict > 0:
                        low_priority_miss += LOWTEAM_PRIORITY_MISS_WEIGHT * float(missed_strict)

                if priority_low_window:
                    in_window = sum(1 for p in low_team if p in priority_low_window)
                    need_in_window = min(len(low_team), max(1, len(low_team) - LOWTEAM_PRIORITY_BUFFER + 1))
                    if in_window < need_in_window:
                        low_priority_miss += LOWTEAM_PRIORITY_WINDOW_MISS_WEIGHT * float(need_in_window - in_window)

                # Consecutive low-team protection
                if LOWTEAM_STREAK_HARD_CAP:
                    for p in low_team:
                        if int(low_streak.get(p, 0)) >= int(LOWTEAM_STREAK_HARD_CAP):
                            low_bias += LOWTEAM_STREAK_HARD_PEN

                extra += low_bias
                extra += low_priority_miss

            comp_pen = _season_composition_penalty(team_a) + _season_composition_penalty(team_b)
            opp_pen = _season_opponent_penalty(team_a, team_b)

            role_pen, role_pen_meta = _nt_role_split_penalty(team_a, team_b, restricted_roles)

            total_score = float(base_score) + float(extra) + float(comp_pen) + float(opp_pen) + float(role_pen)

            meta = {
                "team_a": team_a, "team_b": team_b, "low_team": low_team,
                "total_score": total_score, "base_score": float(base_score),
                "pair_worst_over": float(worst_over),
                "pair_under_sum": float(under_sum),
                "low_spread": float(spread),
                "low_l1avg": float(l1avg),
                "season_comp_penalty": float(comp_pen),
                "season_opp_penalty": float(opp_pen),
                "low_bias": float(low_bias),
                "extra_total": float(extra),
                "role_penalty": float(role_pen),
                "role_pen_coverage": float(role_pen_meta.get("coverage", 0.0)),
                "role_pen_concentration": float(role_pen_meta.get("concentration", 0.0)),
                "pair_lock_47_enforced": bool(enforce_pair_lock),
                "low_post_abs": float(low_post_abs),
                "low_post_max": float(low_post_max),
                "low_post_under": float(low_post_under),
                "low_post_over": float(low_post_over),
                "low_priority_miss": float(low_priority_miss),
                "low_deficit_reward": float(deficit_reward),
                "low_over_pick_pen": float(over_pick_pen),
            }

            heap_i += 1
            entry = (-total_score, heap_i, meta)

            if len(best_heap) < int(RAND_PICK_TOP_K):
                heapq.heappush(best_heap, entry)
            else:
                if entry[0] > best_heap[0][0]:
                    heapq.heapreplace(best_heap, entry)

        return best_heap

    pair_lock_enforced = bool(hard_locked_pairs)
    best_heap = _build_top_heap(enforce_pair_lock=pair_lock_enforced)

    if not best_heap and pair_lock_enforced:
        session.pair_lock_47_disabled = True
        session.pair_lock_47_disabled_lobby = tuple(sorted(active))
        pair_lock_auto_disabled_this_roll = True
        hard_locked_pairs = set()
        best_heap = _build_top_heap(enforce_pair_lock=False)
        try:
            _save_session_state(key, session)
        except Exception:
            pass

    if not best_heap:
        await channel.send("Unable to generate a team split. Try again.")
        return

    # Convert heap to sorted ascending by total_score
    top = sorted([(-neg, i, meta) for (neg, i, meta) in best_heap], key=lambda x: x[0])

    # Weighted random pick among top candidates (rank 1 favoured)
    # Target weights: rank1=45%, rank2=25%, rank3=15%, rank4=10%, rank5=5%
    WEIGHTS_BY_RANK = [60, 40, 0, 0, 0]
    weights_used = WEIGHTS_BY_RANK[:len(top)]

    if len(top) <= 1:
        pick_idx = 0
    else:
        # Safety: if someone sets all weights to 0, fall back to uniform
        if sum(weights_used) <= 0:
            pick_idx = random.randrange(len(top))
        else:
            pick_idx = random.choices(range(len(top)), weights=weights_used, k=1)[0]

    picked_total, picked_internal_id, picked = top[pick_idx]
    picked_rank = pick_idx + 1
    picked_pool = len(top)


    team_a = picked["team_a"]
    team_b = picked["team_b"]
    low_team = picked["low_team"]

    # Ensure teams (3+ humans) are not ALL banned from the same role
    _nt_fix_team_monobans(team_a, restricted_roles, role_restrict_debug)
    _nt_fix_team_monobans(team_b, restricted_roles, role_restrict_debug)

    # Debug info for !fairness_debug
    base_score, debug_info = _compute_fairness_score(
        team_a, team_b, low_team, fair_ctx, session,
        active_players=active, debug=True
    )
    if debug_info is not None:
        debug_info["steep_pair_worst_over"] = picked.get("pair_worst_over", 0.0)
        debug_info["steep_pair_under_sum"] = picked.get("pair_under_sum", 0.0)
        debug_info["steep_low_spread"] = picked.get("low_spread", 0.0)
        debug_info["steep_low_l1avg"] = picked.get("low_l1avg", 0.0)
        debug_info["steep_season_comp_penalty"] = picked.get("season_comp_penalty", 0.0)
        debug_info["steep_season_opp_penalty"] = picked.get("season_opp_penalty", 0.0)
        debug_info["steep_low_bias"] = picked.get("low_bias", 0.0)
        debug_info["steep_extra_total"] = picked.get("extra_total", 0.0)
        debug_info["total_with_steep_terms"] = float(picked_total)
        debug_info["topk_pool"] = int(picked_pool)
        debug_info["topk_rank_picked"] = int(picked_rank)
        debug_info["topk_weights_used"] = list(weights_used)
        debug_info["topk_pick_idx"] = int(pick_idx)
        debug_info["topk_pick_internal_id"] = int(picked_internal_id)
        debug_info["role_penalty"] = picked.get("role_penalty", 0.0)
        debug_info["role_pen_coverage"] = picked.get("role_pen_coverage", 0.0)
        debug_info["role_pen_concentration"] = picked.get("role_pen_concentration", 0.0)
        debug_info["restricted_roles"] = dict(restricted_roles or {})
        debug_info["restricted_roles_math"] = dict(role_restrict_debug or {})
        debug_info["pair_lock_47_threshold"] = float(PAIR_LOCK_THRESHOLD)
        debug_info["pair_lock_47_disabled"] = bool(getattr(session, "pair_lock_47_disabled", False))
        debug_info["pair_lock_47_disabled_lobby"] = list(getattr(session, "pair_lock_47_disabled_lobby", []) or [])
        debug_info["pair_lock_47_auto_disabled_this_roll"] = bool(pair_lock_auto_disabled_this_roll)
        debug_info["pair_lock_47_reenabled_this_roll"] = bool(pair_lock_reenabled_this_roll)
        debug_info["pair_lock_47_reenabled_added_players"] = list(pair_lock_reenabled_added_players)
        debug_info["pair_lock_47_reenabled_removed_players"] = list(pair_lock_reenabled_removed_players)
        debug_info["pair_lock_47_pairs"] = [
            {"a": a, "b": b, "pct": float(_current_pair_rate(a, b))}
            for a, b in sorted(hard_locked_pairs)
        ]

    session.last_split = {
        "team_a": team_a,
        "team_b": team_b,
        "low_team": low_team,
        "score": float(base_score),
    }
    session.last_debug = debug_info

    def disp(pkey: str) -> str:
        return session.display_name_map.get(pkey, pkey)

    predicted_line = None
    try:
        predicted_line = _format_predicted_win_line(team_a, team_b)
    except Exception:
        predicted_line = None

    label_a = f"Team 1 ({len(team_a)} players)"
    label_b = f"Team 2 ({len(team_b)} players)"
    if low_team:
        if low_team == team_a:
            label_a += " — low team"
        elif low_team == team_b:
            label_b += " — low team"

    lines = [f"**Next Teams (with role restrictions) (score {base_score:.3f})**"]
    if predicted_line:
        lines.append(predicted_line)

    # Show which option was chosen from the Top-K pool
    lines.append(f"🎲 Picked **#{picked_rank} of {picked_pool}**")

    def _disp_with_restrict(p: str) -> str:
        return f"{disp(p)} ({_nt_role_emoji((restricted_roles or {}).get(p))})"

    lines.extend([
        f"**{label_a}:** " + ", ".join(_disp_with_restrict(p) for p in sorted(team_a)),
        f"**{label_b}:** " + ", ".join(_disp_with_restrict(p) for p in sorted(team_b)),
    ])

    token = uuid4().hex
    session.pending_roll_token = token
    session.pending_roll_data = {
        "team_a": team_a,
        "team_b": team_b,
        "low_team": low_team,
        "restricted_roles": dict(restricted_roles or {}),
    }

    view = NextTeamsControlsView(key)
    msg = await channel.send("\n".join(lines), view=view)
    session.pending_roll_message_id = msg.id

    try:
        _save_session_state(key, session)
    except Exception:
        pass

# -------------------------
# API identity helpers
# -------------------------
def _pkey_from_uid(uid: int) -> str:
    """Stable string key for a player_uid used by engine dict[str, *] structures."""
    return f"u{int(uid)}"


def _uid_from_pkey(pkey: str) -> int | None:
    try:
        if isinstance(pkey, str) and pkey.startswith("u"):
            return int(pkey[1:])
    except Exception:
        pass
    return None


def _get_all_players() -> dict[str, str]:
    """
    Returns the season-aware player pool used by fairness commands.

    Returns:
      { player_key(str) : display_name(str) }
    Human-only, current season.
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    c.execute(
        """
        SELECT
            pm.player_uid,
            MAX(pm.player) AS player
        FROM mr_player_match pm
        WHERE pm.season_id=?
          AND pm.is_bot=0
        GROUP BY pm.player_uid
        ORDER BY LOWER(MAX(pm.player)) ASC
    """, (season_id, ))

    out = {}
    for uid, name in c.fetchall():
        if uid is None:
            continue
        out[_pkey_from_uid(int(uid))] = str(name or f"UID_{uid}")
    return out

@dataclass
class FairnessContext:
    games_played: dict[str, int] = field(default_factory=dict)
    low_team_games: dict[str, int] = field(default_factory=dict)
    uneven_games: dict[str, int] = field(
        default_factory=dict)  # denominator for low-team ratio
    low_team_pair_games: dict[tuple[str, str], int] = field(
        default_factory=dict)  # season-only teammate pairs on the low team
    pair_games: dict[tuple[str, str], int] = field(default_factory=dict)

    pair_pct: dict[tuple[str, str], float] = field(default_factory=dict)
    avg_pair_pct_by_player: dict[str, float] = field(default_factory=dict)

    low_team_pair_pct: dict[tuple[str, str], float] = field(default_factory=dict)
    avg_low_team_pair_pct_by_player: dict[str, float] = field(default_factory=dict)

    season_low_team_ratio: dict[str, float] = field(
        default_factory=dict)  # low/uneven


@dataclass
class SessionState:
    active_players: set[str] = field(default_factory=set)  # player_key strings
    display_name_map: dict[str, str] = field(default_factory=dict)

    session_games: list[dict] = field(default_factory=list)
    session_low_team_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int))

    last_split: dict | None = None
    last_debug: dict | None = None

    # pending roll state (provisional teams)
    pending_roll_token: str | None = None
    pending_roll_data: dict | None = None
    pending_roll_message_id: int | None = None

    # 47% pair-lock session state
    pair_lock_47_disabled: bool = False
    pair_lock_47_disabled_lobby: tuple[str, ...] | None = None

def _build_fairness_context() -> FairnessContext:
    """
    API-backed season-wide context (HUMANS ONLY):
    - games_played per player
    - low_team_games per player
    - uneven_games per player (denominator for low-team exposure)
    - low_team_pair_games per pair (same low team, season only)
    - pair_games per teammate pair (same team)
    - derived percentages
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    c.execute(
        """
        SELECT pm.game_label, pm.player_uid, pm.is_win
        FROM mr_player_match pm
        WHERE pm.season_id=?
          AND pm.is_bot=0
    """, (season_id, ))
    rows = c.fetchall()

    games_played = defaultdict(int)
    low_team_games = defaultdict(int)
    uneven_games = defaultdict(int)
    low_team_pair_games = defaultdict(int)
    pair_games = defaultdict(int)
    by_game = defaultdict(list)

    for game_label, player_uid, is_win in rows:
        if player_uid is None:
            continue
        p = _pkey_from_uid(int(player_uid))
        games_played[p] += 1
        by_game[str(game_label)].append((p, int(is_win)))

    for _, entries in by_game.items():
        winners = {p for p, w in entries if w == 1}
        losers = {p for p, w in entries if w == 0}

        # Uneven game? Track denominators for all present players.
        if winners and losers and len(winners) != len(losers):
            present = winners | losers
            for p in present:
                uneven_games[p] += 1

            low = winners if len(winners) < len(losers) else losers
            for p in low:
                low_team_games[p] += 1

            # Season-only low-team teammate pair history.
            for a, b in combinations(sorted(low), 2):
                key = (a, b) if a < b else (b, a)
                low_team_pair_games[key] += 1

        # Pairings on same team (season)
        for team in (winners, losers):
            for a, b in combinations(sorted(team), 2):
                key = (a, b) if a < b else (b, a)
                pair_games[key] += 1

    ctx = FairnessContext(
        games_played=dict(games_played),
        low_team_games=dict(low_team_games),
        uneven_games=dict(uneven_games),
        low_team_pair_games=dict(low_team_pair_games),
        pair_games=dict(pair_games),
    )

    # -------------------------
    # Normal teammate pair pct
    # -------------------------
    pair_pct = {}
    avg_by_player = defaultdict(list)
    for (a, b), gms in pair_games.items():
        min_g = max(1, min(games_played[a], games_played[b]))
        pct = gms / min_g
        pair_pct[(a, b)] = pct
        avg_by_player[a].append(pct)
        avg_by_player[b].append(pct)

    ctx.pair_pct = pair_pct
    ctx.avg_pair_pct_by_player = {
        p: (sum(vs) / len(vs)) if vs else 0.0
        for p, vs in avg_by_player.items()
    }

    # ------------------------------------
    # Low-team teammate pair pct (season)
    # ------------------------------------
    low_team_pair_pct = {}
    avg_low_pair_by_player = defaultdict(list)

    for (a, b), gms in low_team_pair_games.items():
        min_low = max(1, min(low_team_games.get(a, 0), low_team_games.get(b, 0)))
        pct = gms / min_low
        low_team_pair_pct[(a, b)] = pct
        avg_low_pair_by_player[a].append(pct)
        avg_low_pair_by_player[b].append(pct)

    ctx.low_team_pair_pct = low_team_pair_pct
    ctx.avg_low_team_pair_pct_by_player = {
        p: (sum(vs) / len(vs)) if vs else 0.0
        for p, vs in avg_low_pair_by_player.items()
    }

    # low-team ratio (low / uneven)
    season_low = {}
    for p in games_played.keys():
        lt = low_team_games.get(p, 0)
        ug = uneven_games.get(p, 0)
        season_low[p] = (lt / ug) if ug > 0 else 0.0
    ctx.season_low_team_ratio = season_low

    return ctx


def _get_session_key(ctx: commands.Context) -> tuple[int, int]:
    guild_id = ctx.guild.id if ctx.guild else 0
    channel_id = ctx.channel.id
    return (guild_id, channel_id)


def _get_or_create_session(ctx):
    key = _get_session_key(ctx)

    # Always ensure season context exists (rebuild from DB if missing)
    if key not in FAIRNESS_CONTEXTS:
        FAIRNESS_CONTEXTS[key] = _build_fairness_context()

    # Restore session from DB if not in memory (e.g., after restart)
    if key not in SESSION_STATES:
        session = SessionState()
        session.display_name_map = _get_all_players()

        saved = _load_session_state(key)
        if saved:
            _apply_session_state(session, saved)

        # If display map empty (first run), refresh from API
        if not session.display_name_map:
            session.display_name_map = _get_all_players()

        SESSION_STATES[key] = session

    return SESSION_STATES[key], FAIRNESS_CONTEXTS[key]

def _get_or_create_session_by_key(key: tuple[int, int]):
    # Ensure season context exists
    if key not in FAIRNESS_CONTEXTS:
        FAIRNESS_CONTEXTS[key] = _build_fairness_context()

    # Restore session from DB if not in memory (restart-safe)
    if key not in SESSION_STATES:
        session = SessionState()
        session.display_name_map = _get_all_players()

        saved = _load_session_state(key)
        if saved:
            _apply_session_state(session, saved)

        if not session.display_name_map:
            session.display_name_map = _get_all_players()

        SESSION_STATES[key] = session

    return SESSION_STATES[key], FAIRNESS_CONTEXTS[key]

class ActivePlayersView(discord.ui.View):
    """
    Multi-select UI to toggle active players for this session.
    When on_done is provided, it will be called after selection is saved.

    Options:
      - persist=False -> do NOT write to SESSION_STATES / DB (useful for previews like !pregame)
      - placeholder / confirm_label -> customise the UI text
    """

    def __init__(self,
                 all_players: dict[str, str],
                 preselected: set[str],
                 session_state: SessionState,
                 on_done=None,
                 *,
                 persist: bool = True,
                 placeholder: str = "Select active players for this session…",
                 confirm_label: str = "Active players updated"):
        super().__init__(timeout=120)
        self.session_state = session_state
        self.on_done = on_done
        self.persist = bool(persist)
        self.confirm_label = str(confirm_label or "Updated")
        self._placeholder = str(placeholder or "Select players…")

        if not all_players:
            return

        options = [
            discord.SelectOption(label=disp, value=pkey, default=(pkey in preselected))
            for pkey, disp in all_players.items()
        ]

        max_values = len(options) if options else 1
        select = discord.ui.Select(
            placeholder=self._placeholder,
            min_values=0,
            max_values=max_values,
            options=options
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        selected = set(self.children[0].values) if self.children else set()
        self.session_state.active_players = selected

        # Persist when requested; session and next_teams flows enable persistence by default.
        if self.persist:
            try:
                key = (int(interaction.guild_id), int(interaction.channel_id))
                _save_session_state(key, self.session_state)
            except Exception:
                pass

        disp_names = [self.session_state.display_name_map.get(k, k) for k in sorted(selected)]
        txt = ", ".join(disp_names) if disp_names else "None"

        await interaction.response.edit_message(
            content=f"{self.confirm_label}: {txt}",
            view=None
        )
        self.stop()

        if self.on_done:
            try:
                await self.on_done(interaction)
            except Exception:
                pass



class NextTeamsControlsView(discord.ui.View):
    """
    Season 5 workflow buttons:
      - Redo - Change Lobby   (discard, change active players, auto reroll)
      - Next Teams - Same Lobby   (commit played, reroll)
      - Next Teams - Change Lobby (commit played, change active players, auto reroll)
    """

    MAX_AGE_SECONDS = 3600  # 1 hour

    def __init__(self, key: tuple[int, int]):
        # timeout=None makes this a persistent view that can survive bot restarts
        super().__init__(timeout=None)
        self.key = key

    def _get_session(self):
        return SESSION_STATES.get(self.key)

    def _is_expired(self, interaction: discord.Interaction) -> bool:
        try:
            msg = interaction.message
            created_at = getattr(msg, "created_at", None)
            if created_at is None:
                return False
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_s = (datetime.now(timezone.utc) - created_at).total_seconds()
            return age_s >= float(self.MAX_AGE_SECONDS)
        except Exception:
            return False

    async def _reject_if_expired(self, interaction: discord.Interaction) -> bool:
        if not self._is_expired(interaction):
            return False

        try:
            await interaction.response.edit_message(view=None)
        except Exception:
            try:
                await interaction.response.send_message(
                    "These buttons have expired. Run `!next_teams` again to continue.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return True

        try:
            await interaction.followup.send(
                "These buttons have expired. Run `!next_teams` again to continue.",
                ephemeral=True,
            )
        except Exception:
            pass

        return True

    @discord.ui.button(
        label="Redo - Change Lobby",
        style=discord.ButtonStyle.danger,
        custom_id="nextteams:redo_change_lobby",
    )
    async def redo_change_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._reject_if_expired(interaction):
            return

        session, _ = _get_or_create_session_by_key(self.key)

        # Discard pending without recording
        session.pending_roll_token = None
        session.pending_roll_data = None
        session.pending_roll_message_id = None
        try:
            _save_session_state(self.key, session)
        except Exception:
            pass

        # Mark old message as discarded + remove buttons
        old = (interaction.message.content or "") + "\n\n🗑️ Discarded (not played)."
        await interaction.response.edit_message(content=old, view=None)

        # Prompt lobby change; after selection, auto-roll next teams
        if not session.display_name_map:
            session.display_name_map = _get_all_players()

        async def _after_lobby_change(_interaction: discord.Interaction):
            await _run_next_teams_roll(_interaction.channel, self.key, commit_pending=False)

        view = ActivePlayersView(session.display_name_map, session.active_players, session, on_done=_after_lobby_change)
        await interaction.followup.send("Update active players for this session:", view=view)

    @discord.ui.button(
        label="Next Teams - Same Lobby",
        style=discord.ButtonStyle.success,
        custom_id="nextteams:next_same_lobby",
    )
    async def next_same_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._reject_if_expired(interaction):
            return

        session, _ = _get_or_create_session_by_key(self.key)

        if not session or not getattr(session, "pending_roll_token", None) or not getattr(session, "pending_roll_data", None):
            await interaction.response.send_message("No pending teams to record. Run `!next_teams` first.", ephemeral=True)
            return

        # Commit pending roll as played
        try:
            _commit_pending_roll(session, session.pending_roll_token, key=self.key)
        except NameError:
            _commit_pending_roll_fallback(session, session.pending_roll_token, key=self.key)

        try:
            _save_session_state(self.key, session)
        except Exception:
            pass

        # Close out old message
        old = (interaction.message.content or "") + "\n\n✅ Recorded as played."
        await interaction.response.edit_message(content=old, view=None)

        # Generate next teams
        await _run_next_teams_roll(interaction.channel, self.key, commit_pending=False)

    @discord.ui.button(
        label="Next Teams - Change Lobby",
        style=discord.ButtonStyle.primary,
        custom_id="nextteams:next_change_lobby",
    )
    async def next_change_lobby(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await self._reject_if_expired(interaction):
            return

        session, _ = _get_or_create_session_by_key(self.key)

        if not session or not getattr(session, "pending_roll_token", None) or not getattr(session, "pending_roll_data", None):
            await interaction.response.send_message("No pending teams to record. Run `!next_teams` first.", ephemeral=True)
            return

        # Commit pending roll as played
        try:
            _commit_pending_roll(session, session.pending_roll_token, key=self.key)
        except NameError:
            _commit_pending_roll_fallback(session, session.pending_roll_token, key=self.key)

        try:
            _save_session_state(self.key, session)
        except Exception:
            pass

        # Close out old message
        old = (interaction.message.content or "") + "\n\n✅ Recorded as played."
        await interaction.response.edit_message(content=old, view=None)

        # Prompt lobby change; after selection, auto-roll next teams
        if not session.display_name_map:
            session.display_name_map = _get_all_players()

        async def _after_lobby_change(_interaction: discord.Interaction):
            await _run_next_teams_roll(_interaction.channel, self.key, commit_pending=False)

        view = ActivePlayersView(session.display_name_map, session.active_players, session, on_done=_after_lobby_change)
        await interaction.followup.send("Update active players for this session:", view=view)

def _iter_saved_pending_nextteams_views():
    """
    Returns a list of:
      [((guild_id, channel_id), pending_roll_message_id), ...]
    for sessions that still have an active pending next_teams message.
    """
    try:
        c.execute("SELECT guild_id, channel_id, state_json FROM session_state")
        rows = c.fetchall()
    except Exception:
        return []

    out = []
    for guild_id, channel_id, state_json in rows:
        try:
            data = json.loads(state_json)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        message_id = data.get("pending_roll_message_id")
        token = data.get("pending_roll_token")
        pending_data = data.get("pending_roll_data")

        if not message_id or not token or not pending_data:
            continue

        try:
            out.append(((int(guild_id), int(channel_id)), int(message_id)))
        except Exception:
            continue

    return out


def _register_persistent_nextteams_views():
    global _PERSISTENT_NEXTTEAMS_VIEWS_REGISTERED

    if _PERSISTENT_NEXTTEAMS_VIEWS_REGISTERED:
        return

    for key, message_id in _iter_saved_pending_nextteams_views():
        try:
            bot.add_view(NextTeamsControlsView(key), message_id=message_id)
        except Exception:
            pass

    _PERSISTENT_NEXTTEAMS_VIEWS_REGISTERED = True

def _commit_pending_roll_fallback(session: SessionState,
                                  token: str,
                                  *,
                                  key=None) -> bool:
    if not token or session.pending_roll_token != token or not session.pending_roll_data:
        return False

    data = session.pending_roll_data
    team_a = frozenset(data.get("team_a") or [])
    team_b = frozenset(data.get("team_b") or [])
    low_team = data.get("low_team")
    low_team = frozenset(low_team) if low_team else None

    rr = data.get("restricted_roles")
    restricted_roles = dict(rr) if isinstance(rr, dict) and rr else None

    session.session_games.append({
        "team_a": team_a,
        "team_b": team_b,
        "low_team": low_team,
        "restricted_roles": restricted_roles,
    })

    if low_team:
        for p in low_team:
            session.session_low_team_counts[p] += 1

    session.pending_roll_token = None
    session.pending_roll_data = None
    session.pending_roll_message_id = None

    try:
        if key is not None:
            _save_session_state(key, session)
    except Exception:
        pass

    return True


def _commit_pending_roll(session: SessionState,
                         token: str,
                         *,
                         key: tuple[int, int] | None = None) -> bool:
    """
    Converts the currently pending roll into a committed session game.
    This makes the pending roll 'included' even if you never click Played,
    as soon as another command triggers a commit.
    """
    if not token:
        return False
    if session.pending_roll_token != token:
        return False
    if not session.pending_roll_data:
        return False

    data = session.pending_roll_data

    # Pending data may contain frozensets already; normalise safely
    def _to_froze(x):
        if x is None:
            return None
        if isinstance(x, (set, frozenset)):
            return frozenset(x)
        if isinstance(x, list):
            return frozenset(x)
        return frozenset([x])

    team_a = _to_froze(data.get("team_a")) or frozenset()
    team_b = _to_froze(data.get("team_b")) or frozenset()
    low_team = _to_froze(
        data.get("low_team")) if data.get("low_team") else None

    rr = data.get("restricted_roles")
    restricted_roles = dict(rr) if isinstance(rr, dict) and rr else None

    session.session_games.append({
        "team_a": team_a,
        "team_b": team_b,
        "low_team": low_team,
        "restricted_roles": restricted_roles,
    })

    # Update low-team counts used by the fairness engine.
    if low_team:
        for p in low_team:
            session.session_low_team_counts[p] += 1

    # Clear pending state
    session.pending_roll_token = None
    session.pending_roll_data = None
    session.pending_roll_message_id = None

    # Persist immediately so session continues across restarts
    try:
        if key is not None:
            _save_session_state(key, session)
    except Exception:
        pass

    return True


def _serialise_game(g: dict) -> dict:

    def _as_list(x):
        if x is None:
            return None
        if isinstance(x, (set, frozenset)):
            return sorted(list(x))
        if isinstance(x, list):
            return x
        return [x]

    return {
        "team_a": _as_list(g.get("team_a")),
        "team_b": _as_list(g.get("team_b")),
        "low_team": _as_list(g.get("low_team")) if g.get("low_team") else None,
    }


def _deserialise_game(g: dict) -> dict:

    def _as_froze(x):
        if x is None:
            return None
        return frozenset(x)

    return {
        "team_a": _as_froze(g.get("team_a") or []),
        "team_b": _as_froze(g.get("team_b") or []),
        "low_team":
        _as_froze(g.get("low_team")) if g.get("low_team") else None,
    }


# serialize EVERYTHING needed to resume sessions after restart,
# including pending_roll_* fields and frozenset/set conversion.


def _json_safe(obj):
    """Recursively convert session objects (sets/frozensets/defaultdict/tuples) into JSON-safe types."""

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, (set, frozenset)):
        # sort for stable output
        return sorted(list(obj))

    if isinstance(obj, tuple):
        return [_json_safe(x) for x in obj]

    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]

    if isinstance(obj, defaultdict):
        return {str(k): _json_safe(v) for k, v in dict(obj).items()}

    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}

    # last resort: stringify unknown objects
    return str(obj)


def _serialize_session(session: SessionState) -> dict:
    """Full SessionState → dict suitable for json.dumps()."""
    payload = {
        "version": 1,

        # lobby
        "active_players": sorted(list(session.active_players)),
        "display_name_map": dict(session.display_name_map or {}),

        # committed session history
        "session_games": session.session_games or [],
        "session_low_team_counts": dict(session.session_low_team_counts or {}),

        # last roll/debug (optional)
        "last_split": session.last_split,
        "last_debug": session.last_debug,

        # Pending roll state required across interactions.
        "pending_roll_token": session.pending_roll_token,
        "pending_roll_data": session.pending_roll_data,
        "pending_roll_message_id": session.pending_roll_message_id,

        # pair-lock session state
        "pair_lock_47_disabled": bool(getattr(session, "pair_lock_47_disabled", False)),
        "pair_lock_47_disabled_lobby": (
            sorted(list(getattr(session, "pair_lock_47_disabled_lobby", []) or []))
            if getattr(session, "pair_lock_47_disabled_lobby", None)
            else None
        ),
    }

    # Ensure JSON safe (frozensets -> lists, defaultdict -> dict, etc.)
    return _json_safe(payload)

def _build_session_pair_stats(session: SessionState):
    """
    Build session-level teammate pairing stats:
      - pair_games_session[(a,b)]
      - games_session_player[p]
      - pair_pct_session[(a,b)]
      - avg_pair_pct_session_by_player[p]
    Based only on committed games in this session.
    """
    pair_games = defaultdict(int)
    games_played = defaultdict(int)

    for g in session.session_games:
        for team in (g["team_a"], g["team_b"]):
            for p in team:
                games_played[p] += 1
            for a, b in combinations(sorted(team), 2):
                pair_games[(a, b)] += 1

    pair_pct_session = {}
    avg_pair_pct_session_by_player = defaultdict(list)

    for (a, b), cnt in pair_games.items():
        min_g = max(1, min(games_played[a], games_played[b]))
        pct = cnt / min_g
        pair_pct_session[(a, b)] = pct
        avg_pair_pct_session_by_player[a].append(pct)
        avg_pair_pct_session_by_player[b].append(pct)

    avg_session = {
        p: (sum(vs) / len(vs)) if vs else 0.0
        for p, vs in avg_pair_pct_session_by_player.items()
    }

    return pair_pct_session, avg_session

def _compute_fairness_score(
    team_a: frozenset[str],
    team_b: frozenset[str],
    low_team: frozenset[str] | None,
    ctx: FairnessContext,
    session: SessionState,
    active_players: list[str],
    *,
    debug: bool = False,
) -> tuple[float, dict | None]:
    """Season pairing + low-team fairness score.

    This remains season-focused. Committed session games are treated as additional
    season games so the score evolves immediately as you record games.

    Low-team teammate mix fairness is season-only:
    - it penalises repeated low-team pairings when those pairings are unusually high
      relative to each player's broader season low-team partner mix
    """

    # Pairing overuse penalty weight
    alpha_season = 50.0
    # Low-team imbalance penalty weight
    beta = 200.0
    # Season-only low-team teammate-repeat penalty weight.
    gamma_low_pair = 90.0

    # Small noise only (tie-break)
    noise = random.uniform(0.0, 0.01)

    # ---- Build effective (season + committed session) stats ----
    eff_games = defaultdict(int, ctx.games_played or {})
    for g in (session.session_games or []):
        for p in (g["team_a"] | g["team_b"]):
            eff_games[p] += 1

    eff_pair_games = defaultdict(int, ctx.pair_games or {})
    for g in (session.session_games or []):
        for team in (g["team_a"], g["team_b"]):
            for a, b in combinations(sorted(team), 2):
                key = (a, b) if a < b else (b, a)
                eff_pair_games[key] += 1

    eff_pair_pct = {}
    eff_avg_by_player = defaultdict(list)
    for a, b in combinations(sorted(active_players), 2):
        key = (a, b) if a < b else (b, a)
        gms = float(eff_pair_games.get(key, 0))
        min_g = max(1.0, float(min(eff_games.get(a, 0), eff_games.get(b, 0))))
        pct = gms / min_g
        eff_pair_pct[key] = pct
        eff_avg_by_player[a].append(pct)
        eff_avg_by_player[b].append(pct)

    eff_avg_pair_pct = {
        p: (sum(vs) / len(vs)) if vs else 0.0
        for p, vs in eff_avg_by_player.items()
    }

    pair_details = []

    def team_pair_penalty(team: frozenset[str]) -> float:
        total = 0.0
        pair_count = 0
        for i, j in combinations(sorted(team), 2):
            key = (i, j) if i < j else (j, i)
            p_ij = float(eff_pair_pct.get(key, 0.0))
            avg_i = float(eff_avg_pair_pct.get(i, 0.0))
            avg_j = float(eff_avg_pair_pct.get(j, 0.0))

            over_i = max(0.0, p_ij - avg_i)
            over_j = max(0.0, p_ij - avg_j)
            over_total = (over_i + over_j)

            total += over_total
            pair_count += 1

            if debug:
                pair_details.append({
                    "pair": (i, j),
                    "pair_pct": p_ij,
                    "avg_i": avg_i,
                    "avg_j": avg_j,
                    "over_i": over_i,
                    "over_j": over_j,
                    "over_total": over_total,
                })

        return (total / pair_count) if pair_count else 0.0

    season_pair_penalty = team_pair_penalty(team_a) + team_pair_penalty(team_b)

    # ---------- Low-team penalty (season objective, evolving via committed session games) ----------
    low_team_penalty = 0.0
    low_team_details = []

    eff_uneven = defaultdict(int, ctx.uneven_games or {})
    eff_low = defaultdict(int, ctx.low_team_games or {})

    for g in (session.session_games or []):
        lt = g.get("low_team")
        if not lt:
            continue
        for p in (g["team_a"] | g["team_b"]):
            eff_uneven[p] += 1
        for p in lt:
            eff_low[p] += 1

    target_low = (len(low_team) / max(1, len(active_players))) if low_team else None

    if low_team and target_low is not None:
        MIN_UNEVEN_BASELINE = 2

        def effective_ratio(p: str) -> float:
            ug = int(eff_uneven.get(p, 0))
            if ug < MIN_UNEVEN_BASELINE:
                return float(target_low)
            lc = int(eff_low.get(p, 0))
            return (lc / ug) if ug > 0 else float(target_low)

        for p in low_team:
            eff_r = effective_ratio(p)
            base_penalty = max(0.0, eff_r - float(target_low))
            low_team_penalty += base_penalty

            if debug:
                low_team_details.append({
                    "player": p,
                    "effective_ratio": eff_r,
                    "target_low": float(target_low),
                    "base_penalty": base_penalty,
                    "eff_low": int(eff_low.get(p, 0)),
                    "eff_uneven": int(eff_uneven.get(p, 0)),
                })

    # ---------- Season-only low-team teammate mix penalty ----------
    low_team_pair_penalty = 0.0
    low_team_pair_details = []

    if low_team and len(low_team) >= 2:
        total = 0.0
        pair_count = 0

        season_low_pair_pct = dict(ctx.low_team_pair_pct or {})
        season_low_pair_avg = dict(ctx.avg_low_team_pair_pct_by_player or {})
        season_low_pair_games = dict(ctx.low_team_pair_games or {})
        season_low_games = dict(ctx.low_team_games or {})

        for i, j in combinations(sorted(low_team), 2):
            key = (i, j) if i < j else (j, i)

            p_ij = float(season_low_pair_pct.get(key, 0.0))
            avg_i = float(season_low_pair_avg.get(i, 0.0))
            avg_j = float(season_low_pair_avg.get(j, 0.0))

            over_i = max(0.0, p_ij - avg_i)
            over_j = max(0.0, p_ij - avg_j)
            over_total = over_i + over_j

            total += over_total
            pair_count += 1

            if debug:
                low_team_pair_details.append({
                    "pair": (i, j),
                    "season_low_pair_games": int(season_low_pair_games.get(key, 0)),
                    "low_team_games_i": int(season_low_games.get(i, 0)),
                    "low_team_games_j": int(season_low_games.get(j, 0)),
                    "pair_pct": p_ij,
                    "avg_i": avg_i,
                    "avg_j": avg_j,
                    "over_i": over_i,
                    "over_j": over_j,
                    "over_total": over_total,
                })

        low_team_pair_penalty = (total / pair_count) if pair_count else 0.0

    score = (
        (alpha_season * season_pair_penalty)
        + (beta * low_team_penalty)
        + (gamma_low_pair * low_team_pair_penalty)
        + noise
    )

    if not debug:
        return score, None

    debug_info = {
        "season_pair_penalty": float(season_pair_penalty),
        "low_team_penalty": float(low_team_penalty),
        "low_team_pair_penalty": float(low_team_pair_penalty),
        "total_score": float(score),
        "pair_details": pair_details,
        "low_team_details": low_team_details,
        "low_team_pair_details": low_team_pair_details,
        "target_low": (float(target_low) if target_low is not None else None),
    }
    return score, debug_info


# ---- Candidate utilities ----
def _iter_splits_exhaustive(players: list[str], big_size: int):
    """
    Yield unique (team_a, team_b) splits.
    For even n and equal sizes, anchor one player to avoid mirrored duplicates.
    """
    players = list(players)
    n = len(players)

    if n % 2 == 0 and big_size == n // 2:
        anchor = players[0]
        rest = players[1:]
        for combo in combinations(rest, big_size - 1):
            team_a = frozenset((anchor, *combo))
            team_b = frozenset(p for p in players if p not in team_a)
            yield team_a, team_b
    else:
        for combo in combinations(players, big_size):
            team_a = frozenset(combo)
            team_b = frozenset(p for p in players if p not in team_a)
            yield team_a, team_b


# ============================================================
# Skill model + size advantage — API INTEGRATED
# (Used only for predicted win chance display — does NOT affect teams)
# ============================================================


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _compute_skill_scores(*,
                          skill_min_games_shrink_k: float = 8.0,
                          win_smooth: float = 2.0,
                          award_smooth: float = 10.0,
                          W_WIN: float = 0.88,
                          W_MVP: float = 0.08,
                          W_SVP: float = 0.04):
    """
    API-backed.
    Returns:
      skill_by_key: dict[player_key] -> float in [0..1]
      games_by_key: dict[player_key] -> int
      wins_by_key : dict[player_key] -> int
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    # games + wins from mr_player_match (humans only)
    c.execute(
        """
        SELECT
            player_uid,
            COUNT(*) as games,
            SUM(CASE WHEN is_win=1 THEN 1 ELSE 0 END) as wins
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
        GROUP BY player_uid
    """, (season_id, ))
    rows = c.fetchall()

    games = {}
    wins = {}
    for uid, g, w in rows:
        if uid is None:
            continue
        key = _pkey_from_uid(int(uid))
        games[key] = int(g or 0)
        wins[key] = int(w or 0)

    # MVP/SVP counts from mr_match_meta (per match)
    c.execute(
        """
        SELECT mvp_uid, svp_uid
        FROM mr_match_meta
        WHERE season_id=?
    """, (season_id, ))
    meta = c.fetchall()

    mvps = defaultdict(int)
    svps = defaultdict(int)
    for mvp_uid, svp_uid in meta:
        if mvp_uid is not None:
            try:
                mvps[_pkey_from_uid(int(mvp_uid))] += 1
            except Exception:
                pass
        if svp_uid is not None:
            try:
                svps[_pkey_from_uid(int(svp_uid))] += 1
            except Exception:
                pass

    skill = {}
    for p, g in games.items():
        if g <= 0:
            continue

        w = wins.get(p, 0)
        m = mvps.get(p, 0)
        s = svps.get(p, 0)

        win_rate = (w + (win_smooth * 0.5)) / (g + win_smooth)
        mvp_rate = (m + (award_smooth * 0.0)) / (g + award_smooth)
        svp_rate = (s + (award_smooth * 0.0)) / (g + award_smooth)

        raw = (W_WIN * win_rate) + (W_MVP * mvp_rate) + (W_SVP * svp_rate)
        raw = _clamp(raw, 0.0, 1.0)

        reliability = g / (g + skill_min_games_shrink_k)
        final_skill = 0.5 + (raw - 0.5) * reliability
        skill[p] = _clamp(final_skill, 0.0, 1.0)

    return dict(skill), dict(games), dict(wins)


def _compute_team_size_advantage_map(scale: float = 6.0) -> dict[int, float]:
    """
    API-backed.
    Returns mapping: size_diff -> diff_equiv (added to skill difference).
    Uses historical larger-team win rate in uneven games (humans only).
    """
    ensure_mr_api_tables()
    season_id = get_current_season_id()

    c.execute(
        """
        SELECT game_label, is_win
        FROM mr_player_match
        WHERE season_id=?
          AND is_bot=0
    """, (season_id, ))
    rows = c.fetchall()

    by_game = defaultdict(list)
    for game_label, is_win in rows:
        by_game[str(game_label)].append(int(is_win or 0))

    bigger_wins = defaultdict(int)
    counts = defaultdict(int)

    for _, wins_list in by_game.items():
        win_ct = sum(1 for w in wins_list if w == 1)
        loss_ct = sum(1 for w in wins_list if w == 0)
        if win_ct == 0 or loss_ct == 0:
            continue
        if win_ct == loss_ct:
            continue

        diff = abs(win_ct - loss_ct)
        counts[diff] += 1

        # bigger team won if winning team is larger
        larger_team_won = 1 if win_ct > loss_ct else 0
        bigger_wins[diff] += larger_team_won

    adv = {}
    for diff, n in counts.items():
        r = bigger_wins[diff] / n
        r = min(0.999, max(0.001, r))
        logit = math.log(r / (1.0 - r))
        diff_equiv = logit / scale
        diff_equiv = max(-0.10, min(0.10, diff_equiv))
        adv[diff] = diff_equiv

    return adv


# ======================================================================
# Session/next_teams selectable players come from mr_roster,
# falling back to season match data when the roster is empty.
# ======================================================================

def _get_all_players_from_roster() -> dict[str, str]:
    """
    Returns { 'u<player_uid>': display_name } for enabled roster players.
    This works even if the current season has zero imported games yet.
    """
    ensure_auto_import_tables()
    c.execute("""
        SELECT player_uid, player_name
        FROM mr_roster
        WHERE enabled=1
        ORDER BY
          CASE WHEN TRIM(COALESCE(player_name,''))='' THEN 1 ELSE 0 END,
          LOWER(COALESCE(player_name,'')) ASC,
          player_uid ASC
    """)
    out: dict[str, str] = {}
    for uid, nm in c.fetchall():
        if uid is None:
            continue
        try:
            uid_i = int(uid)
        except Exception:
            continue
        pkey = f"u{uid_i}"
        disp = (nm or "").strip() or f"UID_{uid_i}"
        out[pkey] = disp
    return out


def _get_all_players_prefer_roster() -> dict[str, str]:
    """
    Prefer roster; fallback to existing season-derived player list.
    """
    roster_map = _get_all_players_from_roster()
    if roster_map:
        return roster_map

    # Compatibility fallbacks for optional helpers.
    try:
        return _get_all_players_unified()  # optional unified helper
    except Exception:
        pass

    try:
        return _get_all_players()  # season-derived (mr_player_match)
    except Exception:
        pass

    return {}


# Override the fairness/session player list source used across UI controls
try:
    globals()["_get_all_players"] = _get_all_players_prefer_roster
except Exception:
    pass


# ------------------------------------------------------------------------------------------------------------
# session_start (roster-first, works with 0 games in the season)
# ------------------------------------------------------------------------------------------------------------
try:
    bot.remove_command("session_start")
except Exception:
    pass

@bot.command(name="session_start")
async def session_start_cmd(ctx):
    """
    Start/reset fairness session and select active players.
    Player list is sourced from enabled roster first (fallbacks if roster empty).
    Works even if the current season has zero imported games.
    """
    key = _get_session_key(ctx)

    # Rebuild season context for current season (OK if no games yet; context may be empty)
    try:
        FAIRNESS_CONTEXTS[key] = _build_fairness_context()
    except Exception:
        pass

    # Reset persisted session for this channel
    try:
        _delete_session_state(key)
    except Exception:
        pass

    session = SessionState()
    session.display_name_map = _get_all_players_prefer_roster()
    SESSION_STATES[key] = session

    try:
        _save_session_state(key, session)
    except Exception:
        pass

    if not session.display_name_map:
        await ctx.send(
            "No players available yet. Add players using `!roster_add <player_uid> [name]`, "
            "or import at least one match for this season."
        )
        return

    view = ActivePlayersView(session.display_name_map, session.active_players, session)
    await ctx.send("Select active players for this session:", view=view)


# Re-register session_players to use roster-based display map
try:
    bot.remove_command("session_players")
except Exception:
    pass


@bot.command(name="session_players")
async def session_players(ctx):
    """
    Adjust active players for current session.
    Player list is sourced from enabled roster first.
    """
    session, _fair_ctx = _get_or_create_session(ctx)
    key = _get_session_key(ctx)

    # Keep existing behaviour: if there is a pending roll, commit it before changing lobby.
    try:
        if getattr(session, "pending_roll_token", None) and getattr(session, "pending_roll_data", None):
            _commit_pending_roll(session, session.pending_roll_token, key=key)
    except Exception:
        pass

    if not session.display_name_map:
        session.display_name_map = _get_all_players_prefer_roster()

    if not session.display_name_map:
        await ctx.send(
            "No players available yet. Add players using `!roster_add <player_uid> [name]` "
            "or import at least one match for this season."
        )
        return

    view = ActivePlayersView(session.display_name_map, session.active_players, session)
    await ctx.send("Update active players for this session:", view=view)

@bot.command(name='next_teams')
async def next_teams(ctx):
    key = _get_session_key(ctx)
    await _run_next_teams_roll(ctx.channel, key, commit_pending=True)

@bot.command(name='fairness_debug')
async def fairness_debug(ctx):
    """Explain the last `!next_teams` result (season + session-aware)."""

    key = _get_session_key(ctx)
    session = SESSION_STATES.get(key)

    if not session or not session.last_split or not session.last_debug:
        await ctx.send("No recent team randomisation found to debug.")
        return

    split = session.last_split
    dbg = session.last_debug or {}

    team_a = split.get("team_a") or frozenset()
    team_b = split.get("team_b") or frozenset()
    low_team = split.get("low_team")

    def disp(pkey: str) -> str:
        return session.display_name_map.get(pkey, pkey)

    lines = []
    lines.append("**Fairness debug for last `!next_teams`**")
    lines.append(f"Base score (season pair + low-team): {float(dbg.get('total_score', 0.0)):.4f}")
    lines.append(f"Season pair penalty (raw): {float(dbg.get('season_pair_penalty', 0.0)):.4f}")
    lines.append(f"Low-team penalty (raw): {float(dbg.get('low_team_penalty', 0.0)):.4f}")

    if dbg.get("target_low") is not None:
        lines.append(f"Target low-team rate this lobby: {float(dbg.get('target_low', 0.0)):.3f}")

    # “steep” / extra terms applied in _run_next_teams_roll
    if "total_with_steep_terms" in dbg:
        lines.append("")
        lines.append(f"Total with steep + season composition terms: {float(dbg.get('total_with_steep_terms', 0.0)):.4f}")
        lines.append(f"  - worst_over (steep): {float(dbg.get('steep_pair_worst_over', 0.0)):.4f}")
        lines.append(f"  - under_sum (steep): {float(dbg.get('steep_pair_under_sum', 0.0)):.4f}")
        lines.append(f"  - low spread (steep): {float(dbg.get('steep_low_spread', 0.0)):.4f}")
        lines.append(f"  - low L1 avg (steep): {float(dbg.get('steep_low_l1avg', 0.0)):.4f}")
        lines.append(f"  - season composition penalty: {float(dbg.get('steep_season_comp_penalty', 0.0)):.4f}")
        lines.append(f"  - steep extra total (excl. comp): {float(dbg.get('steep_extra_total', 0.0)):.4f}")

    lines.append("")
    label_a = "Team 1"
    label_b = "Team 2"
    if low_team:
        if low_team == team_a:
            label_a += " (low team)"
        elif low_team == team_b:
            label_b += " (low team)"

    lines.append(f"**{label_a}:** " + ", ".join(sorted(disp(p) for p in team_a)))
    lines.append(f"**{label_b}:** " + ", ".join(sorted(disp(p) for p in team_b)))
    lines.append("")

    ltd = dbg.get("low_team_details") or []
    if ltd:
        lines.append("**Low-team details (effective ratio vs target):**")
        for e in ltd:
            p = disp(e.get("player", ""))
            lines.append(
                f"- {p}: eff_ratio={float(e.get('effective_ratio', 0.0)):.3f}, "
                f"target={float(e.get('target_low', 0.0)):.3f}, "
                f"base_pen={float(e.get('base_penalty', 0.0)):.3f}, "
                f"eff_low={int(e.get('eff_low', 0))}, eff_uneven={int(e.get('eff_uneven', 0))}"
            )
        lines.append("")

    pair_details = dbg.get("pair_details") or []
    if pair_details:
        top = sorted(pair_details, key=lambda e: float(e.get("over_total", 0.0)), reverse=True)[:10]
        lines.append("**Top teammate pairs (overuse vs each player's average):**")
        for e in top:
            p1 = disp(e["pair"][0])
            p2 = disp(e["pair"][1])
            lines.append(
                f"- {p1} & {p2}: pair_pct={float(e.get('pair_pct', 0.0)):.3f}, "
                f"avg_i={float(e.get('avg_i', 0.0)):.3f}, avg_j={float(e.get('avg_j', 0.0)):.3f}, "
                f"over={float(e.get('over_total', 0.0)):.3f}"
            )

    await ctx.send("\n".join(lines))



# ============================================================================================================
# ============================================================================================================
# Command - Help Me
# ============================================================================================================
# ============================================================================================================

@bot.command(name="helpme", aliases=["helper", "commands", "help_cmds"])
async def helpme(ctx):
    admin_only = ""

    sections = [
        (
            "📥 Match Imports & Game Management (API)",
            [
                ("!submit_match <match_id_or_url> [game_label]",
                 "Import one match from the official API or a RivalsMeta match URL."),
                ("!browse_games",
                 "List recorded games for the current season, most recent first."),
                ("!edit_game <game_label> [new_match_or_url]",
                 "Re-import/replace a stored game label via the official API or RivalsMeta."),
                ("!undo_last_game",
                 "Delete the most recently imported game in the current season."),
                ("!delete_game <game_label>",
                 "Delete a game and create a DELETED tombstone so auto-import does not bring it back."),
                ("!undelete_match <match_uid>",
                 "Remove a DELETED tombstone so the match can be imported again if discoverable."),
            ],
        ),
        (
            "🤖 Manual Auto Import",
            [
                ("!auto_import_run [days=4] [refresh] [reset_cursor] [rivalsmeta]",
                 "Manual official-first import with automatic RivalsMeta fallback; use rivalsmeta to force the backup provider."),
                ("!auto_import_status",
                 "Show manual-import settings, cutoff, last run summary, and API seasons scanned."),
                ("!auto_import_cutoff [YYYY-MM-DD]",
                 "Show or set the Brisbane-date import cutoff floor."),
                ("!auto_import_debug <player_uid>",
                 "Debug why recent matches are/aren’t importing for a UID."),
                ("!match_history_probe <player_uid> [pages] [step] [season] [game_mode]",
                 "Probe raw match-history paging/rate-limit behaviour."),
                ("!skipped_draws [limit]",
                 "List matches skipped because they were detected as draws."),
                ("!auto_import_on / !auto_import_off",
                 "Legacy compatibility flag only; background polling is disabled in this build."),
            ],
        ),
        (
            "👥 Roster & Season Windows",
            [
                ("!roster_list",
                 "Show the enabled import roster UIDs."),
                ("!roster_add <player_uid> [name]",
                 "Add/enable a roster UID."),
                ("!roster_remove <player_uid>",
                 "Disable a roster UID."),
                ("!roster_update_all",
                 "Queue API-side refresh for all enabled roster UIDs. Use sparingly."),
                ("!season_windows",
                 "Show configured Brisbane-time season windows used by auto-import routing."),
                ("!season_window_set <season_id> <start> <end|OPEN> [note=...]",
                 "Set a Brisbane-time season window."),
                ("!season_split_window_set <season_id> <0|0.5> <start> <end> [note]",
                 "Set exact Brisbane-date windows for each leaderboard half. Alias: !season_half_window_set."),
            ],
        ),
        (
            "🗂️ Seasons",
            [
                ("!season",
                 "Show the current active season id."),
                ("!list_seasons",
                 "List seasons and game counts."),
                ("!set_season <season_id>",
                 "Switch active season."),
                ("!reset_season [season_id]",
                 "Start/switch to a new season while preserving old seasons."),
            ],
        ),
        (
            "🏆 Leaderboards & Reporting",
            [
                ("!run_all_stats",
                 "Create/update dedicated stats channels and post the latest stat outputs."),
                ("!leaderboard_image [0.5|bots|both|main]",
                 "Render leaderboard image(s), including the split 0/.5 season view."),
                ("!session_overview [YYYY-MM-DD]",
                 "Session reporting images for a Brisbane date."),
                ("!season_overviews",
                 "Create a thread with session_overview outputs for the season."),
                ("!season_story",
                 "Season recap card with top performers, duos, hero meta, bans and upset highlights."),
                ("!season_movie_pack [season_id]",
                 "Download a JSON/Markdown pack for generating a cinematic season story."),
                ("!profile [player]",
                 "Single-player season dashboard image."),
                ("!pregame",
                 "Select expected-online players and generate pregame low-team, matrix, role and leaderboard images."),
            ],
        ),
        (
            "🦸 Heroes, Roles & Bans",
            [
                ("!hero_time [player]",
                 "Hero time played stats."),
                ("!player_heros [player]",
                 "Hero performance for a player or top dominant hero-player combos. Alias: !player_heroes."),
                ("!hero_tierlist [humans|bots|both] [min_picks] [top_n]",
                 "Season hero tier list using eligible hero time."),
                ("!hero_synergy [humans|bots|both] [min_games] [top_n]",
                 "Best same-team hero pairings by win%."),
                ("!hero_bans",
                 "Overall season hero ban stats."),
                ("!player_bans",
                 "Enemy-ban stats against each player."),
                ("!refresh_heroes",
                 "Force refresh hero name/role cache from the API."),
                ("!hero_roles_check",
                 "Audit hero role coverage in hero_cache."),
                ("!hero_role_set <hero_id> <role>",
                 "Manually set a hero role in hero_cache."),
                ("!backfill_hero_dht [season]",
                 "Backfill per-hero damage/heal/taken from stored raw match JSON."),
            ],
        ),
        (
            "🤝 Synergy, Matrices & Matchups",
            [
                ("!teammate_matrix_fair",
                 "Fair teammate matrix showing same-team overlap and percentages."),
                ("!teammate_matrix_lowteam_fair",
                 "Low-team teammate matrix for uneven games only."),
                ("!win_matrix",
                 "Teammate win matrix."),
                ("!low_team",
                 "Low-team exposure and performance image."),
                ("!2v2_records",
                 "Everyone’s 2v2 W/L records."),
                ("!4v4_records",
                 "Everyone's W/L records for games with at least 4 humans per team."),
                ("!h2h",
                 "Head-to-head / matchup view. Aliases: !head2head, !head_to_head."),
                ("!role_distribution",
                 "Role distribution images."),
                ("!role_winrates [player] [role]",
                 "Role win-rate table, with optional player-role teammate filter."),
                ("!top3_stack",
                 "Analyse how often players were on a team with selected top-3 players."),
            ],
        ),
        (
            "🧠 Fairness Team Randomiser",
            [
                ("!session_start",
                 "Start a new fairness session and select active players."),
                ("!session_players",
                 "Update active players for the current fairness session."),
                ("!next_teams",
                 "Generate next teams using fairness-weighted randomisation."),
                ("!fairness_debug",
                 "Explain the last !next_teams result."),
            ],
        ),
        (
            "🧪 Diagnostics / Maintenance",
            [
                ("!mr_cleanup_orphans",
                 "Clean orphaned rows in convenience tables."),
                ("!helpme",
                 "Show this command guide."),
            ],
        ),
    ]

    try:
        embed = discord.Embed(
            title="📌 Bot Command Guide",
            description="Arguments in [brackets] are optional; <angle brackets> are required.",
            color=discord.Color.gold(),
        )

        for title, items in sections:
            lines = [f"• **{cmd}** — {desc}" for cmd, desc in items]
            embed.add_field(name=title, value="\n".join(lines), inline=False)

        embed.set_footer(
            text="Tip: Run !auto_import_run after each session; add rivalsmeta to force the backup provider."
        )
        await ctx.send(embed=embed)

    except Exception:
        out = []
        out.append("BOT COMMAND GUIDE")
        out.append("Args: [optional] <required>")
        out.append("")
        for title, items in sections:
            out.append(title)
            for cmd, desc in items:
                out.append(f"  - {cmd}: {desc}")
            out.append("")
        out.append("Tip: Run !auto_import_run after each session; add rivalsmeta to force the backup provider.")
        await ctx.send("```" + "\n".join(out) + "```")


# ============================================================================================================
# ============================================================================================================
# Bot On Ready
# ============================================================================================================
# ============================================================================================================


@bot.event
async def on_ready():
    # Keep season/db initialisation here if you want a single clear startup point.
    try:
        ensure_season_exists(get_current_season_id())
        refresh_season_views()
        ensure_mr_api_tables()
        _register_persistent_nextteams_views()
        # Startup API calls are avoided by default. Run !refresh_heroes manually if the
        # hero cache needs a refresh, or set ENABLE_STARTUP_HERO_CACHE_REFRESH=true.
        if _env_flag("ENABLE_STARTUP_HERO_CACHE_REFRESH", False):
            try:
                await refresh_hero_cache(force=False)
            except Exception:
                pass
    except Exception as e:
        print("Startup init warning:", repr(e))

    # Background polling is disabled; use !auto_import_run manually after sessions.

    print(f"Logged in as {bot.user}")
    print("Marvel Rivals Stats Bot ready for action!")


# ------------------------------------------------------------------------------------------------------------
# Session Overview uses Brisbane-local game_stats.timestamp
# ------------------------------------------------------------------------------------------------------------

def _db_has_table(table_name: str) -> bool:
    """Return True if a table exists in the current SQLite DB."""
    try:
        c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table_name),),
        )
        return c.fetchone() is not None
    except Exception:
        return False


def _db_has_column(table_name: str, column_name: str) -> bool:
    """Return True if table has the given column (case-insensitive)."""
    try:
        c.execute(f"PRAGMA table_info({table_name})")
        cols = [str(r[1]).lower() for r in c.fetchall()]
        return str(column_name).lower() in cols
    except Exception:
        return False


# Preserve the original API date-grouping helper BEFORE we override its name.
# This prevents recursion if the manual-union function needs to fall back.
if "_get_games_grouped_by_date_api_original" not in globals():
    try:
        _get_games_grouped_by_date_api_original = _get_games_grouped_by_date_api
    except Exception:
        _get_games_grouped_by_date_api_original = None


def _get_games_grouped_by_date_manual_union(season_id: int):
    """
    Groups games by Brisbane-local date using game_stats.timestamp.
    Returns: ordered_dates, by_date dict[date_str] -> [game_label,...] chronological.
    """
    # If game_stats or timestamp isn't available, fall back safely to the original API grouping.
    if (not _db_has_table("game_stats")) or (not _db_has_column("game_stats", "timestamp")):
        try:
            fn = globals().get("_get_games_grouped_by_date_api_original")
            if callable(fn):
                return fn(season_id)
        except Exception:
            pass
        return [], {}

    c.execute(
        """
        SELECT game_label, MIN(timestamp) AS ts
        FROM game_stats
        WHERE season_id=?
        GROUP BY game_label
        ORDER BY ts ASC
        """,
        (int(season_id),),
    )
    per_game = c.fetchall()

    by_date = {}
    ordered_dates = []
    for label, ts in per_game:
        # expects ISO-like "YYYY-MM-DD HH:MM:SS" so [:10] yields YYYY-MM-DD
        d = (str(ts) if ts else "")[:10]
        if not d:
            continue
        if d not in by_date:
            by_date[d] = []
            ordered_dates.append(d)
        by_date[d].append(str(label))

    return ordered_dates, by_date


# Override the helper name used by session_overview
try:
    globals()["_get_games_grouped_by_date_api"] = _get_games_grouped_by_date_manual_union
except Exception:
    pass

# =====================================================================================
# Roster-first player pool for sessions / next_teams (works with 0 games)
# =====================================================================================

def _get_all_players_roster_first() -> dict[str, str]:
    """
    Returns { 'u<player_uid>': display_name }.

    Priority:
      1) Enabled roster (mr_roster)  -> works even if current season has 0 games
         - If roster name is blank, attempts to pull last known API name from mr_player_match (any season)
      2) Fallback to current-season mr_player_match (if roster is empty)
    """
    ensure_auto_import_tables()  # ensures mr_roster + mr_player_match exist

    out: dict[str, str] = {}

    # 1) Roster-first
    c.execute("""
        SELECT player_uid, COALESCE(player_name,'')
        FROM mr_roster
        WHERE enabled=1
        ORDER BY
          CASE WHEN TRIM(COALESCE(player_name,''))='' THEN 1 ELSE 0 END,
          LOWER(COALESCE(player_name,'')) ASC,
          player_uid ASC
    """)
    roster_rows = c.fetchall()

    if roster_rows:
        for uid, nm in roster_rows:
            if uid is None:
                continue
            try:
                uid_i = int(uid)
            except Exception:
                continue

            name = (nm or "").strip()

            # If roster name not provided, try to use last known API name (from any season)
            if not name:
                try:
                    c.execute("""
                        SELECT MAX(player)
                        FROM mr_player_match
                        WHERE player_uid=?
                          AND is_bot=0
                          AND player IS NOT NULL
                          AND TRIM(player) <> ''
                    """, (uid_i,))
                    row = c.fetchone()
                    if row and row[0]:
                        name = str(row[0]).strip()
                except Exception:
                    pass

            out[_pkey_from_uid(uid_i)] = name or f"UID_{uid_i}"

        return out

    # 2) Fallback: current-season API stats.
    season_id = int(get_current_season_id())
    c.execute("""
        SELECT
            pm.player_uid,
            MAX(pm.player) AS player
        FROM mr_player_match pm
        WHERE pm.season_id=?
          AND pm.is_bot=0
        GROUP BY pm.player_uid
        ORDER BY LOWER(MAX(pm.player)) ASC
    """, (season_id,))

    for uid, name in c.fetchall():
        if uid is None:
            continue
        out[_pkey_from_uid(int(uid))] = str(name or f"UID_{uid}")

    return out


# Force the bot to use roster-first player pool everywhere sessions/teams need it
try:
    globals()["_get_all_players"] = _get_all_players_roster_first
except Exception:
    pass

if __name__ == "__main__":
    # Replit-style keep-alive/web monitor is optional. On DigitalOcean, leave
    # ENABLE_WEB_MONITOR/ENABLE_KEEP_ALIVE unset and run the bot under systemd.
    if _env_flag("ENABLE_WEB_MONITOR", False):
        try:
            from web_monitor import run_web_monitor
            web_thread = threading.Thread(target=run_web_monitor, daemon=True)
            web_thread.start()
            print("Web monitor started on http://0.0.0.0:5000")
        except Exception as e:
            print("Web monitor disabled/failed:", repr(e))

    if _env_flag("ENABLE_KEEP_ALIVE", False):
        try:
            from keep_alive import keep_alive
            keep_alive()
        except Exception as e:
            print("Keep-alive disabled/failed:", repr(e))

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if bot_token:
        bot.run(bot_token)
    else:
        print("ERROR: DISCORD_BOT_TOKEN environment variable not found!")
        raise SystemExit(1)
