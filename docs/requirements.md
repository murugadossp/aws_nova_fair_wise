# FareWise — Product Requirements Document
> India's AI Price Intelligence · Powered by Amazon Nova · Chrome Extension + Web App + Mobile PWA

**Version:** 1.1 (updated March 2026 — post-implementation)
**Hackathon:** Amazon Nova AI Hackathon 2026
**Categories:** UI Automation · Multimodal Understanding · Voice AI
**Team:** Solo / India

---

## Current Build Status

| Component | Status | Notes |
|---|---|---|
| Chrome Extension | ✅ Complete | MV3, side panel, popup, service worker, onboarding, icons |
| Web App | ✅ Complete | `frontend_webapp/index.html` — Bricolage Grotesque design |
| Backend — FastAPI | ✅ Complete | `main.py`, all routers, CORS, WebSocket |
| Nova Lite (identifier) | ✅ Complete | `backend/nova/identifier.py` |
| Nova Multimodal (validator) | ✅ Complete | `backend/nova/validator.py` |
| Nova Pro (reasoner) | ✅ Complete | `backend/nova/reasoner.py` — model: `us.amazon.nova-pro-v1:0` |
| Nova Act agents (×5) | ✅ Complete | amazon, flipkart, makemytrip, goibibo, cleartrip |
| Orchestrator | ✅ Complete | `backend/agents/orchestrator.py` — `ThreadPoolExecutor(max_workers=5)` |
| Nova Sonic voice | ✅ Complete | `backend/routers/voice.py` — Polly MVP; Nova Sonic target for production |
| Bank card database | ✅ Complete | `backend/data/card_offers.json` — 5 cards × 5 platforms |
| Mobile PWA manifest + SW | ⏳ Pending | `frontend_webapp/manifest.json` + `sw.js` |
| Demo video | ⏳ Pending | — |
| Live AWS wiring | ⏳ Pending | Requires `.env` with real credentials |

---

## 1. Vision

> "See the real price. Every time."

FareWise is India's AI-powered price intelligence agent. It eliminates the hidden cost of price fragmentation — whether you're buying a gadget or booking a flight. Users paste a WhatsApp deal screenshot, type a product name, or speak a route, and FareWise searches across platforms simultaneously, applies their bank card offers, and announces the true cheapest option by voice.

**Tagline:** See the real price. Every time.
**Sub-tagline:** Gadgets. Flights. With your bank card offer.

**Two modes, one truth:**
- **Products Mode** — Paste any WhatsApp screenshot or type a product name → Compare on Amazon + Flipkart with your bank card
- **Travel Mode** — Speak or type "Mumbai to Delhi, March 15" → Compare on MakeMyTrip + Goibibo + Cleartrip with your bank card

**Three surfaces, one backend:**
- Chrome Extension (desktop, in-context)
- Web App (desktop, no install needed)
- Mobile PWA (Android + iOS, camera + WhatsApp share)

---

## 2. The Problem

### 2.1 The Price Fragmentation Reality

India has two massive price fragmentation problems that cost consumers ₹4,000–₹15,000 per major purchase:

#### Electronics Fragmentation
- Amazon India and Flipkart actively price-compete on the same products
- Price gaps of ₹2,000–₹10,000 on the same exact gadget are common
- Bank card offers differ per platform: HDFC gets 15% on Amazon, Axis gets 15% on Flipkart
- True final price (base − card offer − coupon + delivery) is almost impossible to calculate mentally
- Only 23% of Indian consumers check multiple platforms before buying

#### Travel Fragmentation
- Same flight listed differently on MakeMyTrip vs Goibibo vs Cleartrip
- Markup differences: ₹300–₹1,500 for the same flight
- OTA-specific card partnerships: SBI gets extra 10% on Goibibo, HDFC gets 8% on MakeMyTrip
- Convenience fees hidden until checkout
- Real final price requires checking 3 OTAs × multiple card combinations = ~20 minutes of work

