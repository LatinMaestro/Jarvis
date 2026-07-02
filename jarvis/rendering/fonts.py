from PIL import ImageFont


DEFAULT_FONT_PATH = "cour.ttf"
BODY_PT = 24
TITLE_PT = 36


def get_fonts(
    font_path: str = DEFAULT_FONT_PATH,
    body_pt: int = BODY_PT,
    title_pt: int = TITLE_PT,
):
    candidate_paths = [
        font_path,
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for candidate in candidate_paths:
        try:
            body_font = ImageFont.truetype(candidate, body_pt)
            title_font = ImageFont.truetype(candidate, title_pt)
            return body_font, title_font
        except Exception:
            continue

    body_font = title_font = ImageFont.load_default()
    return body_font, title_font
