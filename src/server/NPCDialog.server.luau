--[[
    NPCDialogSystem — LocalScript
    Place in: StarterPlayerScripts

    Handles:
      • CollectionService-tagged NPC discovery
      • ProximityPrompt → open dialog
      • Typewriter text effect (click/tap or Escape to skip/close)
      • Branching dialog trees defined per NPC
      • Quest acceptance via RemoteEvent to server
--]]

local CollectionService  = game:GetService("CollectionService")
local Players            = game:GetService("Players")
local ReplicatedStorage  = game:GetService("ReplicatedStorage")
local TweenService       = game:GetService("TweenService")
local UserInputService   = game:GetService("UserInputService")

-- ─────────────────────────────────────────────
--  Types
-- ─────────────────────────────────────────────

export type DialogOption = {
    text:        string,
    nextId:      string?,   -- branch to this node
    questAccept: string?,   -- accept a quest by ID
    questDecline: boolean?, -- decline (no quest fired)
    closeDialog: boolean?,  -- end the conversation
}

export type DialogNode = {
    id:      string,
    speaker: string,
    text:    string,
    options: { DialogOption }?,
}

export type DialogTree = { [string]: DialogNode }

-- ─────────────────────────────────────────────
--  Constants
-- ─────────────────────────────────────────────

local NPC_TAG          = "DialogNPC"
local TYPEWRITER_SPEED = 0.035  -- seconds per character
local TWEEN_OPEN       = TweenInfo.new(0.25, Enum.EasingStyle.Quart, Enum.EasingDirection.Out)
local TWEEN_CLOSE      = TweenInfo.new(0.18, Enum.EasingStyle.Quart, Enum.EasingDirection.In)

local COLOR_BG         = Color3.fromRGB(12, 14, 26)
local COLOR_BORDER     = Color3.fromRGB(90, 170, 255)
local COLOR_SPEAKER    = Color3.fromRGB(100, 200, 255)
local COLOR_TEXT       = Color3.fromRGB(225, 225, 225)
local COLOR_OPT_BG     = Color3.fromRGB(25, 45, 80)
local COLOR_OPT_HOVER  = Color3.fromRGB(45, 80, 140)
local COLOR_OPT_TEXT   = Color3.fromRGB(200, 225, 255)
local COLOR_QUEST_GLOW = Color3.fromRGB(255, 210, 60)

-- ─────────────────────────────────────────────
--  Dialog Data  (move to a ReplicatedStorage ModuleScript for large projects)
-- ─────────────────────────────────────────────

