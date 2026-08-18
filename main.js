const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { execFile } = require('child_process');
const { autoUpdater } = require('electron-updater');

// 显式设置更新源（解决 app-update.yml 缺失问题）
autoUpdater.setFeedURL({
    provider: 'github',
    owner: 'cha-mi',
    repo: 'aiCatCode'
});

// ========== 单实例锁 + 右键菜单启动参数 ==========
// 扫描 argv 找第一个看起来像文件路径的参数（跳过 exe 自身和所有 -- flag）
// 这样不依赖任何 flag 的固定位置，即使 Electron 自动注入 --allow-file-access-from-files 等参数也不会出错
function parseDeleteFileArg(argv) {
    for (let i = 1; i < argv.length; i++) {
        const arg = argv[i];
        if (!arg) continue;
        // 跳过所有 flag（--xxx / -x）
        if (arg.startsWith('--') || arg.startsWith('-')) continue;
        // 去引号
        let candidate = arg.replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1').trim();
        // 检查是否像 Windows 绝对路径（X:\...）
        if (/^[a-zA-Z]:[\\/]/.test(candidate)) {
            return candidate;
        }
    }
    return null;
}

const pendingDeleteFromArgv = parseDeleteFileArg(process.argv);

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
    // 已有实例运行，退出（second-instance 事件会在主实例中触发）
    app.quit();
} else {
    app.on('second-instance', (event, commandLine, workingDirectory) => {
        // 第二实例启动（右键菜单触发），解析文件路径并通知主窗口
        console.log('[second-instance] commandLine=', JSON.stringify(commandLine));
        const filePath = parseDeleteFileArg(commandLine);
        console.log('[second-instance] parsed filePath=', filePath, 'exists=', filePath ? fs.existsSync(filePath) : 'N/A');

        if (filePath) {
            if (mainWindow && !mainWindow.isDestroyed()) {
                if (mainWindow.isMinimized()) mainWindow.restore();
                mainWindow.show();
                mainWindow.focus();
                mainWindow.webContents.send('context-menu-delete-file', filePath);
            }
        } else {
            // 普通启动，聚焦窗口
            if (mainWindow) {
                if (mainWindow.isMinimized()) mainWindow.restore();
                mainWindow.show();
                mainWindow.focus();
            }
        }
    });
}

let mainWindow;
let stickerWindow = null;
let stickerOriginX = 0;  // 贴纸窗口在虚拟桌面中的起点 X
let stickerOriginY = 0;  // 贴纸窗口在虚拟桌面中的起点 Y
let fxWindow = null;
let fxOriginX = 0;  // fx 窗口虚拟桌面起点 X
let fxOriginY = 0;  // fx 窗口虚拟桌面起点 Y
let tray = null;
let isAlwaysOnTop = true;
let mouseTrackInterval = null;

function createWindow() {
    const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;

    const winWidth = 360;
    const winHeight = 460;

    mainWindow = new BrowserWindow({
        width: winWidth,
        height: winHeight,
        x: screenWidth - winWidth - 100,
        y: screenHeight - winHeight - 100,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        skipTaskbar: true,  // 不显示在任务栏
        hasShadow: false,
        backgroundColor: '#00000000',
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        }
    });

    mainWindow.setAlwaysOnTop(true, 'screen-saver');
    mainWindow.setVisibleOnAllWorkspaces(true);

    mainWindow.loadFile(path.join(__dirname, 'output', 'index.html'));

    // 关闭窗口时最小化到托盘，而不是退出
    mainWindow.on('close', (e) => {
        if (!app.isQuitting) {
            e.preventDefault();
            mainWindow.hide();
        }
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
        if (mouseTrackInterval) {
            clearInterval(mouseTrackInterval);
            mouseTrackInterval = null;
        }
    });

    // 启动全屏鼠标跟踪
    startMouseTracking();

    // 创建全屏透明贴纸窗口（用于💩拖尾贴纸）
    createStickerWindow();
    // 创建全屏透明特效窗口（用于准星/爆炸/开枪等覆盖层）
    createFxWindow();
}

