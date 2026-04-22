const tg = window.Telegram.WebApp;
const API_BASE = window.location.origin;

let currentUser = {
    user_id: tg.initDataUnsafe?.user?.id || 0, // Fallback for testing
    course: '',
    group: '',
    subgroup: '1'
};

let scheduleData = null;
let metaData = null;
let currentDay = 'Понедельник';

// Initialize
tg.expand();
tg.ready();

async function init() {
    // Determine current day (default to Monday if Sunday)
    const days = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
    const d = new Date();
    currentDay = days[d.getDay()];
    if (currentDay === "Воскресенье") currentDay = "Понедельник";
    
    updateActiveDayButton();
    
    try {
        await loadMetaData();
        const profile = await fetchProfile();
        if (profile.registered) {
            currentUser = { ...currentUser, ...profile };
            updateUserInfo();
            await loadSchedule();
        } else {
            showRegistration();
        }
    } catch (e) {
        console.error("Init error", e);
    }
}

async function loadMetaData() {
    const res = await fetch(`${API_BASE}/api/meta`);
    metaData = await res.json();
    
    const courseSelect = document.getElementById('course-select');
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
        scheduleData = await res.json();
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
        // lesson is string like "🔹 *8:00 - 9:35*: Subject Name" or "▫️ 8:00 - 9:35: _Нет пары_"
        const card = document.createElement('div');
        card.className = 'lesson-card';
        card.style.animationDelay = `${index * 0.1}s`;
        
        const timeMatch = lesson.match(/(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})/);
        const time = timeMatch ? timeMatch[0] : '';
        const subject = lesson.replace(/🔹|▫️|\*|_/g, '').replace(time, '').replace(':', '').trim();
        
        const isNone = subject.toLowerCase().includes('нет пары');
        
        card.innerHTML = `
            <div class="lesson-time">${time}</div>
            <div class="lesson-name" style="${isNone ? 'color: var(--text-secondary); font-style: italic;' : ''}">${subject}</div>
        `;
        container.appendChild(card);
    });
}

function updateUserInfo() {
    const info = document.getElementById('user-info');
    info.innerHTML = `
        <h1>${currentUser.course}</h1>
        <p>Группа ${currentUser.group}, подгруппа ${currentUser.subgroup}</p>
    `;
}

function showRegistration() {
    const overlay = document.getElementById('registration-overlay');
    overlay.classList.remove('hidden');
}

// Event Listeners
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
    } else {
        groupSelect.disabled = true;
    }
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
    
    if (!course || !group) {
        tg.showAlert("Пожалуйста, заполните все поля");
        return;
    }
    
    const btn = document.getElementById('save-profile');
    btn.textContent = "Сохранение...";
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/update_profile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser.user_id,
                course: course,
                group_num: group,
                subgroup: currentUser.subgroup
            })
        });
        
        if (res.ok) {
            currentUser.course = course;
            currentUser.group = group;
            document.getElementById('registration-overlay').classList.add('hidden');
            updateUserInfo();
            await loadSchedule();
        }
    } catch (e) {
        tg.showAlert("Ошибка при сохранении");
    } finally {
        btn.textContent = "Сохранить";
        btn.disabled = false;
    }
});

document.getElementById('days-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.day-btn');
    if (!btn) return;
    
    currentDay = btn.dataset.day;
    updateActiveDayButton();
    renderSchedule();
});

function updateActiveDayButton() {
    document.querySelectorAll('.day-btn').forEach(btn => {
        if (btn.dataset.day === currentDay) {
            btn.classList.add('active');
            btn.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        } else {
            btn.classList.remove('active');
        }
    });
}

init();
