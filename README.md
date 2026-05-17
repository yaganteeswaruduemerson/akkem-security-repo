# Customer Service Calculation Assistant

A professional, text-based agent for customer service scenarios that performs addition of two numbers with robust input validation, error handling, and structured, customer-friendly responses. Integrates with Azure OpenAI, Azure Content Safety, and provides full observability via Azure SQL.

---

## Quick Start

### 1. Create a virtual environment:
```
python -m venv .venv
```

### 2. Activate the virtual environment:

**Windows:**
```
.venv\Scripts\activate
```

**macOS/Linux:**
```
source .venv/bin/activate
```

### 3. Install dependencies:
```
pip install -r requirements.txt
```

### 4. Environment setup:
Copy the example environment file and fill in all required values:
```
cp .env.example .env
```
Edit `.env` and provide your API keys, Azure SQL credentials, and other required settings.

### 5. Running the agent

**Direct execution:**
```
python code/agent.py
```

**As a FastAPI server:**
```
uvicorn code.agent:app --reload --host 0.0.0.0 --port 8000
```

---

## Environment Variables

**Agent Identity**
- `AGENT_NAME` — Agent name (preconfigured)
- `AGENT_ID` — Agent unique identifier
- `PROJECT_NAME` — Project name
- `PROJECT_ID` — Project unique identifier

**General**
- `ENVIRONMENT` — Deployment environment (e.g., development, production)

**Azure Key Vault (optional for production)**
- `USE_KEY_VAULT` — Enable Azure Key Vault integration (`true`/`false`)
- `KEY_VAULT_URI` — Azure Key Vault URI
- `AZURE_USE_DEFAULT_CREDENTIAL` — Use DefaultAzureCredential (`true`/`false`)
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — Service principal credentials (if not using managed identity)

**LLM Configuration**
- `MODEL_PROVIDER` — LLM provider (`openai`, `azure`, `anthropic`, `google`)
- `LLM_MODEL` — LLM model name (e.g., `gpt-4.1`)
- `LLM_TEMPERATURE` — Model temperature (float)
- `LLM_MAX_TOKENS` — Maximum tokens in model response (int)
- `AZURE_OPENAI_ENDPOINT` — Azure OpenAI endpoint URL

**API Keys / Secrets**
- `OPENAI_API_KEY` — OpenAI API key
- `AZURE_OPENAI_API_KEY` — Azure OpenAI API key
- `ANTHROPIC_API_KEY` — Anthropic API key
- `GOOGLE_API_KEY` — Google API key
- `AZURE_CONTENT_SAFETY_KEY` — Azure Content Safety API key

**Service Endpoints**
- `AZURE_CONTENT_SAFETY_ENDPOINT` — Azure Content Safety endpoint URL
- `AZURE_SEARCH_ENDPOINT` — Azure AI Search endpoint URL (if using RAG)

**Observability Database (Azure SQL)**
- `OBS_DATABASE_TYPE` — Should be `azure_sql`
- `OBS_AZURE_SQL_SERVER` — Azure SQL server
- `OBS_AZURE_SQL_DATABASE` — Azure SQL database name
- `OBS_AZURE_SQL_PORT` — Azure SQL port (default: 1433)
- `OBS_AZURE_SQL_USERNAME` — Azure SQL username
- `OBS_AZURE_SQL_PASSWORD` — Azure SQL password
- `OBS_AZURE_SQL_SCHEMA` — Azure SQL schema (default: `dbo`)
- `OBS_AZURE_SQL_TRUST_SERVER_CERTIFICATE` — Should be `yes`

**Agent-Specific**
- `SERVICE_NAME` — Service name for observability/logging
- `SERVICE_VERSION` — Service version
- `VALIDATION_CONFIG_PATH` — Path to input validation config (optional)
- `VERSION` — Agent version string (optional)
- `LLM_MODELS` — JSON array of LLM model configs for token pricing/cost (optional)

---

## API Endpoints

### **GET** `/health`
Health check endpoint.

**Response:**
```
{
  "status": "ok"
}
```

---

### **POST** `/query`
Perform addition of two numbers with input validation and customer-friendly response.

**Request body:**
```
{
  "number1": "string (required)",
  "number2": "string (required)"
}
```

**Response:**
```
{
  "success": true|false,
  "result": "string|null",           // Structured customer service response (if success)
  "error": "string|null",            // Error message (if failed)
  "fixing_tip": "string|null",       // Helpful tip for fixing input errors (if failed)
  "tool_calls_made": null            // Always null (no tool calls in this agent)
}
```

---

## Running Tests

### 1. Install test dependencies (if not already installed):
```
pip install pytest pytest-asyncio
```

### 2. Run all tests:
```
pytest tests/
```

### 3. Run a specific test file:
```
pytest tests/test_<module_name>.py
```

### 4. Run tests with verbose output:
```
pytest tests/ -v
```

### 5. Run tests with coverage report:
```
pip install pytest-cov
pytest tests/ --cov=code --cov-report=term-missing
```

---

## Deployment with Docker

### 1. Prerequisites: Ensure Docker is installed and running.

### 2. Environment setup: Copy `.env.example` to `.env` and configure all required environment variables.

### 3. Build the Docker image:
```
docker build -t customer-service-calculation-assistant -f deploy/Dockerfile .
```

### 4. Run the Docker container:
```
docker run -d --env-file .env -p 8000:8000 --name customer-service-calculation-assistant customer-service-calculation-assistant
```

### 5. Verify the container is running:
```
docker ps
```

### 6. View container logs:
```
docker logs customer-service-calculation-assistant
```

### 7. Stop the container:
```
docker stop customer-service-calculation-assistant
```

---

## Notes

- All run commands must use the `code/` prefix (e.g., `python code/agent.py`, `uvicorn code.agent:app ...`).
- See `.env.example` for all required and optional environment variables.
- The agent requires access to LLM API keys and (optionally) Azure SQL for observability.
- For production, configure Key Vault and secure credentials as needed.

---

**Customer Service Calculation Assistant** — Reliable, professional addition and validation for customer service automation.