function createStickerWindow() {
    // 覆盖所有显示器的虚拟桌面并集
    const displays = screen.getAllDisplays();
    let vMinX = Infinity, vMinY = Infinity, vMaxX = -Infinity, vMaxY = -Infinity;
    for (const d of displays) {
        vMinX = Math.min(vMinX, d.bounds.x);
        vMinY = Math.min(vMinY, d.bounds.y);
        vMaxX = Math.max(vMaxX, d.bounds.x + d.bounds.width);
        vMaxY = Math.max(vMaxY, d.bounds.y + d.bounds.height);
    }
    const winW = vMaxX - vMinX;
    const winH = vMaxY - vMinY;
    stickerOriginX = vMinX;
    stickerOriginY = vMinY;

    stickerWindow = new BrowserWindow({
        width: winW,
        height: winH,
        x: vMinX,
        y: vMinY,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        skipTaskbar: true,
        hasShadow: false,
        backgroundColor: '#00000000',
        webPreferences: {
            preload: path.join(__dirname, 'sticker_preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        }
    });

    stickerWindow.setAlwaysOnTop(true, 'screen-saver');
    stickerWindow.setVisibleOnAllWorkspaces(true);
    // 鼠标穿透：让贴纸窗口不阻挡任何点击
    stickerWindow.setIgnoreMouseEvents(true, { forward: false });

    stickerWindow.loadFile(path.join(__dirname, 'output', 'sticker.html'));

    stickerWindow.on('close', (e) => {
        if (!app.isQuitting) {
            e.preventDefault();
            stickerWindow.hide();
        }
    });

    stickerWindow.on('closed', () => {
        stickerWindow = null;
    });
}

function createFxWindow() {
    const displays = screen.getAllDisplays();
    let vMinX = Infinity, vMinY = Infinity, vMaxX = -Infinity, vMaxY = -Infinity;
    for (const d of displays) {
        vMinX = Math.min(vMinX, d.bounds.x);
        vMinY = Math.min(vMinY, d.bounds.y);
        vMaxX = Math.max(vMaxX, d.bounds.x + d.bounds.width);
        vMaxY = Math.max(vMaxY, d.bounds.y + d.bounds.height);
    }
    const winW = vMaxX - vMinX;
    const winH = vMaxY - vMinY;
    fxOriginX = vMinX;
    fxOriginY = vMinY;

    fxWindow = new BrowserWindow({
        width: winW,
        height: winH,
        x: vMinX,
        y: vMinY,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        resizable: false,
        skipTaskbar: true,
        hasShadow: false,
        backgroundColor: '#00000000',
        focusable: false,
        webPreferences: {
            preload: path.join(__dirname, 'fx_preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
        }
    });

    fxWindow.setAlwaysOnTop(true, 'screen-saver');
    fxWindow.setVisibleOnAllWorkspaces(true);
    fxWindow.setIgnoreMouseEvents(true, { forward: false });

    fxWindow.loadFile(path.join(__dirname, 'output', 'fx.html'));

    fxWindow.on('close', (e) => {
        if (!app.isQuitting) { e.preventDefault(); fxWindow.hide(); }
    });
    fxWindow.on('closed', () => { fxWindow = null; });
}

// ============== FX 相关 IPC（给渲染进程用） ==============
function sendToFx(channel, payload) {
    if (fxWindow && !fxWindow.isDestroyed()) {
        fxWindow.webContents.send(channel, payload);
    }
}

/**
 * cfg: {
 *   key,            // string 唯一标识：crosshair / explosion-<id>
 *   sprite,         // string 文件名：crosshair_sprite.webp
 *   frames, cols, rows, frameW, frameH,
 *   x, y,           // number 屏幕绝对坐标（中心点）
 *   w, h,           // number 实际显示尺寸（图标大小 110x130 之类）
 *   fps, loop       // bool 是否循环播放
 * }
 */
ipcMain.handle('fx-play', async (event, cfg) => {
    if (!cfg || !cfg.key) return false;
    const wrapped = Object.assign({}, cfg, {
        _winX: fxOriginX,
        _winY: fxOriginY,
    });
    sendToFx('fx-play', wrapped);
    return true;
});

ipcMain.handle('fx-stop', async (event, { key }) => {
    sendToFx('fx-stop', { key });
    return true;
});

ipcMain.handle('fx-stop-all', async () => {
    sendToFx('fx-stop-all');
    return true;
});

// 收到 fx.html 发来的播放结束（主要是一次性播放）
ipcMain.on('fx-play-end', (event, { key }) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('fx-play-ended', { key });
    }
});

function createTray() {
    const iconPath = path.join(__dirname, 'icon.ico');
    let icon = nativeImage.createFromPath(iconPath);
    // Windows 托盘对小尺寸图标显示最稳定，统一缩放到 16x16
    if (!icon.isEmpty()) {
        icon = icon.resize({ width: 16, height: 16 });
    }

    tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);

    const contextMenu = Menu.buildFromTemplate([
        { label: '显示/隐藏', click: () => toggleWindow() },
        { type: 'separator' },
        { label: '退出', click: () => { app.isQuitting = true; app.quit(); } }
    ]);

    tray.setToolTip('安琪');
    tray.setContextMenu(contextMenu);

    // 左键点击切换显示/隐藏
    tray.on('click', () => toggleWindow());
}

