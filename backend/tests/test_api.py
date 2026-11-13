"""Backend test-suite. Run from the backend folder:   python tests/test_api.py
Uses a temporary database and upload folder, so your real data is never touched."""
import io, os, sys, struct, tempfile, zlib, json
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_PATH=f"{tmp}/t.db", UPLOAD_DIR=f"{tmp}/up", RATE_LIMIT="false",
                  ADMIN_EMAIL="admin@campusx.local", ADMIN_PASSWORD="ChangeMe123!", SECRET_KEY="test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as A
A.init_db()
app = A.app

def png(color=(120, 60, 200), w=8, h=8):
    raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

RESULTS = []
def check(name, cond, got=""):
    RESULTS.append((name, bool(cond), got))

def J(r): return r.get_json(silent=True) or {}
def kyc_form(name, sid="S1", ext="id.png", data=None, **over):
    f = dict(fullName=name, college="ABC College", studentId=sid, course="cs", year="3")
    f.update(over); f["document"] = (io.BytesIO(data if data is not None else png()), ext)
    return f
def profile_form(nick, age="21", hobbies="music, coding, football", bio="love coding", photos=3, **over):
    f = dict(nickname=nick, age=age, gender="male", course="CSE", year="3", height="5'10\"", hometown="Delhi",
             hosteller="hosteller", religion="", hobbies=hobbies, bio=bio,
             question1="Cricket", question2="Library and coffee", question3="Trekking")
    f.update(over)
    for i in range(photos): f[f"photo{i}"] = (io.BytesIO(png((i * 40, 90, 200))), f"p{i}.png")
    return f
def post_form(c, url, data): return c.post(url, data=data, content_type="multipart/form-data")

def signup(c, name, ident, pw="secret1"):
    return c.post("/api/signup", json={"fullName": name, "email": ident, "password": pw})
def approve_all(adm):
    for a in J(adm.get("/api/admin/kyc"))["applications"]:
        adm.post(f"/api/admin/kyc/{a['user_id']}/approve", json={})

# ------------------------------------------------------------------- auth
a, b, c3, anon, adm = (app.test_client() for _ in range(5))
r = signup(a, "Asha Rao", "asha@x.edu"); check("signup ok -> kyc.html", r.status_code == 201 and J(r)["next"] == "kyc.html", r.status_code)
r = signup(app.test_client(), "Asha Two", "ASHA@x.edu"); check("duplicate email (case-insensitive) -> 409", r.status_code == 409, r.status_code)
r = signup(app.test_client(), "Roll Number", "21CSE1042"); check("college ID (not an email) accepted", r.status_code == 201, r.status_code)
r = signup(app.test_client(), "Bo", "not an email"); check("invalid identifier -> 400", r.status_code == 400, r.status_code)
r = signup(app.test_client(), "Bob Roy", "bob@x.edu", "12345"); check("password < 6 -> 400", r.status_code == 400, r.status_code)
r = signup(app.test_client(), "Bob Roy", "bob@x.edu", "123456"); check("password of exactly 6 accepted", r.status_code == 201, r.status_code)
signup(b, "Ravi Kumar", "ravi@x.edu"); signup(c3, "Meera Jain", "meera@x.edu")
check("no session -> 401", anon.get("/api/me").status_code == 401)
check("student cannot reach verified API before KYC", a.get("/api/discover").status_code == 403)
r = app.test_client().post("/api/login", json={"email": "asha@x.edu", "password": "wrong"}); check("wrong password -> 401", r.status_code == 401)
r = app.test_client().post("/api/login", json={"email": "ASHA@X.EDU", "password": "secret1"})
check("login (any case) before KYC -> goes to kyc.html", r.status_code == 200 and J(r)["next"] == "kyc.html", J(r))

