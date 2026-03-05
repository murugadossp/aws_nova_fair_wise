# FareWise — Architecture Deep Dive
> Two-Layer Design · Amazon Nova Model Pipeline · WebSocket Streaming · Three Surfaces

**Version:** 1.1 (updated after full backend implementation)

---

## The Core Question: Why Two Layers?

> *"Nova Act is already an agent framework — why do we need a separate orchestrator?"*

This is the right question, and the answer explains the entire architecture.

### What Nova Act IS (and isn't)

**Nova Act** is a **single-site browser automation agent**:
- Controls ONE real Chromium browser instance
- Navigates ONE website per session
- Executes natural language instructions on that page
- Returns structured data (JSON schema output)
- Runs **synchronously** — one step at a time on one page

```python
# Nova Act: one site, one session, one browser
with NovaAct(starting_page="https://www.amazon.in/s?k=Sony+WH-1000XM5") as agent:
    data = agent.act("Extract the top 5 listings", schema={...})
```

Nova Act cannot:
- Coordinate multiple sites simultaneously
- Make Bedrock API calls (Nova Lite, Nova Pro, etc.)
- Stream progress over WebSocket
- Handle partial failures across multiple agents
- Chain different AI models together

### What the Orchestrator Adds

**Our Orchestrator** is a **coordination and intelligence layer**:

| Concern | Nova Act | Orchestrator |
|---|---|---|
| Single-site browsing | ✅ Built-in | — |
| Multi-site parallel execution | ❌ Not possible | ✅ `ThreadPoolExecutor` |
| Nova Lite / Pro / Sonic calls | ❌ Not possible | ✅ Direct Bedrock API |
| WebSocket progress streaming | ❌ Not possible | ✅ Async generator |
| Partial failure handling | ❌ Not possible | ✅ Try/except per agent |
| Card offer calculation | ❌ Not possible | ✅ Nova Pro reasoning |
| Voice I/O | ❌ Not possible | ✅ Nova Sonic + Polly |

**The two layers are complementary, not redundant.** Nova Act handles the browser autonomously per site; the orchestrator coordinates across sites and across Amazon Nova models.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FRONTEND SURFACES (3)                             │
│                                                                      │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐  │
│  │  Chrome Extension│  │   Web App / PWA   │  │   Mobile PWA     │  │
│  │  (Side Panel)    │  │   (Marketing +    │  │   (Camera +      │  │
│  │  380px sidebar   │  │    Live Demo)     │  │   WhatsApp share)│  │
│  │  Manifest V3     │  │                   │  │                  │  │
│  └────────┬─────────┘  └────────┬──────────┘  └────────┬─────────┘  │
└───────────┼─────────────────────┼──────────────────────┼────────────┘
            │                     │                      │
            └─────────────────────┼──────────────────────┘
                                  │ HTTPS + WebSocket
                                  │
