/* Campus X - dashboard: discover, like / pass, matches and chat (all data comes from the API) */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = cx.esc;
  const baseTitle = document.title;
  const typingTimers = {};
  let live = null, connTimer = null;
  const state = { meId: null, profiles: [], index: 0, total: 0, connections: [], current: null, conv: null, typing: {}, busy: false };

  /* ---------- helpers ---------- */
  const fallbackEmoji = "🙂";
  function photoHtml(p, i) {
    const src = p.photos && (p.photos[i] || p.photos[0]);
    return src ? `<img src="${esc(cx.url(src))}" alt="${esc(p.name)} photo" style="width:100%;height:100%;object-fit:cover">` : fallbackEmoji;
  }
  function avatarHtml(c) {
    return c.photo ? `<img src="${esc(cx.url(c.photo))}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">` : esc((c.name || "?")[0].toUpperCase());
  }
  function authFail(e) {
    if (e && (e.status === 401 || e.status === 403)) { window.location.href = "login.html"; return true; }
    return false;
  }

  /* ---------- discover ---------- */
  function renderProfile() {
    const box = $("profileContainer");
    if (state.index >= state.profiles.length) {
      box.innerHTML = "";
      $("homeEmpty").classList.remove("hidden");
      $("profileCounter").textContent = `${state.total} / ${state.total}`;
      return;
    }
    $("homeEmpty").classList.add("hidden");
    const p = state.profiles[state.index];
    $("profileCounter").textContent = `${state.index + 1} / ${state.total}`;
    box.innerHTML = `
      <article class="profile-card" id="activeProfile">
        <div class="profile-name"><h2>${esc(p.name)}</h2><span class="age">${esc(p.age)}</span></div>
        <div class="photo one"><div class="photo-person">${photoHtml(p, 0)}</div><span class="photo-label">Photo 1</span></div>
        <section class="glass details">
          <div class="chip"><span class="chip-icon">⚧</span><span><small>Gender</small><strong>${esc(p.gender)}</strong></span></div>
          <div class="chip"><span class="chip-icon">↕</span><span><small>Height</small><strong>${esc(p.height)}</strong></span></div>
          <div class="chip"><span class="chip-icon">🎓</span><span><small>Branch / Course</small><strong>${esc(p.course)}</strong></span></div>
          <div class="chip"><span class="chip-icon">📅</span><span><small>Year</small><strong>${esc(p.year)}</strong></span></div>
          <div class="chip"><span class="chip-icon">🏠</span><span><small>Residence</small><strong>${esc(p.residence)}</strong></span></div>
          <div class="chip"><span class="chip-icon">📍</span><span><small>Hometown</small><strong>${esc(p.hometown)}</strong></span></div>
        </section>
        <div class="photo two"><div class="photo-person">${photoHtml(p, 1)}</div><span class="photo-label">Photo 2</span></div>
        <section class="glass"><div class="section-title">Interests</div>
          <div class="interest-chips">${p.interests.map((i) => `<span>${esc(i)}</span>`).join("")}</div></section>
        <section class="glass"><div class="section-title">About me</div><p class="bio">${esc(p.bio)}</p></section>
        <div class="photo three"><div class="photo-person">${photoHtml(p, 2)}</div><span class="photo-label">Photo 3</span></div>
        <section class="glass"><div class="section-title">Icebreakers</div>
          ${p.prompts.map((q) => `<div class="prompt"><div class="q">${esc(q[0])}</div><div class="a">${esc(q[1])}</div></div>`).join("")}</section>
        <section class="actions">
          <button class="pass" id="passBtn" aria-label="Pass" title="Pass">✕ &nbsp; PASS</button>
          <button class="like" id="likeBtn" aria-label="Like" title="Like">♡ &nbsp; LIKE</button>
        </section>
        <button class="report" id="reportBtn">⚑ Report profile</button>
      </article>`;
    $("passBtn").onclick = () => act(p, "pass");
    $("likeBtn").onclick = () => act(p, "like");
    $("reportBtn").onclick = () => reportProfile(p);
  }

  function nextProfile(action) {
    const card = $("activeProfile");
    const go = () => { state.index++; renderProfile(); window.scrollTo(0, 0); };
    if (card) { card.classList.add(action === "like" ? "swipe-right" : "swipe-left"); setTimeout(go, 250); } else go();
  }

  async function act(p, action) {
    if (state.busy) return;
    state.busy = true;
    try {
      if (action === "like") {
        const d = await cx.request("/api/like", { json: { user_id: p.id } });
        if (d.match) { alert(`It's a match with ${p.name}! 💜 You can now chat.`); await loadConnections(); }
        else alert(`You liked ${p.name}. If they like you back, you'll get a match.`);
      } else {
        await cx.request("/api/pass", { json: { user_id: p.id } });
      }
      nextProfile(action);
    } catch (e) { if (!authFail(e)) alert(e.message); }
    finally { state.busy = false; }
  }

  async function reportProfile(p) {
    if (!confirm(`Report ${p.name}'s profile? You will no longer see it.`)) return;
    try {
      const d = await cx.request("/api/report", { json: { user_id: p.id } });
      alert(d.message);
      nextProfile("pass");
    } catch (e) { if (!authFail(e)) alert(e.message); }
  }

  async function loadProfiles() {
    try {
      const d = await cx.request("/api/discover");
      if (d.needs_profile) { window.location.href = "profile.html"; return; }
      state.profiles = d.profiles; state.index = 0; state.total = d.profiles.length;
      renderProfile();
    } catch (e) { if (!authFail(e)) { $("profileContainer").innerHTML = `<p style="padding:24px;text-align:center">${esc(e.message)}</p>`; } }
  }

  /* ---------- pages ---------- */
  function showPage(id) {
    document.querySelectorAll(".page-section").forEach((s) => s.classList.remove("active"));
    $(id).classList.add("active");
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === id));
    $("bottomNav").style.display = id === "conversationPage" ? "none" : "grid";
    if (id !== "conversationPage") closeConversation();
    if (id === "chatPage") loadConnections();
    const hash = id === "chatPage" ? "#chat" : id === "profilePage" ? "#profile"
      : id === "conversationPage" && state.current ? "#chat/" + state.current : "#home";
    try { history.replaceState(null, "", hash); } catch (e) { /* ignore */ }
  }

  // After a reload, return to the screen the student was on (not always Home).
  function restoreView() {
    const h = location.hash;
    if (h.indexOf("#chat/") === 0) {
      const id = Number(h.slice(6));
      if (state.connections.some((c) => c.user_id === id)) { openConversation(id); return; }
      showPage("chatPage");
    } else if (h === "#chat") showPage("chatPage");
    else if (h === "#profile") showPage("profilePage");
  }

  /* ---------- matches / chat list ---------- */
  function scheduleConnections() { clearTimeout(connTimer); connTimer = setTimeout(loadConnections, 200); }

  async function loadConnections() {
    try {
      const d = await cx.request("/api/connections");
      state.connections = d.connections;
      renderChats();
    } catch (e) { await sessionLost(e); }
  }

  function totalUnread() { return state.connections.reduce((n, c) => n + (c.unread || 0), 0); }

  function renderChats() {
    const list = $("chatList"), n = state.connections.length, unread = totalUnread();
    $("matchCount").textContent = n;
    $("navBadge").textContent = unread > 99 ? "99+" : unread;
    $("navBadge").classList.toggle("hidden", unread === 0);
    document.title = (unread ? `(${unread}) ` : "") + baseTitle;
    if (!n) { list.innerHTML = ""; $("chatEmpty").classList.remove("hidden"); return; }
    $("chatEmpty").classList.add("hidden");
    list.innerHTML = state.connections.map((c) => {
      const lm = c.last_message;
      let preview;
      if (state.typing[c.user_id]) preview = `<span class="typing-text">typing…</span>`;
      else if (lm) preview = `<span class="${c.unread ? "unread-text" : ""}">${lm.mine ? cx.chat.ticks(lm.status) + " " : ""}${esc(lm.body)}</span>`;
      else preview = `<span>You matched! Start a conversation.</span>`;
      const when = lm ? cx.chat.shortTime(lm.created_at) : "";
      return `<div class="chat-item" data-id="${c.user_id}">
        <div class="avatar${c.online ? " online" : ""}">${avatarHtml(c)}</div>
        <div class="chat-main"><strong>${esc(c.name)}</strong>${preview}</div>
        <div class="chat-side"><small class="chat-time${c.unread ? " has-unread" : ""}">${esc(when)}</small>${c.unread ? `<b class="unread-badge">${c.unread > 99 ? "99+" : c.unread}</b>` : ""}</div>
      </div>`;
    }).join("");
    list.querySelectorAll(".chat-item").forEach((el) => { el.onclick = () => openConversation(Number(el.dataset.id)); });
  }

  /* ---------- conversation ---------- */
  function updateHeader(st) {
    const sub = document.querySelector("#conversationPage .conversation-user span");
    if (sub) { sub.textContent = st.text; sub.className = st.mode; }
    $("conversationAvatar").classList.toggle("online", st.mode === "online" || st.mode === "typing");
  }

  function closeConversation() {
    if (state.conv) { state.conv.destroy(); state.conv.stopTyping(); state.conv = null; }
    state.current = null;
  }

  async function openConversation(id) {
    const c = state.connections.find((x) => x.user_id === id);
    if (!c) { alert("You can chat only after a mutual match."); return; }
    closeConversation();
    document.querySelectorAll(".cx-toast").forEach((t) => t.remove());
    state.current = id;
    $("conversationAvatar").innerHTML = avatarHtml(c);
    $("conversationName").textContent = c.name;
    $("messages").innerHTML = "";
    state.conv = new cx.chat.Conversation({ peerId: id, box: $("messages"), onStatus: updateHeader });
    showPage("conversationPage");
    try { await state.conv.load(); } catch (e) { if (await sessionLost(e)) return; alert(e.message); }
    scheduleConnections();
    $("messageInput").focus();
  }

  $("messageForm").onsubmit = async (event) => {
    event.preventDefault();
    const input = $("messageInput"), text = input.value.trim();
    if (!text || !state.conv) return;
    input.value = "";
    try { await state.conv.send(text); scheduleConnections(); }
    catch (e) { if (await sessionLost(e)) return; alert(e.message); input.value = text; }
    input.focus();
  };
  $("messageInput").addEventListener("input", () => { if (state.conv && $("messageInput").value) state.conv.userTyping(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.conv) state.conv.markRead(); });
  window.addEventListener("focus", () => { if (state.conv) state.conv.markRead(); });

  /* ---------- live events (instant delivery) ---------- */
  function toast(text, onClick) {
    const t = document.createElement("div");
    t.className = "cx-toast"; t.textContent = text;
    t.onclick = () => { t.remove(); if (onClick) onClick(); };
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  function startLive() {
    live = cx.chat.stream({
      open() { loadConnections(); if (state.conv) state.conv.load().catch(() => {}); },
      lost() { sessionLost({ status: 401 }); },
      message(d) {
        if (state.conv) state.conv.handle("message", d);
        state.typing[d.peer] = false;
        if (!d.message.mine && !(state.current === d.peer && !document.hidden)) {
          const c = state.connections.find((x) => x.user_id === d.peer);
          toast(`💬 ${c ? c.name : "New message"}: ${d.message.body.slice(0, 60)}`, () => { if (c) openConversation(c.user_id); });
        }
        scheduleConnections();
      },
      delivered(d) { if (state.conv) state.conv.handle("delivered", d); scheduleConnections(); },
      read(d) { if (state.conv) state.conv.handle("read", d); scheduleConnections(); },
      read_self() { scheduleConnections(); },
      typing(d) {
        if (state.conv) state.conv.handle("typing", d);
        state.typing[d.peer] = d.typing;
        clearTimeout(typingTimers[d.peer]);
        if (d.typing) typingTimers[d.peer] = setTimeout(() => { state.typing[d.peer] = false; renderChats(); }, 4500);
        renderChats();
      },
      presence(d) {
        if (state.conv) state.conv.handle("presence", d);
        const c = state.connections.find((x) => x.user_id === d.peer);
        if (c) { c.online = d.online; if (d.last_seen) c.last_seen = d.last_seen; renderChats(); }
      },
      match(d) { toast(`💜 You matched with ${d.name}! Say hello.`, () => showPage("chatPage")); scheduleConnections(); }
    });
  }

  // Returns true when the session is gone (and we are leaving the page).
  async function sessionLost(e) {
    if (!(e && (e.status === 401 || e.status === 403))) return false;
    let me = null;
    try { me = await cx.request("/api/me"); } catch (x) { /* not logged in */ }
    if (me && me.user.id === state.meId) return false;      // still logged in: just a normal error
    if (live) live.close();
    closeConversation();
    if (me) alert("A different account has logged in from this browser, so this chat cannot continue here.\n\nTo test with two users, use a normal window and a private window (or two different browsers).");
    window.location.href = "login.html";
    return true;
  }

  /* ---------- my profile page ---------- */
  function fillMyProfile(p) {
    $("myName").textContent = `${p.name}, ${p.age}`;
    $("myCourse").textContent = `${p.course} • ${p.year}`;
    const avatar = document.querySelector("#profilePage .my-avatar");
    if (avatar) avatar.innerHTML = p.photos[0] ? `<img src="${esc(cx.url(p.photos[0]))}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">` : esc(p.name.slice(0, 2).toUpperCase());
    const vals = [p.gender, p.height, p.course, p.year, p.residence, p.hometown];
    document.querySelectorAll("#profilePage .chip strong").forEach((el, i) => { if (vals[i] !== undefined) el.textContent = vals[i]; });
    const chips = document.querySelector("#profilePage .interest-chips");
    if (chips) chips.innerHTML = p.interests.map((i) => `<span>${esc(i)}</span>`).join("");
    const bio = document.querySelector("#profilePage .bio");
    if (bio) bio.textContent = p.bio || "";
  }

  /* ---------- wiring ---------- */
  document.querySelectorAll(".nav-btn").forEach((b) => { b.onclick = () => showPage(b.dataset.page); });
  document.querySelectorAll("[data-go]").forEach((b) => { b.onclick = () => showPage(b.dataset.go); });
  $("backToChat").onclick = () => showPage("chatPage");
  $("editProfileBtn").onclick = () => { window.location.href = "profile.html?edit=true"; };
  $("menuBtn").onclick = () => showPage("profilePage");
  $("logoutBtn").onclick = async () => {
    if (live) live.close();
    try { await cx.request("/api/logout", { method: "POST", json: {} }); } catch (e) { /* ignore */ }
    window.location.href = "login.html";
  };

  async function init() {
    try {
      const me = await cx.request("/api/me");
      if (me.user.status !== "verified") { window.location.href = "login.html"; return; }
      if (!me.profile) { window.location.href = "profile.html"; return; }
      state.meId = me.user.id;
      fillMyProfile(me.profile);
    } catch (e) { window.location.href = "login.html"; return; }
    await loadProfiles();
    await loadConnections();
    restoreView();
    startLive();
    setInterval(loadConnections, 30000);   // safety net only; real updates arrive instantly
  }
  init();
})();
