"""Application entry point for PA Agent — WebUI edition.

Starts the FastAPI backend with uvicorn and opens the UI in the default
browser.  The React frontend is served from ``web/dist`` when built; during
frontend development run ``npm run dev`` in ``web/`` instead (Vite proxies
``/api`` to this server).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

#: 判定为「PA Agent 自身进程」的命令行标记（端口被占时只清理自己的旧实例）。
_PA_AGENT_MARKERS = ("run.py", "pa_agent", "pa-agent", "uvicorn")


def _port_in_use(host: str, port: int) -> bool:
    """True 当 host:port 已有监听者（TIME_WAIT 旧连接不算占用）。"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _process_cmdline(pid: int) -> str:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return out.stdout.strip()
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _listeners_on_port(port: int) -> list[tuple[int, str]]:
    """Best-effort: 返回监听该端口的 [(pid, 命令行)]。"""
    pids: list[int] = []
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                    try:
                        pids.append(int(parts[4]))
                    except ValueError:
                        continue
        else:
            out = subprocess.run(
                ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            pids = [int(x) for x in out.split() if x.isdigit()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("port listener lookup failed: %s", exc)
    return [(pid, _process_cmdline(pid)) for pid in dict.fromkeys(pids)]


def _looks_like_pa_agent(cmdline: str) -> bool:
    low = cmdline.lower()
    return any(marker in low for marker in _PA_AGENT_MARKERS)


def _kill_pid(pid: int) -> None:
    """SIGTERM（Windows 用 taskkill），宽限 2s 后强制 SIGKILL。"""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
            return
        import signal

        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("终止进程 %s 失败: %s", pid, exc)


def _free_port(host: str, port: int) -> bool:
    """端口被占时清理：旧 PA Agent 实例直接终止；其他进程不碰并报错退出。

    Returns True 表示端口已可用，可继续启动。
    """
    listeners = _listeners_on_port(port)
    if not listeners:
        logger.error(
            "端口 %s 已被占用，但无法识别占用进程（权限或缺少 lsof）。"
            "请手动关闭，或用 --port 换一个端口启动。",
            port,
        )
        return False

    foreign = [(pid, cmd) for pid, cmd in listeners if not _looks_like_pa_agent(cmd)]
    for pid, cmd in foreign:
        logger.error(
            "端口 %s 被其他进程占用 pid=%s：%s —— 为安全起见不自动终止，"
            "请手动关闭该进程或用 --port 换端口。",
            port,
            pid,
            cmd or "(未知)",
        )
    if foreign:
        return False

    for pid, cmd in listeners:
        logger.info(
            "端口 %s 被旧 PA Agent 进程占用（pid=%s：%s），正在终止…",
            port,
            pid,
            cmd or "(未知)",
        )
        _kill_pid(pid)

    for _ in range(50):
        if not _port_in_use(host, port):
            logger.info("端口 %s 已释放，继续启动", port)
            return True
        time.sleep(0.1)
    logger.error("终止旧进程后端口 %s 仍被占用，请手动处理", port)
    return False


def _open_browser_later(url: str, delay_s: float = 1.2) -> None:
    def _open() -> None:
        time.sleep(delay_s)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            logger.debug("could not open browser for %s", url)

    threading.Thread(target=_open, name="webbrowser-opener", daemon=True).start()


def build_arg_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(prog="pa-agent", description="PA Agent WebUI")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default 8765)")
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open the browser automatically"
    )
    parser.add_argument("--reload", action="store_true", help="uvicorn auto-reload (dev)")
    return parser


def main(argv: list[str] | None = None) -> int:
    from pa_agent.util.crash_diagnostics import enable_crash_diagnostics, log_startup_diagnostics
    from pa_agent.util.logging import configure_logging

    enable_crash_diagnostics()
    configure_logging()
    log_startup_diagnostics()

    # 运维透视镜：kill -USR1 <pid> 向 stderr（logs/webui_stdout.log）转储全部线程栈。
    import faulthandler
    import signal

    try:
        faulthandler.register(signal.SIGUSR1)
    except (ImportError, OSError, RuntimeError, ValueError):  # pragma: no cover
        pass

    args = build_arg_parser().parse_args(argv)

    # 端口被占：先清理旧 PA Agent 实例；被其他进程占用则拒绝启动。
    if _port_in_use(args.host, args.port) and not _free_port(args.host, args.port):
        return 1

    logger.info("PA Agent WebUI starting on %s:%s", args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        _open_browser_later(url)

    import uvicorn

    # reload 只监听 pa_agent 包：logs/、records/ 等运行期写文件不应触发重启。
    reload_kwargs: dict[str, object] = {}
    if args.reload:
        reload_kwargs["reload_dirs"] = [str(Path(__file__).resolve().parent)]

    uvicorn.run(
        "pa_agent.server.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        log_level="info",
        reload=args.reload,
        # SSE 长连接会无限期挂起优雅关闭，导致 --reload / systemctl restart 卡死；
        # 超时后强制断开，前端 EventSource 会自动重连。
        timeout_graceful_shutdown=5,
        **reload_kwargs,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
