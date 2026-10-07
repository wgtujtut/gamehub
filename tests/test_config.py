import json

import config


def test_load_without_file_returns_defaults_copy(tmp_path):
    cfg = config.load(tmp_path / "nope.json")
    assert cfg == config.DEFAULTS
    # изменение результата не портит DEFAULTS
    cfg["port"] = 1
    cfg["gamemode"]["kill_list"].append("x")
    cfg["ping"]["targets"][0]["host"] = "changed"
    assert config.DEFAULTS["port"] == 8790
    assert "x" not in config.DEFAULTS["gamemode"]["kill_list"]
    assert config.DEFAULTS["ping"]["targets"][0]["host"] == "1.1.1.1"


def test_load_partial_file_merges_nested(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "port": 9000,
        "gamemode": {"kill_on_start": True},
        "ping": {"targets": []},
    }), encoding="utf-8")
    cfg = config.load(p)
    assert cfg["port"] == 9000
    assert cfg["gamemode"]["kill_on_start"] is True
    assert cfg["gamemode"]["auto"] is True
    assert cfg["gamemode"]["kill_list"] == config.DEFAULTS["gamemode"]["kill_list"]
    assert cfg["ping"]["targets"] == []          # списки заменяются целиком
    assert cfg["ping"]["enabled"] is True
    assert cfg["deals"] == config.DEFAULTS["deals"]
    assert config.DEFAULTS["port"] == 8790


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "config.json"
    cfg = config.load(p)
    cfg["extra_games"] = [{"id": "custom:x", "name": "Тест", "dir": "D:\\games\\x", "launch": ""}]
    cfg["limits"]["daily_minutes"] = 120
    config.save(cfg, p)
    assert config.load(p) == cfg
    assert not (p.parent / "config.json.tmp").exists()
    assert "Тест" in p.read_text(encoding="utf-8")   # ensure_ascii=False


def test_deep_merge_returns_new_dict():
    base = {"a": {"b": 1, "c": [1]}, "d": 1, "e": {"x": 1}}
    over = {"a": {"b": 2}, "f": 3, "e": 5}
    result = config.deep_merge(base, over)
    assert result == {"a": {"b": 2, "c": [1]}, "d": 1, "e": 5, "f": 3}
    assert base == {"a": {"b": 1, "c": [1]}, "d": 1, "e": {"x": 1}}
    result["a"]["c"].append(2)
    assert base["a"]["c"] == [1]
