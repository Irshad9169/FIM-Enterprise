	#!/bin/bash
# =============================================================================
# Frontend Build Troubleshoot & Deploy Script
# Checks, validates, fixes, rebuilds and deploys the React frontend
# in a single run. Ensures the correct bundle (with CSRF fix) is always served.
#
# Usage: sudo bash frontend_build_deploy.sh
# =============================================================================

set -e

FRONTEND_DIR="/usr/local/opt/fim/frontend"
WEB_SRC="/usr/local/opt/fim/web"
WEB_DEST="/opt/fim/web"

PASS=0; FAIL=0; FIXED=0
ISSUES=()

echo "============================================================"
echo " Frontend Build Troubleshoot & Deploy"
echo "============================================================"

# ── Helper functions ──────────────────────────────────────────────
ok()    { echo "   ✅ $*"; PASS=$((PASS+1)); }
fail()  { echo "   ❌ $*"; FAIL=$((FAIL+1)); ISSUES+=("$*"); }
fixed() { echo "   🔧 FIXED: $*"; FIXED=$((FIXED+1)); ISSUES+=("FIXED: $*"); }
warn()  { echo "   ⚠️  $*"; }

# ── Step 1: Pre-flight checks ─────────────────────────────────────
echo ""
echo "▶ Step 1: Pre-flight checks..."

# Node.js
if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    ok "Node.js: $NODE_VER"
else
    fail "Node.js not found — install Node 18+"
    exit 1
fi

# npm
if command -v npm &>/dev/null; then
    NPM_VER=$(npm --version)
    ok "npm: $NPM_VER"
else
    fail "npm not found"
    exit 1
fi

# Frontend source dir
if [ -d "$FRONTEND_DIR" ]; then
    ok "Frontend source: $FRONTEND_DIR"
else
    fail "Frontend source not found: $FRONTEND_DIR"
    exit 1
fi

# Web destination
if [ -d "$WEB_DEST" ]; then
    ok "Web destination: $WEB_DEST"
else
    mkdir -p "$WEB_DEST"
    fixed "Created web destination: $WEB_DEST"
fi

# ── Step 2: Validate source files ────────────────────────────────
echo ""
echo "▶ Step 2: Validating source files..."

cd "$FRONTEND_DIR"

# Check CSRF fix in client.ts
if grep -q "getCsrfToken\|X-CSRF-Token" src/api/client.ts 2>/dev/null; then
    ok "client.ts has CSRF interceptor"
else
    fail "client.ts missing CSRF interceptor"
    ISSUES+=("client.ts needs getCsrfToken() in axios interceptor")
fi

# Check CSRF fix in dashboard.ts
if grep -q "getCsrfToken\|X-CSRF-Token" src/api/dashboard.ts 2>/dev/null; then
    ok "dashboard.ts has CSRF header in apiCall()"
else
    fail "dashboard.ts missing CSRF header — applying fix..."
    node << 'JSEOF'
const fs = require('fs');
const path = 'src/api/dashboard.ts';
let content = fs.readFileSync(path, 'utf8');

if (content.includes('getCsrfToken')) {
    console.log("   Already has getCsrfToken");
    process.exit(0);
}

const idx = content.indexOf('async function apiCall');
if (idx === -1) { console.log("❌ apiCall not found"); process.exit(1); }

const INJECT = `// GAP #13: read CSRF token from cookie
function getCsrfToken(): string {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="))
    ?.split("=")[1] ?? "";
}

`;
content = content.slice(0, idx) + INJECT + content.slice(idx);
content = content.replace(
  `  const token = localStorage.getItem("fim_token");\n  const response = await fetch`,
  `  const token = localStorage.getItem("fim_token");\n  const csrfToken = getCsrfToken();\n  const response = await fetch`
);
content = content.replace(
  `      "Content-Type": "application/json",\n      ...options?.headers,`,
  `      "Content-Type": "application/json",\n      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),\n      ...options?.headers,`
);
fs.writeFileSync(path, content);
console.log("   ✅ getCsrfToken() injected into dashboard.ts");
JSEOF
    fixed "CSRF header added to dashboard.ts"
fi

# Check date-fns
if [ -d "node_modules/date-fns" ]; then
    ok "date-fns installed"
else
    warn "date-fns missing — installing..."
    npm install date-fns --silent
    fixed "date-fns installed"
