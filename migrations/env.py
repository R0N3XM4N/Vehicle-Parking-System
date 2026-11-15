from alembic import context

connection = context.config.attributes["connection"]
# SQLite's legacy driver mode does not start a transaction for DDL. Acquire an
# explicit writer transaction so a failed migration rolls back every DDL step.
if not connection.connection.driver_connection.in_transaction:
    connection.exec_driver_sql("BEGIN IMMEDIATE")
context.configure(connection=connection, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
