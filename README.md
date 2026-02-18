# 🗂️ Chat con tu Excel

Backend en **Python + FastAPI** que permite subir un archivo Excel y hacerle consultas en lenguaje natural usando **LangChain** y **Groq** (LLM gratuito).

---

## 🧠 ¿Cómo funciona?

El sistema tiene **dos modos de operación** según el rol del usuario:

| Modo | Rol | Motor | Seguridad |
|------|-----|-------|-----------|
| **🔬 Agent** | Admin | LangChain Pandas Agent — genera y ejecuta código Python dinámico | Código libre sobre copia del DataFrame |
| **🔒 Structured** | User | Router de intenciones — el LLM clasifica la pregunta y ejecuta funciones predefinidas | Sin ejecución de código, 100% seguro |

### Flujo general

```
1. El usuario sube un Excel (.xlsx / .xls)
2. El backend parsea TODAS las sheets y las guarda en memoria
3. El usuario envía preguntas en lenguaje natural
4. Según el rol:
   - Admin → Pandas Agent genera código Python y lo ejecuta
   - User  → LLM clasifica la intención y ejecuta una función predefinida
5. El sistema responde con texto, datos y/o gráficos (base64 PNG)
```

### Ejemplos de consultas

| Pregunta | Tipo |
|----------|------|
| "¿Cuántas filas hay?" | Conteo |
| "¿Cuántos alumnos tienen 18 años?" | Filtro |
| "Estadísticas descriptivas de la columna edad" | Análisis |
| "Graficá el conteo por género con barras" | Visualización |
| "¿Hay correlación entre nota y asistencia?" | Correlación |
| "Mostrá un heatmap de las columnas numéricas" | Visualización |

---

## 🏗️ Arquitectura

```
┌──────────────────────────────────────────────────────────┐
│                      FastAPI Backend                      │
│                                                          │
│  POST /auth/register ─── Crear usuario                   │
│  POST /auth/login    ─── JWT con rol (admin/user)        │
│  POST /upload        ─── Subir Excel → session_id        │
│  POST /query         ─── Pregunta → respuesta + gráfico  │
│  GET  /health        ─── Healthcheck                     │
│                                                          │
│  ┌────────────────┐    ┌─────────────────────────────┐   │
│  │  Admin (Agent)  │    │  User (Structured)           │   │
│  │                │    │                             │   │
│  │  Pandas Agent  │    │  LLM clasifica intención    │   │
│  │  genera código │    │  → ejecuta función segura   │   │
│  │  libre, charts │    │  → 8 ops datos + 7 charts   │   │
│  └────────────────┘    └─────────────────────────────┘   │
│           │                        │                     │
│           └────────┬───────────────┘                     │
│                    ▼                                     │
│          Groq API (free tier)                            │
│              Llama 3.3 70B                               │
└──────────────────────────────────────────────────────────┘
         │
         ▼
   PostgreSQL (Docker)
   Tabla: users
```

---

## 📁 Estructura del proyecto

```
├── docker-compose.yml          # PostgreSQL 16
├── .env / .env.example         # Variables de entorno
├── .gitignore
├── requirements.txt            # Dependencias Python
├── main.py                     # FastAPI app + startup
├── config.py                   # Configuración centralizada
├── database.py                 # SQLAlchemy async engine
├── db_models.py                # Modelo User (ORM)
├── models.py                   # Schemas Pydantic (request/response)
├── auth.py                     # JWT + bcrypt + dependencies
├── routers/
│   ├── auth_router.py          # /auth/register, /auth/login
│   ├── upload_router.py        # /upload
│   └── query_router.py         # /query (dual-mode)
├── services/
│   ├── llm_service.py          # Cliente Groq (singleton)
│   ├── excel_service.py        # Parseo Excel + sesiones en memoria
│   ├── agent_service.py        # Pandas Agent (modo admin)
│   ├── structured_service.py   # Router de intenciones (modo user)
│   └── chart_service.py        # 7 tipos de gráficos
└── utils/
    └── safety.py               # Blocklist de código + validaciones
```

---

## 🛡️ Seguridad

### Modo Structured (usuarios normales)
- **Sin ejecución de código** — el LLM solo clasifica la intención
- Funciones predefinidas con validación de parámetros
- Imposible ejecutar código arbitrario

### Modo Agent (admin)
- `df.copy(deep=True)` — nunca se modifica el DataFrame original
- Timeout configurable por consulta
- Mini-blocklist de patrones peligrosos (`os.system`, `subprocess`, `exec`, etc.)
- Solo accesible con autenticación de admin

### General
- Autenticación JWT con bcrypt
- Validación de archivos (extensión, tamaño, cantidad de filas)
- Rate limiting recomendado vía reverse proxy (nginx) en producción

---

## 🚀 Instalación y ejecución

