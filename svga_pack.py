#!/usr/bin/env python3
"""
SVGA Packer -- 將資料夾（animation.json + images + audio）壓縮回 .svga 檔案。

使用方式：
  python svga_pack.py <input_dir> [output.svga]

input_dir 結構（由 svga_extract.py 產生）：
  <input_dir>/
  ├── animation.json    # 動畫工程文件
  ├── images/           # 圖片檔案
  ├── audio/            # 音效檔案（可選）
  └── movie.bin         # 原始 protobuf（可選，優先使用）

依賴：
  pip install protobuf grpcio-tools
"""

import glob
import json
import os
import struct
import sys
import zlib

from svga_extract import _ensure_pb2


# ---------------------------------------------------------------------------
# Protobuf import
# ---------------------------------------------------------------------------

def _import_pb2(script_dir: str):
    _ensure_pb2(script_dir)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import svga_pb2
    return svga_pb2


# ---------------------------------------------------------------------------
# 讀取資源檔案
# ---------------------------------------------------------------------------

_IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".heif")
_AUDIO_EXTS = (".mp3", ".aac", ".wav", ".ogg", ".flac")


def _find_file(directory: str, key: str, exts: tuple) -> str | None:
    """在 directory 中尋找名為 key 加上任一 exts 副檔名的檔案。"""
    for ext in exts:
        path = os.path.join(directory, key + ext)
        if os.path.isfile(path):
            return path
    # 也搜尋子目錄（key 可能帶路徑）
    for ext in exts:
        path = os.path.join(directory, key.split("/")[-1] + ext)
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------
# JSON -> Protobuf 轉換
# ---------------------------------------------------------------------------

def _dict_to_shape(svga_pb2, shape_dict: dict):
    shape = svga_pb2.ShapeEntity()

    # type
    type_name = shape_dict.get("type", 0)
    if isinstance(type_name, str):
        type_map = {"SHAPE": 0, "RECT": 1, "ELLIPSE": 2, "KEEP": 3}
        shape.type = type_map.get(type_name, 0)
    else:
        shape.type = type_name

    # args
    args = shape_dict.get("args", {})
    if "d" in args:
        shape.shape.d = args["d"]
    elif "x" in args and "radiusX" in args:
        shape.ellipse.x = args.get("x", 0.0)
        shape.ellipse.y = args.get("y", 0.0)
        shape.ellipse.radiusX = args.get("radiusX", 0.0)
        shape.ellipse.radiusY = args.get("radiusY", 0.0)
    elif "x" in args and "width" in args:
        shape.rect.x = args.get("x", 0.0)
        shape.rect.y = args.get("y", 0.0)
        shape.rect.width = args.get("width", 0.0)
        shape.rect.height = args.get("height", 0.0)
        shape.rect.cornerRadius = args.get("cornerRadius", 0.0)

    # styles
    styles = shape_dict.get("styles")
    if styles:
        fill = styles.get("fill")
        if fill:
            shape.styles.fill.r = fill.get("r", 0.0)
            shape.styles.fill.g = fill.get("g", 0.0)
            shape.styles.fill.b = fill.get("b", 0.0)
            shape.styles.fill.a = fill.get("a", 1.0)
        stroke = styles.get("stroke")
        if stroke:
            shape.styles.stroke.r = stroke.get("r", 0.0)
            shape.styles.stroke.g = stroke.get("g", 0.0)
            shape.styles.stroke.b = stroke.get("b", 0.0)
            shape.styles.stroke.a = stroke.get("a", 1.0)
        if "strokeWidth" in styles:
            shape.styles.strokeWidth = styles["strokeWidth"]

    # transform
    transform = shape_dict.get("transform")
    if transform:
        shape.transform.a = transform.get("a", 1.0)
        shape.transform.b = transform.get("b", 0.0)
        shape.transform.c = transform.get("c", 0.0)
        shape.transform.d = transform.get("d", 1.0)
        shape.transform.tx = transform.get("tx", 0.0)
        shape.transform.ty = transform.get("ty", 0.0)

    return shape


