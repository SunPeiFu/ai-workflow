const remixState = {
  analysis: null,
  lightboxImages: [],
  lightboxIndex: 0,
  rewriteField: "",
  selectedRewriteByField: {},
  emojiFields: {
    title: false,
    body: false,
  },
  rewriteModels: [],
  rewriteModel: "",
  selectedPackageFile: "",
  packageContents: [],
  selectedContentId: "",
  activeTab: "extract",
  selectedContentByTab: {},
  packagePageByTab: {},
  uploadPreviewUrls: {},
};

const $ = (id) => document.getElementById(id);

function setRemixStatus(text, kind = "") {
  const pill = $("remixStatus");
  pill.textContent = text;
  pill.className = `status-pill ${kind}`.trim();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `请求失败: ${path}`);
  }
  return data;
}

function remixPayload() {
  return {
    url: $("sourceUrl").value.trim(),
  };
}

function splitLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

async function analyzeLink() {
  setRemixStatus("拆解中", "busy");
  const data = await api("/api/remix/analyze", {
    method: "POST",
    body: JSON.stringify(remixPayload()),
  });
  remixState.analysis = data;
  renderAnalysis(data);
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("拆解完成");
}

function renderAnalysis(data) {
  const copywriting = data.copywriting || {};
  $("titleText").textContent = copywriting.title || "未读取到标题，可在左侧手动补充后重新拆解。";
  $("bodyText").textContent = copywriting.body || "未读取到正文，可在左侧手动补充后重新拆解。";
  $("tagsText").textContent = (copywriting.tags || []).map((tag) => `#${tag}`).join(" ") || "未读取到标签。";
  $("copyAllBtn").disabled = false;
  $("xiaohongshuFlowBtn").disabled = false;
  $("jianyingFlowBtn").disabled = false;
  $("jianyingBtn").disabled = false;
  $("affiliatePlanBtn").disabled = false;
  $("affiliateJianyingBtn").disabled = false;
  renderImages(data.images || []);
}

function copyFieldId(field) {
  return {
    title: "titleText",
    body: "bodyText",
    tags: "tagsText",
  }[field];
}

function copyFieldLabel(field) {
  return {
    title: "标题",
    body: "正文",
    tags: "标签",
  }[field] || "文案";
}

function copyFields() {
  return ["title", "body", "tags"];
}

