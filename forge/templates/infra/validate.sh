#!/usr/bin/env bash
set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}"
BACKEND_URL="${BACKEND_URL:-http://localhost:5000}"

MUTED='\033[0;2m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e ""
echo -e "  ${MUTED}Waiting for services...${NC}"
echo -e ""

# Wait for Keycloak (check realm endpoint)
until curl -sf "${KEYCLOAK_URL}/realms/master" > /dev/null 2>&1; do sleep 2; done
echo -e "  ${GREEN}[ok]${NC} Keycloak ready"

# Wait for frontend
until curl -sf "${FRONTEND_URL}" > /dev/null 2>&1; do sleep 2; done
echo -e "  ${GREEN}[ok]${NC} Frontend ready"

# Wait for backend health
until curl -sf "${BACKEND_URL}/api/v1/health/live" > /dev/null 2>&1; do sleep 2; done
echo -e "  ${GREEN}[ok]${NC} Backend ready"

E2E_DIR=$(find . -maxdepth 1 -name '*-e2e' -type d | head -1)
if [ -z "$E2E_DIR" ]; then
  echo -e "  ${MUTED}No E2E directory found, skipping tests${NC}"
  exit 0
fi

echo -e ""
echo -e "  ${MUTED}Installing test dependencies...${NC}"
cd "$E2E_DIR/e2e-platform" && npm ci > /dev/null 2>&1
npx playwright install chromium > /dev/null 2>&1
cd ..

echo -e ""
echo -e "  ${MUTED}Running E2E auth validation...${NC}"
echo -e ""

BASE_URL="${FRONTEND_URL}" KEYCLOAK_URL="${KEYCLOAK_URL}" \
  npx playwright test tests/auth.spec.ts

echo -e ""
echo -e "  ${GREEN}Validation complete.${NC}"
echo -e ""
