import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from storage.sqlite_repo import get_records_repo


def load_json_records(path: str) -> list:
    if not os.path.exists(path):
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
        if not content:
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("JSON root must be a list of records")
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate analysis_records.json to SQLite")
    parser.add_argument(
        "--json-path",
        default="analysis_records.json",
        help="Path to legacy analysis_records.json",
    )
    args = parser.parse_args()

    records = load_json_records(args.json_path)
    repo = get_records_repo()
    repo.upsert_daily_latest(records)
    print(f"✅ Migrated {len(records)} records into SQLite.")


if __name__ == "__main__":
    main()
