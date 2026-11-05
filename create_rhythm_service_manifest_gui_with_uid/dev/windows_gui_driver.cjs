/**
 * Drives the RHYTHM manifest tool's GUI on a real Windows 11 VM
 * (dockur/windows, web viewer on http://127.0.0.1:<port>/) the way a
 * partner would: open the folder in Explorer, open the .exe (Enter on the
 * selected file = the same "open" action as a double-click), fill in the
 * three paths and the batch ID, press "Generate JSON Manifest".
 *
 * Keyboard driven. Every step that has a side effect is confirmed by a
 * marker file appearing in the shared folder on the host, not by sleeping
 * and hoping.
 *
 * Quirks of driving Windows this way, found the hard way:
 *  - the Run box takes at most 259 characters, so multi-step commands live in
 *    small .bat files the driver writes into the share (stage.bat,
 *    collect.bat) and the Run box only starts them;
 *  - keyboard.type() loses Shift ("A>:_" arrives as "a.;-"), so shifted
 *    characters are sent as explicit "Shift+<key>" presses (typeText);
 *  - Win+R does not focus a Run box that is already open, so after opening
 *    it the driver clicks into its text field (the only screen coordinate
 *    used; the Run box always opens bottom-left at this 1280x800 size).
 *
 * Usage (normally via test_exe_windows_gui.sh):
 *   node windows_gui_driver.cjs --share <host shared dir> --shots <dir>
 *        --run <run_dir_name> [--port 8006] [--ready-timeout 1800]
 * <share>/<run>/in must contain RHYTHM_manifest_tool.exe, template.xlsx and
 * zips/; the manifest ends up in <share>/<run>/out/. Each run uses new
 * folders: Windows caches SMB directory handles, so reading a folder that
 * was deleted and recreated on the host fails with error 87.
 */
const fs = require('fs');
const path = require('path');

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);
const SHARE = args.share;
const SHOTS = args.shots;
const RUN = args.run;
const PORT = args.port || '8006';
const READY_TIMEOUT_S = Number(args['ready-timeout'] || 1800);
if (!SHARE || !SHOTS || !RUN) {
  console.error('usage: windows_gui_driver.cjs --share <dir> --shots <dir> --run <name> [--port 8006]');
  process.exit(2);
}
const PLAYWRIGHT = process.env.PLAYWRIGHT_MODULE
  || path.resolve(__dirname, '../../ct_upload_platform/node_modules/playwright');
const { chromium } = require(PLAYWRIGHT);

// A fresh folder per run: a folder left open in Explorer by an earlier run
// cannot be cleaned and refilled reliably.
const WIN_DIR = `C:\\rhythm_test_${new Date().toISOString().replace(/\D/g, '').slice(0, 14)}`;
const SHARE_UNC = `\\\\host.lan\\Data\\${RUN}`;
const OUT = path.join(SHARE, RUN, 'out');
const IN = path.join(SHARE, RUN, 'in');