┌─────────────────────────────────▼───────────────────────────────────┐
│                         FastAPI Backend                               │
│                                                                       │
│  REST Endpoints:                  WebSocket:                          │
│  POST /api/products/identify      WS /ws/search/{task_id}            │
│  POST /api/products/search        (streams progress in real-time)    │
│  POST /api/travel/search          WS /api/voice/ws                   │
│  POST /api/travel/parse-voice     (Nova Sonic voice session)         │
│  GET  /health                                                         │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │                              │
   ┌───────────▼────────────┐   ┌─────────────▼──────────────────────┐
   │   NOVA MODEL LAYER     │   │      NOVA ACT AGENT LAYER          │
   │                        │   │                                    │
   │  nova/identifier.py    │   │  ThreadPoolExecutor (max 5 workers)│
   │  ┌────────────────┐    │   │                                    │
   │  │  Nova Lite     │    │   │  Products Mode (2 agents):         │
   │  │  nova-lite-v1  │    │   │  ┌──────────────────────────────┐  │
   │  │  Reads text    │    │   │  │ agents/amazon.py             │  │
   │  │  from image    │    │   │  │ NovaAct → amazon.in          │  │
   │  └────────────────┘    │   │  │ Returns: price, offers, ETA  │  │
   │                        │   │  └──────────────────────────────┘  │
   │  nova/validator.py     │   │  ┌──────────────────────────────┐  │
   │  ┌────────────────┐    │   │  │ agents/flipkart.py           │  │
   │  │  Nova Multi-   │    │   │  │ NovaAct → flipkart.com       │  │
   │  │  modal Embed.  │    │   │  │ Returns: price, offers, ETA  │  │
   │  │  Cosine sim.   │    │   │  └──────────────────────────────┘  │
   │  │  validation    │    │   │                                    │
   │  └────────────────┘    │   │  Travel Mode (3 agents):           │
   │                        │   │  ┌──────────────────────────────┐  │
   │  nova/reasoner.py      │   │  │ agents/makemytrip.py         │  │
   │  ┌────────────────┐    │   │  │ NovaAct → makemytrip.com     │  │
   │  │  Nova Pro      │    │   │  └──────────────────────────────┘  │
   │  │  nova-pro-v1   │    │   │  ┌──────────────────────────────┐  │
   │  │  Price calc +  │    │   │  │ agents/goibibo.py            │  │
   │  │  card offers   │    │   │  │ NovaAct → goibibo.com        │  │
   │  └────────────────┘    │   │  └──────────────────────────────┘  │
   │                        │   │  ┌──────────────────────────────┐  │
   │  routers/voice.py      │   │  │ agents/cleartrip.py          │  │
   │  ┌────────────────┐    │   │  │ NovaAct → cleartrip.com      │  │
   │  │  Nova Sonic    │    │   │  └──────────────────────────────┘  │
   │  │  (via Polly    │    │   │                                    │
   │  │   for MVP TTS) │    │   │  agents/orchestrator.py            │
   │  └────────────────┘    │   │  Coordinates parallel execution    │
   └────────────────────────┘   └────────────────────────────────────┘
                   │                              │
                   └──────────────┬───────────────┘
                                  │ Both layers feed into
                                  ▼
                        data/card_offers.json
                        (bank card offer database)
```

---

## Products Mode — Complete Pipeline

```
Step 1: INPUT
  WhatsApp screenshot (paste) / product name (text) / voice

Step 2: NOVA LITE IDENTIFICATION  [nova/identifier.py]
  Model: us.amazon.nova-lite-v1:0
  Input: base64 image bytes
  Does:  - Reads all visible text (OCR + knowledge)
         - Identifies brand, model number, variant
         - Assigns confidence: high / medium / low
  Output: { product_name, model_number, brand, search_query, confidence }
  Time:  ~2 seconds

Step 3: NOVA MULTIMODAL EMBEDDING  [nova/validator.py]
  Model: amazon.nova-multimodal-embeddings-v1
  Input: user image + up to 10 search result thumbnails
  Does:  - Embeds user image into vector space
         - Embeds each result thumbnail
         - Cosine similarity → filters to best matches (threshold: 0.72)
  Output: validated results list (wrong SKU variants filtered out)
  Time:  ~3-5 seconds (parallel embedding calls)

Step 4: NOVA ACT PARALLEL SEARCH  [agents/orchestrator.py]
  Workers: ThreadPoolExecutor(max_workers=5)
  Agents run simultaneously:
  ┌─────────────────────────────────────────────────────┐
  │  Thread 1: AmazonAgent.search(query)                │
  │  ├── NovaAct(starting_page=amazon.in/s?k=...)       │
  │  ├── agent.act("Extract top 5 listings", schema=..) │
  │  └── Returns: [{platform, title, price, ...}]       │
  │                                                     │
  │  Thread 2: FlipkartAgent.search(query)              │
  │  ├── NovaAct(starting_page=flipkart.com/search?q=)  │
  │  ├── agent.act("Extract top 5 listings", schema=..) │
  │  └── Returns: [{platform, title, price, ...}]       │
  └─────────────────────────────────────────────────────┘
  Each agent streams "done" event to client as it completes
  Time:  ~30-45 seconds (parallel, not serial)

