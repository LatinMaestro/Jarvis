from collections import Counter, defaultdict

from jarvis.stats.profile_analytics import normalise_side as _profile_norm_side
from jarvis.stats.profile_analytics import role_bucket as _profile_role_bucket
from jarvis.stats.hero_roles import load_hero_cache_rows
from jarvis.stats.profiles import load_accuracy_rows, load_season_totals


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _kda(kills: float, deaths: float, assists: float) -> float:
    return (float(kills) + float(assists)) / max(1.0, float(deaths))


def _digits_only(value: str) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def has_column(cursor, table: str, column: str) -> bool:
    try:
        cursor.execute(f"PRAGMA table_info({table})")
        return any(str(row[1]).lower() == column.lower() for row in cursor.fetchall())
    except Exception:
        return False


def load_hero_roles(cursor) -> dict[int, str]:
    """
    Returns {hero_id_int: role_str} from hero_cache.hero_role.
    Safe if hero_cache missing or hero_role not populated.
    """
    if not has_column(cursor, "hero_cache", "hero_role"):
        return {}

    out: dict[int, str] = {}
    try:
        for hid, _hero_name, role in load_hero_cache_rows(cursor):
            if role is None or not str(role).strip():
                continue
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


def get_accuracy_by_player(cursor, season_id: int) -> dict[int, float]:
    """
    Weighted accuracy by seconds where session_hit_rate exists.
    """
    out: dict[int, float] = {}
    try:
        for uid, hit_sum, sec_sum in load_accuracy_rows(cursor, season_id):
            uid_i = _safe_int(uid)
            sec = float(_safe_float(sec_sum))
            if uid_i <= 0 or sec <= 0.0:
                continue
            out[uid_i] = float(_safe_float(hit_sum)) / sec
    except Exception:
        return {}
    return out


def get_season_totals(cursor, season_id: int, player_uid: int) -> dict:
    """
    Player season totals + per-game derived metrics.
    Includes FH/SK if columns exist.
    """
    fh_col = has_column(cursor, "mr_player_match", "final_hits")
    sk_col = has_column(cursor, "mr_player_match", "solo_kill")

    row = load_season_totals(cursor, season_id, player_uid, fh_col, sk_col)
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


def get_all_player_metrics(cursor, season_id: int, *, min_games: int = 5) -> dict[int, dict]:
    """
    Per-player baseline metrics for percentile calculations.
    Filters to humans with >= min_games.
    """
    fh_col = has_column(cursor, "mr_player_match", "final_hits")
    sk_col = has_column(cursor, "mr_player_match", "solo_kill")

    extra_cols = []
    extra_cols.append("SUM(COALESCE(final_hits,0)) as final_hits" if fh_col else "0 as final_hits")
    extra_cols.append("SUM(COALESCE(solo_kill,0)) as solo_kills" if sk_col else "0 as solo_kills")
    extra_sql = ",\n            ".join(extra_cols)

    cursor.execute(
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

    acc_map = get_accuracy_by_player(cursor, season_id)

    out: dict[int, dict] = {}
    for row in cursor.fetchall() or []:
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


def get_win_seq_by_import_time(cursor, season_id: int, player_uid: int) -> list[int]:
    """
    Uses match_imports.imported_at as match ordering.
    """
    cursor.execute(
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
    return [1 if _safe_int(r[0]) == 1 else 0 for r in cursor.fetchall()]


def get_momentum_last_n(cursor, season_id: int, player_uid: int, n: int = 10) -> dict:
    """
    Last-N win%, deaths/g, final-hits/g from match_imports ordering.
    """
    fh_col = has_column(cursor, "mr_player_match", "final_hits")
    sel_fh = "COALESCE(pm.final_hits,0)" if fh_col else "0"

    cursor.execute(
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

    rows = cursor.fetchall() or []
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


def get_hero_stats(cursor, season_id: int, player_uid: int) -> list[dict]:
    """
    Aggregated per-hero stats (time, games, win%, KDA, FH/G).
    """
    fh_col = has_column(cursor, "mr_hero_segments", "final_hits")
    sel_fh = "SUM(COALESCE(hs.final_hits,0))" if fh_col else "0"

    cursor.execute(
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
    for hid, sec, games, wins, k, d, a, acc, fh in cursor.fetchall() or []:
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


def get_role_mix_and_role_wr(
    cursor,
    season_id: int,
    player_uid: int,
    role_map: dict[int, str],
) -> tuple[dict[str, float], dict[str, dict]]:
    """
    Role seconds share + role winrate by PRIMARY hero per match (max seconds).
    """
    # Seconds share
    cursor.execute(
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
    for hid, sec in cursor.fetchall() or []:
        hi = _safe_int(hid)
        s = float(_safe_float(sec))
        total_sec += s
        rb = _profile_role_bucket(role_map.get(hi) or "")
        if rb in secs_by_role:
            secs_by_role[rb] += s

    share = {k: (v / total_sec) if total_sec > 0 else 0.0 for k, v in secs_by_role.items()}

    # Primary hero role per match -> role WR
    cursor.execute(
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
    for mid, hid, sec, is_win in cursor.fetchall() or []:
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


def get_chemistry(cursor, season_id: int, player_uid: int, *, min_games: int = 4) -> dict:
    """
    Best allies / worst pairings / under-used synergy (NO Δpp deltas).
    Uses camp + match_uid to identify allies.
    """
    cursor.execute(
        """
        SELECT match_uid, camp, is_win
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
          AND match_uid IS NOT NULL
    """,
        (int(season_id), int(player_uid)),
    )
    rows = cursor.fetchall() or []
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
        cursor.execute(
            f"""
            SELECT match_uid, player_uid, player, camp
            FROM mr_player_match
            WHERE season_id=?
              AND COALESCE(is_bot,0)=0
              AND match_uid IN ({q_marks})
        """,
            (int(season_id), *chunk),
        )
        for mid, uid, name, camp in cursor.fetchall() or []:
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


def get_enemy_bans(cursor, season_id: int, player_uid: int) -> dict:
    """
    Top enemy bans against player (requires camp + mr_ban_picks).
    """
    cursor.execute(
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
    for mid, camp in cursor.fetchall() or []:
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
        cursor.execute(
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
        for mid, bside, hid in cursor.fetchall() or []:
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


def get_teammate_hero_wr_lists(
    cursor,
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
    cursor.execute(
        """
        SELECT match_uid, camp, is_win
        FROM mr_player_match
        WHERE season_id=? AND player_uid=? AND COALESCE(is_bot,0)=0
          AND match_uid IS NOT NULL
        """,
        (int(season_id), int(player_uid)),
    )
    rows = cursor.fetchall() or []
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
        cursor.execute(
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

        for mid, uid, camp, hid, sec in cursor.fetchall() or []:
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
