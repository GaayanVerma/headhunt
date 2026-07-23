"""LinkedIn Scraper - Async Playwright-based scraper for LinkedIn."""

# Version
__version__ = "3.1.2"

# Core modules
from .core import (
    BrowserManager,
    login_with_credentials,
    login_with_cookie,
    is_logged_in,
    wait_for_manual_login,
    load_credentials_from_env,
    load_github_token_from_env,
    # Exceptions
    LinkedInScraperException,
    AuthenticationError,
    RateLimitError,
    ElementNotFoundError,
    ProfileNotFoundError,
    NetworkError,
    ScrapingError,
)

# Scrapers
from .scrapers import (
    PersonScraper,
    CompanyScraper,
    JobScraper,
    JobSearchScraper,
    PeopleSearchScraper,
    CompanyPostsScraper,
)

# Callbacks
from .callbacks import (
    ProgressCallback,
    ConsoleCallback,
    SilentCallback,
    JSONLogCallback,
    MultiCallback,
)

# Models
from .models import (
    Person,
    PersonSearchResult,
    Experience,
    Education,
    Contact,
    Accomplishment,
    Interest,
    Company,
    CompanySummary,
    Employee,
    Job,
    Post,
    ResumeData,
    ResumeProject,
)

# Resume parser
from .resume import ResumeParser

# GitHub analyzer
from .github import GitHubAnalyzer, resolve_github_username, GitHubClient

__all__ = [
    # Version
    "__version__",
    # Core
    "BrowserManager",
    "login_with_credentials",
    "login_with_cookie",
    "is_logged_in",
    "wait_for_manual_login",
    "load_credentials_from_env",
    "load_github_token_from_env",
    # Scrapers
    "PersonScraper",
    "CompanyScraper",
    "JobScraper",
    "JobSearchScraper",
    "PeopleSearchScraper",
    "CompanyPostsScraper",
    # Exceptions
    "LinkedInScraperException",
    "AuthenticationError",
    "RateLimitError",
    "ElementNotFoundError",
    "ProfileNotFoundError",
    "NetworkError",
    "ScrapingError",
    # Callbacks
    "ProgressCallback",
    "ConsoleCallback",
    "SilentCallback",
    "JSONLogCallback",
    "MultiCallback",
    # Models
    "Person",
    "PersonSearchResult",
    "Experience",
    "Education",
    "Contact",
    "Accomplishment",
    "Interest",
    "Company",
    "CompanySummary",
    "Employee",
    "Job",
    "Post",
    "ResumeData",
    "ResumeProject",
    # Resume parser
    "ResumeParser",
    # GitHub analyzer
    "GitHubAnalyzer",
    "resolve_github_username",
    "GitHubClient",
]
