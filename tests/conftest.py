"""Pytest configuration and fixtures."""

import pytest
from typer.testing import CliRunner

from anysite.main import app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a CLI runner for testing commands."""
    return CliRunner()


@pytest.fixture
def sample_linkedin_profile() -> dict:
    """Sample LinkedIn profile data."""
    return {
        "@type": "LinkedinUser",
        "urn": "urn:li:fsd_profile:ACoAAA123",
        "name": "Test User",
        "first_name": "Test",
        "last_name": "User",
        "alias": "testuser",
        "url": "https://www.linkedin.com/in/testuser",
        "headline": "Software Engineer at Test Company",
        "follower_count": 1000,
        "connection_count": 500,
        "location": "San Francisco, CA",
        "about": "Test bio",
        "experience": [
            {
                "company": "Test Company",
                "title": "Software Engineer",
                "start_date": "2020-01",
                "end_date": None,
            }
        ],
        "education": [
            {
                "school": "Test University",
                "degree": "BS Computer Science",
                "start_date": "2016",
                "end_date": "2020",
            }
        ],
        "skills": ["Python", "JavaScript", "SQL"],
    }


@pytest.fixture
def sample_instagram_user() -> dict:
    """Sample Instagram user data."""
    return {
        "@type": "InstagramUser",
        "id": "123456789",
        "username": "testuser",
        "full_name": "Test User",
        "biography": "Test bio",
        "follower_count": 10000,
        "following_count": 500,
        "media_count": 100,
        "is_verified": False,
        "is_private": False,
        "profile_pic_url": "https://example.com/pic.jpg",
    }


@pytest.fixture
def sample_twitter_user() -> dict:
    """Sample Twitter user data."""
    return {
        "@type": "TwitterUser",
        "id": "123456789",
        "screen_name": "testuser",
        "name": "Test User",
        "description": "Test bio",
        "followers_count": 5000,
        "friends_count": 200,
        "statuses_count": 1000,
        "verified": False,
        "profile_image_url": "https://example.com/pic.jpg",
        "created_at": "2015-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_api_response(sample_linkedin_profile):
    """Mock API response (returns list)."""
    return [sample_linkedin_profile]
