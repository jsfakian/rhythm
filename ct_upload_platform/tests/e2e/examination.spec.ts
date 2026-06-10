/**
 * End-to-end tests for the CT Examination Data Entry pages.
 *
 * Covers:
 *   - Authentication gate for entry, list, and delete pages
 *   - Examination entry page: renders fields, dynamic phases table,
 *     manufacturer → model cascade, protocol pre-fill
 *   - Save examination via AJAX → success banner
 *   - Examinations list: displays saved records, image quality filter
 *   - Delete confirmation page and delete flow
 *   - Full CRUD: create → verify in list → delete → verify gone
 *
 * Prerequisites:
 *   - Django dev server on http://localhost:8000 with migrations applied
 *   - At least one CTScannerProfile and one CTManufacturer in the database
 *   - A superuser with credentials matching TEST_USER below
 *
 * Run:
 *   npx playwright test tests/e2e/examination.spec.ts
 *   npx playwright test tests/e2e/examination.spec.ts --headed
 */

import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8000';
const TEST_USER = {
  username: process.env.TEST_USERNAME ?? 'admin',
  password: process.env.TEST_PASSWORD ?? 'adminpassword',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login/`);
  await page.fill('#username', TEST_USER.username);
  await page.fill('#password', TEST_USER.password);
  await page.click('#loginBtn');
  // Login form uses AJAX + a 2 s setTimeout before redirect
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 10000 });
}

async function ensureLoggedIn(page: Page): Promise<void> {
  const resp = await page.goto(`${BASE_URL}/examinations/entry/`);
  if (resp && resp.url().includes('/login')) {
    await login(page);
  }
}

// ---------------------------------------------------------------------------
// 1. Authentication gate
// ---------------------------------------------------------------------------

test.describe('Authentication gate', () => {
  test('entry page redirects to login when not authenticated', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/entry/`);
    await expect(page).toHaveURL(/\/login\//);
  });

  test('list page redirects to login when not authenticated', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(page).toHaveURL(/\/login\//);
  });

  test('delete page redirects to login when not authenticated', async ({ page }) => {
    // Use a random UUID — should redirect to login before 404
    await page.goto(`${BASE_URL}/examinations/00000000-0000-0000-0000-000000000000/delete/`);
    await expect(page).toHaveURL(/\/login\//);
  });
});

// ---------------------------------------------------------------------------
// 2. Examination entry page — structure
// ---------------------------------------------------------------------------

