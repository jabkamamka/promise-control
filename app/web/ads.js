/* Реклама в панели для бесплатного тарифа.
   Тариф спрашиваем у /api/v1/auth/me: free и аноним — показываем полосу, pro — нет. */

(async function () {
  const strip = document.getElementById("adStrip");
  if (!strip) return;

  // Пользователь может скрыть полосу до перезагрузки страницы.
  if (sessionStorage.getItem("adStripHidden") === "1") return;

  try {
    const me = await (await fetch("/api/v1/auth/me")).json();
    if (!me.ads) return;
    strip.hidden = false;
  } catch (error) {
    return; // API недоступен — не показываем сломанную полосу
  }

  document.getElementById("adClose").addEventListener("click", () => {
    strip.hidden = true;
    sessionStorage.setItem("adStripHidden", "1");
  });
})();
