import asyncio as _asyncio

import time as _time
from observability.observability_wrapper import (
    trace_agent, trace_step, trace_step_sync, trace_model_call, trace_tool_call,
)
from config import settings as _obs_settings

import logging as _obs_startup_log
from contextlib import asynccontextmanager
from observability.instrumentation import initialize_tracer

_obs_startup_logger = _obs_startup_log.getLogger(__name__)

from modules.guardrails.content_safety_decorator import with_content_safety

GUARDRAILS_CONFIG = {
    'content_safety_enabled': True,
    'runtime_enabled': True,
    'content_safety_severity_threshold': 3,
    'check_toxicity': True,
    'check_jailbreak': True,
    'check_pii_input': False,
    'check_credentials_output': True,
    'check_output': True,
    'check_toxic_code_output': True,
    'sanitize_pii': False
}

import logging
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, model_validator
from pathlib import Path

from config import Config

import openai

SYSTEM_PROMPT = (
    "You are a professional customer service calculation assistant. Your task is to provide a clear specification for adding two numbers using Python logic. Respond with a concise, step-by-step description of how to perform the addition operation, ensuring input validation and error handling. If the user provides invalid inputs, explain the error and request valid numbers. Output your response in a structured format suitable for customer service use. If information is not available, politely inform the user."
)
OUTPUT_FORMAT = "Provide the specification in structured text, including input validation, calculation steps, and error handling."
FALLBACK_RESPONSE = "I'm sorry, I could not find the information needed to perform the addition. Please provide two valid numbers."
FEW_SHOT_EXAMPLES = [
    "Add 3 and 4. -> The sum of 3 and 4 is 7.",
    "Add 10 and 15. -> The sum of 10 and 15 is 25."
]

VALIDATION_CONFIG_PATH = Config.VALIDATION_CONFIG_PATH or str(Path(__file__).parent / "validation_config.json")

_logger = logging.getLogger("agent")
ENRICHED_FIELDS = ["entities", "keyphrases", "relationships"]
_enriched_available = None  # None = not yet checked, True/False after first search

class QueryRequest(BaseModel):
    number1: str = Field(..., description="First number to add")
    number2: str = Field(..., description="Second number to add")

    @model_validator(mode="after")
    def validate_content(self):
        if not self.number1 or not self.number1.strip():
            raise ValueError("First number must be non-empty.")
        if not self.number2 or not self.number2.strip():
            raise ValueError("Second number must be non-empty.")
        if len(self.number1.strip()) > 50_000 or len(self.number2.strip()) > 50_000:
            raise ValueError("Input exceeds maximum length.")
        self.number1 = self.number1.strip()
        self.number2 = self.number2.strip()
        return self

class QueryResponse(BaseModel):
    success: bool = Field(..., description="Whether the operation succeeded")
    result: Optional[str] = Field(None, description="Structured customer service response")
    error: Optional[str] = Field(None, description="Error message, if any")
    fixing_tip: Optional[str] = Field(None, description="Helpful tip for fixing input errors")
    tool_calls_made: Optional[List[str]] = Field(None, description="List of tool calls made (none for this agent)")

