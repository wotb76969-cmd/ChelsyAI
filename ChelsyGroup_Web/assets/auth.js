/* Chelsy Group 0.9.4: own Host Auth (cookie + Bearer). No Supabase / jsDelivr. */
(function () {
  const config = window.CHELSY_CONFIG || {};
  const apiBase = (config.apiBase || '').replace(/\/$/, '');
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const setStatus = (element, message, success = false) => {
    if (!element) return;
    element.textContent = message;
    element.hidden = !message;
    element.classList.toggle('auth-message-success', !!success);
  };
  function stopSubmit(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.classList.toggle('is-busy', busy);
  }
  function api(path, options = {}) {
    const headers = Object.assign({ 'Accept': 'application/json' }, options.headers || {});
    if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const token = sessionStorage.getItem('chelsy_access') || '';
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(apiBase + path, {
      method: options.method || 'GET',
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: 'include',
    }).then(async (resp) => {
      let data = null;
      try { data = await resp.json(); } catch (_) { data = null; }
      if (!resp.ok) {
        const err = new Error((data && (data.message || data.error)) || ('HTTP ' + resp.status));
        err.status = resp.status;
        err.data = data;
        throw err;
      }
      return data;
    });
  }
  function saveTokens(data) {
    if (data.access_token) sessionStorage.setItem('chelsy_access', data.access_token);
    if (data.refresh_token) sessionStorage.setItem('chelsy_refresh', data.refresh_token);
  }
  function clearTokens() {
    sessionStorage.removeItem('chelsy_access');
    sessionStorage.removeItem('chelsy_refresh');
  }
  async function refreshIfNeeded() {
    const refresh = sessionStorage.getItem('chelsy_refresh');
    if (!refresh) return null;
    try {
      const data = await api('/api/v3/auth/refresh', { method: 'POST', body: { refresh_token: refresh } });
      saveTokens(data);
      return data.user;
    } catch (_) {
      clearTokens();
      return null;
    }
  }
  async function currentUser() {
    if (!sessionStorage.getItem('chelsy_access')) {
      return refreshIfNeeded();
    }
    try {
      const data = await api('/api/v3/me');
      return data.user;
    } catch (_) {
      return refreshIfNeeded();
    }
  }
  async function updateHeader() {
    const user = await currentUser();
    if (user) document.querySelectorAll('a.header-login').forEach((link) => {
      link.href = 'account.html';
      link.textContent = 'Личный кабинет';
    });
  }
  async function handleLogin(form) {
    const status = $('#login-status');
    const submit = form.querySelector('[type=submit]');
    if (!form.checkValidity()) { form.reportValidity(); return; }
    stopSubmit(submit, true); setStatus(status, '');
    try {
      const data = await api('/api/v3/auth/login', {
        method: 'POST',
        body: {
          email: String(form.elements.email.value).trim().toLowerCase(),
          password: form.elements.password.value,
          device_label: 'web-cabinet',
        },
      });
      saveTokens(data);
      setStatus(status, 'Вход выполнен.', true);
      location.href = 'account.html';
    } catch (error) {
      setStatus(status, error.message || 'Не удалось войти');
    } finally {
      stopSubmit(submit, false);
    }
  }
  async function handleRegister(form) {
    const status = $('#register-status');
    const submit = form.querySelector('[type=submit]');
    const password = form.elements.password?.value || '';
    const confirm = form.elements.password_confirm?.value || '';
    if (!form.checkValidity()) { form.reportValidity(); return; }
    if (password.length < 15) { setStatus(status, 'Пароль должен содержать минимум 15 символов.'); return; }
    if (password !== confirm) { setStatus(status, 'Пароли не совпадают.'); return; }
    if (form.elements.consent && !form.elements.consent.checked) {
      setStatus(status, 'Требуется согласие с политикой обработки данных.'); return;
    }
    stopSubmit(submit, true); setStatus(status, '');
    try {
      const data = await api('/api/v3/auth/register', {
        method: 'POST',
        body: {
          email: String(form.elements.email.value).trim().toLowerCase(),
          password,
          display_name: String(form.elements.name?.value || '').trim(),
        },
      });
      saveTokens(data);
      setStatus(status, 'Аккаунт создан.', true);
      location.href = 'account.html';
    } catch (error) {
      setStatus(status, error.message || 'Регистрация недоступна. Обратитесь к администратору Host.');
    } finally {
      stopSubmit(submit, false);
    }
  }
  async function handleAccount() {
    const status = $('#account-status');
    const content = $('#account-content');
    try {
      const user = await currentUser();
      if (!user) {
        setStatus(status, 'Нужен вход.');
        location.href = 'login.html';
        return;
      }
      if ($('#account-name')) $('#account-name').textContent = user.display_name || '—';
      if ($('#account-email')) $('#account-email').textContent = user.email || '—';
      if ($('#account-plan')) $('#account-plan').textContent = 'Квоты выдаёт Host (не подписка)';
      if ($('#account-verified')) $('#account-verified').textContent = user.email_verified ? 'Да' : 'Ожидает подтверждения';
      if (content) content.hidden = false;
      setStatus(status, '');
      // Cabinet overview
      try {
        const overview = await api('/api/v3/cabinet/overview');
        const box = $('#cabinet-overview');
        if (box) {
          box.hidden = false;
          box.innerHTML = '<ul class="account-details">' +
            `<li><span>Host</span><strong>${overview.host?.version || '—'} · Ollama ${overview.host?.ollama ? 'да' : 'нет'}</strong></li>` +
            `<li><span>Активные задачи</span><strong>${overview.tasks_active}</strong></li>` +
            `<li><span>Файлы</span><strong>${overview.files_count} (${Math.round((overview.files_bytes || 0) / 1024)} КБ)</strong></li>` +
            `<li><span>Квота</span><strong>${overview.quota_mb_used}/${overview.quota_mb_limit} МБ</strong></li>` +
            '</ul>';
        }
      } catch (_) { /* host may be unreachable — do not pretend history deleted */ }
    } catch (error) {
      setStatus(status, error.message || 'Ошибка загрузки профиля');
    }
    $('#signout-button')?.addEventListener('click', async () => {
      try { await api('/api/v3/auth/logout', { method: 'POST', body: {} }); } catch (_) {}
      clearTokens();
      location.href = 'login.html';
    });
  }
  document.addEventListener('DOMContentLoaded', () => {
    updateHeader();
    const login = $('#login-form');
    if (login) login.addEventListener('submit', (e) => { e.preventDefault(); handleLogin(login); });
    const register = $('#register-form');
    if (register) register.addEventListener('submit', (e) => { e.preventDefault(); handleRegister(register); });
    if ($('#account-content') || $('#account-status')) handleAccount();
  });
  window.ChelsyAuth = { api, currentUser, saveTokens, clearTokens };
})();
