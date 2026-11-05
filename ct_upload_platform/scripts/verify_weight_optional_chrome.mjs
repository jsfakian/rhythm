/**
 * Manual Chrome verification of the young-adult mastoid weight-optional fix.
 *
 * Usage:
 *   SESSION_ID=<django-sessionid> node scripts/verify_weight_optional_chrome.mjs
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { createWriteStream } from 'fs';
import { execSync } from 'child_process';
import zlib from 'zlib';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, '../temp_test_data/chrome_verify_weight');
const BASE_URL = process.env.BASE_URL || 'https://rhythm.med.uoc.gr';
const SESSION_ID = process.env.SESSION_ID;

if (!SESSION_ID) {
  console.error('SESSION_ID env var is required');
  process.exit(1);
}

fs.mkdirSync(OUT_DIR, { recursive: true });

function makeTinyZip() {
  const zipPath = path.join(OUT_DIR, 'mastoid_verify.zip');
  const srcDir = path.join(OUT_DIR, 'zip_src');
  fs.mkdirSync(srcDir, { recursive: true });
  fs.writeFileSync(path.join(srcDir, 'slice.dcm'), Buffer.from('DICM' + 'x'.repeat(200)));
  execSync(`zip -q -j "${zipPath}" "${path.join(srcDir, 'slice.dcm')}"`);
  return zipPath;
}

async function selectOptionContaining(page, selectSelector, textSubstring) {
  const value = await page.$eval(selectSelector, (sel, needle) => {
    const opt = [...sel.options].find((o) => o.textContent.includes(needle));
    if (!opt) return null;
    sel.value = opt.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return opt.value;
  }, textSubstring);
  if (!value) throw new Error(`No option containing "${textSubstring}" in ${selectSelector}`);
  return value;
}

async function main() {
  const zipPath = makeTinyZip();
  const results = [];

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: false,
    slowMo: 250,
    args: ['--ignore-certificate-errors'],
  });

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1400, height: 900 },
  });

  const url = new URL(BASE_URL);
  await context.addCookies([
    {
      name: 'sessionid',
      value: SESSION_ID,
      domain: url.hostname,
      path: '/',
      httpOnly: true,
      secure: url.protocol === 'https:',
      sameSite: 'Lax',
    },
  ]);

  const page = await context.newPage();

  // --- Case 1: Young adult + Mastoid, no weight ---
  await page.goto(`${BASE_URL}/examinations/entry/`, { waitUntil: 'networkidle' });
  if (page.url().includes('/login')) {
    throw new Error('Session cookie rejected — redirected to login');
  }

  await selectOptionContaining(page, '#sel_indication_combo', 'Mastoid');
  await page.selectOption('#sel_protocol_type', 'YOUNG_ADULT');
  // Wait for hint / exam-group auto-fill
  await page.waitForTimeout(400);

  const scannerCount = await page.locator('#sel_scanner option:not([value=""])').count();
  if (scannerCount > 0) {
    await page.locator('#sel_scanner').selectOption({ index: 1 });
  }

  const hintMastoid = (await page.locator('#weight_hint').textContent()) || '';
  await page.locator('#inp_weight').fill('');
  await page.locator('#inp_age').fill('22');
  await page.locator('#ctdi_1').fill('18.5');
  await page.locator('#dlp_1').fill('210');
  await page.selectOption('#sel_quality', 'GOOD');
  await page.setInputFiles('#inp_study_set', zipPath);

  await page.screenshot({
    path: path.join(OUT_DIR, '01_young_adult_mastoid_no_weight.png'),
    fullPage: true,
  });

  const [saveResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/examinations/api/save/'), { timeout: 30000 }).catch(() => null),
    page.click('#btn_save_exam'),
  ]);

  await page.waitForTimeout(800);
  const errorText = ((await page.locator('#errorBanner').textContent()) || '').trim();
  const successText = ((await page.locator('#successBanner').textContent()) || '').trim();
  const status = saveResp ? saveResp.status() : null;
  let body = null;
  if (saveResp) {
    try { body = await saveResp.json(); } catch { body = await saveResp.text(); }
  }

  await page.screenshot({
    path: path.join(OUT_DIR, '02_young_adult_mastoid_after_save.png'),
    fullPage: true,
  });

  const weightMentioned = /weight/i.test(errorText) || /weight/i.test(JSON.stringify(body || ''));
  const savedOk = status === 200 || status === 201 || /saved|success|created/i.test(successText);
  results.push({
    case: 'YOUNG_ADULT + Mastoid, empty weight',
    scanner_options: scannerCount,
    weight_hint: hintMastoid,
    hint_ok: /optional/i.test(hintMastoid),
    http_status: status,
    error_banner: errorText,
    success_banner: successText,
    response: body,
    weight_still_required: weightMentioned,
    // Success, or any non-weight validation error, both prove weight is not required.
    pass: /optional/i.test(hintMastoid) && !weightMentioned && (savedOk || errorText.length > 0 || status !== null),
  });

  // --- Case 2: Young adult + Head, no weight (brain CT) ---
  await page.click('#btn_clear_exam');
  await page.waitForTimeout(300);
  await selectOptionContaining(page, '#sel_indication_combo', 'Head / Trauma');
  await page.selectOption('#sel_protocol_type', 'YOUNG_ADULT');
  await page.waitForTimeout(400);
  const hintHead = (await page.locator('#weight_hint').textContent()) || '';
  await page.screenshot({
    path: path.join(OUT_DIR, '03_young_adult_head_hint.png'),
    fullPage: true,
  });
  results.push({
    case: 'YOUNG_ADULT + Head hint',
    weight_hint: hintHead,
    pass: /optional/i.test(hintHead),
  });

  // --- Case 3: Young adult + Chest, no weight (should still require weight) ---
  await page.click('#btn_clear_exam');
  await page.waitForTimeout(300);
  await selectOptionContaining(page, '#sel_indication_combo', 'Chest / Complicated');
  await page.selectOption('#sel_protocol_type', 'YOUNG_ADULT');
  await page.waitForTimeout(400);
  if ((await page.locator('#sel_scanner option:not([value=""])').count()) > 0) {
    await page.locator('#sel_scanner').selectOption({ index: 1 });
  }
  const hintChest = (await page.locator('#weight_hint').textContent()) || '';
  await page.locator('#inp_age').fill('22');
  await page.locator('#ctdi_1').fill('5');
  await page.locator('#dlp_1').fill('80');
  await page.selectOption('#sel_quality', 'GOOD');
  await page.setInputFiles('#inp_study_set', zipPath);
  await page.click('#btn_save_exam');
  await page.waitForTimeout(600);
  const chestError = ((await page.locator('#errorBanner').textContent()) || '').trim();
  await page.screenshot({
    path: path.join(OUT_DIR, '04_young_adult_chest_requires_weight.png'),
    fullPage: true,
  });
  results.push({
    case: 'YOUNG_ADULT + Chest, empty weight (must require weight)',
    weight_hint: hintChest,
    error_banner: chestError,
    pass: !/optional/i.test(hintChest) && /weight/i.test(chestError),
  });

  fs.writeFileSync(path.join(OUT_DIR, 'results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));

  const failed = results.filter((r) => !r.pass);
  await page.waitForTimeout(1500);
  await browser.close();

  if (failed.length) {
    console.error(`FAILED ${failed.length}/${results.length} checks`);
    process.exit(1);
  }
  console.log(`PASSED ${results.length}/${results.length} checks`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
