// Progressive enhancement only: every page works without this file.
document.addEventListener("submit", (e) => {
  const f = e.target;
  const danger = e.submitter && e.submitter.classList.contains("danger");
  if (danger && !confirm("Are you sure?")) { e.preventDefault(); return; }
  if (f.dataset.busy) {
    f.classList.add("busy");
    const b = f.querySelector("button");
    if (b) b.textContent = f.dataset.busy;
  }
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
