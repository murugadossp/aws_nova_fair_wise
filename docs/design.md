# FareWise — Design Document
> Brand Identity · UI System · Component Library · Screen Designs

**Version:** 1.1 (updated March 2026 — post-implementation)
**Design Direction:** Dark Precision Fintech — "Bloomberg meets CRED, built for India"

---

## 1. Design Philosophy

### Core Principle: "One Truth, Instantly"
Every screen must communicate the single most important number — the true cheapest price — within 1 second of seeing it. The user may be in a noisy store, on a moving train, or casually scrolling WhatsApp. Design for distraction.

### Three Design Laws
1. **One winner, always** — never make the user compare equals. There is always a gold-bordered winner.
2. **Prices are bigger than everything** — the true price in large type, the platform second, the explanation third.
3. **Progressive revelation** — show the first result the moment it arrives, not after all results are ready.

### The India Design Standard
- ₹ symbol is always present (not "Rs" or "INR")
- Bank card names in their actual marketing style: "HDFC Regalia", not just "HDFC"
- "Book" not "Purchase" (travel context); "Buy" not "Checkout" (products)
- Dates in Indian format when needed: "15 Mar" not "Mar 15"
- EMI framing: always show "₹3,416/mo for 24 months" alongside lump sum

---

## 2. Brand Identity

### Name & Mark
```
Product Name:  FareWise
Tagline:       "See the real price. Every time."
Sub-tagline:   "Gadgets. Flights. With your bank card offer."

Logo Icon:     A compass needle (▶) pointing to a price tag (₹)
               Represents: always finding the right direction to the best price
               The needle doubles as a ">" which implies "better than"

Logo Wordmark: FARE in Bricolage Grotesque 800 weight, WISE in Bricolage Grotesque 400 weight (web app)
               Syne 700/800 used in Extension/PWA (matches compact UI)
               The contrast in weight signals: "price" (bold) + "intelligence" (precise)
```

### Brand Voice
- **Authoritative, not arrogant** — "Amazon wins by ₹3,748" not "We found the best price ever!"
- **Specific, not vague** — always cite numbers: "₹4,499 cheaper" not "much cheaper"
- **India-smart** — knows that "convenience fee" is a scam, cashback is delayed, and EMI can be no-cost
- **Friend, not feature** — sounds like a financially knowledgeable friend giving advice in 2 sentences

### Tagline Variants
- Hero (large): *"See the real price. Every time."*
- Products context: *"Any gadget. Cheapest price. With your card."*
- Travel context: *"Any flight. Cheapest fare. With your card."*
- Savings moment: *"You just saved ₹5,748."* (full stop. nothing else needed)

---

## 3. Color System

### Foundation — Dark Canvas
```css
:root {
  /* Backgrounds */
  --bg-base:      #070711;   /* Deep space — primary background, extension panel */
  --bg-surface:   #0F0F1E;   /* Cards, panels, elevated surfaces */
  --bg-elevated:  #161630;   /* Active states, hover, modals */
  --bg-overlay:   #1E1E40;   /* Tooltips, dropdowns */
  --bg-input:     #0D0D22;   /* Input fields */
}
```

### Brand Colors
```css
  /* Intelligence Blue — primary accent */
  --blue:           #4F8EF7;
  --blue-dim:       #3A6DD4;
  --blue-glow:      rgba(79, 142, 247, 0.15);
  --blue-border:    rgba(79, 142, 247, 0.25);

  /* Winner Gold — best deal, success, celebration */
  --gold:           #F5A623;
  --gold-dim:       #D4881A;
  --gold-glow:      rgba(245, 166, 35, 0.12);
  --gold-border:    rgba(245, 166, 35, 0.35);
```

### Semantic Colors
```css
  /* Savings Green */
  --green:          #2ED47A;
  --green-glow:     rgba(46, 212, 122, 0.10);
  --green-border:   rgba(46, 212, 122, 0.20);

  /* Cashback Yellow (delayed value — use with ⏱ icon) */
  --yellow:         #FFD166;
  --yellow-glow:    rgba(255, 209, 102, 0.10);

  /* Worst Price Red */
  --red:            #FF5F5F;
  --red-glow:       rgba(255, 95, 95, 0.08);

  /* Neutral */
  --white:          #F0F0FF;
  --text-primary:   #EEEEFF;   /* Prices, headings, primary content */
  --text-secondary: #8B8FA8;   /* Labels, descriptions */
  --text-muted:     #4A4D6A;   /* Placeholders, disabled, hints */
```

