const PAGE_DATA = JSON.parse(document.getElementById('exam-entry-data').textContent);
const SCANNERS      = PAGE_DATA.scanners;
const CLINICAL_ROWS = PAGE_DATA.clinical_rows;
const PROTOCOLS     = PAGE_DATA.protocols;
const SITE_CODE     = PAGE_DATA.site_code;
const CSRF_TOKEN    = PAGE_DATA.csrf_token;
let examCount       = PAGE_DATA.exam_count;

// INDICATION_CODES mirrors repository_study_id.py
const INDICATION_CODES = {
    "Head / Trauma": "HEADTRAUMA",
    "Mastoid bone/Inner Ear / Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants": "MASTOID",
    "Chest / Complicated infections": "CHESTCOMP",
    "Chest / Fungal infections": "CHESTFUNG",
    "Chest/HRCT (Inspiration/Expiration) / Interstitial lung diseases, small airways disease, cystic fibrosis, asthma, primary ciliary dyskinesia, chronic lung disease of prematurity": "HRCTILD",
    "Abdomen / Acute abdomen": "ACUTEABD",
    "Neck-Chest-Abdomen / Lymphoma": "LYMPHOMA",
    "Chest-Abdomen / Tumor staging & follow-up (Wilms tumor, neuroblastoma, other)": "CABDTUMOR",
};
const CONTRAST_CODES = {
    "Non-contrast": "NC",
    "Contrast-enhanced": "CE",
    "Non-contrast, Contrast-enhanced": "MIX",
};
const EXAM_GROUPS = {
    PEDIATRIC_HEAD: [
        "Group 1 – Neonate",
        "Group 2 – Infant",
        "Group 3 – Early Childhood",
        "Group 4 – Childhood",
    ],
    PEDIATRIC_BODY: [
        "Group 1 – Neonate",
        "Group 2 – Infant, Toddler and Early Childhood",
        "Group 3 – Childhood",
        "Group 4 – Early Adolescence",
        "Group 5 – Adolescence",
    ],
    YOUNG_ADULT: [
        "Group 6 – Young Adulthood",
    ],
};
const GROUP_CODES = {
    "Group 1": "G1", "Group 2": "G2", "Group 3": "G3",
    "Group 4": "G4", "Group 5": "G5", "Group 6": "G6",
};

