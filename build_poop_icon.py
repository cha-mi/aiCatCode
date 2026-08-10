"""
从 base_poop.jpg 生成独立的透明背景 poop_icon.webp（用于堆积显示）
抠图策略：flood fill 从四角开始，只去除与边界连通的白色背景
"""
from PIL import Image
import os
import numpy as np
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_POOP_JPG = os.path.join(SCRIPT_DIR, 'output', 'base_poop.jpg')
OUTPUT_WEBP = os.path.join(SCRIPT_DIR, 'output', 'poop_icon.webp')
OUTPUT_SIZE = 80  # 输出 80x80 像素（放大2倍）


def main():
    print(f'[1/3] 读取 {BASE_POOP_JPG} ...')
    img = Image.open(BASE_POOP_JPG).convert('RGBA')
    arr = np.array(img)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    H, W = arr.shape[:2]
    print(f'      原尺寸: {W}x{H}')

    print('[2/3] 抠除白底（flood fill 四角连通背景）...')
    # 1. 生成宽松白掩膜（纯白 + 近白）
    loose_white = (r > 230) & (g > 230) & (b > 230)
    lw_u8 = (loose_white.astype(np.uint8)) * 255
    fm = np.zeros((H + 2, W + 2), np.uint8)
    for seed in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        cv2.floodFill(lw_u8, fm, seed, 128, 0, 0, 4)
    bg_white = (lw_u8 == 128)

    # 2. alpha：背景白按亮度渐变透明
    alpha = 255 * np.ones(arr.shape[:2], np.uint8)
    pure_bg = bg_white & (r > 248) & (g > 248) & (b > 248)
    alpha[pure_bg] = 0
    near_bg = bg_white & ~pure_bg
    dist_bg = np.maximum.reduce([255 - r, 255 - g, 255 - b]).astype(np.uint8)
    alpha[near_bg] = np.clip(dist_bg[near_bg] * 8, 0, 255)
    arr[..., 3] = alpha

    # 3. 裁剪前景内容
    matted = Image.fromarray(arr)
    bbox = matted.getbbox()
    if bbox:
        bx0, by0, bx1, by1 = bbox
        print(f'      前景 bbox: ({bx0},{by0})-({bx1},{by1})  尺寸:{bx1-bx0}x{by1-by0}')
    else:
        bx0, by0, bx1, by1 = 0, 0, W, H
    bw, bh = bx1 - bx0, by1 - by0

    # 4. 缩放到 OUTPUT_SIZE×OUTPUT_SIZE（保持比例居中）
    scale = min(OUTPUT_SIZE / bw, OUTPUT_SIZE / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    offx = (OUTPUT_SIZE - nw) // 2
    offy = (OUTPUT_SIZE - nh) // 2
    cropped = matted.crop(bbox)
    scaled = cropped.resize((nw, nh), Image.LANCZOS)
    final = Image.new('RGBA', (OUTPUT_SIZE, OUTPUT_SIZE), (0, 0, 0, 0))
    final.paste(scaled, (offx, offy), scaled)

    print(f'[3/3] 保存到 {OUTPUT_WEBP} ...')
    final.save(OUTPUT_WEBP, 'WEBP', quality=95, method=6, lossless=False)
    sz = os.path.getsize(OUTPUT_WEBP)
    print(f'      最终尺寸: {final.size}, 文件大小: {sz} bytes')

    # 统计透明像素
    final_arr = np.array(final)
    transparent = (final_arr[..., 3] == 0).sum()
    opaque = (final_arr[..., 3] > 128).sum()
    total = final_arr.shape[0] * final_arr.shape[1]
    print(f'      透明像素: {transparent}/{total} ({transparent/total*100:.1f}%)')
    print(f'      不透明像素: {opaque}/{total} ({opaque/total*100:.1f}%)')
    print('✅ 完成!')


if __name__ == '__main__':
    main()
