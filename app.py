from functools import wraps
from pathlib import Path
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from game.player import Player
from game.game_state import GameState
from game.role_manager import RoleManager
from game.action import NightAction
from security import BodyLimitMiddleware, SecurityHeadersMiddleware
from chatbot import config as chat_config
from chatbot.api import TurnTrackerMiddleware, build_chat  # CAMORRA AI Companion (additive, read-only)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MAX_NAME_LENGTH = 40          # same limit the setup form enforces in the browser
NO_CACHE = {"Cache-Control": "no-cache"}
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}

# One game runs at a time and every route that changes it takes this lock, so two requests that
# arrive together (double click, slow network) can never both act as the same player.
_game_lock = threading.RLock()


def locked(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _game_lock:
            return fn(*args, **kwargs)
    return wrapper


class LocalOnlyMiddleware:
    """The game has no accounts: whoever can reach it can act as any player. By default only the
    computer running it is served. Set CAMORRA_ALLOW_REMOTE=1 to deliberately allow other devices."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and os.environ.get("CAMORRA_ALLOW_REMOTE", "").strip() != "1":
            client = (scope.get("client") or ("",))[0]
            if client and client not in LOCAL_CLIENTS:
                body = b'{"detail":"This game only accepts connections from the computer it runs on."}'
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


app = FastAPI(title="Camorra — Phase 1")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
game_state = GameState()

# AI Companion: adds /api/ai/chat/* only. It reads the game state, it never changes it.
chat = build_chat(lambda: game_state)
app.include_router(chat.router)
app.add_middleware(TurnTrackerMiddleware, tracker=chat.tracker, get_state=lambda: game_state)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(LocalOnlyMiddleware)


class StartGameRequest(BaseModel):
    total_players: int = Field(..., ge=6, le=15)
    player_names: list[str]
    mafia_count: int = Field(..., ge=1, le=3)


class RolePlayerRequest(BaseModel):
    player_id: int


class NightReadyRequest(BaseModel):
    player_id: int


class MafiaShortlistRequest(BaseModel):
    actor_id: int
    candidate_ids: list[int]


class MafiaVoteRequest(BaseModel):
    actor_id: int
    target_id: int


class DoctorTargetRequest(BaseModel):
    actor_id: int
    target_id: int


class DetectiveTargetRequest(BaseModel):
    actor_id: int
    target_id: int


class VillagerActivityRequest(BaseModel):
    actor_id: int
    activity: str


class DayVoteRequest(BaseModel):
    voter_id: int
    target_id: int


def reset_game():
    global game_state
    game_state = GameState()


def get_player(player_id: int) -> Player:
    player = game_state.get_player(player_id)
    if player is None:
        raise HTTPException(404, "Player does not exist.")
    return player


def get_alive_player(player_id: int) -> Player:
    player = get_player(player_id)
    if not player.alive:
        raise HTTPException(400, "That player is no longer in the game.")
    return player


def role_name(player: Player) -> str:
    return player.role.name if player.role else "Unknown"


def public_player(player: Player):
    data = {
        "id": player.player_id,
        "name": player.name,
        "alive": bool(player.alive),
    }
    # Roles stay secret during play and are revealed only once the game ends.
    if game_state.game_over:
        data["role"] = role_name(player)
    return data


def public_players():
    return [public_player(player) for player in game_state.players]


def private_role_data(player: Player):
    data = {
        "id": player.player_id,
        "player_name": player.name,
        "role": role_name(player),
    }
    if player.is_mafia():
        data["mafia_partners"] = [
            {"id": partner.player_id, "name": partner.name}
            for partner in game_state.get_alive_mafia()
            if partner.player_id != player.player_id
        ]
    return data


def require_phase(*phases):
    if game_state.phase not in phases:
        raise HTTPException(
            400,
            f"This action is not available during {game_state.phase}."
        )


def require_current_night_actor(actor_id: int) -> Player:
    require_phase("NIGHT")
    actor = get_alive_player(actor_id)
    current = game_state.get_current_night_player()
    if current is None:
        raise HTTPException(400, "Night actions are already complete.")
    if current.player_id != actor_id:
        raise HTTPException(400, f"It is currently {current.name}'s night turn.")
    return actor


def validate_night_target(actor: Player, target_id: int) -> Player:
    target = get_alive_player(target_id)
    if actor.player_id == target.player_id and role_name(actor) == "Detective":
        raise HTTPException(400, "You cannot investigate yourself.")
    if actor.is_mafia() and target.is_mafia():
        raise HTTPException(400, "Mafia cannot choose another Mafia member.")
    return target


def mafia_turn_index(actor_id: int):
    mafia = game_state.get_alive_mafia()
    for index, player in enumerate(mafia):
        if player.player_id == actor_id:
            return index
    return None


def first_mafia_id():
    mafia = game_state.get_alive_mafia()
    return mafia[0].player_id if mafia else None


def mafia_previous_actions():
    result = []
    for entry in game_state.mafia_action_history:
        actor = game_state.get_player(entry["actor_id"])
        if actor is None:
            continue
        result.append({
            "actor_id": actor.player_id,
            "actor_name": actor.name,
            "shortlist": [
                {
                    "id": target_id,
                    "name": game_state.get_player(target_id).name,
                }
                for target_id in entry.get("shortlist_ids", [])
                if game_state.get_player(target_id) is not None
            ],
            "target": (
                {
                    "id": entry["target_id"],
                    "name": game_state.get_player(entry["target_id"]).name,
                }
                if entry.get("target_id") is not None
                and game_state.get_player(entry["target_id"]) is not None
                else None
            ),
        })
    return result


def doctor_self_save_available():
    return not game_state.doctor_self_save_used


def complete_night_if_finished():
    if game_state.get_current_night_player() is not None:
        return None

    game_state.resolve_night()

    # A Detective's Mafia discovery is resolved publicly only at morning.
    # The Detective's identity and innocent findings remain private.
    if game_state.detective_result == "MAFIA" and game_state.detective_target_id is not None:
        found = get_player(game_state.detective_target_id)
        game_state.detective_found_mafia_id = found.player_id
        if found.alive:
            found.kill()

    # Public record for the AI companion: exactly what the morning screen announces, nothing more.
    game_state.log_public({
        "type": "night_report", "night": game_state.night_number,
        "mafia_target": game_state.mafia_target_id,
        "doctor_choice": game_state.night_saved_player_id,
        "killed": game_state.night_killed_player_id,
        "detective_found_mafia": game_state.detective_found_mafia_id,
    })

    # The night is now complete. We still enter the morning result even if
    # that result ends the game immediately.
    winner = game_state.check_win()
    if not winner:
        game_state.start_day()

    return {
        "complete": True,
        "game_over": bool(winner),
        "winner": winner,
        "players": public_players(),
        "day_number": game_state.day_number,
    }


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)


@app.get("/api/state")
def state():
    return {
        "phase": game_state.phase,
        "game_over": game_state.game_over,
        "winner": game_state.winner,
        "players": public_players(),
        "day_number": game_state.day_number,
        "night_number": game_state.night_number,
    }


@app.post("/api/new-game")
@locked
def new_game():
    """NEW GAME button: discard the finished (or abandoned) match and return to a clean setup state.
    Reloading the page alone cannot do this, because the server deliberately keeps the game so that a refresh
    resumes it."""
    reset_game()
    chat.service.sessions.close_all()
    return {"success": True, "phase": game_state.phase}


@app.post("/api/start")
@locked
def start_game(request: StartGameRequest):
    # Validate EVERYTHING before touching the running game: a rejected request must not wipe it.
    if len(request.player_names) != request.total_players:
        raise HTTPException(422, "Enter a name for every player.")

    cleaned = [name.strip() for name in request.player_names]
    if any(not name for name in cleaned):
        raise HTTPException(422, "Every player must have a name.")
    if any(len(name) > MAX_NAME_LENGTH for name in cleaned):
        raise HTTPException(422, f"Player names must be {MAX_NAME_LENGTH} characters or fewer.")
    if len({name.casefold() for name in cleaned}) != len(cleaned):
        raise HTTPException(422, "Player names must be unique.")

    manager = RoleManager(request.total_players, request.mafia_count, 1, 1)
    try:
        roles = manager.create_role_list()
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    reset_game()

    for index, (name, role) in enumerate(zip(cleaned, roles), start=1):
        player = Player(index, name, True)
        player.assign_role(role)
        game_state.add_player(player)

    game_state.phase = "ROLE_ASSIGNMENT"
    game_state.role_reveal_index = 0

    first = game_state.players[0]
    return {
        "success": True,
        "phase": game_state.phase,
        "players": public_players(),
        "distribution": manager.get_distribution(),
        "current_player": {"id": first.player_id, "name": first.name},
    }


@app.get("/api/role/current")
def role_current():
    require_phase("ROLE_ASSIGNMENT")
    player = game_state.get_current_role_reveal_player()
    if player is None:
        raise HTTPException(400, "Role assignment is already complete.")
    return {
        "phase": game_state.phase,
        "player_id": player.player_id,
        "player_name": player.name,
        "revealed": False,
        "role": None,
    }


@app.post("/api/role/show")
@locked
def role_show(request: RolePlayerRequest):
    require_phase("ROLE_ASSIGNMENT")
    player = game_state.get_current_role_reveal_player()
    if player is None or player.player_id != request.player_id:
        raise HTTPException(400, "That player is not the current role-assignment player.")
    return {"revealed": True, **private_role_data(player)}


@app.post("/api/role/complete")
@locked
def role_complete(request: RolePlayerRequest):
    require_phase("ROLE_ASSIGNMENT")
    player = game_state.get_current_role_reveal_player()
    if player is None or player.player_id != request.player_id:
        raise HTTPException(400, "That player is not the current role-assignment player.")

    game_state.role_reveal_index += 1
    if game_state.role_reveal_index >= len(game_state.players):
        game_state.start_night()
        return {
            "complete": True,
            "next_phase": "NIGHT",
            "night_number": game_state.night_number,
        }

    next_player = game_state.get_current_role_reveal_player()
    return {
        "complete": False,
        "next_player": {"id": next_player.player_id, "name": next_player.name},
    }


@app.get("/api/night/current")
@locked
def night_current(preview: int = 0):
    require_phase("NIGHT")
    current = game_state.get_current_night_player()
    if current is None:
        raise HTTPException(400, "Night actions are already complete.")

    if preview:
        # The "pass the device" screen only needs to know WHO is next, never what they will do.
        return {
            "phase": "NIGHT",
            "night_number": game_state.night_number,
            "player_id": current.player_id,
            "player_name": current.name,
        }

    if game_state.night_ready_for != (game_state.night_number, current.player_id):
        # Private details (role, partners, previous Mafia actions) are released only after "I'M READY".
        raise HTTPException(403, "Press I'M READY first: the device must be with the player whose turn it is.")

    data = {
        "phase": "NIGHT",
        "night_number": game_state.night_number,
        "player_id": current.player_id,
        "player_name": current.name,
        "role": role_name(current),
        "players": [public_player(player) for player in game_state.get_alive_players()],
    }

    if current.is_mafia():
        alive_mafia = game_state.get_alive_mafia()
        multiple_mafia = len(alive_mafia) > 1
        first_mafia = first_mafia_id()
        is_first_mafia = current.player_id == first_mafia

        data["mafia_partners"] = [
            {"id": partner.player_id, "name": partner.name}
            for partner in alive_mafia
            if partner.player_id != current.player_id
        ]
        data["previous_actions"] = mafia_previous_actions()
        data["shared_shortlist"] = [
            public_player(get_player(player_id))
            for player_id in game_state.mafia_shortlist_ids
            if get_player(player_id) is not None and get_player(player_id).alive
        ]

        if multiple_mafia and not game_state.mafia_shortlist_ids and is_first_mafia:
            data["stage"] = "SHORTLIST"
            data["targets"] = [
                public_player(player)
                for player in game_state.get_alive_players()
                if not player.is_mafia()
            ]
            data["minimum_shortlist"] = 2
            data["maximum_shortlist"] = min(4, len(data["targets"]))
            data["instruction"] = "Choose 2–4 living non-Mafia players for the Mafia shortlist."
        else:
            data["stage"] = "ACTUAL_TARGET"
            targets = game_state.mafia_shortlist_ids if multiple_mafia else [
                player.player_id
                for player in game_state.get_alive_players()
                if not player.is_mafia()
            ]
            data["targets"] = [
                public_player(get_player(player_id))
                for player_id in targets
                if get_player(player_id) is not None and get_player(player_id).alive
            ]
            data["instruction"] = "Choose one player from the Mafia shortlist." if multiple_mafia else "Choose one living non-Mafia player to kill."

    elif role_name(current) == "Doctor":
        data["targets"] = [public_player(player) for player in game_state.get_alive_players()]
        data["self_save_available"] = doctor_self_save_available()
        data["instruction"] = "Choose one living player to protect."

    elif role_name(current) == "Detective":
        data["targets"] = [
            public_player(player)
            for player in game_state.get_alive_players()
            if player.player_id != current.player_id
        ]
        data["instruction"] = "Investigate one living player."

    else:
        data["activities"] = [
            "Study in your room",
            "Read quietly",
            "Write in your diary",
            "Look through the window",
            "Go to sleep",
        ]
        data["instruction"] = "Choose what you do inside your house tonight."

    return data


@app.post("/api/night/ready")
@locked
def night_ready(request: NightReadyRequest):
    require_current_night_actor(request.player_id)
    game_state.night_ready_for = (game_state.night_number, request.player_id)
    return {"ready": True, "player_id": request.player_id}


@app.post("/api/night/mafia/shortlist")
@locked
def mafia_shortlist(request: MafiaShortlistRequest):
    actor = require_current_night_actor(request.actor_id)
    if not actor.is_mafia():
        raise HTTPException(403, "Only Mafia can create the Mafia shortlist.")

    alive_mafia = game_state.get_alive_mafia()
    if len(alive_mafia) <= 1:
        raise HTTPException(400, "A shortlist is only used when more than one Mafia is alive.")
    if actor.player_id != first_mafia_id() or game_state.mafia_shortlist_ids:
        raise HTTPException(400, "Only the first living Mafia player creates the shared shortlist.")

    unique_ids = list(dict.fromkeys(request.candidate_ids))
    if not 2 <= len(unique_ids) <= min(4, len(game_state.get_alive_players()) - len(alive_mafia)):
        raise HTTPException(400, "Choose between 2 and 4 living non-Mafia players.")

    candidates = []
    for target_id in unique_ids:
        target = get_alive_player(target_id)
        if target.is_mafia():
            raise HTTPException(400, "The Mafia shortlist cannot contain Mafia members.")
        candidates.append(target)

    game_state.mafia_shortlist_ids = [target.player_id for target in candidates]
    game_state.mafia_shortlist_owner_id = actor.player_id
    game_state.record_night_action(
        NightAction(actor.player_id, "Mafia shortlist", target_ids=game_state.mafia_shortlist_ids)
    )
    game_state.mafia_action_history.append({
        "actor_id": actor.player_id,
        "shortlist_ids": list(game_state.mafia_shortlist_ids),
        "target_id": None,
    })
    return {
        "saved": True,
        "stage": "ACTUAL_TARGET",
        "shared_shortlist": [public_player(target) for target in candidates],
        "message": "Shortlist saved. Now choose one target from it.",
    }


@app.post("/api/night/mafia/vote")
@locked
def mafia_vote(request: MafiaVoteRequest):
    actor = require_current_night_actor(request.actor_id)
    if not actor.is_mafia():
        raise HTTPException(403, "Only Mafia can make a Mafia night choice.")

    target = validate_night_target(actor, request.target_id)
    alive_mafia = game_state.get_alive_mafia()

    if len(alive_mafia) > 1:
        if not game_state.mafia_shortlist_ids:
            raise HTTPException(400, "The shared Mafia shortlist has not been created yet.")
        if target.player_id not in game_state.mafia_shortlist_ids:
            raise HTTPException(400, "Choose a target from the shared Mafia shortlist.")

    game_state.mafia_votes[actor.player_id] = target.player_id
    game_state.record_night_action(NightAction(actor.player_id, "Mafia kill", target.player_id))

    # Update this Mafia's history entry, including their actual target.
    for entry in reversed(game_state.mafia_action_history):
        if entry["actor_id"] == actor.player_id and entry.get("target_id") is None:
            entry["target_id"] = target.player_id
            break
    else:
        game_state.mafia_action_history.append({
            "actor_id": actor.player_id,
            "shortlist_ids": list(game_state.mafia_shortlist_ids),
            "target_id": target.player_id,
        })

    game_state.advance_night_turn()
    result = complete_night_if_finished()
    if result:
        return result
    next_player = game_state.get_current_night_player()
    return {"complete": False, "next_player": {"id": next_player.player_id, "name": next_player.name}}


@app.post("/api/night/doctor")
@locked
def doctor_target(request: DoctorTargetRequest):
    actor = require_current_night_actor(request.actor_id)
    if role_name(actor) != "Doctor":
        raise HTTPException(403, "Only the Doctor can make this choice.")

    target = get_alive_player(request.target_id)
    if target.player_id == actor.player_id and game_state.doctor_self_save_used:
        raise HTTPException(400, "The Doctor has already used the one self-save.")
    if target.player_id == actor.player_id:
        game_state.doctor_self_save_used = True

    game_state.doctor_target_id = target.player_id
    game_state.record_night_action(NightAction(actor.player_id, "Doctor save", target.player_id))
    game_state.advance_night_turn()
    result = complete_night_if_finished()
    if result:
        return result
    next_player = game_state.get_current_night_player()
    return {"complete": False, "next_player": {"id": next_player.player_id, "name": next_player.name}}


@app.post("/api/night/detective")
@locked
def detective_target(request: DetectiveTargetRequest):
    actor = require_current_night_actor(request.actor_id)
    if role_name(actor) != "Detective":
        raise HTTPException(403, "Only the Detective can investigate.")

    target = validate_night_target(actor, request.target_id)
    game_state.detective_target_id = target.player_id
    game_state.detective_result = "MAFIA" if target.is_mafia() else "INNOCENT"
    game_state.record_night_action(NightAction(actor.player_id, "Detective investigate", target.player_id))
    private_result = game_state.detective_result
    game_state.advance_night_turn()
    result = complete_night_if_finished()
    return {
        "complete": bool(result),
        "private_result": private_result,
        **(result or {
            "next_player": {
                "id": game_state.get_current_night_player().player_id,
                "name": game_state.get_current_night_player().name,
            }
        }),
    }


@app.post("/api/night/villager")
@locked
def villager_activity(request: VillagerActivityRequest):
    actor = require_current_night_actor(request.actor_id)
    if role_name(actor) != "Villager":
        raise HTTPException(403, "Only a Villager can choose this activity.")

    allowed = {
        "Study in your room",
        "Read quietly",
        "Write in your diary",
        "Look through the window",
        "Go to sleep",
    }
    if request.activity not in allowed:
        raise HTTPException(400, "Choose one of the available activities.")

    action = NightAction(actor.player_id, "Night activity")
    action.resolve(request.activity)
    game_state.record_night_action(action)
    game_state.advance_night_turn()
    result = complete_night_if_finished()
    if result:
        return result
    next_player = game_state.get_current_night_player()
    return {"complete": False, "next_player": {"id": next_player.player_id, "name": next_player.name}}


@app.get("/api/night/morning")
@locked
def morning():
    if game_state.phase not in {"DISCUSSION", "GAME_OVER"} or not game_state.morning_ready:
        raise HTTPException(400, "Morning result is not ready.")

    killed = get_player(game_state.night_killed_player_id) if game_state.night_killed_player_id else None
    saved = get_player(game_state.night_saved_player_id) if game_state.night_saved_player_id else None
    found = get_player(game_state.detective_found_mafia_id) if game_state.detective_found_mafia_id else None

    detective_alive = bool(game_state.get_alive_detectives())
    return {
        "night_number": game_state.night_number,
        "mafia_target": (
            {
                "id": game_state.mafia_target_id,
                "name": get_player(game_state.mafia_target_id).name,
            }
            if game_state.mafia_target_id is not None
            else None
        ),
        "killed_player": {"id": killed.player_id, "name": killed.name} if killed else None,
        "saved_player": {"id": saved.player_id, "name": saved.name} if saved else None,
        "detective_found_mafia": {"id": found.player_id, "name": found.name} if found else None,
        "detective_working": found is None and detective_alive,
        "detective_out": found is None and not detective_alive,
        "players": public_players(),
        "game_over": game_state.game_over,
        "winner": game_state.winner,
    }


@app.post("/api/day/discussion-start")
@locked
def discussion_start():
    require_phase("DISCUSSION")
    if not game_state.discussion_active:
        game_state.discussion_started_at = time.time()
        game_state.discussion_active = True
    return {"success": True, "seconds": 180}


@app.get("/api/day/current")
@locked
def day_current(preview: int = 0):
    if game_state.phase not in {"DISCUSSION", "VOTING", "GAME_OVER"}:
        raise HTTPException(400, "Day voting is not active yet.")

    remaining = 0
    if game_state.phase == "DISCUSSION" and game_state.discussion_started_at:
        remaining = max(0, 180 - int(time.time() - game_state.discussion_started_at))

    current = game_state.get_current_voter() if game_state.phase == "VOTING" else None
    forbidden_target_ids = []
    if current and current.is_mafia() and not preview:
        forbidden_target_ids = [p.player_id for p in game_state.get_alive_mafia()]

    alive_total = len(game_state.get_alive_players())
    return {
        "phase": game_state.phase,
        "day_number": game_state.day_number,
        "voter_number": min(game_state.voting_turn_index + 1, alive_total),
        "voter_total": alive_total,
        "discussion_seconds_remaining": remaining,
        "discussion_active": game_state.discussion_active,
        "voting_complete": game_state.phase != "VOTING" or current is None,
        "voter": {"id": current.player_id, "name": current.name} if current else None,
        "forbidden_target_ids": forbidden_target_ids,
        "players": public_players(),
        "game_over": game_state.game_over,
        "winner": game_state.winner,
    }


@app.post("/api/day/start-voting")
@locked
def start_voting():
    require_phase("DISCUSSION")
    game_state.start_voting()
    return {"success": True, "phase": game_state.phase}


@app.post("/api/day/vote")
@locked
def day_vote(request: DayVoteRequest):
    require_phase("VOTING")
    voter = game_state.get_current_voter()
    if voter is None or voter.player_id != request.voter_id:
        raise HTTPException(400, "That is not the current voter.")
    if not voter.alive:
        raise HTTPException(400, "Dead players cannot vote.")

    target = get_alive_player(request.target_id)
    if target.player_id == voter.player_id:
        raise HTTPException(400, "You cannot vote for yourself.")
    if voter.is_mafia() and target.is_mafia():
        raise HTTPException(400, "Mafia cannot vote to eliminate a Mafia partner.")

    game_state.record_vote(voter.player_id, target.player_id)

    current = game_state.get_current_voter()
    if current is not None:
        return {
            "complete": False,
            "next_voter": {"id": current.player_id, "name": current.name},
        }

    eliminated_id = game_state.resolve_day_votes()
    eliminated = get_player(eliminated_id) if eliminated_id else None
    game_state.log_public({"type": "vote_result", "day": game_state.day_number,
                           "eliminated": eliminated_id, "tie": game_state.vote_tie})
    winner = game_state.check_win()

    result = {
        "complete": True,
        "game_over": bool(winner),
        "winner": winner,
        "eliminated_player": (
            {
                "id": eliminated.player_id,
                "name": eliminated.name,
                "role": role_name(eliminated),
            }
            if eliminated else None
        ),
        "vote_counts": game_state.last_vote_counts,
        "tie": game_state.vote_tie,
        "players": public_players(),
    }

    if winner:
        return result

    # Do NOT start the next night here. Stay on the ELIMINATION screen until
    # the players press BEGIN NEXT NIGHT, which calls /api/day/continue.
    game_state.phase = "ELIMINATION"
    result.update({
        "game_over": False,
        "next_phase": "ELIMINATION",
    })
    return result


@app.get("/api/day/elimination")
@locked
def day_elimination():
    """Re-shows the result of the last vote (used to resume the elimination screen after a reload)."""
    require_phase("ELIMINATION")
    eliminated = get_player(game_state.eliminated_player_id) if game_state.eliminated_player_id else None
    return {
        "eliminated_player": (
            {"id": eliminated.player_id, "name": eliminated.name, "role": role_name(eliminated)}
            if eliminated else None
        ),
        "tie": game_state.vote_tie,
        "game_over": False,
        "players": public_players(),
    }


@app.post("/api/day/continue")
@locked
def continue_after_day_vote():
    require_phase("ELIMINATION")
    game_state.start_night()
    return {
        "success": True,
        "phase": game_state.phase,
        "night_number": game_state.night_number,
        "players": public_players(),
    }


@app.get("/healthz")
def healthz():
    """Liveness: the process is up. Says nothing about any game."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: the files the game needs are present and the chatbot's data folder is writable. Reports no game
    state, no player information and no configuration values."""
    checks = {
        "static_files": (STATIC_DIR / "index.html").is_file(),
        "rulebook": (chat_config.KNOWLEDGE_DIR / "facts.json").is_file(),
        "data_dir_writable": _data_dir_writable(),
    }
    ok = all(checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503,
                        headers={"Cache-Control": "no-store"})


def _data_dir_writable():
    try:
        chat_config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = chat_config.DATA_DIR / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False
