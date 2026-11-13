const forgotPasswordForm = document.getElementById("forgotPasswordForm");
const emailInput = document.getElementById("email");
const message = document.getElementById("message");

function showMessage(text, type) {
  message.textContent = text;
  message.style.color = type === "success" ? "#7cffb2" : "#ff7c8f";
}

forgotPasswordForm.addEventListener("submit", async function (event) {
  event.preventDefault();
  const email = emailInput.value.trim();
  if (!email) { showMessage("Please enter your college email.", "error"); return; }
  if (!email.includes("@")) { showMessage("Please enter a valid email address.", "error"); return; }
  const btn = forgotPasswordForm.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const data = await cx.request("/api/forgot-password", { json: { email } });
    showMessage(data.message, "success");
    emailInput.value = "";
  } catch (err) {
    showMessage(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});
