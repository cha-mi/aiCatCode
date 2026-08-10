from PIL import Image
import os
import json
import math
import numpy as np

frames_dir = r"C:\project\doubao\aiCatCode\frames_new"
output_dir = r"C:\project\doubao\aiCatCode\output"
sprite_path = os.path.join(output_dir, "sprite.webp")
framefront_path = os.path.join(output_dir, "framefront.webp")
anglekeys_path = os.path.join(output_dir, "anglekeys.json")

os.makedirs(output_dir, exist_ok=True)

# 补帧参数：每两个关键帧之间生成多少张中间帧
# 设为 0 = 不补帧，使用纯关键帧，避免 alpha 混合产生的虚影/重影
INTERP_FRAMES = 0

# ========== 读取关键帧 ==========
print("读取关键帧...")
files = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
print(f"共 {len(files)} 张关键帧")

key_frames = []
for i, f in enumerate(files):
    img = Image.open(os.path.join(frames_dir, f))
    img = img.convert("RGBA")
    key_frames.append(img)
    if i % 10 == 0:
        print(f"  已读取 {i+1}/{len(files)}")

print(f"原始尺寸: {key_frames[0].size}")

# ========== 计算统一裁剪区域 ==========
print("\n计算统一裁剪区域...")
min_x = float('inf')
min_y = float('inf')
max_x = 0
max_y = 0

for i, img in enumerate(key_frames):
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        min_x = min(min_x, bbox[0])
        min_y = min(min_y, bbox[1])
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])
    if i % 10 == 0:
        print(f"  处理第 {i+1}/{len(key_frames)} 帧")

margin = 15
min_x = max(0, min_x - margin)
min_y = max(0, min_y - margin)
max_x = min(key_frames[0].width, max_x + margin)
max_y = min(key_frames[0].height, max_y + margin)

crop_w = max_x - min_x
crop_h = max_y - min_y
print(f"裁剪区域: x={min_x}, y={min_y}, w={crop_w}, h={crop_h}")

# ========== 裁剪关键帧 ==========
print("\n裁剪关键帧...")
cropped_keys = []
for img in key_frames:
    c = img.crop((min_x, min_y, max_x, max_y))
    cropped_keys.append(c)

# ========== 缩放关键帧 ==========
target_height = 400
scale = target_height / crop_h
target_width = int(crop_w * scale)
print(f"\n缩放到 {target_width}x{target_height}...")

resized_keys = []
for i, img in enumerate(cropped_keys):
    r = img.resize((target_width, target_height), Image.LANCZOS)
    resized_keys.append(r)
    if i % 10 == 0:
        print(f"  缩放第 {i+1}/{len(cropped_keys)} 帧")

frame_w = target_width
frame_h = target_height
print(f"帧尺寸: {frame_w}x{frame_h}")

# ========== 补帧（帧混合） ==========
print(f"\n补帧：每两帧之间生成 {INTERP_FRAMES} 张中间帧...")

all_frames = []
num_keys = len(resized_keys)

# 由于是 360 度循环，最后一帧和第一帧之间也需要过渡
# 但最后一帧（frame_0180）和第一帧（frame_0000）都是正面，几乎一样
# 所以我们只需要处理 num_keys - 1 个间隔，最后一帧单独处理

for i in range(num_keys - 1):
    frame_a = resized_keys[i]
    frame_b = resized_keys[i + 1]
    
    # 添加关键帧 A
    all_frames.append(frame_a)
    
    # 添加中间帧
    for j in range(1, INTERP_FRAMES + 1):
        alpha = j / (INTERP_FRAMES + 1)
        # 混合 RGB 和 alpha
        arr_a = np.array(frame_a).astype(float)
        arr_b = np.array(frame_b).astype(float)
        mixed = arr_a * (1 - alpha) + arr_b * alpha
        mixed_img = Image.fromarray(mixed.astype(np.uint8), 'RGBA')
        all_frames.append(mixed_img)

# 添加最后一个关键帧
all_frames.append(resized_keys[-1])

num_total = len(all_frames)
print(f"总帧数: {num_total}")

# ========== 生成 sprite ==========
print("\n生成 sprite.webp...")
cols = 12  # 12列
rows = math.ceil(num_total / cols)
sprite_width = cols * frame_w
sprite_height = rows * frame_h
print(f"Sprite 网格: {cols}x{rows}, 尺寸: {sprite_width}x{sprite_height}")

sprite = Image.new("RGBA", (sprite_width, sprite_height), (0, 0, 0, 0))
for i, img in enumerate(all_frames):
    row = i // cols
    col = i % cols
    x = col * frame_w
    y = row * frame_h
    sprite.paste(img, (x, y))

sprite.save(sprite_path, "WEBP", quality=90, method=6)
sprite_size = os.path.getsize(sprite_path)
print(f"Sprite 已保存: {sprite_path}, 大小: {sprite_size/1024:.1f} KB")

# ========== 生成 framefront ==========
# 正面帧：第 0 帧（frame_0000）
front_idx = 0
front_img = all_frames[front_idx]
front_img.save(framefront_path, "WEBP", quality=90)
print(f"Framefront 已保存: {framefront_path} (第 {front_idx} 帧)")

# ========== 计算 ANGLEKEYS ==========
# 37 个关键帧覆盖 360 度，从 frame_0000（正面朝上）开始，顺时针转一圈
# 关键帧索引 i 对应的角度 = i / (num_keys - 1) * 360
# 总帧数 num_total，每帧对应的角度 = i / (num_total - 1) * 360

print("\n计算角度校准表...")

# 关键角度对应的帧号
# 0°: 第 0 帧（正面朝上）
# 45°: 第 num_keys * 45/360 = num_keys/8 帧
# 90°: 第 num_keys/4 帧
# 135°: 第 num_keys*3/8 帧
# 180°: 第 num_keys/2 帧
# 225°: 第 num_keys*5/8 帧
# 270°: 第 num_keys*3/4 帧
# 315°: 第 num_keys*7/8 帧

# 先计算关键帧对应的角度索引
def key_idx_to_angle(key_idx):
    """关键帧索引 -> 角度"""
    return key_idx / (num_keys - 1) * 360

def angle_to_total_idx(angle):
    """角度 -> 总帧索引"""
    # 规范化角度到 0-360
    angle = angle % 360
    # 总帧数 num_total 覆盖 360 度
    idx = angle / 360 * (num_total - 1)
    return int(round(idx))

# 计算 8 个关键角度对应的总帧索引
ANGLEKEYS = {}
for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
    frame_idx = angle_to_total_idx(angle)
    ANGLEKEYS[angle] = frame_idx
    print(f"  {angle}° -> 第 {frame_idx} 帧")

# 保存 anglekeys.json
anglekeys_data = {
    "angle_keys": {str(k): v for k, v in ANGLEKEYS.items()},
    "total_frames": num_total,
    "frame_width": frame_w,
    "frame_height": frame_h,
    "sprite_cols": cols,
    "sprite_rows": rows,
    "description": "0=up, 90=right, 180=down, 270=left, clockwise, 360 degree full rotation"
}

with open(anglekeys_path, 'w', encoding='utf-8') as f:
    json.dump(anglekeys_data, f, indent=2, ensure_ascii=False)
print(f"Anglekeys 已保存: {anglekeys_path}")

print("\n全部完成!")
print(f"总结: {num_keys} 个关键帧 -> {num_total} 帧, 360度全覆盖")
