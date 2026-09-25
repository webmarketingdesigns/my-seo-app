/*
 * Home equity debt-elimination & cash flow engine.
 *
 * The question it answers: if I borrow against my home equity to wipe out
 * high-rate debts, what happens to (a) how fast I get debt-free, (b) how much
 * interest I hand over, and (c) how much cash is free every month?
 *
 * Four scenarios, deliberately paired so the comparison is honest:
 *
 *   A  Minimums only ............. no HELOC, no discipline   (the drift case)
 *   B  Avalanche ................. no HELOC, full discipline (the free option)
 *   C  Consolidate, then coast ... HELOC, no discipline      (the trap)
 *   D  Consolidate, then attack .. HELOC, full discipline    (the strategy)
 *
 * A and C spend the same money (minimums only). B and D spend the same money
 * (every dollar of the debt budget). So B vs D isolates what the equity draw
 * is really worth, and A vs C shows what happens if the freed cash flow gets
 * spent instead of redeployed. Unlike a 1st-lien sweep, the gain here is plain
 * rate arbitrage — 24% card debt refinanced at 8% — which is real and large.
 *
 * The cost it cannot price: unsecured debt becomes secured against the house.
 * That is a risk flag, not a number.
 *
 * Loads in a browser (window.EquityPlan) and in Node (module.exports).
 */
