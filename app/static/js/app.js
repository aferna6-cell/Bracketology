// Bracketology - NCAA Tournament Projection App
let _bracketData = null;
let _watchlist = new Set();
let _scoreboardData = [];
let _scoreboardDateKey = null;

document.addEventListener("DOMContentLoaded", () => {
    setupTabs();
    loadWatchlist();
    loadBracket();
    initScoreboard();
});

// ─── Tabs ────────────────────────────────────────────────────
function setupTabs() {
    document.querySelectorAll(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            tab.classList.add("active");
            const target = document.getElementById("tab-" + tab.dataset.tab);
            if (target) target.classList.add("active");
            if (tab.dataset.tab === "history") loadHistory();
        });
    });
}

// ─── Load Bracket ────────────────────────────────────────────
async function loadBracket() {
    try {
        const resp = await fetch("/api/bracket");
        if (resp.status === 404) {
            showLoading("Fetching data from ESPN for the first time...");
            pollForData();
            return;
        }
        const data = await resp.json();
        _bracketData = data;
        renderAll(data);
    } catch (err) {
        showToast("Failed to load bracket: " + err.message);
    }
}

async function pollForData() {
    for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 3000));
        try {
            const resp = await fetch("/api/bracket");
            if (resp.ok) {
                hideLoading();
                const data = await resp.json();
                _bracketData = data;
                renderAll(data);
                return;
            }
        } catch (e) { /* keep waiting */ }
    }
    hideLoading();
    showToast("Data fetch is taking longer than expected. Try clicking Update Now.");
}

function renderAll(data) {
    if (!data || !data.regions) return;
    document.getElementById("last-updated").textContent = "Updated: " + (data.timestamp || "");

    // Show recent changes banner
    renderChangesBanner(data.changes || []);

    for (const r of ["South", "East", "West", "Midwest"]) renderRegion(r, data.regions[r] || []);
    renderFirstFour(data.first_four || []);
    renderSeedList(data);
    renderBubble(data);
    renderP5Status(data.p5_status || {});
    renderConferences(data.conference_breakdown || {});
    populateWhatIfTeams(data);
    if (_scoreboardData.length) {
        renderScoreboard(_scoreboardData, _scoreboardDateKey);
    }
}

// ─── Changes Banner ──────────────────────────────────────────
function renderChangesBanner(changes) {
    const el = document.getElementById("changes-banner");
    if (!changes.length || (changes.length === 1 && changes[0].type === "initial")) {
        el.classList.add("hidden");
        return;
    }
    const msgs = changes.slice(0, 5).map(c =>
        `<span class="change-chip ${c.type}">${c.message}</span>`
    ).join("");
    el.innerHTML = `<strong>Recent changes:</strong> ${msgs}`;
    el.classList.remove("hidden");
}

// ─── Update ──────────────────────────────────────────────────
async function triggerUpdate() {
    const btn = document.getElementById("btn-update");
    btn.disabled = true;
    showLoading("Fetching data from ESPN...");
    try {
        const resp = await fetch("/api/update", { method: "POST" });
        const data = await resp.json();
        if (data.status === "ok") {
            await loadBracket();
            if (data.errors && data.errors.length) showToast("Warnings: " + data.errors.join("; "));
        } else {
            showToast("Update failed: " + (data.errors || []).join("; ") || "Unknown error");
        }
    } catch (err) {
        showToast("Update error: " + err.message);
    } finally {
        btn.disabled = false;
        hideLoading();
    }
}

// ─── Bracket Regions ─────────────────────────────────────────
function renderRegion(regionName, entries) {
    const container = document.querySelector(`#region-${regionName} .region-matchups`);
    if (!container) return;
    entries.sort((a, b) => a.seed - b.seed);
    const matchupOrder = [[1,16],[8,9],[5,12],[4,13],[6,11],[3,14],[7,10],[2,15]];
    const bySeeds = {};
    entries.forEach(e => { bySeeds[e.seed] = e; });
    let html = "";
    for (const [s1, s2] of matchupOrder) {
        html += matchupRow(bySeeds[s1], s1) + matchupRow(bySeeds[s2], s2);
    }
    container.innerHTML = html;
}

