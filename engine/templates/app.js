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

/* Hardware catalog search/filter progressive enhancement.
   Same contract as the software list: the full catalog is server-rendered and
   this only narrows what is shown. The vendor chip row is a second control for
   the vendor select, kept in sync with it. */
(function () {
  "use strict";

  var body = document.getElementById("hardware-list");
  if (!body) return;

  var form = document.getElementById("hardware-filters");
  var query = document.getElementById("hw-filter-q");
  var vendor = document.getElementById("hw-filter-vendor");
  var status = document.getElementById("hw-filter-status");
  var sort = document.getElementById("hw-filter-sort");
  var count = document.getElementById("hardware-result-count");
  var empty = document.getElementById("hw-no-results");
  var chips = Array.prototype.slice.call(
    document.querySelectorAll("#hardware-vendor-chips .chip"));

  var rows = Array.prototype.slice.call(body.querySelectorAll(".hardware-row"));
  var total = rows.length;
  rows.forEach(function (row) {
    row.dataset.sortName = (row.querySelector(".hardware-name a").textContent || "").trim().toLowerCase();
  });

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function matches(row, text, vendorValue, statusValue) {
    if (text && row.dataset.search.indexOf(text) === -1) return false;
    if (vendorValue && row.dataset.vendor !== vendorValue) return false;
    if (statusValue && row.dataset.status !== statusValue) return false;
    return true;
  }

  function comparator(value) {
    function byName(a, b) {
      return a.dataset.sortName.localeCompare(b.dataset.sortName);
    }
    if (value === "vendor") {
      return function (a, b) {
        return a.dataset.vendor.localeCompare(b.dataset.vendor) || byName(a, b);
      };
    }
    if (value === "status") {
      return function (a, b) {
        return Number(a.dataset.statusOrder) - Number(b.dataset.statusOrder) || byName(a, b);
      };
    }
    if (value === "eol") {
      return function (a, b) {
        var left = a.dataset.eol || "9999-12-31";
        var right = b.dataset.eol || "9999-12-31";
        if (left !== right) return left < right ? -1 : 1;
        return byName(a, b);
      };
    }
    return byName;
  }

  function syncChips() {
    chips.forEach(function (chip) {
      var active = chip.dataset.vendor === vendor.value;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function apply(reorder) {
    // Filtering only toggles `hidden`; rows are re-inserted through a detached
    // fragment only when the sort order changes, so typing never moves 6910
    // nodes. Filtering is order-independent, so a hidden row can stay where it
    // is in the sorted sequence.
    var text = (query.value || "").trim().toLowerCase();
    var vendorValue = vendor.value;
    var statusValue = status.value;
    var shown = 0;

    rows.forEach(function (row) {
      var matched = matches(row, text, vendorValue, statusValue);
      row.hidden = !matched;
      if (matched) shown += 1;
    });

    if (reorder) {
      rows.slice().sort(comparator(sort.value)).forEach(function (row) {
        fragment.appendChild(row);
      });
      body.appendChild(fragment);
    }

    if (count) {
      var filtered = shown !== total;
      count.textContent = filtered
        ? "Showing " + plural(shown, "hardware record") + " of " + total
        : plural(total, "hardware record");
    }
    if (empty) empty.hidden = shown !== 0;
    syncChips();
    if (form) {
      var activeFilters = [query.value, vendorValue, statusValue].filter(Boolean).length;
      form.dataset.filtered = activeFilters ? "true" : "false";
    }
  }

  var fragment = document.createDocumentFragment();

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      vendor.value = vendor.value === chip.dataset.vendor ? "" : chip.dataset.vendor;
      apply(false);
    });
  });
  form.addEventListener("input", function () { apply(false); });
  form.addEventListener("change", function (event) {
    // The sort control is the only one that changes which row goes where.
    if (event.target === sort) apply(true);
    else apply(false);
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
  });
  form.addEventListener("reset", function () {
    window.setTimeout(function () { apply(true); }, 0);
  });
  apply(true);
})();

/* Catalog tabs on the homepage: two server-rendered panels, one visible. */
(function () {
  "use strict";

  var tablist = document.getElementById("catalog-tablist");
  if (!tablist) return;

  var tabs = Array.prototype.slice.call(tablist.querySelectorAll(".tab"));
  var panels = tabs.map(function (tab) {
    return document.getElementById(tab.getAttribute("aria-controls"));
  });

  function select(tab) {
    tabs.forEach(function (other, index) {
      var active = other === tab;
      other.setAttribute("aria-selected", active ? "true" : "false");
      other.setAttribute("tabindex", active ? "0" : "-1");
      panels[index].hidden = !active;
    });
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      select(tab);
    });
    tab.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      var next = tabs[(index + step + tabs.length) % tabs.length];
      next.focus();
      select(next);
    });
  });

  // Both panels are server-rendered and visible without JavaScript. With it,
  // only the active panel stays visible; #hardware opens the hardware tab, so
  // the tab is linkable.
  select(window.location.hash === "#hardware" ? tabs[tabs.length - 1] : tabs[0]);
})();
