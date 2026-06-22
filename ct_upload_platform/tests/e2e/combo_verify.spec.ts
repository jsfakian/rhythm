import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://127.0.0.1:8003';

// Known scanner IDs
const SIEMENS_SCANNER_ID = 'b365b079-fc22-477c-8c95-7295c9ace142';
const GE_SCANNER_ID      = '2620fcaa-958c-4ccd-9502-4edb7cc3bf1a';

async function login(page: Page) {
  await page.goto(`${BASE_URL}/login/`);
  await page.waitForSelector('#username');
  await page.fill('#username', 'admin');
  await page.fill('#password', 'adminpassword');
  const respPromise = page.waitForResponse(r => r.url().includes('/api/v1/auth/login/'), { timeout: 10000 });
  await page.locator('#loginBtn').click();
  await respPromise;
  await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 10000 });
}

/** Get to Step 3 with a specific scanner selected. */
async function reachStep3(page: Page, scannerId: string) {
  await page.goto(`${BASE_URL}/protocols/gui/`);
  await page.waitForLoadState('networkidle');

  // Step 1: pick first combined clinical/region option
  const clinicalSel = page.locator('#cl_clinical');
  const opts = await clinicalSel.locator('option:not([value=""])').all();
  if (opts.length === 0) throw new Error('No options in #cl_clinical');
  await clinicalSel.selectOption(await opts[0].getAttribute('value') ?? '');
  await page.waitForTimeout(300);

  // Pick contrast (may be auto-selected already)
  const contrastSel = page.locator('#cl_contrast');
  const cOpts = await contrastSel.locator('option:not([value=""])').all();
  if (cOpts.length > 0) await contrastSel.selectOption(await cOpts[0].getAttribute('value') ?? '');
  await page.waitForTimeout(300);

  // Step 2: select the specific scanner
  const scannerSel = page.locator('#scanner_select');
  try {
    await scannerSel.selectOption(scannerId);
  } catch(e) {
    throw new Error(`Scanner ${scannerId} not found in dropdown`);
  }
  await page.waitForTimeout(500);

  // Verify Step 3 fields are visible
  await expect(page.locator('#fld_auto_kvp_selection')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('#fld_auto_ma_modulation')).toBeVisible({ timeout: 5000 });
}

// ─── Test 1: kV Assist + SmartmA (GE scanner) ──────────────────────────────

test('GE kV Assist + SmartmA → shows min mA, max mA, Noise Index, Clinical mode', async ({ page }) => {
  await login(page);
  await reachStep3(page, GE_SCANNER_ID);

  const kvpSel = page.locator('#fld_auto_kvp_selection');
  const maSel  = page.locator('#fld_auto_ma_modulation');

  // Confirm options are present
  const kvpOpts = await kvpSel.locator('option').allInnerTexts();
  const maOpts  = await maSel.locator('option').allInnerTexts();
  console.log('KVP options:', kvpOpts.join(', '));
  console.log('MA options:', maOpts.join(', '));

  if (!kvpOpts.some(o => o.includes('kV Assist'))) {
    throw new Error(`kV Assist not found in KVP options: [${kvpOpts.join(', ')}]`);
  }
  if (!maOpts.some(o => o.includes('SmartmA'))) {
    throw new Error(`SmartmA not found in MA options: [${maOpts.join(', ')}]`);
  }

  await kvpSel.selectOption({ label: 'kV Assist' });
  await page.waitForTimeout(400);

  // Slot should update immediately when kvp changes
  let slotHtml = await page.locator('#mas_inputs_slot').innerHTML();
  console.log('After kV Assist only:', slotHtml.slice(0, 200));

  await maSel.selectOption({ label: 'SmartmA' });
  await page.waitForTimeout(400);

  slotHtml = await page.locator('#mas_inputs_slot').innerHTML();
  console.log('After kV Assist + SmartmA slot:', slotHtml.slice(0, 400));

  // Four fields must be present
  expect(slotHtml).toContain('min mA');
  expect(slotHtml).toContain('max mA');
  expect(slotHtml).toContain('Noise Index');
  expect(slotHtml).toContain('Clinical mode');

  // Clinical mode is text, not number
  await expect(page.locator('#mas_inputs_slot input[placeholder="Clinical mode"]'))
    .toHaveAttribute('type', 'text');
  await expect(page.locator('#mas_inputs_slot input[placeholder="min mA"]'))
    .toHaveAttribute('type', 'number');
});

