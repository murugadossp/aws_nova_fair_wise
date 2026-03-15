# FareWise Backend — Setup Guide

Complete steps to go from zero to a live, working backend.

---

## Step 1 — AWS Account & Credentials

### 1A. Create IAM User (skip if you already have AWS CLI configured)

1. Open https://console.aws.amazon.com/iam/
2. **Users → Create user**
   - Username: `farewise-dev`
   - Access type: **Programmatic access**
3. **Attach policies directly** → search and add:
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess` (or a scoped policy for the Nova Act S3 bucket)
4. **Create user → Download CSV** (or copy Access Key ID + Secret)

### 1B. Check if credentials are already configured

```bash
cat ~/.aws/credentials
```

If you see `[default]` with `aws_access_key_id` and `aws_secret_access_key`, you can skip to Step 2.

### 1C. Configure AWS CLI

```bash
aws configure
```

Enter when prompted:
```
AWS Access Key ID:     AKIA...
AWS Secret Access Key: your_secret...
Default region name:   us-east-1
Default output format: json
```

> **Region must be us-east-1** — Nova Act only runs in us-east-1.

---

## Step 2 — Enable Bedrock Model Access

Nova models are **not enabled by default**. You must request access manually.

1. Open https://console.aws.amazon.com/bedrock/
2. Left sidebar → **Model access**
3. Click **Modify model access**
4. Check all four:
   - ✅ Amazon Nova Lite
   - ✅ Amazon Nova Multimodal Embeddings (or Titan Multimodal Embeddings as fallback)
   - ✅ Amazon Nova Pro
   - ✅ Amazon Nova Sonic
5. Click **Save changes**

Access is usually instant for Nova models (no review needed).

---

## Step 3 — Nova Act Authentication (IAM mode)

FareWise uses **IAM authentication** for Nova Act — no separate API key needed. The travel agents (MakeMyTrip, Cleartrip, Ixigo) use the `Workflow` class with your existing AWS credentials from Step 1.

Each agent calls `nova_auth.get_or_create_workflow_definition(name)` which registers a workflow definition in AWS (like `farewise-cleartrip`) on the first run and caches it in memory. Subsequent calls skip the AWS check.

**S3 bucket:** Workflow definitions require an S3 bucket for artifact storage. Create one in us-east-1:

```bash
aws s3 mb s3://farewise-nova --region us-east-1
```

Then set `NOVA_ACT_S3_BUCKET=farewise-nova` in your `.env` (see Step 4).

> **Note:** `NOVA_ACT_API_KEY` is **not** used by the travel agents and is actively removed from the environment before each agent run to prevent conflicts with IAM credentials. You do not need to obtain an API key.

---

## Step 4 — Create the .env File

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend

cp .env.example .env
```

Open `.env` and fill in your values:

```env
# AWS credentials (IAM user with AmazonBedrockFullAccess)
AWS_ACCESS_KEY_ID=AKIA...your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
AWS_DEFAULT_REGION=us-east-1

# Nova Act workflow management (IAM mode — no API key needed)
NOVA_ACT_S3_BUCKET=farewise-nova       # S3 bucket created in Step 3

# Optional: override default workflow names
# NOVA_ACT_WORKFLOW_MMT=farewise-makemytrip
# NOVA_ACT_WORKFLOW_CLEARTRIP=farewise-cleartrip
# NOVA_ACT_WORKFLOW_IXIGO=farewise-ixigo

# Server settings
FAREWISE_PORT=8000
FAREWISE_CORS_ORIGINS=chrome-extension://*,http://localhost:*,http://127.0.0.1:*

# Optional: show Nova Act browser window while tests run
# FAREWISE_HEADED=1

# Optional: increase Nova Act max steps per agent (default 50)
# NOVA_ACT_MAX_STEPS=50
```

---

## Step 5 — Create Python Virtual Environment

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend

/opt/homebrew/bin/python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` in your shell prompt.

---

## Step 6 — Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `fastapi` + `uvicorn` — web framework
- `boto3` — AWS SDK for Bedrock (Nova Lite, Multimodal, Pro)
- `nova-act` — Nova Act SDK (downloads a bundled Chromium ~200MB, first run takes 2–3 min)
- `Pillow` + `numpy` — image processing and cosine similarity
- `python-dotenv` — loads the `.env` file

---

## Step 7 — Verify Installation

```bash
# Confirm boto3 can see your credentials
python3 -c "import boto3; print(boto3.client('sts').get_caller_identity())"
```

Expected output:
```json
{"UserId": "AIDA...", "Account": "123456789012", "Arn": "arn:aws:iam::..."}
```

If you get a credential error, re-check Step 4 (`.env` file) or Step 1C (AWS configure).

---

## Step 8 — Start the Backend

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend
source .venv/bin/activate

uvicorn main:app --reload --port 8000
```

