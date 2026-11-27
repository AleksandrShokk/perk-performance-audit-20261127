"""Explicit tenant filters complement PostgreSQL RLS, including worker reads."""


def scope(model, workspace_id, store_id):
    return model.workspace_id == workspace_id, model.store_id == store_id