function matchupRow(t, seed) {
    const name = t ? teamLink(t) : "TBD";
    const info = t ? t.record || "" : "";
    const badge = t ? (t.is_auto_bid ? `<span class="bid bid-auto">AUTO</span>` : `<span class="bid bid-al">AL</span>`) : "";
    const watched = t && _watchlist.has(t.team_id) ? " watched" : "";
    const seedClass = seed <= 4 ? ` seed-${seed}` : "";
    return `<div class="matchup${watched}">
        <span class="matchup-seed${seedClass}">${seed}</span>
        <span class="matchup-team">${name}</span>
        <span class="matchup-info">${info}</span>${badge}
    </div>`;
}

function teamLink(entry) {
    const id = entry.team_id;
    let name = entry.team_name || "Unknown";
    if (entry.is_first_four && entry.first_four_opponent) {
        name += ` / ${entry.first_four_opponent.team_name}`;
    }
    return `<a href="#" class="team-link" onclick="openTeamModal(${id});return false">${name}</a>`;
}

function renderFirstFour(games) {
    const container = document.getElementById("first-four-games");
    if (!games.length) { container.innerHTML = "<p class='info-text'>No First Four data.</p>"; return; }
    let html = "";
    for (const game of games) {
        const [t1, t2] = game.game || [];
        html += `<div class="ff-game">
            <span class="ff-seed">#${game.seed}</span>
            <span>${t1 ? teamLink(t1) : "TBD"} (${t1?.record || ""})</span>
            <span class="ff-vs">vs</span>
            <span>${t2 ? teamLink(t2) : "TBD"} (${t2?.record || ""})</span>
            <span class="ff-region">${game.region}</span>
        </div>`;
    }
    container.innerHTML = html;
}

// ─── Seed List ───────────────────────────────────────────────
function renderSeedList(data) {
    const container = document.getElementById("seed-list");
    if (!container) return;
    const all = [];
    for (const entries of Object.values(data.regions || {})) entries.forEach(e => all.push(e));
    for (const g of data.first_four || []) (g.game || []).forEach(e => { if (e) all.push(e); });
    all.sort((a, b) => a.seed !== b.seed ? a.seed - b.seed : (b.rating || 0) - (a.rating || 0));

    let html = `<div class="seed-row seed-header"><span>Seed</span><span>Team</span><span>Conf</span><span>Record</span><span>Region</span></div>`;
    for (const t of all) {
        const ff = t.is_first_four ? " (FF)" : "";
        const w = _watchlist.has(t.team_id) ? " watched" : "";
        html += `<div class="seed-row${w}">
            <span class="seed-num">${t.seed}</span>
            <span class="team-name">${teamLink(t)}${ff}</span>
            <span class="conference">${t.conference} [${t.is_auto_bid ? "AUTO" : "AL"}]</span>
            <span class="record">${t.record}</span>
            <span class="region-label">${t.region}</span>
        </div>`;
    }
    container.innerHTML = html;
}

// ─── Bubble Watch with Bubble Meter ──────────────────────────
function renderBubble(data) {
    renderBubbleList("last-four-in", data.last_four_in || [], "in");
    renderBubbleList("first-four-out", data.first_four_out || [], "out");
    renderBubbleList("next-four-out", data.next_four_out || [], "out");
}

function renderBubbleList(id, teams, side) {
    const container = document.getElementById(id);
    if (!teams.length) { container.innerHTML = "<p class='info-text'>No data.</p>"; return; }
    let html = "";
    for (const t of teams) {
        const score = t.bubble_score || 50;
        const color = score >= 60 ? "#2ecc71" : score >= 40 ? "#f39c12" : "#e74c3c";
        html += `<div class="bubble-team">
            <span class="team-name">${teamLink(t)}</span>
            <span>${t.conference}</span>
            <span>${t.record}</span>
            <div class="bubble-meter"><div class="bubble-fill" style="width:${score}%;background:${color}"></div><span class="bubble-label">${Math.round(score)}</span></div>
        </div>`;
    }
    container.innerHTML = html;
}