@asynccontextmanager
async def _obs_lifespan(application):
    """Initialise observability on startup, clean up on shutdown."""
    try:
        _obs_startup_logger.info('')
        _obs_startup_logger.info('========== Agent Configuration Summary ==========')
        _obs_startup_logger.info(f'Environment: {getattr(Config, "ENVIRONMENT", "N/A")}')
        _obs_startup_logger.info(f'Agent: {getattr(Config, "AGENT_NAME", "N/A")}')
        _obs_startup_logger.info(f'Project: {getattr(Config, "PROJECT_NAME", "N/A")}')
        _obs_startup_logger.info(f'LLM Provider: {getattr(Config, "MODEL_PROVIDER", "N/A")}')
        _obs_startup_logger.info(f'LLM Model: {getattr(Config, "LLM_MODEL", "N/A")}')
        _cs_endpoint = getattr(Config, 'AZURE_CONTENT_SAFETY_ENDPOINT', None)
        _cs_key = getattr(Config, 'AZURE_CONTENT_SAFETY_KEY', None)
        if _cs_endpoint and _cs_key:
            _obs_startup_logger.info('Content Safety: Enabled (Azure Content Safety)')
            _obs_startup_logger.info(f'Content Safety Endpoint: {_cs_endpoint}')
        else:
            _obs_startup_logger.info('Content Safety: Not Configured')
        _obs_startup_logger.info('Observability Database: Azure SQL')
        _obs_startup_logger.info(f'Database Server: {getattr(Config, "OBS_AZURE_SQL_SERVER", "N/A")}')
        _obs_startup_logger.info(f'Database Name: {getattr(Config, "OBS_AZURE_SQL_DATABASE", "N/A")}')
        _obs_startup_logger.info('===============================================')
        _obs_startup_logger.info('')
    except Exception as _e:
        _obs_startup_logger.warning('Config summary failed: %s', _e)

    _obs_startup_logger.info('')
    _obs_startup_logger.info('========== Content Safety & Guardrails ==========')
    if GUARDRAILS_CONFIG.get('content_safety_enabled'):
        _obs_startup_logger.info('Content Safety: Enabled')
        _obs_startup_logger.info(f'  - Severity Threshold: {GUARDRAILS_CONFIG.get("content_safety_severity_threshold", "N/A")}')
        _obs_startup_logger.info(f'  - Check Toxicity: {GUARDRAILS_CONFIG.get("check_toxicity", False)}')
        _obs_startup_logger.info(f'  - Check Jailbreak: {GUARDRAILS_CONFIG.get("check_jailbreak", False)}')
        _obs_startup_logger.info(f'  - Check PII Input: {GUARDRAILS_CONFIG.get("check_pii_input", False)}')
        _obs_startup_logger.info(f'  - Check Credentials Output: {GUARDRAILS_CONFIG.get("check_credentials_output", False)}')
    else:
        _obs_startup_logger.info('Content Safety: Disabled')
    _obs_startup_logger.info('===============================================')
    _obs_startup_logger.info('')

    _obs_startup_logger.info('========== Initializing Agent Services ==========')
    try:
        from observability.database.engine import create_obs_database_engine
        from observability.database.base import ObsBase
        import observability.database.models  # noqa: F401
        _obs_engine = create_obs_database_engine()
        ObsBase.metadata.create_all(bind=_obs_engine, checkfirst=True)
        _obs_startup_logger.info('✓ Observability database connected')
    except Exception as _e:
        _obs_startup_logger.warning('✗ Observability database connection failed (metrics will not be saved)')
    try:
        _t = initialize_tracer()
        if _t is not None:
            _obs_startup_logger.info('✓ Telemetry monitoring enabled')
        else:
            _obs_startup_logger.warning('✗ Telemetry monitoring disabled')
    except Exception as _e:
        _obs_startup_logger.warning('✗ Telemetry monitoring failed to initialize')
    _obs_startup_logger.info('=================================================')
    _obs_startup_logger.info('')
    yield