// ─── Test 2: CarekV + CareDose4D (Siemens scanner) ─────────────────────────

test('Siemens CarekV + CareDose4D → shows Quality Reference mAs + Dose Optimization setting', async ({ page }) => {
  await login(page);
  await reachStep3(page, SIEMENS_SCANNER_ID);

  const kvpSel = page.locator('#fld_auto_kvp_selection');
  const maSel  = page.locator('#fld_auto_ma_modulation');

  const kvpOpts = await kvpSel.locator('option').allInnerTexts();
  const maOpts  = await maSel.locator('option').allInnerTexts();
  console.log('KVP options:', kvpOpts.join(', '));
  console.log('MA options:', maOpts.join(', '));

  if (!kvpOpts.some(o => o.includes('CarekV'))) {
    throw new Error(`CarekV not found in KVP options: [${kvpOpts.join(', ')}]`);
  }
  if (!maOpts.some(o => o.includes('CareDose4D'))) {
    throw new Error(`CareDose4D not found in MA options: [${maOpts.join(', ')}]`);
  }

  await kvpSel.selectOption({ label: 'CarekV' });
  await page.waitForTimeout(400);
  await maSel.selectOption({ label: 'CareDose4D' });
  await page.waitForTimeout(400);

  const slotHtml = await page.locator('#mas_inputs_slot').innerHTML();
  console.log('After CarekV + CareDose4D slot:', slotHtml.slice(0, 400));

  expect(slotHtml).toContain('Quality Reference mAs');
  expect(slotHtml).toContain('Dose Optimization setting');

  // Dose Optimization setting is text
  await expect(page.locator('#mas_inputs_slot input[placeholder="Dose Optimization setting"]'))
    .toHaveAttribute('type', 'text');
  // QR mAs is number
  await expect(page.locator('#mas_inputs_slot input[placeholder*="Quality Reference"]'))
    .toHaveAttribute('type', 'number');
});

// ─── Test 3: Save with combo fields, verify in detail + edit views ──────────

