import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  getUsage: () => ipcRenderer.invoke('get-usage'),
  refreshNow: () => ipcRenderer.invoke('refresh-now'),
  onUsageUpdate: (callback: (data: any) => void) => {
    const handler = (_event: any, data: any) => callback(data);
    ipcRenderer.on('usage-update', handler);
    return () => ipcRenderer.removeListener('usage-update', handler);
  },
});
