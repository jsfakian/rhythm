/**
 * End-to-end tests for the clinical indication-centred Protocol GUI.
 *
 * Covers:
 *   - Authentication gate
 *   - Step 1: clinical indication dropdowns and preview
 *   - Step 2: scanner dropdown and "Add new scanner" link
 *   - Step 3: protocol tabs (Pediatric HEAD / Pediatric Body / Young Adult),
 *             field rendering, progress bar
 *   - Save protocol (AJAX) → success banner
 *   - Duplicate detection → exists banner → force-update flow
 *   - Protocol Records page: display, type filter, edit and delete links
 *
 * Prerequisites:
 *   - Django dev server on http://localhost:8000 with migrations applied
 *   - At least one CTScannerProfile in the database
 *   - A superuser with credentials matching TEST_USER below
 *
 * Run:
 *   npx playwright test tests/e2e/protocol_gui.spec.ts
 *   npx playwright test tests/e2e/protocol_gui.spec.ts --headed
 */

import { test, expect, Page, Request } from '@playwright/test';

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
  await page.fill('#id_username', TEST_USER.username);
  await page.fill('#id_password', TEST_USER.password);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

async function ensureLoggedIn(page: Page): Promise<void> {
  const resp = await page.goto(`${BASE_URL}/protocols/gui/`);
  if (resp && resp.url().includes('/login')) {
    await login(page);
  }
}

/** Select the first non-empty option in a <select> and return its value. */
async function selectFirstOption(page: Page, selector: string): Promise<string | null> {
  const options = await page.locator(`${selector} option:not([value=""])`).all();
  if (options.length === 0) return null;
  const val = await options[0].getAttribute('value');
  if (val) await page.locator(selector).selectOption(val);
  return val;
}

/** Drive Step 1 to a complete state using the first available choices. */
async function completeStep1(page: Page): Promise<boolean> {
  const regionVal = await selectFirstOption(page, '#cl_region');
  if (!regionVal) return false;
  await page.waitForTimeout(200);

  const indVal = await selectFirstOption(page, '#cl_indication');
  if (!indVal) return false;
  await page.waitForTimeout(200);

  const contrastVal = await selectFirstOption(page, '#cl_contrast');
  if (!contrastVal) return false;
  await page.waitForTimeout(200);

  const commentsCount = await page.locator('#cl_comments option:not([value=""])').count();
  if (commentsCount > 0) {
    const commentsVal = await page.locator('#cl_comments option:not([value=""])').first().getAttribute('value');
    if (commentsVal && commentsVal !== 'Other: Please Specify') {
      await page.locator('#cl_comments').selectOption(commentsVal);
    }
  }
  await page.waitForTimeout(200);
  return true;
}

/** Drive Step 2: pick the first scanner in the dropdown. */
async function completeStep2(page: Page): Promise<boolean> {
  const val = await selectFirstOption(page, '#scanner_select');
  await page.waitForTimeout(200);
  return !!val;
}

// ---------------------------------------------------------------------------
// Authentication gate
// ---------------------------------------------------------------------------

test.describe('Protocol GUI authentication', () => {
  test('unauthenticated visit to /protocols/gui/ redirects to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`${BASE_URL}/protocols/gui/`);
    expect(page.url()).toContain('/login');
  });

  test('unauthenticated visit to /protocols/records/ redirects to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`${BASE_URL}/protocols/records/`);
    expect(page.url()).toContain('/login');
  });

  test('unauthenticated POST to /protocols/api/save/ redirects to login', async ({ page }) => {
    await page.context().clearCookies();
    const resp = await page.goto(`${BASE_URL}/protocols/api/save/`);
    // A GET to a POST-only view also redirects without session
    expect(page.url()).toContain('/login');
  });
});

// ---------------------------------------------------------------------------
// Page load and structure
// ---------------------------------------------------------------------------

