const $ = (id) => document.getElementById(id);

const RECENT_KEY = "baixia.recent";
const ACTIVE_JOB_KEY = "baixia.activeJob";
const FAV_KEY = "baixia.favorites";
const OPTIONS_PREFIX = "baixia.options.";
const THEME_KEY = "baixia.theme";

function resolveTheme(pref) {
  if (pref === "dark") return "dark";
  if (pref === "light") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(pref, persist = false) {
  const choice = ["light", "dark", "system"].includes(pref) ? pref : "system";
  const theme = resolveTheme(choice);
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themePref = choice;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#141718" : "#ffffff";
  if (persist) localStorage.setItem(THEME_KEY, choice);
  document.querySelectorAll(".theme-btn").forEach((button) => {
    const active = button.dataset.themeChoice === choice;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || "system");
  document.querySelectorAll(".theme-btn").forEach((button) => {
    button.addEventListener("click", () => applyTheme(button.dataset.themeChoice, true));
  });
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if ((localStorage.getItem(THEME_KEY) || "system") === "system") applyTheme("system");
  };
  if (media.addEventListener) media.addEventListener("change", onChange);
  else if (media.addListener) media.addListener(onChange);
}

const state = {
  categories: [],
  tools: [],
  caps: {},
  activeCat: localStorage.getItem("baixia.cat") || "doc",
  activeTool: null,
  files: [],
  options: {},
  job: null,
  busy: false,
  pollTimer: null,
  pollFails: 0,
  search: "",
  recent: readRecent(),
  favorites: readFavorites(),
  fileUrls: [],
  modalReturnFocus: null,
  eventSource: null,
  videoProbeKey: null,
  videoProbeDuration: null,
  videoProbeUrl: null,
  gallery: null,
};

function readFavorites() {
  try {
    const value = JSON.parse(localStorage.getItem(FAV_KEY) || "[]");
    return Array.isArray(value) ? value.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function saveFavorites() {
  localStorage.setItem(FAV_KEY, JSON.stringify(state.favorites));
}

function extOf(name) {
  const match = String(name || "").toLowerCase().match(/\.[a-z0-9]+$/);
  return match ? match[0] : "";
}

const BROWSER_IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"]);
const PREVIEW_EXTS = new Set([
  ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif", ".bmp", ".tif", ".tiff",
  ".pdf", ".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi", ".ts",
]);

function isPreviewable(name) {
  return PREVIEW_EXTS.has(extOf(name));
}

function readRecent() {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(value) ? value.slice(0, 8) : [];
  } catch {
    return [];
  }
}

function saveRecent() {
  localStorage.setItem(RECENT_KEY, JSON.stringify(state.recent.slice(0, 8)));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

function timeAgo(ts) {
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}

function toolById(id) {
  return state.tools.find((tool) => tool.id === id);
}

function catById(id) {
  return state.categories.find((cat) => cat.id === id);
}

function subjectFor(tool) {
  if (tool.id === "images-to-pdf" || tool.id.startsWith("image-")) return "图片";
  if (tool.id === "gif-to-video") return "GIF";
  if (tool.id.startsWith("video-")) return "视频";
  if (tool.id === "audio-convert") return "音频";
  if (tool.id.startsWith("pdf-")) return "PDF 文件";
  if (tool.id.startsWith("docx-")) return "Word 文档";
  if (tool.id.startsWith("md-")) return "Markdown 文件";
  if (tool.id === "xlsx-convert") return "表格文件";
  return "文件";
}

function toast(message, bad = false) {
  const node = document.createElement("div");
  node.className = `toast${bad ? " bad" : ""}`;
  node.innerHTML = `<svg class="icon"><use href="#${bad ? "i-alert" : "i-check"}"/></svg><span>${escapeHtml(message)}</span>`;
  $("toast-wrap").appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transform = "translateY(4px)";
    node.style.transition = "opacity .2s ease, transform .2s ease";
    setTimeout(() => node.remove(), 220);
  }, bad ? 4600 : 2800);
}

function uploadJob(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.timeout = 0;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { data = null; }
      if (xhr.status >= 200 && xhr.status < 300 && data) {
        resolve(data);
        return;
      }
      let detail = (data && data.detail) || `上传失败 (${xhr.status})`;
      if (Array.isArray(detail)) detail = detail.map((item) => item.msg || "").join("；") || "上传参数不正确";
      reject(new Error(detail));
    };
    xhr.onerror = () => reject(new Error("上传失败，请确认本地服务正在运行"));
    xhr.ontimeout = () => reject(new Error("上传超时，请重试"));
    xhr.send(form);
  });
}

function ensureNotificationPermission() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    try { Notification.requestPermission(); } catch { return; }
  }
}

function notifyJob(job) {
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  const title = job.status === "error" ? "白匣 · 任务失败" : job.status === "cancelled" ? "白匣 · 任务已取消" : "白匣 · 任务完成";
  const detail = job.status === "error"
    ? (job.error || "处理失败")
    : job.status === "cancelled"
      ? "已取消，未保留未完成文件"
      : `生成 ${job.outputs.length} 个文件`;
  try {
    new Notification(title, { body: String(detail).slice(0, 140), tag: job.id });
  } catch {
    return;
  }
}

async function api(url, options) {
  const response = await fetch(url, options);
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    let detail = (data && (data.detail || data.message)) || "请求失败，请重试";
    if (Array.isArray(detail)) detail = detail.map((item) => item.msg || "").join("；") || "参数不正确";
    throw new Error(detail);
  }
  return data;
}

/* ───────── 初始化 ───────── */

async function init() {
  initTheme();
  try {
    const data = await api("/api/tools");
    state.categories = data.categories;
    state.tools = data.tools;
    state.caps = data.capabilities || {};
  } catch (error) {
    toast(`无法连接本地服务：${error.message}`, true);
    return;
  }
  renderCategories();
  renderCapabilities();
  updateStats();
  wireEvents();
  const savedId = localStorage.getItem("baixia.tool");
  const tool = toolById(savedId) || toolById("pdf-split") || state.tools[0];
  if (tool) selectTool(tool.id, true);
  renderRecent();
  await resumeActiveJob();
}

function renderCategories() {
  const counts = {};
  state.tools.forEach((tool) => { counts[tool.cat] = (counts[tool.cat] || 0) + 1; });
  const items = [
    { id: "all", name: "全部工具", icon: "all", count: state.tools.length },
    { id: "fav", name: "收藏", icon: "star", count: state.favorites.length },
    ...state.categories.map((cat) => ({ ...cat, count: counts[cat.id] || 0 })),
  ];
  $("cat-list").innerHTML = items.map((cat) => `
    <button type="button" class="cat${state.activeCat === cat.id ? " active" : ""}" data-cat="${cat.id}" aria-pressed="${state.activeCat === cat.id}">
      <svg class="icon"><use href="#i-${cat.icon}"/></svg>
      <span>${escapeHtml(cat.name)}</span>
      <span class="cat-count">${cat.count}</span>
    </button>`).join("");
  $("cat-list").querySelectorAll(".cat").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.busy) { toast("任务处理中，完成后再切换分类", true); return; }
      state.activeCat = button.dataset.cat;
      state.search = "";
      $("search").value = "";
      localStorage.setItem("baixia.cat", state.activeCat);
      renderCategories();
      renderTools();
      const tools = visibleTools();
      const keep = state.activeTool && tools.some((tool) => tool.id === state.activeTool.id);
      if (!keep && tools[0]) selectTool(tools[0].id);
    });
  });
}

function visibleTools() {
  if (state.search) {
    const needle = state.search.toLowerCase();
    return state.tools.filter((tool) => {
      const haystack = [tool.name, tool.desc, tool.route, tool.id, ...(tool.accept || [])].join(" ").toLowerCase();
      return haystack.includes(needle);
    });
  }
  if (state.activeCat === "all") return state.tools.slice();
  if (state.activeCat === "fav") return state.tools.filter((tool) => state.favorites.includes(tool.id));
  return state.tools.filter((tool) => tool.cat === state.activeCat);
}

