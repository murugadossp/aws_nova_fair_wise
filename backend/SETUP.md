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

## Step 3 — Get Nova Act API Key

Nova Act requires a separate API key from the Nova console.

1. Open https://nova.amazon.com (or search "Nova Act" in AWS Console)
2. Sign in with your AWS account
3. Navigate to **API Keys → Create API Key**
4. Copy the key — it starts with `na-`

> If nova.amazon.com is not yet publicly available, check:
> AWS Console → Amazon Bedrock → Nova → Nova Act

---

## Step 4 — Create the .env File

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend

cp .env.example .env
```

Open `.env` and fill in your values:

```env
AWS_ACCESS_KEY_ID=AKIA...your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
AWS_DEFAULT_REGION=us-east-1
NOVA_ACT_API_KEY=na-...your_nova_act_key_here
FAREWISE_PORT=8000
FAREWISE_CORS_ORIGINS=chrome-extension://*,http://localhost:*,http://127.0.0.1:*
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

Open a second terminal tab (keep uvicorn running in the first):

```bash
cd /Users/murugadosssp/hackathons/devpost/aws_nova/backend
source .venv/bin/activate

# Test each component individually:
python3 tests/test_nova_identifier.py    # Nova Lite — product ID from text
python3 tests/test_nova_reasoner.py      # Nova Pro — price + card math
python3 tests/test_amazon_agent.py       # Nova Act — live Amazon search
python3 tests/test_flipkart_agent.py     # Nova Act — live Flipkart search
python3 tests/test_makemytrip_agent.py   # Nova Act — live MakeMyTrip search
python3 tests/test_goibibo_agent.py      # Nova Act — live Goibibo search
python3 tests/test_cleartrip_agent.py    # Nova Act — live Cleartrip search
```

To see the Nova Act browser window while tests run (watch the agent interact with the page), set `FAREWISE_HEADED=1` in your `.env` file, or before running, e.g.:

```bash
# Option 1: add to .env
# FAREWISE_HEADED=1

# Option 2: inline when running
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

**Travel search:** The WebSocket payload `route` can include `user_prompt` or `criteria` (e.g. `"morning flights between 6am and 12pm"`) so the agent extracts flights matching that instead of only "cheapest 5".

---

## Documentation

- **[docs/AGENTS_ARCHITECTURE.md](docs/AGENTS_ARCHITECTURE.md)** — Agents folder structure, `config.yaml` layout, placeholders, and how to add a new agent.
- **[docs/EXCEPTION_HANDLING.md](docs/EXCEPTION_HANDLING.md)** — How Nova Act errors are handled and how to use `ActExceptionHandler`.
