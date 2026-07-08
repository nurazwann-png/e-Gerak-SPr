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

// Shared PIN that unlocks the Admin page and every admin-only API call below.
// Override via env var for a real deployment if you don't want the default in source.
const ADMIN_PIN = process.env.ADMIN_PIN || 'admin1234SPr';

// Same domain rule as the frontend's ALLOWED_EMAIL_REGEX - checked again here
// so self-registration can't be bypassed by calling the API directly.
const ALLOWED_EMAIL_DOMAIN = /^[^@]+@moe\.gov\.my$/;

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

// Staff roster - only e-mails an admin has added here may sign in. This is
// what gives "delete a user" real meaning (it revokes their ability to log
// in), rather than just being a display list.
db.exec(`
  CREATE TABLE IF NOT EXISTS staff (
    email TEXT PRIMARY KEY,
    nama TEXT NOT NULL,
    jawatan TEXT NOT NULL,
    addedAt TEXT NOT NULL
  )
`);

// Jawatan options shown in the identify form's dropdown - admin-editable
// instead of hardcoded in the frontend.
db.exec(`
  CREATE TABLE IF NOT EXISTS jawatan_list (
    jawatan TEXT PRIMARY KEY
  )
`);
const jawatanCount = db.prepare('SELECT COUNT(*) AS n FROM jawatan_list').get().n;
if (jawatanCount === 0) {
  const seedJawatan = db.prepare('INSERT INTO jawatan_list (jawatan) VALUES (?)');
  seedJawatan.run('Penolong Pegawai Pendidikan');
  seedJawatan.run('Timbalan Sektor Perancangan');
}

// Simple audit trail for admin actions (record deletions via admin override,
// and staff/jawatan roster changes) - deleted records otherwise vanish with
// no trace of who removed them or when.
db.exec(`
  CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    performedAt TEXT NOT NULL
  )
`);

function generateId() {
  return 'id_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 9);
}

function logAudit(action, detail) {
  db.prepare('INSERT INTO audit_log (id, action, detail, performedAt) VALUES (?, ?, ?, ?)')
    .run(generateId(), action, detail, new Date().toISOString());
}

