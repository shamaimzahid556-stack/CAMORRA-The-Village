"""Privacy-preserving usage statistics used to find explanations that need improving.

WHAT IS STORED (aggregate counters only):
    per knowledge section id (e.g. "roles.detective"): how often it was used to answer,
    how often a player said "helpful" / "not helpful", how often a follow-up showed confusion;
    plus counters per broad intent category and for refusals / off-topic questions.

WHAT IS NEVER STORED: message text, answers, player names, who asked, which role the asker had,
timestamps, session ids, game state, targets, votes or investigation results.

Section ids are public rulebook headings, so the file reveals nothing about any game.

RELIABILITY RULE: statistics are optional. Nothing in this file may ever raise into the chat.
A missing, empty, corrupt or unwritable file (for example one that OneDrive is syncing) is
treated as "start from zero", and a failure to save is silently ignored.
"""
import copy
import json
import os
import threading

from .config import DATA_DIR

EMPTY = {"version": 1, "sections": {}, "intents": {}, "events": {}}
SECTION_FIELDS = ("asked", "helpful", "unhelpful", "confused")


def _clean(data):
    """Build a valid counters structure from whatever was in the file (anything may be in it)."""
    out = copy.deepcopy(EMPTY)
    if not isinstance(data, dict):
        return out
    for bucket in ("intents", "events"):
        src = data.get(bucket)
        if isinstance(src, dict):
            out[bucket] = {str(k): v for k, v in src.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
    src = data.get("sections")
    if isinstance(src, dict):
        for sid, entry in src.items():
            if isinstance(entry, dict):
                out["sections"][str(sid)] = {f: (entry.get(f) if isinstance(entry.get(f), int) and entry.get(f) >= 0 else 0)
                                             for f in SECTION_FIELDS}
    return out


class Metrics:
    def __init__(self, path=None, enabled=True):
        self.path = path or (DATA_DIR / "metrics.json")
        self.enabled = enabled
        self._lock = threading.Lock()
        self._data = None

    def _load(self):
        if self._data is None:
            raw = None
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                raw = None
            self._data = _clean(raw)
        return self._data

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._load(), fh, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except (OSError, ValueError, TypeError):
            pass                                    # statistics must never break the game

    def _bump(self, bucket, key, field=None):
        data = self._load()
        if field is None:
            data[bucket][key] = data[bucket].get(key, 0) + 1
        else:
            entry = data[bucket].setdefault(key, {f: 0 for f in SECTION_FIELDS})
            entry[field] = entry.get(field, 0) + 1

    def record(self, intent=None, chunk_ids=(), field="asked", event=None):
        """Count something. Never raises."""
        if not self.enabled:
            return
        try:
            changed = False
            with self._lock:
                if intent:
                    self._bump("intents", str(intent)); changed = True
                for cid in chunk_ids or ():
                    self._bump("sections", str(cid), field); changed = True
                if event:
                    self._bump("events", str(event)); changed = True
                if changed:                         # never write a file when there is nothing to write
                    self._save()
        except Exception:
            pass

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._load())