### 2.2 The WhatsApp Deal Problem
- Indians share ~800M product/deal screenshots daily on WhatsApp
- "Is this a good deal?" has no quick answer
- Friend may have shared an old screenshot with an outdated price
- User has no way to verify if the shared price is current or the platform cheapest

### 2.3 The Bank Card Blind Spot
- Average Indian household holds 2.3 credit/debit cards
- Almost no one knows which card is optimal for which platform
- Platform-card partnerships change monthly (Flipkart-Axis, Amazon-HDFC, etc.)
- Difference between worst card and best card for a ₹80,000 laptop: ₹8,000–₹12,000

---

## 3. Target Users

### Primary — "The WhatsApp Verifier"
- **Age:** 22–45, Tier 1 Indian cities
- **Behavior:** Receives deal screenshots on WhatsApp, wants to verify before buying
- **Quote:** *"My friend sent this headphone deal — is ₹26,990 actually good?"*
- **Key need:** Instant verification without opening multiple tabs

### Secondary — "The Card Optimizer"
- **Age:** 28–50, holds multiple credit cards
- **Behavior:** Knows card offers exist but finds them impossible to track
- **Quote:** *"I have HDFC and Axis cards — which one to use for this flight?"*
- **Key need:** Automatic card offer calculation across all their cards

### Tertiary — "The Travel Planner"
- **Age:** 25–40
- **Behavior:** Books flights on mobile, uses voice as primary input
- **Quote:** *"Just tell me the cheapest Mumbai–Bangalore flight for Friday"*
- **Key need:** Fast, voice-driven comparison without opening multiple OTA apps

---

## 4. Solution — FareWise

### 4.1 Products Mode

**Primary input:** Paste a WhatsApp screenshot of a product listing (text always visible → 90%+ accuracy)
**Alternative inputs:** Type the product name, speak the product name, upload any image

**Pipeline:**
```
Input (screenshot / text / voice)
    ↓
Nova Lite [multimodal LLM]
    Reads visible text from screenshot
    Identifies: brand, model, variant, search query
    Confidence: high / medium / low
    ↓
Nova Multimodal Embeddings [cross-modal validator]
    Embeds user's image + 5-10 search result thumbnails
    Cosine similarity → picks best-matching product
    Confirms exact SKU variant selected
    ↓
Nova Act [2 agents, parallel]
    Agent 1: navigates Amazon.in → extracts price, card offers, coupons, delivery
    Agent 2: navigates Flipkart.com → same extraction
    ↓
Nova Pro [reasoning]
    Applies user's bank cards to each platform
    Formula: base_price − card_discount − coupon + delivery_fee = true_cost
    Ranks: Amazon×HDFC | Amazon×SBI | Flipkart×Axis | Flipkart×SBI | ...
    Selects winner + generates explanation (3 sentences max)
    ↓
Nova Sonic [voice output]
    "Amazon wins at ₹22,491 with your HDFC card. You save ₹4,499."
    Handles follow-up: "What about SBI card?" "What's the delivery date?"
```

**Input accuracy tiers:**
| Input Type | Accuracy | Why |
|---|---|---|
| WhatsApp product listing screenshot | 90%+ | Product name text always present in listing |
| Product box photo (in-store) | 90%+ | Model number text visible on packaging |
| Text / voice product name | 99% | Direct lookup, no identification needed |
| Bare product photo (no label) | 40-60% | Limited to visual design recognition |

### 4.2 Travel Mode

**Inputs:** Voice ("Mumbai to Delhi, this Friday") or text
**No image needed** — routing is always text-based

