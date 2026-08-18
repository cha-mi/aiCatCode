"""
build_sprites.py — 桌面宠物素材统一构建脚本（全 rembg AI 抠图版）

替换 video/ 中的视频后运行此脚本，自动完成 AI 抠图 → 裁剪 → 缩放 → 雪碧图拼贴全流程。
所有动画均使用 rembg AI 模型抠除背景，无需绿幕/蓝幕，支持任意背景的视频。

用法:
  python build_sprites.py              # 生成全部 sprite
  python build_sprites.py yawn groom    # 只生成指定 sprite
  python build_sprites.py --list        # 列出所有可用 sprite
  python build_sprites.py --help        # 显示帮助

前置条件:
  pip install rembg opencv-python Pillow numpy

素材目录结构:
  video/       — 原始视频文件 (.mp4)，任意背景
  frames/  — 转头关键帧 PNG (37张透明图，需预先去背景)
  output/      — 生成的雪碧图 (.webp)
  output/base_poop.jpg — 💩emoji 源图
"""

import os, sys, math, json
import numpy as np
from PIL import Image, ImageDraw
import cv2

from matting_utils import (
    sample_frames_uniform,
    remove_bg_rembg,
    crop_nontransparent, build_sprite,
    resize_frames, resize_frames_by_height,
    mirror_sprite,
)

# ========== 路径配置 ==========
ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(ROOT, "video")
FRAMES_DIR = os.path.join(ROOT, "frames")
OUT_DIR = os.path.join(ROOT, "output")
FPS_OUT = 24

# ========== 雪碧图配置 ==========
# 全部使用 rembg AI 抠图，无需绿幕/蓝幕
#
# type 可选:
#   transparent_frames — 从透明 PNG 关键帧拼贴（无抠图，需预先去背景）
#   rembg              — 视频 rembg AI 抠图
#   rembg_image        — 单张图片 rembg AI 抠图（用于 poop_icon）
#   mirror             — 从已有 sprite 镜像翻转（walk_left）
#   poop_emoji         — 在 sprite 上叠加方向感知💩emoji

SPRITES = {
    # ===== 转头主循环（透明 PNG 关键帧，无需抠图） =====
    "sprite": {
        "type": "transparent_frames",
        "input_dir": FRAMES_DIR,
        "output": "sprite.webp",
        "frame_height": 400,
        "cols": 12,
        "margin": 15,
        "extras": True,  # 同时输出 framefront.webp + anglekeys.json
    },

    # ===== 💩模式转头（sprite + poop emoji 叠加） =====
    "sprite_poop": {
        "type": "poop_emoji",
        "input": "sprite.webp",
        "base_poop": "base_poop.jpg",
        "output": "sprite_poop.webp",
        "frame_width": 322,
        "frame_height": 400,
        "cols": 12,
        "num_frames": 37,
        "emoji_size": 124,
    },

    # ===== 哈欠 =====
    "yawn": {
        "type": "rembg",
        "video": "哈欠.mp4",
        "output": "yawn_sprite.webp",
        "frame_width": 322,
        "frame_height": 400,
        "crop_bbox": True,
    },

    # ===== 舔毛 =====
    "groom": {
        "type": "rembg",
        "video": "舔毛.mp4",
        "output": "groom_sprite.webp",
        "frame_width": 322,
        "frame_height": 400,
        "crop_bbox": True,
    },

    # ===== 猫条 =====
    "feed": {
        "type": "rembg",
        "video": "猫条.mp4",
        "output": "feed_sprite.webp",
        "frame_width": 322,
        "frame_height": 400,
        "crop_bbox": True,
    },

    # ===== 咀嚼 =====
    "chew": {
        "type": "rembg",
        "video": "咀嚼.mp4",
        "output": "chew_sprite.webp",
        "frame_width": 322,
        "frame_height": 400,
        "crop_bbox": True,
    },

    # ===== 走路右（按原视频比例等比缩放） =====
    "walk_right": {
        "type": "rembg",
        "video": "走路.mp4",
        "output": "walk_right_sprite.webp",
        "frame_height": 400,  # 仅指定高度，宽度按等比
        "crop_bbox": True,
    },

    # ===== 走路左（walk_right 镜像翻转） =====
    "walk_left": {
        "type": "mirror",
        "source": "walk_right_sprite.webp",
        "output": "walk_left_sprite.webp",
        # 显式指定帧尺寸，避免 process_mirror 用最大公约数启发式误判
        # （7616 既能被 16 整除=476，也能被 17 整除=448，真实布局是 16×476）
        "frame_width": 476,
        "frame_height": 400,
        "cols": 16,
        "rows": 16,
    },

    # ===== 铲屎 =====
    "scoop": {
        "type": "rembg",
        "video": "铲屎.mp4",
        "output": "scoop_sprite.webp",
        "frame_width": 322,
        "frame_height": 400,
        "crop_bbox": True,
    },

    # ===== 准星 =====
    "crosshair": {
        "type": "rembg",
        "video": "准星.mp4",
        "output": "crosshair_sprite.webp",
        "frame_height": 260,
        "crop_bbox": True,
    },

    # ===== 开枪 =====
    "shoot": {
        "type": "rembg",
        "video": "开枪.mp4",
        "output": "shoot_sprite.webp",
        "frame_height": 480,
        "crop_bbox": True,
    },

    # ===== 爆炸 =====
    "explosion": {
        "type": "rembg",
        "video": "爆炸.mp4",
        "output": "explosion_sprite.webp",
        "frame_height": 260,
        "crop_bbox": True,
    },

    # ===== 💩图标（从 base_poop.jpg 用 rembg 抠图） =====
    "poop_icon": {
        "type": "rembg_image",
        "input": "base_poop.jpg",
        "output": "poop_icon.webp",
        "size": 80,
    },
}

