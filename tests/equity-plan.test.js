/*
 * Invariants for the home equity debt-elimination engine.
 * Run: node --test tests/equity-plan.test.js
 */
const test = require('node:test');
const assert = require('node:assert');
const EP = require('../src/static/js/equity-plan.js');

const BASE = {
  property: { homeValue: 450000, mortgageBalance: 280000, maxCltv: 85 },
  heloc: { rate: 8.5, drawYears: 10, repayYears: 20, closingCosts: 0, annualFee: 50, rollClosingCosts: true },
  cashflow: { netIncome: 8200, livingExpenses: 4200, mortgagePayment: 1950 },
  debts: [
    { id: 'c1', name: 'Visa', type: 'card', balance: 18000, apr: 24.99, minimum: 450 },
    { id: 'c2', name: 'Store card', type: 'card', balance: 9500, apr: 21.5, minimum: 240 },
    { id: 'a1', name: 'Auto loan', type: 'auto', balance: 22000, apr: 7.2, minimum: 520 },
    { id: 'p1', name: 'Personal loan', type: 'personal', balance: 12000, apr: 14.9, minimum: 310 },
    { id: 's1', name: 'Student loan', type: 'student', balance: 28000, apr: 6.8, minimum: 290 },
  ],
};

const clone = (o) => JSON.parse(JSON.stringify(o));

test('usable equity is the lendable ceiling minus what is already owed', () => {
  const r = EP.calculate(BASE);
  assert.strictEqual(r.equity.usable, 450000 * 0.85 - 280000); // 102,500
  assert.ok(Math.abs(r.equity.currentLtv - 62.22) < 0.01);
});

test('no equity means no draw, and it is called out', () => {
  const input = clone(BASE);
  input.property.mortgageBalance = 430000;
  const r = EP.calculate(input);
  assert.strictEqual(r.equity.usable, 0);
  assert.strictEqual(r.draw.helocBalance, 0);
  assert.ok(r.warnings.some((w) => w.key === 'noequity' && w.level === 'danger'));
});

test('only debts costing more than the line are moved onto the house', () => {
  const r = EP.calculate(BASE);
  const moved = r.draw.consolidated.map((d) => d.id).sort();
  assert.deepStrictEqual(moved, ['c1', 'c2', 'p1']); // the 24.99%, 21.5% and 14.9%
  // The 7.2% auto and 6.8% student loans are cheaper than the 8.5% line.
  assert.deepStrictEqual(r.draw.skipped.map((d) => d.id).sort(), ['a1', 's1']);
});

test('null include follows the rate rule, exactly as undefined does', () => {
  // The UI stores "auto" as null; the engine must not read that as "exclude".
  const input = clone(BASE);
  input.debts.forEach((d) => { d.include = null; });
  const r = EP.calculate(input);
  assert.deepStrictEqual(r.draw.consolidated.map((d) => d.id).sort(), ['c1', 'c2', 'p1']);
  assert.ok(r.draw.helocBalance > 0);
});

test('an explicit include overrides the rate rule in both directions', () => {
  const input = clone(BASE);
  input.debts.find((d) => d.id === 's1').include = true;  // cheaper, but forced in
  input.debts.find((d) => d.id === 'c1').include = false; // costly, but held back
  const r = EP.calculate(input);
  const moved = r.draw.consolidated.map((d) => d.id);
  assert.ok(moved.includes('s1'));
  assert.ok(!moved.includes('c1'));
  assert.ok(r.warnings.some((w) => w.key === 'cheaper'));
});

test('the draw stops at the equity available, leaving a partial paydown', () => {
  const input = clone(BASE);
  input.property.mortgageBalance = 360000; // only $22,500 of room — not enough for both cards
  const r = EP.calculate(input);
  assert.ok(r.draw.helocBalance <= r.equity.usable + 0.01);
  assert.strictEqual(r.draw.consolidated.map((d) => d.id).join(','), 'c1'); // the costliest first
  assert.ok(r.draw.partial, 'the remaining room dents the next debt');
  assert.ok(r.warnings.some((w) => w.key === 'partial'));
});

test('freed cash flow is the drop in required monthly payments', () => {
  const r = EP.calculate(BASE);
  assert.ok(Math.abs(r.cashflow.requiredBefore - 1810) < 0.01);
  const expected = r.cashflow.requiredBefore - r.cashflow.requiredAfter;
  assert.ok(Math.abs(r.cashflow.freed - expected) < 0.01);
  assert.ok(r.cashflow.freed > 0);
});