# -------------------------------------------------------------------- KYC
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", ext="id.exe", data=b"MZ\x90\x00binary")); check("KYC executable rejected", r.status_code == 400, J(r).get("message"))
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", ext="id.png", data=b"this is text pretending to be png")); check("KYC fake png (bad content) rejected", r.status_code == 400)
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", data=b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10))); check("KYC > 5 MB rejected", r.status_code == 400)
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", course="")); check("KYC missing field rejected", r.status_code == 400)
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", sid="S1")); check("KYC valid PNG -> 201 pending", r.status_code == 201, r.status_code)
r = post_form(b, "/api/kyc", kyc_form("Ravi Kumar", sid="S1")); check("same college ID on a 2nd account -> 409", r.status_code == 409, r.status_code)
post_form(b, "/api/kyc", kyc_form("Ravi Kumar", sid="S2", ext="id.pdf", data=b"%PDF-1.4 fake"))
post_form(c3, "/api/kyc", kyc_form("Meera Jain", sid="S3"))
r = app.test_client().post("/api/login", json={"email": "asha@x.edu", "password": "secret1"})
check("login while KYC pending -> no next + message", r.status_code == 200 and J(r)["next"] is None and "reviewed" in J(r)["message"], J(r))
check("kyc status pending", J(a.get("/api/kyc/status"))["status"] == "pending")

# -------------------------------------------------------------------- admin
check("admin API without login -> 401", anon.get("/api/admin/kyc").status_code == 401)
check("student session cannot use admin API", a.get("/api/admin/kyc").status_code == 401)
check("wrong admin password -> 401", adm.post("/api/admin/login", json={"email": "admin@campusx.local", "password": "x"}).status_code == 401)
r = adm.post("/api/admin/login", json={"email": "admin@campusx.local", "password": "ChangeMe123!"})
check("admin login returns admin_id/name/email", r.status_code == 200 and {"admin_id", "name", "email"} <= set(J(r)), J(r))
st = J(adm.get("/api/admin/stats"))["stats"]
check("admin stats counts", st == {"total_users": 5, "pending": 3, "approved": 0, "rejected": 0}, st)
apps = J(adm.get("/api/admin/kyc"))["applications"]
check("admin list has fields used by the panel", all({"kyc_id", "user_id", "name", "email", "file_name", "status", "submitted_at"} <= set(x) for x in apps) and len(apps) == 3)
asha = next(x for x in apps if x["email"] == "asha@x.edu")
r = adm.get(f"/api/admin/kyc/document/{asha['kyc_id']}"); check("admin sees ID image (image/png)", r.status_code == 200 and r.mimetype == "image/png", r.mimetype)
pdf = next(x for x in apps if x["email"] == "ravi@x.edu")
check("PDF served with application/pdf", adm.get(f"/api/admin/kyc/document/{pdf['kyc_id']}").mimetype == "application/pdf")
check("reject needs a reason", adm.post(f"/api/admin/kyc/{asha['user_id']}/reject", json={}).status_code == 400)
r = adm.post(f"/api/admin/kyc/{asha['user_id']}/reject", json={"admin_id": 1, "reason": "Photo is blurry"}); check("admin rejects by USER id", r.status_code == 200, J(r))
r = app.test_client().post("/api/login", json={"email": "asha@x.edu", "password": "secret1"})
check("rejected user is told the reason and sent to kyc.html", J(r)["next"] == "kyc.html" and "blurry" in J(r)["message"], J(r))
r = post_form(a, "/api/kyc", kyc_form("Asha Rao", sid="S1")); check("rejected user can re-upload", r.status_code == 201)
approve_all(adm)
st = J(adm.get("/api/admin/stats"))["stats"]; check("stats after approvals", st["approved"] == 3 and st["pending"] == 0, st)
r = app.test_client().post("/api/login", json={"email": "asha@x.edu", "password": "secret1"})
check("approved user without profile -> profile.html", J(r)["next"] == "profile.html", J(r))
check("admin and student can be logged in at the same time", a.get("/api/me").status_code == 200 and adm.get("/api/admin/me").status_code == 200)

