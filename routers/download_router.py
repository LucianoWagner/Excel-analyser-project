"""
Download router — admin-only version history viewer and Excel download.

GET  /download          → HTML page showing version history for a session/sheet
GET  /download/versions → JSON list of versions (for JS consumption)
GET  /download/excel    → Download a specific version as .xlsx
"""

import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, StreamingResponse
from jose import JWTError, jwt

from auth import require_admin, CurrentUser
from config import settings
from services.excel_service import get_versions, get_version_df

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/download", tags=["Download (Admin)"])


# ══════════════════════════════════════════════════
#  JSON: version list
# ══════════════════════════════════════════════════

@router.get("/versions")
async def list_versions(
    session_id: str = Query(..., description="Session ID"),
    sheet_name: str = Query(..., description="Sheet name"),
    user: CurrentUser = Depends(require_admin),
):
    """Return all saved versions for a session/sheet (metadata + preview rows)."""
    versions = get_versions(session_id, sheet_name)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sesión no encontrada o sin versiones guardadas.",
        )
    return {"session_id": session_id, "sheet_name": sheet_name, "versions": versions}


# ══════════════════════════════════════════════════
#  Excel Download
# ══════════════════════════════════════════════════

@router.get("/excel")
async def download_excel(
    session_id: str = Query(...),
    sheet_name: str = Query(...),
    version: int = Query(0, ge=0, description="Version index (0 = original)"),
    token: str = Query(..., description="JWT Bearer token"),
):
    """Download a specific version of a sheet as .xlsx."""
    
    # ── Authenticate token manually since it comes from query string ──
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores.")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado.")

    df = get_version_df(session_id, sheet_name, version)
    if df is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Versión {version} no encontrada para la sesión/sheet indicada.",
        )

    buf = BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    label = "original" if version == 0 else f"v{version}"
    filename = f"{sheet_name}_{label}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ══════════════════════════════════════════════════
#  HTML History Page
# ══════════════════════════════════════════════════

