import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import engine  # noqa: E402


BACKFILL_SQL = """
INSERT INTO meeting_projects (meeting_id, project_id)
SELECT meeting_id, project_id FROM tasks WHERE project_id IS NOT NULL
UNION
SELECT meeting_id, project_id FROM decisions WHERE project_id IS NOT NULL
UNION
SELECT meeting_id, project_id FROM risks WHERE project_id IS NOT NULL
ON CONFLICT (meeting_id, project_id) DO NOTHING
"""


async def main() -> None:
    async with engine.begin() as connection:
        result = await connection.execute(text(BACKFILL_SQL))
    print(f"Meeting-project relationships backfilled: {result.rowcount}")


if __name__ == "__main__":
    asyncio.run(main())