function toggleWindow() {
    if (!mainWindow) return;
    if (mainWindow.isVisible()) {
        mainWindow.hide();
    } else {
        mainWindow.show();
        mainWindow.focus();
    }
}

function startMouseTracking() {
    if (mouseTrackInterval) {
        clearInterval(mouseTrackInterval);
    }
    
    let lastCursorPos = null;
    
    mouseTrackInterval = setInterval(() => {
        if (!mainWindow || mainWindow.isDestroyed()) return;
        
        try {
            const cursorPos = screen.getCursorScreenPoint();
            
            // 只在鼠标位置实际变化时才发送事件，避免鼠标静止时不断重置闲置计时器
            if (lastCursorPos &&
                cursorPos.x === lastCursorPos.x &&
                cursorPos.y === lastCursorPos.y) {
                return;
            }
            lastCursorPos = cursorPos;
            
            const winPos = mainWindow.getPosition();
            const winSize = mainWindow.getSize();
            
            // 计算宠物中心在屏幕上的位置
            const petCenterX = winPos[0] + winSize[0] / 2;
            const petCenterY = winPos[1] + winSize[1] / 2;
            
            // 计算鼠标相对于宠物中心的位置
            const dx = cursorPos.x - petCenterX;
            const dy = cursorPos.y - petCenterY;
            
            // 发送给渲染进程
            // 多显示器支持：计算所有显示器的并集边界（虚拟桌面）
            // 这样前端散步/跟随动画的碰壁判断能覆盖多屏拼接场景
            const displays = screen.getAllDisplays();
            let vMinX = Infinity, vMinY = Infinity, vMaxX = -Infinity, vMaxY = -Infinity;
            for (const d of displays) {
                const b = d.bounds;
                vMinX = Math.min(vMinX, b.x);
                vMinY = Math.min(vMinY, b.y);
                vMaxX = Math.max(vMaxX, b.x + b.width);
                vMaxY = Math.max(vMaxY, b.y + b.height);
            }
            mainWindow.webContents.send('global-mouse-move', {
                x: cursorPos.x,
                y: cursorPos.y,
                dx: dx,
                dy: dy,
                winX: winPos[0],
                winY: winPos[1],
                winWidth: winSize[0],
                winHeight: winSize[1],
                // 虚拟桌面边界（所有显示器并集）
                virtualMinX: vMinX,
                virtualMinY: vMinY,
                virtualMaxX: vMaxX,
                virtualMaxY: vMaxY,
                // 兼容旧逻辑：主显示器工作区
                screenWidth: screen.getPrimaryDisplay().workArea.width,
                screenHeight: screen.getPrimaryDisplay().workArea.height
            });
        } catch (e) {
            // 忽略错误
        }
    }, 50); // 每 50ms 更新一次，约 20fps
}

ipcMain.handle('toggle-always-on-top', () => {
    isAlwaysOnTop = !isAlwaysOnTop;
    mainWindow.setAlwaysOnTop(isAlwaysOnTop, 'screen-saver');
    return isAlwaysOnTop;
});

// 调试：F12 切换 DevTools（独立窗口）+ 临时取消置顶/点击穿透，便于点击 DevTools
// 再次按 F12 关闭 DevTools 时恢复原置顶状态
let devToolsOpen = false;
let prevAlwaysOnTopForDev = null;
ipcMain.handle('toggle-dev-tools', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (!devToolsOpen) {
        // 打开前：保存当前置顶状态，临时取消置顶，避免遮挡 DevTools
        prevAlwaysOnTopForDev = mainWindow.isAlwaysOnTop();
        mainWindow.setAlwaysOnTop(false);
        // 关闭点击穿透，让用户能点击 DevTools（即便鼠标移到宠物窗口上方）
        mainWindow.setIgnoreMouseEvents(false);
        // 独立窗口模式打开 DevTools
        mainWindow.webContents.openDevTools({ mode: 'detach' });
        devToolsOpen = true;
    } else {
        mainWindow.webContents.closeDevTools();
        // 恢复原置顶状态
        if (prevAlwaysOnTopForDev) {
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
        }
        prevAlwaysOnTopForDev = null;
        devToolsOpen = false;
    }
    return devToolsOpen;
});

ipcMain.handle('exit-app', () => {
    app.isQuitting = true;
    app.quit();
});

ipcMain.handle('drag-window', (event, x, y) => {
    const nx = Math.round(Number(x));
    const ny = Math.round(Number(y));
    if (isFinite(nx) && isFinite(ny)) {
        mainWindow.setPosition(nx, ny);
    }
});