### Platform Brand Colors
```css
  /* Products Mode */
  --amazon:         #FF9900;   /* Amazon India */
  --flipkart:       #2874F0;   /* Flipkart */

  /* Travel Mode */
  --makemytrip:     #D42B2B;   /* MakeMyTrip */
  --goibibo:        #E8390E;   /* Goibibo */
  --cleartrip:      #E87722;   /* Cleartrip */

  /* Airlines (commonly shown) */
  --indigo:         #1A1F71;
  --airasia:        #FF0000;
  --spicejet:       #FF4B00;
  --vistara:        #4B0082;
  --airindia:       #8B0000;
```

### Mode Accent Colors
```css
  /* Products Mode accent: softer blue-violet */
  --mode-products:  #6B8EF7;

  /* Travel Mode accent: sky cyan */
  --mode-travel:    #00C4CC;
```

---

## 4. Typography

> **Note:** Two distinct font systems are used across surfaces. The Extension/PWA uses Syne + DM Sans (compact, UI-focused). The Web App was redesigned with Bricolage Grotesque + Instrument Sans for a more editorial, distinctive marketing feel.

### 4A. Extension + Mobile PWA Font Pairing
```
Display / Prices / CTAs:  "Syne" (Google Fonts)
  — Geometric, modern, distinctively square — unlike any other sans
  — Used for: logo, large prices, winner announcement prices
  — Weights: 700 (prices, CTAs), 800 (logo)
  — Import: @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800')

Body / Labels / UI copy:  "DM Sans" (Google Fonts)
  — Clean, highly legible at 12–14px, warm personality
  — Used for: all body text, labels, inputs, descriptions, fine print
  — Weights: 400, 500, 600
  — Import: @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600')
```

### 4B. Web App (Marketing Site) Font Pairing ← UPDATED
```
Hero / Section Headings:  "Bricolage Grotesque" (Google Fonts, variable)
  — Expressive variable font released 2023 — editorial, modern, distinctive
  — Variable axes: wdth (75–100), wght (200–800)
  — Used for: nav logo, hero headline, section titles, nav links
  — Headline size: clamp(32px, 3.2vw, 46px) — stays readable at all viewport widths
  — Import: @import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@12..96,75..100,200..800')

Body / UI copy:           "Instrument Sans" (Google Fonts)
  — Humanist sans with excellent small-size legibility, warm at display sizes
  — Used for: all body copy, descriptions, stats, badges, buttons, form labels
  — Weights: 400, 500, 600
  — Import: @import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600')

Why revised from original spec:
  — Original Syne at clamp(38px, 5vw, 62px) on a 518px column produced 4-line
    headline overflow filling the entire hero viewport.
  — Bricolage Grotesque at clamp(32px, 3.2vw, 46px) keeps to 2 lines on all
    viewport sizes while being more editorially distinctive than Syne.
```

### Type Scale
```css
--text-xs:    11px;   /* Fine print, badges, metadata */
--text-sm:    13px;   /* Labels, secondary info, card descriptions */
--text-base:  15px;   /* Primary body text, input fields */
--text-md:    17px;   /* Platform names, card offer labels */
--text-lg:    20px;   /* Secondary prices, section subheads */
--text-xl:    24px;   /* Winner price summary */
--text-2xl:   32px;   /* True price (final number — most prominent) */
--text-3xl:   42px;   /* Hero headline (website) */
--text-4xl:   56px;   /* Hero display price (website demo) */
```

### Spacing System
```css
--space-1:   4px;
--space-2:   8px;
--space-3:   12px;
--space-4:   16px;
--space-5:   20px;
--space-6:   24px;
--space-8:   32px;
--space-10:  40px;
--space-12:  48px;
--space-16:  64px;
```

### Border Radius
```css
--radius-sm:   6px;    /* Badges, small tags */
--radius-md:   10px;   /* Cards, inputs */
--radius-lg:   14px;   /* Main cards, panels */
--radius-xl:   20px;   /* Winner card */
--radius-full: 999px;  /* Pill badges, circular buttons */
```