app = FastAPI(
    title="Customer Service Calculation Assistant",
    description="Professional customer service calculation agent for addition operations.",
    version=Config.SERVICE_VERSION if hasattr(Config, "SERVICE_VERSION") else "1.0.0",
    lifespan=_obs_lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

@app.exception_handler(Exception)
@with_content_safety(config=GUARDRAILS_CONFIG)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle generic exceptions and malformed JSON errors."""
    _logger.error("Unhandled exception: %s", exc)
    return QueryResponse(
        success=False,
        error="An unexpected error occurred. Please check your input and try again.",
        fixing_tip="Ensure your JSON is properly formatted and all required fields are present."
    )

@app.post("/query", response_model=QueryResponse)
@with_content_safety(config=GUARDRAILS_CONFIG)
async def query_endpoint(req: QueryRequest):
    """Main calculation endpoint."""
    agent = CustomerServiceCalculationAgent()
    result = await agent.process_user_query(req.number1, req.number2)
    return result

class AuditLogger:
    """Logs calculation requests, errors, and responses for compliance and monitoring."""
    def __init__(self):
        self.logger = logging.getLogger("audit")

    def log_event(self, event_type: str, payload: dict) -> None:
        """Log calculation events and errors."""
        try:
            self.logger.info(f"Event: {event_type} | Payload: {json.dumps(payload, default=str)}")
        except Exception as e:
            self.logger.warning(f"Logging failed: {e}")

class MonitoringService:
    """Tracks request count, error rate, and timeouts for operational visibility."""
    def __init__(self):
        self.logger = logging.getLogger("monitoring")

    def record_metric(self, metric_name: str, value: int) -> None:
        """Record operational metrics."""
        try:
            self.logger.info(f"Metric: {metric_name} | Value: {value}")
        except Exception as e:
            self.logger.warning(f"Metric recording failed: {e}")

class CalculationService:
    """Validates inputs, performs addition, handles calculation errors."""
    def __init__(self, error_handler: 'ErrorHandler'):
        self.error_handler = error_handler

    def add_numbers(self, number1: str, number2: str) -> float:
        """Validate and add two numbers."""
        try:
            n1 = float(number1)
            n2 = float(number2)
        except Exception:
            raise ValueError("INVALID_INPUT_TYPE")
        try:
            return n1 + n2
        except Exception:
            raise ValueError("CALCULATION_ERROR")

class ErrorHandler:
    """Handles input validation errors, calculation errors, timeouts, and provides user-friendly error messages."""
    def __init__(self, llm_service: 'LLMService'):
        self.llm_service = llm_service

    async def handle_error(self, error_code: str, details: dict) -> str:
        """Map error codes to responses, escalate if repeated failures."""
        context = {
            "error_code": error_code,
            "details": details,
            "system_prompt": SYSTEM_PROMPT,
            "output_format": OUTPUT_FORMAT,
            "fallback_response": FALLBACK_RESPONSE
        }
        try:
            response = await self.llm_service.generate_response(context)
            return response
        except Exception:
            return FALLBACK_RESPONSE

class LLMService:
    """Generates structured responses, handles fallback messaging, applies system prompt and few-shot examples."""
    def __init__(self):
        self.model = Config.LLM_MODEL or "gpt-4.1"
        self.temperature = Config.LLM_TEMPERATURE if hasattr(Config, "LLM_TEMPERATURE") else 0.7
        self.max_tokens = Config.LLM_MAX_TOKENS if hasattr(Config, "LLM_MAX_TOKENS") else 2000
        self.client = None

    def _get_client(self):
        if self.client is None:
            api_key = Config.AZURE_OPENAI_API_KEY
            if not api_key:
                raise ValueError("AZURE_OPENAI_API_KEY not configured")
            self.client = openai.AsyncAzureOpenAI(
                api_key=api_key,
                api_version="2024-02-01",
                azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            )
        return self.client

    @with_content_safety(config=GUARDRAILS_CONFIG)
    @trace_agent(agent_name=_obs_settings.AGENT_NAME, project_name=_obs_settings.PROJECT_NAME)
    async def generate_response(self, context: dict) -> str:
        """Generate structured response using LLM with context."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nOutput Format: " + OUTPUT_FORMAT},
        ]
        user_content = self._build_user_content(context)
        messages.append({"role": "user", "content": user_content})
        _llm_kwargs = Config.get_llm_kwargs()
        _t0 = _time.time()
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                **_llm_kwargs
            )
            content = response.choices[0].message.content
            try:
                trace_model_call(
                    provider="azure",
                    model_name=self.model,
                    prompt_tokens=getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0,
                    latency_ms=int((_time.time() - _t0) * 1000),
                    response_summary=content[:200] if content else "",
                )
            except Exception:
                pass
            return sanitize_llm_output(content, content_type="text")
        except Exception as e:
            _logger.error("LLM call failed: %s", e)
            return FALLBACK_RESPONSE

    def _build_user_content(self, context: dict) -> str:
        """Build user content for LLM call."""
        if "error_code" in context:
            if context["error_code"] == "INVALID_INPUT_TYPE":
                return f"User provided invalid input: {context.get('details', {})}. Please explain the error and request valid numbers."
            elif context["error_code"] == "CALCULATION_ERROR":
                return f"Calculation error occurred: {context.get('details', {})}. Please explain and request valid numbers."
        if "number1" in context and "number2" in context:
            return f"Add {context['number1']} and {context['number2']}."
        return "Please provide two numbers to add."

class ChunkRetriever:
    """Dummy for RAG pipeline; not used as no document context is present."""
    pass

