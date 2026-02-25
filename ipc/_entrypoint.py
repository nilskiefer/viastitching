#!/usr/bin/env python3

import os
import sys
import traceback
from datetime import datetime


def _bootstrap_log_path():
    return os.path.join(os.path.dirname(__file__), "viastitching_bootstrap.log")


def _log_bootstrap_error(context, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_bootstrap_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{context}] {message}\n")
    except Exception:
        pass


def _show_bootstrap_error(message):
    try:
        import wx  # type: ignore

        wx.MessageBox(
            f"{message}\n\nBootstrap log:\n{_bootstrap_log_path()}",
            "ViaStitching",
            wx.OK | wx.ICON_ERROR,
        )
        return
    except Exception:
        pass
    print(f"ViaStitching: {message}", file=sys.stderr)
    print(f"Bootstrap log: {_bootstrap_log_path()}", file=sys.stderr)


def run(mode):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    try:
        from viastitching_ipc import run_mode
    except Exception:
        err = traceback.format_exc()
        _log_bootstrap_error("import", err)
        _show_bootstrap_error(
            "Unable to import ViaStitching IPC backend. Reinstall plugin and retry."
        )
        return 1

    try:
        result = run_mode(mode)
        return int(result) if result is not None else 0
    except Exception:
        err = traceback.format_exc()
        _log_bootstrap_error("run_mode", err)
        _show_bootstrap_error("ViaStitching IPC action failed before completion.")
        return 1
