import os
import shutil
import sqlite3


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "enabled")


def prepare_sqlite_db_file(db_path: str, seed_path: str | None = None) -> None:
    """Create the database directory and seed a missing database when requested."""
    target_abs = os.path.abspath(db_path)
    target_dir = os.path.dirname(target_abs)
    if target_dir and not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    if os.path.exists(target_abs) or not seed_path:
        return

    seed_abs = os.path.abspath(seed_path)
    if seed_abs == target_abs:
        return

    if os.path.exists(seed_abs):
        shutil.copy2(seed_abs, target_abs)


def open_sqlite_connection(db_path: str):
    """Open SQLite with Jarvis's existing concurrency and durability settings."""
    connection = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return connection, connection.cursor()