@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def version_history_page(
    session_id: str = Query(...),
    sheet_name: str = Query(...),
    token: str = Query(..., description="JWT Bearer token (passed via URL for browser tab nav)"),
):
    """
    Admin-only HTML page showing version history.
    Token is passed as query param since this opens in a new browser tab.
    The page validates the token client-side via the /download/versions API.
    """
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Historial de versiones — Chat con tu Excel</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: #0f0f1a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 2rem 1rem;
    }}

    .container {{ max-width: 1100px; margin: 0 auto; }}

    header {{
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 2rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid #2d2d4e;
    }}

    header h1 {{
      font-size: 1.5rem;
      background: linear-gradient(135deg, #a78bfa, #60a5fa);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .badge {{
      background: #1e1e3a;
      border: 1px solid #3d3d6e;
      border-radius: 6px;
      padding: 0.25rem 0.75rem;
      font-size: 0.78rem;
      color: #94a3b8;
    }}

    .version-grid {{
      display: grid;
      gap: 1.5rem;
    }}

    .version-card {{
      background: #16162a;
      border: 1px solid #2d2d4e;
      border-radius: 12px;
      overflow: hidden;
      transition: border-color 0.2s;
    }}

    .version-card:hover {{ border-color: #6366f1; }}

    .version-card.original {{ border-left: 3px solid #10b981; }}
    .version-card.modified {{ border-left: 3px solid #a78bfa; }}

    .card-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1rem 1.25rem;
      background: #1e1e3a;
      flex-wrap: wrap;
      gap: 0.75rem;
    }}

    .card-title {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .card-title h2 {{ font-size: 1rem; font-weight: 600; }}

    .meta {{
      font-size: 0.78rem;
      color: #64748b;
    }}

    .meta span {{ margin-left: 0.75rem; }}

    .btn-download {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 0.5rem 1rem;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      transition: opacity 0.2s, transform 0.15s;
    }}

    .btn-download:hover {{ opacity: 0.85; transform: translateY(-1px); }}

    .table-wrapper {{
      overflow-x: auto;
      padding: 1rem 1.25rem;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}

    th {{
      text-align: left;
      padding: 0.5rem 0.75rem;
      background: #0f0f1a;
      color: #94a3b8;
      font-weight: 500;
      border-bottom: 1px solid #2d2d4e;
      white-space: nowrap;
    }}

    td {{
      padding: 0.4rem 0.75rem;
      border-bottom: 1px solid #1e1e3a;
      color: #cbd5e1;
      max-width: 180px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    tr:hover td {{ background: #1a1a2e; }}

    .more-rows {{
      text-align: center;
      padding: 0.5rem;
      color: #64748b;
      font-size: 0.78rem;
      font-style: italic;
    }}

    .loading {{
      text-align: center;
      padding: 3rem;
      color: #64748b;
    }}

    .error-msg {{
      background: #2d1b1b;
      border: 1px solid #7f1d1d;
      color: #fca5a5;
      border-radius: 8px;
      padding: 1rem;
      margin-top: 1rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>📋 Historial de versiones</h1>
        <div style="margin-top:0.4rem; display:flex; gap:0.5rem; flex-wrap:wrap;">
          <span class="badge">🗂️ Sheet: {sheet_name}</span>
          <span class="badge" id="version-count">Cargando...</span>
        </div>
      </div>
    </header>

    <div id="content" class="version-grid">
      <div class="loading">⏳ Cargando versiones...</div>
    </div>
  </div>

  <script>
    const SESSION_ID = {repr(session_id)};
    const SHEET_NAME = {repr(sheet_name)};
    const TOKEN = {repr(token)};
    const BASE_URL = window.location.origin;

    async function loadVersions() {{
      const content = document.getElementById('content');
      try {{
        const res = await fetch(
          `${{BASE_URL}}/download/versions?session_id=${{SESSION_ID}}&sheet_name=${{encodeURIComponent(SHEET_NAME)}}`,
          {{ headers: {{ Authorization: `Bearer ${{TOKEN}}` }} }}
        );

        if (!res.ok) {{
          const err = await res.json();
          content.innerHTML = `<div class="error-msg">❌ ${{err.detail || 'Error al cargar versiones.'}}</div>`;
          return;
        }}

        const data = await res.json();
        const versions = data.versions;

        document.getElementById('version-count').textContent =
          `${{versions.length}} versión${{versions.length !== 1 ? 'es' : ''}} guardada${{versions.length !== 1 ? 's' : ''}}`;

        content.innerHTML = versions.map(v => buildCard(v)).join('');

      }} catch (err) {{
        content.innerHTML = `<div class="error-msg">📡 Error de conexión: ${{err.message}}</div>`;
      }}
    }}

    function buildCard(v) {{
      const isOriginal = v.index === 0;
      const cardClass = isOriginal ? 'original' : 'modified';
      const icon = isOriginal ? '🟢' : '🟣';

      const downloadUrl = `${{BASE_URL}}/download/excel?session_id=${{SESSION_ID}}&sheet_name=${{encodeURIComponent(SHEET_NAME)}}&version=${{v.index}}&token=${{TOKEN}}`;

      const headers = v.column_names.map(c => `<th>${{escHtml(c)}}</th>`).join('');
      const rows = v.preview.map(row => {{
        const cells = v.column_names.map(c => `<td title="${{escHtml(String(row[c] ?? ''))}}">${{escHtml(String(row[c] ?? ''))}}</td>`).join('');
        return `<tr>${{cells}}</tr>`;
      }}).join('');

      const moreRows = v.rows > v.preview.length
        ? `<tr><td colspan="${{v.column_names.length}}" class="more-rows">... ${{v.rows - v.preview.length}} filas más</td></tr>`
        : '';

      return `
        <div class="version-card ${{cardClass}}">
          <div class="card-header">
            <div class="card-title">
              <span>${{icon}}</span>
              <h2>${{escHtml(v.label)}}</h2>
            </div>
            <div class="meta">
              <span>📅 ${{v.timestamp}}</span>
              <span>📊 ${{v.rows}} filas · ${{v.columns}} columnas</span>
            </div>
            <a class="btn-download" href="${{downloadUrl}}" download>
              ⬇️ Descargar .xlsx
            </a>
          </div>
          <div class="table-wrapper">
            <table>
              <thead><tr>${{headers}}</tr></thead>
              <tbody>${{rows}}${{moreRows}}</tbody>
            </table>
          </div>
        </div>`;
    }}

    function escHtml(str) {{
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }}

    loadVersions();
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)
