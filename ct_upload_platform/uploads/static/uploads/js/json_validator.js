function validateJSON() {
    const text = document.getElementById('jsonInput').value.trim();
    const box = document.getElementById('resultBox');
    const statRow = document.getElementById('statRow');
    document.getElementById('prettyOut').style.display = 'none';
    statRow.innerHTML = '';
    box.className = 'result-box';
    box.style.display = '';

    if (!text) {
        box.className = 'result-box result-warn';
        box.textContent = 'No JSON text to validate. Paste some JSON or load a file first.';
        return;
    }
    try {
        const parsed = JSON.parse(text);
        box.className = 'result-box result-ok';
        box.textContent = 'Valid JSON — no syntax errors found.';
        statRow.innerHTML = buildStats(parsed, text);
    } catch (e) {
        box.className = 'result-box result-err';
        box.innerHTML = '<strong>Invalid JSON:</strong> ' + escHtml(e.message);
        const m = e.message.match(/position (\d+)/);
        if (m) {
            const pos = parseInt(m[1]);
            const snippet = text.substring(Math.max(0, pos - 30), pos + 30);
            box.innerHTML += '<br><code style="font-size:12px;opacity:.8;">…' + escHtml(snippet) + '…</code>';
        }
    }
}

function buildStats(parsed, text) {
    const type = Array.isArray(parsed) ? 'array' : typeof parsed;
    let stats = `<span class="stat">Type: ${type}</span>`;
    if (type === 'object') stats += `<span class="stat">Keys: ${Object.keys(parsed).length}</span>`;
    if (Array.isArray(parsed)) stats += `<span class="stat">Items: ${parsed.length}</span>`;
    stats += `<span class="stat">Size: ${(text.length / 1024).toFixed(1)} KB</span>`;
    return stats;
}

function prettyPrint() {
    const text = document.getElementById('jsonInput').value.trim();
    const pre = document.getElementById('prettyOut');
    const box = document.getElementById('resultBox');
    box.style.display = 'none';
    pre.style.display = 'none';
    if (!text) return;
    try {
        const parsed = JSON.parse(text);
        pre.textContent = JSON.stringify(parsed, null, 2);
        pre.style.display = 'block';
    } catch (e) {
        box.className = 'result-box result-err';
        box.innerHTML = '<strong>Cannot pretty-print:</strong> ' + escHtml(e.message);
    }
}

function minify() {
    const text = document.getElementById('jsonInput').value.trim();
    if (!text) return;
    try {
        const parsed = JSON.parse(text);
        document.getElementById('jsonInput').value = JSON.stringify(parsed);
        document.getElementById('prettyOut').style.display = 'none';
        validateJSON();
    } catch (e) {
        const box = document.getElementById('resultBox');
        box.className = 'result-box result-err';
        box.innerHTML = '<strong>Cannot minify:</strong> ' + escHtml(e.message);
    }
}

function clearAll() {
    document.getElementById('jsonInput').value = '';
    document.getElementById('resultBox').className = 'result-box';
    document.getElementById('resultBox').style.display = 'none';
    document.getElementById('prettyOut').style.display = 'none';
    document.getElementById('statRow').innerHTML = '';
    document.getElementById('fileInput').value = '';
}

function loadFile() {
    const fi = document.getElementById('fileInput');
    if (!fi.files || !fi.files[0]) { alert('Please select a .json file first.'); return; }
    const reader = new FileReader();
    reader.onload = e => {
        document.getElementById('jsonInput').value = e.target.result;
        validateJSON();
    };
    reader.readAsText(fi.files[0]);
}

document.getElementById('fileInput').addEventListener('change', () => {
    if (document.getElementById('fileInput').files[0]) loadFile();
});
document.getElementById('btnLoadFile').addEventListener('click', loadFile);
document.getElementById('btnValidate').addEventListener('click', validateJSON);
document.getElementById('btnPrettyPrint').addEventListener('click', prettyPrint);
document.getElementById('btnMinify').addEventListener('click', minify);
document.getElementById('btnClearAll').addEventListener('click', clearAll);

function escHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
}
