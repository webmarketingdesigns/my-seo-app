/*
 * Math invariants for the 1st lien HELOC engine.
 * Run: node --test tests/
 */
const test = require('node:test');
const assert = require('node:assert');
const calc = require('../src/static/js/heloc-calc.js');

const BASE = {
  mortgageBalance: 350000,
  mortgageRate: 6.5,
  mortgageTermMonths: 324,
  helocRate: 7.75,
  helocLimit: 400000,
  drawPeriodYears: 10,
  repayPeriodYears: 20,
  closingCosts: 3500,
  annualFee: 75,
  rollClosingCosts: true,
  netMonthlyIncome: 9000,
  monthlyExpenses: 4500,
  payFrequency: 'semimonthly',
};

test('monthlyPayment matches the standard amortization formula', () => {
  // $200,000 at 6% for 30 years is a well-known $1,199.10.
  assert.ok(Math.abs(calc.monthlyPayment(200000, 6, 360) - 1199.10) < 0.05);
  // Zero interest is just principal spread over the term.
  assert.strictEqual(calc.monthlyPayment(120000, 0, 240), 500);
});

test('amortizing at the scheduled payment retires the loan on schedule', () => {
  const payment = calc.monthlyPayment(200000, 6, 360);
  const result = calc.amortize(200000, 6, payment, 0);
  assert.strictEqual(result.months, 360);
  assert.ok(result.paidOff);
  assert.ok(Math.abs(result.totalInterest - 231676) < 500);
});

test('extra principal shortens the term and cuts interest', () => {
  const payment = calc.monthlyPayment(200000, 6, 360);
  const plain = calc.amortize(200000, 6, payment, 0);
  const extra = calc.amortize(200000, 6, payment, 500);
  assert.ok(extra.months < plain.months);
  assert.ok(extra.totalInterest < plain.totalInterest);
});

test('a payment below the accruing interest is flagged, not looped forever', () => {
  const result = calc.amortize(200000, 6, 100, 0);
  assert.ok(result.negativeAmortization);
  assert.ok(!result.paidOff);
  assert.ok(result.months < calc.MAX_MONTHS);
});

test('the HELOC and the extra-principal mortgage spend the same money each month', () => {
  const r = calc.calculate(BASE);
  const towardHousing = r.mortgageExtra.payment + r.mortgageExtra.extraPerMonth;
  assert.ok(Math.abs(towardHousing - (BASE.netMonthlyIncome - BASE.monthlyExpenses)) < 0.01);
});

test('at a higher variable rate the HELOC loses to paying the same surplus', () => {
  const r = calc.calculate(BASE);
  assert.ok(r.heloc.paidOff);
  // It still beats making only the minimum mortgage payment...
  assert.ok(r.comparison.savedVsMortgage > 0);
  // ...but that advantage is the extra money, not the sweep.
  assert.ok(r.comparison.savedVsExtra < 0);
});

test('at an equal rate the sweep float is a real but small edge', () => {
  const r = calc.calculate({ ...BASE, helocRate: BASE.mortgageRate, closingCosts: 0, annualFee: 0 });
  assert.ok(r.comparison.savedVsExtra > 0);
  // Single-digit thousands on a $350k loan — not the six figures sales pitches quote.
  assert.ok(r.comparison.savedVsExtra < 10000);
});

test('break-even rate sits where HELOC cost equals the fair mortgage baseline', () => {
  const r = calc.calculate(BASE);
  const rate = r.comparison.breakEvenRate;
  assert.ok(rate > 0 && rate < 25);
  const atBreakEven = calc.simulateHeloc(calc.normalize(BASE), rate);
  assert.ok(Math.abs(atBreakEven.totalCost - r.mortgageExtra.totalCost) < 1500);
});

test('a line that never pays off is never reported as cheap', () => {
  const r = calc.calculate({ ...BASE, netMonthlyIncome: 5000 });
  assert.ok(!r.heloc.paidOff);
  assert.ok(r.warnings.some((w) => w.level === 'danger'));
});

test('when the whole paycheck lands earlier, daily interest is lower', () => {
  const monthly = calc.simulateHeloc(calc.normalize({ ...BASE, payFrequency: 'monthly' }));
  const semi = calc.simulateHeloc(calc.normalize({ ...BASE, payFrequency: 'semimonthly' }));
  // Splitting pay across the 1st and the 16th leaves a higher average daily
  // balance than depositing everything on the 1st, so it costs more interest.
  assert.ok(semi.totalInterest > monthly.totalInterest);
});

test('a line smaller than the mortgage is called out as disqualifying', () => {
  const r = calc.calculate({ ...BASE, helocLimit: 200000 });
  assert.ok(r.warnings.some((w) => w.level === 'danger' && /credit line/.test(w.text)));
});

test('payment shock at the end of the draw period is surfaced', () => {
  // Barely positive cash flow leaves a large balance when draws stop.
  const r = calc.calculate({ ...BASE, netMonthlyIncome: 7200, drawPeriodYears: 5 });
  assert.ok(r.heloc.drawEndBalance > 0);
  assert.ok(r.heloc.repayPayment > 0);
  assert.ok(r.warnings.some((w) => /draw period ends/.test(w.text)));
});
