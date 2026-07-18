/* Shared helpers: API wrapper, formatting, and the task detail modal. */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { location.href = "/login"; throw new Error("signed out"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function todayISO() { return new Date().toISOString().slice(0, 10); }

function dueChip(t) {
  if (!t.due_date) return "";
  const d = t.due_date.slice(0, 10);
  const today = todayISO();
  const soon = new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10);
  let cls = "", label = "Due " + d;
  if (t.status !== "done" && d < today) { cls = "overdue"; label = "Overdue " + d; }
  else if (t.status !== "done" && d <= soon) cls = "due-soon";
  return `<span class="chip ${cls}">${esc(label)}</span>`;
}

function srcChip(t) {
  const map = { fireflies: "Fireflies", teams: "Teams", manual: "Manual", ai: "AI" };
  return `<span class="chip src-${esc(t.source)}" title="${esc(t.meeting_title || "")}">${map[t.source] || t.source}</span>`;
}

function metaChips(t) {
  const bits = [dueChip(t), srcChip(t)];
  if (t.acceptance === "pending") bits.push('<span class="chip pending">Awaiting acceptance</span>');
  if (t.subtasks && t.subtasks.total)
    bits.push(`<span class="chip">☑ ${t.subtasks.done}/${t.subtasks.total}</span>`);
  if (t.collaborators && t.collaborators.length)
    bits.push(`<span class="chip">+${t.collaborators.length} collab</span>`);
  return bits.join(" ");
}

let TEAM = null;
async function team() {
  if (!TEAM) TEAM = await api("/api/team");
  return TEAM;
}
function teamName(email, members) {
  const m = (members || []).find(u => u.email === email);
  return m ? m.name : (email || "");
}

/* ---------------- task modal ---------------- */

async function openTask(tid, onChange) {
  const root = document.getElementById("modal-root");
  const me = window.ME || (window.ME = await api("/api/me"));
  const members = await team();
  let t;
  try { t = await api(`/api/tasks/${tid}`); }
  catch (e) { alert(e.message); return; }

  const close = () => { root.innerHTML = ""; onChange && onChange(); };
  const edit = t.can_edit;
  const subRows = t.subtask_rows || [];
  const doneCount = subRows.filter(s => s.done).length;
  const pct = subRows.length ? Math.round(100 * doneCount / subRows.length) : 0;

  const assigneeOpts = ['<option value="">— unassigned —</option>']
    .concat(members.map(u =>
      `<option value="${esc(u.email)}" ${u.email === t.assignee ? "selected" : ""}>${esc(u.name)} (${esc(u.role_label)})</option>`))
    .join("");
  const canReassign = me.is_admin || (!t.assignee);

  root.innerHTML = `
  <div class="modal-back" id="mb">
    <div class="modal">
      <div class="modal-head">
        <div class="grow">
          <h3 id="m-title" ${edit ? "contenteditable" : ""}>${esc(t.title)}</h3>
          <div style="margin-top:6px">${metaChips(t)}
            <span class="chip">${esc(t.status === "in_progress" ? "In progress" : t.status === "done" ? "Done" : "To do")}</span>
          </div>
        </div>
        <button class="btn sm" id="m-close">✕</button>
      </div>
      ${t.ai_rationale ? `<div class="ai-audit" style="margin-top:10px"><b>AI allocation:</b>
        ${esc(t.ai_rationale)} <span class="muted">(confidence ${Math.round((t.ai_confidence || 0) * 100)}%${t.meeting_title ? ", from “" + esc(t.meeting_title) + "”" : ""})</span></div>` : ""}
      ${t.assignee === me.email && t.acceptance === "pending" ? `
        <div class="notice" style="margin-top:10px" id="m-accept">
          This task was assigned to you and needs your response:
          <button class="btn ok sm" id="m-yes">Accept</button>
          <button class="btn danger sm" id="m-no">Decline</button>
        </div>` : ""}
      <div class="modal-grid">
        <div>
          <div class="side-label">Description</div>
          <div class="desc-edit" id="m-desc" ${edit ? "contenteditable" : ""}>${esc(t.description || "")}</div>
          <div class="side-label" style="margin-top:16px">Subtasks ${subRows.length ? `(${doneCount}/${subRows.length})` : ""}</div>
          ${subRows.length ? `<div class="progress" style="margin:6px 0"><i style="width:${pct}%"></i></div>` : ""}
          <div id="m-subs">
            ${subRows.map(s => `
              <div class="subtask ${s.done ? "done" : ""}" data-id="${s.id}">
                <input type="checkbox" ${s.done ? "checked" : ""} ${edit ? "" : "disabled"}>
                <span>${esc(s.title)}</span>
                ${edit ? '<button class="btn sm x">✕</button>' : ""}
              </div>`).join("")}
          </div>
          ${edit ? `<form class="mini-form" id="m-addsub" style="margin-top:6px">
            <input placeholder="Add a subtask…" maxlength="300"><button class="btn sm">Add</button>
          </form>` : ""}
          <div class="side-label" style="margin-top:16px">Activity</div>
          <div id="m-comments">
            ${(t.comments || []).map(c => `
              <div class="comment ${c.email === "ai" ? "ai" : ""}">
                <b>${c.email === "ai" ? "🤖 WonderTask AI" : esc(teamName(c.email, members))}</b>
                <span class="muted"> ${esc((c.created_at || "").slice(0, 16).replace("T", " "))}</span><br>
                ${esc(c.body)}
              </div>`).join("") || '<div class="empty">No activity yet.</div>'}
          </div>
          <form class="mini-form" id="m-addcomment" style="margin-top:8px">
            <input placeholder="Write a comment…" maxlength="4000"><button class="btn sm">Post</button>
          </form>
        </div>
        <div class="modal-side">
          <div>
            <div class="side-label">Assignee</div>
            <select id="m-assignee" ${canReassign ? "" : "disabled"}>${assigneeOpts}</select>
            ${!t.assignee && !me.is_admin ? `<button class="btn sm" id="m-claim" style="margin-top:6px">Claim this task</button>` : ""}
          </div>
          <div>
            <div class="side-label">Due date</div>
            <input type="date" id="m-due" value="${esc((t.due_date || "").slice(0, 10))}" ${edit ? "" : "disabled"}>
          </div>
          <div>
            <div class="side-label">Status</div>
            <select id="m-status" ${edit ? "" : "disabled"}>
              <option value="todo" ${t.status === "todo" ? "selected" : ""}>To do</option>
              <option value="in_progress" ${t.status === "in_progress" ? "selected" : ""}>In progress</option>
              <option value="done" ${t.status === "done" ? "selected" : ""}>Done</option>
            </select>
          </div>
          <div>
            <div class="side-label">Collaborators</div>
            <div id="m-collabs">
              ${(t.collaborators || []).map(c => `
                <div class="collab-row" data-email="${esc(c)}">👤 ${esc(teamName(c, members))}
                  ${edit ? '<button class="btn sm x">✕</button>' : ""}</div>`).join("") || '<div class="empty">None yet</div>'}
            </div>
            ${edit ? `<div class="mini-form" style="margin-top:6px">
              <select id="m-addcollab-sel">
                <option value="">Add teammate…</option>
                ${members.filter(u => u.email !== t.assignee && !(t.collaborators || []).includes(u.email))
                  .map(u => `<option value="${esc(u.email)}">${esc(u.name)}</option>`).join("")}
              </select></div>` : ""}
          </div>
          ${(me.is_admin || t.created_by === me.email) ? `<button class="btn danger sm" id="m-del">Delete task</button>` : ""}
        </div>
      </div>
    </div>
  </div>`;

  const $ = sel => root.querySelector(sel);
  $("#m-close").onclick = close;
  $("#mb").addEventListener("click", e => { if (e.target.id === "mb") close(); });

  const patch = async body => {
    try { await api(`/api/tasks/${tid}`, { method: "PATCH", body }); }
    catch (e) { alert(e.message); }
  };
  if (edit) {
    $("#m-title").addEventListener("blur", () => patch({ title: $("#m-title").innerText.trim() }));
    $("#m-desc").addEventListener("blur", () => patch({ description: $("#m-desc").innerText.trim() }));
    $("#m-due").addEventListener("change", () => patch({ due_date: $("#m-due").value }));
    $("#m-status").addEventListener("change", () => patch({ status: $("#m-status").value }));
  }
  if (canReassign) $("#m-assignee").addEventListener("change", async () => {
    try { await api(`/api/tasks/${tid}`, { method: "PATCH", body: { assignee: $("#m-assignee").value } }); openTask(tid, onChange); }
    catch (e) { alert(e.message); }
  });
  const claim = $("#m-claim");
  if (claim) claim.onclick = async () => {
    try { await api(`/api/tasks/${tid}`, { method: "PATCH", body: { assignee: me.email } }); openTask(tid, onChange); }
    catch (e) { alert(e.message); }
  };
  const yes = $("#m-yes"), no = $("#m-no");
  if (yes) yes.onclick = async () => { await api(`/api/tasks/${tid}/accept`, { method: "POST" }); openTask(tid, onChange); };
  if (no) no.onclick = async () => {
    const reason = prompt("Why are you declining? (optional)") || "";
    await api(`/api/tasks/${tid}/decline`, { method: "POST", body: { reason } }); close();
  };

  root.querySelectorAll(".subtask").forEach(el => {
    const sid = el.dataset.id;
    el.querySelector("input").onchange = e =>
      api(`/api/subtasks/${sid}`, { method: "PATCH", body: { done: e.target.checked } })
        .then(() => openTask(tid, onChange));
    const x = el.querySelector(".x");
    if (x) x.onclick = () => api(`/api/subtasks/${sid}`, { method: "DELETE" })
      .then(() => openTask(tid, onChange));
  });
  const addSub = $("#m-addsub");
  if (addSub) addSub.onsubmit = async e => {
    e.preventDefault();
    const v = addSub.querySelector("input").value.trim();
    if (v) { await api(`/api/tasks/${tid}/subtasks`, { method: "POST", body: { title: v } }); openTask(tid, onChange); }
  };
  $("#m-addcomment").onsubmit = async e => {
    e.preventDefault();
    const v = $("#m-addcomment").querySelector("input").value.trim();
    if (v) { await api(`/api/tasks/${tid}/comments`, { method: "POST", body: { body: v } }); openTask(tid, onChange); }
  };
  root.querySelectorAll(".collab-row .x").forEach(x => {
    x.onclick = () => api(`/api/tasks/${tid}/collaborators/${x.closest(".collab-row").dataset.email}`,
      { method: "DELETE" }).then(() => openTask(tid, onChange));
  });
  const addCollab = $("#m-addcollab-sel");
  if (addCollab) addCollab.onchange = async () => {
    if (addCollab.value) {
      try { await api(`/api/tasks/${tid}/collaborators`, { method: "POST", body: { email: addCollab.value } }); openTask(tid, onChange); }
      catch (e) { alert(e.message); }
    }
  };
  const del = $("#m-del");
  if (del) del.onclick = async () => {
    if (confirm("Delete this task for everyone?")) {
      await api(`/api/tasks/${tid}`, { method: "DELETE" }); close();
    }
  };
}
