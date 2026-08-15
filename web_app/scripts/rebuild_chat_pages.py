# -*- coding: utf-8 -*-
"""
Regenerate user/index.html 侧栏片段；admin/index.html 写为跳转至用户管理（无问答页）。
布局：frontend/user、frontend/admin、静态资源 frontend/shared。
在仓库根目录执行:  python web_app/scripts/rebuild_chat_pages.py
"""
from __future__ import annotations

import re
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
FRONTEND = _SCRIPTS.parent / "frontend"
USER = FRONTEND / "user"
ADMIN = FRONTEND / "admin"

# Chat page history block (must match app.js ids)
HISTORY_CHAT = """      <section class="gpt-sidebar-history" id="sidebarHistory" aria-label="\u5386\u53f2\u8bb0\u5f55">
        <button type="button" class="gpt-sidebar-history-toggle" id="btnHistoryToggle" aria-expanded="true" aria-controls="convListWrap">
          <span class="gpt-sidebar-history-toggle-label">\u5386\u53f2\u8bb0\u5f55</span>
          <span class="gpt-sidebar-history-chevron" aria-hidden="true">\u25bc</span>
        </button>
        <div class="gpt-conv-scroll-wrap" id="convListWrap">
          <div class="gpt-conv-scroll" id="convList"></div>
        </div>
      </section>"""

SETTINGS_HISTORY_RE = re.compile(
    r'<section class="gpt-sidebar-history"[^>]*>.*?</section>',
    re.DOTALL,
)

# User index: button new chat (not link)
NEWCHAT_LINK_USER = re.compile(
    r'<a href="/" class="gpt-btn-newchat"[^>]*>.*?</a>\s*',
    re.DOTALL,
)
NEWCHAT_BTN_USER = """          <button type="button" class="gpt-btn-newchat" id="btnNewConv">
            <span class="gpt-icon">\uff0b</span><span class="gpt-sidebar-btn-text">\u65b0\u5efa\u5bf9\u8bdd</span>
          </button>
"""

def extract_aside(html: str) -> str:
    m = re.search(
        r'<aside class="gpt-sidebar[^"]*" id="gptSidebar">.*?</aside>',
        html,
        re.DOTALL,
    )
    if not m:
        raise ValueError("aside not found")
    return m.group(0)


def sidebar_user_for_chat(html: str) -> str:
    s = extract_aside(html)
    s = NEWCHAT_LINK_USER.sub(NEWCHAT_BTN_USER, s, count=1)
    s = SETTINGS_HISTORY_RE.sub(HISTORY_CHAT, s, count=1)
    s = re.sub(r' aria-current="page"', "", s)
    s = s.replace(
        '<a href="/" class="gpt-nav-item">',
        '<a href="/" class="gpt-nav-item" aria-current="page">',
        1,
    )
    return s


def build_index(sidebar: str) -> str:
    title = "\u667a\u80fd\u95ee\u7b54 \u00b7 \u7528\u6237"
    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="theme-color" content="#171717" media="(prefers-color-scheme: dark)" />
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
  <title>{title}</title>
  <link rel="stylesheet" href="/static/style.css?v=20260415" />
  <script src="https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js" crossorigin="anonymous"></script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.8/dist/purify.min.js" crossorigin="anonymous"></script>
