import random
from game.action import NightAction


class GameState:
    def __init__(self):
        self.players = []
        self.phase = "SETUP"
        self.day_number = 0
        self.night_number = 0
        self.game_over = False
        self.winner = None

        self.role_reveal_index = 0
        self.night_turn_index = 0
        self.night_order_ids = []
        self.night_ready_for = None      # (night_number, player_id) once that player pressed I'M READY
        self.night_actions = {}

        # Mafia night coordination
        self.mafia_votes = {}
        self.mafia_target_id = None
        self.mafia_shortlist_ids = []
        self.mafia_shortlist_owner_id = None
        self.mafia_action_history = []

        # Doctor / Detective
        self.doctor_target_id = None
        self.detective_target_id = None
        self.detective_result = None
        self.doctor_self_save_used = False

        # Night result
        self.night_killed_player_id = None
        self.night_saved_player_id = None
        self.public_log = []   # only what every player has been shown on screen (used by the AI companion)
        self.detective_found_mafia_id = None
        self.morning_ready = False

        # Day
        self.discussion_active = False
        self.discussion_started_at = None
        self.voting_started = False
        self.voting_turn_index = 0
        self.day_votes = {}
        self.eliminated_player_id = None
        self.vote_tie = False
        self.last_vote_counts = {}

    def add_player(self, player):
        self.players.append(player)

    def get_alive_players(self):
        return [p for p in self.players if p.alive]

    def get_dead_players(self):
        return [p for p in self.players if not p.alive]

    def get_player(self, player_id):
        return next((p for p in self.players if p.player_id == player_id), None)

    @staticmethod
    def get_role_name(player):
        return getattr(getattr(player, "role", None), "name", None)

    def get_alive_mafia(self):
        return [p for p in self.get_alive_players() if self.get_role_name(p) == "Mafia"]

    def get_alive_doctors(self):
        return [p for p in self.get_alive_players() if self.get_role_name(p) == "Doctor"]

    def get_alive_detectives(self):
        return [p for p in self.get_alive_players() if self.get_role_name(p) == "Detective"]

    def get_alive_villagers(self):
        return [p for p in self.get_alive_players() if self.get_role_name(p) == "Villager"]

    def get_mafia_partners(self, player_id):
        return [p for p in self.get_alive_mafia() if p.player_id != player_id]

    def get_current_role_reveal_player(self):
        if self.role_reveal_index >= len(self.players):
            return None
        return self.players[self.role_reveal_index]

    def start_night(self):
        if self.game_over:
            return
        self.phase = "NIGHT"
        self.night_number += 1
        self.night_turn_index = 0
        self.night_order_ids = [p.player_id for p in self.get_alive_players()]
        self.night_actions = {}
        self.night_ready_for = None
        self.mafia_votes = {}
        self.mafia_target_id = None
        self.mafia_shortlist_ids = []
        self.mafia_shortlist_owner_id = None
        self.mafia_action_history = []
        self.doctor_target_id = None
        self.detective_target_id = None
        self.detective_result = None
        self.night_killed_player_id = None
        self.night_saved_player_id = None
        self.detective_found_mafia_id = None
        self.morning_ready = False

    def get_night_order(self):
        return [
            self.get_player(player_id)
            for player_id in self.night_order_ids
            if self.get_player(player_id) is not None
        ]

    def get_current_night_player(self):
        while self.night_turn_index < len(self.night_order_ids):
            player = self.get_player(self.night_order_ids[self.night_turn_index])
            if player is not None and player.alive:
                return player
            self.night_turn_index += 1
        return None

    def advance_night_turn(self):
        self.night_turn_index += 1
        return self.get_current_night_player()

    def record_night_action(self, action):
        self.night_actions[action.actor_id] = action

    def record_mafia_action(self, actor_id, shortlist_ids=None, target_id=None):
        entry = {
            "actor_id": actor_id,
            "shortlist_ids": list(shortlist_ids or []),
            "target_id": target_id,
        }
        self.mafia_action_history.append(entry)
        if target_id is not None:
            self.mafia_votes[actor_id] = target_id

    def start_day(self):
        self.phase = "DISCUSSION"
        self.day_number += 1
        self.discussion_active = False
        self.discussion_started_at = None
        self.voting_started = False
        self.voting_turn_index = 0
        self.day_votes = {}
        self.eliminated_player_id = None
        self.vote_tie = False
        self.last_vote_counts = {}

    def start_voting(self):
        if self.game_over:
            return
        self.discussion_active = False
        self.voting_started = True
        self.voting_turn_index = 0
        self.phase = "VOTING"

    def get_current_voter(self):
        voters = self.get_alive_players()
        if self.voting_turn_index >= len(voters):
            return None
        return voters[self.voting_turn_index]

    def record_vote(self, voter_id, target_id):
        self.day_votes[voter_id] = target_id
        self.voting_turn_index += 1

    def check_win(self):
        mafia = len(self.get_alive_mafia())
        innocents = len(self.get_alive_players()) - mafia
        if mafia == 0:
            self.game_over = True
            self.winner = "Civilians"
            self.phase = "GAME_OVER"
            return self.winner
        if mafia >= innocents:
            self.game_over = True
            self.winner = "Mafia"
            self.phase = "GAME_OVER"
            return self.winner
        return None

    def resolve_mafia_kill(self):
        votes = {}
        for target_id in self.mafia_votes.values():
            votes[target_id] = votes.get(target_id, 0) + 1
        if not votes:
            return None
        high = max(votes.values())
        tied = [target for target, count in votes.items() if count == high]
        return random.choice(tied)

    def log_public(self, entry):
        """Record an event that the game has shown to everybody. Never put hidden facts here."""
        self.public_log.append(entry)

    def resolve_night(self):
        self.mafia_target_id = self.resolve_mafia_kill()
        self.night_killed_player_id = None
        self.night_saved_player_id = self.doctor_target_id

        if self.mafia_target_id is not None:
            target = self.get_player(self.mafia_target_id)
            if target and target.alive and self.mafia_target_id != self.doctor_target_id:
                target.kill()
                self.night_killed_player_id = self.mafia_target_id

        self.morning_ready = True
        return {
            "killed_player_id": self.night_killed_player_id,
            "saved_player_id": self.night_saved_player_id,
        }

    def resolve_day_votes(self):
        counts = {}
        for target_id in self.day_votes.values():
            counts[target_id] = counts.get(target_id, 0) + 1
        self.last_vote_counts = counts
        if not counts:
            return None
        high = max(counts.values())
        tied = [pid for pid, count in counts.items() if count == high]
        self.vote_tie = len(tied) > 1
        target_id = random.choice(tied)
        target = self.get_player(target_id)
        if target and target.alive:
            target.kill()
            self.eliminated_player_id = target_id
        return target_id

    def __str__(self):
        return (
            f"Phase: {self.phase} | Day: {self.day_number} | "
            f"Night: {self.night_number} | Players: {len(self.players)}"
        )
