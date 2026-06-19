# BrightBank — AI Cheque Scanner

A Flask app that scans a photo of an Indian bank cheque and extracts the bank name,
branch, cheque number, MICR code, IFSC code, date, payee, account holder, account
number, and amount — then runs two real validation checks that a teller would
normally do by eye: cross-checking the amount in words against the amount in figures,
and verifying the IFSC/MICR codes actually match their real-world format.

Reading is done by a self-hosted **Qwen2.5-VL** vision-language model served via
**Ollama** on a remote GPU server. No cloud AI APIs (OpenAI, Anthropic, etc.) are used
anywhere in this project.

---

## Important: what this does *not* do

The "signature" field is **presence detection only** — it flags whether something
resembling a handwritten signature is visible in the signature area. It does **not**
verify whose signature it is, and it is not a fraud-detection or forensic signature
matching tool. That's a fundamentally different, specialized problem (matching against
a specimen signature) that a vision-language model isn't built for. Don't rely on a
"Yes" here as proof of authenticity — it only means *something* is there.

---

## How it works

```
User                       Flask App                    Remote GPU Server
 |                              |                               |
 | 1. Uploads cheque photo      |                               |
 |----------------------------->|                               |
 |                              | 2. Sends image + prompt        |
 |                              |------------------------------>|
 |                              |                        Qwen2.5-VL reads the cheque
 |                              | 3. Returns extracted JSON       |
 |                              |<------------------------------|
 |                              | 4. Parses amount-in-words,      |
 |                              |    validates IFSC/MICR format    |
 | 5. Reviews & edits fields    |                               |
 |<-----------------------------|                               |
 | 6. Confirms & saves          |                               |
 |----------------------------->| Saved to database.db, ref no.  |
```

If the scan fails (unreachable server, garbled response), the app falls back to an
empty manual-entry form rather than crashing — same pattern as the other projects in
this series.

---

## Features

- **Single-photo extraction** of 11 cheque fields via Qwen2.5-VL
- **Amount cross-check**: a custom words-to-number parser (handles Indian
  ones/tens/hundred/thousand/lakh/crore phrasing) converts "Five Lakh Twenty Three
  Thousand Four Hundred Fifty Only" → `523450` and compares it against the figures
  field — flags a mismatch if they disagree
- **IFSC/MICR format validation** via regex against the real specifications
  (`^[A-Z]{4}0[A-Z0-9]{6}$` for IFSC, 9 digits for MICR)
- **Editable review step** before anything is saved — the AI's extraction is a
  starting point, not the final word
- **Register page** listing every scanned cheque with all the flags (match/mismatch,
  valid/invalid format, auto/manual) visible at a glance
- **Graceful manual fallback** if the scan itself fails for any reason

---

## Project structure

```
cheque_scanner/
├── app.py              # Routes: home, scan, review, confirmation, register
├── config.py            # DB, upload, and Ollama connection settings
├── extensions.py         # Shared SQLAlchemy db object
├── models.py              # ChequeRecord table
├── cheque_extract.py      # Qwen2.5-VL call + words-to-number parser + IFSC/MICR validators
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── scan.html
│   ├── review.html
│   ├── confirmation.html
│   └── register.html
├── static/css/style.css
└── uploads/                 # Saved cheque images (auto-created)
```

---

## Setup & running

### 1. On the remote GPU server (where Qwen2.5-VL runs)

```bash
ollama pull qwen2.5vl:7b
OLLAMA_HOST=0.0.0.0 ollama serve
```

Ollama only listens on `127.0.0.1` by default — `OLLAMA_HOST=0.0.0.0` is required for
this app to reach it from another machine.

**Security note:** Ollama has no built-in authentication. Don't expose port `11434`
to the open internet — restrict it via firewall/security group, or tunnel over SSH:
```bash
ssh -L 11434:localhost:11434 user@remote-gpu-server
```

### 2. On the machine running this Flask app

```bash
cd cheque_scanner
pip install -r requirements.txt
```

Edit `config.py` and point `OLLAMA_HOST` at your server:
```python
OLLAMA_HOST = "http://203.0.113.10:11434"   # or http://localhost:11434 if tunneling
```

### 3. Run it

```bash
python app.py
```

Open `http://localhost:5003`. (The other projects in this series run on ports
5000/5001/5002, so all four can run side by side if you want them all up at once.)

**If you hit a Windows auto-reloader restart loop** (`Restarting with watchdog`
repeating endlessly, often blamed on an unrelated file like `confection\_config.py`):
that's Flask's debug reloader watching your whole Python install, not a bug in this
app. Quick fix — disable the reloader in `app.py`:
```python
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5003)
```

### 4. Try it

Click **"Scan a Cheque"** → upload a clear photo, MICR line and signature area
included → review the pre-filled (or empty, if the scan failed) form → save → check
the **Register** for the validation flags.

Quick connectivity check if scanning hangs or fails outright:
```bash
curl http://<your-remote-gpu-server-ip>:11434/api/tags
```

---

## Things worth testing deliberately

- **Trigger a mismatch on purpose**: during manual review, type an amount in figures
  that doesn't match the amount in words — confirm the register shows a red
  "Mismatch" badge rather than silently accepting it.
- **Feed it a malformed IFSC code** (e.g. `BADCODE123`) — confirm it's flagged
  "Invalid / unrecognized format" rather than waved through.
- **Simulate a scan failure** (disconnect from the GPU server, or just try before
  it's configured) — confirm you land on an empty manual-entry form with a clear
  explanation, not an error page.

---

## What's been tested vs. what to verify yourself

Tested end-to-end with mocked Ollama responses:
- ✅ Clean extraction → fields pre-fill, amounts match, valid IFSC/MICR badges show
- ✅ Amount mismatch (words ≠ figures) → flagged correctly in confirmation & register
- ✅ Malformed IFSC/MICR entered manually → flagged correctly
- ✅ Scan/extraction failure → graceful fallback to manual entry
- ✅ `words_to_number` against several Indian-phrasing test cases (thousand/lakh/crore)
- ✅ `clean_amount_figures` against currency-prefixed strings like `"Rs. 5500"` — this
  one actually caught a real bug (see below) before it ever reached you

**A bug worth knowing about, since it explains a design choice in the code:** the
first version of the figures-cleaning function stripped everything except digits and
dots, which turned `"Rs. 5500"` into `".5500"` (₹0.55 instead of ₹5,500) because the
period right after "Rs" got mistaken for a decimal point. Fixed by stripping
letter-sequences together with any period immediately following them, before parsing
digits — but it's a good reminder that any currency-prefix format you haven't tested
against could still trip up the parser. Worth a quick spot-check if your real cheques
use an unusual amount format.

**Not testable from this environment:**
- Actual extraction accuracy of `qwen2.5vl:7b` on real cheque photos — handwriting
  quality, image angle, and lighting will all affect this in ways mocked tests can't
  capture
- Network reliability between your Flask app and the remote GPU server

---

## Possible extensions

- OCR confidence flagging — re-prompt the model to flag fields it's unsure about
- Duplicate-cheque detection (same cheque number + account number scanned twice)
- Export the register to Excel/CSV for reconciliation
- Bank/IFSC cross-reference — look up the IFSC against a real bank master list to
  catch a code that's *valid format* but doesn't actually exist
