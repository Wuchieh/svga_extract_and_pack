#!/usr/bin/env python3
"""
SVGA Extractor — 將 SVGA 檔案解壓縮為獨立圖片、音效及工程文件。

支援格式：
  - SVGA 1.x (ZIP + JSON)
  - SVGA 2.x (zlib + Protobuf)

使用方式：
  python svga_extract.py <input.svga> [output_dir]

依賴：
  pip install protobuf

首次執行時會自動從 svga.proto 編譯出 svga_pb2.py，
需要系統已安裝 protoc 或 pip install grpcio-tools。
"""

import io
import json
import os
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Protobuf 自動編譯
# ---------------------------------------------------------------------------

def _ensure_pb2(script_dir: str) -> None:
    """確保 svga_pb2.py 存在，若不存在則自動編譯 svga.proto。"""
    pb2_path = os.path.join(script_dir, "svga_pb2.py")
    proto_path = os.path.join(script_dir, "svga.proto")

    if os.path.isfile(pb2_path):
        return

    if not os.path.isfile(proto_path):
        print(f"[錯誤] 找不到 {proto_path}，請確認 svga.proto 與本腳本在同一目錄。")
        sys.exit(1)

    print("[INFO] 正在編譯 svga.proto → svga_pb2.py ...")

    # 嘗試方式 1: grpc_tools.protoc (pip install grpcio-tools)
    try:
        from grpc_tools import protoc

        result = protoc.main([
            "grpc_tools.protoc",
            f"--proto_path={script_dir}",
            f"--python_out={script_dir}",
            proto_path,
        ])
        if result == 0 and os.path.isfile(pb2_path):
            print("[INFO] 編譯成功 (grpc_tools.protoc)")
            return
    except ImportError:
        pass

    # 嘗試方式 2: 系統 protoc
    import subprocess

    try:
        subprocess.run(
            [
                "protoc",
                f"--proto_path={script_dir}",
                f"--python_out={script_dir}",
                proto_path,
            ],
            check=True,
            capture_output=True,
        )
        if os.path.isfile(pb2_path):
            print("[INFO] 編譯成功 (protoc)")
            return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    print(
        "[錯誤] 無法編譯 svga.proto。\n"
        "請安裝其中一項：\n"
        "  pip install grpcio-tools\n"
        "  或安裝 protoc (https://grpc.io/docs/protoc-installation/)"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# SVGA 版本偵測
# ---------------------------------------------------------------------------

def _detect_version(data: bytes) -> int:
    """根據檔案 header 判斷 SVGA 版本。

    Returns:
        1 = SVGA 1.x (ZIP 格式, header: PK 或 53 56 47 41)
        2 = SVGA 2.x (zlib 格式, header: 78 9C 或 78 01)
    """
    if len(data) < 4:
        return 0

    # zlib magic: 78 01 (low), 78 5E (default), 78 9C (default), 78 DA (best)
    if data[0] == 0x78 and data[1] in (0x01, 0x5E, 0x9C, 0xDA):
        return 2

    # ZIP magic: PK\x03\x04
    if data[:4] == b"PK\x03\x04":
        return 1

    # SVGA 1.x 可能以 "SVGA" 開頭，後面接 ZIP
    if data[:4] == b"SVGA":
        return 1

    return 0


# ---------------------------------------------------------------------------
# SVGA 1.x 解析 (ZIP + JSON)
# ---------------------------------------------------------------------------

def _extract_svga1(data: bytes, output_dir: str) -> None:
    """解壓 SVGA 1.x 檔案 (本質上是 ZIP)。"""
    # 如果有 SVGA header，跳過找到 PK
    zip_offset = data.find(b"PK\x03\x04")
    if zip_offset == -1:
        print("[錯誤] SVGA 1.x 格式無法找到 ZIP header")
        return

    zip_data = data[zip_offset:]
    bio = io.BytesIO(zip_data)

    with zipfile.ZipFile(bio, "r") as zf:
        zf.extractall(output_dir)
        count = len(zf.namelist())
        print(f"[INFO] SVGA 1.x -- extracted {count} files to {output_dir}/")
        for name in zf.namelist():
            print(f"  {name}")


# ---------------------------------------------------------------------------
# SVGA 2.x 解析 (zlib + Protobuf)
# ---------------------------------------------------------------------------

def _extract_svga2(data: bytes, output_dir: str, script_dir: str) -> None:
    """解壓 SVGA 2.x 檔案 (zlib + Protobuf)。"""
    _ensure_pb2(script_dir)

    # 動態 import，因為可能是剛編譯出來的
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import svga_pb2

    # 解壓 zlib
    decompressed = zlib.decompress(data)
    print(f"[INFO] zlib 解壓: {len(data):,} → {len(decompressed):,} bytes")

    # 解析 Protobuf
    movie = svga_pb2.MovieEntity()
    movie.ParseFromString(decompressed)

    # 建立輸出目錄
    images_dir = os.path.join(output_dir, "images")
    audio_dir = os.path.join(output_dir, "audio")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    # ---- 列印動畫資訊 ----
    print()
    print("=" * 55)
    print("  SVGA 動畫資訊")
    print("=" * 55)
    print(f"  版本     : {movie.version}")
    print(f"  畫布大小 : {movie.params.viewBoxWidth} x {movie.params.viewBoxHeight}")
    print(f"  FPS      : {movie.params.fps}")
    print(f"  總影格數 : {movie.params.frames}")
    print(f"  圖層數   : {len(movie.sprites)}")
    print(f"  音效數   : {len(movie.audios)}")
    print(f"  資源數   : {len(movie.images)}")
    print()

    # ---- 提取圖片 ----
    image_count = 0
    for key, image_data in movie.images.items():
        if key.startswith("audio"):
            continue

        # 確認副檔名
        ext = _detect_image_ext(image_data)
        filename = os.path.join(images_dir, f"{key}{ext}")

        # 確保父目錄存在 (key 可能帶路徑)
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "wb") as f:
            f.write(image_data)
        image_count += 1

    print(f"[圖片] 已提取 {image_count} 張圖片到 {images_dir}/")

    # ---- 提取音效 ----
    audio_count = 0
    for key, audio_data in movie.images.items():
        if not key.startswith("audio"):
            continue

        ext = _detect_audio_ext(audio_data)
        filename = os.path.join(audio_dir, f"{key}{ext}")

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "wb") as f:
            f.write(audio_data)
        audio_count += 1

    if audio_count > 0:
        print(f"[音效] 已提取 {audio_count} 個音效到 {audio_dir}/")
    else:
        print("[音效] 此 SVGA 不含音效資料")

    # ---- 匯出工程文件 (JSON) ----
    project_data = _build_project_json(movie)
    project_path = os.path.join(output_dir, "animation.json")
    with open(project_path, "w", encoding="utf-8") as f:
        json.dump(project_data, f, indent=2, ensure_ascii=False)
    print(f"[工程] 已匯出動畫工程文件到 {project_path}")

    # ---- 匯出原始 protobuf 二進位 ----
    raw_path = os.path.join(output_dir, "movie.bin")
    with open(raw_path, "wb") as f:
        f.write(decompressed)
    print(f"[原始] 已匯出 protobuf 二進位到 {raw_path}")

    print()
    print(f"完成！所有檔案已輸出到 {output_dir}/")


