// Automated (bulk batch) upload page.
//
// Flow:
//   1. Load + validate a v2 (server-assigned batch) manifest.json against
//      the real server-side schema via /api/v1/uploads/validate-manifest/.
//   2. Match each manifest item's `filename` against the selected ZIP files.
//   3. For each matched item, drive the existing chunked-upload API
//      (/api/v1/uploads/chunked/init|<id>/chunk|<id>/complete/) — the same
//      resumable, hash-verified pipeline the token-authenticated /upload/
//      SPA uses — tagging the upload with `batch` and `manifest_item` so it
//      creates its own UploadJob, trackable on the My Uploads page.
//
// Authenticated via the user's existing login session (SessionAuthentication
// on the DRF views), not a separately-issued API token — POST/DELETE calls
// must carry the CSRF header like every other page in this app.

const PAGE_DATA  = JSON.parse(document.getElementById('automated-upload-data').textContent);
const CSRF_TOKEN = PAGE_DATA.csrf_token;

const CHUNK_SIZE = 10 * 1024 * 1024; // 10MB, matches the server default

let manifest = null;
let zipFilesByName = {};

function showResult(kind, html) {
    const box = document.getElementById('resultBox');
    box.className = `result-box result-${kind}`;
    box.innerHTML = html;
}

function escHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
}

document.getElementById('inp_zips').addEventListener('change', (e) => {
    zipFilesByName = {};
    for (const f of e.target.files) zipFilesByName[f.name] = f;
    if (manifest) renderItemsTable();
});

document.getElementById('btn_validate').addEventListener('click', async () => {
    const fileInput = document.getElementById('inp_manifest');
    if (!fileInput.files[0]) {
        showResult('warn', 'Select a manifest.json file first.');
        return;
    }

    let text;
    try {
        text = await fileInput.files[0].text();
    } catch (e) {
        showResult('err', `Could not read the manifest file: ${escHtml(e.message)}`);
        return;
    }

    let parsed;
    try {
        parsed = JSON.parse(text);
    } catch (e) {
        showResult('err', `Manifest is not valid JSON: ${escHtml(e.message)}`);
        return;
    }

    let resp, data;
    try {
        resp = await fetch('/api/v1/uploads/validate-manifest/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ manifest: parsed }),
        });
        data = await resp.json();
    } catch (e) {
        showResult('err', `Validation request failed: ${escHtml(e.message)}`);
        return;
    }

    if (!data.valid) {
        const errList = (data.errors || [])
            .map(err => `<li><code>${escHtml(err.field || '$')}</code> — ${escHtml(err.message)} (${escHtml(err.code)})</li>`)
            .join('');
        showResult('err', `<strong>Manifest is invalid${data.schema_version ? ` (detected schema: ${escHtml(data.schema_version)})` : ''}:</strong><ul>${errList}</ul>`);
        document.getElementById('items_card').style.display = 'none';
        document.getElementById('btn_start_upload').disabled = true;
        return;
    }

    if (data.schema_version !== 'v2') {
        showResult('warn',
            'This manifest is valid, but it is a v1 (single-study) manifest. The Automated Upload page ' +
            'only drives v2 (server-assigned batch) manifests here — a v1 manifest belongs inside a tar ' +
            'archive together with its images, uploaded directly.');
        document.getElementById('items_card').style.display = 'none';
        document.getElementById('btn_start_upload').disabled = true;
        return;
    }

    manifest = parsed;
    showResult('ok', `Manifest is valid — ${manifest.items.length} item(s) in batch "${escHtml(manifest.batch || '—')}".`);
    document.getElementById('items_card').style.display = 'block';
    renderItemsTable();
});