// ─── P5 Status ───────────────────────────────────────────────
function renderP5Status(p5) {
    const container = document.getElementById("p5-status-list");
    const entries = Object.entries(p5);
    if (!entries.length) { container.innerHTML = "<p class='info-text'>No data. Run an update.</p>"; return; }
    const order = ["lock", "safe", "bubble_in", "auto_bid", "bubble_out", "eliminated"];
    entries.sort((a, b) => (order.indexOf(a[1]) - order.indexOf(b[1])) || a[0].localeCompare(b[0]));
    const labels = { lock: "LOCK", safe: "SAFE", bubble_in: "BUBBLE IN", bubble_out: "BUBBLE OUT", eliminated: "ELIMINATED", auto_bid: "AUTO-BID" };
    let html = "";
    for (const [team, status] of entries) {
        html += `<div class="p5-team status-${status}">
            <span class="team-name">${team}</span>
            <span class="status-badge ${status}">${labels[status] || status}</span>
        </div>`;
    }
    container.innerHTML = html;
}

// ─── Conference Breakdown ────────────────────────────────────
function renderConferences(breakdown) {
    const container = document.getElementById("conference-list");
    if (!Object.keys(breakdown).length) { container.innerHTML = "<p class='info-text'>No data.</p>"; return; }

    // Power conferences first
    const sorted = Object.entries(breakdown).sort((a, b) => {
        if (a[1].is_power !== b[1].is_power) return a[1].is_power ? -1 : 1;
        return a[0].localeCompare(b[0]);
    });

    let html = "";
    for (const [conf, data] of sorted) {
        const power = data.is_power ? " power-conf" : "";
        const autobid = data.auto_bid
            ? `<div class="conf-autobid"><span class="badge-auto">AUTO-BID</span> ${data.auto_bid.name} (${data.auto_bid.record})</div>`
            : `<div class="conf-autobid muted">No auto-bid projected</div>`;
        const atLarge = data.at_large.map(t =>
            `<span class="conf-team-chip at-large" onclick="openTeamModal(${t.id})">${t.name} (${t.record})</span>`
        ).join("");
        const bubble = data.bubble.map(t =>
            `<span class="conf-team-chip ${t.status}" onclick="openTeamModal(${t.id})">${t.name} (${t.record})</span>`
        ).join("");

        html += `<div class="conf-card${power}">
            <div class="conf-header"><h3>${conf}</h3><span class="conf-count">${data.total} teams</span></div>
            ${autobid}
            ${atLarge ? `<div class="conf-section"><span class="conf-label">At-Large:</span>${atLarge}</div>` : ""}
            ${bubble ? `<div class="conf-section"><span class="conf-label">Bubble:</span>${bubble}</div>` : ""}
        </div>`;
    }
    container.innerHTML = html;
}

// ─── Scoreboard ──────────────────────────────────────────────
function initScoreboard() {
    const dateInput = document.getElementById("scoreboard-date");
    const prevBtn = document.getElementById("scoreboard-prev");
    const nextBtn = document.getElementById("scoreboard-next");
    if (!dateInput || !prevBtn || !nextBtn) return;

    dateInput.addEventListener("change", () => {
        const dateKey = (dateInput.value || "").replace(/-/g, "");
        loadScoreboard(dateKey);
    });
    prevBtn.addEventListener("click", () => shiftScoreboardDate(-1));
    nextBtn.addEventListener("click", () => shiftScoreboardDate(1));
    loadScoreboard();
}

function shiftScoreboardDate(delta) {
    if (!_scoreboardDateKey) return;
    const date = parseDateKey(_scoreboardDateKey);
    date.setDate(date.getDate() + delta);
    loadScoreboard(formatDateKey(date));
}

