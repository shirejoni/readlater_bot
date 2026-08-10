/* Read-later dashboard: lightweight fetch() actions, no page reload for most
 * item actions. Structural changes (save link, playlists) reload the page. */
const STATUS = {
  unread: "⬜ خوانده نشده",
  in_progress: "🔁 در حال خواندن",
  done: "✅ خوانده شد",
};

let _toastTimer;

const P = window.APP_PREFIX || "";

function flash(msg, kind) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "";
  if (kind) el.classList.add(kind);
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

async function post(path, payload) {
  let resp;
  try {
    resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
  } catch (_) {
    return { ok: false, data: { error: "خطا در اتصال به سرور." } };
  }
  let data = {};
  try { data = await resp.json(); } catch (_) {}
  return { ok: resp.ok, data };
}

function dataError(data, fallback) {
  return data && data.error ? data.error : fallback;
}

/* ---------- save link ---------- */
const saveBtn = document.getElementById("saveBtn");
const saveModal = document.getElementById("saveModal");
const saveUrls = document.getElementById("saveUrls");
const savePl = document.getElementById("savePl");
const saveGo = document.getElementById("saveGo");
const saveCancel = document.getElementById("saveCancel");
const saveStatus = document.getElementById("saveStatus");

function openSave() {
  if (saveUrls) saveUrls.value = "";
  if (saveStatus) { saveStatus.textContent = ""; saveStatus.classList.remove("err"); }
  saveModal.classList.remove("hidden");
  if (saveUrls) saveUrls.focus();
}
saveBtn.addEventListener("click", openSave);
saveCancel.addEventListener("click", () => saveModal.classList.add("hidden"));
saveModal.addEventListener("click", (e) => {
  if (e.target === saveModal) saveModal.classList.add("hidden");
});
saveStatus && saveStatus.closest(".modal-box").addEventListener("keydown", (e) => {
  if (e.key === "Escape") saveModal.classList.add("hidden");
});

saveGo.addEventListener("click", async () => {
  const urls = (saveUrls && saveUrls.value || "").trim();
  if (!urls) {
    saveStatus.textContent = "لینکی وارد نشده است.";
    saveStatus.classList.add("err");
    return;
  }
  saveGo.disabled = true;
  saveStatus.textContent = "در حال دریافت اطلاعات…";
  saveStatus.classList.remove("err");
  const playlist_id = savePl && savePl.value ? Number(savePl.value) : null;
  const { ok, data } = await post(`${P}/api/items`, { urls, playlist_id });
  saveGo.disabled = false;
  if (ok) {
    location.reload();
  } else {
    saveStatus.textContent = dataError(data, "خطایی رخ داد.");
    saveStatus.classList.add("err");
  }
});

/* ---------- playlist actions ---------- */
document.querySelectorAll(".delpl").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const pid = btn.dataset.pid;
    if (!confirm("این پلی‌لیست و همه‌ی لینک‌هایش حذف شود؟")) return;
    const { ok, data } = await post(`${P}/api/playlists/${pid}/delete`);
    if (ok) location.reload();
    else flash(dataError(data, "خطا در حذف پلی‌لیست."), "err");
  });
});

const newplForm = document.getElementById("newplForm");
const newplName = document.getElementById("newplName");
newplForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = (newplName.value || "").trim();
  if (!name) return;
  const { ok, data } = await post(`${P}/api/playlists`, { name });
  if (ok) location.reload();
  else flash(dataError(data, "خطا در ساخت پلی‌لیست."), "err");
});

/* ---------- item actions ---------- */
document.querySelectorAll(".item").forEach((card) => {
  const id = card.dataset.id;

  card.querySelectorAll(".status-group button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const s = btn.dataset.s;
      const chip = card.querySelector(".status");
      const prev = { st: chip.dataset.status, text: chip.textContent };
      chip.dataset.status = s;
      chip.className = `status st-${s}`;
      chip.textContent = STATUS[s] || s;
      card.querySelectorAll(".status-group button").forEach((b) =>
        b.classList.toggle("on", b.dataset.s === s));
      const { ok, data } = await post(`${P}/api/items/${id}/status`, { status: s });
      if (!ok) {
        chip.dataset.status = prev.st;
        chip.className = `status st-${prev.st}`;
        chip.textContent = prev.text;
        card.querySelectorAll(".status-group button").forEach((b) =>
          b.classList.toggle("on", b.dataset.s === prev.st));
        flash(dataError(data, "خطا در تغییر وضعیت."), "err");
      }
    });
  });

  const pinBtn = card.querySelector(".pin");
  pinBtn.addEventListener("click", async () => {
    const { ok, data } = await post(`${P}/api/items/${id}/pin`);
    if (ok) location.reload();      // order changes: pinned float to top
    else flash(dataError(data, "خطا در پین."), "err");
  });

  const delBtn = card.querySelector(".del");
  delBtn.addEventListener("click", async () => {
    if (!confirm("این لینک حذف شود؟")) return;
    const { ok, data } = await post(`${P}/api/items/${id}/delete`);
    if (ok) {
      card.style.opacity = "0";
      setTimeout(() => card.remove(), 200);
    } else {
      flash(dataError(data, "خطا در حذف."), "err");
    }
  });
});

/* ---------- comments ---------- */
document.querySelectorAll(".cmt-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = form.querySelector("input");
    const text = (input.value || "").trim();
    if (!text) return;
    const kind = form.dataset.kind;
    const id = form.dataset.id;
    const { ok, data } = await post(`${P}/api/${kind}/${id}/comment`, { text });
    if (ok) location.reload();
    else flash(dataError(data, "خطا در ثبت نظر."), "err");
  });
});