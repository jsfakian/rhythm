const PAGE_DATA = JSON.parse(document.getElementById('protocol-gui-data').textContent);
const CLINICAL_ROWS = PAGE_DATA.clinical_rows;
const SCANNERS = PAGE_DATA.scanners;
const PROTOCOL_TABS = PAGE_DATA.protocol_tabs;
const PROTOCOL_CHOICES = PAGE_DATA.protocol_choices;
const MANUFACTURER_OPTIONS = PAGE_DATA.manufacturer_options;
const MA_INPUT_SPECS = PAGE_DATA.ma_input_specs;
// Combination overrides: keyed by "kvp_value|ma_value", each entry is an array of
// {label, type} objects. Takes precedence over MA_INPUT_SPECS when both fields match.
const COMBO_INPUT_SPECS = {
    'kV Assist|SmartmA': [
        {label: 'min mA',       type: 'number'},
        {label: 'max mA',       type: 'number'},
        {label: 'Noise Index',  type: 'number'},
        {label: 'Clinical mode', type: 'text'},
    ],
    'CarekV|CareDose4D': [
        {label: 'Quality Reference mAs (QR mAs)', type: 'number'},
        {label: 'Dose Optimization setting',      type: 'text'},
    ],
};
const CSRF_TOKEN = PAGE_DATA.csrf_token;
// Derived lookup helpers populated from CLINICAL_ROWS for convenience
const ANATOMICAL_REGIONS = [...new Set(CLINICAL_ROWS.map(r => r.anatomical_region))];
const CLINICAL_INDICATIONS = [...new Set(CLINICAL_ROWS.map(r => r.clinical_indication))];

const OTHER_VAL = "Other: Please Specify";

let state = {
    region: "", indication: "", contrast: "", comments: "",
    scannerId: "",
    activeTab: Object.keys(PROTOCOL_TABS)[0],
    fields: {},
};

/* ── Helpers ── */
function unique(arr) { return [...new Set(arr.filter(v => v))]; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }
function setSelect(el, options, placeholder, current) {
    const blank = placeholder ? `<option value="">${esc(placeholder)}</option>` : '';
    el.innerHTML = blank +
        options.map(o => `<option value="${esc(o)}"${o===current?' selected':''}>${esc(o)}</option>`).join('');
}

/* ── Step 1 ── */
function initStep1() {
    const pairs = unique(CLINICAL_ROWS.map(r => `${r.anatomical_region} / ${r.clinical_indication}`));
    const current = state.region && state.indication ? `${state.region} / ${state.indication}` : '';
    setSelect(document.getElementById('cl_clinical'), pairs, 'Select region / indication...', current);
}

function onClinicalChange() {
    const val = document.getElementById('cl_clinical').value;
    if (val) {
        const sep = val.indexOf(' / ');
        state.region = val.substring(0, sep);
        state.indication = val.substring(sep + 3);
    } else {
        state.region = ""; state.indication = "";
    }
    state.contrast = ""; state.comments = "";
    const matches = CLINICAL_ROWS.filter(r => r.anatomical_region === state.region && r.clinical_indication === state.indication);
    // IV contrast options — auto-select when only one option available
    const contrastOpts = unique(matches.flatMap(r => r.iv_contrast.split(',').map(s => s.trim())));
    setSelect(document.getElementById('cl_contrast'), contrastOpts, 'Select contrast option...', '');
    const contrastSel = document.getElementById('cl_contrast');
    contrastSel.disabled = !!state.region;
    contrastSel.style.opacity = state.region ? '0.6' : '';
    contrastSel.style.cursor = state.region ? 'not-allowed' : '';
    if (contrastOpts.length === 1) {
        contrastSel.value = contrastOpts[0];
        state.contrast = contrastOpts[0];
    }
    // Comments from data
    const commentOpts = unique(['Indication-specific protocol', ...matches.map(r => r.comments).filter(Boolean)]);
    setSelect(document.getElementById('cl_comments'), commentOpts, '', '');
    if (commentOpts.length === 1) {
        document.getElementById('cl_comments').value = commentOpts[0];
        state.comments = commentOpts[0];
    }
    // Auto-select the pediatric tab that is visible for this indication
    if (state.region && state.indication) {
        const autoTab = HEAD_INDICATIONS.has(`${state.region} / ${state.indication}`) ? 'PEDIATRIC_HEAD' : 'PEDIATRIC_BODY';
        if (state.activeTab !== autoTab) {
            state.activeTab = autoTab;
            state.fields = {};
        }
    }
    updatePreview(); updateProtocolContext();
}

