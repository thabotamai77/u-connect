(() => {
    "use strict";

    const byId = (id) => document.getElementById(id);
    const profileForm = byId("profileForm");
    const profileMessage = byId("profileMessage");

    async function readJson(path, options = {}) {
        const response = await fetch(path, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Request failed.");
        return data;
    }

    function initializeTheme() {
        const button = byId("themeBtn");
        try {
            if (localStorage.getItem("uconnect-theme") === "dark") {
                document.documentElement.dataset.theme = "dark";
            }
        } catch (error) {
            console.error("Could not read the selected theme.", error);
        }
        const updateButton = () => {
            const dark = document.documentElement.dataset.theme === "dark";
            button.textContent = dark ? "☀️" : "🌙";
            button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
            button.setAttribute("aria-pressed", String(dark));
        };
        updateButton();
        button.addEventListener("click", () => {
            const dark = document.documentElement.dataset.theme === "dark";
            if (dark) delete document.documentElement.dataset.theme;
            else document.documentElement.dataset.theme = "dark";
            try {
                localStorage.setItem("uconnect-theme", dark ? "light" : "dark");
            } catch (error) {
                console.error("Could not save the selected theme.", error);
            }
            updateButton();
        });
    }

    async function loadProfile() {
        const result = await readJson("/api/student");
        const student = result.student;
        if (!student) throw new Error("Student profile not found.");
        byId("profileName").textContent = student.full_name;
        byId("profileStatus").textContent = student.email || "U-CONNECT student";
        byId("profileFullName").value = student.full_name;
        byId("profileEmail").value = student.email || "";
        byId("profilePhone").value = student.phone || "";
    }

    async function loadProgress() {
        const result = await readJson("/api/progress");
        const subjects = result.summary || result.progress || [];
        const average = subjects.length
            ? Math.round(subjects.reduce((sum, item) => sum + Number(item.percentage || 0), 0) / subjects.length)
            : 0;
        byId("lessonCount").textContent = String(result.activity_count ?? result.progress?.length ?? 0);
        byId("quizCount").textContent = String(subjects.length);
        byId("profileProgress").textContent = `${average}%`;
        byId("lessonCount").nextElementSibling.textContent = "Progress entries";
        byId("quizCount").nextElementSibling.textContent = "Subjects tracked";
        const ring = byId("ringFg");
        const circumference = 2 * Math.PI * 32;
        ring.style.strokeDasharray = circumference;
        ring.style.strokeDashoffset = circumference * (1 - average / 100);
        byId("pct").textContent = `${average}%`;
        ring.closest(".ring").setAttribute("aria-label", `Learning progress ${average} percent`);
    }

    profileForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        profileMessage.textContent = "Saving…";
        try {
            await readJson("/api/student", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    full_name: byId("profileFullName").value,
                    phone: byId("profilePhone").value || null
                })
            });
            profileMessage.textContent = "Profile updated.";
            await loadProfile();
        } catch (error) {
            profileMessage.textContent = error.message;
        }
    });

    async function initialize() {
        initializeTheme();
        const policeContact = document.querySelector('#help a[href="tel:10111"]');
        if (policeContact) {
            policeContact.querySelector(".ic").textContent = "🚔";
            policeContact.querySelector("h3").textContent = "South African Police";
            policeContact.querySelector("p").textContent =
                "For urgent police assistance in South Africa, call 10111.";
            policeContact.querySelector(".go").textContent = "Call 10111 →";
        }
        const health = await readJson("/health").catch(() => null);
        byId("connectionStatus").textContent = health ? "🟢 Online" : "🔴 Offline";
        try {
            await Promise.all([loadProfile(), loadProgress()]);
        } catch (error) {
            byId("profileStatus").textContent = error.message;
        }
    }

    if (window.uconnectUser) initialize();
    else window.addEventListener("uconnect:authenticated", initialize, { once: true });

    const links = document.querySelectorAll(".tabs a");
    const sections = ["learn", "safe", "help", "profile"].map(byId);
    window.addEventListener("scroll", () => {
        let active = 0;
        sections.forEach((section, index) => {
            if (section.getBoundingClientRect().top < window.innerHeight * 0.5) active = index;
        });
        links.forEach((link, index) => link.classList.toggle("active", index === active));
    }, { passive: true });

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("./service-worker.js").catch((error) => {
                console.error("Could not register the service worker.", error);
            });
        });
    }
})();
