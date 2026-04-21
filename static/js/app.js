document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (target && target.id) {
    target.dataset.lastUpdated = "true";
  }
});
