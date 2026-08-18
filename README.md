# 素材替换指南

本文档介绍如何替换桌面宠物"安琪"的角色动画素材，并重新打包发布。

## 目录结构

```
aiCatCode/
├── video/              ← 放置原始视频文件 (.mp4，任意背景)
├── frames_new/         ← 转头关键帧 PNG (37张透明图，需预先去背景)
├── output/             ← 生成的雪碧图 + HTML/JS 运行时
│   ├── base_poop.jpg   ← 💩emoji 源图
│   ├── sprite.webp     ← 转头主循环雪碧图
│   ├── sprite_poop.webp← 💩模式转头雪碧图
│   ├── yawn_sprite.webp← 哈欠动画
│   ├── ...             ← 其他动画雪碧图
│   ├── index.html      ← 主窗口
│   ├── fx.html         ← 特效窗口
│   └── sticker.html    ← 贴纸窗口
├── build_sprites.py    ← 统一素材构建脚本
├── matting_utils.py    ← 抠图工具库
├── main.js             ← Electron 主进程
├── package.json        ← 项目配置
└── ASSETS.md           ← 本文件
```

## 前置条件

### 安装 Python 依赖

```bash
pip install rembg opencv-python Pillow numpy
```

> rembg 首次运行会自动下载 ONNX 模型 (\~170MB)，需联网。

### 安装 Node.js 依赖

```bash
npm install
```

## 快速替换素材

### 1. 替换视频文件

将新视频文件放入 `video/` 目录，文件名必须与下表一致：

| 动画 | 文件名    | 目标帧尺寸   | 说明     |
| -- | ------ | ------- | ------ |
| 哈欠 | 哈欠.mp4 | 322×400 | 固定尺寸   |
| 舔毛 | 舔毛.mp4 | 322×400 | 固定尺寸   |
| 猫条 | 猫条.mp4 | 322×400 | 固定尺寸   |
| 咀嚼 | 咀嚼.mp4 | 322×400 | 固定尺寸   |
| 走路 | 走路.mp4 | 等比×400  | 按原视频比例 |
| 铲屎 | 铲屎.mp4 | 322×400 | 固定尺寸   |
| 准星 | 准星.mp4 | 等比×260  | 按原视频比例 |
| 开枪 | 开枪.mp4 | 等比×480  | 按原视频比例 |
| 爆炸 | 爆炸.mp4 | 等比×260  | 按原视频比例 |

> 所有视频均使用 rembg AI 自动抠除背景，无需绿幕/蓝幕，支持任意背景。

### 2. 替换转头关键帧（可选）

如果角色转头动画也要替换，将 37 张透明背景 PNG 放入 `frames_new/` 目录：

- 文件名格式：`frame_0000.png` \~ `frame_0036.png`
- 每帧覆盖 360 度中的 10 度（37帧=360度+1帧闭环）
- 必须是透明背景 PNG（rembg 不处理这些帧，直接拼贴）

### 3. 替换💩emoji源图（可选）

如果💩图标也要替换，将新图片放入 `output/base_poop.jpg`：

- 任意背景的💩图片（rembg 会自动抠除背景生成 poop\_icon）
- 💩模式转头（sprite\_poop）中的 emoji 叠加需要检测眼睛位置，建议💩图有两只明显的眼睛

### 4. 重新生成雪碧图

```bash
# 生成全部雪碧图
npm run build:sprites

# 或只生成指定动画
python build_sprites.py yawn groom feed

# 查看可用动画列表
npm run build:sprites:only
```

脚本运行完成后会在 `output/` 目录生成所有 `.webp` 雪碧图文件，
并在终端打印 JS 配置代码（`XXX_ANIMATION` 常量），需将其粘贴到 `output/index.html` 中对应的动画配置区。

### 5. 更新 index.html 动画配置

build\_sprites.py 运行结束后会输出类似如下的配置：

```javascript
const YAWN_ANIMATION = {
    name: 'yawn',
    sprite: 'yawn_sprite.webp',
    frames: 47,
    cols: 12,
    rows: 4,
    frameWidth: 322,
    frameHeight: 400,
};
```

将这些配置粘贴到 `output/index.html` 中替换对应的旧配置。
重点关注 `frames`、`cols`、`rows`、`frameWidth`、`frameHeight` 是否变化。

### 6. 打包发布

```bash
# 仅生成安装包
npm run build

# 先重新生成雪碧图再打包（一步到位）
npm run build:all
```

生成的安装包位于 `dist13/` 目录，文件名格式：`Anqi-Setup-{version}.exe`。

## 抠图方式说明

### rembg AI 抠图（统一方式）

- **原理**：使用 ONNX 深度学习模型自动识别前景物体并抠除背景
- **优势**：无需绿幕/蓝幕，支持任意背景的视频和图片
- **劣势**：边缘可能有轻微残留，处理速度比色度键控慢
- **适用**：全部动画（哈欠、舔毛、猫条、咀嚼、走路、铲屎、准星、开枪、爆炸、💩图标）

### 透明PNG拼贴（转头主循环）

- **原理**：直接使用已去背景的透明 PNG 序列拼贴雪碧图
- **优势**：最高质量，无抠图误差
- **适用**：转头主循环（sprite.webp），需预先用其他工具去背景

### 💩emoji 叠加（sprite\_poop）

- **原理**：在转头雪碧图每帧右下角叠加方向感知的💩emoji
- **特殊**：emoji 内部的白底抠除 + 眼睛检测 + 瞳孔绘制逻辑保留独立实现
- **适用**：💩模式转头（sprite\_poop.webp）

## 自定义参数

所有动画的参数集中在 `build_sprites.py` 顶部的 `SPRITES` 字典中。

### 调整目标帧尺寸

```python
"yawn": {
    ...
    "frame_width": 322,   # ← 修改宽度
    "frame_height": 400,  # ← 修改高度
    ...
}
```

如果新视频宽高比不同，可以只指定高度（宽度按等比缩放）：

```python
"walk_right": {
    ...
    "frame_height": 400,  # 只指定高度
    # 不写 frame_width
    ...
}
```

### 调整采样帧率

修改 `build_sprites.py` 顶部的 `FPS_OUT`：

```python
FPS_OUT = 24  # ← 修改为目标帧率
```

## 常见问题

### Q: 替换视频后角色比例不对？

A: 检查 `SPRITES` 中对应动画的 `frame_width` 和 `frame_height`。
如果新视频宽高比不同，去掉 `frame_width`（只保留 `frame_height`）实现等比缩放，
然后更新 index.html 中的 `frameWidth/frameHeight` 值。

### Q: rembg 抠图有背景残留？

A: rembg 对纯色背景效果最好。如果背景复杂，尽量使用纯色背景拍摄。
也可以在抠图后手动检查 `output/` 下的 sprite 文件。

### Q: rembg 处理太慢？

A: rembg 首次运行需下载模型 (\~170MB)。后续会缓存到 `~/.rembg/`。
可只处理单个动画：`python build_sprites.py chew`

### Q: 走路动画方向不对？

A: walk\_left 是从 walk\_right 镜像翻转生成的。确保走路视频中角色向右走。

### Q: 转头帧不够流畅？

A: 可在 `frames_new/` 中提供更多关键帧（如 73 张覆盖 360 度）。
但帧数变化后需同步更新 `SPRITES.sprite.cols` 和 `sprite_poop.num_frames`。
