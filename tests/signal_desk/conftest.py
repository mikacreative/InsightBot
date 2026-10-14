"""Workspace confirmation must read live, fictional account metadata."""
import json
import pytest


@pytest.fixture(autouse=True)
def workspace_accounts(request, tmp_path):
    if request.node.path.name in {'test_workspace_v2.py', 'test_enrichment_v2.py', 'test_empty_delivery.py'}:
        (tmp_path / 'users.json').write_text(json.dumps({
            'admin': {'role': 'admin'}, 'alice': {'role': 'editor'},
            'bob': {'role': 'editor'}, 'reviewer': {'role': 'editor'}}))
