const ADMIN_REFRESH_SPIN_DURATION_MS = 720;

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
  initializeProfileImageUploader(root);
  renderMath(target || document.body);
});

window.startAdminRefreshAnimation = function startAdminRefreshAnimation(button) {
  if (!(button instanceof HTMLElement)) {
    return;
  }
  window.clearTimeout(Number(button.dataset.refreshStopTimer || 0));
  button.classList.remove("is-refreshing");
  // Force a reflow so repeat clicks restart the spin immediately.
  void button.offsetWidth;
  button.dataset.refreshStartedAt = String(Date.now());
  button.classList.add("is-refreshing");
};

window.stopAdminRefreshAnimation = function stopAdminRefreshAnimation() {
  document.querySelectorAll("[data-admin-refresh-button].is-refreshing").forEach((button) => {
    if (!(button instanceof HTMLElement)) {
      return;
    }
    const startedAt = Number(button.dataset.refreshStartedAt || 0);
    const elapsed = startedAt ? Date.now() - startedAt : ADMIN_REFRESH_SPIN_DURATION_MS;
    const progressInCurrentSpin = elapsed % ADMIN_REFRESH_SPIN_DURATION_MS;
    const remaining =
      progressInCurrentSpin === 0
        ? 0
        : ADMIN_REFRESH_SPIN_DURATION_MS - progressInCurrentSpin;
    window.clearTimeout(Number(button.dataset.refreshStopTimer || 0));
    const timerId = window.setTimeout(() => {
      button.classList.remove("is-refreshing");
      delete button.dataset.refreshStartedAt;
      delete button.dataset.refreshStopTimer;
    }, remaining);
    button.dataset.refreshStopTimer = String(timerId);
  });
};

document.body.addEventListener("htmx:afterRequest", () => {
  window.stopAdminRefreshAnimation();
});

document.body.addEventListener("htmx:responseError", () => {
  window.stopAdminRefreshAnimation();
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

function initializeProfileImageUploader(root = document) {
  const allowedContentTypes = new Set([
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
  ]);

  const forms =
    root instanceof Element
      ? root.matches("[data-profile-edit-form]")
        ? [root]
        : root.querySelectorAll("[data-profile-edit-form]")
      : document.querySelectorAll("[data-profile-edit-form]");

  forms.forEach((form) => {
    if (!(form instanceof HTMLFormElement) || form.dataset.uploadReady === "true") {
      return;
    }

    const fileInput = form.querySelector("[data-profile-image-file-input]");
    const hiddenInput = form.querySelector('input[name="profile_image"]');
    const statusNode = form.querySelector("[data-profile-image-upload-status]");
    const previewImage = form
      .closest(".grid")
      ?.querySelector("[data-profile-image-preview]");
    const fallbackNode = form
      .closest(".grid")
      ?.querySelector("[data-profile-image-fallback]");
    const clearButton = form.querySelector("[data-profile-image-clear]");
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');

    if (
      !(fileInput instanceof HTMLInputElement) ||
      !(hiddenInput instanceof HTMLInputElement) ||
      !(statusNode instanceof HTMLElement) ||
      !(csrfInput instanceof HTMLInputElement)
    ) {
      return;
    }

    const setStatus = (message, tone = "muted") => {
      statusNode.textContent = message;
      statusNode.classList.remove("hidden", "text-red-700", "text-emerald-700");
      statusNode.classList.add("block");
      statusNode.classList.toggle("text-red-700", tone === "error");
      statusNode.classList.toggle("text-emerald-700", tone === "success");
    };

    const updatePreview = (imageUrl) => {
      hiddenInput.value = imageUrl;
      if (previewImage instanceof HTMLImageElement) {
        if (imageUrl) {
          previewImage.src = imageUrl;
          previewImage.classList.remove("hidden");
        } else {
          previewImage.src = "";
          previewImage.classList.add("hidden");
        }
      }
      if (fallbackNode instanceof HTMLElement) {
        fallbackNode.classList.toggle("hidden", Boolean(imageUrl));
      }
    };

    clearButton?.addEventListener("click", () => {
      fileInput.value = "";
      updatePreview("");
      statusNode.classList.add("hidden");
    });

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) {
        return;
      }

      if (!allowedContentTypes.has(file.type)) {
        setStatus("지원하지 않는 이미지 형식입니다.", "error");
        fileInput.value = "";
        return;
      }

      setStatus("업로드를 준비하고 있습니다.");

      let prepareResponse;
      try {
        const preparePayload = new URLSearchParams({
          filename: file.name,
          content_type: file.type,
        });
        prepareResponse = await fetch(fileInput.dataset.uploadPrepareUrl || "", {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-CSRFToken": csrfInput.value,
            "X-Requested-With": "XMLHttpRequest",
          },
          body: preparePayload.toString(),
          credentials: "same-origin",
        });
      } catch {
        setStatus("업로드 준비 중 오류가 발생했습니다.", "error");
        return;
      }

      const prepareData = await prepareResponse.json();
      if (!prepareResponse.ok) {
        setStatus(prepareData.error || "업로드를 준비할 수 없습니다.", "error");
        return;
      }

      const uploadPayload = new FormData();
      Object.entries(prepareData.fields || {}).forEach(([key, value]) => {
        uploadPayload.append(key, `${value}`);
      });
      uploadPayload.append("file", file);

      setStatus("이미지를 업로드하고 있습니다.");

      let uploadResponse;
      try {
        uploadResponse = await fetch(prepareData.upload_url, {
          method: "POST",
          body: uploadPayload,
          mode: "cors",
        });
      } catch {
        setStatus("이미지 업로드에 실패했습니다.", "error");
        return;
      }

      if (!uploadResponse.ok) {
        setStatus("이미지 업로드를 완료하지 못했습니다.", "error");
        return;
      }

      updatePreview(`${prepareData.public_url || ""}`);
      setStatus("업로드가 완료되었습니다. 저장하기를 누르면 반영됩니다.", "success");
    });

    form.dataset.uploadReady = "true";
  });
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

