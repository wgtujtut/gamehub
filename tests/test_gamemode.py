import psutil

import gamemode
from gamemode import BALANCED, HIGH, ULTIMATE

RU_OUTPUT = """\
Существующие схемы управления питанием (* - активные)
-----------------------------------
GUID схемы питания: 381b4222-f694-41f0-9685-ff5bb260df2e  (Сбалансированная)
GUID схемы питания: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Высокая производительность)
GUID схемы питания: a1841308-3541-4fab-bc81-f71556f20b4a  (Экономия энергии)
GUID схемы питания: e9a42b02-d5df-448d-aa00-03f14749eb61  (Максимальная производительность) *
""".replace("\n", "\r\n")

EN_OUTPUT = """\
Existing Power Schemes (* Active)
-----------------------------------
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance)
Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)
"""

NAMES = {
    BALANCED: "Сбалансированная",
    HIGH: "Высокая производительность",
    ULTIMATE: "Максимальная производительность",
}


# --- parse_schemes / best_scheme ---

def test_parse_schemes_ru():
    res = gamemode.parse_schemes(RU_OUTPUT)
    assert res == [
        {"guid": BALANCED, "name": "Сбалансированная", "active": False},
        {"guid": HIGH, "name": "Высокая производительность", "active": False},
        {"guid": "a1841308-3541-4fab-bc81-f71556f20b4a", "name": "Экономия энергии", "active": False},
        {"guid": ULTIMATE, "name": "Максимальная производительность", "active": True},
    ]


def test_parse_schemes_en():
    res = gamemode.parse_schemes(EN_OUTPUT)
    assert [s["name"] for s in res] == ["Balanced", "High performance", "Power saver"]
    assert [s["active"] for s in res] == [True, False, False]
    assert res[0]["guid"] == BALANCED


def test_parse_schemes_empty():
    assert gamemode.parse_schemes("") == []


def test_best_scheme():
    all_ = gamemode.parse_schemes(RU_OUTPUT)
    assert gamemode.best_scheme(all_)["guid"] == ULTIMATE
    no_ultimate = [s for s in all_ if s["guid"] != ULTIMATE]
    assert gamemode.best_scheme(no_ultimate)["guid"] == HIGH
    only_balanced = [s for s in all_ if s["guid"] == BALANCED]
    assert gamemode.best_scheme(only_balanced) is None
    assert gamemode.best_scheme([]) is None


# --- kill_processes ---

class FakeProc:
    def __init__(self, pid, name, fail=False):
        self.info = {"pid": pid, "name": name}
        self.fail = fail
        self.terminated = False

    def terminate(self):
        if self.fail:
            raise psutil.AccessDenied(self.info["pid"])
        self.terminated = True


def test_kill_processes():
    procs = [
        FakeProc(1, "llama-server.exe"),
        FakeProc(2, "llama-server.exe"),
        FakeProc(3, "BIONIC.EXE"),
        FakeProc(4, "explorer.exe"),
        FakeProc(5, "python.exe"),
        FakeProc(6, "dnplayer.exe", fail=True),
        FakeProc(7, "notepad.exe"),
        FakeProc(8, "Ld9BoxHeadless"),
    ]
    names = ["llama-server", "bionic.exe", "explorer.exe", "python", "dnplayer", "ld9boxheadless.exe"]

    res = gamemode.kill_processes(names, iter_procs=lambda: procs)

    assert res == ["llama-server.exe", "BIONIC.EXE", "Ld9BoxHeadless"]
    assert procs[0].terminated and procs[1].terminated and procs[2].terminated
    assert procs[7].terminated
    # защищённые и чужие не тронуты
    assert not procs[3].terminated
    assert not procs[4].terminated
    assert not procs[6].terminated


def test_kill_processes_empty():
    procs = [FakeProc(1, "notepad.exe")]
    assert gamemode.kill_processes([], iter_procs=lambda: procs) == []
    assert not procs[0].terminated


# --- GameMode ---

class FakePower:
    def __init__(self, active, guids=(BALANCED, HIGH, ULTIMATE)):
        self.active = active
        self.guids = guids
        self.calls = []

    def list(self):
        return [{"guid": g, "name": NAMES[g], "active": g == self.active} for g in self.guids]

    def set(self, guid):
        self.calls.append(guid)
        self.active = guid
        return True