function renderItemsTable() {
    const tbody = document.getElementById('items_tbody');
    tbody.innerHTML = '';
    let anyMatched = false;

    manifest.items.forEach((item, idx) => {
        const matched = !!zipFilesByName[item.filename];
        if (matched) anyMatched = true;
        const tr = document.createElement('tr');
        tr.id = `item_row_${idx}`;
        tr.innerHTML = `
            <td class="mono">${escHtml(item.ref || '')}</td>
            <td class="mono">${escHtml(item.filename || '')}</td>
            <td>${escHtml(item.clinical_indication_code || '')}</td>
            <td>${escHtml(item.patient_group_code || '')}</td>
            <td>${matched ? '<span class="badge-status badge-matched">matched</span>' : '<span class="badge-status badge-unmatched">no file selected</span>'}</td>
            <td><progress class="item-progress" id="item_progress_${idx}" value="0" max="100"></progress></td>
            <td id="item_status_${idx}"><span class="badge-status badge-pending">pending</span></td>
        `;
        tbody.appendChild(tr);
    });

    document.getElementById('btn_start_upload').disabled = !anyMatched;
}

document.getElementById('btn_start_upload').addEventListener('click', async () => {
    document.getElementById('btn_start_upload').disabled = true;
    for (let idx = 0; idx < manifest.items.length; idx++) {
        const item = manifest.items[idx];
        const file = zipFilesByName[item.filename];
        if (!file) continue; // unmatched — skip, already flagged in the table
        await uploadOneItem(idx, item, file);
    }
    showResult('ok', 'Batch upload complete. Track ingestion progress on the My Uploads page.');
});

function setItemStatus(idx, cls, label) {
    document.getElementById(`item_status_${idx}`).innerHTML = `<span class="badge-status badge-${cls}">${escHtml(label)}</span>`;
}

function setItemProgress(idx, percent) {
    document.getElementById(`item_progress_${idx}`).value = percent;
}

async function sha256Hex(buffer) {
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function uploadOneItem(idx, item, file) {
    setItemStatus(idx, 'uploading', 'initializing…');
    try {
        const initResp = await fetch('/api/v1/uploads/chunked/init/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({
                filename: file.name,
                total_size: file.size,
                chunk_size: CHUNK_SIZE,
                batch: manifest.batch || '',
                manifest_item: item,
            }),
        });
        if (!initResp.ok) {
            const err = await initResp.json().catch(() => ({}));
            setItemStatus(idx, 'error', err.error || `init failed (${initResp.status})`);
            return;
        }
        const session = await initResp.json();
        const totalChunks = session.total_chunks;

        for (let chunkNumber = 0; chunkNumber < totalChunks; chunkNumber++) {
            const start = chunkNumber * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunkBlob = file.slice(start, end);
            const chunkBuffer = await chunkBlob.arrayBuffer();
            const chunkHash = await sha256Hex(chunkBuffer);

            const chunkResp = await fetch(
                `/api/v1/uploads/chunked/${session.session_id}/chunk/?chunk_number=${chunkNumber}&chunk_hash=${chunkHash}`,
                {
                    method: 'POST',
                    headers: { 'X-CSRFToken': CSRF_TOKEN },
                    body: chunkBlob,
                }
            );
            if (!chunkResp.ok) {
                const err = await chunkResp.json().catch(() => ({}));
                setItemStatus(idx, 'error', err.error || `chunk ${chunkNumber} failed`);
                return;
            }
            setItemProgress(idx, Math.round(((chunkNumber + 1) / totalChunks) * 100));
            setItemStatus(idx, 'uploading', `uploading (${chunkNumber + 1}/${totalChunks})`);
        }

        setItemStatus(idx, 'uploading', 'verifying…');
        // Whole-file hash for the completion step — read once more so the
        // server can verify the reassembled archive matches byte-for-byte.
        const wholeFileHash = await sha256Hex(await file.arrayBuffer());

        const completeResp = await fetch(`/api/v1/uploads/chunked/${session.session_id}/complete/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ file_hash: wholeFileHash }),
        });
        if (!completeResp.ok) {
            const err = await completeResp.json().catch(() => ({}));
            setItemStatus(idx, 'error', err.error || `completion failed (${completeResp.status})`);
            return;
        }
        setItemProgress(idx, 100);
        setItemStatus(idx, 'done', 'queued for ingestion');
    } catch (e) {
        setItemStatus(idx, 'error', e.message || 'unexpected error');
    }
}
