# CAMORRA overview

## What CAMORRA is
CAMORRA is a Mafia-style social deduction game for {{min_players}} to {{max_players}} people sharing one device. Its tagline is "The village is watching. Someone is lying." Every player gets a secret role. The village alternates between night, when roles act in secret, and day, when everyone discusses and votes someone out. A computer moderator runs the game: it deals the roles, tracks the turns, counts the votes and announces the results.

Everyone in the game is a real person. In this version there are no computer-controlled players, and the moderator does not listen to the discussion.

Simple version: it is a hidden-roles party game. Some players secretly belong to the Mafia and try to take over the village. Everyone else tries to find them before that happens. The computer is only the referee.

## The objective and the two teams
There are two sides. The Mafia team tries to take control of the village. The Town team (the Detective, the Doctor and the Villagers, shown as the "Civilians" on the result screen) tries to eliminate every Mafia member.

The Mafia wins when the number of living Mafia is equal to or greater than the number of living non-Mafia players. The Civilians win when no Mafia are left alive. See the win conditions for the exact rules.

Simple version: Town wins by getting rid of all the Mafia. The Mafia wins by getting as many players as the rest of the village.

## Player counts and the roles in a game
A game has between {{min_players}} and {{max_players}} players. How many Mafia can there be? The limit on the Mafia count is {{max_mafia}}: the host chooses the number of Mafia, from {{min_mafia}} to {{max_mafia}}. Every game has exactly {{detective_count}} Detective and exactly {{doctor_count}} Doctor. In every game, all the players who are not Mafia, the Detective or the Doctor are Villagers, and there must be at least {{min_villagers}} Villager. The roles are shuffled randomly among the players, so nobody chooses their own role.

Simple version: pick how many players and how many Mafia. There is always one Detective and one Doctor, and everyone else is a Villager.

## How a new game begins
On the first screen the host selects the total number of characters, types a unique name for every player and chooses the number of Mafia. The setup screen shows how many Villagers that leaves and whether the setup is valid. START THE GAME begins the game, and it is disabled while the setup is invalid. Starting a game always replaces any game already in progress.

After START THE GAME the roles are assigned privately, one player at a time, by passing the device around. Then Night 1 begins.

## Structure of a round
The game starts with Night 1, right after role assignment. After that each round follows the same cycle: a night where each living player takes a private turn, a morning report, a timed discussion, a private voting round, and an elimination announcement. If nobody has won, the next night begins.

After every night resolves and after every vote the game checks whether either side has won. If one has, the game goes straight to the result screen.

Simple version: night, morning, discussion, vote, elimination, then night again, until a team wins.

## How players use the interface
The game is played with large buttons on one shared screen. Private moments use a "PASS THE DEVICE" screen that names the player who should take the device. That player presses a button to confirm they are ready before anything secret is shown. Choices are made by tapping a player card or an option and then pressing CONTINUE.
