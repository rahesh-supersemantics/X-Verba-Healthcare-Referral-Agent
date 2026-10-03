# X-Verba Healthcare Referral Agent: frontend

React + Vite frontend with two separate surfaces:

| Route | Audience | Purpose |
|---|---|---|
| `/` | Clinicians | Healthcare Referral Assistant: natural-language chat, request status, referral result |
| `/engineering` | AI / governance engineers | Governance & Review Console: VSL ledger evidence per decision |

The frontend talks to the FastAPI backend **only** through `src/api.js`. It never
calls the language model or the database, and it contains no governance logic.
Clinician messages are derived from the backend's workflow status code
(`src/lib/outcomes.js`), never from HTTP status alone.

```powershell
npm install
npm run dev        # http://localhost:5173  (proxies /api -> http://127.0.0.1:8000)
npm run lint
npm test           # Node built-in test runner, no extra dependencies
npm run build
```

Environment (optional):

* `XVERBA_API_TARGET`: backend URL used by the dev/preview proxy (default `http://127.0.0.1:8000`).
* `VITE_API_URL`: call the backend directly instead of through `/api` (it must then be allowed by the backend's CORS setting).
