import pathlib

ASSETS_DIR = pathlib.Path(__file__).parent
LOGO_PATH  = ASSETS_DIR / "logo.png"                    # square icon
WORDMARK   = ASSETS_DIR / "haze_wordmark.png"           # transparent text logo
LOGO_TRANSPARENT = pathlib.Path(__file__).parent.parent.parent / "haze_transparent_logo.png"