function onStep1Change() {
    state.contrast = document.getElementById('cl_contrast').value;
    state.comments = document.getElementById('cl_comments').value;
    updatePreview(); updateProtocolContext();
    // Re-sync the locked contrast field if the protocol form is already visible
    const mappedContrast = mapContrastFromIV(state.contrast);
    const sel = document.getElementById('fld_contrast');
    if (sel) { sel.value = mappedContrast; state.fields['contrast'] = mappedContrast; }
}

function updatePreview() {
    const box = document.getElementById('clinicalPreview');
    if (state.region && state.indication && state.contrast) {
        box.style.display = 'block';
        box.innerHTML = `<strong>Selected:</strong> ${esc(state.region)} — ${esc(state.indication)}<br><strong>IV contrast:</strong> ${esc(state.contrast)}${state.comments ? `<br><strong>Comments:</strong> ${esc(state.comments)}` : ''}`;
    } else {
        box.style.display = 'none';
    }
}

/* ── Step 2 ── */
function initStep2() {
    const sel = document.getElementById('scanner_select');
    if (!SCANNERS.length) {
        document.getElementById('noScannersNotice').style.display = 'block';
        sel.style.display = 'none';
    } else {
        sel.innerHTML = '<option value="">Select scanner...</option>' +
            SCANNERS.map(s => `<option value="${esc(s.id)}">${esc(s.display)}${s.year ? ' (' + esc(s.year) + ')' : ''}</option>`).join('');
    }
}

function onScannerChange() {
    state.scannerId = document.getElementById('scanner_select').value;
    // Clear manufacturer-specific fields so stale values from a previous scanner don't carry over
    delete state.fields['auto_kvp_selection'];
    delete state.fields['auto_ma_modulation'];
    const scanner = SCANNERS.find(s => s.id === state.scannerId);
    const preview = document.getElementById('scannerPreview');
    if (scanner) {
        preview.style.display = 'block';
        preview.innerHTML = `${esc(scanner.manufacturer)} | ${esc(scanner.model)}${scanner.detector_rows ? ' | ' + esc(scanner.detector_rows) : ''}${scanner.note ? ' | ' + esc(scanner.note) : ''}`;
    } else {
        preview.style.display = 'none';
    }
    updateProtocolContext();
}

/* ── Step 3 ── */
function updateProtocolContext() {
    const ready = state.region && state.indication && state.contrast && state.scannerId;
    document.getElementById('protocolBlocked').style.display = ready ? 'none' : 'block';
    document.getElementById('protocolFormWrap').style.display = ready ? 'block' : 'none';
    if (!ready) return;
    const scanner = SCANNERS.find(s => s.id === state.scannerId);
    document.getElementById('protocolContextText').innerHTML =
        `Selected: <strong>${esc(state.region)} / ${esc(state.indication)}</strong> &nbsp;&middot;&nbsp; Scanner: <strong>${esc(scanner ? scanner.display : '')}</strong>`;
    renderTabs();
    renderFields();
}

const HEAD_INDICATIONS = new Set([
    'Head / Trauma',
    'Mastoid bone/Inner Ear / Hearing loss; congenital malformations, infection, cholesteatoma, cochlear implants',
]);

function hiddenTab(region, indication, tabKey) {
    const pair = `${region} / ${indication}`;
    if (HEAD_INDICATIONS.has(pair)) return tabKey === 'PEDIATRIC_BODY';
    return tabKey === 'PEDIATRIC_HEAD';
}

function renderTabs() {
    const container = document.getElementById('protocolTabs');
    container.innerHTML = Object.entries(PROTOCOL_TABS).map(([key, tab]) => {
        if (hiddenTab(state.region, state.indication, key)) return '';
        return `<button class="tab-btn${key===state.activeTab?' active':''}" data-tab-key="${esc(key)}">${esc(tab.label)}</button>`;
    }).join('');
}

