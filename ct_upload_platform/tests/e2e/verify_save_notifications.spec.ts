/**
 * Verification: success notifications appear after saving on:
 *   1. Edit protocol form (ProtocolUpdateView) → protocol detail page
 *   2. GUI protocol page (ProtocolGUIView) → inline success banner
 */
import { test, expect, Page } from '@playwright/test';

const BASE = 'http://localhost:8003';
const CREDS = { username: 'appuser', password: 'appuser' };
const EDIT_URL = `${BASE}/protocols/PEDIATRIC_HEAD/4e0b270f-c45d-4258-b8d3-079eb183d6f9/edit/`;
const GUI_URL = `${BASE}/protocols/gui/`;

async function login(page: Page) {
  await page.goto(`${BASE}/login/`);
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 10000 });
}

test.describe('Save notifications', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  // ── 1. Edit protocol form ─────────────────────────────────────────────────
  test('edit form: success message appears on detail page after save', async ({ page }) => {
    await page.goto(EDIT_URL);
    await expect(page).not.toHaveURL(/login/);

    await page.screenshot({ path: '/tmp/notif_edit_before.png', fullPage: true });

    // Submit without changing anything — round-trip the current values
    await page.click('button[type="submit"]');
    // Wait for redirect to detail page
    await page.waitForURL((u) => !u.pathname.endsWith('/edit/'), { timeout: 10000 });

    await page.screenshot({ path: '/tmp/notif_detail_after_save.png', fullPage: true });

    // The alert-success banner must be visible with the right message
    const banner = page.locator('.alert-success');
    await expect(banner).toBeVisible({ timeout: 5000 });
    await expect(banner).toContainText('updated successfully');

    console.log('Banner text:', await banner.textContent());
    console.log('Detail URL:', page.url());
  });

  // ── 2. GUI protocol page ──────────────────────────────────────────────────
  test('GUI page: success banner appears after saving a protocol', async ({ page }) => {
    await page.goto(GUI_URL);
    await expect(page).not.toHaveURL(/login/);

    // Step 1: pick first available clinical indication / region pair
    const clinicalSel = page.locator('#cl_clinical');
    await clinicalSel.waitFor({ state: 'visible', timeout: 5000 });
    const clinicalOpts = await clinicalSel.locator('option').all();
    // Pick the first non-empty option
    let targetValue = '';
    for (const opt of clinicalOpts) {
      const val = await opt.getAttribute('value');
      if (val && val.trim()) { targetValue = val; break; }
    }
    expect(targetValue, 'No clinical options available').not.toBe('');
    await clinicalSel.selectOption(targetValue);
    await page.waitForTimeout(300); // let onClinicalChange run

    // Step 1b: select contrast if needed (may auto-select when only one option)
    const contrastSel = page.locator('#cl_contrast');
    const contrastVal = await contrastSel.inputValue();
    if (!contrastVal) {
      const contrastOpts = await contrastSel.locator('option').all();
      for (const opt of contrastOpts) {
        const v = await opt.getAttribute('value');
        if (v && v.trim()) { await contrastSel.selectOption(v); break; }
      }
    }
    await page.waitForTimeout(200);

    // Step 2: pick a scanner
    const scannerSel = page.locator('#scanner_select');
    await scannerSel.waitFor({ state: 'visible', timeout: 5000 });
    const scannerOpts = await scannerSel.locator('option').all();
    let scannerValue = '';
    for (const opt of scannerOpts) {
      const v = await opt.getAttribute('value');
      if (v && v.trim()) { scannerValue = v; break; }
    }
    if (!scannerValue) {
      console.log('No scanners registered — skipping GUI save test');
      test.skip();
      return;
    }
    await scannerSel.selectOption(scannerValue);
    await page.waitForTimeout(300);

    // Step 3: wait for the protocol form to become visible
    await expect(page.locator('#protocolFormWrap')).toBeVisible({ timeout: 5000 });

    // Pick the first examination group / age group pair
    const egSel = page.locator('#fld_eg_ag');
    await egSel.waitFor({ state: 'visible', timeout: 5000 });
    const egOpts = await egSel.locator('option').all();
    let egValue = '';
    for (const opt of egOpts) {
      const v = await opt.getAttribute('value');
      if (v && v.trim()) { egValue = v; break; }
    }
    if (egValue) {
      await egSel.selectOption(egValue);
      await page.waitForTimeout(200);
    }

    await page.screenshot({ path: '/tmp/notif_gui_before_save.png', fullPage: true });

    // Click Save Protocol
    await page.click('.btn-save');

    // Wait for either successBanner or existsBanner to appear
    await page.waitForFunction(() => {
      const s = document.getElementById('successBanner');
      const e = document.getElementById('existsBanner');
      return (s && s.style.display !== 'none') ||
             (e && e.classList.contains('visible'));
    }, null, { timeout: 8000 });

    await page.screenshot({ path: '/tmp/notif_gui_after_save.png', fullPage: true });

    const successBanner = page.locator('#successBanner');
    const existsBanner = page.locator('#existsBanner');

    const successVisible = await successBanner.isVisible();
    const existsVisible = await existsBanner.evaluate(el => el.classList.contains('visible'));

    console.log('successBanner visible:', successVisible);
    console.log('existsBanner visible:', existsVisible);

    if (existsVisible && !successVisible) {
      // Duplicate detected — click "Update existing record" and verify success banner
      console.log('Duplicate detected — testing force update path');
      await page.click('.btn-update');

      await page.waitForFunction(() => {
        const s = document.getElementById('successBanner');
        return s && s.style.display !== 'none';
      }, null, { timeout: 8000 });

      await page.screenshot({ path: '/tmp/notif_gui_after_update.png', fullPage: true });
    }

    await expect(successBanner).toBeVisible({ timeout: 5000 });
    const bannerText = await successBanner.textContent();
    console.log('GUI success banner text:', bannerText);
    expect(bannerText).toMatch(/Protocol successfully (created|updated)/);
  });

  // ── Probe: verify message is NOT shown without a save (no false positive) ─
  test('edit form: no success banner present on fresh load of detail page', async ({ page }) => {
    // Navigate directly to the detail page without saving
    await page.goto(`${BASE}/protocols/PEDIATRIC_HEAD/4e0b270f-c45d-4258-b8d3-079eb183d6f9/`);
    const banner = page.locator('.alert-success');
    // Should not exist / not be visible
    const count = await banner.count();
    expect(count, 'Stale success banner present without saving').toBe(0);
    console.log('No false-positive banner on fresh detail load — correct');
  });
});
