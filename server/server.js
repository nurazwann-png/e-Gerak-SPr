// Backend + static file server for e-Gerak SPR - one process serves both the
// app (index.html, manifest, icons) and the shared /api/movements data, so
// staff on other devices just need one URL, e.g. http://<this-pc's-LAN-IP>:3001
// (find that IP with `ipconfig` on Windows), rather than running two servers.
//
// Uses only Node's built-in http + fs + node:sqlite modules - no npm install needed.
// Run with: node server/server.js  (requires Node 22.5+)
//
// Local/LAN use: binds to all interfaces on port 3001, DB file lives next to this
// script. Make sure Windows Firewall allows inbound connections on this port so
// other devices on the same Wi-Fi/LAN can reach it.
//
// Deployed (e.g. Railway): set the PORT env var (the host usually sets this for you)
// and DB_PATH to a path inside a mounted persistent volume, e.g. /data/movements.db -
// without a persistent volume, the database resets on every redeploy/restart.

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');

const PORT = process.env.PORT || 3001;
const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'movements.db');
const db = new DatabaseSync(DB_PATH);

// The frontend files (index.html, manifest.json, sw.js, icons/) live one
// level up from this script, at the project root.
const STATIC_ROOT = path.join(__dirname, '..');
const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

function serveStatic(req, res, pathname) {
  const relativePath = pathname === '/' ? '/index.html' : pathname;
  const fullPath = path.join(STATIC_ROOT, relativePath);

  // Guard against path traversal (e.g. "/../server/server.js")
  if (!fullPath.startsWith(STATIC_ROOT)) {
    res.writeHead(403, { 'Content-Type': 'text/plain' });
    res.end('Forbidden');
    return;
  }

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not found');
      return;
    }
    const contentType = MIME_TYPES[path.extname(fullPath)] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

db.exec(`
  CREATE TABLE IF NOT EXISTS movements (
    id TEXT PRIMARY KEY,
    nama TEXT NOT NULL,
    tarikh TEXT NOT NULL,
    destinasi TEXT NOT NULL,
    tujuan TEXT NOT NULL,
    nota TEXT,
    submittedBy TEXT NOT NULL
  )
`);

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json', ...CORS_HEADERS });
  res.end(JSON.stringify(data));
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => { raw += chunk; });
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (req.method === 'OPTIONS') {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  try {
    // GET /api/movements - list every record (shared across all devices)
    if (url.pathname === '/api/movements' && req.method === 'GET') {
      const rows = db.prepare('SELECT * FROM movements ORDER BY tarikh DESC').all();
      sendJSON(res, 200, rows);
      return;
    }

    // POST /api/movements - create a new record
    if (url.pathname === '/api/movements' && req.method === 'POST') {
      const body = await readJsonBody(req);
      const { id, nama, tarikh, destinasi, tujuan, nota, submittedBy } = body;

      if (!id || !nama || !tarikh || !destinasi || !tujuan || !submittedBy) {
        sendJSON(res, 400, { error: 'Missing required fields' });
        return;
      }

      db.prepare(`
        INSERT INTO movements (id, nama, tarikh, destinasi, tujuan, nota, submittedBy)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).run(id, nama, tarikh, destinasi, tujuan, nota || '', submittedBy);

      sendJSON(res, 201, { ok: true });
      return;
    }

    // DELETE /api/movements - clear everything (used by "Tetap Semula Orbit")
    if (url.pathname === '/api/movements' && req.method === 'DELETE') {
      db.prepare('DELETE FROM movements').run();
      sendJSON(res, 200, { ok: true });
      return;
    }

    // DELETE /api/movements/:id?email=... - delete one record, server-enforced
    // to only the person who submitted it (real enforcement, unlike the old
    // client-only check which anyone could bypass via devtools).
    if (url.pathname.startsWith('/api/movements/') && req.method === 'DELETE') {
      const id = decodeURIComponent(url.pathname.split('/').pop());
      const requesterEmail = url.searchParams.get('email');

      const record = db.prepare('SELECT * FROM movements WHERE id = ?').get(id);
      if (!record) {
        sendJSON(res, 404, { error: 'Record not found' });
        return;
      }
      if (!requesterEmail || record.submittedBy !== requesterEmail) {
        sendJSON(res, 403, { error: 'You may only delete your own records' });
        return;
      }

      db.prepare('DELETE FROM movements WHERE id = ?').run(id);
      sendJSON(res, 200, { ok: true });
      return;
    }

    // Anything else (GET requests for the page/assets) - serve the frontend files
    if (!url.pathname.startsWith('/api/') && (req.method === 'GET' || req.method === 'HEAD')) {
      serveStatic(req, res, url.pathname);
      return;
    }

    sendJSON(res, 404, { error: 'Not found' });
  } catch (err) {
    console.error(err);
    sendJSON(res, 500, { error: 'Server error' });
  }
});

server.listen(PORT, () => {
  console.log(`e-Gerak SPR backend listening on port ${PORT}`);
});
