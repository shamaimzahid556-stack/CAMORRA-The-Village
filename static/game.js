"use strict";

const $ = (id) => document.getElementById(id);
let currentNight = null;
let currentVoter = null;
let discussionTimer = null;
let discussionRemaining = 180;
let pendingNightChoice = null;
let morningResult = null;
let votingStarting = false;

// Role-assignment backgrounds: 15 images, shuffled like a deck of cards so each
// player gets a different one in random order and none repeats (max 15 players).
const ROLE_BACKGROUND_COUNT = 15;
const NIGHT_PORTRAIT_COUNT = 15;
let roleBackgroundDeck = [];
// role-assignment-background-13.png is byte-identical to #8; keep it out of the deck so no two players see the same image.
const DUPLICATE_BACKGROUNDS = new Set([13]);

function shuffled(items) {
    const copy = items.slice();
    for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
}

function resetRoleBackgroundDeck() {
    roleBackgroundDeck = shuffled(Array.from({ length: ROLE_BACKGROUND_COUNT }, (_, i) => i + 1)
        .filter(n => !DUPLICATE_BACKGROUNDS.has(n)));
}

function pickNextRoleBackground() {
    if (!roleBackgroundDeck.length) resetRoleBackgroundDeck();
    const number = roleBackgroundDeck.pop();
    const url = `/static/role-assignment-background-${number}.png`;
    new Image().src = url; // preload so the screen never flashes
    document.documentElement.style.setProperty("--role-bg", `url("${url}")`);
}

function show(id) {
    document.querySelectorAll(".panel").forEach(panel => panel.classList.add("hidden"));
    const panel = $(id);
    if (panel) panel.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "instant" });
}

function error(message) {
    // The old .error box only exists inside the (hidden) setup panel, so errors
    // on every other screen were invisible. This banner shows on every screen.
    console.error(message);
    document.querySelectorAll(".error").forEach(box => {
        box.textContent = message;
        box.hidden = false;
    });
    const banner = $("globalError");
    if (banner) {
        banner.textContent = message;
        banner.hidden = false;
        clearTimeout(error._t);
        error._t = setTimeout(() => { banner.hidden = true; }, 6000);
    }
}

function clearError() {
    document.querySelectorAll(".error").forEach(box => {
        box.textContent = "";
        box.hidden = true;
    });
    const banner = $("globalError");
    if (banner) banner.hidden = true;
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options
    });
    let data = null;
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
        throw new Error(data?.detail || data?.error || `Request failed (${response.status})`);
    }
    return data;
}

function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>'"]/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#39;",
        '"': "&quot;"
    }[ch]));
}

function roleDescription(role) {
    return {
        Mafia: "You are Mafia. You know your partners. Choose the Mafia's victim at night and survive the vote.",
        Doctor: "You are the Doctor. Choose one living player to protect each night. Your self-save can be used once in the whole game.",
        Detective: "You are the Detective. Investigate one living player each night.",
        Villager: "You are a Villager. You have no special power. Your observations and your vote can help eliminate Mafia."
    }[role] || "Your role is private.";
}

function updateSetup() {
    const total = Number($("totalPlayers").value);
    const mafia = Number($("mafiaCount").value);
    const villagers = total - mafia - 2;
    $("villagerCount").textContent = Math.max(villagers, 0);
    $("roleTotal").textContent = `${mafia + 2} / ${total} roles selected`;
    const valid = total >= 6 && total <= 15 && mafia >= 1 && mafia <= 3 && villagers >= 1;
    $("roleStatus").textContent = valid ? "✓ Valid setup" : "✕ Invalid setup";
    $("roleStatus").className = valid ? "valid" : "invalid";
    $("startGameButton").disabled = !valid;
    updateNameInputs(total);
}

function updateNameInputs(total) {
    const container = $("humanNames");
    const old = [...container.querySelectorAll("input")].map(input => input.value);
    container.innerHTML = "";
    for (let i = 0; i < total; i++) {
        const wrapper = document.createElement("div");
        wrapper.className = "name-field";
        const number = document.createElement("span");
        number.className = "name-number";
        number.textContent = i + 1;
        const input = document.createElement("input");
        input.type = "text";
        input.className = "player-name";
        input.maxLength = 40;
        input.placeholder = `Player ${i + 1}`;
        input.value = old[i] || `Player ${i + 1}`;
        wrapper.append(number, input);
        container.appendChild(wrapper);
    }
}

