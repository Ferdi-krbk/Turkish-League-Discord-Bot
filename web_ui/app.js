// State Management
const state = {
    activeTab: 'league',
    teams: [],
    europeData: {},
    selectedTeam: 'Galatasaray',
    europeTab: 'UCL',
    europePage: 1,
    europeFixtureRound: 1
};

// DOM Elements
const tabContent = document.getElementById('tab-content');
const pageTitle = document.getElementById('page-title');
const refreshBtn = document.getElementById('refresh-btn');
const navLinks = document.querySelectorAll('.nav-links li');

// Initialize
async function init() {
    console.log("App initializing...");
    setupNav();
    try {
        await loadTab('league');
        console.log("Initial tab loaded");
    } catch (err) {
        console.error("Initialization error:", err);
        tabContent.innerHTML = `<div class="error">Yükleme hatası: ${err.message}</div>`;
    }
}

// Navigation Setup
function setupNav() {
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            console.log("Tab clicked:", link.getAttribute('data-tab'));
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            const tab = link.getAttribute('data-tab');
            loadTab(tab);
        });
    });

    refreshBtn.addEventListener('click', () => {
        console.log("Refreshing tab:", state.activeTab);
        loadTab(state.activeTab);
    });
}

// Tab Loading Logic
async function loadTab(tab) {
    console.log("Loading tab:", tab);
    state.activeTab = tab;
    tabContent.innerHTML = '<div class="loader">Yükleniyor...</div>';

    try {
        switch (tab) {
            case 'league':
                pageTitle.innerText = "Süper Lig Puan Durumu";
                await renderLeague();
                break;
            case 'europe':
                pageTitle.innerText = "Avrupa Kupaları";
                await renderEurope();
                break;
            case 'squads':
                pageTitle.innerText = "Takım Kadroları";
                await renderSquads();
                break;
            case 'transfers':
                pageTitle.innerText = "Son Transferler";
                await renderTransfers();
                break;
            case 'fixtures':
                pageTitle.innerText = "Fikstür & Sonuçlar";
                await renderFixtures();
                break;
            case 'logs':
                pageTitle.innerText = "Sistem Logları";
                await renderLogs();
                break;
            case 'management':
                pageTitle.innerText = "Sezon & Lig Yönetimi";
                await renderManagement();
                break;
        }
        console.log("Tab loaded successfully:", tab);
    } catch (err) {
        console.error(`Error loading tab ${tab}:`, err);
        tabContent.innerHTML = `<div class="error">Bir hata oluştu: ${err.message}</div>`;
    }
}

