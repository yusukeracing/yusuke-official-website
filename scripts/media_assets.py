"""Prepare faithful delivery images without modifying source photographs.

Only referenced local images are emitted. EXIF orientation is applied, embedded
ICC colours are converted to sRGB, and tracking/location EXIF is not delivered.
There are no photographic filters, crops, sharpening or contrast adjustments.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

from PIL import Image, ImageCms, ImageOps, __version__ as PILLOW_VERSION
from content_render import _opening, _rewrite

IMAGE_FIELDS = {"heroImage", "heroMobileImage", "portraitImage", "detailImage", "image", "mobileImage", "logo", "ogImage", "currentRace", "pit", "supportFeature"}
EMPTY = {"", "xxx", "tba"}
RASTER_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".avif": "AVIF"}
RASTER = set(RASTER_FORMATS)
SAFE_DECODERS = ["JPEG", "PNG", "WEBP", "AVIF"]
WEBP_QUALITY = 92
WEBP_METHOD = 6


def delivery_profile_bytes(profile):
    """Remove build-time ICC metadata without changing its colour transform."""
    data = bytearray(profile.tobytes())
    # ICC header DateTimeNumber: 2000-01-01 00:00:00. A zero profile ID denotes
    # an uncomputed ID. These delivery-only header fields do not alter colour
    # primaries, transfer curves, white point or the source photograph.
    data[24:36] = bytes.fromhex("07d000010001000000000000")
    data[84:100] = bytes(16)
    return bytes(data)


def unset(value):
    return value is None or isinstance(value, str) and (value.strip().lower() in EMPTY or Path(value).name.lower().startswith("xxx-"))


@dataclass(frozen=True)
class DeliveryImage:
    path: str
    width: int
    height: int
    bytes: int
    sha256: str

    def as_dict(self):
        return {"path": self.path, "width": self.width, "height": self.height,
                "bytes": self.bytes, "sha256": self.sha256}


class _Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


class MediaPipeline:
    def __init__(self, root: Path, destination: Path, base: str):
        release = re.match(r"^(\d+)\.(\d+)", PILLOW_VERSION)
        if not release or tuple(map(int, release.groups())) < (13, 0):
            raise ValueError("Pillow 13.0.0 or later is required for safe image decoding. Install requirements-build.txt and run .build-venv/bin/python.")
        self.root = root.resolve()
        self.destination = destination
        self.base = base
        self.cache = {}
        self.delivered = {}
        self.sources = {}

    def source_path(self, value: str):
        if not isinstance(value, str):
            raise ValueError("Image path must be text")
        parsed = urlsplit(unescape(value))
        if parsed.scheme or parsed.netloc:
            if not value.startswith(self.base):
                raise ValueError(f"Image must be a local upload: {value}")
            value = value[len(self.base):]
            parsed = urlsplit(value)
        path = unquote(parsed.path)
        if (parsed.query or parsed.fragment or not path.startswith("assets/images/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or re.search(r"[\x00-\x1f\x7f\\]", path)):
            raise ValueError(f"Unsafe local image path: {value}")
        file = self.root / path
        if file.is_symlink() or any(parent.is_symlink() for parent in file.parents if parent != self.root.parent):
            raise ValueError(f"Image symlinks are not published: {value}")
        if not file.is_file():
            candidates = [str(item.relative_to(self.root)) for item in (self.root / "assets/images").rglob("*")
                          if item.is_file() and str(item.relative_to(self.root)).casefold() == path.casefold()]
            hint = f"; check exact spelling/case: {candidates[0]}" if candidates else ""
            raise ValueError(f"Image does not exist: {path}{hint}")
        return file, path

    def _vector(self, file, source, digest):
        try:
            tree = ET.fromstring(file.read_bytes())
        except ET.ParseError as error:
            raise ValueError(f"Invalid SVG: {source}") from error
        for element in tree.iter():
            if element.tag.rsplit("}", 1)[-1].lower() in {"script", "foreignobject", "iframe", "object", "embed"}:
                raise ValueError(f"Active SVG is not a public photo: {source}")
            for key, value in element.attrib.items():
                local = key.rsplit("}", 1)[-1].lower()
                if local.startswith("on") or local in {"href", "src"} and not value.startswith("#"):
                    raise ValueError(f"External/active SVG references are forbidden: {source}")
        view = tree.get("viewBox", "").split()
        try:
            width, height = (int(float(view[2])), int(float(view[3]))) if len(view) == 4 else (1600, 1067)
        except ValueError:
            width, height = 1600, 1067
        relative = f"assets/optimized/{digest[:20]}.svg"
        target = self.destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
        asset = DeliveryImage(relative, width, height, target.stat().st_size, digest)
        self.delivered[relative] = asset
        self.sources.setdefault(source, {"source": source, "sourceSha256": digest,
                                        "sourceBytes": file.stat().st_size, "width": width, "height": height,
                                        "colour": "SVG source preserved", "variants": []})["variants"].append(asset.as_dict())
        return asset

    def image(self, value, mobile=False):
        if unset(value):
            return None
        if value in self.delivered:
            return self.delivered[value]
        key = (value, mobile)
        if key in self.cache:
            return self.cache[key]
        file, source = self.source_path(value)
        original = file.read_bytes()
        digest = sha256(original).hexdigest()
        if file.suffix.lower() == ".svg":
            result = self._vector(file, source, digest)
            self.cache[key] = result
            return result
        if file.suffix.lower() not in RASTER:
            raise ValueError(f"Unsupported photo format: {source}; use JPEG, PNG, WebP or AVIF")
        try:
            # Do not let an upload with a false .jpg extension enter unrelated
            # decoders (notably JPEG 2000). The suffix must match the identified
            # safe format before pixel decoding starts.
            with Image.open(BytesIO(original), formats=SAFE_DECODERS) as image:
                expected_format = RASTER_FORMATS[file.suffix.lower()]
                if image.format != expected_format:
                    raise ValueError(f"{source}: extension {file.suffix.lower()} does not match image format {image.format}; expected {expected_format}")
                if image.width * image.height > 40_000_000:
                    raise ValueError(f"Photo exceeds the 40-megapixel build limit: {source}")
                if getattr(image, "is_animated", False):
                    raise ValueError(f"Animated images must not be silently flattened: {source}")
                image.load()
                photo = ImageOps.exif_transpose(image)
                original_size = photo.size
                icc = image.info.get("icc_profile")
                colour = "assumed sRGB (source has no ICC profile)"
                srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
                if icc:
                    try:
                        alpha = photo.getchannel("A") if "A" in photo.getbands() else None
                        # LittleCMS must receive the source profile's original
                        # colour channels. Flattening CMYK/LAB to RGB first would
                        # discard their colour meaning before the ICC transform.
                        cms_input = photo if photo.mode in {"RGB", "CMYK", "LAB", "L"} else photo.convert("RGB")
                        photo = ImageCms.profileToProfile(cms_input, ImageCms.ImageCmsProfile(BytesIO(icc)), srgb, outputMode="RGB")
                        if alpha is not None:
                            photo.putalpha(alpha)
                        colour = "embedded ICC converted to sRGB"
                    except (ImageCms.PyCMSError, OSError, ValueError) as error:
                        raise ValueError(f"Cannot safely convert the embedded photo colour profile: {source}") from error
                elif photo.mode not in {"RGB", "RGBA"}:
                    photo = photo.convert("RGBA" if "A" in photo.getbands() else "RGB")
                cap = 720 if mobile else 1600
                photo.thumbnail((cap, cap), Image.Resampling.LANCZOS)
                width, height = photo.size
                encoded = BytesIO()
                photo.save(encoded, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD,
                           icc_profile=delivery_profile_bytes(srgb))
                delivery_bytes = encoded.getvalue()
                delivery_digest = sha256(delivery_bytes).hexdigest()
                # Cache immutable bytes, not just source inputs: upgrading the
                # encoder or transform policy must produce a new delivery URL.
                relative = f"assets/optimized/{delivery_digest[:20]}-{width}x{height}.webp"
                target = self.destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(delivery_bytes)
                result = DeliveryImage(relative, width, height, len(delivery_bytes), delivery_digest)
        except (OSError, SyntaxError) as error:
            raise ValueError(f"Cannot decode photo: {source}: {error}") from error
        self.cache[key] = result
        self.delivered[relative] = result
        entry = self.sources.setdefault(source, {"source": source, "sourceSha256": digest,
                "sourceBytes": len(original), "width": original_size[0], "height": original_size[1],
                "colour": colour, "variants": []})
        if result.as_dict() not in entry["variants"]:
            entry["variants"].append(result.as_dict())
        return result

    def rewrite_data(self, value, trail=()):
        if isinstance(value, list):
            return [self.rewrite_data(item, (*trail, str(index))) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            prose_fields = {"description", "body", "text", "message", "intro", "alt", "caption", "imageAlt", "imageCaption", "name", "title", "heroAlt", "label", "handle"}
            exact_image_path = (isinstance(item, str) and key not in prose_fields
                                and re.fullmatch(r"assets/images/[^\r\n<>\"]+\.(?:jpe?g|png|webp|avif|svg)", item, re.I))
            image_field = key in IMAGE_FIELDS or key == "race" and trail[-1:] == ("photos",) or bool(exact_image_path)
            if image_field:
                asset = self.image(item, mobile=key in {"heroMobileImage", "mobileImage"})
                result[key] = asset.path if asset else ""
            else:
                result[key] = self.rewrite_data(item, (*trail, key))
        if isinstance(result.get("image"), str) and result["image"] in self.delivered:
            asset = self.delivered[result["image"]]
            result.update(width=asset.width, height=asset.height, imageWidth=asset.width, imageHeight=asset.height)
        if isinstance(result.get("logo"), str) and result["logo"] in self.delivered:
            asset = self.delivered[result["logo"]]
            result.update(logoWidth=asset.width, logoHeight=asset.height)
        if isinstance(result.get("mobileImage"), str) and result["mobileImage"] in self.delivered:
            asset = self.delivered[result["mobileImage"]]
            result.update(mobileWidth=asset.width, mobileHeight=asset.height)
        if result.get("heroImage") in self.delivered and not result.get("heroMobileImage"):
            original_hero = value["heroImage"]
            mobile = self.image(original_hero, mobile=True)
            result["heroMobileImage"] = mobile.path
        return result

    def translate_reference(self, value, mobile=False):
        decoded = unescape(value)
        absolute = decoded.startswith(self.base)
        relative = decoded[len(self.base):] if absolute else decoded
        if relative in self.delivered:
            return decoded
        if not relative.startswith("assets/images/") or unset(relative):
            return decoded
        asset = self.image(relative, mobile=mobile)
        return urljoin(self.base, asset.path) if absolute else asset.path

    def rewrite_html(self, text, content):
        def binding(tag, attrs, opening, body, closing):
            key = attrs.get("data-photo-bind", "")
            configured = content
            for part in key.split("."):
                configured = configured.get(part) if isinstance(configured, dict) else None
            tags = _Tags(body).tags
            images = [a for t, a in tags if t == "img"]
            if not images:
                return opening + body + closing
            selected = configured if not unset(configured) else images[0].get("src")
            if unset(selected):
                return ""
            asset = self.image(selected)
            attrs["data-photo"] = asset.path
            attrs["data-original-photo"] = next((source for source, entry in self.sources.items()
                if any(item["path"] == asset.path for item in entry["variants"])), "")
            if key == "site.heroImage":
                alt = content.get("site", {}).get("heroAlt", "池田優介のレース活動")
            else:
                alt = images[0].get("alt")
            def image_tag(match):
                original = _Tags(match.group()).tags[0][1]
                original.update(src=asset.path, width=str(asset.width), height=str(asset.height))
                original["alt"] = alt if alt and alt != "xxx" else "池田優介のレース活動"
                if key == "site.heroImage":
                    original.pop("loading", None)
                    original["fetchpriority"] = "high"
                else:
                    original["loading"] = "lazy"
                return _opening("img", original)
            body = re.sub(r"<img\b[^>]*>", image_tag, body, count=1, flags=re.I | re.S)
            if key == "site.heroImage":
                mobile = content.get("site", {}).get("heroMobileImage")
                body = re.sub(r"<source\b[^>]*>", "", body, flags=re.I)
                if mobile:
                    item = self.image(mobile)
                    source = f'<source media="(max-width: 767px)" srcset="{escape(item.path, quote=True)}" width="{item.width}" height="{item.height}" data-photo-source>'
                    body = re.sub(r"(<picture\b[^>]*>)", lambda match: match[1] + source, body, count=1, flags=re.I)
            return _opening(tag, attrs) + body + closing
        text = _rewrite(text, lambda tag, attrs: tag == "figure" and "data-photo-bind" in attrs, binding)
        def tag_image(match):
            tag, attrs = _Tags(match.group()).tags[0]
            src = attrs.get("src")
            if not src:
                return match.group()
            reference = self.translate_reference(src)
            if reference != src:
                attrs["src"] = reference
            relative = reference[len(self.base):] if reference.startswith(self.base) else reference
            if relative in self.delivered:
                asset = self.delivered[relative]
                attrs.update(width=str(asset.width), height=str(asset.height))
                if attrs.get("alt") in {None, "", "xxx"}:
                    attrs["alt"] = "池田優介のレース活動"
            return _opening(tag, attrs)
        text = re.sub(r"<img\b[^>]*>", tag_image, text, flags=re.I | re.S)
        def references(match):
            value = unescape(match[3])
            return match[1] + match[2] + escape(self.translate_reference(value), quote=True) + match[2]
        text = re.sub(r'(\b(?:data-photo|data-src|poster)\s*=\s*)(["\'])(.*?)\2', references, text, flags=re.I | re.S)
        def source_tag(match):
            tag, attrs = _Tags(match.group()).tags[0]
            values = []
            for part in attrs.get("srcset", "").split(","):
                pieces = part.strip().split()
                if pieces:
                    values.append(" ".join([self.translate_reference(pieces[0], mobile=True), *pieces[1:]]))
            attrs["srcset"] = ", ".join(values)
            path = values[0].split()[0] if len(values) == 1 else ""
            if path in self.delivered:
                asset = self.delivered[path]
                attrs.update(width=str(asset.width), height=str(asset.height))
            return _opening(tag, attrs)
        return re.sub(r"<source\b[^>]*>", source_tag, text, flags=re.I | re.S)

    def copy_runtime_fallbacks(self):
        # These are UI error illustrations referenced from JS, not photo uploads.
        for name in ("photo-unavailable.svg", "image-unavailable.svg"):
            source = self.root / "assets/images" / name
            if source.is_file():
                relative = Path("assets/images") / name
                target = self.destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

    def manifest(self):
        return {"version": 1, "policy": "Originals retained in source; delivery images: sRGB, orientation preserved, no crop/filter; WebP quality 92; long edge 1600/720px.",
                "images": [self.sources[key] for key in sorted(self.sources)]}

    def write_manifest(self):
        destination = self.destination / "data/media-manifest.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