fi

# Check node_modules exists
if [ -d "node_modules" ]; then
    ok "node_modules present"
else
    warn "node_modules missing — running npm install..."
    npm install --silent
    fixed "npm install completed"
fi

# Check package.json has build script
if grep -q '"build"' package.json 2>/dev/null; then
    BUILD_CMD=$(grep '"build"' package.json | head -1 | sed 's/.*: "//' | sed 's/".*//')
    ok "Build script: $BUILD_CMD"
else
    fail "No build script in package.json"
fi

# ── Step 3: Check for stale/duplicate bundles ─────────────────────
echo ""
echo "▶ Step 3: Checking for stale/duplicate bundles..."

# Check WEB_DEST for multiple JS bundles
JS_COUNT=$(ls "$WEB_DEST/assets/index-"*.js 2>/dev/null | wc -l)
if [ "$JS_COUNT" -gt 1 ]; then
    warn "$JS_COUNT JS bundles found in $WEB_DEST/assets/ — removing old ones"
    # Keep only the newest
    ls -t "$WEB_DEST/assets/index-"*.js 2>/dev/null | tail -n +2 | xargs rm -f
    fixed "Removed $(($JS_COUNT - 1)) old bundle(s)"
elif [ "$JS_COUNT" -eq 1 ]; then
    ok "Single JS bundle in $WEB_DEST/assets/"
else
    warn "No bundles in $WEB_DEST yet — will deploy after build"
fi

# Check if index.html references existing bundle
if [ -f "$WEB_DEST/index.html" ]; then
    REFERENCED=$(grep -o 'index-[^"]*\.js' "$WEB_DEST/index.html" 2>/dev/null || echo "none")
    if [ -f "$WEB_DEST/assets/$REFERENCED" ]; then
        ok "index.html references existing bundle: $REFERENCED"
    else
        warn "index.html references missing bundle: $REFERENCED — will be fixed after rebuild"
    fi
fi

# ── Step 4: Clean build cache ─────────────────────────────────────
echo ""
echo "▶ Step 4: Cleaning build cache..."

if [ -d ".vite" ]; then
    rm -rf .vite
    fixed "Cleared .vite cache"
else
    ok "No .vite cache to clear"
fi

if [ -d "node_modules/.vite" ]; then
    rm -rf node_modules/.vite
    fixed "Cleared node_modules/.vite cache"
else
    ok "No node_modules/.vite cache"
fi

# Clear previous build output
if [ -d "$WEB_SRC" ]; then
    rm -rf "$WEB_SRC"
    fixed "Cleared previous build output: $WEB_SRC"
fi

# ── Step 5: Build ─────────────────────────────────────────────────
echo ""
echo "▶ Step 5: Building frontend..."

BUILD_OUTPUT=$(npm run build 2>&1)
BUILD_EXIT=$?

if [ $BUILD_EXIT -eq 0 ]; then
    BUNDLE=$(ls "$WEB_SRC/assets/index-"*.js 2>/dev/null | head -1)
    BUNDLE_NAME=$(basename "$BUNDLE" 2>/dev/null || echo "unknown")
    BUNDLE_SIZE=$(du -sh "$BUNDLE" 2>/dev/null | cut -f1 || echo "unknown")
    ok "Build succeeded: $BUNDLE_NAME ($BUNDLE_SIZE)"
else
    fail "Build failed — output:"
    echo "$BUILD_OUTPUT" | grep -E "error|Error|warn" | head -20 | sed 's/^/      /'

    # Try to auto-fix common build errors
    if echo "$BUILD_OUTPUT" | grep -q "Cannot find module\|Module not found"; then
        MISSING=$(echo "$BUILD_OUTPUT" | grep -oP "(?<=Cannot find module ')([^']+)" | head -1)
        warn "Missing module: $MISSING — attempting install..."
        npm install "$MISSING" --silent 2>/dev/null && {
            fixed "Installed missing module: $MISSING"
            warn "Re-running build..."
            npm run build 2>&1 | tail -5
        }
    fi
    exit 1
fi

# ── Step 6: Validate build output ────────────────────────────────
echo ""
echo "▶ Step 6: Validating build output..."

