(function () {
  function updateStateTrack(card, status) {
    const nodes = card.querySelectorAll(".state-node");
    const order = { OPEN: 1, ACKNOWLEDGED: 2, RESOLVED: 3 };
    const current = order[status.toUpperCase()] || 1;
    nodes.forEach((node) => {
      node.classList.toggle("state-live", order[node.textContent.trim()] <= current);
    });
  }

  document.querySelectorAll(".alert-action-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const alertId = button.dataset.alertId;
      const status = button.dataset.status;
      const card = document.querySelector(`[data-alert-id="${CSS.escape(alertId)}"]`);
      const originalHtml = button.innerHTML;

      button.disabled = true;
      button.innerHTML = "Updating...";

      try {
        const response = await fetch(`/api/alerts/${encodeURIComponent(alertId)}/status`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not update alert.");

        card?.setAttribute("data-status", result.status);
        const badge = card?.querySelector(".alert-status-badge");
        if (badge) {
          badge.textContent = result.status;
          badge.dataset.status = result.status;
        }
        updateStateTrack(card, result.status);

        if (result.status === "Acknowledged") {
          card?.classList.add("alert-acknowledged");
          card?.querySelector("[data-status='Acknowledged']")?.remove();
        }

        if (result.status === "Resolved") {
          card?.classList.add("alert-resolved");
          card?.querySelectorAll(".alert-action-btn").forEach((action) => action.remove());
        }

        window.showToast?.(
          "ALERT UPDATED",
          `${alertId} marked as ${result.status}`,
          "success"
        );
      } catch (error) {
        console.error(error);
        window.showToast?.("UPDATE FAILED", error.message, "error");
      } finally {
        if (button.isConnected && !button.classList.contains("removed")) {
          button.disabled = false;
          button.innerHTML = originalHtml;
        }
      }
    });
  });
})();