function namesFromForm() {
    return [...document.querySelectorAll(".player-name")].map(input => input.value.trim());
}

let startingGame = false;
async function startGame(event) {
    if (event) event.preventDefault(); // prevent the browser's default form submit (which would cause a 405)
    if (startingGame) return;               // a double click must not send two start requests
    
    clearError();
    const total = Number($("totalPlayers").value);
    const mafia = Number($("mafiaCount").value);
    const names = namesFromForm();
    const villagers = total - mafia - 2;

    if (villagers < 1) {
        error("Invalid setup. At least 1 Villager is required.");
        return;
    }
    if (names.length !== total || names.some(name => !name)) {
        error("Enter a name for every player.");
        return;
    }
    const normalized = names.map(name => name.casefold ? name.casefold() : name.toLowerCase());
    if (new Set(normalized).size !== normalized.length) {
        error("Player names must be unique.");
        return;
    }

    startingGame = true;
    try {
        const result = await api("/api/start", {
            method: "POST",
            body: JSON.stringify({ total_players: total, player_names: names, mafia_count: mafia })
        });
        clearError();
        resetRoleBackgroundDeck();
        pickNextRoleBackground();
        showRoleAssignment(result.current_player);
    } catch (err) {
        error(err.message);
    } finally {
        startingGame = false;
    }
}

function showRoleAssignment(player) {
    show("roleAssignment");
    $("roleAssignmentTitle").textContent = "PASS THE DEVICE";
    $("roleAssignmentMessage").textContent = `Pass the device to ${player.name}.`;
    $("roleAssignmentPlayer").textContent = player.name.toUpperCase();
    $("roleRevealCard").classList.add("hidden");
    $("roleAssignmentStage").classList.remove("hidden");
    $("showRoleButton").classList.remove("hidden");
}

async function showMyRole() {
    clearError();
    try {
        const current = await api("/api/role/current");
        const result = await api("/api/role/show", {
            method: "POST",
            body: JSON.stringify({ player_id: current.player_id })
        });
        $("roleRevealRole").textContent = result.role.toUpperCase();
        $("roleRevealDescription").textContent = roleDescription(result.role);
        const partners = $("mafiaPartners");
        if (result.role === "Mafia") {
            const names = result.mafia_partners || [];
            partners.innerHTML = `<strong>YOUR MAFIA PARTNERS</strong><br>${names.length ? names.map(p => escapeHTML(p.name)).join(", ") : "No other Mafia."}`;
            partners.classList.remove("hidden");
        } else {
            partners.innerHTML = "";
            partners.classList.add("hidden");
        }
        $("roleAssignmentStage").classList.add("hidden"); // hide the "pass the device" card
        $("roleRevealCard").classList.remove("hidden");
        $("showRoleButton").classList.add("hidden");
    } catch (err) {
        error(err.message);
    }
}

async function hideMyRole() {
    clearError();
    try {
        const current = await api("/api/role/current");
        const result = await api("/api/role/complete", {
            method: "POST",
            body: JSON.stringify({ player_id: current.player_id })
        });
        $("roleRevealCard").classList.add("hidden");
        if (result.complete) {
            $("nightIntroTitle").textContent = `NIGHT ${result.night_number}`;
            const state = await api("/api/state");
            renderNightPlayerRoster(state.players);
            show("nightIntro");
        } else {
            $("rolePassPlayer").textContent = result.next_player.name.toUpperCase();
            $("rolePassMessage").textContent = `Pass the device to ${result.next_player.name}.`;
            pickNextRoleBackground();
            show("rolePass");
        }
    } catch (err) {
        error(err.message);
    }
}

function nightPortraitSource(playerId) {
    const id = Number(playerId);
    const portrait = Number.isInteger(id) && id > 0 ? ((id - 1) % NIGHT_PORTRAIT_COUNT) + 1 : 1;
    return `/static/night-player-${portrait}.png`;
}

