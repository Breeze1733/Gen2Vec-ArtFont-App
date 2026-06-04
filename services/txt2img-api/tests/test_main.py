"""Tests for app/main.py launcher resolution."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app import main
from app.main import (
    _COMFYUI_PORTABLE_INNER,
    _CPU_BAT,
    _ENV_COMFYUI_LAUNCHER_BAT,
    _ENV_COMFYUI_PORTABLE_ROOT,
    _GPU_BAT,
    _PORTABLE_OUTER_NAMES,
    _pick_comfyui_launcher_bat,
    _resolve_portable_root,
)


def _make_fake_bundle(root: Path, *, with_nvidia: bool = True, with_cpu: bool = True) -> Path:
    """Create a fake ComfyUI portable distribution under ``root``.

    Layout: ``<root>/ComfyUI_windows_portable/{run_nvidia_*.bat, run_cpu.bat}``
    Returns the inner directory.
    """
    inner = root / _COMFYUI_PORTABLE_INNER
    inner.mkdir(parents=True, exist_ok=True)
    if with_nvidia:
        (inner / _GPU_BAT).write_text("@echo off\n")
    if with_cpu:
        (inner / _CPU_BAT).write_text("@echo off\n")
    return inner


class TestResolvePortableRoot:
    def test_env_var_takes_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_root = tmp_path / "my-comfyui"
        env_root.mkdir()
        auto_root = tmp_path / "ComfyUI_windows_portable_nvidia"
        auto_root.mkdir()
        monkeypatch.setenv(_ENV_COMFYUI_PORTABLE_ROOT, str(env_root))
        with patch.object(main, "_get_executable_dir", return_value=tmp_path):
            result = _resolve_portable_root()
        assert result == env_root.resolve()

    def test_env_var_invalid_falls_through_to_auto(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_COMFYUI_PORTABLE_ROOT, str(tmp_path / "nonexistent"))
        auto_root = tmp_path / "ComfyUI_portable"  # 3rd in _PORTABLE_OUTER_NAMES
        auto_root.mkdir()
        with patch.object(main, "_get_executable_dir", return_value=tmp_path):
            result = _resolve_portable_root()
        assert result == auto_root.resolve()

    def test_auto_discovery_finds_first_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # All three names exist; should pick the first in _PORTABLE_OUTER_NAMES
        for name in _PORTABLE_OUTER_NAMES:
            (tmp_path / name).mkdir()
        monkeypatch.delenv(_ENV_COMFYUI_PORTABLE_ROOT, raising=False)
        with patch.object(main, "_get_executable_dir", return_value=tmp_path):
            result = _resolve_portable_root()
        assert result == (tmp_path / _PORTABLE_OUTER_NAMES[0]).resolve()

    def test_nothing_found_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_COMFYUI_PORTABLE_ROOT, raising=False)
        with patch.object(main, "_get_executable_dir", return_value=tmp_path):
            result = _resolve_portable_root()
        assert result is None


class TestPickComfyuiLauncherBat:
    def test_env_launcher_bat_takes_top_priority(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit = tmp_path / "my-runner.bat"
        explicit.write_text("@echo off\n")
        monkeypatch.setenv(_ENV_COMFYUI_LAUNCHER_BAT, str(explicit))
        # Even if COMFYUI_PORTABLE_ROOT and auto discovery would also resolve,
        # the explicit .bat should win.
        monkeypatch.setenv(_ENV_COMFYUI_PORTABLE_ROOT, str(tmp_path / "ignored"))
        result = _pick_comfyui_launcher_bat()
        assert result == explicit.resolve()

    def test_env_portable_root_used_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_COMFYUI_LAUNCHER_BAT, raising=False)
        root = tmp_path / "user-comfyui"
        _make_fake_bundle(root, with_nvidia=False, with_cpu=True)
        monkeypatch.setenv(_ENV_COMFYUI_PORTABLE_ROOT, str(root))
        # Force CPU branch by pretending no GPU
        with patch.object(main, "_has_nvidia_gpu", return_value=False):
            result = _pick_comfyui_launcher_bat()
        assert result == (root / _COMFYUI_PORTABLE_INNER / _CPU_BAT).resolve()

    def test_auto_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_COMFYUI_LAUNCHER_BAT, raising=False)
        monkeypatch.delenv(_ENV_COMFYUI_PORTABLE_ROOT, raising=False)
        root = tmp_path / "ComfyUI_windows_portable_nvidia"
        _make_fake_bundle(root, with_nvidia=False, with_cpu=True)
        with patch.object(main, "_get_executable_dir", return_value=tmp_path), \
             patch.object(main, "_has_nvidia_gpu", return_value=False):
            result = _pick_comfyui_launcher_bat()
        assert result == (root / _COMFYUI_PORTABLE_INNER / _CPU_BAT).resolve()

    def test_no_comfyui_found_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_COMFYUI_LAUNCHER_BAT, raising=False)
        monkeypatch.delenv(_ENV_COMFYUI_PORTABLE_ROOT, raising=False)
        with patch.object(main, "_get_executable_dir", return_value=tmp_path):
            with pytest.raises(FileNotFoundError) as exc_info:
                _pick_comfyui_launcher_bat()
        # Error message should hint at both options
        msg = str(exc_info.value)
        assert _ENV_COMFYUI_PORTABLE_ROOT in msg
        assert _PORTABLE_OUTER_NAMES[0] in msg


class TestStartComfyuiSilent:
    """_start_comfyui_background should write launcher output to a file
    (not DEVNULL) and skip spawning when ComfyUI is already up."""

    def test_spawns_proc_with_log_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stdout/stderr should be redirected to a log file."""
        from unittest.mock import MagicMock, mock_open, patch

        from app import main
        from app.main import _start_comfyui_background

        fake_bat = MagicMock()
        with patch.object(main, "_pick_comfyui_launcher_bat", return_value=fake_bat), \
             patch.object(main, "_is_port_open", return_value=False), \
             patch.object(main, "_get_executable_dir", return_value=tmp_path), \
             patch("builtins.open", mock_open()), \
             patch("app.main.subprocess.Popen") as mock_popen:
            main._comfyui_proc = None  # reset state
            _start_comfyui_background()
            time.sleep(0.3)
            assert mock_popen.called
            kwargs = mock_popen.call_args.kwargs
            # stdout/stderr should be a file handle, not DEVNULL
            assert kwargs["stdout"] is not subprocess.DEVNULL
            assert kwargs["stderr"] is not subprocess.DEVNULL

        # cleanup
        main._comfyui_proc = None

    def test_skips_spawn_when_port_already_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-flight: if 8188 is open, do nothing and don't set _comfyui_proc."""
        from unittest.mock import MagicMock, patch

        from app import main
        from app.main import _start_comfyui_background

        with patch.object(main, "_pick_comfyui_launcher_bat", return_value=MagicMock()), \
             patch.object(main, "_is_port_open", return_value=True), \
             patch("app.main.subprocess.Popen") as mock_popen:
            main._comfyui_proc = None
            _start_comfyui_background()
            time.sleep(0.3)
            mock_popen.assert_not_called()
            # Critical: must NOT set _comfyui_proc, so _stop_comfyui
            # doesn't kill someone else's process.
            assert main._comfyui_proc is None
