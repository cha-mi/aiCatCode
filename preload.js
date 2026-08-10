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

    // 自动更新
    checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
    downloadUpdate: () => ipcRenderer.invoke('download-update'),
    quitAndInstall: () => ipcRenderer.invoke('quit-and-install'),
    onUpdateAvailable: (callback) => ipcRenderer.on('update-available', (e, data) => callback(data)),
    onUpdateNotAvailable: (callback) => ipcRenderer.on('update-not-available', () => callback()),
    onUpdateDownloadProgress: (callback) => ipcRenderer.on('update-download-progress', (e, data) => callback(data)),
    onUpdateDownloaded: (callback) => ipcRenderer.on('update-downloaded', () => callback()),
    onUpdateError: (callback) => ipcRenderer.on('update-error', (e, msg) => callback(msg)),
});
