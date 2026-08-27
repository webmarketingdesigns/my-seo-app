/* 1st Lien HELOC calculator — form wiring, results, chart. */
(function () {
  'use strict';

  var FIELDS = ['mortgageBalance', 'mortgageRate', 'mortgageYears', 'mortgagePayment',
    'helocLimit', 'helocRate', 'drawYears', 'repayYears', 'closingCosts', 'annualFee',
    'netIncome', 'monthlyExpenses', 'payFrequency', 'rollClosingCosts'];

  var $ = function (id) { return document.getElementById(id); };

  /* ── Formatting ── */

  function money(n) {
    if (!isFinite(n)) return '—';
    return (n < 0 ? '-$' : '$') + Math.round(Math.abs(n)).toLocaleString('en-US');
  }

  function term(months, paidOff) {
    if (!paidOff) return 'Never';
    var y = Math.floor(months / 12);
    var m = months % 12;
    if (y === 0) return m + ' mo';
    return y + ' yr' + (m ? ' ' + m + ' mo' : '');
  }

  function spanOfMonths(months) {
    var y = Math.floor(Math.abs(months) / 12);
    var m = Math.abs(months) % 12;
    var parts = [];
    if (y) parts.push(y + ' year' + (y === 1 ? '' : 's'));
    if (m) parts.push(m + ' month' + (m === 1 ? '' : 's'));
    return parts.join(' ') || '0 months';
  }

  /* ── Read the form ── */

  function readForm() {
    return {
      mortgageBalance: $('mortgageBalance').value,
      mortgageRate: $('mortgageRate').value,
      mortgageTermMonths: Math.round(parseFloat($('mortgageYears').value || 0) * 12),
      mortgagePaymentOverride: $('mortgagePayment').value,
      helocLimit: $('helocLimit').value,
      helocRate: $('helocRate').value,
      drawPeriodYears: $('drawYears').value,
      repayPeriodYears: $('repayYears').value,
      closingCosts: $('closingCosts').value,
      annualFee: $('annualFee').value,
      netMonthlyIncome: $('netIncome').value,
      monthlyExpenses: $('monthlyExpenses').value,
      payFrequency: $('payFrequency').value,
      rollClosingCosts: $('rollClosingCosts').checked,
    };
  }

  /* ── Render ── */

  function render(r) {
    var c = r.comparison;
    var wins = r.heloc.paidOff && c.savedVsExtra > 0;

    // Verdict — judged against the fair comparison, not the straw man.
    var verdict = $('verdict');
    var incomplete = r.input.mortgageBalance <= 0 || r.input.netMonthlyIncome <= 0;
    verdict.className = 'verdict ' + (incomplete ? 'neutral' : !r.heloc.paidOff ? 'bad' : wins ? 'good' : 'mixed');
    if (incomplete) {
      verdict.innerHTML = '<div class="verdict-head">Fill in your numbers above</div>' +
        '<p>Enter your mortgage balance and your take-home pay, and the comparison below updates as you type.</p>';
    } else if (!r.heloc.paidOff) {
      verdict.innerHTML = '<div class="verdict-head">This doesn\'t work at these numbers</div>' +
        '<p>The balance never gets paid off — interest keeps pace with what you deposit. ' +
        'Check the flags below.</p>';
    } else if (wins) {
      verdict.innerHTML = '<div class="verdict-head">The HELOC comes out ahead by ' + money(c.savedVsExtra) + '</div>' +
        '<p>Compared with keeping your mortgage <em>and</em> paying the same ' + money(c.surplusVsMortgage) +
        '/mo surplus toward principal. That is the fair comparison, and it accounts for closing costs and fees. ' +
        'It assumes the rate never rises — see the stress table.</p>';
    } else {
      // The HELOC can lose to the fair baseline and still beat the minimum-payment
      // mortgage — or, with weak cash flow, lose to both. Say which.
      var vsMinimum = c.savedVsMortgage > 0
        ? 'The HELOC does beat making only the minimum mortgage payment — by ' + money(c.savedVsMortgage) +
          ' — but that is because you\'d be putting ' + money(c.surplusVsMortgage) +
          '/mo of surplus toward the balance.'
        : 'It costs ' + money(-c.savedVsMortgage) + ' more than even making only the minimum mortgage ' +
          'payment, because the higher variable rate outruns what you can put in.';
      verdict.innerHTML = '<div class="verdict-head">Paying your own mortgage down wins by ' + money(-c.savedVsExtra) + '</div>' +
        '<p>' + vsMinimum + ' Send that same money to your existing mortgage and you finish ' +
        spanOfMonths(c.monthsSavedVsExtra * -1) + ' sooner at a lower cost, with a fixed rate.</p>';
    }

    // Warnings
    $('warnings').innerHTML = r.warnings.map(function (w) {
      return '<div class="warn-item ' + w.level + '">' + w.text + '</div>';
    }).join('');

    // Scenario cards
    fillCard('cardMortgage', term(r.mortgage.months, r.mortgage.paidOff),
      money(r.mortgage.totalCost), money(r.mortgage.payment) + '/mo');
    fillCard('cardExtra', term(r.mortgageExtra.months, r.mortgageExtra.paidOff),
      money(r.mortgageExtra.totalCost),
      money(r.mortgageExtra.payment + r.mortgageExtra.extraPerMonth) + '/mo');
    fillCard('cardHeloc', term(r.heloc.months, r.heloc.paidOff),
      r.heloc.paidOff ? money(r.heloc.totalCost) : '—', money(c.netCashFlow) + '/mo');

    // Where the savings actually come from
    if (!r.heloc.paidOff) {
      $('attribution').innerHTML = '<h3>Where the difference actually comes from</h3>' +
        '<p class="attr-note">There is no lifetime saving to split up: at these numbers the line never ' +
        'pays off. Paying ' + money(Math.max(0, c.surplusVsMortgage)) + '/mo of surplus straight at your ' +
        'mortgage would still retire it in ' + term(r.mortgageExtra.months, r.mortgageExtra.paidOff) + '.</p>';
    } else {
    $('attribution').innerHTML =
      '<h3>Where the difference actually comes from</h3>' +
      '<div class="attr-rows">' +
      attrRow('Paying extra toward principal', c.fromPayingExtra,
        'You could do this today, with no new loan and no variable rate.') +
      attrRow('The HELOC structure itself', c.savedVsExtra,
        'The daily-interest float from parking your paycheck, minus the higher rate, closing costs and fees.') +
      '</div>' +
      '<p class="attr-note">A sales pitch quoting <strong>' + money(c.savedVsMortgage) +
      '</strong> in savings is adding these two together. Only the second row is something the HELOC gives you.</p>';
    }

    // Stress table
    $('stressBody').innerHTML = r.stress.map(function (s) {
      var good = s.savedVsExtra > 0;
      return '<tr' + (s.bump === 0 ? ' class="current"' : '') + '>' +
        '<td>' + s.rate.toFixed(2) + '%' + (s.bump ? ' <span class="bump">(+' + s.bump + ')</span>' :
          ' <span class="bump">today</span>') + '</td>' +
        '<td>' + term(s.months, s.paidOff) + '</td>' +
        '<td>' + (s.paidOff ? money(s.totalCost) : '—') + '</td>' +
        '<td class="' + (good ? 'pos' : 'neg') + '">' +
        (s.paidOff ? (good ? '+' : '−') + money(Math.abs(s.savedVsExtra)) : 'never pays off') + '</td>' +
        '</tr>';
    }).join('');

    // Break-even rate
    var be = $('breakeven');
    if (c.breakEvenRate == null) {
      be.className = 'breakeven neg';
      be.innerHTML = 'At <strong>no rate at all</strong> does this HELOC beat paying the same surplus toward ' +
        'your mortgage — the closing costs and fees alone outweigh the float advantage.';
    } else {
      var margin = c.breakEvenRate - r.input.helocRate;
      be.className = 'breakeven ' + (margin > 0 ? 'pos' : 'neg');
      be.innerHTML = '<strong>Break-even rate: ' + c.breakEvenRate.toFixed(2) + '%.</strong> ' +
        'Above that, the HELOC costs more than simply paying the surplus toward your mortgage. ' +
        (margin > 0
          ? 'Your rate is ' + Math.abs(margin).toFixed(2) + ' points below it — that is your whole cushion against rate increases.'
          : 'Your rate is already ' + Math.abs(margin).toFixed(2) + ' points above it.');
    }

    // Month-by-month detail
    $('amortBody').innerHTML = r.heloc.rows.slice(0, 60).map(function (row) {
      return '<tr' + (row.phase === 'repay' ? ' class="repay"' : '') + '>' +
        '<td>' + row.month + '</td>' +
        '<td>' + money(row.opening) + '</td>' +
        '<td class="pos">' + money(row.deposits) + '</td>' +
        '<td>' + money(row.draws) + '</td>' +
        '<td class="neg">' + money(row.interest) + '</td>' +
        '<td>' + money(row.closing) + '</td>' +
        '</tr>';
    }).join('');

    drawChart(r);
  }

  function fillCard(id, termText, interestText, paymentText) {
    var el = $(id);
    el.querySelector('[data-field="term"]').textContent = termText;
    el.querySelector('[data-field="interest"]').textContent = interestText;
    el.querySelector('[data-field="payment"]').textContent = paymentText;
  }

  function attrRow(label, amount, note) {
    var sign = amount >= 0 ? 'pos' : 'neg';
    return '<div class="attr-row">' +
      '<div class="attr-label">' + label + '<span class="attr-note-inline">' + note + '</span></div>' +
      '<div class="attr-amount ' + sign + '">' + (amount >= 0 ? '' : '−') + money(Math.abs(amount)) + '</div>' +
      '</div>';
  }

  /* ── Chart: balance over time, drawn as inline SVG ── */

  function drawChart(r) {
    var series = [
      { cls: 's-mortgage', data: r.mortgage.balances },
      { cls: 's-extra', data: r.mortgageExtra.balances },
      { cls: 's-heloc', data: r.heloc.balances },
    ];

    var maxMonths = Math.max.apply(null, series.map(function (s) { return s.data.length; }));
    var maxBal = Math.max.apply(null, series.map(function (s) {
      return Math.max.apply(null, s.data);
    }));
    if (!isFinite(maxMonths) || !isFinite(maxBal) || maxBal <= 0) {
      $('chart').innerHTML = '';
      return;
    }

    var W = 900, H = 320, padL = 62, padR = 14, padT = 14, padB = 34;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var x = function (m) { return padL + (m / Math.max(1, maxMonths - 1)) * plotW; };
    var y = function (b) { return padT + plotH - (b / maxBal) * plotH; };

    var parts = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Loan balance over time for each scenario">'];

    // Horizontal gridlines with dollar labels
    for (var i = 0; i <= 4; i++) {
      var val = (maxBal / 4) * i;
      var gy = y(val);
      parts.push('<line class="grid" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" />');
      parts.push('<text class="axis" x="' + (padL - 8) + '" y="' + (gy + 4) + '" text-anchor="end">' +
        '$' + Math.round(val / 1000) + 'k</text>');
    }

    // Year labels along the bottom
    var yearStep = maxMonths > 240 ? 60 : maxMonths > 120 ? 24 : 12;
    for (var m = 0; m < maxMonths; m += yearStep) {
      parts.push('<text class="axis" x="' + x(m) + '" y="' + (H - 10) + '" text-anchor="middle">' +
        (m / 12) + 'y</text>');
    }

    // The draw-period boundary is where the HELOC's rules change
    var drawEnd = r.heloc.drawMonths;
    if (drawEnd < maxMonths) {
      parts.push('<line class="draw-line" x1="' + x(drawEnd) + '" y1="' + padT + '" x2="' + x(drawEnd) +
        '" y2="' + (padT + plotH) + '" />');
      parts.push('<text class="axis draw-label" x="' + (x(drawEnd) + 6) + '" y="' + (padT + 12) + '">draw period ends</text>');
    }

    series.forEach(function (s) {
      var pts = s.data.map(function (b, idx) { return x(idx) + ',' + y(Math.max(0, b)); }).join(' ');
      parts.push('<polyline class="line ' + s.cls + '" points="' + pts + '" />');
    });

    parts.push('</svg>');
    $('chart').innerHTML = parts.join('');
  }

  /* ── Wire up ── */

  function recalc() {
    render(window.HelocCalc.calculate(readForm()));
  }

  FIELDS.forEach(function (id) {
    var el = $(id);
    if (el) el.addEventListener('input', recalc);
    if (el) el.addEventListener('change', recalc);
  });

  $('helocForm').addEventListener('submit', function (e) { e.preventDefault(); recalc(); });

  recalc();
})();
