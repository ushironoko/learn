#!/usr/bin/env python3
"""Generate a newspaper-style tech digest image for May 8, 2026."""

from PIL import Image, ImageDraw, ImageFont
import textwrap
import os

# ── Canvas ──────────────────────────────────────────────────────────────────
W, H = 1600, 2200
BG      = (252, 248, 238)   # newsprint cream
INK     = (20,  20,  20)
RED     = (180,  20,  20)
GRAY    = (90,  90,  90)
LGRAY   = (200, 195, 185)
DIVIDER = (60,  60,  60)

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── Font helper ──────────────────────────────────────────────────────────────
FONT_DIR = "/usr/share/fonts"

def find_font(names, size):
    candidates = []
    for root, _, files in os.walk(FONT_DIR):
        for f in files:
            if f.endswith((".ttf", ".otf")):
                candidates.append(os.path.join(root, f))
    for name in names:
        for path in candidates:
            if name.lower() in path.lower():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
    return ImageFont.load_default()

F_MASTHEAD  = find_font(["DejaVuSerif-Bold", "FreeSerifBold", "LiberationSerif-Bold"], 72)
F_TAGLINE   = find_font(["DejaVuSerif",      "FreeSerif",     "LiberationSerif"],      18)
F_DATE      = find_font(["DejaVuSans",       "FreeSans",      "LiberationSans"],        16)
F_SEC_HEAD  = find_font(["DejaVuSerif-Bold", "FreeSerifBold", "LiberationSerif-Bold"], 22)
F_HEADLINE  = find_font(["DejaVuSerif-Bold", "FreeSerifBold", "LiberationSerif-Bold"], 17)
F_BODY      = find_font(["DejaVuSerif",      "FreeSerif",     "LiberationSerif"],      13)
F_CAPTION   = find_font(["DejaVuSans",       "FreeSans",      "LiberationSans"],        11)
F_TAG       = find_font(["DejaVuSans-Bold",  "FreeSansBold",  "LiberationSans-Bold"],  11)

# ── Helpers ──────────────────────────────────────────────────────────────────
def hline(y, x0=40, x1=W-40, color=DIVIDER, width=1):
    draw.line([(x0, y), (x1, y)], fill=color, width=width)

def vline(x, y0, y1, color=LGRAY):
    draw.line([(x, y0), (x, y1)], fill=color, width=1)

def wrap_text(text, font, max_w):
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines

def draw_block(x, y, w, section_tag, headline, body_lines, tag_color=RED):
    """Draw a single article block. Returns new y."""
    # Section tag
    draw.rectangle([x, y, x + draw.textlength(section_tag, font=F_TAG) + 10, y + 16],
                   fill=tag_color)
    draw.text((x + 5, y + 2), section_tag, font=F_TAG, fill=(255, 255, 255))
    y += 22

    # Headline (wrapped)
    for hl in wrap_text(headline, F_HEADLINE, w):
        draw.text((x, y), hl, font=F_HEADLINE, fill=INK)
        y += 22
    y += 4

    # Body
    for line in body_lines:
        for wl in wrap_text(line, F_BODY, w):
            draw.text((x, y), wl, font=F_BODY, fill=GRAY)
            y += 17
        y += 5
    return y + 12

