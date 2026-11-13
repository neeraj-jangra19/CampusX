/* Campus X - signup */
function setupPasswordToggle(inputId, buttonId, eyeId) {
  const input = document.getElementById(inputId);
  const button = document.getElementById(buttonId);
  const eye = document.getElementById(eyeId);
  const HIDDEN = `<path d="M2 12s3.5-7 10-7 10 7 10 7 -3.5 7-10 7 S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle>`;
  const SHOWN = `<path d="M3 3l18 18"></path><path d="M10.6 10.6 a2 2 0 0 0 2.8 2.8"></path><path d="M9.9 5.1 A10.5 10.5 0 0 1 12 5 c6.5 0 10 7 10 7 a18 18 0 0 1 -3.2 4.1"></path><path d="M6.2 6.2 C3.5 8.3 2 12 2 12 s3.5 7 10 7 c1.7 0 3.2-.4 4.5-1"></path>`;
  button.addEventListener("click", function () {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    eye.innerHTML = show ? SHOWN : HIDDEN;
  });
}
setupPasswordToggle("password", "passwordToggle", "passwordEye");
setupPasswordToggle("confirmPassword", "confirmPasswordToggle", "confirmPasswordEye");

const signupForm = document.getElementById("signupForm");
signupForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  const fullName = document.getElementById("fullName").value.trim();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const confirmPassword = document.getElementById("confirmPassword").value;
  const terms = document.getElementById("terms").checked;

  if (!fullName) { alert("Please enter your full name."); return; }
  if (!email) { alert("Please enter your Email or College ID."); return; }
  if (password.length < 6) { alert("Password must contain at least 6 characters."); return; }
  if (password !== confirmPassword) { alert("Passwords do not match."); return; }
  if (!terms) { alert("Please accept the Terms & Conditions and Privacy Policy."); return; }

  const btn = signupForm.querySelector('button[type="submit"]');
  const original = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = "<span>Creating account...</span>"; }
  try {
    const data = await cx.request("/api/signup", { json: { fullName, email, password } });
    window.location.href = data.next || "kyc.html";
  } catch (err) {
    alert(err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = original; }
  }
});
