"""在服务器上运行：把实盘相关数据增量同步到远程桌面挂载的本地硬盘（只读源、只增不删）。

  python scripts/sync_to_local.py --dest "\\\\tsclient\\C\\<本地目录>"
目标目录也可写在 .env 的 GYRO_SYNC_DEST。只复制大小或修改时间有变化的文件；SQLite 用备份接口得到一致副本。
同步内容：storage 下的 app.sqlite、live/、executor_v2/、实盘调度状态；.vntrader 下的 log/ 和两个 CTA json；券商 DBF。
.vntrader 里的连接配置（connect_*.json、vt_setting.json）不会被复制。
"""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.environment import env
from backend.core.paths import RUNTIME_ROOT, STORAGE_ROOT

VNTRADER_FILES = ("cta_strategy_setting.json", "cta_strategy_data.json")


def _long(path: Path) -> Path:
    """Windows 长路径前缀：实盘快照里的策略文件名很长，加上目标目录容易超过 260 字符。"""
    text = os.path.abspath(path)  # 长路径前缀下不会再规范化 “..” 和 “/”，这里先规范化
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)


def _changed(source: Path, target: Path) -> bool:
    if not target.is_file():
        return True
    a, b = source.stat(), target.stat()
    return a.st_size != b.st_size or int(a.st_mtime) != int(b.st_mtime)


def _copy(source: Path, target: Path, stats: dict) -> None:
    is_sqlite = source.suffix.lower() == ".sqlite"  # 数据库路径都很短，SQLite 不支持长路径前缀
    if not is_sqlite:
        source, target = _long(source), _long(target)
    if not _changed(source, target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    if is_sqlite:
        reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        writer = sqlite3.connect(temporary)
        try:
            reader.backup(writer)
        finally:
            writer.close(); reader.close()
        os.utime(temporary, (source.stat().st_atime, source.stat().st_mtime))
    else:
        shutil.copy2(source, temporary)
    temporary.replace(target)
    stats["files"] += 1
    stats["bytes"] += target.stat().st_size


def _tree(root: Path, target: Path, stats: dict, pattern: str = "*") -> None:
    if root.is_dir():
        for path in root.rglob(pattern):
            if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith((".part", ".tmp", "-journal", "-wal", "-shm", ".lock")):
                _copy(path, target / path.relative_to(root), stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=env("GYRO_SYNC_DEST"))
    args = parser.parse_args()
    if not args.dest:
        raise SystemExit("请用 --dest 或 .env 的 GYRO_SYNC_DEST 指定本地目录")
    dest = Path(args.dest)
    if not dest.parent.exists():
        raise SystemExit(f"目标不可访问（远程桌面是否已挂载本地硬盘？）：{dest}")
    stats = {"files": 0, "bytes": 0}
    _copy(STORAGE_ROOT / "db" / "app.sqlite", dest / "storage" / "db" / "app.sqlite", stats)
    for name in ("live", "executor_v2"):
        _tree(STORAGE_ROOT / name, dest / "storage" / name, stats)
    status = RUNTIME_ROOT / "live_scheduler_status.json"
    if status.is_file():
        _copy(status, dest / "storage" / "runtime" / status.name, stats)
    vntrader = Path(env("GYRO_LIVE_VNTRADER_DIR") or Path.home() / ".vntrader")
    _tree(vntrader / "log", dest / "vntrader" / "log", stats)
    for name in VNTRADER_FILES:
        if (vntrader / name).is_file():
            _copy(vntrader / name, dest / "vntrader" / name, stats)
    dbf = env("GYRO_LIVE_BROKER_DBF_DIR")
    if dbf:
        _tree(Path(dbf), dest / "broker_dbf", stats, "*.dbf")
    print(f"同步完成：更新 {stats['files']} 个文件，{stats['bytes'] / 1e6:.1f} MB → {dest}")


if __name__ == "__main__":
    main()