function setTab(key) {
    state.activeTab = key;
    state.fields = {};
    renderTabs();
    renderFields();
}

function getOptions(categoryKey) {
    return (PROTOCOL_CHOICES[categoryKey] || []).map(o => o.value);
}

function getManufacturerFieldOptions(fieldKey) {
    const scanner = SCANNERS.find(s => s.id === state.scannerId);
    if (!scanner) return null;
    const mfrOpts = MANUFACTURER_OPTIONS[scanner.manufacturer];
    if (!mfrOpts) return null;
    return mfrOpts[fieldKey] || null;
}

function makeSelect(fieldKey, options, label, fullWidth, noOther, required = true) {
    const dedupedOpts = options.filter(o => o !== OTHER_VAL);
    const allOpts = noOther ? dedupedOpts : [...dedupedOpts, OTHER_VAL];
    const val = state.fields[fieldKey] || '';
    const isOther = !noOther && val && !dedupedOpts.includes(val);
    const labelHtml = required ? `${esc(label)} <span class="required-marker">*</span>` : esc(label);
    return `<div class="field-row${fullWidth?' full':''}">
        <label>${labelHtml}</label>
        <select id="fld_${fieldKey}" data-field-key="${esc(fieldKey)}"${required?' required':''}>
            <option value="">Select...</option>
            ${allOpts.map(o => `<option value="${esc(o)}"${o===val||(!noOther&&o===OTHER_VAL&&isOther)?' selected':''}>${esc(o)}</option>`).join('')}
        </select>
        <div id="fld_${fieldKey}_other" style="margin-top:6px;${isOther?'':'display:none;'}">
            <input type="text" id="fld_${fieldKey}_other_txt" value="${esc(isOther?val:'')}" placeholder="Specify value..." data-other-key="${esc(fieldKey)}" />
        </div>
    </div>`;
}

function makeInput(fieldKey, label, fullWidth, isTextarea, required = true) {
    const val = esc(state.fields[fieldKey] || '');
    const cls = `field-row${fullWidth?' full':''}`;
    const labelHtml = required ? `${esc(label)} <span class="required-marker">*</span>` : esc(label);
    if (isTextarea) {
        return `<div class="${cls}"><label>${labelHtml}</label><textarea id="fld_${fieldKey}" data-field-key="${esc(fieldKey)}"${required?' required':''}>${val}</textarea></div>`;
    }
    return `<div class="${cls}"><label>${labelHtml}</label><input type="text" id="fld_${fieldKey}" value="${val}" data-field-key="${esc(fieldKey)}"${required?' required':''} /></div>`;
}

function mapContrastFromIV(ivContrast) {
    if (!ivContrast) return '';
    return /non/i.test(ivContrast) ? 'No Contrast' : 'Contrast-Enhanced';
}

function onCombinedEgAgChange() {
    const idx = parseInt(document.getElementById('fld_eg_ag').value);
    const tab = PROTOCOL_TABS[state.activeTab];
    if (!isNaN(idx) && idx >= 0 && tab) {
        state.fields['examination_group'] = tab.examination_groups[idx] || '';
        state.fields['age_group'] = tab.age_groups[idx] || '';
    } else {
        state.fields['examination_group'] = '';
        state.fields['age_group'] = '';
    }
    updateCompletion();
}

function formatCombinedExamAgeLabel(tab, group, ageGroup) {
    if (state.activeTab === 'YOUNG_ADULT') {
        return group.replace(/\s*\([^)]*\)\s*$/, '');
    }
    if (!ageGroup) {
        return group;
    }
    return `${group} (${ageGroup})`;
}