Expected output:
```
[FareWise] Starting up — warming Nova clients...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

## Step 9 — Verify the Backend is Live

```bash
curl http://localhost:8000/health
```

Expected:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "nova_models": ["nova-lite-v1", "nova-multimodal", "nova-pro-v1", "nova-sonic"]
}
```

---

## Step 10 — Run the Agent Tests

### Option A — `run_test.sh` (recommended)

`run_test.sh` handles venv activation, `.env` loading, banner printing, and elapsed time
reporting automatically. Run it from the `backend/` directory:

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend

# Quick smoke test: Nova model validation only (~30-60s, no browser)
./run_test.sh nova

# Ixigo E2E — Phase 1 only (~3-4 min, no booking funnel)
./run_test.sh ixigo --phase1-only

# Ixigo E2E — all 7 tests (~8-10 min)
./run_test.sh ixigo

# Show the Nova Act browser while tests run
./run_test.sh ixigo --headed

# Full test suite (CI / pre-push)
./run_test.sh
```

For the complete flag reference and test documentation, see **[docs/TESTING.md](docs/TESTING.md)**.

### Option B — direct Python (per-component)

Open a second terminal tab (keep uvicorn running in the first):

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend
source .venv/bin/activate

# Nova model tests (no browser):
python3 tests/test_nova_identifier.py    # Nova Lite — product ID from text
python3 tests/test_nova_planner.py       # Nova Lite — NL query → structured plan
python3 tests/test_nova_reasoner.py      # Nova Pro — price + card math

# Ixigo E2E tests (browser required):
python3 tests/test_ixigo_e2e.py                   # full suite — all 7 tests
python3 tests/test_ixigo_e2e.py --phase1-only     # Phase 1 only (fast)
python3 tests/test_ixigo_e2e.py --skip-orchestrator  # skip the slowest test

# Individual agent tests:
python3 tests/test_amazon_agent.py       # Nova Act — live Amazon search
python3 tests/test_flipkart_agent.py     # Nova Act — live Flipkart search
python3 tests/test_makemytrip_agent.py   # Nova Act — live MakeMyTrip search
python3 tests/test_cleartrip_agent.py    # Nova Act — live Cleartrip search
python3 tests/test_ixigo_agent.py        # Nova Act — live Ixigo search
```

To see the Nova Act browser window while tests run (watch the agent interact with the page), set `FAREWISE_HEADED=1` in your `.env` file, or before running, e.g.:

```bash
# Option 1: add to .env
# FAREWISE_HEADED=1

# Option 2: inline when running
FAREWISE_HEADED=1 python3 tests/test_ixigo_e2e.py
FAREWISE_HEADED=1 ./tests/run_agent.sh cleartrip
```

---

## Step 11 — Load the Chrome Extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select: `/Users/murugadosssp/hackathons/devpost/aws_nova/frontend_chrome_extension`
5. FareWise icon appears in toolbar
6. Click it → open side panel → search works with live backend

---

## Troubleshooting

| Error | Fix |
|---|---|
| `NoCredentialsError` | Check `.env` — AWS keys not loaded |
| `AccessDeniedException` on Bedrock | Enable model access in Step 2 |
| `nova_act` import error | Run `pip install nova-act` in the `.venv` |
| Port 8000 already in use | `lsof -i :8000` to find PID, then `kill <PID>` |
| Nova Act Chromium crash | Run `python3 tests/test_amazon_agent.py` to see the actual error |
| Extension not connecting | Confirm backend is on port 8000; check Settings tab in extension |
| `ActExceededMaxStepsError` / "Exceeded max steps" | Set `NOVA_ACT_MAX_STEPS=50` (or up to 99) in `.env`; agents return gracefully with partial results |

**Travel search:** The orchestrator reads `plan["filters"]` (a structured dict from `TravelPlanner`) and passes it to each agent and to `FlightNormalizer`. Filters include `departure_window` (list of two HH:MM strings), `max_stops` (int or null), and `sort_by` (string). Each agent converts this to a readable hint via `_filters_to_criteria(filters)` before passing to `nova.act()`.

---

## Documentation

- **[docs/TESTING.md](docs/TESTING.md)** — Complete testing guide: test suite structure, what each test mimics, assertion reference, log file locations, and how to add new tests.
- **[ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md)** — Session logging system and admin dashboard at `http://localhost:7891/admin`.
- **[FLIGHT_DATA_FLOW.md](FLIGHT_DATA_FLOW.md)** — End-to-end data pipeline: Phase 1 (extraction) → Phase 2 (normalization) → Phase 3 (offers) → Phase 4 (Nova Pro reasoning).
- **[docs/AGENTS_ARCHITECTURE.md](docs/AGENTS_ARCHITECTURE.md)** — Agents folder structure, `config.yaml` layout, placeholders, and how to add a new agent.
- **[docs/EXCEPTION_HANDLING.md](docs/EXCEPTION_HANDLING.md)** — How Nova Act errors are handled and how to use `ActExceptionHandler`.
