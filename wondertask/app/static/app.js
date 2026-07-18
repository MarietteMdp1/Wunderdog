/* Dashboard — personal view for everyone; admins additionally see the whole team + the
   Needs-Allocation pool for tasks the AI could not confidently place. */

async function loadDash() {
  const el = document.getElementById("dash");
  const [me, data, members] = await Promise.all([
    window.ME ? Promise.resolve(window.ME) : api("/api/me").then(m => (window.ME = m)),
    api("/api/tasks"),
    team(),
  ]);

  const row = t => `
    <div class="task-row" data-id="${t.id}">
      <div class="t-title">${esc(t.title)}
        ${t.assignee && t.assignee !== me.email ? `<small>→ ${esc(t.assignee_name || t.assignee)}</small>` : ""}
      </div>
      ${metaChips(t)}
    </div>`;
  const listOf = ts => ts.length ? ts.map(row).join("") : '<div class="empty">Nothing here 🎉</div>';

  const openMine = data.mine.filter(t => t.status !== "done");
  const overdue = openMine.filter(t => (t.due_date || "").slice(0, 10) < todayISO());

  let html = `
    <div class="stat-row">
      <div class="stat"><b>${openMine.length}</b><span>My open tasks</span></div>
      <div class="stat"><b>${data.pending.length}</b><span>Awaiting my acceptance</span></div>
      <div class="stat"><b>${overdue.length}</b><span>Overdue</span></div>
      <div class="stat"><b>${data.collaborating.length}</b><span>Collaborating on</span></div>
      ${me.is_admin ? `<div class="stat"><b>${data.needs_allocation.length}</b><span>Needs allocation</span></div>` : ""}
      <div class="grow"></div>
      <button class="btn primary" id="new-task">+ New task</button>
    </div>`;

  if (data.pending.length) html += `
    <div class="panel pending-panel">
      <h2>⏳ Assigned to you — accept or decline</h2>
      <p class="section-note">The AI (or a teammate) allocated these to you. They only count as yours once you accept.</p>
      ${data.pending.map(row).join("")}
    </div>`;

  if (me.is_admin) html += `
    <div class="panel pool-panel">
      <h2>🗂 Needs allocation</h2>
      <p class="section-note">Action items the AI could not confidently match to a team role — allocate them by hand (open a task and pick an assignee).</p>
      ${listOf(data.needs_allocation)}
    </div>`;

  html += `
    <div class="dash-grid">
      <div class="panel"><h2>My tasks</h2>${listOf(data.mine.filter(t => t.status !== "done"))}</div>
      <div class="panel"><h2>Collaborating</h2>
        <p class="section-note">Tasks a teammate added you to — they also appear on your board.</p>
        ${listOf(data.collaborating)}</div>
      <div class="panel"><h2>Recently done</h2>${listOf(data.mine.filter(t => t.status === "done").slice(0, 8))}</div>
      ${me.is_admin ? `<div class="panel"><h2>Whole team (admin)</h2>
        ${listOf(data.all.filter(t => t.status !== "done").slice(0, 25))}</div>` : ""}
    </div>`;

  el.innerHTML = html;
  el.classList.remove("loading");
  el.querySelectorAll(".task-row").forEach(r =>
    r.addEventListener("click", () => openTask(r.dataset.id, loadDash)));
  document.getElementById("new-task").onclick = () => newTaskModal(members, me);
}

function newTaskModal(members, me) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `
  <div class="modal-back" id="mb">
    <div class="modal" style="max-width:520px">
      <div class="modal-head"><h3 class="grow">New task</h3><button class="btn sm" id="m-close">✕</button></div>
      <form class="stack" id="nt-form" style="margin-top:14px">
        <label>Title <input name="title" required maxlength="300"></label>
        <label>Description <textarea name="description"></textarea></label>
        <label>Due date (required) <input name="due_date" type="date" required value="${todayISO()}"></label>
        <label>Assign to
          <select name="assignee">
            <option value="${esc(me.email)}">Me (${esc(me.name || me.email)})</option>
            <option value="">— unassigned (allocation pool) —</option>
            ${members.filter(u => u.email !== me.email)
              .map(u => `<option value="${esc(u.email)}">${esc(u.name)} (${esc(u.role_label)})</option>`).join("")}
          </select>
        </label>
        <button class="btn primary">Create task</button>
      </form>
    </div>
  </div>`;
  root.querySelector("#m-close").onclick = () => (root.innerHTML = "");
  root.querySelector("#mb").addEventListener("click", e => { if (e.target.id === "mb") root.innerHTML = ""; });
  root.querySelector("#nt-form").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api("/api/tasks", { method: "POST", body: {
        title: f.get("title"), description: f.get("description"),
        due_date: f.get("due_date"), assignee: f.get("assignee") } });
      root.innerHTML = "";
      loadDash();
    } catch (err) { alert(err.message); }
  };
}

loadDash().catch(e => { document.getElementById("dash").innerHTML = `<p class="error">${esc(e.message)}</p>`; });