function renderTools() {
  const list = $("tool-list");
  const tools = visibleTools();
  const searching = !!state.search || state.activeCat === "all";
  list.classList.toggle("searching", searching);
  $("list-label").textContent = state.search
    ? "搜索结果"
    : state.activeCat === "all"
      ? "全部工具"
      : state.activeCat === "fav"
        ? "收藏"
        : (catById(state.activeCat)?.name || "");
  $("list-count").textContent = String(tools.length);
  if (!tools.length) {
    const message = state.search
      ? "没有匹配的工具<br><span>换个关键词，或点「全部工具」看看</span>"
      : state.activeCat === "fav"
        ? "还没有收藏工具<br><span>打开一个工具，点标题旁的星标即可收藏</span>"
        : "这个分类还没有工具";
    list.innerHTML = `<div class="tool-empty">${message}</div>`;
    return;
  }
  let html = "";
  let lastCat = "";
  tools.forEach((tool) => {
    if (searching && tool.cat !== lastCat) {
      lastCat = tool.cat;
      html += `<div class="group-label">${escapeHtml(catById(tool.cat)?.name || "")}</div>`;
    }
    const active = state.activeTool && state.activeTool.id === tool.id;
    html += `
      <button type="button" class="tool${active ? " active" : ""}" data-tool="${tool.id}" aria-current="${active ? "true" : "false"}">
        <span class="tool-name">${escapeHtml(tool.name)}<span class="tool-cat">${escapeHtml(catById(tool.cat)?.name || "")}</span></span>
        <span class="tool-route">${escapeHtml(tool.route)}</span>
      </button>`;
  });
  list.innerHTML = html;
  list.querySelectorAll(".tool").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.busy) { toast("任务处理中，完成后再切换工具", true); return; }
      selectTool(button.dataset.tool);
    });
  });
}

function selectTool(id, initial = false) {
  const tool = toolById(id);
  if (!tool) return;
  if (!initial && state.busy) return;
  if (!initial && !state.search && state.activeTool && state.activeTool.id === tool.id) return;
  state.activeTool = tool;
  const keepFav = state.activeCat === "fav" && state.favorites.includes(tool.id);
  state.activeCat = keepFav ? "fav" : tool.cat;
  localStorage.setItem("baixia.tool", tool.id);
  localStorage.setItem("baixia.cat", state.activeCat);
  if (state.search) {
    state.search = "";
    $("search").value = "";
  }
  renderCategories();
  renderTools();
  renderToolHead(tool);
  if (initial) resetFiles(); else preserveCompatibleFiles(tool);
  renderOptions(tool);
  hideProgress();
  $("run-hint").textContent = tool.multi ? "可多选" : "单个文件";
  $("start").disabled = false;
  $("clear").disabled = false;
  document.title = `${tool.name} · 白匣 BAIXIA`;
  document.querySelector(".bench-scroll")?.scrollTo({ top: 0, behavior: "smooth" });
}

function preserveCompatibleFiles(tool) {
  if (!state.files.length) {
    renderQueue();
    return;
  }
  const accepted = new Set(tool.accept || []);
  const kept = state.files.filter((file) => accepted.has(extOf(file.name)));
  const limit = tool.multi ? 60 : 1;
  const next = kept.slice(0, limit);
  const dropped = state.files.length - next.length;
  state.files = next;
  renderQueue();
  if (!next.length) {
    toast(`当前文件与「${tool.name}」不兼容，已清空`, true);
  } else if (dropped > 0) {
    toast(`已保留 ${next.length} 个兼容文件，跳过 ${dropped} 个`);
  } else {
    toast(`已保留 ${next.length} 个兼容文件`);
  }
}

function updateFavButton(tool) {
  const button = $("fav-toggle");
  if (!button) return;
  const active = state.favorites.includes(tool.id);
  button.classList.toggle("is-fav", active);
  button.setAttribute("aria-pressed", String(active));
  button.setAttribute("aria-label", active ? "取消收藏当前工具" : "收藏当前工具");
  button.title = active ? "取消收藏" : "收藏当前工具";
}

function toggleFavorite() {
  const tool = state.activeTool;
  if (!tool) return;
  if (state.favorites.includes(tool.id)) {
    state.favorites = state.favorites.filter((id) => id !== tool.id);
    toast(`已取消收藏「${tool.name}」`);
  } else {
    state.favorites.push(tool.id);
    toast(`已收藏「${tool.name}」`);
  }
  saveFavorites();
  updateFavButton(tool);
  renderCategories();
  renderTools();
}

function renderToolHead(tool) {
  const cat = catById(tool.cat);
  $("crumb").innerHTML = `<span>${escapeHtml(cat?.name || "")}</span><span class="sep">/</span><span>${escapeHtml(tool.name)}</span>`;
  $("tool-title").textContent = tool.name;
  const parts = tool.route.split("→").map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    $("tool-route").innerHTML = `<span class="hl">${escapeHtml(parts[0])}</span><span class="arr">→</span><span>${parts.slice(1).map(escapeHtml).join(" → ")}</span>`;
  } else {
    $("tool-route").innerHTML = `<span class="hl">${escapeHtml(tool.route)}</span>`;
  }
  $("tool-desc").textContent = tool.desc;
  const warning = $("tool-warning");
  warning.hidden = !tool.warning;
  warning.textContent = tool.warning || "";
  updateFavButton(tool);
  const subject = subjectFor(tool);
  $("drop-title").textContent = `把${subject}拖到这里`;
  $("drop-limit").textContent = tool.multi ? " · 可多选" : " · 单个文件";
  $("drop-formats").textContent = (tool.accept || []).map((ext) => ext.replace(".", "").toUpperCase()).join(" · ");
  $("folder-pick").hidden = !(tool.cat === "image" || tool.id === "images-to-pdf");
  const input = $("file-input");
  input.accept = (tool.accept || []).join(",");
  input.multiple = !!tool.multi;
  input.value = "";
  $("folder-input").value = "";
}

/* ───────── 选项 ───────── */

function optionStorageKey(toolId) {
  return `${OPTIONS_PREFIX}${toolId}`;
}

function sanitizeOption(spec, value) {
  if (spec.type === "checkbox") {
    return value === true || value === "true" || value === 1 || value === "1";
  }
  if (spec.type === "number" || spec.type === "range") {
    let number = Number(value);
    if (!Number.isFinite(number)) number = Number(spec.default) || 0;
    const min = spec.min === undefined ? -Infinity : Number(spec.min);
    const max = spec.max === undefined ? Infinity : Number(spec.max);
    return Math.max(min, Math.min(max, number));
  }
  if (spec.type === "select") {
    const allowed = (spec.choices || []).map((choice) => choice[0]);
    return allowed.includes(String(value)) ? String(value) : spec.default;
  }
  return value === undefined || value === null ? spec.default : String(value);
}

function loadToolOptions(tool) {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(optionStorageKey(tool.id)) || "{}") || {};
  } catch {
    saved = {};
  }
  const options = {};
  (tool.options || []).forEach((spec) => {
    if (spec.key === "password") {
      options[spec.key] = spec.default;
      return;
    }
    options[spec.key] = sanitizeOption(spec, Object.prototype.hasOwnProperty.call(saved, spec.key) ? saved[spec.key] : spec.default);
  });
  return options;
}

function rangeDisplay(spec, value) {
  if (spec.key === "target_mb") {
    const number = Number(value) || 0;
    if (number < 1) return `${number.toFixed(2)} MB`;
    if (Number.isInteger(number)) return `${number} MB`;
    return `${number.toFixed(1)} MB`;
  }
  return String(value);
}

function optionConditionMet(condition) {
  if (!condition) return true;
  const actual = state.options[condition.key];
  if (typeof condition.equals === "boolean") return Boolean(actual) === condition.equals;
  return String(actual) === String(condition.equals);
}

function applyConditionalOptions(tool) {
  const grid = $("options-grid");
  (tool.options || []).forEach((spec) => {
    if (!spec.enable_if) return;
    const field = grid.querySelector(`[data-key="${spec.key}"]`);
    if (field) field.hidden = !optionConditionMet(spec.enable_if);
  });
  if (tool.id === "video-compress") syncVideoTargetRange(tool);
}

