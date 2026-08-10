"""
生成动画 sprite（哈欠、舔毛）
绿幕抠图 + 裁剪 + 缩放 + 生成 sprite
"""
import cv2
import numpy as np
from PIL import Image
import os

# 配置（路径基于脚本所在目录，便于跨环境运行）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_VIDEOS = {
    'yawn': os.path.join(SCRIPT_DIR, 'yawn.mp4'),
    'groom': os.path.join(SCRIPT_DIR, 'groom.mp4'),
    'feed': os.path.join(SCRIPT_DIR, 'video', '猫条.mp4'),
}
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output')
TARGET_WIDTH = 322
TARGET_HEIGHT = 400
SPRITE_COLS = 12

# 裁剪区域（和转头 sprite 保持一致）
CROP_X = 19
CROP_Y = 90
CROP_W = 701
CROP_H = 870

# 绿幕抠图参数（HSV）——按视频区分
# yawn 背景为纯绿（H≈73, S≈108），阈值宽松即可
# groom 背景为浅绿渐变（H≈44-53, S≈52-65），猫的黄绿毛H≈41会误抠，
# 故 groom 提高 H 下限到 43，排除猫毛同时保留背景
GREEN_PARAMS = {
    'yawn':  (np.array([35, 40, 40]),  np.array([90, 255, 255])),
    'groom': (np.array([43, 40, 100]), np.array([90, 255, 255])),
    'feed':  (np.array([35, 40, 40]),  np.array([90, 255, 255])),
}

# 形态学操作参数——按视频区分
# groom 猫毛颜色（H≈44）接近绿幕背景，需用更小的核避免蚕食猫体边缘；
# yawn 用更小的 dilate(3) 和 close(5)，配合更强 erode(3) 减少腿部边缘损失（72 vs 原 278）
MORPH_PARAMS = {
    'yawn':  {'close': 5, 'open': 3, 'dilate': 3, 'erode': 3},
    'groom': {'close': 3, 'open': 3, 'dilate': 2, 'erode': 0},
    'feed':  {'close': 7, 'open': 3, 'dilate': 5, 'erode': 3},
}

# 水印检测参数——按视频区分
# 暗度阈值、搜索区域起点比例、最大连通块面积、是否要求与严格绿色背景4连通
# yawn: 水印为暗色(V<80)，遍布整个画面（半透明覆盖）。
#   不用 fixed_rect 限定区域，用全图搜索。
#   移除策略：只移除"暗色 + 紧邻绿色背景"的水印（绿色背景上的水印残留）。
#   猫体上的水印不紧邻绿色背景，自然被保护，避免镂空。
WM_PARAMS = {
    'yawn':  {'dark_thr': 80,
              'sx': 0.0, 'sy': 0.0, 'max_area': 50000, 'bg_connect': False},
    'groom': {'dark_thr': 80, 'sx': 0.68, 'sy': 0.82, 'max_area': 50000, 'bg_connect': False},
    'feed':  {'dark_thr': 80, 'sx': 0.68, 'sy': 0.82, 'max_area': 50000, 'bg_connect': False},
}

# 边缘绿幕清理参数——按视频区分
# groom 背景为浅绿渐变，边缘有大量抗锯齿浅绿像素（H<43, S<40）无法被严格阈值捕获，
# 用宽松阈值 + 四角 flood fill 清理连通的渐变背景，同时保留被非绿色区域隔开的猫体
# yawn/feed 背景为纯绿，严格阈值即可，无需边缘清理
EDGE_CLEANUP = {
    'yawn':  None,
    'groom': (np.array([35, 25, 60]), np.array([90, 255, 255])),
    'feed':  None,
}

