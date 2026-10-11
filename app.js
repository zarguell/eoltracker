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
   the vendor select, and the catalog chip row a second control for the catalog
   select, each kept in sync with its select. */
(function () {
  "use strict";

  var body = document.getElementById("hardware-list");
  if (!body) return;

  var form = document.getElementById("hardware-filters");
  var query = document.getElementById("hw-filter-q");
  var vendor = document.getElementById("hw-filter-vendor");
  var status = document.getElementById("hw-filter-status");
  var catalog = document.getElementById("hw-filter-catalog");
  var sort = document.getElementById("hw-filter-sort");
  var count = document.getElementById("hardware-result-count");
  var empty = document.getElementById("hw-no-results");
  var vendorChips = Array.prototype.slice.call(
    document.querySelectorAll("#hardware-vendor-chips .chip"));
  var catalogChips = Array.prototype.slice.call(
    document.querySelectorAll("#hardware-catalog-chips .chip"));
  var pagination = document.getElementById("hardware-pagination");
  var previousPage = document.getElementById("hardware-prev");
  var nextPage = document.getElementById("hardware-next");
  var pageLabel = document.getElementById("hardware-page-label");
  var page = 0;
  var PAGE_SIZE = 200;

  // One plain-JavaScript record per row, holding every value the filters and
  // the comparators need, read from the DOM once. Reading `dataset` inside a
  // comparator went through the DOM string map on both sides of every one of
  // the roughly 90,000 comparisons a sort of 6999 rows makes, and again once
  // per row on every keystroke; these fields turn both into array access.
  var records = Array.prototype.slice.call(body.querySelectorAll(".hardware-row"))
    .map(function (row) {
      return {
        node: row,
        id: row.id,
        hidden: row.hidden,
        name: (row.querySelector(".hardware-name a").textContent || "").trim().toLowerCase(),
        search: row.dataset.search,
        vendor: row.dataset.vendor,
        status: row.dataset.status,
        catalog: row.dataset.catalog,
        statusOrder: Number(row.dataset.statusOrder),
        catalogOrder: Number(row.dataset.catalogOrder),
        eol: row.dataset.eol || "9999-12-31"
      };
    });
  records.forEach(function (record) {
    record.node.style.contentVisibility = "auto";
    record.node.style.containIntrinsicSize = "0 3.5rem";
    record.node.style.contain = "strict";
  });
  var total = records.length;
  // The order the document currently shows, one entry per record. Filtering
  // never changes it, and `setOrder` rewrites it only when it actually moves
  // rows, so it stays the truth about where each row sits.
  var order = records.slice();
  var sortedOrders = {};

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function matches(record, text, vendorValue, statusValue, catalogValue) {
    if (text && record.search.indexOf(text) === -1) return false;
    if (vendorValue && record.vendor !== vendorValue) return false;
    if (statusValue && record.status !== statusValue) return false;
    if (catalogValue === "lifecycle-row") {
      // A lifecycle row is one with no catalog state of its own: notice-table
      // records, which carry dates rather than a listing.
      if (record.catalog) return false;
    } else if (catalogValue && record.catalog !== catalogValue) {
      return false;
    }
    return true;
  }

  function comparator(value) {
    function byName(a, b) {
      return a.name.localeCompare(b.name);
    }
    if (value === "vendor") {
      return function (a, b) {
        return a.vendor.localeCompare(b.vendor) || byName(a, b);
      };
    }
    if (value === "status") {
      // Records with no status of their own sort last: the unknown key is
      // deliberately outside the documented status order.
      return function (a, b) {
        return a.statusOrder - b.statusOrder || byName(a, b);
      };
    }
    if (value === "catalog") {
      return function (a, b) {
        return a.catalogOrder - b.catalogOrder || byName(a, b);
      };
    }
    if (value === "eol") {
      return function (a, b) {
        if (a.eol !== b.eol) return a.eol < b.eol ? -1 : 1;
        return byName(a, b);
      };
    }
    return byName;
  }

  function syncChips(chips, control, key) {
    chips.forEach(function (chip) {
      var active = chip.dataset[key] === control.value;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  // The sorted order for a sort key, built once and reused: re-selecting a sort
  // already visited costs no comparisons, and the sort itself is pure
  // JavaScript over `records`.
  function sortedOrder(value) {
    if (!sortedOrders[value]) {
      var next = records.slice();
      next.sort(comparator(value));
      sortedOrders[value] = next;
    }
    return sortedOrders[value];
  }

  // Keep the complete data set in JavaScript, but render only one bounded page
  // of rows. Reordering 6,999 table rows forces a full table layout; moving at
  // most PAGE_SIZE visible rows keeps filters and sorts responsive while the
  // pagination controls expose the rest of the catalog.
  function renderPage(next, resetPage) {
    if (resetPage) page = 0;
    var text = (query.value || "").trim().toLowerCase();
    var vendorValue = vendor.value;
    var statusValue = status.value;
    var catalogValue = catalog ? catalog.value : "";
    var matching = next.filter(function (record) {
      return matches(record, text, vendorValue, statusValue, catalogValue);
    });
    var pages = Math.max(1, Math.ceil(matching.length / PAGE_SIZE));
    if (page >= pages) page = pages - 1;
    var visible = matching.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    var visibleRecords = visible.slice();

    records.forEach(function (record) {
      var shouldHide = visibleRecords.indexOf(record) === -1;
      if (record.hidden !== shouldHide) {
        record.hidden = shouldHide;
        record.node.hidden = shouldHide;
      }
    });
    var fragment = document.createDocumentFragment();
    visible.forEach(function (record) { fragment.appendChild(record.node); });
    body.appendChild(fragment);

    if (count) {
      if (pages > 1) {
        count.textContent = "Showing " + plural(visible.length, "hardware record") +
          " of " + matching.length + " (page " + (page + 1) + " of " + pages + ")";
      } else if (matching.length !== total) {
        count.textContent = "Showing " + plural(matching.length, "hardware record") + " of " + total;
      } else {
        count.textContent = plural(total, "hardware record");
      }
    }
    if (empty) empty.hidden = matching.length !== 0;
    if (pagination) pagination.hidden = pages <= 1;
    if (pageLabel) pageLabel.textContent = "Page " + (page + 1) + " of " + pages;
    if (previousPage) previousPage.disabled = page === 0;
    if (nextPage) nextPage.disabled = page >= pages - 1;
    syncChips(vendorChips, vendor, "vendor");
    if (catalog) syncChips(catalogChips, catalog, "catalog");
    if (form) {
      var activeFilters = [query.value, vendorValue, statusValue, catalogValue].filter(Boolean).length;
      form.dataset.filtered = activeFilters ? "true" : "false";
    }
  }

  function apply(reorder, resetPage) {
    var next = reorder ? sortedOrder(sort.value) : order;
    if (reorder) order = next;
    renderPage(next, resetPage !== false);
  }

  vendorChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      vendor.value = vendor.value === chip.dataset.vendor ? "" : chip.dataset.vendor;
      apply(false, true);
    });
  });
  catalogChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      if (!catalog) return;
      catalog.value = catalog.value === chip.dataset.catalog ? "" : chip.dataset.catalog;
      apply(false, true);
    });
  });
  form.addEventListener("input", function () { apply(false, true); });
  form.addEventListener("change", function (event) {
    // The sort control is the only one that changes which row goes where.
    if (event.target === sort) apply(true, true);
    else apply(false, true);
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
  });
  form.addEventListener("reset", function () {
    window.setTimeout(function () { apply(true, true); }, 0);
  });
  if (previousPage) previousPage.addEventListener("click", function () {
    if (page > 0) { page -= 1; renderPage(order, false); }
  });
  if (nextPage) nextPage.addEventListener("click", function () {
    page += 1; renderPage(order, false);
  });
  apply(true, true);
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
