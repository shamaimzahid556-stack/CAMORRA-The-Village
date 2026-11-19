"""Constraint Satisfaction Problems (AI subject: CSP).

A CSP has three parts:
  * variables    the things to decide        (each player's role, each phase's time slot)
  * domains      the allowed values          (Mafia / Detective / Doctor / Villager, slots 1-5)
  * constraints  the rules every answer must obey

Camorra-themed examples live here. They are solved by the generic backtracking solver in
`backtracking.py`.
"""
from .backtracking import backtrack, n_queens  # noqa: F401  (n_queens re-exported for convenience)

ROLES = ["Mafia", "Detective", "Doctor", "Villager"]


def role_counts(total_players, mafia_count):
    """How many of each role Camorra deals (1 Detective, 1 Doctor, the rest Villagers)."""
    return {"Mafia": mafia_count, "Detective": 1, "Doctor": 1,
            "Villager": total_players - mafia_count - 2}


def role_assignment(names, mafia_count, forbidden_mafia=()):
    """Assign roles as a CSP.
    Constraints: exact role counts; two neighbours at the table can't both be Mafia;
    optional players that may not be Mafia."""
    need = role_counts(len(names), mafia_count)
    domains = {n: list(ROLES) for n in names}
    for n in forbidden_mafia:
        if n in domains:
            domains[n].remove("Mafia")
    index = {n: i for i, n in enumerate(names)}

    def counts(assign):
        return all(list(assign.values()).count(r) <= need[r] for r in ROLES)

    def not_adjacent(assign):
        for a, ra in assign.items():
            for b, rb in assign.items():
                d = abs(index[a] - index[b])
                if a < b and ra == rb == "Mafia" and d in (1, len(names) - 1):
                    return False
        return True

    sols, stats = backtrack(names, domains, [counts, not_adjacent], mrv=True)
    return (sols[0] if sols else None), stats, need


def verify_role_assignment(roles_by_player):
    """Check an existing assignment against the game's role-count rules, using the same CSP
    machinery (each variable gets a single-value domain, so the solver just validates it)."""
    names = list(roles_by_player)
    need = role_counts(len(names), sum(r == "Mafia" for r in roles_by_player.values()))

    def counts(assign):
        return all(list(assign.values()).count(r) <= need[r] for r in ROLES)

    sols, stats = backtrack(names, {n: [roles_by_player[n]] for n in names}, [counts])
    return bool(sols), stats, need


def day_schedule():
    """Task scheduling: place the phases of one game day into time slots.
    Constraints: every phase gets its own slot, and the phases keep their order."""
    tasks = ["Night actions", "Morning report", "Discussion", "Voting", "Elimination reveal"]
    domains = {t: list(range(1, 6)) for t in tasks}
    before = [("Night actions", "Morning report"), ("Morning report", "Discussion"),
              ("Discussion", "Voting"), ("Voting", "Elimination reveal")]

    def alldiff(a):
        return len(set(a.values())) == len(a)

    def prec(a):
        return all(a[x] < a[y] for x, y in before if x in a and y in a)

    sols, stats = backtrack(tasks, domains, [alldiff, prec])
    return (sols[0] if sols else None), stats, before
