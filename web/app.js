const state = {
  projects: [],
  voices: [],
  bgmSources: [],
  analytics: null,
  preview: null,
  selectedProjectId: "",
  selectedProjectIds: new Set(),
  generatingProjectIds: new Set(),
  previewSeeking: false,
  activeLibraryTab: "overview",
};

const $ = (id) => document.getElementById(id);

function setStatus(text, kind = "") {
  const pill = $("statusPill");
  pill.textContent = text;
  pill.className = `status-pill ${kind}`.trim();
}

function setGenerationProgress(percent, label) {
  $("generationProgressBar").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  $("generationProgressValue").textContent = `${Math.round(percent)}%`;
  $("generationProgressLabel").textContent = label;
}

function setProjectGenerating(projectId, generating) {
  if (generating) {
    state.generatingProjectIds.add(projectId);
  } else {
    state.generatingProjectIds.delete(projectId);
  }
  const currentProjectId = $("projectId").value.trim();
  $("voiceBtn").disabled = state.generatingProjectIds.has(currentProjectId);
  $("previewBtn").disabled = state.generatingProjectIds.has(currentProjectId);
  renderProjects();
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

function payload() {
  const bgmPaths = splitPathList($("bgmPath").value);
  const contentMode = currentContentMode();
  return {
    project_id: $("projectId").value.trim(),
    script_path: $("scriptPath").value.trim(),
    script_text: $("scriptText").value,
    content_mode: contentMode,
    video_type: $("videoType").value,
    product_name: $("productName").value.trim(),
    product_category: $("productCategory").value,
    price: $("productPrice").value.trim(),
    commission: $("productCommission").value.trim(),
    pain_point: $("painPoint").value.trim(),
    selling_points: $("sellingPoints").value.trim(),
    target_platform: $("targetPlatform").value,
    product_link: $("productLink").value.trim(),
    voice: $("voiceSelect").value,
    bgm: bgmPaths[0] || "",
    images: splitPathList($("imagePaths").value),
    platforms: selectedPlatforms(),
    chars_per_second: Number($("charsPerSecond").value || 4.8),
    target_duration_seconds: targetDurationSeconds(),
  };
}

function currentContentMode() {
  return document.querySelector('input[name="contentMode"]:checked')?.value || "script";
}

function targetDurationSeconds() {
  const value = Number($("targetDuration").value || 0);
  return value > 0 ? value : "";
}

function selectedPlatforms() {
  const checked = [...document.querySelectorAll('input[name="platform"]:checked')].map((item) => item.value);
  return checked.length ? checked : ["bilibili", "douyin", "xiaohongshu"];
}

function splitPathList(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function writeResult(data) {
  $("resultBox").textContent = JSON.stringify(data, null, 2);
}

async function refresh() {
  setStatus("刷新中", "busy");
  const [voices, projects, bgmSources, analytics] = await Promise.all([
    api("/api/voices"),
    api("/api/projects"),
    api("/api/bgm-sources"),
    api("/api/analytics"),
  ]);
  state.voices = voices.voices || [];
  state.projects = projects.projects || [];
  state.bgmSources = bgmSources.sources || [];
  state.analytics = analytics;
  ensureSelectedProject();
  renderVoices();
  renderBgmSources();
  renderAnalytics();
  pruneProjectSelection();
  renderProjects();
  renderTabWorkspaces();
  renderProjectSelectionControls();
  $("voiceCount").textContent = state.voices.length;
  $("projectCount").textContent = state.projects.length;
  setStatus("Ready");
}

function ensureSelectedProject() {
  if (!state.projects.length) {
    state.selectedProjectId = "";
    return;
  }
  if (!state.selectedProjectId || !state.projects.some((project) => project.id === state.selectedProjectId)) {
    state.selectedProjectId = state.projects[0].id;
  }
}

function selectedProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || state.projects[0] || null;
}

function pruneProjectSelection() {
  const available = new Set(state.projects.map((project) => project.id));
  state.selectedProjectIds = new Set([...state.selectedProjectIds].filter((id) => available.has(id)));
}

function renderAnalytics() {
  const box = $("analyticsBox");
  const analytics = state.analytics || {};
  const platforms = Object.values(analytics.platforms || {}).sort((a, b) => (b.score || 0) - (a.score || 0));
  box.innerHTML = "";
  const headline = document.createElement("div");
  headline.className = "analytics-headline";
  headline.innerHTML = `<strong>${analytics.total_views || 0}</strong><span>总播放</span>`;
  const best = document.createElement("div");
  best.className = "analytics-best";
  best.textContent = analytics.best_platform
    ? `最佳平台 ${platformLabel(analytics.best_platform)} · 最佳项目 ${analytics.best_project || "--"}`
    : "等待复盘数据";
  box.append(headline, best);
  if (platforms.length) {
    const list = document.createElement("div");
    list.className = "analytics-platforms";
    for (const item of platforms.slice(0, 3)) {
      const row = document.createElement("span");
      row.textContent = `${platformLabel(item.platform)} ${item.views}播放 互动${formatPercent(item.engagement_rate)}`;
      list.appendChild(row);
    }
    box.appendChild(list);
  }
  const suggestions = document.createElement("ul");
  for (const suggestion of (analytics.suggestions || []).slice(0, 2)) {
    const item = document.createElement("li");
    item.textContent = suggestion;
    suggestions.appendChild(item);
  }
  box.appendChild(suggestions);
}

function renderBgmSources() {
  const select = $("bgmSourceSelect");
  const current = select.value;
  select.innerHTML = "";
  for (const source of state.bgmSources) {
    const option = document.createElement("option");
    option.value = source.key;
    option.textContent = source.name;
    select.appendChild(option);
  }
  if (current && state.bgmSources.some((source) => source.key === current)) {
    select.value = current;
  }
  renderBgmSourceNote();
}

function currentBgmSource() {
  return state.bgmSources.find((source) => source.key === $("bgmSourceSelect").value) || state.bgmSources[0] || null;
}

function renderBgmSourceNote() {
  const source = currentBgmSource();
  $("bgmSourceNote").textContent = source
    ? `${source.license_note} ${source.best_for} ${source.caution}`
    : "暂无素材库，请选择本地音频文件。";
}

function renderVoices() {
  const select = $("voiceSelect");
  const current = select.value || "剪映沉稳男声（同款参考）";
  select.innerHTML = "";
  const voices = state.voices.length ? state.voices : ["剪映沉稳男声（同款参考）"];
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice;
    option.textContent = voice;
    select.appendChild(option);
  }
  select.value = voices.includes(current) ? current : voices[0];
}

