document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target && target.id) {
    target.dataset.lastUpdated = "true";
  }
});

function markTimezoneReady() {
  document.body.classList.remove("js-timezone-pending");
  document.body.classList.add("js-timezone-ready");
}

async function syncBrowserTimezone() {
  const currentTimezone = document.body.dataset.currentTimezone;
  const syncUrl = document.body.dataset.timezoneSyncUrl;
  const csrfInput = document.querySelector("#timezone-sync-form input[name=csrfmiddlewaretoken]");

  if (!syncUrl || !csrfInput) {
    markTimezoneReady();
    return;
  }

  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!browserTimezone) {
    markTimezoneReady();
    return;
  }

  if (browserTimezone === currentTimezone) {
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
      window.location.reload();
      return;
    }
  } catch {
    // Fall back to server-rendered time if the sync request fails.
  }

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