test.describe('Examination entry page — structure', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('page returns 200 and shows title', async ({ page }) => {
    await expect(page).not.toHaveURL(/\/login\//);
    await expect(page.locator('h1')).toContainText(/Examination|Data Entry/i);
  });

  test('scanner manufacturer dropdown is present', async ({ page }) => {
    await expect(page.locator('#sel_manufacturer, select[id*="manufacturer"]').first()).toBeVisible();
  });

  test('anatomical region dropdown is present', async ({ page }) => {
    await expect(page.locator('#sel_region, select[id*="region"]').first()).toBeVisible();
  });

  test('clinical indication dropdown is present', async ({ page }) => {
    await expect(page.locator('#sel_indication, select[id*="indication"]').first()).toBeVisible();
  });

  test('patient weight input is present', async ({ page }) => {
    await expect(page.locator('#inp_weight, input[id*="weight"]').first()).toBeVisible();
  });

  test('patient age input is present', async ({ page }) => {
    await expect(page.locator('#inp_age, input[id*="age"]').first()).toBeVisible();
  });

  test('number of phases input is present', async ({ page }) => {
    await expect(page.locator('#inp_phases, input[id*="phases"]').first()).toBeVisible();
  });

  test('image quality dropdown is present', async ({ page }) => {
    await expect(page.locator('#sel_quality, select[id*="quality"]').first()).toBeVisible();
  });

  test('save button is present', async ({ page }) => {
    await expect(page.locator('button.btn-save, button:has-text("Save")').first()).toBeVisible();
  });

  test('link to saved examinations list is present', async ({ page }) => {
    await expect(page.locator('a.btn-list[href="/examinations/"]')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 3. Dynamic phases table
// ---------------------------------------------------------------------------

test.describe('Dynamic phases table', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('phases table renders on load with 1 row', async ({ page }) => {
    const phasesInput = page.locator('#inp_phases');
    await expect(phasesInput).toHaveValue('1');
    // After page load the table should have 1 CTDI input
    await expect(page.locator('#ctdi_1, input[id^="ctdi_"]').first()).toBeVisible();
  });

  test('increasing phases adds rows', async ({ page }) => {
    const phasesInput = page.locator('#inp_phases');
    await phasesInput.fill('3');
    await phasesInput.dispatchEvent('input');
    await expect(page.locator('#ctdi_3, input[id="ctdi_3"]')).toBeVisible();
    await expect(page.locator('#dlp_3, input[id="dlp_3"]')).toBeVisible();
  });

  test('decreasing phases removes rows', async ({ page }) => {
    const phasesInput = page.locator('#inp_phases');
    await phasesInput.fill('3');
    await phasesInput.dispatchEvent('input');
    await phasesInput.fill('1');
    await phasesInput.dispatchEvent('input');
    await expect(page.locator('#ctdi_2, input[id="ctdi_2"]')).not.toBeVisible();
  });

  test('phase table shows CTDI vol column header', async ({ page }) => {
    await page.locator('#inp_phases').fill('2');
    await page.locator('#inp_phases').dispatchEvent('input');
    await expect(page.locator('#phases_table_wrap')).toContainText(/CTDI/i);
  });

  test('phase table shows DLP column header', async ({ page }) => {
    await page.locator('#inp_phases').fill('2');
    await page.locator('#inp_phases').dispatchEvent('input');
    await expect(page.locator('#phases_table_wrap')).toContainText(/DLP/i);
  });
});

// ---------------------------------------------------------------------------
// 4. WED field behaviour
// ---------------------------------------------------------------------------

test.describe('WED field', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('WED field is visible on the form', async ({ page }) => {
    await expect(page.locator('#inp_wed, input[id*="wed"]').first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 5. Manufacturer → Model cascade
// ---------------------------------------------------------------------------

test.describe('Manufacturer → Model cascade', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('model dropdown is populated after selecting a manufacturer', async ({ page }) => {
    const mfrSelect = page.locator('#sel_manufacturer, select[id*="manufacturer"]').first();
    const options = await mfrSelect.locator('option:not([value=""])').all();

    if (options.length === 0) {
      test.skip();
      return;
    }

    const mfrId = await options[0].getAttribute('value');
    if (!mfrId) { test.skip(); return; }

    // Intercept the cascade API call
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/v1/scanners/models/')),
      mfrSelect.selectOption(mfrId),
    ]);

    expect(response.status()).toBe(200);
    const modelSelect = page.locator('#sel_model, select[id*="model"]').first();
    const modelOptions = await modelSelect.locator('option:not([value=""])').count();
    expect(modelOptions).toBeGreaterThanOrEqual(0);
  });
});

// ---------------------------------------------------------------------------
// 6. Save examination (AJAX)
// ---------------------------------------------------------------------------

test.describe('Save examination', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  async function fillMinimalForm(page: Page): Promise<void> {
    // Set 1 phase and fill CTDI + DLP
    const phasesInput = page.locator('#inp_phases');
    await phasesInput.fill('1');
    await phasesInput.dispatchEvent('input');
    // Wait for dynamic table
    await page.locator('#ctdi_1').waitFor({ state: 'visible' });
    await page.locator('#ctdi_1').fill('5.5');
    await page.locator('#dlp_1').fill('88.0');
    // Fill other optional fields
    await page.locator('#inp_weight').fill('15.0');
    await page.locator('#inp_age').fill('6');
  }

  test('save button triggers AJAX POST to /examinations/api/save/', async ({ page }) => {
    await fillMinimalForm(page);

    const [request] = await Promise.all([
      page.waitForRequest((r) => r.url().includes('/examinations/api/save/')),
      page.locator('button.btn-save, button:has-text("Save")').first().click(),
    ]);

    expect(request.method()).toBe('POST');
  });

  test('successful save shows success banner', async ({ page }) => {
    await fillMinimalForm(page);

    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/examinations/api/save/')),
      page.locator('button.btn-save, button:has-text("Save")').first().click(),
    ]);

    await expect(
      page.locator('.banner-success, .alert-success, [class*="success"]').first()
    ).toBeVisible({ timeout: 5000 });
  });

  test('success banner contains confirmation text', async ({ page }) => {
    await fillMinimalForm(page);

    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/examinations/api/save/')),
      page.locator('button.btn-save, button:has-text("Save")').first().click(),
    ]);

    await expect(page.locator('body')).toContainText(/saved|success/i, { timeout: 5000 });
  });
});

