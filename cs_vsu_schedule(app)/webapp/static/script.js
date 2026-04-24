const tg = window.Telegram.WebApp;
const API_BASE = window.location.origin;

let currentUser = {
    user_id: tg.initDataUnsafe?.user?.id || 0,
    course: '',
    group: '',
    subgroup: '1',
    mode: 'обычный',
    timezone_offset: 0,
    server_time_drift: 0,
    week_type: 0
};

let scheduleData = null;
let metaData = null;
let currentDay = 'Понедельник';

const TIME_SLOTS = [
    { start: "08:00", end: "09:35" },
    { start: "09:45", end: "11:20" },
    { start: "11:30", end: "13:05" },
    { start: "13:25", end: "15:00" },
    { start: "15:10", end: "16:45" },
    { start: "16:55", end: "18:30" },
    { start: "18:40", end: "20:00" },
    { start: "20:10", end: "21:30" }
];

// Initialize
tg.expand();
tg.ready();

async function init() {
    setupEventListeners();
    setInterval(updateCountdown, 1000);
    
    const slotSelect = document.getElementById('room-slot-select');
    if (slotSelect) {
        slotSelect.innerHTML = '';
        TIME_SLOTS.forEach(s => {
            const opt = document.createElement('option');
            opt.value = `${s.start} - ${s.end}`;
            opt.textContent = `${s.start} - ${s.end}`;
            slotSelect.appendChild(opt);
        });
    }

    const daySelect = document.getElementById('room-day-select');
    if (daySelect) {
        daySelect.innerHTML = '';
        ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"].forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            daySelect.appendChild(opt);
        });
    }

    try {
        await loadMetaData();
        const profile = await fetchProfile();
        
        const weekBadge = document.getElementById('week-badge');
        if (weekBadge) weekBadge.textContent = profile.week_type === 0 ? "Числитель" : "Знаменатель";
        currentUser.week_type = profile.week_type;
        
        const weekSelect = document.getElementById('room-week-select');
        if (weekSelect) weekSelect.value = profile.week_type;
        
        if (profile.is_updating) {
            showUpdatingMessage("⚠️ Расписание обновляется. Зайдите позже.");
            return;
        }

        if (profile.registered) {
            currentUser = { ...currentUser, ...profile };
            if (profile.server_time) {
                const phoneNow = Math.floor(Date.now() / 1000);
                currentUser.server_time_drift = profile.server_time - phoneNow;
            }

            const now = getAdjustedNow();
            const daysArr = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
            currentDay = daysArr[now.getDay()];
            if (currentDay === "Воскресенье") currentDay = "Понедельник";
            
            if (daySelect && currentDay !== "Воскресенье") daySelect.value = currentDay;

            updateActiveDayButton();
            updateUserInfo();
            updateModeButtons();
            await loadSchedule();
        } else {
            openOverlay('registration-overlay');
        }
    } catch (e) { console.error("Init error", e); openOverlay('registration-overlay'); }
}

function getAdjustedNow() {
    const now = new Date();
    if (currentUser.server_time_drift) now.setSeconds(now.getSeconds() + currentUser.server_time_drift);
    return now;
}

function updateUserInfo() {
    const info = document.getElementById('user-info');
    if (!info) return;
    info.innerHTML = `<h1>${currentUser.course}</h1><p>${currentUser.group}, подгруппа ${currentUser.subgroup}</p>`;
}

function updateCountdown() {
    if (!scheduleData) return;
    const now = getAdjustedNow();
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const todayName = days[now.getDay()];
    const container = document.getElementById('countdown-container');
    if (!container) return;

    if (todayName === "Воскресенье") {
        container.classList.add('hidden');
        return;
    }
    
    const todaysLessons = scheduleData[todayName] || [];
    const totalSeconds = (now.getHours() * 3600) + (now.getMinutes() * 60) + now.getSeconds();

    let targetSeconds = null; let label = ""; let sub = "";

    for (const slot of TIME_SLOTS) {
        const start = parseTimeToSeconds(slot.start);
        const end = parseTimeToSeconds(slot.end);
        if (totalSeconds >= start && totalSeconds < end) {
            const lesson = findLessonInSchedule(todaysLessons, slot.start);
            if (lesson && !lesson.toLowerCase().includes("нет пары")) {
                targetSeconds = end; label = "До конца пары:"; sub = lesson.replace(/🔹|▫️|\*|_/g, '').trim();
                break;
            }
        }
    }

    if (targetSeconds === null) {
        for (const slot of TIME_SLOTS) {
            const start = parseTimeToSeconds(slot.start);
            if (totalSeconds < start) {
                const lesson = findLessonInSchedule(todaysLessons, slot.start);
                if (lesson && !lesson.toLowerCase().includes("нет пары")) {
                    targetSeconds = start; label = "До начала пары:"; sub = "Следующая: " + lesson.replace(/🔹|▫️|\*|_/g, '').trim();
                    break;
                }
            }
        }
    }

    if (targetSeconds !== null) {
        const diff = targetSeconds - totalSeconds;
        const h = Math.floor(diff / 3600); const m = Math.floor((diff % 3600) / 60); const s = diff % 60;
        container.classList.remove('hidden');
        const lEl = document.getElementById('countdown-label');
        const tEl = document.getElementById('countdown-timer');
        const sEl = document.getElementById('countdown-sub');
        if (lEl) lEl.textContent = label;
        if (tEl) tEl.textContent = (h > 0 ? h + ":" : "") + m.toString().padStart(2, '0') + ":" + s.toString().padStart(2, '0');
        if (sEl) sEl.textContent = sub;
    } else container.classList.add('hidden');
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
    const res = await fetch(`${API_BASE}/api/meta`);
    metaData = await res.json();
    const courseSelect = document.getElementById('course-select');
    if (!courseSelect) return;
    courseSelect.innerHTML = '<option value="">Выберите курс</option>';
    Object.keys(metaData).forEach(course => {
        const opt = document.createElement('option');
        opt.value = course; opt.textContent = course;
        courseSelect.appendChild(opt);
    });
}

