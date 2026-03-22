-- InventoryModule.luau
-- Server-side player inventory system: slot management, item stacking,
-- configurable capacity, and DataStore persistence with retry logic.
-- Place in: ServerScriptService (or a server Modules folder).

local DataStoreService = game:GetService("DataStoreService")

--------------------------------------------------------------------------------
-- Constants
--------------------------------------------------------------------------------

local DATASTORE_NAME    = "PlayerInventory_v1"
local DEFAULT_MAX_SLOTS = 20
local SAVE_COOLDOWN     = 30  -- minimum seconds between DataStore writes per player
local MAX_RETRIES       = 3
local RETRY_DELAY       = 2   -- base seconds for exponential back-off

--------------------------------------------------------------------------------
-- Type Definitions
--------------------------------------------------------------------------------

export type ItemMetadata = { [string]: any }

export type ItemDefinition = {
	id:          string,
	name:        string,
	description: string,
	maxStack:    number,
	icon:        string?,
}

export type ItemStack = {
	itemId:   string,
	quantity: number,
	metadata: ItemMetadata?,
}

--- Serialisable snapshot stored in DataStore.
export type InventoryData = {
	slots:    { [number]: ItemStack },
	maxSlots: number,
	version:  number,
}

--- Public interface exposed to callers for type-checking.
export type Inventory = {
	playerId: number,
	maxSlots: number,
	slots:    { [number]: ItemStack },

	addItem:      (self: Inventory, itemId: string, quantity: number, metadata: ItemMetadata?) -> (boolean, string),
	removeItem:   (self: Inventory, itemId: string, quantity: number) -> (boolean, string),
	findItem:     (self: Inventory, itemId: string) -> number?,
	hasItem:      (self: Inventory, itemId: string, quantity: number?) -> boolean,
	getItemCount: (self: Inventory, itemId: string) -> number,
	getSlot:      (self: Inventory, slotIndex: number) -> ItemStack?,
	getEmptySlot: (self: Inventory) -> number?,
	toData:       (self: Inventory) -> InventoryData,
	save:         (self: Inventory) -> boolean,
	load:         (self: Inventory) -> boolean,
	destroy:      (self: Inventory) -> (),
}

--------------------------------------------------------------------------------
-- Module Setup
--------------------------------------------------------------------------------

local InventoryModule = {}
InventoryModule.__index = InventoryModule

--- Global item registry: itemId → ItemDefinition
local itemRegistry: { [string]: ItemDefinition } = {}

--- Per-player last-save timestamps (os.clock)
local lastSaveTime: { [number]: number } = {}

--- DataStore handle — wrapped so require() never throws in Studio offline mode.
local inventoryStore: DataStore? = nil
do
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(DATASTORE_NAME)
	end)
	if ok then
		inventoryStore = result
	else
		warn(`[InventoryModule] DataStore unavailable — persistence disabled: {result}`)
	end
end

--------------------------------------------------------------------------------
-- Private Helpers
--------------------------------------------------------------------------------

local function dsKey(playerId: number): string
	return `Inventory_{playerId}`
end

--- Retry wrapper with exponential back-off. Returns (success, valueOrErrorMsg).
local function retryDS(fn: () -> any): (boolean, any)
	local lastErr = ""
	for attempt = 1, MAX_RETRIES do
		local ok, result = pcall(fn)
		if ok then
			return true, result
		end
		lastErr = tostring(result)
		warn(`[InventoryModule] DataStore attempt {attempt}/{MAX_RETRIES} failed: {lastErr}`)
		if attempt < MAX_RETRIES then
			task.wait(RETRY_DELAY * attempt)
		end
	end
	return false, lastErr
end

--------------------------------------------------------------------------------
-- Public API — Item Registry
--------------------------------------------------------------------------------

--- Register an item definition. Must be called before items of that type are added.
function InventoryModule.registerItem(def: ItemDefinition)
	assert(type(def.id) == "string" and #def.id > 0,
		"ItemDefinition.id must be a non-empty string")
	assert(type(def.maxStack) == "number" and def.maxStack >= 1,
		"ItemDefinition.maxStack must be >= 1")
	itemRegistry[def.id] = def
end

--- Look up a registered item definition; returns nil if unknown.
function InventoryModule.getItemDef(itemId: string): ItemDefinition?
	return itemRegistry[itemId]
end

--------------------------------------------------------------------------------
-- Constructor
--------------------------------------------------------------------------------

