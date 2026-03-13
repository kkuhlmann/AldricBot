-- AldricBotAddon.lua  v1.0.0
-- Guild chat RP bot for Claude AI
-- Communication via SavedVariables file I/O (synced on each /reload)

AldricBotAddonDB = AldricBotAddonDB or {}

local AldricBotAddon = CreateFrame("Frame", "AldricBotAddonFrame", UIParent)
local updateInterval = 1.0  -- seconds between state updates
local timeSinceLastUpdate = 0

-- ============================================================
-- MESSAGE BUFFER
-- Captures guild chat and system messages for Claude
-- ============================================================

local MESSAGE_BUFFER_SIZE = 30
local messageBuffer = {}

local function AddMessage(msgType, text, senderInfo)
    local entry = {
        type = msgType,
        text = text,
        time = GetTime(),
    }
    if senderInfo then
        if senderInfo.zone and senderInfo.zone ~= "" then entry.senderZone = senderInfo.zone end
        if senderInfo.class and senderInfo.class ~= "" then entry.senderClass = senderInfo.class end
        if senderInfo.level then entry.senderLevel = senderInfo.level end
        if senderInfo.rank and senderInfo.rank ~= "" then entry.senderRank = senderInfo.rank end
        if senderInfo.note and senderInfo.note ~= "" then entry.senderNote = senderInfo.note end
        if senderInfo.officerNote and senderInfo.officerNote ~= "" then entry.senderOfficerNote = senderInfo.officerNote end
    end
    table.insert(messageBuffer, entry)
    while #messageBuffer > MESSAGE_BUFFER_SIZE do
        table.remove(messageBuffer, 1)
    end
    -- Persist so messages survive /reload
    AldricBotAddonDB.messageHistory = messageBuffer
end

-- Lazy-initialized pattern for "hey <player_name>" prefix matching
local heyPattern = nil
local function GetHeyPattern()
    if not heyPattern then
        local name = UnitName("player")
        if name then heyPattern = "^hey " .. name:lower() end
    end
    return heyPattern
end

local function GetGuildMemberInfo(name)
    if not IsInGuild() then return nil end
    for i = 1, GetNumGuildMembers() do
        local memberName, rank, _, level, class, zone, note, officernote = GetGuildRosterInfo(i)
        if memberName == name then
            return {
                zone = zone,
                class = class,
                level = level,
                rank = rank,
                note = note,
                officerNote = officernote,
            }
        end
    end
    return nil
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
        AldricBotAddon:Print("Ran macro: " .. cmd.text)
        return "ok"
    else
        AldricBotAddon:Print("Unknown command: " .. tostring(cmd.action))
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
eventFrame:RegisterEvent("CHAT_MSG_PARTY_LEADER")
eventFrame:RegisterEvent("CHAT_MSG_RAID")
eventFrame:RegisterEvent("CHAT_MSG_RAID_LEADER")
eventFrame:RegisterEvent("CHAT_MSG_ACHIEVEMENT")

eventFrame:SetScript("OnEvent", function(self, event, ...)
    if event == "UI_ERROR_MESSAGE" then
        local _, msg = ...
        if msg then
            AddMessage("error", msg)
        end

    elseif event == "CHAT_MSG_SYSTEM" then
        local msg = ...
        if msg then
            local loginName = msg:match("^(%S+) has come online%.$")
            if loginName then
                local senderInfo = GetGuildMemberInfo(loginName)
                if senderInfo then
                    AddMessage("login", loginName, senderInfo)
                end
            else
                local lvlName, lvlNum = msg:match("^(%S+) has reached level (%d+)!")
                if lvlName then
                    local senderInfo = GetGuildMemberInfo(lvlName)
                    AddMessage("levelup", lvlName .. ":" .. lvlNum, senderInfo)
                else
                    AddMessage("system", msg)
                end
            end
        end

    elseif event == "CHAT_MSG_ACHIEVEMENT" then
        local msg, sender = ...
        if sender then
            local senderInfo = GetGuildMemberInfo(sender)
            if senderInfo then
                local clean = msg and msg:gsub("|H.-|h(.-)|h", "%1") or "an achievement"
                AddMessage("achievement", sender .. ": " .. clean, senderInfo)
            end
        end

    elseif event == "CHAT_MSG_WHISPER" then
        local msg, sender = ...
        if msg then
            local senderInfo = GetGuildMemberInfo(sender)
            AddMessage("whisper", sender .. ": " .. msg, senderInfo)
        end

    elseif event == "CHAT_MSG_GUILD" then
        local msg, sender = ...
        local pat = GetHeyPattern()
        if msg and sender and pat and msg:lower():find(pat) then
            local senderInfo = GetGuildMemberInfo(sender)
            AddMessage("guild", sender .. ": " .. msg, senderInfo)
        end

    elseif event == "CHAT_MSG_PARTY" or event == "CHAT_MSG_PARTY_LEADER" then
        local msg, sender = ...
        local pat = GetHeyPattern()
        if msg and sender and pat and msg:lower():find(pat) then
            local senderInfo = GetGuildMemberInfo(sender)
            AddMessage("party", sender .. ": " .. msg, senderInfo)
        end

    elseif event == "CHAT_MSG_RAID" or event == "CHAT_MSG_RAID_LEADER" then
        local msg, sender = ...
        local pat = GetHeyPattern()
        if msg and sender and pat and msg:lower():find(pat) then
            local senderInfo = GetGuildMemberInfo(sender)
            AddMessage("raid", sender .. ": " .. msg, senderInfo)
        end
    end
end)