function renderFields() {
    const tab = PROTOCOL_TABS[state.activeTab];
    if (!tab) return;
    const container = document.getElementById('protocolFields');
    const egVal = state.fields['examination_group'] || '';
    const selectedIdx = egVal ? tab.examination_groups.indexOf(egVal) : -1;
    const egAgPairs = tab.examination_groups.map((group, i) => (
        formatCombinedExamAgeLabel(tab, group, tab.age_groups[i] || '')
    ));
    const egAgLabel = `Examination Group / ${tab.age_label || 'Age / Weight Group'}`;

    const contrastOpts = ['No Contrast', 'Contrast-Enhanced'];
    const contrastVal = mapContrastFromIV(state.contrast);
    state.fields['contrast'] = contrastVal;
    const contrastHtml = `<div class="field-row">
        <label>Contrast <span class="required-marker">*</span></label>
        <select id="fld_contrast" disabled required style="opacity:.6;cursor:not-allowed;">
            <option value="">—</option>
            ${contrastOpts.map(o => `<option value="${esc(o)}"${o===contrastVal?' selected':''}>${esc(o)}</option>`).join('')}
        </select>
    </div>`;

    const scanTypeOpts = getOptions('scan_type').filter(o => /sequential|axial|helical|spiral/i.test(o));
    const pitchVal = esc(state.fields['pitch'] || '');
    const pitchHtml = `<div class="field-row">
        <label>Pitch <span class="required-marker">*</span></label>
        <input type="number" id="fld_pitch" min="0" max="3" step="0.01" value="${pitchVal}" required
               placeholder="e.g. 0.98" data-field-key="pitch" style="width:100%;border:1px solid var(--border);border-radius:10px;padding:9px 11px;font-size:14px;font-family:inherit;color:var(--text);" />
    </div>`;

    let html = `<div class="fields-grid" style="margin-bottom:16px;">
        <div class="field-row half">
            <label>${esc(egAgLabel)} <span class="required-marker">*</span></label>
            <select id="fld_eg_ag" required>
                <option value="">Select...</option>
                ${egAgPairs.map((label, i) => `<option value="${i}"${i===selectedIdx?' selected':''}>${esc(label)}</option>`).join('')}
            </select>
        </div>
    </div>
    <div class="fields-grid">
        ${makeSelect('scan_type', scanTypeOpts, 'Scan Type', false, true)}
        ${contrastHtml}
        ${makeSelect('auto_kvp_selection', getManufacturerFieldOptions('auto_kvp_selection') || getOptions('auto_kvp_selection'), 'Automatic kVp Selection', false)}
        ${makeSelect('kvp', getOptions('kvp'), 'kVp / kVp (ref)', false)}
        ${makeSelect('auto_ma_modulation', getManufacturerFieldOptions('auto_ma_modulation') || getOptions('auto_ma_modulation'), 'Automatic mA Modulation', false)}
        ${pitchHtml}
        <div id="mas_inputs_slot" style="grid-column:1/-1;">${renderMasInputs()}</div>
        ${makeSelect('rotation_time', getOptions('rotation_time'), 'Rotation Time (s)', false)}
        ${makeSelect('slice_thickness', getOptions('slice_thickness'), 'Slice Thickness 1st Recon (mm)', false)}
        ${makeInput('kernel_class', 'Reconstruction filter kernel', false, false)}
        ${makeInput('reconstruction_algorithm', 'Reconstruction Algorithm', false, false)}
        ${makeInput('strength', 'Strength (optional)', false, false, false)}
        ${makeInput('notes', 'Additional Free-Text Notes', true, true, false)}
    </div>`;

    container.innerHTML = html;
    updateCompletion();
}

function getMasInputSpecs(checkDom = false) {
    const maValue = state.fields['auto_ma_modulation'] || '';
    const kvpValue = state.fields['auto_kvp_selection'] || '';
    const sel = checkDom ? document.getElementById('fld_auto_ma_modulation') : null;
    const dropdownIsOther = sel && sel.value === OTHER_VAL;

    // Check combination override first
    const comboKey = kvpValue + '|' + maValue;
    if (Object.prototype.hasOwnProperty.call(COMBO_INPUT_SPECS, comboKey)) {
        return COMBO_INPUT_SPECS[comboKey];
    } else if (!maValue && !dropdownIsOther) {
        return [];
    } else if (dropdownIsOther || !Object.prototype.hasOwnProperty.call(MA_INPUT_SPECS, maValue)) {
        return (MA_INPUT_SPECS['Other: Please Specify'] || ['mA']).map(l => ({label: l, type: 'number'}));
    }
    return MA_INPUT_SPECS[maValue].map(l => ({label: l, type: 'number'}));
}

