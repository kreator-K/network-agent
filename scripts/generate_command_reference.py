"""Generate the Telegram command reference from the bot handler registry."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "telegram_bot" / "bot.py"
OUTPUT = ROOT / "docs" / "telegram_command_reference.md"


def registered_commands() -> list[str]:
    tree = ast.parse(BOT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "CommandHandler":
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            names.add(node.args[0].value)
    return sorted(names)


def render() -> str:
    lines = [
        "# Telegram Command Reference",
        "",
        "Generated from `telegram_bot/bot.py` `CommandHandler` registrations.",
        "Handlers validate input, call `NetworkOrchestrator`, and format safe responses.",
        "",
    ]
    lines.extend(f"- `/{name}`" for name in registered_commands())
    return "\n".join(lines) + "\n"


def main() -> int:
    OUTPUT.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