function applyCommunityComposePayload(payload) {
  const bodyInput = document.querySelector("[data-community-compose-body]");
  const statusInput = document.querySelector('select[name="status"]');
  const draftIdInput = document.querySelector('input[name="draft_id"]');
  const tagInput = getCommunityTagInput();
  if (
    !(bodyInput instanceof HTMLTextAreaElement) ||
    !(statusInput instanceof HTMLSelectElement) ||
    !(draftIdInput instanceof HTMLInputElement) ||
    !tagInput
  ) {
    return;
  }

  bodyInput.value = `${payload.body_markdown || ""}`;
  statusInput.value = `${payload.status || "published"}`;
  draftIdInput.value = `${payload.draft_id || ""}`;
  tagInput.value = `${payload.tag_names || ""}`;
  renderCommunitySelectedTags(getCommunitySelectedTags(tagInput));
  renderCommunitySelectedWikiDocuments(payload.wiki_document_payloads || []);
}

function resetCommunityComposeModalState() {
  const payloadElement = document.getElementById("community-compose-initial-payload");
  if (!payloadElement) {
    return;
  }

  const payload = JSON.parse(payloadElement.textContent || "{}");
  applyCommunityComposePayload(payload);

  document.querySelectorAll("[data-community-draft-load]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    const draftId = button.dataset.draftId?.trim() || "";
    const isActive = draftId && draftId === `${payload.draft_id || ""}`;
    button.classList.toggle("border-primary/30", isActive);
    button.classList.toggle("bg-primary-container/40", isActive);
    button.classList.toggle("border-transparent", !isActive);
    button.classList.toggle("bg-white", !isActive);
  });
}

document.body.addEventListener("click", (event) => {
  const openTrigger =
    event.target instanceof Element
      ? event.target.closest("[data-community-compose-open]")
      : null;
  if (openTrigger) {
    if (!document.querySelector("[data-community-compose-modal]")) {
      return;
    }
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
    resetCommunityComposeModalState();
    setCommunityComposeModalOpen(false);
    return;
  }

  const modal =
    event.target instanceof Element
      ? event.target.closest("[data-community-compose-modal]")
      : null;
  if (modal && event.target === modal) {
    resetCommunityComposeModalState();
    setCommunityComposeModalOpen(false);
  }
});

function getCommunityTagInput() {
  const input = document.querySelector("[data-community-tag-input]");
  return input instanceof HTMLInputElement ? input : null;
}

function getCommunityTagSelectedContainer() {
  const container = document.querySelector("[data-community-tag-selected]");
  return container instanceof HTMLElement ? container : null;
}

function getCommunityTagSearchInput() {
  const input = document.querySelector("[data-community-tag-search]");
  return input instanceof HTMLInputElement ? input : null;
}