def detect_watermark_mask(video_path, name='yawn'):
    """
    检测静态水印。水印在所有帧中位置/颜色固定，且位于右下角小范围。
    判据：在采样帧中始终为暗色且始终为非绿色背景的像素，
    仅在右下角极小区域搜索，只保留小连通块，可选过滤必须连通绿色背景。
    返回二值掩码（255=水印，0=非水印）。
    name: yawn / groom / feed，用于选择 WM_PARAMS
    """
    params = WM_PARAMS.get(name, WM_PARAMS['yawn'])
    dark_thr = params['dark_thr']
    sx = params['sx']
    sy = params['sy']
    max_area = params['max_area']
    do_bg_connect = params['bg_connect']

    cap = cv2.VideoCapture(video_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idxs = np.linspace(0, max(n - 1, 0), min(20, max(n, 1))).astype(int)
    hsv_frames = []
    gray_frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, f = cap.read()
        if ret:
            hsv_frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2HSV))
            gray_frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.int32))
    cap.release()
    if not hsv_frames:
        return None

    h, w = gray_frames[0].shape

    # 始终非绿色（所有帧中都不是绿色背景）
    green_masks = [cv2.inRange(hsv, np.array([30, 30, 30]), np.array([90, 255, 255])) == 0
                   for hsv in hsv_frames]
    always_nongreen = np.stack(green_masks, 0).all(0)

    # 水印检测：两种模式
    # 1) light_thr 模式：水印为静态浅灰(V>light_thr, S<low_sat, std<5)
    #    加入静态检查(std<5)，避免猫腿动态浅灰部分被误判
    # 2) dark_thr 模式（默认）：水印为暗色(min(gray)<dark_thr)
    #    可选 static_std 参数：加入跨帧标准差检查，区分静态水印与动态猫腿
    #    groom/feed 背景渐变导致std偏大，不加静态检查；
    #    yawn 水印被猫体覆盖，"暗色+紧邻绿色"移除条件不生效，改用 static_std 区分
    light_thr = params.get('light_thr')
    if light_thr is not None:
        low_sat = params.get('low_sat', 80)
        gray_stack = np.stack(gray_frames, 0)
        static_mask = gray_stack.std(0) < 5
        # 跨帧最大V值：任一帧V>light_thr 即可能是水印
        max_v = np.stack([hsv[:,:,2] for hsv in hsv_frames], 0).max(0)
        # 跨帧最小S值：所有帧S都低才是灰色（排除彩色猫体）
        min_s = np.stack([hsv[:,:,1] for hsv in hsv_frames], 0).min(0)
        wm = (always_nongreen & static_mask & (max_v > light_thr) & (min_s < low_sat)).astype(np.uint8) * 255
    else:
        always_dark = np.stack(gray_frames, 0).min(0) < dark_thr
        wm_mask_cond = always_nongreen & always_dark
        # 静态检查：水印跨帧不变(std<static_std)，猫腿会移动(std>=static_std)
        static_std = params.get('static_std')
        if static_std is not None:
            gray_stack = np.stack(gray_frames, 0)
            static_mask = gray_stack.std(0) < static_std
            wm_mask_cond = wm_mask_cond & static_mask
        wm = wm_mask_cond.astype(np.uint8) * 255

    # 水印搜索区域：优先使用固定矩形 ROI（精确限定水印位置），
    # 否则回退到右下角比例区域
    wm_full = np.zeros((h, w), np.uint8)
    if 'fixed_rect' in params:
        x0, x1, y0, y1 = params['fixed_rect']
        wm_full[y0:y1, x0:x1] = wm[y0:y1, x0:x1]
    else:
        search_x = int(w * sx)
        search_y = int(h * sy)
        wm_full[search_y:, search_x:] = wm[search_y:, search_x:]

    # 只保留小连通块
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(wm_full, connectivity=8)
    wm_small = np.zeros((h, w), np.uint8)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < max_area:
            wm_small[labels == i] = 255

    # 背景连通性过滤：保留与严格绿色背景(4-邻域膨胀5px后)相连通的水印块
    # 猫体内部的暗色像素（如腿部暗毛）周围都是猫体，不接触绿色背景，故被排除
    if do_bg_connect:
        lower_g, upper_g = GREEN_PARAMS.get(name, GREEN_PARAMS['yawn'])
        # 所有采样帧中，任一帧出现过的严格绿色区域并集
        green_all = np.zeros((h, w), bool)
        for hsv in hsv_frames:
            green_all |= (cv2.inRange(hsv, lower_g, upper_g) > 0)
        bg_dil = cv2.dilate(green_all.astype(np.uint8) * 255,
                            np.ones((5, 5), np.uint8), iterations=1) > 0
        nw2, l2, s2, _ = cv2.connectedComponentsWithStats(
            (wm_small > 0).astype(np.uint8) * 255, connectivity=4)
        keep = np.zeros((h, w), bool)
        for i in range(1, nw2):
            blk = (l2 == i)
            if np.any(blk & bg_dil):
                keep |= blk
        wm_small = (keep.astype(np.uint8)) * 255

    # 膨胀 3x3，覆盖水印边缘抗锯齿像素
    wm_small = cv2.dilate(wm_small, np.ones((3, 3), np.uint8), iterations=1)
    return wm_small if np.any(wm_small > 0) else None

