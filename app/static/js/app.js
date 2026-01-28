// Bracketology - NCAA Tournament Projection App

document.addEventListener("DOMContentLoaded", () => {
    setupTabs();
    loadBracket();
});

// ─── Tab Navigation ──────────────────────────────────────────

function setupTabs() {
    document.querySelectorAll(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            tab.classList.add("active");
            const target = document.getElementById("tab-" + tab.dataset.tab);
            if (target) target.classList.add("active");

            // Lazy-load history
            if (tab.dataset.tab === "history") loadHistory();
        });
    });
}

// ─── Load Bracket Data ───────────────────────────────────────

async function loadBracket() {
    try {
        const resp = await fetch("/api/bracket");
        if (resp.status === 404) {
            showEmptyState();
            return;
        }
        const data = await resp.json();
        renderBracket(data);
    } catch (err) {
        console.error("Failed to load bracket:", err);
        showEmptyState();
    }
}

function showEmptyState() {
    document.querySelector(".bracket-container").innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
            <h3>No Bracket Data Yet</h3>
            <p>Click "Update Now" to fetch data and generate the first bracket projection.</p>
        </div>`;
}

// ─── Trigger Update ──────────────────────────────────────────

async function triggerUpdate() {
    const btn = document.getElementById("btn-update");
    const overlay = document.getElementById("loading-overlay");
    btn.disabled = true;
    overlay.classList.remove("hidden");

    try {
        const resp = await fetch("/api/update", { method: "POST" });
        const data = await resp.json();
        if (data.status === "ok") {
            await loadBracket();
        } else {
            alert("Update failed: " + (data.message || "Unknown error"));
        }
    } catch (err) {
        console.error("Update error:", err);
        alert("Update failed. Check console for details.");
    } finally {
        btn.disabled = false;
        overlay.classList.add("hidden");
    }
}

// ─── Render Bracket ──────────────────────────────────────────

function renderBracket(data) {
    if (!data || !data.regions) return;

    // Update timestamp
    const tsEl = document.getElementById("last-updated");
    if (data.timestamp) {
        tsEl.textContent = "Last updated: " + data.timestamp;
    }

    // Render regions
    for (const region of ["South", "East", "West", "Midwest"]) {
        renderRegion(region, data.regions[region] || []);
    }

    // Render First Four
    renderFirstFour(data.first_four || []);

    // Render Seed List
    renderSeedList(data);

    // Render Bubble Watch
    renderBubble(data);

    // Render P5 Status
    renderP5Status(data.p5_status || {});
}

function renderRegion(regionName, entries) {
    const container = document.querySelector(`#region-${regionName} .region-matchups`);
    if (!container) return;

    // Sort by seed
    entries.sort((a, b) => a.seed - b.seed);

    // Build first-round matchups (1v16, 8v9, 5v12, 4v13, 6v11, 3v14, 7v10, 2v15)
    const matchupOrder = [[1,16],[8,9],[5,12],[4,13],[6,11],[3,14],[7,10],[2,15]];
    const bySeeds = {};
    entries.forEach(e => { bySeeds[e.seed] = e; });

    let html = "";
    for (const [s1, s2] of matchupOrder) {
        const t1 = bySeeds[s1];
        const t2 = bySeeds[s2];
        html += renderMatchupPair(t1, s1, t2, s2);
    }

    container.innerHTML = html;
}

function renderMatchupPair(t1, s1, t2, s2) {
    return `
        <div class="matchup">
            <span class="matchup-seed seed-${s1 <= 4 ? s1 : ''}">${s1}</span>
            <span class="matchup-team">${t1 ? teamName(t1) : "TBD"}</span>
            <span class="matchup-info">${t1 ? t1.record || "" : ""}</span>
            ${t1 ? bidBadge(t1) : ""}
        </div>
        <div class="matchup">
            <span class="matchup-seed">${s2}</span>
            <span class="matchup-team">${t2 ? teamName(t2) : "TBD"}</span>
            <span class="matchup-info">${t2 ? t2.record || "" : ""}</span>
            ${t2 ? bidBadge(t2) : ""}
        </div>`;
}

function teamName(entry) {
    let name = entry.team_name || "Unknown";
    if (entry.is_first_four) {
        const oppName = entry.first_four_opponent ? entry.first_four_opponent.team_name : "TBD";
        name += ` / ${oppName}`;
    }
    return name;
}

function bidBadge(entry) {
    if (entry.is_auto_bid) {
        return `<span class="matchup-bid bid-auto">AUTO</span>`;
    }
    return `<span class="matchup-bid bid-at-large">AL</span>`;
}

function renderFirstFour(games) {
    const container = document.getElementById("first-four-games");
    if (!container) return;

    if (!games.length) {
        container.innerHTML = "<p class='info-text'>No First Four data available.</p>";
        return;
    }

    let html = "";
    for (const game of games) {
        const [t1, t2] = game.game || [];
        html += `
            <div class="ff-game">
                <span class="ff-seed">#${game.seed}</span>
                <span>${t1 ? t1.team_name : "TBD"} (${t1 ? t1.record : ""})</span>
                <span class="ff-vs">vs</span>
                <span>${t2 ? t2.team_name : "TBD"} (${t2 ? t2.record : ""})</span>
                <span class="ff-region">${game.region} Region</span>
            </div>`;
    }
    container.innerHTML = html;
}