</head>
<body data-portal="user" data-page="chat" class="gpt-root-chat">
  <div class="gpt-layout">
{sidebar}

    <div class="gpt-backdrop" id="gptBackdrop" hidden aria-hidden="true"></div>

    <div class="gpt-main">
      <header class="gpt-topbar gpt-topbar--chat">
        <button type="button" class="gpt-menu-mobile gpt-sidebar-toggle-chat" id="btnSidebarToggle" aria-label="\u6253\u5f00\u4fa7\u680f\u83dc\u5355">\u2630</button>
        <div class="gpt-topbar-title gpt-topbar-title--chat">
          <span id="topbarTitle">\u667a\u80fd\u95ee\u7b54</span>
          <span class="gpt-topbar-sub" id="topbarSub"></span>
        </div>
        <div class="gpt-topbar-actions">
          <div class="gpt-conv-menu" id="convMenu">
            <button type="button" class="gpt-btn-more" id="convMenuBtn" aria-haspopup="true" aria-expanded="false" aria-label="\u5f53\u524d\u5bf9\u8bdd\u64cd\u4f5c">\u22ee</button>
            <div class="gpt-conv-dropdown" id="convDropdown" role="menu" hidden>
              <button type="button" class="gpt-dropdown-item" data-conv-action="pin" role="menuitem">\u7f6e\u9876</button>
              <button type="button" class="gpt-dropdown-item" data-conv-action="rename" role="menuitem">\u91cd\u547d\u540d</button>
              <button type="button" class="gpt-dropdown-item" data-conv-action="export" role="menuitem">\u5bfc\u51fa</button>
              <button type="button" class="gpt-dropdown-item gpt-dropdown-danger" data-conv-action="delete" role="menuitem">\u5220\u9664</button>
            </div>
          </div>
        </div>
      </header>

      <div class="gpt-thread-wrap">
        <div class="gpt-empty" id="emptyState">
          <div class="gpt-empty-orb" aria-hidden="true"></div>
          <h2>\u4eca\u5929\u6709\u4ec0\u4e48\u53ef\u4ee5\u5e2e\u4f60\u7684\uff1f</h2>
          <p class="gpt-empty-lead">\u5148\u4e0a\u4f20\u6587\u6863\uff0c\u518d\u57fa\u4e8e\u4e2a\u4eba\u77e5\u8bc6\u5e93\u63d0\u95ee\uff0c\u56de\u7b54\u4f1a\u5f15\u7528\u68c0\u7d22\u5230\u7684\u7247\u6bb5\u3002</p>
          <div class="gpt-empty-actions">
            <a href="/kb.html?tab=kb-upload" class="gpt-chip">\U0001f4e4 \u4e0a\u4f20\u6587\u6863</a>
            <a href="/kb.html" class="gpt-chip">\U0001f4da \u7ba1\u7406\u77e5\u8bc6\u5e93</a>
            <a href="/settings.html" class="gpt-chip">\u2699 \u4e2a\u6027\u5316\u8bbe\u7f6e</a>
          </div>
          <p class="gpt-empty-note">\u6570\u636e\u4fdd\u5b58\u5728\u60a8\u8d26\u53f7\u72ec\u7acb\u76ee\u5f55 <code>data/web/users/&lt;id&gt;/knowledge_db</code></p>
        </div>
        <div class="gpt-thread" id="thread" hidden></div>
      </div>

      <footer class="gpt-composer-area" id="composerArea">
        <div class="gpt-chat-rag-strip" id="chatRagStrip">
          <div class="gpt-chat-rag-row">
            <div class="gpt-rag-field gpt-rag-field-chat gpt-rag-scope-row">
              <span class="gpt-rag-inline-label" id="kbScopeLabel">\u68c0\u7d22\u8303\u56f4</span>
              <div class="gpt-rag-kb-widget">
                <button type="button" class="gpt-rag-kb-trigger" id="kbTrigger" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="kbScopeLabel kbTriggerText" aria-controls="kbListbox">
                  <span class="gpt-rag-kb-trigger-text" id="kbTriggerText">\u2014</span>
                  <span class="gpt-rag-kb-chevron" aria-hidden="true">\u25bc</span>
                </button>
                <ul class="gpt-rag-kb-menu" id="kbListbox" role="listbox" hidden></ul>
                <select id="kb" class="gpt-rag-kb-native" title="\u77e5\u8bc6\u5e93\u8303\u56f4" tabindex="-1"></select>
              </div>
            </div>
            <label class="gpt-rag-switch gpt-rag-switch-chat">
              <span class="gpt-rag-switch-text">\u6df7\u5408\u68c0\u7d22</span>
              <input type="checkbox" id="hybridToggle" />
              <span class="gpt-rag-switch-ui" aria-hidden="true"></span>
            </label>
            <input type="hidden" id="searchMode" value="vector" />
          </div>
          <p class="gpt-callout gpt-callout-compact gpt-hybrid-hint-chat" id="hybridHint" hidden></p>
        </div>
        <form class="gpt-composer" id="form">
          <textarea id="input" rows="1" placeholder="\u53d1\u9001\u6d88\u606f" required autocomplete="off"></textarea>
          <button type="submit" class="gpt-send" id="send" aria-label="\u53d1\u9001">\u2192</button>
        </form>
        <p class="gpt-hint">Enter \u53d1\u9001 \u00b7 Shift+Enter \u6362\u884c \u00b7 \u52a9\u624b\u6027\u683c\u5728\u300c\u4e2a\u6027\u5316\u8bbe\u7f6e\u300d\u3002</p>
      </footer>
    </div>
  </div>

  <div id="toastHost" class="gpt-toast-host" aria-live="polite"></div>

  <dialog class="gpt-dialog gpt-dialog-wide" id="dlgPreview">
    <div class="gpt-dlg-head">
      <h2 id="previewTitle">\u9884\u89c8</h2>
      <button type="button" class="gpt-dlg-close" data-close-dlg="dlgPreview">\u00d7</button>
    </div>
    <div class="gpt-dlg-body gpt-preview-body" id="previewBody"></div>
  </dialog>

  <dialog class="gpt-dialog" id="dlgEditDoc">
    <div class="gpt-dlg-head">
      <h2>\u7f16\u8f91\u6587\u6863\u4fe1\u606f</h2>
      <button type="button" class="gpt-dlg-close" data-close-dlg="dlgEditDoc">\u00d7</button>
    </div>
    <div class="gpt-dlg-body">
      <input type="hidden" id="editDocName" />
      <label>\u77e5\u8bc6\u5e93</label>
      <select id="editDocCat" class="gpt-input"></select>
      <label>\u63cf\u8ff0</label>
      <textarea id="editDocDesc" class="gpt-input" rows="3"></textarea>
      <button type="button" class="gpt-btn-primary" id="btnEditDocSave">\u4fdd\u5b58</button>
    </div>
  </dialog>

  <dialog class="gpt-dialog" id="dlgProfile">
    <div class="gpt-dlg-head">
      <h2>\u8d26\u6237</h2>
      <button type="button" class="gpt-dlg-close" data-close-dlg="dlgProfile">\u00d7</button>
    </div>
    <div class="gpt-dlg-body">
      <div class="gpt-profile-avatar-row">
        <div class="gpt-profile-avatar-preview" id="profileAvatarPreview">
          <img id="profileAvatarImg" alt="" hidden />
          <span id="profileAvatarPh">\u5934\u50cf</span>
        </div>
        <div class="gpt-profile-avatar-actions">
          <label class="gpt-btn-sm gpt-btn-file">
            \u4e0a\u4f20\u5934\u50cf
            <input type="file" id="profileAvatarFile" accept="image/jpeg,image/png,image/webp,image/gif" hidden />
          </label>
          <button type="button" class="gpt-btn-sm" id="btnProfileClearAvatar">\u79fb\u9664\u5934\u50cf</button>
        </div>
      </div>
      <p class="gpt-muted">\u767b\u5f55\u8d26\u53f7\uff1a<strong id="profileUsername">\u2014</strong></p>
      <p class="gpt-muted">\u89d2\u8272\uff1a<span id="profileRole">\u2014</span></p>
      <label>\u6635\u79f0</label>
      <input type="text" id="profileNickname" class="gpt-input" maxlength="32" />
      <p class="gpt-muted">\u9ed8\u8ba4\u300c\u7528\u6237\u300d \u7528\u6237\u540d\u524d 5 \u4f4d\u3002</p>
      <div class="gpt-row gpt-row-end">
        <button type="button" class="gpt-btn-primary" id="btnProfileSave">\u4fdd\u5b58</button>
      </div>
      <p class="gpt-log" id="profileMsg" hidden></p>
    </div>
  </dialog>

  <dialog class="gpt-dialog" id="dlgHelp">
    <div class="gpt-dlg-head">
      <h2>\u5e2e\u52a9</h2>
      <button type="button" class="gpt-dlg-close" data-close-dlg="dlgHelp">\u00d7</button>
    </div>
    <div class="gpt-dlg-body gpt-help-body">
      <p><strong>\u6587\u6863\u4e0a\u4f20</strong>\uff1a\u5728\u300c\u4e0a\u4f20\u300d\u4e2d\u9009\u62e9\u77e5\u8bc6\u5e93\u4e0e\u6587\u4ef6\uff0c\u5165\u5e93\u540e\u53ef\u95ee\u7b54\u68c0\u7d22\u3002</p>
      <p><strong>\u77e5\u8bc6\u5e93</strong>\uff1a\u7ba1\u7406\u5206\u7c7b\u3001\u9884\u89c8\u4e0e\u5220\u9664\u6587\u6863\u3002</p>
      <p><strong>\u667a\u80fd\u95ee\u7b54</strong>\uff1a\u5728\u300c\u4e2a\u6027\u5316\u8bbe\u7f6e\u300d\u4e2d\u914d\u7f6e\u68c0\u7d22\u8303\u56f4\u3001\u6df7\u5408\u68c0\u7d22\u3001\u6a21\u578b\u53c2\u6570\u4e0e\u52a9\u624b\u6027\u683c\u9884\u8bbe\u3002</p>
      <p><strong>\u77e5\u8bc6\u5e93</strong>\uff1a\u6587\u6863\u4e0e\u4e0a\u4f20\u5728\u72ec\u7acb\u9875\u9762<a href="/kb.html">\u77e5\u8bc6\u5e93\u7ba1\u7406</a>\u3002</p>
      <p class="gpt-muted">\u6280\u672f\u95ee\u9898\u89c1 <a href="/docs" target="_blank" rel="noopener">API \u6587\u6863</a>\u3002</p>
    </div>
  </dialog>

  <dialog class="gpt-dialog" id="dlgRename">
    <form method="dialog" class="gpt-rename-form" id="formRename">
      <h3>\u91cd\u547d\u540d\u5bf9\u8bdd</h3>
      <input type="text" id="renameInput" class="gpt-input" required maxlength="64" />
      <div class="gpt-row gpt-row-end">
        <button type="button" class="gpt-btn-text" id="renameCancel">\u53d6\u6d88</button>
        <button type="submit" class="gpt-btn-primary" id="renameOk">\u4fdd\u5b58</button>
      </div>
    </form>
  </dialog>

  <script src="/static/app.js?v=20260433"></script>
