"""Manual curated dataset sync entrypoint."""

from __future__ import annotations

import argparse

from .curated_sync import CuratedDatasetSyncService
from .database import get_session_factory, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync curated reply examples into PostgreSQL.")
    parser.add_argument("--force", action="store_true", help="Run the exact sync even if the file hash matches.")
    args = parser.parse_args()

    init_db()
    service = CuratedDatasetSyncService(get_session_factory())
    result = service.sync(force=args.force)
    print(
        "curated_sync "
        f"skipped={str(result.skipped).lower()} "
        f"inserted={result.inserted} "
        f"updated={result.updated} "
        f"deleted={result.deleted} "
        f"unchanged={result.unchanged} "
        f"accepted_backfilled={result.accepted_backfilled} "
        f"example_count={result.example_count}"
    )


if __name__ == "__main__":
    main()
