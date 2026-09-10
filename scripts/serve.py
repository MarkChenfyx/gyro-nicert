"""Run the built workbench locally without a Node development server or hot reload."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("Frontend missing: run npm --prefix frontend ci and npm --prefix frontend run build first.")
    os.chdir(ROOT)
    subprocess.run([sys.executable, "scripts/init_db.py"], check=True)
    print(f"Workbench: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    subprocess.run([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.port)], check=True)


if __name__ == "__main__":
    main()
