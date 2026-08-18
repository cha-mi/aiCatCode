const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fxAPI', {
    onPlay: (callback) => {
        ipcRenderer.on('fx-play', (event, data) => callback(data));
    },
    onStop: (callback) => {
        ipcRenderer.on('fx-stop', (event, data) => callback(data));
    },
    onStopAll: (callback) => {
        ipcRenderer.on('fx-stop-all', () => callback());
    },
    notifyPlayEnd: (key) => {
        try { ipcRenderer.send('fx-play-end', { key }); } catch(_) {}
    },
});
