-- ClaudeBot.lua  v3.0
-- Guild chat RP bot for Claude AI
-- Communication via SavedVariables file I/O (synced on each /reload)

ClaudeBotDB = ClaudeBotDB or {}

local ClaudeBot = CreateFrame("Frame", "ClaudeBotFrame", UIParent)
local updateInterval = 1.0  -- seconds between state updates
local timeSinceLastUpdate = 0

-- ============================================================
-- MESSAGE BUFFER
-- Captures guild chat and system messages for Claude
-- ============================================================

local MESSAGE_BUFFER_SIZE = 30
local messageBuffer = {}

local function AddMessage(msgType, text)
    table.insert(messageBuffer, {
        type = msgType,
        text = text,
        time = GetTime(),
    })
    while #messageBuffer > MESSAGE_BUFFER_SIZE do
        table.remove(messageBuffer, 1)
    end
end

-- ============================================================
-- STATE COLLECTION (minimal — chat bot only)
-- ============================================================

local function GetPlayerInfo()
    return {
        name    = UnitName("player"),
        class   = UnitClass("player"),
        level   = UnitLevel("player"),
        zone    = GetRealZoneText(),
        subZone = GetSubZoneText(),
        isDead  = UnitIsDead("player") and true or false,
        isGhost = UnitIsGhost("player") and true or false,
    }
end

local function CollectState()
    return {
        timestamp    = GetTime(),
        player       = GetPlayerInfo(),
        chatMessages = messageBuffer,
    }
end

-- ============================================================
-- COMPACT JSON SERIALIZER (for SavedVariables lastState)
-- ============================================================