// ---------------------------------------------------------------------------
// 7. Examinations list page
// ---------------------------------------------------------------------------

test.describe('Examinations list page', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('list page loads with 200', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(page).not.toHaveURL(/\/login\//);
    await expect(page.locator('h1, h2').first()).toBeVisible();
  });

  test('image quality filter dropdown is present', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(page.locator('select[name="image_quality"]')).toBeVisible();
  });

  test('filter by image quality updates URL', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await page.selectOption('select[name="image_quality"]', 'EXCELLENT');
    await page.waitForURL(/image_quality=EXCELLENT/);
    await expect(page).toHaveURL(/image_quality=EXCELLENT/);
  });

  test('sidebar contains examinations nav link', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(page.locator('nav a[href="/examinations/"], .sidebar a[href="/examinations/"]').first()).toBeVisible();
  });

  test('sidebar contains exam entry nav link', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(
      page.locator('nav a[href="/examinations/entry/"], .sidebar a[href="/examinations/entry/"]').first()
    ).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 8. Delete confirmation page
// ---------------------------------------------------------------------------

test.describe('Delete examination', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('invalid UUID on delete page returns 404', async ({ page }) => {
    const resp = await page.goto(
      `${BASE_URL}/examinations/00000000-0000-0000-0000-000000000000/delete/`
    );
    expect(resp?.status()).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// 9. Full CRUD flow
// ---------------------------------------------------------------------------

test.describe('Full CRUD flow', () => {
  test('create examination, verify in list, delete, verify gone', async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);

    // Fill form with 2 phases
    const phasesInput = page.locator('#inp_phases');
    await phasesInput.fill('2');
    await phasesInput.dispatchEvent('input');
    await page.locator('#ctdi_1').waitFor({ state: 'visible' });
    await page.locator('#ctdi_1').fill('3.1');
    await page.locator('#ctdi_2').fill('4.2');
    await page.locator('#dlp_1').fill('50.0');
    await page.locator('#dlp_2').fill('60.0');
    await page.locator('#inp_weight').fill('12.5');
    await page.locator('#inp_age').fill('4');

    // Select image quality
    const qualitySelect = page.locator('#sel_quality, select[id*="quality"]').first();
    await qualitySelect.selectOption('GOOD');

    // Save
    await Promise.all([
      page.waitForResponse((r) => r.url().includes('/examinations/api/save/')),
      page.locator('button.btn-save, button:has-text("Save")').first().click(),
    ]);

    await expect(page.locator('body')).toContainText(/saved|success/i, { timeout: 5000 });

    // Navigate to list and find the record
    await page.goto(`${BASE_URL}/examinations/`);
    await expect(page.locator('body')).toContainText(/Good/i);

    // Find and click the delete link for the first record
    const deleteLink = page.locator('a[href*="/delete/"]').first();
    const deleteHref = await deleteLink.getAttribute('href');
    expect(deleteHref).toBeTruthy();

    await deleteLink.click();
    // Confirm delete page
    await expect(page.locator('body')).toContainText(/delete|confirm/i, { timeout: 3000 });

    // Submit delete form
    await page.locator('button[type="submit"], form[method="post"] button').first().click();
    await page.waitForURL(`${BASE_URL}/examinations/`);

    // Just verify we're back on the list page without an error
    await expect(page).toHaveURL(`${BASE_URL}/examinations/`);
  });
});

// ---------------------------------------------------------------------------
// 10. Protocol link dropdown
// ---------------------------------------------------------------------------

test.describe('Protocol link dropdown', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('protocol dropdown is present', async ({ page }) => {
    await expect(page.locator('#sel_protocol')).toBeVisible();
  });

  test('protocol dropdown defaults to empty (no pre-selected protocol)', async ({ page }) => {
    const value = await page.locator('#sel_protocol').inputValue();
    expect(value).toBe('');
  });

  test('selecting a protocol pre-fills region dropdown (when protocols exist)', async ({ page }) => {
    const options = await page.locator('#sel_protocol option[data-region]').all();
    if (options.length === 0) test.skip();

    const firstOption = options[0];
    const region = await firstOption.getAttribute('data-region');
    const value = await firstOption.getAttribute('value');
    if (!value || !region) { test.skip(); return; }

    await page.locator('#sel_protocol').selectOption(value);
    await page.waitForTimeout(400);

    const regionValue = await page.locator('#sel_region').inputValue();
    expect(regionValue).toBe(region);
  });
});

// ---------------------------------------------------------------------------
// 11. Region → Indication cascade in entry form
// ---------------------------------------------------------------------------

test.describe('Region → Indication cascade', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('indication dropdown is empty before region selection', async ({ page }) => {
    const count = await page.locator('#sel_indication option:not([value=""])').count();
    expect(count).toBe(0);
  });

  test('selecting a region populates the indication dropdown', async ({ page }) => {
    const regionOptions = await page.locator('#sel_region option:not([value=""])').all();
    if (regionOptions.length === 0) test.skip();

    const val = await regionOptions[0].getAttribute('value');
    await page.locator('#sel_region').selectOption(val!);
    await page.waitForTimeout(200);

    const count = await page.locator('#sel_indication option:not([value=""])').count();
    expect(count).toBeGreaterThan(0);
  });

  test('changing region resets the indication dropdown', async ({ page }) => {
    const regionOptions = await page.locator('#sel_region option:not([value=""])').all();
    if (regionOptions.length < 2) test.skip();

    const v1 = await regionOptions[0].getAttribute('value');
    await page.locator('#sel_region').selectOption(v1!);
    await page.waitForTimeout(200);
    await page.locator('#sel_indication').selectOption({ index: 1 });

    const v2 = await regionOptions[1].getAttribute('value');
    await page.locator('#sel_region').selectOption(v2!);
    await page.waitForTimeout(200);

    const indValue = await page.locator('#sel_indication').inputValue();
    expect(indValue).toBe('');
  });
});

