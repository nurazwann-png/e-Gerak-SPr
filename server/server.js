// Local backend for e-Gerak SPR - lets multiple devices/browsers share the
// same movement records instead of each keeping its own localStorage copy.
//
// Uses only Node's built-in http + node:sqlite modules - no npm install needed.
// Run with: node server/server.js  (requires Node 22.5+)
//
// NOTE: this binds to localhost only, so it's reachable from THIS machine
// only (matching "test it on my machine" scope). To let other devices on the
// network reach it, this would need to listen on 0.0.0.0 and the frontend's
// API_BASE would need to point at this machine's LAN IP instead of localhost.

const http = require('node:http');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');

const PORT = 3001;
const db = new DatabaseSync(path.join(__dirname, 'movements.db'));

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

    sendJSON(res, 404, { error: 'Not found' });
  } catch (err) {
    console.error(err);
    sendJSON(res, 500, { error: 'Server error' });
  }
});

server.listen(PORT, 'localhost', () => {
  console.log(`e-Gerak SPR backend listening on http://localhost:${PORT}`);
});
