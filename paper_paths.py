import hashlib
import re


def safe_filename(title, identifier):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    name = re.sub(r"\s+", " ", name).strip(" .")[:145].rstrip(" .")
    return f"{name or hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:12]}.pdf"
