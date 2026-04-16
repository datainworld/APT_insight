// Chainlit 로고를 시스템 소개 텍스트로 교체
(function () {
  function replaceLogo() {
    // 이미 교체했으면 무시
    if (document.getElementById("apt-insight-logo")) return;

    // Chainlit 로고 이미지 찾기
    const imgs = document.querySelectorAll("img");
    let logoImg = null;
    for (const img of imgs) {
      if (img.src && (img.src.includes("logo") || img.alt === "logo")) {
        logoImg = img;
        break;
      }
    }

    if (!logoImg) return;

    // 로고를 텍스트 블록으로 교체
    const container = document.createElement("div");
    container.id = "apt-insight-logo";
    container.style.textAlign = "center";
    container.style.padding = "20px 0";

    container.innerHTML =
      '<div style="font-size:32px;font-weight:700;color:#e0e0e0;margin-bottom:12px;">APT Insight</div>' +
      '<div style="font-size:16px;color:#999;margin-bottom:8px;">수도권 아파트 실거래가 / 매물 / 뉴스 종합 분석</div>' +
      '<div style="font-size:14px;color:#777;">아래 예시를 클릭하거나 질문을 입력하세요</div>';

    logoImg.parentNode.replaceChild(container, logoImg);
  }

  const observer = new MutationObserver(replaceLogo);
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(replaceLogo, 1000);
  setTimeout(replaceLogo, 3000);
})();
