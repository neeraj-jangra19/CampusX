# Campus X: backend + wired frontend

Your original frontend never called a server (only the admin pages did), so a backend alone
could not make it work. This package contains **a complete backend and your frontend wired to it**.
The design and layout of every page is unchanged.

## 1. Run it (3 minutes)

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows      (macOS/Linux:  source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Windows      (macOS/Linux:  cp .env.example .env)
python app.py
```

Open **http://127.0.0.1:5000** (the backend also serves the frontend, so one command runs everything).

| Who | Where | Login |
|---|---|---|
| Student | `/signup.html`, `/login.html` | sign up with your own account |
| Admin | `/admin_login.html` | `admin@campusx.local` / `ChangeMe123!` (change it in `.env`) |

### Try the whole flow
1. **Student A**: sign up, then upload a college ID (PNG / JPG / PDF, under 5 MB).
2. **Admin** (use another browser or a private window): log in, press *Review*, *Approve*.
3. **Student A**: log in. You go to profile setup (3 photos, age 18+, 3 answers), then the dashboard.
4. Repeat for **Student B** in another browser. Each student likes the other; the second like says
   *"It's a match"* and chat opens. Messages arrive automatically every 4 seconds.

Want people on the dashboard straight away?
```bash
python seed_demo.py --likes your@email   # adds 6 demo students (password Demo@123) who already liked you
python seed_demo.py --reset              # removes them again
```

## 2. What is in the backend

* **Flask + SQLite**, no extra services. Database file `campusx_v2.db` and `uploads/` appear on first run.
* **WhatsApp-style chat**: messages, ticks, typing and online status are pushed live (Server-Sent Events, no extra library): instant delivery, time on every bubble, "Today / Yesterday" separators, ✓ sent, ✓✓ delivered, blue ✓✓ read, "typing…", green online dot, "last seen", unread counters (list, bottom nav and tab title) and a pop-up when a message or match arrives while you are elsewhere. A database from the earlier version is upgraded automatically on start.
* Student flow: sign up (email **or** college ID, password 6+ chars) -> KYC -> admin approval -> profile -> discover -> like / pass -> match -> chat.
* Recommendation order: `Score = min( Jaccard(hobbies+bio words) + 0.12 if same course + 0.05 if same year , 1 )`.
* Password reset: `POST /api/forgot-password` + new page `reset-password.html`. Without SMTP settings, the reset
  link is **printed in the server console** (fill `SMTP_*` in `.env` to send real emails).
* Report button saves to the database; reported students disappear from that user's feed (`GET /api/admin/reports`).

### Security built in
Hashed passwords, HTTP-only SameSite cookies, file type checked by **content** (not just extension), size limits,
random stored file names, ID documents visible **only to admins**, profile photos only to logged-in verified students,
chat only between matched students, email/college ID is **never** sent to other students, Origin check against CSRF,
rate limiting on login/signup/reset/messages, same college ID cannot be used on two accounts, SQL placeholders everywhere.

### Main API
| Method | Endpoint | Who |
|---|---|---|
| POST | `/api/signup`, `/api/login`, `/api/logout` | public / student |
| GET | `/api/me` | student |
| POST, GET | `/api/kyc`, `/api/kyc/status` | student |
| POST | `/api/profile` (multipart, `photo0..2`) | verified |
| GET | `/api/discover`, `/api/connections`, `/api/profile/<id>` | verified |
| POST | `/api/like`, `/api/pass`, `/api/report` | verified |
| GET, POST | `/api/messages/<id>?after=`, `/api/messages` | verified + matched |
| POST | `/api/messages/<id>/read`, `/api/typing` | verified + matched |
| GET | `/api/stream` (live events) | verified |
| POST | `/api/forgot-password`, `/api/reset-password` | public |
| POST, GET | `/api/admin/login`, `/logout`, `/me`, `/stats`, `/kyc`, `/kyc/document/<kyc_id>`, `/kyc/<user_id>/approve`, `/kyc/<user_id>/reject`, `/reports` | admin |

## 3. Changes to your frontend files
* **New:** `api.js` (shared fetch helper), `reset-password.html/.js`, `privacy.html` (the signup page linked to it but it did not exist).
* **Rewritten against the API** (same look): `signup.js`, `login.js`, `forgot-password.js`, `profile.js`, `dashboard.js`, `chat.js`.
  Demo data and `localStorage` fake logic were removed.
* **`kyc.html`**: the submit now uploads to `/api/kyc`; reopening the page shows *pending*, and a rejected user sees the reason.
* **`admin.html`, `admin_login.html`**: send the login cookie, use the right API address, redirect to the login page when the session
  expires, show PDF IDs as a link, and the Logout button now ends the server session.
* **`dashboard.css`**: small addition so real photos fit the round avatars.

### Bugs in the original frontend that I fixed
* `profile.js` referenced `question4`, `promptQuestion` and `promptAnswer`, which do not exist in `profile.html`, so the script crashed
  on load and **"Create My Profile" did nothing**.
* After a failed validation the profile button stayed disabled on "Creating Profile...".
* Admin approve/reject URLs use the **user id** while the document URL uses the **KYC id**; the backend matches this exactly.
* Admin pages sent no cookies, so a login session could never work across ports.

## 4. Tests (I ran both; all passed)
```bash
cd backend
python tests/test_api.py      # 105 API checks, uses a temporary database
```
I also drove the real pages in Chromium (signup, KYC, admin approve/reject, profile, like/match, chat, edit profile,
password reset, logout, access control): **45/45 checks passed** (including instant delivery, read receipts and typing between two live browsers), with no JavaScript errors. The app was tested both ways:
everything on port 5000, and frontend on port 5500 with the API on 5000.

## 5. Settings (`backend/.env`)
`SECRET_KEY` (auto-generated if empty), `PORT`, `ADMIN_EMAIL/ADMIN_PASSWORD`, `COOKIE_SECURE=true` (when using HTTPS),
`FRONTEND_ORIGINS` (only if you serve the frontend from another port), `PUBLIC_URL`, `SMTP_*`.
Use `http://127.0.0.1:...` or `http://localhost:...` consistently (do not mix them in one session).

## 6. Before putting it on the internet
Use HTTPS with `COOKIE_SECURE=true`, set a strong `ADMIN_PASSWORD`, run with `gunicorn app:app` (not `python app.py`),
configure SMTP, and back up `campusx_v2.db` and `uploads/`. Live chat keeps one open connection per browser tab in memory, so run **one** worker with threads: `gunicorn app:app -k gthread --threads 100 -w 1` (for many thousands of users, move the live events to Redis). A browser allows about 6 open connections per site over HTTP/1.1, so avoid opening more than ~5 tabs of the app at once.
Rate-limit counters live in memory (they reset on restart).

## 7. Troubleshooting
* *The page jumps back to Home by itself*: something reloaded the page. The most common cause is the **VS Code "Live Server"** extension: the database file is inside the project folder, so every message changes a watched file and Live Server refreshes the browser. Best fix: do not use Live Server; open **http://127.0.0.1:5000** (the Flask server already serves the pages). The included `.vscode/settings.json` also tells Live Server to ignore the `backend` folder. Even if a reload happens, the dashboard now returns you to the same screen (the address shows `#home`, `#chat`, `#chat/<id>` or `#profile`).
* *"Unable to reach the Campus X server"*: the backend is not running, or the page was opened as a file (`file:///...`). Use `http://127.0.0.1:5000`.
* *Redirected to login again and again*: you mixed `localhost` and `127.0.0.1`, or the browser blocks cookies.
* *Photos show an emoji*: the photo URL needs a logged-in, verified session; log in again.
* *Forgot the admin password*: change `ADMIN_PASSWORD` in `.env` and restart; it is updated automatically.
#   C a m p u s X  
 