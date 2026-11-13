"""CampusX backend: Flask + SQLite.

Serves the REST API under /api, protected media under /media and (for convenience)
the frontend pages from ../frontend, so the whole project runs with one command:
    python app.py   ->   http://127.0.0.1:5000
"""
import os, re, json, time, queue, threading, hashlib, secrets, sqlite3, smtplib, logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, request, jsonify, session, send_from_directory, redirect, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("campusx")

# --------------------------------------------------------------------------- config
BASE = Path(__file__).resolve().parent
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", BASE.parent / "frontend"))
DB_PATH = Path(os.getenv("DATABASE_PATH", BASE / "campusx_v2.db"))
UPLOADS = Path(os.getenv("UPLOAD_DIR", BASE / "uploads"))
KYC_DIR, PROFILE_DIR = UPLOADS / "kyc", UPLOADS / "profiles"
for d in (KYC_DIR, PROFILE_DIR):
    d.mkdir(parents=True, exist_ok=True)

def _secret_key():
    key = os.getenv("SECRET_KEY", "").strip()
    if key:
        return key
    f = BASE / ".secret_key"
    if f.exists():
        return f.read_text().strip()
    key = secrets.token_hex(32)
    f.write_text(key)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return key

app = Flask(__name__, static_folder=None)
app.secret_key = _secret_key()
app.config.update(
    MAX_CONTENT_LENGTH=18 * 1024 * 1024,
    SESSION_COOKIE_NAME="campusx_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    RATE_LIMIT=os.getenv("RATE_LIMIT", "true").lower() == "true",
)
ALLOWED_ORIGINS = {o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",") if o.strip()}

MAX_KYC = 5 * 1024 * 1024
MAX_PHOTO = 5 * 1024 * 1024
STATIC_EXT = {"html", "css", "js", "png", "jpg", "jpeg", "webp", "svg", "ico", "woff", "woff2"}

GENDERS = {"male": "Male", "female": "Female", "non-binary": "Non-binary", "prefer-not": "Prefer not to say"}
YEARS = {"1": "1st Year", "2": "2nd Year", "3": "3rd Year", "4": "4th Year", "masters": "Master's"}
RESIDENCE = {"hosteller": "Hosteller", "day-scholar": "Day Scholar"}
RELIGIONS = {"", "hindu", "muslim", "christian", "sikh", "buddhist", "jain", "other", "prefer-not"}
KYC_COURSES = {"cs", "eng", "bus", "arts", "sci", "other"}
KYC_YEARS = {"1", "2", "3", "4", "grad"}
QUESTIONS = ["What's something you're always up for?",
             "What's your perfect college day?",
             "What's something you want to try this year?"]
MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "pdf": "application/pdf"}

# ------------------------------------------------------------------------- database
@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'kyc_pending', created_at TEXT NOT NULL, last_seen TEXT);
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kyc(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE,
  full_name TEXT NOT NULL, college TEXT NOT NULL, student_id TEXT NOT NULL,
  course TEXT NOT NULL, year TEXT NOT NULL, original_file TEXT NOT NULL,
  stored_file TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  reason TEXT, submitted_at TEXT NOT NULL, reviewed_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS profiles(
  user_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL, age INTEGER NOT NULL,
  gender TEXT, course TEXT, year TEXT, height TEXT, hometown TEXT, hosteller TEXT,
  religion TEXT, hobbies TEXT, bio TEXT, q1 TEXT, q2 TEXT, q3 TEXT,
  photos TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS likes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER NOT NULL, to_user INTEGER NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(from_user,to_user),
  FOREIGN KEY(from_user) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(to_user) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS passes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER NOT NULL, to_user INTEGER NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(from_user,to_user),
  FOREIGN KEY(from_user) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(to_user) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS connections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_a INTEGER NOT NULL, user_b INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'accepted', created_at TEXT NOT NULL, UNIQUE(user_a,user_b),
  CHECK(user_a < user_b),
  FOREIGN KEY(user_a) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(user_b) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL,
  body TEXT NOT NULL, created_at TEXT NOT NULL, delivered_at TEXT, read_at TEXT,
  FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id, receiver_id, id);
CREATE TABLE IF NOT EXISTS password_resets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, reported_id INTEGER NOT NULL,
  reason TEXT, created_at TEXT NOT NULL, UNIQUE(reporter_id,reported_id),
  FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(reported_id) REFERENCES users(id) ON DELETE CASCADE);
