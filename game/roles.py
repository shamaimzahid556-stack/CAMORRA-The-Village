class Role:
    def __init__(self, name, team, night_action=False):
        self.name = name
        self.team = team
        self.night_action = night_action

    def __str__(self):
        return self.name


VILLAGER = Role("Villager", "Town", False)
DETECTIVE = Role("Detective", "Town", True)
DOCTOR = Role("Doctor", "Town", True)
MAFIA = Role("Mafia", "Mafia", True)