function renderProjects() {
  const list = $("projectList");
  list.innerHTML = "";
  if (!state.projects.length) {
    list.textContent = "暂无生成内容";
    renderProjectSelectionControls();
    return;
  }
  for (const project of state.projects) {
    const item = document.createElement("div");
    item.className = `project-item ${project.id === state.selectedProjectId ? "is-selected" : ""}`.trim();
    item.addEventListener("click", () => {
      state.selectedProjectId = project.id;
      renderProjects();
      renderTabWorkspaces();
    });
    const header = document.createElement("div");
    header.className = "project-item-head";
    const select = document.createElement("label");
    select.className = "project-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedProjectIds.has(project.id);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", (event) => {
      event.stopPropagation();
      toggleProjectForDeletion(project.id, checkbox.checked);
    });
    const selectText = document.createElement("span");
    selectText.textContent = "选择";
    select.append(checkbox, selectText);
    const title = document.createElement("strong");
    title.textContent = project.id;
    header.append(select, title);
    const status = document.createElement("div");
    status.className = "content-status";
    status.append(
      statusChip("文案", project.has_script),
      statusChip("口播", project.has_audio),
      statusChip("字幕", project.has_subtitles),
      countChip("图片", project.image_count),
      countChip("BGM", project.bgm_count),
    );
    const platformChips = document.createElement("div");
    platformChips.className = "project-platform-chips";
    for (const platformPackage of (project.platform_packages || []).slice(0, 3)) {
      const chip = document.createElement("span");
      chip.textContent = `${platformPackage.name} ${platformPackage.score ?? "--"}`;
      platformChips.appendChild(chip);
    }
    const actions = document.createElement("div");
    actions.className = "project-actions";
    const inspectBtn = document.createElement("button");
    inspectBtn.className = "secondary";
    inspectBtn.textContent = "详情";
    inspectBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      state.selectedProjectId = project.id;
      setLibraryTab("growth");
      renderProjects();
      renderTabWorkspaces();
    });
    const previewBtn = document.createElement("button");
    previewBtn.textContent = "预览播放";
    previewBtn.disabled = !project.can_preview || state.generatingProjectIds.has(project.id);
    previewBtn.title = state.generatingProjectIds.has(project.id) ? "这个项目正在生成视频" : "";
    previewBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      $("projectId").value = project.id;
      state.selectedProjectId = project.id;
      renderProjects();
      renderTabWorkspaces();
      await loadPreview();
    });
    actions.append(inspectBtn, previewBtn);
    item.append(header, status, platformChips, actions);
    list.appendChild(item);
  }
  renderProjectSelectionControls();
}

function toggleProjectForDeletion(projectId, selected) {
  if (selected) {
    state.selectedProjectIds.add(projectId);
  } else {
    state.selectedProjectIds.delete(projectId);
  }
  renderProjects();
  renderProjectSelectionControls();
}

function renderProjectSelectionControls() {
  const selectAll = $("selectAllProjects");
  const count = $("selectedProjectCount");
  const clearBtn = $("clearProjectSelectionBtn");
  const deleteBtn = $("deleteProjectsBtn");
  if (!selectAll || !count || !clearBtn || !deleteBtn) return;

  const selectedCount = state.selectedProjectIds.size;
  selectAll.checked = state.projects.length > 0 && selectedCount === state.projects.length;
  selectAll.indeterminate = selectedCount > 0 && selectedCount < state.projects.length;
  selectAll.disabled = !state.projects.length;
  count.textContent = `已选 ${selectedCount}`;
  clearBtn.disabled = selectedCount === 0;
  deleteBtn.disabled = selectedCount === 0;
}

async function deleteSelectedProjects() {
  const projectIds = [...state.selectedProjectIds];
  if (!projectIds.length) return;
  const message = `确认删除 ${projectIds.length} 个项目？删除后会移除项目目录和已生成文件。`;
  if (!window.confirm(message)) return;

  setStatus("删除项目", "busy");
  const data = await api("/api/projects/delete", {
    method: "POST",
    body: JSON.stringify({ project_ids: projectIds }),
  });
  writeResult(data);
  state.selectedProjectIds.clear();
  if (projectIds.includes(state.selectedProjectId)) {
    state.selectedProjectId = "";
  }
  await refresh();
}

function renderTabWorkspaces() {
  const project = selectedProject();
  renderSelectedProjectBox(project);
  renderGrowthWorkspace(project);
  renderPublishWorkspace(project);
}

function renderSelectedProjectBox(project) {
  const box = $("selectedProjectBox");
  box.innerHTML = "";
  if (!project) {
    box.textContent = "暂无选中项目";
    return;
  }
  const title = document.createElement("strong");
  title.textContent = project.id;
  const meta = document.createElement("span");
  meta.textContent = `${project.platform_packages?.length || 0} 个平台包 · ${project.has_video ? "有成片" : "待生成成片"}`;
  box.append(title, meta);
}

function renderGrowthWorkspace(project) {
  const workspace = $("growthWorkspace");
  workspace.innerHTML = "";
  if (!project) {
    workspace.textContent = "暂无项目";
    return;
  }
  workspace.append(
    renderHookPanel(project),
    renderTitleExperimentPanel(project),
    renderSeriesPanel(project),
  );
}

