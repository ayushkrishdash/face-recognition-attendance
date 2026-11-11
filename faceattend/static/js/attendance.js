(() => {
  const $ = (sel) => document.querySelector(sel);
  const el = {
    video: $("#liveVideo"), empty: $("#stageEmpty"), start: $("#startCam"), stop: $("#stopCam"),
    scan: $("#scanNow"), auto: $("#autoScan"), status: $("#camStatus"), error: $("#camError"),
    hint: $("#scanHint"), result: $("#resultCard"), todayBody: $("#todayBody"),
    todayCount: $("#todayCount"), unmarked: $("#unmarkedList"), search: $("#manualSearch"),
  };
  const SCAN_INTERVAL_MS = 2000;
  const METHOD = { face: "Face", face_reviewed: "Confirmed", manual: "Manual" };
  let timer = null;
  let busy = false;
  let cooldownUntil = 0;
  let unmarked = [];

  const statusBadge = (s) => `<span class="badge ${s === "late" ? "late" : "present"}">${s === "late" ? "Late" : "Present"}</span>`;

  function setStatus(text, live = false) {
    el.status.textContent = text;
    el.status.classList.toggle("live", live);
  }

  function showError(msg) {
    el.error.textContent = msg || "";
    el.error.hidden = !msg;
  }

  function setRunning(running) {
    el.start.disabled = running;
    el.stop.disabled = !running;
    el.scan.disabled = !running;
    el.video.hidden = !running;
    el.empty.hidden = running;
  }

  function renderIdle() {
    el.result.innerHTML = `<div class="result"><i data-lucide="user-search"></i><p>The result of each scan appears here.</p></div>`;
    lucide.createIcons();
  }

  function renderCard(type, title, bodyHtml) {
    el.result.innerHTML = `<div class="result-card ${type}" role="status"><h3>${esc(title)}</h3>${bodyHtml}</div>`;
  }

  const studentBlock = (s, a) => `
    <strong class="name">${esc(s.full_name)}</strong>
    <span>Roll ${esc(s.roll_no)} · ${esc(s.class_name)}${s.section ? " " + esc(s.section) : ""}</span>
    <span>Status: ${a.status === "late" ? "Late" : "Present"} · ${esc(a.date)} ${esc((a.check_in || "").slice(0, 5))}</span>`;

  function renderReview(candidates) {
    const items = candidates.map((c) => `
      <div class="candidate">
        <div>
          <strong>${esc(c.student.full_name)}</strong><br>
          <small class="muted">Roll ${esc(c.student.roll_no)} · ${esc(c.student.class_name)} · distance ${esc(c.distance)}</small>
        </div>
        <button class="btn primary small" data-confirm="${esc(c.student.id)}">Confirm</button>
      </div>`).join("");
    el.result.innerHTML = `
      <div class="result-card review" role="status">
        <h3>Uncertain match</h3>
        <p>Confirm the correct student, or dismiss this result. Lower distance means a closer match.</p>
        ${items}
        <div class="btn-row"><button class="btn small" data-dismiss>None of these</button></div>
      </div>`;
  }

  function handleResult(d) {
    switch (d.status) {
      case "marked":
        cooldownUntil = Date.now() + 4000;
        renderCard("success", "Attendance Marked Successfully", studentBlock(d.student, d.attendance));
        el.hint.textContent = "";
        toast(`${d.student.full_name} marked ${d.attendance.status}`);
        refreshToday();
        break;
      case "duplicate":
        cooldownUntil = Date.now() + 4000;
        renderCard("warn", "Already marked today",
          `${studentBlock(d.student, d.attendance)}<p>No duplicate entry was created.</p>`);
        refreshToday();
        break;
      case "review":
        cooldownUntil = Date.now() + 10000;
        renderReview(d.candidates);
        break;
      case "unknown":
        cooldownUntil = Date.now() + 3000;
        renderCard("danger", "Unknown Student",
          "<p>This face does not match any enrolled student. Check the person or use manual attendance.</p>");
        break;
      case "no_face":
      case "multiple_faces":
      case "face_too_small":
        el.hint.textContent = d.message;
        break;
      default:
        renderCard("danger", "Scan could not be completed", `<p>${esc(d.message || "Unexpected response from the server.")}</p>`);
    }
  }

  async function scanOnce(force) {
    if (busy || !CameraKit.isRunning()) return;
    if (!force && Date.now() < cooldownUntil) return;
    busy = true;
    setStatus("Scanning…", true);
    try {
      const blob = await CameraKit.capture(el.video);
      if (!blob) return;
      const form = new FormData();
      form.append("image", blob, "frame.jpg");
      const { data } = await apiFetch("/api/attendance/verify", { method: "POST", body: form });
      handleResult(data);
    } catch (err) {
      renderCard("danger", "Scan failed", `<p>${esc(err.message)}</p>`);
    } finally {
      busy = false;
      if (CameraKit.isRunning()) setStatus("Camera live", true);
    }
  }

  function startAuto() {
    stopAuto();
    timer = setInterval(() => scanOnce(false), SCAN_INTERVAL_MS);
    el.hint.textContent = "Auto-scan is on. Students can simply face the camera.";
  }

  function stopAuto() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  async function startCamera() {
    showError("");
    try {
      await CameraKit.start(el.video);
      setRunning(true);
      setStatus("Camera live", true);
      if (el.auto.checked) startAuto();
    } catch (err) {
      showError(CameraKit.errorMessage(err));
      setStatus("Camera unavailable");
    }
  }

  function stopCamera() {
    stopAuto();
    CameraKit.stop();
    el.video.srcObject = null;
    setRunning(false);
    setStatus("Camera off");
    el.hint.textContent = "";
  }

  async function refreshToday() {
    const { data } = await apiFetch("/api/attendance/today");
    if (!data.records) return;
    el.todayCount.textContent = data.records.length;
    el.todayBody.innerHTML = data.records.length
      ? data.records.map((r) => `
          <tr>
            <td>${esc(r.student.full_name)}</td>
            <td>${esc(r.student.roll_no)}</td>
            <td>${esc(r.student.class_name)}</td>
            <td>${esc(r.check_in)}</td>
            <td>${statusBadge(r.status)}</td>
            <td>${esc(METHOD[r.method] || r.method)}</td>
          </tr>`).join("")
      : `<tr><td colspan="6" class="empty">No attendance marked yet today.</td></tr>`;
    unmarked = data.unmarked;
    renderUnmarked();
  }

  function renderUnmarked() {
    const q = el.search.value.trim().toLowerCase();
    const list = unmarked.filter((s) => !q || s.full_name.toLowerCase().includes(q) || s.roll_no.toLowerCase().includes(q));
    el.unmarked.innerHTML = list.length
      ? list.map((s) => `
          <li>
            <div>
              <strong>${esc(s.full_name)}</strong><br>
              <small class="muted">Roll ${esc(s.roll_no)} · ${esc(s.class_name)}${s.enrolled ? "" : " · no face profile"}</small>
            </div>
            <button class="btn small" data-manual="${esc(s.id)}" data-name="${esc(s.full_name)}">Mark present</button>
          </li>`).join("")
      : `<li class="muted">No students match.</li>`;
  }

  el.start.addEventListener("click", startCamera);
  el.stop.addEventListener("click", stopCamera);
  el.scan.addEventListener("click", () => scanOnce(true));
  el.auto.addEventListener("change", () => {
    if (!CameraKit.isRunning()) return;
    if (el.auto.checked) startAuto();
    else { stopAuto(); el.hint.textContent = "Auto-scan is off. Use Scan now."; }
  });
  el.search.addEventListener("input", renderUnmarked);

  el.result.addEventListener("click", async (e) => {
    const confirmBtn = e.target.closest("[data-confirm]");
    if (confirmBtn) {
      confirmBtn.disabled = true;
      const { data } = await apiFetch("/api/attendance/confirm", {
        json: { student_id: Number(confirmBtn.dataset.confirm) },
      });
      handleResult(data);
      return;
    }
    if (e.target.closest("[data-dismiss]")) renderIdle();
  });

  el.unmarked.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-manual]");
    if (!btn) return;
    if (!window.confirm(`Mark ${btn.dataset.name} present manually?`)) return;
    btn.disabled = true;
    const { data } = await apiFetch("/api/attendance/manual", {
      json: { student_id: Number(btn.dataset.manual) },
    });
    handleResult(data);
  });

  window.addEventListener("pagehide", stopCamera);
  renderIdle();
  refreshToday();
  setInterval(refreshToday, 15000);
})();
