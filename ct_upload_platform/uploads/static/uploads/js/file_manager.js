    // ── Tab switching ──────────────────────────────────────────────
    function switchTab(name, btn) {
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(`tab-${name}`).classList.add('active');
        btn.classList.add('active');
        activeTable = name === 'exams' ? 'exam-table' : 'protocol-table';
        filterRows();
    }

    // ── Client-side text search across visible table ───────────────
    let activeTable = 'exam-table';

    function filterRows() {
        const q = document.getElementById('global-search').value.toLowerCase();
        const tbody = document.querySelector(`#${activeTable} tbody`);
        tbody.querySelectorAll('tr').forEach(row => {
            if (row.querySelector('td[colspan]')) return; // empty-state row
            const text = row.textContent.toLowerCase();
            row.style.display = (!q || text.includes(q)) ? '' : 'none';
        });
    }

    document.getElementById('global-search').addEventListener('input', filterRows);
    document.querySelectorAll('.tab-btn[data-tab]').forEach((btn) => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab, btn));
    });