(function (root) {
  'use strict';

  var MAX_MONTHS = 600; // 50 years — simulation guard

  function num(value, fallback) {
    var n = typeof value === 'string' ? parseFloat(value.replace(/[$,\s%]/g, '')) : value;
    return typeof n === 'number' && isFinite(n) ? n : (fallback || 0);
  }

  function round2(n) { return Math.round(n * 100) / 100; }

  function money(n) { return '$' + Math.round(n).toLocaleString('en-US'); }

  /** Standard fully-amortizing payment. */
  function monthlyPayment(balance, annualRatePct, months) {
    if (months <= 0 || balance <= 0) return balance > 0 ? balance : 0;
    var r = annualRatePct / 100 / 12;
    if (r === 0) return balance / months;
    return (balance * r) / (1 - Math.pow(1 + r, -months));
  }

  /**
   * Month-by-month payoff simulation over a set of accounts.
   *
   * accounts: [{ id, name, balance, apr, minimum, kind }] where kind is
   *   'debt' or 'heloc'. A HELOC's minimum is interest-only during the draw
   *   period, then the amortizing payment over the repayment period.
   *
   * opts.budget      total dollars available for debt service each month
   * opts.applyExtra  whether anything above the minimums is actually applied
   *                  (false models the freed cash flow being spent)
   */
  function simulate(accounts, opts) {
    opts = opts || {};
    var budget = num(opts.budget);
    var applyExtra = !!opts.applyExtra;
    var drawMonths = Math.round(num(opts.helocDrawYears, 10) * 12);
    var repayMonths = Math.round(num(opts.helocRepayYears, 20) * 12);
    var annualFee = num(opts.helocAnnualFee);

    var live = accounts.map(function (a) {
      return {
        id: a.id, name: a.name, kind: a.kind || 'debt',
        balance: num(a.balance), apr: num(a.apr), minimum: num(a.minimum),
        paidOffMonth: null,
      };
    }).filter(function (a) { return a.balance > 0.005; });

    var startingTotal = live.reduce(function (s, a) { return s + a.balance; }, 0);
    var totalInterest = 0;
    var totalFees = 0;
    var history = [startingTotal];
    var firstMonthOutlay = null;
    var month = 0;
    var stalled = false;
    var infeasible = false;

    while (month < MAX_MONTHS) {
      var open = live.filter(function (a) { return a.balance > 0.005; });
      if (!open.length) break;
      month++;

      // 1. Interest accrues, plus any annual fee on the line.
      open.forEach(function (a) {
        var interest = a.balance * (a.apr / 100 / 12);
        a.balance += interest;
        totalInterest += interest;
        if (a.kind === 'heloc' && annualFee > 0 && month % 12 === 0) {
          a.balance += annualFee;
          totalFees += annualFee;
        }
      });

      // 2. Minimum due on each account.
      var dues = open.map(function (a) {
        var due;
        if (a.kind === 'heloc') {
          var interestOnly = a.balance * (a.apr / 100 / 12);
          if (month <= drawMonths) {
            due = interestOnly;
          } else {
            var left = Math.max(1, repayMonths - (month - drawMonths) + 1);
            due = monthlyPayment(a.balance, a.apr, left);
          }
        } else {
          due = a.minimum;
        }
        return { account: a, due: Math.min(due, a.balance) };
      });

      var totalDue = dues.reduce(function (s, d) { return s + d.due; }, 0);

      // The plan is not affordable at all if the minimums exceed the budget.
      if (totalDue > budget + 0.005) infeasible = true;

      dues.forEach(function (d) {
        d.account.balance -= d.due;
      });

      // 3. Anything left in the budget attacks the costliest debt first.
      var spent = totalDue;
      if (applyExtra) {
        var extra = budget - totalDue;
        while (extra > 0.005) {
          var target = live
            .filter(function (a) { return a.balance > 0.005; })
            .sort(function (x, y) { return y.apr - x.apr; })[0];
          if (!target) break;
          var pay = Math.min(extra, target.balance);
          target.balance -= pay;
          extra -= pay;
          spent += pay;
        }
      }

      if (firstMonthOutlay === null) firstMonthOutlay = spent;

      live.forEach(function (a) {
        if (a.balance <= 0.005 && a.paidOffMonth === null) {
          a.balance = 0;
          a.paidOffMonth = month;
        }
      });

      var remaining = live.reduce(function (s, a) { return s + a.balance; }, 0);
      history.push(remaining);

      // A balance that has not moved in a year is never going to.
      if (month === 12 && remaining >= startingTotal - 0.005) { stalled = true; break; }
    }

    var cleared = live.every(function (a) { return a.balance <= 0.005; });

    return {
      months: month,
      paidOff: cleared && !stalled && month < MAX_MONTHS,
      stalled: stalled,
      infeasible: infeasible,
      totalInterest: totalInterest,
      totalFees: totalFees,
      totalCost: totalInterest + totalFees,
      startingTotal: startingTotal,
      firstMonthOutlay: firstMonthOutlay || 0,
      history: history,
      accounts: live.map(function (a) {
        return { id: a.id, name: a.name, kind: a.kind, paidOffMonth: a.paidOffMonth };
      }),
    };
  }

  function daysInMonth(year, monthIndex) {
    return new Date(year, monthIndex + 1, 0).getDate();
  }

  /**
   * SWEEP MODE — the all-in-one / 1st-lien style arrangement.
   *
   * Every paycheck is deposited straight into the equity line, which drops the
   * balance that day. Everything the household spends — the mortgage, the
   * itemized bills, general spending, and the minimums on any debt that was
   * not consolidated — is drawn back out across the month. Interest is charged
   * on the AVERAGE DAILY BALANCE, so idle cash cuts the interest bill for
   * every day it sits in the line before it is spent.
   *
   * Against simply paying the same surplus monthly, the extra gain is the
   * float alone. Modelling it separately is the point: it lets the float be
   * measured rather than assumed.
   */
  function simulateSweep(input, draw, otherDebts, topUp) {
    var h = input.heloc;
    var c = input.cashflow;
    var income = c.netIncome + Math.max(0, topUp || 0);
    var dailyRate = h.rate / 100 / 365;
    var drawMonths = Math.round(h.drawYears * 12);
    var repayMonths = Math.round(h.repayYears * 12);
    var depositDays = c.payFrequency === 'weekly' ? [1, 8, 15, 22]
      : c.payFrequency === 'semimonthly' ? [1, 16] : [1];
    var perDeposit = income / depositDays.length;

    var billsTotal = input.bills.reduce(function (s, b) { return s + b.minimum; }, 0);
    var fixedOutflow = c.mortgagePayment + billsTotal + c.livingExpenses;

    var balance = draw.helocBalance;
    var debts = otherDebts.map(function (d) {
      return { balance: d.balance, apr: d.apr, minimum: d.minimum };
    });

    var outstanding = function () {
      return debts.reduce(function (s, d) { return s + Math.max(0, d.balance); }, 0);
    };

    var startingTotal = balance + outstanding();
    var totalInterest = 0, totalFees = 0;
    var history = [startingTotal];
    var month = 0, stalled = false;
    var start = new Date();
    var peak = balance;
    var drawEndBalance = null;

    while (month < MAX_MONTHS && month < drawMonths) {
      if (balance <= 0.005 && outstanding() <= 0.005) { balance = Math.min(balance, 0); break; }
      var cursor = new Date(start.getFullYear(), start.getMonth() + month, 1);
      var days = daysInMonth(cursor.getFullYear(), cursor.getMonth());
      month++;

      // Debts left outside the line take their minimums, drawn from the line.
      var debtPayments = 0;
      debts.forEach(function (d) {
        if (d.balance <= 0.005) return;
        var interest = d.balance * (d.apr / 100 / 12);
        d.balance += interest;
        totalInterest += interest;
        var pay = Math.min(d.minimum, d.balance);
        d.balance -= pay;
        debtPayments += pay;
        if (d.balance <= 0.005) d.balance = 0;
      });

      var dailyOut = (fixedOutflow + debtPayments) / days;
      var monthInterest = 0;

      for (var day = 1; day <= days; day++) {
        if (depositDays.indexOf(day) !== -1) balance -= perDeposit;
        balance += dailyOut;
        if (balance > 0) monthInterest += balance * dailyRate;
      }

      balance += monthInterest;
      totalInterest += monthInterest;
      if (h.annualFee > 0 && month % 12 === 0 && balance > 0) {
        balance += h.annualFee;
        totalFees += h.annualFee;
      }

      // "Chunking": once the line is clear, the cash piling up in it is drawn
      // straight back out to kill the next-costliest debt. Without this the
      // surplus would sit idle while high-rate balances crawled along on their
      // minimums — which is not how anyone actually runs a sweep.
      while (balance < -0.005 && outstanding() > 0.005) {
        var target = debts
          .filter(function (d) { return d.balance > 0.005; })
          .sort(function (x, y) { return y.apr - x.apr; })[0];
        if (!target) break;
        var chunk = Math.min(-balance, target.balance);
        target.balance -= chunk;
        balance += chunk;
        if (target.balance <= 0.005) target.balance = 0;
      }

      if (balance > peak) peak = balance;
      history.push(Math.max(0, balance) + outstanding());

      if (month === 12 && Math.max(0, balance) + outstanding() >= startingTotal - 0.005) {
        stalled = true;
        break;
      }
    }

    // Draw period over: no more drawing. Whatever is left amortizes, paid out
    // of whatever the household has spare each month.
    if (!stalled && month >= drawMonths && (balance > 0.005 || outstanding() > 0.005)) {
      drawEndBalance = balance;
      var spare = income - fixedOutflow;
      var required = monthlyPayment(balance, h.rate, repayMonths);
      var tailAccounts = [{
        id: 'heloc', name: 'Home equity line', balance: balance,
        apr: h.rate, minimum: Math.max(required, 0), kind: 'debt',
      }];
      debts.forEach(function (d, i) {
        if (d.balance > 0.005) {
          tailAccounts.push({ id: 'rest' + i, name: 'Remaining debt', balance: d.balance, apr: d.apr, minimum: d.minimum, kind: 'debt' });
        }
      });
      var tail = simulate(tailAccounts, {
        budget: Math.max(spare, required), applyExtra: true,
        helocDrawYears: 0, helocRepayYears: h.repayYears, helocAnnualFee: h.annualFee,
      });
      totalInterest += tail.totalInterest;
      totalFees += tail.totalFees;
      for (var k = 1; k < tail.history.length; k++) history.push(tail.history[k]);
      month += tail.months;
      if (!tail.paidOff) stalled = true;
      balance = tail.paidOff ? 0 : balance;
      if (tail.paidOff) debts.forEach(function (d) { d.balance = 0; });
    }

    var cleared = !stalled && balance <= 0.005 && outstanding() <= 0.005;
    return {
      months: month,
      paidOff: cleared && month < MAX_MONTHS,
      stalled: stalled,
      infeasible: income < fixedOutflow,
      totalInterest: totalInterest,
      totalFees: totalFees,
      totalCost: totalInterest + totalFees,
      startingTotal: startingTotal,
      firstMonthOutlay: fixedOutflow,
      peakBalance: peak,
      drawEndBalance: drawEndBalance,
      history: history,
      accounts: [],
    };
  }

  /**
   * Normalize one row. A row is either a DEBT — a balance being paid down,
   * which the payoff engine simulates — or a BILL: a steady monthly amount
   * with no balance (utilities, insurance, storage), which is simply part of
   * the cost of living and never gets "paid off".
   *
   * `minimum` carries the monthly amount for both, so a row can move between
   * the two without any of its numbers being rewritten.
   */
  function normalizeRow(raw, index) {
    var balance = Math.max(0, num(raw.balance));
    // An explicit kind wins; otherwise a balance is what makes it a debt.
    var kind = (raw.kind === 'bill' || raw.kind === 'debt')
      ? raw.kind
      : (balance > 0 ? 'debt' : 'bill');
    return {
      id: raw.id || ('r' + index),
      name: (raw.name || '').toString().slice(0, 60),
      type: raw.type || 'other',
      kind: kind,
      balance: kind === 'bill' ? 0 : balance,
      apr: kind === 'bill' ? 0 : Math.max(0, num(raw.apr)),
      minimum: Math.max(0, num(raw.minimum)),
      // null/undefined mean "decide by rate"; true/false is an explicit override
      include: raw.include == null ? null : !!raw.include,
    };
  }

  function normalize(raw) {
    raw = raw || {};
    var p = raw.property || {};
    var h = raw.heloc || {};
    var c = raw.cashflow || {};
    // One list in, split by kind. `bills` may arrive as its own list too.
    var rows = (raw.debts || []).concat(raw.bills || []).map(normalizeRow);
    return {
      property: {
        homeValue: Math.max(0, num(p.homeValue)),
        mortgageBalance: Math.max(0, num(p.mortgageBalance)),
        maxCltv: Math.min(100, Math.max(0, num(p.maxCltv, 85))),
      },
      heloc: {
        rate: Math.max(0, num(h.rate)),
        drawYears: Math.max(1, num(h.drawYears, 10)),
        repayYears: Math.max(1, num(h.repayYears, 20)),
        closingCosts: Math.max(0, num(h.closingCosts)),
        annualFee: Math.max(0, num(h.annualFee)),
        rollClosingCosts: h.rollClosingCosts !== false,
      },
      cashflow: {
        netIncome: Math.max(0, num(c.netIncome)),
        // Kept under its original key so existing saved plans keep working.
        // It now means "spending not itemized as a bill below".
        livingExpenses: Math.max(0, num(c.livingExpenses)),
        mortgagePayment: Math.max(0, num(c.mortgagePayment)),
        // How often pay lands matters: sweep interest is charged daily.
        payFrequency: (c.payFrequency === 'weekly' || c.payFrequency === 'semimonthly')
          ? c.payFrequency : 'monthly',
      },
      debts: rows.filter(function (r) { return r.kind === 'debt' && r.balance > 0; }),
      bills: rows.filter(function (r) { return r.kind === 'bill'; }),
    };
  }

  /**
   * Decide what the equity draw actually pays off.
   *
   * Only debts costing more than the line are worth moving, highest rate
   * first, and only as far as the available equity reaches. Whatever capacity
   * is left over makes a partial dent in the next debt down.
   */
  function buildDraw(input, usableEquity) {
    var rate = input.heloc.rate;
    // include: null/undefined both mean "follow the rate rule"; true/false are
    // explicit overrides from the user.
    var candidates = input.debts.filter(function (d) {
      return d.include == null ? d.apr > rate : !!d.include;
    }).sort(function (a, b) { return b.apr - a.apr; });

    var costs = input.heloc.rollClosingCosts ? input.heloc.closingCosts : 0;
    var capacity = Math.max(0, usableEquity - costs);

    var consolidated = [];
    var partial = null;
    var drawn = 0;

    for (var i = 0; i < candidates.length; i++) {
      var d = candidates[i];
      if (d.balance <= capacity - drawn + 0.005) {
        consolidated.push(d);
        drawn += d.balance;
      } else {
        var room = capacity - drawn;
        if (room > 1) {
          partial = { debt: d, amount: room };
          drawn += room;
        }
        break;
      }
    }

    return {
      consolidated: consolidated,
      partial: partial,
      drawn: drawn,
      helocBalance: drawn + costs,
      closingCostsFinanced: costs,
      skipped: input.debts.filter(function (d) {
        return consolidated.indexOf(d) === -1 && (!partial || partial.debt !== d);
      }),
    };
  }

  /** Accounts as they stand today, before any equity draw. */
  function currentAccounts(input) {
    return input.debts.map(function (d) {
      return { id: d.id, name: d.name, balance: d.balance, apr: d.apr, minimum: d.minimum, kind: 'debt' };
    });
  }

  /** Accounts after the draw: survivors, plus the line that replaced the rest. */
  function consolidatedAccounts(input, draw) {
    var out = [];
    input.debts.forEach(function (d) {
      var gone = draw.consolidated.indexOf(d) !== -1;
      if (gone) return;
      var balance = d.balance;
      if (draw.partial && draw.partial.debt === d) balance = Math.max(0, balance - draw.partial.amount);
      if (balance <= 0.005) return;
      out.push({ id: d.id, name: d.name, balance: balance, apr: d.apr, minimum: Math.min(d.minimum, balance), kind: 'debt' });
    });
    if (draw.helocBalance > 0.005) {
      out.push({
        id: 'heloc', name: 'Home equity line', balance: draw.helocBalance,
        apr: input.heloc.rate, minimum: 0, kind: 'heloc',
      });
    }
    return out;
  }

  function calculate(raw) {
    var input = normalize(raw);
    var h = input.heloc;

    var usableEquity = Math.max(0,
      (input.property.homeValue * input.property.maxCltv / 100) - input.property.mortgageBalance);

    var billsTotal = input.bills.reduce(function (s, b) { return s + b.minimum; }, 0);
    var otherSpending = input.cashflow.livingExpenses;
    var totalExpenses = billsTotal + otherSpending;

    var totalDebt = input.debts.reduce(function (s, d) { return s + d.balance; }, 0);
    var totalMinimums = input.debts.reduce(function (s, d) { return s + d.minimum; }, 0);
    var weightedApr = totalDebt > 0
      ? input.debts.reduce(function (s, d) { return s + d.balance * d.apr; }, 0) / totalDebt
      : 0;

    // Everything available for debt service once the roof and the groceries
    // are paid for.
    var debtBudget = input.cashflow.netIncome - totalExpenses - input.cashflow.mortgagePayment;
    var surplus = debtBudget - totalMinimums;

    // When the minimums exceed what the budget leaves, EVERY plan needs the
    // same top-up to be achievable. Applying it uniformly keeps the scenarios
    // comparable; the shortfall is reported separately so it cannot hide.
    // Only ever bridges the gap between a workable budget and the minimums.
    // If the budget is already negative — income short of the mortgage and
    // living costs — there is nothing to bridge, and inventing income would
    // hide the actual problem.
    var requiredTopUp = debtBudget < 0 ? 0 : Math.max(0, totalMinimums - debtBudget);
    var planBudget = debtBudget + requiredTopUp;

    var draw = buildDraw(input, usableEquity);
    var before = currentAccounts(input);
    var after = consolidatedAccounts(input, draw);

    // Cash flow: what leaves the account every month, before and after.
    var helocInterestOnly = draw.helocBalance * (h.rate / 100 / 12);
    var survivingMinimums = after
      .filter(function (a) { return a.kind === 'debt'; })
      .reduce(function (s, a) { return s + a.minimum; }, 0);
    var afterMinimums = survivingMinimums + helocInterestOnly;

    var simOpts = {
      helocDrawYears: h.drawYears,
      helocRepayYears: h.repayYears,
      helocAnnualFee: h.annualFee,
    };
    var withCosts = function (result) {
      if (!h.rollClosingCosts) result.totalCost += h.closingCosts;
      return result;
    };

    var scenarios = {
      minimums: simulate(before, Object.assign({ budget: totalMinimums, applyExtra: false }, simOpts)),
      avalanche: simulate(before, Object.assign({ budget: planBudget, applyExtra: true }, simOpts)),
      coast: withCosts(simulate(after, Object.assign({ budget: afterMinimums, applyExtra: false }, simOpts))),
      attack: withCosts(simulate(after, Object.assign({ budget: planBudget, applyExtra: true }, simOpts))),
      sweep: withCosts(simulateSweep(input, draw, after.filter(function (a) { return a.kind === 'debt'; }), requiredTopUp)),
    };

    // Cash flow: what leaves the account every month, before and after.
    var cashflow = {
      debtBudget: debtBudget,
      surplus: surplus,
      requiredBefore: totalMinimums,
      requiredAfter: afterMinimums,
      freed: totalMinimums - afterMinimums,
      helocInterestOnly: helocInterestOnly,
      // Can the household actually cover today's minimums out of its budget?
      canMeetMinimums: debtBudget >= totalMinimums - 0.005,
      shortfall: Math.max(0, totalMinimums - debtBudget),
      // And can it cover them after consolidating?
      canMeetAfter: debtBudget >= afterMinimums - 0.005,
      billsTotal: billsTotal,
      otherSpending: otherSpending,
      totalExpenses: totalExpenses,
      requiredTopUp: requiredTopUp,
      planBudget: planBudget,
    };

    var comparison = {
      // The honest one: same discipline, with the line versus without it.
      interestSavedVsAvalanche: scenarios.avalanche.totalCost - scenarios.attack.totalCost,
      monthsSavedVsAvalanche: scenarios.avalanche.months - scenarios.attack.months,
      // The flattering one a pitch would quote.
      interestSavedVsMinimums: scenarios.minimums.totalCost - scenarios.attack.totalCost,
      monthsSavedVsMinimums: scenarios.minimums.months - scenarios.attack.months,
      // What discipline alone is worth, with the line already in place.
      costOfCoasting: scenarios.coast.totalCost - scenarios.attack.totalCost,
      monthsOfCoasting: scenarios.coast.months - scenarios.attack.months,
      // What the SWEEP itself adds, over paying the same money monthly. This
      // is the float, isolated — usually small, and the honest way to judge
      // whether routing every paycheck through the line is worth the hassle.
      sweepGainVsAttack: scenarios.attack.totalCost - scenarios.sweep.totalCost,
      sweepMonthsVsAttack: scenarios.attack.months - scenarios.sweep.months,
      sweepGainVsAvalanche: scenarios.avalanche.totalCost - scenarios.sweep.totalCost,
    };

    return {
      input: input,
      equity: {
        homeValue: input.property.homeValue,
        mortgageBalance: input.property.mortgageBalance,
        maxCltv: input.property.maxCltv,
        lendableTotal: input.property.homeValue * input.property.maxCltv / 100,
        usable: usableEquity,
        currentLtv: input.property.homeValue > 0
          ? (input.property.mortgageBalance / input.property.homeValue) * 100 : 0,
        afterLtv: input.property.homeValue > 0
          ? ((input.property.mortgageBalance + draw.helocBalance) / input.property.homeValue) * 100 : 0,
      },
      debtSummary: {
        totalDebt: totalDebt,
        totalMinimums: totalMinimums,
        weightedApr: weightedApr,
        count: input.debts.length,
      },
      draw: draw,
      cashflow: cashflow,
      expenses: {
        bills: billsTotal,
        other: otherSpending,
        total: totalExpenses,
        billCount: input.bills.length,
        mortgage: input.cashflow.mortgagePayment,
      },
      scenarios: scenarios,
      comparison: comparison,
      warnings: buildWarnings(input, usableEquity, draw, cashflow, scenarios),
    };
  }

  /** The things that matter more than the headline number. */
  function buildWarnings(input, usableEquity, draw, cashflow, scenarios) {
    var w = [];
    var h = input.heloc;

    if (!input.debts.length || input.cashflow.netIncome <= 0) {
      w.push({ level: 'info', key: 'setup', text: 'Add your debts and your take-home pay to see a real plan.' });
      return w;
    }

    var unsecured = draw.consolidated.filter(function (d) {
      return d.type === 'card' || d.type === 'personal' || d.type === 'medical' || d.type === 'student';
    });
    if (unsecured.length) {
      var amount = unsecured.reduce(function (s, d) { return s + d.balance; }, 0);
      w.push({
        level: 'danger', key: 'secured',
        text: 'This plan moves ' + money(amount) + ' of unsecured debt onto your house. A credit card ' +
          'company can sue you; a home equity lender can foreclose. That is the real price of the lower rate, ' +
          'and no calculator can put a number on it.',
      });
    }

    if (draw.consolidated.some(function (d) { return d.type === 'card'; })) {
      w.push({
        level: 'warn', key: 'reaccumulate',
        text: 'The most common way this plan fails: the cards get paid off, then filled back up. ' +
          'Now you owe the old balances and the equity line. Close or freeze the accounts as part of the plan.',
      });
    }

    if (usableEquity <= 0) {
      w.push({
        level: 'danger', key: 'noequity',
        text: 'At ' + input.property.maxCltv + '% combined loan-to-value there is no equity to draw on. ' +
          'Lenders size the line off your home value and your mortgage balance.',
      });
    } else if (draw.partial || draw.skipped.some(function (d) { return d.apr > h.rate; })) {
      w.push({
        level: 'warn', key: 'partial',
        text: 'Your equity does not stretch to every debt worth moving. The plan below consolidates the ' +
          'most expensive ones first and leaves the rest in place.',
      });
    }

    if (cashflow.debtBudget <= 0) {
      w.push({
        level: 'danger', key: 'nobudget',
        text: 'After your mortgage and living costs, there is nothing left for debt payments. Consolidating ' +
          'lowers the monthly minimum but does not fix a budget that is already underwater.',
      });
    } else if (!cashflow.canMeetMinimums) {
      w.push({
        level: 'danger', key: 'cantmeet',
        text: 'Your minimum payments come to ' + money(cashflow.requiredBefore) + ' a month but your budget ' +
          'leaves only ' + money(cashflow.debtBudget) + ' — you are ' + money(cashflow.shortfall) +
          ' short every month. ' + (cashflow.canMeetAfter
            ? 'Consolidating would bring the required payment inside your budget, which is a genuine reason ' +
              'to do it — but it treats the symptom, so fix the gap as well.'
            : 'Consolidating does not close that gap either. Talk to a nonprofit credit counselor before ' +
              'borrowing against your house.'),
      });
    }

    if (cashflow.surplus <= 0 && cashflow.debtBudget > 0) {
      w.push({
        level: 'warn', key: 'nosurplus',
        text: 'You have no surplus above the minimums today, so the whole plan rests on the cash flow the ' +
          'consolidation frees up. If that money gets spent, look at the "then coast" row.',
      });
    }

    var costlier = draw.consolidated.filter(function (d) { return d.apr <= h.rate; });
    if (costlier.length) {
      w.push({
        level: 'warn', key: 'cheaper',
        text: costlier.length + ' debt' + (costlier.length > 1 ? 's are' : ' is') + ' already at or below the ' +
          'line\'s rate. Moving ' + (costlier.length > 1 ? 'them' : 'it') + ' onto your house costs you money ' +
          'and adds risk.',
      });
    }

    if (!scenarios.attack.paidOff) {
      w.push({
        level: 'danger', key: 'nopayoff',
        text: 'Even applying every available dollar, the balances never clear. The gap is too wide to ' +
          'refinance your way out of.',
      });
    }

    var afterLtv = input.property.homeValue > 0
      ? ((input.property.mortgageBalance + draw.helocBalance) / input.property.homeValue) * 100 : 0;
    if (afterLtv > 80 && draw.helocBalance > 0) {
      w.push({
        level: 'warn', key: 'ltv',
        text: 'You would owe ' + Math.round(afterLtv) + '% of what the house is worth. If values fall you ' +
          'could end up underwater, unable to sell or refinance without bringing cash.',
      });
    }

    if (cashflow.billsTotal > 0 && input.cashflow.livingExpenses > 0) {
      w.push({
        level: 'info', key: 'doublecount',
        text: 'Check that the ' + money(cashflow.billsTotal) + ' of bills listed below is not also sitting ' +
          'inside your "everything else" figure. Counted twice, your budget looks tighter than it is.',
      });
    }

    if (draw.helocBalance > 0 && scenarios.sweep.infeasible) {
      w.push({
        level: 'danger', key: 'sweepnegative',
        text: 'Sweep mode cannot work here: your monthly outgoings are more than your take-home pay, ' +
          'so routing everything through the line makes the balance grow rather than shrink.',
      });
    }

    if (draw.helocBalance > 0 && scenarios.sweep.drawEndBalance > 0) {
      w.push({
        level: 'warn', key: 'sweepdrawend',
        text: 'Sweeping does not clear the line before the ' + input.heloc.drawYears +
          '-year draw period ends. After that you cannot draw from it any more, so the account stops ' +
          'working as your checking account and the balance has to be amortized.',
      });
    }

    if (draw.helocBalance > 0) {
      w.push({
        level: 'info', key: 'variable',
        text: 'A home equity line is usually variable-rate. Your payment can rise for as long as you owe, ' +
          'and the interest-only draw period ends after ' + h.drawYears + ' years — at which point the ' +
          'balance has to start amortizing.',
      });
    }

    return w;
  }

  var api = {
    calculate: calculate,
    normalize: normalize,
    simulate: simulate,
    simulateSweep: simulateSweep,
    buildDraw: buildDraw,
    monthlyPayment: monthlyPayment,
    MAX_MONTHS: MAX_MONTHS,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.EquityPlan = api;
})(typeof window !== 'undefined' ? window : null);
