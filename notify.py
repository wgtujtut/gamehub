"""Уведомления Windows: через трей (sink) или тостом PowerShell."""
import logging
import os
import subprocess

log = logging.getLogger(__name__)

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# title/body приходят ТОЛЬКО из переменных окружения и экранируются для XML.
# В тексте скрипта нет двойных кавычек, чтобы не ломался разбор командной строки.
_SCRIPT = "; ".join([
    "$t = [Security.SecurityElement]::Escape($env:GH_TITLE)",
    "$b = [Security.SecurityElement]::Escape($env:GH_BODY)",
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null",
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null",
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument",
    "$xml.LoadXml('<toast><visual><binding template=''ToastGeneric''><text>' + $t + '</text><text>' + $b + '</text></binding></visual></toast>')",
    "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml",
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('" + APP_ID + "').Show($toast)",
])

_sink = None


def set_sink(fn) -> None:
    """fn(title, body) — например, Icon.notify из pystray. None — снова PowerShell."""
    global _sink
    _sink = fn


def toast(title: str, body: str) -> None:
    """Показать уведомление. Ошибки не пробрасывает."""
    if _sink is not None:
        try:
            _sink(title, body)
        except Exception:
            log.exception("уведомление через sink не удалось")
        return
    try:
        env = dict(os.environ, GH_TITLE=str(title), GH_BODY=str(body))
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _SCRIPT],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        log.exception("уведомление PowerShell не удалось")
