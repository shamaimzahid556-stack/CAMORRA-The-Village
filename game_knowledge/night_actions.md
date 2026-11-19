# Night actions

## How a night turn works
Each living player takes exactly one private night turn, in the order the names were entered at setup. The turn has three steps. First the game shows "PASS THE DEVICE" with the player's name. Second, the named player takes the device and presses I'M READY. Third, their private action screen appears, where they make one choice and press CONTINUE. The game then passes to the next living player.

If it is not your turn, the game refuses the action with a message that names the player whose turn it is.

Simple version: take the device when your name appears, press I'M READY, make your choice, press CONTINUE, and pass the device on.

## Mafia night action with one living Mafia
When only one Mafia player is alive, that player chooses one living non-Mafia player to kill. The screen lists the possible victims. The player taps one, and then presses CONTINUE. There is no shortlist step.

## Mafia shortlist when there are several living Mafia
When two or more Mafia are alive, the first living Mafia player (by the order of names) goes first and builds a shared shortlist of {{shortlist_min}} to {{shortlist_max}} living non-Mafia players. The CONTINUE button stays disabled until at least {{shortlist_min}} players are selected, and no more than {{shortlist_max}} can be selected. After saving the shortlist, that same player then picks the actual target from the shortlist.

Simple version: with several Mafia, the first one picks a shortlist and every Mafia picks a victim from that shortlist.

## Mafia target choice and who dies
Each Mafia player picks one target. Later Mafia players see a "Previous Mafia actions" box that shows what earlier Mafia players shortlisted and chose. The player with the most Mafia votes becomes the Mafia's target for the night. If there is a tie for the most votes, the game picks one of the tied players at random. A Mafia player can never choose another Mafia member.

The target dies unless the Doctor protected that same player.

## Doctor night action
The Doctor sees a list of all living players and chooses one to protect. The Doctor may pick themselves only once in the whole game. The screen tells the Doctor whether the self-save is still available. If the Doctor tries to use it a second time, the game refuses. If the Mafia's target is the protected player, nobody dies from the Mafia that night.

Simple version: the Doctor taps the player to protect, and presses CONTINUE. If the Mafia picked that same person, they survive.

## Detective night action
The Detective sees a list of the living players, except themselves, and chooses one to investigate. After pressing CONTINUE, the Detective sees a private result card that says MAFIA or INNOCENT. The Detective presses HIDE RESULT & CONTINUE to hide it and pass the device on.

Simple version: pick someone, learn privately whether they are Mafia, and hide the result before passing the device.

## Villager night action
A Villager sees {{villager_activity_count}} activities and picks one: {{villager_activities}}. The choice has no effect on the game.

## How the night is resolved
When the last living player has finished, the game resolves the night in this order. First the Mafia's target is worked out from the Mafia votes. The target is killed unless the Doctor protected that player. Then, if the Detective investigated a Mafia member, that Mafia member is eliminated. Then the game checks whether either team has won. If nobody has won, the morning report is shown.

Because every action was submitted during the night, a player who is killed that night still completed their own night turn, so a Detective's investigation still counts even if the Detective is killed the same night.

## What happens when no action is available
Players who are no longer alive are skipped automatically and do not get a night turn. Villagers always have their {{villager_activity_count}} activities to choose from. On the voting screen, if a voter has no legal target the screen says that no legal vote is available.

## Can the Mafia choose the Doctor or the Detective as a victim?
Yes, the Mafia may choose any living player who is not Mafia as a victim, and that includes the Doctor and the Detective.

## What if the Doctor or the Detective is dead?
A dead Doctor or Detective no longer has a night turn and is skipped automatically. Without a living Doctor nobody can be protected, so every Mafia kill succeeds. Without a living Detective nobody can be investigated. The game does not announce who the Doctor or the Detective is.
