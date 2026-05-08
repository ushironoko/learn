#!/usr/bin/env python3
"""Generate a Japanese newspaper-style image summarizing daily tech news."""

from PIL import Image, ImageDraw, ImageFont
import textwrap
import datetime

# --- Constants ---
W, H = 2200, 3500
BG_COLOR = "#F5F0E8"
HEADER_BG = "#1A1A1A"
HEADER_TEXT = "#F5F0E8"
SECTION_BG = "#2C2C2C"
SECTION_TEXT = "#F5F0E8"
BODY_TEXT = "#1A1A1A"
DIVIDER = "#8B7355"
ACCENT_RED = "#C0392B"
ACCENT_BLUE = "#1A5276"
ACCENT_GREEN = "#1E8449"
ACCENT_ORANGE = "#D35400"
ACCENT_PURPLE = "#6C3483"
LIGHT_GRAY = "#E8E0D0"
MID_GRAY = "#B8A898"
DARK_ACCENT = "#4A3728"

FONT_JP = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

def load_font(size):
    try:
        return ImageFont.truetype(FONT_JP, size)
    except:
        return ImageFont.load_default()

def draw_multiline(draw, text, x, y, font, color, max_width, line_spacing=1.4):
    """Draw wrapped text and return final y position."""
    lines = []
    for paragraph in text.split('\n'):
        if paragraph == '':
            lines.append('')
            continue
        # Wrap each paragraph
        wrapped = wrap_text(paragraph, font, max_width)
        lines.extend(wrapped)

    current_y = y
    line_height = int(font.size * line_spacing)
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=color)
        current_y += line_height
    return current_y

def wrap_text(text, font, max_width):
    """Wrap text to fit within max_width pixels."""
    words = list(text)  # Character-based for Japanese
    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        bbox = font.getbbox(test_line)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
    if current_line:
        lines.append(current_line)
    return lines if lines else ['']

def draw_rounded_rect(draw, xy, radius, fill, outline=None, outline_width=2):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                            outline=outline, width=outline_width)

def draw_section_header(draw, x, y, width, title, accent_color, font_title):
    h = 52
    draw_rounded_rect(draw, [x, y, x+width, y+h], 6, fill=accent_color)
    # Draw left accent bar
    draw.rectangle([x, y, x+8, y+h], fill=DARK_ACCENT)
    draw.text((x+20, y+10), title, font=font_title, fill="#FFFFFF")
    return y + h + 10

def draw_article_card(draw, x, y, width, title, body_lines, font_title, font_body,
                       accent_color, tag=None):
    # Card background
    card_h = estimate_card_height(title, body_lines, font_title, font_body, width)
    draw.rectangle([x, y, x+width, y+card_h], fill="#FFFFFF")
    draw.rectangle([x, y, x+4, y+card_h], fill=accent_color)
    draw.rectangle([x, y+card_h-1, x+width, y+card_h], fill=LIGHT_GRAY)

    cy = y + 12
    # Tag badge
    if tag:
        tag_bbox = font_body.getbbox(tag)
        tw = tag_bbox[2] - tag_bbox[0] + 16
        draw.rounded_rectangle([x+12, cy, x+12+tw, cy+24], radius=4, fill=accent_color)
        draw.text((x+20, cy+4), tag, font=font_body, fill="#FFFFFF")
        cy += 30

    # Title
    title_lines = wrap_text(title, font_title, width - 24)
    for line in title_lines:
        draw.text((x+12, cy), line, font=font_title, fill=BODY_TEXT)
        cy += int(font_title.size * 1.3)
    cy += 4

    # Divider
    draw.line([x+12, cy, x+width-12, cy], fill=LIGHT_GRAY, width=1)
    cy += 8

    # Body
    for bl in body_lines:
        if bl == '':
            cy += int(font_body.size * 0.6)
            continue
        blines = wrap_text(bl, font_body, width - 24)
        for bline in blines:
            draw.text((x+12, cy), bline, font=font_body, fill="#3D3D3D")
            cy += int(font_body.size * 1.45)

    return y + card_h + 10

def estimate_card_height(title, body_lines, font_title, font_body, width):
    h = 20  # top padding
    title_lines = wrap_text(title, font_title, width - 24)
    h += len(title_lines) * int(font_title.size * 1.3) + 4 + 1 + 8 + 8
    for bl in body_lines:
        if bl == '':
            h += int(font_body.size * 0.6)
            continue
        blines = wrap_text(bl, font_body, width - 24)
        h += len(blines) * int(font_body.size * 1.45)
    h += 16  # bottom padding
    return max(h, 60)

