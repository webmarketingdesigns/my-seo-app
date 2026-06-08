/* ── State ── */
const today = new Date();
let currentYear = today.getFullYear();
let currentMonth = today.getMonth() + 1; // 1-based
let allTransactions = [];
let activePerson = 'all';
let activeActivity = 'all';

const todayStr = today.toISOString().split('T')[0];
document.getElementById('txnDate').value = todayStr;
document.getElementById('txnDate').max = todayStr;

/* ── Helpers ── */
function ym() {
  return `${currentYear}-${String(currentMonth).padStart(2, '0')}`;
}

function isCurrentMonth() {
  return currentYear === today.getFullYear() && currentMonth === (today.getMonth() + 1);
}

function formatDate(iso) {
  const [y, m, d] = iso.split('-');
  const dt = new Date(Number(y), Number(m) - 1, Number(d));
  return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function setBar(barEl, remainingEl, remaining, total) {
  const pct = Math.max(0, Math.min(100, (remaining / total) * 100));
  barEl.style.width = pct + '%';

  remainingEl.classList.remove('warn', 'danger');
  barEl.classList.remove('warn', 'danger');

  if (pct <= 15) {
    remainingEl.classList.add('danger');
    barEl.classList.add('danger');
  } else if (pct <= 30) {
    remainingEl.classList.add('warn');
    barEl.classList.add('warn');
  }
}

/* ── Load & Render ── */
async function loadAll() {
  const month = ym();
  const [summaryRes, txnsRes] = await Promise.all([
    fetch(`/api/summary/${month}`),
    fetch(`/api/transactions/${month}`),
  ]);
  const summary = await summaryRes.json();
  const txns = await txnsRes.json();
  renderSummary(summary);
  renderTransactions(txns);
}

function renderSummary(s) {
  document.getElementById('monthLabel').textContent = s.meta.month_name;

  for (const person of ['karen', 'wally']) {
    const d = s[person];
    document.getElementById(`${person}Remaining`).textContent = d.remaining.toFixed(2);
    document.getElementById(`${person}Spent`).textContent = d.spent.toFixed(2);
    setBar(
      document.getElementById(`${person}Bar`),
      document.getElementById(`${person}Remaining`),
      d.remaining,
      d.total_credits,
    );
  }

  const meta = s.meta;
  let infoText = `${meta.month_name} — ${meta.days_in_month} days in this month.`;
  if (isCurrentMonth()) {
    infoText += ` Day ${meta.days_elapsed} of ${meta.days_in_month} — ${meta.days_remaining} day${meta.days_remaining !== 1 ? 's' : ''} remaining.`;
    infoText += ' Credits reset to 350 on the 1st of next month.';
  } else {
    infoText += ' Viewing past month (read-only).';
  }
  document.getElementById('monthInfo').textContent = infoText;

  // Hide add form for past months
  document.getElementById('addSection').style.display = isCurrentMonth() ? 'block' : 'none';
}

function renderTransactions(txns) {
  allTransactions = txns;
  applyFilters();
}

function applyFilters() {
  const list = document.getElementById('txnList');
  const filtered = allTransactions.filter(t => {
    if (activePerson !== 'all' && t.person !== activePerson) return false;
    if (activeActivity !== 'all') {
      const activity = t.description.split(' – ')[0];
      if (activity !== activeActivity) return false;
    }
    return true;
  });

  if (!filtered.length) {
    const msg = allTransactions.length
      ? 'No purchases match the selected filters.'
      : 'No purchases recorded yet.';
    list.innerHTML = `<p class="empty-msg">${msg}</p>`;
    return;
  }

  list.innerHTML = filtered.map(t => `
    <div class="txn-item ${t.person}">
      <span class="txn-who">${t.person.charAt(0).toUpperCase() + t.person.slice(1)}</span>
      <span class="txn-date">${formatDate(t.date)}</span>
      <span class="txn-desc">${escHtml(t.description)}</span>
      <span class="txn-amount">${Number(t.amount).toFixed(2)} cr</span>
      ${isCurrentMonth() ? `<button class="txn-delete" data-id="${t.id}">Remove</button>` : ''}
    </div>
  `).join('');

  list.querySelectorAll('.txn-delete').forEach(btn => {
    btn.addEventListener('click', () => deleteTransaction(Number(btn.dataset.id)));
  });
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Add Transaction ── */
document.getElementById('addForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = document.getElementById('formMsg');
  msg.className = 'form-msg';
  msg.textContent = '';

  const activity = document.getElementById('activitySelect').value;
  const notes = document.getElementById('txnDesc').value.trim();
  const description = notes ? `${activity} – ${notes}` : activity;

  const rawAmount = document.getElementById('txnAmount').value;
  const amount = parseFloat(rawAmount);
  if (!rawAmount || isNaN(amount) || amount <= 0) { showMsg('Please enter a valid credit amount.', 'error'); return; }
  if (!/^\d+\.\d{2}$/.test(rawAmount)) { showMsg('Amount must have exactly 2 decimal places (e.g. 12.50).', 'error'); return; }

  const body = {
    person: document.getElementById('personSelect').value,
    amount,
    description,
    date: document.getElementById('txnDate').value,
  };

  try {
    const res = await fetch('/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json();
      showMsg(err.error || 'Could not save.', 'error');
      return;
    }
    document.getElementById('txnAmount').value = '';
    document.getElementById('txnDesc').value = '';
    showMsg('Purchase added!', 'success');
    loadAll();
  } catch {
    showMsg('Network error — please try again.', 'error');
  }
});

function showMsg(text, type) {
  const el = document.getElementById('formMsg');
  el.textContent = text;
  el.className = `form-msg ${type}`;
}

/* ── Delete ── */
async function deleteTransaction(id) {
  if (!confirm('Remove this purchase?')) return;
  try {
    await fetch(`/api/transactions/${id}`, { method: 'DELETE' });
    loadAll();
  } catch {
    alert('Could not remove — please try again.');
  }
}

/* ── Month Navigation ── */
document.getElementById('prevMonth').addEventListener('click', () => {
  currentMonth -= 1;
  if (currentMonth < 1) { currentMonth = 12; currentYear -= 1; }
  loadAll();
});

document.getElementById('nextMonth').addEventListener('click', () => {
  // Don't allow navigating past the current month
  if (isCurrentMonth()) return;
  currentMonth += 1;
  if (currentMonth > 12) { currentMonth = 1; currentYear += 1; }
  loadAll();
});

/* ── Filters ── */
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const group = btn.dataset.filter;
    document.querySelectorAll(`.filter-btn[data-filter="${group}"]`).forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (group === 'person') activePerson = btn.dataset.value;
    if (group === 'activity') activeActivity = btn.dataset.value;
    applyFilters();
  });
});

/* ── Init ── */
loadAll();