function renderPublishWorkspace(project) {
  const workspace = $("publishWorkspace");
  workspace.innerHTML = "";
  if (!project) {
    workspace.textContent = "暂无项目";
    return;
  }
  workspace.append(
    renderPlatformPackages(project),
    renderMonetizationPanel(project),
    renderPublishSchedulePanel(project),
    renderPerformancePanel(project),
    renderProjectPaths(project),
  );
}

function renderPlatformPackages(project) {
  const platformBox = document.createElement("div");
  platformBox.className = "platform-packages";
  const packages = project.platform_packages || [];
  if (!packages.length) {
    platformBox.textContent = "暂无平台发布包";
    return platformBox;
  }
  for (const item of packages) {
    const row = document.createElement("div");
    row.className = "platform-package";
    if (item.cover) {
      const cover = document.createElement("img");
      cover.className = "platform-cover";
      cover.src = item.cover;
      cover.alt = `${item.name}封面`;
      row.appendChild(cover);
    }
    const meta = document.createElement("div");
    meta.className = "platform-meta";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const titleText = document.createElement("span");
    titleText.textContent = item.title || "待生成标题";
    meta.append(name, titleText);
    const stat = document.createElement("div");
    stat.className = "platform-stat";
    const ratio = document.createElement("span");
    ratio.textContent = item.aspect_ratio || "--";
    const score = document.createElement("b");
    score.textContent = item.score ?? "--";
    const packBtn = document.createElement("button");
    packBtn.className = "package-btn";
    packBtn.type = "button";
    packBtn.textContent = "打包";
    packBtn.title = `打包下载${item.name}发布包`;
    packBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await packagePlatform(project, item);
      } catch (error) {
        setStatus("Error", "error");
        writeResult({ ok: false, error: error.message });
      }
    });
    stat.append(ratio, score, packBtn);
    row.append(meta, stat);
    row.title = item.title || "";
    if (item.video) {
      row.addEventListener("click", async () => {
        try {
          await loadPlatformPreview(project, item);
        } catch (error) {
          setStatus("Error", "error");
          writeResult({ ok: false, error: error.message });
        }
      });
    }
    const details = renderPlatformDetails(item);
    platformBox.append(row, details);
  }
  return platformBox;
}

function renderProjectPaths(project) {
  const paths = document.createElement("pre");
  paths.className = "content-paths";
  paths.textContent = [
    project.script && `文案: ${project.script}`,
    project.audio && `口播: ${project.audio}`,
    project.subtitles && `字幕: ${project.subtitles}`,
  ].filter(Boolean).join("\n") || "还没有生成文件";
  return paths;
}

function statusChip(label, ok) {
  const chip = document.createElement("span");
  chip.className = `chip ${ok ? "ok" : "missing"}`;
  chip.textContent = `${label}${ok ? "✓" : "未生成"}`;
  return chip;
}

function countChip(label, count) {
  const chip = document.createElement("span");
  chip.className = `chip ${count ? "ok" : "missing"}`;
  chip.textContent = `${label} ${count || 0}`;
  return chip;
}

function renderPlatformDetails(item) {
  const details = document.createElement("details");
  details.className = "platform-details";
  const summary = document.createElement("summary");
  summary.textContent = "发布检查";
  details.appendChild(summary);

  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-publish-btn";
  copyBtn.type = "button";
  copyBtn.textContent = "复制发布文案";
  copyBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(renderPublishText(item));
      setStatus("已复制");
    } catch (error) {
      writeResult({ ok: false, error: "复制失败，请从发布包 publish.md 复制" });
    }
  });
  details.appendChild(copyBtn);

  const groups = [
    ["标题", item.title_variants || []],
    ["标签", (item.hashtags || []).map((tag) => `#${tag}`)],
    ["互动", [item.comment_prompt, item.conversion_cta].filter(Boolean)],
    ["流量", item.traffic_checklist || []],
    ["技术", item.technical_checklist || []],
    ["优化", item.improvement_suggestions || []],
    ["风险", (item.risk_checks || []).map((risk) => risk.action || risk.type).filter(Boolean)],
  ];
  for (const [label, values] of groups) {
    if (!values.length) continue;
    const block = document.createElement("div");
    block.className = "check-group";
    const title = document.createElement("b");
    title.textContent = label;
    const list = document.createElement("ul");
    const visibleValues = values.slice(0, label === "标签" ? 8 : 3);
    for (const value of visibleValues) {
      const li = document.createElement("li");
      li.textContent = value;
      list.appendChild(li);
    }
    block.append(title, list);
    details.appendChild(block);
  }
  return details;
}

function renderPublishText(item) {
  const tags = (item.hashtags || []).map((tag) => `#${tag}`).join(" ");
  return [
    item.title,
    "",
    item.description || "",
    "",
    tags,
    "",
    item.comment_prompt ? `评论引导：${item.comment_prompt}` : "",
    item.conversion_cta ? `转化提示：${item.conversion_cta}` : "",
  ].filter((line) => line !== "").join("\n");
}

