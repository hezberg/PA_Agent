"""端口占用检测与启动前清理（pa_agent.main）。"""
from __future__ import annotations

import socket
import threading
from unittest.mock import patch

from pa_agent import main as pa_main


def _bind_and_listen(port: int) -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen()
    return srv


def test_port_in_use_detects_active_listener() -> None:
    srv = _bind_and_listen(0)
    port = srv.getsockname()[1]
    try:
        assert pa_main._port_in_use("127.0.0.1", port) is True
    finally:
        srv.close()


def test_port_in_use_false_when_free() -> None:
    srv = _bind_and_listen(0)
    port = srv.getsockname()[1]
    srv.close()
    assert pa_main._port_in_use("127.0.0.1", port) is False


def test_looks_like_pa_agent_matches_own_instances() -> None:
    assert pa_main._looks_like_pa_agent("/usr/bin/python3 run.py")
    assert pa_main._looks_like_pa_agent("python -m pa_agent.main")
    assert pa_main._looks_like_pa_agent("python run.py --subprocess")
    assert pa_main._looks_like_pa_agent("pa-agent --port 8765")
    assert pa_main._looks_like_pa_agent("uvicorn pa_agent.server.app:create_app")
    assert not pa_main._looks_like_pa_agent("nginx: worker process")
    assert not pa_main._looks_like_pa_agent("")
    assert not pa_main._looks_like_pa_agent("python -c 'import http.server'")


def test_free_port_kills_stale_pa_agent_instance() -> None:
    killed: list[int] = []
    with (
        patch.object(pa_main, "_listeners_on_port", return_value=[(4321, "python run.py")]),
        patch.object(pa_main, "_kill_pid", side_effect=lambda pid: killed.append(pid)),
        patch.object(
            pa_main,
            "_port_in_use",
            side_effect=lambda *_: len(killed) == 0,  # kill 后视为端口已释放
        ),
    ):
        assert pa_main._free_port("127.0.0.1", 8765) is True
    assert killed == [4321]


def test_free_port_refuses_foreign_process() -> None:
    killed: list[int] = []
    with (
        patch.object(
            pa_main, "_listeners_on_port", return_value=[(999, "nginx: worker")]
        ),
        patch.object(pa_main, "_kill_pid", side_effect=lambda pid: killed.append(pid)),
    ):
        assert pa_main._free_port("127.0.0.1", 8765) is False
    assert killed == []


def test_free_port_false_when_lookup_finds_nothing() -> None:
    with patch.object(pa_main, "_listeners_on_port", return_value=[]):
        assert pa_main._free_port("127.0.0.1", 8765) is False


def test_main_exits_cleanly_when_port_cannot_be_freed() -> None:
    with (
        patch.object(pa_main, "_port_in_use", return_value=True),
        patch.object(pa_main, "_free_port", return_value=False),
    ):
        assert pa_main.main(["--no-browser"]) == 1