"""

def ensure_columns(c):
    """Upgrade a database created by an older version (adds the chat columns)."""
    for table, col in (("messages", "delivered_at"), ("messages", "read_at"), ("users", "last_seen")):
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")

def init_db():
    with db() as c:
        c.executescript(SCHEMA)
        ensure_columns(c)
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(receiver_id, sender_id, read_at)")
        email = os.getenv("ADMIN_EMAIL", "admin@campusx.com").strip().lower()
        name = os.getenv("ADMIN_NAME", "CampusX Administrator")
        pw = os.getenv("ADMIN_PASSWORD", "campusX@2026)
        row = c.execute("SELECT id, password_hash FROM admins WHERE email=?", (email,)).fetchone()
        if not row:
            c.execute("INSERT INTO admins(name,email,password_hash) VALUES(?,?,?)",
                      (name, email, generate_password_hash(pw)))
        else:  # keep admin credentials in sync with .env
            c.execute("UPDATE admins SET name=? WHERE id=?", (name, row["id"]))
            if not check_password_hash(row["password_hash"], pw):
                c.execute("UPDATE admins SET password_hash=? WHERE id=?",
                          (generate_password_hash(pw), row["id"]))
    if os.getenv("ADMIN_PASSWORD", "ChangeMe123!") == "ChangeMe123!":
        log.warning("Admin is using the default password. Change ADMIN_PASSWORD in .env before real use.")

# ------------------------------------------------------------------------- helpers
def ok(**kw):
    return jsonify(success=True, **kw)

def fail(message, code=400, **kw):
    return jsonify(success=False, message=message, **kw), code

_hits = {}
def allowed(key, limit, window):
    """Tiny in-memory rate limiter. Returns False when the limit is exceeded."""
    if not app.config["RATE_LIMIT"]:
        return True
    t = time.time()
    q = [x for x in _hits.get(key, []) if t - x < window]
    if len(q) >= limit:
        _hits[key] = q
        return False
    q.append(t)
    _hits[key] = q
    return True

def clean(v, n):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v if v is not None else "")).strip()[:n]

def sniff(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n": return "png"
    if data[:3] == b"\xff\xd8\xff": return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return "webp"
    if data[:5] == b"%PDF-": return "pdf"
    return None

def read_upload(f, limit, kinds):
    """Return (bytes, kind) or (None, error message). File type comes from the content, not the name."""
    data = f.read(limit + 1)
    if not data:
        return None, "The uploaded file is empty."
    if len(data) > limit:
        return None, f"File must be under {limit // (1024 * 1024)} MB."
    kind = sniff(data)
    if kind not in kinds:
        return None, "Unsupported file type."
    return data, kind

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    with db() as c:
        r = c.execute("SELECT id, full_name, email, status FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        session.pop("uid", None)
    return dict(r) if r else None

def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        u = current_user()
        if not u:
            return fail("Please log in first.", 401)
        request.user = u
        return fn(*a, **k)
    return w

def verified_required(fn):
    @wraps(fn)
    def w(*a, **k):
        u = current_user()
        if not u:
            return fail("Please log in first.", 401)
        if u["status"] != "verified":
            return fail("Your college ID has not been verified yet.", 403)
        request.user = u
        return fn(*a, **k)
    return w

def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        aid = session.get("aid")
        if not aid:
            return fail("Admin login required.", 401)
        with db() as c:
            if not c.execute("SELECT 1 FROM admins WHERE id=?", (aid,)).fetchone():
                session.pop("aid", None)
                return fail("Admin login required.", 401)
        return fn(*a, **k)
    return w

def valid_identifier(s):
    if not (3 <= len(s) <= 120) or re.search(r"\s", s):
        return False
    if "@" in s:
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s))
    return bool(re.fullmatch(r"[A-Za-z0-9._\-/]+", s))

# ---------------------------------------------------------- profile + recommendation
STOP = set("a an and are as at be but by for from has have i if in is it its me my of on or so that the this to was we with you your am im".split())

def tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 1 and w not in STOP}

def score(me, other):
    """Score(A,B) = min(|TA∩TB| / |TA∪TB| + 0.12[same course] + 0.05[same year], 1)"""
    ta = tokens((me["hobbies"] or "") + " " + (me["bio"] or ""))
    tb = tokens((other["hobbies"] or "") + " " + (other["bio"] or ""))
    union = ta | tb
    s = len(ta & tb) / len(union) if union else 0.0
    if (me["course"] or "").strip().lower() and (me["course"] or "").strip().lower() == (other["course"] or "").strip().lower():
        s += 0.12
    if (me["year"] or "") and me["year"] == other["year"]:
        s += 0.05
    return round(min(s, 1.0), 3)

def photo_list(row):
    try:
        return [p for p in json.loads(row["photos"] or "[]") if p]
    except ValueError:
        return []

def interests(row):
    out = []
    for h in (row["hobbies"] or "").split(","):
        h = h.strip()
        if h and h.lower() not in [x.lower() for x in out]:
            out.append(h[:30])
    return out[:12]

def public_profile(row, sc=None):
    qs = [row["q1"], row["q2"], row["q3"]]
    d = {
        "id": row["user_id"], "name": row["nickname"], "age": row["age"],
        "gender": GENDERS.get(row["gender"], row["gender"] or "-"),
        "height": row["height"] or "-", "course": row["course"] or "-",
        "year": YEARS.get(row["year"], row["year"] or "-"),
        "residence": RESIDENCE.get(row["hosteller"], row["hosteller"] or "-"),
        "hometown": row["hometown"] or "-", "interests": interests(row), "bio": row["bio"] or "",
        "prompts": [[QUESTIONS[i], a] for i, a in enumerate(qs) if a],
        "photos": [f"/media/profile/{p}" for p in photo_list(row)],
    }
    if sc is not None:
        d["score"] = sc
    return d

def own_profile(row):
    d = public_profile(row)
    d["raw"] = {k: row[k] for k in ("nickname", "age", "gender", "course", "year", "height", "hometown",
                                    "hosteller", "religion", "hobbies", "bio")}
    d["raw"].update(question1=row["q1"], question2=row["q2"], question3=row["q3"])
    return d

def get_profile_row(c, uid):
    return c.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()

# --------------------------------------------------------------- request hooks
@app.before_request
def csrf_origin_check():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and origin != "null" and origin not in ALLOWED_ORIGINS \
                and urlparse(origin).netloc != request.host:
            return fail("Cross-site request blocked.", 403)

@app.after_request
def headers(resp):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        resp.headers["Vary"] = "Origin"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith(("/api/", "/media/")):
        resp.headers["Cache-Control"] = "no-store"
    elif request.path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.errorhandler(404)
def not_found(e):
    return fail("Not found.", 404) if request.path.startswith("/api/") else ("Not found", 404)

@app.errorhandler(405)
def bad_method(e):
    return fail("Method not allowed.", 405)

@app.errorhandler(413)
def too_big(e):
    return fail("Uploaded files are too large.", 413)

@app.errorhandler(500)
def server_error(e):
    log.exception("Unhandled error")
    return fail("Something went wrong on the server.", 500)

# -------------------------------------------------------------------------- auth
@app.get("/api/health")
def health():
    return ok(service="CampusX API", status="running")

@app.post("/api/signup")
def signup():
    d = request.get_json(silent=True) or {}
    if not allowed(f"signup:{request.remote_addr}", 10, 3600):
        return fail("Too many sign-ups from this network. Try again later.", 429)
    name = clean(d.get("fullName", d.get("full_name")), 80)
    ident = clean(d.get("email"), 120).lower()
    pw = str(d.get("password", ""))
    if len(name) < 2:
        return fail("Please enter your full name.")
    if not valid_identifier(ident):
        return fail("Enter a valid college email or college ID.")
    if len(pw) < 6:
        return fail("Password must contain at least 6 characters.")
    if len(pw) > 128:
        return fail("Password is too long.")
    try:
        with db() as c:
            uid = c.execute("INSERT INTO users(full_name,email,password_hash,created_at) VALUES(?,?,?,?)",
                            (name, ident, generate_password_hash(pw), now())).lastrowid
    except sqlite3.IntegrityError:
        return fail("This email / college ID is already registered.", 409)
    session.clear()
    session.permanent = True
    session["uid"] = uid
    return ok(message="Account created. Please verify your college ID.", next="kyc.html"), 201

def next_page(u):
    """Where should this user go after logging in?"""
    with db() as c:
        k = c.execute("SELECT status, reason FROM kyc WHERE user_id=?", (u["id"],)).fetchone()
        prof = get_profile_row(c, u["id"])
    if u["status"] == "verified":
        return ("dashboard.html" if prof else "profile.html"), None
    if not k:
        return "kyc.html", "Please upload your college ID to continue."
    if k["status"] == "rejected":
        return "kyc.html", "Your college ID was rejected" + (f": {k['reason']}" if k["reason"] else ".") + " Please upload it again."
    return None, "Your college ID is still being reviewed. Please check back soon."

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    ident = clean(d.get("email"), 120).lower()
    if not allowed(f"login:{request.remote_addr}:{ident}", 8, 600):
        return fail("Too many login attempts. Please wait a few minutes.", 429)
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (ident,)).fetchone()
    if not u or not check_password_hash(u["password_hash"], str(d.get("password", ""))):
        return fail("Incorrect email / college ID or password.", 401)
    session.pop("uid", None)
    session.permanent = True
    session["uid"] = u["id"]
    nxt, msg = next_page(dict(u))
    return ok(status=u["status"], next=nxt, message=msg, user={"id": u["id"], "full_name": u["full_name"]})

@app.post("/api/logout")
def logout():
    session.pop("uid", None)
    return ok()

@app.get("/api/me")
@login_required
def me():
    u = request.user
    with db() as c:
        p = get_profile_row(c, u["id"])
        k = c.execute("SELECT status, reason FROM kyc WHERE user_id=?", (u["id"],)).fetchone()
    return ok(user=u, kyc=dict(k) if k else {"status": "not_submitted"},
              profile=own_profile(p) if p else None)

# --------------------------------------------------------------------------- KYC
@app.post("/api/kyc")
@login_required
def kyc_submit():
    u = request.user
    if u["status"] == "verified":
        return fail("Your account is already verified.", 409)
    if not allowed(f"kyc:{u['id']}", 10, 3600):
        return fail("Too many attempts. Please try again later.", 429)
    f = {k: clean(request.form.get(k), 120) for k in ("fullName", "college", "studentId", "course", "year")}
    if not all(f.values()):
        return fail("Please complete all verification fields.")
    if f["course"] not in KYC_COURSES or f["year"] not in KYC_YEARS:
        return fail("Please select a valid course and year.")
    up = request.files.get("document") or request.files.get("file")
    if not up or not up.filename:
        return fail("Please upload your college ID.")
    data, kind = read_upload(up, MAX_KYC, {"png", "jpg", "pdf"})
    if data is None:
        return fail(kind if kind != "Unsupported file type." else "Please upload a PNG, JPG or PDF file.")
    stored = f"{secrets.token_hex(16)}.{kind}"
    original = secure_filename(up.filename)[:100] or f"id.{kind}"
    with db() as c:
        dup = c.execute("""SELECT 1 FROM kyc WHERE lower(college)=lower(?) AND lower(student_id)=lower(?)
                           AND user_id<>? AND status IN ('pending','approved')""",
                        (f["college"], f["studentId"], u["id"])).fetchone()
        if dup:
            return fail("This college ID is already linked to another account.", 409)
        old = c.execute("SELECT stored_file FROM kyc WHERE user_id=?", (u["id"],)).fetchone()
        (KYC_DIR / stored).write_bytes(data)
        if old:
            c.execute("""UPDATE kyc SET full_name=?,college=?,student_id=?,course=?,year=?,original_file=?,
                         stored_file=?,status='pending',reason=NULL,submitted_at=?,reviewed_at=NULL WHERE user_id=?""",
                      (f["fullName"], f["college"], f["studentId"], f["course"], f["year"], original,
                       stored, now(), u["id"]))
            try:
                (KYC_DIR / old["stored_file"]).unlink()
            except OSError:
                pass
        else:
            c.execute("""INSERT INTO kyc(user_id,full_name,college,student_id,course,year,original_file,
                         stored_file,submitted_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                      (u["id"], f["fullName"], f["college"], f["studentId"], f["course"], f["year"],
                       original, stored, now()))
        c.execute("UPDATE users SET status='kyc_pending' WHERE id=?", (u["id"],))
    return ok(message="Verification submitted.", status="pending"), 201

