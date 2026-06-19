"""
Extracts structured fields from an Indian bank cheque image using a self-hosted
Qwen2.5-VL model served via Ollama, plus helper functions to cross-check the
extracted amount and validate IFSC/MICR formats.

Requires Ollama running on the remote server with the model pulled, e.g.:
    ollama pull qwen2.5vl:7b
    OLLAMA_HOST=0.0.0.0 ollama serve
"""
import base64
import json
import re
import requests

CHEQUE_PROMPT = (
    "This is an image of an Indian bank cheque. Look carefully and extract the following "
    "fields. Respond with ONLY a JSON object (no markdown, no explanation) with exactly these "
    "keys: bank_name, branch, cheque_number, micr_code, ifsc_code, date, payee_name, "
    "account_holder_name, account_number, amount_words, amount_figures, signature_present. "
    "date must be in DD/MM/YYYY format. micr_code is the 9-digit code printed at the bottom "
    "of the cheque in a distinct font. ifsc_code is the 11-character branch code (4 letters, "
    "then a zero, then 6 alphanumeric characters). amount_words is the handwritten amount "
    "spelled out in words. amount_figures is the handwritten amount written in numerals. "
    "signature_present must be exactly one of: 'Yes', 'No', or 'Unclear', based only on "
    "whether something resembling a handwritten signature is visible in the signature area — "
    "do not attempt to verify whose signature it is. "
    "If any other field is not clearly visible, set its value to null."
)

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
MICR_PATTERN = re.compile(r"^\d{9}$")

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_SCALES = {"thousand": 1000, "lakh": 100000, "lac": 100000, "crore": 10000000}
_FILLER_WORDS = {"rupees", "rupee", "only", "and", "inr", "rs", "paise", "paisa"}


def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _strip_to_json(raw_text):
    """Models sometimes wrap JSON in ```json fences even when told not to — strip those off."""
    text = raw_text.strip()
    text = re.sub(r"^```(json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def words_to_number(text):
    """
    Converts an Indian-style amount-in-words string (e.g. 'Five Lakh Twenty Three
    Thousand Four Hundred Fifty Only') to a number. Heuristic — not bulletproof,
    but handles standard ones/tens/hundred/thousand/lakh/crore phrasing.
    Returns None if it can't parse anything meaningful.
    """
    if not text:
        return None
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", text.lower())
    tokens = [t for t in cleaned.split() if t not in _FILLER_WORDS]
    if not tokens:
        return None

    total = 0
    current = 0
    matched_any = False

    for tok in tokens:
        if tok in _ONES:
            current += _ONES[tok]
            matched_any = True
        elif tok in _TENS:
            current += _TENS[tok]
            matched_any = True
        elif tok == "hundred":
            current = (current or 1) * 100
            matched_any = True
        elif tok in _SCALES:
            scale = _SCALES[tok]
            current = (current or 1) * scale
            total += current
            current = 0
            matched_any = True
        # unrecognized tokens are silently skipped

    total += current
    return total if matched_any and total > 0 else None


def clean_amount_figures(raw):
    """Strips currency symbols/words/commas from a figures string and returns a float, or None."""
    if raw is None:
        return None
    text = str(raw)
    # Remove letter sequences (Rs, INR, etc.) along with an immediately-following period,
    # so "Rs. 5500" doesn't leave a stray "." that gets misread as a decimal point.
    text = re.sub(r"[A-Za-z\u20B9]+\.?", "", text)
    text = text.replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def validate_ifsc(code):
    if not code:
        return False
    return bool(IFSC_PATTERN.match(code.strip().upper()))


def validate_micr(code):
    if not code:
        return False
    digits_only = re.sub(r"\D", "", str(code))
    return bool(MICR_PATTERN.match(digits_only))


def call_ollama(image_path, ollama_host, model, timeout_seconds):
    """
    Sends the cheque image + extraction prompt to a self-hosted Qwen2.5-VL model via Ollama.
    Returns (success: bool, data_or_none: dict, raw_response_text: str, error_message: str)
    """
    try:
        image_b64 = encode_image(image_path)
    except Exception as e:
        return False, None, "", f"Could not read uploaded image: {e}"

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": CHEQUE_PROMPT, "images": [image_b64]}
        ],
        "format": "json",
        "stream": False,
    }

    try:
        resp = requests.post(f"{ollama_host}/api/chat", json=payload, timeout=timeout_seconds)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        return False, None, "", (
            "Could not reach the Ollama server. Make sure 'ollama serve' is running "
            f"and reachable at {ollama_host}."
        )
    except requests.exceptions.Timeout:
        return False, None, "", "Ollama took too long to respond (timed out)."
    except requests.exceptions.HTTPError as e:
        return False, None, "", f"Ollama returned an error: {e}"
    except Exception as e:
        return False, None, "", f"Unexpected error calling Ollama: {e}"

    try:
        raw_text = resp.json()["message"]["content"]
    except (KeyError, ValueError) as e:
        return False, None, "", f"Unexpected response shape from Ollama: {e}"

    cleaned = _strip_to_json(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return False, None, raw_text, "The model's response wasn't valid JSON — try re-uploading a clearer image."

    return True, data, raw_text, ""


def extract_cheque(image_path, ollama_host, model, timeout_seconds):
    return call_ollama(image_path, ollama_host, model, timeout_seconds)