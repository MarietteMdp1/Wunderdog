/* Admin — Users, Roles (skills breakdown for AI matching), AI / Integrations. */

let TAB = "users";

async function loadAdmin() {
  const el = document.getElementById("admin");
  const data = await api("/api/admin/users");
  el.classList.remove("loading");
  el.innerHTML = `
    <div class="tabs">
      <button data-t="users" class="${TAB === "users" ? "active" : ""}">Team members</button>
      <button data-t="roles" class="${TAB === "roles" ? "active" : ""}">Roles &amp; skills</button>
      <button data-t="ai" class="${TAB === "ai" ? "active" : ""}">AI &amp; integrations</button>
    </div>
    <div id="tab-body"></div>`;
  el.querySelectorAll(".tabs button").forEach(b =>
    b.onclick = () => { TAB = b.dataset.t; loadAdmin(); });
  const body = el.querySelector("#tab-body");
  if (TAB === "users") renderUsers(body, data);
  else if (TAB === "roles") renderRoles(body, data);
  else renderAI(body);
}

function renderUsers(body, data) {
  const roleOpts = sel => data.roles.map(r =>
    `<option value="${esc(r.role)}" ${r.role === sel ? "selected" : ""}>${esc(r.label)}</option>`).join("");
  body.innerHTML = `
    <div class="panel">
      <h2>Add a team member</h2>
      <form class="flex" id="add-user">
        <input name="name" placeholder="Name" required>
        <input name="email" type="email" placeholder="email@wonderdoc.com" required>
        <select name="role">${roleOpts("viewer")}</select>
        <button class="btn primary">Create</button>
      </form>
      <p class="muted" id="add-user-out" style="margin:8px 0 0"></p>
    </div>
    <div class="panel">
      <h2>Team</h2>
      <table class="grid"><thead><tr>
        <th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th></th>
      </tr></thead><tbody>
        ${data.users.map(u => `
          <tr data-email="${esc(u.email)}">
            <td>${esc(u.name || "")}</td>
            <td>${esc(u.email)}</td>
            <td><select class="u-role">${roleOpts(u.role)}</select></td>
            <td>${u.active ? '<span class="chip" style="color:var(--ok)">active</span>' : '<span class="chip">disabled</span>'}</td>
            <td class="muted">${esc((u.last_login || "—").slice(0, 16).replace("T", " "))}</td>
            <td class="flex">
              <button class="btn sm u-reset">Reset pw</button>
              <button class="btn sm ${u.active ? "danger" : "ok"} u-toggle">${u.active ? "Disable" : "Enable"}</button>
            </td>
          </tr>`).join("")}
      </tbody></table>
    </div>`;

  body.querySelector("#add-user").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const out = await api("/api/admin/users", { method: "POST", body: {
        name: f.get("name"), email: f.get("email"), role: f.get("role") } });
      body.querySelector("#add-user-out").textContent =
        `Created ${out.email} — temporary password: ${out.temp_password} (they must change it on first login)`;
      setTimeout(loadAdmin, 4000);
    } catch (err) { alert(err.message); }
  };
  body.querySelectorAll("tbody tr").forEach(tr => {
    const email = tr.dataset.email;
    tr.querySelector(".u-role").onchange = e =>
      api(`/api/admin/users/${email}`, { method: "PATCH", body: { role: e.target.value } })
        .catch(err => alert(err.message));
    tr.querySelector(".u-reset").onclick = async () => {
      const out = await api(`/api/admin/users/${email}`, { method: "PATCH", body: { reset_password: true } });
      alert(`New temporary password for ${email}: ${out.temp_password}`);
    };
    tr.querySelector(".u-toggle").onclick = async () => {
      const disabling = tr.querySelector(".u-toggle").textContent === "Disable";
      try {
        await api(`/api/admin/users/${email}`, { method: "PATCH", body: { active: !disabling ? true : false } });
        loadAdmin();
      } catch (err) { alert(err.message); }
    };
  });
}

