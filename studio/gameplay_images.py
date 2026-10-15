"""Safe, decoded image previews for locally registered BG/CG/character stills."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import threading

from .gameplay_core.common import checked_file, open_verified_asset

MAX_COMPRESSED=16*1024*1024
MAX_PIXELS=36_000_000
IMAGE_SUFFIXES=frozenset({".png",".jpeg",".jpg",".webp"})
_DECODE_LOCK=threading.RLock()  # protects Pillow's global MAX_IMAGE_PIXELS

def checked_image_bytes(asset_root: Path, asset: dict, *,
                        require_verified=True, max_size=(2200,1600)) -> bytes:
    """Resolve by service-owned record, verify SHA-256 and decode/re-encode PNG.

    For the human REVIEW UI only, `require_verified=False` is permitted after
    the caller looks up the asset_id inside this service's scanned registry.
    The regular render endpoint must always use require_verified=True.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError
    import warnings

    if not isinstance(asset,dict):
        raise ValueError("不存在的媒体记录")
    extension=Path(asset["relative_path"]).suffix.casefold()
    if extension not in IMAGE_SUFFIXES:
        raise ValueError("此媒体不是支持的静态图片")
    if asset.get("bytes",0)>MAX_COMPRESSED:
        raise ValueError("图片文件超过本工作台安全预览上限")
    if require_verified:
        with open_verified_asset(asset_root,asset,
                                 allowed_extensions=IMAGE_SUFFIXES) as f:
            data=f.read(MAX_COMPRESSED+1)
    else:
        path=checked_file(asset_root,asset["relative_path"],
                          allowed_extensions=IMAGE_SUFFIXES,
                          max_bytes=MAX_COMPRESSED)
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=asset["file_hash"]:
            raise ValueError("图片内容已变更，必须重新扫描并审核")
    if len(data)>MAX_COMPRESSED:raise ValueError("压缩图片过大")
    with _DECODE_LOCK:
        previous=Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS=MAX_PIXELS
            with warnings.catch_warnings():
                warnings.simplefilter("error",Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as img:
                    img.verify()
                with Image.open(BytesIO(data)) as img:
                    if img.width*img.height>MAX_PIXELS:
                        raise ValueError("像素数量过大")
                    im=ImageOps.exif_transpose(img)
                    im.thumbnail(max_size,Image.Resampling.LANCZOS)
                    if im.mode not in ("RGB","RGBA"):
                        im=im.convert("RGBA")
                    buffer=BytesIO()
                    im.save(buffer,format="PNG",optimize=False)
                    return buffer.getvalue()
        except (OSError,ValueError,Image.DecompressionBombError,
                Image.DecompressionBombWarning,UnidentifiedImageError) as ex:
            raise ValueError("图片文件无法安全解码") from ex
        finally:
            Image.MAX_IMAGE_PIXELS=previous