function tagsFromText(text) {
  return text
    .split(/[\s,，、]+/)
    .map((tag) => tag.trim().replace(/^#+/, ""))
    .filter(Boolean);
}

function tagsToText(tags) {
  return (tags || []).map((tag) => `#${String(tag).replace(/^#+/, "")}`).join(" ");
}

function refreshCopyText() {
  const copywriting = remixState.analysis?.copywriting;
  if (!copywriting) return;
  copywriting.copy_text = [
    copywriting.title,
    copywriting.body,
    tagsToText(copywriting.tags),
  ].filter(Boolean).join("\n\n");
}

function syncCopyFieldFromEditable(field, normalizeDisplay = false) {
  const copywriting = remixState.analysis?.copywriting;
  const targetId = copyFieldId(field);
  if (!copywriting || !targetId) return;
  const target = $(targetId);
  const value = target.textContent.trim();
  if (field === "tags") {
    const tags = tagsFromText(value);
    copywriting.tags = tags;
    if (normalizeDisplay) target.textContent = tagsToText(tags);
  } else {
    copywriting[field] = value;
  }
  refreshCopyText();
}

function syncCopyFieldsFromEditable(normalizeDisplay = false) {
  for (const field of copyFields()) {
    syncCopyFieldFromEditable(field, normalizeDisplay);
  }
}

function setCopyFieldValue(field, value) {
  const targetId = copyFieldId(field);
  if (!targetId) return;
  $(targetId).textContent = value;
  syncCopyFieldFromEditable(field, true);
}

function setupEditableCopyFields() {
  for (const field of copyFields()) {
    const targetId = copyFieldId(field);
    const target = $(targetId);
    target.contentEditable = "plaintext-only";
    target.tabIndex = 0;
    target.role = "textbox";
    target.dataset.copyField = field;
    target.setAttribute("aria-label", `${copyFieldLabel(field)}，点击后可直接编辑`);
    target.classList.add("copy-editable");
    target.addEventListener("focus", () => {
      target.classList.add("is-editing");
      setRemixStatus(`正在编辑${copyFieldLabel(field)}`);
    });
    target.addEventListener("blur", () => {
      target.classList.remove("is-editing");
      syncCopyFieldFromEditable(field, true);
      if (remixState.analysis) writeResult(remixState.analysis);
      setRemixStatus("已保存编辑");
    });
    target.addEventListener("input", () => syncCopyFieldFromEditable(field, false));
    target.addEventListener("paste", (event) => {
      event.preventDefault();
      const text = event.clipboardData?.getData("text/plain") || "";
      document.execCommand("insertText", false, text);
      syncCopyFieldFromEditable(field, false);
    });
    target.addEventListener("keydown", (event) => {
      const saveShortcut = (event.metaKey || event.ctrlKey) && event.key === "Enter";
      const singleLineEnter = (field === "title" || field === "tags") && event.key === "Enter";
      if (saveShortcut || singleLineEnter) {
        event.preventDefault();
        target.blur();
      }
    });
  }
}

function renderImages(images) {
  const list = $("imageList");
  list.innerHTML = "";
  if (!images.length) {
    list.textContent = "暂无图片。可以在左侧粘贴图片 URL 或本地素材路径后重新拆解。";
    $("deleteImagesBtn").disabled = true;
    return;
  }
  $("deleteImagesBtn").disabled = selectedImageValues().length > 0;
  remixState.lightboxImages = images.map((image) => imagePreviewUrl(image)).filter(Boolean);
  for (const [index, image] of images.entries()) {
    const value = imageValue(image);
    const card = document.createElement("article");
    card.className = "remix-image-card";
    const preview = document.createElement("div");
    preview.className = "remix-image-preview";
    const thumbnail = document.createElement("img");
    thumbnail.alt = "拆解图片预览";
    thumbnail.loading = "lazy";
    thumbnail.referrerPolicy = "no-referrer";
    thumbnail.addEventListener("load", () => applyImageAspectRatio(thumbnail, card));
    thumbnail.addEventListener("dblclick", () => openImageLightbox(index));
    preview.addEventListener("dblclick", () => openImageLightbox(index));
    thumbnail.addEventListener("error", () => {
      preview.classList.add("is-broken");
      preview.textContent = "图片无法预览";
    });
    thumbnail.src = imagePreviewUrl(image);
    applyImageAspectRatio(thumbnail, card);
    preview.appendChild(thumbnail);
    const select = document.createElement("label");
    select.className = "remix-image-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = value;
    checkbox.checked = Boolean(image.selected);
    checkbox.title = value;
    checkbox.addEventListener("change", updateImageActionState);
    select.title = value;
    select.setAttribute("aria-label", "选择图片");
    select.appendChild(checkbox);
    card.append(preview, select);
    list.appendChild(card);
  }
  updateImageActionState();
}

function applyImageAspectRatio(image, card) {
  if (!image?.naturalWidth || !image?.naturalHeight || !card) return;
  const ratio = image.naturalWidth / image.naturalHeight;
  if (!Number.isFinite(ratio) || ratio <= 0) return;
  card.style.setProperty("--image-ratio", `${image.naturalWidth} / ${image.naturalHeight}`);
  card.dataset.imageOrientation = ratio < 0.85 ? "portrait" : ratio > 1.25 ? "landscape" : "square";
}

function imageValue(image) {
  return String(image?.url || image?.path || "").trim();
}

function imagePreviewUrl(image) {
  const value = imageValue(image);
  return image?.preview_url || remixState.uploadPreviewUrls[value] || value;
}

function openImageLightbox(index = 0) {
  if (!remixState.lightboxImages.length) return;
  const box = $("imageLightbox");
  remixState.lightboxIndex = normalizeLightboxIndex(index);
  renderLightboxImage();
  box.classList.remove("is-hidden");
}

function renderLightboxImage() {
  const url = remixState.lightboxImages[remixState.lightboxIndex] || "";
  $("imageLightboxImg").src = url;
  $("imageLightboxCounter").textContent = `${remixState.lightboxIndex + 1} / ${remixState.lightboxImages.length}`;
  const hasMultiple = remixState.lightboxImages.length > 1;
  $("imageLightboxPrev").disabled = !hasMultiple;
  $("imageLightboxNext").disabled = !hasMultiple;
}

function showLightboxOffset(offset) {
  if ($("imageLightbox").classList.contains("is-hidden")) return;
  remixState.lightboxIndex = normalizeLightboxIndex(remixState.lightboxIndex + offset);
  renderLightboxImage();
}

function normalizeLightboxIndex(index) {
  const length = remixState.lightboxImages.length;
  if (!length) return 0;
  return ((Number(index) || 0) % length + length) % length;
}

function closeImageLightbox() {
  const box = $("imageLightbox");
  const image = $("imageLightboxImg");
  box.classList.add("is-hidden");
  image.removeAttribute("src");
}

async function createPackage() {
  if (!remixState.analysis) throw new Error("请先拆解链接");
  setRemixStatus("生成包", "busy");
  const data = await api("/api/remix/package", {
    method: "POST",
    body: JSON.stringify({
      analysis: selectedAnalysis(),
      package_name: packageName(),
    }),
  });
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("Ready");
  return data;
}

async function createPackageAndGo(tab) {
  await createPackage();
  setActiveTab(tab);
  setRemixStatus(tab === "jianying" ? "已生成基础素材包，可在剪映视频历史继续生成视频包" : "已生成基础素材包，可在小红书图文历史继续生成图文包");
}

async function createXiaohongshuPackageAndGo() {
  const packageData = await createPackage();
  setActiveTab("xiaohongshu");
  const content = currentPackageContent("xiaohongshu");
  if (!content) {
    setRemixStatus("已生成基础素材包，请在小红书图文历史中手动生成图文包");
    return;
  }
  setRemixStatus("小红书图文包生成中", "busy");
  const data = await api("/api/remix/content/xiaohongshu-generate", {
    method: "POST",
    body: JSON.stringify({ id: content.id, source_package_path: packageData.package_path || "" }),
  });
  writeResult(data);
  await loadPackageHistory();
  setActiveTab("xiaohongshu");
  selectContent(content.id);
  renderXiaohongshuGenerationResult(data);
  setRemixStatus("小红书图文包已按当前图片重新生成");
}

function currentPackageContent(tab = remixState.activeTab) {
  const sourceUrl = String(remixState.analysis?.url || "").trim();
  const title = String(remixState.analysis?.copywriting?.title || "").trim();
  const contents = filterContentsForTab(remixState.packageContents, tab);
  return (
    contents.find((item) => sourceUrl && item.source_url === sourceUrl) ||
    contents.find((item) => title && item.title === title) ||
    null
  );
}

async function createJianyingPackage() {
  if (!remixState.analysis) throw new Error("请先拆解链接");
  setRemixStatus("生成剪映包", "busy");
  const data = await api("/api/remix/jianying", {
    method: "POST",
    body: JSON.stringify({
      analysis: selectedAnalysis(),
      package_name: `${packageName()}-jianying`,
      launch: $("launchJianying").checked,
    }),
  });
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("Ready");
}

async function createAffiliatePlan() {
  if (!remixState.analysis) throw new Error("请先拆解链接");
  setRemixStatus("生成带货方案", "busy");
  const data = await api("/api/remix/affiliate-plan", {
    method: "POST",
    body: JSON.stringify({
      analysis: selectedAnalysis(),
      product_name: $("affiliateProductName").value.trim(),
      product_category: $("affiliateProductCategory").value.trim(),
      selling_points: $("affiliateSellingPoints").value.trim(),
      pain_point: $("affiliatePainPoint").value.trim(),
    }),
  });
  renderAffiliatePlan(data);
  writeResult(data);
  setRemixStatus("Ready");
}

async function createAffiliateJianyingPackage() {
  if (!remixState.analysis) throw new Error("请先拆解链接");
  setRemixStatus("生成剪映工作包", "busy");
  const data = await api("/api/remix/affiliate-jianying", {
    method: "POST",
    body: JSON.stringify({
      analysis: selectedAnalysis(),
      product_name: $("affiliateProductName").value.trim(),
      product_category: $("affiliateProductCategory").value.trim(),
      selling_points: $("affiliateSellingPoints").value.trim(),
      pain_point: $("affiliatePainPoint").value.trim(),
      package_name: `${packageName()}-带货剪映包`,
      launch: $("launchJianying").checked,
    }),
  });
  renderAffiliateHandoff(data);
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("Ready");
}

function renderAffiliateHandoff(data) {
  const box = $("affiliatePlanResult");
  const block = document.createElement("section");
  block.className = "affiliate-list-block";
  const title = document.createElement("h3");
  title.textContent = "剪映工作包已生成";
  const dir = document.createElement("p");
  dir.textContent = data.handoff_dir || "";
  const list = document.createElement("ul");
  for (const file of data.files || []) {
    const item = document.createElement("li");
    item.textContent = file;
    list.appendChild(item);
  }
  block.append(title, dir, list);
  box.prepend(block);
}

async function loadPackageHistory() {
  const data = await api("/api/remix/packages");
  remixState.packageContents = data.contents || [];
  renderPackageHistory();
}

function historyElements(tab = remixState.activeTab) {
  const config = {
    extract: {
      list: "",
      detail: "",
      editorTitle: "",
      saveButton: "",
      editor: "",
    },
    jianying: {
      list: "jianyingHistoryList",
      detail: "jianyingContentDetail",
      editorTitle: "jianyingEditorTitle",
      saveButton: "jianyingSaveFileBtn",
      editor: "jianyingFileEditor",
    },
    xiaohongshu: {
      list: "xiaohongshuHistoryList",
      detail: "",
      editorTitle: "",
      saveButton: "",
      editor: "",
      pager: "xiaohongshuHistoryPager",
    },
  }[tab];
  return {
    list: config.list ? $(config.list) : null,
    detail: config.detail ? $(config.detail) : null,
    editorTitle: config.editorTitle ? $(config.editorTitle) : null,
    saveButton: config.saveButton ? $(config.saveButton) : null,
    editor: config.editor ? $(config.editor) : null,
    pager: config.pager ? $(config.pager) : null,
  };
}

function packageGroupsForTab(tab) {
  return {
    extract: ["remix"],
    jianying: ["remix", "jianying", "affiliate-jianying"],
    xiaohongshu: ["remix", "xiaohongshu-note"],
  }[tab] || [];
}

function filterPackagesForTab(content, tab = remixState.activeTab) {
  const groups = new Set(packageGroupsForTab(tab));
  return (content.packages || []).filter((item) => groups.has(item.group));
}

function filterContentsForTab(contents, tab = remixState.activeTab) {
  return contents
    .map((content) => {
      const allPackages = content.packages || [];
      const packages = filterPackagesForTab(content, tab);
      return {
        ...content,
        allPackages,
        packages,
        package_count: packages.length,
        file_count: packages.reduce((total, packageItem) => total + (packageItem.files || []).length, 0),
      };
    })
    .filter((content) => content.packages.length);
}

function renderPackageHistory() {
  const tab = remixState.activeTab;
  if (tab === "extract") return;
  const contents = filterContentsForTab(remixState.packageContents, tab);
  const { list, pager } = historyElements(tab);
  if (!list) return;
  list.innerHTML = "";
  if (pager) pager.innerHTML = "";
  if (!contents.length) {
    list.textContent = emptyHistoryText(tab);
    renderContentDetail(null);
    return;
  }
  const pageInfo = historyPageItems(contents, tab);
  for (const item of pageInfo.items) {
    const card = document.createElement("article");
    card.className = "package-history-card";
    card.dataset.contentId = item.id;
    const title = document.createElement("div");
    title.className = "package-history-title";
    title.textContent = `标题：${item.title || "未命名内容"}`;
    const meta = document.createElement("div");
    meta.className = "package-history-meta";
    meta.textContent = `平台：${platformName(item.platform)} · 素材包：${item.package_count}`;
    const status = document.createElement("div");
    status.className = "package-workflow-status";
    status.appendChild(packageStatusBadge(item, tab));
    if (tab !== "xiaohongshu") status.appendChild(packageWorkflowSteps(item));
    const source = document.createElement("div");
    source.className = "package-history-source";
    source.textContent = `链接：${item.source_url || "无来源链接"}`;
    const actions = document.createElement("div");
    actions.className = "package-history-actions";
    const viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.className = "text-btn";
    viewBtn.textContent = "查看详情";
    viewBtn.addEventListener("click", () => selectContent(item.id));
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "text-btn";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => selectContent(item.id, true));
    const tabActionButtons = packageActionButtons(item);
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "text-btn danger-text-btn";
    deleteBtn.textContent = "删除";
    deleteBtn.addEventListener("click", () => deleteContent(item.id, item.title || item.source_url));
    const baseButtons = tab === "xiaohongshu" ? [] : [viewBtn, editBtn];
    actions.append(...baseButtons, ...tabActionButtons, deleteBtn);
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      selectContent(item.id);
    });
    card.append(title, meta, status, source, actions);
    list.appendChild(card);
  }
  renderHistoryPager(tab, contents.length, pageInfo.page, pageInfo.totalPages);
  const selectedId = remixState.selectedContentByTab[tab] || remixState.selectedContentId;
  const selected = pageInfo.items.find((item) => item.id === selectedId) || pageInfo.items[0];
  selectContent(selected.id);
}

