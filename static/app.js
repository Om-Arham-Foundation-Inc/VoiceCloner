const $ = (id) => document.getElementById(id);
const form = $("form");
const statusEl = $("status");
const message = $("message");

function showMessage(text, isError) {
  message.hidden = !text;
  message.textContent = text || "";
  message.classList.toggle("error", !!isError);
}

// Poll until the voice model has finished loading.
async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    const s = await res.json();
    if (s.error) {
      statusEl.className = "status error";
      statusEl.textContent = s.error;
      return;
    }
    if (s.ready) {
      statusEl.className = "status ready";
      statusEl.textContent = "Voice model ready";
      return;
    }
  } catch (e) { /* server not reachable yet */ }
  setTimeout(checkStatus, 2000);
}
checkStatus();

$("reference").addEventListener("change", (e) => {
  const file = e.target.files[0];
  const player = $("refPlayer");
  if (!file) { player.hidden = true; return; }
  player.src = URL.createObjectURL(file);
  player.hidden = false;
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = $("go");
  const data = new FormData();
  data.append("reference", $("reference").files[0]);
  data.append("text", $("text").value);
  data.append("mode", $("mode").value);
  data.append("transcript", $("transcript").value);

  button.disabled = true;
  button.textContent = "Cloning… this can take a minute";
  showMessage("");
  $("result").hidden = true;

  try {
    const res = await fetch("/api/clone", { method: "POST", body: data });
    const out = await res.json();
    if (!res.ok) throw new Error(out.error || "Request failed");

    $("player").src = out.url;
    $("download").href = out.url;
    $("meta").textContent =
      `${out.duration}s of audio. Reference: ${out.reference_seconds}s, detected language "${out.language}". ` +
      `Heard as: ${out.transcript}`;
    $("result").hidden = false;
    $("player").play().catch(() => {});
  } catch (err) {
    showMessage(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Clone voice";
  }
});