class CustomerServiceCalculationAgent:
    """Main agent class orchestrating the flow."""
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.monitoring_service = MonitoringService()
        self.llm_service = LLMService()
        self.error_handler = ErrorHandler(self.llm_service)
        self.calculation_service = CalculationService(self.error_handler)

    @with_content_safety(config=GUARDRAILS_CONFIG)
    async def process_user_query(self, number1: str, number2: str) -> QueryResponse:
        """Orchestrate the flow: receive input, validate, calculate, handle errors, generate response."""
        async with trace_step(
            "parse_input", step_type="parse",
            decision_summary="Validate and parse user input",
            output_fn=lambda r: f"parsed={r}"
        ) as step:
            self.audit_logger.log_event("request_received", {"number1": number1, "number2": number2})
            self.monitoring_service.record_metric("request_count", 1)
            try:
                sum_result = self.calculation_service.add_numbers(number1, number2)
            except ValueError as ve:
                error_code = str(ve)
                self.audit_logger.log_event("error", {"error_code": error_code, "number1": number1, "number2": number2})
                self.monitoring_service.record_metric("error_count", 1)
                async with trace_step(
                    "handle_error", step_type="process",
                    decision_summary="Handle input or calculation error",
                    output_fn=lambda r: f"error_response={r}"
                ) as error_step:
                    error_response = await self.error_handler.handle_error(error_code, {"number1": number1, "number2": number2})
                    error_step.capture(error_response)
                return QueryResponse(
                    success=False,
                    result=None,
                    error=error_response,
                    fixing_tip="Please provide two valid numbers (e.g., 5 and 7).",
                    tool_calls_made=None
                )
            step.capture({"sum": sum_result})
        async with trace_step(
            "generate_response", step_type="llm_call",
            decision_summary="Generate structured customer service response",
            output_fn=lambda r: f"llm_response={r}"
        ) as gen_step:
            context = {
                "number1": number1,
                "number2": number2,
                "sum": sum_result,
                "system_prompt": SYSTEM_PROMPT,
                "output_format": OUTPUT_FORMAT,
                "few_shot_examples": FEW_SHOT_EXAMPLES
            }
            response = await self.llm_service.generate_response(context)
            gen_step.capture(response)
            self.audit_logger.log_event("response_generated", {"number1": number1, "number2": number2, "sum": sum_result, "response": response})
            self.monitoring_service.record_metric("success_count", 1)
        return QueryResponse(
            success=True,
            result=response,
            error=None,
            fixing_tip=None,
            tool_calls_made=None
        )

import re as _re

_FENCE_RE = _re.compile(r"```(?:\w+)?\s*\n(.*?)```", _re.DOTALL)
_LONE_FENCE_START_RE = _re.compile(r"^```\w*$")
_WRAPPER_RE = _re.compile(
    r"^(?:"
    r"Here(?:'s| is)(?: the)? (?:the |your |a )?(?:code|solution|implementation|result|explanation|answer)[^:]*:\s*"
    r"|Sure[!,.]?\s*"
    r"|Certainly[!,.]?\s*"
    r"|Below is [^:]*:\s*"
    r")",
    _re.IGNORECASE,
)
_SIGNOFF_RE = _re.compile(
    r"^(?:Let me know|Feel free|Hope this|This code|Note:|Happy coding|If you)",
    _re.IGNORECASE,
)
_BLANK_COLLAPSE_RE = _re.compile(r"\n{3,}")

def _strip_fences(text: str, content_type: str) -> str:
    """Extract content from Markdown code fences."""
    fence_matches = _FENCE_RE.findall(text)
    if fence_matches:
        if content_type == "code":
            return "\n\n".join(block.strip() for block in fence_matches)
        for match in fence_matches:
            fenced_block = _FENCE_RE.search(text)
            if fenced_block:
                text = text[:fenced_block.start()] + match.strip() + text[fenced_block.end():]
        return text
    lines = text.splitlines()
    if lines and _LONE_FENCE_START_RE.match(lines[0].strip()):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()

def _strip_trailing_signoffs(text: str) -> str:
    """Remove conversational sign-off lines from the end of code output."""
    lines = text.splitlines()
    while lines and _SIGNOFF_RE.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).rstrip()

@with_content_safety(config=GUARDRAILS_CONFIG)
def sanitize_llm_output(raw: str, content_type: str = "code") -> str:
    """
    Generic post-processor that cleans common LLM output artefacts.
    Args:
        raw: Raw text returned by the LLM.
        content_type: 'code' | 'text' | 'markdown'.
    Returns:
        Cleaned string ready for validation, formatting, or direct return.
    """
    if not raw:
        return ""
    text = _strip_fences(raw.strip(), content_type)
    text = _WRAPPER_RE.sub("", text, count=1).strip()
    if content_type == "code":
        text = _strip_trailing_signoffs(text)
    return _BLANK_COLLAPSE_RE.sub("\n\n", text).strip()

async def _run_agent():
    """Entrypoint: runs the agent with observability (trace collection only)."""
    import uvicorn

    _LOG_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(name)s: %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn":        {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error":  {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            "agent":          {"handlers": ["default"], "level": "INFO", "propagate": False},
            "__main__":       {"handlers": ["default"], "level": "INFO", "propagate": False},
            "observability": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "config": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "azure":   {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "urllib3": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        },
    }

    config = uvicorn.Config(
        "agent:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
        log_config=_LOG_CONFIG,
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    _asyncio.run(_run_agent())