function historyPageSize(tab) {
  return tab === "xiaohongshu" ? 6 : Number.POSITIVE_INFINITY;
}

function historyPageItems(contents, tab) {
  const pageSize = historyPageSize(tab);
  if (!Number.isFinite(pageSize)) {
    return { items: contents, page: 1, totalPages: 1 };
  }
  const totalPages = Math.max(1, Math.ceil(contents.length / pageSize));
  const requestedPage = Number(remixState.packagePageByTab[tab]) || 1;
  const page = Math.min(Math.max(1, requestedPage), totalPages);
  remixState.packagePageByTab[tab] = page;
  const start = (page - 1) * pageSize;
  return {
    items: contents.slice(start, start + pageSize),
    page,
    totalPages,
  };
}

function renderHistoryPager(tab, totalItems, page, totalPages) {
  const { pager } = historyElements(tab);
  if (!pager) return;
  pager.innerHTML = "";
  const count = document.createElement("span");
  count.textContent = `共 ${totalItems} 个项目 · 第 ${page}/${totalPages} 页`;
  const prev = document.createElement("button");
  prev.type = "button";
  prev.className = "text-btn";
  prev.textContent = "上一页";
  prev.disabled = page <= 1;
  prev.addEventListener("click", () => {
    remixState.packagePageByTab[tab] = page - 1;
    renderPackageHistory();
  });
  const next = document.createElement("button");
  next.type = "button";
  next.className = "text-btn";
  next.textContent = "下一页";
  next.disabled = page >= totalPages;
  next.addEventListener("click", () => {
    remixState.packagePageByTab[tab] = page + 1;
    renderPackageHistory();
  });
  pager.append(count, prev, next);
}