function normalizeCommunityTagValue(value) {
  return value.trim().replaceAll(/\s+/g, " ");
}

function getCommunitySelectedTags(tagInput) {
  return tagInput.value
    .split(",")
    .map((value) => normalizeCommunityTagValue(value))
    .filter(Boolean);
}

function syncCommunityTagEmptyState(container) {
  const emptyState = container.querySelector("[data-community-tag-empty]");
  const hasChips = container.querySelector("[data-community-tag-selected-chip]");
  if (!(emptyState instanceof HTMLElement)) {
    return;
  }
  emptyState.classList.toggle("hidden", Boolean(hasChips));
}

function syncCommunityTagOptionVisibility(searchQuery, selectedTags) {
  const normalizedQuery = normalizeCommunityTagValue(searchQuery).toLowerCase();
  const selectedSet = new Set(selectedTags.map((tag) => tag.toLowerCase()));
  document.querySelectorAll("[data-community-tag-option]").forEach((option) => {
    if (!(option instanceof HTMLElement)) {
      return;
    }
    const tagValue = normalizeCommunityTagValue(option.dataset.tagValue || "");
    const matchesQuery =
      !normalizedQuery || tagValue.toLowerCase().includes(normalizedQuery);
    const isSelected = selectedSet.has(tagValue.toLowerCase());
    option.classList.toggle("hidden", !matchesQuery || isSelected);
  });
}

function renderCommunitySelectedTags(selectedTags) {
  const tagInput = getCommunityTagInput();
  const container = getCommunityTagSelectedContainer();
  if (!tagInput || !container) {
    return;
  }

  const emptyState = container.querySelector("[data-community-tag-empty]");
  container
    .querySelectorAll("[data-community-tag-selected-chip]")
    .forEach((chip) => chip.remove());

  selectedTags.forEach((tagValue) => {
    const chip = document.createElement("span");
    chip.className =
      "inline-flex items-center gap-2 rounded-full bg-secondary-container px-3 py-2 text-xs font-semibold text-on-secondary-container";
    chip.dataset.communityTagSelectedChip = "";
    chip.dataset.tagValue = tagValue;
    chip.innerHTML = `
      <span>#${tagValue}</span>
      <button type="button" class="rounded-full bg-black/10 px-2 py-0.5 text-[10px]" data-community-tag-remove>제거</button>
    `;
    if (emptyState instanceof HTMLElement) {
      container.insertBefore(chip, emptyState);
    } else {
      container.appendChild(chip);
    }
  });

  tagInput.value = selectedTags.join(", ");
  syncCommunityTagEmptyState(container);
  const searchInput = getCommunityTagSearchInput();
  syncCommunityTagOptionVisibility(searchInput?.value || "", selectedTags);
}

function tryAddCommunityTag(rawValue) {
  const tagInput = getCommunityTagInput();
  const container = getCommunityTagSelectedContainer();
  if (!tagInput || !container) {
    return false;
  }

  const tagValue = normalizeCommunityTagValue(rawValue);
  if (!tagValue) {
    return false;
  }

  const selectedTags = getCommunitySelectedTags(tagInput);
  if (
    selectedTags.some((selectedTag) => selectedTag.toLowerCase() === tagValue.toLowerCase())
  ) {
    return false;
  }

  const maxSelected = Number.parseInt(container.dataset.communityTagMax || "5", 10);
  if (selectedTags.length >= maxSelected) {
    return false;
  }

  renderCommunitySelectedTags([...selectedTags, tagValue]);
  const searchInput = getCommunityTagSearchInput();
  if (searchInput) {
    searchInput.value = "";
  }
  return true;
}

function initializeCommunityTagSelector() {
  const tagInput = getCommunityTagInput();
  if (!tagInput) {
    return;
  }
  renderCommunitySelectedTags(getCommunitySelectedTags(tagInput));
}