// Renderer Functions
async function renderLeague() {
    console.log("Fetching league data...");
    if (!state.leagueStatsTab) state.leagueStatsTab = 'goals';
    
    const [standings, scorers, assists, suspensions] = await Promise.all([
        eel.get_league_standings()(),
        eel.get_league_top_scorers()(),
        eel.get_league_top_assists()(),
        eel.get_league_suspensions()()
    ]);
    console.log("League data received");
    
    let html = `
        <div class="grid-2">
            <div class="league-table-container card">
                <table>
                    <thead>
                        <tr>
                            <th>Sıra</th>
                            <th>Takım</th>
                            <th>O</th>
                            <th>G</th>
                            <th>B</th>
                            <th>M</th>
                            <th>AV</th>
                            <th>P</th>
                            <th>Form</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${standings.map((t, index) => `
                            <tr>
                                <td class="rank">${index + 1}</td>
                                <td>
                                    <div class="team-info">
                                        ${t.name}
                                    </div>
                                </td>
                                <td>${t.played}</td>
                                <td>${t.won}</td>
                                <td>${t.drawn}</td>
                                <td>${t.lost}</td>
                                <td>${t.gf - t.ga}</td>
                                <td style="font-weight: 800;">${t.points}</td>
                                <td>
                                    <div class="form-dots">
                                        ${(t.form_streak || '').split('').map(char => `<span class="dot ${char}"></span>`).join('')}
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <div class="sidebar-stats">
                <div class="card" style="height: fit-content; max-height: 80vh; display: flex; flex-direction: column;">
                    <div class="squad-selector" style="margin-bottom: 20px; flex-shrink: 0;">
                        <button class="team-btn ${state.leagueStatsTab === 'goals' ? 'active' : ''}" style="font-size: 0.75rem; padding: 6px 10px;" onclick="switchLeagueStatsTab('goals')">Gol</button>
                        <button class="team-btn ${state.leagueStatsTab === 'assists' ? 'active' : ''}" style="font-size: 0.75rem; padding: 6px 10px;" onclick="switchLeagueStatsTab('assists')">Asist</button>
                        <button class="team-btn ${state.leagueStatsTab === 'suspensions' ? 'active' : ''}" style="font-size: 0.75rem; padding: 6px 10px;" onclick="switchLeagueStatsTab('suspensions')">Ceza</button>
                    </div>

                    <div style="overflow-y: auto; flex: 1; padding-right: 5px;">
                        ${state.leagueStatsTab === 'goals' ? `
                            <h3 class="card-title">Gol Krallığı ⚽</h3>
                            ${scorers.map(s => `
                                <div class="player-card">
                                    <span style="font-size: 0.85rem;">${s.player_name} (${s.team || 'Bilinmiyor'})</span>
                                    <span class="ovr" style="font-size: 0.8rem;">${s.goals} GOL</span>
                                </div>
                            `).join('')}
                        ` : state.leagueStatsTab === 'assists' ? `
                            <h3 class="card-title">Asist Krallığı 🎯</h3>
                            ${assists.map(a => `
                                <div class="player-card">
                                    <span style="font-size: 0.85rem;">${a.player_name} (${a.team || 'Bilinmiyor'})</span>
                                    <span class="ovr" style="font-size: 0.8rem; background: var(--accent-blue); color: white;">${a.assists} AST</span>
                                </div>
                            `).join('')}
                        ` : `
                            <h3 class="card-title">Ceza Raporu ⚖️</h3>
                            ${suspensions.map(p => `
                                <div class="player-card">
                                    <div style="display: flex; flex-direction: column;">
                                        <span style="font-size: 0.85rem; font-weight: 600;">${p.name}</span>
                                        <span style="font-size: 0.7rem; color: var(--text-secondary);">${p.team || 'Boşta'}</span>
                                    </div>
                                    <span class="ovr" style="font-size: 0.75rem; background: var(--accent-red); color: white;">
                                        ${p.suspension_matches} Maç
                                    </span>
                                </div>
                            `).join('')}
                            ${suspensions.length === 0 ? '<p style="font-size: 0.8rem; color: var(--text-secondary);">Şu an cezalı oyuncu yok.</p>' : ''}
                        `}
                    </div>
                </div>
            </div>
        </div>
    `;
    tabContent.innerHTML = html;
}

window.switchLeagueStatsTab = (tab) => {
    state.leagueStatsTab = tab;
    renderLeague();
};

async function renderEurope() {
    const data = await eel.get_europe_data()();
    
    if (!data || !data.UCL) {
        console.error("Invalid Europe data received:", data);
        tabContent.innerHTML = `<div class="error">Avrupa verileri yüklenemedi. Lütfen turnuvaların oluşturulduğundan emin olun.</div>`;
        return;
    }
    
    state.europeData = data;

    function renderEuropeTab(type) {
        const cup = data[type];
        if (!cup) {
            tabContent.innerHTML = `<div class="error">${type} verisi bulunamadı.</div>`;
            return;
        }
        const itemsPerPage = 12;
        const totalTeams = cup.standings.length;
        const totalPages = Math.ceil(totalTeams / itemsPerPage);
        
        // Paginate standings
        const start = (state.europePage - 1) * itemsPerPage;
        const paginatedStandings = cup.standings.slice(start, start + itemsPerPage);

        let html = `
            <div class="europe-header">
                <div class="europe-tab ${type === 'UCL' ? 'active' : ''}" onclick="switchEuropeTab('UCL')">Champions League</div>
                <div class="europe-tab ${type === 'UEL' ? 'active' : ''}" onclick="switchEuropeTab('UEL')">Europa League</div>
                <div class="europe-tab ${type === 'UECL' ? 'active' : ''}" onclick="switchEuropeTab('UECL')">Conference League</div>
            </div>
            
            <div class="grid-2">
                <div class="card ${type.toLowerCase()}-card">
                    <h3 class="card-title">Lig Aşaması Puan Durumu</h3>
                    <table>
                        <thead>
                            <tr><th>Sıra</th><th>Takım</th><th>O</th><th>G</th><th>B</th><th>M</th><th>AV</th><th>P</th></tr>
                        </thead>
                        <tbody>
                            ${paginatedStandings.map((t, i) => `
                                <tr>
                                    <td>${start + i + 1}</td>
                                    <td>${t.team}</td>
                                    <td>${t.mp}</td>
                                    <td>${t.w}</td>
                                    <td>${t.d}</td>
                                    <td>${t.l}</td>
                                    <td>${t.gd}</td>
                                    <td style="font-weight: 800;">${t.pts}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                    
                    ${totalPages > 1 ? `
                        <div class="pagination" style="margin-top: 20px; display: flex; justify-content: center; gap: 10px;">
                            ${Array.from({length: totalPages}, (_, i) => i + 1).map(p => `
                                <button class="team-btn ${state.europePage === p ? 'active' : ''}" onclick="switchEuropePage(${p})">${p}</button>
                            `).join('')}
                        </div>
                    ` : ''}
                </div>
                <div class="card">
                    <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                        Maç Fikstürü
                        ${(() => {
                            const roundStr = `Lig Aşaması - MD${state.europeFixtureRound || 1}`;
                            return cup.fixtures.some(f => f.round === roundStr && f.status === 'Pending') ? `
                                <button class="team-btn" style="font-size: 0.65rem; background: var(--accent-red); padding: 2px 8px;" onclick="fastSimAllEurope('${type}')">Geri Kalanları Simüle Et</button>
                            ` : '';
                        })()}
                    </div>
                    
                    <!-- Dynamic Round Selector -->
                    <div class="squad-selector" style="margin-bottom: 15px; font-size: 0.75rem; flex-wrap: wrap;">
                        ${(() => {
                            const allRounds = [...new Set(cup.fixtures.map(f => f.round))];
                            // Sort logic: Lig Aşaması MDs first, then others
                            allRounds.sort((a, b) => {
                                if (a.includes("Lig Aşaması") && b.includes("Lig Aşaması")) {
                                    return a.localeCompare(b, undefined, {numeric: true});
                                }
                                return 0;
                            });
                            
                            if (!state.europeFixtureRound) state.europeFixtureRound = allRounds[0];

                            return allRounds.map(rn => `
                                <button class="team-btn ${state.europeFixtureRound === rn ? 'active' : ''}" 
                                        style="padding: 4px 8px; margin-bottom: 5px;"
                                        onclick="switchEuropeRound('${rn}')">${rn.replace("Lig Aşaması - ", "")}</button>
                            `).join('');
                        })()}
                    </div>

                    <div class="fixture-list" style="max-height: 400px; overflow-y: auto; padding-right: 5px;">
                        ${(() => {
                            const roundStr = state.europeFixtureRound;
                            const roundFixtures = cup.fixtures.filter(f => f.round === roundStr);
                            
                            if (roundFixtures.length === 0) return '<p>Bu hafta için maç bulunamadı.</p>';
                            
                            return roundFixtures.map(f => `
                                <div class="player-card" style="margin-bottom: 5px; font-size: 0.85rem; display: flex; align-items: center; justify-content: space-between;">
                                    <span style="flex: 1; text-align: right; padding-right: 10px;">${f.home_team}</span>
                                    <span style="font-weight: 800; width: 60px; text-align: center;">
                                        ${f.status === 'Played' ? `${f.home_score} - ${f.away_score}` : 'vs'}
                                    </span>
                                    <span style="flex: 1; text-align: left; padding-left: 10px;">${f.away_team}</span>
                                    <div style="width: 110px; display: flex; justify-content: flex-end; gap: 5px;">
                                        ${f.status === 'Pending' ? `
                                            <div class="match-actions">
                                                <button class="team-btn" style="font-size: 0.65rem; padding: 2px 8px; background: var(--accent-blue);" onclick="toggleMatchOptions(${f.id})">Oyna</button>
                                                <div id="options-${f.id}" class="match-options" style="display: none;">
                                                    <button onclick="triggerLiveSim('${f.home_team}', '${f.away_team}', '${type}', true)">Live</button>
                                                    <button onclick="triggerLiveSim('${f.home_team}', '${f.away_team}', '${type}', false)">Hızlı</button>
                                                </div>
                                            </div>
                                        ` : `
                                            <span class="ovr" style="background: var(--accent-blue); width: 35px; text-align: center; font-size: 0.7rem; margin: 0;">MS</span>
                                        `}
                                    </div>
                                </div>
                            `).join('');
                        })()}
                    </div>
                </div>
            </div>
        `;
        tabContent.innerHTML = html;
    }

    renderEuropeTab(state.europeTab);
}

// Exposed for onclick in HTML strings
window.switchEuropeTab = (type) => {
    state.europeTab = type;
    state.europePage = 1; // Reset to page 1 on tab switch
    renderEurope();
};

window.switchEuropePage = (page) => {
    state.europePage = page;
    renderEurope();
};

window.switchEuropeRound = (round) => {
    state.europeFixtureRound = round;
    renderEurope();
};

async function renderSquads() {
    const standings = await eel.get_league_standings()();
    const currentTeam = await eel.get_team_details(state.selectedTeam)();

    let html = `
        <div class="squad-selector">
            ${standings.map(t => `
                <button class="team-btn ${t.name === state.selectedTeam ? 'active' : ''}" onclick="selectTeam('${t.name}')">
                    ${t.name}
                </button>
            `).join('')}
        </div>
        <div class="grid-2">
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3 class="card-title" style="margin-bottom:0;">${state.selectedTeam} Kadrosu <span class="ovr" style="margin-left:10px;">${currentTeam.team.overall} OVR</span></h3>
                    <div style="display:flex; gap:10px;">
                        <button class="team-btn" style="background:var(--accent-green); padding: 5px 12px; font-size:0.8rem;" onclick="handleRefreshSquad()">🔄 Kadroyu Güncelle</button>
                        <button class="team-btn" style="background:var(--accent-blue); padding: 5px 12px; font-size:0.8rem;" onclick="toggleAddPlayerForm()">+ Oyuncu Ekle</button>
                    </div>

                </div>
                
                <div id="add-player-form" style="display:none; background:var(--card-bg); border:1px solid var(--glass-border); border-radius:10px; padding:15px; margin-bottom:15px;">
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:10px;">
                        <input type="hidden" id="edit-player-id" value="">
                        <input type="text" id="new-player-name" placeholder="Oyuncu Adı" style="padding:8px; border-radius:5px; border:none; background:#111; color:#fff;">
                        <input type="text" id="new-player-pos" placeholder="Mevki (Örn: ST, CM)" style="padding:8px; border-radius:5px; border:none; background:#111; color:#fff;">
                        <input type="number" id="new-player-ovr" placeholder="OVR (Örn: 80)" style="padding:8px; border-radius:5px; border:none; background:#111; color:#fff;">
                        <input type="number" id="new-player-val" placeholder="Değer (€)" style="padding:8px; border-radius:5px; border:none; background:#111; color:#fff;">
                        <input type="number" id="new-player-age" placeholder="Yaş" value="25" style="padding:8px; border-radius:5px; border:none; background:#111; color:#fff;">
                    </div>
                    <button class="team-btn" id="save-player-btn" style="width:100%; background:var(--accent-green); padding:8px;" onclick="savePlayer('${state.selectedTeam}')">Kaydet</button>
                </div>


                <div class="player-list">
                    ${currentTeam.players.sort((a,b) => b.overall - a.overall).map(p => `
                        <div class="player-card">
                            <span><strong>[${p.position}]</strong> ${p.name}</span>
                            <div style="display:flex; gap:10px; align-items:center;">
                                <span style="font-size: 0.8rem; color: var(--text-secondary)">${p.goals} G / ${p.assists} A</span>
                                <span class="ovr">${p.overall}</span>
                                <button onclick="openEditPlayer(${p.id}, '${p.name.replace(/'/g, "\\'")}', '${p.position}', ${p.overall}, ${p.market_value || 0}, ${p.age})" style="background:var(--accent-blue); color:white; border:none; border-radius:5px; padding:3px 8px; cursor:pointer; font-weight:bold;">✎</button>
                                <button onclick="deletePlayer(${p.id}, '${p.name.replace(/'/g, "\\'")}')" style="background:var(--accent-red); color:white; border:none; border-radius:5px; padding:3px 8px; cursor:pointer; font-weight:bold;">X</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            <div class="card">
                <h3 class="card-title">Takım Bilgileri</h3>
                <p style="color: var(--text-secondary); margin-bottom: 10px;">Bütçe: <span style="color: #00ff88; font-weight: 800;">${(currentTeam.team.budget / 1000000).toFixed(1)}M €</span></p>
                <p style="color: var(--text-secondary); margin-bottom: 10px;">Şehir: ${currentTeam.team.city || 'Belirtilmemiş'}</p>
                <p style="color: var(--text-secondary); margin-bottom: 10px;">Stadyum: ${currentTeam.team.stadium || 'Belirtilmemiş'}</p>
            </div>
        </div>
    `;
    tabContent.innerHTML = html;
}

window.selectTeam = (name) => {
    state.selectedTeam = name;
    renderSquads();
};

window.toggleAddPlayerForm = () => {
    const form = document.getElementById('add-player-form');
    if (form) {
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
        if (form.style.display === 'block') {
            document.getElementById('edit-player-id').value = ''; // Reset ID for adding
            document.getElementById('new-player-name').value = '';
            document.getElementById('new-player-pos').value = '';
            document.getElementById('new-player-ovr').value = '';
            document.getElementById('new-player-val').value = '';
            document.getElementById('new-player-age').value = '25';
        }
    }
};

window.handleRefreshSquad = async () => {
    if (!state.selectedTeam) return;
    
    showNotification("GǬncelleniyor", `${state.selectedTeam} kadrosu gǬncelleniyor...`, "info");
    try {
        await eel.refresh_team_stats(state.selectedTeam)();
        showNotification("BaYarl", 'Kadro ve OVR deYerleri baYaryla gǬncellendi!', 'success');
        renderSquads(); // Refresh UI
    } catch (error) {
        showNotification("Hata", 'GǬncelleme srasnda hata oluYtu.', 'error');
        console.error(error);
    }
};

window.openEditPlayer = (id, name, pos, ovr, val, age) => {

    const form = document.getElementById('add-player-form');
    if (form) {
        form.style.display = 'block';
        document.getElementById('edit-player-id').value = id;
        document.getElementById('new-player-name').value = name;
        document.getElementById('new-player-pos').value = pos;
        document.getElementById('new-player-ovr').value = ovr;
        document.getElementById('new-player-val').value = val;
        document.getElementById('new-player-age').value = age || 25;
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
};

window.savePlayer = async (teamName) => {
    const editId = document.getElementById('edit-player-id').value;
    const name = document.getElementById('new-player-name').value;
    const pos = document.getElementById('new-player-pos').value;
    const ovr = document.getElementById('new-player-ovr').value;
    const val = document.getElementById('new-player-val').value;
    const age = document.getElementById('new-player-age').value;

    if (!name || !pos || !ovr || !val || !age) {
        showNotification("Hata", "Lütfen tüm alanları doldurun.", "warning");
        return;
    }

    if (editId) {
        // Edit mode
        const success = await eel.edit_player_gui(editId, name, pos, ovr, val, age)();
        if (success) {
            showNotification("Başarılı", `${name} güncellendi!`, "success");
            renderSquads();
        } else {
            showNotification("Hata", "Oyuncu güncellenemedi.", "error");
        }
    } else {
        // Add mode
        const success = await eel.add_player_gui(name, teamName, pos, ovr, val, age)();
        if (success) {
            showNotification("Başarılı", `${name} kadroya eklendi!`, "success");
            renderSquads();
        } else {
            showNotification("Hata", "Oyuncu eklenemedi.", "error");
        }
    }
};

window.deletePlayer = async (id, name) => {
    if (confirm(`${name} isimli oyuncuyu silmek istediğine emin misin?`)) {
        const success = await eel.delete_player_gui(id)();
        if (success) {
            showNotification("Başarılı", `${name} kadrodan silindi!`, "success");
            renderSquads();
        } else {
            showNotification("Hata", "Oyuncu silinemedi.", "error");
        }
    }
};

async function renderTransfers() {
    const transfers = await eel.get_recent_transfers()();
    let html = `
        <div class="card">
            <h3 class="card-title">Transfer Geçmişi</h3>
            <div class="league-table-container">
                <table>
                    <thead>
                        <tr><th>Tarih</th><th>Oyuncu</th><th>Kimden</th><th>Kime</th><th>Bonservis</th><th>İşlem</th></tr>
                    </thead>
                    <tbody>
                        ${transfers.map(t => `
                            <tr>
                                <td>${t.date}</td>
                                <td style="font-weight: 600;">${t.player_name}</td>
                                <td>${t.from_team}</td>
                                <td>${t.to_team}</td>
                                <td style="color: #00ff88; font-weight: 800;">${(t.fee / 1000000).toFixed(1)}M €</td>
                                <td>
                                    <button class="team-btn" 
                                            style="background: rgba(255, 62, 62, 0.1); color: #ff3e3e; border: 1px solid rgba(255, 62, 62, 0.2); padding: 4px 10px; font-size: 0.75rem;"
                                            onclick="undoTransfer(${t.id})">İptal</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
    tabContent.innerHTML = html;
}

window.undoTransfer = async (id) => {
    if (confirm("Bu transferi iptal etmek istediğine emin misin? Oyuncu eski takımına dönecek ve ödenen miktar iade edilecektir.")) {
        const success = await eel.cancel_transfer(id)();
        if (success) {
            renderTransfers();
        } else {
            showNotification("Hata", "Transfer iptal edilemedi.", "error");
        }
    }
};

async function renderFixtures() {
    // If leagueFixtureRound is not set yet, fetch the current round
    if (!state.leagueFixtureRound || state.leagueFixtureRound === 1) {
        const currentRound = await eel.get_league_fixtures()();
        if (currentRound && currentRound.length > 0) {
            state.leagueFixtureRound = currentRound[0].round_no || 1;
        }
    }

    const fixtures = await eel.get_league_fixtures(state.leagueFixtureRound)();
    
    let html = `
        <div class="card">
            <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                Süper Lig Fikstürü
                <div style="display: flex; align-items: center; gap: 15px;">
                    <div style="font-size: 0.9rem; color: var(--text-secondary)">Hafta ${state.leagueFixtureRound || ''}</div>
                    ${fixtures.some(f => f.status === 'Pending') ? `
                        <button class="team-btn" style="font-size: 0.75rem; background: var(--accent-red); padding: 5px 12px;" onclick="simAllLeague(${state.leagueFixtureRound})">Geri Kalanları Simüle Et</button>
                    ` : ''}
                </div>
            </div>
            
            <!-- Round Selector -->
            <div id="league-round-selector" class="squad-selector" style="margin-bottom: 20px; overflow-x: auto; padding-bottom: 10px; white-space: nowrap; display: block;">
                ${Array.from({length: 34}, (_, i) => i + 1).map(r => `
                    <button class="team-btn ${state.leagueFixtureRound === r ? 'active' : ''}" 
                            id="btn-round-${r}"
                            style="padding: 4px 12px; margin-right: 5px; display: inline-block;"
                            onclick="switchLeagueRound(${r})">${r}. Hafta</button>
                `).join('')}
            </div>

            <div class="fixture-list">
                ${fixtures.map(f => `
                    <div class="player-card">
                        <div style="flex: 1; text-align: center; display: flex; justify-content: center; align-items: center; gap: 20px;">
                            <span style="width: 150px; text-align: right; font-weight: 600;">${f.home_team}</span>
                            <div style="display: flex; flex-direction: column; align-items: center; gap: 5px;">
                                <span class="ovr" style="background: ${f.status === 'Played' ? 'var(--accent-red)' : 'var(--card-bg)'}; width: 80px; font-size: 1.1rem; border: 1px solid var(--glass-border);">
                                    ${f.status === 'Played' ? `${f.home_score} - ${f.away_score}` : 'vs'}
                                </span>
                            </div>
                            <span style="width: 150px; text-align: left; font-weight: 600;">${f.away_team}</span>
                            
                            <div style="width: 100px; display: flex; justify-content: flex-end;">
                                ${f.status === 'Pending' ? `
                                    <div class="match-actions">
                                        <button class="team-btn" style="font-size: 0.7rem; padding: 3px 10px; background: var(--accent-blue);" onclick="toggleMatchOptions('L-${f.id}')">Oyna</button>
                                        <div id="options-L-${f.id}" class="match-options" style="display: none;">
                                            <button onclick="triggerLiveSim('${f.home_team}', '${f.away_team}', 'League', true)">Live</button>
                                            <button onclick="triggerLiveSim('${f.home_team}', '${f.away_team}', 'League', false)">Hızlı</button>
                                        </div>
                                    </div>
                                ` : `
                                    <span class="ovr" style="background: var(--accent-red); width: 40px; text-align: center; font-size: 0.75rem;">MS</span>
                                `}
                            </div>
                        </div>
                    </div>
                `).join('')}
                ${fixtures.length === 0 ? '<p style="text-align:center; color:var(--text-secondary); padding: 20px;">Bu hafta için fikstür bulunamadı.</p>' : ''}
            </div>
        </div>
    `;
    tabContent.innerHTML = html;

    // Fix for scroll reset: Scroll the active button into view
    setTimeout(() => {
        const activeBtn = document.getElementById(`btn-round-${state.leagueFixtureRound}`);
        if (activeBtn) {
            activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
    }, 100);
}

window.switchLeagueRound = (round) => {
    state.leagueFixtureRound = round;
    renderFixtures();
};

window.switchEuropeRound = (round) => {
    state.europeFixtureRound = round;
    renderEurope();
};

window.toggleMatchOptions = (id) => {
    const options = document.getElementById(`options-${id}`);
    const isVisible = options.style.display === 'flex';
    
    // Close all other options first
    document.querySelectorAll('.match-options').forEach(el => el.style.display = 'none');
    
    // Toggle current
    options.style.display = isVisible ? 'none' : 'flex';
    
    // Close when clicking elsewhere
    if (!isVisible) {
        setTimeout(() => {
            const closeHandler = (e) => {
                if (!options.contains(e.target)) {
                    options.style.display = 'none';
                    document.removeEventListener('click', closeHandler);
                }
            };
            document.addEventListener('click', closeHandler);
        }, 10);
    }
};

window.fastSimMatch = async (id, type) => {
    const success = await eel.sim_match(id, type)();
    if (success) {
        if (type === 'Europe') renderEurope();
        else renderFixtures();
    } else {
        showNotification("Hata", "Maç simüle edilemedi.", "error");
    }
};

window.triggerLiveSim = async (home, away, type, isLive = true) => {
    const success = await eel.trigger_live_sim(home, away, type, isLive)();
    if (success) {
        const mode = isLive ? "canlı" : "hızlı";
        const channel = type === 'League' ? 'beinsports-1' : 'exxen-1';
        showNotification("Maç Başlatıldı", `${home} vs ${away} maçı ${channel} kanalında ${mode} olarak başlatıldı!`, "success");
    } else {
        showNotification("Hata", "Maç başlatılamadı.", "error");
    }
};

window.fastSimAllEurope = async (tournamentName) => {
    const roundStr = state.europeFixtureRound;
    const success = await eel.sim_all_europe(tournamentName, roundStr)();
    if (success) {
        renderEurope();
    } else {
        showNotification("Hata", "Maçlar simüle edilemedi.", "error");
    }
};

window.simAllLeague = async (roundNo) => {
    const success = await eel.sim_all_league(roundNo)();
    if (success) {
        renderFixtures();
    } else {
        showNotification("Hata", "Hafta simüle edilemedi.", "error");
    }
};

async function renderLogs() {
    tabContent.innerHTML = `
        <div class="card">
            <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
                Sistem Çıktıları (Canlı)
                <button class="team-btn" style="font-size: 0.75rem; background: var(--accent-blue); padding: 5px 12px;" onclick="refreshLogs()">Logları Tazele 🔄</button>
            </div>
            <div id="log-viewer" style="background: #000; color: #00ff88; font-family: 'Consolas', monospace; padding: 15px; border-radius: 10px; font-size: 0.85rem; line-height: 1.4; height: 500px; overflow-y: auto; white-space: pre-wrap; border: 1px solid var(--glass-border);">
                Yükleniyor...
            </div>
        </div>
    `;
    
    await refreshLogs();
}

window.refreshLogs = async () => {
    const logs = await eel.get_bot_logs()();
    const viewer = document.getElementById('log-viewer');
    if (viewer) {
        viewer.innerText = logs;
        viewer.scrollTop = viewer.scrollHeight; // Auto-scroll to bottom
    }
};

// Start the app
init();
// UI Helper: Custom Notifications
function showNotification(title, message, type = 'success') {
    const container = document.getElementById('notification-container');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    
    const icon = type === 'success' ? '🏟️' : '⚠️';
    
    notification.innerHTML = `
        <div class="notification-icon">${icon}</div>
        <div class="notification-content">
            <h4>${title}</h4>
            <p>${message}</p>
        </div>
    `;
    
    container.appendChild(notification);
    
    // Trigger animation
    setTimeout(() => notification.classList.add('show'), 10);
    
    // Auto-remove
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 600);
    }, 5000);
}

// MANAGEMENT RENDERER
async function renderManagement() {
    tabContent.innerHTML = '<div class="loader">Yükleniyor...</div>';
    
    try {
        const allTeams = await eel.get_all_teams_gui()();
        
        let html = `
            <div class="management-container">
                <div class="grid-2">
                    <!-- Section 1: Reset Actions -->
                    <div class="card">
                        <h3 class="card-title">⚠️ Kritik İşlemler</h3>
                        <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 20px;">
                            Bu işlemler geri alınamaz. Lütfen dikkatli kullanın.
                        </p>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <button class="action-btn danger" onclick="resetLeague()">
                                <span class="icon">🔄</span> Ligi ve Puan Durumunu Sıfırla
                            </button>
                            <button class="action-btn success" onclick="generateFixtures()" style="background: var(--accent-gold); color: black;">
                                <span class="icon">📅</span> Yeni Lig Fikstürü Çek
                            </button>
                            <button class="action-btn danger" onclick="resetEurope()">
                                <span class="icon">🌍</span> Avrupa Kupalarını Sıfırla
                            </button>
                        </div>
                    </div>

                    <!-- Section 2: Promotion/Relegation -->
                    <div class="card">
                        <h3 class="card-title">📉 Küme Düşme / Çıkma</h3>
                        <div class="form-group">
                            <label>Küme Düşen Takımlar (Düşenleri işaretle)</label>
                            <div class="team-selection-grid" style="max-height: 200px;">
                                ${allTeams.map(t => `
                                    <label class="checkbox-container">
                                        <input type="checkbox" name="relegated-teams" value="${t}">
                                        <span class="checkmark"></span>
                                        ${t}
                                    </label>
                                `).join('')}
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Yeni Çıkan Takımlar (Virgülle ayır)</label>
                            <input type="text" id="promoted-teams" placeholder="Iğdır FK, Sakaryaspor...">
                        </div>
                        <button class="action-btn" onclick="applySeasonTransition()">
                            <span class="icon">🚀</span> Sezon Geçişini Uygula
                        </button>
                    </div>
                </div>

                <!-- Section 3: European Tournament Setup -->
                <div class="card" style="margin-top: 20px;">
                    <h3 class="card-title">🏆 Avrupa Kupası Sihirbazı</h3>
                    <div class="grid-3">
                        <div class="form-group">
                            <label>Turnuva Seç</label>
                            <select id="tourney-name">
                                <option value="UCL">Champions League (UCL)</option>
                                <option value="UEL">Europa League (UEL)</option>
                                <option value="UECL">Conference League (UECL)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Tur Seç</label>
                            <select id="tourney-round">
                                <option value="Lig Aşaması">Lig Aşaması (36 Takım)</option>
                                <option value="Son 16">Son 16</option>
                                <option value="Çeyrek Final">Çeyrek Final</option>
                                <option value="Yarı Final">Yarı Final</option>
                                <option value="Final">Final</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Maç Sayısı</label>
                            <select id="tourney-legs">
                                <option value="2">Çift Maç (Rövanşlı)</option>
                                <option value="1">Tek Maç (Final)</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="form-group" style="margin-top: 15px;">
                        <label>Katılacak Takımlar (İstediğin kadar seç, eksikler AI devleriyle dolar)</label>
                        <div class="team-selection-grid">
                            ${allTeams.map(t => `
                                <label class="checkbox-container">
                                    <input type="checkbox" name="tourney-teams" value="${t}">
                                    <span class="checkmark"></span>
                                    ${t}
                                </label>
                            `).join('')}
                        </div>
                    </div>
                    
                    <button class="action-btn success" onclick="setupEurope()">
                        <span class="icon">✨</span> Turnuvayı Kur ve Fikstürü Çek
                    </button>
                </div>
            </div>
        `;
        tabContent.innerHTML = html;
    } catch (err) {
        console.error("Error rendering management:", err);
        tabContent.innerHTML = `<div class="error">Yükleme hatası: ${err.message}</div>`;
    }
}

// ACTION HELPERS
async function resetLeague() {
    if (!confirm("TÜM lig verilerini sıfırlamak istediğine emin misin? Bu işlem geri alınamaz!")) return;
    
    showNotification("Lig sıfırlanıyor...", "info");
    const success = await eel.reset_league_standings_gui()();
    if (success) {
        showNotification("Lig başarıyla sıfırlandı!", "success");
        loadTab('league');
    }
}

async function resetEurope() {
    if (!confirm("Avrupa kupalarını sıfırlamak istediğine emin misin?")) return;
    
    showNotification("Avrupa verileri temizleniyor...", "info");
    const success = await eel.reset_europe_tournaments_gui()();
    if (success) {
        showNotification("Avrupa kupaları başarıyla temizlendi!", "success");
        loadTab('europe');
    }
}

async function setupEurope() {
    const name = document.getElementById('tourney-name').value;
    const round = document.getElementById('tourney-round').value;
    const legs = document.getElementById('tourney-legs').value;
    
    const checkboxes = document.querySelectorAll('input[name="tourney-teams"]:checked');
    const selectedTeams = Array.from(checkboxes).map(cb => cb.value);
    
    if (selectedTeams.length === 0) {
        showNotification("En az bir takım seçmelisin!", "error");
        return;
    }
    
    showNotification(`${name} kuruluyor...`, "info");
    const success = await eel.setup_europe_gui(name, round, selectedTeams, legs)();
    
    if (success) {
        showNotification(`${name} başarıyla kuruldu!`, "success");
        loadTab('europe');
    } else {
        showNotification("Turnuva kurulurken hata oluştu.", "error");
    }
}

async function applySeasonTransition() {
    const checkboxes = document.querySelectorAll('input[name="relegated-teams"]:checked');
    const relegated = Array.from(checkboxes).map(cb => cb.value);
    
    const promotedStr = document.getElementById('promoted-teams').value;
    const promoted = promotedStr.split(',').map(s => s.trim()).filter(s => s !== "");
    
    if (relegated.length === 0 && promoted.length === 0) {
        showNotification("Hiçbir değişiklik yapılmadı.", "info");
        return;
    }
    
    if (!confirm(`${relegated.length} takım düşecek, ${promoted.length} takım çıkacak. Onaylıyor musun?`)) return;
    
    showNotification("Sezon geçişi uygulanıyor...", "info");
    const success = await eel.handle_promotion_relegation_gui(relegated, promoted)();
    
    if (success) {
        showNotification("Yeni sezon kadrosu hazır!", "success");
        loadTab('management'); // Reload to see updated team list
    }
}

async function generateFixtures() {
    if (!confirm("Mevcut lig fikstürü silinecek ve yeni takımlara göre sıfırdan oluşturulacak. Emin misin?")) return;
    
    showNotification("Lig fikstürü çekiliyor...", "info");
    const success = await eel.generate_league_fixtures_gui()();
    
    if (success) {
        showNotification("Mükemmel fikstür oluşturuldu!", "success");
        loadTab('league');
    } else {
        showNotification("Fikstür çekilirken hata oluştu (Takım sayısı yetersiz olabilir).", "error");
    }
}