async function fetchProfile() {
    const res = await fetch(`${API_BASE}/api/profile/${currentUser.user_id}`);
    return await res.json();
}

async function loadSchedule() {
    const container = document.getElementById('schedule-container');
    if (!container) return;
    container.innerHTML = '<div class="loading-container"><div class="loader"></div><p>Загрузка...</p></div>';
    try {
        const res = await fetch(`${API_BASE}/api/schedule/${currentUser.user_id}`);
        const data = await res.json();
        if (data.updating) { showUpdatingMessage(data.message); return; }
        const nav = document.getElementById('days-nav');
        if (nav) nav.style.display = 'flex';
        scheduleData = data; renderSchedule();
    } catch (e) { container.innerHTML = '<div class="empty-state">Ошибка загрузки расписания</div>'; }
}

function renderSchedule() {
    const container = document.getElementById('schedule-container');
    if (!container) return;
    const daySchedule = scheduleData[currentDay] || [];
    if (daySchedule.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎉</div><p>Пар нет, отдыхай!</p></div>';
        return;
    }
    container.innerHTML = '';
    daySchedule.forEach((lesson, index) => {
        const card = document.createElement('div');
        card.className = 'lesson-card';
        card.style.animationDelay = `${index * 0.1}s`;
        const timeMatch = lesson.match(/(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})/);
        const time = timeMatch ? timeMatch[0] : '';
        const subject = lesson.replace(/🔹|▫️|\*|_/g, '').replace(time, '').replace(':', '').trim();
        const isNone = subject.toLowerCase().includes('нет пары') || subject.toLowerCase().includes('похуй, домой') || subject.toLowerCase().includes('по пивку, чилл');
        card.innerHTML = `<div class="lesson-time">${time}</div><div class="lesson-name" style="${isNone ? 'color: var(--text-secondary); font-style: italic;' : ''}">${subject}</div>`;
        container.appendChild(card);
    });
}

// Управление окнами (Overlays)
function openOverlay(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.remove('hidden');
        document.body.classList.add('no-scroll');
    }
}

function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.add('hidden');
        // Проверяем, остались ли открытые оверлеи
        const visibleOverlays = document.querySelectorAll('.overlay:not(.hidden)');
        if (visibleOverlays.length === 0) {
            document.body.classList.remove('no-scroll');
        }
    }
}