async function loadScoreboard(dateKey = null) {
    const container = document.getElementById("scoreboard-list");
    if (container) container.innerHTML = "<p class='info-text'>Loading scoreboard...</p>";
    const url = dateKey ? `/api/scoreboard?date=${dateKey}` : "/api/scoreboard";

    try {
        const resp = await fetch(url);
        const data = await resp.json();
        _scoreboardDateKey = data.date || dateKey;
        _scoreboardData = data.games || [];
        syncScoreboardDateInput(_scoreboardDateKey);
        renderScoreboard(_scoreboardData, _scoreboardDateKey, data.error);
    } catch (err) {
        if (container) {
            container.innerHTML = `<p class='info-text'>Scoreboard error: ${err.message}</p>`;
        }
    }
}

function renderScoreboard(games, dateKey, errorMessage = null) {
    const container = document.getElementById("scoreboard-list");
    if (!container) return;

    if (errorMessage) {
        container.innerHTML = `<p class='info-text'>${errorMessage}</p>`;
        return;
    }

    if (!games.length) {
        container.innerHTML = "<p class='info-text'>No games found for this date.</p>";
        return;
    }

    const fieldTeams = getFieldTeamIds();
    const ratingsMap = getRatingsMap();

    const cards = games.map(game => {
        const status = game.status || "Scheduled";
        const home = game.home || {};
        const away = game.away || {};
        const isFinal = status === "Final";
        const winner = isFinal ? getWinner(home, away) : null;
        const upset = isFinal && isUpsetResult(home, away, ratingsMap);

        return `<div class="scoreboard-card">
            <div class="scoreboard-status">
                <span class="status-text">${status}</span>
                ${upset ? `<span class="scoreboard-badge upset">UPSET</span>` : ""}
            </div>
            <div class="scoreboard-team ${fieldTeams.has(away.id) ? "in-field" : ""}">
                ${renderScoreboardTeam(away, winner)}
                ${fieldTeams.has(away.id) ? `<span class="scoreboard-badge in">IN</span>` : ""}
            </div>
            <div class="scoreboard-team ${fieldTeams.has(home.id) ? "in-field" : ""}">
                ${renderScoreboardTeam(home, winner)}
                ${fieldTeams.has(home.id) ? `<span class="scoreboard-badge in">IN</span>` : ""}
            </div>
        </div>`;
    }).join("");

    container.innerHTML = cards;
}

function renderScoreboardTeam(team, winner) {
    const name = team.name || "TBD";
    const score = team.score !== undefined ? team.score : "-";
    const winnerClass = winner && winner.id === team.id ? "winner" : "";
    if (team.id) {
        return `<button class="scoreboard-team-link ${winnerClass}" onclick="openTeamModal(${team.id})">
            <span class="team-name">${name}</span>
            <span class="team-score">${score}</span>
        </button>`;
    }
    return `<div class="scoreboard-team-link ${winnerClass}">
        <span class="team-name">${name}</span>
        <span class="team-score">${score}</span>
    </div>`;
}

function getWinner(home, away) {
    if (home.score === undefined || away.score === undefined) return null;
    if (home.score === away.score) return null;
    return home.score > away.score ? home : away;
}

function isUpsetResult(home, away, ratingsMap) {
    if (!ratingsMap.size) return false;
    const homeRating = ratingsMap.get(home.id);
    const awayRating = ratingsMap.get(away.id);
    if (homeRating === undefined || awayRating === undefined) return false;
    const winner = getWinner(home, away);
    if (!winner) return false;
    const loser = winner.id === home.id ? away : home;
    const winnerRating = ratingsMap.get(winner.id);
    const loserRating = ratingsMap.get(loser.id);
    return winnerRating < loserRating;
}

function getFieldTeamIds() {
    const ids = new Set();
    if (!_bracketData) return ids;
    for (const entries of Object.values(_bracketData.regions || {})) {
        entries.forEach(e => ids.add(e.team_id));
    }
    for (const g of _bracketData.first_four || []) {
        (g.game || []).forEach(e => { if (e) ids.add(e.team_id); });
    }
    return ids;
}