local DIALOG_TREES: { [string]: DialogTree } = {

    OldMerchant = {
        root = {
            id      = "root",
            speaker = "Old Merchant",
            text    = "Ah, a traveler! It's been ages since someone passed through. I could use your help with something...",
            options = {
                { text = "What do you need?",   nextId = "questOffer"  },
                { text = "Just passing through.", nextId = "goodbye"    },
            },
        },
        questOffer = {
            id      = "questOffer",
            speaker = "Old Merchant",
            text    = "Bandits ambushed my supply wagon on the eastern road. Retrieve my goods and I'll reward you handsomely — gold and rare supplies.",
            options = {
                { text = "I'll get it back for you.",     nextId = "questAccepted", questAccept  = "retrieve_wagon" },
                { text = "Sounds dangerous. Tell me more.", nextId = "questDetails"                                  },
                { text = "Sorry, I can't help.",           nextId = "questDeclined", questDecline = true             },
            },
        },
        questDetails = {
            id      = "questDetails",
            speaker = "Old Merchant",
            text    = "There were three of them, armed. They headed toward the cliffs east of the mill. I'll pay double if you bring back my ledger too.",
            options = {
                { text = "Alright, I'll do it.",    nextId = "questAccepted", questAccept  = "retrieve_wagon" },
                { text = "Still too risky for me.", nextId = "questDeclined", questDecline = true             },
            },
        },
        questAccepted = {
            id      = "questAccepted",
            speaker = "Old Merchant",
            text    = "Bless you! The wagon was last seen near the eastern cliffs, past the old mill. Be careful — those bandits are desperate men.",
            options = {
                { text = "I'll return soon.", closeDialog = true },
            },
        },
        questDeclined = {
            id      = "questDeclined",
            speaker = "Old Merchant",
            text    = "I understand... Perhaps someone else will come along. Safe travels to you, friend.",
            options = {
                { text = "Farewell.", closeDialog = true },
            },
        },
        goodbye = {
            id      = "goodbye",
            speaker = "Old Merchant",
            text    = "Of course! The road can be weary. Come back if you ever need anything. Safe travels!",
            options = {
                { text = "Take care.", closeDialog = true },
            },
        },
    },

    GuardCaptain = {
        root = {
            id      = "root",
            speaker = "Guard Captain",
            text    = "Halt. State your business in Ashenvale. We've had trouble with outsiders lately.",
            options = {
                { text = "I mean no harm — just travelling.",  nextId = "friendly"   },
                { text = "I heard you need help with something.", nextId = "questOffer" },
                { text = "None of your concern.",              nextId = "hostile"    },
            },
        },
        friendly = {
            id      = "friendly",
            speaker = "Guard Captain",
            text    = "Very well. Keep your weapons sheathed and stay out of trouble. The mayor's office is at the town center if you need anything official.",
            options = {
                { text = "Understood.", closeDialog = true },
            },
        },
        questOffer = {
            id      = "questOffer",
            speaker = "Guard Captain",
            text    = "Sharp ears. Yes — wolves have been attacking the northern farms. My men are stretched thin. I need someone to drive them back.",
            options = {
                { text = "I can handle it.", nextId = "questAccepted", questAccept = "drive_back_wolves" },
                { text = "Maybe later.",     nextId = "laterReply"                                      },
            },
        },
        questAccepted = {
            id      = "questAccepted",
            speaker = "Guard Captain",
            text    = "Good. Head north along the mill road. Farmers have been barricading at night — speak to them first. And don't underestimate the pack leader.",
            options = {
                { text = "On my way.", closeDialog = true },
            },
        },
        laterReply = {
            id      = "laterReply",
            speaker = "Guard Captain",
            text    = "Don't wait too long. Every night without action costs us livestock — and lives.",
            options = {
                { text = "I understand.", closeDialog = true },
            },
        },
        hostile = {
            id      = "hostile",
            speaker = "Guard Captain",
            text    = "Bold words. Move along before I make it my concern. Don't push your luck.",
            options = {
                { text = "Fine, fine...", closeDialog = true },
            },
        },
    },
}

-- ─────────────────────────────────────────────
--  Remote setup
-- ─────────────────────────────────────────────

local Remotes     = ReplicatedStorage:WaitForChild("Remotes")
local QuestRemote = Remotes:WaitForChild("QuestAccepted") :: RemoteEvent

-- ─────────────────────────────────────────────
--  UI Construction
-- ─────────────────────────────────────────────

local localPlayer = Players.LocalPlayer
local playerGui   = localPlayer:WaitForChild("PlayerGui")

local function makeCorner(radius: number, parent: Instance): UICorner
    local c = Instance.new("UICorner")
    c.CornerRadius = UDim.new(0, radius)
    c.Parent = parent
    return c
end

local function makeStroke(color: Color3, thickness: number, parent: Instance): UIStroke
    local s = Instance.new("UIStroke")
    s.Color       = color
    s.Thickness   = thickness
    s.Transparency = 0.25
    s.Parent      = parent
    return s
end

-- Root ScreenGui
local screenGui = Instance.new("ScreenGui")
screenGui.Name           = "NPCDialogGui"
screenGui.ResetOnSpawn   = false
screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screenGui.IgnoreGuiInset = true
screenGui.Parent         = playerGui

-- Dialog panel
local panel = Instance.new("Frame")
panel.Name                 = "Panel"
panel.AnchorPoint          = Vector2.new(0.5, 1)
panel.Size                 = UDim2.new(0.58, 0, 0, 210)
panel.Position             = UDim2.new(0.5, 0, 0.94, 0)
panel.BackgroundColor3     = COLOR_BG
panel.BackgroundTransparency = 0.08
panel.BorderSizePixel      = 0
panel.Visible              = false
panel.Parent               = screenGui
makeCorner(14, panel)
makeStroke(COLOR_BORDER, 2, panel)

local innerPad = Instance.new("UIPadding")
innerPad.PaddingTop    = UDim.new(0, 10)
innerPad.PaddingBottom = UDim.new(0, 10)
innerPad.PaddingLeft   = UDim.new(0, 14)
innerPad.PaddingRight  = UDim.new(0, 14)
innerPad.Parent        = panel