@app.get("/api/kyc/status")
@login_required
def kyc_status():
    with db() as c:
        r = c.execute("SELECT status, reason, submitted_at, reviewed_at FROM kyc WHERE user_id=?",
                      (request.user["id"],)).fetchone()
    return ok(**(dict(r) if r else {"status": "not_submitted"}))

# -------------------------------------------------------------------------- admin
@app.post("/api/admin/login")
def admin_login():
    d = request.get_json(silent=True) or {}
    email = clean(d.get("email"), 120).lower()
    if not allowed(f"admin:{request.remote_addr}", 8, 600):
        return fail("Too many login attempts. Please wait a few minutes.", 429)
    with db() as c:
        a = c.execute("SELECT * FROM admins WHERE email=?", (email,)).fetchone()
    if not a or not check_password_hash(a["password_hash"], str(d.get("password", ""))):
        return fail("Invalid admin credentials.", 401)
    session.pop("aid", None)
    session.permanent = True
    session["aid"] = a["id"]
    return ok(admin_id=a["id"], name=a["name"], email=a["email"])

@app.post("/api/admin/logout")
def admin_logout():
    session.pop("aid", None)
    return ok()

@app.get("/api/admin/me")
@admin_required
def admin_me():
    with db() as c:
        a = c.execute("SELECT id,name,email FROM admins WHERE id=?", (session["aid"],)).fetchone()
    return ok(admin=dict(a))

