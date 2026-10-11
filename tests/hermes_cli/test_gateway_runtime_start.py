"""The unmanaged-spawn env never carries launch-only client flags to the shared daemon."""
import subprocess
import sys
import time

_LAUNCH_ONLY_ENV = (
    "HERMES_PROFILE",
    "HERMES_YOLO_MODE",
    "HERMES_ACCEPT_HOOKS",
    "HERMES_IGNORE_RULES",
    "HERMES_SAFE_MODE",
    "HERMES_IGNORE_USER_CONFIG",
)


def test_spawn_unmanaged_gateway_strips_launch_only_env(tmp_path, monkeypatch):
    """Launch-only approval/context/config flags ride the launching session, not the daemon.

    HERMES_ACCEPT_HOOKS is launch-only too: one client must not enable hook consent
    for all later surfaces.
    """
    from hermes_cli import gateway_runtime_start as grs

    captured = {}

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs.get("env", {}))

    monkeypatch.setattr(subprocess, "Popen", DummyPopen)
    if sys.platform == "win32":
        from hermes_cli import gateway_windows

        monkeypatch.setattr(
            gateway_windows,
            "windowless_gateway_restart_spec",
            lambda command: (command, None, {"HERMES_WINDOWLESS": "1"}),
        )
    for key in _LAUNCH_ONLY_ENV:
        monkeypatch.setenv(key, "1")
    home = tmp_path / "home"
    grs.spawn_unmanaged_gateway(home, deadline=time.monotonic() + 30)
    for key in _LAUNCH_ONLY_ENV:
        assert key not in captured, key
    assert captured["HERMES_GATEWAY_DETACHED"] == "1"
