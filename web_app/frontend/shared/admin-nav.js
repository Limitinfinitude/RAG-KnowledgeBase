/**
 * 管理端侧栏菜单：各页 body 设 data-admin-nav 与下方 id 之一对应。
 */
(function (global) {
  var ITEMS = [
    {
      id: "hub",
      href: "/admin/hub.html",
      label: "调控中心",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    },
    {
      id: "users",
      href: "/admin/users.html",
      label: "用户管理",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    },
    {
      id: "docs",
      href: "/admin/docs.html",
      label: "知识库与文档",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    },
    {
      id: "trash",
      href: "/admin/trash.html",
      label: "文档回收站",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    },
    {
      id: "analytics",
      href: "/admin/analytics.html",
      label: "统计与运营",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 16V8"/><path d="M12 16v-5"/><path d="M17 16V4"/></svg>',
    },
    {
      id: "monitor",
      href: "/admin/monitor.html",
      label: "监控台",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>',
    },
    {
      id: "logs",
      href: "/admin/logs.html",
      label: "操作日志",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>',
    },
    {
      id: "feedback",
      href: "/admin/feedback.html",
      label: "用户反馈",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    },
    {
      id: "quality",
      href: "/admin/quality.html",
      label: "好差评流水",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>',
    },
    {
      id: "flags",
      href: "/admin/flags.html",
      label: "功能开关",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>',
    },
    {
      id: "advanced",
      href: "/admin/advanced.html",
      label: "高级参数",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/><path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/></svg>',
    },
    {
      id: "prompts",
      href: "/admin/prompts.html",
      label: "提示词模板",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
    },
    {
      id: "llm-mysql-logs",
      href: "/admin/llm-mysql-logs.html",
      label: "LLM 调用(MySQL)",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
    },
    {
      id: "vector",
      href: "/admin/vector.html",
      label: "向量维护",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/></svg>',
    },
    {
      id: "settings",
      href: "/admin/settings.html?tab=set-model",
      label: "模型配置",
      svg:
        '<svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
    },
  ];

  function mountAdminNav(activeId) {
    var nav = document.getElementById("adminNavMount");
    if (!nav) return;
    var sid = String(activeId || "").trim();
    var html = ITEMS.map(function (it) {
      var cur = sid && it.id === sid ? ' aria-current="page"' : "";
      return (
        '<a href="' +
        it.href +
        '" class="gpt-nav-item"' +
        cur +
        '><span class="gpt-nav-ico" aria-hidden="true">' +
        it.svg +
        '</span><span class="gpt-nav-label">' +
        it.label +
        "</span></a>"
      );
    }).join("");
    nav.innerHTML = html;
  }

  global.mountAdminNav = mountAdminNav;
})(typeof window !== "undefined" ? window : globalThis);
