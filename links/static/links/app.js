document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-copy], [data-copy-target]');
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy || document.getElementById(button.dataset.copyTarget).value);
    const label = button.textContent;
    button.textContent = 'コピーしました';
    document.getElementById('copy-status').textContent = 'クリップボードにコピーしました。';
    setTimeout(() => { button.textContent = label; }, 2000);
  } catch {
    button.textContent = 'コピーできません。文字列を選択してください';
    document.getElementById('copy-status').textContent = 'コピーできませんでした。文字列を選択してコピーしてください。';
  }
});
document.addEventListener('submit', (event) => {
  if (event.target.dataset.confirm && !window.confirm(event.target.dataset.confirm)) event.preventDefault();
});