# ════════════════════════════════════════════════════════════════════════════
# MASTHEAD
# ════════════════════════════════════════════════════════════════════════════
hline(30, width=3)
title = "TECH DAILY DIGEST"
tw = draw.textlength(title, font=F_MASTHEAD)
draw.text(((W - tw) // 2, 38), title, font=F_MASTHEAD, fill=INK)

tag = "Powered by Claude · Security · AI · Open Source"
tw2 = draw.textlength(tag, font=F_TAGLINE)
draw.text(((W - tw2) // 2, 120), tag, font=F_TAGLINE, fill=GRAY)

date_str = "Friday, May 8, 2026  ·  Vol. MMXXVI  ·  No. 128  ·  Past-24h Edition"
dw = draw.textlength(date_str, font=F_DATE)
draw.text(((W - dw) // 2, 148), date_str, font=F_DATE, fill=GRAY)

hline(174, width=3)
hline(178, width=1)

# ════════════════════════════════════════════════════════════════════════════
# THREE-COLUMN BODY  (col widths: 480, 480, 480)  margins 40px each side
# ════════════════════════════════════════════════════════════════════════════
COL_W   = 460
GAP     = 40
C1X     = 40
C2X     = C1X + COL_W + GAP
C3X     = C2X + COL_W + GAP
TOP_Y   = 195

# ── Column separators ────────────────────────────────────────────────────────
vline(C2X - 20, TOP_Y, H - 60)
vline(C3X - 20, TOP_Y, H - 60)

# ════════════════════════════════════════════════════════════════════════════
# COLUMN 1 – CVE / Security
# ════════════════════════════════════════════════════════════════════════════
y1 = TOP_Y
draw.text((C1X, y1), "CYBERSECURITY", font=F_SEC_HEAD, fill=RED)
y1 += 30
hline(y1, C1X, C1X + COL_W, color=RED, width=2)
y1 += 8

y1 = draw_block(C1X, y1, COL_W,
    "CRITICAL",
    "CVE-2026-31431: Linux Local Privilege Escalation (CVSS 7.8)",
    [
        "CISA added this Linux kernel flaw to its Known Exploited",
        "Vulnerabilities catalog. An unprivileged local user can obtain",
        "root access. Federal agencies must patch by May 15, 2026.",
    ], tag_color=(160, 30, 30))

y1 = draw_block(C1X, y1, COL_W,
    "HIGH",
    "cPanel CVE-2026-41940 (CVSS 9.8) Exploited in the Wild",
    [
        "Authentication bypass in cPanel & WebHost Manager allows",
        "remote attackers to gain elevated control. Actively weaponized",
        "against government and MSP networks.",
    ], tag_color=(190, 80, 10))

y1 = draw_block(C1X, y1, COL_W,
    "HIGH",
    "BaSyx CVE-2026-7411 (CVSS 10.0) — Unauthenticated Path Traversal",
    [
        "Critical path traversal in the BaSyx ICS framework lets",
        "unauthenticated attackers read arbitrary files. A companion",
        "blind SSRF flaw (CVE-2026-7412, CVSS 8.6) was also disclosed.",
    ], tag_color=(190, 80, 10))

y1 = draw_block(C1X, y1, COL_W,
    "MEDIUM",
    "JWCrypto < 1.5.7 Memory Exhaustion via Crafted JWE Tokens",
    [
        "Tokens under 250 KB can decompress to ~100 MB, causing",
        "server-side memory exhaustion. Update immediately.",
    ], tag_color=(120, 100, 20))

y1 = draw_block(C1X, y1, COL_W,
    "REPORT",
    "28.3 % of CVEs Now Exploited Within 24 Hours of Disclosure",
    [
        "Mandiant M-Trends 2026 report: exploits routinely arrive",
        "before patches. 2026 is being called the Year of AI-Assisted",
        "Attacks as threat actors automate reconnaissance.",
    ], tag_color=(60, 60, 140))

# ════════════════════════════════════════════════════════════════════════════
# COLUMN 2 – AI News (Anthropic + OpenAI)
# ════════════════════════════════════════════════════════════════════════════
y2 = TOP_Y
draw.text((C2X, y2), "ARTIFICIAL INTELLIGENCE", font=F_SEC_HEAD, fill=(20, 80, 160))
y2 += 30
hline(y2, C2X, C2X + COL_W, color=(20, 80, 160), width=2)
y2 += 8

# Anthropic sub-header
draw.text((C2X, y2), "▸ Anthropic / Claude", font=F_CAPTION, fill=(20, 80, 160))
y2 += 18

y2 = draw_block(C2X, y2, COL_W,
    "RELEASE",
    "Claude Opus 4.7 Now Generally Available",
    [
        "Anthropic's newest flagship model delivers major gains in",
        "advanced software engineering and vision tasks. Higher-",
        "resolution image processing and stronger creative output.",
        "Priced at $5 / 1M input · $25 / 1M output tokens.",
        "Available via API, Amazon Bedrock, Vertex AI & MS Foundry.",
    ], tag_color=(20, 130, 80))

y2 = draw_block(C2X, y2, COL_W,
    "POLICY",
    "Anthropic Commits: Claude Will Stay Ad-Free",
    [
        "Advertising incentives are incompatible with a genuinely",
        "helpful AI assistant. Anthropic outlined plans to expand",
        "access while preserving user trust.",
    ], tag_color=(80, 20, 140))

# Separator within column
hline(y2, C2X, C2X + COL_W, color=LGRAY)
y2 += 10

# OpenAI sub-header
draw.text((C2X, y2), "▸ OpenAI", font=F_CAPTION, fill=(20, 80, 160))
y2 += 18

y2 = draw_block(C2X, y2, COL_W,
    "RELEASE",
    "GPT-5.5 Instant Launched — 'Smarter, Clearer, Personalised'",
    [
        "OpenAI released GPT-5.5 Instant on May 5-6 alongside its",
        "system card. Optimised for low-latency voice AI use-cases;",
        "new realtime voice models added to the API.",
    ], tag_color=(20, 130, 80))

y2 = draw_block(C2X, y2, COL_W,
    "PRODUCT",
    "ChatGPT Testing Ads — First Commercial Integration",
    [
        "OpenAI began ad testing inside ChatGPT (May 7) and launched",
        "new tools for advertisers. The company is also deepening its",
        "collaboration with the U.S. Department of Energy as part of",
        "its '2026 Year of Science' vision.",
    ], tag_color=(180, 100, 0))

y2 = draw_block(C2X, y2, COL_W,
    "EDUCATION",
    "ChatGPT Futures: Recognising the 'Class of 2026'",
    [
        "OpenAI honours the first cohort to start and finish college",
        "entirely alongside ChatGPT, reflecting the tool's normalisation",
        "in academic life over four years.",
    ], tag_color=(60, 60, 140))

# ════════════════════════════════════════════════════════════════════════════
# COLUMN 3 – HackerNews + GitHub
# ════════════════════════════════════════════════════════════════════════════
y3 = TOP_Y
draw.text((C3X, y3), "OPEN SOURCE & COMMUNITY", font=F_SEC_HEAD, fill=(30, 120, 40))
y3 += 30
hline(y3, C3X, C3X + COL_W, color=(30, 120, 40), width=2)
y3 += 8

draw.text((C3X, y3), "▸ Hacker News — Hot Today", font=F_CAPTION, fill=(30, 120, 40))
y3 += 18

y3 = draw_block(C3X, y3, COL_W,
    "SECURITY",
    "Edge Browser Storing Passwords in Plaintext — HN Thread Viral",
    [
        "A ThreatsDay Bulletin revealed Microsoft Edge caching",
        "plaintext passwords in an accessible profile directory.",
        "HN discussion reached front page within hours.",
    ], tag_color=(160, 30, 30))

y3 = draw_block(C3X, y3, COL_W,
    "AI / INFRA",
    "Oracle Moves to Monthly Security Patches for Critical CVEs",
    [
        "Breaking from quarterly cadence, Oracle will issue monthly",
        "critical patches starting May 28, 2026. Community debate on",
        "whether faster releases help or overwhelm ops teams.",
    ], tag_color=(60, 60, 140))

y3 = draw_block(C3X, y3, COL_W,
    "DISCUSSION",
    "Ask HN: Who Is Hiring? (May 2026) — 800+ Comments",
    [
        "Monthly hiring thread drew heavy AI-engineer demand.",
        "Most-listed skills: Rust, TypeScript, LLM fine-tuning,",
        "and agentic workflow design.",
    ], tag_color=(80, 80, 80))

hline(y3, C3X, C3X + COL_W, color=LGRAY)
y3 += 10

draw.text((C3X, y3), "▸ GitHub Trending Stars (May 2026)", font=F_CAPTION, fill=(30, 120, 40))
y3 += 18

repos = [
    ("★ +16.8k", "nexu-io/open-design",
     "Local-first open-source alternative to Claude Design. 28.2k total."),
    ("★ +10.2k", "TauricResearch/TradingAgents",
     "Multi-agent LLM financial trading framework. 69.4k total."),
    ("★ +10.1k", "mattpocock/skills",
     "'Skills for Real Engineers' — TypeScript & tooling deep-dives."),
    ("★ 210k+",  "OpenClaw (breakout star)",
     "Fastest-growing OSS project in GitHub history; went viral Jan 2026."),
]

for star, name, desc in repos:
    # star badge
    sw = draw.textlength(star, font=F_TAG)
    draw.rectangle([C3X, y3, C3X + sw + 10, y3 + 16], fill=(30, 120, 40))
    draw.text((C3X + 5, y3 + 2), star, font=F_TAG, fill=(255, 255, 255))
    y3 += 22
    draw.text((C3X, y3), name, font=F_HEADLINE, fill=INK)
    y3 += 20
    for wl in wrap_text(desc, F_BODY, COL_W):
        draw.text((C3X, y3), wl, font=F_BODY, fill=GRAY)
        y3 += 17
    y3 += 10

# ════════════════════════════════════════════════════════════════════════════
# FOOTER
# ════════════════════════════════════════════════════════════════════════════
footer_y = H - 55
hline(footer_y, width=2)
footer_y += 8
sources = (
    "Sources: NVD · CISA · The Hacker News · Anthropic Blog · OpenAI News · "
    "Hacker News (news.ycombinator.com) · GitHub Trending · Trendshift"
)
fw = draw.textlength(sources, font=F_CAPTION)
draw.text(((W - fw) // 2, footer_y), sources, font=F_CAPTION, fill=GRAY)
footer_y += 18
copy_text = "© 2026 Tech Daily Digest — Auto-generated by Claude Sonnet 4.6 · For informational purposes only"
cw = draw.textlength(copy_text, font=F_CAPTION)
draw.text(((W - cw) // 2, footer_y), copy_text, font=F_CAPTION, fill=LGRAY)

# ── Save ─────────────────────────────────────────────────────────────────────
out_path = "/home/user/learn/tech_daily_2026-05-08.png"
img.save(out_path, "PNG", dpi=(150, 150))
print(f"Saved → {out_path}  ({W}×{H}px)")
