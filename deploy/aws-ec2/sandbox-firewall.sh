#!/usr/bin/env bash
# Firewall for the sandbox that runs a repository's own tests (run as root;
# testsphere-sandbox-firewall.service re-applies it at every boot).
#
# Sandbox containers sit on the Docker bridge ts-sandbox0 (network
# "testsphere-sandbox").  Installing dependencies needs the internet, but
# nothing else: these rules drop what they send to
#   - the instance metadata service (169.254.0.0/16: where the instance
#     role's credentials come from),
#   - private and shared address ranges (the VPC, other containers),
#   - this host itself (published ports, the Docker API, anything listening).
# The tests themselves run with no network at all.
#
# The worker checks before every sandbox run that the metadata service is
# unreachable from this network, and refuses to run repository code if not.
set -euo pipefail

BRIDGE=ts-sandbox0
BLOCKED="169.254.0.0/16 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10"

rule() {  # rule CHAIN ARGS...: insert once (idempotent)
  local chain=$1; shift
  iptables -C "$chain" "$@" 2>/dev/null || iptables -I "$chain" "$@"
}

# DOCKER-USER exists once Docker has started; it is evaluated before Docker's own rules
iptables -L DOCKER-USER -n >/dev/null 2>&1 || iptables -N DOCKER-USER
for net in $BLOCKED; do
  rule DOCKER-USER -i "$BRIDGE" -d "$net" -j DROP
done
# Traffic to the host's own addresses goes through INPUT, not FORWARD
rule INPUT -i "$BRIDGE" -j DROP

echo "Sandbox firewall on $BRIDGE: dropped to $BLOCKED and to this host"
