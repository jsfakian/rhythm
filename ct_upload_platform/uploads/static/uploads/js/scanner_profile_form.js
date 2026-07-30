    // ── Generic combobox ────────────────────────────────────────────────────────
    function initCombobox(wrap) {
        var input    = wrap.querySelector('input');
        var toggle   = wrap.querySelector('.cb-toggle');
        var dropdown = wrap.querySelector('.cb-dropdown');
        if (!input || !dropdown) return;

        var activeIdx = -1;

        function reposition() {
            // Use fixed positioning to escape any parent overflow:hidden clipping
            var rect = input.getBoundingClientRect();
            dropdown.style.position = 'fixed';
            dropdown.style.top      = rect.bottom + 'px';
            dropdown.style.left     = rect.left + 'px';
            dropdown.style.width    = rect.width + 'px';
        }

        function open() {
            reposition();
            dropdown.classList.add('open');
        }

        function close() {
            dropdown.classList.remove('open');
            activeIdx = -1;
        }

        function selectItem(li) {
            input.value = li.dataset.value;
            close();
            // Use 'change' so cascade/other-specify listeners fire
            // without re-triggering the input→open handler
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // mousedown fires before blur/focus: toggle close when already open
        input.addEventListener('mousedown', function (e) {
            if (dropdown.classList.contains('open')) {
                e.preventDefault();
                close();
            }
        });
        input.addEventListener('focus', open);
        input.addEventListener('input', open);
        input.addEventListener('blur', function () { setTimeout(close, 160); });

        input.addEventListener('keydown', function (e) {
            var vis = Array.from(dropdown.querySelectorAll('li'));
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIdx = Math.min(activeIdx + 1, vis.length - 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIdx = Math.max(activeIdx - 1, 0);
            } else if ((e.key === 'Enter' || e.key === 'Tab') && activeIdx >= 0) {
                if (e.key === 'Enter') e.preventDefault();
                selectItem(vis[activeIdx]);
                return;
            } else if (e.key === 'Escape') {
                close(); return;
            }
            vis.forEach(function (li, i) { li.classList.toggle('cb-active', i === activeIdx); });
            if (activeIdx >= 0 && vis[activeIdx]) {
                vis[activeIdx].scrollIntoView({ block: 'nearest' });
            }
        });

        toggle.addEventListener('mousedown', function (e) {
            e.preventDefault();
            if (dropdown.classList.contains('open')) { close(); } else { input.focus(); open(); }
        });

        // Event delegation — works for dynamically added items too
        dropdown.addEventListener('mousedown', function (e) {
            var li = e.target.closest('li[data-value]');
            if (li) { e.preventDefault(); selectItem(li); }
        });
    }

    document.querySelectorAll('.cb-wrap').forEach(initCombobox);

    // ── Manufacturer → Model cascade ────────────────────────────────────────────
    (function () {
        var mfgInput  = document.getElementById('id_manufacturer');
        var modelList = document.getElementById('scanner-model-list');
        if (!mfgInput || !modelList) return;

        var debounce = null;

        function fetchModels(mfgName) {
            if (!mfgName) { modelList.innerHTML = ''; return; }
            fetch('/api/v1/scanners/models/?manufacturer_name=' + encodeURIComponent(mfgName))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    modelList.innerHTML = '';
                    (data.models || []).forEach(function (item) {
                        var li = document.createElement('li');
                        li.setAttribute('role', 'option');
                        li.dataset.value = item.name;
                        li.textContent   = item.name;
                        modelList.appendChild(li);
                    });
                })
                .catch(function (err) { console.warn('Model cascade failed:', err); });
        }

        function clearOtherFields() {
            ['id_scanner_model', 'id_detector_rows', 'id_year_of_installation'].forEach(function (id) {
                var el = document.getElementById(id);
                if (el) el.value = '';
            });
        }

        function onMfgChange() {
            clearOtherFields();
            clearTimeout(debounce);
            debounce = setTimeout(function () { fetchModels(mfgInput.value.trim()); }, 300);
        }

        // Listen to both 'input' (typing) and 'change' (combobox selection)
        mfgInput.addEventListener('input', onMfgChange);
        mfgInput.addEventListener('change', onMfgChange);

        // Pre-populate model list on edit page load
        if (mfgInput.value.trim()) { fetchModels(mfgInput.value.trim()); }
    }());