function emptyHistoryText(tab) {
  return {
    extract: "暂无基础素材包。请先在素材拆解 tab 生成图文/视频包。",
    jianying: "暂无可用于剪映的视频素材。请先在素材拆解 tab 生成基础素材包。",
    xiaohongshu: "暂无可用于小红书的拆解内容。请先在素材拆解 tab 生成基础素材包。",
  }[tab] || "暂无生成内容。";
}

function packageStatusBadge(item, tab = remixState.activeTab) {
  const status = workflowStatusForContent(item, tab);
  const badge = document.createElement("span");
  badge.className = `workflow-status-badge ${status.kind}`;
  badge.textContent = status.text;
  return badge;
}

function packageWorkflowSteps(item) {
  const steps = document.createElement("div");
  steps.className = "package-workflow-steps";
  for (const step of workflowStepsForContent(item)) {
    const node = document.createElement("span");
    node.className = `workflow-step ${step.state}`;
    node.textContent = step.label;
    steps.appendChild(node);
  }
  return steps;
}

function workflowStepsForContent(item) {
  const groups = packageGroupSet(item);
  return [
    { label: "拆解", state: groups.has("remix") ? "done" : "todo" },
    { label: "剪映", state: groups.has("jianying") || groups.has("affiliate-jianying") ? "done" : "todo" },
    { label: "小红书", state: groups.has("xiaohongshu-note") ? "done" : "todo" },
  ];
}

function workflowStatusForContent(item, tab = remixState.activeTab) {
  const groups = packageGroupSet(item);
  if (tab === "jianying") {
    if (groups.has("affiliate-jianying")) return { text: "带货剪映包已生成", kind: "ready" };
    if (groups.has("jianying")) return { text: "剪映包已生成", kind: "ready" };
    if (groups.has("remix")) return { text: "待生成剪映任务", kind: "pending" };
  }
  if (tab === "xiaohongshu") {
    if (groups.has("xiaohongshu-note")) return { text: "小红书图文包已生成", kind: "ready" };
    if (groups.has("remix")) return { text: "待生成图文包", kind: "pending" };
  }
  if (groups.has("remix")) return { text: "已拆解", kind: "ready" };
  return { text: "缺少基础素材包", kind: "blocked" };
}

function packageGroupSet(item) {
  return new Set((item.allPackages || item.packages || []).map((packageItem) => packageItem.group));
}

function packageActionButtons(item) {
  if (remixState.activeTab === "jianying") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-btn jianying-generate-btn";
    const groups = packageGroupSet(item);
    button.textContent = groups.has("jianying") || groups.has("affiliate-jianying") ? "调用剪映" : "生成剪映任务";
    button.addEventListener("click", () => startJianyingGeneration(item.id, button));
    return [button];
  }
  if (remixState.activeTab === "xiaohongshu") {
    const groups = packageGroupSet(item);
    const generateBtn = document.createElement("button");
    generateBtn.type = "button";
    generateBtn.className = "text-btn xiaohongshu-generate-btn";
    generateBtn.textContent = groups.has("xiaohongshu-note") ? "重新生成图文包" : "生成图文包";
    generateBtn.addEventListener("click", () => startXiaohongshuGeneration(item.id, generateBtn));
    if (!groups.has("xiaohongshu-note")) return [generateBtn];
    const publishBtn = document.createElement("button");
    publishBtn.type = "button";
    publishBtn.className = "text-btn xiaohongshu-publish-btn";
    publishBtn.textContent = "一键发布到小红书";
    publishBtn.addEventListener("click", () => startXiaohongshuPublish(item.id, publishBtn));
    return [generateBtn, publishBtn];
  }
  return [];
}

function formatBytes(size) {
  const value = Number(size) || 0;
  if (value < 1024) return `${value}B`;
  return `${Math.round(value / 1024)}KB`;
}

function selectContent(contentId, openFirstEditable = false) {
  remixState.selectedContentId = contentId;
  remixState.selectedContentByTab[remixState.activeTab] = contentId;
  document.querySelectorAll(".package-history-card").forEach((card) => {
    card.classList.toggle("is-active", card.dataset.contentId === contentId);
  });
  const content = filterContentsForTab(remixState.packageContents).find((item) => item.id === contentId);
  renderContentDetail(content);
  if (openFirstEditable && content) {
    const file = firstEditableFile(content);
    if (file) openPackageFile(file.path);
  }
}

function firstEditableFile(content) {
  for (const packageItem of content.packages || []) {
    const file = (packageItem.files || []).find((item) => item.editable);
    if (file) return file;
  }
  return null;
}

function renderContentDetail(content) {
  const { detail } = historyElements();
  if (!detail) return;
  detail.innerHTML = "";
  if (!content) {
    detail.textContent = "选择左侧内容查看详情。";
    return;
  }
  const title = document.createElement("h3");
  title.textContent = content.title || "未命名内容";
  const source = document.createElement("p");
  source.className = "package-history-source";
  source.textContent = content.source_url || "无来源链接";
  detail.append(title, source);
  for (const packageItem of content.packages || []) {
    const block = document.createElement("section");
    block.className = "package-detail-card";
    const head = document.createElement("strong");
    head.textContent = `${packageGroupLabel(packageItem.group)} · ${packageItem.name}`;
    const files = document.createElement("div");
    files.className = "package-file-list";
    for (const file of packageItem.files || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "package-file-btn";
      button.textContent = `${file.name} · ${formatBytes(file.size)}`;
      button.disabled = !file.editable;
      button.title = file.editable ? "点击编辑" : "该文件不支持在线编辑";
      button.addEventListener("click", () => openPackageFile(file.path));
      files.appendChild(button);
    }
    block.append(head, files);
    detail.appendChild(block);
  }
}

function packageGroupLabel(group) {
  return {
    remix: "图文/视频包",
    jianying: "剪映包",
    "affiliate-jianying": "带货剪映包",
    "xiaohongshu-note": "小红书图文包",
  }[group] || group;
}

