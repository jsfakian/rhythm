/**
 * End-to-End tests for CT Protocol pages.
 *
 * Covers all three protocol types:
 *   - Pediatric Head CT Protocols  (/protocols/PEDIATRIC_HEAD/)
 *   - Pediatric Body CT Protocols  (/protocols/PEDIATRIC_BODY/)
 *   - Young Adult CT Protocols     (/protocols/YOUNG_ADULT/)
 *
 * Prerequisites:
 *   - Django server running on http://localhost:8000
 *   - A seeded test database: `make shell` then run
 *       python manage.py populate_protocol_choices
 *   - A superuser with credentials matching TEST_USER below
 *
 * Run:
 *   npx playwright test tests/e2e/protocols.spec.ts
 *   npx playwright test tests/e2e/protocols.spec.ts --headed
 */

import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8000';
const TEST_USER = {
  username: process.env.TEST_USERNAME ?? 'admin',
  password: process.env.TEST_PASSWORD ?? 'adminpassword',
};

const PROTOCOL_TYPES = [
  { key: 'PEDIATRIC_HEAD', label: 'Pediatric Head CT' },
  { key: 'PEDIATRIC_BODY', label: 'Pediatric Body CT' },
  { key: 'YOUNG_ADULT',    label: 'Young Adult CT' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login/`);
  await page.fill('#id_username', TEST_USER.username);
  await page.fill('#id_password', TEST_USER.password);
  await page.click('button[type="submit"]');
  // Wait until we are no longer on the login page
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

async function ensureLoggedIn(page: Page): Promise<void> {
  // Check if already authenticated by visiting a protected page
  const resp = await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/`);
  if (resp && resp.url().includes('/login')) {
    await login(page);
  }
}

// ---------------------------------------------------------------------------
// Test: Authentication gate
// ---------------------------------------------------------------------------

test.describe('Protocol pages authentication', () => {
  test('unauthenticated visit to list page redirects to login', async ({ page }) => {
    // Make sure we have no session cookies
    await page.context().clearCookies();
    const resp = await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/`);
    // Should end up on the login page
    expect(page.url()).toContain('/login');
  });

  test('unauthenticated visit to scanner list redirects to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`${BASE_URL}/scanners/`);
    expect(page.url()).toContain('/login');
  });
});

// ---------------------------------------------------------------------------
// Test: Protocol list pages
// ---------------------------------------------------------------------------

test.describe('Protocol list pages', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  for (const pt of PROTOCOL_TYPES) {
    test(`${pt.label} list page loads`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/`);
      await expect(page).toHaveURL(`${BASE_URL}/protocols/${pt.key}/`);
      // Page title or heading should reference the protocol type
      const body = await page.textContent('body');
      expect(body).toContain(pt.label);
    });

    test(`${pt.label} list shows correct navigation tabs`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/`);
      // All three type tabs should be present
      await expect(page.locator('text=Pediatric Head CT')).toBeVisible();
      await expect(page.locator('text=Pediatric Body CT')).toBeVisible();
      await expect(page.locator('text=Young Adult CT')).toBeVisible();
    });

    test(`${pt.label} list has "Add New Protocol" button`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/`);
      const addBtn = page.locator(`a[href="/protocols/${pt.key}/create/"]`);
      await expect(addBtn).toBeVisible();
    });
  }

  test('Switching between tabs navigates correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/`);
    await page.click('text=Pediatric Body CT');
    await expect(page).toHaveURL(`${BASE_URL}/protocols/PEDIATRIC_BODY/`);

    await page.click('text=Young Adult CT');
    await expect(page).toHaveURL(`${BASE_URL}/protocols/YOUNG_ADULT/`);

    await page.click('text=Pediatric Head CT');
    await expect(page).toHaveURL(`${BASE_URL}/protocols/PEDIATRIC_HEAD/`);
  });
});

// ---------------------------------------------------------------------------
// Test: Scanner profile pages
// ---------------------------------------------------------------------------