class FakeKill:
    def __init__(self, result=("llama-server.exe",)):
        self.result = list(result)
        self.calls = []

    def __call__(self, names):
        self.calls.append(list(names))
        return self.result


CFG = {"auto": True, "power_plan": True, "kill_on_start": False, "kill_list": ["llama-server"]}


def make_gm(power, kill=None):
    return gamemode.GameMode(list_fn=power.list, set_fn=power.set, kill_fn=kill or FakeKill())


def test_enter_and_exit():
    power = FakePower(BALANCED)
    gm = make_gm(power)

    res = gm.enter(CFG)

    assert res == {"scheme": "Максимальная производительность", "killed": []}
    assert power.calls == [ULTIMATE]
    assert gm.active is True
    assert gm.status() == {"active": True, "scheme": "Максимальная производительность",
                           "previous": "Сбалансированная"}

    # повторный enter ничего не делает
    gm.enter(CFG)
    assert power.calls == [ULTIMATE]

    gm.exit()
    assert power.calls == [ULTIMATE, BALANCED]
    assert gm.active is False
    assert gm.status() == {"active": False, "scheme": "Сбалансированная", "previous": None}


def test_enter_high_when_no_ultimate():
    power = FakePower(BALANCED, guids=(BALANCED, HIGH))
    gm = make_gm(power)
    assert gm.enter(CFG)["scheme"] == "Высокая производительность"
    assert power.calls == [HIGH]


def test_already_best_no_set():
    power = FakePower(ULTIMATE)
    gm = make_gm(power)
    gm.enter(CFG)
    assert power.calls == []
    gm.exit()
    assert power.calls == []
    assert gm.active is False


def test_power_plan_off():
    power = FakePower(BALANCED)
    gm = make_gm(power)
    res = gm.enter({**CFG, "power_plan": False})
    assert res["scheme"] is None
    assert power.calls == []
    gm.exit()
    assert power.calls == []


def test_kill_on_start():
    power = FakePower(ULTIMATE)
    kill = FakeKill()
    gm = make_gm(power, kill)
    res = gm.enter({**CFG, "kill_on_start": True})
    assert kill.calls == [["llama-server"]]
    assert res["killed"] == ["llama-server.exe"]


def test_no_kill_by_default():
    kill = FakeKill()
    gm = make_gm(FakePower(ULTIMATE), kill)
    assert gm.enter(CFG)["killed"] == []
    assert kill.calls == []


def test_kill_now():
    kill = FakeKill(["dnplayer.exe"])
    gm = make_gm(FakePower(BALANCED), kill)
    assert gm.kill_now(["dnplayer"]) == ["dnplayer.exe"]
    assert kill.calls == [["dnplayer"]]
    assert gm.active is False


def test_status_caches_powercfg():
    calls = []
    schemes = [{"guid": gamemode.BALANCED, "name": "Сбалансированная", "active": True},
               {"guid": gamemode.ULTIMATE, "name": "Максимальная", "active": False}]

    def list_fn():
        calls.append(1)
        return schemes

    gm = gamemode.GameMode(list_fn=list_fn, set_fn=lambda g: True, kill_fn=lambda n: [])
    gm.status()
    gm.status()
    assert len(calls) == 1
    gm.enter({"power_plan": True})
    n = len(calls)
    gm.status()
    assert len(calls) == n + 1   # после enter кэш сброшен


def test_parse_schemes_question_marks():
    text = ("???: e9a42b02-d5df-448d-aa00-03f14749eb61  (???????????? ??????????????????) *\r\n"
            "???: 11111111-2222-3333-4444-555555555555  (??? ?????)\r\n"
            "Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (My High)\r\n")
    s = gamemode.parse_schemes(text)
    assert s[0]["name"] == "Максимальная производительность" and s[0]["active"]
    assert s[1]["name"] == "Своя схема"
    assert s[2]["name"] == "My High"


def test_kill_never_self():
    procs = [FakeProc(1, "GameHub.exe"), FakeProc(2, "msedgewebview2.exe")]
    assert gamemode.kill_processes(["gamehub", "msedgewebview2"], iter_procs=lambda: procs) == []
    assert not procs[0].terminated and not procs[1].terminated
