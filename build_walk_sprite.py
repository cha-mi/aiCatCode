"""
生成走路动画 sprite（walk_right, walk_left）
蓝幕抠图 + 水印去除 + 裁剪 + 缩放 + 生成 sprite
walk_right: 原视频方向（猫面向右走）
walk_left: 镜像翻转（猫面向左走）
"""
import cv2
import numpy as np
from PIL import Image
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.path.join(SCRIPT_DIR, 'video', '走路.mp4')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output')
TARGET_WIDTH = 322
TARGET_HEIGHT = 400
SPRITE_COLS = 12

# 裁剪区域（和其他 sprite 保持一致，适配 720x960 视频）
CROP_X = 19
CROP_Y = 90
CROP_W = 701
CROP_H = 870

# 蓝幕抠图参数（背景 HSV≈(104,200,150)）
# 走路视频猫体蓝色反光极少（S>=80,V>=50 仅 3.9%），可以用更宽松的严格阈值
# 严格阈值：S>=80, V>=50，覆盖脚底边缘蓝色残留（S>=120,V>=80 仅覆盖 98%）
BLUE_HSV_LOWER = np.array([95, 80, 50])
BLUE_HSV_UPPER = np.array([135, 255, 255])
# 宽松阈值用于边缘清理：捕获抗锯齿半透明蓝色像素
BLUE_HSV_LOOSE_LOWER = np.array([90, 40, 30])
BLUE_HSV_LOOSE_UPPER = np.array([140, 255, 255])


