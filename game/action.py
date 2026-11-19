class NightAction:
    def __init__(self, actor_id, action_type, target_id=None, target_ids=None):
        self.actor_id = actor_id
        self.action_type = action_type
        self.target_id = target_id
        self.target_ids = target_ids or []
        self.resolved = False
        self.result = None

    def resolve(self, result=None):
        self.resolved = True
        self.result = result

    def __str__(self):
        targets = ", ".join(map(str, self.target_ids)) if self.target_ids else str(self.target_id)
        return f"Player {self.actor_id} {self.action_type} {targets} | Resolved: {self.resolved}"