function syncVideoTargetRange(tool) {
  if (!tool || tool.id !== "video-compress") return;
  const input = $("opt-target_mb");
  if (!input) return;
  const field = input.closest(".field");
  const output = field ? field.querySelector(".range-val") : null;
  const hint = field ? field.querySelector(".field-hint") : null;
  const source = state.files[0];
  if (!source) {
    if (state.videoProbeUrl) {
      URL.revokeObjectURL(state.videoProbeUrl);
      state.videoProbeUrl = null;
    }
    state.videoProbeKey = null;
    state.videoProbeDuration = null;
    input.min = "1";
    input.max = "100";
    input.step = "1";
    let value = Number(state.options.target_mb) || 10;
    value = Math.max(1, Math.min(100, Math.round(value)));
    state.options.target_mb = value;
    input.value = String(value);
    if (hint) hint.textContent = "选择视频后，滑杆上限自动设为原视频大小";
  } else {
    const key = `${source.name}:${source.size}:${source.lastModified}`;
    if (state.videoProbeKey !== key) {
      if (state.videoProbeUrl) URL.revokeObjectURL(state.videoProbeUrl);
      state.videoProbeKey = key;
      state.videoProbeDuration = null;
      const probe = document.createElement("video");
      probe.preload = "metadata";
      probe.muted = true;
      const url = URL.createObjectURL(source);
      state.videoProbeUrl = url;
      probe.src = url;
      probe.onloadedmetadata = () => {
        if (state.videoProbeKey === key) {
          state.videoProbeDuration = Number.isFinite(probe.duration) ? probe.duration : null;
          syncVideoTargetRange(tool);
        }
        URL.revokeObjectURL(url);
        if (state.videoProbeUrl === url) state.videoProbeUrl = null;
      };
      probe.onerror = () => {
        URL.revokeObjectURL(url);
        if (state.videoProbeUrl === url) state.videoProbeUrl = null;
      };
    }
    const sourceMB = source.size / (1024 * 1024);
    const step = sourceMB < 20 ? 0.01 : sourceMB < 200 ? 0.1 : sourceMB < 2000 ? 1 : 10;
    const duration = state.videoProbeDuration;
    const rawMin = duration ? (118 * duration / 8 / 1024) : 0.1;
    let minimum = Math.max(0.1, rawMin);
    minimum = step >= 1 ? Math.ceil(minimum / step) * step : Math.ceil(minimum * 100) / 100;
    const maxMB = minimum + Math.floor(Math.max(0, sourceMB * 0.99 - minimum) / step) * step;
    input.min = String(Math.min(minimum, maxMB));
    input.step = String(step);
    input.max = String(Math.max(minimum, maxMB));
    let value = Number(state.options.target_mb) || 0;
    if (!Number.isFinite(value) || value < minimum || value > maxMB) {
      value = minimum + Math.round(((maxMB * 0.6) - minimum) / step) * step;
      value = Math.min(maxMB, Math.max(minimum, value));
    }
    value = minimum + Math.round((value - minimum) / step) * step;
    state.options.target_mb = Number(value.toFixed(2));
    input.value = String(state.options.target_mb);
    if (hint) {
      hint.textContent = duration
        ? `原视频 ${sourceMB.toFixed(2)} MB · 目标范围 ${minimum.toFixed(2)}–${maxMB.toFixed(2)} MB`
        : `原视频 ${sourceMB.toFixed(2)} MB · 目标必须小于原大小`;
    }
  }
  if (output) output.textContent = rangeDisplay({ key: "target_mb" }, input.value);
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const pct = ((Number(input.value) - min) / Math.max(0.001, max - min)) * 100;
  input.style.setProperty("--pct", `${Math.max(0, Math.min(100, pct))}%`);
  if (state.options.custom_size) persistToolOptions(tool);
}

function pdfGalleryKey(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function syncPdfGallery(tool) {
  const panel = $("pdf-gallery");
  if (!panel) return;
  if (!tool || tool.id !== "pdf-pages" || !state.files.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const file = state.files[0];
  const key = pdfGalleryKey(file);
  if (!state.gallery || state.gallery.key !== key) {
    loadPdfGallery(file);
  } else {
    renderPdfGallery();
  }
}

async function loadPdfGallery(file, force = false) {
  const key = pdfGalleryKey(file);
  if (!force && state.gallery && state.gallery.key === key && (state.gallery.loading || state.gallery.token)) {
    renderPdfGallery();
    return;
  }
  state.gallery = { key, loading: true, token: "", pages: [], items: [], error: "" };
  renderPdfGallery();
  const form = new FormData();
  form.append("file", file, file.name);
  try {
    const data = await api("/api/pdf-gallery", { method: "POST", body: form });
    if (!state.gallery || state.gallery.key !== key) return;
    state.gallery = {
      key,
      loading: false,
      token: data.token,
      pages: data.pages || [],
      items: (data.pages || []).map((page) => ({ src: page.index, rotate: 0 })),
      error: "",
    };
  } catch (error) {
    if (state.gallery && state.gallery.key === key) {
      state.gallery = { key, loading: false, token: "", pages: [], items: [], error: error.message };
    }
  }
  renderPdfGallery();
}

function resetPdfGallery() {
  const gallery = state.gallery;
  if (!gallery || !gallery.pages.length) return;
  gallery.items = gallery.pages.map((page) => ({ src: page.index, rotate: 0 }));
  renderPdfGallery();
  toast("已恢复全部页面和原始顺序");
}

function renderPdfGallery() {
  const panel = $("pdf-gallery");
  const tool = state.activeTool;
  if (!panel) return;
  if (!tool || tool.id !== "pdf-pages" || !state.files.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const gallery = state.gallery;
  const status = $("gallery-status");
  const grid = $("gallery-grid");
  const reset = $("gallery-reset");
  const reload = $("gallery-reload");
  const hint = $("gallery-hint");
  status.classList.remove("error");
  if (!gallery || gallery.loading) {
    $("gallery-count").textContent = "正在准备";
    status.textContent = "正在生成页面缩略图，请不要关闭页面…";
    grid.innerHTML = "";
    reset.hidden = true;
    reload.hidden = true;
    hint.hidden = true;
    return;
  }
  if (gallery.error) {
    $("gallery-count").textContent = "";
    status.textContent = gallery.error;
    status.classList.add("error");
    grid.innerHTML = `<div class="gallery-empty">无法载入页面预览。请重新载入或更换文件。</div>`;
    reset.hidden = true;
    reload.hidden = false;
    hint.hidden = true;
    return;
  }
  const total = gallery.pages.length;
  const items = gallery.items;
  const original = items.length === total && items.every((item, index) => item.src === index && !item.rotate);
  $("gallery-count").textContent = `${items.length} / ${total} 页`;
  status.textContent = items.length ? "已按当前顺序准备，开始处理后导出新 PDF。" : "已删除全部页面，至少保留一页才能处理。";
  status.classList.toggle("error", !items.length);
  reset.hidden = original;
  reload.hidden = false;
  hint.hidden = !items.length;
  if (!items.length) {
    grid.innerHTML = `<div class="gallery-empty">页面已全部删除。<br>点「重置页面」恢复全部页面。</div>`;
    return;
  }
  grid.innerHTML = items.map((item, index) => {
    const scale = item.rotate % 180 ? ".7" : "1";
    return `<figure class="gallery-card" draggable="true" data-index="${index}" title="拖动调整顺序">
      <div class="gallery-thumb">
        <img src="/api/pdf-gallery/${encodeURIComponent(gallery.token)}/thumb/${item.src}" alt="第 ${item.src + 1} 页缩略图" loading="lazy" style="transform: rotate(${item.rotate}deg) scale(${scale})">
        <span class="gallery-page-no">${index + 1}</span>
        <span class="gallery-actions">
          <button type="button" data-act="left" title="前移一位" aria-label="第 ${index + 1} 页前移">←</button>
          <button type="button" data-act="right" title="后移一位" aria-label="第 ${index + 1} 页后移">→</button>
          <button type="button" data-act="rotate" title="顺时针旋转 90°" aria-label="旋转第 ${index + 1} 页">↻</button>
          <button type="button" class="danger" data-act="delete" title="删除这一页" aria-label="删除第 ${index + 1} 页">×</button>
        </span>
      </div>
      <figcaption><span>原第 ${item.src + 1} 页</span><span>${item.rotate ? `↻ ${item.rotate}°` : ""}</span></figcaption>
    </figure>`;
  }).join("");
  grid.querySelectorAll(".gallery-card").forEach((card) => {
    const index = Number(card.dataset.index);
    card.querySelectorAll("[data-act]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (state.busy) return;
        const action = button.dataset.act;
        if (action === "rotate") items[index].rotate = (items[index].rotate + 90) % 360;
        if (action === "delete") items.splice(index, 1);
        if (action === "left" && index > 0) [items[index - 1], items[index]] = [items[index], items[index - 1]];
        if (action === "right" && index < items.length - 1) [items[index + 1], items[index]] = [items[index], items[index + 1]];
        renderPdfGallery();
      });
    });
  });
  let dragIndex = null;
  const clearDrag = () => grid.querySelectorAll(".gallery-card").forEach((card) => card.classList.remove("dragging", "drag-over"));
  grid.querySelectorAll(".gallery-card").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      if (state.busy) { event.preventDefault(); return; }
      dragIndex = Number(card.dataset.index);
      event.dataTransfer.effectAllowed = "move";
      try { event.dataTransfer.setData("text/plain", String(dragIndex)); } catch {}
      card.classList.add("dragging");
    });
    card.addEventListener("dragover", (event) => {
      if (dragIndex === null) return;
      event.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", (event) => {
      if (dragIndex === null) return;
      event.preventDefault();
      event.stopPropagation();
      const from = dragIndex;
      const to = Number(card.dataset.index);
      dragIndex = null;
      clearDrag();
      if (!Number.isInteger(from) || from === to) return;
      const [moved] = items.splice(from, 1);
      items.splice(to, 0, moved);
      renderPdfGallery();
    });
    card.addEventListener("dragend", () => { dragIndex = null; clearDrag(); });
  });
}

