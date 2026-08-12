const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('stickerAPI', {
    onDropSticker: (callback) => {
        ipcRenderer.on('drop-poop-sticker', (event, data) => callback(data));
    },
    onClearStickers: (callback) => {
        ipcRenderer.on('clear-poop-stickers', () => callback());
    },
});
