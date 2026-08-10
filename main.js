const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const { autoUpdater } = require('electron-updater');

let mainWindow;
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
            const workArea = screen.getPrimaryDisplay().workArea;
            mainWindow.webContents.send('global-mouse-move', {
                x: cursorPos.x,
                y: cursorPos.y,
                dx: dx,
                dy: dy,
                winX: winPos[0],
                winY: winPos[1],
                winWidth: winSize[0],
                winHeight: winSize[1],
                screenWidth: workArea.width,
                screenHeight: workArea.height
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

ipcMain.handle('exit-app', () => {
    app.isQuitting = true;
    app.quit();
});

ipcMain.handle('drag-window', (event, x, y) => {
    mainWindow.setPosition(Math.round(x), Math.round(y));
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
