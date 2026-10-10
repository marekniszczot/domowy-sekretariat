// Upload (DR-6): pages pile up as thumbnails, then go as one request.
// Without JavaScript the form still works with the native multiple file input.
(function () {
  var form = document.getElementById("upload");
  if (!form || !window.FormData || !window.fetch) return;
  var max = Number(form.dataset.maxPages);
  var camera = document.getElementById("camera");
  var picker = document.getElementById("file");
  var thumbs = document.getElementById("thumbs");
  var addTile = document.getElementById("add-page");
  var addLabel = document.getElementById("add-label");
  var submit = document.getElementById("submit");
  var error = document.getElementById("upload-error");
  var pages = [];

  [camera, picker].forEach(function (input) {
    input.removeAttribute("name"); // files are sent from `pages` below
    input.addEventListener("change", function () {
      Array.prototype.forEach.call(input.files, function (file) {
        if (pages.length < max) pages.push(file);
      });
      input.value = "";
      draw();
    });
  });

  function draw() {
    thumbs.querySelectorAll(".thumb.page").forEach(function (t) { t.remove(); });
    pages.forEach(function (file, index) {
      var tile = document.createElement("div");
      tile.className = "thumb page";
      if (file.type.indexOf("image/") === 0) {
        var img = document.createElement("img");
        img.alt = "Strona " + (index + 1);
        img.src = URL.createObjectURL(file);
        tile.appendChild(img);
      } else {
        tile.textContent = "PDF";
      }
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "Usuń stronę " + (index + 1));
      remove.addEventListener("click", function () { pages.splice(index, 1); draw(); });
      tile.appendChild(remove);
      thumbs.insertBefore(tile, addTile);
    });
    addLabel.textContent = pages.length ? "Dodaj stronę" : "Zrób zdjęcie";
    addTile.hidden = pages.length >= max;
    submit.disabled = pages.length === 0;
  }

  function fail(message) {
    error.querySelector("span:last-child").textContent = message;
    error.hidden = false;
    submit.disabled = pages.length === 0;
    submit.textContent = "Gotowe, przeanalizuj";
    window.scrollTo(0, 0);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var data = new FormData(form);
    pages.forEach(function (file) { data.append("pages", file, file.name); });
    submit.disabled = true;
    submit.textContent = "Wysyłam…";
    fetch(form.action, { method: "POST", body: data, credentials: "same-origin" })
      .then(function (response) {
        if (response.redirected && response.ok) { window.location = response.url; return; }
        if (response.status === 413) return fail("Zdjęcia są za duże. Dodaj mniej stron naraz.");
        return response.text().then(function (html) {
          var page = new DOMParser().parseFromString(html, "text/html");
          var message = page.querySelector("#upload-error span:last-child");
          fail(message && message.textContent.trim() ? message.textContent : "Nie udało się. Spróbuj ponownie.");
        });
      })
      .catch(function () { fail("Nie udało się. Sprawdź internet i spróbuj ponownie."); });
  });

  draw();
})();
