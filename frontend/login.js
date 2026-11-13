/* Campus X - login */
const passwordInput = document.getElementById("password");
const passwordToggle = document.getElementById("passwordToggle");
const eyeIcon = document.getElementById("eyeIcon");
passwordToggle.addEventListener("click", function () {
  const show = passwordInput.type === "password";
  passwordInput.type = show ? "text" : "password";
  passwordToggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
  eyeIcon.innerHTML = show
    ? `<path d="M3 3l18 18"></path><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"></path><path d="M9.9 5.1A10.5 10.5 0 0 1 12 5 c6.5 0 10 7 10 7 a18 18 0 0 1-3.2 4.1"></path><path d="M6.2 6.2C3.5 8.3 2 12 2 12 s3.5 7 10 7 c1.7 0 3.2-.4 4.5-1"></path>`
    : `<path d="M2 12s3.5-7 10-7 10 7 10 7 -3.5 7-10 7 S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle>`;
});

const rememberCheckbox = document.getElementById("remember");
rememberCheckbox.addEventListener("change", function () {
  if (this.checked) localStorage.setItem("campusxRemember", "true");
  else { localStorage.removeItem("campusxRemember"); localStorage.removeItem("campusxRememberEmail"); }
});
window.addEventListener("DOMContentLoaded", function () {
  const saved = localStorage.getItem("campusxRememberEmail");
  if (saved && localStorage.getItem("campusxRemember") === "true") {
    document.getElementById("email").value = saved;
    rememberCheckbox.checked = true;
  }
});

const loginForm = document.getElementById("loginForm");
const loginButton = document.getElementById("loginButton");
loginForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  if (!email) { alert("Please enter your Email or College ID."); return; }
  if (!password) { alert("Please enter your password."); return; }
  if (password.length < 6) { alert("Password must be at least 6 characters."); return; }

  if (rememberCheckbox.checked) {
    localStorage.setItem("campusxRemember", "true");
    localStorage.setItem("campusxRememberEmail", email);
  } else {
    localStorage.removeItem("campusxRemember");
    localStorage.removeItem("campusxRememberEmail");
  }

  const original = loginButton.innerHTML;
  loginButton.disabled = true;
  loginButton.innerHTML = "<span>Logging In...</span>";
  try {
    const data = await cx.request("/api/login", { json: { email, password } });
    if (data.next) {
      if (data.message) alert(data.message);
      window.location.href = data.next;
    } else {
      alert(data.message || "Your account is not active yet.");
    }
  } catch (err) {
    alert(err.message);
  } finally {
    loginButton.disabled = false;
    loginButton.innerHTML = original;
  }
});