function getRatingsMap() {
    const ratings = new Map();
    if (!_bracketData) return ratings;
    for (const entries of Object.values(_bracketData.regions || {})) {
        entries.forEach(e => ratings.set(e.team_id, e.rating));
    }
    for (const g of _bracketData.first_four || []) {
        (g.game || []).forEach(e => { if (e) ratings.set(e.team_id, e.rating); });
    }
    return ratings;
}

function syncScoreboardDateInput(dateKey) {
    const dateInput = document.getElementById("scoreboard-date");
    if (!dateInput || !dateKey) return;
    const date = parseDateKey(dateKey);
    dateInput.value = date.toISOString().slice(0, 10);
}

function parseDateKey(dateKey) {
    const year = parseInt(dateKey.slice(0, 4));
    const month = parseInt(dateKey.slice(4, 6)) - 1;
    const day = parseInt(dateKey.slice(6, 8));
    return new Date(year, month, day);
}

function formatDateKey(date) {
    const y = date.getFullYear().toString();
    const m = (date.getMonth() + 1).toString().padStart(2, "0");
    const d = date.getDate().toString().padStart(2, "0");
    return `${y}${m}${d}`;
}

// ─── What-If Simulator ───────────────────────────────────────
function populateWhatIfTeams(data) {
    const select = document.getElementById("whatif-team");
    if (!select) return;
    const all = [];
    for (const entries of Object.values(data.regions || {})) entries.forEach(e => all.push(e));
    for (const g of data.first_four || []) (g.game || []).forEach(e => { if (e) all.push(e); });
    for (const e of (data.last_four_in || [])) all.push(e);
    for (const e of (data.first_four_out || [])) all.push(e);
    all.sort((a, b) => (a.team_name || "").localeCompare(b.team_name || ""));

    const seen = new Set();
    let html = "";
    for (const t of all) {
        if (seen.has(t.team_id)) continue;
        seen.add(t.team_id);
        html += `<option value="${t.team_id}">${t.team_name} (${t.record})</option>`;
    }
    select.innerHTML = html;
}