-- ============================================================
-- MAIN UPDATE LOOP
-- ============================================================

AldricBotAddon:SetScript("OnUpdate", function(self, elapsed)
    timeSinceLastUpdate = timeSinceLastUpdate + elapsed
    if timeSinceLastUpdate < updateInterval then return end
    timeSinceLastUpdate = 0

    local state = CollectState()
    AldricBotAddonDB.lastState = toJSON(state)
    AldricBotAddonDB.lastStateTime = state.timestamp
end)

-- ============================================================
-- SLASH COMMANDS
-- ============================================================

SLASH_ALDRICBOTADDON1 = "/ab"
SLASH_ALDRICBOTADDON2 = "/aldricbot"

SlashCmdList["ALDRICBOTADDON"] = function(msg)
    local cmd = msg:match("^(%S+)") or ""
    cmd = cmd:lower()

    if cmd == "status" or cmd == "" then
        AldricBotAddon:Print("AldricBotAddon v1.0.0 - Chat Bot Mode")
        if AldricBotAddonDB.commandQueue then
            AldricBotAddon:Print("Command queue: " .. #AldricBotAddonDB.commandQueue .. " commands")
        end
        AldricBotAddon:Print("Messages buffered: " .. #messageBuffer)

    elseif cmd == "help" then
        AldricBotAddon:Print("AldricBotAddon v1.0.0 Commands:")
        AldricBotAddon:Print("/ab status - show bot status")
        AldricBotAddon:Print("/ab help - show this help")
    else
        AldricBotAddon:Print("Unknown command. Try /ab help")
    end
end

-- ============================================================
-- ADDON LOADED — process command queue
-- ============================================================

local initFrame = CreateFrame("Frame")
initFrame:RegisterEvent("ADDON_LOADED")
initFrame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" and arg1 == "AldricBotAddon" then
        AldricBotAddonDB = AldricBotAddonDB or {}

        -- Restore messages captured before the last /reload, pruning stale ones
        if AldricBotAddonDB.messageHistory then
            local now = GetTime()
            local fresh = {}
            for _, msg in ipairs(AldricBotAddonDB.messageHistory) do
                if now - msg.time < 60 then
                    table.insert(fresh, msg)
                end
            end
            messageBuffer = fresh
            AldricBotAddonDB.messageHistory = messageBuffer
        end

        -- Process command queue (batch execution)
        if AldricBotAddonDB.commandQueue and #AldricBotAddonDB.commandQueue > 0 then
            AldricBotAddonDB.commandResults = {}
            AldricBotAddonDB.queueComplete = false

            for i, cmd in ipairs(AldricBotAddonDB.commandQueue) do
                local result = ExecuteCommand(cmd)
                table.insert(AldricBotAddonDB.commandResults, {
                    index = i,
                    action = cmd.action,
                    result = result,
                    timestamp = GetTime(),
                })
            end

            AldricBotAddonDB.queueComplete = true
            AldricBotAddonDB.commandQueue = nil
            AldricBotAddon:Print("Queue complete: " .. #AldricBotAddonDB.commandResults .. " commands executed")

        end

        -- Request fresh guild roster data for sender zone lookups
        if IsInGuild() then
            GuildRoster()
        end

        AldricBotAddon:Print("AldricBotAddon v1.0.0 loaded! Chat bot mode. Type /ab help.")
    end
end)