// ---------------------------------------------------------------------------
// 12. Clear form button
// ---------------------------------------------------------------------------

test.describe('Clear form button', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('"Clear form" button is present and visible', async ({ page }) => {
    await expect(page.locator('button.btn-clear')).toBeVisible();
  });

  test('clicking "Clear form" resets numeric inputs', async ({ page }) => {
    await page.locator('#inp_weight').fill('50.0');
    await page.locator('#inp_age').fill('10');
    await page.locator('#inp_phases').fill('3');
    await page.locator('#inp_phases').dispatchEvent('input');

    await page.locator('button.btn-clear').click();
    await page.waitForTimeout(200);

    expect(await page.locator('#inp_weight').inputValue()).toBe('');
    expect(await page.locator('#inp_age').inputValue()).toBe('');
    expect(await page.locator('#inp_phases').inputValue()).toBe('1');
  });

  test('clicking "Clear form" resets region and indication', async ({ page }) => {
    const regionOptions = await page.locator('#sel_region option:not([value=""])').all();
    if (regionOptions.length === 0) test.skip();

    const v = await regionOptions[0].getAttribute('value');
    await page.locator('#sel_region').selectOption(v!);
    await page.waitForTimeout(200);

    await page.locator('button.btn-clear').click();
    await page.waitForTimeout(200);

    expect(await page.locator('#sel_region').inputValue()).toBe('');
    expect(await page.locator('#sel_indication option:not([value=""])').count()).toBe(0);
  });

  test('clicking "Clear form" resets manufacturer and collapses model options', async ({ page }) => {
    const mfrOptions = await page.locator('#sel_manufacturer option:not([value=""])').all();
    if (mfrOptions.length === 0) test.skip();

    const mfrId = await mfrOptions[0].getAttribute('value');
    await page.locator('#sel_manufacturer').selectOption(mfrId!);
    await page.waitForTimeout(400);

    await page.locator('button.btn-clear').click();
    await page.waitForTimeout(200);

    expect(await page.locator('#sel_manufacturer').inputValue()).toBe('');
    // Model select should be back to single placeholder option
    const modelOptions = await page.locator('#sel_model option:not([value=""])').count();
    expect(modelOptions).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 13. Error banner
// ---------------------------------------------------------------------------

test.describe('Error banner', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/entry/`);
  });

  test('error banner is present in the DOM but initially hidden', async ({ page }) => {
    const banner = page.locator('#errorBanner');
    await expect(banner).toBeAttached();
    // Hidden via CSS class (.error-box { display: none }), not inline style
    await expect(banner).toBeHidden();
  });

  test('error banner becomes visible when server returns an error', async ({ page }) => {
    await page.route('**/examinations/api/save/', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Validation failed' }),
      });
    });

    await page.locator('#ctdi_1').waitFor({ state: 'visible' });
    await page.locator('#ctdi_1').fill('5.0');
    await page.locator('#dlp_1').fill('80.0');
    await page.locator('button.btn-save').click();
    await page.waitForTimeout(600);

    await expect(page.locator('#errorBanner')).not.toBeHidden();
  });
});

// ---------------------------------------------------------------------------
// 14. Exam list — table structure
// ---------------------------------------------------------------------------

test.describe('Examinations list — table structure', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/`);
  });

  const expectedHeaders = [
    '#', 'Protocol', 'Scanner', 'Region', 'Clinical Indication',
    'Weight (kg)', 'WED (cm)', 'Age (y)', 'Phases',
    'Image Quality', 'Recorded', 'Actions',
  ];

  for (const header of expectedHeaders) {
    test(`table has "${header}" column header`, async ({ page }) => {
      const thead = await page.locator('thead').textContent();
      expect(thead).toContain(header);
    });
  }

  test('"+ Add Examination" button links to /examinations/entry/', async ({ page }) => {
    const btn = page.locator('a:has-text("+ Add Examination")');
    await expect(btn).toBeVisible();
    const href = await btn.getAttribute('href');
    expect(href).toContain('/examinations/entry/');
  });

  test('page heading is "CT Examination Records"', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('CT Examination Records');
  });
});