---

## 5. Component Library

### 5.1 Mode Toggle (Top of Extension Panel)

```
┌──────────────────────────────────────────┐
│  FW  [  📦 Products  ] [  ✈️ Travel  ]  ⚙ │
└──────────────────────────────────────────┘
```

```css
.mode-toggle {
  display: flex;
  background: var(--bg-surface);
  border-radius: var(--radius-full);
  padding: 3px;
  gap: 2px;
}
.mode-tab {
  font-family: 'DM Sans', sans-serif;
  font-size: var(--text-sm);
  font-weight: 600;
  padding: 7px 14px;
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-secondary);
}
.mode-tab.active-products {
  background: var(--blue-glow);
  color: var(--blue);
  border: 1px solid var(--blue-border);
}
.mode-tab.active-travel {
  background: rgba(0, 196, 204, 0.10);
  color: var(--mode-travel);
  border: 1px solid rgba(0, 196, 204, 0.25);
}
```

### 5.2 Search Input Area

**Products Mode:**
```
┌──────────────────────────────────────────┐
│  📋 Paste WhatsApp screenshot            │
│  ─────────── or ───────────              │
│  [ Type or speak a product name...  🎤 ] │
└──────────────────────────────────────────┘
```

**Travel Mode:**
```
┌──────────────────────────────────────────┐
│  🎤 "Mumbai to Delhi, this Friday"       │
│  ─────────── or ───────────              │
│  From: [Mumbai       ▾] To: [Delhi  ▾]  │
│  Date: [15 Mar ▾]  Class: [Economy ▾]   │
└──────────────────────────────────────────┘
```

### 5.3 Platform Result Card

```
┌─────────────────────────────────────────┐ ← gold border if winner
│  🟠 Amazon India        HDFC Regalia    │
│                                          │
│  ₹21,242                                │ ← var(--text-2xl), Syne 700
│  base ₹24,990 − 15% HDFC − ₹0 delivery │ ← var(--text-xs), text-muted
│                                          │
│  ✓ BEST DEAL                [BUY →]    │ ← gold badge + blue button
│  📦 Delivered in 2 days                 │
│  + ₹600 cashback in 45 days (SBI ICICI) │ ← yellow, shows delayed value
└─────────────────────────────────────────┘
```

```css
.platform-card {
  background: var(--bg-surface);
  border: 1px solid var(--bg-elevated);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  transition: border-color 0.3s ease;
}
.platform-card.winner {
  border-color: var(--gold-border);
  background: linear-gradient(135deg, var(--bg-surface) 0%, rgba(245,166,35,0.04) 100%);
  box-shadow: 0 0 20px var(--gold-glow);
}
.price-true {
  font-family: 'Syne', sans-serif;
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}
.price-breakdown {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: 'DM Sans', sans-serif;
}
.winner-badge {
  background: var(--gold-glow);
  border: 1px solid var(--gold-border);
  color: var(--gold);
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--radius-full);
}
```

### 5.4 Savings Banner

```
╔═════════════════════════════════════════╗
║  💰 You save ₹5,748 vs worst option    ║
║     vs WhatsApp price: ₹4,499 cheaper  ║
╚═════════════════════════════════════════╝
```

```css
.savings-banner {
  background: linear-gradient(135deg, rgba(46,212,122,0.08) 0%, rgba(79,142,247,0.05) 100%);
  border: 1px solid var(--green-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  text-align: center;
}
.savings-amount {
  font-family: 'Syne', sans-serif;
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--green);
}
```

### 5.5 Loading / Progress State

```
┌──────────────────────────────────────────┐
│  Searching...                            │
│                                          │
│  🟠 Amazon India        [████████░░] 80% │
│  🔵 Flipkart            [██████░░░░] 60% │
│                                          │
│  Results arrive as agents complete →     │
└──────────────────────────────────────────┘
```

```css
.search-progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.agent-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.progress-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-elevated);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: linear-gradient(90deg, var(--blue) 0%, var(--gold) 100%);
  transition: width 0.4s ease;
}
```

### 5.6 Voice Active State

```
┌──────────────────────────────────────────┐
│            🎤  Listening...              │
│         ●  ●  ●  ●  ●  ●  ●             │ ← animated waveform bars
│    "Mumbai to Delhi, this Friday"        │ ← live transcript
└──────────────────────────────────────────┘
```