function renderHookPanel(project) {
  const panel = document.createElement("details");
  panel.className = "hook-panel";
  const summary = document.createElement("summary");
  const hook = project.hook_analysis || {};
  summary.textContent = hook.score ? `前三秒钩子 · ${hook.score}分 · ${hook.grade}` : "前三秒钩子";
  panel.appendChild(summary);
  if (!hook.hook_text) {
    const empty = document.createElement("div");
    empty.className = "hook-empty";
    empty.textContent = "暂无钩子分析，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  const body = document.createElement("div");
  body.className = "hook-body";
  const hookText = document.createElement("p");
  hookText.className = "hook-text";
  hookText.textContent = hook.hook_text;
  const featureRow = document.createElement("div");
  featureRow.className = "hook-features";
  const labels = {
    has_question: "问题",
    has_contrast: "反差",
    has_audience: "人群",
    has_benefit: "收益",
    is_short: "短",
    has_specificity: "具体",
  };
  for (const [key, label] of Object.entries(labels)) {
    const chip = document.createElement("span");
    chip.className = hook.features?.[key] ? "ok" : "missing";
    chip.textContent = label;
    featureRow.appendChild(chip);
  }
  body.append(hookText, featureRow);

  const recommendations = document.createElement("ul");
  recommendations.className = "hook-recommendations";
  for (const item of (hook.recommendations || []).slice(0, 4)) {
    const li = document.createElement("li");
    li.textContent = item;
    recommendations.appendChild(li);
  }
  body.appendChild(recommendations);

  const rewrites = document.createElement("div");
  rewrites.className = "hook-rewrites";
  for (const [platform, values] of Object.entries(hook.platform_rewrites || {})) {
    const block = document.createElement("div");
    block.className = "hook-rewrite-group";
    const title = document.createElement("strong");
    title.textContent = platformLabel(platform);
    const list = document.createElement("ul");
    for (const value of (values || []).slice(0, 3)) {
      const li = document.createElement("li");
      li.textContent = value;
      list.appendChild(li);
    }
    block.append(title, list);
    rewrites.appendChild(block);
  }
  body.appendChild(rewrites);
  panel.appendChild(body);
  return panel;
}

function renderMonetizationPanel(project) {
  const panel = document.createElement("details");
  panel.className = "monetization-panel";
  const summary = document.createElement("summary");
  const plan = project.monetization_plan || {};
  summary.textContent = plan.primary_offer?.name ? `变现承接 · ${plan.primary_offer.name}` : "变现承接";
  panel.appendChild(summary);
  if (!plan.primary_offer) {
    const empty = document.createElement("div");
    empty.className = "monetization-empty";
    empty.textContent = "暂无变现承接计划，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  const body = document.createElement("div");
  body.className = "monetization-body";
  const ladder = document.createElement("div");
  ladder.className = "offer-ladder";
  for (const offer of plan.offer_ladder || []) {
    const card = document.createElement("div");
    card.className = "offer-card";
    const name = document.createElement("strong");
    name.textContent = `${offer.level} · ${offer.name}`;
    const goal = document.createElement("span");
    goal.textContent = offer.goal || "";
    card.append(name, goal);
    ladder.appendChild(card);
  }
  body.appendChild(ladder);

  const routes = document.createElement("div");
  routes.className = "monetization-routes";
  for (const [platform, route] of Object.entries(plan.platform_routes || {})) {
    const block = document.createElement("div");
    block.className = "monetization-route";
    const title = document.createElement("strong");
    title.textContent = platformLabel(platform);
    const cta = document.createElement("p");
    cta.textContent = route.cta || "";
    const meta = document.createElement("span");
    meta.textContent = `${route.entry_point || ""} · ${route.best_metric || ""}`;
    block.append(title, cta, meta);
    routes.appendChild(block);
  }
  body.appendChild(routes);

  const checklist = document.createElement("ul");
  checklist.className = "monetization-checklist";
  for (const item of (plan.profile_checklist || []).slice(0, 4)) {
    const li = document.createElement("li");
    li.textContent = item;
    checklist.appendChild(li);
  }
  body.appendChild(checklist);

  const risks = document.createElement("div");
  risks.className = "monetization-risks";
  for (const note of plan.risk_notes || []) {
    const item = document.createElement("span");
    item.textContent = note;
    risks.appendChild(item);
  }
  body.appendChild(risks);
  panel.appendChild(body);
  return panel;
}

function renderSeriesPanel(project) {
  const panel = document.createElement("details");
  panel.className = "series-panel";
  const summary = document.createElement("summary");
  const plan = project.series_plan || {};
  summary.textContent = plan.series_name ? `系列选题 · ${plan.series_name}` : "系列选题";
  panel.appendChild(summary);
  if (!plan.episodes?.length) {
    const empty = document.createElement("div");
    empty.className = "series-empty";
    empty.textContent = "暂无系列化选题，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  const body = document.createElement("div");
  body.className = "series-body";
  const cadence = document.createElement("p");
  cadence.className = "series-cadence";
  cadence.textContent = plan.cadence || "";
  body.appendChild(cadence);

  const grid = document.createElement("div");
  grid.className = "series-grid";
  for (const episode of (plan.episodes || []).slice(0, 9)) {
    const card = document.createElement("div");
    card.className = "series-card";
    const head = document.createElement("strong");
    head.textContent = `${episode.index}. ${platformLabel(episode.platform)} · ${episode.pillar}`;
    const title = document.createElement("span");
    title.textContent = episode.title || "";
    const hook = document.createElement("p");
    hook.textContent = episode.hook || "";
    const meta = document.createElement("small");
    meta.textContent = episode.success_metric || "";
    card.append(head, title, hook, meta);
    grid.appendChild(card);
  }
  body.appendChild(grid);

  const notes = document.createElement("ul");
  notes.className = "series-notes";
  for (const note of (plan.reuse_notes || []).slice(0, 4)) {
    const li = document.createElement("li");
    li.textContent = note;
    notes.appendChild(li);
  }
  body.appendChild(notes);
  panel.appendChild(body);
  return panel;
}

function renderPublishSchedulePanel(project) {
  const panel = document.createElement("details");
  panel.className = "publish-schedule-panel";
  const summary = document.createElement("summary");
  const schedule = project.publish_schedule || {};
  summary.textContent = schedule.slots?.length ? `发布排期 · ${schedule.slots.length} 条` : "发布排期";
  panel.appendChild(summary);
  if (!schedule.slots?.length) {
    const empty = document.createElement("div");
    empty.className = "publish-schedule-empty";
    empty.textContent = "暂无发布排期，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  const body = document.createElement("div");
  body.className = "publish-schedule-body";
  const cadence = document.createElement("p");
  cadence.className = "publish-schedule-cadence";
  cadence.textContent = schedule.cadence || "";
  body.appendChild(cadence);

  const list = document.createElement("div");
  list.className = "publish-schedule-list";
  for (const slot of (schedule.slots || []).slice(0, 9)) {
    const card = document.createElement("div");
    card.className = "publish-slot";
    const head = document.createElement("strong");
    head.textContent = `${slot.day} · ${platformLabel(slot.platform)} · ${slot.time_window}`;
    const title = document.createElement("span");
    title.textContent = slot.title || "";
    const asset = document.createElement("small");
    asset.textContent = slot.asset || "";
    const rule = document.createElement("p");
    rule.textContent = slot.decision_rule || "";
    card.append(head, title, asset, rule);
    list.appendChild(card);
  }
  body.appendChild(list);

  const review = document.createElement("ul");
  review.className = "publish-review";
  for (const item of (schedule.daily_review || []).slice(0, 4)) {
    const li = document.createElement("li");
    li.textContent = item;
    review.appendChild(li);
  }
  body.appendChild(review);
  panel.appendChild(body);
  return panel;
}

function renderTitleExperimentPanel(project) {
  const panel = document.createElement("details");
  panel.className = "title-experiment-panel";
  const summary = document.createElement("summary");
  summary.textContent = "标题实验";
  panel.appendChild(summary);

  const rows = project.title_experiments || [];
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "title-experiment-empty";
    empty.textContent = "暂无标题实验表，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  const grouped = groupByPlatform(rows);
  const editor = document.createElement("div");
  editor.className = "title-experiment-editor";
  for (const [platform, platformRows] of Object.entries(grouped)) {
    const group = document.createElement("div");
    group.className = "title-experiment-group";
    const heading = document.createElement("strong");
    heading.textContent = platformLabel(platform);
    group.appendChild(heading);
    for (const row of platformRows) {
      group.appendChild(renderTitleExperimentRow(row));
    }
    editor.appendChild(group);
  }

  const saveBtn = document.createElement("button");
  saveBtn.className = "secondary title-experiment-save";
  saveBtn.type = "button";
  saveBtn.textContent = "保存标题实验";
  saveBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      await saveTitleExperiments(project.id, panel);
    } catch (error) {
      setStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
  panel.append(editor, saveBtn);
  return panel;
}

function groupByPlatform(rows) {
  return rows.reduce((groups, row) => {
    const key = row.platform || "unknown";
    if (!groups[key]) groups[key] = [];
    groups[key].push(row);
    return groups;
  }, {});
}

function renderTitleExperimentRow(row) {
  const item = document.createElement("div");
  item.className = "title-experiment-row";
  item.dataset.platform = row.platform;
  item.dataset.platformName = row.platform_name || platformLabel(row.platform);
  item.dataset.variantIndex = row.variant_index || 0;
  const selected = document.createElement("label");
  selected.className = "title-selected";
  selected.textContent = "主推";
  const checkbox = document.createElement("input");
  checkbox.name = "selected";
  checkbox.type = "checkbox";
  checkbox.checked = row.selected === "yes";
  selected.prepend(checkbox);
  item.append(
    selected,
    titleExperimentInput("title", row.title || "", "标题", true),
    titleExperimentInput("hypothesis", row.hypothesis || "", "假设", true),
    titleExperimentInput("views", row.views || 0, "播放", false, "number"),
    titleExperimentInput("click_rate", row.click_rate || "", "点击率%"),
    titleExperimentInput("publish_url", row.publish_url || "", "链接", true),
    titleExperimentInput("notes", row.notes || "", "结论", true),
  );
  return item;
}

function titleExperimentInput(name, value, label, multiline = false, type = "text") {
  const wrap = document.createElement("label");
  wrap.textContent = label;
  const input = document.createElement(multiline ? "textarea" : "input");
  input.name = name;
  input.value = value;
  if (!multiline) {
    input.type = type;
    if (type === "number") input.min = "0";
  }
  wrap.appendChild(input);
  return wrap;
}

function collectTitleExperiments(panel) {
  return [...panel.querySelectorAll(".title-experiment-row")].map((row) => ({
    platform: row.dataset.platform,
    platform_name: row.dataset.platformName,
    variant_index: Number(row.dataset.variantIndex || 0),
    title: row.querySelector('[name="title"]').value,
    hypothesis: row.querySelector('[name="hypothesis"]').value,
    selected: row.querySelector('[name="selected"]').checked ? "yes" : "",
    publish_url: row.querySelector('[name="publish_url"]').value,
    views: Number(row.querySelector('[name="views"]').value || 0),
    click_rate: row.querySelector('[name="click_rate"]').value,
    notes: row.querySelector('[name="notes"]').value,
  }));
}

async function saveTitleExperiments(projectId, panel) {
  setStatus("保存标题实验", "busy");
  const data = await api("/api/title-experiments", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, title_experiments: collectTitleExperiments(panel) }),
  });
  writeResult(data);
  await refresh();
  setStatus("Ready");
}

function renderPerformancePanel(project) {
  const panel = document.createElement("details");
  panel.className = "performance-panel";
  const summary = document.createElement("summary");
  summary.textContent = "发布复盘";
  panel.appendChild(summary);

  const rows = project.performance || [];
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "performance-empty";
    empty.textContent = "暂无复盘表，生成项目后会自动创建。";
    panel.appendChild(empty);
    return panel;
  }

  panel.appendChild(renderPerformanceInsights(project.performance_insights || {}));
  const editor = document.createElement("div");
  editor.className = "performance-editor";
  for (const row of rows) {
    editor.appendChild(renderPerformanceRow(row));
  }
  const saveBtn = document.createElement("button");
  saveBtn.className = "secondary performance-save";
  saveBtn.type = "button";
  saveBtn.textContent = "保存复盘";
  saveBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      await savePerformance(project.id, panel);
    } catch (error) {
      setStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
  panel.append(editor, saveBtn);
  return panel;
}