**Pipeline:**
```
Input (voice / text)
    ↓
Nova Sonic [voice input]
    Parses: origin, destination, date(s), traveller count, class
    "Mumbai to Delhi, this Friday, 1 adult, economy"
    ↓
Nova Act [3 agents, parallel]
    Agent 1: navigates MakeMyTrip.com → finds flights, extracts fares + card offers
    Agent 2: navigates Goibibo.com → same
    Agent 3: navigates Cleartrip.com → same
    ↓
Nova Pro [reasoning]
    Per OTA per card: base_fare + convenience_fee − card_discount = true_cost
    Ranks all combinations (3 OTAs × 5 cards = up to 15 comparisons)
    Considers: same flight on different OTAs, different cards on same OTA
    ↓
Nova Sonic [voice output]
    "Goibibo wins. IndiGo 6E-204 at ₹4,201 with your SBI card.
     That's ₹1,340 cheaper than MakeMyTrip. Book?"
```

---

## 5. Amazon Nova Model Mapping

| Nova Model | Model ID | Role | Why This Model — Not Alternatives |
|---|---|---|---|
| **Nova Lite** (multimodal LLM) | `us.amazon.nova-lite-v1:0` | Primary product identifier — reads text labels from screenshots/photos; uses training knowledge; outputs exact brand + model + variant | A generative LLM is the ONLY way to identify products from images without a pre-built catalog. Nova Lite accepts images as input and can read printed text (OCR) + use knowledge to identify electronics. No catalog needed. |
| **Nova Multimodal Embeddings** | `amazon.nova-multimodal-embeddings-v1` | SKU validation — embeds user's image + 5-10 search result thumbnails; cosine similarity picks the correct variant | Pure embedding model used in its correct role: cross-modal similarity (image↔image or image↔text). Not a generative model. Used AFTER identification to confirm the right variant was selected on Amazon/Flipkart. |
| **Nova Act** | Nova Act API | Web agent pair (Products: Amazon + Flipkart) and triple (Travel: MMT + Goibibo + Cleartrip) — navigates real sites, extracts live prices + card offer banners | No public APIs exist for live pricing + card offer data. OTA/e-commerce sites require real browser navigation. Nova Act runs server-side Chromium and extracts data reliably. |
| **Nova Pro** | `us.amazon.nova-pro-v1:0` | Multi-variable price reasoning across all platform × card combinations — calculates true cost, ranks options, explains winner in natural language | The card offer calculation is a multi-step financial reasoning task. Nova Pro's 300K context window handles all platform results + card offer rules simultaneously. Generates natural language explanation of the winner. |
| **Nova Sonic** | `amazon.nova-sonic-v1:0` | Bidirectional voice — listens to travel queries ("Mumbai to Delhi, Friday"), reads product announcements, handles follow-up Q&A ("What about SBI card?") | True end-to-end speech model with barge-in support. User in a store or on the go doesn't have to type. Follow-up questions in the same voice session (tool use mid-conversation). |

> **Implementation note:** Voice TTS uses Amazon Polly (Aditi neural) as MVP fallback in `routers/voice.py`. Nova Sonic bidirectional streaming is the production target.

**Genuine multi-model architecture (not forced):**
- Products mode: all Nova models in sequence (Nova Lite → Nova Multimodal → Nova Act ×2 → Nova Pro → Nova Sonic)
- Travel mode: 3 Nova models (Nova Sonic → Nova Act ×3 → Nova Pro → Nova Sonic)
- No model is bolted on artificially — each one does what only it can do

---

## 6. Functional Requirements

### F1: Products — Screenshot & Image Analysis
- Accept: clipboard paste, file upload, mobile camera (PWA), WhatsApp share
- Primary target: product listing screenshots (Amazon/Flipkart listing images)
- Nova Lite identifies: brand, full model name, model number, variant, search query
- Confidence score shown: High / Medium / Low
- Medium confidence: shows user "Is this the Sony WH-1000XM5?" with confirm/edit option
- Low confidence: suggests text search, still shows best guess
- Nova Multimodal: validates search result images match the input image (5-10 comparisons)

### F2: Products — Price Search (Amazon + Flipkart)
- Two Nova Act agents run in parallel (ThreadPoolExecutor)
- Per platform: base price, all card offer banners, active coupon codes, delivery fee, delivery ETA, seller type (official brand store vs marketplace)
- Results within 45 seconds
- Graceful fallback: if one platform fails, show the other with note
- Streams results via WebSocket as each agent completes (progressive reveal)

