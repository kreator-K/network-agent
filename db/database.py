"""SQLite database helpers for the network-agent data layer."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_CORE_INTENT_PATH = Path(__file__).resolve().parent.parent / "config" / "core_intent.json"


def connect(database_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection and enable foreign key enforcement."""
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(
    database_path: str | Path,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    core_intent_path: str | Path = DEFAULT_CORE_INTENT_PATH,
) -> None:
    """Initialize tables and seed `core_intent` from human-edited JSON."""
    schema = Path(schema_path).read_text(encoding="utf-8")
    with connect(database_path) as connection:
        connection.executescript(schema)
        seed_core_intent(connection, core_intent_path)


def seed_core_intent(
    connection: sqlite3.Connection,
    core_intent_path: str | Path = DEFAULT_CORE_INTENT_PATH,
) -> None:
    """Upsert core intent rules from `config/core_intent.json` into SQLite."""
    rules = _load_core_intent_rules(core_intent_path)
    updated_at = _utc_now()
    connection.executemany(
        """
        INSERT INTO core_intent (rule_key, rule_value, description, updated_at)
        VALUES (:rule_key, :rule_value, :description, :updated_at)
        ON CONFLICT(rule_key) DO UPDATE SET
            rule_value = excluded.rule_value,
            description = excluded.description,
            updated_at = excluded.updated_at
        """,
        (
            {
                "rule_key": rule["rule_key"],
                "rule_value": rule["rule_value"],
                "description": rule.get("description"),
                "updated_at": updated_at,
            }
            for rule in rules
        ),
    )


def _load_core_intent_rules(core_intent_path: str | Path) -> list[dict[str, str]]:
    raw_data = json.loads(Path(core_intent_path).read_text(encoding="utf-8"))
    raw_rules = raw_data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("core_intent.json must contain a list at key 'rules'.")
    return [_normalize_core_intent_rule(rule) for rule in raw_rules]


def _normalize_core_intent_rule(rule: dict[str, Any]) -> dict[str, str]:
    rule_key = rule.get("rule_key")
    if not isinstance(rule_key, str) or not rule_key:
        raise ValueError("Each core intent rule must include a non-empty rule_key.")

    rule_value = rule.get("rule_value", rule.get("value"))
    if not isinstance(rule_value, str):
        rule_value = json.dumps(rule_value)

    description = rule.get("description", rule.get("rule_text", ""))
    if not isinstance(description, str):
        description = str(description)

    return {
        "rule_key": rule_key,
        "rule_value": rule_value,
        "description": description,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fetch_all_rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: Iterable[Any] = (),
) -> list[sqlite3.Row]:
    """Fetch rows for data-layer tests and scripts."""
    return list(connection.execute(query, tuple(parameters)).fetchall())
