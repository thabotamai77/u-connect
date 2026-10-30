(() => {
    "use strict";

    const byId = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
    const statusClass = (status) => status.toLowerCase().replace(/\s+/g, "-");
    const validStatuses = ["New", "In review", "Approved", "Resolved", "Rejected"];
    const teams = ["Unassigned", "Support team", "Academic team", "Wellbeing team", "Practical support team"];

    let csrfToken = "";
    let user = null;
    let ownRequests = [];
    let schoolRequests = [];
    let activeFilter = "all";
    let toastTimer;

    async function api(path, options = {}) {
        const method = options.method || "GET";
        const headers = new Headers(options.headers || {});
        headers.set("Accept", "application/json");
        if (options.body !== undefined) headers.set("Content-Type", "application/json");
        if (["POST", "PATCH", "PUT", "DELETE"].includes(method)) {
            headers.set("X-CSRF-Token", csrfToken);
        }
        const response = await fetch(path, {
            ...options,
            method,
            headers,
            credentials: "same-origin"
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(result.error || "The request could not be completed.");
            error.status = response.status;
            error.code = result.code || "";
            throw error;
        }
        return result;
    }

    function showToast(message) {
        const toast = byId("toast");
        toast.textContent = message;
        toast.classList.add("show");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("show"), 3600);
    }

    function showAuthMessage(message, isError = false) {
        const element = byId("auth-message");
        element.textContent = message;
        element.classList.toggle("error-message", isError);
        element.hidden = !message;
    }

    function setAuthMode(mode) {
        const registering = mode === "register";
        byId("login-form").hidden = registering;
        byId("registration-form").hidden = !registering;
        byId("auth-title").textContent = registering ? "Create your account" : "Welcome to U-Connect";
        showAuthMessage("");
    }

    function setSignedInState() {
        const signedIn = Boolean(user);
        byId("auth-panel").hidden = signedIn;
        byId("student-view").hidden = !signedIn || document.querySelector(".nav-link.active")?.dataset.view === "admin-view";
        byId("admin-view").hidden = !signedIn || user.role !== "administrator"
            || document.querySelector(".nav-link.active")?.dataset.view !== "admin-view";
        byId("app-navigation").hidden = !signedIn;
        byId("account-actions").hidden = !signedIn;
        byId("admin-navigation").hidden = !signedIn || user.role !== "administrator";
        if (!signedIn) {
            document.querySelectorAll(".nav-link").forEach((button) => button.classList.remove("active"));
            return;
        }
        byId("header-name").textContent = user.name;
        document.querySelector(".avatar-small").textContent = user.name.charAt(0).toUpperCase();
        byId("profile-display-name").textContent = user.name;
        byId("profile-display-email").textContent = user.email;
        document.querySelector(".profile-avatar").textContent = user.name.charAt(0).toUpperCase();
        byId("profile-name-input").value = user.name;
        byId("profile-email-input").value = user.email;
        document.querySelectorAll(".nav-link").forEach((button) => {
            const active = !byId("admin-view").hidden
                ? button.dataset.view === "admin-view"
                : button.dataset.view === "student-view";
            button.classList.toggle("active", active);
            button.setAttribute("aria-current", active ? "page" : "false");
        });
    }

    function switchView(viewId) {
        if (!user || (viewId === "admin-view" && user.role !== "administrator")) return;
        document.querySelectorAll(".app-view").forEach((view) => {
            view.hidden = view.id !== viewId;
        });
        document.querySelectorAll(".nav-link").forEach((button) => {
            const active = button.dataset.view === viewId;
            button.classList.toggle("active", active);
            button.setAttribute("aria-current", active ? "page" : "false");
        });
        if (viewId === "admin-view") loadSchoolRequests().catch(showToast);
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function switchStudentPage(pageId) {
        const selectedPage = byId(pageId);
        if (!selectedPage || !selectedPage.classList.contains("student-page")) return;
        document.querySelectorAll(".student-page").forEach((page) => {
            page.classList.toggle("active", page === selectedPage);
        });
        document.querySelectorAll(".tab-link").forEach((button) => {
            const active = button.dataset.page === pageId;
            button.classList.toggle("active", active);
            button.setAttribute("aria-current", active ? "page" : "false");
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function formatDate(dateString) {
        const date = new Date(dateString);
        if (Number.isNaN(date.getTime())) return "Date unavailable";
        return new Intl.DateTimeFormat(undefined, {
            day: "numeric", month: "short", year: "numeric"
        }).format(date);
    }

    function renderOwnRequests() {
        const list = byId("request-list");
        const ordered = ownRequests.slice().sort((a, b) => new Date(b.created) - new Date(a.created));
        byId("request-total").textContent = String(ownRequests.length);
        byId("requests-empty").hidden = ownRequests.length > 0;
        list.innerHTML = ordered.slice(0, 5).map((item) => `
            <article class="request-item">
                <div><strong>${escapeHtml(item.category)}</strong><small>${escapeHtml(item.id)} · ${formatDate(item.created)}</small></div>
                <span class="status-badge status-${statusClass(item.status)}">${escapeHtml(item.status)}</span>
            </article>`).join("");
        const attention = ownRequests.filter((item) => ["New", "In review", "Approved"].includes(item.status)).length;
        byId("notification-count").textContent = String(attention);
        byId("notification-count").hidden = attention === 0;
    }

    async function loadOwnRequests() {
        const result = await api("/api/requests");
        ownRequests = result.requests;
        renderOwnRequests();
    }

    function getFilteredSchoolRequests() {
        const query = byId("request-search").value.trim().toLowerCase();
        const status = byId("status-filter").value;
        const category = byId("category-filter").value;
        const dateFrom = byId("date-from").value;
        const dateTo = byId("date-to").value;
        const invalidRange = Boolean(dateFrom && dateTo && dateFrom > dateTo);
        byId("date-filter-error").hidden = !invalidRange;
        if (invalidRange) return [];
        return schoolRequests.filter((item) => {
            const searchable = `${item.id} ${item.name} ${item.category} ${item.description}`.toLowerCase();
            const date = String(item.created).slice(0, 10);
            return searchable.includes(query)
                && (status === "all" || item.status === status)
                && (category === "all" || item.category === category)
                && (!dateFrom || date >= dateFrom)
                && (!dateTo || date <= dateTo);
        });
    }

    function renderSchoolRequests() {
        const matching = getFilteredSchoolRequests();
        byId("queue-count").textContent = `${matching.length} ${matching.length === 1 ? "request" : "requests"}`;
        byId("admin-requests-empty").hidden = matching.length > 0;
        byId("admin-request-rows").innerHTML = matching.map((item) => `
            <tr>
                <td><strong>${escapeHtml(item.category)}</strong><br><small>${escapeHtml(item.id)}</small></td>
                <td>${escapeHtml(item.name)}</td>
                <td>${formatDate(item.created)}</td>
                <td><span class="status-badge status-${statusClass(item.status)}">${escapeHtml(item.status)}</span></td>
                <td><label class="visually-hidden" for="assign-${escapeHtml(item.id)}">Assign ${escapeHtml(item.id)}</label>
                    <select id="assign-${escapeHtml(item.id)}" data-assign-request="${escapeHtml(item.id)}">
                        ${teams.map((team) => `<option${item.assigned === team ? " selected" : ""}>${team}</option>`).join("")}
                    </select>
                </td>
                <td><label class="visually-hidden" for="status-${escapeHtml(item.id)}">Update status for ${escapeHtml(item.id)}</label>
                    <select id="status-${escapeHtml(item.id)}" data-update-request="${escapeHtml(item.id)}">
                        ${validStatuses.map((status) => `<option${item.status === status ? " selected" : ""}>${status}</option>`).join("")}
                    </select>
                </td>
            </tr>`).join("");
    }

    async function loadSchoolRequests() {
        const result = await api("/api/admin/requests");
        schoolRequests = result.requests;
        renderSchoolRequests();
    }

    function updateServiceFilter() {
        const query = byId("service-search").value.trim().toLowerCase();
        let visible = 0;
        byId("service-grid").querySelectorAll(".service-card").forEach((card) => {
            const matches = (activeFilter === "all" || card.dataset.category === activeFilter)
                && `${card.dataset.search} ${card.textContent}`.toLowerCase().includes(query);
            card.hidden = !matches;
            if (matches) visible += 1;
        });
        byId("service-empty").hidden = visible > 0;
    }

    function openRequestDialog(category) {
        byId("form-error").hidden = true;
        byId("request-category").value = category || "";
        byId("request-dialog").showModal();
    }

    function csvCell(value) {
        let text = String(value ?? "");
        if (/^[\t\r=+\-@]/.test(text)) text = `'${text}`;
        return `"${text.replace(/"/g, '""')}"`;
    }

    async function loadSchools() {
        const result = await api("/api/schools");
        const select = byId("school-select");
        select.innerHTML = '<option value="">Choose your school</option>';
        result.schools.forEach((school) => {
            const option = document.createElement("option");
            option.value = school.slug;
            option.textContent = school.name;
            select.append(option);
        });
        if (result.schools.length === 0) {
            select.innerHTML = '<option value="">School registration is not configured</option>';
            byId("registration-form").querySelector('button[type="submit"]').disabled = true;
        }
    }

    async function handleVerificationLink() {
        const params = new URLSearchParams(window.location.hash.slice(1));
        const token = params.get("verify");
        if (!token) return;
        window.history.replaceState(null, "", window.location.pathname);
        try {
            const result = await api("/api/auth/verify", {
                method: "POST",
                body: JSON.stringify({ token })
            });
            showAuthMessage(result.message);
        } catch (error) {
            showAuthMessage(error.message, true);
        }
    }

    document.querySelectorAll(".nav-link").forEach((button) => {
        button.addEventListener("click", () => switchView(button.dataset.view));
    });
    document.querySelectorAll(".tab-link").forEach((button) => {
        button.addEventListener("click", () => switchStudentPage(button.dataset.page));
    });
    document.querySelectorAll("[data-go-page]").forEach((button) => {
        button.addEventListener("click", () => switchStudentPage(button.dataset.goPage));
    });
    byId("show-registration").addEventListener("click", () => setAuthMode("register"));
    byId("show-login").addEventListener("click", () => setAuthMode("login"));
    byId("login-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!event.currentTarget.reportValidity()) return;
        const data = Object.fromEntries(new FormData(event.currentTarget));
        try {
            const result = await api("/api/auth/login", {
                method: "POST", body: JSON.stringify(data)
            });
            csrfToken = result.csrf_token;
            user = result.user;
            setSignedInState();
            await loadOwnRequests();
            showAuthMessage("");
        } catch (error) {
            showAuthMessage(error.message, true);
        }
    });
    byId("registration-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!event.currentTarget.reportValidity()) return;
        const data = Object.fromEntries(new FormData(event.currentTarget));
        try {
            const result = await api("/api/auth/register", {
                method: "POST", body: JSON.stringify(data)
            });
            setAuthMode("login");
            showAuthMessage(result.message);
        } catch (error) {
            showAuthMessage(error.message, true);
        }
    });
    byId("resend-verification").addEventListener("click", async () => {
        const email = byId("login-form").elements.email.value.trim();
        if (!email) {
            showAuthMessage("Enter your email address first.", true);
            byId("login-form").elements.email.focus();
            return;
        }
        try {
            const result = await api("/api/auth/resend-verification", {
                method: "POST", body: JSON.stringify({ email })
            });
            showAuthMessage(result.message);
        } catch (error) {
            showAuthMessage(error.message, true);
        }
    });
    byId("logout-button").addEventListener("click", async () => {
        try {
            await api("/api/auth/logout", { method: "POST" });
            const result = await api("/api/session");
            csrfToken = result.csrf_token;
            user = null;
            ownRequests = [];
            schoolRequests = [];
            switchStudentPage("home");
            setSignedInState();
            setAuthMode("login");
        } catch (error) {
            showToast(error.message);
        }
    });

    document.querySelectorAll(".filter-chip").forEach((button) => {
        button.addEventListener("click", () => {
            activeFilter = button.dataset.filter;
            document.querySelectorAll(".filter-chip").forEach((chip) => {
                const selected = chip === button;
                chip.classList.toggle("selected", selected);
                chip.setAttribute("aria-pressed", String(selected));
            });
            updateServiceFilter();
        });
    });
    byId("service-search").addEventListener("input", updateServiceFilter);
    document.querySelectorAll("[data-request]").forEach((button) => {
        button.addEventListener("click", () => openRequestDialog(button.dataset.request));
    });
    byId("get-started").addEventListener("click", () => {
        byId("services").scrollIntoView({ behavior: "smooth" });
        byId("service-search").focus({ preventScroll: true });
    });
    byId("new-request-button").addEventListener("click", () => openRequestDialog());
    byId("browse-services").addEventListener("click", () => {
        switchStudentPage("home");
        byId("services").scrollIntoView({ behavior: "smooth" });
    });
    byId("faq-button").addEventListener("click", () => {
        byId("faq-list").hidden = !byId("faq-list").hidden;
    });
    byId("notification-button").addEventListener("click", () => {
        const pending = ownRequests.filter((item) => ["New", "In review"].includes(item.status)).length;
        showToast(pending
            ? `You have ${pending} request${pending === 1 ? "" : "s"} being reviewed. Check My requests for updates.`
            : "You’re all caught up. No new request updates.");
        switchStudentPage("get-help");
        byId("my-requests").scrollIntoView({ behavior: "smooth" });
    });
    byId("profile-button").addEventListener("click", () => byId("profile-dialog").showModal());
    byId("edit-profile-button").addEventListener("click", () => byId("profile-dialog").showModal());
    byId("profile-logout-button").addEventListener("click", () => byId("logout-button").click());
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
        button.addEventListener("click", () => button.closest("dialog").close());
    });
    document.querySelectorAll("dialog").forEach((dialog) => {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    });

    byId("request-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        if (!form.reportValidity()) return;
        const data = new FormData(form);
        try {
            const result = await api("/api/requests", {
                method: "POST",
                body: JSON.stringify({
                    category: data.get("category"),
                    description: data.get("description")
                })
            });
            await loadOwnRequests();
            if (user.role === "administrator" && !byId("admin-view").hidden) {
                await loadSchoolRequests();
            }
            form.reset();
            byId("request-dialog").close();
            showToast(`Request ${result.id} sent. You can follow updates in My requests.`);
        } catch (error) {
            byId("form-error").textContent = error.message;
            byId("form-error").hidden = false;
        }
    });
    byId("profile-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!event.currentTarget.reportValidity()) return;
        const name = byId("profile-name-input").value.trim();
        try {
            await api("/api/profile", {
                method: "PATCH", body: JSON.stringify({ name })
            });
            user = { ...user, name };
            setSignedInState();
            byId("profile-dialog").close();
            showToast("Your profile has been updated.");
        } catch (error) {
            showToast(error.message);
        }
    });

    ["request-search", "status-filter", "category-filter", "date-from", "date-to"].forEach((id) => {
        byId(id).addEventListener("input", renderSchoolRequests);
        byId(id).addEventListener("change", renderSchoolRequests);
    });
    byId("admin-request-rows").addEventListener("change", async (event) => {
        const requestId = event.target.dataset.assignRequest || event.target.dataset.updateRequest;
        if (!requestId) return;
        const field = event.target.dataset.assignRequest ? "assigned" : "status";
        const value = event.target.value;
        try {
            await api(`/api/admin/requests/${encodeURIComponent(requestId)}`, {
                method: "PATCH",
                body: JSON.stringify({ [field]: value })
            });
            await loadSchoolRequests();
            showToast(`Request ${requestId} updated.`);
        } catch (error) {
            showToast(error.message);
            await loadSchoolRequests();
        }
    });
    byId("export-button").addEventListener("click", () => {
        const rows = [["Request ID", "Student", "Category", "Status", "Assigned to", "Created"]];
        const filtered = getFilteredSchoolRequests();
        if (!byId("date-filter-error").hidden) {
            byId("date-from").focus();
            showToast("Correct the date range before exporting.");
            return;
        }
        filtered.forEach((item) => rows.push([
            item.id, item.name, item.category, item.status, item.assigned || "", item.created
        ]));
        const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `u-connect-requests-${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        showToast("Request report downloaded as CSV.");
    });
    byId("theme-button").addEventListener("click", () => {
        document.body.classList.toggle("dark");
        try {
            localStorage.setItem("uconnect.theme", document.body.classList.contains("dark") ? "dark" : "light");
        } catch (error) {
            console.error("Could not save the selected colour theme.", error);
        }
    });

    async function initialize() {
        try {
            const result = await api("/api/session");
            csrfToken = result.csrf_token;
            user = result.user;
            setSignedInState();
            await loadSchools();
            await handleVerificationLink();
            if (user) {
                await loadOwnRequests();
                if (user.role === "administrator") await loadSchoolRequests();
            }
        } catch (error) {
            showAuthMessage(`U-Connect could not connect to its server: ${error.message}`, true);
        }
        try {
            if (localStorage.getItem("uconnect.theme") === "dark") document.body.classList.add("dark");
        } catch (error) {
            console.error("Could not read the selected colour theme.", error);
        }
    }

    initialize();
})();