async function copyLanUrl(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("地址已复制");
    return;
  } catch {}
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast("地址已复制");
  } catch {
    toast("复制失败，请手动选择地址", true);
  }
}

async function openLanModal() {
  let info;
  try {
    info = await api("/api/network");
  } catch (error) {
    toast(`无法读取局域网状态：${error.message}`, true);
    return;
  }
  let body = "";
  let foot = `<button type="button" class="btn ghost" data-lan-close>关闭</button>`;
  if (info.lan_enabled && info.urls && info.urls.length) {
    const url = info.urls[0];
    body = `<div class="lan-box">
      <div class="lan-ok"><span class="live-dot"></span> 局域网模式已开启，手机可直接访问</div>
      <div class="lan-qr"><img src="/api/network/qr?ts=${Date.now()}" alt="局域网地址二维码"></div>
      <div class="lan-url"><code>${escapeHtml(url)}</code><button type="button" class="mini-btn" data-copy-url="${escapeHtml(url)}">复制</button></div>
      <p class="lan-note">手机与电脑连接同一个 Wi-Fi，扫码或在浏览器输入上面的地址即可打开白匣，手机里的文件可直接上传处理，处理结果也能下载回手机。</p>
      <div class="lan-warn">局域网模式没有密码，同一网络内的设备都能打开此页面。请只在可信 Wi-Fi 下使用，公共网络请点「停止白匣」后改用本机启动。</div>
    </div>`;
  } else {
    body = `<div class="lan-box">
      <div class="lan-warn">当前是「仅本机」模式，只有这台电脑能访问。要扫码互传，请先关闭白匣，再双击项目目录里的 <b>启动白匣（局域网）.vbs</b>。</div>
      <ol class="lan-steps">
        <li>双击 <code>停止白匣.vbs</code> 关闭当前服务。</li>
        <li>双击 <code>启动白匣（局域网）.vbs</code>，允许 Windows 防火墙访问。</li>
        <li>手机连接同一个 Wi-Fi，重新打开本弹窗即可看到二维码。</li>
      </ol>
      <div class="lan-url"><code>${escapeHtml(info.local_url || "http://127.0.0.1:8765")}</code><button type="button" class="mini-btn" data-copy-url="${escapeHtml(info.local_url || "http://127.0.0.1:8765")}">复制本机地址</button></div>
      <p class="lan-note">局域网模式下文件仍然只在这台电脑处理，不会上传到云端；手机只是通过浏览器访问本机服务。</p>
    </div>`;
  }
  openModal("局域网互传", body, foot);
  $("modal-foot").querySelector("[data-lan-close]")?.addEventListener("click", closeModal);
  $("modal-body").querySelectorAll("[data-copy-url]").forEach((button) => {
    button.addEventListener("click", () => copyLanUrl(button.dataset.copyUrl || ""));
  });
}

function hasSavedOptions(tool) {
  try {
    return !!localStorage.getItem(optionStorageKey(tool.id));
  } catch {
    return false;
  }
}

function persistToolOptions(tool, options = state.options) {
  try {
    const safe = {};
    (tool.options || []).forEach((spec) => {
      if (spec.key !== "password" && Object.prototype.hasOwnProperty.call(options, spec.key)) {
        safe[spec.key] = options[spec.key];
      }
    });
    localStorage.setItem(optionStorageKey(tool.id), JSON.stringify(safe));
  } catch {
    return;
  }
}

function renderOptions(tool) {
  const specs = tool.options || [];
  const section = $("options");
  const grid = $("options-grid");
  state.options = loadToolOptions(tool);
  $("reset-options").hidden = !hasSavedOptions(tool);
  if (!specs.length) {
    section.hidden = true;
    grid.innerHTML = "";
    return;
  }
  section.hidden = false;
  $("options-note").textContent = tool.hint || "按需调整，默认设置通常就够用";
  grid.innerHTML = specs.map((spec) => optionHtml(spec)).join("");
  specs.forEach((spec) => {
    const field = grid.querySelector(`[data-key="${spec.key}"]`);
    if (!field) return;
    if (spec.type === "select") {
      const select = field.querySelector("select");
      select.addEventListener("change", () => {
        state.options[spec.key] = select.value;
        persistToolOptions(tool);
      });
    } else if (spec.type === "checkbox") {
      const box = field.querySelector("input[type=checkbox]");
      box.addEventListener("change", () => {
        state.options[spec.key] = box.checked;
        persistToolOptions(tool);
        applyConditionalOptions(tool);
      });
    } else if (spec.type === "range") {
      const range = field.querySelector("input[type=range]");
      const value = field.querySelector(".range-val");
      const sync = () => {
        state.options[spec.key] = Number(range.value);
        value.textContent = rangeDisplay(spec, range.value);
        const min = Number(range.min || 0);
        const max = Number(range.max || 100);
        const pct = ((Number(range.value) - min) / (max - min)) * 100;
        range.style.setProperty("--pct", `${pct}%`);
      };
      range.addEventListener("input", () => { sync(); persistToolOptions(tool); });
      sync();
    } else if (spec.type === "number") {
      const input = field.querySelector("input");
      input.addEventListener("input", () => {
        state.options[spec.key] = input.value;
        persistToolOptions(tool);
      });
    } else {
      const input = field.querySelector("input");
      input.addEventListener("input", () => {
        state.options[spec.key] = input.value;
        persistToolOptions(tool);
      });
    }
  });
  applyConditionalOptions(tool);
}

