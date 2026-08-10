"""
给 37 帧转头雪碧图的每帧右下角添加💩emoji
方案：使用 seedream 生成的基础💩图，抠除白底 → 逐帧修改眼睛方向 → 合成
emoji 眼睛方向与猫转头方向一致，保持角色原大小不变
"""
from PIL import Image, ImageDraw
import math
import os
import numpy as np
import cv2

# ========== 配置 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_SPRITE = os.path.join(SCRIPT_DIR, 'output', 'sprite.webp')
BASE_POOP_JPG = os.path.join(SCRIPT_DIR, 'output', 'base_poop.jpg')
OUTPUT_SPRITE = os.path.join(SCRIPT_DIR, 'output', 'sprite_poop.webp')

FRAME_W = 322
FRAME_H = 400
COLS = 12
ROWS = 4
NUM_FRAMES = 37

ANGLEKEYS = {
    0: 0, 14: 45, 18: 90, 22: 135, 24: 180, 28: 225, 31: 270, 33: 315,
}

EMOJI_SIZE = 124
EMOJI_MARGIN_X = 6
EMOJI_MARGIN_Y = 6


# ========== 帧号 -> 角度 ==========
def frame_to_angle(fi):
    items = sorted(ANGLEKEYS.items())
    for i in range(len(items)):
        f0, a0 = items[i]
        f1, a1 = items[(i + 1) % len(items)]
        if i == len(items) - 1:
            a1 = a1 + 360
            if fi >= f0 or fi <= f1:
                if fi >= f0:
                    t = (fi - f0) / ((NUM_FRAMES - f0) + f1)
                else:
                    t = ((NUM_FRAMES - f0) + fi) / ((NUM_FRAMES - f0) + f1)
                return (a0 + t * (a1 - a0)) % 360
        elif f0 <= fi <= f1:
            t = (fi - f0) / (f1 - f0)
            return a0 + t * (a1 - a0)
    return 0.0


def angle_to_eyeshift(angle_deg, shift_rad):
    """角度→眼珠偏移 (dx, dy)。0°=上 顺时针"""
    m = math.radians(90 - angle_deg)
    return (round(shift_rad * math.cos(m)),
            round(-shift_rad * math.sin(m)))


