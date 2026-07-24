from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


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

    backend_command = [sys.executable, "-m", "uvicorn", "backend.main:app"]
    if not args.no_reload:
        backend_command.append("--reload")

    print("[3/3] 启动前后端…", flush=True)
    backend = start_process(backend_command, PROJECT_ROOT)
    frontend = start_process([node, str(vite_entry)], FRONTEND_ROOT)
    processes = [("后端", backend), ("前端", frontend)]

    print("\n服务已启动：", flush=True)
    print("  工作台  http://127.0.0.1:5173", flush=True)
    print("  API 文档 http://127.0.0.1:8000/docs", flush=True)
    print("按 Ctrl+C 可同时关闭前后端。\n", flush=True)

    try:
        if args.smoke_test:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if backend.poll() is not None or frontend.poll() is not None:
                    break
                if url_is_ready("http://127.0.0.1:8000/api/health") and url_is_ready("http://127.0.0.1:5173"):
                    print("启动检查通过，前后端均可访问。", flush=True)
                    return 0
                time.sleep(0.5)
            print("启动检查失败：20 秒内未能同时访问前后端。", file=sys.stderr)
            return 1

        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"{name}进程已退出（状态码 {exit_code}）。", file=sys.stderr)
                    return exit_code or 1
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