--- Create a new Inventory for the given player.
--- @param playerId  Player.UserId of the owner.
--- @param maxSlots  Slot cap; defaults to DEFAULT_MAX_SLOTS.
function InventoryModule.new(playerId: number, maxSlots: number?): Inventory
	assert(type(playerId) == "number" and playerId > 0,
		"playerId must be a positive integer")

	local self = setmetatable({
		playerId     = playerId,
		maxSlots     = maxSlots or DEFAULT_MAX_SLOTS,
		slots        = {} :: { [number]: ItemStack },
		_saveLock    = false :: boolean,
		_savePending = false :: boolean,
	}, InventoryModule)

	return self :: any
end

--------------------------------------------------------------------------------
-- Inventory Methods — Queries
--------------------------------------------------------------------------------

--- Return the ItemStack occupying `slotIndex`, or nil.
function InventoryModule:getSlot(slotIndex: number): ItemStack?
	return self.slots[slotIndex]
end

--- Return the index of the first empty slot, or nil when the inventory is full.
function InventoryModule:getEmptySlot(): number?
	for i = 1, self.maxSlots do
		if self.slots[i] == nil then
			return i
		end
	end
	return nil
end

--- Return the first slot index that holds `itemId`, or nil if absent.
function InventoryModule:findItem(itemId: string): number?
	for slotIndex, stack in self.slots do
		if stack.itemId == itemId then
			return slotIndex
		end
	end
	return nil
end

--- Return the total quantity of `itemId` summed across all stacks.
function InventoryModule:getItemCount(itemId: string): number
	local total = 0
	for _, stack in self.slots do
		if stack.itemId == itemId then
			total += stack.quantity
		end
	end
	return total
end

--- Return true when the inventory holds at least `quantity` (default 1) of `itemId`.
function InventoryModule:hasItem(itemId: string, quantity: number?): boolean
	return self:getItemCount(itemId) >= (quantity or 1)
end

--------------------------------------------------------------------------------
-- Inventory Methods — Mutation
--------------------------------------------------------------------------------

--- Add `quantity` of `itemId`, filling existing stacks before opening new slots.
--- Respects the maxStack defined in the item registry (defaults to 1 if unknown).
--- Returns (true, "ok") or (false, errorReason).
function InventoryModule:addItem(
	itemId:   string,
	quantity: number,
	metadata: ItemMetadata?
): (boolean, string)
	if quantity <= 0 then
		return false, "Quantity must be greater than zero"
	end

	local def      = itemRegistry[itemId]
	local maxStack = if def then def.maxStack else 1
	local remaining = quantity

	-- Pass 1: top up existing stacks of the same item.
	for _, stack in self.slots do
		if remaining <= 0 then break end
		if stack.itemId == itemId then
			local space = maxStack - stack.quantity
			if space > 0 then
				local toAdd   = math.min(space, remaining)
				stack.quantity += toAdd
				remaining      -= toAdd
			end
		end
	end

	-- Pass 2: open new slots for any leftover quantity.
	while remaining > 0 do
		local slot = self:getEmptySlot()
		if slot == nil then
			return false,
				`Inventory full — unable to add {remaining} of '{itemId}' (no free slots)`
		end
		local toAdd = math.min(maxStack, remaining)
		self.slots[slot] = {
			itemId   = itemId,
			quantity = toAdd,
			metadata = metadata,
		}
		remaining -= toAdd
	end

	return true, "ok"
end

--- Remove `quantity` of `itemId`, depleting the last-indexed stacks first.
--- Returns (true, "ok") or (false, errorReason).
function InventoryModule:removeItem(itemId: string, quantity: number): (boolean, string)
	if quantity <= 0 then
		return false, "Quantity must be greater than zero"
	end

	local available = self:getItemCount(itemId)
	if available < quantity then
		return false,
			`Insufficient stock: need {quantity} '{itemId}', only have {available}`
	end

	local remaining = quantity
	for slotIndex = self.maxSlots, 1, -1 do
		if remaining <= 0 then break end
		local stack = self.slots[slotIndex]
		if stack and stack.itemId == itemId then
			local toRemove  = math.min(stack.quantity, remaining)
			stack.quantity  -= toRemove
			remaining       -= toRemove
			if stack.quantity <= 0 then
				self.slots[slotIndex] = nil
			end
		end
	end

	return true, "ok"
end

--- Remove every item from all slots.
function InventoryModule:clear()
	table.clear(self.slots)
end

--------------------------------------------------------------------------------
-- Inventory Methods — Serialisation
--------------------------------------------------------------------------------

--- Produce a plain-data snapshot suitable for DataStore.
function InventoryModule:toData(): InventoryData
	local slotsCopy: { [number]: ItemStack } = {}
	for idx, stack in self.slots do
		slotsCopy[idx] = {
			itemId   = stack.itemId,
			quantity = stack.quantity,
			metadata = stack.metadata,
		}
	end
	return {
		slots    = slotsCopy,
		maxSlots = self.maxSlots,
		version  = 1,
	}
