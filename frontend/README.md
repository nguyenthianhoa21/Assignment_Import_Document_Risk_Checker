# Frontend — Import Document Risk Checker

UI for AI-assisted import document inspection: upload -> extraction display
-> cross-document diff matrix -> risk highlight.

## Stack

React (Vite) + TypeScript + TailwindCSS + React Router v6 + Axios + Lucide icons.

## Screens

| Route | Purpose |
| ----- | ------- |
| `/` | Dashboard: shipment history, PASSED/WARNING/REJECTED stats, history table |
| `/upload` | Drag & drop multiple PDFs/images, title form, progress Upload -> Extracting -> Done, auto-navigate to detail |
| `/shipments/:id` | Split view: side-by-side CI/PL/BL matrix + risk alert list with highlight + evidence modal |

## Run

```powershell
cd frontend
npm install
copy .env.example .env
# Edit .env: VITE_API_URL=http://localhost:8000/api/v1
npm run dev
```

Default port: http://localhost:5173

## Demo walkthrough (with the 3 provided samples)

1. Open `/upload`, set title e.g. `Lot 2609 QDO26091288`.
2. Drop the 3 sample PDFs (`Sample_Commercial_Invoice.pdf`,
   `Sample_Packing_List.pdf`, `Sample_Bill_of_Lading.pdf`).
3. Click "Process & Validate", wait until redirected to `/shipments/:id`.
4. Observe highlights in the matrix:
   - **Invoice No.**: `IV-2026-1008` (CI) vs `IV-2026-100B` (PL) — red `HIGH`.
   - **Gross Weight**: `231,000 KG` (CI) vs `232,000 KG` (PL/BL) — red `HIGH`.
   - **Container 2**: `OOLU7654327` (BL) vs `OOLU7654321` (PL) — red `HIGH`.
   - **Consignee**: `GREENFIELD FOOD...` vs `...FOODS... LIMITED` — amber `MEDIUM`.
5. Click a risk card ("Highlight field") to scroll + pulsate the cell;
   click "View snippet" to inspect the verbatim evidence.
