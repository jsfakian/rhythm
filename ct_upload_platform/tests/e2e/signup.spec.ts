/**
 * End-to-End Tests for the Signup Page
 *
 * Prerequisites:
 * - Django server running on http://localhost:8000
 * - Playwright installed: npm install -D @playwright/test
 *
 * Run:
 *   npx playwright test signup.spec.ts
 *   npx playwright test signup.spec.ts --headed
 */

import { test, expect } from './fixtures';

const SIGNUP_URL = '/signup/';
const LOGIN_URL = '/login/';

// Unique suffix per test run to avoid collisions when running against a live DB
const RUN_ID = Date.now();

function uniqueUser(suffix: string) {
    return {
        username: `e2e_${suffix}_${RUN_ID}`,
        email: `e2e_${suffix}_${RUN_ID}@test.example.com`,
        password: 'E2eTestPass99!',
    };
}

test.describe('Signup Page', () => {
    // ------------------------------------------------------------------
    // Page load / structure
    // ------------------------------------------------------------------
    test.describe('Page structure', () => {
        test('renders the signup page', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await expect(page).toHaveTitle(/Sign Up|CT Upload/i);
            await expect(page.locator('h1')).toContainText('CT Upload Platform');
        });

        test('contains all required form fields', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await expect(page.locator('#username')).toBeVisible();
            await expect(page.locator('#email')).toBeVisible();
            await expect(page.locator('#password')).toBeVisible();
            await expect(page.locator('#password2')).toBeVisible();
        });

        test('contains optional first/last name fields', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await expect(page.locator('#firstName')).toBeVisible();
            await expect(page.locator('#lastName')).toBeVisible();
        });

        test('has a link back to the login page', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            const loginLink = page.locator(`a[href="${LOGIN_URL}"]`);
            await expect(loginLink).toBeVisible();
        });

        test('submit button is visible', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await expect(page.locator('#signupBtn')).toBeVisible();
        });
    });

    // ------------------------------------------------------------------
    // Client-side validation
    // ------------------------------------------------------------------
    test.describe('Client-side validation', () => {
        test('shows error when username is empty', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await page.fill('#email', 'test@example.com');
            await page.fill('#password', 'StrongPass99!');
            await page.fill('#password2', 'StrongPass99!');
            await page.click('#signupBtn');
            await expect(page.locator('#usernameError')).toBeVisible();
        });

        test('shows error when email is empty', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await page.fill('#username', 'testuser');
            await page.fill('#password', 'StrongPass99!');
            await page.fill('#password2', 'StrongPass99!');
            await page.click('#signupBtn');
            await expect(page.locator('#emailError')).toBeVisible();
        });

        test('shows error when password is empty', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await page.fill('#username', 'testuser');
            await page.fill('#email', 'test@example.com');
            await page.click('#signupBtn');
            await expect(page.locator('#passwordError')).toBeVisible();
        });

        test('shows error when passwords do not match', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            await page.fill('#username', 'testuser');
            await page.fill('#email', 'test@example.com');
            await page.fill('#password', 'StrongPass99!');
            await page.fill('#password2', 'DifferentPass99!');
            await page.click('#signupBtn');
            await expect(page.locator('#password2Error')).toBeVisible();
            await expect(page.locator('#password2Error')).toContainText(/match/i);
        });

        test('clears field error when user starts typing', async ({ page }) => {
            await page.goto(SIGNUP_URL);
            // Trigger username error
            await page.fill('#email', 'test@example.com');
            await page.fill('#password', 'StrongPass99!');
            await page.fill('#password2', 'StrongPass99!');
            await page.click('#signupBtn');
            await expect(page.locator('#usernameError')).toBeVisible();

            // Start typing — error should clear
            await page.fill('#username', 'a');
            await expect(page.locator('#usernameError')).not.toBeVisible();
        });
    });

    // ------------------------------------------------------------------
    // Successful registration
    // ------------------------------------------------------------------
    test.describe('Successful registration', () => {
        test('creates account and redirects to main page', async ({ page }) => {
            const user = uniqueUser('success');
            await page.goto(SIGNUP_URL);

            await page.fill('#username', user.username);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');

            // Success message appears
            await expect(page.locator('#successMessage')).toBeVisible({ timeout: 5000 });
            await expect(page.locator('#successMessage')).toContainText(user.username);

            // Redirects to main page
            await page.waitForURL('/', { timeout: 5000 });
        });

        test('stores token in localStorage after signup', async ({ page }) => {
            const user = uniqueUser('token');
            await page.goto(SIGNUP_URL);

            await page.fill('#username', user.username);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');

            await expect(page.locator('#successMessage')).toBeVisible({ timeout: 5000 });

            const token = await page.evaluate(() => localStorage.getItem('token'));
            expect(token).toBeTruthy();
        });

        test('supports optional first and last name', async ({ page }) => {
            const user = uniqueUser('withname');
            await page.goto(SIGNUP_URL);

            await page.fill('#firstName', 'Jane');
            await page.fill('#lastName', 'Smith');
            await page.fill('#username', user.username);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');

            await expect(page.locator('#successMessage')).toBeVisible({ timeout: 5000 });
        });
    });

    // ------------------------------------------------------------------
    // Server-side validation errors surfaced in UI
    // ------------------------------------------------------------------
    test.describe('Server-side validation errors', () => {
        test('shows error for duplicate username', async ({ page }) => {
            const user = uniqueUser('dup');
            // First signup
            await page.goto(SIGNUP_URL);
            await page.fill('#username', user.username);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');
            await expect(page.locator('#successMessage')).toBeVisible({ timeout: 5000 });

            // Second signup — same username, different email
            await page.goto(SIGNUP_URL);
            await page.fill('#username', user.username);
            await page.fill('#email', `other_${user.email}`);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');

            await expect(page.locator('#usernameError')).toBeVisible({ timeout: 5000 });
        });

        test('shows error for duplicate email', async ({ page }) => {
            const user = uniqueUser('dupemail');
            // First signup
            await page.goto(SIGNUP_URL);
            await page.fill('#username', user.username);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');
            await expect(page.locator('#successMessage')).toBeVisible({ timeout: 5000 });

            // Second signup — different username, same email
            await page.goto(SIGNUP_URL);
            await page.fill('#username', `other_${user.username}`);
            await page.fill('#email', user.email);
            await page.fill('#password', user.password);
            await page.fill('#password2', user.password);
            await page.click('#signupBtn');

            await expect(page.locator('#emailError')).toBeVisible({ timeout: 5000 });
        });
    });

    // ------------------------------------------------------------------
    // Login page integration
    // ------------------------------------------------------------------
    test.describe('Login page integration', () => {
        test('login page has a link to signup', async ({ page }) => {
            await page.goto(LOGIN_URL);
            const signupLink = page.locator(`a[href="${SIGNUP_URL}"]`);
            await expect(signupLink).toBeVisible();
        });

        test('clicking signup link navigates to signup page', async ({ page }) => {
            await page.goto(LOGIN_URL);
            await page.locator(`a[href="${SIGNUP_URL}"]`).click();
            await expect(page).toHaveURL(new RegExp(SIGNUP_URL));
        });
    });
});