function renderNightPlayerRoster(players) {
    const roster = $("nightPlayerRoster");
    roster.replaceChildren();
    roster.style.setProperty("--roster-columns", Math.min(players.length, 6));

    players.forEach(player => {
        const card = document.createElement("div");
        card.className = `night-player${player.alive ? "" : " is-out"}`;
        card.setAttribute("aria-label", `${player.name}${player.alive ? "" : ", eliminated"}`);

        const avatar = document.createElement("img");
        avatar.className = "night-player-avatar";
        avatar.src = nightPortraitSource(player.id);
        avatar.alt = "";
        avatar.setAttribute("aria-hidden", "true");

        const name = document.createElement("span");
        name.className = "night-player-name";
        name.textContent = player.name;

        card.append(avatar, name);

        if (!player.alive) {
            const status = document.createElement("span");
            status.className = "night-player-status";
            status.textContent = "OUT";
            card.appendChild(status);
        }

        roster.appendChild(card);
    });
}

async function continueRoleAssignment() {
    try {
        const current = await api("/api/role/current");
        showRoleAssignment({ id: current.player_id, name: current.player_name });
    } catch (err) {
        error(err.message);
    }
}

async function beginNight() {
    clearError();
    try {
        const state = await api("/api/night/current?preview=1");
        showNightPass(state);
    } catch (err) {
        error(err.message);
    }
}

function showNightPass(state) {
    currentNight = state;
    pendingNightChoice = null;
    $("nightPassEyebrow").textContent = `NIGHT ${state.night_number}`;
    $("nightPassPlayer").textContent = state.player_name.toUpperCase();
    $("nightPassMessage").textContent = `Pass the device to ${state.player_name}.`;
    $("nightPassAvatar").src = nightPortraitSource(state.player_id);
    show("nightPass");
}

async function nightReady() {
    clearError();
    try {
        await api("/api/night/ready", {
            method: "POST",
            body: JSON.stringify({ player_id: currentNight.player_id })
        });
        // Private details are fetched only now, after the handover, never while the device is still with the previous player.
        const full = await api("/api/night/current");
        currentNight = full;
        renderNightAction(full);
    } catch (err) {
        error(err.message);
    }
}

function renderNightAction(state) {
    $("nightTitle").textContent = `NIGHT ${state.night_number}`;
    $("nightPlayerName").textContent = state.player_name.toUpperCase();
    $("nightRoleBadge").textContent = state.role.toUpperCase();
    $("nightActorAvatar").src = nightPortraitSource(state.player_id);
    const area = $("nightActionArea");
    area.innerHTML = `<p class="action-instruction">${escapeHTML(state.instruction)}</p>`;
    pendingNightChoice = null;

    if (state.role === "Mafia") {
        const partners = state.mafia_partners || [];
        const partnerText = partners.length ? partners.map(p => escapeHTML(p.name)).join(", ") : "No other Mafia.";
        area.insertAdjacentHTML("beforeend", `<div class="results-card"><div class="result-row"><span class="result-label">Mafia partners</span>${partnerText}</div></div>`);

        const history = state.previous_actions || [];
        if (history.length) {
            const historyCard = document.createElement("div");
            historyCard.className = "results-card previous-actions";
            historyCard.innerHTML = `<div class="result-label">PREVIOUS MAFIA ACTIONS</div>`;
            history.forEach(entry => {
                const row = document.createElement("div");
                row.className = "result-row";
                const shortlist = entry.shortlist?.length
                    ? `Shortlist: ${entry.shortlist.map(p => escapeHTML(p.name)).join(", ")}`
                    : "";
                const target = entry.target ? `Target: ${escapeHTML(entry.target.name)}` : "Target not chosen yet";
                row.innerHTML = `<span class="result-label">${escapeHTML(entry.actor_name)}</span>${shortlist}${shortlist ? " — " : ""}${target}`;
                historyCard.appendChild(row);
            });
            area.appendChild(historyCard);
        }

        if (state.stage === "SHORTLIST") {
            renderMafiaShortlist(area, state.targets || [], state.minimum_shortlist || 2, state.maximum_shortlist || 4);
        } else {
            if (state.shared_shortlist?.length) {
                const list = state.shared_shortlist.map(p => escapeHTML(p.name)).join(", ");
                area.insertAdjacentHTML("beforeend", `<div class="results-card"><div class="result-row"><span class="result-label">SHARED SHORTLIST</span>${list}</div></div>`);
            }
            renderSingleChoice(area, state.targets || [], "Choose victim", choice => confirmNightChoice("mafia", choice));
        }
    } else if (state.role === "Doctor") {
        renderSingleChoice(area, state.targets || [], "Protect", choice => confirmNightChoice("doctor", choice));
        if (!state.self_save_available) {
            area.querySelectorAll(".player-choice").forEach((button, index) => {
                if ((state.targets || [])[index] && state.targets[index].id === state.player_id) {
                    button.disabled = true;
                    button.title = "Your one self-save has already been used.";
                }
            });
        }
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent = state.self_save_available
            ? "Your one self-save is available tonight."
            : "Your one self-save has already been used.";
        area.appendChild(note);
    } else if (state.role === "Detective") {
        renderSingleChoice(area, state.targets || [], "Investigate", choice => confirmNightChoice("detective", choice));
    } else {
        const grid = document.createElement("div");
        grid.className = "selection-grid";
        state.activities.forEach(activity => {
            const button = document.createElement("button");
            button.className = "choice";
            button.type = "button";
            button.textContent = activity;
            button.addEventListener("click", () => confirmNightChoice("villager", activity));
            grid.appendChild(button);
        });
        area.appendChild(grid);
    }
    show("night");
}

