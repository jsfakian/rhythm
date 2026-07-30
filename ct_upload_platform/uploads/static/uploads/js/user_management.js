    const PAGE_DATA = JSON.parse(document.getElementById('user-management-data').textContent);
    const CSRF = PAGE_DATA.csrf_token;
    let pendingUserId = null;
    let pendingUsername = null;

    // ── Stats ──────────────────────────────────────────────────────
    function refreshStats() {
        const rows = document.querySelectorAll('#users-tbody tr[data-user-id]');
        let active = 0, staff = 0, su = 0, pending = 0;
        rows.forEach(r => {
            if (r.dataset.isActive === 'true') active++;
            if (r.dataset.isStaff === 'true') staff++;
            if (r.dataset.isSuperuser === 'true') su++;
            if (r.dataset.isActive === 'false' && r.dataset.emailVerified === 'false') pending++;
        });
        document.getElementById('stat-total').textContent = rows.length;
        document.getElementById('stat-active').textContent = active;
        document.getElementById('stat-staff').textContent = staff;
        document.getElementById('stat-superuser').textContent = su;
        document.getElementById('stat-pending').textContent = pending;
    }

    // ── Toast ──────────────────────────────────────────────────────
    function showToast(msg, type = 'success') {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.className = `toast toast-${type}`;
        clearTimeout(t._timer);
        t._timer = setTimeout(() => t.classList.add('hidden'), 3500);
    }

    // ── Modal helpers ──────────────────────────────────────────────
    function openModal(id) { document.getElementById(id).classList.add('open'); }
    function closeModal(id) { document.getElementById(id).classList.remove('open'); }

    document.querySelectorAll('.modal-overlay').forEach(m => {
        m.addEventListener('click', e => { if (e.target === m) m.classList.remove('open'); });
    });

    // ── Toggle active ──────────────────────────────────────────────
    async function toggleActive(userId) {
        const res = await apiPost(`/users/api/${userId}/update/`, { action: 'toggle_active' });
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) { showToast(data.error, 'error'); return; }
        const row = document.getElementById(`user-row-${userId}`);
        const isActive = data.is_active;
        row.dataset.isActive = isActive ? 'true' : 'false';
        const emailVerified = row.dataset.emailVerified === 'true';
        const cell = row.querySelector('.cell-active');
        if (isActive) {
            cell.innerHTML = '<span class="badge badge-active">Active</span>';
        } else if (!emailVerified) {
            cell.innerHTML = '<span class="badge badge-pending">Pending verification</span>';
        } else {
            cell.innerHTML = '<span class="badge badge-inactive">Inactive</span>';
        }
        const btn = row.querySelector('[data-action="toggle-active"]');
        btn.textContent = isActive ? 'Deactivate' : 'Activate';
        btn.className = `toggle-btn ${isActive ? 'toggle-btn-active' : 'toggle-btn-inactive'}`;
        refreshStats();
        showToast(`User ${isActive ? 'activated' : 'deactivated'}.`);
    }

    // ── Send verification email ────────────────────────────────────
    async function sendVerificationEmail(userId) {
        const btn = document.querySelector(`#user-row-${userId} [data-action="send-verification"]`);
        if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
        const res = await apiPost(`/users/api/${userId}/update/`, { action: 'send_verification_email' });
        const data = res.ok ? await res.json() : {};
        if (btn) { btn.disabled = false; btn.textContent = 'Send Verification Email'; }
        if (!res.ok || data.error) return;
        showToast('Verification email sent.');
    }

    // ── Toggle staff ───────────────────────────────────────────────
    async function toggleStaff(userId) {
        const res = await apiPost(`/users/api/${userId}/update/`, { action: 'toggle_staff' });
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) { showToast(data.error, 'error'); return; }
        const row = document.getElementById(`user-row-${userId}`);
        const isStaff = data.is_staff;
        row.dataset.isStaff = isStaff ? 'true' : 'false';
        const cell = row.querySelector('.cell-staff');
        cell.innerHTML = isStaff
            ? '<span class="badge badge-staff">Staff</span>'
            : '<span class="badge" style="background:#f2f3f4;color:#7f8c8d;">No</span>';
        const btn = row.querySelector('[data-action="toggle-staff"]');
        btn.textContent = isStaff ? 'Revoke Staff' : 'Grant Staff';
        btn.className = `toggle-btn ${isStaff ? 'toggle-btn-staff' : 'toggle-btn-nostaff'}`;
        refreshStats();
        showToast(`Staff access ${isStaff ? 'granted' : 'revoked'}.`);
    }

    // ── Reset password modal ───────────────────────────────────────
    function openPasswordModal(userId, username) {
        pendingUserId = userId;
        document.getElementById('pw-modal-username').textContent = username;
        document.getElementById('pw-new').value = '';
        document.getElementById('pw-confirm').value = '';
        document.getElementById('pw-error').style.display = 'none';
        openModal('password-modal');
        setTimeout(() => document.getElementById('pw-new').focus(), 80);
    }

    async function submitPassword() {
        const pw = document.getElementById('pw-new').value.trim();
        const pw2 = document.getElementById('pw-confirm').value.trim();
        const errEl = document.getElementById('pw-error');
        errEl.style.display = 'none';

        if (!pw) { errEl.textContent = 'Password is required.'; errEl.style.display = 'block'; return; }
        if (pw.length < 8) { errEl.textContent = 'Password must be at least 8 characters.'; errEl.style.display = 'block'; return; }
        if (pw !== pw2) { errEl.textContent = 'Passwords do not match.'; errEl.style.display = 'block'; return; }

        const btn = document.getElementById('pw-submit-btn');
        btn.disabled = true; btn.textContent = 'Saving…';
        const res = await apiPost(`/users/api/${pendingUserId}/update/`, { action: 'set_password', password: pw });
        btn.disabled = false; btn.textContent = 'Update Password';
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) { errEl.textContent = data.error; errEl.style.display = 'block'; return; }
        closeModal('password-modal');
        showToast('Password updated successfully.');
    }

    // ── Delete modal ───────────────────────────────────────────────
    function confirmDelete(userId, username) {
        pendingUserId = userId;
        pendingUsername = username;
        document.getElementById('delete-modal-username').textContent = username;
        openModal('delete-modal');
    }

    async function submitDelete() {
        const btn = document.getElementById('delete-confirm-btn');
        btn.disabled = true; btn.textContent = 'Deleting…';
        const res = await apiPost(`/users/api/${pendingUserId}/delete/`, {});
        btn.disabled = false; btn.textContent = 'Delete';
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) { showToast(data.error, 'error'); closeModal('delete-modal'); return; }
        closeModal('delete-modal');
        const row = document.getElementById(`user-row-${pendingUserId}`);
        if (row) row.remove();
        refreshStats();
        showToast(`User "${data.deleted}" deleted.`);
    }

    // ── Create user modal ──────────────────────────────────────────
    function openCreateModal() {
        document.getElementById('create-username').value = '';
        document.getElementById('create-password').value = '';
        document.getElementById('create-email').value = '';
        document.getElementById('create-firstname').value = '';
        document.getElementById('create-lastname').value = '';
        document.getElementById('create-institution').value = '';
        document.getElementById('create-department').value = '';
        document.getElementById('create-is-staff').checked = false;
        document.getElementById('create-error').style.display = 'none';
        openModal('create-modal');
        setTimeout(() => document.getElementById('create-username').focus(), 80);
    }

    async function submitCreate() {
        const errEl = document.getElementById('create-error');
        errEl.style.display = 'none';
        const payload = {
            username:   document.getElementById('create-username').value.trim(),
            password:   document.getElementById('create-password').value.trim(),
            email:      document.getElementById('create-email').value.trim(),
            first_name: document.getElementById('create-firstname').value.trim(),
            last_name:  document.getElementById('create-lastname').value.trim(),
            institution: document.getElementById('create-institution').value.trim(),
            department:  document.getElementById('create-department').value.trim(),
            is_staff:   document.getElementById('create-is-staff').checked,
        };
        if (!payload.username) { errEl.textContent = 'Username is required.'; errEl.style.display = 'block'; return; }
        if (!payload.password) { errEl.textContent = 'Password is required.'; errEl.style.display = 'block'; return; }
        if (!payload.institution) { errEl.textContent = 'Institution is required.'; errEl.style.display = 'block'; return; }

        const btn = document.getElementById('create-submit-btn');
        btn.disabled = true; btn.textContent = 'Creating…';
        const res = await apiPost('/users/api/create/', payload);
        btn.disabled = false; btn.textContent = 'Create User';
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) { errEl.textContent = data.error; errEl.style.display = 'block'; return; }

        closeModal('create-modal');
        appendUserRow(data);
        refreshStats();
        showToast(`User "${data.username}" created.`);
    }

    function appendUserRow(u) {
        const tbody = document.getElementById('users-tbody');
        const emptyRow = document.getElementById('empty-row');
        if (emptyRow) emptyRow.remove();

        const tr = document.createElement('tr');
        tr.id = `user-row-${u.id}`;
        tr.dataset.userId = u.id;
        tr.dataset.username = u.username;
        tr.dataset.isActive = 'true';
        tr.dataset.isStaff = u.is_staff ? 'true' : 'false';
        tr.dataset.isSuperuser = 'false';
        tr.dataset.emailVerified = 'true';

        const staffBadge = u.is_staff
            ? '<span class="badge badge-staff">Staff</span>'
            : '<span class="badge" style="background:#f2f3f4;color:#7f8c8d;">No</span>';

        tr.innerHTML = `
            <td><strong>${escHtml(u.username)}</strong></td>
            <td>${escHtml(u.first_name)} ${escHtml(u.last_name)}</td>
            <td>${escHtml(u.email) || '—'}</td>
            <td>${escHtml(u.institution) || '—'}${u.site_code ? ` <span style="font-size:11px;font-weight:600;color:#fff;background:#1e3a5f;border-radius:5px;padding:1px 6px;margin-left:4px;">${escHtml(u.site_code)}</span>` : ''}</td>
            <td>—</td>
            <td class="cell-active"><span class="badge badge-active">Active</span></td>
            <td class="cell-staff">${staffBadge}</td>
            <td>${escHtml(u.date_joined)}</td>
            <td>
                <div class="actions-cell">
                    <button class="toggle-btn toggle-btn-active" data-action="toggle-active" title="Deactivate account">Deactivate</button>
                    <button class="toggle-btn ${u.is_staff ? 'toggle-btn-staff' : 'toggle-btn-nostaff'}"
                            data-action="toggle-staff">${u.is_staff ? 'Revoke Staff' : 'Grant Staff'}</button>
                    <button class="btn btn-secondary btn-sm" data-action="open-password">Reset PW</button>
                    <button class="btn btn-danger btn-sm" data-action="confirm-delete">Delete</button>
                </div>
            </td>`;
        tbody.appendChild(tr);
    }

    // ── Helpers ────────────────────────────────────────────────────
    async function apiPost(url, payload) {
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                showToast(data.error || `Server error (${res.status})`, 'error');
            }
            return res;
        } catch (e) {
            showToast('Network error — please try again.', 'error');
            return { ok: false };
        }
    }

    function escHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    // ── Event wiring (CSP-compliant: no inline handlers) ────────────
    document.getElementById('add-user-btn').addEventListener('click', openCreateModal);
    document.getElementById('create-submit-btn').addEventListener('click', submitCreate);
    document.getElementById('pw-submit-btn').addEventListener('click', submitPassword);
    document.getElementById('delete-confirm-btn').addEventListener('click', submitDelete);

    document.querySelectorAll('[data-close-modal]').forEach(btn => {
        btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
    });

    document.getElementById('users-tbody').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const row = btn.closest('tr[data-user-id]');
        if (!row) return;
        const userId = row.dataset.userId;
        const username = row.dataset.username;
        switch (btn.dataset.action) {
            case 'send-verification': sendVerificationEmail(userId); break;
            case 'toggle-active': toggleActive(userId); break;
            case 'toggle-staff': toggleStaff(userId); break;
            case 'open-password': openPasswordModal(userId, username); break;
            case 'confirm-delete': confirmDelete(userId, username); break;
        }
    });

    // ── Init ───────────────────────────────────────────────────────
    refreshStats();