</body>
</html>
"""


def build_admin_index_redirect() -> str:
    """\u7ba1\u7406\u7ad9\u4e0d\u518d\u63d0\u4f9b\u95ee\u7b54\u804a\u5929\uff1b\u9996\u9875\u8df3\u8f6c\u7528\u6237\u7ba1\u7406\u3002"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="0; url=/admin/users.html" />
  <title>\u8df3\u8f6c\u4e2d\u2026</title>
  <script>location.replace("/admin/users.html");</script>
</head>
<body>
  <p><a href="/admin/users.html">\u8fdb\u5165\u7ba1\u7406\u7aef</a></p>
</body>
</html>
"""


def main() -> None:
    settings = (USER / "settings.html").read_text(encoding="utf-8")

    side_user = sidebar_user_for_chat(settings)

    idx = build_index(side_user)
    adm = build_admin_index_redirect()

    (USER / "index.html").write_text(idx, encoding="utf-8", newline="\n")
    (ADMIN / "index.html").write_text(adm, encoding="utf-8", newline="\n")

    idx.encode("utf-8").decode("utf-8")
    adm.encode("utf-8").decode("utf-8")
    assert "\u667a\u80fd\u95ee\u7b54 \u00b7 \u7528\u6237" in idx
    assert "/admin/users.html" in adm
    print("Wrote", USER / "index.html", "and", ADMIN / "index.html", "OK")


if __name__ == "__main__":
    main()