function renderSingleChoice(container, players, actionWord, callback) {
    const grid = document.createElement("div");
    grid.className = "selection-grid";
    players.forEach(player => {
        const button = createNightPlayerChoice(player, actionWord);
        button.addEventListener("click", () => {
            grid.querySelectorAll(".choice").forEach(item => item.classList.remove("selected"));
            button.classList.add("selected");
            callback(player);
        });
        grid.appendChild(button);
    });
    container.appendChild(grid);
}

function createNightPlayerChoice(player, actionWord) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice player-choice";
    button.setAttribute("aria-label", `${player.name}: ${actionWord}`);

    const avatar = document.createElement("img");
    avatar.className = "choice-avatar";
    avatar.src = nightPortraitSource(player.id);
    avatar.alt = "";
    avatar.setAttribute("aria-hidden", "true");

    const name = document.createElement("span");
    name.className = "choice-player-name";
    name.textContent = player.name;

    const action = document.createElement("span");
    action.className = "choice-action";
    action.textContent = actionWord;

    button.append(avatar, name, action);
    return button;
}

function confirmNightChoice(kind, value) {
    pendingNightChoice = { kind, value };
    const area = $("nightActionArea");
    const old = $("nightContinueButton");
    if (old) old.remove();

    const button = document.createElement("button");
    button.id = "nightContinueButton";
    button.type = "button";
    button.className = "primary continue-action";
    button.textContent = "CONTINUE";
    button.addEventListener("click", () => commitNightChoice());
    area.appendChild(button);
}

function renderMafiaShortlist(container, players, minimum, maximum) {
    const grid = document.createElement("div");
    grid.className = "selection-grid shortlist-grid";
    const selected = new Set();

    players.forEach(player => {
        const button = createNightPlayerChoice(player, "SHORTLIST");
        button.addEventListener("click", () => {
            if (selected.has(player.id)) {
                selected.delete(player.id);
                button.classList.remove("selected");
            } else {
                if (selected.size >= maximum) return;
                selected.add(player.id);
                button.classList.add("selected");
            }
            updateShortlistContinue(container, selected, minimum, maximum);
        });
        grid.appendChild(button);
    });
    container.appendChild(grid);
    updateShortlistContinue(container, selected, minimum, maximum);
}

function updateShortlistContinue(container, selected, minimum, maximum) {
    let button = $("nightContinueButton");
    if (button) button.remove();

    button = document.createElement("button");
    button.id = "nightContinueButton";
    button.type = "button";
    button.className = "primary continue-action";
    button.textContent = selected.size >= minimum
        ? `CONTINUE — SAVE ${selected.size} PLAYERS`
        : `SELECT AT LEAST ${minimum} PLAYERS`;
    button.disabled = selected.size < minimum;
    button.addEventListener("click", () => {
        pendingNightChoice = { kind: "mafiaShortlist", value: [...selected] };
        commitNightChoice();
    });
    container.appendChild(button);
}

