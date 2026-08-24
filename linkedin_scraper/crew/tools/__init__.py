"""CrewAI tools that wrap existing LinkedIn + Google/X-ray search backends.

Importing this package does not require CrewAI; tool classes raise on use/import
of the concrete modules until `pip install -e ".[crew]"` is installed.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .google_search import GoogleXraySearchTool
    from .linkedin_search import LinkedInPeopleSearchTool

__all__ = [
    "GoogleXraySearchTool",
    "LinkedInPeopleSearchTool",
]


def __getattr__(name: str) -> Any:
    if name == "GoogleXraySearchTool":
        from .google_search import GoogleXraySearchTool

        return GoogleXraySearchTool
    if name == "LinkedInPeopleSearchTool":
        from .linkedin_search import LinkedInPeopleSearchTool

        return LinkedInPeopleSearchTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
