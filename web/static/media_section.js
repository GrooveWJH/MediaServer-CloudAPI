const DEFAULT_POLL_INTERVAL = 2000;
const MAX_IMAGE_RETRIES = 3;
const RETRY_DELAY_MS = 800;

function attachImageRetry(img) {
  img.addEventListener("error", () => {
    const retries = parseInt(img.dataset.retries || "0", 10);
    if (retries >= MAX_IMAGE_RETRIES) return;
    img.dataset.retries = String(retries + 1);
    const url = new URL(img.src, window.location.origin);
    url.searchParams.set("_ts", String(Date.now()));
    setTimeout(() => {
      img.src = url.toString();
    }, RETRY_DELAY_MS);
  });
}

function normalizeBase(base) {
  if (!base) return "";
  return base.endsWith("/") ? base.slice(0, -1) : base;
}

function buildPreviewUrl(apiBase, objectKey) {
  return `${apiBase}/preview?object_key=${encodeURIComponent(objectKey)}`;
}

function buildCard(item, apiBase) {
  if (!item.object_key) return null;
  const card = document.createElement("article");
  card.className = "media-card";
  card.dataset.recordId = item.id;
  card.innerHTML = `
    <div class="media-preview">
      <img src="${buildPreviewUrl(apiBase, item.object_key)}" alt="${item.file_name || item.object_key}" loading="lazy" />
    </div>
    <div class="media-meta"><strong>名称：</strong>${item.file_name || "-"}</div>
    <div class="media-meta"><strong>时间：</strong>${item.created_at}</div>
    <div class="media-meta"><strong>Workspace：</strong>${item.workspace_id}</div>
    <div class="media-meta"><strong>Object Key：</strong>${item.object_key}</div>
    <div class="media-meta"><strong>Fingerprint：</strong>${item.fingerprint || "-"}</div>
    <div class="media-actions">
      <button type="button" data-delete="1" data-record-id="${item.id}" data-object-key="${item.object_key}">删除</button>
    </div>
  `;
  const img = card.querySelector("img");
  if (img) attachImageRetry(img);
  return card;
}

async function pollNew(state) {
  const { apiBase, grid, emptyState } = state;
  try {
    const res = await fetch(`${apiBase}/api/media?since_id=${state.lastId}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.items || !data.items.length) return;
    data.items.forEach((item) => {
      if (item.id > state.lastId) state.lastId = item.id;
      const card = buildCard(item, apiBase);
      if (card) grid.prepend(card);
    });
    if (emptyState) emptyState.classList.add("hidden");
  } catch (_err) {
    // ignore polling errors
  }
}

async function handleDelete(state, btn) {
  const recordId = btn.dataset.recordId;
  const objectKey = btn.dataset.objectKey;
  if (!recordId || !objectKey) return;
  const form = new URLSearchParams();
  form.set("record_id", recordId);
  form.set("object_key", objectKey);
  const res = await fetch(`${state.apiBase}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  if (!res.ok) return;
  const card = btn.closest(".media-card");
  if (card) card.remove();
  if (state.grid && state.grid.children.length === 0 && state.emptyState) {
    state.emptyState.classList.remove("hidden");
  }
}

export function initMediaSection(options) {
  const root = typeof options.root === "string" ? document.querySelector(options.root) : options.root;
  if (!root) {
    throw new Error("media_section: root element not found");
  }
  const apiBase = normalizeBase(options.apiBase);
  const pollInterval = options.pollInterval || DEFAULT_POLL_INTERVAL;

  const grid = root.querySelector(".media-grid");
  if (!grid) {
    throw new Error("media_section: .media-grid element not found");
  }
  const emptyState = root.querySelector(".media-empty");
  const lastId = parseInt(root.dataset.lastId || "0", 10);

  const state = { apiBase, grid, emptyState, lastId };

  root.querySelectorAll(".media-preview img").forEach(attachImageRetry);

  root.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-delete]");
    if (btn) {
      handleDelete(state, btn);
    }
  });

  setInterval(() => pollNew(state), pollInterval);
  return state;
}
