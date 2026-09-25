// Copies the Cookie header a browser sends to music.youtube.com (what Music Assistant's
// YouTube Music provider asks for). Nothing leaves the browser: it only goes to the clipboard.
const status = (html) => { document.getElementById("status").innerHTML = html; };

document.getElementById("copy").addEventListener("click", async () => {
  try {
    // Auth cookies (SAPISID, __Secure-3PAPISID, ...) live on .youtube.com, so query the domain;
    // the host permission for *.youtube.com is what lets the extension read them.
    const cookies = (await chrome.cookies.getAll({ domain: "youtube.com" }))
      .filter((c) => c.domain === ".youtube.com" || c.domain === "youtube.com" || c.domain.endsWith("music.youtube.com"));
    const signedIn = cookies.some((c) => c.name === "SAPISID" || c.name === "__Secure-3PAPISID");
    if (!signedIn) {
      status("Вы не вошли в YouTube Music в этом профиле Chrome. Откройте <b>music.youtube.com</b>, войдите в аккаунт с Premium и нажмите снова.");
      return;
    }
    const header = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    await navigator.clipboard.writeText(header);
    status(`Скопировано (${cookies.length} cookie). Теперь в терминале:<code>ssh -t root@home ytm-cookie</code>вставьте (Ctrl+V / правый клик) и нажмите Enter.`);
  } catch (e) {
    status("Ошибка: " + (e && e.message ? e.message : e));
  }
});
