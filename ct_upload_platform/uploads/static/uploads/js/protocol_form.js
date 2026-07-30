const PAGE_DATA = JSON.parse(document.getElementById('protocol-form-data').textContent);
const CLINICAL_ROWS_FORM = PAGE_DATA.clinical_rows;
var MFR_OPTIONS_FORM = PAGE_DATA.manufacturer_options;
var SCANNERS_FOR_FORM = PAGE_DATA.scanners_for_form;
var MA_INPUT_SPECS_FORM = PAGE_DATA.ma_input_specs;

// ── Clinical indication cascade ──
        function getClinicalCascadeSelects() {
            return {
                region: document.getElementById('id_anatomical_region'),
                indication: document.getElementById('id_clinical_indication'),
                contrast: document.getElementById('id_contrast'),
            };
        }

        function rebuildSelect(sel, values, currentVal) {
            if (!sel) return;
            const blank = sel.options[0] && sel.options[0].value === '' ? sel.options[0].text : '--- Select ---';
            sel.innerHTML = '<option value="">' + blank + '</option>';
            values.forEach(function(v) {
                var opt = document.createElement('option');
                opt.value = v; opt.textContent = v;
                if (v === currentVal) opt.selected = true;
                sel.appendChild(opt);
            });
        }

        function onRegionChange() {
            var s = getClinicalCascadeSelects();
            var region = s.region ? s.region.value : '';
            var prevInd = s.indication ? s.indication.value : '';
            var rows = region
                ? CLINICAL_ROWS_FORM.filter(function(r) { return r.anatomical_region === region; })
                : CLINICAL_ROWS_FORM;
            var indVals = [...new Set(rows.map(function(r) { return r.clinical_indication; }))].sort();
            rebuildSelect(s.indication, indVals, prevInd);
            onIndicationChange();
        }

        function onIndicationChange() {
            var s = getClinicalCascadeSelects();
            var region = s.region ? s.region.value : '';
            var indication = s.indication ? s.indication.value : '';
            var prevContrast = s.contrast ? s.contrast.value : '';
            var rows = CLINICAL_ROWS_FORM.filter(function(r) {
                return (!region || r.anatomical_region === region) &&
                       (!indication || r.clinical_indication === indication);
            });
            if (!rows.length) rows = CLINICAL_ROWS_FORM;
            var contrastVals = [...new Set(
                rows.flatMap(function(r) { return (r.iv_contrast || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean); })
            )].sort();
            rebuildSelect(s.contrast, contrastVals, prevContrast);
        }

        function initClinicalCascade() {
            var s = getClinicalCascadeSelects();
            if (s.region) s.region.addEventListener('change', onRegionChange);
            if (s.indication) s.indication.addEventListener('change', onIndicationChange);
            // Run once on page load so edit mode pre-filters options
            onRegionChange();
        }

        // ── Card collapse/expand ──
        function toggleCard(key) {
            var body = document.getElementById('body-' + key);
            var hdr  = document.getElementById('hdr-'  + key);
            var caret = document.getElementById('caret-' + key);
            if (body.classList.contains('collapsed')) {
                body.classList.remove('collapsed');
                hdr.classList.remove('collapsed');
            } else {
                body.classList.add('collapsed');
                hdr.classList.add('collapsed');
            }
        }

        // ── "Other" select handler ──
        // Attach to every <select> that has an "Other" option.
        function initOtherHandlers() {
            var selects = document.querySelectorAll('select');
            selects.forEach(function(sel) {
                var name = sel.name;
                if (!name) return;

                // Normalise: strip the trailing [] that ModelMultipleChoiceField adds
                var baseName = name.replace(/\[\]$/, '');

                var otherPanel = document.getElementById('other-' + baseName) ||
                                 document.getElementById('inline-other-' + baseName);
                if (!otherPanel) return;

                function check() {
                    if (sel.value === 'Other' || sel.value === 'other') {
                        otherPanel.classList.add('visible');
                    } else {
                        otherPanel.classList.remove('visible');
                    }
                }

                sel.addEventListener('change', check);
                check(); // run on page load (edit mode)
            });
        }

        // ── Before submit: copy "Other" text values back into hidden inputs ──
        function hookFormSubmit() {
            var forms = document.querySelectorAll('form[method="post"]');
            forms.forEach(function(frm) {
                frm.addEventListener('submit', function() {
                    var selects = frm.querySelectorAll('select');
                    selects.forEach(function(sel) {
                        if (sel.value === 'Other' || sel.value === 'other') {
                            var baseName = sel.name.replace(/\[\]$/, '');
                            var textInput = document.getElementById(baseName + '_other_text') ||
                                            document.getElementById('inline_' + baseName + '_other_text');
                            if (textInput && textInput.value.trim()) {
                                sel.value = textInput.value.trim();
                            }
                        }
                    });
                });
            });
        }

        // ── Manufacturer → Model cascade ──
        // Works for both the main form scanner select and the inline scanner form.
        function initManufacturerCascade() {
            // Try to find a manufacturer select in both the main form and inline panel
            var mfgSelects = document.querySelectorAll('select[name*="manufacturer"]');
            mfgSelects.forEach(function(mfgSel) {
                mfgSel.addEventListener('change', function() {
                    var mfgId = mfgSel.value;
                    if (!mfgId) return;

                    // Find the closest scanner_model select
                    var container = mfgSel.closest('.form-grid') || mfgSel.closest('form');
                    if (!container) return;
                    var modelSel = container.querySelector('select[name*="scanner_model"]') ||
                                   container.querySelector('select[name*="model"]');
                    if (!modelSel) return;

                    fetch('/api/v1/scanners/models/?manufacturer_id=' + encodeURIComponent(mfgId))
                        .then(function(r) { return r.json(); })
                        .then(function(data) {
                            // data expected: [{id, name}, ...]
                            var current = modelSel.value;
                            modelSel.innerHTML = '<option value="">---------</option>';
                            data.forEach(function(item) {
                                var opt = document.createElement('option');
                                opt.value = item.id;
                                opt.textContent = item.name;
                                if (String(item.id) === String(current)) {
                                    opt.selected = true;
                                }
                                modelSel.appendChild(opt);
                            });
                        })
                        .catch(function(err) {
                            console.warn('Model cascade failed:', err);
                        });
                });
            });
        }

        // ── Manufacturer-specific options for auto_kvp_selection / auto_ma_modulation ──
        var OTHER_VAL_FORM = 'Other: Please Specify';

        function getManufacturerForScanner(scannerId) {
            var entry = SCANNERS_FOR_FORM.find(function(s) { return s.id === scannerId; });
            return entry ? entry.manufacturer : null;
        }

        function rebuildMfrSelect(sel, options, storedVal) {
            if (!sel) return;
            var prev = storedVal !== undefined ? storedVal : sel.value;
            sel.innerHTML = '<option value="">--- Select ---</option>';
            (options || []).forEach(function(opt) {
                var el = document.createElement('option');
                el.value = opt; el.textContent = opt;
                if (opt === prev) el.selected = true;
                sel.appendChild(el);
            });
            // Always append Other
            var otherEl = document.createElement('option');
            otherEl.value = OTHER_VAL_FORM; otherEl.textContent = OTHER_VAL_FORM;
            if (prev === OTHER_VAL_FORM) otherEl.selected = true;
            sel.appendChild(otherEl);
        }

        function updateMfrFields(scannerId, storedKvp, storedMa) {
            var mfr = getManufacturerForScanner(scannerId);
            var mfrOpts = mfr ? (MFR_OPTIONS_FORM[mfr] || {}) : {};
            var kvpSel = document.getElementById('id_auto_kvp_selection');
            var maSel  = document.getElementById('id_auto_ma_modulation');
            rebuildMfrSelect(kvpSel, mfrOpts['auto_kvp_selection'], storedKvp);
            rebuildMfrSelect(maSel,  mfrOpts['auto_ma_modulation'],  storedMa);
        }

        function initMfrFields() {
            var scannerSel = document.getElementById('id_scanner');
            if (!scannerSel) return;
            // Pre-read the values that the server rendered into the select options
            var kvpSel = document.getElementById('id_auto_kvp_selection');
            var maSel  = document.getElementById('id_auto_ma_modulation');
            var storedKvp = kvpSel ? kvpSel.value : '';
            var storedMa  = maSel  ? maSel.value  : '';
            // Populate options for the current scanner on page load
            updateMfrFields(scannerSel.value, storedKvp, storedMa);
            // Repopulate (clearing stored values) when the scanner changes
            scannerSel.addEventListener('change', function() {
                updateMfrFields(scannerSel.value, '', '');
                // Reset mAs inputs when scanner changes
                if (typeof renderMasFormInputs === 'function') {
                    renderMasFormInputs('', {});
                }
            });
            // When mA modulation changes, trigger mAs input re-render via existing initMasInputs handler
        }

        // ── Dynamic mAs inputs driven by Automatic mA Modulation ──
        var MA_INPUT_LABEL_ALIASES_FORM = {
            'Min mA': ['Min mA', 'min mA'],
            'Max mA': ['Max mA', 'max mA'],
        };

        function getStoredMasValue(storedValues, label) {
            if (!storedValues) return '';
            var aliases = MA_INPUT_LABEL_ALIASES_FORM[label] || [label];
            for (var i = 0; i < aliases.length; i++) {
                var alias = aliases[i];
                if (storedValues[alias] != null) {
                    return storedValues[alias];
                }
            }
            return '';
        }

        function getMasLabels(maValue) {
            var OTHER_SENTINEL = (typeof OTHER_VAL_FORM !== 'undefined') ? OTHER_VAL_FORM : 'Other: Please Specify';
            var maSel = document.getElementById('id_auto_ma_modulation');
            var dropdownIsOther = maSel && maSel.value === OTHER_SENTINEL;
            if (!maValue && !dropdownIsOther) return [];
            if (dropdownIsOther || !Object.prototype.hasOwnProperty.call(MA_INPUT_SPECS_FORM, maValue)) {
                return MA_INPUT_SPECS_FORM['Other: Please Specify'] || ['mA'];
            }
            return MA_INPUT_SPECS_FORM[maValue];
        }

        function renderMasFormInputs(maValue, storedValues) {
            var labels = getMasLabels(maValue);
            var slot = document.getElementById('mas_inputs_form_slot');
            var container = document.getElementById('mas_inputs_fields');
            if (!slot || !container) return;
            if (!labels.length) { slot.style.display = 'none'; container.innerHTML = ''; return; }
            slot.style.display = 'block';
            container.innerHTML = '<div style="display:flex;gap:10px;align-items:flex-end;">' +
                labels.map(function(label) {
                    var inputId = 'mas_' + label.replace(/[^a-zA-Z0-9]/g, '_');
                    var val = getStoredMasValue(storedValues, label);
                    return '<div style="flex:1;min-width:70px;">' +
                        '<label for="' + inputId + '" style="display:block;font-weight:600;font-size:13px;margin-bottom:5px;">' + label + '</label>' +
                        '<input type="number" id="' + inputId + '" class="form-control" min="0" step="any" ' +
                        'value="' + val + '" placeholder="' + label + '" />' +
                        '</div>';
                }).join('') +
                '</div>';
        }

        function collectMasInputs() {
            var maSelect = document.getElementById('id_auto_ma_modulation');
            var maValue = maSelect ? maSelect.value : '';
            var labels = getMasLabels(maValue);
            var result = {};
            labels.forEach(function(label) {
                var inputId = 'mas_' + label.replace(/[^a-zA-Z0-9]/g, '_');
                var el = document.getElementById(inputId);
                if (el) result[label] = el.value;
            });
            return result;
        }

        function initMasInputs() {
            var maSelect = document.getElementById('id_auto_ma_modulation');
            if (!maSelect) return;

            // Read stored values from hidden field
            var hiddenField = document.getElementById('id_mas_inputs');
            var stored = {};
            if (hiddenField && hiddenField.value) {
                try { stored = JSON.parse(hiddenField.value); } catch(e) {}
            }

            renderMasFormInputs(maSelect.value, stored);

            maSelect.addEventListener('change', function() {
                renderMasFormInputs(maSelect.value, {});
            });

            // Before submit: write collected values to the hidden field
            var frm = maSelect.closest('form');
            if (frm) {
                frm.addEventListener('submit', function() {
                    var hiddenF = document.getElementById('id_mas_inputs');
                    if (hiddenF) hiddenF.value = JSON.stringify(collectMasInputs());
                }, true);
            }
        }

        initMasInputs();

        // ── Init ──
        if (typeof initMfrFields === 'function') initMfrFields();
        initOtherHandlers();
        hookFormSubmit();
        initManufacturerCascade();
        if (typeof initClinicalCascade === 'function') initClinicalCascade();

document.getElementById('hdr-scanner').addEventListener('click', function () { toggleCard('scanner'); });
document.getElementById('hdr-tech').addEventListener('click', function () { toggleCard('tech'); });
document.getElementById('hdr-exposure').addEventListener('click', function () { toggleCard('exposure'); });
document.getElementById('hdr-recon').addEventListener('click', function () { toggleCard('recon'); });