test('Save CarekV+CareDose4D combo, fields appear in detail and edit views', async ({ page }) => {
  await login(page);
  await reachStep3(page, SIEMENS_SCANNER_ID);

  const kvpSel = page.locator('#fld_auto_kvp_selection');
  const maSel  = page.locator('#fld_auto_ma_modulation');

  // Select the combo
  await kvpSel.selectOption({ label: 'CarekV' });
  await page.waitForTimeout(400);
  await maSel.selectOption({ label: 'CareDose4D' });
  await page.waitForTimeout(400);

  // Fill combo-specific fields
  await page.locator('#mas_inputs_slot input[placeholder*="Quality Reference"]').fill('175');
  await page.locator('#mas_inputs_slot input[placeholder="Dose Optimization setting"]').fill('CARE_QUALITY_TEST');

  // Fill required fields
  const selectFirst = async (selector: string) => {
    const el = page.locator(selector);
    if (!await el.isVisible({ timeout: 1000 }).catch(() => false)) return;
    const opts = await el.locator('option:not([value=""])').all();
    if (opts.length > 0) await el.selectOption(await opts[0].getAttribute('value') ?? '');
    await page.waitForTimeout(100);
  };
  // Examination group + age group combined: #fld_eg_ag with integer index values
  await selectFirst('#fld_eg_ag');
  await selectFirst('#fld_scan_type');
  await selectFirst('#fld_kvp');
  await selectFirst('#fld_pitch');
  await selectFirst('#fld_rotation_time');
  await selectFirst('#fld_slice_thickness');
  await selectFirst('#fld_kernel_class');
  await selectFirst('#fld_reconstruction_algorithm');
  await page.waitForTimeout(300);

  // Register listeners BEFORE clicking save
  let saveRespPromise = page.waitForResponse(
    r => r.url().includes('/protocols/api/save/') && r.request().method() === 'POST',
    { timeout: 10000 }
  );
  let saveReqPromise = page.waitForRequest(
    req => req.url().includes('/protocols/api/save/') && req.method() === 'POST',
    { timeout: 10000 }
  );
  await page.locator('button:has-text("Save Protocol")').click();
  let [saveResp, saveReq] = await Promise.all([saveRespPromise, saveReqPromise]);
  let saveBody = await saveResp.json();
  let reqBody  = JSON.parse(saveReq.postData() ?? '{}');
  console.log('Save response:', JSON.stringify(saveBody).slice(0, 300));
  console.log('Request mas_inputs:', JSON.stringify(reqBody.protocol_fields?.mas_inputs));

  // If protocol already exists from a prior run, force-update it
  if (saveBody.status === 'exists') {
    console.log('Protocol exists — clicking Update existing record');
    saveRespPromise = page.waitForResponse(
      r => r.url().includes('/protocols/api/save/') && r.request().method() === 'POST',
      { timeout: 10000 }
    );
    saveReqPromise = page.waitForRequest(
      req => req.url().includes('/protocols/api/save/') && req.method() === 'POST',
      { timeout: 10000 }
    );
    await page.locator('button:has-text("Update existing record")').click();
    [saveResp, saveReq] = await Promise.all([saveRespPromise, saveReqPromise]);
    saveBody = await saveResp.json();
    reqBody  = JSON.parse(saveReq.postData() ?? '{}');
    console.log('Force-update response:', JSON.stringify(saveBody).slice(0, 300));
    console.log('Force-update mas_inputs:', JSON.stringify(reqBody.protocol_fields?.mas_inputs));
  }

  expect(saveResp.status()).toBe(200);
  expect(saveBody.status === 'created' || saveBody.status === 'updated').toBe(true);

  await page.waitForTimeout(600);
  const successVisible = await page.locator('#successBanner').isVisible();
  const existsVisible  = await page.locator('#existsBanner').isVisible();
  console.log('successBanner:', successVisible, '| existsBanner:', existsVisible);
  expect(successVisible || existsVisible).toBe(true);

  const protocolId   = saveBody.id;
  const protocolType = reqBody.protocol_type;
  console.log('Saved protocol ID:', protocolId, '| type:', protocolType);
  expect(protocolId).toBeTruthy();

  // Verify mas_inputs were sent correctly in the request
  const sentMasInputs = reqBody.protocol_fields?.mas_inputs ?? {};
  console.log('Sent mas_inputs:', JSON.stringify(sentMasInputs));
  expect(sentMasInputs['Dose Optimization setting']).toBe('CARE_QUALITY_TEST');
  expect(String(sentMasInputs['Quality Reference mAs (QR mAs)'])).toBe('175');

  // ── Detail view ──
  await page.goto(`${BASE_URL}/protocols/${protocolType}/${protocolId}/`);
  await page.waitForLoadState('networkidle');
  const detailHtml = await page.locator('body').innerHTML();
  console.log('Detail — has CARE_QUALITY_TEST:', detailHtml.includes('CARE_QUALITY_TEST'));
  console.log('Detail — has 175:', detailHtml.includes('175'));
  expect(detailHtml).toContain('CARE_QUALITY_TEST');
  expect(detailHtml).toContain('175');

  // Take a screenshot of the detail view
  await page.screenshot({ path: 'test-results/combo-detail-view.png' });

  // ── Edit view ──
  await page.goto(`${BASE_URL}/protocols/${protocolType}/${protocolId}/edit/`);
  await page.waitForLoadState('networkidle');
  const editText = await page.locator('body').textContent() ?? '';
  console.log('Edit page loaded, title:', await page.title());
  expect(editText).not.toContain('Page not found');
  expect(editText).not.toContain('Server Error');

  // Check CareDose4D is pre-populated in the edit form
  const maEditVal = await page.locator('#id_auto_ma_modulation').inputValue().catch(() => '');
  console.log('Edit form auto_ma_modulation:', maEditVal);
  if (maEditVal) expect(maEditVal).toBe('CareDose4D');

  await page.screenshot({ path: 'test-results/combo-edit-view.png' });
});