test('discipline beats drift, with or without the equity line', () => {
  const r = EP.calculate(BASE);
  assert.ok(r.scenarios.avalanche.months < r.scenarios.minimums.months);
  assert.ok(r.scenarios.attack.months < r.scenarios.coast.months);
  assert.ok(r.scenarios.attack.totalCost < r.scenarios.coast.totalCost);
});

test('consolidating and then spending the freed cash flow is the expensive path', () => {
  const r = EP.calculate(BASE);
  // Coasting on a 30-year line costs more than never consolidating at all.
  assert.ok(r.scenarios.coast.totalCost > r.scenarios.minimums.totalCost);
  assert.ok(r.comparison.costOfCoasting > 0);
});

test('the fair comparison is stated separately from the flattering one', () => {
  const r = EP.calculate(BASE);
  // Rate arbitrage is real here, so the line does beat a plain avalanche...
  assert.ok(r.comparison.interestSavedVsAvalanche > 0);
  // ...but by far less than the do-nothing baseline suggests.
  assert.ok(r.comparison.interestSavedVsMinimums > r.comparison.interestSavedVsAvalanche);
});

test('every scenario reconciles: principal + interest equals what was paid', () => {
  const r = EP.calculate(BASE);
  const s = r.scenarios.avalanche;
  const budget = r.cashflow.debtBudget;
  const paid = budget * s.months;
  const owed = s.startingTotal + s.totalInterest;
  // The final month is partial, so payments never exceed the debt by more than one month.
  assert.ok(paid >= owed - 0.5);
  assert.ok(paid - owed < budget);
});

test('moving unsecured debt onto the house is always flagged', () => {
  const r = EP.calculate(BASE);
  const flag = r.warnings.find((w) => w.key === 'secured');
  assert.ok(flag && flag.level === 'danger');
  assert.ok(/unsecured/.test(flag.text));
  assert.ok(r.warnings.some((w) => w.key === 'reaccumulate'));
});

test('a minimum below the accruing interest is caught, not looped forever', () => {
  const r = EP.calculate({
    ...clone(BASE),
    debts: [{ id: 'x', name: 'Runaway card', type: 'card', balance: 20000, apr: 29.99, minimum: 100 }],
  });
  assert.ok(!r.scenarios.minimums.paidOff);
  assert.ok(r.scenarios.minimums.months <= EP.MAX_MONTHS);
});

test('minimums exceeding the budget are reported as the real problem', () => {
  const input = clone(BASE);
  input.cashflow.netIncome = 6300; // budget falls below the $1,810 of minimums
  const r = EP.calculate(input);
  assert.strictEqual(r.cashflow.canMeetMinimums, false);
  assert.ok(r.cashflow.shortfall > 0);
  assert.ok(r.warnings.some((w) => w.key === 'cantmeet' && w.level === 'danger'));
});

test('an empty plan asks for input instead of inventing a verdict', () => {
  const r = EP.calculate({ property: {}, heloc: {}, cashflow: {}, debts: [] });
  assert.strictEqual(r.debtSummary.totalDebt, 0);
  assert.deepStrictEqual(r.warnings.map((w) => w.key), ['setup']);
});

test('drawing past 80% of the home value is flagged', () => {
  const input = clone(BASE);
  input.property.mortgageBalance = 330000; // 73% before the draw
  const r = EP.calculate(input);
  assert.ok(r.equity.afterLtv > 80);
  assert.ok(r.warnings.some((w) => w.key === 'ltv'));
});

/* ── Bills vs debts, and sweep mode ── */

const WITH_BILLS = {
  ...clone(BASE),
  cashflow: { ...BASE.cashflow, payFrequency: 'monthly' },
  debts: [
    ...clone(BASE).debts,
    { id: 'b1', name: 'Electric', type: 'other', balance: 0, minimum: 180 },
    { id: 'b2', name: 'Internet', type: 'other', balance: 0, minimum: 90 },
  ],
};

test('a row with no balance is a bill; a row with a balance is a debt', () => {
  const n = EP.normalize(WITH_BILLS);
  assert.strictEqual(n.bills.length, 2);
  assert.strictEqual(n.debts.length, 5);
  assert.deepStrictEqual(n.bills.map((b) => b.name), ['Electric', 'Internet']);
});