function platformName(platform) {
  return {
    douyin: "抖音",
    xiaohongshu: "小红书",
    kuaishou: "快手",
  }[platform] || "未知平台";
}

async function openPackageFile(path) {
  const data = await api(`/api/remix/file?path=${encodeURIComponent(path)}`);
  remixState.selectedPackageFile = data.path;
  const { editorTitle, editor, saveButton } = historyElements();
  if (!editorTitle || !editor || !saveButton) return;
  editorTitle.textContent = data.name;
  editor.value = data.content || "";
  saveButton.disabled = false;
  setRemixStatus("已载入文件");
}

async function savePackageFile() {
  if (!remixState.selectedPackageFile) throw new Error("请先选择文件");
  const { editor } = historyElements();
  if (!editor) throw new Error("当前 tab 不支持文件编辑");
  const data = await api("/api/remix/file", {
    method: "POST",
    body: JSON.stringify({
      path: remixState.selectedPackageFile,
      content: editor.value,
    }),
  });
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("已保存文件");
}

async function deleteContent(contentId, title) {
  const confirmed = window.confirm(`确定删除「${title || "该内容"}」下的所有生成包吗？`);
  if (!confirmed) return;
  const data = await api("/api/remix/content/delete", {
    method: "POST",
    body: JSON.stringify({ id: contentId }),
  });
  remixState.selectedPackageFile = "";
  remixState.selectedContentId = "";
  remixState.selectedContentByTab[remixState.activeTab] = "";
  const { editor, editorTitle, saveButton } = historyElements();
  if (editor) editor.value = "";
  if (editorTitle) editorTitle.textContent = "文件编辑";
  if (saveButton) saveButton.disabled = true;
  writeResult(data);
  await loadPackageHistory();
  setRemixStatus("已删除内容");
}

async function startJianyingGeneration(contentId, button) {
  const progress = startManualButtonProgress(button);
  try {
    selectContent(contentId);
    setRemixStatus("剪映自动化启动中", "busy");
    const data = await api("/api/remix/content/jianying-generate", {
      method: "POST",
      body: JSON.stringify({ id: contentId, launch: true, automation: true }),
    });
    const status = await pollJianyingJob(data.job_id, progress);
    progress.stop(status.state === "completed");
    renderJianyingGenerationResult(status);
    writeResult(status);
    setRemixStatus(status.state === "completed" ? "剪映自动化已完成" : "剪映自动化失败", status.state === "failed" ? "error" : "");
  } catch (error) {
    progress.stop(false);
    setRemixStatus("剪映自动化失败", "error");
    writeResult({ ok: false, error: error.message });
  }
}

async function startXiaohongshuGeneration(contentId, button) {
  const progress = startManualButtonProgress(button);
  try {
    selectContent(contentId);
    setRemixStatus("小红书图文包生成中", "busy");
    progress.update(35);
    const data = await api("/api/remix/content/xiaohongshu-generate", {
      method: "POST",
      body: JSON.stringify({ id: contentId }),
    });
    progress.update(100);
    progress.stop(true);
    writeResult(data);
    await loadPackageHistory();
    selectContent(contentId);
    renderXiaohongshuGenerationResult(data);
    setRemixStatus("小红书图文包已生成");
  } catch (error) {
    progress.stop(false);
    setRemixStatus("小红书生成失败", "error");
    writeResult({ ok: false, error: error.message });
  }
}

async function startXiaohongshuPublish(contentId, button) {
  const progress = startManualButtonProgress(button);
  try {
    selectContent(contentId);
    setRemixStatus("小红书发布助手启动中", "busy");
    progress.update(30);
    const data = await api("/api/remix/content/xiaohongshu-publish", {
      method: "POST",
      body: JSON.stringify({ id: contentId, launch: true }),
    });
    progress.update(100);
    progress.stop(true);
    renderXiaohongshuPublishResult(data);
    writeResult(data);
    setRemixStatus("小红书发布助手已准备");
  } catch (error) {
    progress.stop(false);
    setRemixStatus("小红书发布助手失败", "error");
    writeResult({ ok: false, error: error.message });
  }
}

async function pollJianyingJob(jobId, progress) {
  let latest = null;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    latest = await api(`/api/remix/content/jianying-job?id=${encodeURIComponent(jobId)}`);
    progress.update(latest.progress || 0);
    renderJianyingGenerationResult(latest);
    if (latest.state === "completed" || latest.state === "failed") return latest;
    await delay(1000);
  }
  throw new Error("剪映自动化任务超时，请查看剪映窗口当前状态");
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function startManualButtonProgress(button) {
  const originalText = button.textContent;
  button.disabled = true;
  button.classList.add("is-progressing");
  renderOptimizeProgress(button, 5);
  return {
    update(progress) {
      renderOptimizeProgress(button, Math.max(5, Math.min(100, Number(progress) || 0)));
    },
    stop(done = false) {
      if (done) renderOptimizeProgress(button, 100);
      window.setTimeout(() => {
        button.disabled = false;
        button.classList.remove("is-progressing");
        button.textContent = originalText;
        button.style.removeProperty("--progress");
      }, done ? 350 : 0);
    },
  };
}

function renderJianyingGenerationResult(data) {
  const { detail } = historyElements();
  const old = detail.querySelector(".jianying-generation-result");
  if (old) old.remove();
  const block = document.createElement("section");
  block.className = "package-detail-card jianying-generation-result";
  const title = document.createElement("strong");
  title.textContent = data.job_id ? `剪映自动化 · ${data.progress || 0}%` : "剪映生成任务已准备";
  const message = document.createElement("p");
  message.textContent = data.error || data.message || "";
  const steps = document.createElement("ul");
  for (const step of data.steps || []) {
    const item = document.createElement("li");
    item.textContent = `${step.label}：${step.state}`;
    steps.appendChild(item);
  }
  const packageDir = document.createElement("p");
  packageDir.className = "package-history-source";
  packageDir.textContent = `素材目录：${data.package_dir || ""}`;
  const taskFile = document.createElement("p");
  taskFile.className = "package-history-source";
  taskFile.textContent = `任务单：${data.task_file || ""}`;
  block.append(title, message, steps, packageDir, taskFile);
  detail.prepend(block);
}

