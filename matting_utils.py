"""
matting_utils.py — 桌面宠物素材抠图通用工具库

提供视频帧采样、rembg AI 抠图、透明裁剪、雪碧图拼贴、帧缩放等通用函数。
所有抠除背景的操作统一使用 rembg AI 模型，无需绿幕/蓝幕。

依赖: pip install rembg opencv-python Pillow numpy
"""

import os, math
import numpy as np
from PIL import Image
import cv2

try:
    from rembg import remove as _rembg_remove, new_session as _rembg_new_session
    _HAS_REMBG = True
except ImportError:
    _HAS_REMBG = False
    _rembg_new_session = None


# ========== 视频帧采样 ==========

def sample_frames_uniform(video_path, target_fps=24):
    """按目标帧率均匀采样视频帧，返回 PIL RGBA 帧列表"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if src_fps <= 0:
        src_fps = 30.0
    out_duration = total / src_fps
    target_total = max(1, int(round(out_duration * target_fps)))
    idxs = [min(total - 1, int(round((i / target_total) * total))) for i in range(target_total)]
    # 去重保持顺序
    seen = set()
    idxs_u = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            idxs_u.append(i)
    idxs = idxs_u or [0]

    frames = {}
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, bgr = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        frames[idx] = Image.fromarray(rgb).convert("RGBA")
    cap.release()
    return [frames[i] for i in idxs if i in frames]


# ========== AI 抠图 (rembg) ==========

# 模型选择：u2net=176MB(推荐,通用) / u2netp=4.7MB(轻量) / bria-rmbg=1GB(高质量但下载慢)
REMBG_MODEL = os.environ.get("REMBG_MODEL", "u2net")

# session 缓存（避免每帧重新加载模型）
_SESSIONS = {}


def _get_session():
    """获取/创建 rembg session（缓存模型避免重复加载）"""
    model = REMBG_MODEL
    if model not in _SESSIONS:
        print(f"  [rembg] 加载模型: {model} ...")
        _SESSIONS[model] = _rembg_new_session(model)
    return _SESSIONS[model]


def remove_bg_rembg(img_rgba):
    """使用 rembg AI 模型抠除背景（支持任意背景的视频/图片）"""
    if not _HAS_REMBG:
        raise RuntimeError("rembg 未安装，请运行: pip install rembg")
    session = _get_session()
    out = _rembg_remove(img_rgba, session=session)
    if not isinstance(out, Image.Image):
        out = Image.open(out).convert("RGBA")
    return out.convert("RGBA")


# ========== 透明区域裁剪 ==========

def crop_nontransparent(frames, margin=4):
    """
    按所有帧的 alpha bounding box 统一裁剪
    返回裁剪后的帧列表
    """
    min_x = min_y = float("inf")
    max_x = max_y = 0
    for im in frames:
        a = im.split()[3]
        bb = a.getbbox()
        if bb:
            min_x = min(min_x, bb[0])
            min_y = min(min_y, bb[1])
            max_x = max(max_x, bb[2])
            max_y = max(max_y, bb[3])
    if max_x <= min_x or max_y <= min_y:
        return frames
    W, H = frames[0].size
    min_x = max(0, min_x - margin)
    min_y = max(0, min_y - margin)
    max_x = min(W, max_x + margin)
    max_y = min(H, max_y + margin)
    return [im.crop((min_x, min_y, max_x, max_y)) for im in frames]


# ========== 雪碧图拼贴 ==========

def build_sprite(frames, out_path, cols=None, quality=90):
    """
    将帧列表拼贴为雪碧图 webp

    参数:
        frames: PIL RGBA 帧列表
        out_path: 输出路径
        cols: 列数（None=自动按平方根）
        quality: webp 质量

    返回: dict {frames, frame_w, frame_h, cols, rows}
    """
    n = len(frames)
    if n == 0:
        raise ValueError("帧列表为空")
    fw, fh = frames[0].size
    if cols is None:
        cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    sprite = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
    for i, im in enumerate(frames):
        r, c = divmod(i, cols)
        sprite.paste(im, (c * fw, r * fh))
    sprite.save(out_path, "WEBP", quality=quality, method=6)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  -> {os.path.basename(out_path)}  "
          f"{fw}x{fh} x {cols}x{rows} ({n}f) {size_kb:.0f}KB")
    return {"frames": n, "frame_w": fw, "frame_h": fh, "cols": cols, "rows": rows}


# ========== 帧缩放辅助 ==========

def resize_frames(frames, target_w, target_h):
    """将帧列表缩放到指定尺寸"""
    return [f.resize((target_w, target_h), Image.LANCZOS) for f in frames]


def resize_frames_by_height(frames, target_h):
    """按高度等比缩放帧列表，返回 (resized_frames, new_width)"""
    w0, h0 = frames[0].size
    scale = target_h / h0
    new_w = max(1, int(w0 * scale))
    resized = [f.resize((new_w, target_h), Image.LANCZOS) for f in frames]
    return resized, new_w


def resize_frames_by_height_with_crop(frames, target_w, target_h):
    """
    按高度等比缩放，宽度不足则居中填充 canvas，宽度超出则裁剪中间
    """
    resized, new_w = resize_frames_by_height(frames, target_h)
    if new_w < target_w:
        canvas_frames = []
        x_offset = (target_w - new_w) // 2
        for f in resized:
            canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
            canvas.paste(f, (x_offset, 0))
            canvas_frames.append(canvas)
        return canvas_frames
    elif new_w > target_w:
        x_offset = (new_w - target_w) // 2
        return [f.crop((x_offset, 0, x_offset + target_w, target_h)) for f in resized]
    return resized


def mirror_sprite(sprite_path, out_path, frame_w, frame_h, cols, rows):
    """
    读取雪碧图，逐帧左右镜像翻转，生成新雪碧图
    用于 walk_right -> walk_left 生成
    """
    sprite = Image.open(sprite_path).convert("RGBA")
    n = cols * rows
    mirrored_frames = []
    for i in range(n):
        r, c = divmod(i, cols)
        frame = sprite.crop((c * frame_w, r * frame_h,
                            (c + 1) * frame_w, (r + 1) * frame_h))
        mirrored = frame.transpose(Image.FLIP_LEFT_RIGHT)
        mirrored_frames.append(mirrored)
    return build_sprite(mirrored_frames, out_path, cols=cols)
