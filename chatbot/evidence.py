"""The player-authorized evidence set: the ONLY view of the game that the advice engine and the
language model ever receive.

Why this exists
---------------
A reply can leak a secret without naming it ("you should investigate Sara" is a leak if the bot picked
Sara because it knows she is Mafia). So recommendations are never produced from the full game state.
Instead `build_evidence` (the single place in the chatbot that reads the game state for advice) copies
out a small, purpose-specific record containing only what the asking player is allowed to use:

  * PUBLIC facts every player has been shown: who is alive, what the morning and elimination screens
    announced, the roles the game itself revealed.
  * The asker's OWN facts, only after the game verified the device handover: their role, their own
    legal options for the decision they face, and (for Mafia) their own team, because the game shows
    Mafia players their partners and shortlist on their own screen.

Nothing about any other player's hidden role, secret choice or vote is ever copied into it. Everything
downstream (advice.py, the prompt, the validators) sees this object and nothing else, so the boundary is
enforced by construction on the server and not by asking a model to keep quiet.

Each item carries an id ("E1" ...) so every recommendation can state exactly which evidence it used.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Evidence:
    phase: str
    screen: str
    asker_name: object = None           # set only when the game verified who is holding the device
    role: object = None                 # the asker's OWN role, only when verified
    team: object = None
    facts: dict = field(default_factory=dict)
    alive: tuple = ()                   # public
    out: tuple = ()                     # public: names no longer in the game
    revealed: dict = field(default_factory=dict)   # public: name -> role the game itself revealed
    public_events: tuple = ()           # public: plain-language lines
    action: str = "none"                # kill | protect | investigate | shortlist | vote | none
    options: tuple = ()                 # legal choices for the asker's pending decision
    teammates: tuple = ()               # Mafia asker only: their own living partners
    shortlist: tuple = ()               # Mafia asker only: the shared shortlist shown on their screen
    items: tuple = ()                   # ((id, description), ...) what this evidence consists of
    turn_key: str = ""

    def item_ids(self):
        return tuple(i for i, _ in self.items)

    def all_names(self):
        return set(self.alive) | set(self.out)

    def render(self):
        """Plain-text block for the language model prompt."""
        lines = []
        for item_id, desc in self.items:
            lines.append(f"[{item_id}] {desc}")
        return "\n".join(lines) if lines else "(no game evidence is available)"


def _names(gs, ids):
    out = []
    for pid in ids:
        p = gs.get_player(pid)
        if p is not None:
            out.append(p)
    return out


def _public_events(gs):
    """Translate gs.public_log (filled only with events the game displayed to everyone)."""
    lines, revealed = [], {}
    for entry in getattr(gs, "public_log", []):
        if entry.get("type") == "night_report":
            n = entry.get("night")
            target = gs.get_player(entry["mafia_target"]) if entry.get("mafia_target") is not None else None
            killed = gs.get_player(entry["killed"]) if entry.get("killed") is not None else None
            guarded = gs.get_player(entry["doctor_choice"]) if entry.get("doctor_choice") is not None else None
            found = gs.get_player(entry["detective_found_mafia"]) if entry.get("detective_found_mafia") is not None else None
            if target is not None:
                lines.append(f"Night {n}: the morning report said {target.name} was targeted by the Mafia"
                             + (" and survived." if killed is None else "."))
            else:
                lines.append(f"Night {n}: the morning report said no Mafia kill was selected.")
            if killed is not None:
                lines.append(f"Night {n}: {killed.name} was eliminated during the night (the game does not reveal their role).")
            if guarded is not None:
                lines.append(f"Night {n}: the morning report said {guarded.name} was chosen by the Doctor for protection.")
            if found is not None:
                lines.append(f"Night {n}: the morning report said the Detective found that {found.name} is Mafia.")
                revealed[found.name] = "Mafia"
        elif entry.get("type") == "vote_result":
            d = entry.get("day")
            victim = gs.get_player(entry["eliminated"]) if entry.get("eliminated") is not None else None
            if victim is None:
                lines.append(f"Day {d}: nobody was eliminated by the vote.")
            else:
                role = victim.role.name if victim.role else "Unknown"
                lines.append(f"Day {d}: {victim.name} was voted out; the game revealed their role: {role}"
                             + (" (the vote was tied and the game chose randomly)." if entry.get("tie") else "."))
                revealed[victim.name] = role
    return tuple(lines), revealed


def build_evidence(gs, ctx):
    """Build the evidence set for the player the game engine says is asking (see privacy.build_context)."""
    alive_players = list(gs.get_alive_players())
    alive = tuple(p.name for p in alive_players)
    out = tuple(p.name for p in gs.players if not p.alive)
    events, revealed = _public_events(gs)

    items = []

    def add(desc):
        items.append((f"E{len(items) + 1}", desc))

    add("Players still in the game (public): " + (", ".join(alive) or "none") + ".")
    if out:
        add("Players already out of the game (public): " + ", ".join(out) + ".")
    if events:
        add("Public events the game has announced to everyone: " + " ".join(events))

    asker = gs.get_player(ctx.actor_id) if ctx.actor_id is not None else None
    voter = gs.get_player(ctx.voter_id) if ctx.voter_id is not None else None
    role = ctx.role if asker is not None else None
    team = ctx.team if asker is not None else None

    action, options, teammates, shortlist = "none", (), (), ()
    if asker is not None and ctx.phase == "NIGHT" and role is not None:
        add(f"The asker's own role (verified by the game): {role}, {team} team.")
        others = [p for p in alive_players if p.player_id != asker.player_id]
        if role == "Mafia":
            # The game shows a Mafia player their own living partners, so the asker may use them.
            partners = [p for p in alive_players if p.player_id != asker.player_id and p.is_mafia()]
            teammates = tuple(p.name for p in partners)
            mafia_ids = {p.player_id for p in partners} | {asker.player_id}
            if teammates:
                add("The asker's living Mafia partners (shown on their own screen): " + ", ".join(teammates) + ".")
            shortlist_players = [p for p in _names(gs, gs.mafia_shortlist_ids) if p.alive and p.player_id not in mafia_ids]
            if ctx.facts.get("stage") == "choose_from_shortlist" and shortlist_players:
                shortlist = tuple(p.name for p in shortlist_players)
                options = shortlist
                action = "kill"
                add("The shared Mafia shortlist the asker must choose from: " + ", ".join(shortlist) + ".")
            elif ctx.facts.get("stage") == "build_shortlist":
                options = tuple(p.name for p in alive_players if p.player_id not in mafia_ids)
                action = "shortlist"
                add("The asker must build a shortlist of "
                    f"2 to 4 living non-Mafia players. Legal choices: {', '.join(options)}.")
            else:
                options = tuple(p.name for p in alive_players if p.player_id not in mafia_ids)
                action = "kill"
                add("Legal kill targets for the asker (living players who are not Mafia): " + ", ".join(options) + ".")
        elif role == "Doctor":
            can_self = bool(ctx.facts.get("self_save_available"))
            options = tuple(p.name for p in alive_players if can_self or p.player_id != asker.player_id)
            action = "protect"
            add("Legal protection choices for the asker: " + ", ".join(options)
                + (" (the one self-save is still available)." if can_self else " (the self-save is already used)."))
        elif role == "Detective":
            options = tuple(p.name for p in others)
            action = "investigate"
            add("Legal investigation choices for the asker (everyone alive except themselves): " + ", ".join(options) + ".")
        else:
            add("The asker is a Villager: their night activity has no effect on the game.")
    elif asker is not None and role is not None:
        add(f"The asker's own role (verified by the game): {role}, {team} team.")
    if voter is not None and ctx.phase == "VOTING":
        action = "vote"
        options = tuple(p.name for p in alive_players if p.player_id != voter.player_id)
        add(f"The voting screen is showing {voter.name}'s turn. Players they could vote for (the screen shows the exact list): "
            + ", ".join(options) + ".")

    return Evidence(
        phase=ctx.phase, screen=ctx.screen,
        asker_name=asker.name if asker else (voter.name if voter else None),
        role=role, team=team, facts=dict(ctx.facts) if asker is not None else {},
        alive=alive, out=out, revealed=revealed, public_events=events,
        action=action, options=options, teammates=teammates, shortlist=shortlist,
        items=tuple(items), turn_key=ctx.turn_key,
    )