function renderPerformanceInsights(insights) {
  const box = document.createElement("div");
  box.className = "performance-insights";
  const best = document.createElement("strong");
  best.textContent = insights.best_platform ? `最佳平台：${platformLabel(insights.best_platform)}` : "等待发布数据";
  box.appendChild(best);
  const metrics = document.createElement("div");
  metrics.className = "performance-metrics";
  for (const row of insights.rows || []) {
    const metric = document.createElement("span");
    metric.textContent = `${platformLabel(row.platform)} 互动${formatPercent(row.engagement_rate)} 收藏${formatPercent(row.favorite_rate)} 涨粉${formatPercent(row.follower_rate)}`;
    metrics.appendChild(metric);
  }
  box.appendChild(metrics);
  const list = document.createElement("ul");
  for (const suggestion of (insights.suggestions || []).slice(0, 3)) {
    const item = document.createElement("li");
    item.textContent = suggestion;
    list.appendChild(item);
  }
  box.appendChild(list);
  return box;
}

function renderPerformanceRow(row) {
  const item = document.createElement("div");
  item.className = "performance-row";
  item.dataset.platform = row.platform;
  const title = document.createElement("strong");
  title.textContent = platformLabel(row.platform);
  item.appendChild(title);
  item.append(
    performanceInput("status", row.status || "planned", "状态"),
    performanceInput("publish_url", row.publish_url || "", "发布链接"),
    performanceInput("views", row.views || 0, "播放", "number"),
    performanceInput("likes", row.likes || 0, "点赞", "number"),
    performanceInput("comments", row.comments || 0, "评论", "number"),
    performanceInput("favorites", row.favorites || 0, "收藏", "number"),
    performanceInput("shares", row.shares || 0, "分享", "number"),
    performanceInput("followers_delta", row.followers_delta || 0, "涨粉", "number"),
    performanceInput("conversion_notes", row.conversion_notes || "", "转化备注"),
    performanceInput("review_notes", row.review_notes || "", "复盘结论"),
  );
  return item;
}