-- Speaker name
local speakerLabel = Instance.new("TextLabel")
speakerLabel.Name               = "Speaker"
speakerLabel.Size               = UDim2.new(1, 0, 0, 22)
speakerLabel.Position           = UDim2.new(0, 0, 0, 0)
speakerLabel.BackgroundTransparency = 1
speakerLabel.Text               = ""
speakerLabel.TextColor3         = COLOR_SPEAKER
speakerLabel.TextSize           = 15
speakerLabel.Font               = Enum.Font.GothamBold
speakerLabel.TextXAlignment     = Enum.TextXAlignment.Left
speakerLabel.Parent             = panel

-- Divider
local divider = Instance.new("Frame")
divider.Size             = UDim2.new(1, 0, 0, 1)
divider.Position         = UDim2.new(0, 0, 0, 28)
divider.BackgroundColor3 = COLOR_BORDER
divider.BackgroundTransparency = 0.6
divider.BorderSizePixel  = 0
divider.Parent           = panel

-- Dialog body text
local bodyLabel = Instance.new("TextLabel")
bodyLabel.Name               = "Body"
bodyLabel.Size               = UDim2.new(1, 0, 0, 72)
bodyLabel.Position           = UDim2.new(0, 0, 0, 36)
bodyLabel.BackgroundTransparency = 1
bodyLabel.Text               = ""
bodyLabel.TextColor3         = COLOR_TEXT
bodyLabel.TextSize           = 14
bodyLabel.Font               = Enum.Font.Gotham
bodyLabel.TextXAlignment     = Enum.TextXAlignment.Left
bodyLabel.TextYAlignment     = Enum.TextYAlignment.Top
bodyLabel.TextWrapped        = true
bodyLabel.RichText           = false
bodyLabel.Parent             = panel

-- "Click to continue" hint
local hintLabel = Instance.new("TextLabel")
hintLabel.Name               = "Hint"
hintLabel.Size               = UDim2.new(1, 0, 0, 14)
hintLabel.Position           = UDim2.new(0, 0, 0, 112)
hintLabel.BackgroundTransparency = 1
hintLabel.Text               = "[ Click to skip ]"
hintLabel.TextColor3         = Color3.fromRGB(120, 140, 160)
hintLabel.TextSize           = 11
hintLabel.Font               = Enum.Font.GothamItalic
hintLabel.TextXAlignment     = Enum.TextXAlignment.Right
hintLabel.Visible            = false
hintLabel.Parent             = panel

-- Options scroll frame
local optionsList = Instance.new("Frame")
optionsList.Name             = "Options"
optionsList.Size             = UDim2.new(1, 0, 0, 0)  -- resized dynamically
optionsList.Position         = UDim2.new(0, 0, 0, 132)
optionsList.BackgroundTransparency = 1
optionsList.Visible          = false
optionsList.Parent           = panel

local optionsLayout = Instance.new("UIListLayout")
optionsLayout.FillDirection  = Enum.FillDirection.Vertical
optionsLayout.Padding        = UDim.new(0, 5)
optionsLayout.SortOrder      = Enum.SortOrder.LayoutOrder
optionsLayout.Parent         = optionsList

-- ─────────────────────────────────────────────
--  State
-- ─────────────────────────────────────────────

type ActiveDialog = {
    npcName:     string,
    currentNode: DialogNode,
}

local activeDialog:    ActiveDialog? = nil
local typewriterThread: thread?      = nil
local isDialogOpen                   = false

-- ─────────────────────────────────────────────
--  Forward declarations
-- ─────────────────────────────────────────────

local openDialog:  (npcName: string) -> ()
local closeDialog: () -> ()
local showNode:    (npcName: string, nodeId: string) -> ()

-- ─────────────────────────────────────────────
--  Helper: panel height
-- ─────────────────────────────────────────────

local OPTION_H    = 30
local OPTION_GAP  = 5
local BASE_HEIGHT = 148  -- header + divider + body + hint row

local function resizePanel(optionCount: number): ()
    local optH = if optionCount > 0
        then optionCount * OPTION_H + (optionCount - 1) * OPTION_GAP + 10
        else 0
    panel.Size = UDim2.new(0.58, 0, 0, BASE_HEIGHT + optH)
end

-- ─────────────────────────────────────────────
--  Typewriter
-- ─────────────────────────────────────────────

