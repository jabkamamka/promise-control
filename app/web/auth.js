/* Общая логика страниц входа и регистрации. */

const $ = (id) => document.getElementById(id);

function showError(message) {
  const box = $("error");
  if (!box) return;
  if (!message) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.hidden = false;
  box.textContent = message;
}

async function call(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `Ошибка ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : "Проверьте введённые данные");
  }
  return data;
}

function nextUrl() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  return next && next.startsWith("/") ? next : "/";
}

function setBusy(form, busy, label) {
  const button = form.querySelector("button[type=submit]");
  if (!button) return;
  if (!button.dataset.label) button.dataset.label = label || button.textContent;
  button.disabled = busy;
  button.textContent = busy ? "Подождите…" : button.dataset.label;
}

function switchTab(name) {
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  const linkForm = $("linkForm");
  const passwordForm = $("passwordForm");
  if (linkForm) linkForm.classList.toggle("auth-hidden", name !== "link");
  if (passwordForm) passwordForm.classList.toggle("auth-hidden", name !== "password");
  showError("");
}

function showCodeError() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("error") === "400") {
    showError("Ссылка недействительна или истекла — запросите новую.");
  }
}

function initAuthPage({ mode }) {
  if (mode === "login") {
    document.querySelectorAll(".auth-tab").forEach((tab) => {
      tab.addEventListener("click", () => switchTab(tab.dataset.tab));
    });
    showCodeError();

    const linkForm = $("linkForm");
    const sentBox = $("sentBox");
    const codeForm = $("codeForm");
    const emailInput = $("email");
    const nameInput = $("fullName");

    const send = async () => {
      showError("");
      setBusy(linkForm, true);
      try {
        const data = await call("/auth/email/start", {
          email: emailInput.value.trim(),
          full_name: nameInput.value.trim() || null,
        });
        $("sentEmail").textContent = data.email;
        $("sentEmail").title = data.email;
        const devRow = $("devRow");
        const devLink = $("devLink");
        if (data.dev_link) {
          devRow.hidden = false;
          devLink.href = data.dev_link;
          $("devCode").textContent = data.dev_code;
        } else {
          devRow.hidden = true;
        }
        linkForm.classList.add("auth-hidden");
        sentBox.classList.remove("auth-hidden");
        $("code").focus();
      } catch (error) {
        showError(error.message);
      } finally {
        setBusy(linkForm, false);
      }
    };

    linkForm.addEventListener("submit", (event) => {
      event.preventDefault();
      send();
    });

    codeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      showError("");
      setBusy(codeForm, true);
      try {
        await call("/auth/email/verify", {
          email: $("sentEmail").textContent.trim(),
          code: $("code").value.trim(),
        });
        window.location.href = nextUrl();
      } catch (error) {
        showError(error.message);
        setBusy(codeForm, false);
      }
    });

    $("again").addEventListener("click", () => {
      sentBox.classList.add("auth-hidden");
      linkForm.classList.remove("auth-hidden");
      $("code").value = "";
      emailInput.focus();
    });

    const passwordForm = $("passwordForm");
    passwordForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      showError("");
      setBusy(passwordForm, true);
      try {
        await call("/auth/login", {
          email: $("passwordEmail").value.trim(),
          password: $("password").value,
        });
        window.location.href = nextUrl();
      } catch (error) {
        showError(error.message);
        setBusy(passwordForm, false);
      }
    });
  }

  if (mode === "register") {
    const form = $("registerForm");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      showError("");
      setBusy(form, true);
      try {
        const data = await call("/auth/register", {
          email: $("email").value.trim(),
          password: $("password").value,
          full_name: $("fullName").value.trim(),
        });
        const box = $("confirmBox");
        $("confirmEmail").textContent = data.employee.email;
        const devLink = $("confirmDevLink");
        if (data.dev_link) {
          devLink.href = data.dev_link;
          devLink.parentElement.hidden = false;
        }
        form.classList.add("auth-hidden");
        box.classList.remove("auth-hidden");
      } catch (error) {
        showError(error.message);
      } finally {
        setBusy(form, false);
      }
    });

    const resend = $("confirmResend");
    if (resend) {
      resend.addEventListener("click", async () => {
        showError("");
        resend.disabled = true;
        try {
          await call("/auth/email/resend-confirm", { email: $("confirmEmail").textContent.trim() });
          resend.textContent = "Письмо отправлено ещё раз";
        } catch (error) {
          showError(error.message);
        } finally {
          resend.disabled = false;
        }
      });
    }
  }
}