def mat_green_screen(frame, wm_mask=None, name='yawn'):
    """绿幕抠图 + 去水印，返回 BGRA 图像"""
    h, w = frame.shape[:2]

    # 转换为 HSV
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # 创建掩码（绿色 = 背景）——按视频选用对应阈值
    lower, upper = GREEN_PARAMS.get(name, GREEN_PARAMS['yawn'])
    mask = cv2.inRange(hsv, lower, upper)

    # 边缘绿幕清理：对渐变背景（如 groom），用宽松阈值 + 四角 flood fill
    # 清理连通的浅绿残留（抗锯齿边缘），同时保留被非绿色区域隔开的猫体内部
    ec = EDGE_CLEANUP.get(name)
    if ec is not None:
        loose_lower, loose_upper = ec
        loose_green = cv2.inRange(hsv, loose_lower, loose_upper)
        # 从四角 flood fill 连通的宽松绿色区域，标记为背景
        flood_mask = np.zeros((h + 2, w + 2), np.uint8)
        flood_fill = loose_green.copy()
        for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            cv2.floodFill(flood_fill, flood_mask, seed, 128, 0, 0, 4)
        edge_bg = (flood_fill == 128)
        mask[edge_bg] = 255

    # 形态学操作——按视频选用对应核大小
    mp = MORPH_PARAMS.get(name, MORPH_PARAMS['yawn'])
    kernel_close = np.ones((mp['close'], mp['close']), np.uint8)
    kernel_open = np.ones((mp['open'], mp['open']), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)

    # 膨胀一点，确保边缘绿色都去掉
    kernel_big = np.ones((mp['dilate'], mp['dilate']), np.uint8)
    mask = cv2.dilate(mask, kernel_big, iterations=1)

    # 前景掩码（255=前景，0=背景）
    fg_mask = 255 - mask

    # 填充内部空洞：修复猫眼等被误抠的区域
    # 从四角洪水填充背景，未被填充的黑色区域即为内部洞（如眼睛），恢复为前景
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flood_fill = fg_mask.copy()
    cv2.floodFill(flood_fill, flood_mask, (0, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, 0), 128)
    cv2.floodFill(flood_fill, flood_mask, (0, h - 1), 128)
    cv2.floodFill(flood_fill, flood_mask, (w - 1, h - 1), 128)
    fg_mask[flood_fill == 0] = 255

    # 只保留最大连通分量，去除游离噪点及残余水印碎片
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    if num_labels > 1:
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        fg_mask = (labels == largest_label).astype(np.uint8) * 255

    # 轻微腐蚀，去掉边缘毛刺（groom 不腐蚀，避免蚕食猫体边缘）
    if mp['erode'] > 0:
        kernel_erode = np.ones((mp['erode'], mp['erode']), np.uint8)
        fg_mask = cv2.erode(fg_mask, kernel_erode, iterations=1)

    # 羽化边缘，让过渡更自然
    fg_mask = cv2.GaussianBlur(fg_mask, (7, 7), 0)

    # 去除水印：在所有前景处理完成后，最后一步强制将水印区域设为透明
    # 必须放在填充空洞、最大连通块、腐蚀、羽化之后，否则水印会被当作"空洞"恢复
    # 关键策略：只移除"透明背景边缘"的水印残留，不碰猫体内部
    # 水印在绿色背景上 → 绿幕抠图已处理大部分，残留的暗色水印在此移除
    # 水印在猫体上 → 不移除（避免镂空），水印半透明效果在猫体上几乎不可见
    if wm_mask is not None:
        params = WM_PARAMS.get(name, {})
        if 'light_thr' in params:
            # light_thr 模式：逐帧检测浅灰水印
            light_thr = params['light_thr']
            low_sat = params.get('low_sat', 80)
            is_light_gray = (hsv[:,:,2] > light_thr) & (hsv[:,:,1] < low_sat)
            per_frame_wm = (wm_mask > 0) & is_light_gray
            fg_mask[per_frame_wm] = 0
        else:
            # dark_thr 模式：只移除"暗色 + 紧邻绿色背景"的水印残留
            # 水印在绿色背景上 → 暗色 + 紧邻绿色 → 移除
            # 水印在猫体上 → 暗色 + 不紧邻绿色 → 保留（避免镂空）
            dark_thr_val = params.get('dark_thr', 80)
            is_dark = hsv[:,:,2] < dark_thr_val
            lower_g, upper_g = GREEN_PARAMS.get(name, GREEN_PARAMS['yawn'])
            green_bg = cv2.inRange(hsv, lower_g, upper_g) > 0
            green_dil = cv2.dilate(green_bg.astype(np.uint8) * 255,
                                   np.ones((5, 5), np.uint8), iterations=1) > 0
            per_frame_wm = (wm_mask > 0) & is_dark & green_dil

            # 连通块面积过滤：只移除 area > 30 的块，避免误删猫体边缘小暗色块
            wm_mask_pf = per_frame_wm.astype(np.uint8) * 255
            nl, lbl, stats_pf, _ = cv2.connectedComponentsWithStats(wm_mask_pf, connectivity=8)
            for ci in range(1, nl):
                if stats_pf[ci, cv2.CC_STAT_AREA] > 30:
                    fg_mask[lbl == ci] = 0

    # 应用掩码：绿色/水印区域透明
    result = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    result[:, :, 3] = fg_mask

    return result

