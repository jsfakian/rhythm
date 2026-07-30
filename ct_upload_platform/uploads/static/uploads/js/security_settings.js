const PAGE_DATA = JSON.parse(document.getElementById('security-settings-data').textContent);
const csrftoken = PAGE_DATA.csrf_token;

function showError(msg) {
    const el = document.getElementById('errorMessage');
    el.textContent = msg;
    el.style.display = 'block';
    document.getElementById('successMessage').style.display = 'none';
}
function showSuccess(msg) {
    const el = document.getElementById('successMessage');
    el.textContent = msg;
    el.style.display = 'block';
    document.getElementById('errorMessage').style.display = 'none';
}

document.getElementById('startSetupBtn').addEventListener('click', async () => {
    try {
        const res = await fetch('/account/security/2fa/setup/', {
            method: 'POST',
            headers: {'X-CSRFToken': csrftoken},
        });
        const data = await res.json();
        if (!res.ok) { showError(data.error || 'Could not start 2FA setup.'); return; }

        document.getElementById('qrImage').src = data.qr_data_uri;
        document.getElementById('secretKey').textContent = data.secret;
        document.getElementById('setupPanel').style.display = 'block';
        document.getElementById('startSetupBtn').style.display = 'none';
    } catch (e) {
        showError('Network error. Please try again.');
    }
});

document.getElementById('confirmSetupBtn').addEventListener('click', async () => {
    const code = document.getElementById('confirmCode').value.trim();
    try {
        const res = await fetch('/account/security/2fa/confirm/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrftoken},
            body: JSON.stringify({code}),
        });
        const data = await res.json();
        if (!res.ok) { showError(data.error || 'Invalid code.'); return; }

        showSuccess(data.message);
        document.getElementById('disabledPanel').style.display = 'none';
        document.getElementById('enabledPanel').style.display = 'block';
    } catch (e) {
        showError('Network error. Please try again.');
    }
});
