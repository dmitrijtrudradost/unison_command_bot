"""Проверки переносимых ограничений схемы M0."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Uuid

from teambot.adapters.storage.models import Base
from teambot.adapters.storage.schemas import MembershipValues


def test_every_primary_key_is_uuid_without_server_default() -> None:
    for table in Base.metadata.tables.values():
        primary_keys = list(table.primary_key.columns)
        assert primary_keys, table.name
        assert all(isinstance(column.type, Uuid) for column in primary_keys), table.name
        assert all(column.server_default is None for column in table.columns), table.name


def test_every_team_table_has_required_indexed_team_id() -> None:
    team_tables = [table for table in Base.metadata.tables.values() if "team_id" in table.c]
    assert {table.name for table in team_tables} == {
        "memberships",
        "chats",
        "messages",
        "team_sequences",
        "tasks",
        "ideas",
        "idea_tags",
        "access_codes",
    }
    for table in team_tables:
        column = table.c.team_id
        assert not column.nullable, table.name
        assert column.index, table.name


def test_constraints_are_named_and_foreign_keys_define_delete_action() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            assert constraint.name, f"{table.name}: {constraint}"
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete, f"{table.name}: {foreign_key}"


def test_repository_values_reject_unknown_role_before_database() -> None:
    with pytest.raises(ValidationError):
        MembershipValues.model_validate({"user_id": str(uuid4()), "role": "hacker"})