function renderXiaohongshuGenerationResult(data) {
  const { detail } = historyElements();
  if (!detail) return;
  const old = detail.querySelector(".xiaohongshu-generation-result");
  if (old) old.remove();
  const block = document.createElement("section");
  block.className = "package-detail-card xiaohongshu-generation-result";
  const title = document.createElement("strong");
  title.textContent = "小红书图文包已生成";
  const message = document.createElement("p");
  message.textContent = data.message || "";
  const noteDir = document.createElement("p");
  noteDir.className = "package-history-source";
  noteDir.textContent = `图文包目录：${data.note_dir || ""}`;
  const imageDir = document.createElement("p");
  imageDir.className = "package-history-source";
  imageDir.textContent = `图片目录：${data.image_dir || ""} · ${data.image_count || 0} 张`;
  const openBtn = document.createElement("button");
  openBtn.type = "button";
  openBtn.className = "text-btn xiaohongshu-publish-btn";
  openBtn.textContent = "一键发布到小红书";
  openBtn.addEventListener("click", () => startXiaohongshuPublish(data.content_id, openBtn));
  block.append(title, message, noteDir, imageDir, openBtn);
  detail.prepend(block);
}

function renderXiaohongshuPublishResult(data) {
  const { detail } = historyElements();
  if (!detail) return;
  const old = detail.querySelector(".xiaohongshu-publish-result");
  if (old) old.remove();
  const block = document.createElement("section");
  block.className = "package-detail-card xiaohongshu-publish-result";
  const title = document.createElement("strong");
  title.textContent = "小红书发布助手已准备";
  const message = document.createElement("p");
  message.textContent = data.message || "";
  const noteDir = document.createElement("p");
  noteDir.className = "package-history-source";
  noteDir.textContent = `图文包目录：${data.note_dir || ""}`;
  const payload = document.createElement("p");
  payload.className = "package-history-source";
  payload.textContent = `发布载荷：${data.payload_file || ""}`;
  const imageDir = document.createElement("p");
  imageDir.className = "package-history-source";
  imageDir.textContent = `图片目录：${data.image_dir || ""} · ${data.image_count || 0} 张`;
  block.append(title, message, noteDir, imageDir, payload);
  detail.prepend(block);
}