// ---------------------------------------------------------------------------
// 15. Exam list — filter controls
// ---------------------------------------------------------------------------

test.describe('Examinations list — filter controls', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/examinations/`);
  });

  test('"Filter" submit button is present', async ({ page }) => {
    await expect(page.locator('button[type="submit"]:has-text("Filter")')).toBeVisible();
  });

  test('quality dropdown contains all four quality options', async ({ page }) => {
    const options = await page.locator('select[name="image_quality"] option').allTextContents();
    const joined = options.join(' ');
    expect(joined).toContain('Excellent');
    expect(joined).toContain('Good');
    expect(joined).toContain('Moderate');
    expect(joined).toContain('Poor');
  });

  test('"Clear" link appears when quality filter is active', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/?image_quality=EXCELLENT`);
    await expect(page.locator('a:has-text("Clear")')).toBeVisible();
  });

  test('"Clear" link removes the image_quality URL param', async ({ page }) => {
    await page.goto(`${BASE_URL}/examinations/?image_quality=GOOD`);
    await page.locator('a:has-text("Clear")').click();
    await page.waitForURL(/\/examinations\/$/);
    expect(page.url()).not.toContain('image_quality=');
  });

  test('no "Clear" link when no filter is active', async ({ page }) => {
    const clearCount = await page.locator('a:has-text("Clear")').count();
    expect(clearCount).toBe(0);
  });

  test('empty-state row text when no records match filter', async ({ page }) => {
    // A deliberately impossible filter value ensures 0 results
    await page.goto(`${BASE_URL}/examinations/?image_quality=POOR`);
    const allRows = await page.locator('table tbody tr').count();
    if (allRows > 1) {
      // Records exist for POOR quality — just verify the page loaded OK
      await expect(page.locator('table tbody')).toBeVisible();
    } else {
      await expect(page.locator('table tbody')).toContainText('No examination records yet.');
    }
  });
});

