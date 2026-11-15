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

// ---- Examples: same reference voice, two generated outputs ----
const REF_URL = "/assets/reference/muni-shri-pranamya-sagar-ji-pravchan-ansh_320kbps.mp3";
const EXAMPLES = ["clone_4b9e1f8c", "clone_edefe70d"];

EXAMPLES.forEach(async (name, i) => {
  const box = document.createElement("div");
  box.className = "example";
  const label = document.createElement("strong");
  label.textContent = `Example ${i + 1}`;
  const text = document.createElement("p");
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = `/assets/outputs/${name}.wav`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "Try this example";
  box.append(label, text, audio, btn);
  $("exList").append(box);

  try {
    text.textContent = (await (await fetch(`/assets/outputs/${name}.txt`)).text()).trim();
  } catch (e) { text.textContent = ""; }

  // Load the example's reference voice and text into the form.
  btn.addEventListener("click", async () => {
    try {
      const blob = await (await fetch(REF_URL)).blob();
      const file = new File([blob], "reference.mp3", { type: blob.type || "audio/mpeg" });
      const dt = new DataTransfer();
      dt.items.add(file);
      $("reference").files = dt.files;
      $("reference").dispatchEvent(new Event("change"));
      $("text").value = text.textContent;
      form.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      showMessage("Could not load the example reference.", true);
    }
  });
});
