document.querySelectorAll('select[data-auto-submit]').forEach((el) => {
    el.addEventListener('change', () => el.form.submit());
});
