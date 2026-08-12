"""
生成咀嚼动画 sprite（删除文件时播放）
蓝幕抠图 + 水印去除 + 裁剪 + 缩放 + 生成 sprite
复用 walk 脚本的成熟抠图方案（safe_clean_blue_edges 保护脚部边缘）
背景 HSV≈(101,177,174)，猫体 HSV≈(108,21,153)，S 值差异大，S>=80 可区分
"""
import cv2
import numpy as np
from PIL import Image
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.path.join(SCRIPT_DIR, 'video', '咀嚼.mp4')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output')
TARGET_WIDTH = 322
TARGET_HEIGHT = 400
SPRITE_COLS = 12

# 裁剪区域（和其他 sprite 保持一致，适配 720x960 视频）
CROP_X = 19
CROP_Y = 90
CROP_W = 701
CROP_H = 870

# 蓝幕抠图参数（背景 HSV≈(101,177,174)，猫体 S=21 远低于背景 S=177）
BLUE_HSV_LOWER = np.array([95, 80, 50])
BLUE_HSV_UPPER = np.array([135, 255, 255])
BLUE_HSV_LOOSE_LOWER = np.array([90, 40, 30])
BLUE_HSV_LOOSE_UPPER = np.array([140, 255, 255])


def is_blue_hsv(frame_bgr):
    """HSV 空间判定蓝色背景"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER) > 0


def detect_watermark_mask(video_path):
    """检测静态水印（咀嚼视频可能没有，返回None或小掩码）"""
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

    wm_small = cv2.dilate(wm_small, np.ones((3, 3), np.uint8), iterations=2)
    return wm_small if np.any(wm_small > 0) else None


def safe_clean_blue_edges(image_bgra, alpha_threshold=255, neighbor_radius=2):
    """
    清理蓝色边缘像素。咀嚼视频背景 S=177 vs 猫体 S=21，差异极大，
    可以用 S>=80 阈值安全地清除所有蓝色残留，不需要保护带。
    S>=80 远高于猫体 S=21，不会误伤猫体像素。
    """
    alpha = image_bgra[:, :, 3]
    bgr = image_bgra[:, :, :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    # 蓝色判定：H 在 90-140 范围 + S>=80（猫体 S=21 远低于此阈值，安全）
    blue_mask = (hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 140) & (hsv[:, :, 1] >= 80)

    # 半透明蓝色像素：直接设为透明
    semi_blue = blue_mask & (alpha > 0) & (alpha < 255)
    if np.any(semi_blue):
        image_bgra[semi_blue, 3] = 0

    # 不透明蓝色像素（alpha>=255 但颜色仍偏蓝）：颜色去污染，B=G
    opaque_blue = blue_mask & (alpha == 255)
    if np.any(opaque_blue):
        image_bgra[opaque_blue, 0] = image_bgra[opaque_blue, 1]


def mat_blue_screen(frame, wm_mask=None):
    """蓝幕抠图 + 去水印，返回 BGRA 图像"""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER)

    # 边缘清理：宽松阈值 + 四角 flood fill
    loose_blue = cv2.inRange(hsv, BLUE_HSV_LOOSE_LOWER, BLUE_HSV_LOOSE_UPPER)
    strict_dilated = cv2.dilate(mask, np.ones((35, 35), np.uint8), iterations=1)
    loose_connected = (loose_blue > 0) & (strict_dilated > 0)
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = loose_blue.copy()
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(flood_fill, flood_mask, seed, 128, 0, 0, 4)
    edge_bg = (flood_fill == 128) & loose_connected
    mask[edge_bg] = 255

    # 形态学操作：仅 CLOSE 填充小空洞，不做 OPEN/dilate
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    fg_mask = 255 - mask
    fg_before_fill = fg_mask.copy()

    # 只做小面积洞填充（<500像素），避免把猫体中间的大面积蓝色背景误填为前景
    # 先从四角flood fill找到外部连通背景，剩下的内部封闭区域才作为"内部洞候选"
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    fill_inv = mask.copy()  # fill_inv: 255=原背景(严格蓝色)
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(fill_inv, flood_mask, seed, 128, 0, 0, 4)
    # fill_inv=128: 从四角可连通到的外部背景
    # fill_inv==0 且 fg_before_fill==0: 内部洞候选（原是背景色，但和外部不连通）
    potential_holes = (fill_inv == 0) & (fg_before_fill == 0)
    ph_mask = potential_holes.astype(np.uint8) * 255
    if np.any(ph_mask > 0):
        num_ph, ph_labels, ph_stats, _ = cv2.connectedComponentsWithStats(ph_mask, connectivity=8)
        for i in range(1, num_ph):
            area = ph_stats[i, cv2.CC_STAT_AREA]
            # 只填充小面积洞（毛发/胡须间隙、小瑕疵）
            # 大面积蓝色区域直接作为背景保留，不填充
            if area < 500:
                fg_mask[ph_labels == i] = 255

    # 只保留最大连通分量
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    if num_labels > 1:
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        fg_mask = (labels == largest_label).astype(np.uint8) * 255

    # 轻微模糊抗锯齿
    fg_mask = cv2.GaussianBlur(fg_mask, (3, 3), 0)

    # 去水印
    if wm_mask is not None:
        fg_mask[wm_mask > 0] = 0

    result = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    result[:, :, 3] = fg_mask

    safe_clean_blue_edges(result)

    # 在清理蓝色边缘后，用形态学 CLOSE 填补猫体内部残留的小洞（毛发间隙、胸前镂空等）
    # 用大核 CLOSE 可以可靠地桥接细小缝隙，不会向外扩张轮廓
    alpha_after = result[:, :, 3]
    closed = cv2.morphologyEx(alpha_after, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    # 只在原 alpha>0 的区域附近填充（避免在纯背景区域生成噪声）
    fill_zone = cv2.dilate((alpha_after > 0).astype(np.uint8), np.ones((7, 7), np.uint8), iterations=1)
    result[:, :, 3] = np.where(fill_zone > 0, closed, alpha_after)

    # 颜色去污染：不透明前景边缘的蓝色残留（BGR中B通道偏高）
    # 把蓝色通道拉低到和绿色通道一致，消除蓝色 fringe
    b, g, r = result[:, :, 0], result[:, :, 1], result[:, :, 2]
    blue_tint = (result[:, :, 3] > 100) & (b > g + 15)  # B比G高15以上=蓝色残留
    if np.any(blue_tint):
        result[blue_tint, 0] = result[blue_tint, 1]  # B=G，去掉蓝色偏移

    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f'处理咀嚼视频: {VIDEO_PATH}')

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
            cv2.imwrite(os.path.join(OUTPUT_DIR, 'debug_chew_matting.png'), comp)
            print(f'  调试图: debug_chew_matting.png')

        cropped = frame_rgba[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W]

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

    sprite_path = os.path.join(OUTPUT_DIR, 'chew_sprite.webp')
    # cv2 保存 WEBP（绕过 PIL 在大图上 encoding error 1 的限制）
    sprite_bgra = sprite  # 已经是BGRA
    cv2.imwrite(sprite_path, sprite_bgra, [cv2.IMWRITE_WEBP_QUALITY, 90])

    # sprite 级后处理：再清一次蓝色边缘并重新保存
    sprite_final = cv2.imread(sprite_path, cv2.IMREAD_UNCHANGED)
    safe_clean_blue_edges(sprite_final)
    cv2.imwrite(sprite_path, sprite_final, [cv2.IMWRITE_WEBP_QUALITY, 90])

    file_size = os.path.getsize(sprite_path)
    print(f'  Sprite: {sprite_width}x{sprite_height}, {SPRITE_COLS}x{rows}')
    print(f'  大小: {file_size/1024:.1f} KB')
    print(f'  帧数: {len(frames)}, 列: {SPRITE_COLS}, 行: {rows}')


if __name__ == '__main__':
    main()