function setupEventListeners() {
    const safeAdd = (id, event, fn) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener(event, fn);
    };

    safeAdd('settings-btn', 'click', () => openOverlay('settings-overlay'));
    safeAdd('close-settings', 'click', () => closeOverlay('settings-overlay'));
    safeAdd('search-btn', 'click', () => openOverlay('search-overlay'));
    safeAdd('close-search', 'click', () => closeOverlay('search-overlay'));
    safeAdd('close-registration', 'click', () => closeOverlay('registration-overlay'));
    safeAdd('close-report', 'click', () => closeOverlay('report-overlay'));

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            const tBox = document.getElementById('teacher-search-box');
            const rBox = document.getElementById('rooms-search-box');
            if (tBox) tBox.classList.toggle('hidden', tab !== 'teacher');
            if (rBox) rBox.classList.toggle('hidden', tab !== 'rooms');
            const res = document.getElementById('search-results');
            if (res) res.innerHTML = '';
        });
    });

    safeAdd('do-teacher-search', 'click', async () => {
        const input = document.getElementById('teacher-input');
        const name = input ? input.value.trim() : "";
        if (name.length < 3) { tg.showAlert("Введите минимум 3 буквы"); return; }
        const resList = document.getElementById('search-results');
        if (resList) resList.innerHTML = '<p style="text-align:center">Ищу...</p>';
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
        const day = document.getElementById('room-day-select').value;
        const week = document.getElementById('room-week-select').value;
        const slot = document.getElementById('room-slot-select').value;
        const resList = document.getElementById('search-results');
        if (resList) resList.innerHTML = '<p style="text-align:center">Проверяю аудитории...</p>';
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
        const btn = e.target.closest('.day-btn');
        if (!btn) return;
        currentDay = btn.dataset.day;
        updateActiveDayButton();
        if (scheduleData) renderSchedule();
    });

    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const mode = btn.dataset.mode;
            try {
                const res = await fetch(`${API_BASE}/api/update_mode`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: currentUser.user_id, mode: mode })
                });
                if (res.ok) {
                    currentUser.mode = mode;
                    updateModeButtons();
                    await loadSchedule();
                    if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                }
            } catch (e) { tg.showAlert("Ошибка при смене режима"); }
        });
    });

    safeAdd('edit-profile-btn', 'click', () => {
        const t = document.getElementById('reg-title'); if (t) t.textContent = "Изменение профиля";
        closeOverlay('settings-overlay');
        openOverlay('registration-overlay');
    });

    safeAdd('course-select', 'change', (e) => {
        const course = e.target.value;
        const groupSelect = document.getElementById('group-select'); if (!groupSelect) return;
        groupSelect.innerHTML = '<option value="">Выберите группу</option>';
        if (course && metaData[course]) {
            metaData[course].forEach(group => {
                const opt = document.createElement('option'); opt.value = group; opt.textContent = group;
                groupSelect.appendChild(opt);
            });
            groupSelect.disabled = false;
        } else groupSelect.disabled = true;
    });

    document.querySelectorAll('.sub-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.sub-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentUser.subgroup = btn.dataset.val;
        });
    });

    safeAdd('save-profile', 'click', async () => {
        const cSel = document.getElementById('course-select');
        const gSel = document.getElementById('group-select');
        const course = cSel ? cSel.value : "";
        const group = gSel ? gSel.value : "";
        if (!course || !group) { tg.showAlert("Пожалуйста, заполните все поля"); return; }
        const btn = document.getElementById('save-profile'); btn.textContent = "Сохранение..."; btn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/update_profile`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUser.user_id, course: course, group_num: group, subgroup: currentUser.subgroup })
            });
            if (res.ok) {
                currentUser.course = course; currentUser.group = group;
                closeOverlay('registration-overlay');
                updateUserInfo(); await loadSchedule();
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
            }
        } catch (e) { tg.showAlert("Ошибка при сохранении"); }
        finally { btn.textContent = "Сохранить"; btn.disabled = false; }
    });

    safeAdd('open-report-btn', 'click', () => {
        closeOverlay('settings-overlay');
        openOverlay('report-overlay');
    });

    safeAdd('send-report', 'click', async () => {
        const rt = document.getElementById('report-text');
        const text = rt ? rt.value.trim() : "";
        if (!text) return;
        const btn = document.getElementById('send-report');
        btn.disabled = true; btn.textContent = "Отправка...";
        try {
            const res = await fetch(`${API_BASE}/api/report`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUser.user_id, user_name: tg.initDataUnsafe?.user?.first_name || "User", text: text })
            });
            if (res.ok) {
                tg.showAlert("Жалоба отправлена админу. Спасибо!");
                closeOverlay('report-overlay');
                if (rt) rt.value = '';
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
            }
        } catch (e) { tg.showAlert("Ошибка при отправке"); }
        finally { btn.disabled = false; btn.textContent = "Отправить админу"; }
    });
}

function updateActiveDayButton() {
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const todayName = days[getAdjustedNow().getDay()];
    document.querySelectorAll('.day-btn').forEach(btn => {
        if (btn.dataset.day === currentDay) {
            btn.classList.add('active');
            btn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        } else btn.classList.remove('active');
        if (btn.dataset.day === todayName) btn.classList.add('today');
        else btn.classList.remove('today');
    });
}

function updateModeButtons() {
    document.querySelectorAll('.mode-btn').forEach(btn => {
        if (btn.dataset.mode === currentUser.mode) btn.classList.add('active');
        else btn.classList.remove('active');
    });
}

function showUpdatingMessage(msg) {
    const container = document.getElementById('schedule-container');
    if (container) container.innerHTML = `<div class="empty-state"><div class="empty-icon">🛠</div><p>${msg}</p></div>`;
    const nav = document.getElementById('days-nav');
    if (nav) nav.style.display = 'none';
}

init();