function performanceInput(name, value, label, type = "text") {
  const wrap = document.createElement("label");
  wrap.textContent = label;
  const multiline = ["publish_url", "conversion_notes", "review_notes"].includes(name);
  const input = document.createElement(multiline ? "textarea" : "input");
  input.name = name;
  input.value = value;
  if (!multiline) {
    input.type = type;
    if (type === "number") input.min = "0";
  }
  wrap.appendChild(input);
  return wrap;
}

function collectPerformance(panel) {
  return [...panel.querySelectorAll(".performance-row")].map((row) => ({
    platform: row.dataset.platform,
    status: row.querySelector('[name="status"]').value,
    publish_url: row.querySelector('[name="publish_url"]').value,
    views: Number(row.querySelector('[name="views"]').value || 0),
    likes: Number(row.querySelector('[name="likes"]').value || 0),
    comments: Number(row.querySelector('[name="comments"]').value || 0),
    favorites: Number(row.querySelector('[name="favorites"]').value || 0),
    shares: Number(row.querySelector('[name="shares"]').value || 0),
    followers_delta: Number(row.querySelector('[name="followers_delta"]').value || 0),
    conversion_notes: row.querySelector('[name="conversion_notes"]').value,
    review_notes: row.querySelector('[name="review_notes"]').value,
  }));
}

async function savePerformance(projectId, panel) {
  setStatus("保存复盘", "busy");
  const data = await api("/api/performance", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, performance: collectPerformance(panel) }),
  });
  writeResult(data);
  await refresh();
  setStatus("Ready");
}

