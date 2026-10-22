"""在服务器上运行：把实盘相关数据打成一个压缩包，传到远程桌面挂载的本地硬盘（只读源）。

  双击项目根目录的 sync-to-local.bat，或 python scripts/sync_to_local.py
  本地解压：python scripts/sync_to_local.py --unpack（把 inbox 里的压缩包按时间顺序解压到 server_mirror）
默认目标：远程桌面挂载的本地硬盘上 gyro_nicert 项目的 storage/server_mirror/inbox（storage 不入库）。
也可用 --dest 或 .env 的 GYRO_SYNC_DEST 指定 server_mirror 目录。

跨境远程桌面延迟高，逐个文件复制每个文件要几十次网络往返；因此在服务器本地比对和打包，只传一个 zip。
服务器本地记录上次已打包文件的大小和修改时间（storage/runtime/sync_manifest.json），只打包有变化的文件；
传输成功后才更新记录。--full 忽略记录全部重传。SQLite 先在服务器本地用备份接口得到一致副本再打包。

同步内容：
- storage：app.sqlite、实盘调度状态、executor_v2/；live/ 下的快照配置与状态、每日跟踪结果（不含体积很大的 rows.json）、
  券商 DBF 归档；快照里的策略代码和模型只传最新一天。
- .vntrader：两个 CTA json；log/ 默认不传（每天约 80MB），排查问题时用 --log-days N 传最近 N 天。
- 券商 DBF 导出目录。连接配置（connect_*.json、vt_setting.json）不会被复制。
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.environment import env
from backend.core.paths import RUNTIME_ROOT, STORAGE_ROOT

VNTRADER_FILES = ("cta_strategy_setting.json", "cta_strategy_data.json")
SKIP_SUFFIXES = (".part", ".tmp", "-journal", "-wal", "-shm", ".lock")
MANIFEST = RUNTIME_ROOT / "sync_manifest.json"


def _long(path: Path) -> Path:
    """Windows 长路径前缀：实盘快照里的策略文件名很长，容易超过 260 字符。"""
    text = os.path.abspath(path)  # 长路径前缀下不会再规范化 “..” 和 “/”，这里先规范化
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)


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


def _plan(log_days: int) -> list[tuple[Path, str]]:
    """（源文件, 压缩包内路径）。包内路径即解压到 server_mirror 后的相对路径。"""
    items = [(STORAGE_ROOT / "db" / "app.sqlite", "storage/db/app.sqlite")]
    status = RUNTIME_ROOT / "live_scheduler_status.json"
    if status.is_file():
        items.append((status, f"storage/runtime/{status.name}"))
    live = STORAGE_ROOT / "live"
    items += [(p, "storage/live/" + p.relative_to(live).as_posix()) for p in _live_files(live)]
    executor = STORAGE_ROOT / "executor_v2"
    items += [(p, "storage/executor_v2/" + p.relative_to(executor).as_posix()) for p in _files(executor)]
    vntrader = Path(env("GYRO_LIVE_VNTRADER_DIR") or Path.home() / ".vntrader")
    items += [(vntrader / n, f"vntrader/{n}") for n in VNTRADER_FILES if (vntrader / n).is_file()]
    logs = sorted((p for p in (vntrader / "log").glob("*.log") if re.search(r"\d{8}", p.name)),
                  key=lambda p: re.search(r"\d{8}", p.name).group())[-log_days:] if log_days > 0 and (vntrader / "log").is_dir() else []
    items += [(p, f"vntrader/log/{p.name}") for p in logs]
    dbf = env("GYRO_LIVE_BROKER_DBF_DIR")
    if dbf:
        items += [(p, "broker_dbf/" + p.relative_to(dbf).as_posix()) for p in _files(Path(dbf), "*.dbf")]
    return [(s if s.suffix == ".sqlite" else _long(s), name) for s, name in items]


def _signature(source: Path) -> list[int]:
    stat = source.stat()
    return [stat.st_size, int(stat.st_mtime)]


def _pack(todo: list[tuple[Path, str]], archive: Path, scratch: Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for i, (source, name) in enumerate(todo, 1):
            if source.suffix == ".sqlite":  # 在服务器本地做一致副本，避免打包时数据库正在写入
                copy = scratch / "backup.sqlite"
                reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
                writer = sqlite3.connect(copy)
                try:
                    reader.backup(writer)
                finally:
                    writer.close(); reader.close()
                bundle.write(copy, name)
                copy.unlink()
            else:
                bundle.write(source, name)
            print(f"\r打包 {i}/{len(todo)}", end="", flush=True)
    print()


def _send(archive: Path, target: Path) -> None:
    """一次顺序写入远程盘：先写 .part，完成后改名，中断不会留下半个压缩包。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    total, moved = archive.stat().st_size, 0
    started = time.monotonic()
    with archive.open("rb") as src, temporary.open("wb") as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)
            moved += len(chunk)
            share = moved / total if total else 1
            print(f"\r[{'#' * int(share * 30):<30}] {share:4.0%}  {moved / 1e6:.1f}/{total / 1e6:.1f} MB  "
                  f"已用 {time.monotonic() - started:.0f} 秒", end="", flush=True)
    temporary.replace(target)
    print()