@app.get("/api/admin/stats")
@admin_required
def admin_stats():
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        cnt = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM kyc GROUP BY status")}
    return ok(stats={"total_users": total, "pending": cnt.get("pending", 0),
                     "approved": cnt.get("approved", 0), "rejected": cnt.get("rejected", 0)})

@app.get("/api/admin/kyc")
@admin_required
def admin_kyc():
    with db() as c:
        rows = c.execute("""SELECT k.id AS kyc_id, k.user_id, u.email, k.full_name AS name, u.full_name AS signup_name,
              k.college, k.student_id, k.course, k.year AS academic_year, k.original_file AS file_name,
              k.status, k.reason AS rejection_reason, k.submitted_at, k.reviewed_at
              FROM kyc k JOIN users u ON u.id = k.user_id ORDER BY k.submitted_at DESC""").fetchall()
    return ok(applications=[dict(r) for r in rows])

@app.get("/api/admin/kyc/document/<int:kid>")
@admin_required
def admin_kyc_doc(kid):
    with db() as c:
        r = c.execute("SELECT stored_file FROM kyc WHERE id=?", (kid,)).fetchone()
    if not r:
        return fail("Document not found.", 404)
    ext = r["stored_file"].rsplit(".", 1)[-1]
    return send_from_directory(KYC_DIR, r["stored_file"], mimetype=MIME.get(ext, "application/octet-stream"))