# Check CSRF code in built bundle
CSRF_COUNT=$(grep -o "getCsrfToken\|X-CSRF-Token\|csrf_token" \
    "$WEB_SRC/assets/index-"*.js 2>/dev/null | wc -l)
if [ "$CSRF_COUNT" -ge 2 ]; then
    ok "CSRF code confirmed in bundle ($CSRF_COUNT references)"
else
    fail "CSRF code missing from built bundle (found $CSRF_COUNT references)"
    warn "Check src/api/dashboard.ts and src/api/client.ts"
fi

# Confirm index.html references the new bundle
NEW_BUNDLE=$(grep -o 'index-[^"]*\.js' "$WEB_SRC/index.html" 2>/dev/null)
if [ -n "$NEW_BUNDLE" ] && [ -f "$WEB_SRC/assets/$NEW_BUNDLE" ]; then
    ok "index.html references: $NEW_BUNDLE ✅"
else
    fail "index.html bundle reference mismatch"
fi

# ── Step 7: Deploy to Nginx web root ─────────────────────────────
echo ""
echo "▶ Step 7: Deploying to $WEB_DEST..."

# Remove old bundles from destination first
ls "$WEB_DEST/assets/index-"*.js 2>/dev/null | while read old; do
    rm -f "$old"
    echo "   Removed old: $(basename $old)"
done

# Copy new build
cp -rf "$WEB_SRC"/* "$WEB_DEST/"
ok "Deployed to $WEB_DEST"

# Confirm deployed bundle has CSRF
DEPLOYED_BUNDLE=$(ls "$WEB_DEST/assets/index-"*.js 2>/dev/null | head -1)
DEPLOYED_NAME=$(basename "$DEPLOYED_BUNDLE" 2>/dev/null)
DEPLOYED_CSRF=$(grep -o "X-CSRF-Token\|csrf_token" "$DEPLOYED_BUNDLE" 2>/dev/null | wc -l)

if [ "$DEPLOYED_CSRF" -ge 2 ]; then
    ok "Deployed bundle $DEPLOYED_NAME has CSRF ($DEPLOYED_CSRF references)"
else
    fail "Deployed bundle missing CSRF code"
fi

# Confirm index.html in destination references correct bundle
DEST_BUNDLE=$(grep -o 'index-[^"]*\.js' "$WEB_DEST/index.html" 2>/dev/null)
if [ "$DEST_BUNDLE" = "$DEPLOYED_NAME" ]; then
    ok "index.html → $DEST_BUNDLE (matches deployed bundle)"
else
    fail "index.html references $DEST_BUNDLE but deployed bundle is $DEPLOYED_NAME"
fi

# Only one JS bundle should exist
FINAL_JS_COUNT=$(ls "$WEB_DEST/assets/index-"*.js 2>/dev/null | wc -l)
if [ "$FINAL_JS_COUNT" -eq 1 ]; then
    ok "Exactly 1 JS bundle deployed — no stale files"
else
    warn "$FINAL_JS_COUNT bundles in $WEB_DEST/assets/ — removing extras"
    ls -t "$WEB_DEST/assets/index-"*.js | tail -n +2 | xargs rm -f
    fixed "Extra bundles removed"
fi

# ── Step 8: Summary ───────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Frontend Build & Deploy Complete"
echo "============================================================"
echo ""
echo " Results: $PASS checks passed | $FAIL failed | $FIXED auto-fixed"
echo ""
if [ ${#ISSUES[@]} -gt 0 ]; then
    echo " Issues log:"
    for issue in "${ISSUES[@]}"; do
        echo "   • $issue"
    done
    echo ""
fi
echo " Deployed bundle : $DEPLOYED_NAME"
echo " CSRF references : $DEPLOYED_CSRF (must be ≥ 2)"
echo " Web root        : $WEB_DEST"
echo ""
echo " Browser action required after deploy:"
echo "   1. Open DevTools → Network tab → check 'Disable cache'"
echo "   2. Hard refresh: Ctrl+Shift+R"
echo "   3. Verify in Network tab that $DEPLOYED_NAME loads"
echo "   4. Check Application → Cookies for csrf_token after login"
echo ""
if [ $FAIL -eq 0 ]; then
    echo " ✅ All checks passed — frontend is ready"
else
    echo " ⚠️  $FAIL issue(s) need manual attention (see above)"
fi
echo "============================================================"
