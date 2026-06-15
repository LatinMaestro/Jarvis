#!/usr/bin/env python3
"""Shared safety helpers for Jarvis offline repository checks."""

import ast
import pathlib
import shutil
import sqlite3


def prepare_db_fixture(
    repo_root: pathlib.Path,
    db_arg: str,
    fixture_label: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Copy a database snapshot into .tmp and return (source, fixture)."""
    raw = str(db_arg).strip()
    normalized = raw.replace("\\", "/")
    if normalized == "/data" or normalized.startswith("/data/"):
        raise ValueError("refusing to access the live Railway /data database path")

    source = pathlib.Path(raw)
    if not source.is_absolute():
        source = repo_root / source
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"database snapshot not found: {source}")

    tmp_dir = (repo_root / ".tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fixture = tmp_dir / f"{fixture_label}-{source.name}"

    if fixture.resolve() != source:
        shutil.copy2(source, fixture)

    return source, fixture


def connect_read_only(db_path: pathlib.Path) -> sqlite3.Connection:
    """Open a SQLite database without permitting writes."""
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _literal_string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _literal_strings(node):
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    values = []
    for item in node.elts:
        value = _literal_string(item)
        if value is not None:
            values.append(value)
    return values


def detect_bot_commands(main_py: pathlib.Path) -> list[dict[str, object]]:
    """Return command metadata from @bot.command decorators using the AST."""
    source = main_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(main_py))
    commands = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "command"
                and isinstance(func.value, ast.Name)
                and func.value.id == "bot"
            ):
                continue

            command_name = node.name
            aliases = []
            for keyword in decorator.keywords:
                if keyword.arg == "name":
                    command_name = _literal_string(keyword.value) or command_name
                elif keyword.arg == "aliases":
                    aliases = _literal_strings(keyword.value)

            commands.append(
                {
                    "name": command_name,
                    "aliases": aliases,
                    "function": node.name,
                    "line": node.lineno,
                }
            )

    return sorted(commands, key=lambda item: int(item["line"]))