```css
.voice-panel {
  text-align: center;
  padding: var(--space-6);
}
.voice-waveform {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  height: 32px;
  margin: var(--space-3) 0;
}
.wave-bar {
  width: 3px;
  background: var(--blue);
  border-radius: var(--radius-full);
  animation: wave 0.8s ease-in-out infinite;
}
.wave-bar:nth-child(2) { animation-delay: 0.1s; }
.wave-bar:nth-child(3) { animation-delay: 0.2s; }
.wave-bar:nth-child(4) { animation-delay: 0.15s; }
.wave-bar:nth-child(5) { animation-delay: 0.05s; }
@keyframes wave {
  0%, 100% { height: 6px; }
  50%       { height: 26px; }
}
```

### 5.7 Confidence Badge

```css
.confidence-badge {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-full);
}
.confidence-high   { color: var(--green);  background: var(--green-glow); }
.confidence-medium { color: var(--yellow); background: var(--yellow-glow); }
.confidence-low    { color: var(--red);    background: var(--red-glow); }
```

---

## 6. Screen Designs

### 6.1 Extension Side Panel — Products Mode

**Screen A: Initial / Idle**
```
┌────────────────────────────────┐
│ FW [📦 Products] [✈️ Travel] ⚙ │
├────────────────────────────────┤
│                                │
│  📋 Paste WhatsApp screenshot  │
│     or drag an image here      │
│                                │
│  ────────── or ──────────      │
│                                │
│  ┌──────────────────────────┐  │
│  │ Sony WH-1000XM5...   🎤 │  │
│  └──────────────────────────┘  │
│        [Find Best Price]        │
│                                │
│  Saved cards: HDFC · SBI ✏️   │
└────────────────────────────────┘
```

**Screen B: Searching (Progressive)**
```
┌────────────────────────────────┐
│ FW [📦 Products] [✈️ Travel] ⚙ │
├────────────────────────────────┤
│ Sony WH-1000XM5 Headphones     │
│ ● High confidence              │
├────────────────────────────────┤
│ Searching...                   │
│ 🟠 Amazon India   [████████░] │
│ 🔵 Flipkart       [██████░░░] │
├────────────────────────────────┤
│ ┌──────────────────────────┐   │
│ │ 🟠 Amazon India  WINNER  │   │ ← appears when Amazon completes
│ │ ₹21,242                  │   │
│ │ base ₹24,990 − 15% HDFC  │   │
│ │ ✓ BEST DEAL   [BUY →]   │   │
│ └──────────────────────────┘   │
└────────────────────────────────┘
```

**Screen C: Results Complete**
```
┌────────────────────────────────┐
│ FW [📦 Products] [✈️ Travel] ⚙ │
├────────────────────────────────┤
│ Sony WH-1000XM5 Headphones     │
│ Amazon · Flipkart  [Search ↩]  │
├────────────────────────────────┤
│ ╔══════════════════════════╗   │
│ ║ 💰 You save ₹5,748      ║   │
│ ╚══════════════════════════╝   │
├────────────────────────────────┤
│ ┌──────────────────────────┐   │
│ │ 🟠 Amazon  ★ BEST DEAL  │   │ ← gold border
│ │ ₹21,242                  │   │
│ │ ₹24,990 − HDFC 15%       │   │
│ │ Free delivery, 2 days    │   │
│ │         [BUY ON AMAZON →]│   │
│ └──────────────────────────┘   │
│ ┌──────────────────────────┐   │
│ │ 🔵 Flipkart              │   │
│ │ ₹22,991                  │   │
│ │ ₹26,490 − Axis 13%       │   │
│ │ Free delivery, 3 days    │   │
│ │              [View →]    │   │
│ └──────────────────────────┘   │
│ Nova's reasoning ▾             │
└────────────────────────────────┘
```

### 6.2 Extension Side Panel — Travel Mode

**Screen A: Idle**
```
┌────────────────────────────────┐
│ FW [📦 Products] [✈️ Travel] ⚙ │
├────────────────────────────────┤
│                                │
│  🎤 Tap to speak your route    │
│     or fill below              │
│                                │
│  From: [        ▾] To: [   ▾]  │
│  Date: [      ▾]   [Economy ▾] │
│        [Find Cheapest Flight]   │
│                                │
│  Saved cards: HDFC · SBI ✏️   │
└────────────────────────────────┘
```

