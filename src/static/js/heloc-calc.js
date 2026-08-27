/*
 * 1st Lien HELOC calculator — math engine.
 *
 * A "1st lien HELOC" (a.k.a. all-in-one loan / offset mortgage) replaces the
 * traditional mortgage in first position with a line of credit. Your entire
 * paycheck is deposited into the line, which immediately lowers the balance,
 * and you pay living expenses back out of the line during the month. Interest
 * is charged on the AVERAGE DAILY BALANCE, so idle cash lowers interest for
 * every day it sits there.
 *
 * Two things drive the payoff, and they are very different:
 *   1. Surplus cash flow -> principal. This is just paying extra. A regular
 *      mortgage does the same thing if you send the same money to principal.
 *   2. The "float" from cash sitting in the line before it is spent. This is
 *      the only part that is genuinely unique to the HELOC structure, and it
 *      has to be big enough to overcome the usually-higher variable rate.
 *
 * The engine reports both comparisons so the two are never conflated.
 *
 * Loads in a browser (window.HelocCalc) and in Node (module.exports).
 */
(function (root) {
  'use strict';

  var MAX_MONTHS = 600; // 50 years — simulation guard

  /* ── Small helpers ── */

  function num(value, fallback) {
    var n = typeof value === 'string' ? parseFloat(value.replace(/[$,\s%]/g, '')) : value;
    return typeof n === 'number' && isFinite(n) ? n : (fallback || 0);
  }

  function round2(n) {
    return Math.round(n * 100) / 100;
  }

  function daysInMonth(year, monthIndex) {
    return new Date(year, monthIndex + 1, 0).getDate();
  }

  /** Standard fully-amortizing P&I payment. */
  function monthlyPayment(balance, annualRatePct, months) {
    if (months <= 0 || balance <= 0) return balance > 0 ? balance : 0;
    var r = annualRatePct / 100 / 12;
    if (r === 0) return balance / months;
    return (balance * r) / (1 - Math.pow(1 + r, -months));
  }

  /**
   * Amortize a fixed-rate loan, optionally with a constant extra principal
   * payment each month. Monthly compounding, payment applied at month end.
   */
  function amortize(balance, annualRatePct, payment, extraPerMonth) {
    var r = annualRatePct / 100 / 12;
    var bal = balance;
    var totalInterest = 0;
    var totalPaid = 0;
    var balances = [bal];
    var months = 0;
    var negativeAmortization = false;

    while (bal > 0.005 && months < MAX_MONTHS) {
      var interest = bal * r;
      var due = payment + extraPerMonth;

      if (due <= interest) {
        // Payment does not even cover interest — the balance grows forever.
        negativeAmortization = true;
        break;
      }

      if (due > bal + interest) due = bal + interest; // final, partial payment

      bal = bal + interest - due;
      totalInterest += interest;
      totalPaid += due;
      months++;
      balances.push(Math.max(0, bal));
    }

    return {
      months: months,
      totalInterest: totalInterest,
      totalPaid: totalPaid,
      totalCost: totalInterest,
      balances: balances,
      paidOff: !negativeAmortization && bal <= 0.005,
      negativeAmortization: negativeAmortization,
    };
  }

  /**
   * Simulate the 1st lien HELOC day by day.
   *
   * Draw period: every paycheck lands in the line, expenses are drawn back out
   * across the month, interest accrues daily on any positive balance and is
   * capitalized at month end (equivalent to making the interest-only payment
   * out of the line).
   *
   * Repayment period: draws stop. Whatever is still owed amortizes over the
   * repayment term, paid from income minus expenses.
   */
  function simulateHeloc(input, ratePctOverride) {
    var ratePct = ratePctOverride == null ? input.helocRate : ratePctOverride;
    var dailyRate = ratePct / 100 / 365;
    var drawMonths = Math.round(input.drawPeriodYears * 12);
    var repayMonths = Math.round(input.repayPeriodYears * 12);
    var depositsPerMonth = input.payFrequency === 'semimonthly' ? 2 : 1;
    var depositDays = depositsPerMonth === 2 ? [1, 16] : [1];
    var perDeposit = input.netMonthlyIncome / depositsPerMonth;

    var initialDraw = input.mortgageBalance + (input.rollClosingCosts ? input.closingCosts : 0);
    var balance = initialDraw;

    var totalInterest = 0;
    var totalFees = 0;
    var peakBalance = balance;
    var balances = [balance];
    var rows = [];
    var month = 0;
    var start = new Date();
    var drawEndBalance = null;
    var repayPayment = 0;
    var repayShortfall = 0;
    var growing = false;

    /* ── Draw period: the sweep ── */
    while (balance > 0.005 && month < drawMonths && month < MAX_MONTHS) {
      var cursor = new Date(start.getFullYear(), start.getMonth() + month, 1);
      var days = daysInMonth(cursor.getFullYear(), cursor.getMonth());
      var dailyExpense = input.monthlyExpenses / days;
      var opening = balance;
      var monthInterest = 0;

      for (var day = 1; day <= days; day++) {
        if (depositDays.indexOf(day) !== -1) balance -= perDeposit;
        balance += dailyExpense;
        if (balance > 0) monthInterest += balance * dailyRate;
      }

      balance += monthInterest; // interest capitalizes into the line
      totalInterest += monthInterest;
      month++;

      var fee = 0;
      if (input.annualFee > 0 && month % 12 === 0) {
        fee = input.annualFee;
        balance += fee;
        totalFees += fee;
      }

      rows.push({
        month: month,
        opening: opening,
        deposits: input.netMonthlyIncome,
        draws: input.monthlyExpenses,
        interest: monthInterest,
        fee: fee,
        closing: Math.max(0, balance),
        phase: 'draw',
      });

      if (balance > peakBalance) peakBalance = balance;
      balances.push(Math.max(0, balance));

      // Balance climbing after a full year means the sweep can never win.
      if (month === 12 && balance >= initialDraw) growing = true;
      if (growing) break;
    }

    /* ── Repayment period: draws stop, the rest amortizes ── */
    if (balance > 0.005 && !growing) {
      drawEndBalance = balance;
      var required = monthlyPayment(balance, ratePct, repayMonths);
      var available = input.netMonthlyIncome - input.monthlyExpenses;
      repayPayment = Math.max(required, available);
      repayShortfall = Math.max(0, required - available);

      var repay = amortize(balance, ratePct, repayPayment, 0);
      totalInterest += repay.totalInterest;
      for (var i = 1; i < repay.balances.length; i++) balances.push(repay.balances[i]);

      // Annual fees continue through repayment.
      if (input.annualFee > 0) {
        totalFees += input.annualFee * Math.floor(repay.months / 12);
      }
      for (var j = 0; j < repay.months; j++) {
        rows.push({
          month: month + j + 1,
          opening: repay.balances[j],
          deposits: repayPayment,
          draws: 0,
          interest: repay.balances[j] * (ratePct / 100 / 12),
          fee: 0,
          closing: repay.balances[j + 1],
          phase: 'repay',
        });
      }
      month += repay.months;
      if (!repay.paidOff) growing = true;
      balance = repay.paidOff ? 0 : repay.balances[repay.balances.length - 1];

      repayPayment = required; // report the required payment, i.e. the shock
    }

    var paidOff = !growing && balance <= 0.005 && month < MAX_MONTHS;

    return {
      rate: ratePct,
      initialDraw: initialDraw,
      months: month,
      paidOff: paidOff,
      totalInterest: totalInterest,
      totalFees: totalFees,
      closingCosts: input.closingCosts,
      totalCost: totalInterest + totalFees + input.closingCosts,
      peakBalance: peakBalance,
      drawEndBalance: drawEndBalance,
      repayPayment: repayPayment,
      repayShortfall: repayShortfall,
      balances: balances,
      rows: rows,
      drawMonths: drawMonths,
    };
  }

  /**
   * Lowest HELOC rate is best; find the rate at which the HELOC's total cost
   * equals the apples-to-apples mortgage baseline. Above this rate the HELOC
   * costs more than simply paying the same surplus toward the mortgage.
   */
  function breakEvenRate(input, targetCost) {
    var lo = 0.01;
    var hi = 25;
    var costAt = function (rate) {
      var sim = simulateHeloc(input, rate);
      // A line that never pays off is infinitely worse, not cheap.
      return sim.paidOff ? sim.totalCost : Infinity;
    };
    if (costAt(lo) > targetCost) return null; // never competitive
    if (costAt(hi) < targetCost) return hi;
    for (var i = 0; i < 60; i++) {
      var mid = (lo + hi) / 2;
      if (costAt(mid) < targetCost) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  }

  /** Normalize raw form values into a clean input object. */
  function normalize(raw) {
    raw = raw || {};
    return {
      mortgageBalance: Math.max(0, num(raw.mortgageBalance)),
      mortgageRate: Math.max(0, num(raw.mortgageRate)),
      mortgageTermMonths: Math.max(1, Math.round(num(raw.mortgageTermMonths, 360))),
      mortgagePaymentOverride: Math.max(0, num(raw.mortgagePaymentOverride)),

      helocRate: Math.max(0, num(raw.helocRate)),
      helocLimit: Math.max(0, num(raw.helocLimit)),
      drawPeriodYears: Math.max(1, num(raw.drawPeriodYears, 10)),
      repayPeriodYears: Math.max(1, num(raw.repayPeriodYears, 20)),
      closingCosts: Math.max(0, num(raw.closingCosts)),
      annualFee: Math.max(0, num(raw.annualFee)),
      rollClosingCosts: raw.rollClosingCosts !== false,

      netMonthlyIncome: Math.max(0, num(raw.netMonthlyIncome)),
      monthlyExpenses: Math.max(0, num(raw.monthlyExpenses)),
      payFrequency: raw.payFrequency === 'semimonthly' ? 'semimonthly' : 'monthly',
    };
  }

  /** Run every scenario and assemble the comparison. */
  function calculate(raw) {
    var input = normalize(raw);

    var payment = input.mortgagePaymentOverride > 0
      ? input.mortgagePaymentOverride
      : monthlyPayment(input.mortgageBalance, input.mortgageRate, input.mortgageTermMonths);

    // Scenario 1: keep the mortgage, pay only what is due.
    var mortgage = amortize(input.mortgageBalance, input.mortgageRate, payment, 0);
    mortgage.payment = payment;

    // Scenario 2: keep the mortgage, send the same surplus to principal.
    // This is the honest baseline — the HELOC uses this money too.
    var surplus = input.netMonthlyIncome - input.monthlyExpenses - payment;
    var extraPerMonth = Math.max(0, surplus);
    var mortgageExtra = amortize(input.mortgageBalance, input.mortgageRate, payment, extraPerMonth);
    mortgageExtra.payment = payment;
    mortgageExtra.extraPerMonth = extraPerMonth;

    // Scenario 3: the 1st lien HELOC.
    var heloc = simulateHeloc(input);

    var netCashFlow = input.netMonthlyIncome - input.monthlyExpenses;

    var comparison = {
      netCashFlow: netCashFlow,
      surplusVsMortgage: surplus,
      savedVsMortgage: mortgage.totalCost - heloc.totalCost,
      savedVsExtra: mortgageExtra.totalCost - heloc.totalCost,
      monthsSavedVsMortgage: mortgage.months - heloc.months,
      monthsSavedVsExtra: mortgageExtra.months - heloc.months,
      fromPayingExtra: mortgage.totalCost - mortgageExtra.totalCost,
      breakEvenRate: heloc.paidOff ? breakEvenRate(input, mortgageExtra.totalCost) : null,
    };

    // Rate stress: the mortgage is fixed, the HELOC is not.
    var stress = [0, 1, 2, 3].map(function (bump) {
      var s = simulateHeloc(input, input.helocRate + bump);
      return {
        bump: bump,
        rate: input.helocRate + bump,
        months: s.months,
        paidOff: s.paidOff,
        totalCost: s.totalCost,
        savedVsExtra: mortgageExtra.totalCost - s.totalCost,
      };
    });

    return {
      input: input,
      mortgage: mortgage,
      mortgageExtra: mortgageExtra,
      heloc: heloc,
      comparison: comparison,
      stress: stress,
      warnings: buildWarnings(input, mortgage, mortgageExtra, heloc, comparison),
    };
  }

  /** Plain-language risk flags. These matter more than the headline number. */
  function buildWarnings(input, mortgage, mortgageExtra, heloc, comparison) {
    var w = [];

    if (input.mortgageBalance <= 0 || input.netMonthlyIncome <= 0) {
      w.push({ level: 'info', text: 'Enter your mortgage balance and take-home pay to see real numbers.' });
      return w;
    }

    if (heloc.initialDraw > input.helocLimit) {
      w.push({
        level: 'danger',
        text: 'Your credit line (' + money(input.helocLimit) + ') is smaller than the ' +
          money(heloc.initialDraw) + ' needed to pay off the mortgage. A 1st lien HELOC has to be ' +
          'big enough to replace the whole loan, and lenders size it off your home value and credit.',
      });
    } else if (heloc.initialDraw / input.helocLimit > 0.9) {
      w.push({
        level: 'warn',
        text: 'You would start out using ' + Math.round((heloc.initialDraw / input.helocLimit) * 100) +
          '% of the line, leaving little room for emergencies. The line is also your safety net.',
      });
    }

    if (comparison.netCashFlow <= 0) {
      w.push({
        level: 'danger',
        text: 'Your expenses are at or above your take-home pay, so nothing is left to pay down the ' +
          'balance. A 1st lien HELOC only works when money reliably piles up in the line.',
      });
    } else if (comparison.surplusVsMortgage <= 0) {
      w.push({
        level: 'warn',
        text: 'After your mortgage payment and expenses, there is no surplus left. The balance will fall ' +
          'very slowly, and the variable rate is a real risk.',
      });
    }

    if (!heloc.paidOff) {
      w.push({
        level: 'danger',
        text: 'At these numbers the line never pays off — the interest keeps up with your deposits.',
      });
    }

    if (heloc.repayShortfall > 0) {
      w.push({
        level: 'danger',
        text: 'Payment shock: when the draw period ends you would still owe ' +
          money(heloc.drawEndBalance) + ', requiring ' + money(heloc.repayPayment) +
          '/mo — about ' + money(heloc.repayShortfall) + '/mo more than your cash flow covers.',
      });
    } else if (heloc.drawEndBalance) {
      w.push({
        level: 'warn',
        text: 'You would still owe ' + money(heloc.drawEndBalance) + ' when the draw period ends, ' +
          'switching you to a required ' + money(heloc.repayPayment) + '/mo payment with no more draws.',
      });
    }

    if (input.helocRate > input.mortgageRate) {
      w.push({
        level: 'info',
        text: 'Your HELOC rate is ' + round2(input.helocRate - input.mortgageRate) +
          ' points higher than your mortgage, and it is variable — it can move every month, ' +
          'while your mortgage rate cannot.',
      });
    }

    if (comparison.savedVsExtra < 0) {
      w.push({
        level: 'warn',
        text: 'Against the fair comparison — paying that same surplus straight at your mortgage — ' +
          'the HELOC costs ' + money(Math.abs(comparison.savedVsExtra)) + ' more.',
      });
    }

    return w;
  }

  function money(n) {
    return '$' + Math.round(n).toLocaleString('en-US');
  }

  var api = {
    calculate: calculate,
    normalize: normalize,
    monthlyPayment: monthlyPayment,
    amortize: amortize,
    simulateHeloc: simulateHeloc,
    breakEvenRate: breakEvenRate,
    MAX_MONTHS: MAX_MONTHS,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HelocCalc = api;
})(typeof window !== 'undefined' ? window : null);
