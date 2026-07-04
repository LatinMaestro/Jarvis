TOP3_MORE_MIN_GAMES_FOR_LIFT = 3



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
