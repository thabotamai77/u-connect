// app.js
// Student Safety & Campus App

// API Base URL - update this when deploying to production
const API_BASE = window.location.hostname === 'localhost' 
    ? '' 
    : 'https://u-connect-uf4m.onrender.com';

function openPage(pageName) {
    const pages = document.querySelectorAll(".page");

    pages.forEach(page => {
        page.classList.remove("active");
    });

    const selectedPage = document.getElementById(pageName);

    if (selectedPage) {
        selectedPage.classList.add("active");
    }

    const navButtons = document.querySelectorAll("[data-page]");
    navButtons.forEach(button => {
        button.classList.toggle("active", button.dataset.page === pageName);
    });
}

async function apiRequest(url, options = {}) {
    const fullUrl = url.startsWith('http') ? url : API_BASE + url;
    const response = await fetch(fullUrl, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        ...options
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(data.error || "Request failed");
    }

    return data;
}

document.addEventListener("DOMContentLoaded", () => {
    console.log("Student App loaded successfully 🚀");

    // =========================
    // NAVIGATION
    // =========================

    const navButtons = document.querySelectorAll("[data-page]");
    const pages = document.querySelectorAll(".page");

    navButtons.forEach(button => {
        button.addEventListener("click", () => {
            const pageName = button.dataset.page;
            openPage(pageName);
        });
    });

    pages.forEach(page => {
        if (page.classList.contains("active")) {
            page.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    });


    // =========================
    // EMERGENCY BUTTON
    // =========================

    const emergencyButton = document.getElementById("emergencyBtn");

    if (emergencyButton) {
        emergencyButton.addEventListener("click", () => {

            const confirmed = confirm(
                "🚨 EMERGENCY ALERT\n\nAre you sure you want to send an emergency alert?"
            );

            if (confirmed) {
                sendEmergencyAlert();
            }
        });
    }


    // =========================
    // EMERGENCY ALERT
    // =========================

    function sendEmergencyAlert() {

        // Get user's location if supported
        if (navigator.geolocation) {

            navigator.geolocation.getCurrentPosition(
                position => {

                    const latitude = position.coords.latitude;
                    const longitude = position.coords.longitude;

                    console.log("Emergency location:", latitude, longitude);

                    alert(
                        "🚨 Emergency alert sent!\n\n" +
                        "Your location has been recorded."
                    );

                    // Later we can send this information
                    // to your Python backend.
                },

                () => {
                    alert(
                        "🚨 Emergency alert sent!\n\n" +
                        "Location permission was not available."
                    );
                }
            );

        } else {
            alert("🚨 Emergency alert sent!");
        }
    }


    // =========================
    // REPORT INCIDENT
    // =========================

    const reportForm = document.getElementById("reportForm");

    if (reportForm) {

        reportForm.addEventListener("submit", async event => {

            event.preventDefault();

            const type = document.getElementById("incidentType")?.value;
            const description = document.getElementById("description")?.value;

            if (!type || !description) {
                alert("Please complete all required fields.");
                return;
            }

            try {
                await apiRequest("/api/incident", {
                    method: "POST",
                    body: JSON.stringify({
                        incident_type: type,
                        description: description
                    })
                });

                alert(
                    "✅ Report submitted successfully.\n\n" +
                    "Thank you for helping keep the campus safe."
                );

                reportForm.reset();
            } catch (error) {
                alert(error.message || "Could not save your report.");
            }
        });
    }


    //CAMPUS ANNOUNCEMENTS

    const announcementContainer = document.getElementById("announcements");

    async function loadAnnouncements() {
        if (!announcementContainer) return;

        try {
            const data = await apiRequest("/api/announcements");
            const announcements = data.announcements || [];

            announcementContainer.innerHTML = "";

            announcements.forEach(item => {
                const announcement = document.createElement("div");
                announcement.className = "announcement";
                announcement.innerHTML = `
                    <h3>${item.title}</h3>
                    <p>${item.message}</p>
                `;
                announcementContainer.appendChild(announcement);
            });
        } catch {
            const fallbackAnnouncements = [
                {
                    title: "📢 Campus Update",
                    message: "Check your student portal for the latest announcements."
                },
                {
                    title: "🏆 Sports Day",
                    message: "Don't forget to support your campus teams!"
                },
                {
                    title: "💻 IT Students",
                    message: "Remember to submit your projects before the deadline."
                }
            ];

            announcementContainer.innerHTML = "";

            fallbackAnnouncements.forEach(item => {
                const announcement = document.createElement("div");
                announcement.className = "announcement";
                announcement.innerHTML = `
                    <h3>${item.title}</h3>
                    <p>${item.message}</p>
                `;
                announcementContainer.appendChild(announcement);
            });
        }
    }

    loadAnnouncements();

    async function loadProgress() {
        try {
            const data = await apiRequest("/api/progress");
            const progressEntries = data.progress || [];

            if (!progressEntries.length) {
                document.getElementById("overallProgressText").textContent = "0%";
                document.getElementById("overallProgressBar").style.width = "0%";
                document.getElementById("progressSummaryText").textContent = "Add your first study progress to get started.";
                return;
            }

            const total = progressEntries.reduce((sum, item) => sum + Number(item.percentage || 0), 0);
            const average = Math.round(total / progressEntries.length);

            const progressBar = document.getElementById("overallProgressBar");
            const progressText = document.getElementById("overallProgressText");
            const summaryText = document.getElementById("progressSummaryText");

            if (progressBar) progressBar.style.width = `${average}%`;
            if (progressText) progressText.textContent = `${average}%`;
            if (summaryText) summaryText.textContent = `Latest subject: ${progressEntries[0].subject || "Learning"} | ${average}% complete.`;
        } catch (error) {
            const progressText = document.getElementById("overallProgressText");
            const summaryText = document.getElementById("progressSummaryText");
            if (progressText) progressText.textContent = "0%";
            if (summaryText) summaryText.textContent = "Progress data is not available yet.";
        }
    }

    loadProgress();


    // =========================
    // DARK MODE
    // =========================

    const darkModeButton =
        document.getElementById("darkModeBtn") ||
        document.getElementById("themeButton");

    if (darkModeButton) {

        darkModeButton.addEventListener("click", () => {

            document.body.classList.toggle("dark-mode");

            const darkModeEnabled =
                document.body.classList.contains("dark-mode");

            localStorage.setItem(
                "darkMode",
                darkModeEnabled
            );
        });
    }


    // Load saved dark mode
    const savedDarkMode = localStorage.getItem("darkMode");

    if (savedDarkMode === "true") {
        document.body.classList.add("dark-mode");
    }


    // =========================
    // ONLINE / OFFLINE STATUS
    // =========================

    function updateConnectionStatus() {

        const status = document.getElementById("connectionStatus");

        if (!status) return;

        if (navigator.onLine) {
            status.textContent = "🟢 Online";
        } else {
            status.textContent = "🔴 Offline";
        }
    }

    window.addEventListener("online", updateConnectionStatus);
    window.addEventListener("offline", updateConnectionStatus);

    updateConnectionStatus();


    // =========================
    // STUDENT PROFILE
    // =========================

    const nameElement = document.getElementById("studentName");
    const profileNameElement = document.getElementById("profileName");

    function updateDisplayedName(name) {
        const safeName = name && name.trim() ? name.trim() : "Student";

        if (nameElement) {
            nameElement.textContent = safeName;
        }

        if (profileNameElement) {
            profileNameElement.textContent = safeName;
        }

        localStorage.setItem("studentName", safeName);
    }

    const studentName = localStorage.getItem("studentName");
    updateDisplayedName(studentName || "Student");

    function populateStudentSelect(students) {
        const progressStudentSelect = document.getElementById("progressStudent");
        if (!progressStudentSelect) return;

        const savedStudentId = localStorage.getItem("studentId");
        progressStudentSelect.innerHTML = "<option value=''>Select student</option>";

        students.forEach(student => {
            const option = document.createElement("option");
            option.value = student.id;
            option.textContent = student.full_name || "Student";

            if (String(savedStudentId) === String(student.id)) {
                option.selected = true;
            }

            progressStudentSelect.appendChild(option);
        });

        if (!students.length) {
            progressStudentSelect.innerHTML = "<option value=''>Save a profile first</option>";
        }
    }

    async function loadSavedStudents() {
        const list = document.getElementById("savedStudentsList");
        if (!list) return;

        try {
            const data = await apiRequest("/api/students");
            const students = data.students || [];

            populateStudentSelect(students);

            if (!students.length) {
                list.innerHTML = "<p class='saved-student empty'>No saved students yet.</p>";
                return;
            }

            const latestName = students[0]?.full_name || "Student";
            updateDisplayedName(latestName);

            list.innerHTML = students.map(student => `
                <div class="saved-student">
                    <strong>${student.full_name}</strong>
                    <small>${student.email || "No email"}</small>
                </div>
            `).join("");
        } catch (error) {
            list.innerHTML = `<p class="saved-student empty">${error.message || "Could not load saved students."}</p>`;
        }
    }

    async function loadProgressList() {
        const progressList = document.getElementById("progressList");
        if (!progressList) return;

        try {
            const data = await apiRequest("/api/progress");
            const entries = data.progress || [];

            if (!entries.length) {
                progressList.innerHTML = "<p class='saved-student empty'>No progress saved yet.</p>";
                return;
            }

            progressList.innerHTML = entries.slice(0, 5).map(item => `
                <div class="saved-student">
                    <strong>${item.full_name || "Student"}</strong>
                    <small>${item.subject}: ${item.percentage}%</small>
                </div>
            `).join("");
        } catch (error) {
            progressList.innerHTML = `<p class="saved-student empty">${error.message || "Could not load progress."}</p>`;
        }
    }

    loadSavedStudents();
    loadProgressList();


    // =========================
    // SAVE STUDENT NAME
    // =========================

    const profileForm =
        document.getElementById("profileForm");

    if (profileForm) {

        profileForm.addEventListener("submit", async event => {

            event.preventDefault();

            const name = document.getElementById("name")?.value;

            if (!name) return;

            try {
                const result = await apiRequest("/api/student", {
                    method: "POST",
                    body: JSON.stringify({
                        full_name: name
                    })
                });

                localStorage.setItem("studentId", result.student_id);
                updateDisplayedName(name);
                await loadSavedStudents();
                await loadProgressList();
                alert("Profile saved successfully!");
            } catch (error) {
                alert(error.message || "Could not save profile.");
            }
        });
    }

    const progressForm = document.getElementById("progressForm");

    if (progressForm) {
        progressForm.addEventListener("submit", async event => {
            event.preventDefault();

            const selectedStudentId = document.getElementById("progressStudent")?.value;
            const subject = document.getElementById("progressSubject")?.value?.trim();
            const percentage = Number(document.getElementById("progressPercentage")?.value);

            if (!selectedStudentId || !subject || Number.isNaN(percentage)) {
                alert("Please select a student, enter a subject, and provide a percentage.");
                return;
            }

            const clampedPercentage = Math.max(0, Math.min(100, percentage));

            try {
                await apiRequest("/api/progress", {
                    method: "POST",
                    body: JSON.stringify({
                        student_id: Number(selectedStudentId),
                        subject,
                        percentage: clampedPercentage
                    })
                });

                progressForm.reset();
                await loadProgress();
                await loadProgressList();
                alert("Progress saved successfully!");
            } catch (error) {
                alert(error.message || "Could not save progress.");
            }
        });
    }

});