function renderMasInputs(checkDom = false) {
    const specs = getMasInputSpecs(checkDom);
    if (!specs.length) return '';
    const stored = state.fields['mas_inputs'] || {};
    return `<div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;">` +
        specs.map(({label, type}) => {
            const key = 'mas_' + label.replace(/[^a-zA-Z0-9]/g, '_');
            const val = esc(stored[label] || '');
            const attrs = type === 'number' ? 'type="number" min="0" step="any"' : 'type="text"';
            return `<div class="field-row" style="flex:1;min-width:70px;margin-bottom:0;">
                <label>${esc(label)} <span class="required-marker">*</span></label>
                <input ${attrs} id="${key}" value="${val}" required
                       placeholder="${esc(label)}" data-mas-label="${esc(label)}"
                       style="width:100%;border:1px solid var(--border);border-radius:10px;padding:9px 11px;font-size:14px;font-family:inherit;color:var(--text);" />
            </div>`;
        }).join('') +
        `</div>`;
}

function onMasInput(label) {
    const key = 'mas_' + label.replace(/[^a-zA-Z0-9]/g, '_');
    const el = document.getElementById(key);
    if (!el) return;
    if (!state.fields['mas_inputs']) state.fields['mas_inputs'] = {};
    state.fields['mas_inputs'][label] = el.value;
    updateCompletion();
}

function onFieldChange(key) {
    const el = document.getElementById('fld_' + key);
    if (!el) return;
    if (el.tagName === 'SELECT' && el.value === OTHER_VAL) {
        const otherDiv = document.getElementById('fld_' + key + '_other');
        if (otherDiv) otherDiv.style.display = 'block';
        state.fields[key] = document.getElementById('fld_' + key + '_other_txt')?.value.trim() || '';
    } else {
        const otherDiv = document.getElementById('fld_' + key + '_other');
        if (otherDiv) otherDiv.style.display = 'none';
        state.fields[key] = el.value;
    }
    // When mA modulation or kVp selection changes, reset stored mAs values and re-render
    if (key === 'auto_ma_modulation' || key === 'auto_kvp_selection') {
        state.fields['mas_inputs'] = {};
        const masSlot = document.getElementById('mas_inputs_slot');
        if (masSlot) masSlot.innerHTML = renderMasInputs(true);
    }
    updateCompletion();
}

function onOtherInput(key) {
    state.fields[key] = document.getElementById('fld_' + key + '_other_txt')?.value.trim() || '';
    updateCompletion();
}

function updateCompletion() {
    const keys = ['examination_group', 'age_group', 'scan_type', 'contrast',
        'auto_kvp_selection', 'kvp', 'auto_ma_modulation',
        'pitch', 'rotation_time', 'slice_thickness', 'kernel_class', 'reconstruction_algorithm'];
    const filled = keys.filter(k => state.fields[k] && String(state.fields[k]).trim()).length;
    const pct = Math.round((filled / keys.length) * 100);
    document.getElementById('progressBar').style.width = pct + '%';
    document.getElementById('completionPct').textContent = pct + '%';
}

function clearProtocolForm() {
    state.fields = {};
    renderFields();
    document.getElementById('existsBanner').classList.remove('visible');
    document.getElementById('successBanner').style.display = 'none';
}

function resetStep1() {
    state = { region: "", indication: "", contrast: "", comments: "", scannerId: "", activeTab: Object.keys(PROTOCOL_TABS)[0], fields: {} };
    initStep1();
    setSelect(document.getElementById('cl_contrast'), [], 'Select contrast option...', '');
    setSelect(document.getElementById('cl_comments'), [], '', '');
    updatePreview(); updateProtocolContext();
}

