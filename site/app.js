const byId = id => document.getElementById(id);
const dialog = byId("skill-dialog");
const heroVideo = byId("feature-video");
const detailVideo = byId("detail-video");
const seek = byId("feature-seek");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const repositoryDefault = "https://github.com/qianqiu-max/cutcraft-skills";
let skills = [];
let featured = null;
let selected = null;
let category = "";
let featuredManuallyPaused = false;
let restoreHeroPlayback = false;
let lastInvoker = null;
let toastTimer;

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

function icon(name) {
  const symbol = element("span", "icon i-" + name);
  symbol.setAttribute("aria-hidden", "true");
  return symbol;
}

function pageUrl() {
  return window.location.pathname + window.location.search;
}

function detailHash(id) {
  return "#skill=" + encodeURIComponent(id);
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "--:--";
  const total = Math.max(0, Math.floor(seconds));
  return [Math.floor(total / 60), total % 60].map(n => String(n).padStart(2, "0")).join(":");
}

function updateTime() {
  const duration = heroVideo.duration;
  const time = heroVideo.currentTime;
  byId("play-time").textContent = formatTime(time);
  byId("total-time").textContent = formatTime(duration);
  const progress = duration > 0 ? time / duration * 100 : 0;
  seek.value = String(progress);
  seek.style.setProperty("--progress", progress + "%");
  seek.setAttribute("aria-valuetext", formatTime(time) + " / " + formatTime(duration));
}

function updatePlayButton() {
  const paused = heroVideo.paused;
  const button = byId("feature-play");
  button.setAttribute("aria-label", paused ? "播放预览" : "暂停预览");
  button.firstElementChild.className = paused ? "icon i-play" : "icon i-pause";
}

function maybePlayHero() {
  if (!featured || document.hidden || dialog.open || featuredManuallyPaused || reducedMotion.matches) return;
  heroVideo.play().catch(() => updatePlayButton());
}

function setFeatured(skill) {
  featured = skill;
  byId("feature-title").textContent = skill.title;
  byId("feature-summary").textContent = skill.summary;
  byId("feature-actions").hidden = false;
  byId("feature-detail").href = detailHash(skill.id);
  byId("feature-controls").hidden = false;
  byId("media-error").hidden = true;
  heroVideo.setAttribute("aria-label", skill.title + "效果预览");
  heroVideo.poster = skill.poster;
  heroVideo.src = skill.video;
  maybePlayHero();
}

byId("feature-play").addEventListener("click", async () => {
  if (heroVideo.paused) {
    featuredManuallyPaused = false;
    try { await heroVideo.play(); }
    catch { byId("media-error").hidden = false; }
  } else {
    featuredManuallyPaused = true;
    heroVideo.pause();
  }
});
heroVideo.addEventListener("play", updatePlayButton);
heroVideo.addEventListener("pause", updatePlayButton);
heroVideo.addEventListener("durationchange", updateTime);
heroVideo.addEventListener("timeupdate", updateTime);
heroVideo.addEventListener("error", () => { byId("media-error").hidden = false; });
seek.addEventListener("input", () => {
  if (Number.isFinite(heroVideo.duration)) heroVideo.currentTime = Number(seek.value) / 100 * heroVideo.duration;
});
const player = byId("feature-player");
const expand = byId("feature-expand");
if (player.requestFullscreen && document.fullscreenEnabled) {
  expand.hidden = false;
  expand.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement === player) await document.exitFullscreen();
      else await player.requestFullscreen();
    } catch { notify("当前浏览器无法进入全屏。"); }
  });
  document.addEventListener("fullscreenchange", () => expand.setAttribute("aria-label", document.fullscreenElement === player ? "退出全屏" : "全屏预览"));
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { heroVideo.pause(); detailVideo.pause(); }
  else maybePlayHero();
});
reducedMotion.addEventListener("change", event => {
  if (event.matches) heroVideo.pause();
  else maybePlayHero();
});

function renderFilters() {
  const labels = ["", ...new Set(skills.map(skill => skill.category))];
  byId("filters").replaceChildren(...labels.map(label => {
    const button = element("button", "filter", label || "全部");
    button.type = "button";
    button.dataset.category = label;
    button.setAttribute("aria-pressed", String(category === label));
    button.addEventListener("click", () => {
      category = label;
      for (const item of byId("filters").children) item.setAttribute("aria-pressed", String(item.dataset.category === category));
      renderCards();
    });
    return button;
  }));
}

function card(skill, index) {
  const article = element("article", "card");
  const main = element("a", "card-main");
  main.href = detailHash(skill.id);
  main.dataset.skill = skill.id;
  const titleId = "card-heading-" + index;
  main.setAttribute("aria-labelledby", titleId);
  const media = element("div", "card-media");
  const image = element("img");
  image.src = skill.poster;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.width = 640;
  image.height = 360;
  const play = element("span", "card-play");
  play.setAttribute("aria-hidden", "true");
  play.append(icon("play"));
  media.append(image, play);
  const body = element("div", "card-body");
  const heading = element("h3", "", skill.title);
  heading.id = titleId;
  body.append(element("span", "card-category", skill.category), heading, element("p", "card-summary", skill.summary));
  main.append(media, body);
  const footer = element("div", "card-end");
  const copy = element("button", "quick-copy");
  copy.type = "button";
  copy.setAttribute("aria-label", "复制" + skill.title + "提示词");
  copy.append(icon("copy"), document.createTextNode("复制提示词"));
  copy.addEventListener("click", () => copyPrompt(skill, copy));
  footer.append(element("span", "card-engine", skill.engine), copy);
  article.append(main, footer);
  return article;
}

