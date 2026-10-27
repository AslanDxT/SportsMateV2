/* SportsMate - small progressive enhancements. Every page also works without JavaScript. */
(function () {
    "use strict";

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Show / hide password
    document.addEventListener("click", function (event) {
        var button = event.target.closest("[data-toggle-password]");
        if (!button) {
            return;
        }
        var input = document.getElementById(button.getAttribute("data-toggle-password"));
        if (!input) {
            return;
        }
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        button.textContent = show ? "Hide" : "Show";
        button.setAttribute("aria-pressed", show ? "true" : "false");
    });

    // Flash messages: close button, and success messages fade out by themselves
    function closeFlash(flash) {
        if (!flash || !flash.parentNode) {
            return;
        }
        if (reduceMotion) {
            flash.remove();
            return;
        }
        flash.classList.add("flash--leaving");
        setTimeout(function () { flash.remove(); }, 250);
    }

    document.addEventListener("click", function (event) {
        var close = event.target.closest(".flash__close");
        if (close) {
            closeFlash(close.closest(".flash"));
        }
    });

    document.querySelectorAll(".flash--success").forEach(function (flash) {
        setTimeout(function () { closeFlash(flash); }, 6000);
    });

    // Ask before destructive actions, and stop double submits
    document.addEventListener("submit", function (event) {
        var form = event.target;
        var question = form.getAttribute("data-confirm");
        if (question && !window.confirm(question)) {
            event.preventDefault();
            return;
        }
        if (form.method.toLowerCase() === "post") {
            if (form.dataset.submitting === "1") {
                event.preventDefault();
                return;
            }
            form.dataset.submitting = "1";
            form.querySelectorAll("button[type=submit]").forEach(function (button) {
                button.setAttribute("aria-disabled", "true");
                button.classList.add("is-busy");
            });
        }
    });

    // Pages restored from the back/forward cache: allow submitting again
    window.addEventListener("pageshow", function () {
        document.querySelectorAll("form[data-submitting]").forEach(function (form) {
            delete form.dataset.submitting;
            form.querySelectorAll(".is-busy").forEach(function (button) {
                button.classList.remove("is-busy");
                button.removeAttribute("aria-disabled");
            });
        });
    });

    // Account menu: close when clicking outside or pressing Escape
    var account = document.querySelector("details.account");
    if (account) {
        document.addEventListener("click", function (event) {
            if (account.open && !account.contains(event.target)) {
                account.open = false;
            }
        });
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && account.open) {
                account.open = false;
                account.querySelector("summary").focus();
            }
        });
    }

    // Character counters for long text fields
    document.querySelectorAll("textarea[data-counter][maxlength]").forEach(function (area) {
        var max = parseInt(area.getAttribute("maxlength"), 10);
        var counter = document.createElement("p");
        counter.className = "hint counter";
        counter.setAttribute("aria-live", "polite");
        area.insertAdjacentElement("afterend", counter);
        function update() {
            var left = max - area.value.length;
            counter.textContent = left + " characters left";
            counter.classList.toggle("counter--low", left < 50);
        }
        area.addEventListener("input", update);
        update();
    });

    // Chat: start at the newest message, grow the text box, Enter sends
    var log = document.getElementById("chat-log");
    if (log) {
        log.scrollTop = log.scrollHeight;
    }
    document.querySelectorAll("textarea[data-enter-submit]").forEach(function (area) {
        function grow() {
            area.style.height = "auto";
            area.style.height = Math.min(area.scrollHeight, 160) + "px";
        }
        area.addEventListener("input", grow);
        area.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                if (area.value.trim() !== "") {
                    area.form.requestSubmit();
                }
            }
        });
        grow();
        if (log) {
            area.focus();
        }
    });

    // Offline support (static files only, see service-worker.js)
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/service-worker.js").catch(function () {
                /* The site works fine without it. */
            });
        });
    }
})();
