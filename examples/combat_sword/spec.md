# Combat Sword System

## Overview
A melee combat system centered around a sword tool. Players equip the sword
from their inventory and can swing it to deal damage to other players or NPCs.

## Requirements

### Sword Tool
- The sword is a Tool in StarterPack
- It has a Handle part with a mesh (from the 3D asset pipeline)
- Activation (click/tap) triggers a swing animation + damage zone

### Combat Mechanics
- Swing has a 0.8-second cooldown between attacks
- Damage: 25 HP per hit (configurable via tool attribute)
- Damage is applied server-side via a RemoteEvent
- Hit detection uses a raycast or overlap region in front of the character
- Players cannot damage themselves

### Visual Feedback
- Swing animation plays on activation (use Animation object)
- Hit effect: brief red flash on the damaged character
- Sound effect on swing and on hit

### Server Validation
- All damage is validated server-side
- Verify the attacker is alive and has the sword equipped
- Verify the target is alive and within range (max 8 studs)
- Rate-limit swing requests to prevent spam

### Health System Integration
- Use Humanoid.Health for damage
- Respect ForceField (no damage while active)
- Fire a BindableEvent on kill for other systems to listen to

## Technical Notes
- Use `task.spawn()` and `task.delay()` (not deprecated globals)
- Access services via `game:GetService()`
- Type-annotate all functions
- Script type: `Script` (server-side, in `ServerScriptService`)
- Client script: `LocalScript` (in the Tool, handles input + animation)