def create_newspaper():
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Fonts
    f_masthead = load_font(72)
    f_sub_masthead = load_font(28)
    f_date = load_font(22)
    f_section = load_font(28)
    f_article_title = load_font(26)
    f_article_body = load_font(20)
    f_small = load_font(18)
    f_tag = load_font(16)
    f_big_headline = load_font(44)
    f_lead_body = load_font(22)

    # === MASTHEAD ===
    # Top stripe
    draw.rectangle([0, 0, W, 10], fill=ACCENT_RED)
    draw.rectangle([0, 10, W, 130], fill=HEADER_BG)

    # Newspaper name
    masthead = "テック日報"
    mb = f_masthead.getbbox(masthead)
    mx = (W - (mb[2]-mb[0])) // 2
    draw.text((mx, 28), masthead, font=f_masthead, fill="#FFFFFF")

    # Subtitle
    sub = "TECH NIPPON DAILY — AI・セキュリティ・開発の最前線"
    sb = f_sub_masthead.getbbox(sub)
    sx = (W - (sb[2]-sb[0])) // 2
    draw.text((sx, 108), sub, font=f_sub_masthead, fill=MID_GRAY)

    # Date bar
    draw.rectangle([0, 140, W, 185], fill=DIVIDER)
    date_str = "2026年5月8日（金）　第1号　過去24時間のテックニュース速報"
    db = f_date.getbbox(date_str)
    dx = (W - (db[2]-db[0])) // 2
    draw.text((dx, 153), date_str, font=f_date, fill="#FFFFFF")

    # Bottom stripe
    draw.rectangle([0, 185, W, 195], fill=ACCENT_RED)

    y = 210

    # === BIG HEADLINE (Lead Story) ===
    lead_x = 50
    lead_w = W - 100

    draw.rectangle([lead_x, y, lead_x+lead_w, y+240], fill="#FFFFFF")
    draw.rectangle([lead_x, y, lead_x+6, y+240], fill=ACCENT_RED)
    draw.rectangle([lead_x, y, lead_x+lead_w, y+4], fill=ACCENT_RED)

    # BREAKING label
    draw.rounded_rectangle([lead_x+15, y+14, lead_x+150, y+44], radius=4, fill=ACCENT_RED)
    draw.text((lead_x+25, y+18), "■ 速報", font=f_section, fill="#FFFFFF")

    headline = "Claude Opus 4.7リリース & OpenAI GPT-5.5最新動向"
    hlines = wrap_text(headline, f_big_headline, lead_w - 30)
    hy = y + 54
    for hl in hlines:
        draw.text((lead_x+15, hy), hl, font=f_big_headline, fill=BODY_TEXT)
        hy += int(f_big_headline.size * 1.2)

    lead_body = "AnthropicはClaude Opus 4.7を正式リリース。高度なソフトウェアエンジニアリング、精密な指示追従、自己検証能力が大幅強化。SpaceXとの新たなコンピュート提携も発表。一方OpenAIはGPT-5.5 Instantを公開し、音声AI分野での競争が激化している。"
    lb_lines = wrap_text(lead_body, f_lead_body, lead_w - 30)
    by = hy + 8
    for lb in lb_lines:
        draw.text((lead_x+15, by), lb, font=f_lead_body, fill="#3D3D3D")
        by += int(f_lead_body.size * 1.4)

    y = y + 255

    # === HORIZONTAL DIVIDER ===
    draw.line([50, y, W-50, y], fill=DIVIDER, width=2)
    y += 18

    # === THREE COLUMN LAYOUT ===
    col_count = 3
    margin = 50
    gap = 18
    col_w = (W - 2*margin - (col_count-1)*gap) // col_count
    cols = [margin + i*(col_w+gap) for i in range(col_count)]

    col_y = [y, y, y]

    # --- COLUMN 1: CVE セキュリティ情報 ---
    cx, cy_ = cols[0], col_y[0]
    cy_ = draw_section_header(draw, cx, cy_, col_w, "🔐 セキュリティ / CVE速報", ACCENT_RED, f_section)

    cve_articles = [
        {
            "tag": "CRITICAL 9.3",
            "title": "CVE-2026-0300: Palo Alto PAN-OSにバッファオーバーフロー脆弱性",
            "body": [
                "Palo Alto Networks社のファイアウォール製品",
                "PAN-OSにおける深刻な脆弱性が発覚。",
                "未認証の攻撃者がroot権限で任意のコード",
                "を実行可能。国家支援の脅威アクターによる",
                "積極的な悪用が確認されており、即時パッチ",
                "適用が強く推奨されている。",
            ]
        },
        {
            "tag": "HIGH 8.8",
            "title": "CVE-2026-23918: Apache HTTP/2に二重解放バグ",
            "body": [
                "Apache HTTP Server 2.4.66のHTTP/2",
                "実装に「double free」の脆弱性を発見。",
                "DoSおよびリモートコード実行の可能性あり。",
                "2.4.67へのアップデートで修正済み。",
            ]
        },
        {
            "tag": "HIGH 7.8",
            "title": "CVE-2026-31431: Linux Kernel ローカル権限昇格",
            "body": [
                "非特権ローカルユーザーがroot権限を取得",
                "できるLinuxカーネルの脆弱性。",
                "CISAがKEVカタログに追加。連邦機関は",
                "5月15日までの修正適用が義務付けられた。",
            ]
        },
        {
            "tag": "CRITICAL 9.8",
            "title": "vm2 Node.jsライブラリ: 12件の重大脆弱性",
            "body": [
                "Sandboxを突破して任意コードを実行できる",
                "脆弱性がvm2ライブラリで12件発見。",
                "CVE-2026-24118のCVSSスコアは9.8。",
                "npm利用者は早急なバージョン更新を。",
            ]
        },
    ]

    for art in cve_articles:
        cy_ = draw_article_card(draw, cx, cy_, col_w,
                                 art["title"], art["body"],
                                 f_article_title, f_article_body,
                                 ACCENT_RED, tag=art.get("tag"))

    col_y[0] = cy_

    # --- COLUMN 2: AI ニュース (Anthropic + OpenAI) ---
    cx2, cy2 = cols[1], col_y[1]
    cy2 = draw_section_header(draw, cx2, cy2, col_w, "🤖 AI最新情報", ACCENT_BLUE, f_section)

    ai_articles = [
        {
            "tag": "Anthropic",
            "title": "Claude Opus 4.7 が正式リリース",
            "body": [
                "最上位モデルOpus 4.7が全プラットフォームで",
                "提供開始。ソフトウェアエンジニアリング能力、",
                "ビジョン解像度が大幅に向上。",
                "料金は据え置き（入力$5/百万token）。",
                "AWS Bedrock、Google Vertex AI、",
                "Microsoft Foundryでも利用可能。",
            ]
        },
        {
            "tag": "Anthropic",
            "title": "ClaudeのAD非表示方針と容量拡大を発表",
            "body": [
                "「広告モデルは真の有用性と相容れない」と",
                "Anthropicが表明。SpaceXとの新コンピュート",
                "提携により処理容量を大幅増強予定。",
                "使用量上限も引き上げへ。",
            ]
        },
        {
            "tag": "OpenAI",
            "title": "GPT-5.5 Instant: より賢く・より速く",
            "body": [
                "OpenAIがGPT-5.5 Instantを公開。",
                "「より賢く、明確で、個人化された」応答を",
                "実現。DeepSeek V4との熾烈な競争が",
                "続く中、音声AI機能も強化された。",
            ]
        },
        {
            "tag": "OpenAI",
            "title": "米エネルギー省とのAI協力を深化",
            "body": [
                "OpenAIが米国エネルギー省（DOE）との",
                "協力関係を拡大。2026年を「科学の年」",
                "と位置付け、研究加速を目指す。",
                "Genesis Missionイベントをホワイトハウス",
                "で開催し、産業再生への貢献を強調。",
            ]
        },
        {
            "tag": "OpenAI",
            "title": "ChatGPT Futures: Class of 2026",
            "body": [
                "大学入学から卒業までChatGPTと歩んだ",
                "初の世代を祝う「Class of 2026」企画。",
                "AI世代の台頭を象徴する取り組みとして",
                "注目を集めている。",
            ]
        },
    ]

    for art in ai_articles:
        accent = ACCENT_BLUE if art["tag"] == "Anthropic" else ACCENT_PURPLE
        cy2 = draw_article_card(draw, cx2, cy2, col_w,
                                 art["title"], art["body"],
                                 f_article_title, f_article_body,
                                 accent, tag=art.get("tag"))

    col_y[1] = cy2

    # --- COLUMN 3: HackerNews + GitHub ---
    cx3, cy3 = cols[2], col_y[2]
    cy3 = draw_section_header(draw, cx3, cy3, col_w, "🔥 HackerNews ホット", ACCENT_ORANGE, f_section)

    hn_articles = [
        {
            "tag": "1200+コメント",
            "title": "DeepSeek V4がHNを席巻、GPT-5.5に挑戦",
            "body": [
                "DeepSeek V4がHacker Newsのトップに",
                "浮上。1,200以上のコメントを集め、",
                "OpenAIの最新モデルへの強力な対抗馬",
                "として大きな話題となっている。",
            ]
        },
        {
            "tag": "セキュリティ",
            "title": "PyTorch Lightning 2.6.2が認証情報窃取マルウェアを同梱",
            "body": [
                "人気MLライブラリのサプライチェーン攻撃。",
                "PyTorch Lightning 2.6.2〜2.6.3に",
                "悪意あるコードが含まれており、開発者は",
                "即時バージョン確認が必要。",
            ]
        },
        {
            "tag": "AI",
            "title": "Uberが2026年AIバジェットを4月で使い切る",
            "body": [
                "Uberの年間AI予算が年度4ヶ月足らずで",
                "枯渇したことが明らかに。AI需要の爆発的",
                "拡大と企業のコスト管理の難しさを",
                "浮き彫りにした話題が議論を呼んでいる。",
            ]
        },
        {
            "tag": "セキュリティ",
            "title": "DAEMON Tools公式サイトがバックドア配布に悪用",
            "body": [
                "4月8日以降、DAEMON Toolsの公式配布",
                "インストーラーがトロイの木馬化。数千台",
                "のシステムにバックドアが侵入。",
                "正規ダウンロードを装った攻撃に警戒を。",
            ]
        },
    ]

    for art in hn_articles:
        cy3 = draw_article_card(draw, cx3, cy3, col_w,
                                 art["title"], art["body"],
                                 f_article_title, f_article_body,
                                 ACCENT_ORANGE, tag=art.get("tag"))

    # GitHub Trending section
    cy3 += 8
    cy3 = draw_section_header(draw, cx3, cy3, col_w, "⭐ GitHub トレンド", ACCENT_GREEN, f_section)

    gh_articles = [
        {
            "tag": "+16,804★",
            "title": "nexu-io/open-design — 28.2k Stars",
            "body": [
                "5月に最も急上昇したリポジトリ。",
                "オープンデザインプラットフォームとして",
                "コミュニティの注目を独占。",
            ]
        },
        {
            "tag": "+10,198★",
            "title": "TauricResearch/TradingAgents — 69.4k",
            "body": [
                "AIエージェントによる自動トレーディング",
                "研究プロジェクト。累計スター数も急増中。",
            ]
        },
        {
            "tag": "+10,077★",
            "title": "mattpocock/skills — 61.9k Stars",
            "body": [
                "TypeScript/JavaScript スキルトレーニング",
                "リポジトリ。開発者学習コミュニティで爆発的人気。",
            ]
        },
        {
            "tag": "210k+★",
            "title": "OpenClaw — AIエージェントで最多スター獲得",
            "body": [
                "1月に9,000→60,000星に急上昇した後、",
                "現在210,000星超え。AIエージェント",
                "分野で最も注目されるOSSの一つ。",
            ]
        },
    ]

    for art in gh_articles:
        cy3 = draw_article_card(draw, cx3, cy3, col_w,
                                 art["title"], art["body"],
                                 f_article_title, f_article_body,
                                 ACCENT_GREEN, tag=art.get("tag"))

    col_y[2] = cy3

    # === FOOTER ===
    footer_y = H - 80
    draw.rectangle([0, footer_y, W, footer_y+2], fill=DIVIDER)
    draw.rectangle([0, H-50, W, H], fill=HEADER_BG)

    footer_text = "テック日報 | 本紙の情報はWebSearchにより自動収集されたものです | 2026年5月8日 発行"
    fb = f_small.getbbox(footer_text)
    fx = (W - (fb[2]-fb[0])) // 2
    draw.text((fx, H-38), footer_text, font=f_small, fill=MID_GRAY)

    # === WATERMARK / EDITION ===
    edition = "第1号"
    draw.text((W-120, footer_y+5), edition, font=f_date, fill=DIVIDER)

    # Save
    out_path = "/home/user/learn/newspaper.png"
    img.save(out_path, "PNG", dpi=(150, 150))
    print(f"Saved: {out_path}")
    return out_path

if __name__ == "__main__":
    create_newspaper()
