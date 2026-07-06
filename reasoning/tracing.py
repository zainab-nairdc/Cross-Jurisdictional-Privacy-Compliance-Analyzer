# tracing.py
# optional observability layer. wraps each langgraph node so spans show up
# in opentelemetry / langsmith if those are configured. completely optional —
# if neither is installed, trace_span is a no-op and the pipeline runs fine.

import os
from functools import wraps


# try to import the optional observability libs. either failure is fine —
# we degrade to no-op tracing so the reasoning pipeline keeps working.
try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    _tracer = trace.get_tracer("reasoning")
    _OTEL_AVAILABLE = True
except ImportError:
    _tracer = None
    _OTEL_AVAILABLE = False

try:
    from langsmith import Client as LangSmithClient
    _ls_client = LangSmithClient() if os.getenv("LANGSMITH_API_KEY") else None
except ImportError:
    _ls_client = None


def trace_span(name: str):
    """decorator for async functions. on each call:
       - start an opentelemetry span (if available)
       - record success/failure status
       - send a run record to langsmith (if api key set)
    if neither is configured, this is a transparent passthrough.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not _OTEL_AVAILABLE:
                return await func(*args, **kwargs)

            with _tracer.start_as_current_span(name) as span:
                span.set_attribute("function", func.__name__)
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    if _ls_client is not None:
                        try:
                            _ls_client.create_run(
                                name     = name,
                                inputs   = {"args": [str(a)[:200] for a in args]},
                                outputs  = {"ok": True},
                                metadata = {"function": func.__name__},
                            )
                        except Exception:
                            # langsmith errors must never break the pipeline
                            pass
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise
        return wrapper
    return decorator
