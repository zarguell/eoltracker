/* EOL Tracker — catalog search/filter progressive enhancement.
   The full product list is server-rendered; this only narrows what is shown. */
(function () {
  "use strict";

  var list = document.getElementById("product-list");
  if (!list) return;

  var form = document.getElementById("catalog-filters");
  var query = document.getElementById("filter-q");
  var category = document.getElementById("filter-category");
  var dataFilter = document.getElementById("filter-data");
  var sort = document.getElementById("filter-sort");
  var count = document.getElementById("result-count");
  var empty = document.getElementById("no-results");

  var cards = Array.prototype.slice.call(list.querySelectorAll(".product-card"));
  var total = cards.length;
  cards.forEach(function (card) {
    card.dataset.name = (card.querySelector(".product-name").textContent || "").trim().toLowerCase();
    card.dataset.sortName = card.dataset.name;
    card.dataset.coverageKeys = card.dataset.coverage || "";
  });

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function matches(card, queryText, categoryValue, milestone) {
    if (queryText && card.dataset.search.indexOf(queryText) === -1) return false;
    if (categoryValue && card.dataset.category !== categoryValue) return false;
    if (milestone && card.dataset.coverageKeys.split(" ").indexOf(milestone) === -1) return false;
    return true;
  }

  function comparator(value) {
    if (value === "releases") {
      return function (a, b) {
        return Number(b.dataset.releases) - Number(a.dataset.releases) ||
          a.dataset.sortName.localeCompare(b.dataset.sortName);
      };
    }
    if (value === "upcoming") {
      return function (a, b) {
        var left = a.dataset.nextDate || "9999-12-31";
        var right = b.dataset.nextDate || "9999-12-31";
        if (left !== right) return left < right ? -1 : 1;
        return a.dataset.sortName.localeCompare(b.dataset.sortName);
      };
    }
    return function (a, b) {
      return a.dataset.sortName.localeCompare(b.dataset.sortName);
    };
  }

  function apply() {
    var queryText = (query.value || "").trim().toLowerCase();
    var categoryValue = category.value;
    var milestone = dataFilter.value;
    var shown = 0;

    cards.forEach(function (card) {
      var visible = matches(card, queryText, categoryValue, milestone);
      card.hidden = !visible;
      if (visible) shown += 1;
    });

    cards.slice().sort(comparator(sort.value)).forEach(function (card) {
      list.appendChild(card);
    });

    if (count) {
      var filtered = shown !== total;
      count.textContent = filtered
        ? "Showing " + plural(shown, "product") + " of " + total
        : plural(total, "product");
    }
    if (empty) empty.hidden = shown !== 0;
    var filters = [query.value, categoryValue, dataFilter.value].filter(Boolean).length;
    if (form) form.dataset.filtered = filters ? "true" : "false";
  }

  form.addEventListener("input", apply);
  form.addEventListener("change", apply);
  form.addEventListener("submit", function (event) {
    // The catalog is filtered entirely in the page; a submit would only reload
    // the unfiltered document.
    event.preventDefault();
  });
  form.addEventListener("reset", function () {
    window.setTimeout(apply, 0);
  });
  apply();
})();
