/* Close all open menus when clicking outside; delegate add-protocol/group-header clicks */
document.addEventListener('click', function(e) {
    const addProtoBtn = e.target.closest('.add-proto-btn');
    if (addProtoBtn) { toggleMenu(addProtoBtn); return; }

    const groupHeader = e.target.closest('.group-header');
    if (groupHeader) { toggleGroup(groupHeader); return; }

    if (!e.target.closest('.add-proto-wrap')) {
        document.querySelectorAll('.add-proto-menu.open').forEach(m => m.classList.remove('open'));
    }
});

document.querySelectorAll('#typeFilters input[data-type]').forEach((cb) => {
    cb.addEventListener('change', applyFilters);
});

function toggleMenu(btn) {
    const menu = btn.nextElementSibling;
    const isOpen = menu.classList.contains('open');
    document.querySelectorAll('.add-proto-menu.open').forEach(m => m.classList.remove('open'));
    if (!isOpen) menu.classList.add('open');
}

/* Collapse / expand a protocol group */
function toggleGroup(header) {
    const body = header.nextElementSibling;
    const arrow = header.querySelector('.group-toggle');
    const collapsed = body.style.display === 'none';
    body.style.display = collapsed ? '' : 'none';
    arrow.textContent = collapsed ? '▾' : '▸';
}

/* Show/hide entire protocol-group blocks based on checked types */
function applyFilters() {
    const checked = new Set(
        [...document.querySelectorAll('#typeFilters input:checked')].map(cb => cb.dataset.type)
    );
    document.querySelectorAll('.protocol-group').forEach(g => {
        g.style.display = checked.has(g.dataset.type) ? '' : 'none';
    });
}
