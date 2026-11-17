# Mods built into apps

ExeFS mods that the NSP script builds into a game's app when the NSP folder has no `mods/<title ID>/` of its own ([Mods](../docs/development.md#mods)). Each is the upstream release as published, unchanged. The rewriter converts it with the game's code at build time.

| Game | Mod | Version | Source and licence |
|---|---|---|---|
| [The Legend of Zelda: Ocarina of Time](../dm/games/0400486024DEC000/README.md) (`0400486024DEC000`, build `e0f3ccfa…`, v131072) | Wayfarer: an in-game cheat menu (R3) | v1.1 | [MelianLuthien/Wayfarer](https://github.com/MelianLuthien/Wayfarer), GNU GPL v3; its source is in that repository |

A mod runs as the game's own code, outside any sandbox. `--mods none` (or `MODS = 'none'`) builds an app without them.