function setActiveTab(tab) {
  remixState.activeTab = tab;
  document.querySelectorAll("[data-remix-tab]").forEach((button) => {
    const active = button.dataset.remixTab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-remix-panel]").forEach((panel) => {
    const active = panel.dataset.remixPanel === tab;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
  renderPackageHistory();
}

function renderAffiliatePlan(plan) {
  const box = $("affiliatePlanResult");
  box.innerHTML = "";
  if (!plan.ok) {
    box.textContent = plan.error || "生成失败";
    return;
  }
  const product = document.createElement("div");
  product.className = "affiliate-product-summary";
  product.textContent = `${plan.product?.name || "商品"} · ${plan.product?.category || "类目"} · ${(plan.product?.selling_points || []).join(" / ")}`;
  box.appendChild(product);
  for (const [platform, item] of Object.entries(plan.platform_packages || {})) {
    const section = document.createElement("section");
    section.className = "affiliate-platform-card";
    const title = document.createElement("h3");
    title.textContent = platform === "douyin" ? "抖音橱窗版" : "小红书种草版";
    const titles = document.createElement("ol");
    for (const value of item.titles || []) {
      const li = document.createElement("li");
      li.textContent = value;
      titles.appendChild(li);
    }
    const body = document.createElement("p");
    body.textContent = item.body || "";
    const tags = document.createElement("p");
    tags.className = "affiliate-tags";
    tags.textContent = (item.tags || []).join(" ");
    const voiceover = document.createElement("pre");
    voiceover.textContent = item.voiceover || "";
    section.append(title, titles, body, tags, voiceover, copyAffiliateButton(item));
    box.appendChild(section);
  }
  box.appendChild(affiliateListBlock("分镜重构", (plan.storyboard || []).map((shot) => `${shot.seconds} ${shot.shot}：${shot.purpose}`)));
  box.appendChild(affiliateListBlock("剪映 SVIP 执行清单", plan.jianying_checklist || []));
  box.appendChild(affiliateListBlock("降低判重检查", plan.dedupe_checks || []));
  box.appendChild(affiliateListBlock("发布风险提示", plan.risk_checks || []));
}

function copyAffiliateButton(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-btn";
  button.textContent = "复制此平台文案";
  button.addEventListener("click", async () => {
    const text = [
      ...(item.titles || []),
      "",
      item.body || "",
      "",
      (item.tags || []).join(" "),
      "",
      item.voiceover || "",
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setRemixStatus("已复制带货文案");
  });
  return button;
}

function affiliateListBlock(titleText, items) {
  const block = document.createElement("section");
  block.className = "affiliate-list-block";
  const title = document.createElement("h3");
  title.textContent = titleText;
  const list = document.createElement("ul");
  for (const value of items) {
    const li = document.createElement("li");
    li.textContent = value;
    list.appendChild(li);
  }
  block.append(title, list);
  return block;
}

function selectedAnalysis() {
  syncCopyFieldsFromEditable(true);
  const analysis = JSON.parse(JSON.stringify(remixState.analysis));
  const selected = new Set(selectedImageValues());
  analysis.images = (analysis.images || []).filter((image) => selected.has(imageValue(image)));
  return analysis;
}

function selectedImageValues() {
  return [...document.querySelectorAll("#imageList input[type='checkbox']:checked")].map((input) => input.value);
}

function selectedImageObjects() {
  const selected = new Set(selectedImageValues());
  if (!selected.size) return [];
  const images = remixState.analysis?.images || [];
  if (images.length) return images.filter((image) => selected.has(imageValue(image)));
  return [...selected].map((value) => ({ url: value, path: value }));
}

function packageName() {
  const title = remixState.analysis?.copywriting?.title || "link-remix";
  return title.slice(0, 32);
}

async function copyTextById(id) {
  await navigator.clipboard.writeText($(id).textContent.trim());
  setRemixStatus("已复制");
}

async function copyAll() {
  if (!remixState.analysis) return;
  syncCopyFieldsFromEditable(true);
  await navigator.clipboard.writeText(remixState.analysis.copywriting?.copy_text || "");
  setRemixStatus("已复制");
}

async function uploadImages() {
  $("imageUploadInput").click();
}

async function handleImageUpload(event) {
  const files = Array.from(event.currentTarget.files || []);
  event.currentTarget.value = "";
  if (!files.length) return;
  setRemixStatus("上传图片", "busy");
  const body = new FormData();
  for (const file of files) {
    body.append("files", file, file.name);
  }
  const response = await fetch("/api/upload?kind=remix-images", {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "图片上传失败");
  }
  for (const [index, file] of files.entries()) {
    const saved = data.files?.[index];
    if (saved?.path) {
      remixState.uploadPreviewUrls[saved.path] = URL.createObjectURL(file);
    }
  }
  appendImagePaths((data.files || []).map((file) => file.path).filter(Boolean));
  writeResult(data);
  setRemixStatus("图片已上传");
}

function appendImagePaths(paths) {
  if (!remixState.analysis) {
    renderImages(paths.map((path) => ({ url: path, path, selected: true })));
    return;
  }
  const existingValues = new Set((remixState.analysis.images || []).map((image) => imageValue(image)));
  for (const path of paths) {
    if (!existingValues.has(path)) {
      remixState.analysis.images.push({ url: path, path, selected: true });
    }
  }
  renderImages(remixState.analysis.images);
}

function deleteSelectedImages() {
  const selected = new Set(selectedImageValues());
  if (!selected.size) return;
  if (remixState.analysis) {
    remixState.analysis.images = (remixState.analysis.images || []).filter((image) => !selected.has(imageValue(image)));
  }
  for (const value of selected) {
    if (remixState.uploadPreviewUrls[value]) {
      URL.revokeObjectURL(remixState.uploadPreviewUrls[value]);
      delete remixState.uploadPreviewUrls[value];
    }
  }
  if (remixState.analysis) {
    renderImages(remixState.analysis.images || []);
  } else {
    renderImages([]);
  }
  setRemixStatus("已删除选中图片");
}

function updateImageActionState() {
  const selectedCount = selectedImageValues().length;
  const hasPrompt = Boolean($("imagePolishPrompt")?.value.trim());
  $("deleteImagesBtn").disabled = selectedCount === 0;
  $("aiPolishImagesBtn").disabled = selectedCount === 0 || !hasPrompt;
}

async function polishSelectedImages() {
  const images = selectedImageObjects();
  const prompt = $("imagePolishPrompt").value.trim();
  if (!images.length) throw new Error("请先选择需要 AI 润色的图片");
  if (!prompt) throw new Error("请先填写图片 AI 润色提示词");
  const button = $("aiPolishImagesBtn");
  const progress = startManualButtonProgress(button);
  try {
    setImagePolishStatus("正在发送图片和提示词给 Codex 客户端...");
    setRemixStatus("图片 AI 润色中", "busy");
    progress.update(18);
    const data = await api("/api/remix/images/polish", {
      method: "POST",
      body: JSON.stringify({ images, prompt }),
    });
    progress.update(86);
    replaceSelectedImages(data.images || []);
    writeResult(data);
    setImagePolishStatus(`已回填 ${data.images?.length || 0} 张 AI 润色图片。`);
    setRemixStatus("图片 AI 润色完成");
    progress.stop(true);
  } catch (error) {
    setImagePolishStatus(error.message || "图片 AI 润色失败", true);
    setRemixStatus("图片 AI 润色失败", "error");
    progress.stop(false);
    throw error;
  }
}

function replaceSelectedImages(newImages) {
  const selected = new Set(selectedImageValues());
  const normalized = (newImages || []).map((image) => ({ ...image, selected: true })).filter((image) => imageValue(image));
  if (!normalized.length) return;
  if (!remixState.analysis) {
    renderImages(normalized);
    return;
  }
  const remaining = (remixState.analysis.images || []).filter((image) => !selected.has(imageValue(image)));
  remixState.analysis.images = [...remaining, ...normalized];
  renderImages(remixState.analysis.images);
}

function setImagePolishStatus(text, isError = false) {
  const status = $("imagePolishStatus");
  if (!status) return;
  status.textContent = text;
  status.classList.toggle("is-error", Boolean(isError));
}

async function optimizeCopy(field) {
  syncCopyFieldFromEditable(field, true);
  const targetId = copyFieldId(field);
  const text = targetId ? $(targetId).textContent.trim() : "";
  if (!text || text.startsWith("等待拆解") || text.startsWith("未读取到")) {
    throw new Error(`请先拆解出${copyFieldLabel(field)}内容`);
  }
  const model = selectedRewriteModel();
  const allowEmoji = Boolean(remixState.emojiFields[field]);
  setRemixStatus(model ? `本地模型润色中: ${model}` : "本地模型润色中", "busy");
  const data = await api("/api/remix/optimize-copy", {
    method: "POST",
    body: JSON.stringify({ field, text, model, allow_emoji: allowEmoji }),
  });
  renderRewriteOptions(field, data.suggestions || []);
  setRemixStatus("Ready");
}

function startOptimizeProgress(button) {
  const originalText = button.textContent;
  let progress = 8;
  button.disabled = true;
  button.classList.add("is-progressing");
  renderOptimizeProgress(button, progress);
  const timer = window.setInterval(() => {
    progress = Math.min(92, progress + Math.max(1, Math.round((94 - progress) * 0.12)));
    renderOptimizeProgress(button, progress);
  }, 700);
  return (done = false) => {
    window.clearInterval(timer);
    if (done) renderOptimizeProgress(button, 100);
    window.setTimeout(() => {
      button.disabled = false;
      button.classList.remove("is-progressing");
      button.textContent = originalText;
      button.style.removeProperty("--progress");
    }, done ? 350 : 0);
  };
}

function renderOptimizeProgress(button, progress) {
  button.style.setProperty("--progress", `${progress}%`);
  button.innerHTML = `<span>${progress}%</span>`;
}

async function loadRewriteModels() {
  const select = $("rewriteModelSelect");
  if (!select) return;
  const data = await api("/api/remix/models");
  remixState.rewriteModels = data.models || [];
  remixState.rewriteModel = data.default_model || "";
  renderRewriteModels(data);
}

function renderRewriteModels(data) {
  const select = $("rewriteModelSelect");
  select.innerHTML = "";
  const models = data.models || [];
  if (!models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = data.error || "未读取到模型";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label || model.id;
    option.selected = model.id === data.default_model;
    select.appendChild(option);
  }
}

function selectedRewriteModel() {
  return $("rewriteModelSelect")?.value || remixState.rewriteModel || "";
}

function rewritePanelId(field) {
  return `${field}RewritePanel`;
}

function rewriteOptionsId(field) {
  return `${field}RewriteOptions`;
}

function applyRewriteButton(field) {
  return document.querySelector(`[data-apply-rewrite="${field}"]`);
}

function renderRewriteOptions(field, suggestions) {
  remixState.rewriteField = field;
  remixState.selectedRewriteByField[field] = "";
  const panel = $(rewritePanelId(field));
  const options = $(rewriteOptionsId(field));
  const applyButton = applyRewriteButton(field);
  options.innerHTML = "";
  panel.classList.remove("is-hidden");
  applyButton.disabled = true;
  for (const [index, suggestion] of suggestions.entries()) {
    const option = document.createElement("label");
    option.className = "rewrite-option";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = `${field}RewriteOption`;
    radio.value = suggestion;
    radio.addEventListener("change", () => {
      remixState.selectedRewriteByField[field] = suggestion;
      applyButton.disabled = false;
    });
    const text = document.createElement("span");
    text.textContent = suggestion;
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "text-btn";
    copyBtn.textContent = "复制";
    copyBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      await navigator.clipboard.writeText(suggestion);
      setRemixStatus(`已复制候选 ${index + 1}`);
    });
    option.append(radio, text, copyBtn);
    options.appendChild(option);
  }
}

