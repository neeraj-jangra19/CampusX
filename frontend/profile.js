/* Campus X - profile setup / edit */
(function () {
  const $ = (id) => document.getElementById(id);
  const editMode = new URLSearchParams(location.search).get("edit") === "true";
  const photoBoxes = Array.from(document.querySelectorAll(".photo-box"));
  const submitButton = $("submitProfile");
  const originalButton = submitButton.innerHTML;

  /* PHOTO UPLOADS (preview + checks) */
  photoBoxes.forEach((box) => {
    const input = box.querySelector(".photo-input");
    const preview = box.querySelector(".photo-preview");
    const placeholder = box.querySelector(".photo-placeholder");
    input.addEventListener("change", function () {
      const file = this.files[0];
      if (!file) return;
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        alert("Please upload a JPG, PNG or WEBP image."); this.value = ""; return;
      }
      if (file.size > 5 * 1024 * 1024) { alert("Each photo must be less than 5MB."); this.value = ""; return; }
      const reader = new FileReader();
      reader.onload = (e) => { preview.src = e.target.result; preview.style.display = "block"; placeholder.style.display = "none"; };
      reader.readAsDataURL(file);
    });
  });

  /* CHARACTER COUNTERS */
  [["bio", "bioCount"], ["question1", "question1Count"], ["question2", "question2Count"], ["question3", "question3Count"]]
    .forEach(([i, c]) => {
      const input = $(i), counter = $(c);
      if (input && counter) input.addEventListener("input", function () { counter.textContent = this.value.length; });
    });

  /* PREFILL (edit mode) */
  function prefill(profile) {
    const r = profile.raw;
    const map = { nickname: r.nickname, age: r.age, gender: r.gender, course: r.course, year: r.year, height: r.height,
      hometown: r.hometown, hosteller: r.hosteller, religion: r.religion, hobbies: r.hobbies, bio: r.bio,
      question1: r.question1, question2: r.question2, question3: r.question3 };
    Object.keys(map).forEach((id) => {
      const el = $(id);
      if (el) { el.value = map[id] == null ? "" : map[id]; el.dispatchEvent(new Event("input")); }
    });
    photoBoxes.forEach((box, i) => {
      if (!profile.photos[i]) return;
      const preview = box.querySelector(".photo-preview");
      preview.src = cx.url(profile.photos[i]);
      preview.style.display = "block";
      box.querySelector(".photo-placeholder").style.display = "none";
      box.dataset.existing = "1";
    });
    submitButton.innerHTML = originalButton.replace("Create My Profile", "Save Changes");
  }

  async function init() {
    try {
      const d = await cx.request("/api/me");
      if (d.user.status !== "verified") { window.location.href = "login.html"; return; }
      if (d.profile) {
        if (!editMode) { window.location.href = "dashboard.html"; return; }
        prefill(d.profile);
      }
    } catch (e) {
      window.location.href = "login.html";
    }
  }

  submitButton.addEventListener("click", async function () {
    const v = (id) => ($(id) ? $(id).value.trim() : "");
    const nickname = v("nickname"), age = v("age"), gender = v("gender"), course = v("course"),
      year = v("year"), hosteller = v("hosteller");
    const q1 = v("question1"), q2 = v("question2"), q3 = v("question3");

    const haveAll = photoBoxes.every((box) => box.querySelector(".photo-input").files.length > 0 || box.dataset.existing === "1");
    if (!haveAll) { alert("Please upload all 3 profile photos."); return; }
    if (!nickname) { alert("Please enter your nickname."); return; }
    if (!age || Number(age) < 18) { alert("You must be 18 or older."); return; }
    if (!gender) { alert("Please select your gender."); return; }
    if (!course) { alert("Please enter your branch/course."); return; }
    if (!year) { alert("Please select your year."); return; }
    if (!hosteller) { alert("Please select your living status."); return; }
    if (!q1) { alert("Please answer question 1."); return; }
    if (!q2) { alert("Please answer question 2."); return; }
    if (!q3) { alert("Please answer question 3."); return; }

    const fd = new FormData();
    ["nickname", "age", "gender", "course", "year", "height", "hometown", "hosteller", "religion", "hobbies", "bio",
      "question1", "question2", "question3"].forEach((id) => fd.append(id, v(id)));
    photoBoxes.forEach((box, i) => {
      const f = box.querySelector(".photo-input").files[0];
      if (f) fd.append("photo" + i, f);
    });

    submitButton.disabled = true;
    submitButton.innerHTML = "<span>Saving Profile...</span>";
    try {
      const d = await cx.request("/api/profile", { form: fd });
      window.location.href = d.next || "dashboard.html";
    } catch (err) {
      alert(err.message);
      if (err.status === 401 || err.status === 403) { window.location.href = "login.html"; return; }
      submitButton.disabled = false;
      submitButton.innerHTML = originalButton;
    }
  });

  init();
})();
