import re
from typing import List


NON_BMP_RE = re.compile(r"[\U00010000-\U0010FFFF]")
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]"
)
PHONE_RE = re.compile(r"(?:(?<=\b)|(?<=\D))(?:\+?\d[\d\s\-]{7,}\d)(?=\b|\D)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LONG_DASH_RE = re.compile(r"[\u2012-\u2015\u2212]")

# Slang tokens to remove for colleague role
COLLEAGUE_BANNED = {
    "gonna", "wanna", "btw", "tbh", "rn", "tmr", "tmrw", "u", "ur", "probs",
}


def redact_privacy(text: str) -> str:
    if not text:
        return text
    text = PHONE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub("[redacted]", text)
    return text


def normalize_hyphens(text: str) -> str:
    if not text:
        return text
    return LONG_DASH_RE.sub("-", text)


def strip_emojis_and_non_bmp(text: str) -> str:
    if not text:
        return text
    text = EMOJI_RE.sub("", text)
    text = NON_BMP_RE.sub("", text)
    return text


def enforce_crush_style(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines[:2]:  # cap to two lines
        cleaned = strip_emojis_and_non_bmp(line)
        cleaned = normalize_hyphens(cleaned)
        cleaned = cleaned.lower()
        out.append(cleaned)
    return out


def enforce_colleague_style(text: str) -> str:
    text = strip_emojis_and_non_bmp(text)
    text = normalize_hyphens(text)
    # Remove banned slang tokens as whole words
    def replace_banned(match: re.Match) -> str:
        word = match.group(0)
        return "" if word.lower() in COLLEAGUE_BANNED else word

    text = re.sub(r"\b[\w']+\b", replace_banned, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_lines_max_two(text: str) -> List[str]:
    # Split preserving at most 2 lines
    parts = text.splitlines()
    if len(parts) <= 2:
        return parts
    return parts[:2]


def apply_role_guardrails(role: str, text: str) -> str:
    if role == "crush":
        lines = split_lines_max_two(text)
        lines = enforce_crush_style(lines)
        return "\n".join(lines)
    if role == "colleague":
        return enforce_colleague_style(text)
    return text


def parse_numbered_output(raw: str) -> List[str]:
    """Parse the model's OUTPUT block with exactly three options prefixed by 1) 2) 3).
    Returns list of exactly three strings; raises ValueError if not compliant.
    """
    if not raw:
        raise ValueError("empty model output")
    # Extract lines starting with 1) 2) 3)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    options = []
    for prefix in ("1)", "2)", "3)"):
        match = next((l for l in lines if l.startswith(prefix)), None)
        if not match:
            raise ValueError("missing option prefix: " + prefix)
        # Remove the prefix and any following space
        text = match[len(prefix):].lstrip()
        options.append(text)
    if len(options) != 3:
        raise ValueError("expected exactly three options")
    return options


