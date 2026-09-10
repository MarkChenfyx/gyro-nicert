"""Build a small code-only ZIP for updating an existing server deployment."""
from datetime import datetime
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("backend", "scripts", "frontend/dist")
FILES = ("pyproject.toml", "requirements-server.txt", "start-server.bat", ".env.example")


def main() -> None:
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build frontend first: npm --prefix frontend run build")
    output = ROOT / "outputs" / f"update-{datetime.now():%Y%m%d-%H%M%S}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        candidates.extend((ROOT / directory).rglob("*"))
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for path in sorted(set(candidates)):
            relative = path.relative_to(ROOT)
            if path.is_file() and "__pycache__" not in relative.parts and path.suffix != ".pyc":
                archive.write(path, "gyro_nicert/" + relative.as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed")
    print(output)
    print("Code-only update. Does not include or overwrite .env, .venv, storage, or historical data.")


if __name__ == "__main__":
    main()
