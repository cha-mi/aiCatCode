from PIL import Image
import os
import json
import math

frames_dir = r"C:\project\doubao\aiCat\frames_new"
output_dir = r"C:\project\doubao\aiCat\output"
sprite_path = os.path.join(output_dir, "sprite.webp")
framefront_path = os.path.join(output_dir, "framefront.webp")
anglekeys_path = os.path.join(output_dir, "anglekeys.json")

os.makedirs(output_dir, exist_ok=True)

# 读取所有帧
print("读取图片...")
files = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
print(f"共 {len(files)} 张图片")

frames = []
for i, f in enumerate(files):
    img = Image.open(os.path.join(frames_dir, f))
    # 转换为 RGBA
    img = img.convert("RGBA")
    frames.append(img)
    if i % 10 == 0:
        print(f"  已读取 {i+1}/{len(files)}")

print(f"原始尺寸: {frames[0].size}")

# 计算统一裁剪区域
print("\n计算统一裁剪区域...")
min_x = float('inf')
min_y = float('inf')
max_x = 0
max_y = 0

for i, img in enumerate(frames):
    # 获取 alpha 通道的非透明区域
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        min_x = min(min_x, bbox[0])
        min_y = min(min_y, bbox[1])
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])
    if i % 10 == 0:
        print(f"  处理第 {i+1}/{len(frames)} 帧")

# 加边距
margin = 20
min_x = max(0, min_x - margin)
min_y = max(0, min_y - margin)
max_x = min(frames[0].width, max_x + margin)
max_y = min(frames[0].height, max_y + margin)

crop_w = max_x - min_x
crop_h = max_y - min_y
print(f"裁剪区域: x={min_x}, y={min_y}, w={crop_w}, h={crop_h}")

# 裁剪所有帧
print("\n裁剪帧...")
cropped = []
for i, img in enumerate(frames):
    c = img.crop((min_x, min_y, max_x, max_y))
    cropped.append(c)

# 缩放
target_height = 400
scale = target_height / crop_h
target_width = int(crop_w * scale)
print(f"\n缩放到 {target_width}x{target_height}...")

resized = []
for i, img in enumerate(cropped):
    r = img.resize((target_width, target_height), Image.LANCZOS)
    resized.append(r)
    if i % 10 == 0:
        print(f"  缩放第 {i+1}/{len(cropped)} 帧")

frame_w = target_width
frame_h = target_height
print(f"帧尺寸: {frame_w}x{frame_h}")

# 生成 sprite
print("\n生成 sprite.webp...")
num_frames = len(resized)
cols = 6  # 36 帧，6列6行
rows = math.ceil(num_frames / cols)
sprite_width = cols * frame_w
sprite_height = rows * frame_h
print(f"Sprite 网格: {cols}x{rows}, 尺寸: {sprite_width}x{sprite_height}")

sprite = Image.new("RGBA", (sprite_width, sprite_height), (0, 0, 0, 0))
for i, img in enumerate(resized):
    row = i // cols
    col = i % cols
    x = col * frame_w
    y = row * frame_h
    sprite.paste(img, (x, y))

sprite.save(sprite_path, "WEBP", quality=90, method=6)
sprite_size = os.path.getsize(sprite_path)
print(f"Sprite 已保存: {sprite_path}, 大小: {sprite_size/1024:.1f} KB")

# 生成 framefront（第 2 帧，对应 frame_0010，正面抬头）
front_idx = 2
front_img = resized[front_idx]
front_img.save(framefront_path, "WEBP", quality=90)
print(f"Framefront 已保存: {framefront_path} (第 {front_idx} 帧)")

# 新的 ANGLEKEYS 校准表
# 36 帧，索引 0-35，对应原始帧号 0, 5, 10, ..., 175
ANGLEKEYS = {
    0: 2,     # 上（frame_0010）
    45: 9,    # 右上（frame_0045）
    90: 15,   # 右（frame_0075）
    135: 21,  # 右下（frame_0105）
    180: 26,  # 下（frame_0130）
    225: 31,  # 左下（frame_0155）
    270: 35,  # 左（frame_0175）
    315: 2,   # 左上（用正面近似）
}

# 保存 anglekeys.json
anglekeys_data = {
    "angle_keys": {str(k): v for k, v in ANGLEKEYS.items()},
    "total_frames": num_frames,
    "frame_width": frame_w,
    "frame_height": frame_h,
    "sprite_cols": cols,
    "sprite_rows": rows,
    "description": "0=up, 90=right, 180=down, 270=left, clockwise"
}

with open(anglekeys_path, 'w', encoding='utf-8') as f:
    json.dump(anglekeys_data, f, indent=2, ensure_ascii=False)
print(f"Anglekeys 已保存: {anglekeys_path}")

print("\n全部完成!")
