"""API endpoint definitions."""

from dataclasses import dataclass
from enum import Enum


class Platform(str, Enum):
    """Supported platforms."""

    LINKEDIN = "linkedin"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    WEB = "web"
    YC = "yc"


@dataclass
class Endpoint:
    """API endpoint definition."""

    path: str
    description: str
    platform: Platform


# LinkedIn endpoints
LINKEDIN_USER = Endpoint(
    path="/api/linkedin/user",
    description="Get LinkedIn user profile",
    platform=Platform.LINKEDIN,
)

LINKEDIN_SEARCH_USERS = Endpoint(
    path="/api/linkedin/search/users",
    description="Search LinkedIn users",
    platform=Platform.LINKEDIN,
)

LINKEDIN_COMPANY = Endpoint(
    path="/api/linkedin/company",
    description="Get LinkedIn company information",
    platform=Platform.LINKEDIN,
)

LINKEDIN_COMPANY_EMPLOYEES = Endpoint(
    path="/api/linkedin/company/employees",
    description="Get LinkedIn company employees",
    platform=Platform.LINKEDIN,
)

LINKEDIN_COMPANY_POSTS = Endpoint(
    path="/api/linkedin/company/posts",
    description="Get LinkedIn company posts",
    platform=Platform.LINKEDIN,
)

LINKEDIN_SEARCH_POSTS = Endpoint(
    path="/api/linkedin/search/posts",
    description="Search LinkedIn posts",
    platform=Platform.LINKEDIN,
)

LINKEDIN_POST = Endpoint(
    path="/api/linkedin/post",
    description="Get LinkedIn post by URN",
    platform=Platform.LINKEDIN,
)

LINKEDIN_USER_POSTS = Endpoint(
    path="/api/linkedin/user/posts",
    description="Get LinkedIn user posts",
    platform=Platform.LINKEDIN,
)

# Instagram endpoints
INSTAGRAM_USER = Endpoint(
    path="/api/instagram/user",
    description="Get Instagram user profile",
    platform=Platform.INSTAGRAM,
)

INSTAGRAM_USER_POSTS = Endpoint(
    path="/api/instagram/user/posts",
    description="Get Instagram user posts",
    platform=Platform.INSTAGRAM,
)

INSTAGRAM_USER_REELS = Endpoint(
    path="/api/instagram/user/reels",
    description="Get Instagram user reels",
    platform=Platform.INSTAGRAM,
)

INSTAGRAM_POST = Endpoint(
    path="/api/instagram/post",
    description="Get Instagram post by ID",
    platform=Platform.INSTAGRAM,
)

INSTAGRAM_SEARCH_POSTS = Endpoint(
    path="/api/instagram/search/posts",
    description="Search Instagram posts",
    platform=Platform.INSTAGRAM,
)

# Twitter endpoints
TWITTER_USER = Endpoint(
    path="/api/twitter/user",
    description="Get Twitter user profile",
    platform=Platform.TWITTER,
)

TWITTER_USER_POSTS = Endpoint(
    path="/api/twitter/user/posts",
    description="Get Twitter user posts",
    platform=Platform.TWITTER,
)

TWITTER_SEARCH_POSTS = Endpoint(
    path="/api/twitter/search/posts",
    description="Search Twitter posts",
    platform=Platform.TWITTER,
)

TWITTER_SEARCH_USERS = Endpoint(
    path="/api/twitter/search/users",
    description="Search Twitter users",
    platform=Platform.TWITTER,
)

# Web endpoints
WEB_PARSE = Endpoint(
    path="/api/webparser/parse",
    description="Parse and clean HTML from web page",
    platform=Platform.WEB,
)

WEB_SITEMAP = Endpoint(
    path="/api/webparser/sitemap",
    description="Get sitemap from URL",
    platform=Platform.WEB,
)

# YC endpoints
YC_COMPANY = Endpoint(
    path="/api/yc/company",
    description="Get YC company information",
    platform=Platform.YC,
)

YC_SEARCH_COMPANIES = Endpoint(
    path="/api/yc/search/companies",
    description="Search YC companies",
    platform=Platform.YC,
)

YC_SEARCH_FOUNDERS = Endpoint(
    path="/api/yc/search/founders",
    description="Search YC founders",
    platform=Platform.YC,
)
