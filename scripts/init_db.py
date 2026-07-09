"""Initialize the local SQLite database."""

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config.settings import settings
from db.database import initialize_database


def main() -> None:
    """Create database tables from `db/schema.sql`."""
    initialize_database(settings.database_path, Path("db/schema.sql"))


if __name__ == "__main__":
    main()
