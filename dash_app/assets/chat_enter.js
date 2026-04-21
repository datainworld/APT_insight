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

// ESC 키: 채팅 패널 크기를 한 단계 축소 (maximized → expanded → compact → minimized).
// chat-esc-trigger store 의 data 를 증가시켜 Dash 쪽 size-transition 콜백을 트리거.
(function () {
  function bumpEscTrigger() {
    // Dash Stores are not directly accessible from DOM; use dash_clientside if available.
    if (!window.dash_clientside || !window.dash_clientside.set_props) return;
    try {
      const current =
        (window.dash_clientside.callback_context &&
         window.dash_clientside.callback_context.states &&
         window.dash_clientside.callback_context.states["chat-esc-trigger.data"]) || 0;
      window.dash_clientside.set_props("chat-esc-trigger", {
        data: (typeof current === "number" ? current : 0) + 1,
      });
    } catch (err) {
      // swallow — ESC 키 보조 기능이라 실패해도 치명적 아님
    }
  }
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    const panel = document.getElementById("chat-panel");
    if (!panel) return;
    const size = panel.getAttribute("data-size");
    if (!size || size === "minimized") return;
    e.preventDefault();
    bumpEscTrigger();
  });
})();
