// Read-only wiring for the active project's aggregate production totals.
(function () {
  function activeProject(projects, selectedId) {
    const id = Number(selectedId);
    return projects.find((project) => Number(project.id) === id) || projects[0] || null;
  }

  async function refreshProjectProgressSummary() {
    const target = document.getElementById("projectProgressSummary");
    const select = document.getElementById("projectSelect");
    if (!target || !select || typeof window.formatProjectProgressSummary !== "function") return;

    try {
      const projects = await window.api("/api/projects");
      const project = activeProject(projects, select.value);
      target.textContent = project ? window.formatProjectProgressSummary(project) : "אין עדיין נתוני הפקה";
    } catch (_error) {
      target.textContent = "נתוני ההתקדמות אינם זמינים כרגע";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    refreshProjectProgressSummary();
    const select = document.getElementById("projectSelect");
    if (select) select.addEventListener("change", refreshProjectProgressSummary);
  });

  if (typeof window !== "undefined") {
    window.refreshProjectProgressSummary = refreshProjectProgressSummary;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { activeProject };
  }
})();