function getGroupCode(protocolType, examGroup) {
    const prefix = protocolType === "PEDIATRIC_HEAD" ? "PH" :
                   protocolType === "PEDIATRIC_BODY" ? "PB" : "YA";
    for (const [key, code] of Object.entries(GROUP_CODES)) {
        if (examGroup.startsWith(key)) return `${prefix}-${code}`;
    }
    return "UNK";
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
function init() {
    const comboSel = document.getElementById('sel_indication_combo');
    CLINICAL_ROWS.forEach(r => {
        const o = document.createElement('option');
        o.value = JSON.stringify({ region: r.anatomical_region, indication: r.clinical_indication, contrast: r.iv_contrast });
        o.textContent = `${r.anatomical_region} / ${r.clinical_indication}`;
        comboSel.appendChild(o);
    });

    const scannerSel = document.getElementById('sel_scanner');
    SCANNERS.forEach(s => {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = s.display + (s.year ? ` (${s.year})` : '');
        scannerSel.appendChild(o);
    });
    if (SCANNERS.length === 1) {
        scannerSel.value = SCANNERS[0].id;
    }
    scannerSel.addEventListener('change', renderProtocolOptions);
    renderProtocolOptions();

    renderPhasesTable();
    updatePidPreview();

    comboSel.addEventListener('change', onIndicationComboChange);
    document.getElementById('sel_contrast').addEventListener('change', updatePidPreview);
    document.getElementById('sel_protocol_type').addEventListener('change', onProtocolTypeChange);
    document.getElementById('sel_exam_group').addEventListener('change', updatePidPreview);
    document.getElementById('inp_study_set').addEventListener('change', function () { updateStudySetHint(this); });
    document.getElementById('btn_save_exam').addEventListener('click', saveExamination);
    document.getElementById('btn_clear_exam').addEventListener('click', clearForm);
}

// ---------------------------------------------------------------------------
// Protocol used (optional)
// ---------------------------------------------------------------------------
function renderProtocolOptions() {
    const protocolSel = document.getElementById('sel_protocol');
    const scannerId = document.getElementById('sel_scanner').value;
    const previousValue = protocolSel.value;

    protocolSel.innerHTML = '<option value="">None / not specified…</option>';
    PROTOCOLS
        .filter(p => !scannerId || p.scanner_id === scannerId)
        .forEach((p, i) => {
            const o = document.createElement('option');
            o.value = p.id;
            o.textContent = `${i + 1}. ${p.display}`;
            protocolSel.appendChild(o);
        });

    if (previousValue && [...protocolSel.options].some(o => o.value === previousValue)) {
        protocolSel.value = previousValue;
    }
}

// ---------------------------------------------------------------------------
// Clinical indication combo
// ---------------------------------------------------------------------------
function onIndicationComboChange() {
    const val = document.getElementById('sel_indication_combo').value;
    const contrastContainer = document.getElementById('contrast_container');
    const contrastSelect = document.getElementById('sel_contrast');

    if (!val) {
        contrastContainer.style.display = 'none';
        updatePidPreview();
        return;
    }

    const parsed = JSON.parse(val);
    const contrastOptions = parsed.contrast.split(',').map(s => s.trim());

    contrastSelect.innerHTML = ''; // Clear previous options

    if (contrastOptions.length > 1) {
        contrastOptions.forEach(optionText => {
            const option = document.createElement('option');
            option.value = optionText;
            option.textContent = optionText;
            contrastSelect.appendChild(option);
        });
    } else {
        const option = document.createElement('option');
        option.value = parsed.contrast;
        option.textContent = parsed.contrast;
        contrastSelect.appendChild(option);
    }

    contrastSelect.disabled = contrastOptions.length <= 1;

    contrastContainer.style.display = 'block';
    updatePidPreview();
}

// ---------------------------------------------------------------------------
// Protocol type → populate examination group select
// ---------------------------------------------------------------------------
function onProtocolTypeChange() {
    const ptype = document.getElementById('sel_protocol_type').value;
    const grpSel = document.getElementById('sel_exam_group');
    grpSel.innerHTML = '<option value="">Select group…</option>';
    (EXAM_GROUPS[ptype] || []).forEach(g => {
        const o = document.createElement('option');
        o.value = g; o.textContent = g;
        grpSel.appendChild(o);
    });
    if (ptype === 'YOUNG_ADULT') {
        grpSel.value = 'Group 6 – Young Adulthood';
    }
    updatePidPreview();
}

// ---------------------------------------------------------------------------
// Study-set file hint — shows the name it will be saved under
// ---------------------------------------------------------------------------
function getFileExtension(filename) {
    const lower = filename.toLowerCase();
    for (const ext of ['.tar.gz', '.tar.bz2']) {
        if (lower.endsWith(ext)) return ext;
    }
    const dot = filename.lastIndexOf('.');
    return dot >= 0 ? filename.slice(dot) : '';
}

function updateStudySetHint(input) {
    const hint = document.getElementById('study_set_hint');
    if (!input || !input.files || !input.files[0]) {
        hint.textContent = '';
        return;
    }
    const file = input.files[0];
    const size = (file.size / 1048576).toFixed(1);
    const rsid = document.getElementById('rsid_display').textContent.replace(/-$/, '');
    const ext  = getFileExtension(file.name);
    if (rsid && rsid !== '—') {
        hint.textContent = `Will be saved as: ${rsid}${ext} (${size} MB)`;
    } else {
        hint.textContent = `${file.name} (${size} MB) — complete the form above to preview the final name`;
    }
}

// ---------------------------------------------------------------------------
// Live patient ID prefix preview
// ---------------------------------------------------------------------------
function updatePidPreview() {
    const indRaw = document.getElementById('sel_indication_combo').value;
    const ptype  = document.getElementById('sel_protocol_type').value;
    const grp    = document.getElementById('sel_exam_group').value;
    const contrastContainer = document.getElementById('contrast_container');

    const rsidDisplay = document.getElementById('rsid_display');
    const rsidPending = document.getElementById('rsid_pending');
    const rsidSeq     = document.getElementById('rsid_seq');

    if (!indRaw || !ptype || !grp || contrastContainer.style.display === 'none') {
        rsidDisplay.textContent = '—';
        rsidPending.style.display = '';
        rsidPending.textContent = 'Complete the form below to preview the ID prefix';
        rsidSeq.style.display = 'none';
        updateStudySetHint(document.getElementById('inp_study_set'));
        return;
    }

    const parsed      = JSON.parse(indRaw);
    const indKey      = `${parsed.region} / ${parsed.indication}`;
    const indCode     = INDICATION_CODES[indKey] || 'OTHER';
    const contrastVal = document.getElementById('sel_contrast').value;
    const contCode    = CONTRAST_CODES[contrastVal] || 'UNK';
    const groupCode   = getGroupCode(ptype, grp);
    const prefix      = `RHY-${SITE_CODE}-${indCode}-${contCode}-${groupCode}`;

    rsidDisplay.textContent = `${prefix}-`;
    rsidPending.style.display = 'none';
    rsidSeq.textContent = 'Preview — final number assigned on save';
    rsidSeq.style.display = '';
    updateStudySetHint(document.getElementById('inp_study_set'));
}

// ---------------------------------------------------------------------------
// Phases table
// ---------------------------------------------------------------------------
function renderPhasesTable() {
    const n = 1;
    const wrap = document.getElementById('phases_table_wrap');
    let rows = '';
    for (let i = 1; i <= n; i++) {
        rows += `<tr>
            <td class="phases-label">Phase ${i}</td>
            <td><input type="number" id="ctdi_${i}" min="0" step="0.01" placeholder="mGy" /></td>
            <td><input type="number" id="dlp_${i}" min="0" step="0.1" placeholder="mGy·cm" /></td>
        </tr>`;
    }
    wrap.innerHTML = `<table class="phases-table">
        <thead><tr><th>Phase</th><th>CTDI<sub>vol</sub> (<span style="text-transform:none">mGy</span>)</th><th style="text-transform:none">DLP (mGy·cm)</th></tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------
async function saveExamination() {
    document.getElementById('successBanner').style.display = 'none';
    document.getElementById('errorBanner').style.display = 'none';

    const errors = [];

    const indicationRaw = document.getElementById('sel_indication_combo').value;
    let anatomicalRegion = '', clinicalIndication = '', contrast = '';
    if (!indicationRaw) {
        errors.push('Anatomical region / clinical indication is required.');
    } else {
        const parsed = JSON.parse(indicationRaw);
        anatomicalRegion = parsed.region;
        clinicalIndication = parsed.indication;
        contrast = document.getElementById('sel_contrast').value || '';
    }

    const protocolType = document.getElementById('sel_protocol_type').value;
    if (!protocolType) errors.push('Protocol type is required.');
    const examGroup = document.getElementById('sel_exam_group').value;
    if (!examGroup) errors.push('Examination group is required.');

    const scannerId = document.getElementById('sel_scanner').value || null;
    if (!scannerId) errors.push('CT scanner is required.');

    if (!document.getElementById('inp_age').value) errors.push("Patient's age is required.");

    const n = 1;

    const ctdiVol = [], dlp = [];
    for (let i = 1; i <= n; i++) {
        const ctdiRaw = document.getElementById('ctdi_' + i)?.value;
        const dlpRaw  = document.getElementById('dlp_' + i)?.value;
        if (!ctdiRaw && ctdiRaw !== '0') errors.push(`CTDI vol for phase ${i} is required.`);
        if (!dlpRaw  && dlpRaw  !== '0') errors.push(`DLP for phase ${i} is required.`);
        ctdiVol.push(ctdiRaw !== '' && ctdiRaw != null ? parseFloat(ctdiRaw) : null);
        dlp.push(dlpRaw !== '' && dlpRaw != null ? parseFloat(dlpRaw) : null);
    }

    const weightVal = document.getElementById('inp_weight').value || null;
    if (!weightVal) errors.push("Patient's weight is required.");

    if (!document.getElementById('sel_quality').value) errors.push('Image quality is required.');

    if (!document.getElementById('inp_study_set').files[0]) errors.push('Compressed study set is required.');

    if (errors.length > 0) { showError(errors.join('\n')); return; }

    const fd = new FormData();
    fd.append('scanner_id',               scannerId);
    fd.append('anatomical_region',        anatomicalRegion);
    fd.append('clinical_indication',      clinicalIndication);
    fd.append('contrast',                 contrast);
    fd.append('protocol_type',            protocolType);
    fd.append('examination_group',        examGroup);
    if (weightVal) fd.append('patient_weight', weightVal);
    const ageVal = document.getElementById('inp_age').value;
    if (ageVal)    fd.append('patient_age', ageVal);
    fd.append('number_of_phases',         String(n));
    fd.append('ctdi_vol_per_phase',       JSON.stringify(ctdiVol));
    fd.append('dlp_per_phase',            JSON.stringify(dlp));
    fd.append('image_quality',            document.getElementById('sel_quality').value);
    const protocolId = document.getElementById('sel_protocol').value;
    if (protocolId) fd.append('protocol_id', protocolId);

    const studyFile = document.getElementById('inp_study_set').files[0];
    if (studyFile) {
        fd.append('study_set_file', studyFile);
    }

    try {
        const resp = await fetch('/examinations/api/save/', {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN },
            body: fd,
        });
        let data;
        try {
            data = await resp.json();
        } catch (_) {
            showError(resp.status === 413
                ? 'File is too large to upload.'
                : `Server error (${resp.status}). Please try again or contact support.`);
            return;
        }
        if (data.status === 'created') {
            if (data.repository_study_id) {
                document.getElementById('rsid_display').textContent = data.repository_study_id;
                document.getElementById('rsid_seq').style.display = 'none';
                document.getElementById('rsid_pending').textContent = 'Assigned — record saved';
                document.getElementById('rsid_pending').style.display = '';
            }
            const box = document.getElementById('successBanner');
            box.innerHTML = `${data.message}${data.repository_study_id ? `<br><strong>Repository Study ID:</strong> ${data.repository_study_id}` : ''}`;
            box.style.display = 'block';
            clearForm();
        } else {
            showError(data.error || 'An error occurred.');
        }
    } catch (e) {
        showError('Network error: ' + e.message);
    }
}

function showError(msg) {
    const box = document.getElementById('errorBanner');
    const lines = msg.split('\n').filter(Boolean);
    if (lines.length === 1) {
        box.textContent = lines[0];
    } else {
        box.innerHTML = '<ul style="margin:0;padding-left:18px;">' +
            lines.map(l => `<li>${l}</li>`).join('') + '</ul>';
    }
    box.style.display = 'block';
}

function clearForm() {
    document.getElementById('sel_indication_combo').value = '';
    document.getElementById('contrast_container').style.display = 'none';
    document.getElementById('sel_protocol_type').value = '';
    document.getElementById('sel_exam_group').innerHTML = '<option value="">Select group…</option>';
    const scannerSel = document.getElementById('sel_scanner');
    scannerSel.value = SCANNERS.length === 1 ? SCANNERS[0].id : '';
    renderProtocolOptions();
    document.getElementById('inp_weight').value = '';
    document.getElementById('inp_age').value = '';
    document.getElementById('sel_quality').value = '';
    document.getElementById('inp_study_set').value = '';
    document.getElementById('study_set_hint').textContent = '';
    renderPhasesTable();
    updatePidPreview();
}

init();
