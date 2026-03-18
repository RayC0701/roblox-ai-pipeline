# Coin Collection System

## Overview
A server-side coin collection system for a Roblox game. Players walk over coins
scattered around the map to collect them. Each coin adds to the player's score,
which is displayed on a leaderboard.

## Requirements

### Core Mechanics
- Coins are Parts in Workspace under a `Coins` folder
- When a player's character touches a coin, the coin is collected
- Each coin awards 1 point (configurable via an attribute)
- Collected coins respawn after 10 seconds (configurable)
- A "bling" sound plays on collection (attach Sound to each coin)

### Leaderboard
- Use `leaderstats` folder in the Player for leaderboard integration
- Create an IntValue named "Coins" inside leaderstats
- The leaderboard updates immediately on collection

### Anti-Cheat
- Server-side validation only — never trust the client
- Debounce per-player per-coin to prevent double-collection
- Verify the coin still exists before awarding points

### Data Persistence (Optional Extension)
- Use DataStoreService to save/load player coin counts
- Save on PlayerRemoving and periodically via auto-save

## Technical Notes
- Use `task.spawn()` and `task.wait()` (not deprecated `spawn`/`wait`)
- Access services via `game:GetService()`
- Type-annotate all functions
- Script type: `Script` (server-side, place in `ServerScriptService`)
