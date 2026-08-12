const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    toggleAlwaysOnTop: () => ipcRenderer.invoke('toggle-always-on-top'),
    exitApp: () => ipcRenderer.invoke('exit-app'),
    dragWindow: (dx, dy) => ipcRenderer.invoke('drag-window', dx, dy),
    getWindowPosition: () => ipcRenderer.invoke('get-window-position'),
    onGlobalMouseMove: (callback) => {
        ipcRenderer.on('global-mouse-move', (event, data) => callback(data));
    },
    setIgnoreMouseEvents: (ignore, forward = true) => ipcRenderer.send('set-ignore-mouse-events', ignore, forward),

    // 💩拖尾贴纸（发送到全屏贴纸窗口）
    dropPoopSticker: (x, y, rotation, size) => ipcRenderer.send('drop-poop-sticker', { x, y, rotation, size }),
    clearPoopStickers: () => ipcRenderer.send('clear-poop-stickers'),

    // 自动更新
    checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
    downloadUpdate: () => ipcRenderer.invoke('download-update'),
    quitAndInstall: () => ipcRenderer.invoke('quit-and-install'),
    onUpdateAvailable: (callback) => ipcRenderer.on('update-available', (e, data) => callback(data)),
    onUpdateNotAvailable: (callback) => ipcRenderer.on('update-not-available', () => callback()),
    onUpdateDownloadProgress: (callback) => ipcRenderer.on('update-download-progress', (e, data) => callback(data)),
    onUpdateDownloaded: (callback) => ipcRenderer.on('update-downloaded', () => callback()),
    onUpdateError: (callback) => ipcRenderer.on('update-error', (e, msg) => callback(msg)),

    // 桌面文件操作
    listDesktopFiles: () => ipcRenderer.invoke('list-desktop-files'),
    deleteFile: (filePath) => ipcRenderer.invoke('delete-file', filePath),
    getDesktopFilePosition: (fileName) => ipcRenderer.invoke('get-desktop-file-position', fileName),

    // 右键菜单删除文件（从 Windows shell 右键菜单触发）
    onContextMenuDeleteFile: (callback) => ipcRenderer.on('context-menu-delete-file', (e, filePath) => callback(filePath)),

    // 调试：F12 切换 DevTools（独立窗口）+ 临时取消置顶/穿透，便于点击 DevTools
    toggleDevTools: () => ipcRenderer.invoke('toggle-dev-tools'),
});
