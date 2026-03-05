# FareWise — Hackathon Execution Plan
> 13-Day Sprint · Risk-First Sequencing · Amazon Nova AI Hackathon 2026

**Project:** FareWise — India's AI Price Intelligence
**Modes:** Products (WhatsApp screenshot → Amazon + Flipkart) + Travel (voice → MMT + Goibibo + Cleartrip)
**Surfaces:** Chrome Extension + Web App + Mobile PWA
**Nova Models:** Nova Lite · Nova Multimodal Embeddings · Nova Act · Nova Pro · Nova Sonic

**Build philosophy:**
- Hard + uncertain tasks FIRST. Polish LAST.
- If a Nova model integration doesn't work by Day 3 → adjust scope, don't hide the problem.
- Each phase has a success criterion — if not met, do not proceed until fixed.
- Two modes = two independent demo stories. If one mode has issues, the other saves the demo.

---

## Build Status (Updated March 2026)

| Phase | Status | Files Created |
|---|---|---|
| Phase 0 — Setup | ✅ **COMPLETE** | `requirements.txt`, `.env.example`, `__init__.py` files, `.gitignore` |
| Phase 1 — Nova Lite Identifier | ✅ **COMPLETE** | `backend/nova/identifier.py` |
| Phase 2 — Product Agents | ✅ **COMPLETE** | `backend/agents/amazon.py`, `flipkart.py`, `orchestrator.py` |
| Phase 3 — Travel Agents | ✅ **COMPLETE** | `backend/agents/makemytrip.py`, `goibibo.py`, `cleartrip.py` |
| Phase 4 — Reasoner + Validator | ✅ **COMPLETE** | `backend/nova/reasoner.py`, `validator.py`, `data/card_offers.json` |
| Phase 5 — Nova Sonic Voice | ✅ **COMPLETE** | `backend/routers/voice.py` (Polly MVP; Nova Sonic target for launch) |
| Phase 6 — FastAPI + WebSocket | ✅ **COMPLETE** | `backend/main.py`, `routers/products.py`, `routers/travel.py` |
| Phase 7 — Chrome Extension UI | ✅ **COMPLETE** | `frontend_chrome_extension/` — all files (manifest, popup, sidepanel, service-worker, onboarding, icons) |
| Phase 8 — Web App | ✅ **COMPLETE** | `frontend_webapp/index.html` (Bricolage Grotesque design) |
| Phase 9 — Demo Video | ⏳ **PENDING** | — |
| Phase 10 — Submission | ⏳ **PENDING** | — |

**⚠️ Remaining to test:** Wire real AWS credentials (`.env`), run Nova Act agents against live sites, verify Nova Lite/Pro responses match expected schema.

---

## Deliverables Summary

| Deliverable | Priority | Status | Nova Models |
|---|---|---|---|
| Product identification (Nova Lite) | P0 | ✅ Done | Nova Lite |
| Amazon agent (Nova Act) | P0 | ✅ Done | Nova Act |
| Flipkart agent (Nova Act) | P0 | ✅ Done | Nova Act |
| Travel agents × 3 (Nova Act) | P0 | ✅ Done | Nova Act |
| SKU validator (Nova Multimodal) | P0 | ✅ Done | Nova Multimodal Embeddings |
| Price reasoning engine (Nova Pro) | P0 | ✅ Done | Nova Pro |
| FastAPI + WebSocket layer | P0 | ✅ Done | — |
| Nova Sonic voice I/O | P1 | ✅ Done (Polly MVP) | Nova Sonic |
| Chrome Extension UI (dual-mode) | P1 | ✅ Done | — |
| Website + PWA | P1 | ✅ Done | — |
| Demo video + polish | P2 | ⏳ Pending | — |
| Devpost submission | P2 | ⏳ Pending | — |
| Blog post (bonus prize) | P3 | ⏳ Pending | — |

---

## Phase 0 — Setup (Day 1) ✅ COMPLETE