ipcMain.handle('get-window-position', () => {
    const pos = mainWindow.getPosition();
    return { x: pos[0], y: pos[1] };
});

// 点击穿透：透明区域不拦截鼠标，仅宠物/菜单区域可交互
ipcMain.on('set-ignore-mouse-events', (event, ignore, forward) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.setIgnoreMouseEvents(ignore, { forward: forward !== false });
    }
});

// ========== 💩拖尾贴纸（转发到全屏贴纸窗口，坐标转换为窗口本地坐标）==========
ipcMain.on('drop-poop-sticker', (event, data) => {
    if (stickerWindow && !stickerWindow.isDestroyed()) {
        // 屏幕绝对坐标 → 贴纸窗口本地坐标
        stickerWindow.webContents.send('drop-poop-sticker', {
            x: data.x - stickerOriginX,
            y: data.y - stickerOriginY,
            rotation: data.rotation,
            size: data.size,
        });
    }
});

ipcMain.on('clear-poop-stickers', () => {
    if (stickerWindow && !stickerWindow.isDestroyed()) {
        stickerWindow.webContents.send('clear-poop-stickers');
    }
});

// ========== 桌面文件操作 ==========
// 列出桌面文件（仅文件，不含目录和系统文件）
ipcMain.handle('list-desktop-files', async () => {
    try {
        const desktopPath = path.join(os.homedir(), 'Desktop');
        const entries = fs.readdirSync(desktopPath, { withFileTypes: true });
        const files = [];
        for (const entry of entries) {
            if (!entry.isFile()) continue;
            const name = entry.name;
            // 过滤系统文件
            if (name === 'desktop.ini' || name.startsWith('.')) continue;
            const fullPath = path.join(desktopPath, name);
            try {
                const stat = fs.statSync(fullPath);
                files.push({
                    name: name,
                    path: fullPath,
                    size: stat.size,
                    mtime: stat.mtimeMs,
                });
            } catch (e) {
                // 跳过无法访问的文件
            }
        }
        // 按修改时间倒序，最多返回 30 个
        files.sort((a, b) => b.mtime - a.mtime);
        return files.slice(0, 30);
    } catch (e) {
        return [];
    }
});

// 删除文件（移到回收站，安全删除）
ipcMain.handle('delete-file', async (event, filePath) => {
    let prevAlwaysOnTop = null;
    let prevVisibility = null;
    let prevMinimized = null;
    try {
        if (!filePath || typeof filePath !== 'string') {
            return { success: false, error: '文件路径无效' };
        }
        // 规范化路径：统一使用操作系统的路径分隔符，解析相对路径
        const normalizedPath = path.resolve(filePath.trim());
        // 检查文件是否存在
        if (!fs.existsSync(normalizedPath)) {
            return { success: false, error: `文件不存在: ${normalizedPath}` };
        }

        // ========== 修复：取消 screen-saver 级置顶让系统对话框能显示，但不隐藏窗口（避免角色消失） ==========
        if (mainWindow && !mainWindow.isDestroyed()) {
            prevAlwaysOnTop = mainWindow.isAlwaysOnTop();
            // 只取消置顶级别，不隐藏窗口——这样系统对话框能显示在安琪上方，角色不会消失
            mainWindow.setAlwaysOnTop(false);
            // 短暂等待让 z-order 生效
            await new Promise(r => setTimeout(r, 100));
        }

        // ========== 尝试 1：Electron 原生 shell.trashItem（优先，用户最习惯） ==========
        try {
            await shell.trashItem(normalizedPath);
            return { success: true, path: normalizedPath, method: 'shell' };
        } catch (shellErr) {
            console.warn('[delete-file] shell.trashItem 失败，直接走安琪回收站兜底（跳过 PowerShell，避免弹黑框）:', shellErr.message);

            // ========== 尝试 2：终极回退 —— 把文件移动到应用自己的"安琪回收站"目录（保证不会真的丢文件） ==========
            // （不再使用 trashItemByPowerShell：execFile powershell.exe 可能导致短暂弹窗，用户体验不佳）
            const fallback = await moveToAppTrashBin(normalizedPath);
            if (fallback.success) {
                return {
                    success: true,
                    path: normalizedPath,
                    method: 'app-trash',
                    movedTo: fallback.movedTo,
                    warning: '系统回收站不可用，已移动到安琪临时回收站'
                };
            }

            return {
                success: false,
                error: `删除失败：${shellErr.message}`,
                details: {
                    shell: shellErr.message,
                    appTrash: fallback.error || null,
                }
            };
        }
    } catch (e) {
        console.error('delete-file 顶层异常:', e.message, 'filePath:', filePath);
        return { success: false, error: e.message || '删除失败' };
    } finally {
        // ========== 恢复窗口的置顶状态（窗口未隐藏，无需恢复显示） ==========
        if (mainWindow && !mainWindow.isDestroyed() && prevAlwaysOnTop) {
            try {
                mainWindow.setAlwaysOnTop(true, 'screen-saver');
            } catch (_) {
                // 忽略恢复时的任何错误
            }
        }
    }
});

