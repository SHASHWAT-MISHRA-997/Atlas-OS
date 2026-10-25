"""Colour contrast of gradient buttons, which axe-core cannot measure (it reports them as 'incomplete')."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "app.css").read_text()


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def gradient_stops(rule: str) -> list[str]:
    return re.findall(r"#[0-9a-fA-F]{6}\b", rule)


def test_white_text_on_primary_gradients_meets_wcag_aa():
    rules = re.findall(r"--accent:linear-gradient\([^)]*\)", CSS) + re.findall(r"\.primary\{background:linear-gradient\([^)]*\)", CSS)
    assert len(rules) >= 2
    for rule in rules:
        for stop in gradient_stops(rule):
            assert contrast("#ffffff", stop) >= 4.5, f"{stop} in {rule}: {contrast('#ffffff', stop):.2f}:1"


def test_user_chat_bubble_text_meets_wcag_aa():
    rule = re.search(r"\.bubble\.user\{[^}]*background:linear-gradient\([^)]*\)", CSS).group(0)
    for stop in gradient_stops(rule):
        assert contrast("#ffffff", stop) >= 4.5