# ---------------------------------------------------------------------------
# 檔案類型偵測
# ---------------------------------------------------------------------------

def _detect_image_ext(data: bytes) -> str:
    """根據 magic bytes 偵測圖片格式。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"\x00\x00\x00\x0c" or data[:4] == b"\x00\x00\x00\x14":
        return ".heif"
    return ""


def _detect_audio_ext(data: bytes) -> str:
    """根據 magic bytes 偵測音效格式。"""
    # MP3 with ID3 tag
    if data[:3] == b"ID3":
        return ".mp3"
    # MP3 frame sync
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        return ".mp3"
    # AAC ADTS
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xF0 in (0xF0, 0xF8):
        return ".aac"
    # RIFF/WAVE
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    # OGG
    if data[:4] == b"OggS":
        return ".ogg"
    # FLAC
    if data[:4] == b"fLaC":
        return ".flac"
    return ""


# ---------------------------------------------------------------------------
# 工程文件建構
# ---------------------------------------------------------------------------

def _build_project_json(movie) -> dict:
    """將 Protobuf MovieEntity 轉為可讀的 JSON 結構。"""
    data = {
        "version": movie.version,
        "params": {
            "viewBoxWidth": movie.params.viewBoxWidth,
            "viewBoxHeight": movie.params.viewBoxHeight,
            "fps": movie.params.fps,
            "frames": movie.params.frames,
        },
        "images": {},
        "audios": [],
        "sprites": [],
    }

    # 圖片清單 (只記錄 key 和大小，不嵌入 binary)
    for key, img_bytes in movie.images.items():
        if not key.startswith("audio"):
            data["images"][key] = {
                "size": len(img_bytes),
                "format": _detect_image_ext(img_bytes).lstrip(".") or "unknown",
            }

    # 音效清單 + 時間資訊
    for audio in movie.audios:
        data["audios"].append({
            "audioKey": audio.audioKey,
            "startFrame": audio.startFrame,
            "endFrame": audio.endFrame,
            "startTime": audio.startTime,
            "totalTime": audio.totalTime,
        })

    # 圖層與影格
    for sprite in movie.sprites:
        sprite_data = {
            "imageKey": sprite.imageKey,
            "matteKey": sprite.matteKey or None,
            "frames": [],
        }

        for frame in sprite.frames:
            frame_data = {
                "alpha": frame.alpha,
            }

            # Layout
            if frame.HasField("layout"):
                frame_data["layout"] = {
                    "x": frame.layout.x,
                    "y": frame.layout.y,
                    "width": frame.layout.width,
                    "height": frame.layout.height,
                }

            # Transform
            if frame.HasField("transform"):
                frame_data["transform"] = {
                    "a": frame.transform.a,
                    "b": frame.transform.b,
                    "c": frame.transform.c,
                    "d": frame.transform.d,
                    "tx": frame.transform.tx,
                    "ty": frame.transform.ty,
                }

            # Clip path
            if frame.clipPath:
                frame_data["clipPath"] = frame.clipPath

            # Shapes
            if frame.shapes:
                frame_data["shapes"] = [_shape_to_dict(s) for s in frame.shapes]

            sprite_data["frames"].append(frame_data)

        data["sprites"].append(sprite_data)

    return data


def _shape_to_dict(shape) -> dict:
    """將 ShapeEntity 轉為 dict。"""
    d = {"type": shape.type}

    shape_type = shape.WhichOneof("args")
    if shape_type == "shape":
        d["args"] = {"d": shape.shape.d}
    elif shape_type == "rect":
        d["args"] = {
            "x": shape.rect.x,
            "y": shape.rect.y,
            "width": shape.rect.width,
            "height": shape.rect.height,
            "cornerRadius": shape.rect.cornerRadius,
        }
    elif shape_type == "ellipse":
        d["args"] = {
            "x": shape.ellipse.x,
            "y": shape.ellipse.y,
            "radiusX": shape.ellipse.radiusX,
            "radiusY": shape.ellipse.radiusY,
        }

    if shape.HasField("styles"):
        style = {}
        if shape.styles.HasField("fill"):
            style["fill"] = {
                "r": shape.styles.fill.r,
                "g": shape.styles.fill.g,
                "b": shape.styles.fill.b,
                "a": shape.styles.fill.a,
            }
        if shape.styles.HasField("stroke"):
            style["stroke"] = {
                "r": shape.styles.stroke.r,
                "g": shape.styles.stroke.g,
                "b": shape.styles.stroke.b,
                "a": shape.styles.stroke.a,
            }
        if shape.styles.strokeWidth:
            style["strokeWidth"] = shape.styles.strokeWidth
        d["styles"] = style

    if shape.HasField("transform"):
        d["transform"] = {
            "a": shape.transform.a,
            "b": shape.transform.b,
            "c": shape.transform.c,
            "d": shape.transform.d,
            "tx": shape.transform.tx,
            "ty": shape.transform.ty,
        }

    return d


# ---------------------------------------------------------------------------
# 主程式
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isfile(input_file):
        print(f"[錯誤] 找不到檔案: {input_file}")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 預設輸出目錄 = 檔名去掉副檔名
    if output_dir is None:
        output_dir = os.path.splitext(input_file)[0]

    # 讀取檔案
    with open(input_file, "rb") as f:
        data = f.read()

    print(f"[INFO] 讀取: {input_file} ({len(data):,} bytes)")

    # 偵測版本
    version = _detect_version(data)
    if version == 0:
        print("[錯誤] 無法辨識檔案格式 (不是 SVGA 1.x 或 2.x)")
        sys.exit(1)

    print(f"[INFO] 偵測到 SVGA {version}.x 格式")

    if version == 1:
        _extract_svga1(data, output_dir)
    else:
        _extract_svga2(data, output_dir, script_dir)


if __name__ == "__main__":
    main()
