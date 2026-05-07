document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target && target.id) {
    target.dataset.lastUpdated = "true";
  }
  const root = target instanceof Element ? target : document.body;
  formatTimezoneSensitiveElements(document.body.dataset.currentTimezone, root);
  formatLocalDatetimeInputs(document.body.dataset.currentTimezone, root);
  initializeWikiToc(root);
  initializeCodeCopyButtons(root);
  renderMath(target || document.body);
});

function closeAdminModal() {
  const modalRoot = document.querySelector("#admin-modal-root");
  if (!modalRoot) {
    return;
  }
  modalRoot.innerHTML = "";
}

document.body.addEventListener("click", (event) => {
  const path = typeof event.composedPath === "function" ? event.composedPath() : [];
  const closeTrigger =
    path.find(
      (node) =>
        node instanceof Element && node.hasAttribute("data-admin-modal-close")
    ) ||
    (event.target instanceof Element
      ? event.target.closest("[data-admin-modal-close]")
      : null);
  if (!closeTrigger) {
    return;
  }
  closeAdminModal();
});

document.body.addEventListener("click", async (event) => {
  const copyTrigger =
    event.target instanceof Element
      ? event.target.closest("[data-copy-trigger]")
      : null;
  if (!copyTrigger) {
    return;
  }

  const copySource = copyTrigger.dataset.copySource;
  const copyNode = copySource ? document.getElementById(copySource) : null;
  const copyText =
    copyNode instanceof HTMLTextAreaElement
      ? copyNode.value
      : copyNode?.textContent;
  if (!copyText) {
    return;
  }

  try {
    await writeToClipboard(copyText);
  } catch {
    return;
  }

  const panel = copyTrigger.closest(".wiki-actions-panel");
  const labelNode = copyTrigger.querySelector("[data-copy-label-text]");
  if (!(labelNode instanceof HTMLElement)) {
    return;
  }

  panel?.querySelectorAll("[data-copy-trigger]").forEach((button) => {
    button.classList.remove("is-copied");
    if (!(button instanceof HTMLElement)) {
      return;
    }
    const textNode = button.querySelector("[data-copy-label-text]");
    if (!(textNode instanceof HTMLElement)) {
      return;
    }
    const defaultText = button.dataset.copyDefaultText;
    if (defaultText) {
      textNode.textContent = defaultText;
    }
  });

  if (!copyTrigger.dataset.copyDefaultText) {
    copyTrigger.dataset.copyDefaultText = labelNode.textContent || "";
  }
  copyTrigger.classList.add("is-copied");
  labelNode.textContent =
    copyTrigger.dataset.copySuccessText || "복사됨!";
  window.clearTimeout(Number(copyTrigger.dataset.resetTimer || 0));
  const timerId = window.setTimeout(() => {
    copyTrigger.classList.remove("is-copied");
    labelNode.textContent = copyTrigger.dataset.copyDefaultText || "";
  }, 1800);
  copyTrigger.dataset.resetTimer = String(timerId);
});

async function writeToClipboard(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const fallback = document.createElement("textarea");
  fallback.value = value;
  fallback.setAttribute("readonly", "");
  fallback.style.position = "fixed";
  fallback.style.top = "-9999px";
  fallback.style.left = "-9999px";
  document.body.appendChild(fallback);
  fallback.select();
  fallback.setSelectionRange(0, fallback.value.length);
  const copied = document.execCommand("copy");
  document.body.removeChild(fallback);
  if (!copied) {
    throw new Error("Clipboard copy failed");
  }
}

function initializeCodeCopyButtons(root = document) {
  root.querySelectorAll(".codehilite").forEach((block) => {
    if (!(block instanceof HTMLElement) || block.dataset.copyReady === "true") {
      return;
    }

    const codeNode = block.querySelector("code");
    if (!(codeNode instanceof HTMLElement)) {
      return;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "code-copy-button";
    button.textContent = "Copy";
    button.addEventListener("click", async () => {
      try {
        await writeToClipboard(codeNode.textContent || "");
      } catch {
        return;
      }

      const originalText = button.dataset.defaultText || "Copy";
      button.textContent = "Copied!";
      window.clearTimeout(Number(button.dataset.resetTimer || 0));
      const timerId = window.setTimeout(() => {
        button.textContent = originalText;
      }, 1600);
      button.dataset.defaultText = originalText;
      button.dataset.resetTimer = String(timerId);
    });

    block.appendChild(button);
    block.dataset.copyReady = "true";
  });
}

function renderMath(root) {
  if (typeof window.renderMathInElement !== "function") {
    return;
  }

  window.renderMathInElement(root, {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false },
      { left: "\\(", right: "\\)", display: false },
    ],
    throwOnError: false,
  });
}