function renderRoles(body, data) {
  body.innerHTML = `
    <div class="panel">
      <h2>Roles &amp; skills breakdown</h2>
      <p class="section-note">The AI allocator matches meeting action-items against each role's skills.
      Keep the lists honest: a role only receives tasks whose required skills overlap its list —
      anything unclear goes to your Needs-Allocation pool instead.</p>
      <table class="grid"><thead><tr><th>Role</th><th>Skills (comma-separated)</th><th></th></tr></thead>
      <tbody>
        ${data.roles.map(r => `
          <tr data-role="${esc(r.role)}">
            <td style="min-width:170px"><b>${esc(r.label)}</b>${r.is_admin ? ' <span class="chip">admin</span>' : ""}
              <br><span class="muted" style="font-size:12.5px">${esc(r.description || "")}</span></td>
            <td><textarea class="r-skills" style="width:100%;min-height:56px">${esc((r.skills || []).join(", "))}</textarea></td>
            <td class="flex">
              <button class="btn sm r-save">Save</button>
              ${r.builtin ? "" : '<button class="btn sm danger r-del">Delete</button>'}
            </td>
          </tr>`).join("")}
      </tbody></table>
    </div>
    <div class="panel">
      <h2>Add a role</h2>
      <form class="flex" id="add-role">
        <input name="label" placeholder="Role name (e.g. PPC Specialist)" required>
        <input name="skills" class="grow" placeholder="skills, comma, separated">
        <button class="btn primary">Create</button>
      </form>
    </div>`;

  body.querySelectorAll("tbody tr").forEach(tr => {
    const slug = tr.dataset.role;
    tr.querySelector(".r-save").onclick = async () => {
      const skills = tr.querySelector(".r-skills").value
        .split(",").map(s => s.trim()).filter(Boolean);
      await api(`/api/admin/roles/${slug}`, { method: "PATCH", body: { skills } });
      tr.querySelector(".r-save").textContent = "Saved ✓";
      setTimeout(() => (tr.querySelector(".r-save").textContent = "Save"), 1500);
    };
    const del = tr.querySelector(".r-del");
    if (del) del.onclick = async () => {
      if (confirm(`Delete role ${slug}?`)) {
        try { await api(`/api/admin/roles/${slug}`, { method: "DELETE" }); loadAdmin(); }
        catch (err) { alert(err.message); }
      }
    };
  });
  body.querySelector("#add-role").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const label = f.get("label");
    try {
      await api("/api/admin/roles", { method: "POST", body: {
        role: label.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
        label,
        skills: f.get("skills").split(",").map(s => s.trim()).filter(Boolean) } });
      loadAdmin();
    } catch (err) { alert(err.message); }
  };
}

async function renderAI(body) {
  body.innerHTML = `
    <div class="panel">
      <h2>Analyze meeting notes now</h2>
      <p class="section-note">Paste a transcript, Teams thread or meeting notes. Claude extracts real action
      items, matches them against existing tasks first (no duplicates), and auto-allocates by role skills —
      assignees must accept; anything uncertain lands in your Needs-Allocation pool.</p>
      <form class="stack" id="an-form">
        <div class="flex">
          <input name="meeting_title" placeholder="Meeting title" class="grow">
          <input name="meeting_date" type="date" value="${todayISO()}">
        </div>
        <textarea name="text" style="min-height:160px" placeholder="Paste the transcript or notes here…"></textarea>
        <button class="btn primary" id="an-btn">Analyze &amp; allocate</button>
      </form>
      <pre class="result" id="an-out" style="display:none"></pre>
    </div>
    <div class="panel">
      <h2>Connected sources</h2>
      <p class="section-note">Scheduled syncs run as GitHub Actions (see the repo's
      <code>.github/workflows</code>). You can also trigger a sync now:</p>
      <div class="flex">
        <button class="btn" id="sync-ff">🔮 Sync Fireflies now</button>
        <button class="btn" id="sync-teams">💬 Sync Teams now</button>
      </div>
      <pre class="result" id="sync-out" style="display:none"></pre>
    </div>
    <div class="panel">
      <h2>Processed meetings</h2>
      <div id="meet-log" class="muted">Loading…</div>
    </div>`;

  const show = (id, obj) => {
    const p = body.querySelector(id);
    p.style.display = "block";
    p.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  };
  body.querySelector("#an-form").onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const btn = body.querySelector("#an-btn");
    btn.disabled = true; btn.textContent = "Analyzing… (this can take a minute)";
    try {
      const out = await api("/api/admin/analyze", { method: "POST", body: {
        text: f.get("text"), meeting_title: f.get("meeting_title"),
        meeting_date: f.get("meeting_date") } });
      show("#an-out", out);
    } catch (err) { show("#an-out", "Error: " + err.message); }
    btn.disabled = false; btn.textContent = "Analyze & allocate";
  };
  body.querySelector("#sync-ff").onclick = async () => {
    show("#sync-out", "Syncing Fireflies…");
    try { show("#sync-out", await api("/api/admin/sync/fireflies", { method: "POST" })); }
    catch (err) { show("#sync-out", "Error: " + err.message); }
  };
  body.querySelector("#sync-teams").onclick = async () => {
    show("#sync-out", "Syncing Teams…");
    try { show("#sync-out", await api("/api/admin/sync/teams", { method: "POST" })); }
    catch (err) { show("#sync-out", "Error: " + err.message); }
  };

  const meetings = await api("/api/admin/meetings");
  body.querySelector("#meet-log").innerHTML = meetings.length
    ? `<table class="grid"><thead><tr><th>Source</th><th>Meeting</th><th>Date</th><th>Tasks created</th><th>Matched existing</th></tr></thead>
       <tbody>${meetings.map(m => `<tr>
         <td>${esc(m.source)}</td><td>${esc(m.title || m.id)}</td>
         <td>${esc(m.meeting_date || "")}</td>
         <td>${m.tasks_created}</td><td>${m.tasks_matched}</td></tr>`).join("")}</tbody></table>`
    : "No meetings processed yet.";
}

loadAdmin().catch(e => { document.getElementById("admin").innerHTML = `<p class="error">${esc(e.message)}</p>`; });
