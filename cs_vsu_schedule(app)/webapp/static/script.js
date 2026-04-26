const tg = window.Telegram.WebApp;
const API_BASE = window.location.origin;

let currentUser = {
    user_id: tg.initDataUnsafe?.user?.id || 0,
    course: '', group: '', subgroup: '1', mode: 'обычный',
    timezone_offset: 0, server_time_drift: 0, week_type: 0,
    display_week_type: 0, is_next_week: false,
    show_timer: 1, timer_start_mode: 0, show_intra_break: 0
};

let scheduleData = null; let metaData = null; let currentDay = 'Понедельник';

const TIME_SLOTS = [
    { start: "08:00", end: "09:35" }, { start: "09:45", end: "11:20" },
    { start: "11:30", end: "13:05" }, { start: "13:25", end: "15:00" },
    { start: "15:10", end: "16:45" }, { start: "16:55", end: "18:30" },
    { start: "18:40", end: "20:00" }, { start: "20:10", end: "21:30" }
];

tg.expand(); tg.ready();

async function init() {
    setupEventListeners();
    setInterval(updateCountdown, 1000);
    
    const slotSelect = document.getElementById('room-slot-select');
    if (slotSelect) {
        slotSelect.innerHTML = '';
        TIME_SLOTS.forEach(s => {
            const opt = document.createElement('option');
            opt.value = `${s.start} - ${s.end}`; opt.textContent = `${s.start} - ${s.end}`; slotSelect.appendChild(opt);
        });
    }

    const daySelect = document.getElementById('room-day-select');
    if (daySelect) {
        daySelect.innerHTML = '';
        ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"].forEach(d => {
            const opt = document.createElement('option'); opt.value = d; opt.textContent = d; daySelect.appendChild(opt);
        });
    }

    try {
        await loadMetaData();
        const profile = await fetchProfile();
        
        const weekBadge = document.getElementById('week-badge');
        if (weekBadge) {
            let label = profile.display_week_type === 0 ? "Числитель" : "Знаменатель";
            if (profile.is_next_week) {
                label = `<div style="display:flex; flex-direction:column; align-items:center; line-height:1.1;">
                            <span>${label}</span>
                            <span style="opacity:0.7; font-size:0.55rem; font-weight:400;">следующая неделя</span>
                         </div>`;
            }
            weekBadge.innerHTML = label;
        }
        
        if (profile.registered) {
            currentUser = { ...currentUser, ...profile };
            if (profile.server_time) {
                currentUser.server_time_drift = profile.server_time - Math.floor(Date.now() / 1000);
            }
            updateSettingsUI();
            
            const now = getAdjustedNow();
            const daysArr = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
            currentDay = daysArr[now.getUTCDay()];
            if (currentDay === "Воскресенье") currentDay = "Понедельник";
            
            if (daySelect && currentDay !== "Воскресенье") daySelect.value = currentDay;
            if (document.getElementById('room-week-select')) document.getElementById('room-week-select').value = profile.display_week_type;

            updateActiveDayButton(); updateUserInfo(); updateModeButtons(); await loadSchedule();
        } else { openOverlay('registration-overlay'); }
    } catch (e) { console.error("Init error", e); openOverlay('registration-overlay'); }
}

function getAdjustedNow() {
    const now = new Date();
    if (currentUser.server_time_drift) now.setSeconds(now.getSeconds() + currentUser.server_time_drift);
    return now;
}

function updateUserInfo() {
    const info = document.getElementById('user-info');
    if (info) info.innerHTML = `<h1>${currentUser.course}</h1><p>${currentUser.group}, подгруппа ${currentUser.subgroup}</p>`;
}

function formatTime(totalSeconds) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return (h > 0 ? h + ":" : "") + m.toString().padStart(2, '0') + ":" + s.toString().padStart(2, '0');
}

