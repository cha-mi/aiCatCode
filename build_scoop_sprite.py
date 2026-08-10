"""
生成铲屎动画 sprite
蓝幕抠图 + 水印去除 + 裁剪 + 缩放 + 生成 sprite
"""
import cv2
import numpy as np
from PIL import Image
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_PATH = os.path.join(SCRIPT_DIR, 'video', '铲屎.mp4')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output')
TARGET_WIDTH = 322
TARGET_HEIGHT = 400
SPRITE_COLS = 12

# 裁剪区域（和其他 sprite 保持一致，适配 720x960 视频）
CROP_X = 19
CROP_Y = 90
CROP_W = 701
CROP_H = 870

# 蓝幕抠图参数
# 背景色 BGR≈(230,86,0)，HSV≈(120,255,230)
# 严格阈值：S>=200, V>=180，排除蓝色反光的猫腿（S=80-160, V=100-170）
BLUE_HSV_LOWER = np.array([95, 200, 180])
BLUE_HSV_UPPER = np.array([135, 255, 255])
# 宽松阈值用于边缘清理（捕获半透明蓝色边缘，通过flood fill限定连通区域）
# S>=120 排除猫腿蓝色反光（S=48-100），V>=80 排除暗色非蓝像素
BLUE_HSV_LOOSE_LOWER = np.array([90, 120, 80])
BLUE_HSV_LOOSE_UPPER = np.array([140, 255, 255])


