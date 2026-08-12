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
// 解析命令行参数中的 --delete-file <path> 或 --delete-file-pending
// 健壮解析：跳过 --delete-file 后面紧跟的其他 --xxx 参数（Electron 自带参数会插入其中）
function parseDeleteFileArg(argv) {
    // 新方式：--delete-file-pending（路径在临时文件中，避免命令行中文乱码）
    if (argv.includes('--delete-file-pending')) {
        try {
            const tempFile = path.join(os.tmpdir(), 'anqi_delete_path.txt');
            const raw = fs.readFileSync(tempFile, 'utf-8').trim();
            // 去掉可能的 BOM 和尾随换行
            const cleaned = raw.replace(/^\uFEFF/, '').replace(/\r?\n$/, '').trim();
            try { fs.unlinkSync(tempFile); } catch (_) {}
            if (cleaned && path.isAbsolute(cleaned)) return cleaned;
        } catch (_) {}
        return null;
    }

    // 旧方式：--delete-file <path>（命令行传路径，中文可能乱码）
    const idx = argv.indexOf('--delete-file');
    if (idx < 0) return null;
    for (let i = idx + 1; i < argv.length; i++) {
        const arg = argv[i];
        if (!arg) continue;
        if (arg.startsWith('--') || arg.startsWith('-')) continue;
        let candidate = arg.replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1');
        if (path.isAbsolute(candidate)) {
            return candidate;
        }
    }
    return null;
}

