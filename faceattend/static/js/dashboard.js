(() => {
  const $ = (sel) => document.querySelector(sel);
  const METHOD = { face: "Face", face_reviewed: "Confirmed", manual: "Manual" };
  let trendChart;
  let todayChart;

  function setStat(key, value) {
    const node = document.querySelector(`[data-stat="${key}"]`);
    if (node) node.textContent = value;
  }

  function initCharts() {
    trendChart = new Chart($("#trendChart"), {
      type: "bar",
      data: { labels: [], datasets: [{ label: "Present", data: [], backgroundColor: "#1e3a8a", borderRadius: 8, maxBarThickness: 36 }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });
    todayChart = new Chart($("#todayChart"), {
      type: "doughnut",
      data: {
        labels: ["On time", "Late", "Absent"],
        datasets: [{ data: [0, 0, 0], backgroundColor: ["#16a34a", "#f59e0b", "#e2e8f0"], borderWidth: 0 }],
      },
      options: { cutout: "68%", plugins: { legend: { position: "bottom" } } },
    });
  }

  function render(d) {
    const t = d.totals;
    setStat("total", t.total);
    setStat("enrolled", t.enrolled);
    setStat("present", t.present);
    setStat("late", t.late);
    setStat("absent", t.absent);
    setStat("percent", `${t.percent}%`);
    $("#percentBar").style.width = `${Math.min(t.percent, 100)}%`;

    trendChart.data.labels = d.trend.labels;
    trendChart.data.datasets[0].data = d.trend.present;
    trendChart.update();

    todayChart.data.datasets[0].data = [t.present - t.late, t.late, t.absent];
    todayChart.update();

    $("#liveFeed").innerHTML = d.recent.length
      ? d.recent.map((r) => `
          <li>
            <span class="dot ${r.status === "late" ? "late" : ""}"></span>
            <div>
              <strong>${esc(r.student.full_name)}</strong><br>
              <small>${esc(METHOD[r.method] || r.method)} · ${r.status === "late" ? "late" : "on time"}</small>
            </div>
            <time>${esc(r.check_in)}</time>
          </li>`).join("")
      : `<li class="muted">No check-ins yet today.</li>`;

    $("#recentBody").innerHTML = d.recent.length
      ? d.recent.map((r) => `
          <tr>
            <td>${esc(r.student.full_name)}<br><small class="muted">${esc(r.student.roll_no)} · ${esc(r.student.class_name)}</small></td>
            <td>${esc(r.date)}</td>
            <td>${esc(r.check_in)}</td>
            <td><span class="badge ${r.status === "late" ? "late" : "present"}">${r.status === "late" ? "Late" : "Present"}</span></td>
          </tr>`).join("")
      : `<tr><td colspan="4" class="empty">No records yet.</td></tr>`;

    $("#updated").textContent = d.generated_at;
  }

  async function load() {
    const { ok, data } = await apiFetch("/api/dashboard/stats");
    if (ok) render(data);
    else toast(data.message || "Could not refresh the dashboard.", "error");
  }

  document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    load();
    setInterval(load, 10000);
  });
})();