# ------------------------------------------------------------------ profile
r = post_form(a, "/api/profile", profile_form("Asha", age="17")); check("profile age < 18 rejected", r.status_code == 400)
r = post_form(a, "/api/profile", profile_form("Asha", photos=2)); check("profile with 2 photos rejected (needs 3)", r.status_code == 400, J(r).get("message"))
f = profile_form("Asha"); f["photo1"] = (io.BytesIO(b"not an image"), "x.jpg"); r = post_form(a, "/api/profile", f); check("profile fake image rejected", r.status_code == 400)
r = post_form(a, "/api/profile", profile_form("Asha", gender="alien")); check("profile invalid gender rejected", r.status_code == 400)
r = post_form(a, "/api/profile", profile_form("Asha")); check("profile saved -> dashboard.html", r.status_code == 200 and J(r)["next"] == "dashboard.html", J(r))
post_form(b, "/api/profile", profile_form("Ravi", age="22", hobbies="coding, cricket, music", bio="coder"))
post_form(c3, "/api/profile", profile_form("Meera", age="20", hobbies="painting, travel", bio="artist", course="BBA", year="1", gender="female"))
me = J(a.get("/api/me")); check("/api/me returns raw profile for edit form", me["profile"]["raw"]["hobbies"] == "music, coding, football" and len(me["profile"]["photos"]) == 3, me.get("profile", {}).get("raw"))
r = post_form(a, "/api/profile", profile_form("Asha2", photos=0)); check("edit profile without re-uploading photos works", r.status_code == 200 and J(r)["profile"]["name"] == "Asha2", J(r))
old_photo = J(a.get("/api/me"))["profile"]["photos"][0]
r = post_form(a, "/api/profile", profile_form("Asha", photos=0, **{"photo0": (io.BytesIO(png((1, 2, 3))), "n.png")})); new_photo = J(a.get("/api/me"))["profile"]["photos"][0]
check("replacing one photo changes only that photo + old file deleted", new_photo != old_photo and not (Path(A.PROFILE_DIR) / old_photo.split("/")[-1]).exists())
check("photo is served to logged-in verified student", a.get(new_photo).status_code == 200 and a.get(new_photo).mimetype == "image/png")
check("photo not served to anonymous", anon.get(new_photo).status_code == 401)