def unpack(mirror: Path) -> None:
    """本地运行：把 inbox 里的压缩包按时间顺序解压到 server_mirror，成功后删除压缩包。"""
    archives = sorted((mirror / "inbox").glob("sync_*.zip"))
    if not archives:
        print(f"没有待解压的同步包：{mirror / 'inbox'}")
    for archive in archives:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                target = _long(mirror / info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                stamp = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (stamp, stamp))
        archive.unlink()
        print(f"已解压 {archive.name}（{len(bundle.infolist())} 个文件）→ {mirror}")


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
        if found:  # 通常在 C 盘就找到；远程桌面访问不存在的盘要等超时，找到即停
            break
    if len(found) != 1:
        hint = "；".join(map(str, found)) or "没有找到"
        raise SystemExit(f"无法自动确定本地项目（{hint}）。请确认远程桌面已挂载本地硬盘，"
                         "或用 --dest / .env 的 GYRO_SYNC_DEST 指定目标目录")
    return found[0] / "storage" / "server_mirror"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=env("GYRO_SYNC_DEST"))
    parser.add_argument("--log-days", type=int, default=0, help="同步最近几天的 VeighNa 日志（默认不传；排查问题时再加，如 --log-days 3）")
    parser.add_argument("--full", action="store_true", help="忽略上次同步记录，全部重新打包")
    parser.add_argument("--unpack", action="store_true", help="在本地运行：解压 inbox 里的同步包")
    args = parser.parse_args()
    if args.unpack:
        unpack(Path(args.dest) if args.dest else STORAGE_ROOT / "server_mirror")
        return
    print("正在比对哪些文件有变化（服务器本地）……", flush=True)
    sent = {} if args.full or not MANIFEST.is_file() else json.loads(MANIFEST.read_text(encoding="utf-8"))
    plan = [(s, name, _signature(s)) for s, name in _plan(args.log_days)]
    todo = [(s, name) for s, name, sig in plan if sent.get(name) != sig]
    if not todo:
        print("没有变化，无需同步")
        return
    total = sum(s.stat().st_size for s, _ in todo)
    print(f"{len(todo)} 个文件有变化，原始大小 {total / 1e6:.1f} MB", flush=True)
    print("正在查找本地目录……", flush=True)
    dest = Path(args.dest) if args.dest else _find_local_mirror()
    if not dest.parent.exists():
        raise SystemExit(f"目标不可访问（远程桌面是否已挂载本地硬盘？）：{dest}")
    bundle = f"sync_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / bundle
        _pack(todo, archive, Path(scratch))
        print(f"压缩后 {archive.stat().st_size / 1e6:.1f} MB，正在传输到 {dest / 'inbox'}", flush=True)
        _send(archive, dest / "inbox" / bundle)
    changed = {name for _, name in todo}
    sent.update({name: sig for _, name, sig in plan if name in changed})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    print(f"同步完成：{len(todo)} 个文件 → {dest / 'inbox' / bundle}（本地用 --unpack 解压）")


if __name__ == "__main__":
    main()