function updateCountdown() {
    if (!scheduleData || currentUser.show_timer === 0) {
        const c = document.getElementById('countdown-container'); if (c) c.classList.add('hidden'); return;
    }
    
    const now = getAdjustedNow();
    const todayIndex = now.getUTCDay();
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const todayName = days[todayIndex];
    
    const container = document.getElementById('countdown-container');
    if (!container) return;
    if (todayName === "Воскресенье") { container.classList.add('hidden'); return; }
    
    const todaysLessons = scheduleData[todayName] || [];
    const totalSeconds = (now.getUTCHours() * 3600) + (now.getUTCMinutes() * 60) + now.getUTCSeconds();

    let targetSeconds = null; let label = ""; let sub = ""; let intraText = "";

    for (const slot of TIME_SLOTS) {
        const start = parseTimeToSeconds(slot.start);
        const end = parseTimeToSeconds(slot.end);
        const lesson = findLessonInSchedule(todaysLessons, slot.start);

        if (totalSeconds >= start && totalSeconds < end && lesson && !lesson.toLowerCase().includes("нет пары")) {
            targetSeconds = end; label = "До конца пары:";
            sub = lesson.replace(/🔹|▫️|\*|_/g, '').trim();

            if (currentUser.show_intra_break === 1) {
                const firstHalfEnd = start + (45 * 60);
                const breakEnd = firstHalfEnd + (5 * 60);
                if (totalSeconds < firstHalfEnd) intraText = "До перерыва: " + formatTime(firstHalfEnd - totalSeconds);
                else if (totalSeconds < breakEnd) intraText = "ПЕРЕРЫВ! Окончание: " + formatTime(breakEnd - totalSeconds);
                else intraText = "Вторая половина пары";
            }
            break;
        }
    }

    if (targetSeconds === null) {
        for (const slot of TIME_SLOTS) {
            const start = parseTimeToSeconds(slot.start);
            const lesson = findLessonInSchedule(todaysLessons, slot.start);
            if (totalSeconds < start && lesson && !lesson.toLowerCase().includes("нет пары")) {
                const diffSec = start - totalSeconds;
                const threshold = parseInt(currentUser.timer_start_mode);
                let shouldShow = false;
                if (threshold === 0) shouldShow = true;
                else if (threshold === -1) { if (diffSec < 7200) shouldShow = true; }
                else { if (diffSec <= (threshold * 3600)) shouldShow = true; }
                if (shouldShow) {
                    targetSeconds = start; label = "До начала пары:";
                    sub = "Следующая: " + lesson.replace(/🔹|▫️|\*|_/g, '').trim();
                }
                break;
            }
        }
    }

    if (targetSeconds !== null) {
        container.classList.remove('hidden');
        const lEl = document.getElementById('countdown-label'), tEl = document.getElementById('countdown-timer'), sEl = document.getElementById('countdown-sub'), iEl = document.getElementById('countdown-intra');
        if (lEl) lEl.textContent = label;
        if (tEl) tEl.textContent = formatTime(targetSeconds - totalSeconds);
        if (sEl) sEl.textContent = sub;
        if (iEl) { iEl.textContent = intraText; iEl.classList.toggle('hidden', !intraText); }
    } else { container.classList.add('hidden'); }
}

function parseTimeToSeconds(timeStr) {
    const [h, m] = timeStr.split(':').map(Number);
    return (h * 3600) + (m * 60);
}

function findLessonInSchedule(lessons, timeStart) {
    const t = timeStart.startsWith('0') ? timeStart.substring(1) : timeStart;
    for (const l of lessons) {
        const cleanLine = l.replace(/\s+/g, '');
        if (cleanLine.includes('*' + t + '-') || cleanLine.includes('*' + timeStart + '-')) return l.split(': ').slice(1).join(': ');
    }
    return null;
}

async function loadMetaData() {
    const res = await fetch(`${API_BASE}/api/meta`); metaData = await res.json();
    const cSel = document.getElementById('course-select'); if (cSel) {
        cSel.innerHTML = '<option value="">Выберите курс</option>';
        Object.keys(metaData).forEach(course => { const opt = document.createElement('option'); opt.value = course; opt.textContent = course; cSel.appendChild(opt); });
    }
}

async function fetchProfile() { const res = await fetch(`${API_BASE}/api/profile/${currentUser.user_id}`); return await res.json(); }

