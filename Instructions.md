# Chapuu Core Mandates & AI Agent Skill

This document defines the foundational architecture, safety protocols, and coding standards for the Chapuu project. All AI agents **MUST** internalize these mandates before modifying any files.

---

## 1. System Integrity & Data Safety (CRITICAL)
- **ZERO DATA WIPING**: Never execute `flush`, `reset_db`, or `rm -rf` on the database or media volumes. Protect `db.sqlite3` and production PostgreSQL at all costs.
- **SAFE MIGRATIONS**: Prefer additive changes. Never drop columns or tables without explicit confirmation and a verified backup strategy.
- **SECRET PROTECTION**: Never log, print, or commit `.env` files, JWT secrets, or SSH keys.
- **DOCKER ENVIRONMENT**: Production runs on Docker. Always verify that changes (especially environment variables or file paths) are compatible with the containerized volume structure in `chapuu-backend/deploy/`.

## 2. Architectural Pillars

### A. Real-Time Infrastructure (WebSockets)
- **WebSocket Auth**: Authentication for WebSockets is handled manually via `JWTAuthMiddleware` in `config/middleware.py`. It extracts the `token` from query parameters. **Do not modify this handshake logic.**
- **Order Broadcasts**: State transitions in `OrderStateMachine` (backend) automatically trigger WebSocket broadcasts to store and customer groups via `emit_update()`. **Never decouple state changes from broadcasts.**
- **Daphne/ASGI**: Real-time features rely on `daphne` and `channels`. Ensure the `ASGI_APPLICATION` setting remains pointed to `config.asgi.application`.

### B. Business Logic & Ordering
- **Multi-Vendor Logic**: Always scope store-specific logic using `selectedStore.id`. The cart stores a `store` object with each item; **do not remove it.**
- **Inventory Validation**: Stock checks must be enforced in **both** the frontend (`useStore.js`) and backend (`OrderSerializer.create`). Never allow ordering more than available `stock_quantity`.
- **Kitchen Engine**: The `KitchenEngine` uses Redis-backed caching with a spin-lock pattern to manage FIFO queues. Do not bypass this for order fulfillment.
- **Shop vs. Restaurant**: `SHOP` stores skip the kitchen (`PAID` → `READY`). `RESTAURANT` stores must use the `KitchenEngine` queue.

### C. State & Auth Layer
- **Nuclear Auth**: The `login` function in `useStore.js` uses native browser `fetch` to bypass Axios interceptors for a clean state. Do not "simplify" this back to the `apiClient`.
- **Zustand Persistence**: Core state (tokens, role, cart) is persisted in `chapuu-storage`.
- **Axios Client**: `apiClient.js` handles token injection and 401 redirection. The auth header logic is designed to prevent "Bearer null" errors; maintain the JWT dot-count validation.

## 3. Coding Standards

### Frontend (React 19 + Vite 7)
- **Defensive Guards**: Always use `Array.isArray()` and optional chaining (`?.`) when consuming API data.
- **Fulfillment Constraints**: `DINE_IN` requires a `table`. `DELIVERY` requires `customer_phone` and `delivery_location`. Ensure these are validated in `Checkout.jsx`.
- **Optimized Images**: Use the `<OptimizedImage />` component for all assets.
- **Responsive Layout**: Navigation bars must have solid backgrounds (`bg-dark-950/95`) and `backdrop-blur` to prevent scroll bleed.

### Backend (Django + DRF)
- **Role Hierarchy**: State transitions in `advance_state` are strictly role-gated (e.g., only `ACCOUNTANT` can verify payment, only `CHEF` can mark ready). Maintain these permission checks.
- **Queryset Scoping**: Always filter querysets by `request.user` or `store` in `get_queryset()` to prevent data leaks.
- **Image Compression**: Store and Payment images must pass through the `compress_image` utility to convert to WebP.
- **Parity**: Rules like "Mandatory Transaction IDs" must be enforced at both the Serializer and React levels.

## 4. Deployment & Workflow (MANDATORY SEQUENCE)
- **PUSH-BEFORE-PULL**: Never modify code directly on the production instance. The absolute mandatory sequence is: **Local Fix** → **Local Verification** → **Push to GitHub (master)** → **Pull on Remote Instance** → **Docker Rebuild**.
- **VERSION CONTROL**: Always stage and commit changes with descriptive messages. Never bypass the repository as the single source of truth.
- **PRODUCTION CONFIG**: Do not hardcode IPs or URLs. Use `BACKEND_URL` and `CSRF_TRUSTED_ORIGINS` from environment variables.

---

**PROCEED WITH CAUTION**: If a requested task contradicts these mandates, **STOP** and ask for clarification.