def is_blue_hsv(frame_bgr):
    """HSV 空间判定蓝色背景，返回二值掩码（True=蓝色）"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER) > 0


def detect_watermark_mask(video_path):
    """
    检测静态水印：跨帧始终非蓝色且低变化的像素，排除大面积猫体。
    返回二值掩码（255=水印，0=非水印）。
    关键：添加空间过滤（只搜右下角）+ 背景连通性过滤（只保留与蓝色背景相邻的区域），
    避免猫腿静态暗色毛发被误判为水印。
    """
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

    # 跨帧标准差（低 = 静态）
    stack = np.stack([f.astype(np.float32) for f in frames_bgr], 0)
    std_max = stack.std(0).max(2)

    # 始终非蓝色
    blue_masks = [is_blue_hsv(f) for f in frames_bgr]
    always_blue = np.stack(blue_masks, 0).all(0)

    # 静态非蓝色 = 水印候选
    static_nonblue = (std_max < 5) & ~always_blue
    wm = static_nonblue.astype(np.uint8) * 255
    wm = cv2.dilate(wm, np.ones((3, 3), np.uint8), iterations=1)

    # 空间过滤：只在右下角搜索水印（与 build_anim_sprites.py 一致）
    # 排除猫腿（左下角）等静态猫体部位
    wm_full = np.zeros((h, w), np.uint8)
    search_x = int(w * 0.5)
    search_y = int(h * 0.7)
    wm_full[search_y:, search_x:] = wm[search_y:, search_x:]

    # 连通块分析：只保留小面积块（水印），排除大块（猫体）
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(wm_full, connectivity=8)
    wm_small = np.zeros((h, w), np.uint8)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if 30 < area < 5000:
            wm_small[labels == i] = 255

    # 背景连通性过滤：只保留与蓝色背景（膨胀5px后）相邻的水印块
    # 猫体内部的静态暗色像素（如腿部暗毛）周围都是猫体，不接触蓝色背景，故被排除
    blue_all = np.zeros((h, w), bool)
    for f in frames_bgr:
        blue_all |= is_blue_hsv(f)
    bg_dil = cv2.dilate(blue_all.astype(np.uint8) * 255,
                        np.ones((5, 5), np.uint8), iterations=1) > 0
    nw2, l2, s2, _ = cv2.connectedComponentsWithStats(
        (wm_small > 0).astype(np.uint8) * 255, connectivity=4)
    keep = np.zeros((h, w), bool)
    for i in range(1, nw2):
        blk = (l2 == i)
        if np.any(blk & bg_dil):
            keep |= blk
    wm_small = (keep.astype(np.uint8)) * 255

    # 膨胀覆盖边缘
    wm_small = cv2.dilate(wm_small, np.ones((3, 3), np.uint8), iterations=2)
    return wm_small if np.any(wm_small > 0) else None


def mat_blue_screen(frame, wm_mask=None):
    """蓝幕抠图 + 去水印，返回 BGRA 图像"""
    h, w = frame.shape[:2]

    # HSV 空间检测蓝色背景（严格阈值）
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BLUE_HSV_LOWER, BLUE_HSV_UPPER)

    # 边缘清理：用宽松阈值 + 四角 flood fill 清理连通的浅蓝/半透明蓝色边缘
    # 但限制为只清理与严格蓝色背景相邻的区域，避免误抓猫腿蓝色反光
    loose_blue = cv2.inRange(hsv, BLUE_HSV_LOOSE_LOWER, BLUE_HSV_LOOSE_UPPER)
    # 只保留与严格蓝色掩码连通的宽松蓝色区域（膨胀严格掩码后取交集）
    strict_dilated = cv2.dilate(mask, np.ones((7, 7), np.uint8), iterations=2)
    loose_connected = (loose_blue > 0) & (strict_dilated > 0)
    # flood fill 从四角标记外部连通的背景
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = loose_blue.copy()
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(flood_fill, flood_mask, seed, 128, 0, 0, 4)
    edge_bg = (flood_fill == 128) & loose_connected
    mask[edge_bg] = 255

    # 形态学操作清理噪点
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    # 前景掩码
    fg_mask = 255 - mask

    # 保存hole filling之前的前景掩码，用于区分"原有前景"和"被填充的洞"
    # 猫腿蓝色反光在形态学处理后就是前景，不会被hole filling影响
    fg_before_fill = fg_mask.copy()

    # 填充内部空洞
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = fg_mask.copy()
    cv2.floodFill(flood_fill, flood_mask, (0, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (0, h - 1), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, h - 1), 128)
    fg_mask[flood_fill == 0] = 255

    # 恢复被误填为前景的蓝色背景（手/铲子分隔的右侧蓝色区域）
    # 关键修复：用连通分量分析区分"大面积蓝色背景洞"和"猫腿蓝色反光"
    # 大面积填充区域(>500px)且蓝色占比高 = 实际背景透过洞显示 → 移除
    # 小面积填充区域 = 猫腿反光/猫体特征 → 保留
    strict_blue = cv2.inRange(hsv, np.array([95, 200, 180]), np.array([135, 255, 255])) > 0
    filled_pixels = (fg_mask > 0) & (fg_before_fill == 0)
    filled_mask = filled_pixels.astype(np.uint8) * 255
    num_filled, filled_labels, filled_stats, _ = cv2.connectedComponentsWithStats(filled_mask, connectivity=8)
    for i in range(1, num_filled):
        area = filled_stats[i, cv2.CC_STAT_AREA]
        if area > 500:  # 大面积填充区域才检查是否为蓝色背景
            region = (filled_labels == i)
            region_blue = region & (strict_blue | edge_bg)
            blue_ratio = np.sum(region_blue) / area
            if blue_ratio > 0.5:  # 蓝色占比>50% = 实际背景洞
                fg_mask[region_blue] = 0

    # 只保留最大连通分量
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    if num_labels > 1:
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        fg_mask = (labels == largest_label).astype(np.uint8) * 255

    # 腐蚀前景边缘，去掉残留的蓝色边缘像素
    fg_mask = cv2.erode(fg_mask, np.ones((3, 3), np.uint8), iterations=1)

    # 羽化边缘
    fg_mask = cv2.GaussianBlur(fg_mask, (7, 7), 0)

    # 去水印：强制将水印区域设为透明
    if wm_mask is not None:
        fg_mask[wm_mask > 0] = 0

    result = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    result[:, :, 3] = fg_mask
    return result


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f'处理铲屎视频: {VIDEO_PATH}')

    # 预检测水印
    wm_mask = detect_watermark_mask(VIDEO_PATH)
    if wm_mask is not None and np.sum(wm_mask) > 0:
        print(f'  检测到水印，掩码像素数: {np.sum(wm_mask > 0)}')
    else:
        print(f'  未检测到明显水印')

    cap = cv2.VideoCapture(VIDEO_PATH)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f'  {frame_count} 帧, {fps}fps')

    frames = []
    for i in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            break

        # 蓝幕抠图 + 去水印
        frame_rgba = mat_blue_screen(frame, wm_mask)

        # 调试：保存第一帧抠图对比
        if i == 0:
            fh, fw = frame.shape[:2]
            checker = np.zeros((fh, fw, 3), dtype=np.uint8)
            cs = 20
            for yy in range(0, fh, cs):
                for xx in range(0, fw, cs):
                    c = [200, 200, 200] if (yy//cs + xx//cs) % 2 == 0 else [150, 150, 150]
                    checker[yy:yy+cs, xx:xx+cs] = c
            a = (frame_rgba[:, :, 3].astype(float) / 255.0)
            a3 = np.stack([a, a, a], axis=2)
            comp = (frame.astype(float) * a3 + checker.astype(float) * (1 - a3)).astype(np.uint8)
            cv2.imwrite(os.path.join(OUTPUT_DIR, 'debug_scoop_matting.png'), comp)
            print(f'  调试图已保存: debug_scoop_matting.png')

        # 裁剪
        cropped = frame_rgba[CROP_Y:CROP_Y+CROP_H, CROP_X:CROP_X+CROP_W]

        # 缩放到目标尺寸
        h, w = cropped.shape[:2]
        scale = TARGET_HEIGHT / h
        new_w = int(w * scale)
        resized = cv2.resize(cropped, (new_w, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)

        # 宽度适配
        if new_w < TARGET_WIDTH:
            canvas = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 4), dtype=np.uint8)
            x_offset = (TARGET_WIDTH - new_w) // 2
            canvas[:, x_offset:x_offset+new_w] = resized
            resized = canvas
        elif new_w > TARGET_WIDTH:
            x_offset = (new_w - TARGET_WIDTH) // 2
            resized = resized[:, x_offset:x_offset+TARGET_WIDTH]

        frames.append(resized)

        if (i + 1) % 20 == 0:
            print(f'  已处理 {i+1}/{frame_count} 帧')

    cap.release()
    print(f'  共处理 {len(frames)} 帧')

    # 生成 sprite
    rows = (len(frames) + SPRITE_COLS - 1) // SPRITE_COLS
    sprite_width = SPRITE_COLS * TARGET_WIDTH
    sprite_height = rows * TARGET_HEIGHT

    sprite = np.zeros((sprite_height, sprite_width, 4), dtype=np.uint8)
    for i, frame in enumerate(frames):
        col = i % SPRITE_COLS
        row = i // SPRITE_COLS
        sprite[row*TARGET_HEIGHT:(row+1)*TARGET_HEIGHT,
               col*TARGET_WIDTH:(col+1)*TARGET_WIDTH] = frame

    sprite_path = os.path.join(OUTPUT_DIR, 'scoop_sprite.webp')
    sprite_pil = Image.fromarray(cv2.cvtColor(sprite, cv2.COLOR_BGRA2RGBA))
    sprite_pil.save(sprite_path, 'WEBP', quality=90, method=6)

    file_size = os.path.getsize(sprite_path)
    print(f'  Sprite 已保存: {sprite_path}')
    print(f'  尺寸: {sprite_width}x{sprite_height}, {SPRITE_COLS}x{rows}')
    print(f'  大小: {file_size/1024:.1f} KB')
    print(f'  帧数: {len(frames)}, 列: {SPRITE_COLS}, 行: {rows}')


if __name__ == '__main__':
    main()
