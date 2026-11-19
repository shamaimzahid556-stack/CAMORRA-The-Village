"""Backtracking search (AI subject: Backtracking).

Backtracking builds a solution one variable at a time. After each choice it checks the
constraints. If a constraint is broken it *undoes* the last choice (that is the "back-track")
and tries the next value.

This file holds the generic solver and the classic N-Queens puzzle.
`csp.py` reuses `backtrack()` to solve Camorra-themed Constraint Satisfaction Problems.
"""


def backtrack(variables, domains, constraints, mrv=True, find_all=False, limit=1000):
    """Generic backtracking solver.

    variables   list of variable names, e.g. player names
    domains     dict: variable -> list of allowed values
    constraints list of functions fn(partial_assignment) -> bool (False means "rule broken")
    mrv         "Minimum Remaining Values": always fill the variable with the fewest legal
                values first (fails early, so it backtracks less)
    find_all    collect every solution (up to `limit`) instead of stopping at the first one

    Returns (solutions, stats). stats counts the work done.
    """
    stats = {"assignments_tried": 0, "backtracks": 0}
    solutions = []

    def ok(assign):
        return all(c(assign) for c in constraints)

    def legal(var, assign):
        out = []
        for v in domains[var]:
            assign[var] = v
            if ok(assign):
                out.append(v)
            del assign[var]
        return out

    def rec(assign):
        if len(assign) == len(variables):
            solutions.append(dict(assign))
            return not find_all or len(solutions) >= limit
        free = [v for v in variables if v not in assign]
        options = {v: legal(v, assign) for v in free} if mrv else None
        var = min(free, key=lambda v: len(options[v])) if mrv else free[0]
        for value in (options[var] if mrv else legal(var, assign)):
            stats["assignments_tried"] += 1
            assign[var] = value
            if rec(assign):
                del assign[var]
                return True
            del assign[var]
            stats["backtracks"] += 1
        return False

    rec({})
    return solutions, stats


def n_queens(n=8, find_all=False):
    """Place n queens on an n x n board so that none attack each other.
    Variable = column, value = row. Solved with plain backtracking (no MRV)."""
    cols = list(range(n))
    domains = {c: list(range(n)) for c in cols}

    def safe(assign):
        items = list(assign.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (c1, r1), (c2, r2) = items[i], items[j]
                if r1 == r2 or abs(r1 - r2) == abs(c1 - c2):
                    return False
        return True

    return backtrack(cols, domains, [safe], mrv=False, find_all=find_all, limit=10 ** 6)