function initializeWikiToc(root = document) {
  const tocNav =
    root instanceof Element
      ? root.querySelector("[data-toc-nav]") || document.querySelector("[data-toc-nav]")
      : document.querySelector("[data-toc-nav]");
  if (!(tocNav instanceof HTMLElement)) {
    disconnectWikiTocObserver();
    return;
  }

  const tocLinks = Array.from(tocNav.querySelectorAll("[data-toc-link]"));
  if (!tocLinks.length) {
    disconnectWikiTocObserver();
    return;
  }

  const headingMap = new Map();
  tocLinks.forEach((link) => {
    const targetId = link.getAttribute("data-toc-target");
    if (!targetId) {
      return;
    }
    const heading = document.getElementById(targetId);
    if (!heading) {
      return;
    }
    headingMap.set(targetId, heading);
  });

  const setActiveLink = (activeId) => {
    tocLinks.forEach((link) => {
      const isActive = link.getAttribute("data-toc-target") === activeId;
      link.classList.toggle("bg-surface-container-high", isActive);
      link.classList.toggle("text-on-surface", isActive);
      link.classList.toggle("font-semibold", isActive);
    });
  };

  const headingIds = Array.from(headingMap.keys());
  if (!headingIds.length) {
    return;
  }
  setActiveLink(headingIds[0]);

  if (!("IntersectionObserver" in window)) {
    return;
  }

  disconnectWikiTocObserver();
  let activeId = headingIds[0];
  const observer = new IntersectionObserver(
    (entries) => {
      const visibleEntries = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);

      if (visibleEntries.length) {
        activeId = visibleEntries[0].target.id;
        setActiveLink(activeId);
        return;
      }

      const passedHeadings = headingIds.filter((id) => {
        const heading = headingMap.get(id);
        return heading && heading.getBoundingClientRect().top < 140;
      });
      if (passedHeadings.length) {
        activeId = passedHeadings[passedHeadings.length - 1];
        setActiveLink(activeId);
      }
    },
    {
      rootMargin: "-18% 0px -66% 0px",
      threshold: [0, 1],
    }
  );

  headingMap.forEach((heading) => observer.observe(heading));
  window.hiveWikiTocObserver = observer;
}

function disconnectWikiTocObserver() {
  if (window.hiveWikiTocObserver instanceof IntersectionObserver) {
    window.hiveWikiTocObserver.disconnect();
    window.hiveWikiTocObserver = null;
  }
}

function setCommunityComposeModalOpen(isOpen) {
  const modal = document.querySelector("[data-community-compose-modal]");
  if (!(modal instanceof HTMLElement)) {
    return;
  }

  modal.classList.toggle("hidden", !isOpen);
  modal.classList.toggle("flex", isOpen);
  document.body.classList.toggle("overflow-hidden", isOpen);
}

document.body.addEventListener("click", (event) => {
  const openTrigger =
    event.target instanceof Element
      ? event.target.closest("[data-community-compose-open]")
      : null;
  if (openTrigger) {
    event.preventDefault();
    setCommunityComposeModalOpen(true);
    return;
  }

  const closeTrigger =
    event.target instanceof Element
      ? event.target.closest("[data-community-compose-close]")
      : null;
  if (closeTrigger) {
    event.preventDefault();
    setCommunityComposeModalOpen(false);
    return;
  }

  const modal =
    event.target instanceof Element
      ? event.target.closest("[data-community-compose-modal]")
      : null;
  if (modal && event.target === modal) {
    setCommunityComposeModalOpen(false);
  }
});

document.body.addEventListener("click", (event) => {
  const tagChip =
    event.target instanceof Element
      ? event.target.closest("[data-community-tag-chip]")
      : null;
  if (!(tagChip instanceof HTMLElement)) {
    return;
  }

  const tagInput = document.querySelector("[data-community-tag-input]");
  if (!(tagInput instanceof HTMLInputElement)) {
    return;
  }

  const tagValue = tagChip.dataset.tagValue?.trim();
  if (!tagValue) {
    return;
  }

  const currentValues = tagInput.value
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (currentValues.some((value) => value.toLowerCase() === tagValue.toLowerCase())) {
    return;
  }

  currentValues.push(tagValue);
  tagInput.value = currentValues.join(", ");
  tagInput.dispatchEvent(new Event("input", { bubbles: true }));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (document.querySelector("[data-community-compose-modal].flex")) {
    setCommunityComposeModalOpen(false);
  }
  if (!document.querySelector("[data-admin-modal]")) {
    return;
  }
  closeAdminModal();
});

