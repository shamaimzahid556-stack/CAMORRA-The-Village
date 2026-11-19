"""Hill Climbing (AI subject: Hill Climbing): simple, steepest-ascent and stochastic variants.

Hill climbing repeatedly moves to a better neighbouring state and stops when no neighbour is
better (a local maximum). Used here on a Camorra table-seating puzzle and on a maze."""
import random


# ---------------- Seating arrangement ----------------
def seating_score(order, roles):
    """Higher is better.
    -3 for two Mafia side by side, -1 for Mafia two seats apart,
    -1 for Detective beside Mafia, +1 for Doctor beside Detective."""
    n, s = len(order), 0
    for i in range(n):
        a, b = roles[order[i]], roles[order[(i + 1) % n]]
        c = roles[order[(i + 2) % n]]
        if a == b == "Mafia":
            s -= 3
        if a == c == "Mafia":
            s -= 1
        if {a, b} == {"Mafia", "Detective"}:
            s -= 1
        if {a, b} == {"Doctor", "Detective"}:
            s += 1
    return s


def _neighbours(order):
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            o = order[:]
            o[i], o[j] = o[j], o[i]
            yield o


def climb(kind, start, roles, rng, max_steps=200):
    cur, steps = start[:], 0
    history = [seating_score(cur, roles)]
    while steps < max_steps:
        cs = seating_score(cur, roles)
        nbrs = list(_neighbours(cur))
        if kind == "simple":            # first neighbour that is better
            rng.shuffle(nbrs)
            nxt = next((n for n in nbrs if seating_score(n, roles) > cs), None)
        elif kind == "steepest":        # best neighbour overall
            top = max(nbrs, key=lambda n: seating_score(n, roles))
            nxt = top if seating_score(top, roles) > cs else None
        else:                           # stochastic: random choice among better neighbours
            better = [n for n in nbrs if seating_score(n, roles) > cs]
            nxt = rng.choice(better) if better else None
        if nxt is None:
            break
        cur, steps = nxt, steps + 1
        history.append(seating_score(cur, roles))
    return {"variant": kind, "start_score": history[0], "final_score": history[-1],
            "steps": steps, "final_order": cur, "score_history": history}


def seating_demo(roster, seed=3):
    rng = random.Random(seed)
    names = list(roster)
    start = names[:]
    rng.shuffle(start)                         # random starting seating
    return [climb(k, start, roster, random.Random(seed)) for k in ("simple", "steepest", "stochastic")]


# ---------------- Maze ----------------
MAZE = [
    "S.#.....",
    ".##.###.",
    "....#...",
    ".####.#.",
    "......#G",
]


def _cells():
    walls, start, goal = set(), None, None
    for r, row in enumerate(MAZE):
        for c, ch in enumerate(row):
            if ch == "#":
                walls.add((r, c))
            elif ch == "S":
                start = (r, c)
            elif ch == "G":
                goal = (r, c)
    return walls, start, goal


def maze_climb(kind, seed=1):
    walls, start, goal = _cells()
    rng = random.Random(seed)
    h = lambda p: abs(p[0] - goal[0]) + abs(p[1] - goal[1])      # Manhattan distance (lower is better)

    def nbrs(p):
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            q = (p[0] + dr, p[1] + dc)
            if 0 <= q[0] < len(MAZE) and 0 <= q[1] < len(MAZE[0]) and q not in walls:
                yield q

    cur, path = start, [start]
    while cur != goal:
        better = [q for q in nbrs(cur) if h(q) < h(cur)]
        if not better:
            break
        if kind == "simple":
            nxt = better[0]
        elif kind == "steepest":
            nxt = min(better, key=h)
        else:
            nxt = rng.choice(better)
        cur = nxt
        path.append(cur)
    return {"variant": kind, "reached_goal": cur == goal, "stopped_at": cur,
            "h_at_stop": h(cur), "steps": len(path) - 1, "path": path}


def maze_demo():
    return {"maze": MAZE,
            "note": "S=start, G=goal, #=wall. Hill climbing only moves to a cell closer to G, "
                    "so it can get stuck in a local maximum (dead end).",
            "runs": [maze_climb(k) for k in ("simple", "steepest", "stochastic")]}
