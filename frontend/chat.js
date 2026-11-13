/* Campus X - stand-alone chat page: chat.html?id=<user id>  (same live engine as the dashboard) */
(function () {
  const $ = (id) => document.getElementById(id);
  const otherId = Number(new URLSearchParams(location.search).get("id"));
  let meId = null, conv = null, live = null;

  function blocked(text) {
    document.body.innerHTML = "<main style='padding:40px;text-align:center;color:white;font-family:system-ui'><h2>No chat available</h2><p>" + cx.esc(text) + "</p></main>";
  }
  async function sessionLost(e) {
    if (!(e && (e.status === 401 || e.status === 403))) return false;
    let me = null;
    try { me = await cx.request("/api/me"); } catch (x) { /* not logged in */ }
    if (me && me.user.id === meId) return false;
    if (live) live.close();
    if (me) alert("A different account has logged in from this browser, so this chat cannot continue here.\n\nTo test with two users, use a normal window and a private window (or two different browsers).");
    location.href = "login.html";
    return true;
  }
  function header(st) { const s = $("status"); s.textContent = st.text; s.className = st.mode; }

  async function start() {
    if (!otherId) return blocked("Chat opens only after a mutual like.");
    try {
      meId = (await cx.request("/api/me")).user.id;
      const d = await cx.request("/api/connections");
      const c = d.connections.find((x) => x.user_id === otherId);
      if (!c) return blocked("Chat opens only after a mutual like.");
      $("name").textContent = c.name;
    } catch (e) {
      if (e.status === 401 || e.status === 403) { location.href = "login.html"; return; }
      return blocked(e.message);
    }
    conv = new cx.chat.Conversation({ peerId: otherId, box: $("messages"), onStatus: header });
    await conv.load().catch(() => {});
    live = cx.chat.stream({
      open() { conv.load().catch(() => {}); },
      lost() { sessionLost({ status: 401 }); },
      message(d) { conv.handle("message", d); },
      delivered(d) { conv.handle("delivered", d); },
      read(d) { conv.handle("read", d); },
      typing(d) { conv.handle("typing", d); },
      presence(d) { conv.handle("presence", d); }
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) conv.markRead(); });
    $("input").addEventListener("input", () => { if ($("input").value) conv.userTyping(); });
    $("form").onsubmit = async (e) => {
      e.preventDefault();
      const input = $("input"), text = input.value.trim();
      if (!text) return;
      input.value = "";
      try { await conv.send(text); }
      catch (err) { if (await sessionLost(err)) return; alert(err.message); input.value = text; }
      input.focus();
    };
  }
  start();
})();