# ========== 构建顺序（mirror 依赖 source） ==========
BUILD_ORDER = [
    "sprite", "sprite_poop",
    "yawn", "groom", "feed",
    "chew", "walk_right", "walk_left",
    "scoop",
    "crosshair", "shoot", "explosion",
    "poop_icon",
]


# ============================================================
# 处理函数
# ============================================================

def _video_path(video_name):
    """获取视频完整路径"""
    p = os.path.join(VIDEO_DIR, video_name)
    if os.path.exists(p):
        return p
    p2 = os.path.join(ROOT, video_name)
    if os.path.exists(p2):
        return p2
    return p


# ========== 透明帧拼贴（转头主循环） ==========

def process_transparent_frames(name, cfg):
    print(f"\n=== {name} (transparent_frames) ===")
    input_dir = cfg["input_dir"]
    if not os.path.isdir(input_dir):
        print(f"  SKIP: 目录不存在 {input_dir}")
        return None
    files = sorted([f for f in os.listdir(input_dir) if f.endswith('.png')])
    if not files:
        print(f"  SKIP: 无 PNG 文件")
        return None
    print(f"  读取 {len(files)} 张关键帧...")
    key_frames = [Image.open(os.path.join(input_dir, f)).convert("RGBA") for f in files]

    # 统一裁剪到 alpha bounding box
    min_x, min_y, max_x, max_y = float('inf'), float('inf'), 0, 0
    for img in key_frames:
        bbox = img.split()[3].getbbox()
        if bbox:
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])
    margin = cfg.get("margin", 15)
    min_x = max(0, min_x - margin)
    min_y = max(0, min_y - margin)
    max_x = min(key_frames[0].width, max_x + margin)
    max_y = min(key_frames[0].height, max_y + margin)
    crop_w = max_x - min_x
    crop_h = max_y - min_y

    target_h = cfg["frame_height"]
    scale = target_h / crop_h
    target_w = int(crop_w * scale)
    print(f"  裁剪: {crop_w}x{crop_h} -> 缩放 {target_w}x{target_h}")

    resized = [img.crop((min_x, min_y, max_x, max_y)).resize((target_w, target_h), Image.LANCZOS)
               for img in key_frames]

    out_path = os.path.join(OUT_DIR, cfg["output"])
    result = build_sprite(resized, out_path, cols=cfg["cols"])

    # 额外输出 framefront + anglekeys
    if cfg.get("extras"):
        resized[0].save(os.path.join(OUT_DIR, "framefront.webp"), "WEBP", quality=90)
        num_total = len(resized)
        anglekeys = {}
        for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
            anglekeys[str(angle)] = int(round(angle / 360 * (num_total - 1)))
        ak_data = {
            "angle_keys": anglekeys,
            "total_frames": num_total,
            "frame_width": target_w,
            "frame_height": target_h,
            "sprite_cols": cfg["cols"],
            "sprite_rows": result["rows"],
            "description": "0=up, 90=right, 180=down, 270=left, clockwise"
        }
        with open(os.path.join(OUT_DIR, "anglekeys.json"), 'w', encoding='utf-8') as f:
            json.dump(ak_data, f, indent=2, ensure_ascii=False)
        print(f"  extras: framefront.webp + anglekeys.json")

    return {"key": name, "frames": result["frames"],
            "frame_w": result["frame_w"], "frame_h": result["frame_h"],
            "cols": result["cols"], "rows": result["rows"]}


