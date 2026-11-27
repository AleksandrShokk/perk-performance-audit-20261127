# PERK web

This workspace is a Next.js App Router website, explicitly requested by the user.
The parent Expo instructions apply to apps/mobile. Use Next.js routing and pnpm
for web packages. Read the installed Next.js documentation before changing framework APIs.

Keep route files thin. Feature components and hooks live in src/features; shared
web controls in src/components. Use @app/api, @app/schemas and @app/tokens.
Use the existing backend; marketplace requests never run from browser code.
Private reports must not enter a shared server cache or localStorage.
Browser authentication uses HttpOnly cookies, CSRF and a single refresh request.
Keep empty, loading, error and forbidden states explicit. Never substitute mock
figures for real reports. This private project must not be published without a request.

Before completion: lint, TypeScript, relevant tests and a production build.

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
