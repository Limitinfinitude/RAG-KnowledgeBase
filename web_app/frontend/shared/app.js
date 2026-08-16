(function () {
  "use strict";

  const PORTAL = document.body.getAttribute("data-portal") || "user";
  const PAGE = document.body.getAttribute("data-page") || "chat";
  const IS_INSTANT_PAGE = PAGE === "instant";
  const LOGIN_PAGE = PORTAL === "admin" ? "/admin/login.html" : "/login.html";
  /** 与 GET /api/public/settings 同步；关则隐藏对应页「联网」且请求侧强制 false */
  let _ragWebSearchUiAllowed = true;
  let _instantWebSearchUiAllowed = true;

  const $ = (id) => document.getElementById(id);

  const AUTH_TOKEN_KEY = "rag_auth_token";
  const CHAT_PREFS_KEY = "rag_chat_prefs_v1";
  const RAG_DEFAULTS_SIG_KEY = "rag_rag_defaults_sig_v1";
  const PERSONAS_STORE_KEY = "rag_assistant_personas_v1";
  const DEFAULT_PERSONA_ID = "p_default";
  const MAX_ASSISTANT_PERSONAS = 10;

  function defaultChatPrefs() {
    return {
      preset: "",
      selected_kb: "全部知识库",
      search_mode: "vector",
      enable_reranker: false,
      enable_web_search: false,
      temperature_slider: 0,
      retrieval_k: 10,
      response_style: "balanced",
      active_persona_id: "",
    };
  }

  function defaultPersonasStore() {
    return {
      personas: [
        {
          id: DEFAULT_PERSONA_ID,
          name: "默认助手",
          instruction:
            "在回答时保持专业、准确、友善。优先依据检索到的文档内容作答，并在引用处标注来源编号。若资料不足，请明确说明，不臆测。语气可根据用户问题在正式与亲切之间自然切换。",
          isDefault: true,
        },
      ],
    };
  }

  function normalizePersonasStore(raw) {
    const d = defaultPersonasStore();
    if (!raw || typeof raw !== "object" || !Array.isArray(raw.personas) || !raw.personas.length) {
      return d;
    }
    const personas = raw.personas
      .filter(function (p) {
        return p && p.id;
      })
      .map(function (p) {
        return {
          id: String(p.id),
          name: String(p.name || "未命名").slice(0, 64),
          instruction: String(p.instruction || "").slice(0, 3000),
          isDefault: !!p.isDefault,
        };
      });
    if (!personas.length) return d;
    if (!personas.some(function (p) {
      return p.isDefault;
    })) {
      personas[0].isDefault = true;
    }
    return { personas: personas };
  }

  function getPersonasStore() {
    try {
      const raw = JSON.parse(localStorage.getItem(PERSONAS_STORE_KEY) || "null");
      return normalizePersonasStore(raw);
    } catch {
      return defaultPersonasStore();
    }
  }

  function savePersonasStore(storePersonas) {
    try {
      localStorage.setItem(PERSONAS_STORE_KEY, JSON.stringify(storePersonas));
      schedulePushWebUiState();
    } catch (e) {
      console.warn("personas save", e);
    }
  }

  function getActivePersonaInstruction() {
    const prefs = getChatPrefs();
    const id = prefs.active_persona_id;
    const s = getPersonasStore();
    let p = id ? s.personas.find(function (x) {
      return x.id === id;
    }) : null;
    if (!p) {
      p = s.personas.find(function (x) {
        return x.isDefault;
      }) || s.personas[0];
    }
    return (p && String(p.instruction || "").trim()) || "";
  }

  function getChatPrefs() {
    try {
      const raw = localStorage.getItem(CHAT_PREFS_KEY);
      const j = raw ? JSON.parse(raw) : {};
      return Object.assign(defaultChatPrefs(), j);
    } catch {
      return defaultChatPrefs();
    }
  }

  function setChatPrefs(patch) {
    const next = Object.assign(getChatPrefs(), patch);
    localStorage.setItem(CHAT_PREFS_KEY, JSON.stringify(next));
    schedulePushWebUiState();
  }

  let __webUiPushTimer = null;

  function schedulePushWebUiState() {
    if (!getAuthToken() || currentUser == null || currentUser.id == null) return;
    if (__webUiPushTimer) clearTimeout(__webUiPushTimer);
    __webUiPushTimer = setTimeout(function () {
      __webUiPushTimer = null;
      void pushWebUiState();
    }, 2200);
  }

  async function flushPushWebUiState() {
    if (__webUiPushTimer) {
      clearTimeout(__webUiPushTimer);
      __webUiPushTimer = null;
    }
    await pushWebUiState();
  }

  async function pushWebUiState() {
    if (!getAuthToken() || currentUser == null) return;
    try {
      const kbRaw = localStorage.getItem(getKbConversationStorageKey());
      const instRaw = localStorage.getItem(getInstantConversationStorageKey());
      const payload = {
        chat_prefs: getChatPrefs(),
        personas_store: getPersonasStore(),
        theme: localStorage.getItem("rag_theme") || "dark",
      };
      if (kbRaw != null) payload.conversation_store = kbRaw;
      if (instRaw != null) payload.conversation_store_instant = instRaw;
      await api("/api/auth/web-ui-state", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.warn("web-ui-state push", e);
    }
  }

  async function pullWebUiStateAndApply() {
    if (!getAuthToken() || currentUser == null || currentUser.id == null) return;
    try {
      const s = await api("/api/auth/web-ui-state");
      if (!s || typeof s !== "object") return;
      const kbKey = getKbConversationStorageKey();
      const instKey = getInstantConversationStorageKey();
      if (typeof s.conversation_store === "string" && s.conversation_store.length > 2) {
        try {
          JSON.parse(s.conversation_store);
          localStorage.setItem(kbKey, s.conversation_store);
        } catch (_) {}
      }
      if (typeof s.conversation_store_instant === "string" && s.conversation_store_instant.length > 2) {
        try {
          JSON.parse(s.conversation_store_instant);
          localStorage.setItem(instKey, s.conversation_store_instant);
        } catch (_) {}
      }
      store = loadStoreForCurrentUser();
      if (s.chat_prefs && typeof s.chat_prefs === "object") {
        const merged = Object.assign(defaultChatPrefs(), s.chat_prefs);
        localStorage.setItem(CHAT_PREFS_KEY, JSON.stringify(merged));
      }
      if (s.personas_store && typeof s.personas_store === "object") {
        try {
          localStorage.setItem(
            PERSONAS_STORE_KEY,
            JSON.stringify(normalizePersonasStore(s.personas_store))
          );
        } catch (_) {}
      }
      if (typeof s.theme === "string" && s.theme) {
        localStorage.setItem("rag_theme", s.theme);
        document.documentElement.setAttribute("data-theme", s.theme);
      }
    } catch (e) {
      console.warn("web-ui-state pull", e);
    }
  }

  /** @type {{ id:number, username:string, nickname:string, role:string, is_admin:boolean, avatar?:string|null } | null} */
  let currentUser = null;

  let pendingAvatarClear = false;

  /** 知识库上传队列行 id（与 Service Worker 回传对应） */
  let __kbUploadRowUid = 0;
  /** @type {Record<string, { total:number, done:number, ok:number, fail:number, lastErr:string }>} */
  const __kbSwBatches = Object.create(null);
  let __kbSwMessageWired = false;
  /** @type {string|null|undefined} */
  let pendingAvatarDataUrl = undefined;

  /** 当前朗读中的助手回合索引（与 `data-msg-index` 一致）；null 表示未在播。（浏览器 speechSynthesis） */
  let ttsActiveTurnIndex = null;
  /** 耗时详情浮层所锚定的按钮。 */
  let latencyPopoverAnchor = null;

  function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  }

  function clearAuth() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }

  /** 知识库「文档」标签：文档列表是否展开（默认收起） */
  let kbDocsExpanded = false;

  function kbLatestUploadSummary(documents) {
    const arr = documents || [];
    let best = "";
    arr.forEach(function (d) {
      const t = d.upload_time || "";
      if (t && t > best) best = t;
    });
    return best ? "最近上传：" + best.slice(0, 19).replace("T", " ") : "最近上传：—（暂无文档）";
  }

  const MODE_LABEL = {
    chat: "闲聊",
    rag: "知识库 · 严格依据文档",
    rag_empty: "无命中文档",
    rag_low_score: "低相关检索",
    instant_doc: "即时 · 文档为主",
    instant_web: "即时 · 联网",
    instant_chat: "即时 · 闲聊",
    instant_no_doc: "未附文档",
    error: "错误",
  };

  function uid() {
    return "c_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
  }

  function defaultStore() {
    const id = uid();
    return {
      version: 2,
      currentId: id,
      order: [id],
      conversations: {
        [id]: { title: "新对话", messages: [], updatedAt: Date.now() },
      },
    };
  }

  function conversationStorageKeyBase() {
    if (currentUser != null && currentUser.id != null && currentUser.id !== "") {
      return "rag_web_ui_v2_u_" + currentUser.id;
    }
    return "rag_web_ui_v2_guest";
  }

  /** 知识库智能问答（与即时通道完全分离） */
  function getKbConversationStorageKey() {
    return conversationStorageKeyBase();
  }

  /** 即时文档问答 */
  function getInstantConversationStorageKey() {
    return conversationStorageKeyBase() + "_instant";
  }

  function getConversationStorageKey() {
    return IS_INSTANT_PAGE ? getInstantConversationStorageKey() : getKbConversationStorageKey();
  }

  function parseStorePayload(raw) {
    if (!raw) return defaultStore();
    const d = JSON.parse(raw);
    if (!d.conversations || !d.order || !d.currentId) return defaultStore();
    if (!d.conversations[d.currentId]) {
      const first = d.order[0];
      if (first) d.currentId = first;
      else return defaultStore();
    }
    return d;
  }

  function loadStoreForKey(key) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return defaultStore();
      return parseStorePayload(raw);
    } catch {
      return defaultStore();
    }
  }

  function loadStoreForCurrentUser() {
    const key = getConversationStorageKey();
    return loadStoreForKey(key);
  }

  function saveStore() {
    try {
      localStorage.setItem(getConversationStorageKey(), JSON.stringify(store));
      schedulePushWebUiState();
    } catch (e) {
      console.warn("localStorage", e);
    }
  }

  let store = defaultStore();
  let renameTargetId = null;

  function isDefaultConvTitle(t) {
    const s = String(t || "").trim();
    return s === "新对话" || /^新对话(\s+\d+)?$/.test(s);
  }

  /** 首条用户消息后异步生成侧栏标题（与主对话并行，失败则保持默认标题）。 */
  async function suggestConversationTitle(convId, userText) {
    if (!getAuthToken() || !convId || !userText) return;
    const p = getChatPrefs();
    const preset = (p.preset && String(p.preset).trim()) || null;
    try {
      const r = await api("/api/chat/conversation-title", {
        method: "POST",
        body: JSON.stringify({
          message: String(userText).slice(0, 4000),
          api_config_name: preset,
        }),
      });
      const title = r && r.title != null ? String(r.title).trim() : "";
      if (!title) return;
      if (!store.conversations[convId]) return;
      if (!isDefaultConvTitle(store.conversations[convId].title)) return;
      store.conversations[convId].title = title.slice(0, 80);
      store.conversations[convId].updatedAt = Date.now();
      saveStore();
      renderConvList();
      updateTopbar();
    } catch (_) {}
  }

  function currentConv() {
    return store.conversations[store.currentId];
  }

  function historyForApi(outgoingUserMessage) {
    let list = currentConv()
      .messages.filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content || "" }));
    while (
      list.length &&
      list[list.length - 1].role === "assistant" &&
      !(list[list.length - 1].content || "").trim()
    ) {
      list = list.slice(0, -1);
    }
    const last = list[list.length - 1];
    if (
      last &&
      last.role === "user" &&
      outgoingUserMessage &&
      last.content === outgoingUserMessage
    ) {
      list = list.slice(0, -1);
    }
    return list;
  }

  async function fetchPublicSettings() {
    const r = await fetch("/api/public/settings");
    if (!r.ok) return null;
    return r.json();
  }

  /** 将服务端 RAG 默认写入本地聊天偏好（仅当管理员修改过默认后与上次签名不同才覆盖） */
  function applyWebSearchUiFlagsFromPublicSettings(s) {
    if (!s) return;
    _ragWebSearchUiAllowed = s.rag_show_web_search_ui !== false;
    _instantWebSearchUiAllowed = s.instant_show_web_search_ui !== false;
    const wrapR = $("ragWebSearchWrap");
    if (wrapR) {
      wrapR.hidden = !_ragWebSearchUiAllowed;
      wrapR.style.display = _ragWebSearchUiAllowed ? "" : "none";
    }
    const wrapI = $("instantWebSearchWrap");
    if (wrapI) {
      wrapI.hidden = !_instantWebSearchUiAllowed;
      wrapI.style.display = _instantWebSearchUiAllowed ? "inline-flex" : "none";
    }
    if (PAGE === "chat" && !_ragWebSearchUiAllowed) {
      const ws = $("webSearchToggle");
      if (ws) ws.checked = false;
      setChatPrefs({ enable_web_search: false });
    }
    if (PAGE === "instant" && !_instantWebSearchUiAllowed) {
      const ws = $("webSearchToggle");
      if (ws) ws.checked = false;
      setChatPrefs({ enable_web_search: false });
    }
  }

  async function mergePublicRagPrefsFromServer() {
    const s = await fetchPublicSettings();
    if (!s) return;
    applyWebSearchUiFlagsFromPublicSettings(s);
    if (!s.rag_defaults) return;
    const rd = s.rag_defaults;
    const sig = JSON.stringify(rd);
    try {
      if (localStorage.getItem(RAG_DEFAULTS_SIG_KEY) === sig) return;
      localStorage.setItem(RAG_DEFAULTS_SIG_KEY, sig);
    } catch (_) {
      return;
    }
    const patch = {};
    if (rd.default_retrieval_k != null) {
      const k = parseInt(String(rd.default_retrieval_k), 10);
      if (!Number.isNaN(k)) patch.retrieval_k = k;
    }
    if (rd.default_search_mode === "hybrid" || rd.default_search_mode === "vector") {
      patch.search_mode = rd.default_search_mode;
    }
    if (rd.default_enable_reranker != null) patch.enable_reranker = !!rd.default_enable_reranker;
    if (rd.default_response_style) patch.response_style = String(rd.default_response_style);
    if (rd.default_temperature != null) {
      const t = Number(rd.default_temperature);
      if (!Number.isNaN(t)) patch.temperature_slider = Math.round(t * 10);
    }
    setChatPrefs(patch);
  }

  async function api(path, options = {}) {
    const token = getAuthToken();
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (token) headers["Authorization"] = "Bearer " + token;
    const r = await fetch(path, { ...options, headers });
    if (r.status === 401) {
      clearAuth();
      const next = encodeURIComponent(location.pathname + location.search);
      window.location.href = LOGIN_PAGE + "?next=" + next;
      throw new Error("未登录");
    }
    if (r.status === 403) {
      let msg = "无权访问";
      try {
        const j = await r.json();
        if (j && j.detail) msg = typeof j.detail === "string" ? j.detail : msg;
      } catch (_) {}
      throw new Error(msg);
    }
    if (!r.ok) {
      const t = await r.text();
      throw new Error(t || r.statusText);
    }
    const ct = r.headers.get("content-type");
    if (ct && ct.includes("application/json")) return r.json();
    return r.text();
  }

  function renderMarkdown(el, text) {
    const t = text || "";
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      marked.setOptions({ breaks: true, gfm: true });
      el.innerHTML = DOMPurify.sanitize(marked.parse(t, { async: false }));
    } else {
      el.textContent = t;
    }
    el.classList.add("gpt-md");
  }

  /**
   * 将正文里的 [来源n] / [来源 n] 转为可点击：有网页 URL 则新开标签打开；否则点按展开下方检索块中同序号片段。
   */
  function linkifyInlineSourceCitations(rootEl, sources, blockRoot) {
    if (!rootEl || !sources || !sources.length) return;
    const urlByIndex = new Map();
    sources.forEach(function (s) {
      const ix = Number(s.index);
      if (Number.isNaN(ix)) return;
      const u = sourceEntryHttpUrl(s);
      if (u) urlByIndex.set(ix, u);
    });
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, null);
    const hits = [];
    let tn;
    while ((tn = walker.nextNode())) {
      let p = tn.parentElement;
      let skip = false;
      while (p && p !== rootEl) {
        const tag = p.tagName;
        if (tag === "CODE" || tag === "PRE" || tag === "A") {
          skip = true;
          break;
        }
        p = p.parentElement;
      }
      if (skip) continue;
      if (tn.nodeValue && /\[来源\s*\d+\]/.test(tn.nodeValue)) hits.push(tn);
    }
    hits.forEach(function (textNode) {
      const text = textNode.nodeValue;
      const frag = document.createDocumentFragment();
      let last = 0;
      const re = /\[来源\s*(\d+)\]/g;
      let m;
      let any = false;
      while ((m = re.exec(text)) !== null) {
        any = true;
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        const full = m[0];
        const idx = parseInt(m[1], 10);
        const url = urlByIndex.get(idx);
        const a = document.createElement("a");
        a.className = "gpt-inline-cite";
        a.textContent = full;
        if (url) {
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.title = "打开参考链接";
        } else {
          a.href = "#";
          a.setAttribute("role", "button");
          a.dataset.srcIndex = String(idx);
          a.title = "查看下方对应检索片段";
        }
        frag.appendChild(a);
        last = m.index + full.length;
      }
      if (!any) return;
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      textNode.parentNode.replaceChild(frag, textNode);
    });
  }

  function wireThreadInlineCiteDelegation() {
    const th = $("thread");
    if (!th || th.dataset.inlineCiteWired === "1") return;
    th.dataset.inlineCiteWired = "1";
    th.addEventListener("click", function (ev) {
      const a = ev.target.closest("a.gpt-inline-cite");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || href !== "#") return;
      const sid = a.dataset.srcIndex;
      if (sid == null || sid === "") return;
      ev.preventDefault();
      const blk = a.closest(".gpt-assistant-block");
      if (!blk) return;
      const det = blk.querySelector('details[data-src-index="' + sid + '"]');
      if (det) {
        try {
          det.open = true;
        } catch (_) {}
        det.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  }

  function scorePct(score) {
    if (score == null || Number.isNaN(score)) return "—";
    return Math.min(100, Math.max(0, Math.round(Number(score) * 100))) + "%";
  }

  function sourceEntryHttpUrl(s) {
    const m = s.metadata || {};
    const raw = String(m.url || m.URL || "").trim();
    return /^https?:\/\//i.test(raw) ? raw : "";
  }

  function isWebEvidenceSource(s) {
    if (s.chunk_level === "web") return true;
    const src = String((s.metadata && s.metadata.source) || "").toLowerCase();
    return src.includes("web");
  }

  function buildSourcesBlock(sources) {
    if (!sources || !sources.length) return null;
    const wrap = document.createElement("div");
    wrap.className = "gpt-sources gpt-sources--compact";
    const allWeb = sources.every(isWebEvidenceSource);
    const head = document.createElement("div");
    head.className = "gpt-sources-head";
    head.textContent = allWeb
      ? "联网检索摘要（" + sources.length + "）"
      : "检索片段（" + sources.length + "）";
    wrap.appendChild(head);
    const ul = document.createElement("ul");
    ul.className = "gpt-source-ref-list";
    sources.forEach(function (s) {
      const li = document.createElement("li");
      li.className = "gpt-source-ref";
      const det = document.createElement("details");
      const ixAttr = s.index != null ? String(s.index) : "";
      if (ixAttr !== "") det.setAttribute("data-src-index", ixAttr);
      const sum = document.createElement("summary");
      sum.className = "gpt-source-ref-summary";
      const idxSpan = document.createElement("span");
      idxSpan.className = "gpt-ref-bracket";
      idxSpan.textContent = "[" + (s.index != null ? s.index : "?") + "]";
      sum.appendChild(idxSpan);
      const url = sourceEntryHttpUrl(s);
      const label = String(s.file || "").trim() || "来源";
      sum.appendChild(document.createTextNode(" "));
      if (url) {
        const a = document.createElement("a");
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = "gpt-source-ref-link";
        a.textContent = label;
        a.addEventListener("click", function (ev) {
          ev.stopPropagation();
        });
        sum.appendChild(a);
      } else {
        const sp = document.createElement("span");
        sp.className = "gpt-source-ref-title";
        sp.textContent = label;
        sum.appendChild(sp);
      }
      if (s.score != null && !Number.isNaN(Number(s.score))) {
        const sc = document.createElement("span");
        sc.className = "gpt-ref-score";
        sc.textContent = " · " + scorePct(s.score);
        sum.appendChild(sc);
      }
      det.appendChild(sum);
      const excerpt = document.createElement("div");
      excerpt.className = "gpt-source-ref-excerpt";
      excerpt.textContent = String(s.content || "").trim();
      det.appendChild(excerpt);
      li.appendChild(det);
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showToast(message, type) {
    const host = $("toastHost");
    if (!host || !message) return;
    const t = type || "info";
    const el = document.createElement("div");
    el.className = "gpt-toast gpt-toast-" + (t === "ok" ? "ok" : t === "err" ? "err" : "info");
    el.textContent = message;
    host.appendChild(el);
    const ms = t === "err" ? 4500 : 2800;
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transform = "translateY(8px)";
      el.style.transition = "opacity 0.25s ease, transform 0.25s ease";
      setTimeout(function () {
        el.remove();
      }, 260);
    }, ms);
  }

  function addUploadQueueRow(fileName) {
    const wrap = $("uploadQueueList");
    if (!wrap) return null;
    wrap.hidden = false;
    const row = document.createElement("div");
    row.className = "gpt-upload-queue-row";
    __kbUploadRowUid += 1;
    const uid = __kbUploadRowUid;
    row.id = "gpt-upload-row-" + uid;
    row.dataset.uploadId = String(uid);
    const nm = document.createElement("span");
    nm.className = "gpt-upload-queue-name";
    nm.textContent = fileName || "未命名";
    const st = document.createElement("span");
    st.className = "gpt-upload-queue-status gpt-upload-queue-loading";
    st.textContent = "上传中";
    row.appendChild(nm);
    row.appendChild(st);
    wrap.appendChild(row);
    return row;
  }

  function setUploadQueueRowState(row, ok, detail) {
    if (!row) return;
    const st = row.querySelector(".gpt-upload-queue-status");
    if (!st) return;
    st.className = "gpt-upload-queue-status " + (ok ? "gpt-upload-queue-ok" : "gpt-upload-queue-err");
    st.textContent = ok ? "已完成" : detail || "失败";
  }

  function setUploadRowProcessing(row) {
    if (!row) return;
    const st = row.querySelector(".gpt-upload-queue-status");
    if (!st) return;
    st.className = "gpt-upload-queue-status gpt-upload-queue-loading";
    st.textContent = "后台解析入库中…";
  }

  /** 轮询异步入库任务，直至 done / error 或超时 */
  async function waitForKbIngestJob(jobId) {
    const tok = getAuthToken();
    const uh = {};
    if (tok) uh["Authorization"] = "Bearer " + tok;
    const maxRounds = 900;
    for (let i = 0; i < maxRounds; i++) {
      const r = await fetch("/api/upload/jobs/" + encodeURIComponent(jobId), { headers: uh });
      if (r.status === 401) {
        clearAuth();
        const next = encodeURIComponent(location.pathname + location.search);
        window.location.href = LOGIN_PAGE + "?next=" + next;
        throw new Error("未登录");
      }
      let j = {};
      try {
        j = await r.json();
      } catch (_) {}
      if (!r.ok) {
        const det = j.detail;
        const msg = Array.isArray(det) ? det.map(function (x) {
          return x.msg;
        }).join("; ") : det || r.statusText;
        throw new Error(typeof msg === "string" ? msg : r.statusText);
      }
      if (j.status === "done") return j;
      if (j.status === "error") throw new Error(j.error || "入库失败");
      await new Promise(function (x) {
        setTimeout(x, 1200);
      });
    }
    throw new Error("入库等待超时，请稍后刷新文档列表查看是否已入库");
  }

  function kbSwBatchRecordDone(batchNonce, ok, errMsg) {
    const b = __kbSwBatches[batchNonce];
    if (!b) return;
    b.done += 1;
    if (ok) b.ok += 1;
    else {
      b.fail += 1;
      if (errMsg) b.lastErr = errMsg;
    }
    if (b.done < b.total) return;
    delete __kbSwBatches[batchNonce];
    refreshKbDocs().catch(function () {});
    pingStatus().catch(function () {});
    if (b.fail === 0) showToast("入库完成：成功 " + b.ok + " 个文件", "ok");
    else if (b.ok === 0) showToast("上传失败：" + (b.lastErr || "全部失败"), "err");
    else showToast("完成：成功 " + b.ok + "，失败 " + b.fail, "info");
  }

  function wireKbUploadSwMessageOnce() {
    if (__kbSwMessageWired || typeof navigator === "undefined" || !navigator.serviceWorker) return;
    __kbSwMessageWired = true;
    navigator.serviceWorker.addEventListener("message", function (ev) {
      const d = ev.data;
      if (!d) return;
      if (d.type === "KB_UPLOAD_QUEUED") {
        const row = document.getElementById("gpt-upload-row-" + d.uploadId);
        setUploadRowProcessing(row);
        const bn = d.batchNonce || "";
        const jobId = d.jobId;
        if (!jobId || !bn) return;
        waitForKbIngestJob(jobId).then(
          function () {
            setUploadQueueRowState(row, true, "");
            kbSwBatchRecordDone(bn, true, "");
          },
          function (e) {
            const msg = e && e.message ? e.message : String(e);
            setUploadQueueRowState(row, false, msg);
            kbSwBatchRecordDone(bn, false, msg);
          }
        );
        return;
      }
      if (d.type !== "KB_UPLOAD_DONE") return;
      const row = document.getElementById("gpt-upload-row-" + d.uploadId);
      setUploadQueueRowState(row, d.ok, d.ok ? "" : d.error || "失败");
      const bn = d.batchNonce || "";
      if (!bn) return;
      kbSwBatchRecordDone(bn, d.ok, d.error || "");
    });
  }

  /** @returns {Promise<ServiceWorker|null>} */
  async function getKbUploadSwIfReady() {
    if (typeof navigator === "undefined" || !navigator.serviceWorker) return null;
    if (location.protocol === "file:") return null;
    try {
      const reg = await navigator.serviceWorker.register("/upload-sw.js?v=20260431", {
        scope: "/",
        updateViaCache: "none",
      });
      await navigator.serviceWorker.ready;
      return reg.active || navigator.serviceWorker.controller;
    } catch (e) {
      console.warn("upload-sw register", e);
      return null;
    }
  }

  async function runKbFileUploadsDirect(fileArray) {
    const cat = ($("uploadTargetKb") && $("uploadTargetKb").value) || "默认知识库";
    const desc = ($("uploadDesc") && $("uploadDesc").value) || "";
    let okc = 0;
    let failc = 0;
    let lastErr = "";
    for (let i = 0; i < fileArray.length; i++) {
      const file = fileArray[i];
      const row = addUploadQueueRow(file.name || "未命名");
      try {
        await uploadSingleFileToKb(file, cat, desc, row);
        okc++;
        setUploadQueueRowState(row, true, "");
      } catch (e) {
        failc++;
        lastErr = e.message || String(e);
        setUploadQueueRowState(row, false, lastErr);
      }
    }
    refreshKbDocs().catch(function () {});
    pingStatus().catch(function () {});
    if (failc === 0) showToast("入库完成：成功 " + okc + " 个文件", "ok");
    else if (okc === 0) showToast("上传失败：" + (lastErr || "全部失败"), "err");
    else showToast("完成：成功 " + okc + "，失败 " + failc, "info");
  }

  async function runKbFileUploadsViaServiceWorker(fileArray, sw) {
    const cat = ($("uploadTargetKb") && $("uploadTargetKb").value) || "默认知识库";
    const desc = ($("uploadDesc") && $("uploadDesc").value) || "";
    const batchNonce =
      Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 12);
    const token = getAuthToken() || "";
    __kbSwBatches[batchNonce] = {
      total: fileArray.length,
      done: 0,
      ok: 0,
      fail: 0,
      lastErr: "",
    };
    for (let i = 0; i < fileArray.length; i++) {
      const file = fileArray[i];
      const row = addUploadQueueRow(file.name || "未命名");
      const uid = row && row.dataset.uploadId ? parseInt(row.dataset.uploadId, 10) : 0;
      if (!uid) continue;
      let ab;
      try {
        ab = await file.arrayBuffer();
      } catch (e) {
        const msg = e && e.message ? e.message : String(e);
        setUploadQueueRowState(row, false, msg);
        kbSwBatchRecordDone(batchNonce, false, msg);
        continue;
      }
      try {
        sw.postMessage(
          {
            type: "KB_UPLOAD",
            uploadId: uid,
            batchNonce: batchNonce,
            token: token,
            category: cat,
            description: desc,
            fileName: file.name || "未命名",
            mime: file.type || "",
            buffer: ab,
          },
          [ab]
        );
      } catch (e) {
        const msg = e && e.message ? e.message : String(e);
        setUploadQueueRowState(row, false, msg);
        kbSwBatchRecordDone(batchNonce, false, msg);
      }
    }
  }

  async function uploadSingleFileToKb(file, category, description, row) {
    const fd = new FormData();
    fd.append("category", category);
    fd.append("description", description || "");
    fd.append("files", file);
    const tok = getAuthToken();
    const uh = {};
    if (tok) uh["Authorization"] = "Bearer " + tok;
    const r = await fetch("/api/upload", { method: "POST", body: fd, headers: uh });
    let data;
    try {
      data = await r.json();
    } catch {
      data = {};
    }
    if (!r.ok) {
      const d = data.detail;
      const msg = Array.isArray(d) ? d.map((x) => x.msg).join("; ") : d || r.statusText;
      throw new Error(typeof msg === "string" ? msg : r.statusText);
    }
    const results = data.results || [];
    const first = results[0];
    if (!first || !first.ok) {
      throw new Error((first && first.error) || "入库失败");
    }
    if (first.queued && first.job_id) {
      setUploadRowProcessing(row);
      await waitForKbIngestJob(first.job_id);
    }
    return first;
  }

  async function runKbFileUploads(fileArray) {
    wireKbUploadSwMessageOnce();
    const sw = await getKbUploadSwIfReady();
    if (sw) await runKbFileUploadsViaServiceWorker(fileArray, sw);
    else await runKbFileUploadsDirect(fileArray);
  }

  function statusCodeClass(code) {
    const n = parseInt(code, 10);
    if (n >= 200 && n < 300) return "gpt-code-2xx";
    if (n >= 400 && n < 500) return "gpt-code-4xx";
    if (n >= 500) return "gpt-code-5xx";
    return "";
  }

  const MSG_TOOLBAR_SVG = {
    regen:
      '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    tts:
      '<path d="M11 5 6 9H3v6h3l5 4V5z"/><path d="M15.54 8.46a5 5 0 0 1 .01 7.07"/><path d="M17.66 6.34a8 8 0 0 1 .01 11.32"/>',
    bubble:
      '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    copy:
      '<rect x="8" y="8" width="12" height="12" rx="2" ry="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>',
    share:
      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    good:
      '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-1.8 6.5A2 2 0 0 1 17.07 21H9a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2h.5"/>',
    bad:
      '<path d="M17 14V2"/><path d="M9 18H7.17a2 2 0 0 1-1.92-2.56l1.8-6.5A2 2 0 0 1 8.93 7H17a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-.5"/>',
    more:
      '<circle cx="5" cy="12" r="1.25"/><circle cx="12" cy="12" r="1.25"/><circle cx="19" cy="12" r="1.25"/>',
  };

  function createMsgToolbarButton(action, title) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "gpt-msg-action";
    b.dataset.action = action;
    b.title = title;
    b.setAttribute("aria-label", title);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "gpt-msg-ico");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.75");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const paths = MSG_TOOLBAR_SVG[action] || "";
    if (paths) svg.innerHTML = paths;
    b.appendChild(svg);
    return b;
  }

  function appendMsgToolbar(bar, m) {
    const order = [
      ["regen", "重新生成"],
      ["tts", "朗读"],
      ["bubble", "查看引用"],
      ["copy", "复制"],
      ["share", "分享"],
      ["good", "有用"],
      ["bad", "需改进"],
      ["more", "更多"],
    ];
    order.forEach(function (pair) {
      bar.appendChild(createMsgToolbarButton(pair[0], pair[1]));
    });
    if (m.latencyMs != null && m.latencyMs >= 0) {
      const lb = document.createElement("button");
      lb.type = "button";
      lb.className = "gpt-msg-latency";
      lb.setAttribute("aria-expanded", "false");
      applyLatencyButtonContent(lb, m);
      bar.appendChild(lb);
    }
  }

  function applyLatencyButtonContent(btn, m) {
    const t = m.timing || {};
    const resp = t.msResponse != null ? t.msResponse : m.latencyMs;
    const firstTok = t.msFirstToken != null ? t.msFirstToken : m.latencyMs;
    btn.textContent = firstTok + "ms";
    btn.title = "点击查看耗时详情";
    btn.setAttribute("aria-label", "首字耗时 " + firstTok + " 毫秒，点击查看详情");
    btn.dataset.timingJson = JSON.stringify({
      chunk: t.msFirstChunk != null ? t.msFirstChunk : resp,
      firstToken: firstTok,
      summaryToken: t.msFirstSummaryToken != null ? t.msFirstSummaryToken : firstTok,
      responseMs: resp,
    });
  }

  function ensureLatencyPopover() {
    let pop = $("gptLatencyPopover");
    if (pop) return pop;
    pop = document.createElement("div");
    pop.id = "gptLatencyPopover";
    pop.className = "gpt-latency-popover";
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-modal", "false");
    pop.setAttribute("aria-label", "耗时详情");
    document.body.appendChild(pop);
    return pop;
  }

  function formatResponseTimeLabel(ms) {
    if (ms == null || Number.isNaN(ms)) return "—";
    if (ms >= 1000) return (ms / 1000).toFixed(3) + "s";
    return ms + "ms";
  }

  function positionLatencyPopover(anchor, pop) {
    const r = anchor.getBoundingClientRect();
    const margin = 8;
    pop.style.position = "fixed";
    pop.style.visibility = "hidden";
    pop.hidden = false;
    const pr = pop.getBoundingClientRect();
    let left = r.right - pr.width;
    if (left < margin) left = margin;
    if (left + pr.width > window.innerWidth - margin) {
      left = window.innerWidth - pr.width - margin;
    }
    let top = r.bottom + margin;
    if (top + pr.height > window.innerHeight - margin) {
      top = r.top - pr.height - margin;
    }
    if (top < margin) top = margin;
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    pop.style.visibility = "";
  }

  function toggleLatencyPopover(anchorBtn) {
    const pop = ensureLatencyPopover();
    if (!pop.hidden && latencyPopoverAnchor === anchorBtn) {
      closeLatencyPopover();
      return;
    }
    closeLatencyPopover();
    latencyPopoverAnchor = anchorBtn;
    let data;
    try {
      data = JSON.parse(anchorBtn.dataset.timingJson || "{}");
    } catch (_) {
      data = {};
    }
    const respMs = data.responseMs;
    const respStr = formatResponseTimeLabel(respMs);
    const row = function (label, val) {
      return (
        "<div class=\"gpt-latency-row\"><span class=\"gpt-latency-k\">" +
        label +
        "</span><span class=\"gpt-latency-v\">" +
        val +
        "</span></div>"
      );
    };
    pop.innerHTML =
      "<div class=\"gpt-latency-popover-inner\">" +
      row("Time to first chunk", (data.chunk != null ? data.chunk : "—") + "ms") +
      row("Time to first token", (data.firstToken != null ? data.firstToken : "—") + "ms") +
      row("Time to first summary token", (data.summaryToken != null ? data.summaryToken : "—") + "ms") +
      row("Response time", respStr) +
      "</div>";
    pop.hidden = false;
    anchorBtn.setAttribute("aria-expanded", "true");
    requestAnimationFrame(function () {
      positionLatencyPopover(anchorBtn, pop);
    });
  }

  function closeLatencyPopover() {
    const pop = $("gptLatencyPopover");
    if (pop) pop.hidden = true;
    if (latencyPopoverAnchor) {
      latencyPopoverAnchor.setAttribute("aria-expanded", "false");
      latencyPopoverAnchor = null;
    }
  }

  function initLatencyPopover() {
    if (document.documentElement.dataset.gptLatencyPopoverWired === "1") return;
    document.documentElement.dataset.gptLatencyPopoverWired = "1";
    document.addEventListener("click", function (e) {
      const thread = $("thread");
      const lat = e.target.closest(".gpt-msg-latency");
      if (thread && lat && thread.contains(lat)) {
        e.preventDefault();
        toggleLatencyPopover(lat);
        return;
      }
      const pop = $("gptLatencyPopover");
      if (pop && !pop.hidden && !pop.contains(e.target)) {
        closeLatencyPopover();
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeLatencyPopover();
    });
    window.addEventListener(
      "resize",
      function () {
        closeLatencyPopover();
      },
      { passive: true }
    );
  }

  function stopAllSpeech() {
    try {
      if (typeof window.speechSynthesis !== "undefined") window.speechSynthesis.cancel();
    } catch (_) {}
    ttsActiveTurnIndex = null;
    document.querySelectorAll(".gpt-msg-tts-playing").forEach(function (el) {
      el.classList.remove("gpt-msg-tts-playing");
    });
  }

  function syncAssistantSourcesBlock(block, sources) {
    if (!block) return;
    const actions = block.querySelector(".gpt-assistant-actions");
    const old = block.querySelector(".gpt-sources");
    if (!sources || !sources.length) {
      if (old) old.remove();
      return;
    }
    const blk = buildSourcesBlock(sources);
    if (!blk) return;
    if (old) old.replaceWith(blk);
    else if (actions) block.insertBefore(blk, actions);
    else block.appendChild(blk);
  }

  let chatStreamController = null;
  let sendBtnDefaultAria = null;
  let sendBtnDefaultHtml = null;
  /** 流式生成期间防抖写入，避免切换页面前未落盘导致回来后只有加载圈 */
  let __streamSaveTimer = null;

  function scheduleStreamSave() {
    if (__streamSaveTimer) clearTimeout(__streamSaveTimer);
    __streamSaveTimer = setTimeout(function () {
      __streamSaveTimer = null;
      try {
        saveStore();
      } catch (_) {}
    }, 350);
  }

  /** 修复：未完成流式就离开页面时，会话里可能留下 content 为空的 assistant，渲染会一直转圈 */
  function repairOrphanAssistantMessagesInStore() {
    if (PAGE !== "chat" && PAGE !== "instant") return false;
    let changed = false;
    Object.keys(store.conversations || {}).forEach(function (cid) {
      const c = store.conversations[cid];
      const msgs = c.messages;
      if (!msgs || msgs.length < 2) return;
      const last = msgs[msgs.length - 1];
      const prev = msgs[msgs.length - 2];
      if (last.role !== "assistant" || prev.role !== "user") return;
      if (String(last.content || "").trim()) return;
      last.content =
        "（生成已中断，未保存完整回复；请在本条下使用「重试」，或重新发送同一问题。）";
      last.meta = (last.meta || "").trim() ? last.meta + " · 已中断" : "已中断";
      if (last.latencyMs == null) last.latencyMs = 0;
      changed = true;
    });
    if (changed) {
      try {
        localStorage.setItem(getConversationStorageKey(), JSON.stringify(store));
      } catch (e) {
        console.warn("localStorage", e);
      }
    }
    return changed;
  }

  function getThreadScrollContainer() {
    const th = $("thread");
    if (!th) return null;
    return th.closest(".gpt-thread-wrap") || th;
  }

  function scrollThreadToBottom() {
    const el = getThreadScrollContainer();
    if (!el) return;
    const run = function () {
      el.scrollTop = el.scrollHeight;
    };
    run();
    requestAnimationFrame(function () {
      requestAnimationFrame(run);
    });
  }

  function isThreadNearBottom() {
    const el = getThreadScrollContainer();
    if (!el) return true;
    const tol = 80;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= tol;
  }

  function updateJumpToLatestVisibility() {
    const btn = $("btnScrollToLatest");
    const wrap = $("jumpLatestWrap");
    if (!btn || !wrap) return;
    const th = $("thread");
    const conv = currentConv();
    const hasMsgs = conv && (conv.messages || []).length > 0;
    const threadVisible = th && !th.hidden;
    const show = !!(hasMsgs && threadVisible && !isThreadNearBottom());
    btn.hidden = !show;
    wrap.hidden = !show;
  }

  function ensureJumpToLatestButton() {
    if (PAGE !== "chat" && PAGE !== "instant") return null;
    if ($("btnScrollToLatest")) return $("btnScrollToLatest");
    const form = $("form");
    const area = $("composerArea");
    if (!form || !area) return null;
    let shell = $("composerFormShell");
    if (!shell) {
      if (form.parentNode !== area) return null;
      shell = document.createElement("div");
      shell.className = "gpt-composer-form-shell";
      shell.id = "composerFormShell";
      area.insertBefore(shell, form);
      shell.appendChild(form);
    }
    const wrap = document.createElement("div");
    wrap.className = "gpt-jump-latest-wrap";
    wrap.id = "jumpLatestWrap";
    wrap.hidden = true;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "btnScrollToLatest";
    btn.className = "gpt-jump-latest";
    btn.setAttribute("aria-label", "回到底部");
    btn.hidden = true;
    btn.innerHTML =
      '<svg class="gpt-jump-latest-svg" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    wrap.appendChild(btn);
    shell.insertBefore(wrap, form);
    btn.addEventListener("click", function () {
      scrollThreadToBottom();
      updateJumpToLatestVisibility();
    });
    return btn;
  }

  function wireThreadScrollJumpUi() {
    if (PAGE !== "chat" && PAGE !== "instant") return;
    ensureJumpToLatestButton();
    const sc = getThreadScrollContainer();
    if (!sc || sc.dataset.jumpScrollWired === "1") return;
    sc.dataset.jumpScrollWired = "1";
    sc.addEventListener(
      "scroll",
      function () {
        updateJumpToLatestVisibility();
      },
      { passive: true }
    );
  }

  function setComposerSendStreaming(streaming) {
    const sendEl = $("send");
    if (!sendEl) return;
    if (sendBtnDefaultAria == null) {
      sendBtnDefaultAria = sendEl.getAttribute("aria-label") || "\u53d1\u9001";
      sendBtnDefaultHtml = sendEl.innerHTML.trim() || "\u2192";
    }
    if (streaming) {
      sendEl.disabled = false;
      sendEl.removeAttribute("disabled");
      sendEl.classList.add("gpt-send-stop");
      sendEl.setAttribute("aria-label", "\u7ec8\u6b62\u751f\u6210");
      sendEl.textContent = "\u25a0";
      sendEl.dataset.streamingStop = "1";
    } else {
      sendEl.classList.remove("gpt-send-stop");
      sendEl.setAttribute("aria-label", sendBtnDefaultAria);
      sendEl.innerHTML = sendBtnDefaultHtml;
      delete sendEl.dataset.streamingStop;
    }
  }

  function abortActiveChatStream() {
    const c = chatStreamController;
    if (!c) return;
    try {
      c.abort();
    } catch (_) {}
  }

  function finishAssistantStreamTurn(turnEl, block, actionsEl, msg) {
    if (turnEl) delete turnEl.dataset.streaming;
    if (actionsEl && msg && msg.latencyMs != null) {
      let lb = actionsEl.querySelector(".gpt-msg-latency");
      if (!lb) {
        lb = document.createElement("button");
        lb.type = "button";
        lb.className = "gpt-msg-latency";
        lb.setAttribute("aria-expanded", "false");
        actionsEl.appendChild(lb);
      }
      applyLatencyButtonContent(lb, msg);
    }
    if (isThreadNearBottom()) scrollThreadToBottom();
    updateJumpToLatestVisibility();
  }

  function renderThread() {
    const thread = $("thread");
    if (!thread) return;
    thread.innerHTML = "";
    currentConv().messages.forEach((m, i) => {
      thread.appendChild(buildTurnEl(m, i));
    });
    scrollThreadToBottom();
    updateJumpToLatestVisibility();
  }

  function buildTurnEl(m, msgIndex) {
    const turn = document.createElement("div");
    turn.className = "gpt-turn " + (m.role === "user" ? "gpt-turn-user" : "gpt-turn-assistant");
    turn.dataset.msgIndex = String(msgIndex);

    if (m.role === "user") {
      const row = document.createElement("div");
      row.className = "gpt-turn-row";
      const bubble = document.createElement("div");
      bubble.className = "gpt-user-bubble";
      bubble.textContent = m.content || "";
      row.appendChild(bubble);
      turn.appendChild(row);
      return turn;
    }

    const row = document.createElement("div");
    row.className = "gpt-turn-row";
    const block = document.createElement("div");
    block.className = "gpt-assistant-block";

    const meta = document.createElement("div");
    meta.className = "gpt-turn-meta";
    if (m.meta) meta.textContent = m.meta;
    else meta.hidden = true;
    block.appendChild(meta);

    const hasText = String(m.content || "").trim();
    if (!hasText) {
      const loadingWrap = document.createElement("div");
      loadingWrap.className = "gpt-assistant-loading";
      loadingWrap.setAttribute("role", "status");
      loadingWrap.setAttribute("aria-label", "正在生成回复");
      const spin = document.createElement("span");
      spin.className = "gpt-spinner";
      spin.setAttribute("aria-hidden", "true");
      loadingWrap.appendChild(spin);
      block.appendChild(loadingWrap);
    }

    const body = document.createElement("div");
    body.className = "gpt-assistant-body";
    renderMarkdown(body, m.content || "");
    block.appendChild(body);

    if (m.sources && m.sources.length) {
      const blk = buildSourcesBlock(m.sources);
      if (blk) block.appendChild(blk);
    }

    const bar = document.createElement("div");
    bar.className = "gpt-assistant-actions";
    bar.setAttribute("role", "toolbar");
    appendMsgToolbar(bar, m);
    block.appendChild(bar);
    linkifyInlineSourceCitations(body, m.sources || [], block);
    row.appendChild(block);
    turn.appendChild(row);
    return turn;
  }

  function appendTurnToDom(m) {
    const th = $("thread");
    if (!th) return;
    const i = currentConv().messages.length - 1;
    const stickToBottom = isThreadNearBottom();
    th.appendChild(buildTurnEl(m, i));
    if (stickToBottom) scrollThreadToBottom();
    updateJumpToLatestVisibility();
  }

  function regenerateAssistantAtIndex(assistantIndex) {
    const conv = currentConv();
    const msgs = conv.messages;
    if (assistantIndex < 1 || assistantIndex >= msgs.length) return;
    if (msgs[assistantIndex].role !== "assistant") return;
    const prev = msgs[assistantIndex - 1];
    if (prev.role !== "user" || !(String(prev.content || "").trim())) return;
    const userText = String(prev.content).trim();
    conv.messages = msgs.slice(0, assistantIndex);
    conv.updatedAt = Date.now();
    saveStore();
    renderThread();
    updateTopbar();
    void runChatCompletionForUserText(userText);
  }

  async function runChatCompletionForUserText(userText) {
    readChatPrefsFromForm();
    const th = $("thread");
    chatStreamController = new AbortController();
    const signal = chatStreamController.signal;
    setComposerSendStreaming(true);
    const t0 = performance.now();
    let msFirstChunk = null;
    let msFirstToken = null;
    let msFirstSummaryToken = null;
    let streamTextChunkCount = 0;

    const assistantMsg = {
      role: "assistant",
      content: "",
      meta: "",
      sources: [],
      latencyMs: null,
      timing: null,
    };
    currentConv().messages.push(assistantMsg);
    saveStore();
    appendTurnToDom(assistantMsg);
    updateTopbar();

    const turnEl = th && th.lastElementChild;
    const block = turnEl && turnEl.querySelector(".gpt-assistant-block");
    const metaEl = block && block.querySelector(".gpt-turn-meta");
    const bodyEl = block && block.querySelector(".gpt-assistant-body");
    const actionsEl = block && block.querySelector(".gpt-assistant-actions");
    if (turnEl) turnEl.dataset.streaming = "1";

    let contentAcc = "";
    function removeAssistantLoading() {
      if (!block) return;
      const ld = block.querySelector(".gpt-assistant-loading");
      if (ld) ld.remove();
    }
    function flushMd() {
      if (block && contentAcc.trim()) removeAssistantLoading();
      if (bodyEl) {
        renderMarkdown(bodyEl, contentAcc);
        linkifyInlineSourceCitations(bodyEl, assistantMsg.sources || [], block);
        if (isThreadNearBottom()) scrollThreadToBottom();
        updateJumpToLatestVisibility();
      }
    }
    const token = getAuthToken();
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson, application/json",
    };
    if (token) headers["Authorization"] = "Bearer " + token;

    const chatUrl = IS_INSTANT_PAGE ? "/api/chat/instant" : "/api/chat";
    const chatBody = IS_INSTANT_PAGE
      ? collectInstantChatBody(userText, true)
      : collectChatBody(userText, true);
    try {
      const res = await fetch(chatUrl, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(chatBody),
        signal,
      });
      if (res.status === 401) {
        clearAuth();
        const next = encodeURIComponent(location.pathname + location.search);
        window.location.href = LOGIN_PAGE + "?next=" + next;
        return;
      }
      if (res.status === 403) {
        let msg = "无权访问";
        try {
          const j = await res.json();
          if (j && j.detail) msg = typeof j.detail === "string" ? j.detail : msg;
        } catch (_) {}
        throw new Error(msg);
      }

      const ct = (res.headers.get("content-type") || "").toLowerCase();
      if (ct.includes("application/json")) {
        const j = await res.json();
        if (!res.ok) {
          const det = j.detail;
          throw new Error(typeof det === "string" ? det : res.statusText || "请求失败");
        }
        const answerText =
          j.error && !j.answer ? "错误：" + j.error : j.answer || "（无内容）";
        contentAcc = answerText;
        assistantMsg.content = answerText;
        assistantMsg.sources = j.sources || [];
        const modeZh = MODE_LABEL[j.mode] || j.mode;
        let meta = "模式：" + modeZh;
        if (j.retrieval_query && j.retrieval_query !== userText) {
          meta = "检索用语：" + j.retrieval_query + " · " + meta;
        }
        if (j.error && j.answer) meta += " · " + j.error;
        assistantMsg.meta = meta;
        const latencyMs = Math.round(performance.now() - t0);
        assistantMsg.latencyMs = latencyMs;
        assistantMsg.timing = {
          msFirstChunk: latencyMs,
          msFirstToken: latencyMs,
          msFirstSummaryToken: latencyMs,
          msResponse: latencyMs,
        };
        saveStore();
        if (metaEl) {
          metaEl.hidden = !meta;
          metaEl.textContent = meta;
        }
        syncAssistantSourcesBlock(block, assistantMsg.sources);
        flushMd();
        finishAssistantStreamTurn(turnEl, block, actionsEl, assistantMsg);
        return;
      }

      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }

      const reader = res.body && res.body.getReader();
      if (!reader) throw new Error("无法读取响应流");

      const dec = new TextDecoder();
      let lineBuf = "";
      async function handleStreamEvent(ev) {
        if (!ev || typeof ev !== "object") return;
        if (ev.type === "meta") {
          const modeZh = MODE_LABEL[ev.mode] || ev.mode;
          let meta = "模式：" + modeZh;
          if (ev.retrieval_query && ev.retrieval_query !== userText) {
            meta = "检索用语：" + ev.retrieval_query + " · " + meta;
          }
          if (ev.error) meta += " · " + ev.error;
          assistantMsg.meta = meta;
          assistantMsg.sources = ev.sources || [];
          saveStore();
          if (metaEl) {
            metaEl.hidden = !meta;
            metaEl.textContent = meta;
          }
          syncAssistantSourcesBlock(block, assistantMsg.sources);
          if (isThreadNearBottom()) scrollThreadToBottom();
          updateJumpToLatestVisibility();
          return;
        }
        if (ev.type === "chunk" && ev.text) {
          streamTextChunkCount++;
          const relNow = Math.round(performance.now() - t0);
          if (streamTextChunkCount === 1) msFirstToken = relNow;
          if (streamTextChunkCount === 2) msFirstSummaryToken = relNow;
          contentAcc += ev.text;
          assistantMsg.content = contentAcc;
          scheduleStreamSave();
          flushMd();
        }
      }

      try {
        while (true) {
          const step = await reader.read();
          if (step.done) break;
          if (step.value && step.value.byteLength > 0 && msFirstChunk == null) {
            msFirstChunk = Math.round(performance.now() - t0);
          }
          lineBuf += dec.decode(step.value, { stream: true });
          const parts = lineBuf.split("\n");
          lineBuf = parts.pop() || "";
          for (let pi = 0; pi < parts.length; pi++) {
            const line = parts[pi];
            if (!line.trim()) continue;
            try {
              await handleStreamEvent(JSON.parse(line));
            } catch (_) {}
          }
        }
        if (lineBuf.trim()) {
          try {
            await handleStreamEvent(JSON.parse(lineBuf));
          } catch (_) {}
        }
      } finally {
        try {
          reader.releaseLock();
        } catch (_) {}
      }

      assistantMsg.content = contentAcc;
      const latencyMs = Math.round(performance.now() - t0);
      assistantMsg.latencyMs = latencyMs;
      assistantMsg.timing = {
        msFirstChunk: msFirstChunk != null ? msFirstChunk : latencyMs,
        msFirstToken: msFirstToken != null ? msFirstToken : latencyMs,
        msFirstSummaryToken:
          msFirstSummaryToken != null
            ? msFirstSummaryToken
            : msFirstToken != null
              ? msFirstToken
              : latencyMs,
        msResponse: latencyMs,
      };
      saveStore();
      flushMd();
      finishAssistantStreamTurn(turnEl, block, actionsEl, assistantMsg);
    } catch (err) {
      const latencyMs = Math.round(performance.now() - t0);
      const aborted = err && err.name === "AbortError";
      const errText = err.message || String(err);
      assistantMsg.content = contentAcc;
      if (aborted) {
        showToast("\u5df2\u505c\u6b62\u751f\u6210", "info");
        if (!String(contentAcc || "").trim()) {
          contentAcc = "\uff08\u5df2\u505c\u6b62\u751f\u6210\uff09";
          assistantMsg.content = contentAcc;
        }
        const prev = (assistantMsg.meta || "").trim();
        assistantMsg.meta = prev
          ? prev + " \u00b7 \u5df2\u505c\u6b62\u751f\u6210"
          : "\u5df2\u505c\u6b62\u751f\u6210";
      } else if (!contentAcc.trim()) {
        contentAcc = errText;
        assistantMsg.content = errText;
        assistantMsg.meta = assistantMsg.meta || "\u8bf7\u6c42\u5931\u8d25";
      } else {
        assistantMsg.meta = assistantMsg.meta || "\u8bf7\u6c42\u5931\u8d25";
      }
      assistantMsg.latencyMs = latencyMs;
      assistantMsg.timing = {
        msFirstChunk: latencyMs,
        msFirstToken: latencyMs,
        msFirstSummaryToken: latencyMs,
        msResponse: latencyMs,
      };
      saveStore();
      if (metaEl) {
        metaEl.hidden = !assistantMsg.meta;
        metaEl.textContent = assistantMsg.meta;
      }
      flushMd();
      finishAssistantStreamTurn(turnEl, block, actionsEl, assistantMsg);
    } finally {
      if (__streamSaveTimer) {
        clearTimeout(__streamSaveTimer);
        __streamSaveTimer = null;
      }
      removeAssistantLoading();
      chatStreamController = null;
      setComposerSendStreaming(false);
      $("input")?.focus();
      closeMobileSidebar();
    }
  }

  function initThreadActionBar() {
    const thread = $("thread");
    if (!thread || thread.dataset.actionsWired === "1") return;
    thread.dataset.actionsWired = "1";
    thread.addEventListener("click", function (e) {
      const btn = e.target.closest(".gpt-msg-action[data-action]");
      if (!btn || !thread.contains(btn)) return;
      const action = btn.getAttribute("data-action");
      const turn = btn.closest(".gpt-turn");
      if (!turn || !turn.classList.contains("gpt-turn-assistant")) return;
      const idx = parseInt(turn.dataset.msgIndex, 10);
      if (Number.isNaN(idx)) return;

      if (action === "copy") {
        const body = turn.querySelector(".gpt-assistant-body");
        const text = body ? (body.innerText || "").trim() : "";
        if (text) {
          navigator.clipboard.writeText(text).then(
            () => showToast("已复制到剪贴板", "ok"),
            () => showToast("复制失败", "err")
          );
        }
        return;
      }
      if (action === "tts") {
        const body = turn.querySelector(".gpt-assistant-body");
        const text = body ? (body.innerText || "").trim() : "";
        if (!text || typeof window.speechSynthesis === "undefined") return;
        if (ttsActiveTurnIndex === idx && window.speechSynthesis.speaking) {
          window.speechSynthesis.cancel();
          ttsActiveTurnIndex = null;
          btn.classList.remove("gpt-msg-tts-playing");
          return;
        }
        window.speechSynthesis.cancel();
        document.querySelectorAll(".gpt-msg-tts-playing").forEach(function (el) {
          el.classList.remove("gpt-msg-tts-playing");
        });
        ttsActiveTurnIndex = idx;
        btn.classList.add("gpt-msg-tts-playing");
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "zh-CN";
        u.onend = function () {
          btn.classList.remove("gpt-msg-tts-playing");
          if (ttsActiveTurnIndex === idx) ttsActiveTurnIndex = null;
        };
        u.onerror = function () {
          btn.classList.remove("gpt-msg-tts-playing");
          if (ttsActiveTurnIndex === idx) ttsActiveTurnIndex = null;
        };
        window.speechSynthesis.speak(u);
        return;
      }
      if (action === "regen") {
        if (turn.dataset.streaming === "1") return;
        regenerateAssistantAtIndex(idx);
        return;
      }
      if (action === "bubble") {
        const det = turn.querySelector(".gpt-sources details");
        if (det) {
          det.open = true;
          det.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } else {
          showToast("本轮暂无检索片段", "info");
        }
        return;
      }
      if (action === "share") {
        const body = turn.querySelector(".gpt-assistant-body");
        const text = body ? (body.innerText || "").trim() : "";
        if (!text) return;
        if (navigator.share) {
          navigator
            .share({ text: text })
            .catch(function () {
              navigator.clipboard.writeText(text).then(
                () => showToast("已复制到剪贴板", "ok"),
                () => showToast("分享失败", "err")
              );
            });
        } else {
          navigator.clipboard.writeText(text).then(
            () => showToast("已复制到剪贴板", "ok"),
            () => showToast("复制失败", "err")
          );
        }
        return;
      }
      if (action === "good" || action === "bad") {
        void (async function () {
          try {
            const conv = currentConv();
            const msgs = conv && conv.messages ? conv.messages : [];
            const cur = msgs[idx];
            let aex = "";
            if (cur && cur.role === "assistant") {
              aex = String(cur.content || "").trim();
            } else {
              const bodyEl = turn.querySelector(".gpt-assistant-body");
              aex = bodyEl ? String(bodyEl.innerText || "").trim() : "";
            }
            let uex = "";
            if (idx > 0) {
              const prev = msgs[idx - 1];
              if (prev && prev.role === "user") {
                uex = String(prev.content || "").trim().slice(0, 2000);
              }
            }
            await api("/api/public/message-quality-feedback", {
              method: "POST",
              body: JSON.stringify({
                rating: action,
                page_mode: IS_INSTANT_PAGE ? "instant" : "rag",
                client_conv_id: store.currentId || null,
                message_index: idx,
                user_message_excerpt: uex || null,
                assistant_excerpt: aex || null,
              }),
            });
            showToast(action === "good" ? "感谢反馈" : "已记录", "ok");
          } catch (e) {
            showToast(e.message || String(e), "err");
          }
        })();
        return;
      }
      if (action === "more") {
        showToast("更多功能可后续扩展", "ok");
        return;
      }
    });
  }

  function updateEmptyState() {
    const es = $("emptyState");
    const th = $("thread");
    if (!es || !th) return;
    const has = currentConv().messages.length > 0;
    es.hidden = has;
    th.hidden = !has;
    updateJumpToLatestVisibility();
  }

  function updateTopbar() {
    const c = currentConv();
    const tt = $("topbarTitle");
    const ts = $("topbarSub");
    if (tt)
      tt.textContent = c.title || (IS_INSTANT_PAGE ? "即时文档问答" : "知识库问答");
    const n = c.messages.filter((m) => m.role === "user").length;
    if (ts) ts.textContent = n ? n + " 条提问" : "";
  }

  function syncInstantDocBar() {
    if (!IS_INSTANT_PAGE) return;
    const attached = $("instantAttached");
    const nameEl = $("instantDocName");
    const conv = currentConv();
    const d = conv && conv.instantDoc;
    if (d && d.text) {
      if (attached) attached.hidden = false;
      if (nameEl) nameEl.textContent = (d.fileName || "文档") + " · " + d.text.length + " 字";
    } else {
      if (attached) attached.hidden = true;
      if (nameEl) nameEl.textContent = "";
    }
  }

  function renderConvList() {
    const nav = $("convList");
    if (!nav) return;
    nav.innerHTML = "";
    store.order.forEach((id) => {
      const conv = store.conversations[id];
      if (!conv) return;
      const row = document.createElement("div");
      row.className = "gpt-conv-item" + (id === store.currentId ? " active" : "");
      row.dataset.convId = id;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "label";
      btn.textContent = conv.title;
      btn.title = conv.title;
      btn.addEventListener("click", () => switchConv(id));

      const actions = document.createElement("div");
      actions.className = "gpt-conv-item-actions";
      const menu = document.createElement("div");
      menu.className = "gpt-sidebar-conv-menu";
      const moreBtn = document.createElement("button");
      moreBtn.type = "button";
      moreBtn.className = "gpt-btn-more gpt-sidebar-conv-more";
      moreBtn.setAttribute("aria-label", "对话操作");
      moreBtn.setAttribute("aria-expanded", "false");
      moreBtn.textContent = "⋮";
      const dd = document.createElement("div");
      dd.className = "gpt-conv-dropdown gpt-sidebar-conv-dropdown";
      dd.hidden = true;
      dd.setAttribute("role", "menu");
      [
        ["pin", "置顶"],
        ["rename", "重命名"],
        ["export", "导出"],
        ["delete", "删除"],
      ].forEach(function (pair) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "gpt-dropdown-item" + (pair[0] === "delete" ? " gpt-dropdown-danger" : "");
        b.setAttribute("data-sidebar-conv-action", pair[0]);
        b.setAttribute("role", "menuitem");
        b.textContent = pair[1];
        dd.appendChild(b);
      });
      menu.appendChild(moreBtn);
      menu.appendChild(dd);
      actions.appendChild(menu);

      row.appendChild(btn);
      row.appendChild(actions);
      nav.appendChild(row);
    });
  }

  function switchConv(id) {
    if (!store.conversations[id]) return;
    store.currentId = id;
    saveStore();
    renderConvList();
    renderThread();
    updateEmptyState();
    updateTopbar();
    syncInstantDocBar();
    closeMobileSidebar();
  }

  function pinConv(id) {
    const i = store.order.indexOf(id);
    if (i <= 0) return;
    store.order.splice(i, 1);
    store.order.unshift(id);
    saveStore();
    renderConvList();
  }

  function openRename(id) {
    renameTargetId = id;
    $("renameInput").value = store.conversations[id].title;
    $("dlgRename").showModal();
  }

  function deleteConv(id) {
    if (store.order.length <= 1) {
      alert("至少保留一个对话。");
      return;
    }
    if (!confirm("删除此对话？")) return;
    delete store.conversations[id];
    store.order = store.order.filter((x) => x !== id);
    if (store.currentId === id) store.currentId = store.order[0];
    saveStore();
    void flushPushWebUiState();
    renderConvList();
    renderThread();
    updateEmptyState();
    updateTopbar();
    syncInstantDocBar();
  }

  function exportConversationById(id) {
    const c = id && store.conversations[id] ? store.conversations[id] : null;
    if (!c) return;
    const payload = {
      title: c.title,
      updatedAt: c.updatedAt,
      messages: c.messages,
    };
    if (c.instantDoc) payload.instantDoc = c.instantDoc;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safe = String(c.title || "conversation").replace(/[/\\?%*:|"<>]/g, "_").slice(0, 80);
    a.download = safe + ".json";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("已导出 JSON", "ok");
  }

  function exportCurrentConv() {
    exportConversationById(store.currentId);
  }

  function runConversationAction(id, action) {
    if (!id || !store.conversations[id]) return;
    if (action === "pin") pinConv(id);
    else if (action === "rename") openRename(id);
    else if (action === "export") exportConversationById(id);
    else if (action === "delete") deleteConv(id);
  }

  function closeAllSidebarConvDropdowns() {
    document.querySelectorAll(".gpt-sidebar-conv-dropdown").forEach(function (dd) {
      dd.hidden = true;
    });
    document.querySelectorAll(".gpt-sidebar-conv-menu.is-open").forEach(function (m) {
      m.classList.remove("is-open");
    });
    document.querySelectorAll(".gpt-sidebar-conv-more").forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll(".gpt-conv-item.has-menu-open").forEach(function (r) {
      r.classList.remove("has-menu-open");
    });
  }

  function initSidebarConvListMenusOnce() {
    const nav = $("convList");
    if (!nav || nav.dataset.sidebarConvMenus === "1") return;
    nav.dataset.sidebarConvMenus = "1";
    nav.addEventListener("click", function (e) {
      const more = e.target.closest(".gpt-sidebar-conv-more");
      if (more && nav.contains(more)) {
        e.stopPropagation();
        const menu = more.closest(".gpt-sidebar-conv-menu");
        const dd = menu && menu.querySelector(".gpt-sidebar-conv-dropdown");
        const row = more.closest(".gpt-conv-item");
        const wasOpen = dd && !dd.hidden;
        closeConvDropdown();
        closeAllSidebarConvDropdowns();
        if (!wasOpen && dd && menu && row) {
          dd.hidden = false;
          more.setAttribute("aria-expanded", "true");
          menu.classList.add("is-open");
          row.classList.add("has-menu-open");
        }
        return;
      }
      const actBtn = e.target.closest("[data-sidebar-conv-action]");
      if (actBtn && nav.contains(actBtn)) {
        e.stopPropagation();
        const row = actBtn.closest(".gpt-conv-item");
        const cid = row && row.dataset.convId;
        const action = actBtn.getAttribute("data-sidebar-conv-action");
        closeAllSidebarConvDropdowns();
        if (cid && action) runConversationAction(cid, action);
      }
    });
  }

  function closeConvDropdown() {
    const dd = $("convDropdown");
    const btn = $("convMenuBtn");
    const cm = $("convMenu");
    if (dd && !dd.hidden) {
      dd.hidden = true;
      if (btn) btn.setAttribute("aria-expanded", "false");
      if (cm) cm.classList.remove("is-open");
    }
    closeAllSidebarConvDropdowns();
  }

  function newConv() {
    const id = uid();
    const n = store.order.length + 1;
    store.conversations[id] = { title: "新对话 " + n, messages: [], updatedAt: Date.now() };
    if (IS_INSTANT_PAGE) store.conversations[id].instantDoc = null;
    store.order.unshift(id);
    store.currentId = id;
    saveStore();
    renderConvList();
    renderThread();
    updateEmptyState();
    updateTopbar();
    syncInstantDocBar();
    closeMobileSidebar();
  }

  function collectChatBody(message, stream) {
    // 发送前同步 DOM（避免仅勾选「联网」但未触发 change 时仍用旧 prefs）
    readChatPrefsFromForm();
    const p = getChatPrefs();
    const rs = (p.response_style && String(p.response_style).trim()) || "balanced";
    const persona = getActivePersonaInstruction();
    const body = {
      message,
      history: historyForApi(message),
      selected_kb: p.selected_kb || "全部知识库",
      search_mode: p.search_mode || "vector",
      enable_reranker: !!p.enable_reranker,
      enable_web_search: !!p.enable_web_search && _ragWebSearchUiAllowed,
      temperature: Number(p.temperature_slider ?? 0) / 10,
      api_config_name: (p.preset && String(p.preset).trim()) || null,
      retrieval_k: parseInt(String(p.retrieval_k), 10) || 10,
      response_style: rs,
      persona_prompt: persona || null,
    };
    if (stream) body.stream = true;
    return body;
  }

  function collectInstantChatBody(message, stream) {
    const p = getChatPrefs();
    const rs = (p.response_style && String(p.response_style).trim()) || "balanced";
    const persona = getActivePersonaInstruction();
    const conv = currentConv();
    const idoc = conv && conv.instantDoc;
    const body = {
      message,
      history: historyForApi(message),
      document_text: idoc && idoc.text ? idoc.text : "",
      document_file_name: idoc && idoc.fileName ? idoc.fileName : "",
      enable_web_search: !!p.enable_web_search && _instantWebSearchUiAllowed,
      temperature: Number(p.temperature_slider ?? 0) / 10,
      api_config_name: (p.preset && String(p.preset).trim()) || null,
      response_style: rs,
      persona_prompt: persona || null,
    };
    if (stream) body.stream = true;
    return body;
  }

  function readChatPrefsFromForm() {
    const patch = {};
    if ($("kb")) patch.selected_kb = $("kb").value;
    if ($("presetSelect")) patch.preset = $("presetSelect").value;
    const ht = $("hybridToggle");
    const sm = $("searchMode");
    if (ht && sm) {
      sm.value = ht.checked ? "hybrid" : "vector";
      patch.search_mode = sm.value;
    } else if (sm) {
      patch.search_mode = sm.value;
    }
    if ($("rerank")) patch.enable_reranker = $("rerank").checked;
    if ($("webSearchToggle")) patch.enable_web_search = $("webSearchToggle").checked;
    if ($("temperature")) patch.temperature_slider = Number($("temperature").value);
    if ($("retrievalK")) patch.retrieval_k = parseInt($("retrievalK").value, 10) || 10;
    if ($("responseStyle")) patch.response_style = $("responseStyle").value;
    if ($("activePersonaSelect")) patch.active_persona_id = $("activePersonaSelect").value;
    setChatPrefs(patch);
  }

  function applyChatPrefsToForm() {
    const p = getChatPrefs();
    const kb = $("kb");
    if (kb && p.selected_kb && [...kb.options].some((o) => o.value === p.selected_kb)) kb.value = p.selected_kb;
    const pr = $("presetSelect");
    if (pr && p.preset && [...pr.options].some((o) => o.value === p.preset)) pr.value = p.preset;
    const sm = $("searchMode");
    const ht = $("hybridToggle");
    const mode = p.search_mode || "vector";
    if (sm) sm.value = mode === "hybrid" ? "hybrid" : "vector";
    if (ht) ht.checked = mode === "hybrid";
    const rr = $("rerank");
    if (rr) rr.checked = !!p.enable_reranker;
    const ws = $("webSearchToggle");
    if (ws) ws.checked = !!p.enable_web_search;
    const t = $("temperature");
    if (t) t.value = String(p.temperature_slider ?? 0);
    const rk = $("retrievalK");
    if (rk) rk.value = String(p.retrieval_k ?? 10);
    const rkv = $("retrievalKVal");
    if (rkv && rk) rkv.textContent = rk.value;
    const rs = $("responseStyle");
    const rsv = p.response_style || "balanced";
    if (rs && [...rs.options].some((o) => o.value === rsv)) rs.value = rsv;
    const aps = $("activePersonaSelect");
    if (aps) {
      const aid = p.active_persona_id || "";
      const s = getPersonasStore();
      const ok = aid && s.personas.some(function (x) {
        return x.id === aid;
      });
      if (ok) aps.value = aid;
      else {
        const def = s.personas.find(function (x) {
          return x.isDefault;
        });
        if (def) aps.value = def.id;
      }
    }
    updateTempHint();
    syncChatKbDropdownFromSelect();
  }

  function bindChatPrefsFromFormListeners() {
    const onPreset = function () {
      readChatPrefsFromForm();
      if ($("cfgBaseUrl")) loadCfgDetail();
    };
    $("kb")?.addEventListener("change", readChatPrefsFromForm);
    const ps = $("presetSelect");
    if (ps) {
      ps.addEventListener("change", onPreset);
    }
    $("searchMode")?.addEventListener("change", function () {
      readChatPrefsFromForm();
      refreshBm25Hint().catch(() => {});
    });
    $("hybridToggle")?.addEventListener("change", function () {
      const sm = $("searchMode");
      if (sm) sm.value = this.checked ? "hybrid" : "vector";
      readChatPrefsFromForm();
      refreshBm25Hint().catch(() => {});
    });
    $("rerank")?.addEventListener("change", readChatPrefsFromForm);
    $("webSearchToggle")?.addEventListener("change", readChatPrefsFromForm);
    $("responseStyle")?.addEventListener("change", readChatPrefsFromForm);
    $("activePersonaSelect")?.addEventListener("change", readChatPrefsFromForm);
    $("temperature")?.addEventListener("input", function () {
      readChatPrefsFromForm();
      updateTempHint();
    });
    $("retrievalK")?.addEventListener("input", function () {
      readChatPrefsFromForm();
      const rkv = $("retrievalKVal");
      if (rkv && $("retrievalK")) rkv.textContent = $("retrievalK").value;
    });
  }

  function activateTabInRoot(root, tabKey) {
    if (!root || !tabKey) return;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        const tabBtn = root.querySelector('.gpt-tab[data-tab="' + tabKey + '"]');
        if (tabBtn) tabBtn.click();
      });
    });
  }

  /** 设置页：侧栏「模型配置 / 个性化」与当前 tab、URL ?tab= 一致，避免高亮错位或窄栏误触观感混乱 */
  function syncAdminSettingsNavAriaCurrent(tabKey) {
    if (PAGE !== "admin-settings") return;
    const nav = document.querySelector("#gptSidebar .gpt-sidebar-nav");
    if (!nav) return;
    const key = tabKey === "set-model" ? "set-model" : "set-rag";
    nav.querySelectorAll('a.gpt-nav-item[href*="/admin/settings"]').forEach(function (a) {
      a.removeAttribute("aria-current");
    });
    const sel =
      key === "set-model"
        ? 'a.gpt-nav-item[href*="tab=set-model"]'
        : 'a.gpt-nav-item[href*="tab=set-rag"]';
    const cur = nav.querySelector(sel);
    if (cur) cur.setAttribute("aria-current", "page");
  }

  function updateTempHint() {
    const tr = $("temperature");
    const tv = $("tempVal");
    const th = $("tempHint");
    if (!tr || !tv) return;
    const t = Number(tr.value) / 10;
    tv.textContent = t.toFixed(1);
    let h = "";
    if (t === 0) h = "确定性模式（事实问答）";
    else if (t < 0.5) h = "低随机性（技术文档）";
    else if (t < 1) h = "中等随机性";
    else h = "高随机性（创意）";
    if (th) th.textContent = h;
  }

  function fillActivePersonaSelectOptions() {
    const sel = $("activePersonaSelect");
    if (!sel) return;
    const s = getPersonasStore();
    const prev = sel.value;
    sel.innerHTML = "";
    s.personas.forEach(function (p) {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name + (p.isDefault ? "（默认）" : "");
      sel.appendChild(o);
    });
    const prefs = getChatPrefs();
    const want = prefs.active_persona_id;
    if (want && [...sel.options].some(function (o) {
      return o.value === want;
    })) {
      sel.value = want;
    } else if (prev && [...sel.options].some(function (o) {
      return o.value === prev;
    })) {
      sel.value = prev;
    } else {
      const def = s.personas.find(function (x) {
        return x.isDefault;
      });
      if (def) sel.value = def.id;
    }
  }

  function renderPersonasList() {
    const box = $("personasList");
    if (!box) return;
    const s = getPersonasStore();
    box.innerHTML = "";
    s.personas.forEach(function (p) {
      const onlyOne = s.personas.length <= 1;
      const card = document.createElement("div");
      card.className = "gpt-persona-card";
      card.dataset.personaId = p.id;
      const head = document.createElement("div");
      head.className = "gpt-persona-card-head";
      const nl = document.createElement("label");
      nl.className = "gpt-persona-name-label";
      nl.textContent = "名称";
      const ni = document.createElement("input");
      ni.type = "text";
      ni.className = "gpt-input gpt-persona-name";
      ni.maxLength = 64;
      ni.value = p.name;
      head.appendChild(nl);
      head.appendChild(ni);
      const il = document.createElement("label");
      il.className = "gpt-persona-inst-label";
      il.textContent = "性格与行为设定（会发给大模型）";
      const ta = document.createElement("textarea");
      ta.className = "gpt-input gpt-persona-instruction";
      ta.rows = 4;
      ta.maxLength = 3000;
      ta.value = p.instruction;
      const act = document.createElement("div");
      act.className = "gpt-persona-actions";
      const bs = document.createElement("button");
      bs.type = "button";
      bs.className = "gpt-btn-sm";
      bs.textContent = "保存本条";
      bs.setAttribute("data-persona-save", p.id);
      const bd = document.createElement("button");
      bd.type = "button";
      bd.className = "gpt-btn-sm";
      bd.textContent = "设为默认";
      bd.setAttribute("data-persona-default", p.id);
      if (p.isDefault) bd.disabled = true;
      const bx = document.createElement("button");
      bx.type = "button";
      bx.className = "gpt-btn-sm gpt-btn-danger-text";
      bx.textContent = "删除";
      bx.setAttribute("data-persona-del", p.id);
      if (onlyOne) bx.disabled = true;
      act.appendChild(bs);
      act.appendChild(bd);
      act.appendChild(bx);
      card.appendChild(head);
      card.appendChild(il);
      card.appendChild(ta);
      card.appendChild(act);
      box.appendChild(card);
    });
  }

  function wirePersonasEditor() {
    const box = $("personasList");
    const addBtn = $("btnPersonaAdd");
    if (!box || !addBtn) return;
    if (box.dataset.wired === "1") return;
    box.dataset.wired = "1";
    addBtn.addEventListener("click", function () {
      const s = getPersonasStore();
      if (s.personas.length >= MAX_ASSISTANT_PERSONAS) {
        showToast("最多 " + MAX_ASSISTANT_PERSONAS + " 套性格预设", "err");
        return;
      }
      const id =
        "p_" +
        Date.now().toString(36) +
        "_" +
        Math.random()
          .toString(36)
          .slice(2, 6);
      s.personas.push({
        id: id,
        name: "新性格 " + (s.personas.length + 1),
        instruction: "",
        isDefault: false,
      });
      savePersonasStore(s);
      fillActivePersonaSelectOptions();
      renderPersonasList();
      showToast("已新增，编辑后请点「保存本条」", "ok");
    });
    box.addEventListener("click", function (ev) {
      const t = ev.target;
      if (!(t instanceof HTMLElement)) return;
      const sid = t.getAttribute("data-persona-save");
      const did = t.getAttribute("data-persona-del");
      const defid = t.getAttribute("data-persona-default");
      if (sid) {
        const card = box.querySelector('.gpt-persona-card[data-persona-id="' + sid + '"]');
        if (!card) return;
        const nm = card.querySelector(".gpt-persona-name");
        const ins = card.querySelector(".gpt-persona-instruction");
        const s = getPersonasStore();
        const p = s.personas.find(function (x) {
          return x.id === sid;
        });
        if (!p) return;
        p.name = (nm && nm.value.trim()) || p.name;
        p.instruction = ins ? ins.value : "";
        savePersonasStore(s);
        fillActivePersonaSelectOptions();
        showToast("已保存", "ok");
        return;
      }
      if (defid) {
        const s = getPersonasStore();
        s.personas.forEach(function (p) {
          p.isDefault = p.id === defid;
        });
        savePersonasStore(s);
        fillActivePersonaSelectOptions();
        renderPersonasList();
        showToast("已设为默认", "ok");
        return;
      }
      if (did) {
        const s = getPersonasStore();
        if (s.personas.length <= 1) return;
        if (!confirm("删除该性格预设？")) return;
        const del = s.personas.find(function (x) {
          return x.id === did;
        });
        const wasDefault = del && del.isDefault;
        s.personas = s.personas.filter(function (x) {
          return x.id !== did;
        });
        if (wasDefault || !s.personas.some(function (x) {
          return x.isDefault;
        })) {
          s.personas[0].isDefault = true;
        }
        savePersonasStore(s);
        const prefs = getChatPrefs();
        if (prefs.active_persona_id === did) {
          const nd = s.personas.find(function (x) {
            return x.isDefault;
          });
          if (nd) setChatPrefs({ active_persona_id: nd.id });
        }
        fillActivePersonaSelectOptions();
        applyChatPrefsToForm();
        renderPersonasList();
        showToast("已删除", "ok");
      }
    });
  }

  async function refreshBm25Hint() {
    const el = $("hybridHint");
    if (!el) return;
    let hybrid = false;
    const sm = $("searchMode");
    if (sm) hybrid = sm.value === "hybrid";
    else if ($("hybridToggle")) hybrid = $("hybridToggle").checked;
    if (!hybrid) {
      el.hidden = true;
      return;
    }
    try {
      const st = await api("/api/bm25-status");
      el.hidden = false;
      el.textContent = st.exists
        ? "BM25 索引已就绪。"
        : "首次混合检索将自动构建 BM25（可能较慢）。文件：" + (st.relative_path || "");
    } catch {
      el.hidden = true;
    }
  }

  function syncChatKbDropdownFromSelect() {
    const sel = $("kb");
    const trigger = $("kbTrigger");
    const menu = $("kbListbox");
    const textSpan = $("kbTriggerText");
    if (!sel || !trigger || !menu || !textSpan) return;
    const opt = sel.selectedOptions[0];
    textSpan.textContent = opt ? opt.textContent : sel.value || "—";
    menu.innerHTML = "";
    [...sel.options].forEach(function (o) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("data-value", o.value);
      li.textContent = o.textContent;
      li.className = "gpt-rag-kb-option";
      li.setAttribute("aria-selected", o.selected ? "true" : "false");
      li.addEventListener("mousedown", function (e) {
        e.preventDefault();
      });
      li.addEventListener("click", function (e) {
        e.stopPropagation();
        if (sel.value !== o.value) {
          sel.value = o.value;
          sel.dispatchEvent(new Event("change", { bubbles: true }));
        }
        closeChatKbMenu();
      });
      menu.appendChild(li);
    });
  }

  function closeChatKbMenu() {
    const trigger = $("kbTrigger");
    const menu = $("kbListbox");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    if (menu) menu.hidden = true;
  }

  function openChatKbMenu() {
    const trigger = $("kbTrigger");
    const menu = $("kbListbox");
    if (!trigger || !menu) return;
    syncChatKbDropdownFromSelect();
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  }

  function wireChatKbCustomDropdown() {
    const trigger = $("kbTrigger");
    const menu = $("kbListbox");
    if (!trigger || !menu || trigger.dataset.kbDropWired) return;
    trigger.dataset.kbDropWired = "1";
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      if (menu.hidden) openChatKbMenu();
      else closeChatKbMenu();
    });
    menu.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    document.addEventListener("click", function () {
      closeChatKbMenu();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeChatKbMenu();
    });
  }

  async function fillKbSelects() {
    const data = await api("/api/knowledge-bases");
    const cats = data.categories || [];
    const sync = (sel, keep) => {
      if (!sel) return;
      const v = keep ? sel.value : "";
      sel.innerHTML = "";
      cats.forEach((c) => {
        const o = document.createElement("option");
        o.value = c;
        o.textContent = c;
        sel.appendChild(o);
      });
      if (v && [...sel.options].some((o) => o.value === v)) sel.value = v;
    };
    sync($("kb"), true);
    syncChatKbDropdownFromSelect();
    closeChatKbMenu();
    sync($("kbDocFilter"), true);
    const ut = $("uploadTargetKb");
    if (ut) {
      ut.innerHTML = "";
      getCategoriesOnly(cats).forEach((c) => {
        const o = document.createElement("option");
        o.value = c;
        o.textContent = c;
        ut.appendChild(o);
      });
    }
    syncEditCategories();
  }

  function getCategoriesOnly(cats) {
    return cats.filter((c) => c !== "全部知识库");
  }

  async function pingStatus() {
    const st = $("status");
    if (!st) return;
    try {
      const h = await api("/api/health");
      st.textContent = h.per_user_kb
        ? "Web 多用户模式 · 当前账号独立知识库"
        : "API 就绪";
      st.classList.remove("err");
    } catch {
      st.textContent = "无法连接 API";
      st.classList.add("err");
    }
  }

  async function loadPresets() {
    let data;
    try {
      data = await api("/api/config/presets");
    } catch {
      return;
    }
    const list = data.presets || [];
    const sel = $("presetSelect");
    const prefs = getChatPrefs();
    let prev = (sel && sel.value) || prefs.preset || "";
    if (sel) {
      sel.innerHTML = "";
      list.forEach((p) => {
        const o = document.createElement("option");
        o.value = p;
        o.textContent = p;
        sel.appendChild(o);
      });
      if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
      else if (list.length) {
        sel.value = list[0];
        setChatPrefs({ preset: list[0] });
      }
    } else if (list.length) {
      if (!prev || !list.includes(prev)) {
        prev = list[0];
        setChatPrefs({ preset: prev });
      }
    }
    await loadCfgDetail();
  }

  async function loadCfgDetail() {
    const p = $("presetSelect")?.value;
    if (!p || !$("cfgBaseUrl")) return;
    try {
      const d = await api("/api/config/detail?preset=" + encodeURIComponent(p));
      $("cfgBaseUrl").value = d.base_url || "";
      $("cfgModel").value = d.model || "";
      $("cfgProvider").value = d.provider || "custom";
      $("cfgApiKey").value = "";
      $("cfgApiKey").placeholder = d.has_api_key ? "已保存密钥 · 留空不变" : "请输入 API Key";
    } catch {
      $("cfgTestLog").hidden = false;
      $("cfgTestLog").textContent = "读取配置失败";
    }
  }

  let _vectorProviders = [];

  function fillModelSelect(selectId, currentModel, models) {
    const sel = $(selectId);
    if (!sel) return;
    const opts = [];
    const add = (v, label) => {
      if (v && !opts.some((o) => o.value === v)) opts.push({ value: v, label: label || v });
    };
    add(currentModel, currentModel);
    (models || []).forEach((m) => add(m, m));
    sel.innerHTML = "";
    opts.forEach((o) => {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      sel.appendChild(opt);
    });
    if (currentModel && opts.some((o) => o.value === currentModel)) sel.value = currentModel;
  }

  function renderVectorProviders() {
    const box = $("vectorProviderList");
    if (!box) return;
    const rows = _vectorProviders
      .map((p) => {
        const isLocal = p.name === "local";
        const keyTag = p.has_api_key
          ? '<span class="gpt-provider-key">密钥已配置</span>'
          : '<span class="gpt-provider-key gpt-provider-key-empty">未配密钥</span>';
        const delBtn = isLocal
          ? ""
          : `<button type="button" class="gpt-btn-text" data-del-provider="${escapeHtml(p.name)}">删除</button>`;
        return (
          '<div class="gpt-provider-row"><div class="gpt-provider-meta">' +
          '<span class="gpt-provider-name">' + escapeHtml(p.label || p.name) + '</span>' +
          '<span class="gpt-provider-type">' + (p.type === "local" ? "本地" : "OpenAI 兼容") + '</span>' +
          '<span class="gpt-provider-url">' + escapeHtml(p.base_url || "—") + '</span>' +
          keyTag + '</div>' + delBtn + '</div>'
        );
      })
      .join("");
    box.innerHTML = rows || '<p class="gpt-muted">暂无 provider</p>';
    box.querySelectorAll("[data-del-provider]").forEach((b) => {
      b.addEventListener("click", async () => {
        const name = b.getAttribute("data-del-provider");
        if (!window.confirm(`确定删除 provider「${name}」吗？`)) return;
        try {
          await api("/api/admin/vector-providers/" + encodeURIComponent(name), { method: "DELETE" });
          showToast("已删除 provider", "ok");
          await loadSettingsModelConfig();
        } catch (e) {
          showToast(e.message || String(e), "err");
        }
      });
    });
  }

  function currentVectorProvider() {
    const sel = $("sfEmbedProvider");
    const name = sel && sel.value;
    return _vectorProviders.find((p) => p.name === name) || null;
  }

  function syncSfConnectionFields() {
    const p = currentVectorProvider();
    const sbu = $("sfBaseUrl");
    const sfh = $("sfKeyHint");
    const sfk = $("sfKey");
    if (p) {
      if (sbu) sbu.value = p.base_url || "";
      if (sfk) sfk.placeholder = p.has_api_key ? "****（已配置，留空沿用）" : "sk-...（未配置）";
      if (sfh) {
        sfh.textContent = p.has_api_key
          ? `「${p.label || p.name}」已保存密钥（输入新值可覆盖）`
          : `「${p.label || p.name}」尚未配置密钥`;
      }
    }
  }

  async function loadSettingsModelConfig() {
    try {
      const [prov, s] = await Promise.all([
        api("/api/admin/vector-providers"),
        api("/api/admin/settings"),
      ]);
      _vectorProviders = prov.providers || [];
      const fillProv = (selId, current) => {
        const sel = $(selId);
        if (!sel) return;
        sel.innerHTML = "";
        _vectorProviders.forEach((p) => {
          const o = document.createElement("option");
          o.value = p.name;
          o.textContent = p.label || p.name;
          sel.appendChild(o);
        });
        if (current && _vectorProviders.some((p) => p.name === current)) sel.value = current;
      };
      fillProv("sfEmbedProvider", s.embedding_provider);
      fillProv("sfRerankProvider", s.rerank_provider);
      fillModelSelect("sfEmbedModel", s.embedding_model, []);
      fillModelSelect("sfRerankModel", s.rerank_model, []);
      renderVectorProviders();
      syncSfConnectionFields();
    } catch (e) {
      console.error(e);
    }
  }

  function wireTabs(root) {
    if (!root) return;
    root.querySelectorAll(".gpt-tabs .gpt-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const id = tab.dataset.tab;
        root.querySelectorAll(".gpt-tabs .gpt-tab").forEach((t) => t.classList.remove("active"));
        root.querySelectorAll(".gpt-tab-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const panel = root.querySelector("#panel-" + id);
        if (panel) panel.classList.add("active");
        if (root.id === "settingsPageRoot" && id) {
          syncAdminSettingsNavAriaCurrent(id);
          try {
            const u = new URL(window.location.href);
            u.searchParams.set("tab", id);
            window.history.replaceState({}, "", u.pathname + u.search + u.hash);
          } catch (_) {}
        }
      });
    });
  }

  function wireSubTabs(root) {
    if (!root) return;
    root.querySelectorAll(".gpt-subtab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const id = tab.dataset.subtab;
        root.querySelectorAll(".gpt-subtab").forEach((t) => t.classList.remove("active"));
        root.querySelectorAll(".gpt-subpanel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const panel = root.querySelector("#subpanel-" + id);
        if (panel) panel.classList.add("active");
      });
    });
  }

  function wireCloseDialogs() {
    document.querySelectorAll("[data-close-dlg]").forEach((b) => {
      b.addEventListener("click", () => {
        const id = b.getAttribute("data-close-dlg");
        const el = document.getElementById(id);
        if (!el) return;
        if (el.tagName === "DIALOG" && typeof el.close === "function") {
          el.close();
        } else {
          el.hidden = true;
          el.setAttribute("aria-hidden", "true");
          document.body.style.overflow = "";
        }
      });
    });
  }

  function applyModelTabPermissions() {
    if (PORTAL !== "admin") return;
    const ro = $("modelReadonlyNote");
    const act = $("modelAdminActions");
    if (ro) ro.hidden = true;
    if (act) act.hidden = false;
    ["cfgBaseUrl", "cfgApiKey", "cfgModel", "cfgProvider"].forEach((id) => {
      const el = $(id);
      if (el) el.readOnly = false;
    });
  }

  function updateAvatarDisplay() {
    const img = $("avatarImg");
    const fb = $("avatarFallback");
    if (!fb) return;
    const nick = (currentUser && (currentUser.nickname || currentUser.username)) || "用";
    fb.textContent = (String(nick).charAt(0) || "用").toUpperCase();
    if (img && currentUser && currentUser.avatar) {
      img.src = currentUser.avatar;
      img.hidden = false;
      fb.hidden = true;
    } else if (img) {
      img.removeAttribute("src");
      img.hidden = true;
      fb.hidden = false;
    }
  }

  function applyUserHeader() {
    updateAvatarDisplay();
  }

  function focusComposer() {
    closeMobileSidebar();
    const empty = $("emptyState");
    const thread = $("thread");
    if (empty && thread && currentConv().messages.length > 0) {
      empty.hidden = true;
      thread.hidden = false;
    }
    $("composerArea")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setTimeout(function () {
      $("input")?.focus({ preventScroll: true });
    }, 200);
  }

  function openProfileDialog() {
    if (!currentUser) return;
    pendingAvatarClear = false;
    pendingAvatarDataUrl = undefined;
    const pu = $("profileUsername");
    if (pu) pu.textContent = currentUser.username || "—";
    const pr = $("profileRole");
    if (pr) pr.textContent = currentUser.is_admin ? "管理员" : "普通用户";
    const pn = $("profileNickname");
    if (pn) pn.value = currentUser.nickname || "";
    const pimg = $("profileAvatarImg");
    const pph = $("profileAvatarPh");
    if (currentUser.avatar && pimg) {
      pimg.src = currentUser.avatar;
      pimg.hidden = false;
      if (pph) pph.hidden = true;
    } else if (pimg) {
      pimg.removeAttribute("src");
      pimg.hidden = true;
      if (pph) pph.hidden = false;
    }
    const pm = $("profileMsg");
    if (pm) {
      pm.hidden = true;
      pm.textContent = "";
    }
    const pf = $("profileAvatarFile");
    if (pf) pf.value = "";
    $("dlgProfile")?.showModal();
  }

  function compressImageFile(file, maxEdge, quality) {
    return new Promise(function (resolve, reject) {
      const url = URL.createObjectURL(file);
      const im = new Image();
      im.onload = function () {
        URL.revokeObjectURL(url);
        let w = im.width;
        let h = im.height;
        const m = Math.max(w, h);
        if (m > maxEdge) {
          w = Math.round((w * maxEdge) / m);
          h = Math.round((h * maxEdge) / m);
        }
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        const ctx = c.getContext("2d");
        if (!ctx) {
          reject(new Error("canvas"));
          return;
        }
        ctx.drawImage(im, 0, 0, w, h);
        try {
          const dataUrl = c.toDataURL("image/jpeg", quality);
          resolve(dataUrl);
        } catch (e) {
          reject(e);
        }
      };
      im.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("图片加载失败"));
      };
      im.src = url;
    });
  }

  function wireUserMenu() {
    const um = $("userMenu");
    const ab = $("avatarBtn");
    const dd = $("userDropdown");
    if (!um || !ab || !dd) return;
    if (PORTAL === "admin") {
      dd.querySelectorAll('[data-menu="appearance"]').forEach(function (el) {
        el.remove();
      });
      const ap = document.createElement("button");
      ap.type = "button";
      ap.className = "gpt-dropdown-item";
      ap.setAttribute("data-menu", "appearance");
      ap.setAttribute("role", "menuitem");
      ap.innerHTML = '<span class="gpt-dropdown-ico" aria-hidden="true">◐</span>外观';
      const helpBtn = dd.querySelector('[data-menu="help"]');
      if (helpBtn) {
        dd.insertBefore(ap, helpBtn);
      } else {
        dd.appendChild(ap);
      }
    }
    ab.addEventListener("click", function (e) {
      e.stopPropagation();
      closeConvDropdown();
      um.classList.toggle("is-open");
    });
    document.addEventListener("click", function () {
      um.classList.remove("is-open");
    });
    dd.querySelectorAll("[data-menu]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.stopPropagation();
        um.classList.remove("is-open");
        const a = el.getAttribute("data-menu");
        if (a === "account") openProfileDialog();
        else if (a === "appearance") {
          const cur =
            document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
          const next = cur === "dark" ? "light" : "dark";
          document.documentElement.setAttribute("data-theme", next);
          localStorage.setItem("rag_theme", next);
          schedulePushWebUiState();
        } else if (a === "help") $("dlgHelp")?.showModal();
        else if (a === "logout") doLogout();
      });
    });
  }

  async function doLogout() {
    try {
      await flushPushWebUiState();
    } catch (_) {}
    const tok = getAuthToken();
    try {
      if (tok) {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { Authorization: "Bearer " + tok },
        });
      }
    } catch (_) {}
    clearAuth();
    window.location.href = LOGIN_PAGE;
  }

  function wireHistoryToggle() {
    const toggle = $("btnHistoryToggle");
    const section = $("sidebarHistory");
    if (!toggle || !section) return;
    const KEY = "rag_sidebar_history_collapsed";
    const chev = toggle.querySelector(".gpt-sidebar-history-chevron");
    function applyCollapsed(collapsed) {
      section.classList.toggle("is-collapsed", collapsed);
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      if (chev) chev.textContent = collapsed ? "▶" : "▼";
    }
    if (localStorage.getItem(KEY) === "1") applyCollapsed(true);
    toggle.addEventListener("click", function () {
      const next = !section.classList.contains("is-collapsed");
      applyCollapsed(next);
      localStorage.setItem(KEY, next ? "1" : "0");
    });
  }

  function wireConvMenu() {
    const cm = $("convMenu");
    const btn = $("convMenuBtn");
    const dd = $("convDropdown");
    if (!cm || !btn || !dd) return;
    function openConvMenu() {
      $("userMenu")?.classList.remove("is-open");
      dd.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      cm.classList.add("is-open");
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (dd.hidden) openConvMenu();
      else closeConvDropdown();
    });
    dd.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    document.addEventListener("click", closeConvDropdown);
    dd.querySelectorAll("[data-conv-action]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.stopPropagation();
        closeConvDropdown();
        const a = el.getAttribute("data-conv-action");
        const id = store.currentId;
        if (!id || !store.conversations[id]) return;
        runConversationAction(id, a);
      });
    });
  }

  async function refreshPublicUploadUi() {
    const s = await fetchPublicSettings();
    if (s) applyWebSearchUiFlagsFromPublicSettings(s);
    const label = $("uploadFilesLabel");
    const inp = $("uploadFiles");
    if (!s || !label || !inp) return;
    const exts = (s.allowed_extensions || []).map((x) => "." + String(x).replace(/^\./, ""));
    const accept = exts.length ? exts.join(",") : ".pdf,.txt,.docx,.doc,.md,.xlsx,.xls";
    inp.setAttribute("accept", accept);
    label.textContent =
      "文件（允许 " +
      (s.allowed_extensions || []).join(", ") +
      "，最大 " +
      (s.max_upload_mb || 50) +
      " MB）";
  }

  async function loadAdminUsers() {
    const q = ($("admUserSearch")?.value || "").trim();
    const url =
      q.length > 0 ? "/api/admin/users?q=" + encodeURIComponent(q) : "/api/admin/users";
    const data = await api(url);
    const box = $("adminUserList");
    if (!box) return;
    const users = data.users || [];
    if (!users.length) {
      box.innerHTML = "<p class=\"gpt-muted\">暂无用户</p>";
      return;
    }
    const rows = users
      .map(function (u) {
        const roleZh = (u.role || "") === "admin" ? "管理员" : "普通用户";
        const st = (u.status || "active") === "disabled" ? "禁用" : "正常";
        return (
          "<tr>" +
          "<td>" +
          escapeHtml(String(u.id)) +
          "</td><td>@" +
          escapeHtml(u.username || "") +
          "</td><td>" +
          escapeHtml(u.nickname || "") +
          "</td><td>" +
          escapeHtml(roleZh) +
          "</td><td>" +
          escapeHtml(String(st)) +
          "</td><td>" +
          escapeHtml(String((u.created_at || "").slice(0, 19)).replace("T", " ")) +
          "</td><td>" +
          escapeHtml(String(u.doc_count ?? 0)) +
          "</td><td>" +
          escapeHtml(String(u.chat_count ?? 0)) +
          '</td><td><div class="gpt-doc-actions">' +
          '<button type="button" class="gpt-btn-sm" data-adm-user-edit="' +
          escapeHtml(String(u.id)) +
          '">编辑</button>' +
          '<button type="button" class="gpt-btn-sm" data-adm-user-reset="' +
          escapeHtml(String(u.id)) +
          '">重置密码</button>' +
          '<button type="button" class="gpt-btn-sm" data-adm-user-toggle="' +
          escapeHtml(String(u.id)) +
          '">' +
          (st === "禁用" ? "启用" : "禁用") +
          "</button>" +
          '<button type="button" class="gpt-btn-sm gpt-dropdown-danger" data-adm-user-destroy="' +
          escapeHtml(String(u.id)) +
          '" data-adm-user-uname="' +
          escapeHtml(u.username || "") +
          '">注销账号</button>' +
          "</div></td></tr>"
        );
      })
      .join("");
    box.innerHTML =
      '<table class="gpt-audit-table"><thead><tr><th>ID</th><th>用户名</th><th>昵称</th><th>角色</th><th>状态</th><th>注册时间</th><th>文档数</th><th>问答次数</th><th>操作</th></tr></thead><tbody>' +
      rows +
      "</tbody></table>";
  }

  function wireAdminUsersActions() {
    const box = $("adminUserList");
    if (!box || box.dataset.wired === "1") return;
    box.dataset.wired = "1";
    box.addEventListener("click", async function (e) {
      const editBtn = e.target.closest("[data-adm-user-edit]");
      if (editBtn) {
        const uid = Number(editBtn.getAttribute("data-adm-user-edit"));
        const nickname = prompt("请输入新昵称（1-32）");
        if (!nickname) return;
        const role = prompt("角色：admin / user（留空不改）", "");
        const body = { nickname: nickname.trim() };
        const roleVal = (role || "").trim().toLowerCase();
        if (roleVal === "admin" || roleVal === "user") body.role = roleVal;
        try {
          await api("/api/admin/users/" + uid, {
            method: "PATCH",
            body: JSON.stringify(body),
          });
          showToast("用户信息已更新", "ok");
          await loadAdminUsers();
          await fillAdminUserFilter();
        } catch (err) {
          alert(err.message || String(err));
        }
        return;
      }
      const resetBtn = e.target.closest("[data-adm-user-reset]");
      if (resetBtn) {
        const uid = Number(resetBtn.getAttribute("data-adm-user-reset"));
        const pwd = prompt("请输入新密码（至少8位）");
        if (!pwd) return;
        try {
          await api("/api/admin/users/" + uid + "/reset-password", {
            method: "POST",
            body: JSON.stringify({ password: pwd }),
          });
          showToast("密码已重置", "ok");
        } catch (err) {
          alert(err.message || String(err));
        }
        return;
      }
      const toggleBtn = e.target.closest("[data-adm-user-toggle]");
      if (toggleBtn) {
        const uid = Number(toggleBtn.getAttribute("data-adm-user-toggle"));
        const toDisabled = toggleBtn.textContent.indexOf("禁用") >= 0;
        if (!confirm("确认" + (toDisabled ? "禁用" : "启用") + "该用户？")) return;
        try {
          await api("/api/admin/users/" + uid, {
            method: "PATCH",
            body: JSON.stringify({ status: toDisabled ? "disabled" : "active" }),
          });
          showToast("已更新用户状态", "ok");
          await loadAdminUsers();
          await fillAdminUserFilter();
        } catch (err) {
          alert(err.message || String(err));
        }
        return;
      }
      const desBtn = e.target.closest("[data-adm-user-destroy]");
      if (desBtn) {
        const uid = Number(desBtn.getAttribute("data-adm-user-destroy"));
        const uname = desBtn.getAttribute("data-adm-user-uname") || "";
        if (!uid) return;
        if (
          !confirm(
            "将永久删除该用户账号及其云端个人数据（知识库目录等），且不可恢复。是否继续？"
          )
        )
          return;
        const typed = prompt("请输入要注销的用户名以确认：", "");
        if (typed == null || typed.trim() !== uname) {
          alert("用户名不一致");
          return;
        }
        try {
          await api("/api/admin/users/" + uid + "/destroy", {
            method: "POST",
            body: JSON.stringify({ confirm: true, typed_username: typed.trim() }),
          });
          showToast("用户已注销", "ok");
          await loadAdminUsers();
          await fillAdminUserFilter();
          await loadAdminKbCatalog().catch(() => {});
        } catch (err) {
          alert(err.message || String(err));
        }
      }
    });
  }

  async function fillAdminUserFilter() {
    const sel = $("admDocUserFilter");
    if (!sel) return;
    try {
      const d = await api("/api/admin/users");
      const users = d.users || [];
      const prev = sel.value || "";
      sel.innerHTML = '<option value="">全部用户</option>';
      users.forEach(function (u) {
        const o = document.createElement("option");
        o.value = String(u.id);
        o.textContent = "id " + u.id + " · @" + (u.username || "");
        sel.appendChild(o);
      });
      if (prev && [...sel.options].some(function (o) { return o.value === prev; })) sel.value = prev;
    } catch (e) {
      console.error(e);
    }
  }

  async function loadAdminKbCatalog() {
    const box = $("adminKbCatalogList");
    if (!box) return;
    try {
      const d = await api("/api/admin/knowledge-bases/catalog");
      const items = d.items || [];
      if (!items.length) {
        box.innerHTML = '<p class="gpt-muted">暂无知识库记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          const uid = Number(it.user_id);
          const cat = String(it.category || "");
          const dis = !!it.admin_disabled;
          const catEnc = encodeURIComponent(cat);
          return (
            "<tr><td>" +
            escapeHtml(String(uid)) +
            "</td><td>" +
            escapeHtml(String(it.username || "")) +
            "</td><td>" +
            escapeHtml(cat) +
            "</td><td>" +
            escapeHtml(String(it.doc_count ?? 0)) +
            "</td><td>" +
            escapeHtml(String((it.first_upload_time || "").slice(0, 19)).replace("T", " ")) +
            "</td><td>" +
            escapeHtml(dis ? "已禁用" : "正常") +
            '</td><td><div class="gpt-doc-actions">' +
            '<button type="button" class="gpt-btn-sm" data-adm-kb-toggle="1" data-adm-kb-user="' +
            uid +
            '" data-adm-kb-cat="' +
            catEnc +
            '" data-adm-kb-next="' +
            (dis ? "0" : "1") +
            '">' +
            (dis ? "启用" : "禁用") +
            '</button><button type="button" class="gpt-btn-sm gpt-dropdown-danger" data-adm-kb-wipe="1" data-adm-kb-user="' +
            uid +
            '" data-adm-kb-cat="' +
            catEnc +
            '">移入回收站</button></div></td></tr>'
          );
        })
        .join("");
      box.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>用户ID</th><th>用户名</th><th>知识库</th><th>文档数</th><th>首传时间</th><th>状态</th><th>操作</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      box.innerHTML = '<p class="gpt-muted">' + escapeHtml(e.message || String(e)) + "</p>";
    }
  }

  function wireAdminKbCatalogActions() {
    const box = $("adminKbCatalogList");
    if (!box || box.dataset.wired === "1") return;
    box.dataset.wired = "1";
    box.addEventListener("click", async function (e) {
      const tgl = e.target.closest("[data-adm-kb-toggle]");
      if (tgl) {
        const uid = Number(tgl.getAttribute("data-adm-kb-user") || "0");
        const cat = decodeURIComponent(tgl.getAttribute("data-adm-kb-cat") || "");
        const next = tgl.getAttribute("data-adm-kb-next") === "1";
        if (!uid || !cat) return;
        if (!confirm(next ? "确认禁用该知识库？" : "确认重新启用该知识库？")) return;
        try {
          await api("/api/admin/knowledge-bases/toggle", {
            method: "POST",
            body: JSON.stringify({ user_id: uid, category: cat, disabled: next }),
          });
          showToast(next ? "已禁用" : "已启用", "ok");
          await loadAdminKbCatalog();
        } catch (err) {
          alert(err.message || String(err));
        }
        return;
      }
      const wip = e.target.closest("[data-adm-kb-wipe]");
      if (wip) {
        const uid = Number(wip.getAttribute("data-adm-kb-user") || "0");
        const cat = decodeURIComponent(wip.getAttribute("data-adm-kb-cat") || "");
        if (!uid || !cat) return;
        if (!confirm("将把该知识库下全部有效文档移入回收站（非立即物理删除）。是否继续？")) return;
        const typed = prompt("请再次输入知识库名称以确认：", "");
        if (typed == null || typed.trim() !== cat) {
          alert("知识库名称不一致");
          return;
        }
        try {
          const r = await api("/api/admin/knowledge-bases/soft-wipe", {
            method: "POST",
            body: JSON.stringify({
              user_id: uid,
              category: cat,
              confirm: true,
              typed_category: typed.trim(),
            }),
          });
          showToast("已处理 " + (r.soft_deleted || 0) + " 个文档", "ok");
          await loadAdminKbCatalog();
          await loadAdminDocs().catch(() => {});
        } catch (err) {
          alert(err.message || String(err));
        }
      }
    });
  }

  async function loadAdminDocs() {
    const box = $("adminDocsList");
    if (!box) return;
    const uid = ($("admDocUserFilter")?.value || "").trim();
    let st = "active";
    if (PAGE === "admin-trash") st = "deleted";
    else st = ($("admDocStatusFilter")?.value || "active").trim();
    let url = "/api/admin/documents?status=" + encodeURIComponent(st);
    if (uid) url += "&user_id=" + encodeURIComponent(uid);
    try {
      const d = await api(url);
      const docs = d.documents || [];
      if (!docs.length) {
        box.innerHTML = '<p class="gpt-muted">暂无文档</p>';
        return;
      }
      const rows = docs
        .map(function (x) {
          const canRestore = String(x.status || "") === "deleted";
          const opBtn = canRestore
            ? '<button class="gpt-btn-sm" data-adm-doc-restore="1">恢复</button>'
            : '<button class="gpt-btn-sm" data-adm-doc-delete="1">删除</button>';
          return (
            '<tr data-user-id="' +
            escapeHtml(String(x.user_id || "")) +
            '" data-file-name="' +
            escapeHtml(String(x.file_name || "")) +
            '"><td>' +
            escapeHtml(String(x.user_id || "")) +
            "</td><td>" +
            escapeHtml(String(x.file_name || "")) +
            "</td><td>" +
            escapeHtml(String(x.category || "")) +
            "</td><td>" +
            escapeHtml(String(x.status || "")) +
            "</td><td>" +
            escapeHtml(String(x.file_size_mb || 0)) +
            "</td><td>" +
            escapeHtml(String(x.chunks_count || 0)) +
            "</td><td>" +
            escapeHtml(String((x.upload_time || "").slice(0, 19)).replace("T", " ")) +
            '</td><td><div class="gpt-doc-actions">' +
            opBtn +
            "</div></td></tr>"
          );
        })
        .join("");
      box.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>用户ID</th><th>文件名</th><th>分类</th><th>状态</th><th>大小MB</th><th>分块</th><th>上传时间</th><th>操作</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      box.innerHTML = '<p class="gpt-muted">' + escapeHtml(e.message || String(e)) + "</p>";
    }
  }

  function wireAdminDocsActions() {
    const box = $("adminDocsList");
    if (!box || box.dataset.wired === "1") return;
    box.dataset.wired = "1";
    box.addEventListener("click", async function (e) {
      const row = e.target.closest("tr[data-user-id]");
      if (!row) return;
      const uid = Number(row.getAttribute("data-user-id") || "0");
      const file = row.getAttribute("data-file-name") || "";
      if (!uid || !file) return;
      if (e.target.closest("[data-adm-doc-delete]")) {
        if (!confirm("确认将文档移入回收站？")) return;
        await api(
          "/api/admin/documents/delete?user_id=" +
            encodeURIComponent(String(uid)) +
            "&file_name=" +
            encodeURIComponent(file),
          { method: "POST" }
        );
        showToast("已移入回收站", "ok");
        await loadAdminDocs();
      } else if (e.target.closest("[data-adm-doc-restore]")) {
        await api(
          "/api/admin/documents/restore?user_id=" +
            encodeURIComponent(String(uid)) +
            "&file_name=" +
            encodeURIComponent(file),
          { method: "POST" }
        );
        showToast("已恢复文档", "ok");
        await loadAdminDocs();
      }
    });
  }

  async function loadAdminAnalytics() {
    const cards = $("adminAnalyticsCards");
    const trendEl = $("adminAnalyticsTrend");
    if (!cards || !trendEl) return;
    const trendDays = Number($("admAnalyticsTrendDays")?.value || 30) || 30;
    function analyticsCard(val, lbl, sub) {
      return (
        '<div class="gpt-admin-stat-card">' +
        '<div class="val">' +
        escapeHtml(String(val)) +
        "</div>" +
        '<div class="lbl">' +
        escapeHtml(lbl) +
        "</div>" +
        (sub
          ? '<div class="gpt-analytics-card-sub">' + escapeHtml(sub) + "</div>"
          : "") +
        "</div>"
      );
    }
    try {
      const d = await api(
        "/api/admin/analytics/overview?trend_days=" +
          encodeURIComponent(String(trendDays)) +
          "&active_days=30"
      );
      const ad = d.active_users_window_days || 30;
      const storageMb = Number(d.storage_mb_total || 0);
      const storageLbl =
        storageMb >= 1024
          ? (storageMb / 1024).toFixed(2) + " GB"
          : storageMb.toFixed(1) + " MB";
      const faissMb = Number(d.faiss_mb_total || 0).toFixed(2) + " MB";
      cards.innerHTML =
        '<div class="gpt-admin-stats">' +
        analyticsCard(d.user_total ?? "—", "用户总数") +
        analyticsCard(d.users_active ?? "—", "活跃用户", "近 " + ad + " 天内有登录") +
        analyticsCard(d.knowledge_bases_total ?? "—", "知识库条目数", "平台知识库目录汇总") +
        analyticsCard(storageLbl, "存储占用", "各用户知识库目录合计") +
        analyticsCard(
          d.documents_total ?? "—",
          "文档总量",
          "有效文档；向量块 " +
            Number(d.chunks_total || 0).toLocaleString("zh-CN")
        ) +
        analyticsCard(faissMb, "FAISS 索引约", "全用户向量索引体积") +
        "</div>";
      const trend = d.upload_trend || [];
      if (!trend.length) {
        trendEl.innerHTML = '<p class="gpt-muted">暂无趋势数据</p>';
        return;
      }
      const maxU = Math.max.apply(
        null,
        trend.map(function (x) {
          return Number(x.uploads || 0);
        })
      );
      const maxUp = maxU > 0 ? maxU : 1;
      const bars = trend
        .map(function (x) {
          const u = Number(x.uploads || 0);
          const pct = u / maxUp;
          const ds = String(x.date || "");
          const short = ds.length >= 10 ? ds.slice(5, 10) : ds;
          return (
            '<div class="gpt-analytics-bar-col" title="' +
            escapeHtml(ds + "：上传 " + u + " 次") +
            '"><div class="gpt-analytics-bar-fill" style="--pct:' +
            String(pct) +
            '"></div><span class="gpt-analytics-bar-lbl">' +
            escapeHtml(short) +
            "</span></div>"
          );
        })
        .join("");
      trendEl.innerHTML = '<div class="gpt-analytics-trend-inner">' + bars + "</div>";
    } catch (e) {
      cards.textContent = e.message || String(e);
      trendEl.innerHTML = "";
    }
  }

  async function loadAdminLogs() {
    const el = $("adminLogsBody");
    if (!el) return;
    const cat = $("admLogCategory")?.value || "queries";
    try {
      const d = await api(
        "/api/admin/logs?category=" + encodeURIComponent(cat) + "&limit=150"
      );
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          return (
            "<tr><td>" +
            escapeHtml(String((it.timestamp || it.created_at || "").slice(0, 19)).replace("T", " ")) +
            "</td><td>" +
            escapeHtml(String(it.type || "")) +
            "</td><td>" +
            escapeHtml(JSON.stringify(it).slice(0, 220)) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>类型</th><th>摘要</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminStats() {
    const el = $("adminStatsBody");
    if (!el) return;
    try {
      const s = await api("/api/admin/stats");
      const faissMb = ((s.total_faiss_bytes_all_users || 0) / (1024 * 1024)).toFixed(2);
      el.innerHTML =
        '<div class="gpt-admin-stat-card"><div class="val">' +
        escapeHtml(String(s.user_count ?? "—")) +
        '</div><div class="lbl">注册用户</div></div>' +
        '<div class="gpt-admin-stat-card"><div class="val">' +
        escapeHtml(String(s.total_documents_all_users ?? 0)) +
        '</div><div class="lbl">文档总数</div></div>' +
        '<div class="gpt-admin-stat-card"><div class="val">' +
        escapeHtml(String(s.total_chunks_all_users ?? 0)) +
        '</div><div class="lbl">向量块总数</div></div>' +
        '<div class="gpt-admin-stat-card"><div class="val">' +
        escapeHtml(faissMb) +
        '</div><div class="lbl">FAISS 约 MB</div></div>' +
        '<div class="gpt-admin-stat-card gpt-admin-stat-wide">磁盘用户目录 id：' +
        escapeHtml((s.kb_folder_user_ids || []).join(", ") || "—") +
        "</div>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminTokenStats() {
    const el = $("adminTokenStatsBody");
    if (!el) return;
    try {
      let d;
      try {
        d = await api("/api/admin/tokens-summary");
      } catch (e1) {
        d = await api("/api/admin/token-stats");
      }
      const t = d.totals || {};
      const fmt = function (n) {
        return Number(n || 0).toLocaleString("zh-CN");
      };
      let html = '<div class="gpt-admin-token-cards">';
      html +=
        '<div class="gpt-admin-stat-card"><div class="val">' +
        fmt(t.total_tokens) +
        '</div><div class="lbl">累计 Token</div></div>';
      html +=
        '<div class="gpt-admin-stat-card"><div class="val">' +
        fmt(t.prompt_tokens) +
        '</div><div class="lbl">输入 Token</div></div>';
      html +=
        '<div class="gpt-admin-stat-card"><div class="val">' +
        fmt(t.completion_tokens) +
        '</div><div class="lbl">输出 Token</div></div>';
      html +=
        '<div class="gpt-admin-stat-card"><div class="val">' +
        escapeHtml(String(t.calls ?? 0)) +
        '</div><div class="lbl">LLM 调用次数</div></div>';
      html +=
        '<div class="gpt-admin-stat-card"><div class="val">¥' +
        escapeHtml(String(Number(t.estimated_cost_cny || 0).toFixed(4))) +
        '</div><div class="lbl">估算费用(CNY)</div></div>';
      html += "</div>";
      html +=
        '<p class="gpt-muted" style="margin-top:0.75rem">数据来自知识库目录下的 <code>statistics.json</code>（仅统计 Web 问答等已接入记录的调用）。</p>';

      const byModel = d.by_model || {};
      const mk = Object.keys(byModel);
      if (mk.length) {
        html +=
          '<h4 class="gpt-settings-block-title gpt-settings-block-title-spaced">按模型</h4><table class="gpt-audit-table"><thead><tr><th>模型</th><th>调用</th><th>输入</th><th>输出</th><th>合计</th></tr></thead><tbody>';
        mk.forEach(function (model) {
          const x = byModel[model];
          html +=
            "<tr><td>" +
            escapeHtml(model) +
            "</td><td>" +
            escapeHtml(String(x.calls || 0)) +
            "</td><td>" +
            fmt(x.prompt_tokens) +
            "</td><td>" +
            fmt(x.completion_tokens) +
            "</td><td>" +
            fmt(x.total_tokens) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }

      const byUser = d.by_user || {};
      const uk = Object.keys(byUser);
      if (uk.length) {
        html +=
          '<h4 class="gpt-settings-block-title gpt-settings-block-title-spaced">按用户</h4><table class="gpt-audit-table"><thead><tr><th>用户</th><th>调用</th><th>输入</th><th>输出</th><th>合计</th></tr></thead><tbody>';
        uk
          .slice()
          .sort()
          .forEach(function (k) {
            const x = byUser[k];
            const label = k === "_unset" ? "（历史未带用户 ID）" : "用户 id " + escapeHtml(k);
            html +=
              "<tr><td>" +
              label +
              "</td><td>" +
              escapeHtml(String(x.calls || 0)) +
              "</td><td>" +
              fmt(x.prompt_tokens) +
              "</td><td>" +
              fmt(x.completion_tokens) +
              "</td><td>" +
              fmt(x.total_tokens) +
              "</td></tr>";
          });
        html += "</tbody></table>";
      }

      const recent = d.recent || [];
      if (recent.length) {
        html +=
          '<h4 class="gpt-settings-block-title gpt-settings-block-title-spaced">最近记录</h4><table class="gpt-audit-table"><thead><tr><th>时间</th><th>用户</th><th>类型</th><th>模型</th><th>合计</th></tr></thead><tbody>';
        recent.slice(0, 50).forEach(function (r) {
          const ts = String(r.timestamp || "").slice(5, 22);
          const uid = r.user_id != null ? String(r.user_id) : "—";
          html +=
            "<tr><td>" +
            escapeHtml(ts) +
            "</td><td>" +
            escapeHtml(uid) +
            "</td><td>" +
            escapeHtml(String(r.call_type || "")) +
            "</td><td>" +
            escapeHtml(String(r.model || "")) +
            "</td><td>" +
            fmt(r.total_tokens) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }

      el.innerHTML = html;
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminPlatformAudit() {
    const el = $("adminPlatformAuditBody");
    if (!el) return;
    try {
      const d = await api("/api/admin/platform-audit?limit=200");
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          return (
            "<tr><td>" +
            escapeHtml(String(it.created_at || "").slice(5, 19)) +
            "</td><td>" +
            escapeHtml(String(it.actor_username || "—")) +
            "</td><td>" +
            escapeHtml(String(it.action || "")) +
            "</td><td class=\"gpt-audit-path\" title=\"" +
            escapeHtml(String(it.target || "")) +
            "\">" +
            escapeHtml(String(it.target || "")) +
            "</td><td class=\"gpt-audit-path\">" +
            escapeHtml(String(it.detail || "").slice(0, 160)) +
            "</td><td>" +
            escapeHtml(String(it.client_ip || "—")) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>详情</th><th>IP</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminLoginAudit() {
    const el = $("adminLoginAuditBody");
    if (!el) return;
    try {
      const d = await api("/api/admin/login-audit?limit=200");
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          return (
            "<tr><td>" +
            escapeHtml(String(it.created_at || "").slice(5, 19)) +
            "</td><td>" +
            escapeHtml(String(it.user_id != null ? it.user_id : "—")) +
            "</td><td>" +
            escapeHtml(String(it.username || "—")) +
            "</td><td>" +
            escapeHtml(String(it.outcome || "")) +
            "</td><td>" +
            escapeHtml(String(it.ip || "—")) +
            "</td><td class=\"gpt-audit-path\">" +
            escapeHtml(String(it.user_agent || "").slice(0, 80)) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>用户ID</th><th>用户名</th><th>结果</th><th>IP</th><th>UA</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminLoginFailures() {
    const el = $("adminLoginFailureBody");
    if (!el) return;
    try {
      const d = await api("/api/admin/login-failures?limit=200");
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          return (
            "<tr><td>" +
            escapeHtml(String(it.created_at || "").slice(5, 19)) +
            "</td><td>" +
            escapeHtml(String(it.ip || "—")) +
            "</td><td>" +
            escapeHtml(String(it.username || "—")) +
            "</td><td>" +
            escapeHtml(String(it.reason || "")) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>IP</th><th>用户名</th><th>原因</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminFeedback() {
    const el = $("adminFeedbackBody");
    if (!el) return;
    const stEl = $("admFeedbackStatus");
    const st = stEl && stEl.value ? String(stEl.value) : "";
    try {
      const q = st ? "?limit=100&status=" + encodeURIComponent(st) : "?limit=100";
      const d = await api("/api/admin/feedback" + q);
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          const id = String(it.id);
          const reply = String(it.admin_reply || "").trim();
          return (
            "<tr><td>" +
            escapeHtml(String(it.created_at || "").slice(5, 19)) +
            "</td><td>" +
            escapeHtml(String(it.status || "")) +
            "</td><td>" +
            escapeHtml(String(it.user_id != null ? it.user_id : "—")) +
            "</td><td>" +
            escapeHtml(String(it.username || it.contact || "—")) +
            "</td><td class=\"gpt-audit-path\">" +
            escapeHtml(String(it.title || "").slice(0, 80)) +
            "</td><td class=\"gpt-audit-path\" title=\"" +
            escapeHtml(String(it.content || "")) +
            "\">" +
            escapeHtml(String(it.content || "").slice(0, 120)) +
            "</td><td class=\"gpt-audit-path\">" +
            escapeHtml(reply.slice(0, 80)) +
            "</td><td>" +
            '<button type="button" class="gpt-btn-sm" data-fb-act="processing" data-fid="' +
            id +
            '">处理中</button> ' +
            '<button type="button" class="gpt-btn-sm" data-fb-act="closed" data-fid="' +
            id +
            '">关闭</button> ' +
            '<button type="button" class="gpt-btn-sm" data-fb-act="reply" data-fid="' +
            id +
            '">回复</button>' +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>状态</th><th>用户ID</th><th>用户/联系</th><th>标题</th><th>内容</th><th>回复</th><th>操作</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminAudit() {
    const el = $("adminAuditBody") || $("adminApiAuditBody");
    if (!el) return;
    try {
      const d = await api("/api/admin/audit?limit=150");
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="gpt-muted" style="padding:1rem">暂无记录</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          const sc = it.status_code != null ? String(it.status_code) : "—";
          const cls = statusCodeClass(sc);
          const err = it.error ? escapeHtml(String(it.error).slice(0, 120)) : "";
          return (
            "<tr><td>" +
            escapeHtml(String(it.created_at || "").slice(5, 19)) +
            '</td><td class="gpt-audit-path" title="' +
            escapeHtml(it.path || "") +
            '">' +
            escapeHtml(it.path || "") +
            "</td><td>" +
            escapeHtml(it.method || "") +
            '</td><td class="' +
            cls +
            '">' +
            escapeHtml(sc) +
            "</td><td>" +
            (it.duration_ms != null ? Number(it.duration_ms).toFixed(0) + "ms" : "—") +
            "</td><td>" +
            escapeHtml(it.username || "—") +
            "</td><td>" +
            err +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>时间</th><th>路径</th><th>方法</th><th>状态</th><th>耗时</th><th>用户</th><th>异常</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminAdvancedForm() {
    const msg = $("adminAdvMsg");
    if (msg) {
      msg.hidden = true;
      msg.textContent = "";
    }
    try {
      const s = await api("/api/admin/settings");
      const rd = s.rag_defaults || {};
      const k = $("advRagK");
      if (k) k.value = String(rd.default_retrieval_k ?? 10);
      const sm = $("advSearchMode");
      if (sm) sm.value = rd.default_search_mode === "hybrid" ? "hybrid" : "vector";
      const rr = $("advRerank");
      if (rr) rr.checked = !!rd.default_enable_reranker;
      const rs = $("advRespStyle");
      if (rs) {
        const v = String(rd.default_response_style || "balanced");
        rs.value = ["precise", "balanced", "verbose"].includes(v) ? v : "balanced";
      }
      const te = $("advTemp");
      if (te) te.value = String(rd.default_temperature ?? 0);
      const cl = s.chunk_levels || {};
      const setLv = (lv, idS, idO) => {
        const sub = cl[lv] || {};
        const es = $(idS);
        const eo = $(idO);
        if (es) es.value = String(sub.chunk_size ?? "");
        if (eo) eo.value = String(sub.chunk_overlap ?? "");
      };
      setLv("small", "advCsSmall", "advCoSmall");
      setLv("medium", "advCsMed", "advCoMed");
      setLv("large", "advCsLarge", "advCoLarge");
      const en = $("advEmbedNote");
      if (en) en.value = String(s.embedding_model_note || "");
      const tx = $("advSysExtra");
      if (tx) tx.value = String(s.system_prompt_extra || "");
      const wp = $("advWebSearchProvider");
      if (wp) {
        const v = String(s.web_search_provider || "bocha");
        if (v === "brave") wp.value = "brave";
        else if (v === "baidu") wp.value = "baidu";
        else wp.value = "bocha";
      }
      const bh = $("advBochaKeyHint");
      if (bh) {
        bh.textContent = s.bocha_api_key_configured
          ? "当前已保存博查密钥（输入新值可覆盖）"
          : "尚未在服务端保存博查密钥";
      }
      const brh = $("advBraveKeyHint");
      if (brh) {
        brh.textContent = s.brave_api_key_server_configured
          ? "当前已保存 Brave 密钥（输入新值可覆盖）"
          : "尚未在服务端保存 Brave 密钥";
      }
      const qfh = $("advQianfanKeyHint");
      if (qfh) {
        qfh.textContent = s.qianfan_api_key_configured
          ? "当前已保存千帆密钥（输入新值可覆盖）"
          : "尚未在服务端保存千帆密钥";
      }
      const bk = $("advBochaKey");
      if (bk) bk.value = "";
      const brk = $("advBraveKey");
      if (brk) brk.value = "";
      const qfk = $("advQianfanKey");
      if (qfk) qfk.value = "";
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
    }
  }

  let _adminPromptSlug = "";

  async function loadAdminPromptTemplatesPage() {
    const tbl = $("adminPromptListMeta");
    const sel = $("adminPromptSlug");
    if (!tbl && !sel) return;
    try {
      const d = await api("/api/admin/prompt-templates");
      const items = d.items || [];
      if (tbl) {
        if (!items.length) {
          tbl.innerHTML =
            '<p class="gpt-muted">暂无模板，请先启动应用完成 MySQL 建表与种子，或检查 <code>prompt_templates</code>。</p>';
        } else {
          tbl.innerHTML =
            '<table class="gpt-audit-table"><thead><tr><th>slug</th><th>名称</th><th>启用</th><th>版本</th><th>字数</th><th>更新</th></tr></thead><tbody>' +
            items
              .map(function (it) {
                return (
                  "<tr><td><code>" +
                  escapeHtml(it.slug) +
                  "</code></td><td>" +
                  escapeHtml(it.name || "") +
                  "</td><td>" +
                  (it.is_active ? "是" : "否") +
                  "</td><td>" +
                  escapeHtml(String(it.version || "")) +
                  "</td><td>" +
                  escapeHtml(String(it.body_chars || 0)) +
                  "</td><td>" +
                  escapeHtml(String(it.updated_at || "").slice(0, 19).replace("T", " ")) +
                  "</td></tr>"
                );
              })
              .join("") +
            "</tbody></table>";
        }
      }
      if (sel) {
        const cur = sel.value || _adminPromptSlug || (items[0] && items[0].slug) || "";
        sel.innerHTML = items
          .map(function (it) {
            return (
              '<option value="' +
              escapeHtml(it.slug) +
              '">' +
              escapeHtml(it.slug + " — " + (it.name || "")) +
              "</option>"
            );
          })
          .join("");
        if (
          cur &&
          Array.prototype.some.call(sel.options, function (o) {
            return o.value === cur;
          })
        ) {
          sel.value = cur;
        }
        _adminPromptSlug = sel.value;
        await loadAdminPromptDetail();
      }
    } catch (e) {
      if (tbl) tbl.textContent = e.message || String(e);
    }
  }

  async function loadAdminPromptDetail() {
    const sel = $("adminPromptSlug");
    const slug = (sel && sel.value) || _adminPromptSlug;
    if (!slug) return;
    _adminPromptSlug = slug;
    try {
      const d = await api("/api/admin/prompt-templates/" + encodeURIComponent(slug));
      const n = $("adminPromptName");
      const de = $("adminPromptDesc");
      const tx = $("adminPromptBody");
      const ac = $("adminPromptActive");
      const meta = $("adminPromptMeta");
      if (n) n.value = d.name || "";
      if (de) de.value = d.description || "";
      if (tx) tx.value = d.template_body || "";
      if (ac) ac.checked = d.is_active !== 0;
      if (meta) {
        meta.textContent =
          "版本 v" +
          String(d.version || 1) +
          " · 更新于 " +
          String(d.updated_at || "—").slice(0, 19).replace("T", " ") +
          (d.updated_by_username ? " · " + d.updated_by_username : "");
      }
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  }

  async function saveAdminPromptTemplate() {
    const sel = $("adminPromptSlug");
    const slug = (sel && sel.value) || "";
    if (!slug) return;
    const rawBody = ($("adminPromptBody") && $("adminPromptBody").value) || "";
    if (!rawBody.trim()) {
      showToast("正文不能为空", "err");
      return;
    }
    const body = {
      template_body: rawBody,
      name: ($("adminPromptName") && $("adminPromptName").value.trim()) || "",
      description: ($("adminPromptDesc") && $("adminPromptDesc").value.trim()) || "",
      is_active: $("adminPromptActive") ? !!$("adminPromptActive").checked : true,
    };
    try {
      await api("/api/admin/prompt-templates/" + encodeURIComponent(slug), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      showToast("已保存（约 45s 内前台缓存会刷新）", "ok");
      await loadAdminPromptTemplatesPage();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  }

  async function loadAdminMysqlTableCounts() {
    const el = $("adminMysqlCountsBody");
    if (!el) return;
    try {
      const d = await api("/api/admin/mysql-table-counts");
      const c = d.counts || {};
      const rows = Object.keys(c)
        .filter(function (k) {
          return c[k] >= 0;
        })
        .map(function (k) {
          return (
            "<tr><td><code>" +
            escapeHtml(k) +
            "</code></td><td>" +
            escapeHtml(String(c[k])) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>表</th><th>行数</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminLlmMysqlLogs() {
    const el = $("adminLlmMysqlLogsBody");
    if (!el) return;
    const lim = Math.min(
      500,
      Math.max(1, parseInt($("admLlmMysqlLimit") && $("admLlmMysqlLimit").value, 10) || 80)
    );
    const off = Math.max(0, parseInt($("admLlmMysqlOffset") && $("admLlmMysqlOffset").value, 10) || 0);
    const ct = ($("admLlmMysqlCallType") && $("admLlmMysqlCallType").value.trim()) || "";
    try {
      let url =
        "/api/admin/llm-mysql-logs?limit=" +
        encodeURIComponent(String(lim)) +
        "&offset=" +
        encodeURIComponent(String(off));
      if (ct) url += "&call_type=" + encodeURIComponent(ct);
      const d = await api(url);
      const ttl = $("admLlmMysqlTotal");
      if (ttl) ttl.textContent = "总计 " + String(d.total || 0) + " 条";
      const items = d.items || [];
      if (!items.length) {
        el.innerHTML =
          '<p class="gpt-muted" style="padding:1rem">暂无记录（或尚未产生写入 log_token_usage 的调用）</p>';
        return;
      }
      const rows = items
        .map(function (it) {
          return (
            "<tr><td>" +
            escapeHtml(String(it.id || "")) +
            "</td><td>" +
            escapeHtml(String((it.created_at || "").slice(0, 19)).replace("T", " ")) +
            "</td><td>" +
            escapeHtml(String(it.call_type || "")) +
            "</td><td>" +
            escapeHtml(String(it.model || "—")) +
            "</td><td>" +
            escapeHtml(String(it.total_tokens ?? "—")) +
            "</td><td>" +
            escapeHtml(it.user_id != null ? String(it.user_id) : "—") +
            "</td><td>" +
            escapeHtml(it.success ? "OK" : "失败") +
            '</td><td class="gpt-muted">' +
            escapeHtml(String((it.error_message || "").slice(0, 120))) +
            "</td></tr>"
          );
        })
        .join("");
      el.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>ID</th><th>时间</th><th>类型</th><th>模型</th><th>Tokens</th><th>用户</th><th>结果</th><th>备注</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      el.textContent = e.message || String(e);
    }
  }

  async function loadAdminSettingsForm() {
    const msg = $("adminSysMsg");
    if (msg) {
      msg.hidden = true;
      msg.textContent = "";
    }
    try {
      const s = await api("/api/admin/settings");
      const c = $("admRegEnabled");
      if (c) c.checked = !!s.registration_enabled;
      const cg = $("admGuestEnabled");
      if (cg) cg.checked = !!s.guest_mode_enabled;
      const cm = $("admMaintenanceEnabled");
      if (cm) cm.checked = !!s.maintenance_mode_enabled;
      const mb = $("admMaxMb");
      if (mb) mb.value = String(s.max_upload_mb || 50);
      const sm = $("admStorageCapMb");
      if (sm) sm.value = String(s.per_user_storage_mb ?? 0);
      const pum = $("admPerUserMaxMb");
      if (pum) pum.value = String(s.per_user_max_upload_mb ?? 0);
      const md = $("admMaxDocs");
      if (md) md.value = String(s.max_docs_per_user || 500);
      const qpm = $("admRateLimitQpm");
      if (qpm) qpm.value = String(s.rate_limit_qpm_per_user || 60);
      const ex = $("admExts");
      if (ex) ex.value = (s.allowed_extensions || []).join(",");
      const sw = $("admSensitiveWords");
      if (sw) sw.value = String(s.sensitive_words || "");
      const cad = $("admComplianceAuto");
      if (cad) cad.checked = s.compliance_auto_disable !== false;
      const bfe = $("admBruteforceEnabled");
      if (bfe) bfe.checked = s.login_bruteforce_enabled !== false;
      const bfw = $("admBruteforceWindowMin");
      if (bfw) bfw.value = String(s.login_bruteforce_window_minutes ?? 15);
      const bfi = $("admBruteforceMaxIp");
      if (bfi) bfi.value = String(s.login_bruteforce_max_per_ip ?? 40);
      const bfu = $("admBruteforceMaxUser");
      if (bfu) bfu.value = String(s.login_bruteforce_max_per_username ?? 12);
      const rw = $("admRagWebSearchUi");
      if (rw) rw.checked = s.rag_show_web_search_ui !== false;
      const iw = $("admInstantWebSearchUi");
      if (iw) iw.checked = s.instant_show_web_search_ui !== false;
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
    }
  }

  async function refreshKbDocs() {
    const filter = $("kbDocFilter");
    if (!filter) return;
    const cat = filter.value || "全部知识库";
    const isAll = cat === "全部知识库";

    const stats = await api("/api/kb/stats?category=" + encodeURIComponent(cat));

    let documents = [];
    if (kbDocsExpanded || !isAll) {
      const docsRes = await api("/api/documents?category=" + encodeURIComponent(cat));
      documents = docsRes.documents || [];
    }

    const card = $("kbKbInfoCard");
    const selectHint = $("kbSelectHint");
    const heading = $("kbInfoHeading");
    const recentEl = $("kbInfoRecent");
    const ks = $("kbStats");

    const statsPillsHtml =
      '<div class="gpt-stats-row">' +
      '<span class="gpt-stat-pill"><strong>' +
      stats.total_docs +
      '</strong><small>文档</small></span>' +
      '<span class="gpt-stat-pill"><strong>' +
      stats.total_chunks +
      '</strong><small>文本块</small></span>' +
      '<span class="gpt-stat-pill"><strong>' +
      stats.total_size_mb +
      '</strong><small>约 MB</small></span>' +
      "</div>";

    if (isAll) {
      if (card) card.hidden = false;
      if (selectHint) selectHint.hidden = false;
      if (heading) heading.textContent = "全部知识库 · 汇总";
      if (ks) ks.innerHTML = statsPillsHtml;
      if (recentEl) {
        const lu = stats.latest_upload_time;
        recentEl.textContent = lu
          ? "最近上传：" + String(lu).slice(0, 19).replace("T", " ")
          : kbLatestUploadSummary(documents);
      }
    } else {
      if (card) card.hidden = false;
      if (selectHint) selectHint.hidden = true;
      if (heading) heading.textContent = cat + " · 知识库信息";
      if (ks) ks.innerHTML = statsPillsHtml;
      if (recentEl) recentEl.textContent = kbLatestUploadSummary(documents);
    }

    const wrap = $("kbDocListWrap");
    const expandBtn = $("btnKbExpandDocs");
    if (wrap) wrap.hidden = !kbDocsExpanded;
    if (expandBtn) {
      expandBtn.setAttribute("aria-expanded", kbDocsExpanded ? "true" : "false");
      expandBtn.textContent = kbDocsExpanded ? "收起文档列表" : "展开文档列表";
    }

    const list = $("kbDocList");
    if (!list) return;
    list.innerHTML = "";
    if (!kbDocsExpanded) return;

    if (!documents.length) {
      list.innerHTML = "<p class=\"gpt-muted\">暂无文档</p>";
      return;
    }

    documents.forEach((doc) => {
      const dcard = document.createElement("div");
      dcard.className = "gpt-doc-card";
      const name = doc.file_name || "";
      dcard.innerHTML =
        "<h4>" +
        escapeHtml(name) +
        "</h4><div class=\"gpt-doc-meta\">" +
        escapeHtml(doc.category || "") +
        " · " +
        (doc.chunks_count || 0) +
        " 块 · " +
        (doc.file_size_mb || 0) +
        " MB · " +
        escapeHtml((doc.upload_time || "").slice(0, 16)) +
        "</div>";
      const actions = document.createElement("div");
      actions.className = "gpt-doc-actions";
      [
        ["查看内容", () => openPreview(name, "content")],
        ["结构", () => openPreview(name, "structure")],
        ["编辑", () => openEditDoc(name)],
        ["删除", () => deleteDoc(name)],
      ].forEach(([label, fn]) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "gpt-btn-sm";
        b.textContent = label;
        b.addEventListener("click", fn);
        actions.appendChild(b);
      });
      dcard.appendChild(actions);
      list.appendChild(dcard);
    });
  }

  async function openPreview(fileName, mode) {
    const titleEl = $("previewTitle");
    if (titleEl) {
      titleEl.textContent =
        mode === "structure" ? "文档结构 · " + fileName : "查看内容 · " + fileName;
    }
    const body = $("previewBody");
    body.innerHTML = "加载中…";
    $("dlgPreview").showModal();
    try {
      const d = await api(
        "/api/documents/preview?file_name=" + encodeURIComponent(fileName) + "&mode=" + mode
      );
      if (mode === "structure") {
        body.innerHTML = "<pre class=\"gpt-log\">" + escapeHtml(JSON.stringify(d, null, 2)) + "</pre>";
      } else if (d.chunks && !d.text && (d.chunks || []).length) {
        body.innerHTML = "";
        (d.chunks || []).forEach((ch, i) => {
          const div = document.createElement("div");
          div.className = "gpt-chunk";
          div.innerHTML =
            "<strong>分块 " +
            escapeHtml(String(ch.chunk_id || i)) +
            "</strong> · 页 " +
            escapeHtml(String(ch.page ?? "—")) +
            " · " +
            (ch.chars || 0) +
            " 字";
          const pre = document.createElement("pre");
          pre.style.margin = "0.35rem 0 0";
          pre.style.fontSize = "0.78rem";
          pre.style.whiteSpace = "pre-wrap";
          pre.textContent = ch.content || ch.error || "";
          div.appendChild(pre);
          body.appendChild(div);
        });
      } else {
        body.innerHTML = "";
        const wrap = document.createElement("div");
        if (d.note) {
          const p = document.createElement("p");
          p.className = "gpt-muted";
          p.style.margin = "0 0 0.65rem";
          p.textContent = d.note;
          wrap.appendChild(p);
        }
        if (d.parse_warning) {
          const pw = document.createElement("p");
          pw.className = "gpt-warn";
          pw.style.margin = "0 0 0.5rem";
          pw.textContent = d.parse_warning;
          wrap.appendChild(pw);
        }
        if (d.error && !d.text) {
          const er = document.createElement("p");
          er.className = "gpt-warn";
          er.textContent = d.error;
          wrap.appendChild(er);
        } else {
          const pre = document.createElement("pre");
          pre.className = "gpt-log gpt-doc-fulltext";
          pre.style.whiteSpace = "pre-wrap";
          pre.style.maxHeight = "70vh";
          pre.style.overflow = "auto";
          pre.style.fontSize = "0.82rem";
          pre.textContent = d.text || "";
          wrap.appendChild(pre);
        }
        if (d.truncated) {
          const t = document.createElement("p");
          t.className = "gpt-muted";
          t.style.margin = "0.5rem 0 0";
          t.textContent = "正文较长，已截断显示（最多约 50 万字符）。";
          wrap.appendChild(t);
        }
        body.appendChild(wrap);
      }
    } catch (e) {
      body.textContent = e.message || String(e);
    }
  }

  function kbSearchMatchTypeZh(t) {
    if (t === "meta_filename") return "文件名";
    if (t === "meta_description") return "描述";
    if (t === "content") return "正文";
    if (t === "meta") return "文件名/描述";
    return t || "匹配";
  }

  function kbSearchHitInnerHtml(r) {
    if (r.before != null && r.match != null && r.after != null) {
      return (
        '<div class="gpt-kb-hit-line">' +
        escapeHtml(String(r.before)) +
        '<mark class="gpt-kb-hit-mark">' +
        escapeHtml(String(r.match)) +
        "</mark>" +
        escapeHtml(String(r.after)) +
        "</div>"
      );
    }
    const sn = r.snippet != null ? String(r.snippet) : "";
    return '<div class="gpt-kb-hit-line">' + escapeHtml(sn) + "</div>";
  }

  async function runKbDocSearch() {
    const inp = $("kbDocSearch");
    const out = $("kbSearchResults");
    if (!inp || !out) return;
    const q = inp.value.trim();
    if (!q) {
      out.innerHTML = "";
      return;
    }
    const cat = ($("kbDocFilter") && $("kbDocFilter").value) || "全部知识库";
    out.innerHTML = "<p class=\"gpt-muted\">全文检索中…</p>";
    try {
      const d = await api(
        "/api/documents/search?q=" +
          encodeURIComponent(q) +
          "&category=" +
          encodeURIComponent(cat) +
          "&max_total=1200&max_per_file=300"
      );
      const rows = d.results || [];
      if (!rows.length) {
        out.innerHTML = "<p class=\"gpt-muted\">无匹配条目</p>";
        return;
      }
      out.innerHTML = "";
      const sum = document.createElement("p");
      sum.className = "gpt-kb-search-summary";
      let sumText =
        "共 <strong>" + (d.result_count != null ? d.result_count : rows.length) + "</strong> 处命中（每条为一处，关键词已高亮）";
      if (d.truncated) {
        sumText +=
          " · <span class=\"gpt-warn\">已达返回上限（" +
          (d.max_total || "") +
          "），未全部列出</span>";
      }
      sum.innerHTML = sumText;
      out.appendChild(sum);
      rows.forEach((r) => {
        const div = document.createElement("div");
        div.className = "gpt-kb-search-hit";
        const mt = kbSearchMatchTypeZh(r.match_type);
        const pos = r.global_offset != null ? " · 位置 " + r.global_offset : "";
        const head = document.createElement("div");
        head.className = "gpt-kb-search-hit-head";
        head.innerHTML =
          "<strong>" +
          escapeHtml(r.file_name) +
          '</strong> <span class="gpt-muted">' +
          escapeHtml(mt) +
          escapeHtml(pos) +
          "</span>";
        const sn = document.createElement("div");
        sn.className = "gpt-kb-hit-snippet";
        sn.innerHTML = kbSearchHitInnerHtml(r);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "gpt-btn-sm";
        btn.textContent = "查看全文";
        btn.addEventListener("click", () => openPreview(r.file_name, "content"));
        div.appendChild(head);
        div.appendChild(sn);
        div.appendChild(btn);
        out.appendChild(div);
      });
    } catch (e) {
      out.textContent = e.message || String(e);
    }
  }

  function syncEditCategories() {
    const sel = $("editDocCat");
    if (!sel) return;
    const kbEl = $("kb");
    const df = $("kbDocFilter");
    let catSource = [];
    if (kbEl && kbEl.options && kbEl.options.length) {
      catSource = [...kbEl.options].map((o) => o.value);
    } else if (df && df.options && df.options.length) {
      catSource = [...df.options].map((o) => o.value);
    }
    const prev = sel.value;
    sel.innerHTML = "";
    getCategoriesOnly(catSource).forEach((c) => {
      const o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      sel.appendChild(o);
    });
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  }

  async function openEditDoc(fileName) {
    $("editDocName").value = fileName;
    syncEditCategories();
    const docs = await api("/api/documents?category=全部知识库");
    const doc = (docs.documents || []).find((d) => d.file_name === fileName);
    $("editDocCat").value = (doc && doc.category) || "默认知识库";
    $("editDocDesc").value = (doc && doc.description) || "";
    $("dlgEditDoc").showModal();
  }

  async function deleteDoc(fileName) {
    if (!confirm("永久删除「" + fileName + "」及向量？不可恢复。")) return;
    await api("/api/documents?file_name=" + encodeURIComponent(fileName), { method: "DELETE" });
    await refreshKbDocs();
    await pingStatus();
  }

  async function refreshKbCatList() {
    const ul = $("kbCatList");
    if (!ul) return;
    const data = await api("/api/knowledge-bases");
    ul.innerHTML = "";
    getCategoriesOnly(data.categories || []).forEach((name) => {
      const li = document.createElement("li");
      li.innerHTML = "<span>" + escapeHtml(name) + "</span>";
      if (name !== "默认知识库") {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "gpt-btn-sm";
        b.textContent = "删除";
        b.addEventListener("click", async () => {
          if (!confirm("删除知识库「" + name + "」？文档会移到默认知识库。")) return;
          await api("/api/categories?name=" + encodeURIComponent(name), { method: "DELETE" });
          await fillKbSelects();
          await refreshKbCatList();
        });
        li.appendChild(b);
      } else {
        const s = document.createElement("span");
        s.className = "gpt-muted";
        s.textContent = "（不可删）";
        li.appendChild(s);
      }
      ul.appendChild(li);
    });
  }

  function isMobileSidebarLayout() {
    return window.matchMedia("(max-width: 768px)").matches;
  }

  function syncBackdropToSidebar() {
    const side = $("gptSidebar");
    const back = $("gptBackdrop");
    if (!back || !side) return;
    if (!isMobileSidebarLayout()) {
      back.hidden = true;
    } else {
      back.hidden = side.classList.contains("collapsed");
    }
  }

  function closeMobileSidebar() {
    const side = $("gptSidebar");
    const back = $("gptBackdrop");
    if (!side || !isMobileSidebarLayout()) return;
    side.classList.add("collapsed");
    if (back) back.hidden = true;
  }

  function syncRailToggleIcon() {
    const b = $("btnSidebarRailToggle");
    if (!b) return;
    b.textContent = "⟨";
    b.setAttribute("aria-label", "收起侧栏文字，仅显示图标");
    b.title = "收起文字仅保留图标";
  }

  function sidebarHasRailChrome() {
    return $("gptSidebar") && $("btnSidebarExpand") && $("btnSidebarRailToggle");
  }

  function persistSidebarRail() {
    const side = $("gptSidebar");
    if (!side || !sidebarHasRailChrome() || isMobileSidebarLayout()) return;
    localStorage.setItem("rag_chat_sidebar_rail", side.classList.contains("rail") ? "1" : "0");
  }

  function isSidebarSubpageLayout() {
    return document.body.classList.contains("gpt-subpage");
  }

  function toggleDesktopRail() {
    const side = $("gptSidebar");
    if (!side || isMobileSidebarLayout() || !sidebarHasRailChrome() || isSidebarSubpageLayout()) return;
    side.classList.toggle("rail");
    persistSidebarRail();
    syncRailToggleIcon();
  }

  function initSidebarToggle() {
    const side = $("gptSidebar");
    const togg = $("btnSidebarToggle");
    const railBtn = $("btnSidebarRailToggle");
    const expandTop = $("btnSidebarExpand");
    if (!side) return;
    togg?.addEventListener("click", function (e) {
      e.stopPropagation();
      if (isMobileSidebarLayout()) {
        side.classList.toggle("collapsed");
        syncBackdropToSidebar();
      }
    });
    expandTop?.addEventListener("click", function (e) {
      e.stopPropagation();
      if (isMobileSidebarLayout() || !sidebarHasRailChrome()) return;
      side.classList.remove("rail");
      if (!isSidebarSubpageLayout()) {
        persistSidebarRail();
      }
      syncRailToggleIcon();
    });
    railBtn?.addEventListener("click", function (e) {
      e.stopPropagation();
      if (isSidebarSubpageLayout()) return;
      if (!isMobileSidebarLayout()) toggleDesktopRail();
    });
    $("gptBackdrop")?.addEventListener("click", function () {
      side.classList.add("collapsed");
      syncBackdropToSidebar();
    });
    window.addEventListener("resize", function () {
      if (isMobileSidebarLayout()) {
        side.classList.remove("rail");
      }
      syncBackdropToSidebar();
      syncRailToggleIcon();
    });
    syncRailToggleIcon();
  }

  function initTheme() {
    const saved = localStorage.getItem("rag_theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    const bt = $("btnTheme");
    if (bt) {
      bt.addEventListener("click", function () {
        const cur =
          document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
        const next = cur === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("rag_theme", next);
        schedulePushWebUiState();
      });
    }
  }

  $("btnNewConv")?.addEventListener("click", newConv);

  function wireInstantDocPage() {
    if (!IS_INSTANT_PAGE) return;
    const fin = $("instantFileInput");
    const btn = $("btnInstantAttach");
    const clr = $("instantDocClear");
    btn?.addEventListener("click", function () {
      fin?.click();
    });
    clr?.addEventListener("click", function () {
      const conv = currentConv();
      if (conv) conv.instantDoc = null;
      saveStore();
      syncInstantDocBar();
      showToast("已移除文档", "ok");
    });
    fin?.addEventListener("change", async function () {
      const f = this.files && this.files[0];
      this.value = "";
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f, f.name);
      const token = getAuthToken();
      const headers = {};
      if (token) headers.Authorization = "Bearer " + token;
      try {
        showToast("正在解析…", "ok");
        const res = await fetch("/api/instant-doc/parse", { method: "POST", headers: headers, body: fd });
        if (res.status === 401) {
          clearAuth();
          const next = encodeURIComponent(location.pathname + location.search);
          window.location.href = LOGIN_PAGE + "?next=" + next;
          return;
        }
        const j = await res.json();
        if (!j.ok) {
          showToast(j.error || "解析失败", "err");
          return;
        }
        const conv = currentConv();
        conv.instantDoc = { text: j.text, fileName: j.file_name || f.name };
        saveStore();
        syncInstantDocBar();
        showToast("已载入 " + j.char_count + " 字", "ok");
      } catch (e) {
        showToast(e.message || "上传失败", "err");
      }
    });
  }
  wireInstantDocPage();

  $("formRename")?.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!renameTargetId) return;
    const t = $("renameInput").value.trim();
    if (t) {
      store.conversations[renameTargetId].title = t;
      saveStore();
      void flushPushWebUiState();
      renderConvList();
      updateTopbar();
    }
    $("dlgRename")?.close();
    renameTargetId = null;
  });
  $("renameCancel")?.addEventListener("click", () => {
    $("dlgRename")?.close();
    renameTargetId = null;
  });

  $("form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sendBtn = $("send");
    if (sendBtn && sendBtn.dataset.streamingStop === "1") {
      abortActiveChatStream();
      return;
    }
    const inpEl = $("input");
    if (!inpEl) return;
    const msg = inpEl.value.trim();
    if (!msg) return;

    const convId = store.currentId;
    currentConv().messages.push({ role: "user", content: msg });
    currentConv().updatedAt = Date.now();
    const userTurns = currentConv().messages.filter(function (m) {
      return m.role === "user";
    });
    const isFirstUserMessage = userTurns.length === 1;
    saveStore();
    inpEl.value = "";
    renderThread();
    updateEmptyState();
    updateTopbar();
    if (isFirstUserMessage && isDefaultConvTitle(currentConv().title)) {
      void suggestConversationTitle(convId, msg);
    }
    await runChatCompletionForUserText(msg);
  });

  $("input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const sb = $("send");
      if (sb && sb.dataset.streamingStop === "1") return;
      $("form")?.requestSubmit();
    }
  });

  $("btnKbDocRefresh")?.addEventListener("click", () => refreshKbDocs().catch(alert));
  $("kbDocFilter")?.addEventListener("change", () => {
    refreshKbDocs().catch(alert);
    const out = $("kbSearchResults");
    if (out) out.innerHTML = "";
  });
  $("btnKbExpandDocs")?.addEventListener("click", () => {
    kbDocsExpanded = !kbDocsExpanded;
    refreshKbDocs().catch(alert);
  });
  $("btnKbDocSearch")?.addEventListener("click", () => runKbDocSearch().catch(alert));
  $("kbDocSearch")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runKbDocSearch().catch(alert);
    }
  });

  $("btnCreateCat")?.addEventListener("click", async () => {
    const name = $("newCatName").value.trim();
    if (!name) return;
    try {
      await api("/api/categories", { method: "POST", body: JSON.stringify({ name }) });
      $("newCatName").value = "";
      await fillKbSelects();
      await refreshKbCatList();
    } catch (e) {
      alert(e.message);
    }
  });

  $("uploadFiles")?.addEventListener("change", function () {
    const inp = this;
    const files = inp.files ? Array.from(inp.files) : [];
    if (!files.length) return;
    inp.value = "";
    void runKbFileUploads(files);
  });

  $("btnIndexSave")?.addEventListener("click", async () => {
    try {
      await api("/api/index/save", { method: "POST", body: "{}" });
      showToast("索引已保存", "ok");
    } catch (e) {
      showToast(e.message, "err");
    }
  });

  $("btnIndexReload")?.addEventListener("click", async () => {
    try {
      await api("/api/index/reload", { method: "POST", body: "{}" });
      showToast("已从磁盘重新加载向量库", "ok");
      await pingStatus();
    } catch (e) {
      showToast(e.message, "err");
    }
  });

  $("btnClearAll")?.addEventListener("click", async () => {
    if (!$("clearAllConfirm").checked) {
      alert("请勾选确认");
      return;
    }
    if (!confirm("确定清空全部知识库？不可恢复。")) return;
    try {
      await api("/api/admin/clear-all-knowledge", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      $("clearAllConfirm").checked = false;
      showToast("知识库已清空", "ok");
      await fillKbSelects();
      await refreshKbDocs();
      await pingStatus();
    } catch (e) {
      showToast(e.message, "err");
    }
  });

  $("btnEditDocSave")?.addEventListener("click", async () => {
    const file_name = $("editDocName").value;
    try {
      await api("/api/documents/metadata", {
        method: "PATCH",
        body: JSON.stringify({
          file_name,
          category: $("editDocCat").value,
          description: $("editDocDesc").value,
        }),
      });
      $("dlgEditDoc").close();
      await refreshKbDocs();
    } catch (e) {
      alert(e.message);
    }
  });

  $("btnCfgSave")?.addEventListener("click", async () => {
    try {
      await api("/api/config/save", {
        method: "POST",
        body: JSON.stringify({
          preset: $("presetSelect").value,
          base_url: $("cfgBaseUrl").value,
          api_key: $("cfgApiKey").value,
          model: $("cfgModel").value,
          provider: $("cfgProvider").value,
        }),
      });
      showToast("模型配置已保存", "ok");
      await loadCfgDetail();
    } catch (e) {
      showToast(e.message, "err");
    }
  });

  $("btnPresetAdd")?.addEventListener("click", async () => {
    const name = (window.prompt("请输入新预设名称（如「硅基流动」）") || "").trim();
    if (!name) return;
    try {
      await api("/api/config/save", {
        method: "POST",
        body: JSON.stringify({ preset: name, base_url: "", api_key: "", model: "", provider: "custom" }),
      });
      showToast(`已新增预设「${name}」`, "ok");
      await loadPresets();
      const sel = $("presetSelect");
      if (sel && [...sel.options].some((o) => o.value === name)) sel.value = name;
      await loadCfgDetail();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });

  $("btnPresetDelete")?.addEventListener("click", async () => {
    const sel = $("presetSelect");
    const name = sel?.value;
    if (!name) return;
    if (!window.confirm(`确定删除预设「${name}」吗？`)) return;
    try {
      await api("/api/config/delete?preset=" + encodeURIComponent(name), { method: "DELETE" });
      showToast(`已删除预设「${name}」`, "ok");
      await loadPresets();
      await loadCfgDetail();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });

  $("btnCfgTest")?.addEventListener("click", async () => {
    $("cfgTestLog").hidden = false;
    const key = $("cfgApiKey").value.trim();
    if (!key) {
      $("cfgTestLog").textContent = "请填写 API Key 后再测试（与 Streamlit「测试连接」一致）。";
      return;
    }
    $("cfgTestLog").textContent = "测试中…";
    try {
      const r = await api("/api/config/test", {
        method: "POST",
        body: JSON.stringify({
          base_url: $("cfgBaseUrl").value,
          api_key: key,
          model: $("cfgModel").value,
        }),
      });
      $("cfgTestLog").textContent = "成功 · 回复预览：\n" + (r.reply_preview || "");
    } catch (e) {
      $("cfgTestLog").textContent = "失败：\n" + e.message;
    }
  });

  function fillDatalist(id, items) {
    const dl = $(id);
    if (!dl) return;
    dl.innerHTML = "";
    (items || []).forEach((it) => {
      const o = document.createElement("option");
      o.value = it;
      dl.appendChild(o);
    });
  }

  async function fetchModels(msgEl) {
    const baseUrl = ($("sfBaseUrl")?.value || "").trim();
    const key = ($("sfKey")?.value || "").trim();
    if (!baseUrl) {
      if (msgEl) {
        msgEl.hidden = false;
        msgEl.textContent = "请先填写 Base URL";
      }
      showToast("请先填写 Base URL", "err");
      return;
    }
    if (msgEl) {
      msgEl.hidden = false;
      msgEl.textContent = "获取模型列表中…";
    }
    try {
      const d = await api("/api/admin/models/fetch", {
        method: "POST",
        body: JSON.stringify({ base_url: baseUrl, api_key: key }),
      });
      fillDatalist("cfgModelList", d.chat || []);
      fillModelSelect("sfEmbedModel", $("sfEmbedModel")?.value || "", d.embedding || []);
      fillModelSelect("sfRerankModel", $("sfRerankModel")?.value || "", d.rerank || []);
      const c = (d.chat || []).length;
      const e = (d.embedding || []).length;
      const r = (d.rerank || []).length;
      if (msgEl) msgEl.textContent = `已获取 ${d.total || 0} 个模型（chat ${c} / embedding ${e} / rerank ${r}）`;
      showToast("模型列表已更新", "ok");
    } catch (e2) {
      if (msgEl) msgEl.textContent = e2.message || String(e2);
      showToast(e2.message || String(e2), "err");
    }
  }

  $("btnFetchModels")?.addEventListener("click", () => fetchModels($("sfMsg")));
  $("btnFetchLlmModels")?.addEventListener("click", () => fetchModels($("cfgTestLog")));
  $("sfEmbedProvider")?.addEventListener("change", syncSfConnectionFields);
  $("sfRerankProvider")?.addEventListener("change", syncSfConnectionFields);

  $("btnProviderAdd")?.addEventListener("click", async () => {
    const name = (window.prompt("Provider 唯一标识（英文，如 openai / jina）") || "").trim().toLowerCase();
    if (!name) return;
    const label = (window.prompt("显示名（可留空，默认用标识）") || "").trim() || name;
    const type = window.confirm("是否为「本地模型」provider？\n（确定 = 本地；取消 = OpenAI 兼容 API）") ? "local" : "openai";
    const baseUrl = (window.prompt("Base URL（本地可留空）") || "").trim();
    const apiKey = (window.prompt("API Key（可留空）") || "").trim();
    try {
      await api("/api/admin/vector-providers", {
        method: "POST",
        body: JSON.stringify({ name, label, type, base_url: baseUrl, api_key: apiKey }),
      });
      showToast(`已新增 provider「${label}」`, "ok");
      await loadSettingsModelConfig();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });

  $("btnSaveEmbedRerank")?.addEventListener("click", async () => {
    const msg = $("sfMsg");
    const body = {
      embedding_provider: $("sfEmbedProvider")?.value || "local",
      embedding_model: $("sfEmbedModel")?.value || "",
      rerank_provider: $("sfRerankProvider")?.value || "local",
      rerank_model: $("sfRerankModel")?.value || "",
    };
    try {
      // 若填写了新密钥/URL，同步更新当前 provider 的连接配置
      const keyV = ($("sfKey")?.value || "").trim();
      const urlV = ($("sfBaseUrl")?.value || "").trim();
      const curName = $("sfEmbedProvider")?.value || "";
      const cur = _vectorProviders.find((p) => p.name === curName);
      if (cur && cur.type !== "local" && (keyV || urlV)) {
        await api("/api/admin/vector-providers/" + encodeURIComponent(curName), {
          method: "PUT",
          body: JSON.stringify({ name: curName, base_url: urlV, api_key: keyV }),
        });
      }
      await api("/api/admin/settings/advanced", { method: "PUT", body: JSON.stringify(body) });
      if (msg) {
        msg.hidden = false;
        msg.textContent = "已保存";
      }
      showToast("向量模型配置已保存", "ok");
      await loadSettingsModelConfig();
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  $("profileAvatarFile")?.addEventListener("change", async function () {
    const f = this.files && this.files[0];
    if (!f) return;
    if (!/^image\//.test(f.type)) {
      alert("请选择图片文件");
      return;
    }
    try {
      pendingAvatarDataUrl = await compressImageFile(f, 256, 0.88);
      pendingAvatarClear = false;
      const pimg = $("profileAvatarImg");
      const pph = $("profileAvatarPh");
      if (pimg) {
        pimg.src = pendingAvatarDataUrl;
        pimg.hidden = false;
      }
      if (pph) pph.hidden = true;
    } catch (e) {
      alert(e.message || String(e));
    }
    this.value = "";
  });

  $("btnProfileClearAvatar")?.addEventListener("click", function () {
    pendingAvatarClear = true;
    pendingAvatarDataUrl = undefined;
    const pimg = $("profileAvatarImg");
    const pph = $("profileAvatarPh");
    if (pimg) {
      pimg.removeAttribute("src");
      pimg.hidden = true;
    }
    if (pph) pph.hidden = false;
  });

  $("btnProfileSave")?.addEventListener("click", async () => {
    const pm = $("profileMsg");
    const nick = ($("profileNickname")?.value || "").trim();
    if (!nick) {
      if (pm) {
        pm.hidden = false;
        pm.textContent = "昵称不能为空";
      }
      return;
    }
    const patch = { nickname: nick };
    if (pendingAvatarClear) patch.avatar = null;
    else if (typeof pendingAvatarDataUrl === "string") patch.avatar = pendingAvatarDataUrl;
    try {
      const u = await api("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      currentUser = u;
      pendingAvatarClear = false;
      pendingAvatarDataUrl = undefined;
      applyUserHeader();
      applyModelTabPermissions();
      if (pm) {
        pm.hidden = false;
        pm.textContent = "已保存";
      }
      showToast("账户信息已更新", "ok");
    } catch (e) {
      if (pm) {
        pm.hidden = false;
        pm.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  $("btnProfileDeleteAccount")?.addEventListener("click", async () => {
    const u = currentUser;
    if (!u || !u.username) return;
    if (
      !confirm(
        "注销后将永久删除账号及服务器上的个人数据（知识库、同步状态等），不可恢复。确定继续？"
      )
    )
      return;
    const pwd = prompt("请输入当前登录密码：");
    if (!pwd) return;
    const typed = prompt("请输入登录用户名「" + u.username + "」以最终确认：", "");
    if (typed == null || typed.trim() !== u.username) {
      alert("用户名输入不一致");
      return;
    }
    try {
      await api("/api/auth/delete-account", {
        method: "POST",
        body: JSON.stringify({ password: pwd, confirm_text: typed.trim() }),
      });
      clearAuth();
      window.location.href = LOGIN_PAGE;
    } catch (e) {
      alert(e.message || String(e));
    }
  });

  $("btnAdminSaveAdvanced")?.addEventListener("click", async () => {
    const msg = $("adminAdvMsg");
    try {
      const body = {
        rag_defaults: {
          default_retrieval_k: parseInt(String($("advRagK")?.value || "10"), 10) || 10,
          default_search_mode: $("advSearchMode")?.value || "vector",
          default_enable_reranker: !!$("advRerank")?.checked,
          default_response_style: $("advRespStyle")?.value || "balanced",
          default_temperature: parseFloat(String($("advTemp")?.value || "0")) || 0,
        },
        chunk_levels: {
          small: {
            chunk_size: parseInt(String($("advCsSmall")?.value || "300"), 10),
            chunk_overlap: parseInt(String($("advCoSmall")?.value || "50"), 10),
          },
          medium: {
            chunk_size: parseInt(String($("advCsMed")?.value || "800"), 10),
            chunk_overlap: parseInt(String($("advCoMed")?.value || "100"), 10),
          },
          large: {
            chunk_size: parseInt(String($("advCsLarge")?.value || "2000"), 10),
            chunk_overlap: parseInt(String($("advCoLarge")?.value || "200"), 10),
          },
        },
        system_prompt_extra: ($("advSysExtra")?.value || "").slice(0, 12000),
        embedding_model_note: ($("advEmbedNote")?.value || "").slice(0,500),
        web_search_provider: $("advWebSearchProvider")?.value || "bocha",
      };
      const bochaV = ($("advBochaKey")?.value || "").trim();
      const braveV = ($("advBraveKey")?.value || "").trim();
      const qfV = ($("advQianfanKey")?.value || "").trim();
      if (bochaV) body.bocha_api_key = bochaV;
      if (braveV) body.brave_api_key_server = braveV;
      if (qfV) body.qianfan_api_key = qfV;
      await api("/api/admin/settings/advanced", { method: "PUT", body: JSON.stringify(body) });
      if (msg) {
        msg.hidden = false;
        msg.textContent = "已保存";
      }
      showToast("高级参数已保存", "ok");
      try {
        localStorage.removeItem(RAG_DEFAULTS_SIG_KEY);
      } catch (_) {}
      await mergePublicRagPrefsFromServer();
      applyChatPrefsToForm();
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  $("btnVecRefresh")?.addEventListener("click", () => {
    loadAdminVectorTable().catch((e) => showToast(e.message || String(e), "err"));
  });

  $("btnVecResetFaiss")?.addEventListener("click", async () => {
    const uid = parseInt(String($("vecUserId")?.value || ""), 10);
    const msg = $("adminVecMsg");
    if (!uid || uid < 1) {
      showToast("请填写有效用户 ID", "err");
      return;
    }
    if (!confirm("确认清空用户 " + uid + " 的 FAISS 索引？需重新上传文档才能检索。")) return;
    try {
      await api("/api/admin/vector/reset-faiss", {
        method: "POST",
        body: JSON.stringify({ user_id: uid }),
      });
      showToast("已重置 FAISS", "ok");
      await loadAdminVectorTable();
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  $("btnVecDelBm25")?.addEventListener("click", async () => {
    const uid = parseInt(String($("vecUserId")?.value || ""), 10);
    const msg = $("adminVecMsg");
    if (!uid || uid < 1) {
      showToast("请填写有效用户 ID", "err");
      return;
    }
    if (!confirm("确认删除用户 " + uid + " 的 BM25 索引文件？")) return;
    try {
      await api("/api/admin/vector/delete-bm25", {
        method: "POST",
        body: JSON.stringify({ user_id: uid }),
      });
      showToast("已删除 BM25 文件", "ok");
      await loadAdminVectorTable();
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  bindChatPrefsFromFormListeners();
  wireThreadInlineCiteDelegation();
  wireThreadScrollJumpUi();
  wireChatKbCustomDropdown();
  syncChatKbDropdownFromSelect();

  async function loadAdminVectorTable() {
    const wrap = $("adminVecTableWrap");
    const msg = $("adminVecMsg");
    if (msg) {
      msg.hidden = true;
      msg.textContent = "";
    }
    if (!wrap) return;
    try {
      const data = await api("/api/admin/vector/summary");
      const users = data.users || [];
      if (!users.length) {
        wrap.innerHTML = "<p class=\"gpt-muted\">暂无用户数据</p>";
        return;
      }
      const rows = users
        .map(function (u) {
          const mb = (u.faiss_bytes / (1024 * 1024)).toFixed(2);
          return (
            "<tr><td>" +
            escapeHtml(String(u.user_id)) +
            "</td><td>" +
            escapeHtml(String(u.doc_count)) +
            "</td><td>" +
            escapeHtml(String(u.total_chunks)) +
            "</td><td>" +
            escapeHtml(mb) +
            " MB</td><td>" +
            (u.bm25_index_exists ? "有" : "无") +
            '</td><td class="gpt-audit-path" title="' +
            escapeHtml(u.kb_path || "") +
            '">' +
            escapeHtml((u.kb_path || "").slice(0, 48)) +
            "</td></tr>"
          );
        })
        .join("");
      wrap.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>用户ID</th><th>文档数</th><th>块数</th><th>FAISS</th><th>BM25</th><th>路径</th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
      await loadAdminFaiRegTable().catch(function (e) {
        console.error(e);
      });
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
    }
  }

  async function loadAdminFaiRegTable() {
    var wrap = $("adminFaiRegWrap");
    if (!wrap) return;
    try {
      var data = await api("/api/admin/faiss-registry");
      var items = data.items || [];
      if (!items.length) {
        wrap.innerHTML = "<p class=\"gpt-muted\">暂无登记记录（表 faiss_index_registry 为空或未同步）。</p>";
        return;
      }
      var rows = items
        .map(function (it) {
          var noteEsc = escapeHtml(String(it.notes || ""));
          return (
            "<tr><td>" +
            escapeHtml(String(it.id)) +
            "</td><td>" +
            escapeHtml(String(it.user_id)) +
            "</td><td>" +
            escapeHtml(String(it.username || "—")) +
            "</td><td>" +
            escapeHtml(String(it.storage_key || "")) +
            "</td><td>" +
            escapeHtml(String(it.index_kind || "")) +
            "</td><td>" +
            escapeHtml(String(it.vector_count)) +
            "</td><td>" +
            escapeHtml(String(it.status || "")) +
            "</td><td><input type=\"text\" class=\"gpt-input\" style=\"min-width:10rem;max-width:16rem\" data-faiss-note-inp=\"" +
            escapeHtml(String(it.id)) +
            '" value="' +
            noteEsc +
            "\" /></td><td><button type=\"button\" class=\"gpt-btn-sm\" data-faiss-note-save=\"" +
            escapeHtml(String(it.id)) +
            '">保存备注</button></td></tr>'
          );
        })
        .join("");
      wrap.innerHTML =
        '<table class="gpt-audit-table"><thead><tr><th>ID</th><th>用户</th><th>账号</th><th>storage_key</th><th>类型</th><th>向量数</th><th>状态</th><th>备注</th><th></th></tr></thead><tbody>' +
        rows +
        "</tbody></table>";
    } catch (e) {
      wrap.innerHTML =
        "<p class=\"gpt-log err\" style=\"display:block\">" + escapeHtml(e.message || String(e)) + "</p>";
    }
  }

  document.body.addEventListener(
    "click",
    async function (ev) {
      if (PAGE !== "admin-vector") return;
      var btn = ev.target && ev.target.closest && ev.target.closest("[data-faiss-note-save]");
      if (!btn) return;
      var id = btn.getAttribute("data-faiss-note-save");
      if (!id) return;
      var inp = document.querySelector('[data-faiss-note-inp="' + id.replace(/"/g, "") + '"]');
      var notes = inp ? String(inp.value || "") : "";
      try {
        await api("/api/admin/faiss-registry/" + id, {
          method: "PATCH",
          body: JSON.stringify({ notes: notes }),
        });
        showToast("备注已保存", "ok");
      } catch (e) {
        showToast(e.message || String(e), "err");
      }
    },
    false,
  );

  $("btnAdminSaveSettings")?.addEventListener("click", async () => {
    const msg = $("adminSysMsg");
    const exts = ($("admExts").value || "")
      .split(/[,，\s]+/)
      .map((x) => x.trim().replace(/^\./, ""))
      .filter(Boolean);
    try {
      const reg = $("admRegEnabled");
      const guest = $("admGuestEnabled");
      const maint = $("admMaintenanceEnabled");
      const maxMb = $("admMaxMb");
      const maxDocs = $("admMaxDocs");
      const qpm = $("admRateLimitQpm");
      const capEl = $("admStorageCapMb");
      const pumEl = $("admPerUserMaxMb");
      const swEl = $("admSensitiveWords");
      const cadEl = $("admComplianceAuto");
      const payload = {
        registration_enabled: !!(reg && reg.checked),
        guest_mode_enabled: !!(guest && guest.checked),
        maintenance_mode_enabled: !!(maint && maint.checked),
        rate_limit_qpm_per_user: parseInt(String(qpm ? qpm.value : "60"), 10) || 60,
        max_upload_mb: parseInt(String(maxMb ? maxMb.value : "50"), 10) || 50,
        max_docs_per_user: parseInt(String(maxDocs ? maxDocs.value : "500"), 10) || 500,
        allowed_extensions: exts.length ? exts : undefined,
      };
      if (capEl)
        payload.per_user_storage_mb = Math.max(0, parseInt(String(capEl.value || "0"), 10) || 0);
      if (pumEl)
        payload.per_user_max_upload_mb = Math.max(0, parseInt(String(pumEl.value || "0"), 10) || 0);
      if (swEl) payload.sensitive_words = String(swEl.value || "");
      if (cadEl) payload.compliance_auto_disable = !!cadEl.checked;
      const bfe = $("admBruteforceEnabled");
      const bfw = $("admBruteforceWindowMin");
      const bfi = $("admBruteforceMaxIp");
      const bfu = $("admBruteforceMaxUser");
      if (bfe) payload.login_bruteforce_enabled = !!bfe.checked;
      if (bfw)
        payload.login_bruteforce_window_minutes = Math.max(
          1,
          parseInt(String(bfw.value || "15"), 10) || 15
        );
      if (bfi)
        payload.login_bruteforce_max_per_ip = Math.max(
          1,
          parseInt(String(bfi.value || "40"), 10) || 40
        );
      if (bfu)
        payload.login_bruteforce_max_per_username = Math.max(
          1,
          parseInt(String(bfu.value || "12"), 10) || 12
        );
      const arw = $("admRagWebSearchUi");
      const aiw = $("admInstantWebSearchUi");
      if (arw) payload.rag_show_web_search_ui = !!arw.checked;
      if (aiw) payload.instant_show_web_search_ui = !!aiw.checked;
      await api("/api/admin/settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      if (msg) {
        msg.hidden = false;
        msg.textContent = "已保存";
      }
      showToast("系统策略已保存", "ok");
      await refreshPublicUploadUi();
    } catch (e) {
      if (msg) {
        msg.hidden = false;
        msg.textContent = e.message || String(e);
      }
      showToast(e.message || String(e), "err");
    }
  });

  $("btnAdminRefreshAudit")?.addEventListener("click", () => {
    loadAdminAudit()
      .then(() => showToast("审计列表已刷新", "ok"))
      .catch((e) => showToast(e.message, "err"));
  });

  $("btnUserFeedbackSubmit")?.addEventListener("click", async () => {
    const msg = $("userFeedbackMsg");
    const titleEl = $("userFeedbackTitle");
    const contentEl = $("userFeedbackContent");
    const contactEl = $("userFeedbackContact");
    const content = contentEl ? String(contentEl.value || "").trim() : "";
    if (content.length < 4) {
      showToast("反馈内容至少 4 个字符", "err");
      return;
    }
    try {
      await api("/api/public/feedback", {
        method: "POST",
        body: JSON.stringify({
          title: titleEl ? String(titleEl.value || "").trim() : "",
          content: content,
          contact: contactEl ? String(contactEl.value || "").trim() || null : null,
        }),
      });
      if (contentEl) contentEl.value = "";
      if (titleEl) titleEl.value = "";
      if (msg) {
        msg.hidden = false;
        msg.textContent = "已提交";
      }
      showToast("已提交，感谢反馈", "ok");
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });

  $("btnAdminRefreshAllLogs")?.addEventListener("click", () => {
    Promise.all([
      loadAdminPlatformAudit(),
      loadAdminLoginAudit(),
      loadAdminLoginFailures(),
      loadAdminAudit(),
    ])
      .then(() => showToast("日志已刷新", "ok"))
      .catch((e) => showToast(e.message || String(e), "err"));
  });

  $("btnAdminFeedbackRefresh")?.addEventListener("click", () => {
    loadAdminFeedback()
      .then(() => showToast("已刷新", "ok"))
      .catch((e) => showToast(e.message || String(e), "err"));
  });

  $("admFeedbackStatus")?.addEventListener("change", () => {
    loadAdminFeedback().catch((e) => console.error(e));
  });

  $("adminFeedbackBody")?.addEventListener("click", async function (ev) {
    const t = ev.target;
    if (!t || !t.getAttribute) return;
    const fid = t.getAttribute("data-fid");
    const act = t.getAttribute("data-fb-act");
    if (!fid || !act) return;
    try {
      if (act === "reply") {
        const text = window.prompt("管理员回复（将写入数据库）", "");
        if (text == null) return;
        await api("/api/admin/feedback/" + encodeURIComponent(fid), {
          method: "PATCH",
          body: JSON.stringify({ admin_reply: text }),
        });
      } else {
        await api("/api/admin/feedback/" + encodeURIComponent(fid), {
          method: "PATCH",
          body: JSON.stringify({ status: act }),
        });
      }
      showToast("已更新", "ok");
      await loadAdminFeedback();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });

  $("btnAdmUserSearch")?.addEventListener("click", () => {
    loadAdminUsers().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("admUserSearch")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    loadAdminUsers().catch((err) => showToast(err.message || String(err), "err"));
  });
  $("btnAdmUserSearchReset")?.addEventListener("click", () => {
    if ($("admUserSearch")) $("admUserSearch").value = "";
    loadAdminUsers().catch((e) => showToast(e.message || String(e), "err"));
  });

  $("btnAdmCreateUser")?.addEventListener("click", async () => {
    const un = ($("admNewUserName")?.value || "").trim();
    const pw = ($("admNewUserPwd")?.value || "").trim();
    const role = ($("admNewUserRole")?.value || "user").trim();
    if (!un || !pw) {
      alert("请填写用户名与密码");
      return;
    }
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ username: un, password: pw, role }),
      });
      if ($("admNewUserName")) $("admNewUserName").value = "";
      if ($("admNewUserPwd")) $("admNewUserPwd").value = "";
      showToast("用户已创建", "ok");
      await loadAdminUsers();
      await fillAdminUserFilter();
    } catch (e) {
      alert(e.message || String(e));
    }
  });

  $("btnAdmDocRefresh")?.addEventListener("click", () => {
    loadAdminDocs().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("admDocUserFilter")?.addEventListener("change", () => {
    loadAdminDocs().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("admDocStatusFilter")?.addEventListener("change", () => {
    loadAdminDocs().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdmDocPurge")?.addEventListener("click", async () => {
    const uid = ($("admDocUserFilter")?.value || "").trim();
    if (!confirm("确认清空当前筛选范围的回收站文档？")) return;
    let url = "/api/admin/documents/purge";
    if (uid) url += "?user_id=" + encodeURIComponent(uid);
    try {
      const r = await api(url, { method: "POST" });
      showToast("已清空 " + (r.removed || 0) + " 条", "ok");
      await loadAdminDocs();
    } catch (e) {
      showToast(e.message || String(e), "err");
    }
  });
  $("btnAdmLogRefresh")?.addEventListener("click", () => {
    loadAdminLogs().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("adminPromptSlug")?.addEventListener("change", () => {
    loadAdminPromptDetail().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdminPromptReload")?.addEventListener("click", () => {
    loadAdminPromptTemplatesPage().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdminPromptSave")?.addEventListener("click", () => {
    saveAdminPromptTemplate().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdminLlmMysqlRefresh")?.addEventListener("click", () => {
    loadAdminLlmMysqlLogs().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdminMysqlCountsRefresh")?.addEventListener("click", () => {
    loadAdminMysqlTableCounts().catch((e) => showToast(e.message || String(e), "err"));
  });
  $("btnAdminAnalyticsRefresh")?.addEventListener("click", () => {
    loadAdminAnalytics()
      .then(() => showToast("数据已刷新", "ok"))
      .catch((e) => showToast(e.message || String(e), "err"));
  });
  $("admAnalyticsTrendDays")?.addEventListener("change", () => {
    loadAdminAnalytics().catch((e) => showToast(e.message || String(e), "err"));
  });

  async function boot() {
    if (!getAuthToken()) {
      window.location.href = LOGIN_PAGE + "?next=" + encodeURIComponent(location.pathname || "/");
      return;
    }
    wireKbUploadSwMessageOnce();
    if (PAGE === "kb") void getKbUploadSwIfReady();
    initTheme();
    wireCloseDialogs();
    const kbRoot = $("kbPageRoot");
    if (kbRoot) wireTabs(kbRoot);
    const stRoot = $("settingsPageRoot");
    if (stRoot && stRoot.querySelector(".gpt-tabs")) wireTabs(stRoot);
    if (stRoot && stRoot.querySelector(".gpt-subtabs")) wireSubTabs(stRoot);
    const consoleRoot = $("consolePageRoot");
    if (consoleRoot) wireTabs(consoleRoot);
    const adminDocsRoot = $("adminDocsPageRoot");
    if (adminDocsRoot && adminDocsRoot.querySelector(".gpt-tabs")) wireTabs(adminDocsRoot);
    wireUserMenu();
    wireHistoryToggle();
    wireConvMenu();
    initSidebarConvListMenusOnce();
    const side = $("gptSidebar");
    if (side && isMobileSidebarLayout()) {
      side.classList.add("collapsed");
    } else if (side && !isMobileSidebarLayout() && sidebarHasRailChrome()) {
      if (localStorage.getItem("rag_chat_sidebar_collapsed") === "1") {
        localStorage.setItem("rag_chat_sidebar_rail", "1");
        localStorage.removeItem("rag_chat_sidebar_collapsed");
      }
      if (localStorage.getItem("rag_chat_sidebar_rail") === "1") {
        side.classList.add("rail");
      }
    }
    if (side && isSidebarSubpageLayout()) {
      side.classList.remove("rail");
    }
    initSidebarToggle();
    syncBackdropToSidebar();
    const sip = $("sysIndexPath");
    if (sip) sip.textContent = "data/web/users/<用户ID>/knowledge_db/";
    const rk = $("retrievalK");
    const rkv = $("retrievalKVal");
    if (rk && rkv) rkv.textContent = rk.value;
    updateTempHint();
    const params = new URLSearchParams(location.search);
    if (kbRoot) activateTabInRoot(kbRoot, params.get("tab") || "kb-docs");
    if (stRoot && stRoot.querySelector(".gpt-tabs")) {
      if (PORTAL === "admin" && PAGE === "admin-settings") {
        stRoot.querySelector('.gpt-tab[data-tab="set-rag"]')?.remove();
        stRoot.querySelector("#panel-set-rag")?.remove();
        let settingsTab = params.get("tab") || "set-model";
        if (settingsTab === "set-rag") settingsTab = "set-model";
        activateTabInRoot(stRoot, settingsTab);
        syncAdminSettingsNavAriaCurrent(settingsTab);
      } else {
        const settingsTab = params.get("tab") || "set-rag";
        activateTabInRoot(stRoot, settingsTab);
        syncAdminSettingsNavAriaCurrent(settingsTab);
      }
    }
    try {
      const me = await api("/api/auth/me");
      currentUser = me;
      if (PORTAL === "admin" && !me.is_admin) {
        window.location.replace("/");
        return;
      }
      applyUserHeader();
      store = loadStoreForCurrentUser();
      await pullWebUiStateAndApply();
      await mergePublicRagPrefsFromServer();
      if (PAGE === "chat" || PAGE === "instant") {
        repairOrphanAssistantMessagesInStore();
        renderConvList();
        renderThread();
        updateEmptyState();
        updateTopbar();
        syncInstantDocBar();
        initThreadActionBar();
      }
      applyModelTabPermissions();
      await refreshPublicUploadUi();
      await fillKbSelects();
      if ($("personasList") && $("btnPersonaAdd")) {
        wirePersonasEditor();
        fillActivePersonaSelectOptions();
        renderPersonasList();
      }
      applyChatPrefsToForm();
      await loadPresets();
      applyChatPrefsToForm();
      if ($("searchMode")) await refreshBm25Hint();
      await pingStatus();
      if ($("cfgBaseUrl")) await loadCfgDetail();
      if ($("sfEmbedProvider")) await loadSettingsModelConfig().catch((e) => console.error(e));
      if (PAGE === "kb") {
        await Promise.all([refreshKbDocs().catch(() => {}), refreshKbCatList().catch(() => {})]);
      }
      if (PAGE === "admin-monitor") {
        await Promise.all([
          loadAdminTokenStats().catch((e) => console.error(e)),
          loadAdminLogs().catch((e) => console.error(e)),
        ]);
      }
      if (PAGE === "admin-logs") {
        await Promise.all([
          loadAdminPlatformAudit().catch((e) => console.error(e)),
          loadAdminLoginAudit().catch((e) => console.error(e)),
          loadAdminLoginFailures().catch((e) => console.error(e)),
          loadAdminAudit().catch((e) => console.error(e)),
        ]);
      }
      if (PAGE === "admin-feedback") {
        await loadAdminFeedback().catch((e) => console.error(e));
      }
      if (PAGE === "admin-analytics") {
        await loadAdminAnalytics().catch((e) => console.error(e));
      }
      if (PAGE === "admin-users") {
        wireAdminUsersActions();
        await loadAdminUsers().catch((e) => console.error(e));
      }
      if (PAGE === "admin-docs") {
        wireAdminKbCatalogActions();
        wireAdminDocsActions();
        $("btnAdmKbCatalogRefresh")?.addEventListener("click", () => {
          loadAdminKbCatalog().catch((e) => showToast(e.message || String(e), "err"));
        });
        await fillAdminUserFilter().catch((e) => console.error(e));
        await Promise.all([
          loadAdminKbCatalog().catch((e) => console.error(e)),
          loadAdminDocs().catch((e) => console.error(e)),
        ]);
      }
      if (PAGE === "admin-trash") {
        wireAdminDocsActions();
        await fillAdminUserFilter().catch((e) => console.error(e));
        await loadAdminDocs().catch((e) => console.error(e));
      }
      if (PAGE === "admin-flags") {
        await loadAdminSettingsForm().catch((e) => console.error(e));
      }
      if (PAGE === "admin-advanced") {
        await loadAdminAdvancedForm().catch((e) => console.error(e));
      }
      if (PAGE === "admin-vector") {
        await loadAdminVectorTable().catch((e) => console.error(e));
      }
      if (PAGE === "admin-prompts") {
        await loadAdminPromptTemplatesPage().catch((e) => console.error(e));
      }
      if (PAGE === "admin-llm-mysql-logs") {
        await Promise.all([
          loadAdminMysqlTableCounts().catch((e) => console.error(e)),
          loadAdminLlmMysqlLogs().catch((e) => console.error(e)),
        ]);
      }
    } catch {
      currentUser = null;
      const st = $("status");
      if (st) {
        st.textContent = "无法连接后端";
        st.classList.add("err");
      }
    }
  }

  window.addEventListener("pagehide", function () {
    stopAllSpeech();
    if (PAGE !== "chat" && PAGE !== "instant") return;
    if (!chatStreamController) return;
    try {
      if (__streamSaveTimer) {
        clearTimeout(__streamSaveTimer);
        __streamSaveTimer = null;
      }
      const conv = currentConv();
      const msgs = conv && conv.messages;
      const last = msgs && msgs[msgs.length - 1];
      if (last && last.role === "assistant") {
        if (!String(last.content || "").trim()) {
          last.content =
            "（已离开页面，生成未完成。请在本条下使用「重试」，或重新发送问题。）";
          last.meta = (last.meta || "").trim() ? last.meta + " · 已中断" : "已中断";
          if (last.latencyMs == null) last.latencyMs = 0;
        } else {
          last.meta = (last.meta || "").trim() ? last.meta + " · 离开页面时未写完" : "离开页面时未写完";
        }
        conv.updatedAt = Date.now();
        localStorage.setItem(getConversationStorageKey(), JSON.stringify(store));
      }
      void flushPushWebUiState();
    } catch (_) {}
    abortActiveChatStream();
  });
  window.addEventListener("pageshow", function (ev) {
    if (!ev.persisted) return;
    if (PAGE !== "chat" && PAGE !== "instant") return;
    chatStreamController = null;
    setComposerSendStreaming(false);
    repairOrphanAssistantMessagesInStore();
    if ($("thread") && currentConv()) {
      renderThread();
      updateEmptyState();
      updateTopbar();
      syncInstantDocBar();
    }
  });
  window.addEventListener("beforeunload", stopAllSpeech);
  initLatencyPopover();

  boot();
})();