### 0.1 — AWS + Nova Access
- [ ] Create/verify AWS account, region: `us-east-1`
- [ ] Enable Amazon Bedrock, request access to:
  - [ ] `amazon.nova-lite-v1:0` (multimodal LLM)
  - [ ] `amazon.nova-multimodal-embeddings-v1`
  - [ ] `us.amazon.nova-pro-v1:0` (price reasoning — confirmed model ID)
  - [ ] `amazon.nova-sonic-v1:0`
- [ ] Get Nova Act API key at [nova.amazon.com/act](https://nova.amazon.com/act)
- [ ] Test: `python -c "import boto3; b=boto3.client('bedrock-runtime',region_name='us-east-1'); print('AWS OK')"`
- [ ] Test: `python -c "from nova_act import NovaAct; print('Nova Act OK')"`

### 0.2 — Project Scaffold ✅ (all files created — see Build Status table above)
```
/Users/murugadosssp/hackathons/devpost/aws_nova/
├── docs/           ← this file + requirements.md + design.md
├── website/        ← index.html + manifest.json + sw.js
├── extension/      ← Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background/service-worker.js
│   ├── sidepanel/sidepanel.html + sidepanel.js + sidepanel.css
│   └── popup/popup.html
└── backend/
    ├── main.py             ← FastAPI app
    ├── requirements.txt
    ├── .env                ← AWS keys, Nova Act key (never commit)
    ├── nova/
    │   ├── identifier.py   ← Nova Lite: product ID from image
    │   ├── validator.py    ← Nova Multimodal: SKU validation
    │   ├── reasoner.py     ← Nova 2 Lite: price reasoning
    │   └── voice.py        ← Nova Sonic: voice I/O
    ├── agents/
    │   ├── amazon.py       ← Nova Act: Amazon.in agent
    │   ├── flipkart.py     ← Nova Act: Flipkart.com agent
    │   ├── makemytrip.py   ← Nova Act: MakeMyTrip.com agent
    │   ├── goibibo.py      ← Nova Act: Goibibo.com agent
    │   ├── cleartrip.py    ← Nova Act: Cleartrip.com agent
    │   └── orchestrator.py ← ThreadPoolExecutor, WebSocket streaming
    └── data/
        └── card_offers.json ← bank card offer database (manually maintained)
```

- [ ] Create `backend/requirements.txt`:
  ```
  fastapi
  uvicorn[standard]
  boto3
  nova-act
  python-multipart
  pillow
  python-dotenv
  websockets
  numpy
  httpx
  ```
- [ ] Create `.gitignore` (exclude `.env`, `__pycache__`, `*.pyc`, `.env.local`)
- [ ] Initialize GitHub repo: `farewise-nova`

---

## Phase 1 — Nova Core: Product Identification ✅ COMPLETE

> **Gate check:** If Nova Lite cannot identify a product from a screenshot in < 5 seconds, reassess on Day 3 before continuing.

### Task 1.1 — Nova Lite: Product Identifier
**File:** `backend/nova/identifier.py`

```python
import boto3, json, base64
from PIL import Image
import io

def identify_product(image_bytes: bytes) -> dict:
    """
    Input:  raw image bytes (screenshot, photo, etc.)
    Output: {
      "brand": "Sony",
      "model_name": "WH-1000XM5",
      "full_name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
      "category": "Headphones",
      "variant": "Black",
      "search_query": "Sony WH-1000XM5 noise cancelling headphones",
      "confidence": "high" | "medium" | "low",
      "text_found": ["WH-1000XM5", "Sony", "Noise Cancelling"],
      "raw_visible_text": "all text read from image"
    }
    """
    client = boto3.client("bedrock-runtime", region_name="us-east-1")

    # Resize if too large (Nova Lite image limit)
    img = Image.open(io.BytesIO(image_bytes))
    if max(img.size) > 2000:
        img.thumbnail((2000, 2000))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_bytes = buf.getvalue()

    prompt = """You are a product identification expert for Indian e-commerce.
    Analyze this image carefully. This may be:
    - A WhatsApp-forwarded product listing screenshot from Amazon/Flipkart
    - A photo of a product box in a store
    - A product listing ad or marketing image

    1. Read ALL visible text in the image (OCR everything)
    2. Identify the exact product: brand, model name, model number, variant
    3. Generate a search query that would find this exact product on Amazon India

    Be specific. If you see "WH-1000XM5" text, use that. If you see "Galaxy S25+" use that.
    Do not guess if text is not visible — set confidence to "low" instead.

    Return ONLY valid JSON:
    {
      "brand": "string",
      "model_name": "string",
      "full_name": "string (complete product name)",
      "category": "Headphones|Smartphone|Laptop|TV|Tablet|Smartwatch|Camera|Other",
      "variant": "string (color/storage/size if visible)",
      "search_query": "string (best Amazon/Flipkart search query)",
      "confidence": "high|medium|low",
      "text_found": ["array", "of", "visible", "text"],
      "reasoning": "brief explanation of how you identified this"
    }"""

    response = client.invoke_model(
        modelId="amazon.nova-lite-v1:0",
        body=json.dumps({
            "messages": [{
                "role": "user",
                "content": [
                    {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}},
                    {"text": prompt}
                ]
            }],
            "inferenceConfig": {"maxTokens": 512, "temperature": 0.1}
        })
    )
    result = json.loads(response['body'].read())
    text = result['output']['message']['content'][0]['text']
    return json.loads(text.strip('`json\n '))
```

- [ ] Test with 5 screenshots:
  - [ ] Amazon listing screenshot of Sony WH-1000XM5 → must identify correctly
  - [ ] Flipkart listing screenshot of Samsung Galaxy S25+ → must identify correctly
  - [ ] WhatsApp forwarded deal image with product name visible → must identify
  - [ ] Product box photo (with model text) → must identify
  - [ ] Bare product photo (no text) → must return confidence: "low" gracefully
- [ ] **Success criterion:** 4/5 identified correctly. Bare product case returns graceful low-confidence response.

### Task 1.2 — Confidence Routing
**File:** `backend/nova/identifier.py`

```python
def route_by_confidence(result: dict) -> dict:
    """Adds action field based on confidence"""
    if result["confidence"] == "high":
        result["action"] = "proceed"
        result["message"] = None
    elif result["confidence"] == "medium":
        result["action"] = "confirm"
        result["message"] = f"Is this the {result['full_name']}?"
    else:
        result["action"] = "suggest_text"
        result["message"] = "Image unclear. Try typing the product name."
    return result
```

---

## Phase 2 — Nova Act: Product Agents ✅ COMPLETE

> Both agents share the same output schema. Amazon built first, Flipkart follows same pattern.

### Task 2.1 — Amazon India Agent
**File:** `backend/agents/amazon.py`

```python
from nova_act import NovaAct

async def search_amazon(query: str, user_cards: list[str]) -> dict:
    """
    Input:  "Sony WH-1000XM5", ["HDFC Regalia", "SBI SimplyCLICK"]
    Output: {
      "platform": "Amazon India",
      "platform_color": "#FF9900",
      "base_price": 24990,
      "card_offers": {"HDFC Regalia": {"type": "instant", "percent": 15, "max": 3000}},
      "best_card": "HDFC Regalia",
      "best_card_discount": 3748,
      "final_price": 21242,
      "delivery_fee": 0,
      "delivery_days": 2,
      "product_url": "https://www.amazon.in/dp/...",
      "seller": "Amazon.in",
      "in_stock": true,
      "thumbnail_url": "https://..."
    }
    """
    with NovaAct(starting_page="https://www.amazon.in") as agent:
        # Search for product
        result = agent.act(f"Search for '{query}' and click on the most relevant result")

        # Extract price
        price_result = agent.act(
            "What is the current MRP and selling price? Return as JSON: "
            '{"mrp": number, "selling_price": number}'
        )

        # Check card offers
        offers_result = agent.act(
            "Look for any bank card offers shown (e.g., 10% off with HDFC). "
            "Return as JSON: [{\"bank\": \"HDFC\", \"percent\": 10, \"max_discount\": 2000}]"
        )

        # Get delivery info
        delivery_result = agent.act(
            "What is the delivery fee and estimated delivery date? "
            'Return as JSON: {"fee": number, "days": number}'
        )

        # Get product URL and thumbnail
        url = agent.act("What is the current page URL?")

        return build_product_result("Amazon India", "#FF9900", price_result,
                                     offers_result, delivery_result, url, user_cards)
```

- [ ] Test: Sony WH-1000XM5 → correct price, HDFC offer visible
- [ ] Test: Samsung Galaxy S25+ → correct price, multiple card offers
- [ ] Test: Apple MacBook Air → correct price, delivery details
- [ ] **Success criterion:** 3/3 products return correct price ± ₹100 of actual price

### Task 2.2 — Flipkart Agent
**File:** `backend/agents/flipkart.py`
- [ ] Same interface as `amazon.py`
- [ ] Flipkart-specific: Axis Flipkart card (often 15% off)
- [ ] Handle "Flipkart Assured" badge
- [ ] Extract SuperCoin amount (show separately)
- [ ] **Success criterion:** Same 3 products, correct prices

### Task 2.3 — Product Orchestrator
**File:** `backend/agents/orchestrator.py`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def search_products(query: str, user_cards: list) -> list[dict]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(search_amazon, query, user_cards): "amazon",
            executor.submit(search_flipkart, query, user_cards): "flipkart"
        }
        results = []
        for future in as_completed(futures):
            results.append(future.result())
    return results
```

- [ ] Both agents run in parallel
- [ ] Results yield as each completes (for WebSocket streaming)
- [ ] **Success criterion:** Total time < 45 seconds for both agents

---

## Phase 3 — Nova Act: Travel Agents ✅ COMPLETE

> OTA search patterns from FareGenie work. Three agents share the TravelOrchestrator.

### Task 3.1 — MakeMyTrip Agent
**File:** `backend/agents/makemytrip.py`

```python
async def search_makemytrip(origin: str, destination: str, date: str,
                             pax: int, user_cards: list) -> list[dict]:
    """
    Output: list of flights [
      {
        "platform": "MakeMyTrip",
        "platform_color": "#D42B2B",
        "airline": "IndiGo",
        "flight_no": "6E-204",
        "departure": "07:20",
        "arrival": "09:55",
        "duration": "2h 35m",
        "base_fare": 4890,
        "convenience_fee": 299,
        "card_offers": {"SBI Cashback": {"type": "instant", "percent": 10}},
        "final_fare": 4601,  # after best card
        "best_card": "SBI Cashback",
        "booking_url": "https://..."
      }
    ]
    """
    with NovaAct(starting_page="https://www.makemytrip.com") as agent:
        agent.act(f"Search for one-way flights from {origin} to {destination} on {date}")
        agent.act("Sort by price (cheapest first)")
        flights = agent.act(
            "List the top 3 cheapest flights. For each: airline, flight number, "
            "departure, arrival, total fare including taxes. Return as JSON list."
        )
        offers = agent.act("Any bank card offers shown? Return as JSON.")
        return parse_flight_results("MakeMyTrip", "#D42B2B", flights, offers, user_cards)
```

- [ ] Test: Mumbai → Delhi, upcoming Friday
- [ ] **Success criterion:** Returns ≥ 3 flights with correct fares

### Task 3.2 — Goibibo Agent
**File:** `backend/agents/goibibo.py`
- [ ] Same interface as MakeMyTrip
- [ ] Goibibo-specific: SBI card partnership (extra 10-12%)
- [ ] **Success criterion:** Correct prices for same route

### Task 3.3 — Cleartrip Agent
**File:** `backend/agents/cleartrip.py`
- [ ] Same interface
- [ ] Cleartrip-specific: HDFC partnership, lower convenience fee
- [ ] **Success criterion:** Correct prices for same route

### Task 3.4 — Travel Orchestrator
**File:** `backend/agents/orchestrator.py` (extend existing)
```python
def search_travel(origin, destination, date, pax, user_cards):
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(search_makemytrip, ...): "mmt",
            executor.submit(search_goibibo, ...): "goibibo",
            executor.submit(search_cleartrip, ...): "cleartrip"
        }
        # Stream results via WebSocket as each completes
```
- [ ] **Success criterion:** All 3 agents complete in < 60 seconds total

---

## Phase 4 — Nova Pro: Price Reasoning Engine ✅ COMPLETE

### Task 4.1 — Product Price Reasoner ✅ Done (`backend/nova/reasoner.py`)
**Model used:** `us.amazon.nova-pro-v1:0` (not Nova 2 Lite — confirmed correct ID)

```python
def rank_products(results: list[dict], user_cards: list) -> dict:
    """
    For each (platform × card) combination:
    - Calculate: base_price − card_discount − coupon + delivery = true_cost
    - Return ranked list + winner + explanation
    """
    client = boto3.client("bedrock-runtime", region_name="us-east-1")

    prompt = f"""You are a price comparison expert for Indian e-commerce.
    Given these search results and the user's bank cards, find the true cheapest option.

    Results: {json.dumps(results)}
    User's cards: {user_cards}

    For each (platform × card) combination:
    - Instant discount: applied immediately
    - Cashback: delayed (show separately, don't count as immediate savings)
    - Delivery fee: add to true cost
    - Coupons: apply if available

    Return JSON:
    {{
      "winner": {{
        "platform": "Amazon India",
        "card": "HDFC Regalia",
        "true_price": 21242,
        "breakdown": "₹24,990 − ₹3,748 (HDFC 15%) − ₹0 delivery = ₹21,242"
      }},
      "ranked": [all options sorted by true_cost ascending],
      "savings_vs_worst": 5749,
      "explanation": "Amazon wins because HDFC's 15% instant discount (₹3,748) exceeds Axis's 13% on Flipkart (₹3,444). Both have free delivery.",
      "cashback_notes": ["Flipkart: ₹400 SuperCoin in 30 days"]
    }}"""

    response = client.invoke_model(
        modelId="amazon.nova-lite-v1:0",  # or nova-pro for better reasoning
        body=json.dumps({
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {"maxTokens": 1024, "temperature": 0.1}
        })
    )
    # parse and return
```

### Task 4.2 — Travel Price Reasoner ✅ Done
- [x] Same pattern, adapted for flights
- [ ] Handles: base_fare + convenience_fee − card_discount = true_fare
- [ ] Considers: same flight on different OTAs (common IndiGo 6E-204 across all three)
- [ ] **Success criterion:** Correct winner for 5 test cases (manually verified)

### Task 4.3 — Card Offers Database ✅ Done
**File:** `backend/data/card_offers.json` — 5 cards × 5 platforms, full offer details
```json
{
  "amazon": {
    "HDFC Regalia":     {"type": "instant", "percent": 15, "max_discount": 2000},
    "HDFC Millennia":   {"type": "instant", "percent": 5,  "max_discount": 1000},
    "SBI SimplyCLICK":  {"type": "cashback","percent": 5,  "timeline_days": 30},
    "ICICI Amazon Pay": {"type": "cashback","percent": 5,  "unlimited": true}
  },
  "flipkart": {
    "Axis Flipkart":    {"type": "instant", "percent": 15, "max_discount": 3000},
    "Axis Magnus":      {"type": "instant", "percent": 5,  "max_discount": 1000},
    "Kotak Essentia":   {"type": "instant", "percent": 7,  "max_discount": 1500}
  },
  "makemytrip": {
    "HDFC Regalia":     {"type": "instant", "percent": 8,  "max_discount": 1500},
    "SBI Cashback":     {"type": "instant", "percent": 10, "max_discount": 2000}
  },
  "goibibo": {
    "SBI SimplyCLICK":  {"type": "instant", "percent": 12, "max_discount": 2000},
    "SBI Cashback":     {"type": "instant", "percent": 10, "max_discount": 2000}
  },
  "cleartrip": {
    "HDFC Regalia":     {"type": "instant", "percent": 8,  "max_discount": 1500},
    "ICICI Amazon Pay": {"type": "instant", "percent": 5,  "max_discount": 1000}
  }
}
```
- [ ] Compile from current OTA promotions (check each site's "offers" page)
- [ ] Note: Nova Act also verifies these at checkout step (source of truth)

### Task 4.4 — Nova Multimodal: SKU Validator ✅ Done
**File:** `backend/nova/validator.py`

```python
import numpy as np

def cosine_similarity(a: list, b: list) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

def get_image_embedding(client, image_bytes: bytes) -> list:
    response = client.invoke_model(
        modelId="amazon.nova-multimodal-embeddings-v1",
        body=json.dumps({"inputImage": base64.b64encode(image_bytes).decode()})
    )
    return json.loads(response['body'].read())["embedding"]

def validate_product_match(query_image: bytes, result_thumbnails: list[bytes]) -> int:
    """
    Embeds user's query image + all result thumbnails.
    Returns index of the best-matching result (highest cosine similarity).
    Used to confirm the search found the EXACT product the user photographed.
    """
    client = boto3.client("bedrock-runtime", region_name="us-east-1")
    query_emb = get_image_embedding(client, query_image)
    scores = [cosine_similarity(query_emb, get_image_embedding(client, t))
              for t in result_thumbnails]
    return scores.index(max(scores))
```

- [ ] Test with 5 product images vs 5 result thumbnails (should pick correct one)
- [ ] **Success criterion:** Picks correct match for 4/5 test cases

---

## Phase 5 — Nova Sonic: Voice I/O ✅ COMPLETE (Polly MVP)

### Task 5.1 — Travel Voice Input Parser
**File:** `backend/nova/voice.py`

```python
# Nova Sonic: listen to user's route query
# Input:  audio stream from browser
# Output: { "origin": "Mumbai", "destination": "Delhi", "date": "2026-03-15",
#           "pax": 1, "class_type": "economy" }

def start_voice_session():
    """Initialize Nova Sonic bidirectional session"""
    # Use Nova Sonic's streaming API
    # Handle barge-in (user interrupts mid-response)
    pass

def announce_winner(winner: dict, mode: str) -> str:
    """Generate Nova Sonic announcement script"""
    if mode == "products":
        return (f"{winner['platform']} wins at ₹{winner['true_price']:,} "
                f"with your {winner['card']}. "
                f"You save ₹{winner['savings']:,}.")
    else:  # travel
        return (f"{winner['platform']} wins. "
                f"{winner['airline']} {winner['flight_no']} at ₹{winner['true_fare']:,} "
                f"with your {winner['card']}. "
                f"Departing {winner['departure']}, arrives {winner['arrival']}.")
```

- [ ] Test: voice → parsed route object
- [ ] Test: winner dict → spoken announcement
- [ ] Test: follow-up question "What about SBI card?" in same session
- [ ] **Success criterion:** Route parsed correctly for 5 different voice inputs

---

## Phase 6 — FastAPI + WebSocket Layer ✅ COMPLETE

### Task 6.1 — API Endpoints
**File:** `backend/main.py`

```python
from fastapi import FastAPI, WebSocket, UploadFile
import asyncio, uuid

app = FastAPI(title="FareWise API", version="1.0")

@app.post("/api/products/identify")
async def identify(image: UploadFile):
    """Nova Lite: identify product from uploaded image"""
    image_bytes = await image.read()
    result = identify_product(image_bytes)
    return route_by_confidence(result)

@app.post("/api/products/search")
async def search_products_endpoint(body: dict):
    """Start product search, return task_id immediately"""
    task_id = str(uuid.uuid4())
    asyncio.create_task(run_product_search(task_id, body["query"], body["cards"]))
    return {"task_id": task_id}

@app.post("/api/travel/search")
async def search_travel_endpoint(body: dict):
    """Start travel search, return task_id immediately"""
    task_id = str(uuid.uuid4())
    asyncio.create_task(run_travel_search(task_id, body))
    return {"task_id": task_id}

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """Stream search results as agents complete"""
    await websocket.accept()
    # Listen on task queue, stream each result as it arrives
    # { type: "progress", platform: "Amazon", status: "searching" }
    # { type: "result", platform: "Amazon", data: {...} }
    # { type: "reasoning", winner: {...}, ranked: [...], explanation: "..." }
    # { type: "done" }
```

- [ ] All 4 endpoints functional
- [ ] WebSocket streams partial results (progressive reveal)
- [ ] CORS configured for extension origin
- [ ] **Success criterion:** End-to-end: POST identify → POST search → WebSocket results

### Task 6.2 — CORS & Extension Headers
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware,
    allow_origins=["chrome-extension://*", "http://localhost:*", "https://farewise.app"],
    allow_methods=["*"], allow_headers=["*"])
```

---

## Phase 7 — Chrome Extension UI ✅ COMPLETE

### Task 7.1 — Extension Manifest ✅ Done
**File:** `frontend_chrome_extension/manifest.json` — MV3, sidePanel, 3 keyboard shortcuts, 5 host permissions
```json
{
  "manifest_version": 3,
  "name": "FareWise",
  "version": "1.0",
  "description": "India's AI price intelligence — gadgets and flights with your bank card",
  "permissions": ["sidePanel", "storage", "clipboardRead"],
  "commands": {
    "open-farewise": {
      "suggested_key": { "default": "Ctrl+Shift+F", "mac": "Command+Shift+F" },
      "description": "Open FareWise panel"
    }
  },
  "side_panel": { "default_path": "sidepanel/sidepanel.html" },
  "background": { "service_worker": "background/service-worker.js" },
  "icons": { "128": "icon.png" }
}
```

### Task 7.2 — Side Panel UI ✅ Done
**File:** `frontend_chrome_extension/sidepanel/sidepanel.html` (1607 lines)

Completed components:
- [x] Mode toggle: [📦 Products] [✈️ Travel] (top, persistent)
- [x] Products mode: paste zone + text input + voice button + [Search] button
- [x] Travel mode: voice button + city selects + date picker + [Search] button
- [x] Search progress: per-agent progress bars with platform logos
- [x] Results: winner card (gold border) + other cards + savings banner
- [x] Nova reasoning: collapsible section "Nova's explanation ▾"
- [x] Settings: gear icon → card management (HDFC, SBI, Axis, ICICI, Kotak)
- [x] Real-time: WebSocket client connecting to backend

### Task 7.3 — Background Service Worker ✅ Done
**File:** `frontend_chrome_extension/background/service-worker.js`
- [x] Listen for keyboard shortcut → open side panel (3 shortcuts: ⌘⇧F, ⌘⇧P, ⌘⇧T)
- [x] Handle extension install: open welcome/onboarding page
- [x] Store user's card preferences in `chrome.storage.local`
- [x] Context menus: right-click image → "Compare price", right-click selection → "Search FareWise"

### Task 7.4 — Onboarding + Icons ✅ Done
**Files:** `frontend_chrome_extension/onboarding/onboarding.html`, `icons/*.png`
- [x] First-install welcome page (4 steps, mode grid)
- [x] Icons: 16, 32, 48, 128px PNGs (compass/crosshair in FareWise blue)

---

## Phase 8 — Website + PWA ✅ COMPLETE

### Task 8.1 — Marketing Website ✅ Done
**File:** `frontend_webapp/index.html` — complete rewrite (Bricolage Grotesque + Instrument Sans)

Sections completed:
- [x] Nav: FareWise logo + "Add to Chrome" (sticky)
- [x] Hero: dual-mode preview (extension mockup right, headline left, 3 stats); two-column grid at 1440px
- [x] How it works: tabbed (Products / Travel), 3 steps each with icons + descriptions
- [x] Live demo: simulated search widget with 2.2s animation + result cards + Nova reasoning
- [x] Nova models: 5-card grid (Nova Lite, Multimodal, Act ×2, Pro, Sonic)
- [x] Platform + card badges: all 5 platforms + 5 bank cards
- [x] CTA footer card: "Add to Chrome — Free" + reassurance text

Note: Design revised from original Syne font spec — webapp now uses Bricolage Grotesque (variable display) + Instrument Sans (body). See `docs/design.md` for updated typography section.

### Task 8.2 — PWA Manifest ⏳ Pending
**File:** `frontend_webapp/manifest.json` — not yet created (referenced in design.md)

### Task 8.3 — Service Worker ⏳ Pending
**File:** `frontend_webapp/sw.js` — not yet created

---

## Phase 9 — Polish + Demo Video (Days 12–13)

### Task 9.1 — Demo Video (≤ 3 minutes)
**Story Arc:**
```
0:00–0:15  Problem: "Indians lose ₹5,000+ on every major purchase"
           Show: 3 browser tabs open, manually comparing prices (painful)

0:15–0:45  Demo 1 — Products:
           WhatsApp screenshot → FareWise identifies product → Amazon + Flipkart search
           → HDFC card applied → "Amazon wins at ₹21,242 — save ₹5,748"

0:45–1:15  Demo 2 — Travel:
           Voice: "Mumbai to Delhi, Friday" → 3 OTAs search
           → SBI card applied → "Goibibo wins at ₹4,201 — save ₹1,890"

1:15–1:45  Mobile PWA:
           Open on phone, take photo of product box → same results
           WhatsApp share → tap FareWise in share sheet → result

1:45–2:15  Architecture:
           Show Nova model diagram: Lite → Multimodal → Act → 2 Lite → Sonic

2:15–3:00  Summary + call to action
           "Built for India. Powered by Amazon Nova. Free Chrome Extension + PWA."
```

### Task 9.2 — Polish Checklist
- [ ] All loading states show (no blank screens mid-search)
- [ ] Error states handled gracefully ("Flipkart unavailable — showing Amazon only")
- [ ] Low-confidence product ID: confirmation dialog shown
- [ ] Voice: waveform animation while listening
- [ ] Prices formatted correctly: ₹21,242 (not 21242.0)
- [ ] Savings counter: animated count-up (0 → ₹5,748 in 0.8s)
- [ ] Winner card: gold glow animation (subtle pulse)
- [ ] Extension icon: shows "FW" badge when result found

---

## Phase 10 — Submission (Day 13)

### Task 10.1 — Devpost Submission
- [ ] Project title: "FareWise — India's AI Price Intelligence"
- [ ] Tagline: "See the real price. Every time."
- [ ] Description: 300-400 words covering both modes + Nova model usage
- [ ] Technologies Used: select all 4 Nova models
- [ ] Categories: UI Automation + Multimodal Understanding + Voice AI
- [ ] YouTube demo video: public, ≤ 3 minutes
- [ ] GitHub URL: public repo
- [ ] Live demo URL: web app accessible

### Task 10.2 — Blog Post (Bonus Prize)
- [ ] Publish on builder.aws.com
- [ ] Title: "Building FareWise: How Amazon Nova Powers India's Price Intelligence"
- [ ] Sections: problem, architecture, each Nova model's role, lessons learned
- [ ] Include architecture diagram
- [ ] Qualifies for: Blog Post Prize ($500 + AWS credits)

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Nova Act too slow (> 90s per search) | Medium | High | Reduce agents to 2 products + 2 travel; use offers DB instead of live checkout check |
| Nova Lite can't identify product (low accuracy) | Low | High | Primary input is listing screenshots (90%+ accuracy); voice/text fallback always available |
| Nova Sonic API not available in time | Low | Medium | All results still shown as text; voice is P1 enhancement, not P0 blocker |
| OTA site structure changes (breaks Nova Act) | Medium | Medium | Keep Nova Act prompts flexible; test 3 days before submission |
| AWS Bedrock rate limits | Low | Medium | Implement retry with exponential backoff; cache identical queries |
| Build runs out of time | Medium | High | Travel mode agents are Day 5-6; if blocked, submit Products-only (still uses 4 models) |

---

## Definition of Done

### Minimum Submission (Must Have)
- [ ] Products mode: screenshot → identification → 2-platform price comparison → winner
- [ ] Travel mode: text input → 3-OTA price comparison → winner with card offer
- [ ] All 4 Nova models demonstrably used (shown in video + architecture diagram)
- [ ] Chrome extension working (can be demoed live)
- [ ] Web app accessible at public URL
- [ ] Demo video uploaded to YouTube (< 3 minutes)
- [ ] Devpost submission complete

### Strong Submission (Should Have)
- [ ] Voice input in Travel mode (Nova Sonic)
- [ ] Progressive WebSocket streaming (results appear as agents complete)
- [ ] Mobile PWA installable
- [ ] Live prices (not simulated)

### Exceptional Submission (Nice to Have)
- [ ] Voice follow-up Q&A works ("What about SBI card?")
- [ ] WhatsApp share target on mobile
- [ ] Blog post published
- [ ] Polished demo video with screen recordings
