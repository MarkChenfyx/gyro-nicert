"""Import a copied server live folder as a separate local archive."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.paths import LIVE_ROOT, RUNTIME_ROOT, stored_path
from backend.data_manager.database import APP_DB_PATH
from backend.services import live_service as service
from backend.repositories import live_repository as repository
from backend.common.time_utils import now_iso, timestamp_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    read = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    snapshots = sorted((folder / "snapshots").glob("*/cta_strategy_setting.json"))
    if not snapshots:
        raise ValueError("No snapshots found")
    source_id = "archive_" + timestamp_id() + "_" + uuid4().hex[:6]
    destination = LIVE_ROOT / source_id
    first = snapshots[0].parent
    settings = read(snapshots[0])
    bindings = service._bindings_from_settings(source_id, settings, service._class_inventory(first / "code"))
    backup = RUNTIME_ROOT / "backups" / ("before_live_import_" + timestamp_id() + ".sqlite")
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as original, sqlite3.connect(backup) as copy:
        original.backup(copy)
    shutil.copytree(folder, destination)
    with repository._connect() as db:
        db.execute("INSERT INTO live_sources VALUES (?,?,?,?,?,?,?,?)", (source_id, "服务器归档 " + folder.name, "archive", stored_path(destination / "snapshots" / first.name / "code"), "", first.name, len(bindings), now_iso()))
        for b in bindings:
            db.execute("INSERT INTO live_bindings VALUES (?,?,?,?,?,?,?,?,?,?)", (b["binding_id"], source_id, b["instance_name"], b["class_name"], b["module_path"], b["vt_symbol"], b["fixed_size"], json.dumps(b["parameters"]), b["config_hash"], now_iso()))
        for original in snapshots:
            day = original.parent.name
            path = destination / "snapshots" / day
            setting, state = read(path / "cta_strategy_setting.json"), read(path / "cta_strategy_data.json")
            db.execute("INSERT INTO live_snapshots VALUES (?,?,?,?,?,?,?)", (uuid4().hex, source_id, day, service._hash_json(setting), service._hash_json(state), service._stored_path(path), now_iso()))
        for summary_path in sorted((destination / "daily").glob("*/summary.json")):
            summary = read(summary_path)
            rows = read(summary_path.parent / "rows.json")
            assert isinstance(rows, list)
            db.execute("INSERT INTO live_daily_records VALUES (?,?,?,?,?,?,?)", (uuid4().hex, source_id, summary_path.parent.name, json.dumps(summary, ensure_ascii=False), service._stored_path(summary_path.parent), None, summary.get("completed_at") or now_iso()))
    detail = service.get_source_detail(source_id)
    print(json.dumps({"source_id": source_id, "snapshots": len(detail["snapshots"]), "records": len(detail["records"]), "summary": detail["latest"].get("summary"), "backup": str(backup)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