// ─── Seed List ───────────────────────────────────────────────

function renderSeedList(data) {
    const container = document.getElementById("seed-list");
    if (!container) return;

    // Collect all teams from all regions + first four
    const allTeams = [];
    for (const region of Object.keys(data.regions || {})) {
        for (const entry of data.regions[region]) {
            allTeams.push(entry);
        }
    }
    for (const game of data.first_four || []) {
        for (const entry of game.game || []) {
            if (entry) allTeams.push(entry);
        }
    }

    // Sort by seed then rating
    allTeams.sort((a, b) => {
        if (a.seed !== b.seed) return a.seed - b.seed;
        return (b.rating || 0) - (a.rating || 0);
    });

    let html = `
        <div class="seed-row seed-header">
            <span>Seed</span>
            <span>Team</span>
            <span>Conference</span>
            <span>Record</span>
            <span>Region</span>
        </div>`;

    for (const team of allTeams) {
        const ffLabel = team.is_first_four ? " (FF)" : "";
        const bidType = team.is_auto_bid ? "AUTO" : "AL";
        html += `
            <div class="seed-row">
                <span class="seed-num">${team.seed}</span>
                <span class="team-name">${team.team_name}${ffLabel}</span>
                <span class="conference">${team.conference || ""} [${bidType}]</span>
                <span class="record">${team.record || ""}</span>
                <span class="region-label">${team.region || ""}</span>
            </div>`;
    }

    container.innerHTML = html;
}

// ─── Bubble Watch ────────────────────────────────────────────

function renderBubble(data) {
    renderTeamList("last-four-in", data.last_four_in || []);
    renderTeamList("first-four-out", data.first_four_out || []);
    renderTeamList("next-four-out", data.next_four_out || []);
}

function renderTeamList(containerId, teams) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!teams.length) {
        container.innerHTML = "<p class='info-text'>No data available.</p>";
        return;
    }

    let html = "";
    for (const t of teams) {
        html += `
            <div class="bubble-team">
                <span class="team-name">${t.team_name || "Unknown"}</span>
                <span>${t.conference || ""}</span>
                <span>${t.record || ""}</span>
                <span>NET: ${t.net_ranking < 999 ? t.net_ranking : "N/A"}</span>
            </div>`;
    }
    container.innerHTML = html;
}

// ─── P5 Status ───────────────────────────────────────────────

function renderP5Status(p5Status) {
    const container = document.getElementById("p5-status-list");
    if (!container) return;

    const entries = Object.entries(p5Status);
    if (!entries.length) {
        container.innerHTML = "<p class='info-text'>No P5 status data available. Run an update first.</p>";
        return;
    }

    // Group by status
    const order = ["lock", "safe", "bubble_in", "auto_bid", "bubble_out", "eliminated"];
    entries.sort((a, b) => {
        const ai = order.indexOf(a[1]);
        const bi = order.indexOf(b[1]);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

    const statusLabels = {
        lock: "LOCK",
        safe: "SAFE",
        bubble_in: "BUBBLE IN",
        bubble_out: "BUBBLE OUT",
        eliminated: "ELIMINATED",
        auto_bid: "AUTO-BID",
    };

    let html = "";
    for (const [team, status] of entries) {
        html += `
            <div class="p5-team status-${status}">
                <span class="team-name">${team}</span>
                <span class="status-badge ${status}">${statusLabels[status] || status.toUpperCase()}</span>
                <span></span>
            </div>`;
    }
    container.innerHTML = html;
}

// ─── History ─────────────────────────────────────────────────

async function loadHistory() {
    const container = document.getElementById("history-list");
    if (!container) return;

    try {
        const resp = await fetch("/api/history?limit=30");
        const history = await resp.json();

        if (!history.length) {
            container.innerHTML = "<p class='info-text'>No history yet. Updates will appear here.</p>";
            return;
        }

        let html = "";
        for (const entry of history) {
            const changeCount = (entry.changes || []).length;
            html += `
                <div class="history-entry" onclick="loadSnapshot(${entry.id})">
                    <span class="timestamp">${entry.timestamp}</span>
                    <span class="change-count">${changeCount} change${changeCount !== 1 ? "s" : ""}</span>
                </div>`;
        }
        container.innerHTML = html;
    } catch (err) {
        console.error("Failed to load history:", err);
        container.innerHTML = "<p class='info-text'>Failed to load history.</p>";
    }
}

async function loadSnapshot(id) {
    const detail = document.getElementById("history-detail");
    if (!detail) return;

    try {
        const resp = await fetch(`/api/snapshot/${id}`);
        const data = await resp.json();

        const changes = data.changes || [];
        let html = `<h3>Snapshot Changes</h3>`;

        if (!changes.length) {
            html += `<p class="info-text">No changes recorded for this snapshot.</p>`;
        } else {
            for (const change of changes) {
                const type = change.type || "initial";
                html += `<div class="change-item ${type}">${change.message || JSON.stringify(change)}</div>`;
            }
        }

        detail.innerHTML = html;
        detail.classList.remove("hidden");
    } catch (err) {
        console.error("Failed to load snapshot:", err);
    }
}