test('an explicit kind overrides what the balance implies', () => {
  const n = EP.normalize({
    ...clone(BASE),
    debts: [
      { id: 'x', name: 'Storage', balance: 4500, minimum: 375, kind: 'bill' },
      { id: 'y', name: 'Zero-rate plan', balance: 0, minimum: 100, kind: 'debt' },
    ],
  });
  assert.strictEqual(n.bills.length, 1);
  assert.strictEqual(n.bills[0].name, 'Storage');
  assert.strictEqual(n.bills[0].balance, 0, 'a bill carries no balance');
  // A debt with no balance is dropped from the payoff set, as before.
  assert.strictEqual(n.debts.length, 0);
});

test('bills are added to expenses and shrink the debt budget', () => {
  const plain = EP.calculate(BASE);
  const withBills = EP.calculate(WITH_BILLS);
  assert.strictEqual(withBills.expenses.bills, 270);
  assert.strictEqual(withBills.expenses.other, BASE.cashflow.livingExpenses);
  assert.strictEqual(withBills.expenses.total, BASE.cashflow.livingExpenses + 270);
  assert.ok(Math.abs(withBills.cashflow.debtBudget - (plain.cashflow.debtBudget - 270)) < 0.01);
});

test('no row is lost when a mixed list is split', () => {
  const n = EP.normalize(WITH_BILLS);
  const namesIn = WITH_BILLS.debts.map((d) => d.name).sort();
  const namesOut = n.debts.concat(n.bills).map((d) => d.name).sort();
  assert.deepStrictEqual(namesOut, namesIn);
});

test('every scenario is given the same money to work with', () => {
  // Minimums far above the budget used to hand avalanche more than attack,
  // which made consolidating look catastrophic.
  const input = clone(BASE);
  input.cashflow.netIncome = 6300; // budget below the minimums
  const r = EP.calculate(input);
  assert.ok(r.cashflow.requiredTopUp > 0);
  assert.strictEqual(r.cashflow.planBudget, r.cashflow.debtBudget + r.cashflow.requiredTopUp);
  // Consolidating to a lower rate can never be the slower path on equal money.
  assert.ok(r.scenarios.attack.months <= r.scenarios.avalanche.months);
  assert.ok(r.scenarios.attack.totalCost <= r.scenarios.avalanche.totalCost);
});

test('sweeping beats paying the same money monthly, by the float alone', () => {
  const r = EP.calculate(WITH_BILLS);
  assert.ok(r.scenarios.sweep.paidOff);
  assert.ok(r.comparison.sweepGainVsAttack > 0, 'the float is worth something');
  // But only something: it is a timing edge, not a different strategy.
  assert.ok(r.comparison.sweepGainVsAttack < r.comparison.interestSavedVsAvalanche);
});

test('pay landing later in the month earns less float', () => {
  const asOf = (payFrequency) => EP.calculate({
    ...WITH_BILLS, cashflow: { ...WITH_BILLS.cashflow, payFrequency },
  }).scenarios.sweep.totalCost;
  assert.ok(asOf('monthly') < asOf('semimonthly'));
  assert.ok(asOf('semimonthly') < asOf('weekly'));
});

test('the sweep chunks at remaining debts instead of letting cash idle', () => {
  // With the line cleared early, the surplus must keep working on what is left.
  const input = clone(WITH_BILLS);
  input.property.homeValue = 900000; // plenty of equity, line clears fast
  const r = EP.calculate(input);
  assert.ok(r.scenarios.sweep.paidOff);
  assert.ok(r.scenarios.sweep.months <= r.scenarios.attack.months);
});

test('a sweep that cannot cover its own outgoings is refused, not projected', () => {
  const input = clone(WITH_BILLS);
  input.cashflow.netIncome = 1000; // below the mortgage and bills alone
  const r = EP.calculate(input);
  assert.ok(r.scenarios.sweep.infeasible);
  assert.ok(r.warnings.some((w) => w.key === 'sweepnegative' && w.level === 'danger'));
});

test('itemized bills alongside a lump expense figure raise a double-count note', () => {
  const r = EP.calculate(WITH_BILLS);
  assert.ok(r.warnings.some((w) => w.key === 'doublecount'));
});