async function commitNightChoice() {
    if (!pendingNightChoice) return;
    const choice = pendingNightChoice;
    pendingNightChoice = null;
    const button = $("nightContinueButton");
    if (button) button.disabled = true;

    try {
        let endpoint;
        let body;
        if (choice.kind === "mafiaShortlist") {
            endpoint = "/api/night/mafia/shortlist";
            body = { actor_id: currentNight.player_id, candidate_ids: choice.value };
        } else if (choice.kind === "villager") {
            endpoint = "/api/night/villager";
            body = { actor_id: currentNight.player_id, activity: choice.value };
        } else {
            endpoint = choice.kind === "mafia"
                ? "/api/night/mafia/vote"
                : choice.kind === "doctor"
                    ? "/api/night/doctor"
                    : "/api/night/detective";
            body = { actor_id: currentNight.player_id, target_id: choice.value.id };
        }

        const result = await api(endpoint, {
            method: "POST",
            body: JSON.stringify(body)
        });

        if (choice.kind === "mafiaShortlist") {
            const nextState = await api("/api/night/current");
            renderNightAction(nextState);
            return;
        }

        if (choice.kind === "detective") {
            showPrivateDetectiveResult(result);
            return;
        }

        await afterNightAction(result);
    } catch (err) {
        pendingNightChoice = choice;
        const retry = $("nightContinueButton");
        if (retry) retry.disabled = false;
        error(err.message);
    }
}

function showPrivateDetectiveResult(result) {
    const area = $("nightActionArea");
    area.innerHTML = `
        <div class="role-card">
            <p class="eyebrow">PRIVATE INVESTIGATION RESULT</p>
            <h2>${escapeHTML(result.private_result)}</h2>
            <p>This information is private. Do not show it to anyone else.</p>
            <button id="hideDetectiveResult" class="primary" type="button">HIDE RESULT & CONTINUE</button>
        </div>`;
    $("hideDetectiveResult").addEventListener("click", () => afterNightAction(result));
    show("night");
}

async function afterNightAction(result) {
    if (result.complete) {
        await showMorning();
        return;
    }

    try {
        const state = await api("/api/night/current?preview=1");
        showNightPass(state);
    } catch (err) {
        error(err.message);
    }
}

async function showMorning() {
    try {
        const result = await api("/api/night/morning");
        $("morningTitle").textContent = `MORNING ${result.night_number}`;
        const box = $("morningResults");
        let html = "";

        if (result.mafia_target) {
            const survived = !result.killed_player;
            html += `<div class="result-row result-danger"><span class="result-label">Mafia kill</span>${escapeHTML(result.mafia_target.name)} was targeted by the Mafia${survived ? " and survived." : "."}</div>`;
        } else {
            html += `<div class="result-row"><span class="result-label">Mafia kill</span>No Mafia kill was selected.</div>`;
        }

        if (result.saved_player) {
            html += `<div class="result-row result-good"><span class="result-label">Doctor save</span>${escapeHTML(result.saved_player.name)} was chosen by the Doctor for protection.</div>`;
        } else {
            html += `<div class="result-row"><span class="result-label">Doctor save</span>No protection was selected.</div>`;
        }

        if (result.detective_found_mafia) {
            html += `<div class="result-row result-danger"><span class="result-label">Detective</span>Detective found Mafia is ${escapeHTML(result.detective_found_mafia.name)}.</div>`;
        } else if (result.detective_out) {
            html += `<div class="result-row"><span class="result-label">Detective</span>The Detective is out of the game.</div>`;
        } else {
            html += `<div class="result-row result-good"><span class="result-label">Detective</span>The Detective is working. Trust him!</div>`;
        }

        box.innerHTML = html;
        const button = $("beginDiscussionButton");
        button.textContent = result.game_over ? "VIEW GAME RESULT" : "BEGIN DISCUSSION";
        morningResult = result;
        show("morning");
    } catch (err) {
        error(err.message);
    }
}

function onMorningButton() {
    if (morningResult && morningResult.game_over) {
        showGameOver(morningResult.winner, morningResult.players);
    } else {
        beginDiscussion();
    }
}

async function beginDiscussion(resumeRemaining) {
    clearError();
    try {
        await api("/api/day/discussion-start", { method: "POST" });
        const state = await api("/api/day/current");
        discussionRemaining = typeof resumeRemaining === "number" ? resumeRemaining : 180;
        $("discussionDay").textContent = state.day_number;
        show("discussion");
        updateTimer();
        clearInterval(discussionTimer);
        discussionTimer = setInterval(async () => {
            discussionRemaining -= 1;
            updateTimer();
            if (discussionRemaining <= 0) {
                clearInterval(discussionTimer);
                await startVoting();
            }
        }, 1000);
    } catch (err) {
        error(err.message);
    }
}

function updateTimer() {
    const min = String(Math.max(0, Math.floor(discussionRemaining / 60))).padStart(2, "0");
    const sec = String(Math.max(0, discussionRemaining % 60)).padStart(2, "0");
    $("discussionTimer").textContent = `${min}:${sec}`;
}