function isStaffEmail(email) {
  return !!db.prepare('SELECT 1 FROM staff WHERE email = ?').get(email);
}

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

    // POST /api/movements - create a new record. Only e-mails on the staff
    // roster may submit, mirroring the login gate (closes the gap where
    // someone could otherwise POST directly bypassing the identify form).
    if (url.pathname === '/api/movements' && req.method === 'POST') {
      const body = await readJsonBody(req);
      const { id, nama, tarikh, destinasi, tujuan, nota, submittedBy } = body;

      if (!id || !nama || !tarikh || !destinasi || !tujuan || !submittedBy) {
        sendJSON(res, 400, { error: 'Missing required fields' });
        return;
      }
      if (!isStaffEmail(submittedBy)) {
        sendJSON(res, 403, { error: 'This e-mail is not on the staff roster' });
        return;
      }

      db.prepare(`
        INSERT INTO movements (id, nama, tarikh, destinasi, tujuan, nota, submittedBy)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).run(id, nama, tarikh, destinasi, tujuan, nota || '', submittedBy);

      sendJSON(res, 201, { ok: true });
      return;
    }

    // DELETE /api/movements - clear everything (used by "Tetap Semula Orbit",
    // still open to any signed-in user, unchanged from before)
    if (url.pathname === '/api/movements' && req.method === 'DELETE') {
      db.prepare('DELETE FROM movements').run();
      sendJSON(res, 200, { ok: true });
      return;
    }

    // DELETE /api/movements/:id?email=...   - owner deletes their own record
    // DELETE /api/movements/:id?pin=...     - admin deletes ANY record
    if (url.pathname.startsWith('/api/movements/') && req.method === 'DELETE') {
      const id = decodeURIComponent(url.pathname.split('/').pop());
      const requesterEmail = url.searchParams.get('email');
      const pin = url.searchParams.get('pin');

      const record = db.prepare('SELECT * FROM movements WHERE id = ?').get(id);
      if (!record) {
        sendJSON(res, 404, { error: 'Record not found' });
        return;
      }

      const isOwner = requesterEmail && record.submittedBy === requesterEmail;
      const isAdmin = pin && pin === ADMIN_PIN;

      if (!isOwner && !isAdmin) {
        sendJSON(res, 403, { error: 'You may only delete your own records' });
        return;
      }

      db.prepare('DELETE FROM movements WHERE id = ?').run(id);
      if (isAdmin && !isOwner) {
        logAudit('delete_record', `Admin removed a record for ${record.nama} (${record.tarikh}, ${record.destinasi}) submitted by ${record.submittedBy}`);
      }
      sendJSON(res, 200, { ok: true });
      return;
    }

    // GET /api/jawatan - public list of position options for the identify form
    if (url.pathname === '/api/jawatan' && req.method === 'GET') {
      const rows = db.prepare('SELECT jawatan FROM jawatan_list ORDER BY jawatan ASC').all();
      sendJSON(res, 200, rows.map((r) => r.jawatan));
      return;
    }

    // GET /api/staff/check?email=... - public yes/no roster lookup used by the login gate
    if (url.pathname === '/api/staff/check' && req.method === 'GET') {
      const email = (url.searchParams.get('email') || '').toLowerCase();
      sendJSON(res, 200, { allowed: isStaffEmail(email) });
      return;
    }

    // POST /api/staff/register {email, nama, jawatan} - public self-registration,
    // used the first time someone signs in. No PIN needed - anyone with a valid
    // MOE e-mail can add themselves. Admins can still add/remove staff directly
    // from the Admin panel regardless of this.
    if (url.pathname === '/api/staff/register' && req.method === 'POST') {
      const body = await readJsonBody(req);
      const email = (body.email || '').trim().toLowerCase();
      const nama = (body.nama || '').trim();
      const jawatan = body.jawatan || '';

      if (!ALLOWED_EMAIL_DOMAIN.test(email) || !nama || !jawatan) {
        sendJSON(res, 400, { error: 'Invalid registration details' });
        return;
      }

      db.prepare('INSERT OR REPLACE INTO staff (email, nama, jawatan, addedAt) VALUES (?, ?, ?, ?)')
        .run(email, nama, jawatan, new Date().toISOString());
      logAudit('self_register', `${nama} (${email}, ${jawatan}) registered themselves`);
      sendJSON(res, 201, { ok: true });
      return;
    }

    // ---- Everything below requires the admin PIN ----

    // POST /api/admin/verify {pin} - used to unlock the Admin tab in the UI
    if (url.pathname === '/api/admin/verify' && req.method === 'POST') {
      const body = await readJsonBody(req);
      sendJSON(res, 200, { ok: body.pin === ADMIN_PIN });
      return;
    }

    if (url.pathname.startsWith('/api/admin/')) {
      // Every remaining admin route needs a valid pin, sent as ?pin=... on
      // GET/DELETE or in the JSON body on POST.
      const bodyForWrite = (req.method === 'POST') ? await readJsonBody(req) : null;
      const pin = url.searchParams.get('pin') || (bodyForWrite && bodyForWrite.pin);

      if (pin !== ADMIN_PIN) {
        sendJSON(res, 403, { error: 'Invalid admin PIN' });
        return;
      }

      // GET /api/admin/staff - list the roster
      if (url.pathname === '/api/admin/staff' && req.method === 'GET') {
        const rows = db.prepare('SELECT * FROM staff ORDER BY addedAt DESC').all();
        sendJSON(res, 200, rows);
        return;
      }

      // POST /api/admin/staff {pin, email, nama, jawatan} - add a staff member
      if (url.pathname === '/api/admin/staff' && req.method === 'POST') {
        const { email, nama, jawatan } = bodyForWrite;
        if (!email || !nama || !jawatan) {
          sendJSON(res, 400, { error: 'Missing required fields' });
          return;
        }
        const normalizedEmail = email.trim().toLowerCase();
        db.prepare('INSERT OR REPLACE INTO staff (email, nama, jawatan, addedAt) VALUES (?, ?, ?, ?)')
          .run(normalizedEmail, nama.trim(), jawatan, new Date().toISOString());
        logAudit('add_staff', `Added/updated staff ${nama.trim()} (${normalizedEmail}, ${jawatan})`);
        sendJSON(res, 201, { ok: true });
        return;
      }

      // DELETE /api/admin/staff/:email?pin=... - revoke a staff member's access
      if (url.pathname.startsWith('/api/admin/staff/') && req.method === 'DELETE') {
        const email = decodeURIComponent(url.pathname.split('/').pop());
        const staffMember = db.prepare('SELECT * FROM staff WHERE email = ?').get(email);
        db.prepare('DELETE FROM staff WHERE email = ?').run(email);
        if (staffMember) {
          logAudit('delete_staff', `Removed staff ${staffMember.nama} (${email})`);
        }
        sendJSON(res, 200, { ok: true });
        return;
      }

      // POST /api/admin/jawatan {pin, jawatan} - add a position option
      if (url.pathname === '/api/admin/jawatan' && req.method === 'POST') {
        const { jawatan } = bodyForWrite;
        if (!jawatan || !jawatan.trim()) {
          sendJSON(res, 400, { error: 'Missing jawatan value' });
          return;
        }
        db.prepare('INSERT OR IGNORE INTO jawatan_list (jawatan) VALUES (?)').run(jawatan.trim());
        logAudit('add_jawatan', `Added jawatan option "${jawatan.trim()}"`);
        sendJSON(res, 201, { ok: true });
        return;
      }

      // DELETE /api/admin/jawatan/:value?pin=... - remove a position option
      if (url.pathname.startsWith('/api/admin/jawatan/') && req.method === 'DELETE') {
        const value = decodeURIComponent(url.pathname.split('/').pop());
        db.prepare('DELETE FROM jawatan_list WHERE jawatan = ?').run(value);
        logAudit('delete_jawatan', `Removed jawatan option "${value}"`);
        sendJSON(res, 200, { ok: true });
        return;
      }

      // GET /api/admin/audit - recent admin activity
      if (url.pathname === '/api/admin/audit' && req.method === 'GET') {
        const rows = db.prepare('SELECT * FROM audit_log ORDER BY performedAt DESC LIMIT 200').all();
        sendJSON(res, 200, rows);
        return;
      }

      sendJSON(res, 404, { error: 'Not found' });
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