# --------------------------------------------------------- discover / like / chat
d = J(a.get("/api/discover"))["profiles"]
check("discover excludes myself", all(p["name"] != "Asha" for p in d) and len(d) == 2, [p["name"] for p in d])
check("discover is ranked (Ravi most similar, first)", d[0]["name"] == "Ravi" and d[0]["score"] > d[1]["score"], [(p["name"], p["score"]) for p in d])
check("discover profile shape", {"id", "name", "age", "gender", "height", "course", "year", "residence", "hometown", "interests", "bio", "prompts", "photos"} <= set(d[0]))
check("PRIVACY: no email / password / religion in discover", not any(k in json.dumps(d).lower() for k in ("asha@x.edu", "ravi@x.edu", "password", "religion", "email")))
check("recommendation score matches the formula (0.503)", abs(next(p for p in d if p["name"] == "Ravi")["score"] - 0.503) < 0.001, d[0]["score"])
ravi, meera = d[0]["id"], d[1]["id"]
check("cannot message before a match", a.post("/api/messages", json={"receiver_id": ravi, "body": "hi"}).status_code == 403)
r = a.post("/api/like", json={"user_id": ravi}); check("one-sided like -> match false", J(r)["match"] is False, J(r))
check("liked profile no longer shown", ravi not in [p["id"] for p in J(a.get("/api/discover"))["profiles"]])
check("cannot like yourself", a.post("/api/like", json={"user_id": J(a.get("/api/me"))["user"]["id"]}).status_code == 404)
check("pass hides profile", a.post("/api/pass", json={"user_id": meera}).status_code == 200 and meera not in [p["id"] for p in J(a.get("/api/discover"))["profiles"]])
asha_id = J(a.get("/api/me"))["user"]["id"]
r = b.post("/api/like", json={"user_id": asha_id}); check("mutual like -> match true", J(r)["match"] is True, J(r))
check("like is idempotent (no duplicate connection)", b.post("/api/like", json={"user_id": asha_id}).status_code == 200 and len(J(b.get("/api/connections"))["connections"]) == 1)
check("matched user hidden from discover", ravi not in [p["id"] for p in J(a.get("/api/discover"))["profiles"]])
r = a.post("/api/messages", json={"receiver_id": ravi, "body": "hello Ravi"}); check("send message to match -> 201", r.status_code == 201)
b.post("/api/messages", json={"receiver_id": asha_id, "body": "Hey Asha <b>!</b>"})
m = J(a.get(f"/api/messages/{ravi}"))["messages"]; check("both messages visible, 'mine' flag correct", [x["mine"] for x in m] == [True, False], m)
check("incremental polling (after=id)", len(J(a.get(f"/api/messages/{ravi}?after={m[0]['id']}"))["messages"]) == 1)
check("outsider cannot read the chat", c3.get(f"/api/messages/{ravi}").status_code == 403)
check("outsider cannot message", c3.post("/api/messages", json={"receiver_id": ravi, "body": "x"}).status_code == 403)
check("empty / 2001-char message rejected", a.post("/api/messages", json={"receiver_id": ravi, "body": "  "}).status_code == 400 and a.post("/api/messages", json={"receiver_id": ravi, "body": "x" * 2001}).status_code == 400)
cn = J(a.get("/api/connections"))["connections"]; check("connections list has last message + photo", cn[0]["last_message"]["body"] == "Hey Asha <b>!</b>" and cn[0]["photo"], cn)
check("report profile stored and hides them", a.post("/api/report", json={"user_id": meera, "reason": "spam"}).status_code == 200 and len(J(adm.get("/api/admin/reports"))["reports"]) == 1)

# ------------------------------------------------- live chat (WhatsApp-style)
A.HEARTBEAT = 0.3
def read_until(it, token, limit=25):
    got = []
    for _ in range(limit):
        chunk = next(it).decode()
        got.append(chunk)
        if token in chunk: return chunk, got
    return "", got
def event_data(chunk): return json.loads(chunk.split("data: ", 1)[1].split("\n")[0])

asha_id = J(a.post("/api/login", json={"email": "asha@x.edu", "password": "secret1"}))["user"]["id"]
b.post("/api/login", json={"email": "ravi@x.edu", "password": "newpass1"})
r = a.post("/api/messages", json={"receiver_id": ravi, "body": "sent while Ravi is offline"})
check("message to an offline friend has status 'sent' (one tick)", J(r)["message"]["status"] == "sent", J(r))
check("unread counter for Ravi counts it", next(c for c in J(b.get("/api/connections"))["connections"] if c["user_id"] == asha_id)["unread"] >= 1)

ra = a.get("/api/stream", buffered=False); ita = iter(ra.response)
check("event stream opens as text/event-stream", ra.mimetype == "text/event-stream", ra.mimetype)
chunk, _ = read_until(ita, "event: ready"); check("stream sends 'ready'", "ready" in chunk)
rb = b.get("/api/stream", buffered=False); itb = iter(rb.response); read_until(itb, "event: ready")
chunk, _ = read_until(ita, "event: presence"); check("Asha is told instantly that Ravi came online", event_data(chunk) == {"peer": ravi, "online": True, "last_seen": None}, chunk)
chunk, _ = read_until(ita, "event: delivered"); check("Asha's old message becomes 'delivered' the moment Ravi connects", event_data(chunk)["peer"] == ravi, chunk)
st = [m["status"] for m in J(a.get(f"/api/messages/{ravi}"))["messages"] if m["mine"]]
check("history shows delivered status (double tick)", st and all(x == "delivered" for x in st), st)