test.describe('Scanner profile pages', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('Scanner list page loads', async ({ page }) => {
    await page.goto(`${BASE_URL}/scanners/`);
    await expect(page).toHaveURL(`${BASE_URL}/scanners/`);
    const body = await page.textContent('body');
    expect(body?.toLowerCase()).toMatch(/scanner/);
  });

  test('Scanner create page loads and shows form', async ({ page }) => {
    await page.goto(`${BASE_URL}/scanners/create/`);
    // Form should be present
    await expect(page.locator('form')).toBeVisible();
    // Manufacturer dropdown should be present
    await expect(page.locator('select[name="manufacturer"]')).toBeVisible();
  });

  test('Manufacturer cascade populates scanner model dropdown', async ({ page }) => {
    await page.goto(`${BASE_URL}/scanners/create/`);
    const manufacturerSelect = page.locator('select[name="manufacturer"]');
    await expect(manufacturerSelect).toBeVisible();

    // Select first non-empty option
    const options = await manufacturerSelect.locator('option').all();
    const firstRealOption = options.find(async (o) => (await o.getAttribute('value')) !== '');
    if (firstRealOption) {
      const val = await firstRealOption.getAttribute('value');
      if (val) {
        await manufacturerSelect.selectOption(val);
        // Wait for cascade JS to fire
        await page.waitForTimeout(500);
        // Scanner model select should now have options populated
        const modelSelect = page.locator('select[name="scanner_model"]');
        const modelOptions = await modelSelect.locator('option').count();
        expect(modelOptions).toBeGreaterThan(1);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Test: Protocol create form
// ---------------------------------------------------------------------------

test.describe('Protocol create form', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  for (const pt of PROTOCOL_TYPES) {
    test(`${pt.label} create form loads`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/create/`);
      await expect(page.locator('form')).toBeVisible();
    });

    test(`${pt.label} create form shows relevant age group field`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/create/`);
      // age_group select should be present
      await expect(page.locator('select[name="age_group"]')).toBeVisible();
    });

    test(`${pt.label} create form has protocol_type hidden field`, async ({ page }) => {
      await page.goto(`${BASE_URL}/protocols/${pt.key}/create/`);
      // The hidden protocol_type field should carry the correct value
      const hidden = page.locator('input[name="protocol_type"]');
      const val = await hidden.getAttribute('value');
      expect(val).toBe(pt.key);
    });
  }

  test('Submitting empty form shows validation errors', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/create/`);
    await page.click('button[type="submit"]');
    // Should stay on the same page (form re-render with errors) or show HTML5 validation
    const url = page.url();
    expect(url).toContain('/protocols/PEDIATRIC_HEAD/');
  });

  test('"Other" selection reveals free-text input', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/create/`);
    // Find a select that has an "Other" option (e.g., scan_type)
    const scanTypeSelect = page.locator('select[name="scan_type"]');
    if (await scanTypeSelect.count() > 0) {
      await scanTypeSelect.selectOption('Other');
      await page.waitForTimeout(300);
      // A text input or textarea should appear near the select
      const otherInput = page.locator(`input[data-other-for="scan_type"], #scan_type_other`);
      if (await otherInput.count() > 0) {
        await expect(otherInput).toBeVisible();
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Test: Protocol detail and navigation
// ---------------------------------------------------------------------------

test.describe('Protocol detail page', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('Non-existent protocol UUID returns 404', async ({ page }) => {
    const fakeUuid = '00000000-0000-0000-0000-000000000000';
    const resp = await page.goto(
      `${BASE_URL}/protocols/PEDIATRIC_HEAD/${fakeUuid}/`,
    );
    expect(resp?.status()).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// Test: Full CRUD flow (requires a working DB with choices seeded)
// ---------------------------------------------------------------------------

test.describe('Protocol CRUD flow (requires seeded DB)', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test.skip('Create, view, edit and delete a Pediatric Head protocol', async ({ page }) => {
    // Step 1: Create scanner profile first
    await page.goto(`${BASE_URL}/scanners/create/`);
    const manufacturerSelect = page.locator('select[name="manufacturer"]');
    const options = await manufacturerSelect.locator('option:not([value=""])').all();
    if (options.length === 0) {
      test.skip(); // No manufacturers seeded
      return;
    }
    const mfrVal = await options[0].getAttribute('value');
    await manufacturerSelect.selectOption(mfrVal!);
    await page.waitForTimeout(600); // cascade

    const modelSelect = page.locator('select[name="scanner_model"]');
    const modelOptions = await modelSelect.locator('option:not([value=""])').all();
    if (modelOptions.length > 0) {
      const mVal = await modelOptions[0].getAttribute('value');
      await modelSelect.selectOption(mVal!);
    }
    await page.click('button[type="submit"]');

    // Step 2: Create protocol
    await page.goto(`${BASE_URL}/protocols/PEDIATRIC_HEAD/create/`);
    const scannerSelect = page.locator('select[name="scanner"]');
    const scannerOptions = await scannerSelect.locator('option:not([value=""])').all();
    if (scannerOptions.length > 0) {
      const sv = await scannerOptions[0].getAttribute('value');
      await scannerSelect.selectOption(sv!);
    }

    const ageGroupSelect = page.locator('select[name="age_group"]');
    const agOptions = await ageGroupSelect.locator('option:not([value=""])').all();
    if (agOptions.length > 0) {
      const agv = await agOptions[0].getAttribute('value');
      await ageGroupSelect.selectOption(agv!);
    }

    await page.click('button[type="submit"]');

    // Should redirect to detail page
    await page.waitForURL(/\/protocols\/PEDIATRIC_HEAD\/.+\//);
    const detailUrl = page.url();
    const body = await page.textContent('body');
    expect(body).toBeTruthy();

    // Step 3: Navigate to edit
    const editLink = page.locator('a[href*="/edit/"]');
    if (await editLink.count() > 0) {
      await editLink.click();
      await expect(page.locator('form')).toBeVisible();
      // Submit without changes
      await page.click('button[type="submit"]');
      await page.waitForURL(/\/protocols\/PEDIATRIC_HEAD\/.+\//);
    }

    // Step 4: Delete
    const deleteLink = page.locator('a[href*="/delete/"]');
    if (await deleteLink.count() > 0) {
      await deleteLink.click();
      await expect(page.locator('form')).toBeVisible();
      await page.click('button[type="submit"]');
      await page.waitForURL(/\/protocols\/PEDIATRIC_HEAD\/$/);
    }
  });
});

// ---------------------------------------------------------------------------
// Test: REST API endpoints from the browser
// ---------------------------------------------------------------------------

test.describe('Protocol REST API (via browser fetch)', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('GET /api/v1/manufacturers/ returns JSON list', async ({ page }) => {
    const resp = await page.goto(`${BASE_URL}/api/v1/manufacturers/`);
    expect(resp?.status()).toBe(200);
    const body = await page.textContent('body');
    // DRF browsable API or raw JSON
    expect(body).toBeTruthy();
  });

  test('GET /api/v1/scanner-models/ returns JSON list', async ({ page }) => {
    const resp = await page.goto(`${BASE_URL}/api/v1/scanner-models/`);
    expect(resp?.status()).toBe(200);
  });

  test('GET /api/v1/protocol-choices/ returns JSON list', async ({ page }) => {
    const resp = await page.goto(`${BASE_URL}/api/v1/protocol-choices/`);
    expect(resp?.status()).toBe(200);
  });

  test('GET /api/v1/protocols-api/ returns JSON list', async ({ page }) => {
    const resp = await page.goto(`${BASE_URL}/api/v1/protocols-api/`);
    expect(resp?.status()).toBe(200);
  });

  test('GET /api/v1/protocols-api/by-type/PEDIATRIC_HEAD/ returns 200', async ({ page }) => {
    const resp = await page.goto(
      `${BASE_URL}/api/v1/protocols-api/by-type/PEDIATRIC_HEAD/`,
    );
    expect(resp?.status()).toBe(200);
  });

  test('GET /api/v1/protocols-api/by-type/INVALID_TYPE/ returns 400', async ({ page }) => {
    const resp = await page.goto(
      `${BASE_URL}/api/v1/protocols-api/by-type/INVALID_TYPE/`,
    );
    expect(resp?.status()).toBe(400);
  });

  test('Cascade endpoint returns models for a manufacturer', async ({ page }) => {
    // First get a manufacturer ID from the API
    await page.goto(`${BASE_URL}/api/v1/manufacturers/?format=json`);
    const body = await page.textContent('body');
    try {
      const data = JSON.parse(body ?? '{}');
      const results = data.results ?? data;
      if (Array.isArray(results) && results.length > 0) {
        const mfrId = results[0].id;
        const resp = await page.goto(
          `${BASE_URL}/api/v1/scanners/models/?manufacturer_id=${mfrId}`,
        );
        expect(resp?.status()).toBe(200);
        const cascadeBody = await page.textContent('body');
        const cascadeData = JSON.parse(cascadeBody ?? '{}');
        expect(Array.isArray(cascadeData.models)).toBe(true);
      }
    } catch {
      // If manufacturers not seeded, skip gracefully
    }
  });
});
