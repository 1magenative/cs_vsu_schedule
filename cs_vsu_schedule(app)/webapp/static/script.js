const tg = window.Telegram.WebApp;
const API_BASE = window.location.origin;

let currentUser = {
    user_id: tg.initDataUnsafe?.user?.id || 0,
    course: '',
    group: '',
    subgroup: '1',
    mode: 'обычный',
    timezone_offset: 0,
    server_time_drift: 0 // Разница между временем сервера и телефона
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
    
    try {
        await loadMetaData();
        const profile = await fetchProfile();
        
        const weekBadge = document.getElementById('week-badge');
        weekBadge.textContent = profile.week_type === 0 ? "Числитель" : "Знаменатель";
        
        if (profile.is_updating) {
            showUpdatingMessage("⚠️ Расписание обновляется. Зайдите позже.");
            return;
        }

        if (profile.registered) {
            currentUser = { ...currentUser, ...profile };
            
            // Вычисляем разницу времени с сервером
            if (profile.server_time) {
                const phoneNow = Math.floor(Date.now() / 1000);
                currentUser.server_time_drift = profile.server_time - phoneNow;
            }

            const now = getAdjustedNow();
            const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
            currentDay = days[now.getDay()];
            if (currentDay === "Воскресенье") currentDay = "Понедельник";
            
            updateActiveDayButton();
            updateUserInfo();
            updateModeButtons();
            await loadSchedule();
        } else {
            showRegistration();
        }
    } catch (e) {
        console.error("Init error", e);
    }
}

function getAdjustedNow() {
    const now = new Date();
    // Применяем drift (разница с сервером)
    if (currentUser.server_time_drift) {
        now.setSeconds(now.getSeconds() + currentUser.server_time_drift);
    }
    return now;
}

function updateUserInfo() {
    const info = document.getElementById('user-info');
    info.innerHTML = `
        <h1>${currentUser.course}</h1>
        <p>${currentUser.group}, подгруппа ${currentUser.subgroup}</p>
    `;
}

function updateCountdown() {
    if (!scheduleData) return;
    
    const now = getAdjustedNow();
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const todayName = days[now.getDay()];
    
    if (todayName === "Воскресенье") {
        document.getElementById('countdown-container').classList.add('hidden');
        return;
    }
    
    const todaysLessons = scheduleData[todayName] || [];
    const totalSeconds = (now.getHours() * 3600) + (now.getMinutes() * 60) + now.getSeconds();

    let targetSeconds = null;
    let label = "";
    let sub = "";

    // 1. Проверяем текущую пару
    for (const slot of TIME_SLOTS) {
        const start = parseTimeToSeconds(slot.start);
        const end = parseTimeToSeconds(slot.end);

        if (totalSeconds >= start && totalSeconds < end) {
            const lesson = findLessonInSchedule(todaysLessons, slot.start);
            if (lesson && !lesson.toLowerCase().includes("нет пары")) {
                targetSeconds = end;
                label = "До конца пары:";
                sub = lesson.replace(/🔹|▫️|\*|_/g, '').trim();
                break;
            }
        }
    }

    // 2. Ищем следующую пару сегодня
    if (targetSeconds === null) {
        for (const slot of TIME_SLOTS) {
            const start = parseTimeToSeconds(slot.start);
            if (totalSeconds < start) {
                const lesson = findLessonInSchedule(todaysLessons, slot.start);
                if (lesson && !lesson.toLowerCase().includes("нет пары")) {
                    targetSeconds = start;
                    label = "До начала пары:";
                    sub = "Следующая: " + lesson.replace(/🔹|▫️|\*|_/g, '').trim();
                    break;
                }
            }
        }
    }

    const container = document.getElementById('countdown-container');
    if (targetSeconds !== null) {
        const diff = targetSeconds - totalSeconds;
        const h = Math.floor(diff / 3600);
        const m = Math.floor((diff % 3600) / 60);
        const s = diff % 60;
        
        container.classList.remove('hidden');
        document.getElementById('countdown-label').textContent = label;
        document.getElementById('countdown-timer').textContent = 
            (h > 0 ? h + ":" : "") + 
            m.toString().padStart(2, '0') + ":" + 
            s.toString().padStart(2, '0');
        document.getElementById('countdown-sub').textContent = sub;
    } else {
        container.classList.add('hidden');
    }
}

function parseTimeToSeconds(timeStr) {
    const [h, m] = timeStr.split(':').map(Number);
    return (h * 3600) + (m * 60);
}

function findLessonInSchedule(lessons, timeStart) {
    // timeStart: "08:00"
    const t = timeStart.startsWith('0') ? timeStart.substring(1) : timeStart;
    for (const l of lessons) {
        // Очищаем строку расписания от лишнего для поиска
        const cleanLine = l.replace(/\s+/g, '');
        if (cleanLine.includes('*' + t + '-') || cleanLine.includes('*' + timeStart + '-')) {
            return l.split(': ').slice(1).join(': ');
        }
    }
    return null;
}

