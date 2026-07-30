const loginForm = document.getElementById('loginForm');
const loginBtn = document.getElementById('loginBtn');
const totpForm = document.getElementById('totpForm');
const totpBtn = document.getElementById('totpBtn');
const enrollPanel = document.getElementById('enrollPanel');
const enrollForm = document.getElementById('enrollForm');
const enrollBtn = document.getElementById('enrollBtn');
const errorMessage = document.getElementById('errorMessage');
const successMessage = document.getElementById('successMessage');

function onAuthenticated(data) {
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data));

    successMessage.textContent = `Welcome ${data.username}! Redirecting...`;
    successMessage.classList.add('show');

    setTimeout(() => {
        window.location.href = '/';
    }, 2000);
}

function hideAuxLinks() {
    document.getElementById('forgotPasswordLink').style.display = 'none';
    document.getElementById('signupDivider').style.display = 'none';
    document.getElementById('signupPrompt').style.display = 'none';
}

function showTotpStep() {
    loginForm.style.display = 'none';
    hideAuxLinks();
    totpForm.style.display = 'block';
    document.getElementById('totpCode').focus();
}

async function showEnrollStep() {
    loginForm.style.display = 'none';
    hideAuxLinks();

    try {
        const response = await fetch('/api/v1/auth/enroll-2fa/initiate/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await response.json();

        if (!response.ok) {
            errorMessage.textContent = data.error || 'Could not start 2FA setup. Please sign in again.';
            errorMessage.classList.add('show');
            loginForm.style.display = 'block';
            return;
        }

        document.getElementById('enrollQrImage').src = data.qr_data_uri;
        document.getElementById('enrollSecretKey').textContent = data.secret;
        enrollPanel.style.display = 'block';
        document.getElementById('enrollCode').focus();
    } catch (error) {
        errorMessage.textContent = 'Network error. Please try again.';
        errorMessage.classList.add('show');
        loginForm.style.display = 'block';
        console.error('2FA enrollment start error:', error);
    }
}

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    errorMessage.classList.remove('show');
    successMessage.classList.remove('show');

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    loginBtn.disabled = true;
    const originalText = loginBtn.innerHTML;
    loginBtn.innerHTML = '<span class="loading"></span> Signing in...';

    try {
        const response = await fetch('/api/v1/auth/login/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                username: username,
                password: password,
            }),
        });

        const data = await response.json();

        if (response.ok && data.requires_2fa) {
            loginBtn.disabled = false;
            loginBtn.innerHTML = originalText;
            showTotpStep();
        } else if (response.ok && data.requires_2fa_setup) {
            loginBtn.disabled = false;
            loginBtn.innerHTML = originalText;
            showEnrollStep();
        } else if (response.ok) {
            onAuthenticated(data);
        } else {
            errorMessage.textContent = data.error || 'Login failed. Please try again.';
            errorMessage.classList.add('show');
            loginBtn.disabled = false;
            loginBtn.innerHTML = originalText;
        }
    } catch (error) {
        errorMessage.textContent = 'Network error. Please try again.';
        errorMessage.classList.add('show');
        loginBtn.disabled = false;
        loginBtn.innerHTML = originalText;
        console.error('Login error:', error);
    }
});

totpForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    errorMessage.classList.remove('show');
    successMessage.classList.remove('show');

    const code = document.getElementById('totpCode').value.trim();

    totpBtn.disabled = true;
    const originalText = totpBtn.innerHTML;
    totpBtn.innerHTML = '<span class="loading"></span> Verifying...';

    try {
        const response = await fetch('/api/v1/auth/verify-2fa/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ code: code }),
        });

        const data = await response.json();

        if (response.ok) {
            onAuthenticated(data);
        } else {
            errorMessage.textContent = data.error || 'Invalid code. Please try again.';
            errorMessage.classList.add('show');
            totpBtn.disabled = false;
            totpBtn.innerHTML = originalText;
            document.getElementById('totpCode').value = '';
            document.getElementById('totpCode').focus();
        }
    } catch (error) {
        errorMessage.textContent = 'Network error. Please try again.';
        errorMessage.classList.add('show');
        totpBtn.disabled = false;
        totpBtn.innerHTML = originalText;
        console.error('2FA verification error:', error);
    }
});

enrollForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    errorMessage.classList.remove('show');
    successMessage.classList.remove('show');

    const code = document.getElementById('enrollCode').value.trim();

    enrollBtn.disabled = true;
    const originalText = enrollBtn.innerHTML;
    enrollBtn.innerHTML = '<span class="loading"></span> Confirming...';

    try {
        const response = await fetch('/api/v1/auth/enroll-2fa/confirm/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ code: code }),
        });

        const data = await response.json();

        if (response.ok) {
            onAuthenticated(data);
        } else {
            errorMessage.textContent = data.error || 'Invalid code. Please try again.';
            errorMessage.classList.add('show');
            enrollBtn.disabled = false;
            enrollBtn.innerHTML = originalText;
            document.getElementById('enrollCode').value = '';
            document.getElementById('enrollCode').focus();
        }
    } catch (error) {
        errorMessage.textContent = 'Network error. Please try again.';
        errorMessage.classList.add('show');
        enrollBtn.disabled = false;
        enrollBtn.innerHTML = originalText;
        console.error('2FA enrollment confirm error:', error);
    }
});

// Clear error message when user starts typing
document.getElementById('username').addEventListener('input', () => {
    errorMessage.classList.remove('show');
});
document.getElementById('password').addEventListener('input', () => {
    errorMessage.classList.remove('show');
});
document.getElementById('totpCode').addEventListener('input', () => {
    errorMessage.classList.remove('show');
});
document.getElementById('enrollCode').addEventListener('input', () => {
    errorMessage.classList.remove('show');
});