function optionHtml(spec) {
  const value = state.options[spec.key] ?? spec.default;
  const textValue = escapeHtml(value);
  const wide = ["pages", "pattern", "sizes"].includes(spec.key) || (spec.type === "text" && String(spec.label).includes("范围"));
  if (spec.type === "checkbox") {
    return `<div class="field${wide ? " wide" : ""}" data-key="${spec.key}">
      <label class="switch-row">
        <span class="switch"><input id="opt-${spec.key}" type="checkbox" ${value ? "checked" : ""} aria-label="${escapeHtml(spec.label)}"><span class="track"></span></span>
        <span class="switch-text">${escapeHtml(spec.label)}</span>
      </label>
      ${spec.hint ? `<span class="field-hint">${escapeHtml(spec.hint)}</span>` : ""}
    </div>`;
  }
  if (spec.type === "select") {
    return `<div class="field${wide ? " wide" : ""}" data-key="${spec.key}">
      <label class="field-label" for="opt-${spec.key}">${escapeHtml(spec.label)}</label>
      <div class="select-wrap">
        <select id="opt-${spec.key}">${(spec.choices || []).map(([choiceValue, label]) =>
          `<option value="${escapeHtml(choiceValue)}" ${String(choiceValue) === String(value) ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select>
      </div>
      ${spec.hint ? `<span class="field-hint">${escapeHtml(spec.hint)}</span>` : ""}
    </div>`;
  }
  if (spec.type === "range") {
    return `<div class="field${wide ? " wide" : ""}" data-key="${spec.key}">
      <div class="field-label"><label for="opt-${spec.key}">${escapeHtml(spec.label)}</label></div>
      <div class="range-row">
        <input id="opt-${spec.key}" type="range" min="${spec.min ?? 0}" max="${spec.max ?? 100}" step="${spec.step ?? 1}" value="${textValue}">
        <output class="range-val">${escapeHtml(rangeDisplay(spec, value))}</output>
      </div>
      ${spec.hint ? `<span class="field-hint">${escapeHtml(spec.hint)}</span>` : ""}
    </div>`;
  }
  if (spec.type === "number") {
    return `<div class="field${wide ? " wide" : ""}" data-key="${spec.key}">
      <label class="field-label" for="opt-${spec.key}">${escapeHtml(spec.label)}</label>
      <input class="input" id="opt-${spec.key}" type="number" min="${spec.min ?? ""}" max="${spec.max ?? ""}" step="${spec.step ?? 1}" value="${textValue}">
      ${spec.hint ? `<span class="field-hint">${escapeHtml(spec.hint)}</span>` : ""}
    </div>`;
  }
  return `<div class="field${wide ? " wide" : ""}" data-key="${spec.key}">
    <label class="field-label" for="opt-${spec.key}">${escapeHtml(spec.label)}</label>
    <input class="input" id="opt-${spec.key}" type="${spec.key === "password" ? "password" : "text"}" autocomplete="off" value="${textValue}" placeholder="${escapeHtml(spec.placeholder || "")}">
    ${spec.hint ? `<span class="field-hint">${escapeHtml(spec.hint)}</span>` : ""}
  </div>`;
}

/* ───────── 文件队列 ───────── */

function resetFiles() {
  state.files = [];
  renderQueue();
}

function addFiles(fileList, fromPaste = false) {
  const tool = state.activeTool;
  if (!tool || state.busy) return { added: 0, rejected: 0 };
  const accepted = new Set(tool.accept || []);
  const files = Array.from(fileList || []);
  let rejected = 0;
  let overflow = false;
  const before = state.files.length;
  for (const file of files) {
    const ext = `.${(file.name.split(".").pop() || "").toLowerCase()}`;
    const name = file.name || `pasted-${Date.now()}.png`;
    const candidate = file.name ? file : new File([file], name, { type: file.type });
    if (!accepted.has(ext) && !(fromPaste && file.type.startsWith("image/"))) {
      rejected += 1;
      continue;
    }
    if (!tool.multi) {
      state.files = [candidate];
      break;
    }
    if (state.files.length >= 60) { overflow = true; break; }
    state.files.push(candidate);
  }
  if (rejected) toast(`有 ${rejected} 个文件格式不支持，已跳过`, true);
  if (overflow) toast("一次最多 60 个文件", true);
  renderQueue();
  return { added: state.files.length - before, rejected };
}

function revokeFileUrls() {
  state.fileUrls.forEach((url) => { if (url) URL.revokeObjectURL(url); });
  state.fileUrls = [];
}

function renderQueue() {
  const queue = $("queue");
  const list = $("file-list");
  const drop = $("drop");
  const tool = state.activeTool;
  revokeFileUrls();
  if (!state.files.length) {
    queue.hidden = true;
    list.innerHTML = "";
    drop.classList.remove("has-files");
    if (tool) $("drop-title").textContent = `把${subjectFor(tool)}拖到这里`;
    if (tool && tool.id === "video-compress") syncVideoTargetRange(tool);
    syncPdfGallery(tool);
    return;
  }
  drop.classList.add("has-files");
  $("drop-title").textContent = tool && tool.multi ? "继续添加文件" : "更换文件";
  queue.hidden = false;
  $("queue-count").textContent = state.files.length;
  const total = state.files.reduce((sum, file) => sum + file.size, 0);
  $("queue-size").textContent = fmtSize(total);
  state.fileUrls = state.files.map((file) => (
    BROWSER_IMAGE_EXTS.has(extOf(file.name)) ? URL.createObjectURL(file) : null
  ));
  list.innerHTML = state.files.map((file, index) => {
    const actions = [];
    if (tool && tool.multi && state.files.length > 1) {
      if (index > 0) actions.push(`<button type="button" class="icon-btn" data-act="up" data-i="${index}" aria-label="上移"><svg class="icon"><use href="#i-up"/></svg></button>`);
      if (index < state.files.length - 1) actions.push(`<button type="button" class="icon-btn" data-act="down" data-i="${index}" aria-label="下移"><svg class="icon"><use href="#i-down"/></svg></button>`);
    }
    actions.push(`<button type="button" class="icon-btn danger" data-act="remove" data-i="${index}" aria-label="移除"><svg class="icon"><use href="#i-close"/></svg></button>`);
    const ext = (extOf(file.name).replace(".", "") || "FILE").toUpperCase().slice(0, 5);
    const preview = state.fileUrls[index];
    return `<li class="file-item" draggable="${tool && tool.multi ? "true" : "false"}" data-index="${index}" title="${tool && tool.multi ? "拖动可调整顺序" : ""}">
      <span class="file-mark">${preview ? `<img src="${preview}" alt="" loading="lazy">` : escapeHtml(ext)}</span>
      <span class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
      <span class="file-size">${fmtSize(file.size)}</span>
      <span class="file-actions">${actions.join("")}</span>
    </li>`;
  }).join("");
  list.querySelectorAll(".icon-btn").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.busy) return;
      const index = Number(button.dataset.i);
      const action = button.dataset.act;
      if (action === "remove") state.files.splice(index, 1);
      if (action === "up" && index > 0) {
        [state.files[index - 1], state.files[index]] = [state.files[index], state.files[index - 1]];
      }
      if (action === "down" && index < state.files.length - 1) {
        [state.files[index + 1], state.files[index]] = [state.files[index], state.files[index + 1]];
      }
      renderQueue();
    });
  });
  if (tool && tool.id === "video-compress") syncVideoTargetRange(tool);
  syncPdfGallery(tool);
  if (tool && tool.multi && state.files.length > 1) {
    let dragIndex = null;
    const clearDrag = () => {
      list.querySelectorAll(".file-item").forEach((item) => item.classList.remove("dragging", "drag-over"));
    };
    list.querySelectorAll(".file-item").forEach((item) => {
      item.addEventListener("dragstart", (event) => {
        if (state.busy) { event.preventDefault(); return; }
        dragIndex = Number(item.dataset.index);
        event.dataTransfer.effectAllowed = "move";
        try { event.dataTransfer.setData("text/plain", String(dragIndex)); } catch {}
        item.classList.add("dragging");
      });
      item.addEventListener("dragover", (event) => {
        if (dragIndex === null) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        item.classList.add("drag-over");
      });
      item.addEventListener("dragleave", () => item.classList.remove("drag-over"));
      item.addEventListener("drop", (event) => {
        if (dragIndex === null) return;
        event.preventDefault();
        event.stopPropagation();
        const to = Number(item.dataset.index);
        const from = dragIndex;
        dragIndex = null;
        clearDrag();
        if (from === to || !Number.isInteger(from)) return;
        const [moved] = state.files.splice(from, 1);
        state.files.splice(to, 0, moved);
        renderQueue();
      });
      item.addEventListener("dragend", () => {
        dragIndex = null;
        clearDrag();
      });
    });
  }
}

/* ───────── 运行与轮询 ───────── */

async function startJob() {
  const tool = state.activeTool;
  if (!tool || state.busy) return;
  if (!state.files.length) {
    toast(`请先选择${subjectFor(tool)}`, true);
    return;
  }
  if (tool.id === "video-compress" && state.options.custom_size) {
    const source = state.files[0];
    const sourceMB = source.size / (1024 * 1024);
    const target = Number(state.options.target_mb) || 0;
    const minimum = Number($("opt-target_mb").min) || 0.1;
    if (target <= 0) {
      toast("请设置有效的目标大小", true);
      return;
    }
    if (target < minimum) {
      toast(`目标太小：这个视频最低约 ${minimum.toFixed(2)} MB`, true);
      return;
    }
    if (target >= sourceMB * 0.995) {
      toast(`目标大小必须小于原视频（${sourceMB.toFixed(2)} MB）`, true);
      return;
    }
  }
  const galleryMode = tool.id === "pdf-pages";
  if (galleryMode) {
    const gallery = state.gallery;
    if (!gallery || gallery.loading) {
      toast("页面缩略图还在生成，请稍等", true);
      return;
    }
    if (!gallery.token || gallery.error) {
      toast(gallery.error || "页面预览不可用，请重新载入", true);
      return;
    }
    if (!gallery.items.length) {
      toast("请至少保留一页", true);
      return;
    }
  }
  const form = new FormData();
  form.append("tool", tool.id);
  form.append("options", JSON.stringify(state.options));
  if (galleryMode) {
    form.append("gallery_token", state.gallery.token);
    form.append("gallery_ops", JSON.stringify({ pages: state.gallery.items }));
  } else {
    state.files.forEach((file) => form.append("files", file, file.name));
  }

  ensureNotificationPermission();
  closeJobEvents();
  state.busy = true;
  state.job = null;
  state.pollFails = 0;
  setRunningUI(true);
  clearTray();
  showProgress(0, galleryMode ? "正在提交页面顺序" : "正在上传文件");
  setCancelState(true, true);
  $("start").disabled = true;
  $("clear").disabled = true;
  const totalBytes = state.files.reduce((sum, file) => sum + file.size, 0);
  const started = performance.now();
  try {
    const data = await uploadJob(form, (loaded, total) => {
      const size = total || totalBytes;
      const pct = size ? Math.min(99, Math.round((loaded / size) * 100)) : 0;
      const elapsed = Math.max(0.2, (performance.now() - started) / 1000);
      const speed = loaded / elapsed;
      showProgress(
        galleryMode ? 20 : pct,
        galleryMode ? "正在提交页面顺序" : `正在上传 ${pct}% · ${fmtSize(loaded)} / ${fmtSize(size)} · ${fmtSize(speed)}/s`
      );
    });
    beginJob(data.job);
  } catch (error) {
    state.busy = false;
    setRunningUI(false);
    hideProgress();
    toast(error.message, true);
    renderTrayEmpty();
  }
}

function beginJob(job) {
  state.job = job;
  state.busy = true;
  state.pollFails = 0;
  localStorage.setItem(ACTIVE_JOB_KEY, job.id);
  setRunningUI(true);
  clearTray();
  showProgress(job.progress || 2, job.message || "开始处理");
  setCancelState(false, false);
  watchJob(job.id);
}

function setRunningUI(running) {
  state.busy = running;
  $("start").disabled = running;
  $("clear").disabled = running;
  $("start").querySelector("span").textContent = running ? "处理中…" : "开始处理";
  document.body.classList.toggle("running", running);
  $("file-input").disabled = running;
  $("folder-input").disabled = running;
  if (!running) setCancelState(false, true);
}

function setCancelState(disabled, hidden) {
  const button = $("cancel");
  if (!button) return;
  button.hidden = hidden;
  button.disabled = disabled;
  button.textContent = disabled ? "正在取消…" : "取消任务";
}

function showProgress(pct, message) {
  $("progress").hidden = false;
  const value = Math.max(0, Math.min(100, Math.round(pct || 0)));
  $("progress-fill").style.width = `${value}%`;
  $("progress-pct").textContent = `${value}%`;
  $("progress-msg").textContent = message || "处理中";
}

function hideProgress() {
  $("progress").hidden = true;
  $("progress-fill").style.width = "0%";
  $("progress-pct").textContent = "0%";
  setCancelState(false, true);
}

async function requestCancel() {
  if (!state.busy || !state.job) return;
  setCancelState(true, false);
  showProgress(state.job.progress || 0, "正在取消…");
  try {
    await api(`/api/jobs/${encodeURIComponent(state.job.id)}/cancel`, { method: "POST" });
    toast("已发送取消请求");
  } catch (error) {
    setCancelState(false, false);
    toast(error.message, true);
  }
}

async function retryJob(job) {
  if (!job || state.busy) return;
  try {
    const data = await api(`/api/jobs/${encodeURIComponent(job.id)}/retry`, { method: "POST" });
    state.files = [];
    renderQueue();
    const tool = toolById(job.tool);
    if (tool) selectTool(tool.id, true);
    beginJob(data.job);
    toast("已重新开始任务");
  } catch (error) {
    toast(error.message, true);
  }
}

async function reuseResult(job, tool) {
  if (!job || !tool || state.busy) return;
  closeModal();
  try {
    const data = await api(`/api/jobs/${encodeURIComponent(job.id)}/reuse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool: tool.id }),
    });
    state.files = [];
    renderQueue();
    selectTool(tool.id, true);
    beginJob(data.job);
    toast(`已用上一步结果继续「${tool.name}」`);
  } catch (error) {
    toast(error.message, true);
  }
}

