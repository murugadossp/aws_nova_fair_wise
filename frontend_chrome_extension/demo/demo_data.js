/**
 * FareWise — Demo / Hackathon Presentation Mode
 *
 * This file is NOT loaded by the production extension.
 * It contains pre-baked search results for offline demos when the
 * backend (uvicorn main:app) is not running.
 *
 * To use for a demo:
 *   1. In sidepanel.html add this script tag BEFORE the closing </body>:
 *        <script src="../demo/demo_data.js"></script>
 *   2. In startProductSearch() replace:
 *        showBackendError(...)
 *      with:
 *        runDemoProductSearch(query)
 *   3. Remove the script tag before shipping.
 *
 * ──────────────────────────────────────────────────────────────────────
 * These functions mirror the real handlers but use hardcoded data.
 * Keep them in sync with renderProductCard / renderFlightCard signatures.
 */

'use strict';

// ── Products demo ──────────────────────────────────────────────────────────────

function runDemoProductSearch(query) {
  const productName = query || 'Sony WH-1000XM5 Wireless Headphones';
  showIdentification(productName, 'high', 96);
  setStatus('connected', 'Searching platforms… [DEMO]');
  showProductProgress();

  // Amazon completes first (~1.2s)
  animateProgress('prog-amazon', 'status-amazon', 1200, () => {
    renderProductCard({
      platform:    'Amazon India',
      color:       'var(--amazon)',
      price:       21242,
      base:        24990,
      card:        'HDFC Regalia',
      discount:    15,
      discountAmt: 3748,
      delivery:    0,
      days:        2,
      url:         'https://www.amazon.in',
      winner:      true,
      cashback:    null,
      seller:      'Amazon Cloudtail',
    }, 0);
  });

  // Flipkart completes second (~2.2s)
  animateProgress('prog-flipkart', 'status-flipkart', 2200, () => {
    renderProductCard({
      platform:    'Flipkart',
      color:       'var(--flipkart)',
      price:       22991,
      base:        26490,
      card:        'Axis Flipkart',
      discount:    13,
      discountAmt: 3444,
      delivery:    0,
      days:        3,
      url:         'https://www.flipkart.com',
      winner:      false,
      cashback:    '₹400 SuperCoin in 30d',
      seller:      'Flipkart Assured',
    }, 1);

    setTimeout(() => {
      showSavings('products', 5748);
      showReasoningText('products',
        'Amazon wins with HDFC Regalia giving 15% instant discount (₹3,748 off ₹24,990), ' +
        'compared to Axis Flipkart at 13% (₹3,444 off ₹26,490). ' +
        'Effective saving over Flipkart is ₹1,749. [DEMO DATA]');
      setStatus('connected', 'Done · 2 results [DEMO]');
    }, 300);
  });
}

// ── Travel demo ────────────────────────────────────────────────────────────────

function runDemoTravelSearch(from, to, date) {
  const ROUTES = {
    'BOM-DEL': { flight: 'IndiGo 6E-204',   dep: '07:20', arr: '09:55', dur: '2h 35m' },
    'DEL-BOM': { flight: 'IndiGo 6E-501',   dep: '10:15', arr: '12:45', dur: '2h 30m' },
    'BOM-BLR': { flight: 'Air India AI-657', dep: '08:00', arr: '09:45', dur: '1h 45m' },
    'BLR-DEL': { flight: 'IndiGo 6E-2082',  dep: '06:30', arr: '09:30', dur: '3h 00m' },
  };
  const key = `${from}-${to}`;
  const ri  = ROUTES[key] || { flight: 'IndiGo 6E-100', dep: '08:00', arr: '10:30', dur: '2h 30m' };

  // MakeMyTrip (~1.5s)
  animateProgress('prog-mmt', 'status-mmt', 1500, () => {
    renderFlightCard({
      platform: 'MakeMyTrip', color: 'var(--mmt)',
      price: 5891, base: 5891, card: 'HDFC Regalia',
      discount: 8, discountAmt: 471, convFee: 0,
      ...ri, url: 'https://www.makemytrip.com', winner: false,
    }, 0);
  });

  // Goibibo — cheapest (~2.1s)
  animateProgress('prog-goibibo', 'status-goibibo', 2100, () => {
    renderFlightCard({
      platform: 'Goibibo', color: 'var(--goibibo)',
      price: 4201, base: 4890, card: 'SBI SimplyCLICK',
      discount: 14, discountAmt: 684, convFee: 5,
      ...ri, url: 'https://www.goibibo.com', winner: true,
    }, 1);
  });

  // Cleartrip (~2.8s)
  animateProgress('prog-cleartrip', 'status-cleartrip', 2800, () => {
    renderFlightCard({
      platform: 'Cleartrip', color: 'var(--cleartrip)',
      price: 4680, base: 5102, card: 'HDFC Regalia',
      discount: 8, discountAmt: 408, convFee: 14,
      ...ri, url: 'https://www.cleartrip.com', winner: false,
    }, 2);

    setTimeout(() => {
      showSavings('travel', 4201);
      showReasoningText('travel',
        'Goibibo offers the cheapest fare at ₹4,201 after SBI SimplyCLICK 14% discount. ' +
        'MakeMyTrip is ₹1,690 more expensive. Cleartrip is ₹479 more after HDFC Regalia discount. [DEMO DATA]');
      setStatus('connected', 'Done · 3 OTAs searched [DEMO]');
    }, 300);
  });
}
