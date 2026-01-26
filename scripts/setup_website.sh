#!/bin/bash
# Script to add AIChat showcase to leeostadi.com
# Run this script on your local machine

SERVER="ustad@100.110.106.67"

echo "=== Connecting to leeostadi.com server ==="

# First, let's explore the server
ssh $SERVER << 'ENDSSH'
echo "=== Server Info ==="
hostname
echo ""

echo "=== Finding web root ==="
# Check common web directories
for dir in /var/www/html /var/www /home/*/public_html /srv/www ~/www ~/public_html; do
    if [ -d "$dir" ]; then
        echo "Found: $dir"
        ls -la "$dir" | head -10
    fi
done

echo ""
echo "=== Checking web server ==="
which nginx && echo "Nginx installed"
which apache2 && echo "Apache installed"
systemctl status nginx 2>/dev/null | head -5
systemctl status apache2 2>/dev/null | head -5

echo ""
echo "=== Finding existing HTML files ==="
find /var/www -name "*.html" 2>/dev/null | head -10
find ~ -name "index.html" 2>/dev/null | head -5
ENDSSH

echo ""
echo "=== Done exploring. Run Part 2 to create the page ==="