### F3: Travel — Voice Route Search
- Nova Sonic parses natural language: "Mumbai to Delhi next Friday evening"
- Extracts: origin city/airport, destination city/airport, travel date, time preference, pax count, class
- Three Nova Act agents search simultaneously: MakeMyTrip, Goibibo, Cleartrip
- Per OTA: all matching flights, base fare, convenience fee, card offer, baggage policy
- Results within 60 seconds
- One-click to open OTA booking page for the winning option

### F4: Bank Card Intelligence
- User saves their bank cards in extension settings (card names only, no card numbers ever)
- Cards supported MVP: HDFC Regalia/Millennia, SBI SimplyCLICK/Cashback, Axis Flipkart/Magnus, ICICI Amazon Pay, Kotak Essentia
- Per platform × per card: look up offer (instant discount vs cashback vs EMI)
- Offers database: `backend/data/card_offers.json` (manually maintained, updated weekly)
- Nova Act verifies current offers at payment step (source of truth)
- True price calculation: base − instant_discount − coupon + delivery = true_cost
- Cashback shown separately: "+ ₹800 cashback within 30 days"

### F5: True Price Calculation & Ranking
- Nova Pro processes all results (platform × card combinations)
- Accounts for: instant discount, cashback timeline, no-cost EMI, convenience fees
- Ranks from cheapest to most expensive true cost
- Winner highlighted (gold border + "BEST DEAL" badge)
- Explanation: "Amazon wins because your HDFC card gives 15% instant off (₹3,748) vs Axis on Flipkart which only gives 10% (₹2,499). No delivery fee on both."
- Savings vs most expensive option: "You save ₹5,249 vs the worst option"

### F6: Voice Interface (Nova Sonic)
- Products: voice input ("Find Sony WH-1000XM5"), voice announcement of winner
- Travel: voice input ("Mumbai to Delhi, Friday morning"), voice announcement
- Follow-up Q&A in same session: "What about SBI card?" / "Show only IndiGo flights" / "Any flights tomorrow instead?"
- Barge-in supported (interrupt mid-announcement)
- Works in both extension (desktop mic) and PWA (mobile mic)

### F7: One-Click Booking/Purchase
- "Book on Goibibo" → opens Goibibo flight result in new tab/window, pre-filtered
- "Buy on Amazon" → opens Amazon product page in new tab
- FareWise NEVER touches payment — user completes in their own session
- Deep link where possible, search URL fallback

### F8: Chrome Extension
- Manifest V3
- Side panel (380px wide, full height) — always visible
- Keyboard shortcut: Cmd/Ctrl+Shift+F to open FareWise
- Mode toggle: Products (📦) | Travel (✈️) tabs at top
- Settings page: add/remove saved bank cards, default mode preference
- Works on any URL (FareWise opens independently, not page-scraping)

### F9: Web App + Marketing Website
- Landing page: hero, how it works, demo, Nova models, savings stats, CTA
- Embedded live search widget (same backend API, works without extension install)
- Works on desktop browsers (Chrome, Safari, Firefox, Edge)
- Accessible at a public URL (for hackathon judges to test)

### F10: Mobile PWA
- manifest.json: installable on Android homescreen (Chrome prompt) + iOS (Safari "Add to Home Screen")
- Service worker: caches app shell (offline-capable for UI)
- Mobile-specific: camera access for product photos (`<input type="file" capture="environment">`)
- WhatsApp share target: Android users can "Share → FareWise" from WhatsApp
- Responsive design: thumb-friendly tap targets (min 44px), bottom navigation bar

---

## 7. Non-Functional Requirements

### 7.1 Performance
| Metric | Target |
|---|---|
| Product identification (Nova Lite) | < 3 seconds |
| Price search — products (2 agents) | < 45 seconds |
| Price search — travel (3 agents) | < 60 seconds |
| Voice response latency (Nova Sonic) | < 1.5 seconds |
| Extension side panel open | < 300ms |
| Website first meaningful paint | < 2 seconds |