def review(user_id, state):
    d = request.get_json(silent=True) or {}
    reason = clean(d.get("reason"), 300)
    if state == "rejected" and not reason:
        return fail("Please enter a rejection reason.")
    with db() as c:
        k = c.execute("SELECT id FROM kyc WHERE user_id=?", (user_id,)).fetchone()
        if not k:
            return fail("Application not found.", 404)
        c.execute("UPDATE kyc SET status=?, reason=?, reviewed_at=? WHERE user_id=?",
                  (state, reason if state == "rejected" else None, now(), user_id))
        c.execute("UPDATE users SET status=? WHERE id=?",
                  ("verified" if state == "approved" else "kyc_rejected", user_id))
    return ok(message=f"KYC {state}.")

# NOTE: the admin panel sends the *user id* in these two URLs.
@app.post("/api/admin/kyc/<int:user_id>/approve")
@admin_required
def admin_approve(user_id):
    return review(user_id, "approved")

@app.post("/api/admin/kyc/<int:user_id>/reject")
@admin_required
def admin_reject(user_id):
    return review(user_id, "rejected")

@app.get("/api/admin/reports")
@admin_required
def admin_reports():
    with db() as c:
        rows = c.execute("""SELECT r.id, r.reason, r.created_at, a.email AS reporter, b.email AS reported
              FROM reports r JOIN users a ON a.id=r.reporter_id JOIN users b ON b.id=r.reported_id
              ORDER BY r.id DESC""").fetchall()
    return ok(reports=[dict(r) for r in rows])

# ------------------------------------------------------------------------ profile
@app.post("/api/profile")
@verified_required
def save_profile():
    uid = request.user["id"]
    g = lambda k, n=100: clean(request.form.get(k), n)
    nickname, course = g("nickname", 40), g("course", 60)
    gender, year, host, religion = g("gender"), g("year"), g("hosteller"), g("religion")
    try:
        age = int(g("age", 3))
    except ValueError:
        age = 0
    answers = [g("question1", 180), g("question2", 180), g("question3", 180)]
    if not nickname:
        return fail("Please enter your nickname.")
    if age < 18 or age > 99:
        return fail("You must be 18 or older.")
    if gender not in GENDERS:
        return fail("Please select your gender.")
    if not course:
        return fail("Please enter your branch/course.")
    if year not in YEARS:
        return fail("Please select your year.")
    if host not in RESIDENCE:
        return fail("Please select your living status.")
    if religion not in RELIGIONS:
        return fail("Invalid religion option.")
    for i, a in enumerate(answers, 1):
        if not a:
            return fail(f"Please answer question {i}.")
    with db() as c:
        old = get_profile_row(c, uid)
        photos = (photo_list(old) if old else [])
        photos = (photos + [None, None, None])[:3] if old and len(photo_list(old)) == 3 else [None, None, None]
        new_files, replaced = {}, []
        for i in range(3):
            f = request.files.get(f"photo{i}")
            if f and f.filename:
                data, kind = read_upload(f, MAX_PHOTO, {"png", "jpg", "webp"})
                if data is None:
                    return fail(f"Photo {i + 1}: " + ("must be a JPG, PNG or WEBP image." if kind == "Unsupported file type." else kind))
                new_files[i] = (data, kind)
        if not all(photos[i] or i in new_files for i in range(3)):
            return fail("Please upload all 3 profile photos.")
        for i, (data, kind) in new_files.items():
            name = f"{secrets.token_hex(12)}.{kind}"
            (PROFILE_DIR / name).write_bytes(data)
            if photos[i]:
                replaced.append(photos[i])
            photos[i] = name
        vals = (nickname, age, gender, course, year, g("height", 20), g("hometown", 60), host, religion,
                g("hobbies", 200), g("bio", 300), *answers, json.dumps(photos), now(), uid)
        c.execute("""INSERT INTO profiles(nickname,age,gender,course,year,height,hometown,hosteller,religion,hobbies,
                     bio,q1,q2,q3,photos,updated_at,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname, age=excluded.age,
                     gender=excluded.gender, course=excluded.course, year=excluded.year, height=excluded.height,
                     hometown=excluded.hometown, hosteller=excluded.hosteller, religion=excluded.religion,
                     hobbies=excluded.hobbies, bio=excluded.bio, q1=excluded.q1, q2=excluded.q2, q3=excluded.q3,
                     photos=excluded.photos, updated_at=excluded.updated_at""", vals)
        row = get_profile_row(c, uid)
    for name in replaced:
        try:
            (PROFILE_DIR / name).unlink()
        except OSError:
            pass
    return ok(message="Profile saved.", profile=own_profile(row), next="dashboard.html")

@app.get("/api/profile/<int:uid>")
@verified_required
def get_profile(uid):
    with db() as c:
        row = c.execute("""SELECT p.* FROM profiles p JOIN users u ON u.id=p.user_id
                           WHERE p.user_id=? AND u.status='verified'""", (uid,)).fetchone()
    if not row:
        return fail("Profile not found.", 404)
    return ok(profile=public_profile(row))

@app.get("/media/profile/<path:filename>")
def profile_media(filename):
    u = current_user()
    if not (session.get("aid") or (u and u["status"] == "verified")):
        return fail("Please log in first.", 401)
    resp = send_from_directory(PROFILE_DIR, filename)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp

# ------------------------------------------------------------ discover / like / pass
@app.get("/api/discover")
@verified_required
def discover():
    uid = request.user["id"]
    with db() as c:
        mine = get_profile_row(c, uid)
        if not mine:
            return ok(profiles=[], needs_profile=True)
        rows = c.execute("""
            SELECT p.* FROM profiles p JOIN users u ON u.id = p.user_id
            WHERE u.status='verified' AND p.user_id <> ?
              AND p.user_id NOT IN (SELECT to_user FROM likes WHERE from_user=?)
              AND p.user_id NOT IN (SELECT to_user FROM passes WHERE from_user=?)
              AND p.user_id NOT IN (SELECT reported_id FROM reports WHERE reporter_id=?)
              AND p.user_id NOT IN (SELECT CASE WHEN user_a=? THEN user_b ELSE user_a END
                                    FROM connections WHERE user_a=? OR user_b=?)""",
                         (uid,) * 7).fetchall()
    ranked = sorted(((score(mine, r), r) for r in rows), key=lambda t: (-t[0], t[1]["user_id"]))
    return ok(profiles=[public_profile(r, s) for s, r in ranked[:100]])

def target_profile(c, uid, target):
    return c.execute("""SELECT p.* FROM profiles p JOIN users u ON u.id=p.user_id
                        WHERE p.user_id=? AND u.status='verified' AND p.user_id<>?""", (target, uid)).fetchone()

def target_id(d):
    try:
        return int(d.get("user_id"))
    except (TypeError, ValueError):
        return None

@app.post("/api/like")
@verified_required
def like():
    uid, t = request.user["id"], target_id(request.get_json(silent=True) or {})
    with db() as c:
        row = target_profile(c, uid, t) if t else None
        if not row:
            return fail("Student not found.", 404)
        c.execute("INSERT OR IGNORE INTO likes(from_user,to_user,created_at) VALUES(?,?,?)", (uid, t, now()))
        c.execute("DELETE FROM passes WHERE from_user=? AND to_user=?", (uid, t))
        match = c.execute("SELECT 1 FROM likes WHERE from_user=? AND to_user=?", (t, uid)).fetchone() is not None
        if match:
            a, b = sorted((uid, t))
            c.execute("INSERT OR IGNORE INTO connections(user_a,user_b,status,created_at) VALUES(?,?, 'accepted', ?)",
                      (a, b, now()))
    if match:
        with db() as c:
            me_p = get_profile_row(c, uid)
        publish(t, "match", {"peer": uid, "name": me_p["nickname"] if me_p else "Someone"})
    return ok(match=match, user_id=t, name=row["nickname"])

@app.post("/api/pass")
@verified_required
def pass_profile():
    uid, t = request.user["id"], target_id(request.get_json(silent=True) or {})
    with db() as c:
        if not t or not target_profile(c, uid, t):
            return fail("Student not found.", 404)
        c.execute("INSERT OR IGNORE INTO passes(from_user,to_user,created_at) VALUES(?,?,?)", (uid, t, now()))
    return ok()

@app.post("/api/report")
@verified_required
def report():
    d = request.get_json(silent=True) or {}
    uid, t = request.user["id"], target_id(d)
    with db() as c:
        if not t or not target_profile(c, uid, t):
            return fail("Student not found.", 404)
        c.execute("INSERT OR IGNORE INTO reports(reporter_id,reported_id,reason,created_at) VALUES(?,?,?,?)",
                  (uid, t, clean(d.get("reason"), 300), now()))
    return ok(message="Thanks. This report will be reviewed.")

# ------------------------------------------------- live chat (Server-Sent Events)
HEARTBEAT = float(os.getenv("SSE_HEARTBEAT", "8"))
_subs = {}                      # user id -> set of open event queues (one per open tab)
_subs_lock = threading.Lock()

def publish(uid, event, data):
    with _subs_lock:
        qs = list(_subs.get(uid, ()))
    for q in qs:
        try:
            q.put_nowait((event, data))
        except queue.Full:
            pass

def is_online(uid):
    with _subs_lock:
        return bool(_subs.get(uid))

def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

def is_connected(c, a, b):
    x, y = sorted((a, b))
    return c.execute("SELECT 1 FROM connections WHERE user_a=? AND user_b=? AND status='accepted'",
                     (x, y)).fetchone() is not None

def connected_ids(c, uid):
    return [r["o"] for r in c.execute(
        """SELECT CASE WHEN user_a=? THEN user_b ELSE user_a END AS o FROM connections
           WHERE (user_a=? OR user_b=?) AND status='accepted'""", (uid, uid, uid))]

def announce_presence(uid, online, last_seen=None):
    with db() as c:
        peers = connected_ids(c, uid)
    for p in peers:
        publish(p, "presence", {"peer": uid, "online": online, "last_seen": last_seen})

