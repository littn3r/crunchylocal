// Chromium runs as a hidden local helper. The Crunchyroll page has no Node access.
const { app, BrowserWindow, session } = require('electron');
const readline = require('readline');
const crypto = require('crypto');

if (process.env.CRUNCHY_LOCAL_USER_DATA) app.setPath('userData', process.env.CRUNCHY_LOCAL_USER_DATA);
app.setName('Crunchy Local Background');
app.on('window-all-closed', () => {});

let window;
let queue = Promise.resolve();
let activePartition = '';

async function handle(job) {
  if (!job || typeof job.id !== 'string' || !job.cookie || !job.script || !job.options) {
    throw new Error('Некорректный запрос к скрытому браузеру.');
  }
  const partition = 'crunchy-local-' + crypto.createHash('sha256').update(String(job.options.deviceId)).digest('hex').slice(0, 24);
  const browserSession = session.fromPartition(partition);
  if (job.cookie) await browserSession.cookies.set({
    url: 'https://www.crunchyroll.com/', name: 'etp_rt', value: job.cookie,
    domain: '.crunchyroll.com', path: '/', secure: true, httpOnly: true,
  });
  if (window && !window.isDestroyed() && activePartition !== partition) {
    window.destroy();
    window = null;
  }
  if (!window || window.isDestroyed()) {
    activePartition = partition;
    window = new BrowserWindow({
      show: false, width: 820, height: 560, paintWhenInitiallyHidden: true,
      webPreferences: {
        partition, backgroundThrottling: true, contextIsolation: true,
        nodeIntegration: false, sandbox: true,
      },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.setUserAgent(window.webContents.getUserAgent().replace(/ Electron\/[^ ]+/, ''));
  }
  let timer;
  try { return await Promise.race([
    (async () => {
      if (!window.webContents.getURL().startsWith('https://www.crunchyroll.com/')) {
        await window.loadURL('https://www.crunchyroll.com/');
      }
      return window.webContents.executeJavaScript(`(${job.script})(${JSON.stringify(job.options)})`, true);
    })(),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Crunchyroll request timed out.')), 35000); }),
  ]); } finally { clearTimeout(timer); }
}

// User-controlled official sign-in, streamed to their browser. Nothing is saved to disk.
const logins = new Map();
function trustedLoginURL(url) {
  try { const u = new URL(url); return u.protocol === 'https:' && (u.hostname === 'crunchyroll.com' || u.hostname.endsWith('.crunchyroll.com')); }
  catch { return false; }
}
async function remoteLogin(job) {
  const now = Date.now();
  for (const [id, entry] of logins) {
    if (now > entry.expires || entry.window.isDestroyed()) {
      if (!entry.window.isDestroyed()) entry.window.destroy();
      logins.delete(id);
    }
  }
  let entry = logins.get(job.owner);
  if (job.action === 'login_cancel') {
    if (entry) { entry.window.destroy(); logins.delete(job.owner); }
    return {status: 'closed'};
  }
  if (job.action === 'login_start') {
    if (entry) { entry.window.destroy(); logins.delete(job.owner); }
    if (logins.size >= 3) throw Error('Сейчас открыты другие окна входа. Попробуйте через несколько минут.');
    const partition = 'login-' + crypto.randomUUID();
    const browserSession = session.fromPartition(partition);
    const loginWindow = new BrowserWindow({show:false,width:390,height:680,useContentSize:true,paintWhenInitiallyHidden:true,
      webPreferences:{partition,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false,sandbox:true}});
    loginWindow.webContents.setWindowOpenHandler(() => ({action:'deny'}));
    loginWindow.webContents.on('will-navigate', (event, url) => { if (!trustedLoginURL(url)) event.preventDefault(); });
    loginWindow.webContents.on('will-redirect', (event, url) => { if (!trustedLoginURL(url)) event.preventDefault(); });
    entry = {window:loginWindow,session:browserSession,created:now,expires:now+300000,error:''};
    logins.set(job.owner,entry);
    // Allow the UI to poll even while the official login page is loading.
    loginWindow.loadURL('https://www.crunchyroll.com/login').catch(() => {entry.error='Не удалось загрузить официальный вход Crunchyroll.';});
    return {status:'waiting'};
  }
  if (!entry) throw Error('Время входа истекло. Откройте окно входа заново.');
  const web = entry.window.webContents;
  const action = job.input || {};
  if (job.action === 'login_input') {
    if (action.type === 'click') {
      const x = Math.max(0,Math.min(389,Math.round(Number(action.x)||0)));
      const y = Math.max(0,Math.min(679,Math.round(Number(action.y)||0)));
      web.sendInputEvent({type:'mouseDown',x,y,button:'left',clickCount:1});
      web.sendInputEvent({type:'mouseUp',x,y,button:'left',clickCount:1});
    } else if (action.type === 'text' && typeof action.text === 'string' && action.text.length <= 1024) {
      web.insertText(action.text);
    } else if (action.type === 'credentials') {
      if (typeof action.email !== 'string' || typeof action.password !== 'string' ||
          !action.email || action.email.length > 320 || !action.password || action.password.length > 1024 ||
          !trustedLoginURL(web.getURL())) throw Error('Некорректные данные формы входа.');
      const filled = await web.executeJavaScript(`(() => {
        const values = ${JSON.stringify({email:action.email,password:action.password})};
        const visible = element => element && element.getClientRects().length && !element.disabled;
        const inputs = [...document.querySelectorAll('input')].filter(visible);
        const password = inputs.find(input => input.type === 'password');
        const email = inputs.find(input => input.type === 'email' || input.autocomplete === 'username' || /email/i.test(input.name+' '+input.id))
          || inputs.find(input => input.type === 'text');
        if (!email || !password) return false;
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
        for (const [input,value] of [[email,values.email],[password,values.password]]) {
          input.focus();setter.call(input,value);
          input.dispatchEvent(new Event('input',{bubbles:true}));
          input.dispatchEvent(new Event('change',{bubbles:true}));input.blur();
        }
        return true;
      })()`);
      if (!filled) throw Error('Официальная страница пока не готова. Откройте окно проверки и дождитесь загрузки.');
      // Run in a separate task so controlled inputs can render their new state.
      const submitted = await web.executeJavaScript(`(() => {
        const password = [...document.querySelectorAll('input[type=password]')].find(e=>e.getClientRects().length);
        const form = password?.closest('form');
        const scope = form || document;
        const button = [...scope.querySelectorAll('button,input[type=submit]')].find(e =>
          e.getClientRects().length && !e.disabled && (e.type==='submit' || /^(log\\s*in|sign\\s*in)$/i.test(e.textContent.trim())));
        if (!button) return false;
        button.click();return true;
      })()`);
      if (!submitted) throw Error('Кнопка входа недоступна. Откройте окно проверки.');
      entry.submitted = Date.now();
    } else if (action.type === 'key' && ['Backspace','Enter','Tab','ArrowLeft','ArrowRight'].includes(action.key)) {
      web.sendInputEvent({type:'keyDown',keyCode:action.key});web.sendInputEvent({type:'keyUp',keyCode:action.key});
    } else if (action.type === 'scroll') {
      web.sendInputEvent({type:'mouseWheel',x:195,y:340,deltaX:0,deltaY:Math.max(-500,Math.min(500,Number(action.delta)||0))});
    } else throw Error('Неподдерживаемое действие входа.');
    return {status:'waiting'};
  }
  const cookies = await entry.session.cookies.get({url:'https://www.crunchyroll.com/',name:'etp_rt'});
  if (cookies[0]?.value) {
    const cookie = cookies[0].value;
    entry.window.destroy(); logins.delete(job.owner);
    return {status:'connected',cookie};
  }
  if (entry.error) throw Error(entry.error);
  const needsInteraction = await web.executeJavaScript(`(() => {
    if (/just a moment|security verification/i.test(document.title)) return true;
    return [...document.querySelectorAll('iframe')].some(e => e.getClientRects().length &&
      /challenges.cloudflare|captcha/i.test(e.src+' '+e.title));
  })()`);
  const delayed = entry.submitted && Date.now() - entry.submitted > 12000;
  if (!job.input?.show) return {status:needsInteraction || delayed ? 'interaction' : 'waiting'};
  let image;
  try { image = await web.capturePage(); }
  catch (error) {
    // Chromium may not have a compositor frame immediately after loadURL.
    if (Date.now() - entry.created < 10000) return {status:'waiting'};
    throw error;
  }
  if (image.isEmpty()) return {status:'waiting'};
  return {status:needsInteraction || delayed ? 'interaction' : 'waiting',image:image.toDataURL(),width:390,height:680};
}
setInterval(() => {
  for (const [id, entry] of logins) {
    if (Date.now() > entry.expires) {if (!entry.window.isDestroyed()) entry.window.destroy();logins.delete(id);}
  }
},15000).unref();

app.whenReady().then(() => {
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  lines.on('line', (line) => {
    queue = queue.then(async () => {
      let id = '';
      try {
        const job = JSON.parse(line);
        id = job.id || '';
        const result = job.action?.startsWith('login_') ? await remoteLogin(job) : await handle(job);
        process.stdout.write(JSON.stringify({ id, result }) + '\n');
      } catch (error) {
        process.stdout.write(JSON.stringify({ id, error: String(error.message || error).slice(0, 240) }) + '\n');
      }
    });
  });
  lines.on('close', () => app.quit());
}).catch((error) => {
  process.stdout.write(JSON.stringify({ error: String(error) }) + '\n');
  app.quit();
});