function renderRewriteError(field, message) {
  const panel = $(rewritePanelId(field));
  const options = $(rewriteOptionsId(field));
  const applyButton = applyRewriteButton(field);
  options.innerHTML = "";
  panel.classList.remove("is-hidden");
  applyButton.disabled = true;
  const error = document.createElement("div");
  error.className = "rewrite-error";
  error.textContent = message || "润色失败，请稍后重试。";
  options.appendChild(error);
}

function applyRewrite(field) {
  const value = (remixState.selectedRewriteByField[field] || "").trim();
  const targetId = copyFieldId(field);
  if (!field || !value || !targetId) return;
  setCopyFieldValue(field, value);
  if (remixState.analysis?.copywriting) {
    writeResult(remixState.analysis);
  }
  $(rewritePanelId(field)).classList.add("is-hidden");
  setRemixStatus("已回填");
}

function toggleEmoji(field, button) {
  remixState.emojiFields[field] = !remixState.emojiFields[field];
  const enabled = remixState.emojiFields[field];
  button.setAttribute("aria-pressed", String(enabled));
  button.classList.toggle("is-active", enabled);
  button.textContent = enabled ? "已加入 emoji" : "加入 emoji";
}

function writeResult(data) {
  console.debug("remix result", data);
}

function bind(id, fn) {
  $(id).addEventListener("click", async () => {
    try {
      await fn();
    } catch (error) {
      setRemixStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
}

bind("analyzeBtn", analyzeLink);
bind("xiaohongshuFlowBtn", createXiaohongshuPackageAndGo);
bind("jianyingFlowBtn", () => createPackageAndGo("jianying"));
bind("jianyingBtn", createJianyingPackage);
bind("copyAllBtn", copyAll);
bind("uploadImagesBtn", uploadImages);
bind("deleteImagesBtn", deleteSelectedImages);
bind("aiPolishImagesBtn", async () => {
  try {
    await polishSelectedImages();
  } catch (error) {
    writeResult({ ok: false, error: error.message });
  }
});
bind("affiliatePlanBtn", createAffiliatePlan);
bind("affiliateJianyingBtn", createAffiliateJianyingPackage);
$("imagePolishPrompt").addEventListener("input", updateImageActionState);
$("imageUploadInput").addEventListener("change", async (event) => {
  try {
    await handleImageUpload(event);
  } catch (error) {
    setRemixStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
$("rewriteModelSelect").addEventListener("change", (event) => {
  remixState.rewriteModel = event.target.value;
});

document.querySelectorAll("[data-remix-tab]").forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.remixTab));
});

document.querySelectorAll(".refresh-packages-btn").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await loadPackageHistory();
      setRemixStatus("已刷新列表");
    } catch (error) {
      setRemixStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
});

document.querySelectorAll(".save-package-file-btn").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await savePackageFile();
    } catch (error) {
      setRemixStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
});

$("imageLightboxClose").addEventListener("click", closeImageLightbox);
$("imageLightboxPrev").addEventListener("click", (event) => {
  event.stopPropagation();
  showLightboxOffset(-1);
});
$("imageLightboxNext").addEventListener("click", (event) => {
  event.stopPropagation();
  showLightboxOffset(1);
});
$("imageLightbox").addEventListener("click", (event) => {
  if (event.target.id === "imageLightbox") closeImageLightbox();
});
document.addEventListener("keydown", (event) => {
  if ($("imageLightbox").classList.contains("is-hidden")) return;
  if (event.key === "Escape") {
    closeImageLightbox();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    showLightboxOffset(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    showLightboxOffset(1);
  }
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await copyTextById(button.dataset.copyTarget);
    } catch (error) {
      setRemixStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
});

document.querySelectorAll("[data-optimize-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const stopProgress = startOptimizeProgress(button);
    try {
      await optimizeCopy(button.dataset.optimizeTarget);
      stopProgress(true);
    } catch (error) {
      stopProgress(false);
      setRemixStatus("润色失败", "error");
      renderRewriteError(button.dataset.optimizeTarget, error.message);
    }
  });
});

document.querySelectorAll("[data-emoji-target]").forEach((button) => {
  button.addEventListener("click", () => {
    toggleEmoji(button.dataset.emojiTarget, button);
  });
});

document.querySelectorAll("[data-apply-rewrite]").forEach((button) => {
  button.addEventListener("click", () => {
    applyRewrite(button.dataset.applyRewrite);
  });
});

setupEditableCopyFields();

loadRewriteModels().catch((error) => {
  const select = $("rewriteModelSelect");
  select.innerHTML = "";
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "模型列表读取失败";
  select.appendChild(option);
  select.disabled = true;
  writeResult({ ok: false, error: error.message });
});

loadPackageHistory().catch((error) => {
  const { list } = historyElements();
  if (list) list.textContent = `历史内容加载失败：${error.message}`;
  setRemixStatus("历史内容加载失败", "error");
});
