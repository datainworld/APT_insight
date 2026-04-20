// Submit chat on Enter (without Shift).
// Global delegated listener so it survives Dash re-renders of the chat panel.
document.addEventListener("keydown", function (e) {
  if (e.key !== "Enter" || e.shiftKey) return;
  const target = e.target;
  if (!target || target.id !== "chat-input") return;
  e.preventDefault();
  const btn = document.getElementById("chat-send");
  if (btn) btn.click();
});
