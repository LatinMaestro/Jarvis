def list_roster(cursor) -> list[tuple]:
    cursor.execute(
        "SELECT player_uid, player_name, enabled FROM mr_roster ORDER BY enabled DESC, player_uid ASC"
    )
    return cursor.fetchall()


def list_enabled_roster_uids(cursor) -> list[int]:
    cursor.execute("SELECT player_uid FROM mr_roster WHERE enabled=1 ORDER BY player_uid ASC")
    return [int(row[0]) for row in cursor.fetchall() if row and row[0] is not None]
