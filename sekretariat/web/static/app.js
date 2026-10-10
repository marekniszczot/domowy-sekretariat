// Small enhancements; every page works without them.
(function () {
  // Actions: block the button while the request runs (DR-2 table, "Akcje").
  document.addEventListener("submit", function (event) {
    var button = event.target.querySelector("button[type=submit]");
    if (button) setTimeout(function () { button.disabled = true; }, 0);
  });

  // „Cofnij” stays for 8 s (DR-8); the server accepts it for 60 s.
  var bar = document.querySelector("[data-undo]");
  if (bar) {
    setTimeout(function () {
      bar.classList.add("gone");
      setTimeout(function () { bar.remove(); }, 250);
    }, 8000);
  }

  // Deadline sheet: the button says what will happen.
  var input = document.querySelector(".deadline-form input[type=date]");
  if (input) {
    var save = document.querySelector(".deadline-form button");
    input.addEventListener("input", function () {
      save.textContent = input.value === input.dataset.original ? save.dataset.same : save.dataset.changed;
    });
  }
})();
