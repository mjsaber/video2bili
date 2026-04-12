import re

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")


def extract_bv_id(url: str) -> str:
    """Extract the BV id from a Bilibili video URL."""
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)
