import { app, ipcMain } from 'electron';
import { menubar } from 'menubar';
import path from 'path';
import { Poller } from './poller';

const isDev = !app.isPackaged;
const iconPath = path.join(__dirname, '..', 'public', 'iconTemplate.png');

// Always load built files — works in both dev and production
const htmlPath = path.join(__dirname, '..', 'dist', 'index.html');
const indexUrl = `file://${htmlPath}`;

console.log('[TokenEye] isDev:', isDev, 'index:', indexUrl);

const poller = new Poller(60_000);

const mb = menubar({
  icon: iconPath,
  index: indexUrl,
  browserWindow: {
    width: 380,
    height: 420,
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  },
  showOnAllWorkspaces: false,
  showDockIcon: false,
});

mb.on('ready', () => {
  console.log('[TokenEye] menubar ready');
  poller.setOnResults((results) => {
    const win = mb.window;
    if (win && !win.isDestroyed()) {
      win.webContents.send('usage-update', results);
    }
  });
  poller.start();
});

mb.on('after-show', async () => {
  const win = mb.window;
  if (!win) return;
  poller.pollNow();
  try {
    const html = await win.webContents.executeJavaScript('document.documentElement.outerHTML');
    console.log('[TokenEye] DOM:', html.slice(0, 800));
  } catch (err) {
    console.error('[TokenEye] eval error:', err);
  }
});

mb.on('after-create-window', () => {
  const win = mb.window;
  if (!win) return;
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error('[TokenEye] did-fail-load:', code, desc, url);
  });
  win.webContents.on('did-finish-load', () => {
    console.log('[TokenEye] did-finish-load:', win.webContents.getURL());
  });
  win.webContents.on('console-message', (_e, level, msg, line, sourceId) => {
    const tag = ['VERBOSE', 'INFO', 'WARNING', 'ERROR'][level] ?? level;
    console.log(`[renderer ${tag}] ${msg} (${sourceId}:${line})`);
  });
});

ipcMain.handle('get-usage', async () => poller.getLastResults());
ipcMain.handle('refresh-now', async () => poller.pollNow());

app.on('window-all-closed', () => {});
