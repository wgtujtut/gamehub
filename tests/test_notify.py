import subprocess

import pytest

import notify

# данные «из интернета» с попыткой инъекции
TITLE = "Free! \"; Remove-Item C:\\x; $(calc) '<b>&"
BODY = "Body `whoami` & <script>'"


@pytest.fixture(autouse=True)
def reset_sink():
    notify.set_sink(None)
    yield
    notify.set_sink(None)


class FakePopen:
    calls = []

    def __init__(self, args, **kwargs):
        FakePopen.calls.append((args, kwargs))

    def wait(self, timeout=None):
        return 0


def test_sink_used(monkeypatch):
    got = []
    notify.set_sink(lambda t, b: got.append((t, b)))

    def no_popen(*a, **kw):
        raise AssertionError("при заданном sink PowerShell не нужен")

    monkeypatch.setattr(subprocess, "Popen", no_popen)
    notify.toast("Заголовок", "Текст")
    assert got == [("Заголовок", "Текст")]


def test_sink_error_swallowed():
    def bad(t, b):
        raise RuntimeError("tray died")

    notify.set_sink(bad)
    notify.toast("a", "b")  # не падает


def test_powershell_env_only(monkeypatch):
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    notify.toast(TITLE, BODY)

    assert len(FakePopen.calls) == 1
    args, kwargs = FakePopen.calls[0]
    assert args[0].lower().startswith("powershell")
    assert "-Command" in args
    joined = " ".join(args)
    # title/body не попали в командную строку
    assert TITLE not in joined and BODY not in joined
    assert "Remove-Item" not in joined and "whoami" not in joined
    # переданы через окружение
    assert kwargs["env"]["GH_TITLE"] == TITLE
    assert kwargs["env"]["GH_BODY"] == BODY
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    script = args[args.index("-Command") + 1]
    assert "$env:GH_TITLE" in script and "$env:GH_BODY" in script
    assert "[Security.SecurityElement]::Escape" in script


def test_popen_error_swallowed(monkeypatch):
    def boom(*a, **kw):
        raise OSError("no powershell")

    monkeypatch.setattr(subprocess, "Popen", boom)
    notify.toast("a", "b")  # не падает


def test_timeout_kills(monkeypatch):
    killed = []

    class SlowPopen(FakePopen):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("powershell", timeout)

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(subprocess, "Popen", SlowPopen)
    notify.toast("a", "b")
    assert killed == [True]
