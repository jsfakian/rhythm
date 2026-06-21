/**
 * Verification: protocol edit form — removed fields and save behaviour.
 */
import { test, expect, Page } from '@playwright/test';

const BASE = 'http://localhost:8003';
const CREDS = { username: 'appuser', password: 'testpass123' };
const EDIT_URL = `${BASE}/protocols/PEDIATRIC_HEAD/4e0b270f-c45d-4258-b8d3-079eb183d6f9/edit/`;

async function login(page: Page) {
  await page.goto(`${BASE}/login/`);
  await page.fill('#username', CREDS.username);
  await page.fill('#password', CREDS.password);
  await page.click('#loginBtn');
  await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 10000 });
}

test.describe('Protocol edit form – field removal verification', () => {

  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('removed fields are absent from the edit form', async ({ page }) => {
    await page.goto(EDIT_URL);
    await expect(page).not.toHaveURL(/login/);

    // ── Fields that must NOT be present ──────────────────────────────────
    await expect(page.locator('[name="protocol_name"]')).toHaveCount(0);
    await expect(page.locator('[name="number_of_phases"]')).toHaveCount(0);
    await expect(page.locator('[name="scan_fov"]')).toHaveCount(0);
    await expect(page.locator('[name="protocol_intent"]')).toHaveCount(0);
    await expect(page.locator('[name="dose_metadata"]')).toHaveCount(0);
    await expect(page.locator('[name="notes"]')).toHaveCount(0);

    // ── Section heading must NOT be present ──────────────────────────────
    const headings = page.locator('h2');
    const texts = await headings.allTextContents();
    const hasIntentSection = texts.some(t => /protocol intent/i.test(t));
    expect(hasIntentSection, 'Protocol Intent & Dose section heading still present').toBe(false);

    // ── Core fields that MUST still be present ───────────────────────────
    await expect(page.locator('[name="scanner"]')).toHaveCount(1);
    await expect(page.locator('[name="scan_type"]')).toHaveCount(1);
    await expect(page.locator('[name="kvp"]')).toHaveCount(1);
    await expect(page.locator('[name="kernel_class"]')).toHaveCount(1);
    await expect(page.locator('[name="reconstruction_algorithm"]')).toHaveCount(1);
    await expect(page.locator('[name="strength"]')).toHaveCount(1);

    // kernel_class and reconstruction_algorithm must be text inputs (not selects)
    await expect(page.locator('input[name="kernel_class"]')).toHaveCount(1);
    await expect(page.locator('input[name="reconstruction_algorithm"]')).toHaveCount(1);

    console.log('Section headings found:', texts);
  });

  test('scan_type dropdown only shows helical/axial/sequential/spiral options', async ({ page }) => {
    await page.goto(EDIT_URL);
    const options = await page.locator('[name="scan_type"] option').allTextContents();
    console.log('scan_type options:', options);

    const filtered = options.filter(o => o.trim() && !/^---/.test(o));
    const pattern = /sequential|axial|helical|spiral/i;
    const invalid = filtered.filter(o => !pattern.test(o));
    expect(invalid, `Unexpected scan_type options present: ${invalid.join(', ')}`).toHaveLength(0);
  });

  test('form saves successfully and redirects to detail view', async ({ page }) => {
    await page.goto(EDIT_URL);

    // Take a screenshot of the form before saving
    await page.screenshot({ path: '/tmp/edit_form_before.png', fullPage: true });

    // Just click Save without changing anything — round-trip the existing values
    await page.click('button[type="submit"]');
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
    await page.screenshot({ path: '/tmp/edit_form_after.png', fullPage: true });
    console.log('URL after submit:', page.url());

    // Log any visible field errors
    const errors = await page.locator('.field-errors li, .alert-error li, .errorlist li').allTextContents();
    if (errors.length) console.log('Form errors:', errors);

    // Should redirect to the detail page (not stay on /edit/)
    await page.waitForURL((u) => !u.pathname.endsWith('/edit/'), { timeout: 10000 });
    expect(page.url()).not.toContain('/edit/');
    expect(page.url()).toContain('/protocols/PEDIATRIC_HEAD/');
  });

  test('detail view after save also lacks removed fields', async ({ page }) => {
    // Navigate to detail view directly
    await page.goto(`${BASE}/protocols/PEDIATRIC_HEAD/4e0b270f-c45d-4258-b8d3-079eb183d6f9/`);
    const headings = page.locator('h2');
    const texts = await headings.allTextContents();
    console.log('Detail headings:', texts);

    const hasIntentSection = texts.some(t => /protocol intent/i.test(t));
    expect(hasIntentSection).toBe(false);

    // These labels must not appear in the detail page
    const bodyText = await page.locator('body').textContent();
    expect(bodyText).not.toMatch(/Protocol Name/i);
    expect(bodyText).not.toMatch(/Number of Phases/i);
    expect(bodyText).not.toMatch(/Scan FOV/i);
    expect(bodyText).not.toMatch(/Protocol Intent/i);
    expect(bodyText).not.toMatch(/Dose Metadata/i);

    await page.screenshot({ path: '/tmp/detail_view.png', fullPage: true });
  });
});
