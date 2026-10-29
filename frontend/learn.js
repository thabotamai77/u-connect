const api = (url, options = {}) => fetch(url, options).then(async response => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
});
const gradeSelect = document.getElementById('gradeSelect');
let subjectsCache = [];
const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[character]);
const safeHttpsUrl = value => {
    try {
        const url = new URL(value, window.location.origin);
        return url.protocol === 'https:' ? escapeHtml(url.href) : '#';
    } catch {
        return '#';
    }
};

const themeButton = document.getElementById('themeBtn');
const savedTheme = localStorage.getItem('uconnect-theme') || localStorage.getItem('uc-theme');
if (savedTheme !== 'dark') document.body.classList.add('light-mode');
function updateThemeButton() {
    const isLight = document.body.classList.contains('light-mode');
    themeButton.textContent = isLight ? '🌙' : '☀️';
    themeButton.setAttribute('aria-label', isLight ? 'Switch to dark mode' : 'Switch to light mode');
    themeButton.setAttribute('aria-pressed', String(!isLight));
}
updateThemeButton();
themeButton.addEventListener('click', () => {
    const isLight = document.body.classList.toggle('light-mode');
    localStorage.setItem('uconnect-theme', isLight ? 'light' : 'dark');
    updateThemeButton();
});

function value(id) { return document.getElementById(id).value; }
function post(url, body) {
    return api(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
}

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(item => item.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(panel => panel.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
}));

async function loadSubjects() {
    subjectsCache = await api('/api/subjects?grade=' + value('gradeSelect'));
    document.getElementById('subjectList').innerHTML = subjectsCache.map(subject => `
        <div class="card"><span class="title">${escapeHtml(subject.name)}</span>
        <span class="badge">${subject.is_compulsory ? 'Compulsory' : 'Elective'}</span></div>`).join('');
    const options = subjectsCache.map(subject => `<option value="${escapeHtml(subject.name)}">${escapeHtml(subject.name)}</option>`).join('');
    document.getElementById('ttSubject').innerHTML = options;
    document.getElementById('exSubject').innerHTML = options;
    document.getElementById('paperSubject').innerHTML = '<option value="">All subjects</option>' + options;
    await loadStudyCoach();
}

async function loadStudyCoach() {
    const recommendation = document.getElementById('coachRecommendation');
    const steps = document.getElementById('coachSteps');
    const reason = document.getElementById('coachReason');
    try {
        const plan = await api('/api/learning-plan');
        recommendation.textContent = plan.recommendation;
        steps.innerHTML = plan.steps.map(step => `<li>${escapeHtml(step)}</li>`).join('');
        reason.textContent = plan.reason;
    } catch (error) {
        recommendation.textContent = 'Your study plan is not available yet.';
        steps.innerHTML = '';
        reason.textContent = error.message;
    }
}

async function loadPapers() {
    const subject = value('paperSubject');
    const query = `/api/papers?grade=${value('gradeSelect')}${subject ? '&subject=' + encodeURIComponent(subject) : ''}`;
    const rows = await api(query);
    document.getElementById('paperList').innerHTML = rows.length ? rows.map(paper => `
        <div class="card"><div class="title">${escapeHtml(paper.title)}</div>
        <div class="meta">${escapeHtml(paper.subject)} • ${escapeHtml(paper.year)}${paper.term ? ' • ' + escapeHtml(paper.term) : ''}</div>
        <div class="meta"><a href="${safeHttpsUrl(paper.file_url)}" target="_blank" rel="noopener">📄 Paper</a>
        ${paper.memo_url ? ` &nbsp; <a href="${safeHttpsUrl(paper.memo_url)}" target="_blank" rel="noopener">✅ Memo</a>` : ''}</div></div>`).join('') : '<p class="hint">No papers yet for this grade and subject.</p>';
}

async function addPaper() {
    await post('/api/papers', { grade: value('gradeSelect'), subject: value('paperSubject') || subjectsCache[0].name, title: value('pTitle'), file_url: value('pUrl'), memo_url: value('pMemo'), year: value('pYear'), term: value('pTerm') });
    ['pTitle','pUrl','pMemo','pYear','pTerm'].forEach(id => document.getElementById(id).value = '');
    await loadPapers();
}

document.getElementById('addPaperButton').addEventListener('click', addPaper);
document.getElementById('paperSubject').addEventListener('change', loadPapers);

async function loadTimetable() {
    const rows = await api('/api/timetable?grade=' + value('gradeSelect'));
    const days = ['Monday','Tuesday','Wednesday','Thursday','Friday'];
    document.getElementById('ttGrid').innerHTML = days.map(day => {
        const periods = rows.filter(row => row.day === day);
        return `<div class="day-block"><h3>${escapeHtml(day)}</h3>${periods.length ? periods.map(period => `
            <div class="card"><button class="danger" data-delete-period="${period.id}" aria-label="Delete period">✕</button>
            <div class="title">${escapeHtml(period.start_time)} - ${escapeHtml(period.end_time)} · ${escapeHtml(period.subject)}</div>
            ${period.venue ? `<div class="meta">📍 ${escapeHtml(period.venue)}</div>` : ''}</div>`).join('') : '<p class="hint">No periods</p>'}</div>`;
    }).join('');
}
async function addPeriod() {
    await post('/api/timetable', { grade: value('gradeSelect'), day: value('ttDay'), start_time: value('ttStart'), end_time: value('ttEnd'), subject: value('ttSubject'), venue: value('ttVenue') });
    document.getElementById('ttVenue').value = '';
    await loadTimetable();
}
async function delPeriod(id) { await api('/api/timetable/' + id, {method: 'DELETE'}); await loadTimetable(); }
document.getElementById('ttGrid').addEventListener('click', event => {
    const button = event.target.closest('[data-delete-period]');
    if (button) delPeriod(button.dataset.deletePeriod).catch(error => {
        document.querySelector('.panel.active').insertAdjacentHTML(
            'beforeend',
            `<p class="hint error">${escapeHtml(error.message)}</p>`
        );
    });
});
document.getElementById('addPeriodButton').addEventListener('click', addPeriod);

async function loadExams() {
    const rows = await api('/api/exams?grade=' + value('gradeSelect'));
    document.getElementById('examList').innerHTML = rows.length ? rows.map(exam => `
        <div class="card"><div class="title">${escapeHtml(exam.subject)}</div>
        <div class="meta">📅 ${escapeHtml(exam.exam_date)} at ${escapeHtml(exam.start_time)} • ⏱️ ${escapeHtml(exam.duration_min)} min${exam.venue ? ' • 📍 ' + escapeHtml(exam.venue) : ''}</div>
        <div class="count">${exam.days_left > 0 ? exam.days_left + ' days left' : exam.days_left === 0 ? 'TODAY!' : 'Done'}</div></div>`).join('') : '<p class="hint">No exams added yet.</p>';
}
async function addExam() {
    await post('/api/exams', { grade: value('gradeSelect'), subject: value('exSubject'), exam_date: value('exDate'), start_time: value('exTime'), duration_min: value('exDur'), venue: value('exVenue') });
    document.getElementById('exVenue').value = '';
    document.getElementById('exDate').value = '';
    await loadExams();
}
document.getElementById('addExamButton').addEventListener('click', addExam);

async function refresh() {
    try { await loadSubjects(); await Promise.all([loadPapers(), loadTimetable(), loadExams()]); }
    catch (error) { document.querySelector('.panel.active').insertAdjacentHTML('beforeend', `<p class="hint error">${escapeHtml(error.message)}</p>`); }
}
gradeSelect.addEventListener('change', refresh);
refresh();