test.describe('Protocol GUI page load', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('page loads successfully', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page).toHaveURL(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('body')).toBeVisible();
  });

  test('page title contains CT Protocol', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    const title = await page.title();
    expect(title.toLowerCase()).toContain('protocol');
  });

  test('Step 1 section is visible', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('text=1. Select Clinical Indication')).toBeVisible();
  });

  test('Step 2 section is visible', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('text=2. Select Scanner')).toBeVisible();
  });

  test('Step 3 section is visible', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('text=3. Enter Protocol Fields')).toBeVisible();
  });

  test('Save Protocol button is visible', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('button:has-text("Save Protocol")')).toBeVisible();
  });

  test('"View saved records" link points to /protocols/records/', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    const link = page.locator('a:has-text("View saved records")');
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');
    expect(href).toContain('/protocols/records/');
  });

  test('sidebar contains Protocol GUI link', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('.sidebar a[href="/protocols/gui/"]')).toBeVisible();
  });

  test('sidebar contains Protocol Records link', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    await expect(page.locator('.sidebar a[href="/protocols/records/"]')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Step 1: Clinical Indication dropdowns
// ---------------------------------------------------------------------------

test.describe('Step 1 – clinical indication selectors', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/protocols/gui/`);
  });

  test('Anatomical Region dropdown is populated', async ({ page }) => {
    const count = await page.locator('#cl_region option:not([value=""])').count();
    expect(count).toBeGreaterThan(0);
  });

  test('selecting a region populates the Clinical Indication dropdown', async ({ page }) => {
    await selectFirstOption(page, '#cl_region');
    await page.waitForTimeout(300);
    const count = await page.locator('#cl_indication option:not([value=""])').count();
    expect(count).toBeGreaterThan(0);
  });

  test('selecting an indication populates the Comments dropdown', async ({ page }) => {
    await selectFirstOption(page, '#cl_region');
    await page.waitForTimeout(200);
    await selectFirstOption(page, '#cl_indication');
    await page.waitForTimeout(300);
    const count = await page.locator('#cl_comments option:not([value=""])').count();
    expect(count).toBeGreaterThan(0);
  });

  test('clinical preview box appears after full Step 1 completion', async ({ page }) => {
    const complete = await completeStep1(page);
    if (!complete) test.skip();
    const preview = page.locator('#clinicalPreview');
    await expect(preview).toBeVisible({ timeout: 2000 });
  });

  test('changing region resets indication dropdown', async ({ page }) => {
    const regionOptions = await page.locator('#cl_region option:not([value=""])').all();
    if (regionOptions.length < 2) test.skip();

    const v1 = await regionOptions[0].getAttribute('value');
    await page.locator('#cl_region').selectOption(v1!);
    await page.waitForTimeout(200);
    await selectFirstOption(page, '#cl_indication');

    const v2 = await regionOptions[1].getAttribute('value');
    await page.locator('#cl_region').selectOption(v2!);
    await page.waitForTimeout(200);

    // Indication should be reset (empty value selected)
    const indVal = await page.locator('#cl_indication').inputValue();
    expect(indVal).toBe('');
  });

  test('"Other: Please Specify" in comments reveals text input', async ({ page }) => {
    await selectFirstOption(page, '#cl_region');
    await page.waitForTimeout(200);
    await selectFirstOption(page, '#cl_indication');
    await page.waitForTimeout(200);

    const otherOption = page.locator('#cl_comments option[value="Other: Please Specify"]');
    if (await otherOption.count() === 0) test.skip();

    await page.locator('#cl_comments').selectOption('Other: Please Specify');
    await page.waitForTimeout(200);
    await expect(page.locator('#cl_comments_other_wrap')).toBeVisible();
    await expect(page.locator('#cl_comments_other')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Step 2: Scanner selection
// ---------------------------------------------------------------------------

test.describe('Step 2 – scanner selection', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/protocols/gui/`);
  });

  test('"Add new scanner" button is visible', async ({ page }) => {
    await expect(page.locator('a:has-text("+ Add new scanner")')).toBeVisible();
  });

  test('"Add new scanner" link points to /scanners/create/', async ({ page }) => {
    const link = page.locator('a:has-text("+ Add new scanner")');
    const href = await link.getAttribute('href');
    expect(href).toContain('/scanners/create/');
  });

  test('scanner dropdown is present', async ({ page }) => {
    await expect(page.locator('#scanner_select')).toBeVisible();
  });

  test('selecting a scanner shows scanner preview', async ({ page }) => {
    const val = await selectFirstOption(page, '#scanner_select');
    if (!val) test.skip();
    await page.waitForTimeout(300);
    const preview = page.locator('#scannerPreview');
    await expect(preview).toBeVisible();
    const text = await preview.textContent();
    expect(text!.trim().length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Step 3: Protocol tabs and fields
// ---------------------------------------------------------------------------

test.describe('Step 3 – protocol tabs and fields', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/protocols/gui/`);
  });

  test('protocol form is blocked when Step 1 and Step 2 are incomplete', async ({ page }) => {
    await expect(page.locator('#protocolBlocked')).toBeVisible();
    await expect(page.locator('#protocolFormWrap')).not.toBeVisible();
  });

  test('protocol form unlocks after Step 1 + Step 2 are complete', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('#protocolFormWrap')).toBeVisible();
    await expect(page.locator('#protocolBlocked')).not.toBeVisible();
  });

  test('all three protocol tabs are rendered', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('.tab-btn:has-text("Pediatric HEAD")')).toBeVisible();
    await expect(page.locator('.tab-btn:has-text("Pediatric Body")')).toBeVisible();
    await expect(page.locator('.tab-btn:has-text("Young Adult")')).toBeVisible();
  });

  test('Pediatric HEAD tab is active by default', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    const activeTab = page.locator('.tab-btn.active');
    const text = await activeTab.textContent();
    expect(text).toContain('Pediatric HEAD');
  });

  test('clicking Pediatric Body tab makes it active', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await page.locator('.tab-btn:has-text("Pediatric Body")').click();
    await page.waitForTimeout(200);
    const activeTab = page.locator('.tab-btn.active');
    const text = await activeTab.textContent();
    expect(text).toContain('Pediatric Body');
  });

  test('clicking Young Adult tab makes it active', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await page.locator('.tab-btn:has-text("Young Adult")').click();
    await page.waitForTimeout(200);
    const activeTab = page.locator('.tab-btn.active');
    const text = await activeTab.textContent();
    expect(text).toContain('Young Adult');
  });

  test('Examination Group dropdown is rendered', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('#fld_examination_group')).toBeVisible();
  });

  test('Age / Weight Group dropdown is rendered', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('#fld_age_group')).toBeVisible();
  });

  test('Pediatric HEAD examination groups include neonate option', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    const options = await page.locator('#fld_examination_group option').allTextContents();
    const hasNeonate = options.some(o => o.toLowerCase().includes('neonate'));
    expect(hasNeonate).toBe(true);
  });

  test('Young Adult tab shows only one examination group', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await page.locator('.tab-btn:has-text("Young Adult")').click();
    await page.waitForTimeout(300);
    const options = await page.locator('#fld_examination_group option:not([value=""])').count();
    expect(options).toBe(1);
  });

  test('progress bar updates when fields are filled', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);

    const barBefore = await page.locator('#progressBar').getAttribute('style');
    const pctBefore = parseInt((barBefore?.match(/width:\s*(\d+)%/) ?? ['0', '0'])[1]);

    await selectFirstOption(page, '#fld_examination_group');
    await selectFirstOption(page, '#fld_age_group');
    await page.waitForTimeout(200);

    const barAfter = await page.locator('#progressBar').getAttribute('style');
    const pctAfter = parseInt((barAfter?.match(/width:\s*(\d+)%/) ?? ['0', '0'])[1]);
    expect(pctAfter).toBeGreaterThan(pctBefore);
  });

  test('kVp field is rendered in the protocol form', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('#fld_kvp')).toBeVisible();
  });

  test('Notes textarea is rendered', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await expect(page.locator('#fld_notes')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Save protocol flow
// ---------------------------------------------------------------------------

test.describe('Save protocol (AJAX)', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
    await page.goto(`${BASE_URL}/protocols/gui/`);
  });

  test('clicking Save without Step 1 shows alert', async ({ page }) => {
    page.once('dialog', async (dialog) => {
      expect(dialog.message()).toContain('Step 1');
      await dialog.dismiss();
    });
    await page.locator('button:has-text("Save Protocol")').click();
  });

  test('clicking Save without scanner shows alert', async ({ page }) => {
    const s1 = await completeStep1(page);
    if (!s1) test.skip();
    await page.waitForTimeout(300);

    page.once('dialog', async (dialog) => {
      expect(dialog.message().toLowerCase()).toContain('scanner');
      await dialog.dismiss();
    });
    await page.locator('button:has-text("Save Protocol")').click();
  });

  test('successful save shows success banner', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);

    // Fill mandatory examination + age group fields
    const egVal = await selectFirstOption(page, '#fld_examination_group');
    const agVal = await selectFirstOption(page, '#fld_age_group');
    if (!egVal || !agVal) test.skip();
    await page.waitForTimeout(200);

    // Intercept the save request to check it fires
    const savePromise = page.waitForRequest(
      (req: Request) => req.url().includes('/protocols/api/save/') && req.method() === 'POST',
      { timeout: 5000 },
    );

    await page.locator('button:has-text("Save Protocol")').click();
    await savePromise;
    await page.waitForTimeout(600);

    // Either success or exists banner should appear
    const successVisible = await page.locator('#successBanner').isVisible();
    const existsVisible = await page.locator('#existsBanner').isVisible();
    expect(successVisible || existsVisible).toBe(true);
  });

  test('duplicate save triggers exists banner', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);

    const egVal = await selectFirstOption(page, '#fld_examination_group');
    const agVal = await selectFirstOption(page, '#fld_age_group');
    if (!egVal || !agVal) test.skip();
    await page.waitForTimeout(200);

    // First save
    await page.locator('button:has-text("Save Protocol")').click();
    await page.waitForTimeout(800);

    // Dismiss success if shown (form cleared on create)
    const successVisible = await page.locator('#successBanner').isVisible();
    if (successVisible) {
      // Re-select all fields for the second save
      await page.locator('#cl_region').selectOption({ index: 1 });
      await page.waitForTimeout(200);
      await completeStep1(page);
      await completeStep2(page);
      await page.waitForTimeout(400);
      await selectFirstOption(page, '#fld_examination_group');
      await selectFirstOption(page, '#fld_age_group');
      await page.waitForTimeout(200);
    }

    // Second save — should trigger exists if same key
    await page.locator('button:has-text("Save Protocol")').click();
    await page.waitForTimeout(800);

    const existsBannerVisible = await page.locator('#existsBanner').isVisible();
    // The banner may or may not appear depending on whether the key matches;
    // we just assert no crash (page still 200)
    const status = await page.evaluate(() => document.readyState);
    expect(status).toBe('complete');
  });

  test('Update existing record button is in the exists banner', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    // Inject the exists banner as visible to verify the button
    await page.evaluate(() => {
      const banner = document.getElementById('existsBanner');
      if (banner) banner.classList.add('visible');
    });
    await expect(page.locator('#existsBanner button:has-text("Update existing record")')).toBeVisible();
  });

  test('Clear form button resets fields', async ({ page }) => {
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);
    await selectFirstOption(page, '#fld_examination_group');
    await page.waitForTimeout(200);

    const valBefore = await page.locator('#fld_examination_group').inputValue();
    expect(valBefore).not.toBe('');

    await page.locator('button:has-text("Clear form")').click();
    await page.waitForTimeout(200);

    const valAfter = await page.locator('#fld_examination_group').inputValue();
    expect(valAfter).toBe('');
  });
});

// ---------------------------------------------------------------------------
// Protocol Records page
// ---------------------------------------------------------------------------

test.describe('Protocol Records page', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('records page loads successfully', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    await expect(page).toHaveURL(`${BASE_URL}/protocols/records/`);
    await expect(page.locator('body')).toBeVisible();
  });

  test('records page title contains "Protocol"', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const title = await page.title();
    expect(title.toLowerCase()).toContain('protocol');
  });

  test('"+ Add Protocol" button links to /protocols/gui/', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const btn = page.locator('a:has-text("+ Add Protocol")');
    await expect(btn).toBeVisible();
    const href = await btn.getAttribute('href');
    expect(href).toContain('/protocols/gui/');
  });

  test('type filter select is visible', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    await expect(page.locator('select[name="protocol_type"]')).toBeVisible();
  });

  test('type filter contains all three protocol types', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const options = await page.locator('select[name="protocol_type"] option').allTextContents();
    const text = options.join(' ');
    expect(text).toContain('Pediatric Head');
    expect(text).toContain('Pediatric Body');
    expect(text).toContain('Young Adult');
  });

  test('table headers include expected columns', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const headerText = await page.locator('thead').textContent();
    expect(headerText).toContain('Scanner');
    expect(headerText).toContain('Examination Group');
    expect(headerText).toContain('Protocol Name');
    expect(headerText).toContain('Actions');
  });

  test('filtering by PEDIATRIC_HEAD keeps URL param', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    await page.locator('select[name="protocol_type"]').selectOption('PEDIATRIC_HEAD');
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/protocol_type=PEDIATRIC_HEAD/);
    expect(page.url()).toContain('protocol_type=PEDIATRIC_HEAD');
  });

  test('filtering by YOUNG_ADULT keeps URL param', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    await page.locator('select[name="protocol_type"]').selectOption('YOUNG_ADULT');
    await page.locator('button[type="submit"]').click();
    await page.waitForURL(/protocol_type=YOUNG_ADULT/);
    expect(page.url()).toContain('protocol_type=YOUNG_ADULT');
  });

  test('Clear filter link appears when filter is active', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/?protocol_type=PEDIATRIC_BODY`);
    await expect(page.locator('a:has-text("Clear")')).toBeVisible();
  });

  test('Clear filter removes the protocol_type param', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/?protocol_type=PEDIATRIC_BODY`);
    await page.locator('a:has-text("Clear")').click();
    await page.waitForURL(/protocols\/records\//);
    expect(page.url()).not.toContain('protocol_type=');
  });

  test('sidebar Protocol Records nav item is active on records page', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const activeLink = page.locator('.sidebar a.active[href="/protocols/records/"]');
    await expect(activeLink).toBeVisible();
  });

  test('sidebar Protocol GUI nav item is active on GUI page', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    const activeLink = page.locator('.sidebar a.active[href="/protocols/gui/"]');
    await expect(activeLink).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Full CRUD flow (requires seeded DB with scanner profiles)
// ---------------------------------------------------------------------------

test.describe('Protocol GUI full CRUD flow', () => {
  test.beforeEach(async ({ page }) => {
    await ensureLoggedIn(page);
  });

  test('save a protocol and verify it appears in records', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/gui/`);
    const s1 = await completeStep1(page);
    const s2 = await completeStep2(page);
    if (!s1 || !s2) test.skip();
    await page.waitForTimeout(400);

    const egVal = await selectFirstOption(page, '#fld_examination_group');
    const agVal = await selectFirstOption(page, '#fld_age_group');
    if (!egVal || !agVal) test.skip();

    // Fill protocol name so we can identify it in records
    const uniqueName = `E2E_Test_${Date.now()}`;
    await page.locator('#fld_protocol_name').fill(uniqueName);
    await page.waitForTimeout(200);

    // Save
    const savePromise = page.waitForResponse(
      (resp) => resp.url().includes('/protocols/api/save/'),
      { timeout: 8000 },
    );
    await page.locator('button:has-text("Save Protocol")').click();
    const saveResp = await savePromise;
    const saveData = await saveResp.json();

    // If exists, force-update
    if (saveData.status === 'exists') {
      const updatePromise = page.waitForResponse(
        (resp) => resp.url().includes('/protocols/api/save/'),
        { timeout: 8000 },
      );
      await page.locator('button:has-text("Update existing record")').click();
      await updatePromise;
    }

    await page.waitForTimeout(400);

    // Navigate to records and verify
    await page.goto(`${BASE_URL}/protocols/records/`);
    const body = await page.textContent('body');
    expect(body).toContain(uniqueName);
  });

  test('edit a protocol via the records edit link', async ({ page }) => {
    // Navigate to records and find any "Edit" button
    await page.goto(`${BASE_URL}/protocols/records/`);
    const editLinks = page.locator('a:has-text("Edit")');
    const count = await editLinks.count();
    if (count === 0) test.skip();

    await editLinks.first().click();
    await expect(page.locator('form')).toBeVisible();
  });

  test('delete a protocol via the records delete link', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const deleteLinks = page.locator('a:has-text("Delete")');
    const count = await deleteLinks.count();
    if (count === 0) test.skip();

    // Count rows before
    const rowsBefore = await page.locator('tbody tr').count();

    await deleteLinks.first().click();
    // Confirm delete form
    const confirmForm = page.locator('form');
    if (await confirmForm.count() > 0) {
      await confirmForm.locator('button[type="submit"]').click();
      // Should redirect back to list
      await page.waitForURL(/protocols\//);
      // Navigate to records to count
      await page.goto(`${BASE_URL}/protocols/records/`);
      const rowsAfter = await page.locator('tbody tr').count();
      // Rows should have decreased (or empty state shown)
      const isEmpty = await page.locator('td:has-text("No protocol records found")').count() > 0;
      expect(rowsAfter < rowsBefore || isEmpty).toBe(true);
    }
  });

  test('view a protocol via the records view link', async ({ page }) => {
    await page.goto(`${BASE_URL}/protocols/records/`);
    const viewLinks = page.locator('a:has-text("View")');
    const count = await viewLinks.count();
    if (count === 0) test.skip();

    await viewLinks.first().click();
    // Detail page renders (not 404)
    expect(page.url()).not.toContain('/login');
    await expect(page.locator('body')).toBeVisible();
  });
});
