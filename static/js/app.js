document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target && target.id) {
    target.dataset.lastUpdated = "true";
  }
  formatTimezoneSensitiveElements(document.body.dataset.currentTimezone);
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

function formatTimezoneSensitiveElements(timezoneName) {
  if (!timezoneName) {
    return;
  }

  document.querySelectorAll("[data-local-datetime]").forEach((element) => {
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

async function syncBrowserTimezone() {
  const currentTimezone = document.body.dataset.currentTimezone;
  const syncUrl = document.body.dataset.timezoneSyncUrl;
  const csrfInput = document.querySelector("#timezone-sync-form input[name=csrfmiddlewaretoken]");

  if (!syncUrl || !csrfInput) {
    formatTimezoneSensitiveElements(currentTimezone);
    markTimezoneReady();
    return;
  }

  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!browserTimezone) {
    formatTimezoneSensitiveElements(currentTimezone);
    markTimezoneReady();
    return;
  }

  if (browserTimezone === currentTimezone) {
    formatTimezoneSensitiveElements(browserTimezone);
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
      markTimezoneReady();
      return;
    }
  } catch {
    // Fall back to server-rendered time if the sync request fails.
  }

  formatTimezoneSensitiveElements(currentTimezone);
  markTimezoneReady();
}

void syncBrowserTimezone();

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
