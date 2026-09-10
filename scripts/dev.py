from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import tokenize
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
BACKEND_ROOT = PROJECT_ROOT / "backend"


def command_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"找不到 {name}，请先安装并确保它已加入 PATH。")
    return path


def stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def start_process(command: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    kwargs: dict[str, object] = {"cwd": cwd}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同时启动 gyro_nicert 前端和后端开发服务器")
    parser.add_argument("--no-reload", action="store_true", help="关闭后端代码热重载")
    parser.add_argument("--skip-install", action="store_true", help="缺少 node_modules 时也不自动运行 npm install")
    parser.add_argument("--smoke-test", action="store_true", help="确认前后端可访问后立即关闭")
    return parser.parse_args()


def url_is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_service(
    name: str,
    process: subprocess.Popen[bytes],
    url: str,
    timeout_seconds: float = 20,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"{name}进程提前退出（状态码 {exit_code}）。")
        if url_is_ready(url):
            return
        time.sleep(0.2)
    raise RuntimeError(f"{name}在 {timeout_seconds:g} 秒内未能就绪：{url}")


def backend_source_snapshot() -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in BACKEND_ROOT.rglob("*.py"):
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(BACKEND_ROOT))] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def validate_backend_sources() -> None:
    for path in BACKEND_ROOT.rglob("*.py"):
        with tokenize.open(path) as source_file:
            source = source_file.read()
        compile(source, str(path), "exec")


def main() -> int:
    args = parse_args()
    node = command_path("node")

    print("[1/3] 初始化数据库…", flush=True)
    subprocess.run([sys.executable, "scripts/init_db.py"], cwd=PROJECT_ROOT, check=True)

    vite_entry = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_entry.exists():
        if args.skip_install:
            raise RuntimeError("前端依赖尚未安装，请先在 frontend 目录运行 npm install。")
        print("[2/3] 首次运行，正在安装前端依赖…", flush=True)
        npm = command_path("npm")
        subprocess.run([npm, "install"], cwd=FRONTEND_ROOT, check=True)
    else:
        print("[2/3] 前端依赖已就绪。", flush=True)

    # Uvicorn's Windows reloader broadcasts CTRL_C_EVENT and can terminate the
    # parent batch job.  Keep Uvicorn stable and let this supervisor restart
    # only the backend child when backend Python sources change.
    backend_command = [sys.executable, "-m", "uvicorn", "backend.main:app"]
    reload_enabled = not args.no_reload
    reload_snapshot = backend_source_snapshot() if reload_enabled else {}

    print("[3/3] 启动前后端…", flush=True)
    backend = start_process(backend_command, PROJECT_ROOT)
    processes = [("后端", backend)]

    try:
        wait_for_service("后端", backend, "http://127.0.0.1:8000/api/health")
        frontend = start_process([node, str(vite_entry)], FRONTEND_ROOT)
        processes.append(("前端", frontend))
        wait_for_service("前端", frontend, "http://127.0.0.1:5173")

        print("\n服务已启动：", flush=True)
        print("  工作台  http://127.0.0.1:5173", flush=True)
        print("  API 文档 http://127.0.0.1:8000/docs", flush=True)
        print("按 Ctrl+C 可同时关闭前后端。\n", flush=True)

        if args.smoke_test:
            if reload_enabled:
                print("正在检查后端自动重载…", flush=True)
                stop_process_tree(backend)
                backend = start_process(backend_command, PROJECT_ROOT)
                processes[0] = ("后端", backend)
                wait_for_service("后端", backend, "http://127.0.0.1:8000/api/health")
                print("后端自动重载检查通过，前端进程保持运行。", flush=True)
            print("启动检查通过，前后端均可访问。", flush=True)
            return 0

        while True:
            frontend_exit_code = frontend.poll()
            if frontend_exit_code is not None:
                print(f"前端进程已退出（状态码 {frontend_exit_code}）。", file=sys.stderr)
                return frontend_exit_code or 1

            if reload_enabled:
                current_snapshot = backend_source_snapshot()
                if current_snapshot != reload_snapshot:
                    reload_snapshot = current_snapshot
                    try:
                        validate_backend_sources()
                    except (OSError, SyntaxError) as exc:
                        print(f"后端代码校验失败，继续使用当前服务：{exc}", file=sys.stderr, flush=True)
                    else:
                        print("检测到后端代码变化，正在自动重载…", flush=True)
                        stop_process_tree(backend)
                        backend = start_process(backend_command, PROJECT_ROOT)
                        processes[0] = ("后端", backend)
                        wait_for_service("后端", backend, "http://127.0.0.1:8000/api/health")
                        reload_snapshot = backend_source_snapshot()
                        print("后端自动重载完成。", flush=True)

            backend_exit_code = backend.poll()
            if backend_exit_code is not None:
                print(f"后端进程已退出（状态码 {backend_exit_code}）。", file=sys.stderr)
                return backend_exit_code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在关闭服务…", flush=True)
        return 0
    finally:
        for _, process in reversed(processes):
            stop_process_tree(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