def mark_delivered(uid):
    """Messages sent to uid while offline count as delivered as soon as uid connects."""
    with db() as c:
        rows = c.execute("""SELECT sender_id, MAX(id) AS top FROM messages
                            WHERE receiver_id=? AND delivered_at IS NULL GROUP BY sender_id""", (uid,)).fetchall()
        ts = now()
        for r in rows:
            c.execute("""UPDATE messages SET delivered_at=? WHERE receiver_id=? AND sender_id=?
                         AND delivered_at IS NULL AND id<=?""", (ts, uid, r["sender_id"], r["top"]))
    for r in rows:
        publish(r["sender_id"], "delivered", {"peer": uid, "up_to": r["top"]})

def msg_status(r):
    return "read" if r["read_at"] else ("delivered" if r["delivered_at"] else "sent")

def msg_dict(r, uid):
    return {"id": r["id"], "mine": r["sender_id"] == uid, "body": r["body"],
            "created_at": r["created_at"], "status": msg_status(r)}

@app.get("/api/stream")
@verified_required
def stream():
    uid = request.user["id"]
    q = queue.Queue(maxsize=500)
    with _subs_lock:
        first = not _subs.get(uid)
        _subs.setdefault(uid, set()).add(q)
    if first:
        announce_presence(uid, True)
    mark_delivered(uid)

    def gen():
        try:
            yield "retry: 2000\n\n"
            yield sse("ready", {"user_id": uid})
            while True:
                try:
                    ev, data = q.get(timeout=HEARTBEAT)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                yield sse(ev, data)
        finally:
            with _subs_lock:
                s = _subs.get(uid, set())
                s.discard(q)
                last = not s
                if last:
                    _subs.pop(uid, None)
            if last:
                ts = now()
                with db() as c:
                    c.execute("UPDATE users SET last_seen=? WHERE id=?", (ts, uid))
                announce_presence(uid, False, ts)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/connections")
@verified_required
def connections():
    uid = request.user["id"]
    out = []
    with db() as c:
        for other in connected_ids(c, uid):
            p = c.execute("""SELECT p.*, u.last_seen FROM profiles p JOIN users u ON u.id=p.user_id
                             WHERE p.user_id=? AND u.status='verified'""", (other,)).fetchone()
            if not p:
                continue
            m = c.execute("""SELECT id, sender_id, body, created_at, delivered_at, read_at FROM messages
                             WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
                             ORDER BY id DESC LIMIT 1""", (uid, other, other, uid)).fetchone()
            unread = c.execute("""SELECT COUNT(*) n FROM messages WHERE sender_id=? AND receiver_id=?
                                  AND read_at IS NULL""", (other, uid)).fetchone()["n"]
            cx_row = c.execute("SELECT created_at FROM connections WHERE user_a=? AND user_b=?",
                               tuple(sorted((uid, other)))).fetchone()
            photos = photo_list(p)
            out.append({"user_id": other, "name": p["nickname"], "age": p["age"],
                        "photo": f"/media/profile/{photos[0]}" if photos else None,
                        "matched_at": cx_row["created_at"], "unread": unread,
                        "online": is_online(other), "last_seen": p["last_seen"],
                        "last_message": {"body": m["body"], "mine": m["sender_id"] == uid,
                                         "created_at": m["created_at"], "status": msg_status(m)} if m else None,
                        "_sort": m["created_at"] if m else cx_row["created_at"]})
    out.sort(key=lambda x: x.pop("_sort"), reverse=True)
    return ok(connections=out)

@app.get("/api/messages/<int:other>")
@verified_required
def get_messages(other):
    uid = request.user["id"]
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0
    base = """SELECT id, sender_id, body, created_at, delivered_at, read_at FROM messages
              WHERE ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))"""
    args = (uid, other, other, uid)
    with db() as c:
        if not is_connected(c, uid, other):
            return fail("You can message only a connected student.", 403)
        if after:
            rows = c.execute(base + " AND id>? ORDER BY id LIMIT 500", args + (after,)).fetchall()
        else:  # first load: the most recent 500 messages
            rows = list(reversed(c.execute(base + " ORDER BY id DESC LIMIT 500", args).fetchall()))
        seen = c.execute("SELECT last_seen FROM users WHERE id=?", (other,)).fetchone()
    return ok(messages=[msg_dict(r, uid) for r in rows],
              peer={"online": is_online(other), "last_seen": seen["last_seen"] if seen else None})

@app.post("/api/messages")
@verified_required
def send_message():
    uid = request.user["id"]
    d = request.get_json(silent=True) or {}
    try:
        other = int(d.get("receiver_id"))
    except (TypeError, ValueError):
        return fail("Invalid recipient.")
    body = str(d.get("body", "")).strip()
    if not body or len(body) > 2000:
        return fail("Message must be between 1 and 2000 characters.")
    if not allowed(f"msg:{uid}", 60, 60):
        return fail("You are sending messages too fast.", 429)
    with db() as c:
        if not is_connected(c, uid, other):
            return fail("You can message only a connected student.", 403)
        ts = now()
        delivered = ts if is_online(other) else None
        mid = c.execute("INSERT INTO messages(sender_id,receiver_id,body,created_at,delivered_at) VALUES(?,?,?,?,?)",
                        (uid, other, body, ts, delivered)).lastrowid
    m = {"id": mid, "mine": True, "body": body, "created_at": ts, "status": "delivered" if delivered else "sent"}
    publish(other, "message", {"peer": uid, "message": {**m, "mine": False}})
    publish(uid, "message", {"peer": other, "message": m})      # keeps the sender's other tabs in sync
    return ok(message=m), 201