const pendingDeleteFromArgv = parseDeleteFileArg(process.argv);

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
    // 已有实例运行，退出
    app.quit();
} else {
    app.on('second-instance', (event, commandLine, workingDirectory) => {
        // 第二实例启动（右键菜单触发），解析文件路径并通知主窗口
        console.log('[second-instance] commandLine=', JSON.stringify(commandLine));
        const filePath = parseDeleteFileArg(commandLine);
        console.log('[second-instance] parsed filePath=', filePath);

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
            console.warn('[delete-file] shell.trashItem 失败，尝试 PowerShell 回退方案:', shellErr.message);

            // ========== 尝试 2：PowerShell 调用 VB.NET FileSystem.DeleteFile（SendToRecycleBin 模式，不弹确认更稳定） ==========
            try {
                const psResult = await trashItemByPowerShell(normalizedPath);
                if (psResult.success) {
                    return { success: true, path: normalizedPath, method: 'powershell' };
                }
                console.warn('[delete-file] PowerShell 回退亦失败:', psResult.error);
            } catch (psErr) {
                console.warn('[delete-file] PowerShell 回退异常:', psErr.message);
            }

            // ========== 尝试 3：终极回退 —— 把文件移动到应用自己的"安琪回收站"目录（保证不会真的丢文件） ==========
            const fallback = await moveToAppTrashBin(normalizedPath);
            if (fallback.success) {
                return {
                    success: true,
                    path: normalizedPath,
                    method: 'app-trash',
                    movedTo: fallback.movedTo,
                    warning: '回收站不可用，已移动到安琪临时回收站'
                };
            }

            // 三重保险都失败时才返回失败，并把三次原因都带上便于排查
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

// 获取桌面图标准确位置（通过 PowerShell 跨进程读取桌面 ListView）
// 返回屏幕绝对坐标 {x, y, accurate, lvX, lvY, match, reason}
// 坐标语义：返回的是"宠物应该走到的屏幕点"=图标项中心下方（让宠物脚站在图标正下方，头部不遮挡）
ipcMain.handle('get-desktop-file-position', async (event, fileNameOrPath) => {
    try {
        // fileNameOrPath 可能是文件名（前端调用）或完整路径（右键菜单→second-instance 调用）
        let filePath;
        if (path.isAbsolute(fileNameOrPath)) {
            filePath = path.resolve(fileNameOrPath.trim());
        } else {
            filePath = path.join(os.homedir(), 'Desktop', fileNameOrPath);
        }
        const fileName = path.basename(filePath);

        console.log('[get-desktop-file-position] request fileName=', fileName, 'filePath=', filePath, 'exists=', fs.existsSync(filePath));

        // 调用 PowerShell 脚本获取图标位置
        // 用 -File + 环境变量传路径（避免命令行参数编码问题和 param 块解析问题）
        const scriptPath = path.join(__dirname, 'get_icon_pos.ps1');

        const result = await new Promise((resolve) => {
            const env = { ...process.env, ANQI_FILE_PATH: filePath };
            execFile('powershell.exe', [
                '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', scriptPath
            ], { timeout: 15000, maxBuffer: 1024 * 1024, encoding: 'utf-8', env }, (err, stdout, stderr) => {
                if (err) {
                    console.warn('[get-desktop-file-position] exec err:', err.message, 'stderr:', stderr?.substring(0, 500));
                    resolve(null);
                    return;
                }
                try {
                    const trimmed = stdout.trim();
                    console.log('[get-desktop-file-position] PS stdout:', trimmed.substring(0, 300));
                    const json = JSON.parse(trimmed);
                    resolve(json);
                } catch (e) {
                    console.warn('[get-desktop-file-position] JSON parse err:', e.message, 'stdout=', stdout?.substring(0, 300));
                    resolve(null);
                }
            });
        });

        // 桌面图标项尺寸（含图标+文件名文字区域，Win10/11 默认大图标视图约110x130）
        const ITEM_W = 110;
        const ITEM_H = 130;
        // 目标 = 图标项中心（角色头部会和文件重叠）
        const OFFSET_X = ITEM_W / 2;
        const OFFSET_Y = ITEM_H / 2;

        if (result && result.found) {
            // result.x,y = 桌面 ListView 图标项左上角屏幕坐标
            const finalX = result.x + OFFSET_X;
            const finalY = result.y + OFFSET_Y;
            const out = {
                x: finalX,
                y: finalY,
                accurate: true,
                lvX: result.x,
                lvY: result.y,
                match: result.match || 0,
                lvname: result.lvname || ''
            };
            console.log('[get-desktop-file-position] OK:', JSON.stringify(out));
            return out;
        }

        console.warn('[get-desktop-file-position] PS fallback, result=', JSON.stringify(result), 'reason=', result && result.reason);
        // 降级：网格模拟（按名称排序 → 行列位置 → 中心下方偏移）
        const { workArea } = screen.getPrimaryDisplay();
        const desktopPath = path.join(os.homedir(), 'Desktop');
        const entries = fs.readdirSync(desktopPath, { withFileTypes: true })
            .filter(e => e.isFile() && e.name !== 'desktop.ini' && !e.name.startsWith('.'))
            .map(e => e.name)
            .sort();
        console.log('[get-desktop-file-position] fileName=', fileName, 'entries.length=', entries.length, 'first10=', entries.slice(0, 10));
        // 找索引：先全名，否则 stem
        let idx = entries.indexOf(fileName);
        if (idx < 0) {
            const stem = path.basename(fileName, path.extname(fileName));
            idx = entries.findIndex(n => path.basename(n, path.extname(n)).toLowerCase() === stem.toLowerCase());
        }
        console.log('[get-desktop-file-position] grid idx=', idx);
        let x, y;
        if (idx < 0) {
            // 找不到文件索引：走到屏幕中心偏上（比右下角更合理）
            x = workArea.x + workArea.width / 2;
            y = workArea.y + workArea.height / 3;
        } else {
            const cols = 6;
            const iconW = 110;
            const iconH = 130;
            const col = idx % cols;
            const row = Math.floor(idx / cols);
            // 左上角 + 中心（与 ListView 同款公式：图标中心）
            x = workArea.x + col * iconW + iconW / 2;
            y = workArea.y + row * iconH + iconH / 2;
            x = Math.max(workArea.x + 100, Math.min(workArea.x + workArea.width - 100, x));
            y = Math.max(workArea.y + 100, Math.min(workArea.y + workArea.height - 100, y));
        }
        const out = { x, y, accurate: false, match: -1, reason: result && result.reason };
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
