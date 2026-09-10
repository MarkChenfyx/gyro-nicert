"""Update an existing server checkout without touching local configuration or data."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_FILES = (ROOT / "requirements-server.txt", ROOT / "pyproject.toml")


def _contents() -> tuple[bytes, ...]:
    return tuple(path.read_bytes() if path.is_file() else b"" for path in DEPENDENCY_FILES)


def _run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    if not (ROOT / ".git").is_dir():
        raise SystemExit("当前目录不是 Git 工作区，请先完成服务器首次 Git 部署。")
    before = _contents()
    _run("git", "pull", "--ff-only")
    if before != _contents():
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise SystemExit("未找到 .venv，请先完成服务器首次安装。")
        _run(str(python), "-m", "pip", "install", "-r", "requirements-server.txt")
        _run(str(python), "-m", "pip", "install", "-e", ".")
    print("更新完成。现在可以运行 start-server.bat。")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode or 1)