Step 5: NOVA PRO REASONING  [nova/reasoner.py]
  Model: us.amazon.nova-pro-v1:0
  Input: all platform results + user's saved cards + card_offers.json
  Does:  - Loads platform-specific card offers
         - Formula per option: base − instant_discount − coupon + delivery = true_cost
         - Separates cashback (delayed) from instant discounts
         - Ranks all (platform × card) combinations
         - Generates natural language explanation (3 sentences max)
  Output: { winner, all_results, reasoning }
  Time:  ~2-3 seconds

Step 6: NOVA SONIC ANNOUNCEMENT  [routers/voice.py]
  Via: Amazon Polly (Aditi neural voice) — MVP fallback
  Full: Nova Sonic bidirectional (production target)
  Output: MP3 audio stream of winner announcement
  Example: "Amazon wins at ₹21,242 with your HDFC card. You save ₹5,748."
```

---

## Travel Mode — Complete Pipeline

```
Step 1: INPUT
  Voice ("Mumbai to Delhi, this Friday") or text form fields

Step 2: VOICE PARSING
  Client-side: Web Speech API (fast, no round-trip)
  Server-side: /api/travel/parse-voice (accurate, regex + relative dates)
  Output: { from_city, to_city, date, travel_class, confidence }

Step 3: NOVA ACT PARALLEL SEARCH  [agents/orchestrator.py]
  Workers: ThreadPoolExecutor(max_workers=5)
  Three agents simultaneously:
  ┌─────────────────────────────────────────────────────┐
  │  Thread 1: MakeMyTripAgent.search(route)            │
  │  Thread 2: GoibiboAgent.search(route)               │
  │  Thread 3: CleartripAgent.search(route)             │
  └─────────────────────────────────────────────────────┘
  Each streams "agent_done" event as it completes
  Time:  ~45-60 seconds (parallel, not serial)

Step 4: NOVA PRO REASONING  [nova/reasoner.py]
  Same engine as products, adapted for flights
  Handles: convenience_fee (OTA-specific scam), same flight on multiple OTAs
  Output: { winner, all_results, reasoning }

Step 5: NOVA SONIC ANNOUNCEMENT
  "Goibibo wins. IndiGo 6E-861 at ₹4,201 with your SBI card.
   That's ₹1,890 less than MakeMyTrip."
```

---

## WebSocket Protocol

The WebSocket at `/ws/search/{task_id}` streams real-time progress as each agent completes. This enables **progressive reveal** — the frontend shows results as they arrive, not after all agents finish.

### Message Types (Server → Client)

```javascript
// Agent started browsing
{ "type": "agent_start",  "platform": "amazon",   "message": "Searching Amazon India..." }
{ "type": "agent_start",  "platform": "flipkart",  "message": "Searching Flipkart..." }

// Product identified (Products mode only)
{ "type": "identified",   "product": "Sony WH-1000XM5", "confidence": "high", "search_query": "..." }

// One agent completed (triggers card reveal on frontend)
{ "type": "agent_done",   "platform": "amazon",   "results": [{...}] }
{ "type": "agent_done",   "platform": "flipkart",  "results": [{...}] }

// All agents complete, reasoning done
{ "type": "results",      "winner": {...}, "all_results": [...], "reasoning": "..." }

// Search complete
{ "type": "done" }

// Error (partial — other agents may still be running)
{ "type": "error",        "platform": "cleartrip", "message": "Site unavailable" }
```

### Why WebSocket Instead of Polling?

- **Polling** (POST → GET every 2s): 3-5 requests per agent, wastes bandwidth, adds ~2s delay per result
- **WebSocket**: Server pushes immediately when each agent finishes, zero polling overhead
- **Progressive reveal**: Amazon result card appears at 25s, Flipkart at 32s, reasoning at 35s — not all at 35s

---

## Parallel Execution: The Time Math

### Serial execution (naive approach):
```
Amazon agent: 30s
                  → Flipkart agent: 30s
                                        → Cleartrip: 30s
