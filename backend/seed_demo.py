"""Create 6 demo students so the dashboard has people to discover.

    python seed_demo.py                       # add the demo students
    python seed_demo.py --likes you@email     # also make them like YOUR account, so a Like from you is an instant match
    python seed_demo.py --reset               # remove the demo students again

Every demo account has the password  Demo@123  (login e.g. aarav@demo.campusx)."""
import argparse, json, secrets, struct, sys, zlib
from werkzeug.security import generate_password_hash
import app as A

DEMO = [
    ("Aarav", "Aarav Sharma", 21, "male", "CSE - AI & ML", "4", "5'10\"", "Delhi", "hosteller", "cricket, badminton, technology, music, movies",
     "Tech enthusiast who is always up for cricket, late-night conversations and discovering new places around campus.",
     ["A spontaneous plan with good people.", "Classes, coffee and a long walk with friends.", "Try a hackathon."], (110, 80, 220)),
    ("Mehak", "Mehak Verma", 20, "female", "BBA", "3", "5'5\"", "Panipat", "hosteller", "photography, music, cafes, movies",
     "Creative, friendly and always looking for good conversations and fun campus plans.",
     ["Coffee and a good chat.", "Classes, cafes and a sunset walk.", "A new creative hobby."], (220, 90, 150)),
    ("Rohan", "Rohan Malik", 22, "male", "B.Tech CSE", "4", "6'0\"", "Rohtak", "day-scholar", "football, gaming, coding, music",
     "Developer by day, gamer by night. Always interested in building something useful.",
     ["A football match.", "Morning lectures, evening football.", "Build and ship a startup idea."], (60, 150, 200)),
    ("Simran", "Simran Kaur", 20, "female", "B.Com", "2", "5'4\"", "Ambala", "day-scholar", "dancing, travel, books, cafes",
     "Bookworm with a love for dance and weekend trips. Ask me for a book recommendation.",
     ["A road trip.", "Dance practice and chai.", "Learn a new dance form."], (230, 150, 60)),
    ("Kabir", "Kabir Singh", 23, "male", "MBA", "masters", "5'11\"", "Chandigarh", "hosteller", "cricket, startups, fitness, music",
     "MBA student, gym regular and chai enthusiast. Happy to talk startups or cricket.",
     ["Early morning workouts.", "Gym, classes and a late-night chai.", "Pitch at a startup event."], (70, 170, 110)),
    ("Ananya", "Ananya Gupta", 21, "female", "BCA", "3", "5'6\"", "Karnal", "hosteller", "painting, music, coding, movies",
     "Part-time coder, part-time artist. I like calm cafes and loud playlists.",
     ["An art jam session.", "Studio time, then coding.", "Paint a campus mural."], (160, 90, 220)),
]

def png(color, w=300, h=400):
    rows = []
    for y in range(h):
        k = 0.65 + 0.35 * y / h
        rows.append(b"\x00" + bytes(int(c * k) for c in color) * w)
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--likes", help="email / college ID of your own account")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    with A.db() as c:
        for r in c.execute("SELECT p.photos FROM profiles p JOIN users u ON u.id=p.user_id WHERE u.email LIKE '%@demo.campusx'").fetchall():
            for name in json.loads(r["photos"]):
                try: (A.PROFILE_DIR / name).unlink()
                except OSError: pass
        c.execute("DELETE FROM users WHERE email LIKE '%@demo.campusx'")
        if a.reset:
            print("Demo students removed."); return
        pw = generate_password_hash("Demo@123")
        ids = []
        for nick, full, age, gender, course, year, height, town, host, hobbies, bio, answers, color in DEMO:
            uid = c.execute("INSERT INTO users(full_name,email,password_hash,status,created_at) VALUES(?,?,?,'verified',?)",
                            (full, f"{nick.lower()}@demo.campusx", pw, A.now())).lastrowid
            photos = []
            for i in range(3):
                name = f"{secrets.token_hex(12)}.png"
                (A.PROFILE_DIR / name).write_bytes(png(tuple((v + i * 25) % 256 for v in color)))
                photos.append(name)
            c.execute("""INSERT INTO profiles(user_id,nickname,age,gender,course,year,height,hometown,hosteller,religion,
                         hobbies,bio,q1,q2,q3,photos,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'',?,?,?,?,?,?,?)""",
                      (uid, nick, age, gender, course, year, height, town, host, hobbies, bio, *answers, json.dumps(photos), A.now()))
            ids.append(uid)
        if a.likes:
            me = c.execute("SELECT id FROM users WHERE email=?", (a.likes.strip().lower(),)).fetchone()
            if not me:
                print(f"Account {a.likes} not found. Sign up first, then run the command again."); sys.exit(1)
            for uid in ids:
                c.execute("INSERT OR IGNORE INTO likes(from_user,to_user,created_at) VALUES(?,?,?)", (uid, me["id"], A.now()))
    print(f"Added {len(DEMO)} demo students (password: Demo@123)." + (f" They have all liked {a.likes}." if a.likes else ""))

if __name__ == "__main__":
    main()
