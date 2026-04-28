# SVGA Tool

將 SVGA 動畫檔案解壓縮為獨立的圖片、音效、工程文件，以及反向打包回去。

## 依賴安裝

```bash
pip install protobuf grpcio-tools
```

首次執行時會自動從 `svga.proto` 編譯出 `svga_pb2.py`。

## 使用方法

### 解壓縮 SVGA

```bash
python svga_extract.py <input.svga> [output_dir]
```

- `output_dir` 可選，預設為檔名去掉副檔名。

### 打包回 SVGA

```bash
python svga_pack.py <input_dir> [output.svga]
```

- `output.svga` 可選，預設為目錄名稱加上 `.svga`。

### 完整工作流程

```bash
# 1. 解壓縮
python svga_extract.py animation.svga

# 2. 編輯資源（替換圖片、修改 animation.json 等）

# 3. 重新打包
python svga_pack.py animation output.svga
```

## 輸出結構

```
animation/
├── images/              # 所有圖片（PNG / WebP / JPG）
│   ├── img_001.png
│   └── ...
├── audio/               # 所有音效（MP3 / AAC / WAV / OGG），若有的話
│   └── audio_xxx.mp3
├── animation.json       # 工程文件 — 動畫參數、影格、變換矩陣、向量形狀
└── movie.bin            # 原始 Protobuf 二進位
```

## 支援格式

| 版本 | 封裝格式 | 支援狀態 |
|---|---|---|
| SVGA 1.x | ZIP + JSON | 解壓縮 |
| SVGA 2.x | zlib + Protobuf | 解壓縮 / 打包 |

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `svga_extract.py` | 解壓縮腳本 |
| `svga_pack.py` | 打包腳本 |
| `svga.proto` | SVGA 2.0 Protobuf 定義 |
| `svga_pb2.py` | 自動生成的 Protobuf Python 綁定（首次執行時產生） |