# ========== 处理 seedream 基础图 ==========
def prepare_base_emoji(jpg_path, size):
    """
    读取 seedream jpg -> 抠除白底 -> 裁到内容 -> 缩放到 size×size。
    眼位置/瞳孔检测在原图分辨率做，再按比例映射到最终尺寸。
    返回 (RGBA 身体图(去瞳孔), 左眼中心(x,y), 右眼中心(x,y), 瞳孔半径px, 眼珠最大偏移px)
    """
    img = Image.open(jpg_path).convert('RGBA')
    arr = np.array(img)  # 原图大尺寸 (1920x1920)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    H, W = arr.shape[:2]

    # ========== 白底抠除：只把"与四角连通的背景白"设为透明，保留便便主体上的白眼珠 ==========
    # 1. 生成宽松白掩膜（纯白 + 近白）
    loose_white = (r > 230) & (g > 230) & (b > 230)
    # 2. 从四角做 flood fill，找到"背景白"（与边界连通的宽松白区域）
    lw_u8 = (loose_white.astype(np.uint8)) * 255
    fm = np.zeros((H + 2, W + 2), np.uint8)
    for seed in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        # cv2.floodFill 会在 fm 边界外自动处理 seed，要求 mask 尺寸为 (H+2,W+2)
        cv2.floodFill(lw_u8, fm, seed, 128, 0, 0, 4)
    bg_white = (lw_u8 == 128)  # 与四角连通的 = 背景白

    # 3. alpha：背景白按亮度渐变透明；主体内部的白（如白眼珠）保持 alpha=255 不透明
    alpha = 255 * np.ones(arr.shape[:2], np.uint8)
    # 背景纯白 (R>248) 完全透明
    pure_bg = bg_white & (r > 248) & (g > 248) & (b > 248)
    alpha[pure_bg] = 0
    # 背景近白 (230<R≤248) 按偏离纯白程度渐变透明
    near_bg = bg_white & ~pure_bg
    dist_bg = np.maximum.reduce([255 - r, 255 - g, 255 - b]).astype(np.uint8)
    alpha[near_bg] = np.clip(dist_bg[near_bg] * 8, 0, 255)
    arr[..., 3] = alpha

    # ========== 在原图分辨率上做眼睛/瞳孔检测 ==========
    on_emoji = arr[..., 3] > 120
    near_white_h = (arr[..., 0] > 200) & (arr[..., 1] > 200) & (arr[..., 2] > 200)
    is_white_eye = on_emoji & near_white_h
    num, labels, stats, cents = cv2.connectedComponentsWithStats(
        is_white_eye.astype(np.uint8) * 255, connectivity=8)
    eye_areas = []
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] > 100:  # 原图尺寸：要求至少 100 像素（排除噪点）
            eye_areas.append((stats[i, cv2.CC_STAT_AREA], cents[i], i))
    eye_areas.sort(reverse=True)
    if len(eye_areas) < 2:
        raise RuntimeError('原图未检测到两只眼睛，只找到 %d 个白块' % len(eye_areas))

    eye_cents = [eye_areas[0][1], eye_areas[1][1]]
    eye_cents.sort(key=lambda c: c[0])
    left_eye = (float(eye_cents[0][0]), float(eye_cents[0][1]))
    right_eye = (float(eye_cents[1][0]), float(eye_cents[1][1]))

    # 瞳孔（深色块）检测（原图）
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

    # 采样眼白颜色（原图）
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

    # 眼球半径（原图）：从 eye_areas stats 获取
    def assign_stats():
        e1, e2 = None, None
        for ar, ct, lbl in eye_areas[:2]:
            if abs(ct[0] - left_eye[0]) < abs(ct[0] - right_eye[0]):
                e1 = stats[lbl] if e1 is None else e1
            else:
                e2 = stats[lbl] if e2 is None else e2
        # 如果上面都分给同一只了，剩余那只强制赋另一个
        _, ctA, lblA = eye_areas[0]
        _, ctB, lblB = eye_areas[1]
        if e1 is None:
            e1 = stats[lblB] if abs(ctB[0] - left_eye[0]) < abs(ctA[0] - left_eye[0]) else stats[lblA]
        if e2 is None:
            e2 = stats[lblB] if abs(ctB[0] - right_eye[0]) < abs(ctA[0] - right_eye[0]) else stats[lblA]
        return e1, e2
    st_L, st_R = assign_stats()

    def eye_r(st):
        return max(1.0, (st[cv2.CC_STAT_WIDTH] + st[cv2.CC_STAT_HEIGHT]) / 4.0)
    eye_R_h = min(eye_r(st_L), eye_r(st_R))

    # ========== 做身体去瞳孔版本（原图上操作避免缩放瑕疵）==========
    body_h = Image.fromarray(arr.copy())
    dr = ImageDraw.Draw(body_h)
    R_cover = int(math.ceil(pupil_R_h * 1.35))
    dr.ellipse([lp_cx - R_cover, lp_cy - R_cover, lp_cx + R_cover, lp_cy + R_cover], fill=wh_L)
    dr.ellipse([rp_cx - R_cover, rp_cy - R_cover, rp_cx + R_cover, rp_cy + R_cover], fill=wh_R)

    # ========== 裁剪 + 缩放 body_h 到 size×size，同时映射坐标 ==========
    bbox = body_h.getbbox()
    if bbox:
        bx0, by0, bx1, by1 = bbox
    else:
        bx0, by0, bx1, by1 = 0, 0, W, H
    bw, bh = bx1 - bx0, by1 - by0
    scale = min(size / bw, size / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    offx = (size - nw) // 2
    offy = (size - nh) // 2
    body_cropped = body_h.crop(bbox)
    body_scaled = body_cropped.resize((nw, nh), Image.LANCZOS)
    body_final = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    body_final.paste(body_scaled, (offx, offy), body_scaled)

    # 坐标映射：原图坐标 (x,y) → 去瞳孔缩放后 body_final 的坐标
    def map_coord(hx, hy):
        x2 = (hx - bx0) * scale + offx
        y2 = (hy - by0) * scale + offy
        return x2, y2

    left_final = map_coord(*left_eye)
    right_final = map_coord(*right_eye)
    pupil_r_final = pupil_R_h * scale
    # 安全计算基础最大偏移：眼珠可在白眼区域内移动而不接触边缘
    base_shift = max(0.0, (eye_R_h * scale) - pupil_r_final * 0.8)
    # 为了让方向变化更清晰可见，乘以放大系数（同时保证不超过白眼物理边界）
    max_shift_final = min(base_shift * 1.6, base_shift + pupil_r_final * 0.5)
    # 保证至少能偏移 1.5 像素（52x52 图上方向变化才看得见）
    max_shift_final = max(max_shift_final, min(1.8, base_shift * 2.0))

    return body_final, left_final, right_final, pupil_r_final, max_shift_final


# ========== 按方向在 body_only 上绘制眼睛 ==========
def make_emoji(base_body, eye_L, eye_R, pupil_R, max_shift, angle_deg):
    """基于 body_only 画定向眼珠，返回一个新的 emoji"""
    img = base_body.copy()
    dr = ImageDraw.Draw(img)
    dx, dy = angle_to_eyeshift(angle_deg, max_shift)

    def draw_one_pupil(cx, cy):
        px = cx + dx
        py = cy + dy
        # 黑眼珠
        r = pupil_R
        dr.ellipse([px - r, py - r, px + r, py + r],
                   fill=(15, 15, 15, 255))
        # 小高光（始终在眼珠的左上 1/4 处）
        hl = pupil_R * 0.35
        hl_cx = px - pupil_R * 0.42
        hl_cy = py - pupil_R * 0.45
        dr.ellipse([hl_cx - hl, hl_cy - hl, hl_cx + hl, hl_cy + hl],
                   fill=(255, 255, 255, 255))

    draw_one_pupil(*eye_L)
    draw_one_pupil(*eye_R)
    return img


# ========== 主流程 ==========
def main():
    print('[1/4] 处理 seedream 基础💩图 (抠白+裁边+测眼)...')
    body, eye_L, eye_R, pupil_r, max_shift = prepare_base_emoji(BASE_POOP_JPG, EMOJI_SIZE)
    print(f'      size={body.size}, 左眼={eye_L[0]:.1f},{eye_L[1]:.1f} 右眼={eye_R[0]:.1f},{eye_R[1]:.1f}')
    print(f'      瞳孔半径={pupil_r:.1f}px, 眼珠最大偏移={max_shift:.1f}px')
    # 保存身体基础图（调试）
    body.save(os.path.join(SCRIPT_DIR, 'output', 'debug_body_only.png'))

    # 展示 8 个方向样本
    print('\n[2/4] 生成 8 方向 emoji 样本（调试）...')
    sample_sheet = Image.new('RGBA', (EMOJI_SIZE * 8 + 40, EMOJI_SIZE + 30), (250, 250, 250, 255))
    sd = ImageDraw.Draw(sample_sheet)
    dir_names = ['上0°', '右上45°', '右90°', '右下135°', '下180°', '左下225°', '左270°', '左上315°']
    for i, ang in enumerate([0, 45, 90, 135, 180, 225, 270, 315]):
        em = make_emoji(body, eye_L, eye_R, pupil_r, max_shift, ang)
        x = i * EMOJI_SIZE + 5
        sample_sheet.paste(em, (x, 0), em)
        sd.text((x + 2, EMOJI_SIZE + 4), dir_names[i], fill=(30, 30, 30))
    sample_sheet.save(os.path.join(SCRIPT_DIR, 'output', 'debug_poop_8directions.png'))
    print('      已保存: output/debug_poop_8directions.png')

    print('\n[3/4] 合成 37 帧雪碧图...')
    sprite = Image.open(INPUT_SPRITE).convert('RGBA')
    out = sprite.copy()  # 角色原图像不变

    for fi in range(NUM_FRAMES):
        col = fi % COLS
        row = fi // COLS
        fx = col * FRAME_W
        fy = row * FRAME_H
        angle = frame_to_angle(fi)
        # 生成定向💩
        emoji = make_emoji(body, eye_L, eye_R, pupil_r, max_shift, angle)
        # 粘贴到每帧右下角（透明合成）
        px = fx + (FRAME_W - EMOJI_SIZE - EMOJI_MARGIN_X)
        py = fy + (FRAME_H - EMOJI_SIZE - EMOJI_MARGIN_Y)
        out.paste(emoji, (px, py), emoji)

    print(f'      保存: {OUTPUT_SPRITE}')
    out.save(OUTPUT_SPRITE, 'WEBP', quality=90, method=6)
    sz = os.path.getsize(OUTPUT_SPRITE)
    print(f'      尺寸 {out.size}, 大小 {sz / 1024:.1f} KB')

    print('\n[4/4] 生成调试图（37 帧预览 + 角度标注）...')
    cell_w, cell_h = 170, 220
    cols_p = 6
    rows_p = (NUM_FRAMES + cols_p - 1) // cols_p
    pad = Image.new('RGBA',
                    (cols_p * cell_w, rows_p * cell_h + 50),
                    (240, 240, 240, 255))
    dpad = ImageDraw.Draw(pad)
    for fi in range(NUM_FRAMES):
        sc = fi % COLS
        sr = fi // COLS
        frm = out.crop((sc * FRAME_W, sr * FRAME_H, sc * FRAME_W + FRAME_W, sr * FRAME_H + FRAME_H))
        th = cell_h - 34
        tw = int(FRAME_W * (th / FRAME_H))
        frm_s = frm.resize((tw, th), Image.LANCZOS)
        # 棋盘格透明底
        ck = Image.new('RGB', (cell_w, cell_h - 34), (200, 200, 200))
        ck_d = ImageDraw.Draw(ck)
        cs = 8
        for yy in range(0, cell_h - 34, cs):
            for xx in range(0, cell_w, cs):
                if (yy // cs + xx // cs) % 2 == 0:
                    ck_d.rectangle([xx, yy, xx + cs, yy + cs], fill=(170, 170, 170))
        ox = (cell_w - tw) // 2
        ck.paste(frm_s, (ox, 0), frm_s)
        c = fi % cols_p
        r = fi // cols_p
        pad.paste(ck, (c * cell_w, r * cell_h))
        angle = frame_to_angle(fi)
        dpad.text((c * cell_w + 5, r * cell_h + cell_h - 32),
                  f'帧{fi}  {angle:.0f}°', fill=(30, 30, 30))
    debug_path = os.path.join(SCRIPT_DIR, 'output', 'sprite_poop_debug.png')
    pad.save(debug_path)
    print(f'      已保存: {debug_path}')

    print('\n✅ 全部完成！')


if __name__ == '__main__':
    main()