function markTimezoneReady() {
  document.body.classList.remove("js-timezone-pending");
  document.body.classList.add("js-timezone-ready");
}

function formatPartsToDate(parts, includeTime) {
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  const dateText = `${values.year}.${values.month}.${values.day}`;
  if (!includeTime) {
    return dateText;
  }
  return `${dateText} ${values.hour}:${values.minute}`;
}

function formatTimezoneSensitiveElements(timezoneName, root = document) {
  if (!timezoneName) {
    return;
  }

  root.querySelectorAll("[data-local-datetime]").forEach((element) => {
    const datetimeValue = element.dataset.localDatetime;
    if (!datetimeValue) {
      return;
    }

    const date = new Date(datetimeValue);
    if (Number.isNaN(date.getTime())) {
      return;
    }

    const includeTime = (element.dataset.localFormat || "datetime") === "datetime";
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezoneName,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      ...(includeTime
        ? {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }
        : {}),
    });

    element.textContent = formatPartsToDate(formatter.formatToParts(date), includeTime);
  });
}

function formatDateTimeLocalValue(date, timezoneName) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezoneName,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const values = Object.fromEntries(
    formatter.formatToParts(date).map(({ type, value }) => [type, value])
  );
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
}

function formatLocalDatetimeInputs(timezoneName, root = document) {
  if (!timezoneName) {
    return;
  }

  root.querySelectorAll("[data-local-datetime-input]").forEach((element) => {
    const datetimeValue = element.dataset.localDatetimeSource;
    if (!datetimeValue) {
      return;
    }

    const date = new Date(datetimeValue);
    if (Number.isNaN(date.getTime())) {
      return;
    }

    element.value = formatDateTimeLocalValue(date, timezoneName);
  });
}

async function syncBrowserTimezone() {
  const currentTimezone = document.body.dataset.currentTimezone;
  const syncUrl = document.body.dataset.timezoneSyncUrl;
  const csrfInput = document.querySelector("#timezone-sync-form input[name=csrfmiddlewaretoken]");

  if (!syncUrl || !csrfInput) {
    formatTimezoneSensitiveElements(currentTimezone);
    formatLocalDatetimeInputs(currentTimezone);
    markTimezoneReady();
    return;
  }

  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!browserTimezone) {
    formatTimezoneSensitiveElements(currentTimezone);
    formatLocalDatetimeInputs(currentTimezone);
    markTimezoneReady();
    return;
  }

  if (browserTimezone === currentTimezone) {
    formatTimezoneSensitiveElements(browserTimezone);
    formatLocalDatetimeInputs(browserTimezone);
    markTimezoneReady();
    return;
  }

  try {
    const payload = new URLSearchParams({ timezone: browserTimezone });
    const response = await fetch(syncUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-CSRFToken": csrfInput.value,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: payload.toString(),
      credentials: "same-origin",
    });

    if (response.ok) {
      document.body.dataset.currentTimezone = browserTimezone;
      formatTimezoneSensitiveElements(browserTimezone);
      formatLocalDatetimeInputs(browserTimezone);
      markTimezoneReady();
      return;
    }
  } catch {
    // Fall back to server-rendered time if the sync request fails.
  }

  formatTimezoneSensitiveElements(currentTimezone);
  formatLocalDatetimeInputs(currentTimezone);
  markTimezoneReady();
}

void syncBrowserTimezone();
initializeWikiToc();
initializeCodeCopyButtons();
if (document.querySelector("[data-community-compose-modal].flex")) {
  document.body.classList.add("overflow-hidden");
}
window.addEventListener("load", () => renderMath(document.body));

const flashMessages = document.querySelectorAll(".flash-message");

flashMessages.forEach((message) => {
  window.setTimeout(() => {
    message.classList.add("is-hiding");
    window.setTimeout(() => {
      message.remove();
      const stack = document.querySelector(".flash-stack");
      if (stack && !stack.querySelector(".flash-message")) {
        stack.remove();
      }
    }, 220);
  }, 3200);
});
