class Player:
    def __init__(self, player_id, name, is_human=True):
        self.player_id = player_id
        self.name = name
        self.is_human = is_human
        self.role = None
        self.alive = True

    def assign_role(self, role):
        self.role = role

    def kill(self):
        self.alive = False

    def is_mafia(self):
        return self.role is not None and self.role.team == "Mafia"

    def has_night_action(self):
        return self.role is not None and self.role.night_action

    def __str__(self):
        role_name = self.role.name if self.role is not None else "Unassigned"
        player_type = "Human" if self.is_human else "AI"
        return f"{self.name} | {player_type} | Role: {role_name} | Alive: {self.alive}"
