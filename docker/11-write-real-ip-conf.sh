#!/bin/sh
# Decides what a peer is allowed to tell this sidecar about the original client: its
# address via REAL_IP_HEADER, and its scheme via X-Forwarded-Proto.
#
# geo keys on $realip_remote_addr rather than $remote_addr because real_ip has already
# rewritten the latter to the address under test.
set -eu

conf=/etc/nginx/conf.d/real-ip.conf
trusted_list=$(echo "${REAL_IP_FROM:-}" | tr ',' ' ')

{
    echo 'geo $realip_remote_addr $real_ip_trusted {'
    echo '    default 0;'
    for trusted in $trusted_list; do
        echo "    $trusted 1;"
    done
    echo '}'
    echo
    echo 'map $real_ip_trusted$http_x_forwarded_proto $forwarded_proto {'
    echo '    default $scheme;'
    echo '    "1https" https;'
    echo '    "1http" http;'
    echo '}'
    echo
    for trusted in $trusted_list; do
        echo "set_real_ip_from $trusted;"
    done
    echo "real_ip_header ${REAL_IP_HEADER:-X-Real-IP};"
} >"$conf"
