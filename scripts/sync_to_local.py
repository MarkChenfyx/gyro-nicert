"""在服务器上运行：把实盘相关数据增量同步到远程桌面挂载的本地硬盘（只读源、只增不删）。

  双击项目根目录的 sync-to-local.bat，或 python scripts/sync_to_local.py
默认目标：远程桌面挂载的本地硬盘上 gyro_nicert 项目的 storage/server_mirror（storage 不入库）。
也可用 --dest 或 .env 的 GYRO_SYNC_DEST 指定。只复制大小或修改时间有变化的文件；SQLite 用备份接口得到一致副本。

同步内容（远程桌面传小文件很慢，只传分析需要的部分）：
- storage：app.sqlite、实盘调度状态、executor_v2/；live/ 下的快照配置与状态、每日跟踪结果（不含体积很大的 rows.json）、
  券商 DBF 归档；快照里的策略代码和模型只传最新一天。
- .vntrader：两个 CTA json；log/ 只传最近 --log-days 天，gzip 压缩后传输（日志多为重复的乱序 tick 提示，压缩率很高）。
- 券商 DBF 导出目录。连接配置（connect_*.json、vt_setting.json）不会被复制。
"""
import argparse
import gzip
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.environment import env
from backend.core.paths import RUNTIME_ROOT, STORAGE_ROOT

VNTRADER_FILES = ("cta_strategy_setting.json", "cta_strategy_data.json")
SKIP_SUFFIXES = (".part", ".tmp", "-journal", "-wal", "-shm", ".lock")


def _long(path: Path) -> Path:
    """Windows 长路径前缀：实盘快照里的策略文件名很长，加上目标目录容易超过 260 字符。"""
    text = os.path.abspath(path)  # 长路径前缀下不会再规范化 “..” 和 “/”，这里先规范化
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)


def _changed(source: Path, target: Path, kind: str) -> bool:
    if not target.is_file():
        return True
    a, b = source.stat(), target.stat()
    if kind == "gzip":  # 压缩后大小不同，只比修改时间
        return int(a.st_mtime) != int(b.st_mtime)
    return a.st_size != b.st_size or int(a.st_mtime) != int(b.st_mtime)


def _copy(source: Path, target: Path, kind: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    if kind == "sqlite":
        reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        writer = sqlite3.connect(temporary)
        try:
            reader.backup(writer)
        finally:
            writer.close(); reader.close()
    elif kind == "gzip":
        with source.open("rb") as src, gzip.open(temporary, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    else:
        shutil.copyfile(source, temporary)
    os.utime(temporary, (source.stat().st_atime, source.stat().st_mtime))
    temporary.replace(target)
    return target.stat().st_size


def _files(root: Path, pattern: str = "*"):
    if root.is_dir():
        for path in root.rglob(pattern):
            if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(SKIP_SUFFIXES):
                yield path


def _live_files(live: Path):
    """live/ 下除快照代码外全部传；每个实盘源只传最新一天快照的 code/。"""
    latest = {}
    for day in live.glob("*/snapshots/*"):
        if day.is_dir():
            latest[day.parent] = max(latest.get(day.parent, day), day, key=lambda p: p.name)
    for path in _files(live):
        parts = path.relative_to(live).parts
        if path.name == "rows.json":
            continue
        if "code" in parts and len(parts) > 3 and parts[1] == "snapshots":
            if live / parts[0] / "snapshots" / parts[2] != latest.get(live / parts[0] / "snapshots"):
                continue
        yield path


def _plan(dest: Path, log_days: int) -> list[tuple[Path, Path, str]]:
    items = [(STORAGE_ROOT / "db" / "app.sqlite", dest / "storage" / "db" / "app.sqlite", "sqlite")]
    status = RUNTIME_ROOT / "live_scheduler_status.json"
    if status.is_file():
        items.append((status, dest / "storage" / "runtime" / status.name, "copy"))
    live = STORAGE_ROOT / "live"
    items += [(p, dest / "storage" / "live" / p.relative_to(live), "copy") for p in _live_files(live)]
    executor = STORAGE_ROOT / "executor_v2"
    items += [(p, dest / "storage" / "executor_v2" / p.relative_to(executor),
               "sqlite" if p.suffix == ".sqlite" else "copy") for p in _files(executor)]
    vntrader = Path(env("GYRO_LIVE_VNTRADER_DIR") or Path.home() / ".vntrader")
    items += [(vntrader / n, dest / "vntrader" / n, "copy") for n in VNTRADER_FILES if (vntrader / n).is_file()]
    logs = sorted((p for p in (vntrader / "log").glob("*.log") if re.search(r"\d{8}", p.name)),
                  key=lambda p: re.search(r"\d{8}", p.name).group())[-log_days:] if (vntrader / "log").is_dir() else []
    items += [(p, dest / "vntrader" / "log" / (p.name + ".gz"), "gzip") for p in logs]
    dbf = env("GYRO_LIVE_BROKER_DBF_DIR")
    if dbf:
        items += [(p, dest / "broker_dbf" / p.relative_to(dbf), "copy") for p in _files(Path(dbf), "*.dbf")]
    return [(s, t, k) if k == "sqlite" else (_long(s), _long(t), k) for s, t, k in items]


def _find_local_mirror() -> Path:
    """在远程桌面挂载的本地硬盘（\\\\tsclient\\<盘符>）上找到本地的 gyro_nicert 项目，目标为其 storage/server_mirror。"""
    found = []
    for drive in "CDEFGH":
        root = Path(f"\\\\tsclient\\{drive}")
        try:
            if not root.is_dir():
                continue
            found += [p for p in root.glob("Users/*/Desktop/*/gyro_nicert") if (p / "storage").is_dir()]
        except OSError:
            continue
    if len(found) != 1:
        hint = "；".join(map(str, found)) or "没有找到"
        raise SystemExit(f"无法自动确定本地项目（{hint}）。请确认远程桌面已挂载本地硬盘，"
                         "或用 --dest / .env 的 GYRO_SYNC_DEST 指定目标目录")
    return found[0] / "storage" / "server_mirror"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=env("GYRO_SYNC_DEST"))
    parser.add_argument("--log-days", type=int, default=10, help="VeighNa 日志只同步最近多少天")
    args = parser.parse_args()
    print("正在查找本地目录……", flush=True)
    dest = Path(args.dest) if args.dest else _find_local_mirror()
    if not dest.parent.exists():
        raise SystemExit(f"目标不可访问（远程桌面是否已挂载本地硬盘？）：{dest}")
    print(f"目标：{dest}\n正在比对哪些文件需要更新……", flush=True)
    todo = [(s, t, k) for s, t, k in _plan(dest, args.log_days) if _changed(s, t, k)]
    total = sum(s.stat().st_size for s, _, _ in todo)
    print(f"需要传输 {len(todo)} 个文件，原始大小 {total / 1e6:.1f} MB", flush=True)
    done = moved = sent = 0
    started = last = time.monotonic()
    for source, target, kind in todo:
        sent += _copy(source, target, kind)
        done += 1
        moved += source.stat().st_size
        now = time.monotonic()
        if now - last >= 0.5 or done == len(todo):
            last = now
            share = moved / total if total else 1
            bar = "#" * int(share * 30)
            print(f"\r[{bar:<30}] {share:4.0%}  {done}/{len(todo)} 个文件  {moved / 1e6:.1f}/{total / 1e6:.1f} MB  "
                  f"已用 {now - started:.0f} 秒", end="", flush=True)
    print(f"\n同步完成：更新 {done} 个文件，实际传输 {sent / 1e6:.1f} MB → {dest}")


if __name__ == "__main__":
    main()
