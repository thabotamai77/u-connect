(() => {
    "use strict";

    let csrfToken = "";
    const gate = document.getElementById("authGate");
    const message = document.getElementById("authMessage");
    const loginForm = document.getElementById("loginForm");
    const registerForm = document.getElementById("registerForm");
    const originalFetch = window.fetch.bind(window);
    const appShell = document.getElementById("appShell");

    if (!gate || !message || !loginForm || !registerForm) return;

    window.fetch = (input, init = {}) => {
        const url = new URL(
            typeof input === "string" ? input : input.url,
            window.location.href
        );
        const method = (init.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
        if (url.origin === window.location.origin && url.pathname.startsWith("/api/")) {
            const headers = new Headers(input instanceof Request ? input.headers : undefined);
            new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
            if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && csrfToken) {
                headers.set("X-CSRF-Token", csrfToken);
            }
            return originalFetch(input, {
                ...init,
                headers,
                credentials: "same-origin"
            });
        }
        return originalFetch(input, init);
    };

    function showMessage(text, isError = false) {
        message.textContent = text;
        message.dataset.error = String(isError);
        message.hidden = !text;
    }

    function clearLegacyProfile() {
        try {
            localStorage.removeItem("studentId");
            localStorage.removeItem("studentName");
        } catch (error) {
            console.error("Could not clear legacy browser profile data.", error);
        }
    }

    function setAuthenticated(user) {
        window.uconnectUser = user;
        gate.hidden = true;
        if (appShell) appShell.inert = false;
        const appHeader = document.getElementById("appHeader");
        if (appHeader) appHeader.inert = false;
        document.querySelectorAll(".tabs").forEach((tabs) => { tabs.inert = false; });
        document.body.dataset.authenticated = "true";
        const greeting = document.getElementById("greeting");
        const profileName = document.getElementById("profileName");
        if (greeting) greeting.textContent = `${user.name}, what do you need?`;
        if (profileName) profileName.textContent = user.name;
        const controls = document.getElementById("authControls");
        if (controls) controls.hidden = false;
        const identity = document.getElementById("authIdentity");
        if (identity) identity.textContent = user.email;
        window.dispatchEvent(new CustomEvent("uconnect:authenticated", { detail: user }));
        const adminControls = document.querySelectorAll("[data-admin-only]");
        adminControls.forEach((element) => { element.hidden = user.role !== "administrator"; });
        const progress = document.getElementById("ringFg");
        const percentage = document.getElementById("pct");
        if (progress && percentage) {
            window.fetch("/api/progress")
                .then((response) => response.json().then((data) => {
                    if (!response.ok) throw new Error(data.error || "Progress is unavailable.");
                    return data.summary || data.progress || [];
                }))
                .then((entries) => {
                    const average = entries.length
                        ? Math.round(entries.reduce((sum, item) => sum + Number(item.percentage || 0), 0) / entries.length)
                        : 0;
                    const circumference = 2 * Math.PI * 32;
                    progress.style.strokeDasharray = circumference;
                    progress.style.strokeDashoffset = circumference * (1 - average / 100);
                    percentage.textContent = `${average}%`;
                    const ring = progress.closest(".ring");
                    if (ring) ring.setAttribute("aria-label", `Learning progress ${average} percent`);
                })
                .catch(() => {
                    percentage.textContent = "—";
                    progress.style.strokeDashoffset = 2 * Math.PI * 32;
                });
        }
    }

    async function readSession() {
        const response = await originalFetch("/api/session", { credentials: "same-origin" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not check the session.");
        csrfToken = result.csrf_token;
        if (result.user) setAuthenticated(result.user);
        return result.user;
    }

    async function loadSchools() {
        const response = await originalFetch("/api/schools", { credentials: "same-origin" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not load schools.");
        const select = registerForm.elements.school;
        select.replaceChildren(new Option("Choose your school", ""));
        result.schools.forEach((school) => {
            select.add(new Option(school.name, school.slug));
        });
        if (!result.schools.length) {
            select.add(new Option("School registration is not configured", ""));
            registerForm.querySelector('button[type="submit"]').disabled = true;
        }
    }

    async function verifyFromLink() {
        const token = new URLSearchParams(window.location.hash.slice(1)).get("verify");
        if (!token) return;
        window.history.replaceState(null, "", window.location.pathname);
        const response = await window.fetch("/api/auth/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token })
        });
        const result = await response.json();
        showMessage(result.message || result.error, !response.ok);
    }

    async function submitAuthForm(form, path) {
        if (!form.reportValidity()) return;
        const payload = Object.fromEntries(new FormData(form));
        try {
            const response = await window.fetch(path, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const result = await response.json();
            if (!response.ok) {
                showMessage(result.error || "The request could not be completed.", true);
                return;
            }
            if (result.user) {
                csrfToken = result.csrf_token;
                clearLegacyProfile();
                window.location.reload();
                return;
            }
            showMessage(result.message || "Check your email.");
            registerForm.hidden = true;
            loginForm.hidden = false;
        } catch (error) {
            showMessage(error.message || "Could not connect to U-CONNECT.", true);
        }
    }

    loginForm.addEventListener("submit", (event) => {
        event.preventDefault();
        submitAuthForm(loginForm, "/api/auth/login");
    });
    registerForm.addEventListener("submit", (event) => {
        event.preventDefault();
        submitAuthForm(registerForm, "/api/auth/register");
    });
    document.getElementById("showRegister").addEventListener("click", () => {
        loginForm.hidden = true;
        registerForm.hidden = false;
        showMessage("");
    });
    document.getElementById("showLogin").addEventListener("click", () => {
        registerForm.hidden = true;
        loginForm.hidden = false;
        showMessage("");
    });
    document.getElementById("resendVerification").addEventListener("click", async () => {
        const email = loginForm.elements.email.value.trim();
        if (!email) {
            showMessage("Enter your email address first.", true);
            loginForm.elements.email.focus();
            return;
        }
        try {
            const response = await window.fetch("/api/auth/resend-verification", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email })
            });
            const result = await response.json();
            showMessage(result.message || result.error, !response.ok);
        } catch (error) {
            showMessage(error.message || "Could not send verification email.", true);
        }
    });
    document.getElementById("logoutButton").addEventListener("click", async () => {
        try {
            const response = await window.fetch("/api/auth/logout", { method: "POST" });
            if (!response.ok) throw new Error("Could not sign out. Try again.");
            clearLegacyProfile();
            window.location.reload();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    (async () => {
        try {
            await loadSchools();
            await readSession();
            await verifyFromLink();
        } catch (error) {
            showMessage(`U-CONNECT could not connect: ${error.message}`, true);
        }
    })();
})();
