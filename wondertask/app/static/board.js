/* Trello-style board: the user's own lists (create / rename / delete) with drag & drop cards.
   Cards are the tasks assigned to you (or that you collaborate on); moving a card only changes
   YOUR board layout — teammates arrange the same task on their own boards. */

let BOARD = null;
let BOARD_USER = null; // admins can view a teammate's board (read-only layout)

async function loadBoard() {
  const el = document.getElementById("board");
  const me = window.ME || (window.ME = await api("/api/me"));
  const members = await team();
  BOARD = await api("/api/board" + (BOARD_USER ? `?user=${encodeURIComponent(BOARD_USER)}` : ""));
  const own = BOARD.user === me.email;

  const cardsFor = lid => BOARD.tasks
    .filter(t => t.list_id === lid)
    .sort((a, b) => (a.position || 0) - (b.position || 0));

  const cardHTML = t => `
    <div class="card ${t.status === "done" ? "done" : ""}" draggable="${own}" data-id="${t.id}">
      <div class="c-title">${esc(t.title)}</div>
      <div class="c-meta">${metaChips(t)}</div>
    </div>`;

  el.innerHTML = `
    <div class="board-head">
      <h2>${own ? "My board" : esc(teamName(BOARD.user, members)) + "'s board"}</h2>
      ${me.is_admin ? `
        <select id="board-user">
          ${members.map(u => `<option value="${esc(u.email)}" ${u.email === BOARD.user ? "selected" : ""}>${esc(u.name)}</option>`).join("")}
        </select>` : ""}
      <span class="muted">${own ? "Drag cards between lists — arrange your work your way." : "Read-only view of a teammate's layout."}</span>
    </div>
    <div class="board" id="lists">
      ${BOARD.lists.map(l => `
        <div class="list" data-id="${l.id}">
          <div class="list-head">
            <input value="${esc(l.name)}" ${own ? "" : "disabled"} data-id="${l.id}">
            <span class="list-count">${cardsFor(l.id).length}</span>
            ${own && BOARD.lists.length > 1 ? `<button class="btn sm del-list" title="Delete list">✕</button>` : ""}
          </div>
          <div class="cards" data-id="${l.id}">
            ${cardsFor(l.id).map(cardHTML).join("")}
          </div>
        </div>`).join("")}
      ${own ? `
        <div class="add-list-box">
          <button class="add-list" id="add-list">＋ Add another list</button>
        </div>` : ""}
    </div>`;
  el.classList.remove("loading");

  el.querySelectorAll(".card").forEach(c =>
    c.addEventListener("click", () => openTask(c.dataset.id, loadBoard)));

  const sel = el.querySelector("#board-user");
  if (sel) sel.onchange = () => { BOARD_USER = sel.value; loadBoard(); };

  if (!own) return;

  /* rename / delete / add lists */
  el.querySelectorAll(".list-head input").forEach(inp => {
    inp.addEventListener("change", () =>
      api(`/api/lists/${inp.dataset.id}`, { method: "PATCH", body: { name: inp.value.trim() } }));
    inp.addEventListener("keydown", e => { if (e.key === "Enter") inp.blur(); });
  });
  el.querySelectorAll(".del-list").forEach(btn =>
    btn.addEventListener("click", async e => {
      const lid = e.target.closest(".list").dataset.id;
      if (confirm("Delete this list? Its cards move to your first list.")) {
        try { await api(`/api/lists/${lid}`, { method: "DELETE" }); loadBoard(); }
        catch (err) { alert(err.message); }
      }
    }));
  el.querySelector("#add-list").onclick = async () => {
    const name = prompt("List name:");
    if (name && name.trim()) {
      await api("/api/lists", { method: "POST", body: { name: name.trim() } });
      loadBoard();
    }
  };

  /* drag & drop */
  let dragged = null;
  el.querySelectorAll(".card").forEach(card => {
    card.addEventListener("dragstart", () => { dragged = card; card.classList.add("dragging"); });
    card.addEventListener("dragend", () => { card.classList.remove("dragging"); dragged = null; });
  });
  el.querySelectorAll(".cards").forEach(zone => {
    zone.addEventListener("dragover", e => {
      e.preventDefault();
      if (!dragged) return;
      const after = [...zone.querySelectorAll(".card:not(.dragging)")]
        .find(c => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
      after ? zone.insertBefore(dragged, after) : zone.appendChild(dragged);
    });
    zone.addEventListener("drop", async e => {
      e.preventDefault();
      if (!dragged) return;
      const lid = zone.dataset.id;
      const index = [...zone.querySelectorAll(".card")].indexOf(dragged);
      try {
        await api("/api/board/move", { method: "POST",
          body: { task_id: dragged.dataset.id, list_id: lid, index } });
        loadBoard();
      } catch (err) { alert(err.message); loadBoard(); }
    });
  });
}

loadBoard().catch(e => { document.getElementById("board").innerHTML = `<p class="error">${esc(e.message)}</p>`; });
