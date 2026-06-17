"""Activity log — shim forwarding to the new structured logging system."""
from educe.core.logging.compat import log_activity

__all__ = ["log_activity"]