async function loadSchedule() {
    const container = document.getElementById('schedule-container'); if (!container) return;
    container.innerHTML = '<div class="loading-container"><div class="loader"></div><p>Загрузка...</p></div>';
    try {
        // Мы запрашиваем расписание без параметров, чтобы сервер сам решил (на основе display_week_type)
        const res = await fetch(`${API_BASE}/api/schedule/${currentUser.user_id}`); const data = await res.json();
        if (data.updating) { showUpdatingMessage(data.message); return; }
        const nav = document.getElementById('days-nav'); if (nav) nav.style.display = 'flex';
        scheduleData = data; renderSchedule();
    } catch (e) { container.innerHTML = '<div class="empty-state">Ошибка загрузки расписания</div>'; }
}

function renderSchedule() {
    const container = document.getElementById('schedule-container'); if (!container) return;
    const daySchedule = scheduleData[currentDay] || [];
    if (daySchedule.length === 0) { container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎉</div><p>Пар нет, отдыхай!</p></div>'; return; }
    container.innerHTML = '';
    daySchedule.forEach((lesson, index) => {
        const card = document.createElement('div'); card.className = 'lesson-card';
        const timeMatch = lesson.match(/(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})/);
        const time = timeMatch ? timeMatch[0] : '';
        const subject = lesson.replace(/🔹|▫️|\*|_/g, '').replace(time, '').replace(':', '').trim();
        const isNone = subject.toLowerCase().includes('нет пары') || subject.toLowerCase().includes('похуй, домой') || subject.toLowerCase().includes('по пивку, чилл');
        card.innerHTML = `<div class="lesson-time">${time}</div><div class="lesson-name" style="${isNone ? 'color: var(--text-secondary); font-style: italic;' : ''}">${subject}</div>`;
        container.appendChild(card);
    });
}

function openOverlay(id) { const el = document.getElementById(id); if (el) { el.classList.remove('hidden'); document.body.classList.add('no-scroll'); } }
function closeOverlay(id) { const el = document.getElementById(id); if (el) { el.classList.add('hidden'); if (document.querySelectorAll('.overlay:not(.hidden)').length === 0) document.body.classList.remove('no-scroll'); } }