async function runWhatIf(addW, addL) {
    const teamId = parseInt(document.getElementById("whatif-team").value);
    if (!teamId) return;
    const container = document.getElementById("whatif-result");
    container.innerHTML = "<p class='info-text'>Simulating...</p>";

    try {
        const resp = await fetch("/api/whatif", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ team_id: teamId, add_wins: addW, add_losses: addL }),
        });
        const sim = await resp.json();
        if (sim.error) { container.innerHTML = `<p class="info-text">${sim.error}</p>`; return; }

        // Find where the team ended up
        let teamEntry = null;
        for (const entries of Object.values(sim.regions || {})) {
            for (const e of entries) {
                if (e.team_id === teamId) { teamEntry = e; break; }
            }
            if (teamEntry) break;
        }
        if (!teamEntry) {
            for (const g of sim.first_four || []) {
                for (const e of g.game || []) {
                    if (e && e.team_id === teamId) { teamEntry = e; break; }
                }
            }
        }

        let html = `<div class="whatif-summary">`;
        if (teamEntry) {
            html += `<h3>${teamEntry.team_name}</h3>
                <p>Projected: <strong>Seed ${teamEntry.seed}</strong> in ${teamEntry.region} Region</p>
                <p>Record: ${teamEntry.record} | Rating: ${teamEntry.rating}</p>`;
        } else {
            const name = document.getElementById("whatif-team").selectedOptions[0]?.text || "Team";
            html += `<h3>${name}</h3><p>Not projected in the field with this scenario.</p>`;
        }
        html += `</div>`;

        // Show 1-seeds
        html += `<div class="whatif-seeds"><h4>1-Seeds in this scenario:</h4>`;
        for (const [region, entries] of Object.entries(sim.regions || {})) {
            const one = entries.find(e => e.seed === 1);
            if (one) html += `<p>${region}: ${one.team_name} (${one.record})</p>`;
        }
        html += `</div>`;
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p class="info-text">Error: ${err.message}</p>`;
    }
}

function resetWhatIf() {
    document.getElementById("whatif-result").innerHTML = "";
}

// ─── Team Detail Modal ───────────────────────────────────────
async function openTeamModal(teamId) {
    const modal = document.getElementById("team-modal");
    const body = document.getElementById("modal-body");
    modal.classList.remove("hidden");
    body.innerHTML = "<p>Loading...</p>";

    try {
        const resp = await fetch(`/api/team/${teamId}`);
        const t = await resp.json();
        if (t.error) { body.innerHTML = `<p>${t.error}</p>`; return; }

        const isWatched = _watchlist.has(teamId);
        const watchBtn = isWatched
            ? `<button class="btn-secondary" onclick="toggleWatch(${teamId})">Remove from Watch List</button>`
            : `<button onclick="toggleWatch(${teamId})">Add to Watch List</button>`;

        body.innerHTML = `
            <h2>${t.name}</h2>
            <p class="modal-subtitle">${t.conference} | Standing: #${t.conference_standing} ${t.is_conference_champ ? "(Conf. Leader)" : ""}</p>
            <div class="modal-grid">
                <div class="modal-stat"><label>Record</label><span>${t.record}</span></div>
                <div class="modal-stat"><label>Conf Record</label><span>${t.conf_record}</span></div>
                <div class="modal-stat"><label>Win %</label><span>${(t.win_pct * 100).toFixed(1)}%</span></div>
                <div class="modal-stat"><label>AP Ranking</label><span>${t.net_ranking || "NR"}</span></div>
                <div class="modal-stat"><label>Rating</label><span>${t.rating}</span></div>
                <div class="modal-stat"><label>Road Record</label><span>${t.road_record}</span></div>
                <div class="modal-stat"><label>vs Ranked</label><span>${t.vs_ranked}</span></div>
                <div class="modal-stat"><label>Streak</label><span>${t.streak}</span></div>
                <div class="modal-stat"><label>PPG</label><span>${t.ppg || "N/A"}</span></div>
                <div class="modal-stat"><label>Opp PPG</label><span>${t.opp_ppg || "N/A"}</span></div>
                <div class="modal-stat"><label>Point Diff</label><span>${t.point_diff !== null ? (t.point_diff > 0 ? "+" : "") + t.point_diff : "N/A"}</span></div>
                <div class="modal-stat"><label>Q1 Record</label><span>${t.quad1}</span></div>
            </div>
            <div class="modal-actions">${watchBtn}</div>`;
    } catch (err) {
        body.innerHTML = `<p>Error loading team: ${err.message}</p>`;
    }
}

function closeModal() {
    document.getElementById("team-modal").classList.add("hidden");
}

// ─── Watchlist ───────────────────────────────────────────────
async function loadWatchlist() {
    try {
        const resp = await fetch("/api/watchlist");
        const ids = await resp.json();
        _watchlist = new Set(ids);
    } catch (e) { /* ignore */ }
}

async function toggleWatch(teamId) {
    if (_watchlist.has(teamId)) {
        await fetch(`/api/watchlist/${teamId}`, { method: "DELETE" });
        _watchlist.delete(teamId);
    } else {
        await fetch(`/api/watchlist/${teamId}`, { method: "POST" });
        _watchlist.add(teamId);
    }
    closeModal();
    if (_bracketData) renderAll(_bracketData);
}

// ─── History + Side-by-Side Compare ──────────────────────────
async function loadHistory() {
    const container = document.getElementById("history-list");
    try {
        const resp = await fetch("/api/history?limit=30");
        const history = await resp.json();
        if (!history.length) { container.innerHTML = "<p class='info-text'>No history yet.</p>"; return; }

        // Populate compare dropdowns
        const oldSel = document.getElementById("compare-old");
        const newSel = document.getElementById("compare-new");
        let opts = `<option value="">-- Select --</option>`;
        for (const h of history) {
            opts += `<option value="${h.id}">${h.timestamp} (${(h.changes||[]).length} changes)</option>`;
        }
        oldSel.innerHTML = opts;
        newSel.innerHTML = opts;

        let html = "";
        for (const h of history) {
            const n = (h.changes || []).length;
            html += `<div class="history-entry" onclick="loadSnapshot(${h.id})">
                <span class="timestamp">${h.timestamp}</span>
                <span class="change-count">${n} change${n !== 1 ? "s" : ""}</span>
            </div>`;
        }
        container.innerHTML = html;
    } catch (err) { container.innerHTML = "<p class='info-text'>Failed to load history.</p>"; }
}

async function loadSnapshot(id) {
    const detail = document.getElementById("history-detail");
    try {
        const resp = await fetch(`/api/snapshot/${id}`);
        const data = await resp.json();
        const changes = data.changes || [];
        let html = `<h3>Snapshot Changes</h3>`;
        if (!changes.length) html += `<p class="info-text">No changes.</p>`;
        else for (const c of changes) html += `<div class="change-item ${c.type}">${c.message}</div>`;
        detail.innerHTML = html;
        detail.classList.remove("hidden");
    } catch (err) { /* ignore */ }
}

async function compareSideBySide() {
    const oldId = document.getElementById("compare-old").value;
    const newId = document.getElementById("compare-new").value;
    if (!oldId || !newId) { showToast("Select both snapshots to compare."); return; }

    const container = document.getElementById("compare-result");
    container.classList.remove("hidden");
    container.innerHTML = "<p class='info-text'>Loading...</p>";

    try {
        const resp = await fetch(`/api/compare?old=${oldId}&new=${newId}`);
        const data = await resp.json();

        const oldB = data.old?.bracket || {};
        const newB = data.new?.bracket || {};

        // Extract team sets
        const oldTeams = new Map();
        const newTeams = new Map();
        for (const entries of Object.values(oldB.regions || {}))
            entries.forEach(e => oldTeams.set(e.team_name, e));
        for (const g of oldB.first_four || [])
            (g.game || []).forEach(e => { if (e) oldTeams.set(e.team_name, e); });
        for (const entries of Object.values(newB.regions || {}))
            entries.forEach(e => newTeams.set(e.team_name, e));
        for (const g of newB.first_four || [])
            (g.game || []).forEach(e => { if (e) newTeams.set(e.team_name, e); });

        let html = `<div class="compare-grid">
            <div class="compare-col"><h4>${oldB.timestamp || "Old"}</h4>`;
        for (const [name, e] of [...oldTeams.entries()].sort((a,b) => a[1].seed - b[1].seed)) {
            const cls = !newTeams.has(name) ? " removed" : (newTeams.get(name)?.seed !== e.seed ? " changed" : "");
            html += `<div class="compare-row${cls}"><span>${e.seed}</span><span>${name}</span><span>${e.region}</span></div>`;
        }
        html += `</div><div class="compare-col"><h4>${newB.timestamp || "New"}</h4>`;
        for (const [name, e] of [...newTeams.entries()].sort((a,b) => a[1].seed - b[1].seed)) {
            const cls = !oldTeams.has(name) ? " added" : (oldTeams.get(name)?.seed !== e.seed ? " changed" : "");
            html += `<div class="compare-row${cls}"><span>${e.seed}</span><span>${name}</span><span>${e.region}</span></div>`;
        }
        html += `</div></div>`;
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p class="info-text">Error: ${err.message}</p>`;
    }
}

// ─── Utilities ───────────────────────────────────────────────
function showLoading(text) {
    document.getElementById("loading-text").textContent = text || "Updating bracket...";
    document.getElementById("loading-overlay").classList.remove("hidden");
}
function hideLoading() { document.getElementById("loading-overlay").classList.add("hidden"); }

function showToast(msg) {
    const t = document.getElementById("error-toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    setTimeout(() => t.classList.add("hidden"), 8000);
}
