"""直接运行此文件启动 PA Agent WebUI。

用法：
    python run.py

启动后自动在默认浏览器打开操作界面（默认 http://127.0.0.1:8765）。

注意：不要在 Spyder / Jupyter 里直接运行本文件——服务器会阻塞当前控制台。
在 Spyder 中运行时会自动转到独立进程。
"""
from __future__ import annotations

import os
import subprocess
import sys

# 确保 PA_Agent 目录在 sys.path 里（当从其他目录运行时也能找到包）
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
os.chdir(_here)


def _inside_ipython_kernel() -> bool:
    """True when executed inside Spyder/Jupyter IPython kernel (not a plain terminal)."""
    if "--subprocess" in sys.argv:
        return False
    if os.environ.get("IPYTHON_KERNEL_APP") or os.environ.get("SPYDER_ARGS"):
        return True
    try:
        from IPython import get_ipython

        shell = get_ipython()
    except Exception:
        return False
    if shell is None:
        return False
    if getattr(shell, "kernel", None) is not None:
        return True
    return shell.__class__.__name__ in ("ZMQInteractiveShell", "SpyderShell")


def _launch_detached_subprocess() -> None:
    """Start PA Agent in a separate process so the IDE console stays usable."""
    script = os.path.join(_here, "run.py")
    cmd = [sys.executable, script, "--subprocess"]
    kwargs: dict = {"cwd": _here, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(cmd, **kwargs)


def _print_embedded_console_help() -> None:
    msg = (
        "\n"
        "══════════════════════════════════════════════════════════════\n"
        "  PA Agent 是本地 Web 服务，直接在 Spyder/Jupyter 内核里运行会阻塞控制台。\n"
        "\n"
        "  已尝试在独立进程中启动服务。若浏览器未自动打开，请在终端执行：\n"
        f"      python \"{os.path.join(_here, 'run.py')}\"\n"
        "  然后访问 http://127.0.0.1:8765\n"
        "\n"
        "  崩溃排查可查看：logs/pa_agent.log 、 logs/crash.log\n"
        "══════════════════════════════════════════════════════════════\n"
    )
    print(msg, flush=True)


from pa_agent.main import main

if __name__ == "__main__":
    if _inside_ipython_kernel():
        _print_embedded_console_help()
        _launch_detached_subprocess()
        raise SystemExit(0)
    raise SystemExit(main())
