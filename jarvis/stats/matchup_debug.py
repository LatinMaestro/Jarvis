"""Human-readable diagnostics for exact-lobby matchup diversity.

Formatting only: no changes to team generation or fairness calculations.
"""


def format_matchup_diversity_debug(info):
    if not isinstance(info, dict) or not info:
        return ["**Exact-lobby matchup history:** unavailable for this roll."]

    def number(name, default=0):
        return int(info.get(name, default) or 0)

    lines = ["**Exact-lobby matchup diversity:**"]
    if "selected_repeat_count" not in info:
        lines.append("History lookup or candidate selection diagnostics unavailable.")
        return lines

    lines.append(
        f"- Selected matchup already played: **{number('selected_repeat_count')}** time(s)"
    )
    lines.append(
        f"- Previously played count for fairness-best matchup: {number('best_repeat_count')}"
    )
    lines.append(
        f"- Candidate combinations scored: {number('evaluated')}"
    )
    lines.append(
        f"- Within fairness tolerance: {number('eligible')} "
        f"(unused: **{number('unused_eligible')}**)"
    )
    if "fairness_best" in info and "fairness_selected" in info:
        best = float(info["fairness_best"])
        selected = float(info["fairness_selected"])
        lines.append(
            f"- Total score: best {best:.3f}, selected {selected:.3f} "
            f"(difference +{selected - best:.3f}; lower is better)"
        )
    if "unused_scored" in info:
        lines.append(
            f"- Unused scored candidates overall: {number('unused_scored')}"
        )
    if info.get("best_unused_score") is not None and "fairness_best" in info:
        best_unused = float(info["best_unused_score"])
        best = float(info["fairness_best"])
        lines.append(
            f"- Best unused candidate: {best_unused:.3f} "
            f"(+{best_unused - best:.3f} from fairness best)"
        )
    if info.get("tolerance_enabled") is False:
        lines.append("- Fairness tolerance: disabled (unused eligible matchups take priority)")
    elif "tolerance_limit" in info:
        lines.append(
            f"- Fairness tolerance ceiling: {float(info['tolerance_limit']):.3f}"
        )
    if info.get("history_source_error"):
        lines.append(
            "- WARNING: Imported history lookup failed; only session history may be available."
        )
    if number("selected_repeat_count") > 0:
        if number("unused_eligible") > 0:
            lines.append("- Repetition reason: inspect selection/debug (unused acceptable alternatives existed).")
        elif number("unused_scored") > 0 and info.get("tolerance_enabled") is False:
            lines.append("- WARNING: unused scored alternatives existed despite a repeat; check history and selector.")
        elif number("unused_scored") > 0:
            lines.append("- Repetition reason: unused scored alternatives exceeded the fairness tolerance.")
        else:
            lines.append("- Repetition reason: no unused alternatives survived existing hard filters.")
    lines.append(
        "- Note: candidate counts exclude options rejected by existing hard fairness/role rules."
    )
    return lines
