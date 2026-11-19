"""Checks that game_knowledge/facts.json (and therefore the knowledge text) still matches the real
game engine and interface. Run after changing the game:

    python -m chatbot.verify_rules

Exit code 1 means the documentation is out of date and must be updated before release.
The game code is the single source of truth; this script only reads it.
"""
import json
import re
import sys
from dataclasses import dataclass

from game.game_state import GameState
from game.player import Player
from game.role_manager import RoleManager
from game import roles as roles_module

from .config import KNOWLEDGE_DIR, PROJECT_DIR


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _facts():
    f = json.loads((KNOWLEDGE_DIR / "facts.json").read_text(encoding="utf-8"))
    f.pop("_comment", None)
    return f


def _read(rel):
    return (PROJECT_DIR / rel).read_text(encoding="utf-8")


def _raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def _game(roles_by_name):
    gs = GameState()
    for i, (name, role) in enumerate(roles_by_name, 1):
        p = Player(i, name)
        p.assign_role(role)
        gs.add_player(p)
    return gs


def run_checks():
    f, out = _facts(), []

    def add(name, ok, detail=""):
        out.append(Check(name, bool(ok), detail))

    # roles and teams
    actual = {r.name: r.team for r in (roles_module.MAFIA, roles_module.DETECTIVE, roles_module.DOCTOR, roles_module.VILLAGER)}
    add("roles and teams", actual == f["roles"], f"engine={actual} docs={f['roles']}")
    add("only Detective, Doctor and Mafia have a night action",
        {r.name for r in (roles_module.MAFIA, roles_module.DETECTIVE, roles_module.DOCTOR, roles_module.VILLAGER) if r.night_action}
        == {"Mafia", "Detective", "Doctor"})

    # player and role-count limits (probe RoleManager)
    lo, hi = f["min_players"], f["max_players"]
    add("min players", not _raises(lambda: RoleManager(lo, 1).validate()) and _raises(lambda: RoleManager(lo - 1, 1).validate()))
    add("max players", not _raises(lambda: RoleManager(hi, 1).validate()) and _raises(lambda: RoleManager(hi + 1, 1).validate()))
    add("mafia range", not _raises(lambda: RoleManager(10, f["min_mafia"]).validate())
        and not _raises(lambda: RoleManager(10, f["max_mafia"]).validate())
        and _raises(lambda: RoleManager(10, f["min_mafia"] - 1).validate())
        and _raises(lambda: RoleManager(10, f["max_mafia"] + 1).validate()))
    add("one detective and one doctor", f["detective_count"] == 1 and f["doctor_count"] == 1
        and _raises(lambda: RoleManager(10, 1, 2, 1).validate()) and _raises(lambda: RoleManager(10, 1, 1, 2).validate()))
    dist = RoleManager(lo, f["max_mafia"]).get_distribution()
    add("minimum villagers", dist["Villager"] == f["min_villagers"], f"distribution={dist}")

    # win conditions (probe GameState.check_win)
    M, V, D, T = roles_module.MAFIA, roles_module.VILLAGER, roles_module.DOCTOR, roles_module.DETECTIVE
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    add("no winner while Mafia < non-Mafia", gs.check_win() is None)
    gs = _game([("a", M), ("b", V), ("c", D), ("d", T), ("e", V), ("f", V)])
    for p in gs.players[1:5]:          # leaves 1 Mafia and 1 non-Mafia alive
        p.kill()
    add("Mafia wins when Mafia >= non-Mafia", gs.check_win() == f["mafia_winner_label"] and gs.game_over, f"winner={gs.winner}")
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    gs.players[0].kill()
    add("Civilians win when no Mafia alive", gs.check_win() == f["civilians_winner_label"])

    # night resolution (probe resolve_night)
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    gs.mafia_votes = {1: 2}
    gs.doctor_target_id = None
    r = gs.resolve_night()
    add("unprotected target dies", r["killed_player_id"] == 2 and not gs.get_player(2).alive)
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    gs.mafia_votes = {1: 2}
    gs.doctor_target_id = 2
    r = gs.resolve_night()
    add("protected target survives", r["killed_player_id"] is None and gs.get_player(2).alive)
    add("Doctor self-save counter starts unused", GameState().doctor_self_save_used is False)

    # day votes (probe resolve_day_votes)
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    gs.day_votes = {1: 3, 2: 3, 3: 2}
    gs.resolve_day_votes()
    add("most votes is eliminated", gs.eliminated_player_id == 3 and not gs.vote_tie)
    gs = _game([("a", M), ("b", V), ("c", V), ("d", D), ("e", T), ("f", V)])
    gs.day_votes = {1: 3, 2: 4}
    gs.resolve_day_votes()
    add("tie is flagged and broken at random", gs.vote_tie and gs.eliminated_player_id in (3, 4))

    # numbers and lists written in app.py / game.js
    app_src, js_src, html_src = _read("app.py"), _read("static/game.js"), _read("static/index.html")
    secs = {int(x) for x in re.findall(r'"seconds":\s*(\d+)', app_src)} | {int(x) for x in re.findall(r"max\(0,\s*(\d+)\s*-\s*int", app_src)}
    secs |= {int(x) for x in re.findall(r"discussionRemaining\s*=\s*(\d+)", js_src)}
    add("discussion length", secs == {f["discussion_seconds"]}, f"found={sorted(secs)}")
    mx = {int(x) for x in re.findall(r"min\((\d+),\s*len\(data\[\"targets\"\]\)\)", app_src)} | \
         {int(x) for x in re.findall(r"<=\s*min\((\d+),\s*len\(game_state\.get_alive_players\(\)\)", app_src)}
    mn = {int(x) for x in re.findall(r'"minimum_shortlist"\]\s*=\s*(\d+)', app_src)}
    add("shortlist limits", mx == {f["shortlist_max"]} and mn == {f["shortlist_min"]}, f"min={mn} max={mx}")
    acts = re.findall(r'"([^"]+)"', re.search(r'data\["activities"\]\s*=\s*\[(.*?)\]', app_src, re.S).group(1))
    add("villager activities", acts == f["villager_activities"], f"found={acts}")
    labels_ok = [b for b in f["buttons"] if b.upper() not in (html_src + js_src).upper()]
    add("button labels exist in the interface", not labels_ok, f"missing={labels_ok}")
    add("Mafia cannot target Mafia / vote partner (messages present)",
        "Mafia cannot choose another Mafia member" in app_src and "Mafia cannot vote to eliminate a Mafia partner" in app_src)
    add("Detective cannot investigate self (message present)", "You cannot investigate yourself" in app_src)
    add("nobody can vote for themselves (message present)", "You cannot vote for yourself" in app_src)
    add("self-save is once per game (message present)", "already used the one self-save" in app_src)
    from . import styles
    labels = [v["label"] for v in styles.STYLES.values()]
    add("documented answer styles exist in the code", f["answer_styles"] == labels, f"docs={f['answer_styles']} code={labels}")
    add("default answer style exists", styles.DEFAULT in styles.STYLES)
    return out


def main():
    checks = run_checks()
    for c in checks:
        print(("PASS " if c.ok else "FAIL ") + c.name + (f"   [{c.detail}]" if not c.ok and c.detail else ""))
    bad = [c for c in checks if not c.ok]
    print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
