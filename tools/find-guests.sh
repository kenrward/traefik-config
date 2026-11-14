#!/usr/bin/env bash
# Read-only inventory of Proxmox guests: id, type, name, MAC, current IPv4, and
# which of the Traefik backend ports each guest is listening on.
# Run on the Proxmox host:  ssh root@192.168.86.21 'bash -s' < tools/find-guests.sh
# Changes nothing. No restarts.
set -u
PORTS="5000 5001 5002 5003 10086 80 8123 11434"

probe() {  # $1=ip -> list of open ports among $PORTS
  local ip=$1 open=""
  [ -z "$ip" ] && { echo "-"; return; }
  for p in $PORTS; do
    timeout 1 bash -c "</dev/tcp/$ip/$p" 2>/dev/null && open="$open$p,"
  done
  echo "${open%,}"
}

ip_for_mac() {  # fallback: look the MAC up in the host neighbor table
  ip -4 neigh show | awk -v m="$(echo "$1" | tr 'A-Z' 'a-z')" 'tolower($5)==m {print $1; exit}'
}

printf "%-5s %-4s %-24s %-19s %-16s %s\n" ID TYPE NAME MAC IPV4 OPEN_PORTS
for id in $(pct list | awk 'NR>1 && $2=="running" {print $1}'); do
  name=$(pct config "$id" | awk '/^hostname:/ {print $2}')
  mac=$(pct config "$id" | grep -oiE 'hwaddr=[0-9a-f:]{17}' | head -1 | cut -d= -f2)
  ipv4=$(pct exec "$id" -- ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)
  [ -z "$ipv4" ] && ipv4=$(ip_for_mac "$mac")
  printf "%-5s %-4s %-24s %-19s %-16s %s\n" "$id" lxc "$name" "$mac" "${ipv4:--}" "$(probe "$ipv4")"
done
for id in $(qm list | awk 'NR>1 && $3=="running" {print $1}'); do
  name=$(qm config "$id" | awk '/^name:/ {print $2}')
  mac=$(qm config "$id" | grep -oiE '=[0-9a-f:]{17}' | head -1 | tr -d '=')
  ipv4=$(qm guest cmd "$id" network-get-interfaces 2>/dev/null \
        | grep -oE '"ip-address" *: *"[0-9.]+"' | grep -oE '[0-9.]+"$' | tr -d '"' \
        | grep -vE '^(127\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[01]\.)' | head -1)
  [ -z "$ipv4" ] && ipv4=$(ip_for_mac "$mac")
  printf "%-5s %-4s %-24s %-19s %-16s %s\n" "$id" vm "$name" "$mac" "${ipv4:--}" "$(probe "$ipv4")"
done

echo
echo "== Who currently answers on the original backend IPs (non-guests show up here too) =="
for ip in 192.168.86.52 192.168.86.36 192.168.86.58 192.168.86.55 192.168.86.60 192.168.86.61 192.168.86.67 192.168.86.57; do
  ping -c1 -W1 "$ip" >/dev/null 2>&1
  mac=$(ip -4 neigh show "$ip" | awk '{print $5}')
  printf "%-16s mac=%-19s open=%s\n" "$ip" "${mac:--}" "$(probe "$ip")"
done

echo
echo "== Listeners inside each running LXC on the unknown ports (5003, 10086, 80) =="
for id in $(pct list | awk 'NR>1 && $2=="running" {print $1}'); do
  out=$(pct exec "$id" -- sh -c 'ss -ltnp 2>/dev/null | grep -E ":(5003|10086|80)\b"' 2>/dev/null)
  [ -n "$out" ] && { echo "--- CT $id ($(pct config "$id" | awk '/^hostname:/ {print $2}'))"; echo "$out"; }
done