// Batch files run from the share; %~dp0 is their own folder (...\<run>\in\).
function writeBatchFiles() {
  const crlf = (lines) => lines.join('\r\n') + '\r\n';
  fs.writeFileSync(path.join(IN, 'stage.bat'), crlf([
    '@echo off',
    'taskkill /f /im RHYTHM_manifest_tool.exe >nul 2>&1',
    // robocopy, data only: xcopy intermittently fails on this Samba share.
    `robocopy "%~dp0." "${WIN_DIR}" /E /COPY:D /DCOPY:D /R:3 /W:2 /NP /XF stage.bat collect.bat > "%~dp0..\\out\\copy.log" 2>&1`,
    `mkdir "${WIN_DIR}\\out" 2>nul`,
    `if exist "${WIN_DIR}\\RHYTHM_manifest_tool.exe" echo ok> "%~dp0..\\out\\staged.txt"`,
  ]));
  fs.writeFileSync(path.join(IN, 'collect.bat'), crlf([
    '@echo off',
    `copy /y "${WIN_DIR}\\out\\*" "%~dp0..\\out\\" > "%~dp0..\\out\\collect.log" 2>&1`,
    'echo ok> "%~dp0..\\out\\copied.txt"',
  ]));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// US layout: characters that need Shift, mapped to the unshifted key code.
const SHIFTED = {
  '>': 'Period', '<': 'Comma', ':': 'Semicolon', '"': 'Quote', '?': 'Slash', '_': 'Minus',
  '+': 'Equal', '{': 'BracketLeft', '}': 'BracketRight', '|': 'Backslash', '~': 'Backquote',
  '!': 'Digit1', '@': 'Digit2', '#': 'Digit3', '$': 'Digit4', '%': 'Digit5', '^': 'Digit6',
  '&': 'Digit7', '*': 'Digit8', '(': 'Digit9', ')': 'Digit0',
};
const RUN_BOX_FIELD = { x: 238, y: 622 };  // Run dialog "Open:" field at 1280x800
let step = 0;

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await page.waitForTimeout(4000);
  const canvas = page.locator('canvas').first();
  // Give the remote screen keyboard focus.
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width - 5, box.y + box.height / 2);

  const at = ({ x, y }) => [box.x + (x * box.width) / 1280, box.y + (y * box.height) / 800];
  const typeText = async (text) => {
    for (const ch of text) {
      if (/[A-Z]/.test(ch)) await page.keyboard.press(`Shift+Key${ch}`);
      else if (SHIFTED[ch]) await page.keyboard.press(`Shift+${SHIFTED[ch]}`);
      else await page.keyboard.type(ch);
      await page.waitForTimeout(15);
    }
  };
  const shot = async (name) => {
    step += 1;
    const file = path.join(SHOTS, `${String(step).padStart(2, '0')}_${name}.png`);
    await canvas.screenshot({ path: file });
    console.log(`  screenshot ${path.basename(file)}`);
  };
  const run = async (command) => {
    await page.keyboard.press('Meta+r');
    await page.waitForTimeout(1500);
    await page.mouse.click(...at(RUN_BOX_FIELD));
    await page.keyboard.press('Control+a');
    await typeText(command);
    await page.waitForTimeout(300);
    await page.keyboard.press('Enter');
  };
  const waitFor = async (file, timeoutS) => {
    const p = path.join(OUT, file);
    for (let t = 0; t < timeoutS * 2; t += 1) {
      if (fs.existsSync(p)) return true;
      await sleep(500);
    }
    return false;
  };
  const marker = (name) => `echo ok> ${SHARE_UNC}\\out\\${name}`;

  // 1. Wait until Windows is at the desktop and runs commands: the Run box
  //    writing a marker into the share proves keyboard, shell and share all work.
  console.log('== waiting for the Windows desktop');
  const deadline = Date.now() + READY_TIMEOUT_S * 1000;
  let ready = false;
  while (!ready && Date.now() < deadline) {
    await run(`cmd /c ${marker('ready.txt')}`);
    ready = await waitFor('ready.txt', 20);
    if (!ready) await page.waitForTimeout(20000);
  }
  if (!ready) { await shot('not_ready'); throw new Error('Windows desktop did not become ready in time'); }
  await shot('desktop_ready');

  // 2. Copy the batch to a local folder, like a partner's own disk.
  console.log('== copying the test batch to', WIN_DIR);
  // Close tool windows left over from an earlier run, then copy. The marker
  // is only written once the .exe is really there; the copy's output goes to
  // the share so a failure explains itself.
  writeBatchFiles();
  await run(`cmd /c ${SHARE_UNC}\\in\\stage.bat`);
  if (!(await waitFor('staged.txt', 90))) {
    await shot('stage_failed');
    throw new Error(`copying the batch into Windows failed; see ${path.join(OUT, 'copy.log')}`);
  }

  // 3. Open the folder in Explorer and open the .exe from there.
  console.log('== opening the .exe from Explorer');
  await run(`explorer ${WIN_DIR}`);
  await page.waitForTimeout(4000);
  await shot('explorer_folder');
  await typeText('RHYTHM_manifest');  // type-ahead selects the .exe
  await page.waitForTimeout(800);
  await shot('exe_selected');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(15000);  // one-file PyInstaller unpacks before the window appears
  await shot('gui_opened');

  // 4. Fill in the form with the keyboard (Tk focus order: entry, Browse, ...).
  console.log('== filling in the form');
  const field = async (tabs, text) => {
    for (let i = 0; i < tabs; i += 1) await page.keyboard.press('Tab');
    await page.keyboard.press('Control+a');
    await typeText(text);
  };
  await field(1, `${WIN_DIR}\\template.xlsx`);
  await field(2, `${WIN_DIR}\\zips`);
  await field(2, `${WIN_DIR}\\out\\rhythm_upload_manifest.json`);
  await field(2, 'S001-WINDOWS-GUI-TEST');
  // Keystrokes reach Windows with some lag through the viewer: let them all
  // land before pressing Tab/Space, or those would cut into the text.
  await page.waitForTimeout(3000);
  await shot('form_filled');
  await page.keyboard.press('Tab');  // SHA-256 checkbox
  await page.keyboard.press('Tab');  // Generate JSON Manifest
  await page.keyboard.press('Space');
  await page.waitForTimeout(8000);
  await shot('generated');
  await page.keyboard.press('Enter');  // dismiss "Done" / "Error"
  await page.waitForTimeout(1500);
  await shot('result_log');

  // 5. Bring the manifest back to the host and close the tool.
  console.log('== copying the manifest back to the host');
  await page.keyboard.press('Alt+F4');
  await page.waitForTimeout(1000);
  await run(`cmd /c ${SHARE_UNC}\\in\\collect.bat`);
  if (!(await waitFor('copied.txt', 60))) throw new Error('copying the manifest back to the host failed');
  await browser.close();
}

main().catch((err) => {
  console.error(`ERROR: ${err.message}`);
  process.exit(1);
});