function platformLabel(platform) {
  return {
    bilibili: "哔哩哔哩",
    douyin: "抖音",
    xiaohongshu: "小红书",
  }[platform] || platform;
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 1000) / 10}%`;
}

function setLibraryTab(tab) {
  state.activeLibraryTab = tab;
  document.querySelectorAll(".library-tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".library-pane").forEach((pane) => {
    pane.classList.toggle("is-active", pane.dataset.pane === tab);
  });
}

async function createProject() {
  setStatus("生成项目", "busy");
  const data = await api("/api/project", {
    method: "POST",
    body: JSON.stringify(payload()),
  });
  writeResult(data);
  $("subtitleState").textContent = "已生成";
  await refresh();
}

async function generateVoice() {
  const projectId = $("projectId").value.trim();
  if (state.generatingProjectIds.has(projectId)) {
    writeResult({ ok: false, error: "这个项目正在生成视频，请等待当前任务结束。" });
    return;
  }
  setProjectGenerating(projectId, true);
  try {
    setGenerationProgress(8, "准备项目");
    setStatus("生成项目", "busy");
    const project = await api("/api/project", {
      method: "POST",
      body: JSON.stringify(payload()),
    });
    writeResult(project);
    $("subtitleState").textContent = "已生成";
    await refresh();

    setGenerationProgress(32, "生成口播");
    setStatus("生成口播", "busy");
    const voice = await api("/api/voice", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    });
    writeResult(voice);

    setGenerationProgress(62, "生成轻量预览 MP4");
    setStatus("生成视频", "busy");
    const video = await api("/api/video", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        target_duration_seconds: targetDurationSeconds(),
      }),
    });
    writeResult(video);
    await refresh();

    setGenerationProgress(88, "载入预览");
    setStatus("载入预览", "busy");
    const preview = await api(`/api/preview?project=${encodeURIComponent(projectId)}`);
    state.preview = preview;
    writeResult(preview);
    $("subtitlePreview").textContent = preview.subtitles
      .slice(0, 8)
      .map((item) => `${item.index}. ${item.text}`)
      .join("\n\n");
    setupPreviewPlayer(preview);
    $("previewVideo").play().catch(() => {
      $("liveSubtitle").textContent = "浏览器阻止了自动播放，请点下方视频播放按钮";
    });
    setGenerationProgress(100, "生成完成");
    setStatus("Ready");
  } finally {
    setProjectGenerating(projectId, false);
  }
}

async function uploadFiles(kind, files) {
  if (!files.length) return [];
  setStatus("导入文件", "busy");
  const body = new FormData();
  for (const file of files) {
    body.append("files", file, file.name);
  }
  const response = await fetch(`/api/upload?kind=${encodeURIComponent(kind)}`, {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "文件导入失败");
  }
  writeResult(data);
  setStatus("Ready");
  return data.files.map((file) => file.path);
}

async function downloadBgmFromLibrary() {
  const source = currentBgmSource();
  const url = $("bgmUrl").value.trim();
  if (!source) throw new Error("暂无可用 BGM 素材库");
  if (!url) throw new Error("请先粘贴具体音频下载 URL");
  setStatus("导入中文 BGM", "busy");
  const data = await api("/api/bgm-download", {
    method: "POST",
    body: JSON.stringify({ url, source: source.key }),
  });
  appendPaths($("bgmPath"), data.files.map((file) => file.path));
  writeResult(data);
  $("bgmUrl").value = "";
  setStatus("Ready");
}

function setBgmMode(mode) {
  $("bgmLibraryPanel").classList.toggle("is-hidden", mode !== "library");
  $("bgmLocalPanel").classList.toggle("is-hidden", mode !== "local");
}

function setContentMode(mode) {
  $("productFields").classList.toggle("is-hidden", mode !== "product");
  $("scriptText").placeholder =
    mode === "product"
      ? "商品模式可留空，系统会根据商品信息自动生成带货口播稿；也可以在这里粘贴自定义口播稿覆盖模板。"
      : "也可以直接把完整口播稿粘贴到这里。";
}

function openBgmSource() {
  const source = currentBgmSource();
  if (!source) return;
  window.open(source.url, "_blank", "noopener");
}

function appendPaths(target, paths) {
  const current = splitPathList(target.value);
  target.value = [...current, ...paths].join("\n");
}

async function alignSubtitles() {
  setStatus("校准字幕", "busy");
  const data = await api("/api/align", {
    method: "POST",
    body: JSON.stringify({ project_id: $("projectId").value.trim() }),
  });
  writeResult(data);
  $("subtitlePreview").textContent = data.preview || "没有字幕预览";
  $("subtitleState").textContent = data.ok ? "已校准" : "失败";
  setStatus(data.ok ? "Ready" : "失败", data.ok ? "" : "error");
}

async function loadPreview() {
  const projectId = $("projectId").value.trim();
  if (state.generatingProjectIds.has(projectId)) {
    writeResult({ ok: false, error: "这个项目正在生成视频，请等待当前任务结束。" });
    return;
  }
  setGenerationProgress(92, "载入已有预览");
  setStatus("载入预览", "busy");
  const data = await api(`/api/preview?project=${encodeURIComponent(projectId)}`);
  state.preview = data;
  writeResult(data);
  $("subtitlePreview").textContent = data.subtitles
    .slice(0, 8)
    .map((item) => `${item.index}. ${item.text}`)
    .join("\n\n");
  setupPreviewPlayer(data);
  $("previewVideo").play().catch(() => {
    $("liveSubtitle").textContent = "浏览器阻止了自动播放，请点下方视频播放按钮";
  });
  setGenerationProgress(100, data.video_url ? "视频预览已载入" : "音频预览已载入");
  setStatus("Ready");
}

async function loadPlatformPreview(project, platformPackage) {
  $("projectId").value = project.id;
  setStatus("载入平台预览", "busy");
  const data = await api(`/api/preview?project=${encodeURIComponent(project.id)}`);
  data.video_url = platformPackage.video;
  state.preview = data;
  writeResult({
    ok: true,
    project_id: project.id,
    platform: platformPackage.name,
    video_url: platformPackage.video,
    cover: platformPackage.cover,
  });
  $("subtitlePreview").textContent = data.subtitles
    .slice(0, 8)
    .map((item) => `${item.index}. ${item.text}`)
    .join("\n\n");
  setupPreviewPlayer(data);
  $("liveSubtitle").textContent = `${platformPackage.name}版本已载入，点击播放开始预览`;
  setStatus("Ready");
}

async function packagePlatform(project, platformPackage) {
  setStatus("打包发布包", "busy");
  const data = await api("/api/package", {
    method: "POST",
    body: JSON.stringify({ project_id: project.id, platform: platformPackage.key }),
  });
  writeResult(data);
  await refresh();
  window.location.href = data.package_url;
  setStatus("Ready");
}

function setupPreviewPlayer(data) {
  const video = $("previewVideo");
  const stage = document.querySelector(".preview-stage");
  stage.classList.toggle("has-video", Boolean(data.video_url));
  video.src = data.video_url || data.audio_url;
  video.load();
  resetPreviewSeek();
  renderPreviewFrame(0);
  $("liveSubtitle").textContent = data.video_url ? "点击视频播放按钮开始预览" : "点击音频播放按钮开始预览";
}

function currentSubtitle(time) {
  if (!state.preview) return null;
  return state.preview.subtitles.find((item) => time >= item.start && time <= item.end) || null;
}

function renderPreviewFrame(time) {
  if (state.preview?.video_url) return;
  const frame = $("visualFrame");
  const subtitle = currentSubtitle(time);
  const images = state.preview?.images || [];
  frame.innerHTML = "";
  if (images.length) {
    const index = subtitle ? (subtitle.index - 1) % images.length : 0;
    const image = document.createElement("img");
    image.src = images[index];
    image.alt = `preview image ${index + 1}`;
    frame.appendChild(image);
  } else {
    const text = document.createElement("span");
    text.textContent = subtitle?.text || "未导入图片，当前显示字幕预览";
    frame.appendChild(text);
  }
  $("liveSubtitle").textContent = subtitle?.text || " ";
}

function resetPreviewSeek() {
  $("previewSeek").value = 0;
  $("previewSeek").max = 0;
  $("previewCurrentTime").textContent = "00:00";
  $("previewDuration").textContent = "00:00";
}

function updatePreviewSeek(video) {
  if (!Number.isFinite(video.duration)) return;
  $("previewSeek").max = String(video.duration);
  $("previewDuration").textContent = formatClock(video.duration);
  if (!state.previewSeeking) {
    $("previewSeek").value = String(video.currentTime);
  }
  $("previewCurrentTime").textContent = formatClock(video.currentTime);
}

function seekPreviewTo(value) {
  const video = $("previewVideo");
  if (!video.currentSrc && !video.src) return;
  const duration = Number.isFinite(video.duration) ? video.duration : Number($("previewSeek").max || 0);
  if (!duration) return;

  const nextTime = Math.max(0, Math.min(duration, Number(value) || 0));
  $("previewSeek").value = String(nextTime);
  $("previewCurrentTime").textContent = formatClock(nextTime);
  renderPreviewFrame(nextTime);

  try {
    video.currentTime = nextTime;
  } catch {
    if (typeof video.fastSeek === "function") {
      video.fastSeek(nextTime);
    }
  }
}

function formatClock(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function bind(id, fn) {
  $(id).addEventListener("click", async () => {
    try {
      await fn();
      if (id !== "voiceBtn" && id !== "alignBtn") setStatus("Ready");
    } catch (error) {
      setStatus("Error", "error");
      writeResult({ ok: false, error: error.message });
    }
  });
}

bind("refreshBtn", refresh);
bind("voiceBtn", generateVoice);
bind("alignBtn", alignSubtitles);
bind("previewBtn", loadPreview);
$("selectAllProjects").addEventListener("change", (event) => {
  state.selectedProjectIds = event.currentTarget.checked
    ? new Set(state.projects.map((project) => project.id))
    : new Set();
  renderProjects();
});
$("clearProjectSelectionBtn").addEventListener("click", () => {
  state.selectedProjectIds.clear();
  renderProjects();
});
$("deleteProjectsBtn").addEventListener("click", async () => {
  try {
    await deleteSelectedProjects();
  } catch (error) {
    setStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
document.querySelectorAll(".library-tab").forEach((button) => {
  button.addEventListener("click", () => setLibraryTab(button.dataset.tab));
});
$("scriptPickBtn").addEventListener("click", () => $("scriptFileInput").click());
$("bgmPickBtn").addEventListener("click", () => $("bgmFileInput").click());
$("imagePickBtn").addEventListener("click", () => $("imageFileInput").click());
$("bgmSourceSelect").addEventListener("change", renderBgmSourceNote);
$("bgmDownloadBtn").addEventListener("click", async () => {
  try {
    await downloadBgmFromLibrary();
  } catch (error) {
    setStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
$("bgmOpenSourceBtn").addEventListener("click", openBgmSource);
$("projectId").addEventListener("input", () => {
  const projectId = $("projectId").value.trim();
  $("voiceBtn").disabled = state.generatingProjectIds.has(projectId);
  $("previewBtn").disabled = state.generatingProjectIds.has(projectId);
});
document.querySelectorAll('input[name="bgmMode"]').forEach((input) => {
  input.addEventListener("change", (event) => setBgmMode(event.currentTarget.value));
});
document.querySelectorAll('input[name="contentMode"]').forEach((input) => {
  input.addEventListener("change", (event) => setContentMode(event.currentTarget.value));
});
$("scriptFileInput").addEventListener("change", async (event) => {
  try {
    const paths = await uploadFiles("scripts", Array.from(event.currentTarget.files || []));
    $("scriptPath").value = paths[0] || "";
  } catch (error) {
    setStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
$("bgmFileInput").addEventListener("change", async (event) => {
  try {
    const paths = await uploadFiles("bgm", Array.from(event.currentTarget.files || []));
    appendPaths($("bgmPath"), paths);
  } catch (error) {
    setStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
$("imageFileInput").addEventListener("change", async (event) => {
  try {
    const paths = await uploadFiles("images", Array.from(event.currentTarget.files || []));
    appendPaths($("imagePaths"), paths);
  } catch (error) {
    setStatus("Error", "error");
    writeResult({ ok: false, error: error.message });
  }
});
$("clearLogBtn").addEventListener("click", () => {
  $("resultBox").textContent = "等待操作...";
  $("subtitlePreview").textContent = "生成或校准字幕后会显示在这里。";
});

$("previewVideo").addEventListener("timeupdate", (event) => {
  renderPreviewFrame(event.currentTarget.currentTime);
  updatePreviewSeek(event.currentTarget);
});
$("previewVideo").addEventListener("loadedmetadata", (event) => {
  updatePreviewSeek(event.currentTarget);
});
$("previewVideo").addEventListener("durationchange", (event) => {
  updatePreviewSeek(event.currentTarget);
});
$("previewSeek").addEventListener("pointerdown", () => {
  state.previewSeeking = true;
});
$("previewSeek").addEventListener("input", (event) => {
  state.previewSeeking = true;
  seekPreviewTo(event.currentTarget.value);
});
$("previewSeek").addEventListener("pointerup", (event) => {
  seekPreviewTo(event.currentTarget.value);
  state.previewSeeking = false;
  updatePreviewSeek($("previewVideo"));
});
$("previewSeek").addEventListener("change", (event) => {
  seekPreviewTo(event.currentTarget.value);
  state.previewSeeking = false;
  updatePreviewSeek($("previewVideo"));
});

refresh().catch((error) => {
  setStatus("Error", "error");
  writeResult({ ok: false, error: error.message });
});
