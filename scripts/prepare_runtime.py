"""Create restricted persistent runtime directories for deployment."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings


def _path(value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def main() -> int:
    paths = {_path(value) for value in (settings.media_storage_path, settings.backup_path, settings.log_path, settings.runtime_state_path)}
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    database = _path(settings.database_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    database.parent.chmod(0o700)
    print(f"Prepared {len(paths)} restricted runtime directories and database parent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