### Requisitos previos
- **Python 3.11+**
- **Docker** (para PostgreSQL)
- **Cuenta en Groq** — [console.groq.com](https://console.groq.com) (free tier, sin tarjeta)

### 1. Clonar y configurar

```bash
git clone <url-del-repo>
cd "Proyecto IA analisador de excels"
cp .env.example .env
```

Editá `.env` y pegá tu `GROQ_API_KEY` (obtenela en [console.groq.com/keys](https://console.groq.com/keys)).

### 2. Levantar PostgreSQL

```bash
docker compose up -d
```

### 3. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1    # Windows PowerShell
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
```

### 4. Iniciar el servidor

```bash
uvicorn main:app --reload --port 8000
```

Al iniciar, el server:
- ✅ Crea las tablas en PostgreSQL
- ✅ Crea el usuario admin default (`admin / admin123`)

### 5. Acceder a la documentación

Abrí en el navegador: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📡 Uso de la API

### Autenticación

**Registrar usuario (rol: user):**
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "lucas", "password": "mipass123"}'
```

**Login (obtener token):**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

Respuesta:
```json
{
  "access_token": "eyJhbGciOiJIUzI1...",
  "token_type": "bearer",
  "role": "admin",
  "username": "admin"
}
```

### Subir Excel

```bash
curl -X POST http://localhost:8000/upload \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@datos.xlsx"
```

Respuesta:
```json
{
  "session_id": "a1b2c3d4-...",
  "filename": "datos.xlsx",
  "sheets": [
    {
      "name": "Hoja1",
      "rows": 150,
      "columns": 5,
      "column_names": ["nombre", "edad", "género", "nota", "asistencia"]
    }
  ]
}
```

### Consultar

```bash
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "a1b2c3d4-...",
    "question": "¿Cuántos alumnos tienen más de 18 años?",
    "sheet_name": "Hoja1"
  }'
```

Respuesta (ejemplo admin/agent):
```json
{
  "answer": "Hay 42 alumnos con más de 18 años.",
  "chart_base64": null,
  "code_generated": "len(df[df['edad'] > 18])",
  "operation_used": null,
  "mode": "agent"
}
```

Respuesta (ejemplo user/structured):
```json
{
  "answer": "Hay **42** filas donde `edad > 18`.",
  "chart_base64": null,
  "code_generated": null,
  "operation_used": "filter_count",
  "mode": "structured"
}
```

### Consulta con gráfico

```bash
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "a1b2c3d4-...",
    "question": "Graficá el conteo por género con barras"
  }'
```

El campo `chart_base64` contendrá la imagen PNG codificada en base64.

---

## 📊 Operaciones disponibles (modo Structured)

### Análisis de datos
| Operación | Descripción |
|-----------|-------------|
| `count_rows` | Total de filas y columnas |
| `describe` | Estadísticas descriptivas |
| `column_info` | Info de cada columna (tipo, nulos, únicos) |
| `value_counts` | Conteo de valores únicos |
| `filter_count` | Contar filas con filtro |
| `group_aggregate` | Agrupar y agregar (mean, sum, count, etc.) |
| `correlation` | Correlación entre dos columnas |
| `unique_values` | Listar valores únicos |
| `top_bottom` | Encontrar filas con valores más altos/bajos |

### Visualizaciones
| Gráfico | Descripción |
|---------|-------------|
| `bar_chart` | Barras (vertical/horizontal) |
| `histogram` | Distribución de variable numérica |
| `pie_chart` | Torta con porcentajes |
| `scatter_plot` | Dispersión entre dos variables |
| `box_plot` | Box plot (outliers + distribución) |
| `line_chart` | Línea temporal/secuencial |
| `heatmap` | Correlación entre columnas numéricas |

---

## ⚙️ Configuración

| Variable | Default | Descripción |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | API key de Groq (obligatoria, free tier) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | URL de PostgreSQL |
| `JWT_SECRET` | `change_this...` | Secret para firmar JWTs |
| `JWT_EXPIRE_MINUTES` | `480` | Expiración del token (8 horas) |
| `DEFAULT_ADMIN_USER` | `admin` | Username del admin default |
| `DEFAULT_ADMIN_PASS` | `admin123` | Password del admin default |
| `MAX_FILE_SIZE_MB` | `10` | Tamaño máximo de archivo |
| `MAX_ROWS` | `100000` | Máximo de filas por sheet |
| `QUERY_TIMEOUT_SECONDS` | `30` | Timeout por consulta |

---

## 🛠️ Stack tecnológico

| Componente | Tecnología |
|-----------|------------|
| **Framework** | FastAPI |
| **LLM** | Groq (Llama 3.3 70B) — free tier |
| **Agent** | LangChain `create_pandas_dataframe_agent` |
| **Data** | Pandas + Openpyxl |
| **Gráficos** | Matplotlib + Seaborn |
| **Base de datos** | PostgreSQL 16 (Docker) |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Auth** | JWT (python-jose) + bcrypt (passlib) |
| **Runtime** | Uvicorn |
