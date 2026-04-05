from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


ROOT = Path("/Users/juxiantan/ai_agent_project/stock_quantification")
ARTIFACT_DIR = ROOT / "artifacts" / "2026-03"
CN_JSON = ARTIFACT_DIR / "cn_march_2026_backtest_rebalance.json"
US_JSON = ARTIFACT_DIR / "us_march_2026_backtest_rebalance.json"
OUTPUT_PNG = ARTIFACT_DIR / "march_2026_backtest_nav_curve.png"


Color = Tuple[int, int, int]


@dataclass(frozen=True)
class Series:
    label: str
    color: Color
    dates: List[str]
    values: List[float]


FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "01010", "00100", "00100", "00100", "01010", "10001"],
    "Y": ["10001", "01010", "00100", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00010", "00100", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00100", "01000", "10000", "00000", "00000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "%": ["11001", "11010", "00100", "01000", "10011", "10011", "00000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def load_series(path: Path, label: str, color: Color) -> Series:
    payload = json.loads(path.read_text(encoding="utf-8"))
    daily = payload["daily"]
    dates = [row["trade_date"] for row in daily]
    values = [float(row["end_of_day_nav"]) for row in daily]
    if not dates or not values:
        raise ValueError(f"Empty series in {path}")
    base = values[0]
    normalized = [value / base for value in values]
    return Series(label=label, color=color, dates=dates, values=normalized)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def new_canvas(width: int, height: int, background: Color = (250, 249, 246)) -> List[List[List[int]]]:
    return [[[background[0], background[1], background[2], 255] for _ in range(width)] for _ in range(height)]


def set_pixel(canvas: List[List[List[int]]], x: int, y: int, color: Color) -> None:
    if 0 <= y < len(canvas) and 0 <= x < len(canvas[0]):
        canvas[y][x][:3] = [color[0], color[1], color[2]]
        canvas[y][x][3] = 255


def draw_line(canvas, x0, y0, x1, y1, color: Color, thickness: int = 1) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        for tx in range(-(thickness // 2), thickness // 2 + 1):
            for ty in range(-(thickness // 2), thickness // 2 + 1):
                set_pixel(canvas, x0 + tx, y0 + ty, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def draw_rect(canvas, x, y, w, h, color: Color, fill: bool = False) -> None:
    if fill:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                set_pixel(canvas, xx, yy, color)
        return
    for xx in range(x, x + w):
        set_pixel(canvas, xx, y, color)
        set_pixel(canvas, xx, y + h - 1, color)
    for yy in range(y, y + h):
        set_pixel(canvas, x, yy, color)
        set_pixel(canvas, x + w - 1, yy, color)


def draw_text(canvas, x: int, y: int, text: str, color: Color, scale: int = 2) -> None:
    cursor_x = x
    for ch in text.upper():
        glyph = FONT_5X7.get(ch, FONT_5X7[" "])
        for row_idx, row in enumerate(glyph):
            for col_idx, bit in enumerate(row):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            set_pixel(canvas, cursor_x + col_idx * scale + sx, y + row_idx * scale + sy, color)
        cursor_x += 6 * scale


def draw_axes(canvas, left: int, top: int, right: int, bottom: int, color: Color) -> None:
    draw_line(canvas, left, top, left, bottom, color, thickness=2)
    draw_line(canvas, left, bottom, right, bottom, color, thickness=2)


def draw_grid(canvas, left: int, top: int, right: int, bottom: int, color: Color) -> None:
    width = right - left
    height = bottom - top
    for i in range(1, 5):
        x = left + int(width * i / 5)
        draw_line(canvas, x, top, x, bottom, color, thickness=1)
    for i in range(1, 5):
        y = top + int(height * i / 5)
        draw_line(canvas, left, y, right, y, color, thickness=1)


def render_series(canvas, series_list: Sequence[Series], left: int, top: int, right: int, bottom: int) -> None:
    palette = {series.label: series.color for series in series_list}
    all_values = [value for series in series_list for value in series.values]
    min_val = min(all_values)
    max_val = max(all_values)
    if math.isclose(min_val, max_val):
        max_val = min_val + 0.01
    span = max_val - min_val
    pad = 0.08 * span
    min_val -= pad
    max_val += pad
    chart_height = bottom - top
    chart_width = right - left

    def y_for(value: float) -> int:
        ratio = (value - min_val) / (max_val - min_val)
        return bottom - int(ratio * chart_height)

    def x_for(index: int, count: int) -> int:
        if count <= 1:
            return left
        return left + int(index * chart_width / (count - 1))

    for series in series_list:
        points = list(zip(series.dates, series.values))
        for idx in range(len(points) - 1):
            x0 = x_for(idx, len(points))
            y0 = y_for(points[idx][1])
            x1 = x_for(idx + 1, len(points))
            y1 = y_for(points[idx + 1][1])
            draw_line(canvas, x0, y0, x1, y1, palette[series.label], thickness=3)
        for idx, (_, value) in enumerate(points):
            x = x_for(idx, len(points))
            y = y_for(value)
            draw_rect(canvas, x - 2, y - 2, 5, 5, palette[series.label], fill=True)

    # y-axis labels
    for i in range(6):
        value = min_val + (max_val - min_val) * i / 5
        y = bottom - int(chart_height * i / 5)
        draw_text(canvas, left - 80, y - 8, f"{value:.2f}", (70, 70, 70), scale=1)

    # x-axis labels
    sample_dates = series_list[0].dates
    for idx in [0, len(sample_dates) // 2, len(sample_dates) - 1]:
        x = x_for(idx, len(sample_dates))
        draw_text(canvas, x - 30, bottom + 12, sample_dates[idx], (70, 70, 70), scale=1)


def draw_legend(canvas, x: int, y: int, items: Sequence[Series]) -> None:
    cursor_x = x
    for series in items:
        draw_rect(canvas, cursor_x, y + 4, 20, 8, series.color, fill=True)
        draw_text(canvas, cursor_x + 28, y, series.label, (40, 40, 40), scale=1)
        cursor_x += 200


def encode_png(canvas: List[List[List[int]]]) -> bytes:
    height = len(canvas)
    width = len(canvas[0])
    raw = bytearray()
    for row in canvas:
        raw.append(0)
        for pixel in row:
            raw.extend(bytes(pixel))
    compressed = zlib.compress(bytes(raw), level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )


def build_chart(series_list: Sequence[Series]) -> List[List[List[int]]]:
    width, height = 1500, 900
    canvas = new_canvas(width, height)
    plot_left, plot_top, plot_right, plot_bottom = 140, 120, 1400, 750
    draw_text(canvas, 140, 40, "MARCH 2026 BACKTEST NAV CURVE", (20, 20, 20), scale=2)
    draw_text(canvas, 140, 72, "NORMALIZED FROM 1.00 START", (80, 80, 80), scale=1)
    draw_grid(canvas, plot_left, plot_top, plot_right, plot_bottom, (226, 224, 218))
    draw_axes(canvas, plot_left, plot_top, plot_right, plot_bottom, (60, 60, 60))
    render_series(canvas, series_list, plot_left, plot_top, plot_right, plot_bottom)
    draw_legend(canvas, 140, 790, series_list)
    return canvas


def main() -> None:
    cn = load_series(CN_JSON, "CN BACKTEST", (196, 76, 65))
    us = load_series(US_JSON, "US BACKTEST", (45, 110, 168))
    canvas = build_chart([cn, us])
    OUTPUT_PNG.write_bytes(encode_png(canvas))
    print(json.dumps({"png": str(OUTPUT_PNG), "series": [cn.label, us.label]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