def _dict_to_frame(svga_pb2, frame_dict: dict):
    frame = svga_pb2.FrameEntity()

    frame.alpha = frame_dict.get("alpha", 1.0)

    layout = frame_dict.get("layout")
    if layout:
        frame.layout.x = layout.get("x", 0.0)
        frame.layout.y = layout.get("y", 0.0)
        frame.layout.width = layout.get("width", 0.0)
        frame.layout.height = layout.get("height", 0.0)

    transform = frame_dict.get("transform")
    if transform:
        frame.transform.a = transform.get("a", 1.0)
        frame.transform.b = transform.get("b", 0.0)
        frame.transform.c = transform.get("c", 0.0)
        frame.transform.d = transform.get("d", 1.0)
        frame.transform.tx = transform.get("tx", 0.0)
        frame.transform.ty = transform.get("ty", 0.0)

    clip_path = frame_dict.get("clipPath")
    if clip_path:
        frame.clipPath = clip_path

    shapes = frame_dict.get("shapes")
    if shapes:
        for s in shapes:
            frame.shapes.append(_dict_to_shape(svga_pb2, s))

    return frame


def _build_movie(svga_pb2, project: dict, images_dir: str, audio_dir: str) -> "svga_pb2.MovieEntity":
    movie = svga_pb2.MovieEntity()

    # version
    movie.version = project.get("version", "2.0.0")

    # params
    params = project.get("params", {})
    movie.params.viewBoxWidth = params.get("viewBoxWidth", 0.0)
    movie.params.viewBoxHeight = params.get("viewBoxHeight", 0.0)
    movie.params.fps = params.get("fps", 30)
    movie.params.frames = params.get("frames", 0)

    # images (map<string, bytes>)
    for key, info in project.get("images", {}).items():
        path = _find_file(images_dir, key, _IMAGE_EXTS)
        if path:
            with open(path, "rb") as f:
                movie.images[key] = f.read()
        else:
            print(f"  [WARN] image not found: {key}")

    # audios
    for audio_dict in project.get("audios", []):
        audio = movie.audios.add()
        audio.audioKey = audio_dict.get("audioKey", "")
        audio.startFrame = audio_dict.get("startFrame", 0)
        audio.endFrame = audio_dict.get("endFrame", 0)
        audio.startTime = audio_dict.get("startTime", 0)
        audio.totalTime = audio_dict.get("totalTime", 0)

        # audio binary 也放在 images map 中
        audio_key = audio.audioKey
        path = _find_file(audio_dir, audio_key, _AUDIO_EXTS)
        if path:
            with open(path, "rb") as f:
                movie.images[audio_key] = f.read()

    # sprites
    for sprite_dict in project.get("sprites", []):
        sprite = movie.sprites.add()
        sprite.imageKey = sprite_dict.get("imageKey", "")

        matte_key = sprite_dict.get("matteKey")
        if matte_key:
            sprite.matteKey = matte_key

        for frame_dict in sprite_dict.get("frames", []):
            sprite.frames.append(_dict_to_frame(svga_pb2, frame_dict))

    return movie


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def pack(input_dir: str, output_file: str, script_dir: str) -> None:
    svga_pb2 = _import_pb2(script_dir)

    # 讀取 animation.json
    json_path = os.path.join(input_dir, "animation.json")
    if not os.path.isfile(json_path):
        print(f"[ERROR] animation.json not found in {input_dir}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        project = json.load(f)

    images_dir = os.path.join(input_dir, "images")
    audio_dir = os.path.join(input_dir, "audio")

    print(f"[INFO] Input dir: {input_dir}")
    print(f"[INFO] Version: {project.get('version')}")
    print(f"[INFO] Params: {project.get('params')}")
    print(f"[INFO] Images: {len(project.get('images', {}))}")
    print(f"[INFO] Audios: {len(project.get('audios', []))}")
    print(f"[INFO] Sprites: {len(project.get('sprites', []))}")
    print()

    # 建立 Protobuf MovieEntity
    movie = _build_movie(svga_pb2, project, images_dir, audio_dir)

    # 序列化
    proto_bytes = movie.SerializeToString()
    print(f"[INFO] Protobuf serialized: {len(proto_bytes):,} bytes")

    # zlib 壓縮
    compressed = zlib.compress(proto_bytes)
    print(f"[INFO] zlib compressed: {len(compressed):,} bytes")

    # 寫入 .svga
    with open(output_file, "wb") as f:
        f.write(compressed)

    print()
    print(f"[OK] Saved to {output_file}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_dir = sys.argv[1]
    if not os.path.isdir(input_dir):
        print(f"[ERROR] Not a directory: {input_dir}")
        sys.exit(1)

    # 預設輸出檔名 = 目錄名.svga
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        dir_name = os.path.basename(os.path.normpath(input_dir))
        output_file = dir_name + ".svga"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    pack(input_dir, output_file, script_dir)


if __name__ == "__main__":
    main()
