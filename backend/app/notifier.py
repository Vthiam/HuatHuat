"""Desktop notification when a scan/check-sso run finds something worth a
lawyer's attention. macOS only (the dev/demo machine), via `osascript`.
Never raises -- a notification failure should never break the pipeline
that triggered it.
"""
import platform
import subprocess


def notify(title: str, message: str) -> bool:
    if platform.system() != "Darwin":
        print(f"[notify:noop:{platform.system()}] {title} - {message}")
        return False
    try:
        script = f"display notification {_osa_quote(message)} with title {_osa_quote(title)}"
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5)
        return True
    except Exception as exc:
        print(f"[notify:failed] {title} - {message} ({exc})")
        return False


def _osa_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
