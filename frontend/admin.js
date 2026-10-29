(() => {
    "use strict";

    const message = document.getElementById("adminMessage");
    const list = document.getElementById("reportsList");
    const statuses = ["New", "In review", "Approved", "Resolved", "Rejected"];
    const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);

    async function loadReports() {
        message.textContent = "Loading reports…";
        const response = await fetch("/api/admin/incidents");
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not load reports.");
        const reports = result.incidents || [];
        message.textContent = reports.length
            ? `${reports.length} report${reports.length === 1 ? "" : "s"} for your school`
            : "No reports have been submitted to your school.";
        list.innerHTML = reports.map((report) => `
            <article class="card">
                <h2 class="title">${escapeHtml(report.incident_type)}</h2>
                <p>${escapeHtml(report.description)}</p>
                <p class="meta">Submitted by ${escapeHtml(report.full_name)} · ${escapeHtml(report.created_at)}</p>
                <label class="report-status">Status for report ${escapeHtml(report.id)}
                    <select data-report-status="${escapeHtml(report.id)}">
                        ${statuses.map((status) => `<option${status === report.status ? " selected" : ""}>${status}</option>`).join("")}
                    </select>
                </label>
            </article>`).join("");
    }

    list.addEventListener("change", async (event) => {
        const reportId = event.target.dataset.reportStatus;
        if (!reportId) return;
        try {
            const response = await fetch(`/api/admin/incidents/${encodeURIComponent(reportId)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: event.target.value })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Could not update the report.");
            await loadReports();
        } catch (error) {
            message.textContent = error.message;
            message.dataset.error = "true";
            await loadReports();
        }
    });

    async function initialize(user) {
        if (!user || user.role !== "administrator") {
            message.textContent = "School administrator access is required.";
            message.dataset.error = "true";
            return;
        }
        try {
            await loadReports();
        } catch (error) {
            message.textContent = error.message;
            message.dataset.error = "true";
        }
    }

    if (window.uconnectUser) {
        initialize(window.uconnectUser);
    } else {
        window.addEventListener(
            "uconnect:authenticated",
            (event) => initialize(event.detail),
            { once: true }
        );
    }
})();