Total: 90 seconds (unacceptable)
```

### Parallel execution (our approach):
```
Amazon agent:    ────────────── 30s ──
Flipkart agent:  ─────────────────── 35s ──
Cleartrip agent: ──────────── 28s ──
                 ↑                        ↑
              t=0                      t=35s
Total: 35 seconds (max of parallel tasks)
```

**ThreadPoolExecutor implementation:**
```python
# agents/orchestrator.py
executor = ThreadPoolExecutor(max_workers=5)

async def _run_in_thread(func, *args):
    """Bridge synchronous Nova Act into async FastAPI"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

# Run 2 or 3 agents simultaneously
results = await asyncio.gather(
    _run_in_thread(amazon_agent.search, query),
    _run_in_thread(flipkart_agent.search, query),
    return_exceptions=True  # partial failure doesn't kill others
)
```

The `return_exceptions=True` is critical: if one platform is down, the others still return results. The frontend shows "Flipkart unavailable" and continues with Amazon data.

---

## File Structure — What Each File Does

```
backend/
├── main.py                     FastAPI app + CORS + WebSocket dispatch + lifespan
│
├── nova/                       Amazon Nova model integrations
│   ├── __init__.py
│   ├── identifier.py           Nova Lite: image → product name (OCR + knowledge)
│   ├── validator.py            Nova Multimodal: cosine similarity SKU validation
│   └── reasoner.py             Nova Pro: card offer math + winner selection
│
├── agents/                     Nova Act browser agents (one per platform)
│   ├── __init__.py
│   ├── amazon.py               NovaAct → amazon.in search + extraction
│   ├── flipkart.py             NovaAct → flipkart.com search + extraction
│   ├── makemytrip.py           NovaAct → makemytrip.com flight search
│   ├── goibibo.py              NovaAct → goibibo.com flight search
│   ├── cleartrip.py            NovaAct → cleartrip.com flight search
│   └── orchestrator.py         ThreadPoolExecutor + WebSocket streaming logic
│
├── routers/                    FastAPI route handlers
│   ├── __init__.py
│   ├── products.py             POST /api/products/{identify,search}
│   ├── travel.py               POST /api/travel/{search,parse-voice}
│   └── voice.py                WS /api/voice/ws (Nova Sonic TTS/STT)
│
├── data/
│   └── card_offers.json        Bank card offer database (5 cards × 5 platforms)
│
└── requirements.txt            Python dependencies
```

---

## The Nova Model Roles — Why Each One

This is the most important architecture decision for hackathon judges:

### Nova Lite (`us.amazon.nova-lite-v1:0`) — Identifier
**Role:** Multimodal LLM that reads product screenshots

**Why Nova Lite, not a catalog-based approach?**
- A catalog would require: indexing every electronics product → mapping images to SKUs → maintenance when products launch/change → gigabytes of embeddings to build and query
- Nova Lite already knows product names from training data. It reads the text printed on product listings ("WH-1000XM5", "Galaxy S25+") and uses its knowledge to identify the full product.
- **No catalog needed.** Input: image bytes. Output: `{ brand, model_name, search_query, confidence }` in 2 seconds.

### Nova Multimodal Embeddings — Validator
**Role:** Cross-modal similarity check on search results

**Why not use Nova Lite for this too?**
- After Nova Lite identifies "Sony WH-1000XM5" and we search Amazon, we get 10 results: some are the right product, some are accessories, some are different variants (Gold vs Black).
- Nova Multimodal Embeddings converts the user's original image and each result thumbnail into vectors and picks the highest cosine similarity match.
- This is the **correct use case** for an embedding model: similarity search over a small, bounded set (10 thumbnails). Not blind identification from a cold start.

### Nova Act — Browser Agents
**Role:** Real-time price extraction from live websites

**Why not use official APIs?**
- Amazon India, Flipkart, MakeMyTrip, Goibibo, Cleartrip have **no public pricing API** for consumers. The only way to get live prices + card offers is to browse the site as a user would.
- Nova Act runs server-side Chromium, fills search forms, reads prices, card offer banners, and delivery info — exactly as a human would, but in structured JSON.
- Live prices only. Never cached. This is the data source truth for the product.

### Nova Pro (`us.amazon.nova-pro-v1:0`) — Reasoner
**Role:** Multi-variable financial calculation + natural language explanation

**Why Nova Pro, not simple arithmetic?**
- The card offer rules have complexity: "15% off up to ₹2,000 max, only on electronics orders above ₹5,000, not combinable with coupon codes"
- Nova Pro reads the full `card_offers.json` schema alongside all platform results in a single context window (300K tokens), applies the rules correctly, and generates a plain-English explanation.
- Simple arithmetic would require encoding every rule as code — Nova Pro can reason over the rules in natural language.

### Nova Sonic — Voice Interface
**Role:** Input (parse travel route from speech) + Output (announce winner)

**Why bidirectional?**
- Input: User in a store or on-the-go doesn't type. "Mumbai to Bangalore, this Friday evening, 1 adult" is faster spoken than typed.
- Output: After a 45-60 second search, the user shouldn't have to read a table. "Amazon wins at ₹21,242 with HDFC" delivered in < 2 seconds of audio is the ideal UX.
- Follow-up: "What about SBI card?" / "Show only IndiGo" — barge-in and follow-up Q&A in the same session.

---

## Three Surfaces — One Backend

All three frontend surfaces call the **same FastAPI backend**. There is no separate server per surface.

```
Chrome Extension   →  https://farewise.app/api/...
Web App            →  https://farewise.app/api/...
Mobile PWA         →  https://farewise.app/api/...
```

### Surface-Specific Capabilities

| Feature | Chrome Extension | Web App | Mobile PWA |
|---|---|---|---|
| Products: paste screenshot | ✅ (clipboard) | ✅ (file upload) | ✅ (file upload) |
| Products: camera capture | ❌ | ❌ | ✅ `capture="environment"` |
| Products: WhatsApp share target | ❌ | ❌ | ✅ `share_target` in manifest |
| Travel: voice input | ✅ Web Speech API | ✅ Web Speech API | ✅ Web Speech API |
| Works offline | ❌ | Partial (PWA cache) | ✅ App shell cached |
| In-context (on any tab) | ✅ Side panel | ❌ | ❌ |
| No install required | ❌ | ✅ | ❌ (needs "Add to Home") |

---

## Data Flow: Products Mode End-to-End

```
1. User pastes WhatsApp screenshot into Chrome Extension side panel

2. Extension JS: reads clipboard image, converts to base64
   Sends: POST /api/products/identify { image_b64: "..." }

3. Backend: nova/identifier.py
   Calls Nova Lite with image → returns { product_name: "Sony WH-1000XM5",
                                          search_query: "Sony WH1000XM5 headphones",
                                          confidence: "high" }

4. Extension shows: "Identified: Sony WH-1000XM5 (95% confidence)"
   User sees this in < 3 seconds

5. Extension opens WebSocket: WS /ws/search/{task_id}

6. Extension sends: POST /api/products/search { query: "Sony WH1000XM5", cards: ["hdfc-regalia"] }

7. Backend: orchestrator.py starts async task
   Spawns 2 threads: AmazonAgent + FlipkartAgent (parallel)
   Also: embeds user image via Nova Multimodal

8. Amazon agent finishes at ~30s:
   Backend sends over WS: { type: "agent_done", platform: "amazon", results: [...] }
   Extension immediately shows Amazon result card

9. Flipkart agent finishes at ~35s:
   Backend sends: { type: "agent_done", platform: "flipkart", results: [...] }
   Extension shows Flipkart card

10. Nova Multimodal validation completes:
    Filters out wrong variants from both platforms

11. Nova Pro reasoning (< 3 seconds):
    Backend sends: { type: "results", winner: { platform: "amazon", card: "hdfc-regalia",
                                                true_price: 21242, ... },
                                     reasoning: "Amazon wins because HDFC 15%..." }

12. Extension highlights winner with gold border, shows savings banner
    WebSocket: { type: "done" }

13. Voice announcement via /api/voice/ws:
    "Amazon wins at ₹21,242 with your HDFC card. You save ₹5,748."
    Audio plays in extension

Total user-perceived time: ~38 seconds
Amazon card appears progressively at ~30s — user doesn't wait for Flipkart
```

---

## Security Architecture

### What FareWise Never Touches
- **No card numbers** — user stores card *names* only ("HDFC Regalia"), never numbers
- **No payment flow** — clicking "Buy on Amazon" opens Amazon in a new tab; FareWise session is completely separate
- **No login** — FareWise has no user accounts; all preferences in `chrome.storage.local`
- **No persistent data** — each search is stateless; results not stored server-side after WebSocket closes

### Nova Act Sandboxing
- Each Nova Act session creates a fresh Chromium instance
- Sessions are destroyed after each search (no cookies/history persist)
- Agents are read-only: extract prices, never interact with cart/payment

### CORS Policy
```python
allow_origins=["chrome-extension://*", "http://localhost:*", "https://farewise.app"]
```
Only the Chrome extension origin and the web app domain can call the backend.

---

## Key Technical Decisions (and Why)

| Decision | What We Chose | Why Not Alternative |
|---|---|---|
| Parallel agents | `ThreadPoolExecutor` in FastAPI async | `asyncio.gather` alone can't run synchronous Nova Act; need thread pool to bridge sync→async |
| Product identification | Nova Lite (generative LLM) | Not Nova Multimodal Embeddings — embeddings need a pre-built catalog; Nova Lite needs nothing |
| SKU validation | Nova Multimodal Embeddings | Not Nova Lite — embedding cosine similarity is faster and cheaper than 10 LLM calls |
| Price reasoning | Nova Pro | Not hardcoded formulas — card rules are complex (caps, tiers, exclusions); LLM handles edge cases |
| Voice TTS (MVP) | Amazon Polly (Aditi neural) | Nova Sonic bidirectional streaming requires more setup; Polly is production-ready in 10 lines |
| WebSocket vs REST | WebSocket for search results | Progressive reveal requires server-push; polling adds 2s+ delay per result |
| Extension manifest | MV3 (Manifest V3) | MV2 is deprecated and will be removed from Chrome Store; MV3 is required for new extensions |
| Frontend (extension) | Vanilla HTML/CSS/JS | No build step needed; faster to iterate; extension side panel loads faster without a framework |

---

## Build Status (as of March 2026)

| Layer | Status | Files |
|---|---|---|
| Chrome Extension | ✅ Complete | `frontend_chrome_extension/` — manifest, popup, sidepanel, service-worker, onboarding, icons |
| Backend — FastAPI | ✅ Complete | `backend/main.py`, all routers |
| Backend — Nova Lite | ✅ Complete | `backend/nova/identifier.py` |
| Backend — Nova Multimodal | ✅ Complete | `backend/nova/validator.py` |
| Backend — Nova Pro | ✅ Complete | `backend/nova/reasoner.py` |
| Backend — Nova Sonic | ✅ Complete | `backend/routers/voice.py` (Polly MVP) |
| Backend — Nova Act Agents | ✅ Complete | `backend/agents/{amazon,flipkart,makemytrip,goibibo,cleartrip}.py` |
| Backend — Orchestrator | ✅ Complete | `backend/agents/orchestrator.py` |
| Bank Card Database | ✅ Complete | `backend/data/card_offers.json` (5 cards × 5 platforms) |
| Web App | ✅ Complete | `frontend_webapp/index.html` |
| Demo Video | ⏳ Pending | — |
| Devpost Submission | ⏳ Pending | — |
| Live AWS Integration | ⏳ Pending | Requires `.env` with real Nova Act API key + AWS credentials |