function closeJobEvents() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  clearTimeout(state.pollTimer);
}

function handleJobUpdate(job) {
  if (!job) return;
  const previousStatus = state.job && state.job.id === job.id ? state.job.status : null;
  state.pollFails = 0;
  state.job = job;
  if (job.status === "queued" || job.status === "running") {
    showProgress(job.progress, job.message);
    return;
  }
  if (previousStatus === job.status && ["done", "error", "cancelled"].includes(job.status)) return;
  closeJobEvents();
  state.busy = false;
  setRunningUI(false);
  localStorage.removeItem(ACTIVE_JOB_KEY);
  if (job.status === "cancelled") {
    hideProgress();
    renderJobCancelled(job);
    addRecent(job);
    notifyJob(job);
    toast("任务已取消");
    return;
  }
  if (job.status === "error") {
    hideProgress();
    renderJobError(job);
    addRecent(job);
    notifyJob(job);
    toast(job.error || "处理失败", true);
    return;
  }
  showProgress(100, job.message || "完成");
  setTimeout(hideProgress, 500);
  renderResults(job);
  addRecent(job);
  notifyJob(job);
  const seconds = job.elapsed ? ` · ${job.elapsed}s` : "";
  toast(`完成，生成 ${job.outputs.length} 个文件${seconds}`);
  if (window.innerWidth <= 980) {
    setTimeout(() => document.querySelector(".tray")?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
  }
}

function watchJob(jobId) {
  closeJobEvents();
  if (!("EventSource" in window)) {
    pollJob(jobId);
    return;
  }
  const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);
  state.eventSource = source;
  let received = false;
  source.onmessage = (event) => {
    if (state.eventSource !== source) return;
    received = true;
    try {
      handleJobUpdate(JSON.parse(event.data));
    } catch {
      return;
    }
  };
  source.onerror = () => {
    if (state.eventSource !== source) return;
    source.close();
    state.eventSource = null;
    if (!state.busy) return;
    if (received) pollJob(jobId);
    else setTimeout(() => { if (state.busy && !state.eventSource) pollJob(jobId); }, 300);
  };
}

async function pollJob(jobId) {
  if (state.eventSource) return;
  clearTimeout(state.pollTimer);
  try {
    const job = await api(`/api/jobs/${jobId}`);
    handleJobUpdate(job);
    if (state.busy && (job.status === "queued" || job.status === "running")) {
      state.pollTimer = setTimeout(() => pollJob(jobId), 600);
    }
  } catch (error) {
    state.pollFails += 1;
    if (state.pollFails >= 4) {
      state.busy = false;
      setRunningUI(false);
      hideProgress();
      toast(`任务状态获取失败：${error.message}`, true);
      return;
    }
    state.pollTimer = setTimeout(() => pollJob(jobId), 1200);
  }
}

async function resumeActiveJob() {
  const jobId = localStorage.getItem(ACTIVE_JOB_KEY);
  if (!jobId) return;
  try {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === "queued" || job.status === "running") {
      const tool = toolById(job.tool);
      if (tool) selectTool(tool.id, true);
      beginJob(job);
    } else if (job.status === "done") {
      localStorage.removeItem(ACTIVE_JOB_KEY);
      state.job = job;
      renderResults(job);
      addRecent(job);
    } else {
      localStorage.removeItem(ACTIVE_JOB_KEY);
      state.job = job;
      if (job.status === "cancelled") renderJobCancelled(job);
      else renderJobError(job);
      addRecent(job);
    }
  } catch {
    localStorage.removeItem(ACTIVE_JOB_KEY);
  }
}

/* ───────── 输出 / 最近 ───────── */

function clearTray() {
  $("results").hidden = true;
  $("results").innerHTML = "";
  $("tray-count").textContent = "0";
  $("tray-sub").textContent = "处理完成后在这里下载";
  renderTrayEmpty();
}

function renderTrayEmpty() {
  $("tray-empty").hidden = !!state.job && state.job.status === "done";
  if (!state.job || state.job.status !== "done") {
    $("tray-empty").hidden = false;
    $("tray-empty").querySelector("p").innerHTML = state.busy
      ? "任务正在处理中。<br>完成后文件会出现在这里。"
      : "还没有输出文件。<br>先选一个工具试试。";
  }
}

