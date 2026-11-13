/* Campus X - WhatsApp-style chat engine (shared by dashboard.html and chat.html).
   Live delivery uses Server-Sent Events (GET /api/stream): messages, ticks, typing and
   online status are pushed by the server the moment they happen. */
(function () {
  const esc = cx.esc;
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = (iso) => Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 864e5);
  const time = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  function dayLabel(iso) {
    const diff = dayDiff(iso), d = new Date(iso);
    if (diff <= 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff < 7) return d.toLocaleDateString([], { weekday: "long" });
    return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
  }
  function shortTime(iso) {          // chat-list timestamp
    const diff = dayDiff(iso);
    if (diff <= 0) return time(iso);
    if (diff === 1) return "Yesterday";
    return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
  }
  function ticks(status) {
    if (status === "pending") return '<i class="tick pending" title="Sending">🕓</i>';
    if (status === "sent") return '<i class="tick" title="Sent">✓</i>';
    if (status === "delivered") return '<i class="tick" title="Delivered">✓✓</i>';
    if (status === "read") return '<i class="tick read" title="Read">✓✓</i>';
    return "";
  }
  function messagesHtml(list) {
    if (!list.length) return '<div class="empty-state"><p>Say hello 👋</p></div>';
    let out = "", lastDay = "";
    list.forEach((m) => {
      const key = new Date(m.created_at).toDateString();
      if (key !== lastDay) { out += `<div class="day-sep"><span>${esc(dayLabel(m.created_at))}</span></div>`; lastDay = key; }
      out += `<div class="message ${m.mine ? "me" : "them"}"><div class="text">${esc(m.body)}</div>` +
             `<div class="meta"><span class="time">${esc(time(m.created_at))}</span>${m.mine ? ticks(m.status) : ""}</div></div>`;
    });
    return out;
  }
  function presenceText(online, lastSeen) {
    if (online) return "online";
    if (!lastSeen) return "Matched on Campus X";
    const diff = dayDiff(lastSeen);
    const when = diff <= 0 ? "today at " : diff === 1 ? "yesterday at " :
      new Date(lastSeen).toLocaleDateString([], { day: "numeric", month: "short" }) + " at ";
    return "last seen " + when + time(lastSeen);
  }

  /* ----- live connection (auto-reconnects) ----- */
  function stream(h) {
    let es = null, closed = false, timer = null;
    const EVENTS = ["message", "delivered", "read", "read_self", "typing", "presence", "match"];
    function connect() {
      es = new EventSource(cx.API + "/api/stream", { withCredentials: true });
      es.addEventListener("ready", () => h.open && h.open());
      EVENTS.forEach((ev) => es.addEventListener(ev, (e) => {
        try { h[ev] && h[ev](JSON.parse(e.data)); } catch (x) { console.error(x); }
      }));
      es.onerror = () => {
        if (closed) return;
        if (es.readyState === 2) {            // browser gave up (e.g. logged out): check, then retry
          h.lost && h.lost();
          timer = setTimeout(connect, 3000);
        }
      };
    }
    connect();
    return { close() { closed = true; clearTimeout(timer); if (es) es.close(); } };
  }

  /* ----- one open conversation ----- */
  const RANK = { pending: 0, sent: 1, delivered: 2, read: 3 };
  function Conversation(o) {
    this.peer = o.peerId; this.box = o.box; this.onStatus = o.onStatus || function () {};
    this.messages = []; this.info = { online: false, last_seen: null };
    this.peerTyping = false; this.peerTimer = null; this.idleTimer = null; this.lastTypingSent = 0; this.seq = 0;
  }
  const P = Conversation.prototype;
  P.has = function (id) { return this.messages.some((m) => m.id === id); };
  P.nearBottom = function () {
    const b = this.box;
    if (b.scrollHeight > b.clientHeight + 4) return b.scrollHeight - b.scrollTop - b.clientHeight < 140;
    return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
  };
  P.scroll = function () {
    this.box.scrollTop = this.box.scrollHeight;
    window.scrollTo({ top: document.documentElement.scrollHeight });
  };
  P.render = function (force) {
    const stick = force || this.nearBottom();
    this.box.innerHTML = messagesHtml(this.messages);
    if (stick) this.scroll();
  };
  P.status = function () {
    if (this.peerTyping) return { text: "typing…", mode: "typing" };
    return { text: presenceText(this.info.online, this.info.last_seen), mode: this.info.online ? "online" : "offline" };
  };
  P.pushStatus = function () { this.onStatus(this.status()); };
  P.load = async function () {
    const d = await cx.request("/api/messages/" + this.peer);
    this.messages = d.messages; this.info = d.peer || this.info;
    this.render(true); this.pushStatus(); this.markRead();
  };
  P.markRead = async function () {
    if (document.hidden) return;
    try { await cx.request("/api/messages/" + this.peer + "/read", { json: {} }); } catch (e) { /* ignore */ }
  };
  P.setPeerTyping = function (flag) {
    clearTimeout(this.peerTimer); this.peerTyping = !!flag;
    if (flag) this.peerTimer = setTimeout(() => { this.peerTyping = false; this.pushStatus(); }, 4500);
    this.pushStatus();
  };
  P.upgrade = function (upTo, status) {
    let changed = false;
    this.messages.forEach((m) => {
      if (m.mine && typeof m.id === "number" && m.id <= upTo && RANK[m.status] < RANK[status]) { m.status = status; changed = true; }
    });
    if (changed) this.render();
  };
  P.handle = function (ev, d) {
    if (d.peer !== this.peer) return;
    if (ev === "message") {
      if (this.has(d.message.id)) return;
      this.messages.push(d.message); this.render();
      if (!d.message.mine) { this.setPeerTyping(false); this.markRead(); }
    } else if (ev === "delivered") this.upgrade(d.up_to, "delivered");
    else if (ev === "read") this.upgrade(d.up_to, "read");
    else if (ev === "typing") this.setPeerTyping(d.typing);
    else if (ev === "presence") { this.info = { online: d.online, last_seen: d.last_seen || this.info.last_seen }; this.pushStatus(); }
  };
  P.send = async function (text) {
    text = text.trim(); if (!text) return;
    this.stopTyping();
    const tmp = { id: "t" + (++this.seq), mine: true, body: text, created_at: new Date().toISOString(), status: "pending" };
    this.messages.push(tmp); this.render(true);
    try {
      const d = await cx.request("/api/messages", { json: { receiver_id: this.peer, body: text } });
      const i = this.messages.indexOf(tmp);
      if (this.has(d.message.id)) { if (i > -1) this.messages.splice(i, 1); }   // live event arrived first
      else if (i > -1) this.messages[i] = d.message;
      this.render();
    } catch (e) {
      const i = this.messages.indexOf(tmp); if (i > -1) this.messages.splice(i, 1);
      this.render(); throw e;
    }
  };
  P.userTyping = function () {
    const t = Date.now();
    if (t - this.lastTypingSent > 2000) {
      this.lastTypingSent = t;
      cx.request("/api/typing", { json: { receiver_id: this.peer, typing: true } }).catch(() => {});
    }
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => this.stopTyping(), 2500);
  };
  P.stopTyping = function () {
    clearTimeout(this.idleTimer);
    if (this.lastTypingSent) {
      this.lastTypingSent = 0;
      cx.request("/api/typing", { json: { receiver_id: this.peer, typing: false } }).catch(() => {});
    }
  };
  P.destroy = function () { clearTimeout(this.peerTimer); clearTimeout(this.idleTimer); };

  cx.chat = { time, dayLabel, shortTime, ticks, messagesHtml, presenceText, stream, Conversation };
})();