def process_video(video_path, name):
    """处理单个视频，生成 sprite"""
    print(f'\n处理 {name}...')

    # 预检测水印掩码（基于时间中位数，只检测一次，复用于所有帧）
    wm_mask = detect_watermark_mask(video_path, name=name)
    if wm_mask is not None and np.sum(wm_mask) > 0:
        print(f'  检测到水印，掩码像素数: {np.sum(wm_mask > 0)}')
    else:
        print(f'  未检测到明显水印')

    cap = cv2.VideoCapture(video_path)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f'  总帧数: {frame_count}')

    frames = []

    for i in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            break

        # 抠图（传入水印掩码和视频名以选用对应绿幕阈值）
        frame_rgba = mat_green_screen(frame, wm_mask, name)

        # 调试：保存第一帧的抠图棋盘格对比图
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
            dbg_path = os.path.join(OUTPUT_DIR, f'debug_{name}_matting.png')
            cv2.imwrite(dbg_path, comp)
            print(f'  调试图已保存: {dbg_path}')
        
        # 裁剪
        cropped = frame_rgba[CROP_Y:CROP_Y+CROP_H, CROP_X:CROP_X+CROP_W]
        
        # 缩放到目标尺寸
        # 保持比例，缩放到目标高度
        h, w = cropped.shape[:2]
        scale = TARGET_HEIGHT / h
        new_w = int(w * scale)
        resized = cv2.resize(cropped, (new_w, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)
        
        # 如果宽度不够，居中放置
        if new_w < TARGET_WIDTH:
            canvas = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 4), dtype=np.uint8)
            x_offset = (TARGET_WIDTH - new_w) // 2
            canvas[:, x_offset:x_offset+new_w] = resized
            resized = canvas
        elif new_w > TARGET_WIDTH:
            # 如果宽度超了，裁剪中间部分
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
    
    # 保存 sprite
    sprite_path = os.path.join(OUTPUT_DIR, f'{name}_sprite.webp')
    sprite_pil = Image.fromarray(cv2.cvtColor(sprite, cv2.COLOR_BGRA2RGBA))
    sprite_pil.save(sprite_path, 'WEBP', quality=90, method=6)
    
    file_size = os.path.getsize(sprite_path)
    print(f'  Sprite 已保存: {sprite_path}')
    print(f'  尺寸: {sprite_width}x{sprite_height}, {SPRITE_COLS}x{rows}')
    print(f'  大小: {file_size/1024:.1f} KB')
    
    return len(frames), rows

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    results = {}
    for name, path in INPUT_VIDEOS.items():
        frame_count, rows = process_video(path, name)
        results[name] = {
            'frames': frame_count,
            'cols': SPRITE_COLS,
            'rows': rows,
        }
    
    print('\n全部完成!')
    print('总结:')
    for name, info in results.items():
        print(f'  {name}: {info["frames"]} 帧, {info["cols"]}x{info["rows"]} 网格')

if __name__ == '__main__':
    main()
