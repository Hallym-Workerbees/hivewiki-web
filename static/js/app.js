document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target && target.id) {
    target.dataset.lastUpdated = "true";
  }
});

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
