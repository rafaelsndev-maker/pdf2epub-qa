from __future__ import annotations

import os
import re
import unicodedata


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=\w)", "", text)
    return text


def text_to_paragraphs(text: str) -> list[str]:
    text = clean_text(text)
    blocks = re.split(r"\n\s*\n", text.strip())
    paragraphs: list[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        paragraphs.append(" ".join(lines))
    return paragraphs


def detect_heading(text: str) -> str | None:
    heading_patterns = (
        r"^(cap[ií]tulo|chapter|parte|part|section|seção|secao|livro|book)\b",
        r"^(appendix|apêndice|apendice)\b",
    )
    max_lines = 6
    checked = 0
    candidates: list[tuple[int, str]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        checked += 1
        if checked > max_lines:
            break
        if len(line) > 80:
            continue
        letters = [c for c in line if c.isalpha()]
        if len(letters) < 4:
            continue
        upper_ratio = sum(c.isupper() for c in letters) / len(letters)
        words = [w for w in re.split(r"\s+", line) if w]
        title_ratio = sum(1 for w in words if w[0].isupper()) / max(len(words), 1)
        digit_ratio = sum(c.isdigit() for c in line) / max(len(line), 1)
        if digit_ratio > 0.3:
            continue

        score = 0
        for pattern in heading_patterns:
            if re.match(pattern, line, flags=re.IGNORECASE):
                score += 3
                break
        if upper_ratio >= 0.6:
            score += 1
        if title_ratio >= 0.8:
            score += 1
        if len(line) <= 60:
            score += 1
        if line.endswith((".", ";", ":", ",")):
            score -= 1

        if score >= 2:
            candidates.append((score, line))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates[0][1]
    return None


def tokenize(text: str) -> list[str]:
    text = normalize_text(text)
    return re.findall(r"[\w']+", text, flags=re.UNICODE)


def limit_text(text: str, max_len: int = 200) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