function renderCommunitySelectedWikiDocuments(wikiDocuments) {
  const container = getCommunityWikiSelectedContainer();
  if (!container) {
    return;
  }

  const lockedIds = getLockedWikiIds(container);
  container.querySelectorAll("[data-community-wiki-chip]").forEach((chip) => {
    if (!(chip instanceof HTMLElement)) {
      return;
    }
    const wikiId = chip.dataset.wikiId?.trim();
    if (wikiId && lockedIds.has(wikiId)) {
      return;
    }
    chip.remove();
  });

  document.querySelectorAll("[data-community-wiki-result]").forEach((result) => {
    if (!(result instanceof HTMLElement)) {
      return;
    }
    const wikiId = result.dataset.wikiId?.trim();
    if (wikiId && !lockedIds.has(wikiId)) {
      syncCommunityWikiOptionState(wikiId, false);
    }
  });

  wikiDocuments.forEach((wikiDocument) => {
    const wikiId = `${wikiDocument.id || ""}`.trim();
    const wikiTitle = `${wikiDocument.title || ""}`.trim();
    const wikiSummary = `${wikiDocument.summary || ""}`.trim();
    if (!wikiId || !wikiTitle || lockedIds.has(wikiId)) {
      return;
    }
    appendCommunityWikiChip(container, wikiId, wikiTitle, wikiSummary);
    syncCommunityWikiOptionState(wikiId, true);
  });

  updateCommunityWikiEmptyState(container);
}

document.body.addEventListener("click", (event) => {
  const draftLoad =
    event.target instanceof Element
      ? event.target.closest("[data-community-draft-load]")
      : null;
  if (draftLoad instanceof HTMLButtonElement) {
    const payloadId = draftLoad.dataset.draftPayloadId?.trim();
    const payloadElement = payloadId ? document.getElementById(payloadId) : null;
    if (!payloadElement) {
      return;
    }

    const payload = JSON.parse(payloadElement.textContent || "{}");
    applyCommunityComposePayload(payload);

    document.querySelectorAll("[data-community-draft-load]").forEach((button) => {
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }
      button.classList.remove("border-primary/30", "bg-primary-container/40");
      button.classList.add("border-transparent", "bg-white");
    });
    draftLoad.classList.remove("border-transparent", "bg-white");
    draftLoad.classList.add("border-primary/30", "bg-primary-container/40");
    return;
  }

  const tagOption =
    event.target instanceof Element
      ? event.target.closest("[data-community-tag-option]")
      : null;
  if (tagOption instanceof HTMLElement) {
    const tagValue = tagOption.dataset.tagValue?.trim();
    if (tagValue) {
      tryAddCommunityTag(tagValue);
    }
    return;
  }

  const tagRemove =
    event.target instanceof Element
      ? event.target.closest("[data-community-tag-remove]")
      : null;
  if (!(tagRemove instanceof HTMLElement)) {
    return;
  }

  const tagInput = getCommunityTagInput();
  const chip = tagRemove.closest("[data-community-tag-selected-chip]");
  if (!tagInput || !(chip instanceof HTMLElement)) {
    return;
  }

  const tagValue = normalizeCommunityTagValue(chip.dataset.tagValue || "");
  if (!tagValue) {
    return;
  }

  const nextTags = getCommunitySelectedTags(tagInput).filter(
    (selectedTag) => selectedTag.toLowerCase() !== tagValue.toLowerCase(),
  );
  renderCommunitySelectedTags(nextTags);
});

document.body.addEventListener("input", (event) => {
  const tagSearch =
    event.target instanceof Element
      ? event.target.closest("[data-community-tag-search]")
      : null;
  if (!(tagSearch instanceof HTMLInputElement)) {
    return;
  }

  const tagInput = getCommunityTagInput();
  if (!tagInput) {
    return;
  }
  syncCommunityTagOptionVisibility(tagSearch.value, getCommunitySelectedTags(tagInput));
});

document.body.addEventListener("keydown", (event) => {
  const tagSearch =
    event.target instanceof Element
      ? event.target.closest("[data-community-tag-search]")
      : null;
  if (!(tagSearch instanceof HTMLInputElement)) {
    return;
  }

  if (event.key !== "Enter" && event.key !== ",") {
    return;
  }

  event.preventDefault();
  tryAddCommunityTag(tagSearch.value);
});

function getCommunityWikiSelectedContainer() {
  const container = document.querySelector("[data-community-wiki-selected]");
  return container instanceof HTMLElement ? container : null;
}

function getSelectedWikiIds(container) {
  return Array.from(
    container.querySelectorAll("[data-community-wiki-input]"),
    (input) => input.value,
  );
}