### 7.2 Accuracy
- Product ID from listing screenshot: > 90%
- Product ID from product box photo: > 85%
- Price accuracy: live platform price at time of search (not cached)
- Card offer accuracy: verified by Nova Act at payment step

### 7.3 Security & Privacy
- **Zero card number storage** — only card name saved (e.g., "HDFC Regalia")
- **No payment data** — FareWise never sees, touches, or transmits payment info
- Bank card names: stored in `chrome.storage.local` (never leaves device)
- Nova Act sessions: sandboxed Chromium instances, destroyed after each search
- No user account required — stateless by default
- HTTPS only for all API communication

### 7.4 Reliability
- Single agent failure: show results from the other platform(s) with a note
- All agents fail: show error with retry option + suggest text-based search
- Nova Sonic fails: fall back to text input/output silently
- Confidence shown honestly: never silently show a wrong product

---

## 8. Technical Architecture

> For full architecture details including the Nova Act vs. Orchestrator distinction, WebSocket protocol, and data flow diagrams, see [`docs/architecture.md`](./architecture.md).

```
┌─────────────────────────────────────────────────────────────┐
│              FRONTEND SURFACES (3)                           │
│  Chrome Extension │ Web App / PWA │ Mobile PWA (camera)     │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend                             │
│  POST /api/products/identify                                 │
│  POST /api/products/search                                   │
│  POST /api/travel/search                                     │
│  WebSocket /ws/search/{task_id}                              │
│  GET  /api/history/{session}                                 │
└──────┬────────────────────┬──────────────────────────────────┘
       │                    │
┌──────▼──────┐    ┌────────▼─────────────────────────────────┐
│ Nova Lite   │    │         Nova Act Agent Pool               │
│ (multimodal)│    │  ┌─ Agent: Amazon.in (products)          │
│             │    │  ├─ Agent: Flipkart.com (products)        │
│ Screenshot  │    │  ├─ Agent: MakeMyTrip.com (travel)        │
│ → product   │    │  ├─ Agent: Goibibo.com (travel)           │
│ identity    │    │  └─ Agent: Cleartrip.com (travel)         │
│             │    │  ThreadPoolExecutor: max_workers=5         │
└──────┬──────┘    └────────────┬─────────────────────────────┘
       │                        │
┌──────▼──────┐    ┌────────────▼─────────────────────────────┐
│ Nova        │    │  Nova Pro (Reasoning)                  │
│ Multimodal  │    │  • Applies card offers per platform       │
│ Embeddings  │    │  • Calculates true cost (base-disc+del)   │
│             │    │  • Ranks all options                       │
│ Image↔Image │    │  • Generates explanation                  │
│ similarity  │    └────────────┬─────────────────────────────┘
│ validation  │                 │
└─────────────┘    ┌────────────▼─────────────────────────────┐
                   │  Nova Sonic (Voice)                       │
                   │  • Input: parse route / product query     │
                   │  • Output: announce winner                │
                   │  • Follow-up Q&A                          │
                   └──────────────────────────────────────────┘
```

---

## 9. Platform & Card Coverage

### Products Mode — Platforms
| Platform | Why | Market Share |
|---|---|---|
| **Amazon India** | #1 electronics marketplace, HDFC/SBI/ICICI offers | ~40% |
| **Flipkart** | #2 electronics, Axis card partnership, SuperCoin | ~35% |

*Post-MVP: Tata Cliq, Croma Online, Vijay Sales Online, Reliance Digital*

### Travel Mode — OTAs
| OTA | Why | Market Share |
|---|---|---|
| **MakeMyTrip** | Largest OTA in India, all major card offers | ~60% |
| **Goibibo** | Strong SBI partnership (extra 10-12% off) | ~20% |
| **Cleartrip** | HDFC partnership, often cheapest convenience fee | ~10% |

