import http.client
import json
import threading

import pytest

import server

TOKEN = "test-token-123"


class FakeHub:
    def __init__(self, port):
        self.cfg = {"port": port}
        self.calls = []

    def state(self):
        return {"ok": "state"}

    def stats(self, days):
        self.calls.append(("stats", days))
        return {"days": days}

    def launch(self, game_id):
        self.calls.append(("launch", game_id))
        if game_id == "nope":
            raise server.ApiError("игра не найдена", 404)
        return {"ok": True}

    def gamemode_action(self, action):
        raise RuntimeError("бум")

    def cover(self, game_id, kind):
        if game_id == "steam:730":
            return None, f"https://cdn.example/730/{kind}.jpg"
        return None, None


@pytest.fixture()
def srv():
    # порт 0 — система даст свободный; обработчик пересоздаём, когда порт известен
    httpd = server.make_server(FakeHub(0), 0, TOKEN)
    port = httpd.server_address[1]
    hub = FakeHub(port)
    httpd.RequestHandlerClass = server.make_handler(hub, port, TOKEN)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port, hub
    httpd.shutdown()
    httpd.server_close()


def request(port, method, path, body=None, headers=None, host=None, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        h["X-GameHub"] = token
    h.update(headers or {})
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    conn.request(method, path, body=data, headers=h)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, resp.getheader("Location"), raw


def test_get_state(srv):
    port, _ = srv
    code, _, raw = request(port, "GET", "/api/state")
    assert code == 200 and json.loads(raw) == {"ok": "state"}


def test_localhost_host_allowed(srv):
    port, _ = srv
    code, _, _ = request(port, "GET", "/api/state", host=f"localhost:{port}")
    assert code == 200


def test_foreign_host_rejected(srv):
    port, _ = srv
    code, _, _ = request(port, "GET", "/api/state", host="evil.com")
    assert code == 403


def test_query_days_clamped(srv):
    port, hub = srv
    request(port, "GET", "/api/stats?days=99999")
    request(port, "GET", "/api/stats?days=7")
    assert hub.calls == [("stats", 3650), ("stats", 7)]
    code, _, _ = request(port, "GET", "/api/stats?days=abc")
    assert code == 400


def test_post_requires_header(srv):
    port, hub = srv
    code, _, _ = request(port, "POST", "/api/launch", {"game_id": "steam:730"},
                         {"Content-Type": "application/json"}, token=None)
    assert code == 403 and hub.calls == []


def test_post_with_header(srv):
    port, hub = srv
    code, _, raw = request(port, "POST", "/api/launch", {"game_id": "steam:730"})
    assert code == 200 and json.loads(raw) == {"ok": True}
    assert hub.calls == [("launch", "steam:730")]


def test_post_api_error_and_missing_field(srv):
    port, _ = srv
    code, _, raw = request(port, "POST", "/api/launch", {"game_id": "nope"})
    assert code == 404 and "не найдена" in json.loads(raw)["error"]
    code, _, _ = request(port, "POST", "/api/launch", {"game_id": 5})
    assert code == 400


def test_post_bad_json(srv):
    port, _ = srv
    code, _, _ = request(port, "POST", "/api/launch", b"{not json")
    assert code == 400
    code, _, _ = request(port, "POST", "/api/launch", b"[1,2]")
    assert code == 400


def test_internal_error_is_500(srv):
    port, _ = srv
    code, _, raw = request(port, "POST", "/api/gamemode", {"action": "on"})
    assert code == 500 and "бум" not in json.loads(raw)["error"]   # текст исключения не уходит наружу


def test_static_no_traversal(srv):
    port, _ = srv
    code, _, _ = request(port, "GET", "/static/../server.py")
    assert code == 404
    code, _, _ = request(port, "GET", "/static/..%5Cserver.py")
    assert code == 404


def test_cover_redirect_and_404(srv):
    port, _ = srv
    code, loc, _ = request(port, "GET", "/cover/steam%3A730?kind=hero")
    assert code == 302 and loc == "https://cdn.example/730/hero.jpg"
    code, loc, _ = request(port, "GET", "/cover/steam%3A730?kind=<script>")
    assert code == 302 and loc == "https://cdn.example/730/portrait.jpg"
    code, _, _ = request(port, "GET", "/cover/epic%3Ax")
    assert code == 404


def test_unknown_route(srv):
    port, _ = srv
    assert request(port, "GET", "/api/nope")[0] == 404
    assert request(port, "POST", "/api/nope", {})[0] == 404


@pytest.mark.parametrize("token", [None, "", "wrong", "test-token-12", "\u00e9t\u00e9"])
def test_api_needs_token(srv, token):
    port, hub = srv
    assert request(port, "GET", "/api/state", token=token)[0] == 403
    assert request(port, "POST", "/api/launch", {"game_id": "steam:730"}, token=token)[0] == 403
    assert hub.calls == []


def test_static_and_cover_without_token(srv):
    port, _ = srv
    # картинки и страница не секрет; данные и действия — только с ключом
    assert request(port, "GET", "/cover/steam%3A730", token=None)[0] == 302