@app.post("/api/messages/<int:other>/read")
@verified_required
def read_messages(other):
    uid = request.user["id"]
    with db() as c:
        if not is_connected(c, uid, other):
            return fail("You can message only a connected student.", 403)
        top = c.execute("""SELECT MAX(id) AS top FROM messages WHERE sender_id=? AND receiver_id=?
                           AND read_at IS NULL""", (other, uid)).fetchone()["top"]
        if top:
            ts = now()
            c.execute("""UPDATE messages SET read_at=?, delivered_at=COALESCE(delivered_at,?)
                         WHERE sender_id=? AND receiver_id=? AND read_at IS NULL AND id<=?""",
                      (ts, ts, other, uid, top))
    if top:
        publish(other, "read", {"peer": uid, "up_to": top})
        publish(uid, "read_self", {"peer": other})
    return ok(up_to=top)

@app.post("/api/typing")
@verified_required
def typing():
    uid = request.user["id"]
    d = request.get_json(silent=True) or {}
    try:
        other = int(d.get("receiver_id"))
    except (TypeError, ValueError):
        return fail("Invalid recipient.")
    if not allowed(f"typing:{uid}", 120, 60):
        return ok()
    with db() as c:
        if not is_connected(c, uid, other):
            return fail("You can message only a connected student.", 403)
    publish(other, "typing", {"peer": uid, "typing": bool(d.get("typing"))})
    return ok()

# --------------------------------------------------------------- password reset
def send_reset(to, link):
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        log.warning("PASSWORD RESET LINK for %s (SMTP not configured): %s", to, link)
        return
    msg = EmailMessage()
    msg["Subject"], msg["To"] = "Campus X password reset", to
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "no-reply@campusx.local"
    msg.set_content(f"Use this link to reset your Campus X password (valid for 30 minutes):\n\n{link}\n\n"
                    "If you did not request this, you can ignore this email.")
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
    except Exception:
        log.exception("Could not send reset email")

@app.post("/api/forgot-password")
def forgot_password():
    d = request.get_json(silent=True) or {}
    ident = clean(d.get("email"), 120).lower()
    generic = ok(message="If this email is registered, a password reset link will be sent.")
    if not allowed(f"forgot:{request.remote_addr}", 5, 3600):
        return fail("Too many requests. Please try again later.", 429)
    with db() as c:
        u = c.execute("SELECT id, email FROM users WHERE email=?", (ident,)).fetchone()
        if not u:
            return generic
        token = secrets.token_urlsafe(32)
        c.execute("UPDATE password_resets SET used=1 WHERE user_id=? AND used=0", (u["id"],))
        c.execute("INSERT INTO password_resets(user_id,token_hash,expires_at) VALUES(?,?,?)",
                  (u["id"], hashlib.sha256(token.encode()).hexdigest(),
                   (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(timespec="seconds")))
    base = os.getenv("PUBLIC_URL", "").strip().rstrip("/") or request.host_url.rstrip("/")
    link = f"{base}/reset-password.html?token={token}"
    if "@" in u["email"]:
        send_reset(u["email"], link)
    else:
        log.warning("User %s signed up with a college ID, not an email; reset link: %s", u["email"], link)
    return generic

@app.post("/api/reset-password")
def reset_password():
    d = request.get_json(silent=True) or {}
    token, pw = str(d.get("token", "")), str(d.get("password", ""))
    if not allowed(f"reset:{request.remote_addr}", 10, 3600):
        return fail("Too many attempts. Please try again later.", 429)
    if len(pw) < 6 or len(pw) > 128:
        return fail("Password must contain at least 6 characters.")
    th = hashlib.sha256(token.encode()).hexdigest()
    with db() as c:
        r = c.execute("SELECT id, user_id, expires_at, used FROM password_resets WHERE token_hash=?", (th,)).fetchone()
        if not r or r["used"] or datetime.fromisoformat(r["expires_at"]) < datetime.now(timezone.utc):
            return fail("This reset link is invalid or has expired.", 400)
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), r["user_id"]))
        c.execute("UPDATE password_resets SET used=1 WHERE id=?", (r["id"],))
    return ok(message="Password updated. You can now log in.")

# --------------------------------------------------------------- serve frontend
@app.get("/")
def root():
    return redirect("/login.html")

@app.get("/<path:filename>")
def frontend(filename):
    if filename.startswith(("api/", "media/")) or filename.rsplit(".", 1)[-1].lower() not in STATIC_EXT:
        abort(404)
    return send_from_directory(FRONTEND_DIR, filename)

init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    log.info("CampusX running at http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", threaded=True)
