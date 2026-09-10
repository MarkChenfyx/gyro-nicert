"""Build a clean server ZIP, preserving market data but excluding historical business records."""
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("backend", "scripts", "tests", "frontend/src", "frontend/dist",
               "storage/natural_language", "storage/strategies/manual")
FILES = ("README.md", "pyproject.toml", "requirements-server.txt", ".env.example",
         "start.bat", "start-server.bat", "frontend/package.json", "frontend/package-lock.json",
         "frontend/index.html", "frontend/tsconfig.json", "frontend/tsconfig.node.json",
         "frontend/vite.config.ts")


def main() -> None:
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build frontend first: npm --prefix frontend run build")
    output = ROOT / "outputs" / f"server-{datetime.now():%Y%m%d-%H%M%S}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gyro_package_") as temporary:
        market = ROOT / "storage/db/market_data.sqlite"
        copy = Path(temporary) / "market_data.sqlite"
        if market.is_file():
            source = sqlite3.connect(market.as_uri() + "?mode=ro", uri=True)
            destination = sqlite3.connect(copy)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            candidates = [ROOT / name for name in FILES]
            candidates += list((ROOT / "frontend").glob("tsconfig*.json"))
            for directory in DIRECTORIES:
                candidates.extend((ROOT / directory).rglob("*"))
            for path in sorted(set(candidates)):
                relative = path.relative_to(ROOT)
                if path.is_file() and "__pycache__" not in relative.parts and path.suffix != ".pyc":
                    archive.write(path, "gyro_nicert/" + relative.as_posix())
            if copy.is_file():
                archive.write(copy, "gyro_nicert/storage/db/market_data.sqlite")
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("ZIP integrity check failed")
    print(output)
    print("Includes built frontend and market DB. Excludes .env, historical app DB/runs/pool/live, venv and node_modules.")


if __name__ == "__main__":
    main()
