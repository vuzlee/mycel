"""The sources a person can pick for one turn."""

from enum import StrEnum


class Chip(StrEnum):
    KNOWLEDGE = "knowledge"
    WEB = "web"
    JIRA = "jira"
    CALENDAR = "calendar"
    MAIL = "mail"
