/* Cabinet panels + forms wired to Host api/v3 */
(function () {
  const auth = () => window.ChelsyAuth;
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.cabinet-nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.cabinet-nav-item').forEach((b) => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        const id = btn.getAttribute('data-panel');
        document.querySelectorAll('.cabinet-panel').forEach((p) => {
          const on = p.id === 'panel-' + id;
          p.hidden = !on;
          p.classList.toggle('is-active', on);
        });
        if (id === 'files') loadFiles();
        if (id === 'security') loadSessions();
      });
    });
    const profile = document.getElementById('profile-form');
    profile?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const status = document.getElementById('profile-status');
      try {
        const fd = new FormData(profile);
        await auth().api('/api/v3/me', {
          method: 'POST',
          body: {
            display_name: fd.get('display_name'),
            locale: fd.get('locale'),
            timezone: fd.get('timezone'),
          },
        });
        status.textContent = 'Сохранено на сервере.';
        status.classList.add('auth-message-success');
      } catch (err) {
        status.textContent = err.message || 'Ошибка сохранения';
      }
    });
    document.getElementById('password-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.target;
      const status = document.getElementById('password-status');
      try {
        const data = await auth().api('/api/v3/me/password', {
          method: 'POST',
          body: {
            current_password: form.current_password.value,
            new_password: form.new_password.value,
          },
        });
        auth().saveTokens(data);
        status.textContent = 'Пароль изменён, старые сессии отозваны.';
        status.classList.add('auth-message-success');
      } catch (err) {
        status.textContent = err.message || 'Не удалось сменить пароль';
      }
    });
    document.getElementById('email-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.target;
      const status = document.getElementById('email-status');
      try {
        await auth().api('/api/v3/me/email', {
          method: 'POST',
          body: { password: form.password.value, new_email: form.new_email.value },
        });
        auth().clearTokens();
        status.textContent = 'Email изменён. Войдите снова.';
        location.href = 'login.html';
      } catch (err) {
        status.textContent = err.message || 'Не удалось сменить email';
      }
    });
    document.getElementById('revoke-other-sessions')?.addEventListener('click', async () => {
      if (!confirm('Завершить все другие сессии?')) return;
      await auth().api('/api/v3/me/sessions', { method: 'DELETE' });
      loadSessions();
    });
    document.getElementById('memory-enabled')?.addEventListener('change', async (e) => {
      await auth().api('/api/v3/me', { method: 'POST', body: { memory_enabled: e.target.checked } });
    });
  });

  async function loadFiles() {
    const box = document.getElementById('files-list');
    if (!box) return;
    try {
      const data = await auth().api('/api/v3/artifacts');
      const items = data.artifacts || [];
      if (!items.length) { box.textContent = 'Файлов пока нет.'; return; }
      box.innerHTML = items.map((a) =>
        `<div class="file-row"><strong>${escapeHtml(a.title || a.filename)}</strong> · ${a.format} · ${a.size_bytes} байт · ${a.created}` +
        ` <a href="#" data-id="${a.id}" class="dl">Скачать</a></div>`
      ).join('');
      box.querySelectorAll('a.dl').forEach((a) => a.addEventListener('click', async (ev) => {
        ev.preventDefault();
        const id = a.getAttribute('data-id');
        const token = sessionStorage.getItem('chelsy_access');
        const base = (window.CHELSY_CONFIG?.apiBase || '').replace(/\/$/, '');
        const resp = await fetch(base + '/api/v3/artifacts/' + id + '/download', {
          headers: { Authorization: 'Bearer ' + token }, credentials: 'include',
        });
        if (!resp.ok) { alert('Скачивание отклонено'); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url; link.download = 'chelsy-file'; link.click();
        URL.revokeObjectURL(url);
      }));
    } catch (err) {
      box.textContent = 'Host недоступен или нет сессии — файлы не удалены.';
    }
  }

  async function loadSessions() {
    const box = document.getElementById('sessions-list');
    if (!box) return;
    try {
      const data = await auth().api('/api/v3/me/sessions');
      box.innerHTML = (data.sessions || []).map((s) =>
        `<div>${escapeHtml(s.device_label || 'устройство')} · ${s.last_seen} · ${s.revoked ? 'отозвана' : 'активна'}` +
        (s.revoked ? '' : ` <button type="button" data-sid="${s.id}" class="btn btn-small">Завершить</button>`) +
        `</div>`
      ).join('') || 'Нет сессий';
      box.querySelectorAll('button[data-sid]').forEach((btn) => btn.addEventListener('click', async () => {
        await auth().api('/api/v3/me/sessions/' + btn.getAttribute('data-sid'), { method: 'DELETE' });
        loadSessions();
      }));
    } catch (_) {
      box.textContent = 'Не удалось загрузить сессии';
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
})();
