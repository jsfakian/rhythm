/**
 * E2E Tests for the JSON Validator page (/json-validator/)
 *
 * Covers:
 *   1. Paste valid JSON         → success banner shown
 *   2. Paste invalid JSON       → error banner with parse details shown
 *   3. Upload valid JSON file   → success banner shown
 *   4. Upload invalid JSON file → error banner with parse details shown
 *
 * Prerequisites:
 *   - Django server running on http://localhost:8000
 *   - Playwright installed: npm install -D @playwright/test
 *
 * Run:
 *   npx playwright test json_validator.spec.ts
 *   npx playwright test json_validator.spec.ts --headed
 */

import { test, expect } from './fixtures';
import * as fs from 'fs';
import * as path from 'path';

const SIGNUP_URL = '/signup/';
const LOGIN_URL = '/login/';
const VALIDATOR_URL = '/json-validator/';

// Unique per test run so parallel CI runs never collide
const RUN_ID = Date.now();

const TEST_USER = {
  username: `e2e_jv_${RUN_ID}`,
  email: `e2e_jv_${RUN_ID}@test.example.com`,
  password: 'E2eTestPass99!',
};

// A well-formed manifest that satisfies the application's JSON schema
const VALID_JSON = JSON.stringify(
  {
    manifest_version: '1.0',
    upload_id: '550e8400-e29b-41d4-a716-446655440000',
    study: {
      study_uid: '1.2.3.4.5',
      acquisition_date: '2026-02-20',
      clinical_indication: 'Routine scan',
      contrast_used: false,
    },
    patient: {
      pseudo_id: 'PAT_001_ABC',
      sex: 'M',
      age_at_acquisition: 45,
      cohort_tag: 'control',
    },
    images: [
      {
        filename: 'image_001.dcm',
        checksum_sha256:
          'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        series_uid: '1.2.3.4.5.1',
        body_part: 'CHEST',
        instance_number: 1,
      },
    ],
  },
  null,
  2,
);

// JSON with a syntax error: unquoted key + bare word value
const INVALID_JSON =
  '{ "manifest_version": "1.0", "broken": true, missing_quote: oops }';

test.describe('JSON Validator page', () => {
  // Create the test user once before the suite runs
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await page.goto(SIGNUP_URL);
    await page.fill('#username', TEST_USER.username);
    await page.fill('#email', TEST_USER.email);
    await page.fill('#password', TEST_USER.password);
    await page.fill('#password2', TEST_USER.password);
    await page.click('#signupBtn');
    await expect(page.locator('#successMessage')).toBeVisible({ timeout: 8000 });
    await page.close();
  });

  // Log in and open the validator before every test
  test.beforeEach(async ({ page }) => {
    await page.goto(LOGIN_URL);
    await page.fill('#username', TEST_USER.username);
    await page.fill('#password', TEST_USER.password);
    await page.click('#loginBtn');
    await page.waitForURL('/', { timeout: 8000 });

    await page.goto(VALIDATOR_URL);
    await expect(page.locator('#jsonInput')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // 1. Paste valid JSON
  // ---------------------------------------------------------------------------
  test('shows success banner when valid JSON is pasted and validated', async ({ page }) => {
    await page.fill('#jsonInput', VALID_JSON);
    await page.click('button.btn-primary'); // "Validate" button

    const resultBox = page.locator('#resultBox');
    await expect(resultBox).toBeVisible();
    await expect(resultBox).toHaveClass(/result-ok/);
    await expect(resultBox).toContainText('Valid JSON');
  });

  // ---------------------------------------------------------------------------
  // 2. Paste invalid JSON
  // ---------------------------------------------------------------------------
  test('shows error banner with parse details when invalid JSON is pasted', async ({ page }) => {
    await page.fill('#jsonInput', INVALID_JSON);
    await page.click('button.btn-primary');

    const resultBox = page.locator('#resultBox');
    await expect(resultBox).toBeVisible();
    await expect(resultBox).toHaveClass(/result-err/);
    await expect(resultBox).toContainText('Invalid JSON');

    // The browser's JSON.parse error includes position / token details
    const text = await resultBox.textContent();
    expect(text!.length).toBeGreaterThan('Invalid JSON'.length);
  });

  // ---------------------------------------------------------------------------
  // 3. Upload valid JSON file
  // ---------------------------------------------------------------------------
  test('shows success banner when a valid JSON file is uploaded', async ({
    page,
    testDataDir,
  }) => {
    const filePath = path.join(testDataDir, `valid_${RUN_ID}.json`);
    fs.writeFileSync(filePath, VALID_JSON, 'utf-8');

    // Selecting a file triggers auto-load + validate via the 'change' listener
    await page.locator('#fileInput').setInputFiles(filePath);

    const resultBox = page.locator('#resultBox');
    await expect(resultBox).toBeVisible({ timeout: 3000 });
    await expect(resultBox).toHaveClass(/result-ok/);
    await expect(resultBox).toContainText('Valid JSON');
  });

  // ---------------------------------------------------------------------------
  // 4. Upload invalid JSON file
  // ---------------------------------------------------------------------------
  test('shows error banner with parse details when an invalid JSON file is uploaded', async ({
    page,
    testDataDir,
  }) => {
    const filePath = path.join(testDataDir, `invalid_${RUN_ID}.json`);
    fs.writeFileSync(filePath, INVALID_JSON, 'utf-8');

    await page.locator('#fileInput').setInputFiles(filePath);

    const resultBox = page.locator('#resultBox');
    await expect(resultBox).toBeVisible({ timeout: 3000 });
    await expect(resultBox).toHaveClass(/result-err/);
    await expect(resultBox).toContainText('Invalid JSON');

    const text = await resultBox.textContent();
    expect(text!.length).toBeGreaterThan('Invalid JSON'.length);
  });
});
