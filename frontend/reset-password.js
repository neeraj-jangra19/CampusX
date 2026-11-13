const resetForm = document.getElementById("resetForm");
const message = document.getElementById("message");
const token = new URLSearchParams(location.search).get("token") || "";
function showMessage(text, type) {
  message.textContent = text;
  message.style.color = type === "success" ? "#7cffb2" : "#ff7c8f";
}
if (!token) showMessage("This reset link is missing its token. Request a new one.", "error");
resetForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  const password = document.getElementById("password").value;
  if (password.length < 6) { showMessage("Password must contain at least 6 characters.", "error"); return; }
  if (password !== document.getElementById("confirm").value) { showMessage("Passwords do not match.", "error"); return; }
  const btn = resetForm.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const data = await cx.request("/api/reset-password", { json: { token, password } });
    showMessage(data.message, "success");
    setTimeout(() => { location.href = "login.html"; }, 1500);
  } catch (err) {
    showMessage(err.message, "error");
    btn.disabled = false;
  }
});