// 回退方案 A：通过 PowerShell 调用 VB.NET 的 SendToRecycleBin（不弹 UI，对中文路径兼容性通常更好）
function trashItemByPowerShell(filePath) {
    return new Promise((resolve) => {
        const { execFile } = require('child_process');
        // 对单引号转义（PowerShell 字符串中单引号用 '' 表示）
        const escaped = filePath.replace(/'/g, "''");
        const psCmd = `
            $ErrorActionPreference = 'Stop';
            Add-Type -AssemblyName 'Microsoft.VisualBasic';
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('${escaped}',
                [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
                [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin);
            exit 0;
        `;
        // -NoProfile 快速启动，-WindowStyle Hidden 隐藏窗口，-NonInteractive 不要求交互
        const child = execFile(
            'powershell.exe',
            ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', psCmd],
            { timeout: 15000, windowsHide: true },
            (err, stdout, stderr) => {
                if (err) {
                    resolve({ success: false, error: err.message + ' ' + (stderr || '').toString() });
                } else {
                    resolve({ success: true });
                }
            }
        );
        // 兜底：10 秒强制判定为失败（防止 PowerShell 卡住）
        setTimeout(() => {
            try { child.kill('SIGKILL'); } catch (_) {}
            resolve({ success: false, error: 'PowerShell timeout' });
        }, 10000).unref?.();
    });
}

// 回退方案 B：将文件移动到应用自己的"安琪回收站"目录（用户数据目录/AnqiTrashBin），保证数据不丢
async function moveToAppTrashBin(filePath) {
    try {
        const trashDir = path.join(app.getPath('userData'), 'AnqiTrashBin');
        if (!fs.existsSync(trashDir)) {
            fs.mkdirSync(trashDir, { recursive: true });
        }
        const baseName = path.basename(filePath);
        const ext = path.extname(baseName);
        const stem = path.basename(baseName, ext);
        // 时间戳+随机后缀避免重名覆盖
        const dest = path.join(trashDir, `${stem}_${Date.now()}_${Math.floor(Math.random()*10000)}${ext}`);
        fs.renameSync(filePath, dest);

        // 同时写一个 manifest 记录原始路径，便于后续做"恢复"功能
        const manifest = {
            originalPath: filePath,
            movedTo: dest,
            time: new Date().toISOString(),
        };
        try {
            const manifestDir = path.join(trashDir, '_manifests');
            if (!fs.existsSync(manifestDir)) fs.mkdirSync(manifestDir, { recursive: true });
            fs.writeFileSync(
                path.join(manifestDir, `${Date.now()}_${Math.floor(Math.random()*10000)}.json`),
                JSON.stringify(manifest, null, 2),
                'utf8'
            );
        } catch (_) { /* manifest 写失败不影响主流程 */ }

        return { success: true, movedTo: dest };
    } catch (e) {
        return { success: false, error: e.message };
    }
}

// 桌面图标准确位置缓存：避免每次右键删除都启动 PowerShell（PowerShell 启动慢且可能闪屏）
// 缓存结构：{ ts: number, items: Array<{name, x, y}> }  items 中 x,y 是图标中心屏幕绝对坐标
let desktopIconCache = null;
const DESKTOP_ICON_CACHE_TTL = 5000;  // 5 秒内复用，避免连续调用反复启动 PowerShell

// 通过 PowerShell + C# UIAutomation 读取桌面图标的真实屏幕坐标
// 用 -WindowStyle Hidden + windowsHide 双重隐藏，避免闪屏
// 返回 Array<{name, x, y}>  其中 x,y 是图标中心点屏幕绝对坐标
//
// 为什么用 PowerShell + C#？
//   - Electron 内置 API（如 screen.getCursorScreenPoints）只封装了少量常用功能
//   - 读取桌面 SysListView32 的图标位置不在内置 API 中
//   - JS 层调用 user32.dll 需要 FFI 桥接层（koffi/ffi-napi 需要新依赖）
//   - PowerShell + C# 是无新依赖的方案
//
// 为什么用 UIAutomation 而不是 SendMessage LVM_GETITEMTEXT？
//   - LVM_GETITEMTEXT 跨进程时无法写入 pszText 指向的内存（需要 VirtualAllocEx）
//   - UIAutomation 是 Windows 高层 API，无跨进程内存问题，直接读取项的 BoundingRectangle
function readDesktopIconsViaPowerShell() {
    return new Promise((resolve) => {
        // C# 代码：用 EnumWindows 找到桌面 SysListView32（可能在 Progman 或 WorkerW 下）
        // 然后用 UIAutomation 读取每个 item 的 Name 和 BoundingRectangle
        // 输出 JSON 数组：[{"name":"...", "x":123, "y":456}, ...]
        const psScript = `
$ErrorActionPreference = 'Stop'
# 关键：设置输出编码为 UTF-8，否则中文文件名会被 GBK 编码输出，Node.js 按 UTF-8 解码会乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$csCode = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Windows.Automation;

public class DesktopIconsUA {
    [DllImport("user32.dll")]
    static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int GetClassNameW(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [DllImport("user32.dll", SetLastError = true)]
    static extern IntPtr FindWindowExW(IntPtr hwndParent, IntPtr hwndChildAfter, string lpszClass, string lpszWindow);
    [DllImport("user32.dll")]
    static extern bool IsWindowVisible(IntPtr hWnd);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    static IntPtr foundListView = IntPtr.Zero;

    static IntPtr FindChildRecursive(IntPtr parent, string targetClass, int maxDepth) {
        if (maxDepth <= 0) return IntPtr.Zero;
        IntPtr child = IntPtr.Zero;
        while (true) {
            child = FindWindowExW(parent, child, null, null);
            if (child == IntPtr.Zero) break;
            StringBuilder cls = new StringBuilder(256);
            GetClassNameW(child, cls, 256);
            if (cls.ToString() == targetClass) return child;
            IntPtr deeper = FindChildRecursive(child, targetClass, maxDepth - 1);
            if (deeper != IntPtr.Zero) return deeper;
        }
        return IntPtr.Zero;
    }

    static IntPtr SearchDefViewInTree(IntPtr hWnd, int depth) {
        if (depth > 5) return IntPtr.Zero;
        StringBuilder cls = new StringBuilder(256);
        GetClassNameW(hWnd, cls, 256);
        string cn = cls.ToString();
        if (cn == "SHELLDLL_DefView") {
            if (IsWindowVisible(hWnd)) {
                IntPtr lv = FindWindowExW(hWnd, IntPtr.Zero, "SysListView32", null);
                if (lv == IntPtr.Zero) lv = FindChildRecursive(hWnd, "SysListView32", 3);
                if (lv != IntPtr.Zero) return lv;
            }
            return IntPtr.Zero;
        }
        IntPtr child = IntPtr.Zero;
        while (true) {
            child = FindWindowExW(hWnd, child, null, null);
            if (child == IntPtr.Zero) break;
            IntPtr hit = SearchDefViewInTree(child, depth + 1);
            if (hit != IntPtr.Zero) return hit;
        }
        return IntPtr.Zero;
    }

    static bool EnumTopProc(IntPtr hWnd, IntPtr lParam) {
        StringBuilder cls = new StringBuilder(256);
        GetClassNameW(hWnd, cls, 256);
        string cn = cls.ToString();
        if (cn == "Progman" || cn == "WorkerW") {
            if (IsWindowVisible(hWnd)) {
                IntPtr lv = SearchDefViewInTree(hWnd, 0);
                if (lv != IntPtr.Zero) {
                    foundListView = lv;
                    return false;
                }
            }
        }
        return true;
    }

    public static void Run() {
        foundListView = IntPtr.Zero;
        EnumWindows(EnumTopProc, IntPtr.Zero);
        if (foundListView == IntPtr.Zero) {
            Console.WriteLine("[]");
            return;
        }

        AutomationElement listView = AutomationElement.FromHandle(foundListView);
        if (listView == null) {
            Console.WriteLine("[]");
            return;
        }

        var items = listView.FindAll(TreeScope.Children, Condition.TrueCondition);
        var sb = new StringBuilder("[");
        for (int i = 0; i < items.Count; i++) {
            var item = items[i];
            string name = item.Current.Name ?? "";
            var rect = item.Current.BoundingRectangle;
            int cx = (int)(rect.X + rect.Width / 2);
            int cy = (int)(rect.Y + rect.Height / 2);

            if (i > 0) sb.Append(",");
            var escaped = new StringBuilder();
            foreach (char c in name) {
                if (c == '\\\\') escaped.Append("\\\\\\\\");
                else if (c == '"') escaped.Append("\\\\\\"");
                else if (c < 0x20) escaped.Append(string.Format("\\\\u{0:x4}", (int)c));
                else escaped.Append(c);
            }
            sb.Append("{\\"name\\":\\"" + escaped.ToString() + "\\",\\"x\\":" + cx + ",\\"y\\":" + cy + "}");
        }
        sb.Append("]");
        Console.WriteLine(sb.ToString());
    }
}
'@
$tmp = Join-Path $env:TEMP "icons_ua_$PID.cs"
Set-Content -Path $tmp -Value $csCode -Encoding UTF8
try {
    Add-Type -Path $tmp -ReferencedAssemblies UIAutomationClient,UIAutomationTypes,WindowsBase
    [DesktopIconsUA]::Run()
} catch {
    [Console]::Error.WriteLine("ERR: " + $_.Exception.Message)
    Console.WriteLine("[]")
} finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue
}
`;

        // 编码后通过 -EncodedCommand 传递，避免引号转义问题
        // -WindowStyle Hidden + windowsHide 双重隐藏，避免闪屏
        const buf = Buffer.from(psScript, 'utf16le');
        const encoded = buf.toString('base64');

        const child = execFile(
            'powershell.exe',
            ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-OutputFormat', 'Text', '-EncodedCommand', encoded],
            { windowsHide: true, maxBuffer: 10 * 1024 * 1024, timeout: 15000 }
        );

        let stdout = '';
        let stderr = '';
        child.stdout.on('data', (d) => { stdout += d; });
        child.stderr.on('data', (d) => { stderr += d; });

        const timer = setTimeout(() => {
            try { child.kill(); } catch (_) {}
            resolve([]);
        }, 15000);

        child.on('close', (code) => {
            clearTimeout(timer);
            if (code !== 0) {
                console.warn('[readDesktopIconsViaPowerShell] exit code=', code, 'stderr=', stderr.slice(0, 500));
                resolve([]);
                return;
            }
            // 提取 stdout 中的 JSON 行
            const lines = stdout.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
            for (const line of lines) {
                if (line.startsWith('[')) {
                    try {
                        const arr = JSON.parse(line);
                        if (Array.isArray(arr)) {
                            resolve(arr);
                            return;
                        }
                    } catch (_) {}
                }
            }
            console.warn('[readDesktopIconsViaPowerShell] no JSON in stdout, stderr=', stderr.slice(0, 500));
            resolve([]);
        });

        child.on('error', (e) => {
            clearTimeout(timer);
            console.warn('[readDesktopIconsViaPowerShell] err:', e.message);
            resolve([]);
        });
    });
}

// 获取桌面图标准确位置
// 坐标语义：返回的是图标中心点屏幕绝对坐标
// 优先用 PowerShell + C# UIAutomation 读取 SysListView32 真实图标坐标
// 失败/超时则降级到网格模拟
ipcMain.handle('get-desktop-file-position', async (event, fileNameOrPath) => {
    try {
        let filePath;
        if (path.isAbsolute(fileNameOrPath)) {
            filePath = path.resolve(fileNameOrPath.trim());
        } else {
            filePath = path.join(os.homedir(), 'Desktop', fileNameOrPath);
        }
        const fileName = path.basename(filePath);

        console.log('[get-desktop-file-position] request fileName=', fileName, 'filePath=', filePath, 'exists=', fs.existsSync(filePath));

        // ===== Step 1: 用缓存或调 PowerShell 拿真实图标坐标 =====
        let items = null;
        const now = Date.now();
        if (desktopIconCache && (now - desktopIconCache.ts) < DESKTOP_ICON_CACHE_TTL) {
            items = desktopIconCache.items;
            console.log('[get-desktop-file-position] use cached items, count=', items.length);
        } else {
            console.log('[get-desktop-file-position] reading desktop icons via PowerShell...');
            items = await readDesktopIconsViaPowerShell();
            console.log('[get-desktop-file-position] PowerShell returned items.length=', items.length);
            if (items.length > 0) {
                desktopIconCache = { ts: now, items };
                console.log('[get-desktop-file-position] first10 items:', items.slice(0, 10).map(it => ({ name: it.name, x: it.x, y: it.y })));
            }
        }

        // ===== Step 2: 3-pass 匹配文件名 =====
        if (items.length > 0) {
            // Pass 1: 全名匹配
            let hit = items.find(it => it.name === fileName);
            // Pass 2: stem 匹配（去扩展名，忽略大小写）
            if (!hit) {
                const stem = path.basename(fileName, path.extname(fileName)).toLowerCase();
                hit = items.find(it => path.basename(it.name, path.extname(it.name)).toLowerCase() === stem);
            }
            // Pass 3: .lnk stem 匹配（桌面快捷方式可能展示为 .lnk，目标文件 stem 一致）
            if (!hit) {
                const stem = path.basename(fileName, path.extname(fileName)).toLowerCase();
                hit = items.find(it => {
                    if (!it.name.toLowerCase().endsWith('.lnk')) return false;
                    return path.basename(it.name, '.lnk').toLowerCase() === stem;
                });
            }
            if (hit) {
                const out = { x: hit.x, y: hit.y, accurate: true, match: 1, reason: 'syslistview' };
                console.log('[get-desktop-file-position] SysListView hit:', JSON.stringify(out));
                return out;
            }
            console.log('[get-desktop-file-position] SysListView no match, fall back to grid');
        }

        // ===== Step 3: 网格降级方案 =====
        const { workArea } = screen.getPrimaryDisplay();
        const desktopPath = path.join(os.homedir(), 'Desktop');
        const entries = fs.readdirSync(desktopPath, { withFileTypes: true })
            .filter(e => e.isFile() && e.name !== 'desktop.ini' && !e.name.startsWith('.'))
            .map(e => e.name)
            .sort();
        console.log('[get-desktop-file-position] grid fallback entries.length=', entries.length);
        let idx = entries.indexOf(fileName);
        if (idx < 0) {
            const stem = path.basename(fileName, path.extname(fileName));
            idx = entries.findIndex(n => path.basename(n, path.extname(n)).toLowerCase() === stem.toLowerCase());
        }
        let x, y;
        if (idx < 0) {
            // 找不到文件索引：走到屏幕中心偏上
            x = workArea.x + workArea.width / 2;
            y = workArea.y + workArea.height / 3;
        } else {
            // 估算列数：基于工作区宽度（每列约 100px）
            const cols = Math.max(1, Math.floor(workArea.width / 100));
            const iconW = 100;
            const iconH = 110;
            const col = idx % cols;
            const row = Math.floor(idx / cols);
            x = workArea.x + col * iconW + iconW / 2;
            y = workArea.y + row * iconH + iconH / 2;
            x = Math.max(workArea.x + 50, Math.min(workArea.x + workArea.width - 50, x));
            y = Math.max(workArea.y + 50, Math.min(workArea.y + workArea.height - 50, y));
        }
        const out = { x, y, accurate: false, match: -1, reason: 'grid-fallback' };
        console.log('[get-desktop-file-position] grid fallback:', JSON.stringify(out));
        return out;
    } catch (e) {
        console.error('[get-desktop-file-position] top err:', e.message);
        const { workArea } = screen.getPrimaryDisplay();
        return {
            x: workArea.x + workArea.width / 2,
            y: workArea.y + workArea.height / 2,
            accurate: false,
            match: -1,
            reason: 'EXCEPTION',
            error: e.message
        };
    }
});

// ========== 自动更新 ==========
function setupAutoUpdater() {
    autoUpdater.autoDownload = false;  // 不自动下载，等用户确认
    autoUpdater.autoInstallOnAppQuit = true;  // 下载完成后退出时自动安装

    let updateInfo = null;

    autoUpdater.on('update-available', (info) => {
        updateInfo = info;
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-available', {
                version: info.version,
                releaseNotes: info.releaseNotes || '',
            });
        }
    });

    autoUpdater.on('update-not-available', () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-not-available');
        }
    });

    autoUpdater.on('download-progress', (progress) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-download-progress', {
                percent: Math.round(progress.percent),
                transferred: progress.transferred,
                total: progress.total,
            });
        }
    });

    autoUpdater.on('update-downloaded', () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-downloaded');
        }
    });

    autoUpdater.on('error', (err) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-error', err ? err.message : '未知错误');
        }
    });

    // 启动后 3 秒检查更新（给窗口加载留时间）
    setTimeout(() => {
        autoUpdater.checkForUpdates().catch(() => {});
    }, 3000);
}

// IPC：手动检查更新
ipcMain.handle('check-for-updates', () => {
    autoUpdater.checkForUpdates().catch(() => {});
});

// IPC：开始下载更新
ipcMain.handle('download-update', () => {
    autoUpdater.downloadUpdate().catch(() => {});
});

// IPC：退出并安装更新
ipcMain.handle('quit-and-install', () => {
    app.isQuitting = true;
    autoUpdater.quitAndInstall();
});

app.whenReady().then(() => {
    createWindow();
    createTray();
    setupAutoUpdater();

    // 如果是通过右键菜单启动（首次启动带 --delete-file 参数）
    if (pendingDeleteFromArgv) {
        mainWindow.webContents.once('did-finish-load', () => {
            setTimeout(() => {
                mainWindow.webContents.send('context-menu-delete-file', pendingDeleteFromArgv);
            }, 500);
        });
    }

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
