from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'add_reminder_log_001'
down_revision = '595ad77efa0e'  # Pointer vers la dernière migration existante
branch_labels = None
depends_on = None


def upgrade():
    """Créer la table reminder_log"""
    op.create_table(
        'reminder_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_identifier', sa.String(length=100), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('reminder_type', sa.String(length=20), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False, default=datetime.utcnow),
        sa.Column('scheduled_for', sa.DateTime(), nullable=False),
        sa.Column('message_content', sa.Text(), nullable=True),
        sa.Column('user_last_active', sa.DateTime(), nullable=True),
        sa.Column('hours_since_active', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, default='sent'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Créer les index
    op.create_index('ix_reminder_log_user_platform', 'reminder_log', ['user_identifier', 'platform'])
    op.create_index('ix_reminder_log_sent_at', 'reminder_log', ['sent_at'], postgresql_ops={'sent_at': 'DESC'})
    op.create_index('ix_reminder_log_status', 'reminder_log', ['status'])
    op.create_index('ix_reminder_log_user_identifier', 'reminder_log', ['user_identifier'])
    op.create_index('ix_reminder_log_platform', 'reminder_log', ['platform'])


def downgrade():
    """Supprimer la table reminder_log"""
    op.drop_index('ix_reminder_log_platform', table_name='reminder_log')
    op.drop_index('ix_reminder_log_user_identifier', table_name='reminder_log')
    op.drop_index('ix_reminder_log_status', table_name='reminder_log')
    op.drop_index('ix_reminder_log_sent_at', table_name='reminder_log')
    op.drop_index('ix_reminder_log_user_platform', table_name='reminder_log')
    op.drop_table('reminder_log')