local function skipTypewriter(): ()
    if not typewriterThread then return end
    task.cancel(typewriterThread)
    typewriterThread = nil
    if activeDialog then
        bodyLabel.Text = activeDialog.currentNode.text
    end
    hintLabel.Visible = false
end

local function playTypewriter(text: string, onDone: () -> ()): ()
    skipTypewriter()
    bodyLabel.Text    = ""
    hintLabel.Visible = true

    typewriterThread = task.spawn(function()
        for i = 1, #text do
            bodyLabel.Text = string.sub(text, 1, i)
            task.wait(TYPEWRITER_SPEED)
        end
        typewriterThread  = nil
        hintLabel.Visible = false
        onDone()
    end)
end

-- ─────────────────────────────────────────────
--  Option buttons
-- ─────────────────────────────────────────────

local function clearOptions(): ()
    for _, child in optionsList:GetChildren() do
        if child:IsA("TextButton") then
            child:Destroy()
        end
    end
    optionsList.Visible = false
end

local function buildOptions(npcName: string, options: { DialogOption }): ()
    clearOptions()
    if #options == 0 then return end

    optionsList.Size    = UDim2.new(1, 0, 0, #options * OPTION_H + (#options - 1) * OPTION_GAP)
    optionsList.Visible = true

    for i, option in options do
        local btn = Instance.new("TextButton")
        btn.Name                 = `Option{i}`
        btn.LayoutOrder          = i
        btn.Size                 = UDim2.new(1, 0, 0, OPTION_H)
        btn.BackgroundColor3     = COLOR_OPT_BG
        btn.BorderSizePixel      = 0
        btn.AutoButtonColor      = false
        btn.Text                 = `  ▸  {option.text}`
        btn.TextColor3           = COLOR_OPT_TEXT
        btn.TextSize             = 13
        btn.Font                 = Enum.Font.Gotham
        btn.TextXAlignment       = Enum.TextXAlignment.Left
        btn.TextTruncate         = Enum.TextTruncate.AtEnd
        btn.Parent               = optionsList
        makeCorner(7, btn)

        -- Quest-offer indicator
        if option.questAccept then
            makeStroke(COLOR_QUEST_GLOW, 1, btn)
            btn.TextColor3 = COLOR_QUEST_GLOW
        end

        -- Hover tweens
        btn.MouseEnter:Connect(function()
            TweenService:Create(btn, TweenInfo.new(0.1), { BackgroundColor3 = COLOR_OPT_HOVER }):Play()
        end)
        btn.MouseLeave:Connect(function()
            TweenService:Create(btn, TweenInfo.new(0.1), { BackgroundColor3 = COLOR_OPT_BG }):Play()
        end)

        btn.Activated:Connect(function()
            -- Quest integration
            if option.questAccept then
                local ok, err = pcall(function()
                    QuestRemote:FireServer(option.questAccept)
                end)
                if not ok then
                    warn(`[DialogSystem] QuestRemote:FireServer failed — {err}`)
                end
            end

            if option.closeDialog then
                closeDialog()
            elseif option.nextId then
                showNode(npcName, option.nextId)
            else
                closeDialog()
            end
        end)
    end
end

-- ─────────────────────────────────────────────
--  Core dialog logic
-- ─────────────────────────────────────────────

showNode = function(npcName: string, nodeId: string): ()
    local tree = DIALOG_TREES[npcName]
    if not tree then
        warn(`[DialogSystem] No dialog tree for NPC "{npcName}"`)
        return
    end
    local node = tree[nodeId]
    if not node then
        warn(`[DialogSystem] Node "{nodeId}" missing in tree "{npcName}"`)
        return
    end

    activeDialog  = { npcName = npcName, currentNode = node }
    speakerLabel.Text = node.speaker
    clearOptions()
    resizePanel(0)  -- collapse options while typing

    playTypewriter(node.text, function()
        local opts = node.options
        if opts and #opts > 0 then
            resizePanel(#opts)
            buildOptions(npcName, opts)
        else
            -- Auto-close after a beat if no options
            task.delay(1.5, closeDialog)
        end
    end)
end

openDialog = function(npcName: string): ()
    if isDialogOpen then return end
    isDialogOpen = true

    panel.Visible              = true
    panel.BackgroundTransparency = 1
    panel.Position             = UDim2.new(0.5, 0, 1.0, 0)

    TweenService:Create(panel, TWEEN_OPEN, {
        Position             = UDim2.new(0.5, 0, 0.94, 0),
        BackgroundTransparency = 0.08,
    }):Play()

    showNode(npcName, "root")
end

closeDialog = function(): ()
    if not isDialogOpen then return end
    skipTypewriter()
    clearOptions()

    TweenService:Create(panel, TWEEN_CLOSE, {
        Position             = UDim2.new(0.5, 0, 1.02, 0),
        BackgroundTransparency = 1,
    }):Play()

    task.delay(TWEEN_CLOSE.Time, function()
        panel.Visible = false
        isDialogOpen  = false
        activeDialog  = nil
        speakerLabel.Text = ""
        bodyLabel.Text    = ""
    end)
end

-- ─────────────────────────────────────────────
--  Input handling
-- ─────────────────────────────────────────────

-- Click panel body → skip typewriter
panel.InputBegan:Connect(function(input: InputObject)
    if input.UserInputType == Enum.UserInputType.MouseButton1
    or input.UserInputType == Enum.UserInputType.Touch then
        if typewriterThread then
            skipTypewriter()
            if activeDialog then
                local opts = activeDialog.currentNode.options
                if opts and #opts > 0 then
                    resizePanel(#opts)
                    buildOptions(activeDialog.npcName, opts)
                end
            end
        end
    end
end)

-- Escape → close
UserInputService.InputBegan:Connect(function(input: InputObject, gameProcessed: boolean)
    if gameProcessed or not isDialogOpen then return end
    if input.KeyCode == Enum.KeyCode.Escape then
        closeDialog()
    end
end)

-- ─────────────────────────────────────────────
--  NPC / ProximityPrompt wiring
-- ─────────────────────────────────────────────

local function wireNPC(model: Model): ()
    local npcName = model.Name
    if not DIALOG_TREES[npcName] then
        -- Not a registered dialog NPC; skip silently
        return
    end

    -- Expect server to have placed: RootPart > Attachment "DialogPromptAttachment" > ProximityPrompt
    local root = model.PrimaryPart or model:FindFirstChildWhichIsA("BasePart")
    if not root then
        warn(`[DialogSystem] "{npcName}" has no BasePart`)
        return
    end

    local attachment = root:FindFirstChild("DialogPromptAttachment")
        or root:WaitForChild("DialogPromptAttachment", 8) :: Attachment?

    if not attachment then
        warn(`[DialogSystem] "{npcName}" missing DialogPromptAttachment`)
        return
    end

    local prompt = attachment:FindFirstChildOfClass("ProximityPrompt")
        or attachment:WaitForChild("ProximityPrompt", 8) :: ProximityPrompt?

    if not prompt then
        warn(`[DialogSystem] "{npcName}" missing ProximityPrompt`)
        return
    end

    prompt.Triggered:Connect(function(player: Player)
        if player ~= localPlayer then return end
        if isDialogOpen then return end
        openDialog(npcName)
    end)
end

-- Bootstrap existing + future tagged NPCs
for _, instance in CollectionService:GetTagged(NPC_TAG) do
    task.spawn(wireNPC, instance :: Model)
end

CollectionService:GetInstanceAddedSignal(NPC_TAG):Connect(function(instance: Instance)
    task.spawn(wireNPC, instance :: Model)
end)
```

Here's a breakdown of every system in the script:

---

### Architecture

| Layer | Detail |
|---|---|
| **Discovery** | `CollectionService` tag `"DialogNPC"` — works for both pre-placed and streamed-in NPCs |
| **Triggering** | `ProximityPrompt` inside a named `Attachment` on the NPC's root part (created server-side) |
| **Dialog Data** | `DIALOG_TREES` table — one tree per NPC name, each tree is a map of `nodeId → DialogNode` |
| **Branching** | Each `DialogOption` carries an optional `nextId` to jump to any node in the tree |
| **Quest hook** | `questAccept` on an option fires `ReplicatedStorage.Remotes.QuestAccepted` to the server with the quest ID — the server owns all quest state |
| **Typewriter** | `task.spawn` loop per character; click the panel or press **Escape** to skip/close |
| **UI** | Pure `Instance.new` — no external assets required; hover tweens via `TweenService` |

### Adding a new NPC

1. Tag the NPC model with `"DialogNPC"` via `CollectionService` (or a server script).
2. Add a server-side `Attachment` named `"DialogPromptAttachment"` with a `ProximityPrompt` child.
3. Add a new entry to `DIALOG_TREES` matching the model's **exact name**.
