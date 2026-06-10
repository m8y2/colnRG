#!/bin/bash
set -e

echo "=== 1. CSP: add five.epicollect.net to img-src ==="
cp security-headers.conf /etc/nginx/security-headers.conf

echo "=== 2. DB permissions ==="
chmod 640 /opt/coln-dashboard/backend/dashboard.db
ls -la /opt/coln-dashboard/backend/dashboard.db

echo "=== 3. FRONTEND_ORIGIN ==="
if ! grep -q "FRONTEND_ORIGIN" /etc/environment; then
  echo 'FRONTEND_ORIGIN=https://www.colnrg.app' >> /etc/environment
fi
grep FRONTEND_ORIGIN /etc/environment

echo "=== 4. Systemd hardening ==="
cat > /etc/systemd/system/coln-api.service << 'UNIT'
[Unit]
Description=Coln River Guardians Dashboard API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/coln-dashboard/backend
EnvironmentFile=/etc/environment
Environment=PATH=/opt/coln-dashboard/backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/coln-dashboard/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1

Restart=always
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60
LimitNOFILE=65536
MemoryMax=256M

# Security hardening
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true
PrivateDevices=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
SystemCallArchitectures=native
ProtectClock=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=/opt/coln-dashboard/backend

[Install]
WantedBy=multi-user.target
UNIT

# Also harden the sync service
cat > /etc/systemd/system/coln-sync.service << 'UNIT2'
[Unit]
Description=Coln River Guardians EpiCollect sync (one-shot)

[Service]
Type=oneshot
User=www-data
Group=www-data
WorkingDirectory=/opt/coln-dashboard/backend
Environment=PATH=/opt/coln-dashboard/backend/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/coln-dashboard/backend/venv/bin/python /opt/coln-dashboard/backend/sync_runner.py

PrivateTmp=true
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true
PrivateDevices=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=
ReadWritePaths=/opt/coln-dashboard/backend
UNIT2

systemctl daemon-reload

echo "=== 5. DB backup script + cron ==="
mkdir -p /opt/coln-dashboard/backups
cat > /opt/coln-dashboard/backup.sh << 'BACKUP'
#!/bin/bash
SRC=/opt/coln-dashboard/backend/dashboard.db
DST=/opt/coln-dashboard/backups
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
cp "$SRC" "$DST/$TIMESTAMP.db"
find "$DST" -name "*.db" -mtime +30 -delete
BACKUP
chmod +x /opt/coln-dashboard/backup.sh

# Add cron: every 6 hours
(crontab -l 2>/dev/null | grep -v backup.sh; echo "0 */6 * * * /opt/coln-dashboard/backup.sh") | crontab -
echo "Cron installed:"
crontab -l

echo "=== 6. Remove ModSecurity CRS ==="
rm -f /etc/nginx/modsecurity-crs.conf
echo "Removed"

echo "=== 7. Add fail2ban jail for scanners ==="
# Change injection returns to 403 (so they're logged)
cat > /etc/nginx/injection-headers.conf << 'INJ'
# Lightweight exploit-pattern blocking
if ($query_string ~* "(union.*select|select.*from|insert.*into|drop.*table|delete.*from|update.*set|create.*table|alter.*table|truncate|exec.*xp_cmdshell|exec.*master|sleep\(|benchmark\(|pg_sleep)") { return 403; }
if ($query_string ~* "(%3Cscript|<script|%3Ciframe|<iframe|%3Cobject|<object|%3Cembed|<embed|onerror=|onclick=|onmouseover=)") { return 403; }
if ($query_string ~* "(base64_decode|eval\s*\(|system\s*\(|exec\s*\(|passthru\s*\(|shell_exec\s*\(|popen\s*\(|phpinfo\(\)|var_dump\s*\()") { return 403; }
if ($request_uri ~* "\.\./|%2e%2e/|%252e%252e/") { return 403; }
INJ

# Create fail2ban filter
cat > /etc/fail2ban/filter.d/nginx-exploit.conf << 'FILTER'
[Definition]
failregex = ^<HOST> -.*" (GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH) .*" 403 .*$
ignoreregex =
FILTER

# Add jail
if ! grep -q "nginx-exploit" /etc/fail2ban/jail.local 2>/dev/null; then
cat >> /etc/fail2ban/jail.local << 'JAIL'
[nginx-exploit]
enabled = true
port = http,https
filter = nginx-exploit
logpath = /var/log/nginx/access.log
maxretry = 5
bantime = 604800
findtime = 86400
JAIL
fi

fail2ban-client reload

echo "=== 8. Restart nginx & API ==="
nginx -t && systemctl reload nginx
systemctl daemon-reload
systemctl restart coln-api.service

echo "=== 9. Restart stale services ==="
systemctl restart dbus.service 2>/dev/null || true
systemctl restart systemd-logind.service 2>/dev/null || true
systemctl restart unattended-upgrades.service 2>/dev/null || true

echo "=== DONE ==="
