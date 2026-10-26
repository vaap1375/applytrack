"""Initial application, event, and reminder schema."""
from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("applications", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("owner_id", sa.Uuid(), nullable=False), sa.Column("company_name", sa.String(200), nullable=False), sa.Column("job_title", sa.String(200), nullable=False), sa.Column("location", sa.String(200)), sa.Column("job_url", sa.String(2048)), sa.Column("external_job_id", sa.String(200)), sa.Column("status", sa.String(20), nullable=False), sa.Column("applied_at", sa.DateTime(timezone=True)), sa.Column("notes", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("status IN ('Saved','Applied','Assessment','Interview','Offer','Rejected','Withdrawn')", name="valid_status"), sa.CheckConstraint("length(trim(company_name)) > 0 AND length(trim(job_title)) > 0", name="required_names"))
    op.create_index("ix_applications_owner_id", "applications", ["owner_id"])
    op.create_index("ix_owner_status", "applications", ["owner_id", "status"])
    op.create_table("application_events", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False), sa.Column("event_type", sa.String(40), nullable=False), sa.Column("old_status", sa.String(20)), sa.Column("new_status", sa.String(20)), sa.Column("notes", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])
    op.create_table("reminders", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_reminders_application_id", "reminders", ["application_id"])
    op.create_index("ix_reminders_due_at", "reminders", ["due_at"])

def downgrade():
    op.drop_table("reminders")
    op.drop_table("application_events")
    op.drop_table("applications")