# ========== rembg AI 视频抠图 ==========

def process_rembg(name, cfg):
    print(f"\n=== {name} (rembg) ===")
    vpath = _video_path(cfg["video"])
    if not os.path.exists(vpath):
        print(f"  SKIP: 视频不存在 {vpath}")
        return None
    print(f"  采样帧 @ {FPS_OUT}fps...")
    frames = sample_frames_uniform(vpath, FPS_OUT)
    if not frames:
        print(f"  SKIP: 无帧")
        return None
    print(f"  {len(frames)} 帧, 原始 {frames[0].size}")

    print(f"  rembg AI 抠图...")
    out_frames = []
    for i, im in enumerate(frames):
        im = remove_bg_rembg(im)
        out_frames.append(im)
        if (i + 1) % 10 == 0 or i == 0:
            print(f"    {i+1}/{len(frames)}")

    if cfg.get("crop_bbox"):
        print(f"  裁剪透明区域...")
        out_frames = crop_nontransparent(out_frames, margin=4)

    # 缩放
    target_w = cfg.get("frame_width")
    target_h = cfg.get("frame_height")
    if target_w and target_h:
        print(f"  缩放到 {target_w}x{target_h}...")
        out_frames = resize_frames(out_frames, target_w, target_h)
    elif target_h:
        out_frames, new_w = resize_frames_by_height(out_frames, target_h)
        print(f"  等比缩放到 {new_w}x{target_h}")

    out_path = os.path.join(OUT_DIR, cfg["output"])
    result = build_sprite(out_frames, out_path)
    return {"key": name, "frames": result["frames"],
            "frame_w": result["frame_w"], "frame_h": result["frame_h"],
            "cols": result["cols"], "rows": result["rows"]}


# ========== rembg AI 图片抠图（poop_icon） ==========

