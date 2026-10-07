import pytest

import updater


def release(tag="v1.2.0", name="GameHub-Setup-1.2.0.exe", url=None, **extra):
    url = url or f"https://github.com/wgtujtut/gamehub/releases/download/{tag}/{name}"
    return {"tag_name": tag, "body": "что нового", "html_url": "https://github.com/wgtujtut/gamehub/releases/tag/" + tag,
            "assets": [{"name": "notes.txt", "browser_download_url": "https://github.com/x"},
                       {"name": name, "browser_download_url": url}], **extra}


def test_parse_version():
    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.parse_version("1.0") == (1, 0)
    assert updater.parse_version("beta") == ()
    assert updater.parse_version("") == ()


def test_is_newer():
    assert updater.is_newer("1.0.1", "1.0.0")
    assert updater.is_newer("1.10.0", "1.9.9")   # не строковое сравнение
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("0.9", "1.0.0")
    assert not updater.is_newer("мусор", "1.0.0")


def test_parse_release_ok():
    r = updater.parse_release(release())
    assert r["version"] == "1.2.0"
    assert r["url"].endswith("/GameHub-Setup-1.2.0.exe")
    assert r["notes"] == "что нового"


@pytest.mark.parametrize("data", [
    release(url="https://evil.com/GameHub-Setup-1.2.0.exe"),                 # чужой домен
    release(url="https://github.com/someone/gamehub/releases/download/v1/GameHub-Setup-1.2.0.exe"),  # чужой репозиторий
    release(name="virus.exe"),
    release(draft=True),
    release(prerelease=True),
    release(tag="latest"),
    {"message": "Not Found"},
    [],
])
def test_parse_release_rejects(data):
    assert updater.parse_release(data) is None


def test_download_rejects_foreign_url():
    with pytest.raises(ValueError):
        updater.download_and_run("https://evil.com/GameHub-Setup-1.0.0.exe")
    with pytest.raises(ValueError):
        updater.download_and_run("https://github.com/wgtujtut/gamehub/releases/download/v1/run.bat")