async function saveSettings() {
    try {
        await fetch(`${API_BASE}/api/update_settings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser.user_id,
                show_timer: currentUser.show_timer,
                timer_start_mode: parseInt(currentUser.timer_start_mode),
                show_intra_break: currentUser.show_intra_break
            })
        });
    } catch (e) { console.error("Save settings error", e); }
}

async function updateSubgroupButtons(course, group) {
    const container = document.querySelector('.subgroup-toggle'); if (!container) return;
    try {
        const res = await fetch(`${API_BASE}/api/subgroups?course=${encodeURIComponent(course)}&group=${encodeURIComponent(group)}`);
        const subgroups = await res.json();
        container.innerHTML = subgroups.map(sg => `<button class="sub-btn ${currentUser.subgroup == sg ? 'active' : ''}" data-val="${sg}">${sg}</button>`).join('');
        document.querySelectorAll('.sub-btn').forEach(btn => {
            btn.addEventListener('click', () => { document.querySelectorAll('.sub-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active'); currentUser.subgroup = btn.dataset.val; });
        });
        if (!subgroups.includes(currentUser.subgroup)) currentUser.subgroup = subgroups[0] || '1';
    } catch (e) { console.error("Subgroup fetch error", e); }
}

function setupEventListeners() {
    const safeAdd = (id, event, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(event, fn); };
    safeAdd('settings-btn', 'click', () => openOverlay('settings-overlay'));
    safeAdd('close-settings', 'click', () => closeOverlay('settings-overlay'));
    safeAdd('search-btn', 'click', () => openOverlay('search-overlay'));
    safeAdd('close-search', 'click', () => closeOverlay('search-overlay'));
    safeAdd('close-registration', 'click', () => closeOverlay('registration-overlay'));
    safeAdd('close-report', 'click', () => closeOverlay('report-overlay'));
    safeAdd('open-time-settings', 'click', () => { closeOverlay('settings-overlay'); openOverlay('time-settings-overlay'); });
    safeAdd('close-time-settings', 'click', () => closeOverlay('time-settings-overlay'));
    safeAdd('back-to-settings', 'click', () => { closeOverlay('time-settings-overlay'); openOverlay('settings-overlay'); });
    safeAdd('timer-toggle', 'change', (e) => { currentUser.show_timer = e.target.checked ? 1 : 0; saveSettings(); updateCountdown(); });
    safeAdd('timer-threshold-select', 'change', (e) => { currentUser.timer_start_mode = parseInt(e.target.value); saveSettings(); updateCountdown(); });
    safeAdd('intra-break-toggle', 'change', (e) => { currentUser.show_intra_break = e.target.checked ? 1 : 0; saveSettings(); updateCountdown(); });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active');
            const tab = btn.dataset.tab;
            const tBox = document.getElementById('teacher-search-box'), rBox = document.getElementById('rooms-search-box');
            if (tBox) tBox.classList.toggle('hidden', tab !== 'teacher'); if (rBox) rBox.classList.toggle('hidden', tab !== 'rooms');
            const res = document.getElementById('search-results'); if (res) res.innerHTML = '';
        });
    });
    safeAdd('do-teacher-search', 'click', async () => {
        const input = document.getElementById('teacher-input'); const name = input ? input.value.trim() : "";
        if (name.length < 3) { tg.showAlert("Введите минимум 3 буквы"); return; }
        const resList = document.getElementById('search-results'); if (resList) resList.innerHTML = '<p style="text-align:center">Ищу...</p>';
        try {
            const res = await fetch(`${API_BASE}/api/search/teacher?name=${encodeURIComponent(name)}`);
            const data = await res.json();
            if (resList) {
                if (data.length === 0) resList.innerHTML = '<p style="text-align:center">Ничего не найдено</p>';
                else resList.innerHTML = data.map(item => `<div class="search-item"><h4>${item.day} | ${item.time}</h4><p><b>[${item.week_type}]</b></p><p>${item.course}, ${item.group}</p><p>${item.subject}</p></div>`).join('');
            }
        } catch (e) { if (resList) resList.innerHTML = '<p>Ошибка поиска</p>'; }
    });
    safeAdd('do-room-search', 'click', async () => {
        const day = document.getElementById('room-day-select').value, week = document.getElementById('room-week-select').value, slot = document.getElementById('room-slot-select').value;
        const resList = document.getElementById('search-results'); if (resList) resList.innerHTML = '<p style="text-align:center">Проверяю аудитории...</p>';
        try {
            const res = await fetch(`${API_BASE}/api/search/rooms?day=${day}&slot=${encodeURIComponent(slot)}&week_type=${week}`);
            const data = await res.json();
            if (resList) {
                let html = '';
                if (data.main.length > 0) html += `<div class="room-card"><h4>Главный / 2 корпус</h4><div class="room-text">${data.main.join(', ')}</div></div>`;
                if (data.p.length > 0) html += `<div class="room-card"><h4>Пристройка (П)</h4><div class="room-text">${data.p.join(', ')}</div></div>`;
                resList.innerHTML = html || '<p style="text-align:center">Все аудитории заняты</p>';
            }
        } catch (e) { if (resList) resList.innerHTML = '<p>Ошибка поиска</p>'; }
    });
    safeAdd('days-nav', 'click', (e) => {
        const btn = e.target.closest('.day-btn'); if (!btn) return;
        currentDay = btn.dataset.day; updateActiveDayButton(); if (scheduleData) renderSchedule();
    });
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const mode = btn.dataset.mode;
            try {
                const res = await fetch(`${API_BASE}/api/update_mode`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: currentUser.user_id, mode: mode }) });
                if (res.ok) { currentUser.mode = mode; updateModeButtons(); await loadSchedule(); if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success'); }
            } catch (e) { tg.showAlert("Ошибка при смене режима"); }
        });
    });
    safeAdd('edit-profile-btn', 'click', async () => {
        const t = document.getElementById('reg-title'); if (t) t.textContent = "Изменение профиля";
        closeOverlay('settings-overlay'); if (currentUser.course && currentUser.group) await updateSubgroupButtons(currentUser.course, currentUser.group);
        openOverlay('registration-overlay');
    });
    safeAdd('course-select', 'change', (e) => {
        const course = e.target.value, groupSelect = document.getElementById('group-select'); if (!groupSelect) return;
        groupSelect.innerHTML = '<option value="">Группа</option>';
        if (course && metaData[course]) {
            metaData[course].forEach(group => { const opt = document.createElement('option'); opt.value = group; opt.textContent = group; groupSelect.appendChild(opt); });
            groupSelect.disabled = false;
        } else groupSelect.disabled = true;
    });
    safeAdd('group-select', 'change', async (e) => { const course = document.getElementById('course-select').value; const group = e.target.value; if (course && group) await updateSubgroupButtons(course, group); });
    safeAdd('save-profile', 'click', async () => {
        const cSel = document.getElementById('course-select'), gSel = document.getElementById('group-select');
        const course = cSel ? cSel.value : "", group = gSel ? gSel.value : "";
        if (!course || !group) { tg.showAlert("Пожалуйста, заполните все поля"); return; }
        const btn = document.getElementById('save-profile'); btn.textContent = "Сохранение..."; btn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/update_profile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: currentUser.user_id, course: course, group_num: group, subgroup: currentUser.subgroup }) });
            if (res.ok) { currentUser.course = course; currentUser.group = group; closeOverlay('registration-overlay'); updateUserInfo(); await loadSchedule(); if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success'); }
        } catch (e) { tg.showAlert("Ошибка при сохранении"); }
        finally { btn.textContent = "Сохранить"; btn.disabled = false; }
    });
    safeAdd('open-report-btn', 'click', () => { closeOverlay('settings-overlay'); openOverlay('report-overlay'); });
    safeAdd('send-report', 'click', async () => {
        const rt = document.getElementById('report-text'); const text = rt ? rt.value.trim() : ""; if (!text) return;
        const btn = document.getElementById('send-report'); btn.disabled = true; btn.textContent = "Отправка...";
        try {
            const res = await fetch(`${API_BASE}/api/report`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: currentUser.user_id, user_name: tg.initDataUnsafe?.user?.first_name || "User", text: text }) });
            if (res.ok) { tg.showAlert("Жалоба отправлена админу. Спасибо!"); closeOverlay('report-overlay'); if (rt) rt.value = ''; if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success'); }
        } catch (e) { tg.showAlert("Ошибка при отправке"); }
        finally { btn.disabled = false; btn.textContent = "Отправить админу"; }
    });
}

function updateActiveDayButton() {
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const now = getAdjustedNow();
    const todayName = days[now.getUTCDay()];
    document.querySelectorAll('.day-btn').forEach(btn => {
        if (btn.dataset.day === currentDay) { btn.classList.add('active'); btn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); }
        else btn.classList.remove('active');
        if (btn.dataset.day === todayName) btn.classList.add('today'); else btn.classList.remove('today');
    });
}
function updateModeButtons() { document.querySelectorAll('.mode-btn').forEach(btn => { if (btn.dataset.mode === currentUser.mode) btn.classList.add('active'); else btn.classList.remove('active'); }); }
function updateSettingsUI() {
    const tTog = document.getElementById('timer-toggle'), tThres = document.getElementById('timer-threshold-select'), iTog = document.getElementById('intra-break-toggle');
    if (tTog) tTog.checked = currentUser.show_timer === 1;
    if (tThres) tThres.value = currentUser.timer_start_mode;
    if (iTog) iTog.checked = currentUser.show_intra_break === 1;
}
function showUpdatingMessage(msg) { const container = document.getElementById('schedule-container'); if (container) container.innerHTML = `<div class="empty-state"><div class="empty-icon">🛠</div><p>${msg}</p></div>`; const nav = document.getElementById('days-nav'); if (nav) nav.style.display = 'none'; }

init();