async function startVoting() {
    clearInterval(discussionTimer);
    if (votingStarting) return;          // button click + timer can both fire
    votingStarting = true;
    clearError();
    try {
        await api("/api/day/start-voting", { method: "POST" });
        const state = await api("/api/day/current?preview=1");
        if (state.phase === "GAME_OVER") {
            showGameOver(state.winner, state.players);
            return;
        }
        if (!state.voter) {
            throw new Error("Voting started but no voter was found.");
        }
        currentVoter = state.voter;
        showVotePass(state);
    } catch (err) {
        error(err.message);
    } finally {
        votingStarting = false;
    }
}

function showVotePass(state) {
    $("votePassPlayer").textContent = state.voter.name.toUpperCase();
    $("votePassEyebrow").textContent =
        `DAY ${state.day_number} VOTING — VOTER ${state.voter_number} OF ${state.voter_total}`;
    show("votePass");
}

async function voteReady() {
    clearError();
    try {
        const state = await api("/api/day/current");
        currentVoter = state.voter;
        renderVoting(state);
    } catch (err) {
        error(err.message);
    }
}

function renderVoting(state) {
    $("votingEyebrow").textContent = `DAY ${state.day_number} — VOTE`;
    $("votingPlayer").textContent = state.voter.name.toUpperCase();
    $("votingAvatar").src = nightPortraitSource(state.voter.id);
    const area = $("votingArea");
    area.innerHTML = `<p class="action-instruction">Choose one player to eliminate.</p>`;
    const forbidden = new Set(state.forbidden_target_ids || []);
    const legal = state.players.filter(player =>
        player.alive &&
        player.id !== state.voter.id &&
        !forbidden.has(player.id)
    );

    const grid = document.createElement("div");
    grid.className = "selection-grid";
    legal.forEach(player => {
        const button = createNightPlayerChoice(player, "Eliminate");
        button.addEventListener("click", () => confirmVote(state.voter.id, player.id, button));
        grid.appendChild(button);
    });
    area.appendChild(grid);

    if (!legal.length) {
        grid.innerHTML = `<p class="muted">There is no legal vote available for this player.</p>`;
    }
    show("voting");
}

function confirmVote(voterId, targetId, selectedButton) {
    const area = $("votingArea");
    area.querySelectorAll(".choice").forEach(button => button.classList.remove("selected"));
    selectedButton.classList.add("selected");

    let continueButton = $("voteContinueButton");
    if (continueButton) continueButton.remove();
    continueButton = document.createElement("button");
    continueButton.id = "voteContinueButton";
    continueButton.type = "button";
    continueButton.className = "primary continue-action";
    continueButton.textContent = "CONTINUE";
    continueButton.addEventListener("click", () => castVote(voterId, targetId));
    area.appendChild(continueButton);
}

async function castVote(voterId, targetId) {
    const button = $("voteContinueButton");
    if (button) button.disabled = true;
    try {
        const result = await api("/api/day/vote", {
            method: "POST",
            body: JSON.stringify({ voter_id: voterId, target_id: targetId })
        });
        if (!result.complete) {
            const state = await api("/api/day/current?preview=1");
            showVotePass(state);
            return;
        }
        showElimination(result);
    } catch (err) {
        if (button) button.disabled = false;
        error(err.message);
    }
}

function showElimination(result) {
    const eliminated = result.eliminated_player;
    if (!eliminated) {
        showGameOver(result.winner, result.players || []);
        return;
    }
    $("eliminationTitle").textContent = `${eliminated.name.toUpperCase()} HAS BEEN ELIMINATED`;
    $("eliminatedName").textContent = eliminated.name.toUpperCase();
    $("eliminatedRole").textContent = `ACTUAL ROLE: ${eliminated.role.toUpperCase()}`;
    $("tieMessage").textContent = result.tie
        ? "There was a tie. The computer moderator chose randomly from the tied players."
        : "The player with the most votes was eliminated.";
    $("continueGameButton").textContent = result.game_over ? "VIEW GAME RESULT" : "BEGIN NEXT NIGHT";
    $("continueGameButton").disabled = false;
    $("continueGameButton").onclick = async () => {
        if (result.game_over) {
            showGameOver(result.winner, result.players || []);
            return;
        }
        const button = $("continueGameButton");
        button.disabled = true;
        clearError();
        try {
            // Moves ELIMINATION -> NIGHT on the server. Never calls /api/start.
            const next = await api("/api/day/continue", { method: "POST" });
            $("nightIntroTitle").textContent = `NIGHT ${next.night_number}`;
            renderNightPlayerRoster(next.players);
            show("nightIntro");
        } catch (err) {
            button.disabled = false;
            error(err.message);
        }
    };
    show("elimination");
}