def process_rembg_image(name, cfg):
    print(f"\n=== {name} (rembg_image) ===")
    in_path = os.path.join(OUT_DIR, cfg["input"])
    if not os.path.exists(in_path):
        print(f"  SKIP: 输入文件不存在 {in_path}")
        return None
    print(f"  rembg AI 抠图...")
    img = Image.open(in_path).convert("RGBA")
    img = remove_bg_rembg(img)

    # 裁剪透明区域
    img = crop_nontransparent([img], margin=2)[0]

    # 缩放到目标尺寸（保持比例，居中）
    bbox = img.getbbox()
    if not bbox:
        print(f"  SKIP: 抠图后无内容")
        return None
    cropped = img.crop(bbox)
    bw, bh = cropped.size
    size = cfg["size"]
    scale = min(size / bw, size / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    offx = (size - nw) // 2
    offy = (size - nh) // 2
    scaled = cropped.resize((nw, nh), Image.LANCZOS)
    final = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    final.paste(scaled, (offx, offy), scaled)

    out_path = os.path.join(OUT_DIR, cfg["output"])
    final.save(out_path, 'WEBP', quality=95, method=6, lossless=False)
    print(f"  -> {cfg['output']} {size}x{size} {os.path.getsize(out_path)} bytes")
    return {"key": name, "frames": 1, "frame_w": size, "frame_h": size, "cols": 1, "rows": 1}


# ========== 镜像翻转 ==========

def process_mirror(name, cfg):
    print(f"\n=== {name} (mirror) ===")
    src_path = os.path.join(OUT_DIR, cfg["source"])
    if not os.path.exists(src_path):
        print(f"  SKIP: 源文件不存在 {src_path}")
        return None
    sprite = Image.open(src_path).convert("RGBA")
    W, H = sprite.size
    # 优先使用配置中显式指定的帧尺寸/cols/rows（避免启发式误判）
    if cfg.get("cols") and cfg.get("rows") and cfg.get("frame_width") and cfg.get("frame_height"):
        cols = cfg["cols"]
        rows = cfg["rows"]
        fw = cfg["frame_width"]
        fh = cfg["frame_height"]
    else:
        # 启发式推断 cols/rows（最大公约数）
        cols = 1
        for try_cols in range(20, 0, -1):
            if W % try_cols == 0:
                cols = try_cols
                break
        fw = W // cols
        rows = 1
        for try_rows in range(20, 0, -1):
            if H % try_rows == 0:
                rows = try_rows
                break
        fh = H // rows
    print(f"  sprite={W}x{H}, frame={fw}x{fh}, cols={cols}, rows={rows}")
    out_path = os.path.join(OUT_DIR, cfg["output"])
    result = mirror_sprite(src_path, out_path, fw, fh, cols, rows)
    return {"key": name, "frames": result["frames"],
            "frame_w": result["frame_w"], "frame_h": result["frame_h"],
            "cols": result["cols"], "rows": result["rows"]}


# ========== 💩emoji 叠加（sprite + poop emoji） ==========

def _prepare_poop_emoji(jpg_path, size):
    """处理 base_poop.jpg -> 去白底 + 检测眼睛 + 去瞳孔"""
    img = Image.open(jpg_path).convert('RGBA')
    arr = np.array(img)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    H, W = arr.shape[:2]

    # 白底抠除（flood fill 从四角连通白色背景）
    loose_white = (r > 230) & (g > 230) & (b > 230)
    lw_u8 = (loose_white.astype(np.uint8)) * 255
    fm = np.zeros((H + 2, W + 2), np.uint8)
    for seed in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        cv2.floodFill(lw_u8, fm, seed, 128, 0, 0, 4)
    bg_white = (lw_u8 == 128)

    alpha = 255 * np.ones(arr.shape[:2], np.uint8)
    pure_bg = bg_white & (r > 248) & (g > 248) & (b > 248)
    alpha[pure_bg] = 0
    near_bg = bg_white & ~pure_bg
    dist_bg = np.maximum.reduce([255 - r, 255 - g, 255 - b]).astype(np.uint8)
    alpha[near_bg] = np.clip(dist_bg[near_bg] * 8, 0, 255)
    arr[..., 3] = alpha

    # 检测白色眼睛区域
    on_emoji = arr[..., 3] > 120
    near_white_h = (arr[..., 0] > 200) & (arr[..., 1] > 200) & (arr[..., 2] > 200)
    is_white_eye = on_emoji & near_white_h
    num, labels, stats, cents = cv2.connectedComponentsWithStats(
        is_white_eye.astype(np.uint8) * 255, connectivity=8)
    eye_areas = []
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] > 100:
            eye_areas.append((stats[i, cv2.CC_STAT_AREA], cents[i], i))
    eye_areas.sort(reverse=True)
    if len(eye_areas) < 2:
        raise RuntimeError(f'未检测到两只眼睛，只找到 {len(eye_areas)} 个白块')

    eye_cents = [eye_areas[0][1], eye_areas[1][1]]
    eye_cents.sort(key=lambda c: c[0])
    left_eye = (float(eye_cents[0][0]), float(eye_cents[0][1]))
    right_eye = (float(eye_cents[1][0]), float(eye_cents[1][1]))

    # 检测瞳孔位置
    is_pupil_h = (arr[..., 0] < 60) & (arr[..., 1] < 60) & (arr[..., 2] < 60) & on_emoji

    def find_pupil(xc, yc, search_hw):
        x0, x1 = max(0, int(xc - search_hw)), min(W, int(xc + search_hw))
        y0, y1 = max(0, int(yc - search_hw)), min(H, int(yc + search_hw))
        roi = is_pupil_h[y0:y1, x0:x1]
        ys, xs = np.where(roi)
        if len(xs) == 0:
            return xc, yc, 2.0
        return float(xs.mean() + x0), float(ys.mean() + y0), float(math.sqrt(len(xs) / math.pi))

    hw = int(round(math.hypot(right_eye[0] - left_eye[0], right_eye[1] - left_eye[1]) * 0.45))
    lp_cx, lp_cy, pupil_R_h = find_pupil(*left_eye, hw)
    rp_cx, rp_cy, _ = find_pupil(*right_eye, hw)

    # 采样眼白色
    def sample_white(eye_cx, eye_cy, pupil_cx, pupil_cy, pr):
        samples = []
        hw2 = int(round(pr * 3))
        x0, x1 = max(0, int(eye_cx) - hw2), min(W, int(eye_cx) + hw2)
        y0, y1 = max(0, int(eye_cy) - hw2), min(H, int(eye_cy) + hw2)
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                de = math.hypot(xx - eye_cx, yy - eye_cy)
                dp = math.hypot(xx - pupil_cx, yy - pupil_cy)
                if pr * 1.6 < de < pr * 3.5 and dp > pr * 1.5:
                    px = arr[yy, xx]
                    if px[3] > 200 and px[0] > 220 and px[1] > 220 and px[2] > 220:
                        samples.append(px[:3])
        if samples:
            s = np.median(np.array(samples), axis=0).astype(int)
            return (int(s[0]), int(s[1]), int(s[2]), 255)
        return (252, 252, 252, 255)

    wh_L = sample_white(*left_eye, lp_cx, lp_cy, pupil_R_h)
    wh_R = sample_white(*right_eye, rp_cx, rp_cy, pupil_R_h)

    # 获取眼睛统计信息
    _, ctA, lblA = eye_areas[0]
    _, ctB, lblB = eye_areas[1]
    st_L = stats[lblB] if abs(ctB[0] - left_eye[0]) < abs(ctA[0] - left_eye[0]) else stats[lblA]
    st_R = stats[lblB] if abs(ctB[0] - right_eye[0]) < abs(ctA[0] - right_eye[0]) else stats[lblA]

    def eye_r(st):
        return max(1.0, (st[cv2.CC_STAT_WIDTH] + st[cv2.CC_STAT_HEIGHT]) / 4.0)
    eye_R_h = min(eye_r(st_L), eye_r(st_R))

    # 用眼白色覆盖瞳孔
    body_h = Image.fromarray(arr.copy())
    dr = ImageDraw.Draw(body_h)
    R_cover = int(math.ceil(pupil_R_h * 1.35))
    dr.ellipse([lp_cx - R_cover, lp_cy - R_cover, lp_cx + R_cover, lp_cy + R_cover], fill=wh_L)
    dr.ellipse([rp_cx - R_cover, rp_cy - R_cover, rp_cx + R_cover, rp_cy + R_cover], fill=wh_R)

    # 裁剪 + 缩放到目标尺寸
    bbox = body_h.getbbox()
    if not bbox:
        bbox = (0, 0, W, H)
    bx0, by0, bx1, by1 = bbox
    bw, bh = bx1 - bx0, by1 - by0
    scale = min(size / bw, size / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    offx = (size - nw) // 2
    offy = (size - nh) // 2
    body_scaled = body_h.crop(bbox).resize((nw, nh), Image.LANCZOS)
    body_final = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    body_final.paste(body_scaled, (offx, offy), body_scaled)

    def map_coord(hx, hy):
        return (hx - bx0) * scale + offx, (hy - by0) * scale + offy

    left_final = map_coord(*left_eye)
    right_final = map_coord(*right_eye)
    pupil_r_final = pupil_R_h * scale
    base_shift = max(0.0, (eye_R_h * scale) - pupil_r_final * 0.8)
    max_shift_final = min(base_shift * 1.6, base_shift + pupil_r_final * 0.5)
    max_shift_final = max(max_shift_final, min(1.8, base_shift * 2.0))
    return body_final, left_final, right_final, pupil_r_final, max_shift_final


_POOP_ANGLEKEYS = {0: 0, 14: 45, 18: 90, 22: 135, 24: 180, 28: 225, 31: 270, 33: 315}

def _frame_to_angle(fi, num_frames=37):
    items = sorted(_POOP_ANGLEKEYS.items())
    for i in range(len(items)):
        f0, a0 = items[i]
        f1, a1 = items[(i + 1) % len(items)]
        if i == len(items) - 1:
            a1 = a1 + 360
            if fi >= f0 or fi <= f1:
                if fi >= f0:
                    t = (fi - f0) / ((num_frames - f0) + f1)
                else:
                    t = ((num_frames - f0) + fi) / ((num_frames - f0) + f1)
                return (a0 + t * (a1 - a0)) % 360
        elif f0 <= fi <= f1:
            t = (fi - f0) / (f1 - f0)
            return a0 + t * (a1 - a0)
    return 0.0


def _angle_to_eyeshift(angle_deg, shift_rad):
    m = math.radians(90 - angle_deg)
    return (round(shift_rad * math.cos(m)),
            round(-shift_rad * math.sin(m)))


def _make_poop_emoji(base_body, eye_L, eye_R, pupil_R, max_shift, angle_deg):
    img = base_body.copy()
    dr = ImageDraw.Draw(img)
    dx, dy = _angle_to_eyeshift(angle_deg, max_shift)
    def draw_pupil(cx, cy):
        px, py = cx + dx, cy + dy
        r = pupil_R
        dr.ellipse([px - r, py - r, px + r, py + r], fill=(15, 15, 15, 255))
        hl = pupil_R * 0.35
        dr.ellipse([px - pupil_R * 0.42 - hl, py - pupil_R * 0.45 - hl,
                    px - pupil_R * 0.42 + hl, py - pupil_R * 0.45 + hl],
                   fill=(255, 255, 255, 255))
    draw_pupil(*eye_L)
    draw_pupil(*eye_R)
    return img


def process_poop_emoji(name, cfg):
    print(f"\n=== {name} (poop_emoji) ===")
    sprite_path = os.path.join(OUT_DIR, cfg["input"])
    base_poop_path = os.path.join(OUT_DIR, cfg["base_poop"])
    if not os.path.exists(sprite_path):
        print(f"  SKIP: sprite 不存在 {sprite_path}")
        return None
    if not os.path.exists(base_poop_path):
        print(f"  SKIP: base_poop 不存在 {base_poop_path}")
        return None

    print(f"  准备 emoji...")
    emoji_size = cfg["emoji_size"]
    body, eye_L, eye_R, pupil_r, max_shift = _prepare_poop_emoji(base_poop_path, emoji_size)

    sprite = Image.open(sprite_path).convert('RGBA')
    out = sprite.copy()
    fw = cfg["frame_width"]
    fh = cfg["frame_height"]
    cols = cfg["cols"]
    num_frames = cfg["num_frames"]

    print(f"  叠加 {num_frames} 帧 emoji...")
    for fi in range(num_frames):
        col = fi % cols
        row = fi // cols
        fx, fy = col * fw, row * fh
        angle = _frame_to_angle(fi, num_frames)
        emoji = _make_poop_emoji(body, eye_L, eye_R, pupil_r, max_shift, angle)
        px = fx + (fw - emoji_size - 6)
        py = fy + (fh - emoji_size - 6)
        out.paste(emoji, (px, py), emoji)

    out_path = os.path.join(OUT_DIR, cfg["output"])
    out.save(out_path, 'WEBP', quality=90, method=6)
    print(f"  -> {cfg['output']} {out.size} {os.path.getsize(out_path)/1024:.0f}KB")
    return {"key": name, "frames": num_frames,
            "frame_w": fw, "frame_h": fh, "cols": cols,
            "rows": (num_frames + cols - 1) // cols}


# ========== 分发器 ==========
PROCESSORS = {
    "transparent_frames": process_transparent_frames,
    "rembg": process_rembg,
    "rembg_image": process_rembg_image,
    "mirror": process_mirror,
    "poop_emoji": process_poop_emoji,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return
    if "--list" in args:
        print("可用 sprite:")
        for name in BUILD_ORDER:
            cfg = SPRITES[name]
            print(f"  {name:15s} type={cfg['type']}")
        return

    # 确定要处理的 sprite
    if args:
        names = args
        for n in names:
            if n not in SPRITES:
                print(f"错误: 未知 sprite '{n}'，可用: {', '.join(BUILD_ORDER)}")
                return
        # 自动添加依赖
        if "walk_left" in names and "walk_right" not in names:
            names.insert(names.index("walk_left"), "walk_right")
        if "sprite_poop" in names and "sprite" not in names:
            names.insert(names.index("sprite_poop"), "sprite")
    else:
        names = BUILD_ORDER

    print(f"将处理 {len(names)} 个 sprite: {', '.join(names)}")
    print(f"视频目录: {VIDEO_DIR}")
    print(f"输出目录: {OUT_DIR}")

    results = []
    for name in names:
        cfg = SPRITES[name]
        processor = PROCESSORS.get(cfg["type"])
        if not processor:
            print(f"\n跳过 {name}: 未知 type '{cfg['type']}'")
            continue
        try:
            r = processor(name, cfg)
            if r:
                results.append(r)
        except Exception as e:
            print(f"\n错误 {name}: {e}")
            import traceback
            traceback.print_exc()

    # 输出 SUMMARY
    print("\n" + "=" * 60)
    print("SUMMARY — 将以下代码粘贴到 index.html 的动画配置区")
    print("=" * 60)

    # IDLE_ANIMATIONS 列表（yawn + groom）
    idle_keys = [r["key"] for r in results if r["key"] in ("yawn", "groom")]
    idle_results = [r for r in results if r["key"] in ("yawn", "groom")]
    if idle_results:
        print("const IDLE_ANIMATIONS = [")
        for r in idle_results:
            print(f"    {{ name: '{r['key']}', sprite: '{r['key']}_sprite.webp', "
                  f"frames: {r['frames']}, cols: {r['cols']}, rows: {r['rows']}, "
                  f"frameWidth: {r['frame_w']}, frameHeight: {r['frame_h']} }},")
        print("];")

    # 单独的动画常量
    single_keys = ["feed", "scoop", "chew", "walk_right", "walk_left",
                   "crosshair", "shoot", "explosion"]
    for r in results:
        key = r["key"]
        if key in ("sprite", "sprite_poop", "poop_icon", "yawn", "groom"):
            if key not in ("yawn", "groom"):
                print(f"  // {key}: {r['frames']} frames, {r['cols']}x{r['rows']}")
            continue
        const_name = f"{key.upper()}_ANIMATION"
        sprite_name = f"{key}_sprite.webp"
        print(f"""
const {const_name} = {{
    name: '{key}',
    sprite: '{sprite_name}',
    frames: {r['frames']},
    cols: {r['cols']},
    rows: {r['rows']},
    frameWidth: {r['frame_w']},
    frameHeight: {r['frame_h']},
}};""")

    print("\n// 提示：")
    print("//   1. IDLE_ANIMATIONS 替换 index.html 中对应的列表")
    print("//   2. 各 _ANIMATION 常量替换 index.html 中对应的常量")
    print("//   3. 各动画已自动包含 frameWidth/frameHeight，setIdleAnimFrame 会自动适配")
    print("\nDone!")


if __name__ == "__main__":
    main()