**Screen B: Results**
```
┌────────────────────────────────┐
│ FW [📦 Products] [✈️ Travel] ⚙ │
├────────────────────────────────┤
│ Mumbai → Delhi · 15 Mar · 1pax │
├────────────────────────────────┤
│ ╔══════════════════════════╗   │
│ ║ 💰 You save ₹1,890      ║   │
│ ╚══════════════════════════╝   │
├────────────────────────────────┤
│ ┌──────────────────────────┐   │
│ │ 🟧 Goibibo   ★ BEST     │   │ ← gold border
│ │ ₹4,201  SBI card         │   │
│ │ IndiGo 6E-204  7:20 AM   │   │
│ │ ₹4,890 − SBI 14% − ₹0   │   │
│ │       [BOOK ON GOIBIBO →]│   │
│ └──────────────────────────┘   │
│ ┌──────────────────────────┐   │
│ │ 🔴 MakeMyTrip            │   │
│ │ ₹5,891                   │   │
│ │ IndiGo 6E-204  7:20 AM   │   │
│ └──────────────────────────┘   │
│ ┌──────────────────────────┐   │
│ │ 🟠 Cleartrip             │   │
│ │ ₹4,680  HDFC card        │   │
│ │ IndiGo 6E-204  7:20 AM   │   │
│ └──────────────────────────┘   │
└────────────────────────────────┘
```

---

## 7. Marketing Website Structure

**File:** `frontend_webapp/index.html` ✅ Built

### Sections (Top to Bottom) — As Built
```
1. NAV        ✅ — Logo (Bricolage Grotesque) + "Add to Chrome" (sticky, blur backdrop)
2. HERO       ✅ — Two-column grid: headline left (clamp 32-46px) + extension mock right (400px fixed)
                   Platform trust strip: Amazon · Flipkart · MakeMyTrip · Goibibo · Cleartrip chips
3. HOW        ✅ — "How It Works" — tabbed (Products / Travel), 3 numbered steps each
4. DEMO       ✅ — Interactive demo: 2.2s animated search → result cards + Nova Pro reasoning
5. NOVA       ✅ — 5 Nova model cards (Nova Lite, Multimodal, Act×2, Pro, Sonic)
6. PLATFORMS  ✅ — 5 platform badges + 5 bank card badges in platform-chips grid
7. CTA        ✅ — Footer CTA card: "Add to Chrome — Free" + sub-copy
8. FOOTER     — (included in CTA card section)

Not built vs. original spec:
  — MOBILE: separate PWA section not added (referenced in bank cards section instead)
  — CALCULATOR: savings estimator slider not implemented
  — HISTORY: search history section not in scope for MVP

Note: Background grid uses CSS `background-image: linear-gradient` dots at 5% opacity.
      Original `body::after` noise overlay removed — was blocking screenshot tool at z-index:9999.
```

### Hero Layout (Implemented)
```
┌────────────────────────────────────────────────────┐
│                                                    │
│  FareWise                         [Extension Mock] │
│                                                    │
│  Stop guessing.                   ┌──────────────┐ │
│  See the real price with          │ FW [📦][✈️] ⚙│ │
│  your card offer.                 │              │ │
│                                   │ Sony WH...   │ │
│  Gadgets. Flights.                │ ★ BEST DEAL │ │
│  With your bank card offer.       │ ₹21,242      │ │
│                                   │ HDFC 15% off │ │
│  [Add to Chrome — Free]           └──────────────┘ │
│  [Try on Web →]                                    │
│                                                    │
│  [Amazon] [Flipkart] [MakeMyTrip] [Goibibo] [CT]  │
└────────────────────────────────────────────────────┘
Grid: 1fr 400px at 1440px viewport; stacks on mobile.
```

### Hero Layout
```
┌────────────────────────────────────────────────────┐
│                                                    │
│  FareWise                         [Extension Mock] │
│                                                    │
│  See the real price.              ┌──────────────┐ │
│  Every time.                      │ FW [📦][✈️] ⚙│ │
│                                   │              │ │
│  Gadgets. Flights.                │ Sony WH...   │ │
│  With your bank card offer.       │ ★ BEST DEAL │ │
│                                   │ ₹21,242      │ │
│  [Add to Chrome — Free]           │ HDFC 15% off │ │
│  [Try on Web →]                   │ Save ₹5,748  │ │
│                                   └──────────────┘ │
│  ₹5,748 avg savings                                │
│  45 sec search time                                │
│  5 platforms covered                               │
└────────────────────────────────────────────────────┘
```