async function loadMetaData() {
    const res = await fetch(`${API_BASE}/api/meta`);
    metaData = await res.json();
    const courseSelect = document.getElementById('course-select');
    courseSelect.innerHTML = '<option value="">Выберите курс</option>';
    Object.keys(metaData).forEach(course => {
        const opt = document.createElement('option');
        opt.value = course;
        opt.textContent = course;
        courseSelect.appendChild(opt);
    });
}

async function fetchProfile() {
    const res = await fetch(`${API_BASE}/api/profile/${currentUser.user_id}`);
    return await res.json();
}

async function loadSchedule() {
    const container = document.getElementById('schedule-container');
    container.innerHTML = '<div class="loading-container"><div class="loader"></div><p>Загрузка...</p></div>';
    try {
        const res = await fetch(`${API_BASE}/api/schedule/${currentUser.user_id}`);
        const data = await res.json();
        if (data.updating) {
            showUpdatingMessage(data.message);
            return;
        }
        document.getElementById('days-nav').style.display = 'flex';
        scheduleData = data;
        renderSchedule();
    } catch (e) {
        container.innerHTML = '<div class="empty-state">Ошибка загрузки расписания</div>';
    }
}

function renderSchedule() {
    const container = document.getElementById('schedule-container');
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
        card.innerHTML = `
            <div class="lesson-time">${time}</div>
            <div class="lesson-name" style="${isNone ? 'color: var(--text-secondary); font-style: italic;' : ''}">${subject}</div>
        `;
        container.appendChild(card);
    });
}

function updateModeButtons() {
    document.querySelectorAll('.mode-btn').forEach(btn => {
        if (btn.dataset.mode === currentUser.mode) btn.classList.add('active');
        else btn.classList.remove('active');
    });
}

function showRegistration() {
    document.getElementById('registration-overlay').classList.remove('hidden');
}

function setupEventListeners() {
    document.getElementById('settings-btn').addEventListener('click', () => document.getElementById('settings-overlay').classList.remove('hidden'));
    document.getElementById('close-settings').addEventListener('click', () => document.getElementById('settings-overlay').classList.add('hidden'));
    document.getElementById('close-registration').addEventListener('click', () => document.getElementById('registration-overlay').classList.add('hidden'));
    document.getElementById('days-nav').addEventListener('click', (e) => {
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
    document.getElementById('edit-profile-btn').addEventListener('click', () => {
        document.getElementById('reg-title').textContent = "Изменение профиля";
        document.getElementById('settings-overlay').classList.add('hidden');
        showRegistration();
    });
    document.getElementById('course-select').addEventListener('change', (e) => {
        const course = e.target.value;
        const groupSelect = document.getElementById('group-select');
        groupSelect.innerHTML = '<option value="">Выберите группу</option>';
        if (course && metaData[course]) {
            metaData[course].forEach(group => {
                const opt = document.createElement('option');
                opt.value = group;
                opt.textContent = group;
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
    document.getElementById('save-profile').addEventListener('click', async () => {
        const course = document.getElementById('course-select').value;
        const group = document.getElementById('group-select').value;
        if (!course || !group) { tg.showAlert("Пожалуйста, заполните все поля"); return; }
        const btn = document.getElementById('save-profile');
        btn.textContent = "Сохранение...";
        btn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/update_profile`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUser.user_id, course: course, group_num: group, subgroup: currentUser.subgroup })
            });
            if (res.ok) {
                currentUser.course = course; currentUser.group = group;
                document.getElementById('registration-overlay').classList.add('hidden');
                updateUserInfo(); await loadSchedule();
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
            }
        } catch (e) { tg.showAlert("Ошибка при сохранении"); }
        finally { btn.textContent = "Сохранить"; btn.disabled = false; }
    });
    document.getElementById('open-report-btn').addEventListener('click', () => {
        document.getElementById('settings-overlay').classList.add('hidden');
        document.getElementById('report-overlay').classList.remove('hidden');
    });
    document.getElementById('close-report').addEventListener('click', () => document.getElementById('report-overlay').classList.add('hidden'));
    document.getElementById('send-report').addEventListener('click', async () => {
        const text = document.getElementById('report-text').value.trim();
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
                document.getElementById('report-overlay').classList.add('hidden');
                document.getElementById('report-text').value = '';
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

function showUpdatingMessage(msg) {
    const container = document.getElementById('schedule-container');
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">🛠</div><p>${msg}</p></div>`;
    document.getElementById('days-nav').style.display = 'none';
}

init();