function renderCards() {
  const query = byId("search").value.trim().toLocaleLowerCase();
  const words = query.split(/\s+/).filter(Boolean);
  const matches = skills.filter(skill => {
    const text = [skill.title, skill.category, skill.engine, skill.summary, skill.id, ...skill.inputs].join(" ").toLocaleLowerCase();
    return (!category || category === skill.category) && words.every(word => text.includes(word));
  });
  byId("cards").replaceChildren(...matches.map(card));
  byId("empty").hidden = matches.length > 0;
  byId("library-count").textContent = String(matches.length) + " 项";
  byId("results-status").textContent = "找到 " + matches.length + " 项配方";
}

byId("search").addEventListener("input", renderCards);
byId("reset").addEventListener("click", () => {
  category = "";
  byId("search").value = "";
  renderFilters();
  renderCards();
  byId("search").focus();
});

function notify(message) {
  if (dialog.open) {
    byId("detail-status").textContent = message;
    return;
  }
  const toast = byId("toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toastTimer = setTimeout(() => { toast.textContent = ""; }, 3000);
}

function manualCopy(text) {
  const host = dialog.open ? dialog : document.body;
  const field = element("textarea", "sr-only");
  field.value = text;
  field.setAttribute("readonly", "");
  field.setAttribute("aria-label", "待复制提示词");
  const previous = document.activeElement;
  host.append(field);
  field.focus({ preventScroll: true });
  field.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch { /* Manual selection follows. */ }
  field.remove();
  if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
  return copied;
}

async function copyPrompt(skill, invoker) {
  if (!skill) return;
  let copied = false;
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(skill.prompt); copied = true; }
    catch { /* Embedded or offline previews can reject clipboard access. */ }
  }
  if (!copied) copied = manualCopy(skill.prompt);
  if (copied) {
    notify("提示词已复制，可粘贴到你的 Agent。");
    return;
  }
  openSkill(skill, invoker);
  const field = byId("detail-prompt");
  field.focus({ preventScroll: true });
  field.select();
  notify("已选中完整提示词，请使用系统复制命令。");
}

function showSkill(skill) {
  if (dialog.open && selected?.id === skill.id) return;
  selected = skill;
  if (!dialog.open) restoreHeroPlayback = !heroVideo.paused;
  heroVideo.pause();
  detailVideo.pause();
  byId("detail-title").textContent = skill.title;
  byId("detail-category").textContent = skill.category;
  byId("detail-summary").textContent = skill.summary;
  byId("detail-inputs").replaceChildren(...skill.inputs.map(input => element("li", "", input)));
  byId("detail-engine").textContent = skill.engine;
  byId("detail-prompt").value = skill.prompt;
  byId("detail-source").href = skill.skillUrl;
  const download = byId("detail-download");
  download.hidden = !skill.download;
  if (skill.download) download.href = skill.download;
  else download.removeAttribute("href");
  byId("detail-status").textContent = "";
  detailVideo.poster = skill.poster;
  detailVideo.src = skill.video;
  detailVideo.setAttribute("aria-label", skill.title + "视频预览");
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}

function openSkill(skill, invoker) {
  if (invoker && !dialog.contains(invoker)) lastInvoker = invoker;
  if (location.hash !== detailHash(skill.id)) {
    history.pushState({ cutcraftDetail: true }, "", detailHash(skill.id));
  }
  showSkill(skill);
}

document.addEventListener("click", event => {
  const link = event.target.closest?.('a[href^="#skill="]');
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const skill = skills.find(item => detailHash(item.id) === link.hash);
  if (!skill) return;
  event.preventDefault();
  openSkill(skill, link);
});
byId("feature-copy").addEventListener("click", event => copyPrompt(featured, event.currentTarget));
byId("detail-copy").addEventListener("click", event => copyPrompt(selected, event.currentTarget));

function syncLocation() {
  if (!skills.length) return;
  const skill = skills.find(item => detailHash(item.id) === location.hash);
  if (skill) { showSkill(skill); return; }
  if (dialog.open) dialog.close();
  if (location.hash.startsWith("#skill=")) notify("未找到这个配方，请从配方库重新选择。");
}
function dismissDetail() {
  if (dialog.open) dialog.close();
}
byId("detail-close").addEventListener("click", dismissDetail);
dialog.addEventListener("click", event => {
  if (event.target !== dialog) return;
  const box = dialog.getBoundingClientRect();
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dismissDetail();
});
dialog.addEventListener("close", () => {
  detailVideo.pause();
  if (selected && location.hash === detailHash(selected.id)) {
    if (history.state?.cutcraftDetail) history.back();
    else history.replaceState(null, "", pageUrl());
  }
  selected = null;
  if (restoreHeroPlayback) maybePlayHero();
  restoreHeroPlayback = false;
  if (lastInvoker?.isConnected) lastInvoker.focus({ preventScroll: true });
  lastInvoker = null;
});
window.addEventListener("hashchange", syncLocation);
window.addEventListener("popstate", syncLocation);

async function loadCatalog() {
  byId("load-error").hidden = true;
  try {
    const response = await fetch("./catalog.json");
    if (!response.ok) throw new Error("Catalog unavailable");
    const catalog = await response.json();
    skills = [...catalog.skills].sort((a, b) => a.order - b.order);
    if (!skills.length) throw new Error("Empty catalog");
    for (const link of document.querySelectorAll("[data-repository]")) link.href = catalog.repository || repositoryDefault;
    setFeatured(skills.find(skill => skill.featured) || skills[0]);
    renderFilters();
    renderCards();
    syncLocation();
  } catch {
    byId("load-error").hidden = false;
    byId("empty").hidden = true;
    byId("results-status").textContent = "配方目录加载失败，请重试。";
  }
}
byId("retry").addEventListener("click", loadCatalog);
loadCatalog();