---

## 8. Animation System

### Transitions
```css
/* Standard easing */
--ease-out:   cubic-bezier(0.0, 0.0, 0.2, 1);   /* Most UI transitions */
--ease-in:    cubic-bezier(0.4, 0.0, 1, 1);      /* Exits */
--ease-inout: cubic-bezier(0.4, 0.0, 0.2, 1);   /* Modals */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* Card reveals, badges */

/* Durations */
--dur-fast:   150ms;   /* Button hover, tab switch */
--dur-mid:    250ms;   /* Card reveal, state transitions */
--dur-slow:   400ms;   /* Page load, hero entrance */
```

### Key Animations

**Result card entrance:**
```css
@keyframes slideUpFade {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.platform-card {
  animation: slideUpFade 0.3s var(--ease-spring) both;
}
.platform-card:nth-child(2) { animation-delay: 0.1s; }
.platform-card:nth-child(3) { animation-delay: 0.2s; }
```

**Winner gold pulse:**
```css
@keyframes winnerGlow {
  0%, 100% { box-shadow: 0 0 12px var(--gold-glow); }
  50%       { box-shadow: 0 0 24px rgba(245, 166, 35, 0.25); }
}
.platform-card.winner {
  animation: winnerGlow 2s ease-in-out infinite;
}
```

**Savings counter:**
```css
/* JS-driven counter: 0 → final savings amount over 800ms */
/* Use requestAnimationFrame for smooth counting */
```

---

## 9. Accessibility

- All touch targets: minimum 44×44px (WCAG AA)
- Color contrast: all text on dark backgrounds passes 4.5:1 ratio
- Winner indication: gold border + "BEST DEAL" text (not just color)
- Voice output: all results also displayed visually
- Focus ring: visible blue ring (2px solid #4F8EF7 + 2px offset) on all interactive elements
- Screen reader: `aria-label` on all icon buttons, `aria-live="polite"` on results container
- Keyboard navigation: Tab order follows visual flow, Enter/Space activates all buttons

---

## 10. Mobile PWA Specifics

### Viewport & Safe Areas
```css
/* Support iPhone notch / Dynamic Island / Android camera cutout */
body {
  padding-top: env(safe-area-inset-top);
  padding-bottom: env(safe-area-inset-bottom);
}
```

### Bottom Navigation Bar (Mobile Only)
```
┌─────────────────────────────────────────┐
│  [📦 Products]      [✈️ Travel]        │
└─────────────────────────────────────────┘
```
```css
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0; right: 0;
  background: var(--bg-surface);
  border-top: 1px solid var(--bg-elevated);
  padding: var(--space-2) var(--space-4);
  padding-bottom: calc(var(--space-2) + env(safe-area-inset-bottom));
  display: flex;
  justify-content: space-around;
}
```

### Camera Capture Button (Products Mode — Mobile Only)
```html
<label class="camera-btn">
  <input type="file" accept="image/*" capture="environment" hidden>
  📷 Take Photo
</label>
```
```css
.camera-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--blue-glow);
  border: 1px solid var(--blue-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  font-size: var(--text-base);
  color: var(--blue);
  cursor: pointer;
  width: 100%;
}
```

---

## 11. PWA Manifest

```json
{
  "name": "FareWise",
  "short_name": "FareWise",
  "description": "India's AI price intelligence — gadgets and flights with your bank card offer",
  "start_url": "/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#070711",
  "theme_color": "#4F8EF7",
  "categories": ["finance", "shopping", "travel"],
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ],
  "share_target": {
    "action": "/share",
    "method": "POST",
    "enctype": "multipart/form-data",
    "params": {
      "title": "title",
      "text": "text",
      "url": "url",
      "files": [{ "name": "image", "accept": ["image/*"] }]
    }
  }
}
```

The `share_target` enables Android WhatsApp share sheet integration — users can share any image from WhatsApp directly to FareWise.