function comparisonLine(job) {
  const inputSize = Number(job.input_size || 0);
  const outputSize = Number(job.output_size || 0);
  if (!inputSize || !outputSize) return "";
  const pct = Number(job.saved_percent || 0);
  const tail = pct > 0.5 ? ` · 节省 ${Math.round(pct)}%` : "";
  return `${fmtSize(inputSize)} → ${fmtSize(outputSize)}${tail}`;
}

function compatibleToolsForJob(job) {
  const bare = (job.outputs || []).filter((file) => !file.name.toLowerCase().endsWith(".zip"));
  const sources = bare.length ? bare : (job.outputs || []);
  if (!sources.length) return [];
  const exts = new Set(sources.map((file) => extOf(file.name)));
  if (!exts.size || exts.has(".zip")) return [];
  return state.tools.filter((tool) => {
    const accept = new Set(tool.accept || []);
    if (![...exts].every((ext) => accept.has(ext))) return false;
    if (!tool.multi && sources.length > 1) return false;
    return tool.id !== job.tool;
  });
}

function canCompare(job) {
  const inputs = job.inputs || [];
  const outputs = (job.outputs || []).filter((file) => isPreviewable(file.name) && !file.name.toLowerCase().endsWith(".zip"));
  return inputs.length > 0 && outputs.length > 0 && inputs.some((file) => isPreviewable(file.name));
}

function renderResults(job) {
  const tray = $("results");
  const outputs = job.outputs || [];
  $("tray-empty").hidden = true;
  $("tray-count").textContent = String(outputs.length);
  $("tray-sub").textContent = `${job.tool_name || ""} · ${job.elapsed || 0}s`;
  if (!outputs.length) {
    tray.innerHTML = `<div class="result-error">没有可下载的文件。</div>`;
    tray.hidden = false;
    return;
  }
  const compareText = comparisonLine(job);
  const extraNote = job.note ? ` · ${job.note}` : "";
  const reuseTools = compatibleToolsForJob(job);
  tray.innerHTML = `
    <div class="results-head">
      <span class="results-note">${outputs.length} 个文件${compareText ? ` · ${compareText}` : ""}${extraNote ? escapeHtml(extraNote) : ""}</span>
      <div class="results-actions">
        ${canCompare(job) ? `<button type="button" class="mini-btn" data-compare><svg class="icon"><use href="#i-compare"/></svg>对比</button>` : ""}
        ${reuseTools.length ? `<button type="button" class="mini-btn" data-reuse><svg class="icon"><use href="#i-arrow"/></svg>继续处理</button>` : ""}
        <button type="button" class="mini-btn" data-clear>清除</button>
      </div>
    </div>
    ${outputs.slice(0, 40).map((file) => {
      const ext = (extOf(file.name).replace(".", "") || "FILE").toUpperCase().slice(0, 5);
      const previewable = isPreviewable(file.name);
      return `<div class="result new">
        ${previewable
          ? `<span class="result-thumb"><img src="${file.preview}" alt="" loading="lazy" onerror="this.style.display='none'"><span class="thumb-tag">${escapeHtml(ext)}</span></span>`
          : `<span class="result-thumb no-image"><span class="thumb-tag">${escapeHtml(ext)}</span></span>`}
        <div class="result-main">
          <span class="result-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
          <span class="result-size">${fmtSize(file.size)}</span>
        </div>
        <a class="result-dl" href="/api/jobs/${encodeURIComponent(job.id)}/download/${encodeURIComponent(file.name)}" title="下载" aria-label="下载 ${escapeHtml(file.name)}">
          <svg class="icon"><use href="#i-download"/></svg>
        </a>
      </div>`;
    }).join("")}
    ${outputs.length > 40 ? `<div class="result-more">只显示前 40 个文件，其余请用 ZIP 打包下载。</div>` : ""}
    ${outputs.length > 1 && !outputs.some((file) => file.name.toLowerCase().endsWith(".zip")) ? `<a class="zip-btn" href="/api/jobs/${encodeURIComponent(job.id)}/zip">
      <svg class="icon"><use href="#i-package"/></svg> 打包下载 ZIP
    </a>` : ""}
  `;
  tray.hidden = false;
  tray.querySelector("[data-compare]")?.addEventListener("click", () => openCompare(job));
  tray.querySelector("[data-reuse]")?.addEventListener("click", () => openReuse(job, reuseTools));
  tray.querySelector("[data-clear]")?.addEventListener("click", () => clearJob(true));
}

function compareCard(label, item) {
  if (!item) {
    return `<div class="compare-card">
      <div class="compare-label"><b>${label}</b></div>
      <div class="compare-img compare-empty">无对应文件</div>
    </div>`;
  }
  const ext = (extOf(item.name).replace(".", "") || "FILE").toUpperCase();
  const previewable = isPreviewable(item.name);
  return `<div class="compare-card">
    <div class="compare-label"><b title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</b><span>${fmtSize(item.size)}</span></div>
    ${previewable
      ? `<a class="compare-img" href="${item.preview}" target="_blank" rel="noopener"><img src="${item.preview}" alt="" loading="lazy" onerror="this.style.display='none'; this.parentElement.classList.add('compare-empty');"></a>`
      : `<div class="compare-img compare-empty">${escapeHtml(ext)}</div>`}
  </div>`;
}

function openCompare(job) {
  const inputs = job.inputs || [];
  const outputs = (job.outputs || []).filter((file) => isPreviewable(file.name) && !file.name.toLowerCase().endsWith(".zip"));
  if (!outputs.length) {
    toast("这个任务没有可预览的图片、PDF 或视频", true);
    return;
  }
  const count = Math.min(outputs.length, 4);
  const pairs = [];
  for (let index = 0; index < count; index += 1) {
    pairs.push(`<div class="compare-pair">
      ${compareCard("原文件", inputs[index] || null)}
      ${compareCard("输出", outputs[index])}
    </div>`);
  }
  const summary = comparisonLine(job);
  const foot = summary
    ? `${summary}${outputs.length > count ? ` · 仅显示前 ${count} 组` : ""}`
    : `共 ${outputs.length} 个输出文件`;
  openModal("前后对比", pairs.join(""), foot);
}

function openReuse(job, tools) {
  if (!tools.length) return;
  const body = `<p class="modal-note">选择一个目标工具，将直接使用上一步的输出文件与默认参数开始处理。需要改参数时，先关闭此窗口，再重新选择文件。</p>
    <div class="tool-pick-grid">
      ${tools.map((tool) => `<button type="button" class="tool-pick" data-tool="${tool.id}">
        <b>${escapeHtml(tool.name)}</b>
        <small>${escapeHtml(catById(tool.cat)?.name || "")} · ${escapeHtml(tool.route)}</small>
      </button>`).join("")}
    </div>`;
  openModal("用此结果继续处理", body, "");
  document.querySelectorAll(".tool-pick").forEach((button) => {
    button.addEventListener("click", () => {
      const tool = toolById(button.dataset.tool);
      if (tool) reuseResult(job, tool);
    });
  });
}

function renderJobError(job) {
  $("tray-empty").hidden = true;
  $("tray-count").textContent = "0";
  $("tray-sub").textContent = job.tool_name || "";
  const tray = $("results");
  tray.innerHTML = `<div class="results-head">
      <span class="results-note">任务失败</span>
      <div class="results-actions">
        <button type="button" class="mini-btn" data-retry><svg class="icon"><use href="#i-refresh"/></svg>重试</button>
        <button type="button" class="mini-btn" data-clear>清除</button>
      </div>
    </div>
    <div class="result-error">${escapeHtml(job.error || "处理失败，请检查文件后重试")}</div>`;
  tray.hidden = false;
  tray.querySelector("[data-retry]")?.addEventListener("click", () => retryJob(job));
  tray.querySelector("[data-clear]")?.addEventListener("click", () => clearJob(true));
}

function renderJobCancelled(job) {
  $("tray-empty").hidden = true;
  $("tray-count").textContent = "0";
  $("tray-sub").textContent = job.tool_name || "";
  const tray = $("results");
  tray.innerHTML = `<div class="results-head">
      <span class="results-note">任务已取消</span>
      <div class="results-actions">
        <button type="button" class="mini-btn" data-retry><svg class="icon"><use href="#i-refresh"/></svg>重试</button>
        <button type="button" class="mini-btn" data-clear>清除</button>
      </div>
    </div>
    <div class="result-error">未保留未完成的输出文件。可以重试，或回到左侧重新选择文件。</div>`;
  tray.hidden = false;
  tray.querySelector("[data-retry]")?.addEventListener("click", () => retryJob(job));
  tray.querySelector("[data-clear]")?.addEventListener("click", () => clearJob(true));
}