def is_blue_hsv(frame_bgr):
    """HSV 空间判定蓝色背景"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER) > 0


def detect_watermark_mask(video_path):
    """检测静态水印（走路视频可能没有，返回None或小掩码）"""
    cap = cv2.VideoCapture(video_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idxs = np.linspace(0, max(n - 1, 0), min(30, max(n, 1))).astype(int)
    frames_bgr = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, f = cap.read()
        if ret:
            frames_bgr.append(f)
    cap.release()
    if not frames_bgr:
        return None

    h, w = frames_bgr[0].shape[:2]
    stack = np.stack([f.astype(np.float32) for f in frames_bgr], 0)
    std_max = stack.std(0).max(2)

    blue_masks = [is_blue_hsv(f) for f in frames_bgr]
    always_blue = np.stack(blue_masks, 0).all(0)

    # 静态非蓝色 = 水印候选
    static_nonblue = (std_max < 5) & ~always_blue
    wm = static_nonblue.astype(np.uint8) * 255
    wm = cv2.dilate(wm, np.ones((3, 3), np.uint8), iterations=1)

    # 空间过滤：只在右下角搜索
    wm_full = np.zeros((h, w), np.uint8)
    search_x = int(w * 0.5)
    search_y = int(h * 0.7)
    wm_full[search_y:, search_x:] = wm[search_y:, search_x:]

    # 连通块分析
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(wm_full, connectivity=8)
    wm_small = np.zeros((h, w), np.uint8)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if 30 < area < 5000:
            wm_small[labels == i] = 255

    if not np.any(wm_small > 0):
        return None

    # 膨胀覆盖边缘
    wm_small = cv2.dilate(wm_small, np.ones((3, 3), np.uint8), iterations=2)
    return wm_small if np.any(wm_small > 0) else None


def safe_clean_blue_edges(image_bgra, alpha_threshold=80, neighbor_radius=3):
    """
    清理半透明蓝色边缘像素，但保护与不透明前景相邻的像素（如脚部边缘）。
    直接修改 image_bgra 的 alpha 通道。
    """
    alpha = image_bgra[:, :, 3]
    semi_msk = (alpha > 0) & (alpha < alpha_threshold)
    if not np.any(semi_msk):
        return

    # 膨胀不透明前景区域，得到"保护带"——与前景相邻的半透明像素不被清除
    opaque = (alpha >= alpha_threshold).astype(np.uint8)
    kernel = np.ones((2 * neighbor_radius + 1, 2 * neighbor_radius + 1), np.uint8)
    protected = cv2.dilate(opaque, kernel, iterations=1)

    # 只清理：半透明 + 蓝色 + 不受保护
    candidates = semi_msk & (protected == 0)
    if not np.any(candidates):
        return

    ys, xs = np.where(candidates)
    bgr = image_bgra[ys, xs, :3]
    hsv_pix = cv2.cvtColor(
        bgr.reshape(1, -1, 3).astype(np.uint8),
        cv2.COLOR_BGR2HSV
    ).reshape(-1, 3)
    is_blue = ((hsv_pix[:, 0] >= 95) & (hsv_pix[:, 0] <= 135) &
               (hsv_pix[:, 1] >= 15) & (hsv_pix[:, 2] >= 15))
    if np.any(is_blue):
        image_bgra[ys[is_blue], xs[is_blue], 3] = 0


def mat_blue_screen(frame, wm_mask=None):
    """蓝幕抠图 + 去水印，返回 BGRA 图像"""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER)

    # 边缘清理：宽松阈值 + 四角 flood fill
    loose_blue = cv2.inRange(hsv, BLUE_HSV_LOOSE_LOWER, BLUE_HSV_LOOSE_UPPER)
    # 大 kernel 膨胀 (35px) 连接前景边缘的抗锯齿蓝色
    strict_dilated = cv2.dilate(mask, np.ones((35, 35), np.uint8), iterations=1)
    loose_connected = (loose_blue > 0) & (strict_dilated > 0)
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = loose_blue.copy()
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(flood_fill, flood_mask, seed, 128, 0, 0, 4)
    edge_bg = (flood_fill == 128) & loose_connected
    mask[edge_bg] = 255

    # 形态学操作：仅 CLOSE 填充小空洞，不做 OPEN/dilate（避免吃掉脚趾等细小前景特征）
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    fg_mask = 255 - mask
    fg_before_fill = fg_mask.copy()

    # 填充内部空洞
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = fg_mask.copy()
    cv2.floodFill(flood_fill, flood_mask, (0, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (0, h - 1), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, h - 1), 128)
    fg_mask[flood_fill == 0] = 255

    # 恢复被误填为前景的蓝色背景（使用抠图统一阈值）
    strict_blue = cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER) > 0
    filled_pixels = (fg_mask > 0) & (fg_before_fill == 0)
    filled_mask = filled_pixels.astype(np.uint8) * 255
    num_filled, filled_labels, filled_stats, _ = cv2.connectedComponentsWithStats(filled_mask, connectivity=8)
    for i in range(1, num_filled):
        area = filled_stats[i, cv2.CC_STAT_AREA]
        if area > 500:
            region = (filled_labels == i)
            region_blue = region & (strict_blue | edge_bg)
            blue_ratio = np.sum(region_blue) / area
            if blue_ratio > 0.5:
                fg_mask[region_blue] = 0

    # 只保留最大连通分量
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    if num_labels > 1:
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        fg_mask = (labels == largest_label).astype(np.uint8) * 255

    # 轻微模糊抗锯齿（不 erode，避免猫体边缘内缩导致腿部缺口）
    fg_mask = cv2.GaussianBlur(fg_mask, (3, 3), 0)

    # 去水印
    if wm_mask is not None:
        fg_mask[wm_mask > 0] = 0

    result = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    result[:, :, 3] = fg_mask

    # 后处理：清理外圈蓝色残留（保护与前景相邻的脚部边缘）
    safe_clean_blue_edges(result)

    return result


def process_video(mirror=False):
    """处理视频，生成 sprite（mirror=True 生成左走版本）"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    direction = 'left' if mirror else 'right'
    name = f'walk_{direction}'
    print(f'\n处理 walk_{direction}...')

    wm_mask = detect_watermark_mask(VIDEO_PATH)
    if wm_mask is not None and np.sum(wm_mask) > 0:
        print(f'  检测到水印，掩码像素数: {np.sum(wm_mask > 0)}')
    else:
        print(f'  未检测到水印')

    cap = cv2.VideoCapture(VIDEO_PATH)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f'  {frame_count} 帧, {fps}fps')

    frames = []
    for i in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            break

        frame_rgba = mat_blue_screen(frame, wm_mask)

        # 镜像翻转
        if mirror:
            frame_rgba = frame_rgba[:, ::-1, :]

        # 调试第一帧
        if i == 0:
            fh, fw = frame.shape[:2]
            checker = np.zeros((fh, fw, 3), dtype=np.uint8)
            cs = 20
            for yy in range(0, fh, cs):
                for xx in range(0, fw, cs):
                    c = [200, 200, 200] if (yy // cs + xx // cs) % 2 == 0 else [150, 150, 150]
                    checker[yy:yy + cs, xx:xx + cs] = c
            a = (frame_rgba[:, :, 3].astype(float) / 255.0)
            a3 = np.stack([a, a, a], axis=2)
            comp = (frame.astype(float) * a3 + checker.astype(float) * (1 - a3)).astype(np.uint8)
            if mirror:
                comp = comp[:, ::-1, :]
            cv2.imwrite(os.path.join(OUTPUT_DIR, f'debug_{name}_matting.png'), comp)
            print(f'  调试图: debug_{name}_matting.png')

        # 裁剪
        cropped = frame_rgba[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W]

        # 缩放
        h, w = cropped.shape[:2]
        scale = TARGET_HEIGHT / h
        new_w = int(w * scale)
        resized = cv2.resize(cropped, (new_w, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)

        if new_w < TARGET_WIDTH:
            canvas = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 4), dtype=np.uint8)
            x_offset = (TARGET_WIDTH - new_w) // 2
            canvas[:, x_offset:x_offset + new_w] = resized
            resized = canvas
        elif new_w > TARGET_WIDTH:
            x_offset = (new_w - TARGET_WIDTH) // 2
            resized = resized[:, x_offset:x_offset + TARGET_WIDTH]

        # resize 抗锯齿插值可能在猫体边缘再次产生半透明蓝色，及时清理
        safe_clean_blue_edges(resized)

        frames.append(resized)
        if (i + 1) % 50 == 0:
            print(f'  已处理 {i+1}/{frame_count} 帧')

    cap.release()
    print(f'  共处理 {len(frames)} 帧')

    rows = (len(frames) + SPRITE_COLS - 1) // SPRITE_COLS
    sprite_width = SPRITE_COLS * TARGET_WIDTH
    sprite_height = rows * TARGET_HEIGHT
    sprite = np.zeros((sprite_height, sprite_width, 4), dtype=np.uint8)
    for i, frame in enumerate(frames):
        col = i % SPRITE_COLS
        row = i // SPRITE_COLS
        sprite[row * TARGET_HEIGHT:(row + 1) * TARGET_HEIGHT,
               col * TARGET_WIDTH:(col + 1) * TARGET_WIDTH] = frame

    sprite_path = os.path.join(OUTPUT_DIR, f'{name}_sprite.webp')
    sprite_pil = Image.fromarray(cv2.cvtColor(sprite, cv2.COLOR_BGRA2RGBA))
    sprite_pil.save(sprite_path, 'WEBP', quality=90, method=6)

    # Sprite 级后处理：webp 压缩可能再次在边缘引入半透明蓝色混合
    # 重新读回，清理后再次保存（保护与前景相邻的边缘）
    sprite_final = cv2.imread(sprite_path, cv2.IMREAD_UNCHANGED)
    safe_clean_blue_edges(sprite_final)
    Image.fromarray(cv2.cvtColor(sprite_final, cv2.COLOR_BGRA2RGBA)).save(
        sprite_path, 'WEBP', quality=90, method=6
    )

    file_size = os.path.getsize(sprite_path)
    print(f'  Sprite: {sprite_width}x{sprite_height}, {SPRITE_COLS}x{rows}')
    print(f'  大小: {file_size/1024:.1f} KB')
    return frame_count, rows


if __name__ == '__main__':
    right_frames, right_rows = process_video(mirror=False)
    left_frames, left_rows = process_video(mirror=True)
    print(f'\n全部完成!')
    print(f'  walk_right: {right_frames} 帧, 12x{right_rows}')
    print(f'  walk_left:  {left_frames} 帧, 12x{left_rows}')
