import random
from game.roles import MAFIA, DETECTIVE, DOCTOR, VILLAGER


class RoleManager:
    def __init__(self, total_players, mafia_count, detective_count=1, doctor_count=1):
        self.total_players = total_players
        self.mafia_count = mafia_count
        self.detective_count = detective_count
        self.doctor_count = doctor_count
        self.villager_count = 0

    def validate(self):
        if not 6 <= self.total_players <= 15:
            raise ValueError("Total characters must be between 6 and 15.")
        if not 1 <= self.mafia_count <= 3:
            raise ValueError("Mafia must be between 1 and 3.")
        if self.detective_count != 1:
            raise ValueError("There must be exactly 1 Detective.")
        if self.doctor_count != 1:
            raise ValueError("There must be exactly 1 Doctor.")
        used = self.mafia_count + 1 + 1
        self.villager_count = self.total_players - used
        if self.villager_count < 1:
            raise ValueError("At least 1 Villager is required.")
        return True

    def create_role_list(self):
        self.validate()
        roles = [MAFIA] * self.mafia_count + [DETECTIVE, DOCTOR] + [VILLAGER] * self.villager_count
        random.shuffle(roles)
        return roles

    def get_distribution(self):
        self.validate()
        return {
            "Mafia": self.mafia_count,
            "Detective": 1,
            "Doctor": 1,
            "Villager": self.villager_count,
        }