function getLockedWikiIds(container) {
  return new Set(
    (container.dataset.communityWikiLocked || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );
}

function updateCommunityWikiEmptyState(container) {
  const emptyState = container.querySelector("[data-community-wiki-empty]");
  const hasChips = container.querySelector("[data-community-wiki-chip]");
  if (!(emptyState instanceof HTMLElement)) {
    return;
  }
  emptyState.classList.toggle("hidden", Boolean(hasChips));
}

function syncCommunityWikiOptionState(wikiId, isSelected) {
  document
    .querySelectorAll(`[data-community-wiki-result][data-wiki-id="${wikiId}"]`)
    .forEach((result) => {
      if (!(result instanceof HTMLElement)) {
        return;
      }
      result.classList.toggle("border-primary/20", isSelected);
      result.classList.toggle("bg-primary-container/40", isSelected);
      result.classList.toggle("border-transparent", !isSelected);
      result.classList.toggle("bg-white", !isSelected);
      const label = result.querySelector("[data-community-wiki-option-label]");
      if (label instanceof HTMLButtonElement) {
        if (label.disabled) {
          label.textContent = "기본 참조";
          return;
        }
        label.textContent = isSelected ? "제거" : "추가";
        label.classList.toggle("bg-red-100", isSelected);
        label.classList.toggle("text-red-700", isSelected);
        label.classList.toggle("bg-surface-container-high", !isSelected);
        label.classList.toggle("text-primary", !isSelected);
      }
    });
}

function appendCommunityWikiChip(container, wikiId, wikiTitle, wikiSummary) {
  const chip = document.createElement("span");
  chip.className =
    "inline-flex items-center gap-2 rounded-full bg-secondary-container px-3 py-2 text-xs font-semibold text-on-secondary-container";
  chip.dataset.communityWikiChip = "";
  chip.dataset.wikiId = wikiId;
  chip.dataset.wikiTitle = wikiTitle;
  chip.dataset.wikiSummary = wikiSummary;
  chip.innerHTML = `
    <input type="hidden" name="wiki_documents" value="${wikiId}" data-community-wiki-input>
    <span>${wikiTitle}</span>
    <button type="button" class="rounded-full bg-black/10 px-2 py-0.5 text-[10px]" data-community-wiki-remove>제거</button>
  `;
  container.appendChild(chip);
}

document.body.addEventListener("click", (event) => {
  const wikiOption =
    event.target instanceof Element
      ? event.target.closest("[data-community-wiki-option]")
      : null;
  if (wikiOption instanceof HTMLElement) {
    const container = getCommunityWikiSelectedContainer();
    if (!container) {
      return;
    }

    const wikiId = wikiOption.dataset.wikiId?.trim();
    const wikiTitle = wikiOption.dataset.wikiTitle?.trim();
    const wikiSummary = wikiOption.dataset.wikiSummary?.trim() || "";
    if (!wikiId || !wikiTitle) {
      return;
    }

    const selectedIds = getSelectedWikiIds(container);
    const lockedIds = getLockedWikiIds(container);
    const existingChip = container.querySelector(
      `[data-community-wiki-chip][data-wiki-id="${wikiId}"]`,
    );
    if (existingChip instanceof HTMLElement) {
      if (!lockedIds.has(wikiId)) {
        existingChip.remove();
        updateCommunityWikiEmptyState(container);
        syncCommunityWikiOptionState(wikiId, false);
      }
      return;
    }

    const maxSelected = Number.parseInt(container.dataset.communityWikiMax || "10", 10);
    if (selectedIds.length >= maxSelected) {
      return;
    }

    appendCommunityWikiChip(container, wikiId, wikiTitle, wikiSummary);
    updateCommunityWikiEmptyState(container);
    syncCommunityWikiOptionState(wikiId, true);
    return;
  }

  const wikiRemove =
    event.target instanceof Element
      ? event.target.closest("[data-community-wiki-remove]")
      : null;
  if (!(wikiRemove instanceof HTMLElement)) {
    return;
  }

  const container = getCommunityWikiSelectedContainer();
  const chip = wikiRemove.closest("[data-community-wiki-chip]");
  if (!container || !(chip instanceof HTMLElement)) {
    return;
  }

  const wikiId = chip.dataset.wikiId?.trim();
  const lockedIds = getLockedWikiIds(container);
  if (wikiId && lockedIds.has(wikiId)) {
    return;
  }
  chip.remove();
  updateCommunityWikiEmptyState(container);
  if (wikiId) {
    syncCommunityWikiOptionState(wikiId, false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (document.querySelector("[data-community-compose-modal].flex")) {
    resetCommunityComposeModalState();
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
initializeCommunityTagSelector();
initializeProfileImageUploader();
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