function showGameOver(winner, players) {
    $("gameOver").classList.toggle("mafia-won", winner === "Mafia");
    $("gameOver").classList.toggle("civilians-won", winner !== "Mafia");
    $("gameOverTitle").textContent = winner === "Mafia"
        ? "THE MAFIA WINS!"
        : "THE CIVILIANS WIN!";
    $("gameOverMessage").textContent = winner === "Mafia"
        ? "The Mafia has successfully taken control of the town."
        : "All members of the Mafia have been successfully eliminated. The town is safe!";
    const list = players || [];
    $("finalPlayers").innerHTML = list.map(player => {
        const role = player.role || "Unknown";
        return `<div class="final-player">
            <span>${escapeHTML(player.name)}</span>
            <span class="final-role role-${escapeHTML(role)}">${escapeHTML(role.toUpperCase())}</span>
            <span class="${player.alive ? "is-alive" : "is-out"}">${player.alive ? "ALIVE" : "OUT"}</span>
        </div>`;
    }).join("");
    show("gameOver");
}

// After a page reload the server still holds the game; put the player back on the right screen.
async function resumeGame() {
    try {
        const state = await api("/api/state");
        switch (state.phase) {
            case "ROLE_ASSIGNMENT": {
                const current = await api("/api/role/current");
                resetRoleBackgroundDeck();
                pickNextRoleBackground();
                showRoleAssignment({ id: current.player_id, name: current.player_name });
                break;
            }
            case "NIGHT": {
                try {
                    showNightPass(await api("/api/night/current?preview=1"));
                } catch (err) {
                    await showMorning(); // every night action is done; only the morning report is left
                }
                break;
            }
            case "DISCUSSION": {
                const day = await api("/api/day/current");
                if (!day.discussion_active) {
                    await showMorning();
                } else if (day.discussion_seconds_remaining > 0) {
                    await beginDiscussion(day.discussion_seconds_remaining);
                } else {
                    await startVoting();
                }
                break;
            }
            case "VOTING":
                showVotePass(await api("/api/day/current?preview=1"));
                currentVoter = null;
                break;
            case "ELIMINATION":
                showElimination(await api("/api/day/elimination"));
                break;
            case "GAME_OVER":
                showGameOver(state.winner, state.players);
                break;
            default:
                break; // SETUP: stay on the setup screen
        }
    } catch (err) {
        // Resuming is best effort; the setup screen is always a safe fallback.
    }
}

let restarting = false;
async function resetForNewGame() {
    if (restarting) return;                 // repeated clicks must not fire repeated resets
    restarting = true;
    const button = $("restartButton");
    if (button) button.disabled = true;
    try {
        // The server keeps the finished game so a refresh can resume it; NEW GAME must discard it explicitly.
        await api("/api/new-game", { method: "POST" });
        window.location.reload();
    } catch (err) {
        restarting = false;
        if (button) button.disabled = false;
        error(err.message);
    }
}

function bind() {
    for (let n = 6; n <= 15; n++) {
        const option = document.createElement("option");
        option.value = n;
        option.textContent = n;
        $("totalPlayers").appendChild(option);
    }
    $("totalPlayers").value = "6";
    $("totalPlayers").addEventListener("change", updateSetup);
    $("mafiaCount").addEventListener("change", updateSetup);
    $("startGameButton").addEventListener("click", startGame);
    $("showRoleButton").addEventListener("click", showMyRole);
    $("hideRoleButton").addEventListener("click", hideMyRole);
    $("nextRoleButton").addEventListener("click", continueRoleAssignment);
    $("beginNightButton").addEventListener("click", beginNight);
    $("nightReadyButton").addEventListener("click", nightReady);
    $("beginDiscussionButton").addEventListener("click", onMorningButton);
    $("startVotingButton").addEventListener("click", startVoting);
    $("voteReadyButton").addEventListener("click", voteReady);
    $("restartButton").addEventListener("click", resetForNewGame);
    updateSetup();
    resumeGame();
}

document.addEventListener("DOMContentLoaded", bind);