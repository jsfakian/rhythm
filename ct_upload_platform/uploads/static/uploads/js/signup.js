        const signupForm = document.getElementById('signupForm');
        const signupBtn = document.getElementById('signupBtn');
        const errorMessage = document.getElementById('errorMessage');
        const successMessage = document.getElementById('successMessage');

        const fieldErrors = {
            firstName: document.getElementById('firstNameError'),
            lastName: document.getElementById('lastNameError'),
            username: document.getElementById('usernameError'),
            email: document.getElementById('emailError'),
            password: document.getElementById('passwordError'),
            password2: document.getElementById('password2Error'),
            institution: document.getElementById('institutionError'),
            department: document.getElementById('departmentError'),
            professionalRole: document.getElementById('professionalRoleError'),
            roleOther: document.getElementById('roleOtherError'),
            terms: document.getElementById('termsError'),
        };

        function onRoleChange() {
            const role = document.getElementById('professionalRole').value;
            document.getElementById('roleOtherGroup').style.display = role === 'other' ? 'block' : 'none';
        }
        document.getElementById('professionalRole').addEventListener('change', onRoleChange);

        function clearErrors() {
            errorMessage.classList.remove('show');
            successMessage.classList.remove('show');
            Object.values(fieldErrors).forEach(el => {
                if (el) { el.classList.remove('show'); el.textContent = ''; }
            });
            ['firstName', 'lastName', 'username', 'email', 'password', 'password2', 'institution', 'department', 'professionalRole', 'roleOther'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.remove('error');
            });
        }

        function showFieldError(field, message) {
            const input = document.getElementById(field);
            const errEl = fieldErrors[field];
            if (input) input.classList.add('error');
            if (errEl) {
                errEl.textContent = message;
                errEl.classList.add('show');
            }
        }

        signupForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            clearErrors();

            const username = document.getElementById('username').value.trim();
            const email = document.getElementById('email').value.trim();
            const password = document.getElementById('password').value;
            const password2 = document.getElementById('password2').value;
            const firstName = document.getElementById('firstName').value.trim();
            const lastName = document.getElementById('lastName').value.trim();
            const institution = document.getElementById('institution').value.trim();
            const department = document.getElementById('department').value.trim();
            const professionalRole = document.getElementById('professionalRole').value;
            const roleOther = document.getElementById('roleOther').value.trim();
            const termsAccepted = document.getElementById('termsAccepted').checked;

            let hasError = false;
            if (!firstName) { showFieldError('firstName', 'First name is required.'); hasError = true; }
            if (!lastName) { showFieldError('lastName', 'Last name is required.'); hasError = true; }
            if (!username) { showFieldError('username', 'Username is required.'); hasError = true; }
            if (!email) { showFieldError('email', 'Email is required.'); hasError = true; }
            if (!password) { showFieldError('password', 'Password is required.'); hasError = true; }
            if (password !== password2) { showFieldError('password2', 'Passwords do not match.'); hasError = true; }
            if (!institution) { showFieldError('institution', 'Institution is required.'); hasError = true; }
            if (!department) { showFieldError('department', 'Department / Unit is required.'); hasError = true; }
            if (!professionalRole) { showFieldError('professionalRole', 'Professional role is required.'); hasError = true; }
            if (professionalRole === 'other' && !roleOther) { showFieldError('roleOther', 'Please specify your role.'); hasError = true; }
            if (!termsAccepted) {
                const el = fieldErrors['terms'];
                if (el) { el.textContent = 'You must accept the terms of use to register.'; el.classList.add('show'); }
                hasError = true;
            }
            if (hasError) return;

            signupBtn.disabled = true;
            const originalText = signupBtn.innerHTML;
            signupBtn.innerHTML = '<span class="loading"></span> Creating account...';

            try {
                const response = await fetch('/api/v1/auth/signup/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username,
                        email,
                        password,
                        password2,
                        first_name: firstName,
                        last_name: lastName,
                        institution,
                        department,
                        professional_role: professionalRole,
                        professional_role_other: roleOther,
                        terms_accepted: termsAccepted,
                    }),
                });

                const data = await response.json();

                if (response.ok) {
                    successMessage.textContent = data.message ||
                        `Account created, ${data.username}. An administrator will verify your account before you can sign in.`;
                    successMessage.classList.add('show');
                    signupForm.reset();
                    signupBtn.disabled = true;
                    signupBtn.innerHTML = originalText;
                } else {
                    const details = data.details || {};
                    let handled = false;

                    const fieldMap = {
                        first_name: 'firstName', last_name: 'lastName',
                        username: 'username', email: 'email',
                        password: 'password', password2: 'password2',
                        institution: 'institution', department: 'department',
                        professional_role: 'professionalRole',
                        professional_role_other: 'roleOther',
                        terms_accepted: 'terms',
                    };
                    Object.entries(fieldMap).forEach(([apiKey, formKey]) => {
                        if (details[apiKey]) {
                            const msg = Array.isArray(details[apiKey]) ? details[apiKey].join(' ') : details[apiKey];
                            showFieldError(formKey, msg);
                            handled = true;
                        }
                    });

                    if (details.non_field_errors) {
                        errorMessage.textContent = Array.isArray(details.non_field_errors)
                            ? details.non_field_errors.join(' ')
                            : details.non_field_errors;
                        errorMessage.classList.add('show');
                        handled = true;
                    }

                    if (!handled) {
                        errorMessage.textContent = data.error || 'Registration failed. Please try again.';
                        errorMessage.classList.add('show');
                    }

                    signupBtn.disabled = false;
                    signupBtn.innerHTML = originalText;
                }
            } catch (err) {
                errorMessage.textContent = 'Network error. Please try again.';
                errorMessage.classList.add('show');
                signupBtn.disabled = false;
                signupBtn.innerHTML = originalText;
                console.error('Signup error:', err);
            }
        });

        // Clear field error on input/change
        ['firstName', 'lastName', 'username', 'email', 'password', 'password2', 'institution', 'department'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('input', () => {
                const errEl = fieldErrors[id];
                if (errEl) { errEl.classList.remove('show'); errEl.textContent = ''; }
                el.classList.remove('error');
                errorMessage.classList.remove('show');
            });
        });