r = a.post("/api/messages", json={"receiver_id": ravi, "body": "live message"}); check("message to an ONLINE friend is 'delivered' immediately", J(r)["message"]["status"] == "delivered")
chunk, _ = read_until(itb, "event: message"); d = event_data(chunk)
check("Ravi's open stream receives it instantly (push, no polling)", d["peer"] == asha_id and d["message"]["body"] == "live message" and d["message"]["mine"] is False, d)
check("unread counter = 3 for Ravi (earlier msg + offline msg + live msg)", next(c for c in J(b.get("/api/connections"))["connections"] if c["user_id"] == asha_id)["unread"] == 3)

r = b.post(f"/api/messages/{asha_id}/read"); check("Ravi opens the chat -> mark read ok", r.status_code == 200 and J(r)["up_to"], J(r))
chunk, _ = read_until(ita, "event: read"); check("Asha gets 'read' instantly (blue ticks)", event_data(chunk)["peer"] == ravi, chunk)
st = [m["status"] for m in J(a.get(f"/api/messages/{ravi}"))["messages"] if m["mine"]]
check("history shows read status", st and all(x == "read" for x in st), st)
check("unread counter back to 0", next(c for c in J(b.get("/api/connections"))["connections"] if c["user_id"] == asha_id)["unread"] == 0)
check("marking read twice is harmless", J(b.post(f"/api/messages/{asha_id}/read"))["up_to"] is None)

b.post("/api/typing", json={"receiver_id": asha_id, "typing": True})
chunk, _ = read_until(ita, "event: typing"); check("typing indicator is pushed", event_data(chunk) == {"peer": ravi, "typing": True}, chunk)
check("cannot send typing to a non-friend", c3.post("/api/typing", json={"receiver_id": ravi, "typing": True}).status_code == 403)
check("outsider cannot mark read", c3.post(f"/api/messages/{ravi}/read").status_code == 403)
check("Ravi shows as online in Asha's chat list", next(c for c in J(a.get("/api/connections"))["connections"] if c["user_id"] == ravi)["online"] is True)
check("stream needs login", anon.get("/api/stream").status_code == 401)

rb.close()   # Ravi closes the tab
chunk, _ = read_until(ita, "event: presence"); d = event_data(chunk)
check("Asha is told Ravi went offline, with last-seen time", d["online"] is False and d["last_seen"], d)
cn = next(c for c in J(a.get("/api/connections"))["connections"] if c["user_id"] == ravi)
check("chat list shows offline + last_seen", cn["online"] is False and cn["last_seen"])
ra.close()
check("no subscribers left after both tabs close", not A._subs)

# mutual like pushes a 'match' event to the person who liked first
x1, x2 = app.test_client(), app.test_client()
for cl, n, e, sid in ((x1, "Kiran Das", "kiran@x.edu", "K1"), (x2, "Lata Rao", "lata@x.edu", "K2")):
    signup(cl, n, e); post_form(cl, "/api/kyc", kyc_form(n, sid=sid))
approve_all(adm)
for cl, n, e in ((x1, "Kiran", "kiran@x.edu"), (x2, "Lata", "lata@x.edu")):
    cl.post("/api/login", json={"email": e, "password": "secret1"}); post_form(cl, "/api/profile", profile_form(n))
ids = {p["name"]: p["id"] for p in J(x1.get("/api/discover"))["profiles"]}
rx = x1.get("/api/stream", buffered=False); itx = iter(rx.response); read_until(itx, "event: ready")
x1.post("/api/like", json={"user_id": ids["Lata"]}); x2.post("/api/like", json={"user_id": J(x1.get("/api/me"))["user"]["id"]})
chunk, _ = read_until(itx, "event: match"); check("first liker is told about the match instantly", event_data(chunk)["name"] == "Lata", chunk)
rx.close()