/* ── Save ── */
async function saveProtocol(forceUpdate) {
    document.getElementById('existsBanner').classList.remove('visible');
    document.getElementById('successBanner').style.display = 'none';

    if (!state.region || !state.indication || !state.contrast) {
        alert('Please complete Step 1: select anatomical region, clinical indication, and IV contrast.'); return;
    }
    if (!state.scannerId) { alert('Please select a scanner in Step 2.'); return; }
    if (!state.fields['examination_group'] || !state.fields['age_group']) {
        alert('Please select Examination Group and Age / Weight Group.'); return;
    }
    const REQUIRED_PROTOCOL_FIELDS = [
        { key: 'scan_type', label: 'Scan Type' },
        { key: 'contrast', label: 'Contrast' },
        { key: 'auto_kvp_selection', label: 'Automatic kVp Selection' },
        { key: 'kvp', label: 'kVp / kVp (ref)' },
        { key: 'auto_ma_modulation', label: 'Automatic mA Modulation' },
        { key: 'pitch', label: 'Pitch' },
        { key: 'rotation_time', label: 'Rotation Time (s)' },
        { key: 'slice_thickness', label: 'Slice Thickness 1st Recon (mm)' },
        { key: 'kernel_class', label: 'Reconstruction filter kernel' },
        { key: 'reconstruction_algorithm', label: 'Reconstruction Algorithm' },
    ];
    for (const { key, label } of REQUIRED_PROTOCOL_FIELDS) {
        if (!String(state.fields[key] || '').trim()) {
            alert(`Please complete the required field: ${label}.`); return;
        }
    }
    const masSpecs = getMasInputSpecs();
    const masStored = state.fields['mas_inputs'] || {};
    for (const { label } of masSpecs) {
        if (!String(masStored[label] || '').trim()) {
            alert(`Please complete the required field: ${label}.`); return;
        }
    }

    const payload = {
        scanner_id: state.scannerId,
        protocol_type: state.activeTab,
        anatomical_region: state.region,
        clinical_indication: state.indication,
        contrast: state.contrast,
        clinical_comments: state.comments,
        examination_group: state.fields['examination_group'],
        age_group: state.fields['age_group'],
        force_update: forceUpdate,
        protocol_fields: { ...state.fields },
    };

    try {
        const resp = await fetch('/protocols/api/save/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(payload),
        });
        if (resp.status === 401) {
            alert('Your session has expired. Please log in again to save this protocol.');
            window.location.href = '/login/?next=' + encodeURIComponent(window.location.pathname);
            return;
        }
        let data;
        try {
            data = await resp.json();
        } catch (_) {
            alert(`Server error (${resp.status}). Please try again or contact support.`);
            return;
        }
        if (data.status === 'exists') {
            document.getElementById('existsMsg').textContent = data.message;
            document.getElementById('existsBanner').classList.add('visible');
        } else if (data.status === 'created' || data.status === 'updated') {
            if (data.status === 'created') clearProtocolForm();
            const box = document.getElementById('successBanner');
            box.textContent = data.message;
            box.style.display = 'block';
            box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            alert(data.error || 'An error occurred.');
        }
    } catch (e) {
        alert('Network error: ' + e.message);
    }
}

function dismissBanner() {
    document.getElementById('existsBanner').classList.remove('visible');
}

/* ── Event wiring (CSP-compliant: no inline handlers) ── */
document.getElementById('cl_clinical').addEventListener('change', onClinicalChange);
document.getElementById('cl_contrast').addEventListener('change', onStep1Change);
document.getElementById('cl_comments').addEventListener('change', onStep1Change);
document.getElementById('scanner_select').addEventListener('change', onScannerChange);
document.getElementById('btnSaveProtocol').addEventListener('click', () => saveProtocol(false));
document.getElementById('btnClearProtocol').addEventListener('click', clearProtocolForm);
document.getElementById('btnUpdateProtocol').addEventListener('click', () => saveProtocol(true));
document.getElementById('btnDismissBanner').addEventListener('click', dismissBanner);

// Delegated listeners for dynamically-rendered tab buttons and protocol fields
// (their innerHTML is re-rendered on state changes, but these containers persist).
document.getElementById('protocolTabs').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-tab-key]');
    if (btn) setTab(btn.dataset.tabKey);
});

document.getElementById('protocolFields').addEventListener('change', (e) => {
    if (e.target.id === 'fld_eg_ag') { onCombinedEgAgChange(); return; }
    if (e.target.matches('select[data-field-key]')) onFieldChange(e.target.dataset.fieldKey);
});

document.getElementById('protocolFields').addEventListener('input', (e) => {
    if (e.target.matches('input[data-field-key], textarea[data-field-key]')) onFieldChange(e.target.dataset.fieldKey);
    if (e.target.matches('[data-other-key]')) onOtherInput(e.target.dataset.otherKey);
    if (e.target.matches('[data-mas-label]')) onMasInput(e.target.dataset.masLabel);
});

/* ── Init ── */
initStep1();
initStep2();
