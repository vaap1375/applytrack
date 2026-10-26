"""Gmail credentials, resumable sync/review state, and status revision guards."""
from alembic import op
import sqlalchemy as sa
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('applications',sa.Column('status_revision',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('applications',sa.Column('status_changed_at',sa.DateTime(timezone=True)))
    op.add_column('applications',sa.Column('status_manual_at',sa.DateTime(timezone=True)))
    op.execute('UPDATE applications SET status_changed_at = updated_at, status_manual_at = updated_at')
    op.add_column('application_events',sa.Column('source',sa.String(30),nullable=False,server_default='manual'))
    op.add_column('application_events',sa.Column('source_message_id',sa.String(200)))
    op.add_column('application_events',sa.Column('source_timestamp',sa.DateTime(timezone=True)))
    op.create_table('gmail_connections',
        sa.Column('owner_id',sa.Uuid(),primary_key=True),sa.Column('email',sa.String(320),nullable=False),
        sa.Column('encrypted_refresh',sa.Text()),sa.Column('health',sa.String(40),nullable=False),
        sa.Column('history_id',sa.String(100)),sa.Column('pending',sa.JSON()),
        sa.Column('last_sync_at',sa.DateTime(timezone=True)),sa.Column('dry_run_at',sa.DateTime(timezone=True)),
        sa.Column('auto_updates',sa.Boolean(),nullable=False),sa.Column('auto_enabled_at',sa.DateTime(timezone=True)),
        sa.Column('lookback_days',sa.Integer(),nullable=False),sa.Column('stats',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('gmail_oauth_states',sa.Column('owner_id',sa.Uuid(),primary_key=True),
        sa.Column('state_hash',sa.String(64),unique=True,nullable=False),sa.Column('browser_hash',sa.String(64),nullable=False),
        sa.Column('encrypted_verifier',sa.Text(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('gmail_match_rules',sa.Column('application_id',sa.Uuid(),sa.ForeignKey('applications.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('aliases',sa.JSON(),nullable=False),sa.Column('sender_domains',sa.JSON(),nullable=False))
    op.create_table('gmail_messages',sa.Column('id',sa.Uuid(),primary_key=True),sa.Column('owner_id',sa.Uuid(),nullable=False),
        sa.Column('gmail_id',sa.String(200),nullable=False),sa.Column('subject',sa.String(300)),sa.Column('sender',sa.String(320)),
        sa.Column('excerpt',sa.String(500)),sa.Column('received_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('classification',sa.String(40),nullable=False),sa.Column('class_confidence',sa.Float(),nullable=False),
        sa.Column('match_confidence',sa.Float(),nullable=False),sa.Column('evidence',sa.JSON(),nullable=False),
        sa.Column('application_id',sa.Uuid(),sa.ForeignKey('applications.id',ondelete='SET NULL')),
        sa.Column('proposed_status',sa.String(20)),sa.Column('old_status',sa.String(20)),sa.Column('state',sa.String(30),nullable=False),
        sa.Column('snapshot_revision',sa.Integer()),sa.Column('resulting_revision',sa.Integer()),
        sa.Column('event_id',sa.Uuid(),sa.ForeignKey('application_events.id',ondelete='SET NULL')),
        sa.Column('reason',sa.String(500),nullable=False),sa.Column('processed_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('owner_id','gmail_id',name='uq_gmail_owner_message'))
    for column in ['owner_id','application_id','state']:
        op.create_index('ix_gmail_messages_'+column,'gmail_messages',[column])

def downgrade():
    for table in ['gmail_messages','gmail_match_rules','gmail_oauth_states','gmail_connections']:
        op.drop_table(table)
    for col in ['source_timestamp','source_message_id','source']:
        op.drop_column('application_events',col)
    for col in ['status_manual_at','status_changed_at','status_revision']:
        op.drop_column('applications',col)
