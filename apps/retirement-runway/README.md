# Retirement Runway

A single-page retirement planning calculator: projects portfolio growth
from your current savings and contributions, models drawdown through
retirement at a chosen withdrawal rate, and includes optional
Social Security, tax, FIRE/Coast FIRE, sequence-of-returns risk, and
withdrawal-order tooling in Advanced mode.

Everything is self-contained in the browser — inputs are encoded into a
shareable URL (`?d=...`) rather than stored on any backend, so there's no
account system and nothing to sign up for.

## Stack

- [Vite](https://vite.dev) + React 19
- [Recharts](https://recharts.org) for the projection chart

## Development

```bash
npm install
npm run dev       # local dev server with HMR
npm run build     # production build to dist/
npm run preview   # serve the production build locally
```

## Deployment

This is a static site — `npm run build` produces a `dist/` folder that can
be deployed to any static host (Netlify, Vercel, GitHub Pages, etc). A
`netlify.toml` is included for Netlify deploys.