end

--- Overwrite current state from a deserialised InventoryData table.
--- DataStore round-trips numeric keys as strings, so tonumber() is used.
function InventoryModule:_applyData(data: InventoryData)
	self.slots    = {}
	self.maxSlots = data.maxSlots or self.maxSlots

	if type(data.slots) ~= "table" then return end

	for rawIndex, stack in data.slots do
		local idx = tonumber(rawIndex) :: number?
		if idx and idx >= 1 and idx <= self.maxSlots
			and type(stack.itemId) == "string"
			and type(stack.quantity) == "number"
		then
			self.slots[idx] = {
				itemId   = stack.itemId,
				quantity = math.max(1, stack.quantity),
				metadata = if type(stack.metadata) == "table" then stack.metadata else nil,
			}
		end
	end
end

--------------------------------------------------------------------------------
-- Inventory Methods — Persistence
--------------------------------------------------------------------------------

--- Save the inventory to DataStore.
--- Enforces a per-player cooldown; queues a deferred save when called too soon.
--- Returns true on success (or when a deferred save was queued), false on error.
function InventoryModule:save(): boolean
	if inventoryStore == nil then
		warn(`[InventoryModule] Save skipped for {self.playerId} — DataStore unavailable`)
		return false
	end

	-- Cooldown guard
	local now      = os.clock()
	local lastSave = lastSaveTime[self.playerId] or 0
	local elapsed  = now - lastSave

	if elapsed < SAVE_COOLDOWN then
		if not self._savePending then
			self._savePending = true
			task.delay(SAVE_COOLDOWN - elapsed + 0.1, function()
				if self._savePending then
					self._savePending = false
					self:save()
				end
			end)
		end
		return true  -- a save is already scheduled — not an error
	end

	if self._saveLock then
		return false  -- concurrent save in progress
	end
	self._saveLock = true

	local key  = dsKey(self.playerId)
	local data = self:toData()

	local ok, err = retryDS(function()
		;(inventoryStore :: DataStore):SetAsync(key, data)
	end)

	self._saveLock = false

	if ok then
		lastSaveTime[self.playerId] = os.clock()
	else
		warn(`[InventoryModule] Save failed for player {self.playerId}: {err}`)
	end

	return ok
end

--- Load inventory data from DataStore, replacing current slot contents.
--- Returns true on success (including first-time players with no data).
function InventoryModule:load(): boolean
	if inventoryStore == nil then
		warn(`[InventoryModule] Load skipped for {self.playerId} — DataStore unavailable`)
		return false
	end

	local key         = dsKey(self.playerId)
	local ok, result  = retryDS(function()
		return (inventoryStore :: DataStore):GetAsync(key)
	end)

	if not ok then
		warn(`[InventoryModule] Load failed for player {self.playerId}: {result}`)
		return false
	end

	-- nil result = first-time player; leave slots empty (expected behaviour).
	if result ~= nil then
		self:_applyData(result :: InventoryData)
	end

	return true
end

--- Release resources and cancel any pending saves.
--- Call this when the owning player leaves.
function InventoryModule:destroy()
	self._savePending = false
	self.slots        = {}
	lastSaveTime[self.playerId] = nil
end

--------------------------------------------------------------------------------
return InventoryModule
```

### How it fits together

| Concern | Detail |
|---|---|
| **Types** | `ItemDefinition`, `ItemStack`, `InventoryData`, `Inventory` are all `export type`s — import them in other scripts with `local Types = require(InventoryModule)` then annotate as `Types.Inventory`. |
| **Item registry** | Call `InventoryModule.registerItem(def)` once at startup (e.g., from a shared `ItemDefs` module). The `maxStack` field drives stacking behaviour. Unknown items default to a stack size of `1`. |
| **Lifecycle** | `InventoryModule.new(userId, maxSlots?)` → `inventory:load()` on join; `inventory:save()` on leave (or periodically); `inventory:destroy()` after the final save. |
| **Stacking** | `addItem` fills existing stacks to `maxStack` before consuming new slots, so a single call with `quantity = 150` and `maxStack = 64` will correctly span three slots. |
| **DataStore safety** | All reads/writes go through `retryDS` (3 attempts, exponential back-off). Saves are guarded by a 30-second cooldown per player with an auto-queued deferred save if called too soon, preventing throttle errors. |
| **Server authority** | The module is pure server-side — never `require` it from a `LocalScript`. Use `RemoteEvents` to relay changes to the client for UI updates. |
