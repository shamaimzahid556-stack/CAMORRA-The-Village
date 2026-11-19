"""Shared test helpers. If FastAPI/pydantic are not installed, tiny stand-ins are installed so the
real game route functions in app.py can still be imported and called directly. With the real
packages installed (normal case on your machine) nothing is stubbed."""
import importlib
import inspect
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401
    REAL_FASTAPI = True
except ImportError:
    REAL_FASTAPI = False


def install_stubs():
    if REAL_FASTAPI or "fastapi" in sys.modules:
        return

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code, self.detail = status_code, detail

    class _Routes:
        def __init__(self):
            self.routes = {}

        def _reg(self, method):
            def deco(path, **kw):
                def wrap(fn):
                    self.routes[(method, path)] = fn
                    return fn
                return wrap
            return deco

        def __getattr__(self, name):
            if name in ("get", "post", "delete", "put"):
                return self._reg(name.upper())
            raise AttributeError(name)

    class FastAPI(_Routes):
        def __init__(self, **kw):
            super().__init__()
            self.middleware = []

        def mount(self, *a, **k): pass
        def include_router(self, r): self.routes.update(r.routes)
        def add_middleware(self, cls, **kw): self.middleware.append((cls, kw))

    class APIRouter(_Routes):
        pass

    class JSONResponse:
        def __init__(self, content, status_code=200, headers=None):
            self.content, self.status_code, self.headers = content, status_code, headers or {}

    class BaseModel:
        def __init__(self, **kw):
            for k in getattr(type(self), "__annotations__", {}):
                setattr(self, k, kw.get(k, getattr(type(self), k, None)))

    fa = types.ModuleType("fastapi"); fa.FastAPI, fa.HTTPException, fa.APIRouter = FastAPI, HTTPException, APIRouter
    fr = types.ModuleType("fastapi.responses"); fr.FileResponse = lambda p: ("file", str(p)); fr.JSONResponse = JSONResponse
    fs = types.ModuleType("fastapi.staticfiles"); fs.StaticFiles = lambda **k: None
    pd = types.ModuleType("pydantic"); pd.BaseModel = BaseModel; pd.Field = lambda default=None, *a, **k: default
    for n, m in (("fastapi", fa), ("fastapi.responses", fr), ("fastapi.staticfiles", fs), ("pydantic", pd)):
        sys.modules[n] = m


install_stubs()


def load_app():
    """Import a fresh copy of app.py (fresh game state, fresh chat runtime)."""
    for name in [n for n in sys.modules if n == "app"]:
        del sys.modules[name]
    return importlib.import_module("app")


class Game:
    """Drives the REAL route functions of app.py like the browser does, and feeds the chat
    TurnTracker exactly as the ASGI middleware would after each successful POST."""

    def __init__(self, names=None, mafia=1):
        self.app = load_app()
        self.names = names or ["Ali", "Sara", "Omar", "Hina", "Zain", "Maya"]
        self.chat = self.app.chat
        self.service = self.chat.service
        self.post(self.app.start_game, "/api/start",
                  self.app.StartGameRequest(total_players=len(self.names), player_names=self.names, mafia_count=mafia))

    @property
    def gs(self):
        return self.app.game_state

    def post(self, fn, path, *args):
        res = fn(*args)
        self.chat.tracker.observe(path, 200, self.app.game_state)
        return res

    def role_of(self, name):
        return next(p.role.name for p in self.gs.players if p.name == name)

    def reveal_current_role(self):
        cur = self.app.role_current()
        self.post(self.app.role_show, "/api/role/show", self.app.RolePlayerRequest(player_id=cur["player_id"]))
        return cur

    def finish_role_assignment(self):
        while self.gs.phase == "ROLE_ASSIGNMENT":
            cur = self.reveal_current_role()
            self.post(self.app.role_complete, "/api/role/complete", self.app.RolePlayerRequest(player_id=cur["player_id"]))

    def night_actor(self):
        return self.app.night_current()

    def ready(self):
        cur = self.app.night_current(preview=1)
        self.post(self.app.night_ready, "/api/night/ready", self.app.NightReadyRequest(player_id=cur["player_id"]))
        return self.app.night_current()      # private details are only released after I'M READY

    def do_night_action(self, pick=0):
        """Perform the current night actor's action (first legal target) and advance."""
        cur = self.night_actor()
        a = cur["player_id"]
        role = cur["role"]
        A = self.app
        if role == "Mafia":
            if cur.get("stage") == "SHORTLIST":
                ids = [t["id"] for t in cur["targets"]][:2]
                self.post(A.mafia_shortlist, "/api/night/mafia/shortlist", A.MafiaShortlistRequest(actor_id=a, candidate_ids=ids))
                cur = self.night_actor()
            self.post(A.mafia_vote, "/api/night/mafia/vote", A.MafiaVoteRequest(actor_id=a, target_id=cur["targets"][pick]["id"]))
        elif role == "Doctor":
            tg = [t["id"] for t in cur["targets"] if t["id"] != a]
            self.post(A.doctor_target, "/api/night/doctor", A.DoctorTargetRequest(actor_id=a, target_id=tg[pick]))
        elif role == "Detective":
            self.post(A.detective_target, "/api/night/detective", A.DetectiveTargetRequest(actor_id=a, target_id=cur["targets"][pick]["id"]))
        else:
            self.post(A.villager_activity, "/api/night/villager", A.VillagerActivityRequest(actor_id=a, activity=cur["activities"][0]))
        return role


def api_call(runtime, method, path, payload=None):
    """Call a chat route and return (status_code, json). Works with real FastAPI or the stubs."""
    if REAL_FASTAPI:
        import unittest
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception:                                  # httpx missing: pip install -r requirements-dev.txt
            raise unittest.SkipTest("install httpx (requirements-dev.txt) to run the HTTP-level tests")
        web = FastAPI()
        web.include_router(runtime.router)
        r = TestClient(web).request(method, path, json=payload)
        return r.status_code, r.json()
    handler = runtime.router.routes[(method, path)]
    params = list(inspect.signature(handler).parameters.values())
    args = []
    if params:
        model = params[0].annotation
        args.append(model(**(payload or {})) if inspect.isclass(model) else None)
    res = handler(*args)
    return res.status_code, res.content
