/**
 * Focused verification: Save Protocol form in Protocol GUI
 *
 * Uses the actual selectors from protocol_clinical_gui.html:
 *   #cl_clinical   – combined "Region / Indication" dropdown
 *   #cl_contrast   – IV contrast dropdown
 *   #scanner_select – scanner dropdown
 *   #fld_eg_ag     – combined Examination Group / Age Group (index-valued)
 *
 * Run:
 *   BASE_URL=http://localhost:8003 npx playwright test protocol_save_verify.spec.ts --project=chromium
 */

import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8003';
const USERNAME = process.env.TEST_USERNAME ?? 'admin';
const PASSWORD = process.env.TEST_PASSWORD ?? 'adminpass123';

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login/`);
  await page.fill('#username', USERNAME);
  await page.fill('#password', PASSWORD);
  await page.click('#loginBtn');
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 12000 });
}

async function navigateToGUI(page: Page): Promise<void> {
  const resp = await page.goto(`${BASE_URL}/protocols/gui/`);
  if (resp && resp.url().includes('/login')) {
    await login(page);
    await page.goto(`${BASE_URL}/protocols/gui/`);
  }
  await page.waitForLoadState('networkidle');
}

// ---------------------------------------------------------------------------
// Helper: select the first non-empty option in a <select>
// ---------------------------------------------------------------------------
async function pickFirst(page: Page, sel: string): Promise<string | null> {
  const opts = await page.locator(`${sel} option:not([value=""])`).all();
  if (!opts.length) return null;
  const val = await opts[0].getAttribute('value');
  if (val !== null) await page.locator(sel).selectOption(val);
  return val;
}

// ---------------------------------------------------------------------------
// Test 1: page loads and all three steps are present
// ---------------------------------------------------------------------------
test('protocol GUI page structure is intact', async ({ page }) => {
  await navigateToGUI(page);
  await expect(page.locator('#cl_clinical')).toBeVisible();
  await expect(page.locator('#cl_contrast')).toBeVisible();
  await expect(page.locator('#scanner_select')).toBeVisible();
  await expect(page.locator('button:has-text("Save Protocol")')).toBeVisible();
  await expect(page.locator('#protocolBlocked')).toBeVisible();
  await expect(page.locator('#protocolFormWrap')).not.toBeVisible();
});

// ---------------------------------------------------------------------------
// Test 2: Step 1 dropdowns cascade correctly
// ---------------------------------------------------------------------------
test('Step 1 – selecting clinical indication populates contrast', async ({ page }) => {
  await navigateToGUI(page);
  const val = await pickFirst(page, '#cl_clinical');
  expect(val).not.toBeNull();
  await page.waitForTimeout(300);
  const contrastCount = await page.locator('#cl_contrast option:not([value=""])').count();
  expect(contrastCount).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
// Test 3: protocol form unlocks only when Step 1 + Step 2 are complete
// ---------------------------------------------------------------------------
test('Step 3 – form unlocks after Step 1 and Step 2 are complete', async ({ page }) => {
  await navigateToGUI(page);

  // Step 1: pick clinical (auto-selects contrast when only one option)
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);

  // Form should still be blocked (no scanner yet)
  await expect(page.locator('#protocolBlocked')).toBeVisible();

  // Step 2: pick scanner
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  // Now form should be visible
  await expect(page.locator('#protocolFormWrap')).toBeVisible();
  await expect(page.locator('#protocolBlocked')).not.toBeVisible();
});

// ---------------------------------------------------------------------------
// Test 4: protocol tabs render (at least Pediatric HEAD and Young Adult)
// ---------------------------------------------------------------------------
test('Step 3 – protocol tabs are rendered', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  const tabTexts = await page.locator('.tab-btn').allTextContents();
  expect(tabTexts.some(t => t.toLowerCase().includes('pediatric'))).toBe(true);
  expect(tabTexts.some(t => t.toLowerCase().includes('young adult'))).toBe(true);
});

// ---------------------------------------------------------------------------
// Test 5: combined EG/AG dropdown (#fld_eg_ag) is present and has options
// ---------------------------------------------------------------------------
test('Step 3 – examination group / age group dropdown has options', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  await expect(page.locator('#fld_eg_ag')).toBeVisible();
  const count = await page.locator('#fld_eg_ag option:not([value=""])').count();
  expect(count).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
// Test 6: Clicking Save without Step 1 shows an alert
// ---------------------------------------------------------------------------
test('Save without Step 1 shows alert', async ({ page }) => {
  await navigateToGUI(page);
  let dialogMessage = '';
  page.once('dialog', async (dialog) => { dialogMessage = dialog.message(); await dialog.dismiss(); });
  await page.locator('button:has-text("Save Protocol")').click();
  await page.waitForTimeout(500);
  expect(dialogMessage.toLowerCase()).toMatch(/step 1|clinical indication|region/);
});

// ---------------------------------------------------------------------------
// Test 7: Clicking Save with Step 1 but no scanner shows scanner alert
// ---------------------------------------------------------------------------
test('Save without scanner shows alert', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);

  let dialogMessage = '';
  page.once('dialog', async (dialog) => { dialogMessage = dialog.message(); await dialog.dismiss(); });
  await page.locator('button:has-text("Save Protocol")').click();
  await page.waitForTimeout(500);
  expect(dialogMessage.toLowerCase()).toContain('scanner');
});

// ---------------------------------------------------------------------------
// Test 8: Clicking Save without EG/AG shows alert (core validation)
// ---------------------------------------------------------------------------
test('Save without examination group shows alert', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  // Do NOT pick fld_eg_ag
  let dialogMessage = '';
  page.once('dialog', async (dialog) => { dialogMessage = dialog.message(); await dialog.dismiss(); });
  await page.locator('button:has-text("Save Protocol")').click();
  await page.waitForTimeout(500);
  expect(dialogMessage.toLowerCase()).toMatch(/examination|age|group/);
});

// ---------------------------------------------------------------------------
// Test 9 (MAIN): Full save flow → success banner (or exists banner)
// ---------------------------------------------------------------------------
test('SAVE PROTOCOL – full flow → success or exists banner', async ({ page }) => {
  await navigateToGUI(page);

  // Step 1
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(400);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(300);

  // Step 2
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(500);

  // Step 3 form must now be visible
  await expect(page.locator('#protocolFormWrap')).toBeVisible({ timeout: 3000 });

  // Pick examination group / age group (index 0)
  await page.locator('#fld_eg_ag').selectOption({ index: 1 }); // index 0 is the blank
  await page.waitForTimeout(300);

  // Verify onCombinedEgAgChange wired the state (progress bar should advance)
  const pctText = await page.locator('#completionPct').textContent();
  const pct = parseInt(pctText ?? '0');
  expect(pct).toBeGreaterThan(0);

  // Intercept the save API call
  const saveRespPromise = page.waitForResponse(
    (resp) => resp.url().includes('/protocols/api/save/') && resp.request().method() === 'POST',
    { timeout: 8000 }
  );

  await page.locator('button:has-text("Save Protocol")').click();
  const saveResp = await saveRespPromise;

  // Must be 200 (not 500 / 400)
  expect(saveResp.status()).toBe(200);

  const body = await saveResp.json();
  console.log('API response:', JSON.stringify(body));

  // Must return a valid status
  expect(['created', 'updated', 'exists']).toContain(body.status);

  await page.waitForTimeout(500);

  // Either success banner or exists banner must be visible
  const successVisible = await page.locator('#successBanner').isVisible();
  const existsVisible  = await page.locator('#existsBanner').isVisible();
  expect(successVisible || existsVisible).toBe(true);

  if (successVisible) {
    const msg = await page.locator('#successBanner').textContent();
    console.log('Success banner:', msg);
    expect(msg).toMatch(/successfully (created|updated)/i);
  } else {
    const msg = await page.locator('#existsBanner').textContent();
    console.log('Exists banner:', msg);

    // Force-update and expect success
    const updateRespPromise = page.waitForResponse(
      (resp) => resp.url().includes('/protocols/api/save/') && resp.request().method() === 'POST',
      { timeout: 8000 }
    );
    await page.locator('#existsBanner button:has-text("Update existing record")').click();
    const updateResp = await updateRespPromise;
    expect(updateResp.status()).toBe(200);
    const updateBody = await updateResp.json();
    expect(updateBody.status).toBe('updated');

    await page.waitForTimeout(500);
    await expect(page.locator('#successBanner')).toBeVisible();
  }
});

// ---------------------------------------------------------------------------
// Test 10: progress bar updates as fields are filled
// ---------------------------------------------------------------------------
test('progress bar advances when EG/AG selected', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  const pctBefore = parseInt(await page.locator('#completionPct').textContent() ?? '0');

  await page.locator('#fld_eg_ag').selectOption({ index: 1 });
  await page.waitForTimeout(300);

  const pctAfter = parseInt(await page.locator('#completionPct').textContent() ?? '0');
  expect(pctAfter).toBeGreaterThan(pctBefore);
});

// ---------------------------------------------------------------------------
// Test 11: Clear form resets EG/AG field back to blank
// ---------------------------------------------------------------------------
test('Clear form resets EG/AG dropdown', async ({ page }) => {
  await navigateToGUI(page);
  await pickFirst(page, '#cl_clinical');
  await page.waitForTimeout(300);
  await pickFirst(page, '#cl_contrast');
  await page.waitForTimeout(200);
  await pickFirst(page, '#scanner_select');
  await page.waitForTimeout(400);

  await page.locator('#fld_eg_ag').selectOption({ index: 1 });
  const valBefore = await page.locator('#fld_eg_ag').inputValue();
  expect(valBefore).not.toBe('');

  await page.locator('button:has-text("Clear form")').click();
  await page.waitForTimeout(300);

  const valAfter = await page.locator('#fld_eg_ag').inputValue();
  expect(valAfter).toBe('');
});
