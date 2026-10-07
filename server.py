"""HTTP-сервер панели: отдаёт web/ и JSON API. Вся логика — в объекте hub (app.Hub)."""
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import config

log = logging.getLogger("gamehub.server")

WEB_DIR = config.RES_DIR / "web"
MAX_BODY = 1_000_000


class ApiError(Exception):
    """Ошибка, которую надо показать в ответе как {"error": ...}."""

    def __init__(self, text, code=400):
        super().__init__(text)
        self.code = code


def _int_arg(query, name, default, lo, hi):
    try:
        value = int(query.get(name, [default])[0])
    except ValueError:
        raise ApiError(f"{name}: нужно число")
    return max(lo, min(hi, value))


def _need(body, key, kind: type = str):
    value = body.get(key)
    if not isinstance(value, kind):
        raise ApiError(f"нет поля {key}")
    return value


def make_handler(hub, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    get_routes = {
        "/api/state": lambda q: hub.state(),
        "/api/library": lambda q: hub.library(),
        "/api/stats": lambda q: hub.stats(_int_arg(q, "days", 30, 1, 3650)),
        "/api/deals": lambda q: hub.deals(),
        "/api/cleaner": lambda q: hub.cleaner(),
        "/api/ping": lambda q: hub.ping(_int_arg(q, "minutes", 30, 1, 60)),
        "/api/config": lambda q: hub.get_config(),
        "/api/update": lambda q: hub.update_info(),
    }
    post_routes = {
        "/api/library/rescan": lambda b: hub.rescan(),
        "/api/launch": lambda b: hub.launch(_need(b, "game_id")),
        "/api/open_folder": lambda b: hub.open_folder(_need(b, "game_id")),
        "/api/library/not_game": lambda b: hub.set_not_game(_need(b, "game_id"), _need(b, "value", bool)),
        "/api/deals/refresh": lambda b: hub.refresh_deals(),
        "/api/deals/claim": lambda b: hub.claim_deal(_need(b, "key"), _need(b, "claimed", bool)),
        "/api/cleaner/clean": lambda b: hub.clean(_need(b, "ids", list)),
        "/api/gamemode": lambda b: hub.gamemode_action(_need(b, "action")),
        "/api/config": lambda b: hub.update_config(b),
        "/api/open_url": lambda b: hub.open_url(_need(b, "url")),
        "/api/uninstall": lambda b: hub.uninstall(_need(b, "game_id")),
        "/api/window/show": lambda b: hub.show_window(),
        "/api/update/install": lambda b: hub.install_update(),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "GameHub"

        def log_message(self, format, *args):
            log.debug("%s - %s", self.address_string(), format % args)

        # --- ответы ---
        def _send(self, code, body: bytes, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def _file(self, path: Path, cache=0):
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            headers = {"Cache-Control": f"max-age={cache}" if cache else "no-cache"}
            self._send(200, path.read_bytes(), ctype, headers)

        def _host_ok(self):
            # защита от DNS rebinding: чужое имя хоста — отказ
            if self.headers.get("Host", "") in allowed_hosts:
                return True
            self._json({"error": "bad host"}, 403)
            return False

        def _run(self, fn, arg):
            try:
                self._json(fn(arg))
            except ApiError as e:
                self._json({"error": str(e)}, e.code)
            except Exception as e:
                log.exception("ошибка обработки %s", self.path)
                self._json({"error": f"внутренняя ошибка: {e}"}, 500)

        # --- GET ---
        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            path = url.path
            if path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html")
            if path.startswith("/static/"):
                name = unquote(path[len("/static/"):])
                file = (WEB_DIR / name).resolve()
                if file.is_file() and file.parent == WEB_DIR.resolve():
                    return self._file(file)
                return self._json({"error": "not found"}, 404)
            if path.startswith("/cover/"):
                return self._cover(unquote(path[len("/cover/"):]), parse_qs(url.query))
            fn = get_routes.get(path)
            if fn is None:
                return self._json({"error": "not found"}, 404)
            self._run(fn, parse_qs(url.query))

        def _cover(self, game_id, query):
            kind = query.get("kind", ["portrait"])[0]
            if kind not in ("portrait", "header", "hero"):
                kind = "portrait"
            local, remote = hub.cover(game_id, kind)
            if local:
                return self._file(local, cache=86400)
            if remote:
                self.send_response(302)
                self.send_header("Location", remote)
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._json({"error": "no cover"}, 404)

        # --- POST ---
        def do_POST(self):
            if not self._host_ok():
                return
            # свой заголовок: браузер не даст чужому сайту прислать его без CORS-разрешения
            if self.headers.get("X-GameHub") != "1":
                return self._json({"error": "forbidden"}, 403)
            fn = post_routes.get(urlparse(self.path).path)
            if fn is None:
                return self._json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._json({"error": "bad length"}, 413)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            if not isinstance(body, dict):
                return self._json({"error": "bad json"}, 400)
            self._run(fn, body)

    return Handler


def make_server(hub, port):
    """Создать сервер на 127.0.0.1. Порт занят — OSError."""
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(hub, port))
    server.daemon_threads = True
    return server