*Post-MVP: IRCTC (trains), RedBus (bus), EaseMyTrip*

### Bank Cards
| Bank | Cards (MVP) | Typical Benefit | Best Platform |
|---|---|---|---|
| HDFC | Regalia, Millennia, Diners | 5-15% instant off | Amazon |
| SBI | SimplyCLICK, Cashback | 5-12% + cashback | Goibibo |
| Axis | Flipkart Axis, Magnus | 5-15% instant off | Flipkart |
| ICICI | Amazon Pay ICICI | 5% unlimited cashback | Amazon |
| Kotak | Essentia, League | 5-8% | Both |

---

## 10. Demo Stories (Hackathon Video)

### Demo 1 — Products (30 seconds)
1. Friend forwards WhatsApp screenshot: Sony WH-1000XM5 at ₹26,990
2. User opens FareWise, pastes screenshot → *"Identified: Sony WH-1000XM5 — 95% confidence"*
3. Searching Amazon + Flipkart... (progressive reveal)
4. Amazon: ₹24,990 | Flipkart: ₹26,490
5. HDFC card on Amazon: ₹21,242 final
6. Nova Sonic: *"Amazon wins at ₹21,242 with HDFC. That's ₹5,748 cheaper. The WhatsApp price was also outdated — it dropped ₹2,000."*
7. Click "Buy on Amazon" → opens product page

### Demo 2 — Travel (30 seconds)
1. User speaks: "Cheapest flight from Mumbai to Bangalore this Saturday"
2. Nova Sonic confirms: *"Searching Mumbai–Bangalore, Saturday, economy..."*
3. Three agents stream results: MMT, Goibibo, Cleartrip (progressive reveal)
4. Goibibo shows IndiGo 6E-861 at ₹4,890 | SBI card → ₹4,201
5. Nova Sonic: *"Goibibo wins. IndiGo 6E-861 at 7:20 AM — ₹4,201 with your SBI card. That's ₹1,890 less than MakeMyTrip."*
6. Tap "Book on Goibibo" → opens Goibibo flight page

---

## 11. Success Metrics

### Hackathon Must-Have
- [ ] WhatsApp screenshot → correct product identified (< 3 seconds)
- [ ] Amazon + Flipkart prices both appear (< 45 seconds)
- [ ] Bank card offer correctly applied (HDFC 15% = correct final price)
- [ ] Travel mode: voice route parsed, 3 OTAs searched, winner announced
- [ ] All 4 Nova models demonstrably used (shown in architecture diagram)
- [ ] Chrome extension functional (side panel opens, results display)
- [ ] Web app accessible at public URL, works without extension
- [ ] Mobile PWA installable (manifest.json + service worker)
- [ ] Demo video: 2 stories, < 3 minutes total

### Hackathon Nice-to-Have
- [ ] Live prices (not simulated)
- [ ] Follow-up voice question handled
- [ ] Price history for a product (2-3 searches)
- [ ] Share button: "FareWise found me ₹5,748 savings on Sony headphones!"

---

## 12. Out of Scope (v1.0)

- Fashion, grocery, home, FMCG (different platforms, low photo accuracy)
- Bus/trains (different OTA ecosystem; add in v2)
- More than 2 e-commerce + 3 OTA platforms
- Mobile native app (PWA covers the mobile surface)
- User accounts / cloud sync
- Price history tracking / alerts
- International products (India only, INR only)
- Actual purchase completion (user always pays themselves)
- Hotel / holiday packages (different booking model)

---

## 13. Hackathon Submission Checklist

- [ ] GitHub repo: `farewise-nova` (public)
- [ ] Devpost submission with all 4 Nova models listed under "Technologies Used"
- [ ] Demo video: ≤ 3 minutes, shows both modes, voice in action
- [ ] Live demo URL: web app accessible without login
- [ ] Blog post on builder.aws.com (qualifies for Blog Post Prize: $500 + AWS credits)
- [ ] Architecture diagram showing Nova model pipeline