local function toJSON(val)
    local t = type(val)
    if t == "nil" then return "null"
    elseif t == "boolean" then return tostring(val)
    elseif t == "number" then
        if val ~= val then return "null" end
        return tostring(val)
    elseif t == "string" then
        val = val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\t', '\\t')
        return '"' .. val .. '"'
    elseif t == "table" then
        local isArray = true
        local n = 0
        for k in pairs(val) do
            n = n + 1
            if type(k) ~= "number" or k ~= math.floor(k) then isArray = false; break end
        end
        isArray = isArray and n == #val
        if isArray then
            if n == 0 then return "[]" end
            local items = {}
            for _, v in ipairs(val) do
                items[#items+1] = toJSON(v)
            end
            return "[" .. table.concat(items, ",") .. "]"
        else
            local items = {}
            for k, v in pairs(val) do
                items[#items+1] = '"' .. tostring(k) .. '":' .. toJSON(v)
            end
            if #items == 0 then return "{}" end
            return "{" .. table.concat(items, ",") .. "}"
        end
    end
    return '"[' .. t .. ']"'
end

-- ============================================================
-- COMMAND EXECUTION (run_macro only)
-- ============================================================

local function ExecuteCommand(cmd)
    if not cmd or not cmd.action then return "no_action" end

    if cmd.action == "run_macro" and cmd.text then
        RunMacroText(cmd.text)
        ClaudeBot:Print("Ran macro: " .. cmd.text)
        return "ok"
    else
        ClaudeBot:Print("Unknown command: " .. tostring(cmd.action))
        return "unknown_action"
    end
end

-- ============================================================
-- EVENT HANDLERS
-- Guild chat, party chat, whispers, system messages, errors
-- ============================================================

local eventFrame = CreateFrame("Frame")
eventFrame:RegisterEvent("UI_ERROR_MESSAGE")
eventFrame:RegisterEvent("CHAT_MSG_SYSTEM")
eventFrame:RegisterEvent("CHAT_MSG_WHISPER")
eventFrame:RegisterEvent("CHAT_MSG_GUILD")
eventFrame:RegisterEvent("CHAT_MSG_PARTY")

eventFrame:SetScript("OnEvent", function(self, event, ...)
    if event == "UI_ERROR_MESSAGE" then
        local _, msg = ...
        if msg then
            AddMessage("error", msg)
        end

    elseif event == "CHAT_MSG_SYSTEM" then
        local msg = ...
        if msg then
            AddMessage("system", msg)
        end

    elseif event == "CHAT_MSG_WHISPER" then
        local msg, sender = ...
        if msg then
            AddMessage("whisper", sender .. ": " .. msg)
        end

    elseif event == "CHAT_MSG_GUILD" then
        local msg, sender = ...
        if msg and sender and msg:lower():find("^hey aldric") then
            AddMessage("guild", sender .. ": " .. msg)
        end

    elseif event == "CHAT_MSG_PARTY" then
        local msg, sender = ...
        if msg and sender and msg:lower():find("^hey aldric") then
            AddMessage("party", sender .. ": " .. msg)
        end
    end
end)

-- ============================================================
-- MAIN UPDATE LOOP
-- ============================================================

ClaudeBot:SetScript("OnUpdate", function(self, elapsed)
    timeSinceLastUpdate = timeSinceLastUpdate + elapsed
    if timeSinceLastUpdate < updateInterval then return end
    timeSinceLastUpdate = 0

    local state = CollectState()
    ClaudeBotDB.lastState = toJSON(state)
    ClaudeBotDB.lastStateTime = state.timestamp
end)

-- ============================================================
-- SLASH COMMANDS
-- ============================================================

SLASH_CLAUDEBOT1 = "/cb"
SLASH_CLAUDEBOT2 = "/claudebot"

SlashCmdList["CLAUDEBOT"] = function(msg)
    local cmd = msg:match("^(%S+)") or ""
    cmd = cmd:lower()

    if cmd == "status" or cmd == "" then
        ClaudeBot:Print("ClaudeBot v3.0 - Chat Bot Mode")
        if ClaudeBotDB.commandQueue then
            ClaudeBot:Print("Command queue: " .. #ClaudeBotDB.commandQueue .. " commands")
        end
        ClaudeBot:Print("Messages buffered: " .. #messageBuffer)

    elseif cmd == "help" then
        ClaudeBot:Print("ClaudeBot v3.0 Commands:")
        ClaudeBot:Print("/cb status - show bot status")
        ClaudeBot:Print("/cb help - show this help")
    else
        ClaudeBot:Print("Unknown command. Try /cb help")
    end
end

-- ============================================================
-- ADDON LOADED — process command queue
-- ============================================================

local initFrame = CreateFrame("Frame")
initFrame:RegisterEvent("ADDON_LOADED")
initFrame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" and arg1 == "ClaudeBot" then
        ClaudeBotDB = ClaudeBotDB or {}

        -- Process command queue (batch execution)
        if ClaudeBotDB.commandQueue and #ClaudeBotDB.commandQueue > 0 then
            ClaudeBotDB.commandResults = {}
            ClaudeBotDB.queueComplete = false

            for i, cmd in ipairs(ClaudeBotDB.commandQueue) do
                local result = ExecuteCommand(cmd)
                table.insert(ClaudeBotDB.commandResults, {
                    index = i,
                    action = cmd.action,
                    result = result,
                    timestamp = GetTime(),
                })
            end

            ClaudeBotDB.queueComplete = true
            ClaudeBotDB.commandQueue = nil
            ClaudeBot:Print("Queue complete: " .. #ClaudeBotDB.commandResults .. " commands executed")

        -- Single pending command (backward compat)
        elseif ClaudeBotDB.pendingCommand then
            local result = ExecuteCommand(ClaudeBotDB.pendingCommand)
            ClaudeBotDB.lastCommandResult = {
                action = ClaudeBotDB.pendingCommand.action,
                result = result,
                timestamp = GetTime(),
            }
            ClaudeBotDB.pendingCommand = nil
        end

        ClaudeBot:Print("ClaudeBot v3.0 loaded! Chat bot mode. Type /cb help.")
    end
end)