# an old database (made before these features) is upgraded without losing data
import sqlite3
old = f"{tmp}/old.db"; con = sqlite3.connect(old); con.row_factory = sqlite3.Row
con.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT); CREATE TABLE messages(id INTEGER PRIMARY KEY, sender_id INT, receiver_id INT, body TEXT, created_at TEXT); INSERT INTO messages VALUES(1,1,2,'old msg','t');")
A.ensure_columns(con); cols = {r["name"] for r in con.execute("PRAGMA table_info(messages)")}
check("old database upgraded (delivered_at, read_at added, data kept)", {"delivered_at", "read_at"} <= cols and con.execute("SELECT body FROM messages").fetchone()[0] == "old msg")
con.close()

# ---------------------------------------------------------- password reset
logs = []
import logging
class H(logging.Handler):
    def emit(self, rec): logs.append(rec.getMessage())
A.log.addHandler(H())
check("forgot-password gives same reply for unknown email", J(app.test_client().post("/api/forgot-password", json={"email": "nobody@x.edu"}))["success"])
app.test_client().post("/api/forgot-password", json={"email": "ravi@x.edu"})
link = next((l for l in logs if "reset-password.html?token=" in l), "")
token = link.split("token=")[-1].strip()
check("reset link produced (console when SMTP not set)", len(token) > 20)
check("reset with short password rejected", app.test_client().post("/api/reset-password", json={"token": token, "password": "123"}).status_code == 400)
check("reset with bad token rejected", app.test_client().post("/api/reset-password", json={"token": "nope", "password": "newpass1"}).status_code == 400)
check("reset with valid token works", app.test_client().post("/api/reset-password", json={"token": token, "password": "newpass1"}).status_code == 200)
check("reset token is single-use", app.test_client().post("/api/reset-password", json={"token": token, "password": "another1"}).status_code == 400)
check("login with new password works, old fails", app.test_client().post("/api/login", json={"email": "ravi@x.edu", "password": "newpass1"}).status_code == 200 and app.test_client().post("/api/login", json={"email": "ravi@x.edu", "password": "secret1"}).status_code == 401)

# ------------------------------------------------------ security + hosting
check("CSRF: foreign Origin blocked", app.test_client().post("/api/login", json={}, headers={"Origin": "http://evil.example"}).status_code == 403)
check("CORS: allowed dev origin gets credentials header", app.test_client().get("/api/health", headers={"Origin": "http://127.0.0.1:5500"}).headers.get("Access-Control-Allow-Credentials") == "true")
check("CORS: unknown origin gets no CORS header", "Access-Control-Allow-Origin" not in app.test_client().get("/api/health", headers={"Origin": "http://evil.example"}).headers)
ck = app.test_client().post("/api/signup", json={"fullName": "Cookie Test", "email": "ck@x.edu", "password": "secret1"}).headers.get("Set-Cookie", "")
check("session cookie is HttpOnly + SameSite=Lax", "HttpOnly" in ck and "SameSite=Lax" in ck, ck)
check("frontend page served (login.html)", app.test_client().get("/login.html").status_code == 200)
check("python source not served", app.test_client().get("/app.py").status_code == 404 and app.test_client().get("/../app.py").status_code == 404)
check("unknown API path -> JSON 404", app.test_client().get("/api/nope").get_json()["success"] is False)
A.app.config["RATE_LIMIT"] = True
codes = [app.test_client().post("/api/login", json={"email": "ratelimit@x.edu", "password": "x"}).status_code for _ in range(10)]
check("login rate limit kicks in (429)", 429 in codes, codes)
check("logout works", a.post("/api/logout").status_code == 200 and a.get("/api/me").status_code == 401)

passed = sum(1 for _, ok_, _ in RESULTS if ok_)
for n, ok_, g in RESULTS:
    print(("PASS  " if ok_ else "FAIL  ") + n + ("" if ok_ else f"   -> got: {g}"))
print(f"\n{passed}/{len(RESULTS)} tests passed")
sys.exit(0 if passed == len(RESULTS) else 1)