function addRecent(job) {
  state.recent = state.recent.filter((entry) => entry.id !== job.id);
  state.recent.unshift({
    id: job.id,
    tool: job.tool,
    name: job.tool_name,
    time: Math.round(job.created * 1000) || Date.now(),
    count: (job.outputs || []).length,
    status: job.status,
  });
  state.recent = state.recent.slice(0, 8);
  saveRecent();
  renderRecent();
}

function renderRecent() {
  const section = $("recent");
  const list = $("recent-list");
  if (!state.recent.length) {
    section.hidden = true;
    list.innerHTML = "";
    return;
  }
  section.hidden = false;
  list.innerHTML = state.recent.map((entry) => `
    <button type="button" class="recent-item" data-job="${escapeHtml(entry.id)}">
      <span class="recent-dot${entry.status === "error" ? " bad" : entry.status === "cancelled" ? " warn" : ""}"></span>
      <span class="recent-main">
        <span class="recent-name">${escapeHtml(entry.name || "任务")}</span>
        <span class="recent-meta">${timeAgo((entry.time || Date.now()) / 1000)} · ${entry.count || 0} 个文件</span>
      </span>
      <svg class="icon recent-arrow"><use href="#i-arrow"/></svg>
    </button>`).join("");
  list.querySelectorAll(".recent-item").forEach((button) => {
    button.addEventListener("click", async () => {
      if (state.busy) { toast("当前任务处理中，完成后再查看", true); return; }
      try {
        const job = await api(`/api/jobs/${encodeURIComponent(button.dataset.job)}`);
        if (job.status === "running" || job.status === "queued") {
          toast("这个任务还在处理中");
          return;
        }
        state.job = job;
        if (job.status === "cancelled") renderJobCancelled(job);
        else if (job.status === "error") renderJobError(job);
        else renderResults(job);
        if (window.innerWidth <= 980) $("results").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        toast("这个任务的文件已过期", true);
        state.recent = state.recent.filter((entry) => entry.id !== button.dataset.job);
        saveRecent();
        renderRecent();
      }
    });
  });
}

async function clearJob(removeOnServer = false) {
  if (state.busy) return;
  closeJobEvents();
  closeModal();
  const job = state.job;
  state.job = null;
  state.files = [];
  state.gallery = null;
  localStorage.removeItem(ACTIVE_JOB_KEY);
  $("pdf-gallery").hidden = true;
  renderQueue();
  hideProgress();
  clearTray();
  if (removeOnServer && job) {
    try { await fetch(`/api/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" }); } catch {}
  }
}

function openModal(title, body, foot = "") {
  state.modalReturnFocus = document.activeElement;
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = body;
  $("modal-foot").innerHTML = foot;
  $("modal-foot").hidden = !foot;
  $("modal").hidden = false;
  document.body.classList.add("modal-open");
  $("modal-close").focus();
}

function closeModal() {
  const modal = $("modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  if (state.modalReturnFocus && document.contains(state.modalReturnFocus)) {
    state.modalReturnFocus.focus();
  }
  state.modalReturnFocus = null;
}

/* ───────── 能力展示 / 事件 ───────── */

function renderCapabilities() {
  const caps = state.caps;
  const rows = [];
  if (caps.ffmpeg) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>FFmpeg <b>${escapeHtml(caps.ffmpeg)}</b></span></div>`);
  if (caps.ocr) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>OCR 中文 + 英文</span></div>`);
  if (caps.heic) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>HEIC / HEIF 读取</span></div>`);
  if (caps.avif) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>AVIF 读写</span></div>`);
  if (caps.matting) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>AI 抠图（U2-Netp）</span></div>`);
  if (caps.whisper) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>Whisper 本地字幕</span></div>`);
  if (caps.superres) rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>Real-ESRGAN 本地超分</span></div>`);
  if (caps.hw_encoder && caps.hw_encoder !== "CPU") rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>视频硬件加速 · ${escapeHtml(caps.hw_encoder)}</span></div>`);
  rows.push(`<div class="cap-row"><svg class="icon"><use href="#i-check"/></svg><span>单次最多 <b>${escapeHtml(caps.max_upload || "4 GB")}</b></span></div>`);
  $("cap-list").innerHTML = rows.join("");
}

function updateStats() {
  $("tool-count").textContent = String(state.tools.length);
  $("stat-tools").textContent = String(state.tools.length);
  $("stat-version").textContent = `v${state.caps.version || "1.4.1"}`;
  if (state.caps.ffmpeg) {
    const hw = state.caps.hw_encoder && state.caps.hw_encoder !== "CPU" ? ` · ${state.caps.hw_encoder}` : "";
    $("stat-ffmpeg").textContent = `FFmpeg ${state.caps.ffmpeg}${hw}`;
  }
  const formats = [state.caps.heic ? "HEIC" : "", state.caps.avif ? "AVIF" : ""].filter(Boolean).join(" / ");
  $("stat-formats").textContent = formats ? `${formats} 支持` : "图片格式";
}

function wireEvents() {
  const drop = $("drop");
  const input = $("file-input");
  const folderInput = $("folder-input");
  drop.addEventListener("click", () => { if (!state.busy) input.click(); });
  $("pick-folder").addEventListener("click", (event) => {
    event.stopPropagation();
    if (!state.busy) folderInput.click();
  });
  drop.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && !state.busy) {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    addFiles(input.files);
    input.value = "";
  });
  folderInput.addEventListener("change", () => {
    if (state.busy) return;
    const result = addFiles(folderInput.files);
    if (result.added) toast(`已从文件夹加入 ${result.added} 个文件`);
    folderInput.value = "";
  });
  ["dragenter", "dragover"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      if (!state.busy) drop.classList.add("dragover");
    });
  });
  ["dragleave", "dragend"].forEach((name) => {
    drop.addEventListener(name, () => drop.classList.remove("dragover"));
  });
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("dragover");
    addFiles(event.dataTransfer?.files);
  });
  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());

  window.addEventListener("paste", (event) => {
    if (!state.activeTool || state.busy) return;
    if (!state.activeTool.accept.some((ext) => [".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".bmp", ".tif", ".tiff", ".gif"].includes(ext))) return;
    const items = Array.from(event.clipboardData?.items || []);
    const image = items.find((item) => item.type.startsWith("image/"));
    if (!image) return;
    const file = image.getAsFile();
    if (file) {
      addFiles([file], true);
      toast("已从剪贴板添加图片");
    }
  });

  $("start").addEventListener("click", startJob);
  $("clear").addEventListener("click", () => clearJob(true));
  $("cancel").addEventListener("click", requestCancel);
  $("fav-toggle").addEventListener("click", toggleFavorite);
  $("lan-btn").addEventListener("click", openLanModal);
  $("gallery-reset").addEventListener("click", () => resetPdfGallery());
  $("gallery-reload").addEventListener("click", () => {
    if (state.files[0]) loadPdfGallery(state.files[0], true);
  });
  $("reset-options").addEventListener("click", () => {
    const tool = state.activeTool;
    if (!tool) return;
    localStorage.removeItem(optionStorageKey(tool.id));
    renderOptions(tool);
    toast("已恢复默认参数");
  });
  $("modal-close").addEventListener("click", closeModal);
  document.querySelector("#modal [data-close-modal]").addEventListener("click", closeModal);

  $("search").addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    renderTools();
    if (state.search) {
      const tools = visibleTools();
      $("list-label").textContent = "搜索结果";
      if (tools.length) $("rail-sep").querySelector("span:last-child").textContent = tools.length;
    }
  });
  $("search").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.target.value = "";
      state.search = "";
      renderTools();
      event.target.blur();
    }
    if (event.key === "Enter") {
      const first = visibleTools()[0];
      if (first && !state.busy) selectTool(first.id);
    }
  });
  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    if (event.key === "/" && $("modal").hidden && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
      event.preventDefault();
      $("search").focus();
    }
    if (event.key === "Escape" && state.search) {
      state.search = "";
      $("search").value = "";
      renderTools();
    }
    if (event.key === "Escape" && !$("modal").hidden) {
      closeModal();
      return;
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && $("modal").hidden) {
      startJob();
    }
  });
  $("recent-clear").addEventListener("click", () => {
    state.recent = [];
    saveRecent();
    renderRecent();
  });
}

document.addEventListener("DOMContentLoaded", init);
