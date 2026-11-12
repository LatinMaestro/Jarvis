"""Season-scoped golf champion credits and reshuffle eligibility.

No fairness scores are changed here. All SQL values are parameterized.
"""
import sqlite3


def ensure_golf_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS golf_credits (
        guild_id INTEGER NOT NULL, season_id INTEGER NOT NULL,
        player_uid INTEGER NOT NULL, awarded INTEGER NOT NULL DEFAULT 0,
        spent INTEGER NOT NULL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, season_id, player_uid),
        CHECK (awarded >= 0 AND spent >= 0 AND spent <= awarded)
    )""")
    conn.commit()


def available_credits(conn, guild_id, season_id, player_uid):
    row = conn.execute(
        "SELECT awarded - spent FROM golf_credits WHERE guild_id=? AND season_id=? AND player_uid=?",
        (int(guild_id), int(season_id), int(player_uid)),
    ).fetchone()
    return int(row[0]) if row else 0


def credit_balances(conn, guild_id, season_id):
    rows = conn.execute(
        "SELECT player_uid, awarded, spent FROM golf_credits WHERE guild_id=? AND season_id=? ORDER BY player_uid",
        (int(guild_id), int(season_id)),
    ).fetchall()
    return {f"u{int(uid)}": (int(awarded) - int(spent)) for uid, awarded, spent in rows}


def eligible_champions(balances, active_players, previous_champion=None, minimum=8):
    """Only current lobby members with credits; exclude consecutive same champion."""
    active = set(active_players)
    if len(active) < minimum:
        return {}
    return {
        player: int(balances[player])
        for player in sorted(active)
        if int(balances.get(player, 0)) > 0 and player != previous_champion
    }


def valid_golf_choices(active_players, champion, teammate, opponent):
    active = set(active_players)
    return (
        len(active) >= 8
        and len({champion, teammate, opponent}) == 3
        and {champion, teammate, opponent}.issubset(active)
    )


def satisfies_golf_choices(team_a, team_b, champion, teammate, opponent):
    a, b = set(team_a), set(team_b)
    return ((champion in a and teammate in a and opponent in b)
            or (champion in b and teammate in b and opponent in a))


def adjust_credits(conn, guild_id, season_id, player_uid, delta):
    """Admin-controlled increment or decrement; never erase spent history."""
    delta = int(delta)
    if delta == 0:
        raise ValueError("Credit adjustment must not be zero.")
    ensure_golf_tables(conn)
    args = (int(guild_id), int(season_id), int(player_uid))
    conn.execute("INSERT OR IGNORE INTO golf_credits (guild_id, season_id, player_uid) VALUES (?,?,?)", args)
    cur = conn.execute("""UPDATE golf_credits SET awarded=awarded+?, updated_at=CURRENT_TIMESTAMP
        WHERE guild_id=? AND season_id=? AND player_uid=? AND awarded+? >= spent""",
        (delta, *args, delta))
    if cur.rowcount != 1:
        conn.rollback()
        raise ValueError("Cannot remove credits already spent or exceed available balance.")
    conn.commit()
    return available_credits(conn, *args)


def claim_credit(conn, guild_id, season_id, player_uid):
    """Conditional single-row debit, safe against concurrent claims."""
    cur = conn.execute("""UPDATE golf_credits SET spent=spent+1, updated_at=CURRENT_TIMESTAMP
        WHERE guild_id=? AND season_id=? AND player_uid=? AND awarded>spent""",
        (int(guild_id), int(season_id), int(player_uid)))
    conn.commit()
    return cur.rowcount == 1


def refund_credit(conn, guild_id, season_id, player_uid):
    """Compensate a failed team-message send after a successful claim."""
    conn.execute("""UPDATE golf_credits SET spent=spent-1, updated_at=CURRENT_TIMESTAMP
        WHERE guild_id=? AND season_id=? AND player_uid=? AND spent>0""",
        (int(guild_id), int(season_id), int(player_uid)))
    conn.commit()