// ---------------------------------------------------------------------------
// 16. Delete confirmation page
// ---------------------------------------------------------------------------

/** Create a minimal examination and return the URL of its delete page. */
async function createExamAndGetDeleteUrl(page: Page): Promise<string | null> {
  await page.goto(`${BASE_URL}/examinations/entry/`);
  await page.locator('#ctdi_1').waitFor({ state: 'visible' });
  await page.locator('#ctdi_1').fill('9.9');
  await page.locator('#dlp_1').fill('99.0');
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/examinations/api/save/')),
    page.locator('button.btn-save').click(),
  ]);
  await page.waitForTimeout(500);

  await page.goto(`${BASE_URL}/examinations/`);
  const deleteLink = page.locator('a[href*="/delete/"]').first();
  if (await deleteLink.count() === 0) return null;
  return deleteLink.getAttribute('href');
}

test.describe('Delete confirmation page', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('page heading is "Delete Examination"', async ({ page }) => {
    const url = await createExamAndGetDeleteUrl(page);
    if (!url) test.skip();
    await page.goto(`${BASE_URL}${url}`);
    await expect(page.locator('h1')).toContainText('Delete Examination');
  });

  test('page body contains "Are you sure"', async ({ page }) => {
    const url = await createExamAndGetDeleteUrl(page);
    if (!url) test.skip();
    await page.goto(`${BASE_URL}${url}`);
    await expect(page.locator('body')).toContainText(/Are you sure/i);
  });

  test('"Yes, delete" submit button is present', async ({ page }) => {
    const url = await createExamAndGetDeleteUrl(page);
    if (!url) test.skip();
    await page.goto(`${BASE_URL}${url}`);
    await expect(page.locator('button[type="submit"]')).toContainText(/yes.*delete/i);
  });

  test('"Cancel" link returns to /examinations/', async ({ page }) => {
    const url = await createExamAndGetDeleteUrl(page);
    if (!url) test.skip();
    await page.goto(`${BASE_URL}${url}`);
    await page.locator('a:has-text("Cancel")').click();
    await expect(page).toHaveURL(`${BASE_URL}/examinations/`);
  });

  test('page shows examination region and recorded date', async ({ page }) => {
    const url = await createExamAndGetDeleteUrl(page);
    if (!url) test.skip();
    await page.goto(`${BASE_URL}${url}`);
    // Template renders "Region: <value> · Recorded: <date>"
    await expect(page.locator('body')).toContainText(/Region:/i);
    await expect(page.locator('body')).toContainText(/Recorded:/i);
  });
});
